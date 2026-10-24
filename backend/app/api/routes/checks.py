import hashlib
import json
import time

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.ai import DeepSeekAnalyzer, DeepSeekError
from app.api.routes.shared import (
    Authorization,
    Database,
    check_question_view,
    cluster_audience_ids,
    fallback_quiz,
    require_active_session,
    require_session,
    require_student,
    require_teacher,
    resolve_student,
)
from app.core.config import get_settings
from app.models.classroom import (
    AIRun,
    CheckOption,
    CheckQuestion,
    CheckResponse,
    CheckTarget,
    Cluster,
    Participant,
    Question,
)
from app.schemas.classroom import (
    CheckAnswer,
    CheckQuestionView,
)

router = APIRouter()



@router.post(
    "/sessions/{session_id}/clusters/{cluster_id}/checks/generate",
    response_model=CheckQuestionView,
)
async def generate_check_question(
    session_id: str,
    cluster_id: str,
    db: Database,
    authorization: Authorization = None,
) -> CheckQuestionView:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    cluster = await db.get(Cluster, cluster_id)
    if cluster is None or cluster.session_id != session_id:
        raise HTTPException(status_code=404, detail="cluster_not_found")
    if cluster.feedback_round < 1:
        raise HTTPException(status_code=409, detail="feedback_round_not_started")
    existing = await db.scalar(
        select(CheckQuestion).where(
            CheckQuestion.cluster_id == cluster_id,
            CheckQuestion.feedback_round == cluster.feedback_round,
        )
    )
    if existing:
        return await check_question_view(db, existing, reveal_answer=True)

    settings = get_settings()
    questions = list(
        await db.scalars(select(Question.content).where(Question.cluster_id == cluster_id).limit(8))
    )

    # Link the quiz to the classroom knowledge base: contexts come from the
    # frozen snapshot so the check is answerable from the bound documents.
    knowledge_contexts: list[dict] = []
    try:
        from app.knowledge.retrieval import search_classroom_knowledge

        retrieved = await search_classroom_knowledge(
            db, session_id, " ".join([cluster.title, *questions[:2]]), limit=6
        )
        knowledge_contexts = [
            {"source": chunk.document_title, "content": chunk.content}
            for chunk in retrieved[: settings.rag_context_limit]
        ]
    except Exception:  # noqa: BLE001 - knowledge retrieval must not block checks
        knowledge_contexts = []

    draft = fallback_quiz(cluster)
    source = "local_fallback"
    if settings.llm_api_key:
        fingerprint = hashlib.sha256(
            json.dumps([cluster.id, cluster.feedback_round, questions], ensure_ascii=False).encode()
        ).hexdigest()
        run = AIRun(
            session_id=session_id,
            task_type="check_question_generation",
            provider="deepseek",
            model=settings.llm_model,
            status="running",
            input_fingerprint=fingerprint,
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
            draft, usage = await analyzer.generate_quiz(
                classroom.title, cluster.title, questions, knowledge_contexts or None
            )
            source = "deepseek"
            run.status = "succeeded"
            run.prompt_tokens = usage["prompt_tokens"]
            run.completion_tokens = usage["completion_tokens"]
        except DeepSeekError as exc:
            run.status = "failed"
            run.error_code = str(exc)[:100]
        finally:
            run.latency_ms = round((time.perf_counter() - started) * 1000)

    check = CheckQuestion(
        session_id=session_id,
        cluster_id=cluster_id,
        feedback_round=cluster.feedback_round,
        status="draft",
        stem=draft.stem,
        correct_option_key=draft.correct_option_key,
        explanation=draft.explanation,
        source=source,
        knowledge_backed=bool(knowledge_contexts) and source == "deepseek",
    )
    db.add(check)
    await db.flush()
    db.add_all(
        [
            CheckOption(check_question_id=check.id, option_key=item.key, content=item.content)
            for item in draft.options
        ]
    )
    await db.commit()
    return await check_question_view(db, check, reveal_answer=True)


@router.post("/sessions/{session_id}/checks/{check_id}/approve")
async def approve_check_question(
    session_id: str,
    check_id: str,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    check = await db.get(CheckQuestion, check_id)
    if check is None or check.session_id != session_id:
        raise HTTPException(status_code=404, detail="check_question_not_found")
    if check.status == "draft":
        target_ids = await cluster_audience_ids(db, session_id, check.cluster_id)
        db.add_all(
            [CheckTarget(check_question_id=check.id, participant_id=item) for item in target_ids]
        )
        check.status = "active"
        await db.commit()
    return {"data": (await check_question_view(db, check, reveal_answer=True)).model_dump()}


@router.post("/sessions/{session_id}/checks/{check_id}/close")
async def close_check_question(
    session_id: str,
    check_id: str,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    check = await db.get(CheckQuestion, check_id)
    if check is None or check.session_id != session_id:
        raise HTTPException(status_code=404, detail="check_question_not_found")
    if check.status == "active":
        check.status = "closed"
        await db.commit()
    return {"data": (await check_question_view(db, check, reveal_answer=True)).model_dump()}


@router.get("/sessions/{session_id}/checks", response_model=list[CheckQuestionView])
async def list_teacher_checks(
    session_id: str, db: Database, authorization: Authorization = None
) -> list[CheckQuestionView]:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    checks = list(
        await db.scalars(
            select(CheckQuestion)
            .where(CheckQuestion.session_id == session_id)
            .order_by(CheckQuestion.created_at.desc())
        )
    )
    return [await check_question_view(db, item, reveal_answer=True) for item in checks]


@router.get("/sessions/{session_id}/checks/active", response_model=list[CheckQuestionView])
async def list_student_checks(
    session_id: str, db: Database, authorization: Authorization = None
) -> list[CheckQuestionView]:
    await require_session(db, session_id)
    participant = await resolve_student(db, session_id, authorization)
    check_ids = select(CheckTarget.check_question_id).where(
        CheckTarget.participant_id == participant.id
    )
    checks = list(
        await db.scalars(
            select(CheckQuestion).where(
                CheckQuestion.id.in_(check_ids), CheckQuestion.status == "active"
            )
        )
    )
    return [await check_question_view(db, item, participant.id) for item in checks]


@router.put("/sessions/{session_id}/checks/{check_id}/answer")
async def answer_check_question(
    session_id: str,
    check_id: str,
    payload: CheckAnswer,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    await require_active_session(db, session_id)
    participant = await db.get(Participant, payload.participant_id)
    if participant is None or participant.session_id != session_id:
        raise HTTPException(status_code=403, detail="participant_not_in_session")
    await require_student(db, participant, authorization)
    check = await db.get(CheckQuestion, check_id)
    if check is None or check.session_id != session_id:
        raise HTTPException(status_code=404, detail="check_question_not_found")
    if check.status != "active":
        raise HTTPException(status_code=409, detail="check_question_not_active")
    target = await db.get(CheckTarget, (check_id, participant.id))
    if target is None:
        raise HTTPException(status_code=403, detail="participant_not_check_target")
    option = await db.scalar(
        select(CheckOption).where(
            CheckOption.check_question_id == check_id,
            CheckOption.option_key == payload.option_key,
        )
    )
    if option is None:
        raise HTTPException(status_code=422, detail="invalid_check_option")
    response = await db.scalar(
        select(CheckResponse).where(
            CheckResponse.check_question_id == check_id,
            CheckResponse.participant_id == participant.id,
        )
    )
    if response is not None:
        raise HTTPException(status_code=409, detail="check_already_answered")
    is_correct = payload.option_key == check.correct_option_key
    response = CheckResponse(
        check_question_id=check_id,
        participant_id=participant.id,
        selected_option_key=payload.option_key,
        is_correct=is_correct,
    )
    db.add(response)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="check_already_answered") from exc
    return {
        "data": {
            "selected_option_key": response.selected_option_key,
            "is_correct": is_correct,
            "correct_option_key": check.correct_option_key,
            "explanation": check.explanation,
        }
    }
