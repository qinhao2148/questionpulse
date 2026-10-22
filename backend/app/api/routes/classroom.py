import hashlib
import json
import math
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import ClusterCandidate, DeepSeekAnalyzer, DeepSeekError, QuizDraft, QuizOptionDraft
from app.core.auth import (
    bearer_token,
    issue_access_token,
    issue_join_code,
    token_digest,
    verify_access_token,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.integrations.polyv import PolyvApiError, PolyvNotConfiguredError, PolyvQuestionAdapter
from app.models.classroom import (
    AIDecision,
    AIRun,
    CheckOption,
    CheckQuestion,
    CheckResponse,
    CheckTarget,
    Cluster,
    ClusterEvent,
    Feedback,
    FeedbackTarget,
    Participant,
    Question,
    Submission,
)
from app.models.session import ClassroomSession
from app.schemas.classroom import (
    CheckAnswer,
    CheckOptionView,
    CheckQuestionView,
    ClusterView,
    ConfusionBreakdown,
    DetachRequest,
    FeedbackSummary,
    FeedbackUpdate,
    IntegrationDrill,
    JoinRequest,
    PolyvEventBatch,
    PolyvSyncRequest,
    QuestionCreate,
    QuestionView,
    ReportAIInsight,
    ReportCluster,
    ReportTimelineEvent,
    SessionCreate,
    SessionReport,
    Snapshot,
    StatusUpdate,
)
from app.services.embedding import MODEL_NAME, cosine, embed, normalize

router = APIRouter()
HIGH_CONFIDENCE = 0.55
Database = Annotated[AsyncSession, Depends(get_db)]
Authorization = Annotated[str | None, Header()]
TRANSITIONS = {
    "open": {"addressing"},
    "addressing": {"awaiting_feedback", "open"},
    "awaiting_feedback": {"closed", "addressing", "open"},
    "closed": {"open"},
}


def question_view(question: Question) -> QuestionView:
    return QuestionView(
        id=question.id,
        participant_id=question.participant_id,
        content=question.content,
        source=question.source,
        external_id=question.external_id,
        occurred_at=question.occurred_at,
        cluster_id=question.cluster_id,
        processing_status=question.processing_status,
        assignment_method=question.assignment_method,
        similarity=question.similarity,
        embedding_model=question.embedding_model,
        created_at=question.created_at,
    )


async def require_session(db: AsyncSession, session_id: str) -> ClassroomSession:
    classroom = await db.get(ClassroomSession, session_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return classroom


async def require_active_session(db: AsyncSession, session_id: str) -> ClassroomSession:
    classroom = await require_session(db, session_id)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    return classroom


def require_teacher(classroom: ClassroomSession, authorization: str | None) -> None:
    verify_access_token(
        classroom.teacher_token_hash, authorization, classroom.teacher_token_expires_at
    )


def require_student(participant: Participant, authorization: str | None) -> None:
    verify_access_token(
        participant.access_token_hash, authorization, participant.access_token_expires_at
    )


async def feedback_summary(
    db: AsyncSession, cluster: Cluster, participant_id: str | None = None
) -> FeedbackSummary:
    current_round = cluster.feedback_round
    if current_round == 0:
        return FeedbackSummary(round=0, targets=0, responses=0, understood=0, still_confused=0)
    targets = await db.scalar(
        select(func.count())
        .select_from(FeedbackTarget)
        .where(
            FeedbackTarget.cluster_id == cluster.id,
            FeedbackTarget.round == current_round,
        )
    )
    feedback_rows = list(
        await db.scalars(
            select(Feedback).where(
                Feedback.cluster_id == cluster.id,
                Feedback.round == current_round,
            )
        )
    )
    counts = Counter(row.result for row in feedback_rows)
    own = next((row.result for row in feedback_rows if row.participant_id == participant_id), None)
    return FeedbackSummary(
        round=current_round,
        targets=targets or 0,
        responses=len(feedback_rows),
        understood=counts["understood"],
        still_confused=counts["still_confused"],
        my_result=own,
    )


def confusion_signal(
    participant_count: int,
    total_participants: int,
    recent_question_count: int,
    feedback: FeedbackSummary,
    created_at: datetime,
    check_responses: int = 0,
    check_correct: int = 0,
) -> tuple[float, str, ConfusionBreakdown]:
    age_minutes = max((datetime.now() - created_at).total_seconds() / 60, 0)
    participant_ratio = participant_count / total_participants if total_participants else 0
    recent_activity = min(recent_question_count / 5, 1)
    wait_pressure = min(age_minutes / 15, 1)
    still_confused_ratio = (
        feedback.still_confused / feedback.responses if feedback.responses else 0
    )
    check_error_ratio = (
        (check_responses - check_correct) / check_responses if check_responses else 0
    )
    participant_factor = participant_ratio * 0.25
    activity_factor = recent_activity * 0.15
    wait_factor = min(age_minutes / 15, 1) * 0.2
    feedback_factor = still_confused_ratio * 0.2
    check_factor = check_error_ratio * 0.2
    score = round(
        (participant_factor + activity_factor + wait_factor + feedback_factor + check_factor)
        * 100,
        1,
    )
    level = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return (
        score,
        level,
        ConfusionBreakdown(
            participant_ratio=round(participant_ratio, 4),
            recent_activity=round(recent_activity, 4),
            wait_pressure=round(wait_pressure, 4),
            still_confused_ratio=round(still_confused_ratio, 4),
            check_error_ratio=round(check_error_ratio, 4),
        ),
    )


async def assign_locally(
    db: AsyncSession,
    question: Question,
    vector: list[float],
    prefix: str = "",
) -> None:
    clusters = list(
        await db.scalars(select(Cluster).where(Cluster.session_id == question.session_id))
    )
    scored = [(cluster, cosine(vector, json.loads(cluster.embedding_json))) for cluster in clusters]
    best_cluster, best_score = max(scored, key=lambda item: item[1]) if scored else (None, 0.0)
    if best_cluster is not None and best_score >= HIGH_CONFIDENCE:
        cluster = best_cluster
        method = f"{prefix}semantic_high_confidence"
    else:
        cluster = Cluster(
            session_id=question.session_id,
            title=question.content,
            embedding_json=json.dumps(vector),
            embedding_model=MODEL_NAME,
        )
        db.add(cluster)
        await db.flush()
        method = f"{prefix}new_cluster_low_confidence"
    question.cluster_id = cluster.id
    question.processing_status = "clustered"
    question.assignment_method = method
    question.similarity = round(best_score, 6)


async def deepseek_candidates(
    db: AsyncSession, session_id: str, clusters: list[Cluster]
) -> list[ClusterCandidate]:
    candidates = []
    for cluster in clusters:
        examples = list(
            await db.scalars(
                select(Question.content).where(Question.cluster_id == cluster.id).limit(5)
            )
        )
        candidates.append(
            ClusterCandidate(
                id=cluster.id,
                title=cluster.title,
                representative_questions=examples,
            )
        )
    return candidates


async def assign_with_deepseek(
    db: AsyncSession, question: Question, vector: list[float]
) -> None:
    settings = get_settings()
    classroom = await db.get(ClassroomSession, question.session_id)
    clusters = list(
        await db.scalars(select(Cluster).where(Cluster.session_id == question.session_id))
    )
    candidates = await deepseek_candidates(db, question.session_id, clusters)
    fingerprint_source = json.dumps(
        {
            "question": normalize(question.content),
            "clusters": [(candidate.id, candidate.title) for candidate in candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    run = AIRun(
        session_id=question.session_id,
        task_type="question_clustering",
        provider="deepseek",
        model=settings.llm_model,
        status="running",
        input_fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
    )
    db.add(run)
    await db.flush()
    started = time.perf_counter()
    analyzer = DeepSeekAnalyzer(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    try:
        decision, usage = await analyzer.classify(
            classroom.title if classroom else "课堂",
            question.content,
            candidates,
        )
        cluster = next((item for item in clusters if item.id == decision.cluster_id), None)
        if decision.decision == "join_existing" and cluster is None:
            raise DeepSeekError("unknown_cluster_id")
        if decision.decision == "create_new" or decision.confidence < 0.6:
            cluster = Cluster(
                session_id=question.session_id,
                title=decision.suggested_title,
                embedding_json=json.dumps(vector),
                embedding_model=MODEL_NAME,
            )
            db.add(cluster)
            await db.flush()
            action = "create_new"
        else:
            action = "join_existing"
        question.cluster_id = cluster.id
        question.processing_status = "clustered"
        question.assignment_method = f"deepseek_{action}"
        question.similarity = round(decision.confidence, 6)
        run.status = "succeeded"
        run.prompt_tokens = usage["prompt_tokens"]
        run.completion_tokens = usage["completion_tokens"]
        db.add(
            AIDecision(
                ai_run_id=run.id,
                question_id=question.id,
                cluster_id=cluster.id,
                action=action,
                confidence=decision.confidence,
                reason=decision.reason,
                normalized_intent=decision.normalized_intent,
            )
        )
    except DeepSeekError as exc:
        run.status = "failed"
        run.error_code = str(exc)[:100]
        await assign_locally(db, question, vector, prefix="deepseek_fallback_")
    finally:
        run.latency_ms = round((time.perf_counter() - started) * 1000)


async def assign_question(db: AsyncSession, question: Question) -> None:
    try:
        vector = embed(question.content)
        question.embedding_json = json.dumps(vector)
        question.embedding_model = MODEL_NAME
        settings = get_settings()
        if settings.llm_api_key:
            await assign_with_deepseek(db, question, vector)
        else:
            await assign_locally(db, question, vector)
        question.error_code = None
    except Exception as exc:
        question.processing_status = "pending"
        question.error_code = type(exc).__name__


def mean_unit_vector(vectors: list[list[float]]) -> list[float]:
    average = [sum(values) / len(vectors) for values in zip(*vectors, strict=True)]
    magnitude = math.sqrt(sum(value * value for value in average))
    return [value / magnitude for value in average]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, db: Database) -> dict:
    settings = get_settings()
    teacher_token = issue_access_token("qpt")
    classroom = ClassroomSession(
        title=payload.title,
        status="live",
        teacher_token_hash=token_digest(teacher_token),
        teacher_token_expires_at=datetime.now(UTC)
        + timedelta(hours=settings.access_token_ttl_hours),
        join_code=issue_join_code(),
        polyv_channel_id=settings.polyv_channel_id or None,
        polyv_session_id=settings.polyv_session_id or None,
    )
    db.add(classroom)
    await db.commit()
    await db.refresh(classroom)
    return {
        "data": {
            "id": classroom.id,
            "title": classroom.title,
            "status": classroom.status,
            "teacher_token": teacher_token,
            "join_code": classroom.join_code,
        }
    }


@router.post("/sessions/{session_id}/join")
async def join_session(session_id: str, payload: JoinRequest, db: Database) -> dict:
    classroom = await require_session(db, session_id)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    if classroom.join_code is not None and payload.join_code != classroom.join_code:
        raise HTTPException(status_code=403, detail="invalid_join_code")
    existing = await db.scalar(
        select(Participant).where(
            Participant.session_id == session_id,
            Participant.viewer_key == payload.viewer_key,
        )
    )
    participant = existing or Participant(
        session_id=session_id,
        viewer_key=payload.viewer_key,
        display_name=payload.display_name,
    )
    student_token = issue_access_token("qps")
    participant.access_token_hash = token_digest(student_token)
    participant.access_token_expires_at = datetime.now(UTC) + timedelta(
        hours=get_settings().access_token_ttl_hours
    )
    if existing is None:
        db.add(participant)
    await db.commit()
    await db.refresh(participant)
    return {
        "data": {
            "participant_id": participant.id,
            "display_name": participant.display_name,
            "access_token": student_token,
        }
    }


@router.post("/sessions/{session_id}/questions", status_code=status.HTTP_202_ACCEPTED)
async def submit_question(
    session_id: str, payload: QuestionCreate, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    participant = await db.get(Participant, payload.participant_id)
    if participant is None or participant.session_id != session_id:
        raise HTTPException(status_code=403, detail="participant_not_in_session")
    require_student(participant, authorization)

    existing = await db.scalar(
        select(Submission).where(
            Submission.session_id == session_id,
            Submission.participant_id == payload.participant_id,
            Submission.client_request_id == payload.client_request_id,
        )
    )
    if existing:
        question = await db.get(Question, existing.question_id)
        return {"data": question_view(question).model_dump(mode="json"), "idempotent": True}

    question = Question(
        session_id=session_id,
        participant_id=payload.participant_id,
        content=payload.content.strip(),
        normalized_content=normalize(payload.content),
    )
    db.add(question)
    await db.flush()
    await assign_question(db, question)

    db.add(
        Submission(
            session_id=session_id,
            participant_id=payload.participant_id,
            client_request_id=payload.client_request_id,
            question_id=question.id,
        )
    )
    await db.commit()
    await db.refresh(question)
    return {"data": question_view(question).model_dump(mode="json"), "idempotent": False}


async def build_snapshot(
    db: AsyncSession,
    classroom: ClassroomSession,
    participant_id: str | None = None,
    include_teacher_insights: bool = False,
) -> Snapshot:
    session_id = classroom.id
    clusters = list(await db.scalars(select(Cluster).where(Cluster.session_id == session_id)))
    questions = list(
        await db.scalars(
            select(Question).where(Question.session_id == session_id).order_by(Question.created_at)
        )
    )
    total_participants = (
        await db.scalar(
            select(func.count())
            .select_from(Participant)
            .where(Participant.session_id == session_id)
        )
        or 0
    )
    one_minute_ago = datetime.now() - timedelta(minutes=1)
    insight_by_cluster = {}
    if include_teacher_insights:
        rows = (
            await db.execute(
                select(AIDecision, AIRun)
                .join(AIRun, AIDecision.ai_run_id == AIRun.id)
                .where(
                    AIRun.session_id == session_id,
                    AIRun.provider == "deepseek",
                    AIRun.status == "succeeded",
                    AIDecision.cluster_id.is_not(None),
                )
                .order_by(AIDecision.created_at.desc())
            )
        ).all()
        for decision, run in rows:
            insight_by_cluster.setdefault(decision.cluster_id, (decision, run))
    cluster_views = []
    for cluster in clusters:
        members = [question for question in questions if question.cluster_id == cluster.id]
        summary = await feedback_summary(db, cluster, participant_id)
        participant_count = len({question.participant_id for question in members})
        check_ids = list(
            await db.scalars(
                select(CheckQuestion.id).where(CheckQuestion.cluster_id == cluster.id)
            )
        )
        check_rows = (
            list(
                await db.scalars(
                    select(CheckResponse).where(CheckResponse.check_question_id.in_(check_ids))
                )
            )
            if check_ids
            else []
        )
        confusion_score, confusion_level, confusion_breakdown = confusion_signal(
            participant_count,
            total_participants,
            sum(question.created_at >= one_minute_ago for question in members),
            summary,
            cluster.created_at,
            len(check_rows),
            sum(item.is_correct for item in check_rows),
        )
        insight = insight_by_cluster.get(cluster.id)
        cluster_views.append(
            ClusterView(
                id=cluster.id,
                title=cluster.title,
                status=cluster.status,
                version=cluster.version,
                feedback_round=cluster.feedback_round,
                feedback=summary,
                participant_count=participant_count,
                question_count=len(members),
                confusion_score=confusion_score,
                confusion_level=confusion_level,
                confusion_breakdown=confusion_breakdown,
                ai_normalized_intent=insight[0].normalized_intent if insight else None,
                ai_semantic_reason=insight[0].reason if insight else None,
                ai_model=insight[1].model if insight else None,
                questions=[
                    question_view(question)
                    for question in members
                    if participant_id is None or question.participant_id == participant_id
                ],
            )
        )
    cluster_views.sort(key=lambda item: (-item.participant_count, -item.question_count))
    return Snapshot(
        id=classroom.id,
        title=classroom.title,
        status=classroom.status,
        mode=classroom.mode,
        integration_status=classroom.integration_status,
        polyv_channel_id=classroom.polyv_channel_id,
        polyv_session_id=classroom.polyv_session_id,
        last_synced_at=classroom.last_synced_at,
        integration_error=classroom.integration_error,
        degraded_at=classroom.degraded_at,
        clusters=cluster_views,
        pending_questions=[
            question_view(question)
            for question in questions
            if not question.cluster_id
            and (participant_id is None or question.participant_id == participant_id)
        ],
    )


async def resolve_student(
    db: AsyncSession, session_id: str, authorization: str | None
) -> Participant:
    token = bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=403, detail="access_denied")
    participant = await db.scalar(
        select(Participant).where(
            Participant.session_id == session_id,
            Participant.access_token_hash == token_digest(token),
        )
    )
    if participant is None:
        raise HTTPException(status_code=403, detail="access_denied")
    verify_access_token(
        participant.access_token_hash,
        authorization,
        participant.access_token_expires_at,
    )
    return participant


@router.get(
    "/sessions/{session_id}/student-snapshot",
    response_model=Snapshot,
    response_model_exclude_none=True,
)
async def get_student_snapshot(
    session_id: str, db: Database, authorization: Authorization = None
) -> Snapshot:
    classroom = await require_session(db, session_id)
    participant = await resolve_student(db, session_id, authorization)
    return await build_snapshot(db, classroom, participant.id)


@router.get("/sessions/{session_id}/teacher-snapshot", response_model=Snapshot)
async def get_teacher_snapshot(
    session_id: str, db: Database, authorization: Authorization = None
) -> Snapshot:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    return await build_snapshot(db, classroom, include_teacher_insights=True)


@router.get("/sessions/{session_id}/snapshot", response_model=Snapshot, deprecated=True)
async def get_snapshot(
    session_id: str,
    db: Database,
    participant_id: str | None = Query(default=None),
    authorization: Authorization = None,
) -> Snapshot:
    """Compatibility endpoint for pre-migration demo links."""
    classroom = await require_session(db, session_id)
    if participant_id is None:
        require_teacher(classroom, authorization)
    else:
        participant = await db.get(Participant, participant_id)
        if participant is None or participant.session_id != session_id:
            raise HTTPException(status_code=403, detail="participant_not_in_session")
        require_student(participant, authorization)
    return await build_snapshot(
        db, classroom, participant_id, include_teacher_insights=participant_id is None
    )


@router.post("/sessions/{session_id}/integrations/polyv/events")
async def import_polyv_contract_events(
    session_id: str,
    payload: PolyvEventBatch,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Validate the POLYV mapping with local contract fixtures; performs no POLYV call."""
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    accepted = 0
    duplicates = 0
    pending = 0
    question_ids = []
    for event in payload.events:
        existing = await db.scalar(
            select(Question).where(
                Question.session_id == session_id,
                Question.source == event.source,
                Question.external_id == event.external_id,
            )
        )
        if existing is not None:
            duplicates += 1
            question_ids.append(existing.id)
            continue
        participant = await db.scalar(
            select(Participant).where(
                Participant.session_id == session_id,
                Participant.viewer_key == event.viewer_key,
            )
        )
        if participant is None:
            participant = Participant(session_id=session_id, viewer_key=event.viewer_key)
            db.add(participant)
            await db.flush()
        question = Question(
            session_id=session_id,
            participant_id=participant.id,
            content=event.content.strip(),
            normalized_content=normalize(event.content),
            source=event.source,
            external_id=event.external_id,
            occurred_at=event.occurred_at.replace(tzinfo=None),
        )
        db.add(question)
        await db.flush()
        await assign_question(db, question)
        accepted += 1
        pending += question.processing_status == "pending"
        question_ids.append(question.id)
    classroom.polyv_channel_id = payload.channel_id
    classroom.polyv_session_id = payload.polyv_session_id
    classroom.integration_status = "contract_verified"
    classroom.integration_error = None
    classroom.degraded_at = None
    classroom.last_synced_at = datetime.now()
    await db.commit()
    return {
        "data": {
            "environment": payload.environment,
            "accepted": accepted,
            "duplicates": duplicates,
            "pending": pending,
            "question_ids": question_ids,
            "integration_status": classroom.integration_status,
        }
    }


@router.post("/sessions/{session_id}/integrations/polyv/sync")
async def sync_polyv_questions(
    session_id: str,
    payload: PolyvSyncRequest,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Fetch the configured channel's real POLYV QA records and import them idempotently."""
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    settings = get_settings()
    channel_id = payload.channel_id or classroom.polyv_channel_id or settings.polyv_channel_id
    if not channel_id:
        raise HTTPException(status_code=422, detail="polyv_channel_not_configured")
    adapter = PolyvQuestionAdapter(
        settings.polyv_app_id,
        settings.polyv_app_secret,
        timeout=settings.polyv_api_timeout_seconds,
    )
    try:
        events = await adapter.fetch_questions(channel_id)
    except PolyvNotConfiguredError as exc:
        classroom.integration_status = "not_configured"
        classroom.integration_error = "polyv_credentials_not_configured"
        await db.commit()
        raise HTTPException(status_code=503, detail="polyv_credentials_not_configured") from exc
    except PolyvApiError as exc:
        classroom.integration_status = "degraded"
        classroom.integration_error = str(exc)[:200]
        classroom.degraded_at = datetime.now()
        await db.commit()
        raise HTTPException(status_code=502, detail="polyv_api_unavailable") from exc

    accepted = duplicates = pending = 0
    for event in events:
        existing = await db.scalar(
            select(Question).where(
                Question.session_id == session_id,
                Question.source == event.source,
                Question.external_id == event.external_id,
            )
        )
        if existing is not None:
            duplicates += 1
            continue
        participant = await db.scalar(
            select(Participant).where(
                Participant.session_id == session_id, Participant.viewer_key == event.viewer_key
            )
        )
        if participant is None:
            participant = Participant(session_id=session_id, viewer_key=event.viewer_key)
            db.add(participant)
            await db.flush()
        question = Question(
            session_id=session_id,
            participant_id=participant.id,
            content=event.content,
            normalized_content=normalize(event.content),
            source=event.source,
            external_id=event.external_id,
            occurred_at=event.occurred_at.replace(tzinfo=None),
        )
        db.add(question)
        await db.flush()
        await assign_question(db, question)
        accepted += 1
        pending += question.processing_status == "pending"
    classroom.polyv_channel_id = channel_id
    classroom.polyv_session_id = (
        payload.polyv_session_id or classroom.polyv_session_id or settings.polyv_session_id or None
    )
    classroom.mode = "live"
    classroom.integration_status = "connected"
    classroom.integration_error = None
    classroom.degraded_at = None
    classroom.last_synced_at = datetime.now()
    await db.commit()
    return {
        "data": {
            "accepted": accepted,
            "duplicates": duplicates,
            "pending": pending,
            "fetched": len(events),
            "channel_id": channel_id,
            "polyv_session_id": classroom.polyv_session_id,
            "integration_status": "connected",
        }
    }


@router.post("/sessions/{session_id}/integrations/polyv/drill")
async def run_integration_drill(
    session_id: str,
    payload: IntegrationDrill,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    """Exercise degraded/recovered UI states locally without contacting POLYV."""
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    if payload.action == "degrade":
        classroom.integration_status = "degraded"
        classroom.integration_error = payload.reason or "contract_test_transport_unavailable"
        classroom.degraded_at = datetime.now()
    else:
        classroom.integration_status = (
            "contract_verified" if classroom.polyv_session_id else "not_configured"
        )
        classroom.integration_error = None
        classroom.degraded_at = None
        classroom.last_synced_at = datetime.now()
    await db.commit()
    return {
        "data": {
            "environment": payload.environment,
            "integration_status": classroom.integration_status,
            "integration_error": classroom.integration_error,
        }
    }


@router.post("/sessions/{session_id}/questions/{question_id}/retry")
async def retry_question(
    session_id: str,
    question_id: str,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    question = await db.get(Question, question_id)
    if question is None or question.session_id != session_id:
        raise HTTPException(status_code=404, detail="question_not_found")
    if question.processing_status != "pending":
        raise HTTPException(status_code=409, detail="question_not_pending")
    await assign_question(db, question)
    await db.commit()
    await db.refresh(question)
    return {"data": question_view(question).model_dump(mode="json")}


@router.post("/sessions/{session_id}/questions/retry-pending")
async def retry_pending_questions(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    pending_questions = list(
        await db.scalars(
            select(Question).where(
                Question.session_id == session_id,
                Question.processing_status == "pending",
            )
        )
    )
    recovered = 0
    for question in pending_questions:
        await assign_question(db, question)
        recovered += question.processing_status == "clustered"
    await db.commit()
    return {
        "data": {
            "attempted": len(pending_questions),
            "recovered": recovered,
            "remaining": len(pending_questions) - recovered,
        }
    }


@router.post("/sessions/{session_id}/end")
async def end_session(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    if classroom.status != "ended":
        classroom.status = "ended"
        # MySQL DATETIME does not retain timezone information; store the server-local
        # wall clock so browsers do not interpret a naive UTC value as local time.
        classroom.ended_at = datetime.now()
        await db.execute(
            update(CheckQuestion)
            .where(CheckQuestion.session_id == session_id, CheckQuestion.status == "active")
            .values(status="closed")
        )
        await db.commit()
        await db.refresh(classroom)
    return {
        "data": {
            "id": classroom.id,
            "status": classroom.status,
            "ended_at": classroom.ended_at,
        }
    }


@router.patch("/sessions/{session_id}/clusters/{cluster_id}/status")
async def update_cluster_status(
    session_id: str,
    cluster_id: str,
    payload: StatusUpdate,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    cluster = await db.get(Cluster, cluster_id)
    if cluster is None or cluster.session_id != session_id:
        raise HTTPException(status_code=404, detail="cluster_not_found")
    if payload.status not in TRANSITIONS.get(cluster.status, set()):
        raise HTTPException(status_code=422, detail="invalid_status_transition")

    previous_status = cluster.status
    next_round = cluster.feedback_round + (payload.status == "awaiting_feedback")
    closed_at = datetime.now(UTC).replace(tzinfo=None) if payload.status == "closed" else None
    result = await db.execute(
        update(Cluster)
        .where(Cluster.id == cluster_id, Cluster.version == payload.expected_version)
        .values(
            status=payload.status,
            version=Cluster.version + 1,
            feedback_round=next_round,
            closed_at=closed_at,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="cluster_version_conflict")

    if payload.status == "awaiting_feedback":
        participant_ids = list(
            await db.scalars(
                select(Question.participant_id).where(Question.cluster_id == cluster_id).distinct()
            )
        )
        db.add_all(
            [
                FeedbackTarget(
                    cluster_id=cluster_id,
                    round=next_round,
                    participant_id=participant_id,
                )
                for participant_id in participant_ids
            ]
        )
    elif payload.status == "closed":
        await db.execute(
            update(CheckQuestion)
            .where(CheckQuestion.cluster_id == cluster_id, CheckQuestion.status == "active")
            .values(status="closed")
        )
    db.add(
        ClusterEvent(
            session_id=session_id,
            cluster_id=cluster_id,
            event_type="status_changed",
            payload_json=json.dumps(
                {"from": previous_status, "to": payload.status, "round": next_round}
            ),
        )
    )
    await db.commit()
    updated = await db.get(Cluster, cluster_id)
    return {
        "data": {
            "id": updated.id,
            "status": updated.status,
            "version": updated.version,
            "feedback_round": updated.feedback_round,
        }
    }


@router.put("/sessions/{session_id}/clusters/{cluster_id}/feedback")
async def put_feedback(
    session_id: str,
    cluster_id: str,
    payload: FeedbackUpdate,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    await require_active_session(db, session_id)
    participant = await db.get(Participant, payload.participant_id)
    if participant is None or participant.session_id != session_id:
        raise HTTPException(status_code=403, detail="participant_not_in_session")
    require_student(participant, authorization)
    cluster = await db.get(Cluster, cluster_id)
    if cluster is None or cluster.session_id != session_id:
        raise HTTPException(status_code=404, detail="cluster_not_found")
    if cluster.status != "awaiting_feedback" or payload.round != cluster.feedback_round:
        raise HTTPException(status_code=409, detail="feedback_round_not_open")
    target = await db.get(FeedbackTarget, (cluster_id, payload.round, payload.participant_id))
    if target is None:
        raise HTTPException(status_code=403, detail="participant_not_feedback_target")
    existing = await db.scalar(
        select(Feedback).where(
            Feedback.cluster_id == cluster_id,
            Feedback.round == payload.round,
            Feedback.participant_id == payload.participant_id,
        )
    )
    if existing:
        existing.result = payload.result
        feedback = existing
    else:
        feedback = Feedback(
            cluster_id=cluster_id,
            round=payload.round,
            participant_id=payload.participant_id,
            result=payload.result,
        )
        db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return {
        "data": {
            "cluster_id": cluster_id,
            "round": payload.round,
            "result": feedback.result,
        }
    }


@router.get("/sessions/{session_id}/report", response_model=SessionReport)
async def get_report(
    session_id: str, db: Database, authorization: Authorization = None
) -> SessionReport:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    clusters = list(await db.scalars(select(Cluster).where(Cluster.session_id == session_id)))
    questions = list(await db.scalars(select(Question).where(Question.session_id == session_id)))
    report_clusters = []
    for cluster in clusters:
        members = [question for question in questions if question.cluster_id == cluster.id]
        report_clusters.append(
            ReportCluster(
                id=cluster.id,
                title=cluster.title,
                status=cluster.status,
                participant_count=len({question.participant_id for question in members}),
                question_count=len(members),
                feedback=await feedback_summary(db, cluster),
                questions=[question_view(question) for question in members],
            )
        )
    report_clusters.sort(key=lambda item: (-item.participant_count, -item.question_count))
    summaries = [item.feedback for item in report_clusters]
    targets = sum(item.targets for item in summaries)
    responses = sum(item.responses for item in summaries)
    checks = list(
        await db.scalars(select(CheckQuestion).where(CheckQuestion.session_id == session_id))
    )
    check_ids = [item.id for item in checks]
    check_targets = 0
    check_responses = []
    if check_ids:
        check_targets = (
            await db.scalar(
                select(func.count())
                .select_from(CheckTarget)
                .where(CheckTarget.check_question_id.in_(check_ids))
            )
            or 0
        )
        check_responses = list(
            await db.scalars(
                select(CheckResponse).where(CheckResponse.check_question_id.in_(check_ids))
            )
        )
    check_correct = sum(item.is_correct for item in check_responses)
    cluster_titles = {item.id: item.title for item in clusters}
    timeline = [
        ReportTimelineEvent(
            kind="question_received",
            cluster_id=question.cluster_id,
            cluster_title=cluster_titles.get(question.cluster_id),
            detail=f"收到问题：{question.content}",
            occurred_at=question.occurred_at or question.created_at,
        )
        for question in questions
    ]
    events = list(
        await db.scalars(
            select(ClusterEvent)
            .where(ClusterEvent.session_id == session_id)
            .order_by(ClusterEvent.created_at)
        )
    )
    status_labels = {
        "open": "重新打开疑问",
        "addressing": "教师开始讲解",
        "awaiting_feedback": "讲解结束并收集反馈",
        "closed": "疑问处理完成",
    }
    for event in events:
        payload = json.loads(event.payload_json or "{}")
        if event.event_type == "status_changed":
            detail = status_labels.get(payload.get("to"), "疑问状态发生变化")
        elif event.event_type == "question_detached":
            detail = "教师将问题拆分为独立疑问"
        else:
            detail = event.event_type
        timeline.append(
            ReportTimelineEvent(
                kind=event.event_type,
                cluster_id=event.cluster_id,
                cluster_title=cluster_titles.get(event.cluster_id),
                detail=detail,
                occurred_at=event.created_at,
            )
        )
    timeline.extend(
        ReportTimelineEvent(
            kind="check_created",
            cluster_id=check.cluster_id,
            cluster_title=cluster_titles.get(check.cluster_id),
            detail=f"生成理解检测（{check.source}）",
            occurred_at=check.created_at,
        )
        for check in checks
    )
    timeline.sort(
        key=lambda item: item.occurred_at.replace(tzinfo=None)
        if item.occurred_at.tzinfo
        else item.occurred_at
    )
    decision_rows = list(
        (
            await db.execute(
                select(AIDecision, AIRun)
                .join(AIRun, AIDecision.ai_run_id == AIRun.id)
                .where(
                    AIRun.session_id == session_id,
                    AIRun.provider == "deepseek",
                    AIRun.status == "succeeded",
                    AIDecision.cluster_id.is_not(None),
                )
                .order_by(AIDecision.created_at.desc())
            )
        ).all()
    )
    report_by_cluster = {item.id: item for item in report_clusters}
    ai_insights = []
    seen_insight_clusters = set()
    for decision, run in decision_rows:
        if decision.cluster_id in seen_insight_clusters:
            continue
        cluster_report = report_by_cluster.get(decision.cluster_id)
        if cluster_report is None:
            continue
        if cluster_report.feedback.still_confused > 0:
            recommendation = "结合学生仍困惑反馈重新讲解，并用具体反例后再次检测。"
        elif cluster_report.status != "closed":
            recommendation = "完成本轮讲解与理解反馈，再依据检测结果决定是否关闭。"
        else:
            recommendation = "该疑问已完成闭环，可在下节课开头用一道迁移题快速复核。"
        ai_insights.append(
            ReportAIInsight(
                cluster_id=cluster_report.id,
                cluster_title=cluster_report.title,
                normalized_intent=decision.normalized_intent,
                semantic_reason=decision.reason,
                recommendation=recommendation,
                model=run.model,
            )
        )
        seen_insight_clusters.add(decision.cluster_id)
    return SessionReport(
        id=classroom.id,
        title=classroom.title,
        status=classroom.status,
        ended_at=classroom.ended_at,
        generated_at=datetime.now(UTC),
        question_count=len(questions),
        participant_count=len({question.participant_id for question in questions}),
        cluster_count=len(clusters),
        status_counts=dict(Counter(cluster.status for cluster in clusters)),
        feedback_targets=targets,
        feedback_responses=responses,
        feedback_coverage=round(responses / targets, 4) if targets else 0.0,
        understood=sum(item.understood for item in summaries),
        still_confused=sum(item.still_confused for item in summaries),
        check_targets=check_targets,
        check_responses=len(check_responses),
        check_correct=check_correct,
        check_accuracy=(round(check_correct / len(check_responses), 4) if check_responses else 0.0),
        clusters=report_clusters,
        follow_ups=[item for item in report_clusters if item.feedback.still_confused > 0],
        timeline=timeline,
        ai_insights=ai_insights,
    )


@router.post("/sessions/{session_id}/questions/{question_id}/detach")
async def detach_question(
    session_id: str,
    question_id: str,
    payload: DetachRequest,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    question = await db.get(Question, question_id)
    if question is None or question.session_id != session_id:
        raise HTTPException(status_code=404, detail="question_not_found")
    old_cluster_id = question.cluster_id
    if old_cluster_id is None:
        raise HTTPException(status_code=409, detail="question_has_no_cluster")
    old_members = list(
        await db.scalars(select(Question).where(Question.cluster_id == old_cluster_id))
    )
    if len(old_members) <= 1:
        raise HTTPException(status_code=422, detail="cannot_detach_only_question")
    vector = json.loads(question.embedding_json or "[]")
    if not vector:
        raise HTTPException(status_code=409, detail="question_has_no_embedding")
    new_cluster = Cluster(
        session_id=session_id,
        title=payload.title or question.content,
        embedding_json=json.dumps(vector),
        embedding_model=question.embedding_model or MODEL_NAME,
    )
    db.add(new_cluster)
    await db.flush()
    question.cluster_id = new_cluster.id
    question.assignment_method = "teacher_detach"
    question.similarity = 1.0
    remaining_vectors = [
        json.loads(member.embedding_json)
        for member in old_members
        if member.id != question.id and member.embedding_json
    ]
    old_cluster = await db.get(Cluster, old_cluster_id)
    if old_cluster is not None and remaining_vectors:
        old_cluster.embedding_json = json.dumps(mean_unit_vector(remaining_vectors))
        old_cluster.version += 1
    db.add(
        ClusterEvent(
            session_id=session_id,
            cluster_id=new_cluster.id,
            question_id=question.id,
            event_type="question_detached",
            payload_json=json.dumps({"from_cluster_id": old_cluster_id}),
        )
    )
    await db.commit()
    return {"data": {"question_id": question.id, "cluster_id": new_cluster.id}}


async def check_question_view(
    db: AsyncSession,
    check: CheckQuestion,
    participant_id: str | None = None,
    reveal_answer: bool = False,
) -> CheckQuestionView:
    options = list(
        await db.scalars(
            select(CheckOption)
            .where(CheckOption.check_question_id == check.id)
            .order_by(CheckOption.option_key)
        )
    )
    target_count = await db.scalar(
        select(func.count())
        .select_from(CheckTarget)
        .where(CheckTarget.check_question_id == check.id)
    )
    responses = list(
        await db.scalars(
            select(CheckResponse).where(CheckResponse.check_question_id == check.id)
        )
    )
    own = next((item for item in responses if item.participant_id == participant_id), None)
    return CheckQuestionView(
        id=check.id,
        cluster_id=check.cluster_id,
        feedback_round=check.feedback_round,
        status=check.status,
        stem=check.stem,
        options=[CheckOptionView(key=item.option_key, content=item.content) for item in options],
        source=check.source,
        explanation=check.explanation if reveal_answer or own else None,
        correct_option_key=check.correct_option_key if reveal_answer or own else None,
        target_count=target_count or 0,
        response_count=len(responses),
        correct_count=sum(item.is_correct for item in responses),
        my_option_key=own.selected_option_key if own else None,
        my_is_correct=own.is_correct if own else None,
    )


def fallback_quiz(cluster: Cluster) -> QuizDraft:
    return QuizDraft(
        stem=f"关于“{cluster.title}”，下列哪项最能证明你理解了本轮讲解？",
        options=[
            QuizOptionDraft(key="A", content="能说明核心条件、执行过程和最终结果"),
            QuizOptionDraft(key="B", content="只记住示例中的变量名称"),
            QuizOptionDraft(key="C", content="忽略问题成立所需的前提条件"),
            QuizOptionDraft(key="D", content="认为所有相似场景的结果都完全相同"),
        ],
        correct_option_key="A",
        explanation="理解应当能够解释条件、过程和结果，而不只是记住示例表面形式。",
    )


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
            draft, usage = await analyzer.generate_quiz(classroom.title, cluster.title, questions)
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
        target_ids = list(
            await db.scalars(
                select(FeedbackTarget.participant_id).where(
                    FeedbackTarget.cluster_id == check.cluster_id,
                    FeedbackTarget.round == check.feedback_round,
                )
            )
        )
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
    require_student(participant, authorization)
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


@router.get("/sessions/{session_id}/events")
async def list_events(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    events = list(
        await db.scalars(
            select(ClusterEvent)
            .where(ClusterEvent.session_id == session_id)
            .order_by(ClusterEvent.created_at)
        )
    )
    return {
        "data": [
            {
                "id": event.id,
                "cluster_id": event.cluster_id,
                "question_id": event.question_id,
                "event_type": event.event_type,
                "payload": json.loads(event.payload_json),
                "created_at": event.created_at,
            }
            for event in events
        ]
    }


@router.get("/sessions/{session_id}/counts")
async def counts(
    session_id: str, db: Database, authorization: Authorization = None
) -> dict:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    question_count = await db.scalar(
        select(func.count()).select_from(Question).where(Question.session_id == session_id)
    )
    return {"data": {"question_count": question_count}}
