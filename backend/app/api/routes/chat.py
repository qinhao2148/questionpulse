import hashlib
import re
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.ai import ChatQuestionDecision, DeepSeekAnalyzer, DeepSeekError
from app.api.routes.shared import (
    Authorization,
    Database,
    assign_question,
    external_participant,
    require_active_session,
    require_session,
    require_teacher,
    resolve_student,
)
from app.core.auth import pseudonymize_external_viewer
from app.core.config import get_settings
from app.core.session_gate import session_cluster_gate
from app.integrations.polyv import PolyvApiError, PolyvNotConfiguredError, PolyvQuestionAdapter
from app.models.classroom import (
    AIRun,
    ChatClassification,
    ChatMessage,
    Participant,
    Question,
)
from app.schemas.classroom import ChatMessageCreate, ChatMessageReview, PolyvSyncRequest
from app.services.embedding import normalize

router = APIRouter()

AUTO_PROMOTE_CONFIDENCE = 0.75
REVIEW_CONFIDENCE = 0.45
QUESTION_TYPES = {
    "concept_confusion",
    "procedure_question",
    "error_question",
    "clarification",
    "request_repeat",
}
TRIVIAL_CHAT = {"收到", "好的", "好", "谢谢老师", "明白了", "懂了", "666", "哈哈", "哈哈哈"}


def local_chat_decision(content: str) -> ChatQuestionDecision:
    compact = re.sub(r"\s+", "", content.strip().lower())
    if not compact or compact in TRIVIAL_CHAT or not re.search(r"[\w\u4e00-\u9fff]", compact):
        return ChatQuestionDecision(
            is_question=False,
            confidence=0.95,
            question_type="social",
            normalized_intent="普通课堂聊天",
            reason="消息过短、属于常见回应或不包含有效文本",
        )
    operational = ("声音", "网络", "卡顿", "听不见", "没声音", "画面卡", "延迟")
    if any(item in compact for item in operational):
        return ChatQuestionDecision(
            is_question=False,
            confidence=0.82,
            question_type="classroom_operation",
            normalized_intent="课堂运行问题",
            reason="消息描述设备、声音或网络状况，不属于课程知识疑问",
        )
    cues = (
        "?",
        "？",
        "为什么",
        "怎么",
        "如何",
        "哪里",
        "什么",
        "不懂",
        "没懂",
        "没听懂",
        "再讲",
        "报错",
        "错误",
    )
    is_question = any(item in compact for item in cues)
    return ChatQuestionDecision(
        is_question=is_question,
        confidence=0.78 if is_question else 0.35,
        question_type="clarification" if is_question else "irrelevant",
        normalized_intent=content.strip()[:240],
        suggested_question=content.strip() if is_question else None,
        reason="本地规则检测到疑问表达" if is_question else "未检测到明确的课程疑问表达",
    )


async def promote_chat_message(db: Database, message: ChatMessage) -> Question:
    if message.promoted_question_id:
        existing = await db.get(Question, message.promoted_question_id)
        if existing is not None:
            return existing
    classification = await db.scalar(
        select(ChatClassification).where(ChatClassification.chat_message_id == message.id)
    )
    content = (
        classification.suggested_question
        if classification and classification.suggested_question
        else message.content
    )
    question = Question(
        session_id=message.session_id,
        participant_id=message.participant_id,
        content=content,
        normalized_content=normalize(message.content),
        source="polyv_chat",
        external_id=message.external_id,
        occurred_at=message.occurred_at,
    )
    db.add(question)
    await db.flush()
    await assign_question(db, question)
    message.promoted_question_id = question.id
    message.classification_status = "promoted"
    return question


async def classify_message(db: Database, classroom_title: str, message: ChatMessage) -> None:
    settings = get_settings()
    decision = local_chat_decision(message.content)
    run = None
    if settings.llm_api_key and message.content.strip() not in TRIVIAL_CHAT:
        run = AIRun(
            session_id=message.session_id,
            task_type="chat_question_detection",
            provider="deepseek",
            model=settings.llm_model,
            status="running",
            input_fingerprint=hashlib.sha256(normalize(message.content).encode()).hexdigest(),
        )
        db.add(run)
        await db.flush()
        started = time.perf_counter()
        try:
            analyzer = DeepSeekAnalyzer(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            )
            decision, usage = await analyzer.classify_chat_message(
                classroom_title, message.content
            )
            run.status = "succeeded"
            run.prompt_tokens = usage["prompt_tokens"]
            run.completion_tokens = usage["completion_tokens"]
        except DeepSeekError as exc:
            run.status = "failed"
            run.error_code = str(exc)[:100]
        finally:
            run.latency_ms = round((time.perf_counter() - started) * 1000)

    eligible = decision.is_question and decision.question_type in QUESTION_TYPES
    if eligible and decision.confidence >= AUTO_PROMOTE_CONFIDENCE:
        classification_status = "promoted"
        classification_decision = "auto_promoted"
    elif eligible and decision.confidence >= REVIEW_CONFIDENCE:
        classification_status = "needs_review"
        classification_decision = "needs_review"
    else:
        classification_status = "ignored"
        classification_decision = "ignored"
    message.classification_status = classification_status
    db.add(
        ChatClassification(
            chat_message_id=message.id,
            ai_run_id=run.id if run else None,
            is_question=eligible,
            confidence=decision.confidence,
            question_type=decision.question_type,
            normalized_intent=decision.normalized_intent,
            suggested_question=decision.suggested_question,
            reason=decision.reason,
            decision=classification_decision,
        )
    )
    await db.commit()

    if classification_status == "promoted":
        async with session_cluster_gate(message.session_id):
            await db.commit()
            current = await db.get(ChatMessage, message.id)
            if current is not None and current.promoted_question_id is None:
                await promote_chat_message(db, current)
                await db.commit()


async def participant_for_official_viewer(
    db: Database, session_id: str, viewer_key: str
) -> Participant:
    """Reverse our deterministic watch-page viewer id before creating a shadow identity."""
    settings = get_settings()
    participants = list(
        await db.scalars(select(Participant).where(Participant.session_id == session_id))
    )
    for participant in participants:
        expected = pseudonymize_external_viewer(
            participant.id, settings.participant_pseudonym_key
        )
        if expected == viewer_key:
            return participant
    return await external_participant(db, session_id, viewer_key)


@router.post(
    "/sessions/{session_id}/chat-messages", status_code=status.HTTP_202_ACCEPTED
)
async def ingest_chat_message(
    session_id: str,
    payload: ChatMessageCreate,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    participant = await resolve_student(db, session_id, authorization)
    existing = await db.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.source == "polyv_chat",
            ChatMessage.external_id == payload.external_id,
        )
    )
    if existing is not None:
        return {"data": {"id": existing.id, "status": existing.classification_status}}
    occurred_at = payload.occurred_at
    if occurred_at.tzinfo is not None:
        occurred_at = occurred_at.astimezone(UTC).replace(tzinfo=None)
    message = ChatMessage(
        session_id=session_id,
        participant_id=participant.id,
        external_id=payload.external_id,
        polyv_session_id=payload.polyv_session_id,
        content=payload.content.strip(),
        normalized_content=normalize(payload.content),
        occurred_at=occurred_at,
        ingestion_method="sdk",
    )
    db.add(message)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.source == "polyv_chat",
                ChatMessage.external_id == payload.external_id,
            )
        )
        if existing is None:
            raise
        return {"data": {"id": existing.id, "status": existing.classification_status}}
    await db.refresh(message)
    await classify_message(db, classroom.title, message)
    await db.refresh(message)
    return {"data": {"id": message.id, "status": message.classification_status}}


@router.post("/sessions/{session_id}/integrations/polyv/chat/sync")
async def sync_polyv_chat_messages(
    session_id: str,
    payload: PolyvSyncRequest,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Reconcile missed SDK events against POLYV's signed chat-history API."""
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    settings = get_settings()
    channel_id = payload.channel_id or classroom.polyv_channel_id or settings.polyv_channel_id
    if not channel_id:
        raise HTTPException(status_code=422, detail="polyv_channel_not_configured")
    adapter = PolyvQuestionAdapter(
        settings.polyv_app_id,
        settings.polyv_app_secret,
        timeout=settings.polyv_api_timeout_seconds,
    )
    # The session-level timestamp is also advanced by the separate Q&A sync.
    # Always replay this classroom's bounded window and rely on official IDs for
    # deduplication so one source cannot make the other skip records.
    start_at = classroom.created_at
    try:
        events = await adapter.fetch_chat_messages(
            channel_id,
            start_at=start_at,
            end_at=datetime.now(),
        )
    except PolyvNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="polyv_credentials_not_configured") from exc
    except PolyvApiError as exc:
        classroom.integration_status = "degraded"
        classroom.integration_error = str(exc)[:200]
        classroom.degraded_at = datetime.now()
        await db.commit()
        raise HTTPException(status_code=502, detail="polyv_api_unavailable") from exc

    accepted = duplicates = 0
    new_messages: list[ChatMessage] = []
    for event in events:
        existing = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.source == "polyv_chat",
                ChatMessage.external_id == event.external_id,
            )
        )
        if existing is not None:
            existing.official_confirmed = True
            duplicates += 1
            continue
        participant = await participant_for_official_viewer(
            db, session_id, event.viewer_key
        )
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is not None:
            occurred_at = occurred_at.astimezone(UTC).replace(tzinfo=None)
        message = ChatMessage(
            session_id=session_id,
            participant_id=participant.id,
            external_id=event.external_id,
            polyv_session_id=payload.polyv_session_id or classroom.polyv_session_id,
            content=event.content[:500],
            normalized_content=normalize(event.content)[:500],
            occurred_at=occurred_at,
            ingestion_method="server_api",
            official_confirmed=True,
        )
        db.add(message)
        new_messages.append(message)
        accepted += 1
    classroom.polyv_channel_id = channel_id
    classroom.integration_status = "connected"
    classroom.integration_error = None
    classroom.degraded_at = None
    classroom.last_synced_at = datetime.now()
    await db.commit()
    for message in new_messages:
        await db.refresh(message)
        await classify_message(db, classroom.title, message)
    return {
        "data": {
            "fetched": len(events),
            "accepted": accepted,
            "duplicates": duplicates,
            "integration_status": "connected",
        }
    }


@router.get("/sessions/{session_id}/chat-messages/mine")
async def my_chat_messages(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    await require_session(db, session_id)
    participant = await resolve_student(db, session_id, authorization)
    rows = list(
        await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.participant_id == participant.id,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(30)
        )
    )
    return {
        "data": [
            {
                "external_id": row.external_id,
                "status": row.classification_status,
                "question_id": row.promoted_question_id,
            }
            for row in rows
        ]
    }


@router.get("/sessions/{session_id}/chat-messages/review")
async def review_queue(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    rows = (
        await db.execute(
            select(ChatMessage, ChatClassification)
            .join(ChatClassification, ChatClassification.chat_message_id == ChatMessage.id)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.classification_status == "needs_review",
            )
            .order_by(ChatMessage.occurred_at)
        )
    ).all()
    return {
        "data": [
            {
                "id": message.id,
                "content": message.content,
                "confidence": classification.confidence,
                "normalized_intent": classification.normalized_intent,
                "suggested_question": classification.suggested_question,
                "reason": classification.reason,
                "occurred_at": message.occurred_at,
            }
            for message, classification in rows
        ]
    }


@router.post("/sessions/{session_id}/chat-messages/{message_id}/review")
async def decide_chat_message(
    session_id: str,
    message_id: str,
    payload: ChatMessageReview,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    message = await db.get(ChatMessage, message_id)
    if message is None or message.session_id != session_id:
        raise HTTPException(status_code=404, detail="chat_message_not_found")
    classification = await db.scalar(
        select(ChatClassification).where(ChatClassification.chat_message_id == message.id)
    )
    if classification is None:
        raise HTTPException(status_code=409, detail="chat_message_not_classified")
    if payload.action == "ignore":
        message.classification_status = "ignored"
        classification.decision = "teacher_ignored"
        classification.decided_by = "teacher"
        await db.commit()
        return {"data": {"id": message.id, "status": "ignored"}}
    async with session_cluster_gate(session_id):
        await db.commit()
        message = await db.get(ChatMessage, message_id)
        question = await promote_chat_message(db, message)
        classification = await db.scalar(
            select(ChatClassification).where(ChatClassification.chat_message_id == message.id)
        )
        classification.decision = "teacher_promoted"
        classification.decided_by = "teacher"
        await db.commit()
        return {
            "data": {
                "id": message.id,
                "status": "promoted",
                "question_id": question.id,
            }
        }
