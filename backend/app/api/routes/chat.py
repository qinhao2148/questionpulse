import hashlib
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

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
from app.models.session import ClassroomSession
from app.schemas.classroom import ChatMessageCreate, ChatMessageReview, PolyvSyncRequest
from app.services.embedding import normalize

logger = logging.getLogger(__name__)

router = APIRouter()

AUTO_PROMOTE_CONFIDENCE = 0.75
REVIEW_CONFIDENCE = 0.45
# POLYV can return a message a little after it happened, so the incremental
# window overlaps the previous sync slightly. Duplicates are cheap: official ids
# deduplicate them.
CHAT_SYNC_OVERLAP = timedelta(minutes=2)
CHAT_SYNC_MAX_PAGES = 5
PENDING_RECOVERY_LIMIT = 20
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
    try:
        await db.commit()
    except IntegrityError:
        # Another worker classified this message first; its result wins.
        await db.rollback()
        return

    if classification_status == "promoted":
        promoted_question_id = None
        async with session_cluster_gate(message.session_id):
            await db.commit()
            current = await db.get(ChatMessage, message.id)
            if current is not None and current.promoted_question_id is None:
                question = await promote_chat_message(db, current)
                await db.commit()
                promoted_question_id = question.id
        if promoted_question_id is not None:
            # We are already in the background classification context, so the
            # RAG retrieval + LLM answer can run here without blocking anyone.
            from app.knowledge.answering import draft_answer_for_question

            try:
                await draft_answer_for_question(db, message.session_id, promoted_question_id)
            except Exception:  # noqa: BLE001 - draft failure is recorded in the row
                await db.rollback()
                logger.exception("rag draft failed for %s", promoted_question_id)


async def classify_messages_in_background(bind, session_id: str, message_ids: list[str]) -> None:
    """Classify accepted chat messages after the HTTP response has been sent.

    DeepSeek needs seconds per message. Running it inside the request made the
    learner's upload (and the teacher's sync of a whole lesson) wait for the
    model, so the request now only stores the message and this worker decides.
    Every message is committed on its own: one bad message never blocks the rest.
    """
    if not message_ids or bind is None:
        return
    # Derive the session from the request's engine instead of a global one: the
    # dependency override used by the tests must apply here too.
    async with async_sessionmaker(bind, expire_on_commit=False)() as db:
        classroom = await db.get(ClassroomSession, session_id)
        if classroom is None:
            return
        title = classroom.title
        for message_id in message_ids:
            try:
                message = await db.get(ChatMessage, message_id)
                if message is None:
                    continue
                await classify_message(db, title, message)
            except Exception:
                await db.rollback()
                logger.exception("chat classification failed for %s", message_id)


async def pending_message_ids(db: Database, session_id: str) -> list[str]:
    """Messages accepted but never classified, e.g. because the process restarted."""
    rows = await db.scalars(
        select(ChatMessage.id)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.classification_status == "pending",
        )
        .order_by(ChatMessage.created_at)
        .limit(PENDING_RECOVERY_LIMIT)
    )
    return list(rows)


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
    background_tasks: BackgroundTasks,
    authorization: Authorization = None,
) -> dict:
    await require_active_session(db, session_id)
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
    # Stored as "pending" and classified once the response is on the wire; the
    # student's browser must not wait for a model call that it never reads.
    background_tasks.add_task(
        classify_messages_in_background, db.bind, session_id, [message.id]
    )
    return {"data": {"id": message.id, "status": message.classification_status}}


@router.post("/sessions/{session_id}/integrations/polyv/chat/sync")
async def sync_polyv_chat_messages(
    session_id: str,
    payload: PolyvSyncRequest,
    db: Database,
    background_tasks: BackgroundTasks,
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
    # Chat keeps its own cursor. The Q&A sync advances last_synced_at, so reusing
    # it here would make each source silently skip records belonging to the other.
    cursor = classroom.chat_synced_at or classroom.created_at
    start_at = cursor - CHAT_SYNC_OVERLAP
    end_at = datetime.now()
    try:
        events = await adapter.fetch_chat_messages(
            channel_id,
            start_at=start_at,
            end_at=end_at,
            max_pages=CHAT_SYNC_MAX_PAGES,
        )
    except PolyvNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="polyv_credentials_not_configured") from exc
    except PolyvApiError as exc:
        classroom.integration_status = "degraded"
        classroom.integration_error = str(exc)[:200]
        classroom.degraded_at = datetime.now()
        await db.commit()
        raise HTTPException(status_code=502, detail="polyv_api_unavailable") from exc

    pending_before = await pending_message_ids(db, session_id)
    accepted = duplicates = skipped = 0
    new_messages: list[ChatMessage] = []
    for event in events:
        # One POLYV channel hosts many live sessions. Once this classroom knows
        # its session id, messages from a sibling classroom must not leak in.
        if (
            classroom.polyv_session_id
            and event.polyv_session_id
            and event.polyv_session_id != classroom.polyv_session_id
        ):
            skipped += 1
            continue
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
            # A first sync binds the classroom only after the loop, so fall back
            # to the event's own session id instead of persisting NULL here.
            polyv_session_id=(
                payload.polyv_session_id
                or event.polyv_session_id
                or classroom.polyv_session_id
            ),
            content=event.content[:500],
            normalized_content=normalize(event.content)[:500],
            occurred_at=occurred_at,
            ingestion_method="server_api",
            official_confirmed=True,
        )
        db.add(message)
        new_messages.append(message)
        accepted += 1
    observed_sessions = {event.polyv_session_id for event in events if event.polyv_session_id}
    if not classroom.polyv_session_id and len(observed_sessions) == 1:
        # First usable sync binds this classroom to its live POLYV session, so
        # later syncs can separate it from a sibling classroom on the same channel.
        classroom.polyv_session_id = observed_sessions.pop()
    classroom.polyv_channel_id = channel_id
    classroom.integration_status = "connected"
    classroom.integration_error = None
    classroom.degraded_at = None
    classroom.last_synced_at = end_at
    classroom.chat_synced_at = end_at
    await db.commit()
    # Classification is the slow part (one model call per message), so a lesson
    # with hundreds of messages must not be classified inside this request.
    queued = [message.id for message in new_messages] + pending_before
    # The worker rebuilds its own session from this engine, so `db.bind` must be
    # forwarded here too. Dropping it raises TypeError inside the background
    # task, which surfaces only in the server log: every synced message then
    # stays "pending" forever and never reaches the teacher panel.
    background_tasks.add_task(
        classify_messages_in_background, db.bind, session_id, queued
    )
    return {
        "data": {
            "fetched": len(events),
            "accepted": accepted,
            "duplicates": duplicates,
            "skipped": skipped,
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
    background_tasks: BackgroundTasks,
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
        from app.knowledge.answering import queue_draft_if_knowledge_bound

        await queue_draft_if_knowledge_bound(background_tasks, db, session_id, question.id)
        return {
            "data": {
                "id": message.id,
                "status": "promoted",
                "question_id": question.id,
            }
        }
