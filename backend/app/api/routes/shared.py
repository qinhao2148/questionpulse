import hashlib
import json
import math
import time
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import ClusterCandidate, DeepSeekAnalyzer, DeepSeekError, QuizDraft, QuizOptionDraft
from app.core.auth import (
    bearer_token,
    pseudonymize_external_viewer,
    token_digest,
    verify_access_token,
    verify_teacher_portal_token,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.integrations.base import NormalizedQuestion
from app.models.classroom import (
    AIDecision,
    AIRun,
    CheckOption,
    CheckQuestion,
    CheckResponse,
    CheckTarget,
    Cluster,
    Feedback,
    FeedbackTarget,
    Participant,
    ParticipantToken,
    Question,
    Submission,
)
from app.models.session import ClassroomSession
from app.schemas.classroom import (
    CheckOptionView,
    CheckQuestionView,
    ClusterView,
    ConfusionBreakdown,
    FeedbackSummary,
    QuestionView,
    Snapshot,
)
from app.services.embedding import MODEL_NAME, cosine, embed, normalize

Database = Annotated[AsyncSession, Depends(get_db)]
Authorization = Annotated[str | None, Header()]
HIGH_CONFIDENCE = 0.55



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


async def external_participant(
    db: AsyncSession, session_id: str, raw_viewer_key: str
) -> Participant:
    pseudonym = pseudonymize_external_viewer(
        raw_viewer_key, get_settings().participant_pseudonym_key
    )
    participant = await db.scalar(
        select(Participant).where(
            Participant.session_id == session_id,
            Participant.viewer_key.in_([pseudonym, raw_viewer_key]),
        )
    )
    if participant is None:
        participant = Participant(session_id=session_id, viewer_key=pseudonym, source="polyv")
        db.add(participant)
        await db.flush()
    elif participant.viewer_key == raw_viewer_key:
        participant.viewer_key = pseudonym
    return participant


async def cluster_audience_ids(
    db: AsyncSession, session_id: str, cluster_id: str
) -> list[str]:
    """Participants who should receive feedback prompts and checks for a cluster.

    POLYV's management API can expose a viewer id unrelated to the identity a
    student uses on the student page, so syncing a question may mint a shadow
    participant with no display name. Targeting only question authors then
    strands the real student: their "已理解" call fails with 403 and a generated
    check is never delivered to them.

    Named participants are the people who can actually open the student page, so
    the whole named classroom is the audience. Shadow identities are left out to
    keep the "answered / targeted" ratio honest. A classroom where nobody has a
    display name falls back to the question authors so the flow still works.
    """
    named = set(
        await db.scalars(
            select(Participant.id).where(
                Participant.session_id == session_id,
                Participant.display_name.isnot(None),
            )
        )
    )
    if named:
        return sorted(named)
    return sorted(
        set(
            await db.scalars(
                select(Question.participant_id).where(
                    Question.cluster_id == cluster_id
                ).distinct()
            )
        )
    )


async def store_external_question(
    db: AsyncSession,
    session_id: str,
    event: NormalizedQuestion,
) -> tuple[Question, str]:
    """Store a POLYV question while preserving the authenticated web identity.

    The management API can expose a platform viewer id that differs from the
    watch SDK user id. Student submissions are therefore mirrored locally and
    reconciled by normalized content when POLYV syncs.
    """
    existing = await db.scalar(
        select(Question).where(
            Question.session_id == session_id,
            Question.source == event.source,
            Question.external_id == event.external_id,
        )
    )
    if existing is not None:
        return existing, "duplicate"

    mirror = await db.scalar(
        select(Question)
        .join(Submission, Submission.question_id == Question.id)
        .where(
            Question.session_id == session_id,
            Question.source == "questionpulse",
            Question.external_id.is_(None),
            Question.normalized_content == normalize(event.content),
        )
        .order_by(Question.created_at.desc())
    )
    occurred_at = event.occurred_at.replace(tzinfo=None)
    if mirror is not None:
        mirror.source = event.source
        mirror.external_id = event.external_id
        mirror.occurred_at = occurred_at
        return mirror, "reconciled"

    participant = await external_participant(db, session_id, event.viewer_key)
    question = Question(
        session_id=session_id,
        participant_id=participant.id,
        content=event.content.strip(),
        normalized_content=normalize(event.content),
        source=event.source,
        external_id=event.external_id,
        occurred_at=occurred_at,
    )
    db.add(question)
    await db.flush()
    await assign_question(db, question)
    return question, "accepted"


def is_current_classroom_event(event: NormalizedQuestion, created_at: datetime) -> bool:
    """Exclude question history from earlier broadcasts on a reused POLYV channel."""
    classroom_start = created_at
    if classroom_start.tzinfo is None:
        classroom_start = classroom_start.replace(tzinfo=timezone(timedelta(hours=8)))
    event_time = event.occurred_at
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)
    # Allow a small clock skew while still excluding earlier broadcast history.
    return event_time.astimezone(UTC) >= classroom_start.astimezone(UTC) - timedelta(minutes=2)


def is_teacher_portal_authorized(authorization: str | None) -> bool:
    settings = get_settings()
    return verify_teacher_portal_token(
        bearer_token(authorization),
        settings.teacher_username,
        settings.teacher_portal_secret,
        settings.teacher_portal_ttl_hours,
    )


def require_teacher_portal(authorization: str | None) -> None:
    if not is_teacher_portal_authorized(authorization):
        # A missing or stale portal token is a login problem, not a permission
        # problem. Naming it lets the web console and the browser extension
        # tell the teacher to sign in again instead of asking them to retry.
        raise HTTPException(status_code=403, detail="teacher_login_required")


def require_teacher(classroom: ClassroomSession, authorization: str | None) -> None:
    if is_teacher_portal_authorized(authorization):
        return
    supplied = bearer_token(authorization)
    if supplied is not None and supplied.startswith("qpa_"):
        # The caller presented a portal token that no longer verifies: it aged
        # out or the signing key rotated. A classroom token would fail the same
        # way for every classroom, so report the real cause.
        raise HTTPException(status_code=403, detail="teacher_login_required")
    verify_access_token(
        classroom.teacher_token_hash, authorization, classroom.teacher_token_expires_at
    )


async def require_student(
    db: AsyncSession, participant: Participant, authorization: str | None
) -> None:
    """确认调用者持有的令牌属于这个参与者。

    一个参与者可能同时持有多张令牌（同一浏览器开了多个标签页），所以先查
    令牌表；只查 participant.access_token_hash 会把除最新一张以外的令牌
    全部判成 403。
    """
    token = bearer_token(authorization)
    if token is not None:
        record = await db.scalar(
            select(ParticipantToken).where(
                ParticipantToken.token_hash == token_digest(token)
            )
        )
        if record is not None and record.participant_id == participant.id:
            verify_access_token(record.token_hash, authorization, record.expires_at)
            return
    verify_access_token(
        participant.access_token_hash, authorization, participant.access_token_expires_at
    )


async def feedback_summary(
    db: AsyncSession,
    cluster: Cluster,
    participant_id: str | None = None,
    round_number: int | None = None,
) -> FeedbackSummary:
    current_round = cluster.feedback_round if round_number is None else round_number
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
                feedback_history=[
                    await feedback_summary(db, cluster, participant_id, round_number)
                    for round_number in range(1, cluster.feedback_round + 1)
                ],
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

    rag_answer_views: list = []
    published_answer_views: list = []
    if include_teacher_insights:
        from app.knowledge.views import citation_views
        from app.models.knowledge import RagAnswer, RagCitation

        answer_rows = (
            await db.execute(
                select(RagAnswer, Question)
                .join(Question, Question.id == RagAnswer.question_id)
                .where(
                    RagAnswer.session_id == session_id,
                    RagAnswer.answer_status.in_(["draft", "approved", "published", "failed"]),
                )
                .order_by(RagAnswer.created_at.desc())
                .limit(50)
            )
        ).all()
        if answer_rows:
            citation_rows = list(
                await db.scalars(
                    select(RagCitation)
                    .where(RagCitation.rag_answer_id.in_([row[0].id for row in answer_rows]))
                    .order_by(RagCitation.citation_order)
                )
            )
            citations_by_answer: dict = {}
            for citation in citation_rows:
                citations_by_answer.setdefault(citation.rag_answer_id, []).append(citation)
            from app.schemas.knowledge import RagAnswerView

            for answer, question in reversed(answer_rows):
                rag_answer_views.append(
                    RagAnswerView(
                        id=answer.id,
                        question_id=answer.question_id,
                        cluster_id=answer.cluster_id,
                        question_content=question.content if question else None,
                        answer=answer.answer,
                        confidence=answer.confidence,
                        insufficient_evidence=answer.insufficient_evidence,
                        answer_status=answer.answer_status,
                        model=answer.model,
                        error_code=answer.error_code,
                        citations=await citation_views(
                            db, citations_by_answer.get(answer.id, [])
                        ),
                        created_at=answer.created_at,
                    )
                )
    elif participant_id is not None:
        from app.knowledge.views import citation_views
        from app.models.knowledge import RagAnswer, RagCitation

        # Published answers are classroom-wide: questions promoted from the
        # POLYV chat belong to shadow participants no student client logs in
        # as, so filtering by asker would make those answers unreachable for
        # everyone. The teacher's publish action is the explicit consent to
        # show the answer to the whole class.
        published_rows = (
            await db.execute(
                select(RagAnswer, Question)
                .join(Question, Question.id == RagAnswer.question_id)
                .where(
                    RagAnswer.session_id == session_id,
                    RagAnswer.answer_status == "published",
                )
                .order_by(RagAnswer.published_at.desc())
                .limit(30)
            )
        ).all()
        if published_rows:
            citation_rows = list(
                await db.scalars(
                    select(RagCitation)
                    .where(RagCitation.rag_answer_id.in_([row[0].id for row in published_rows]))
                    .order_by(RagCitation.citation_order)
                )
            )
            citations_by_answer: dict = {}
            for citation in citation_rows:
                citations_by_answer.setdefault(citation.rag_answer_id, []).append(citation)
            from app.schemas.classroom import StudentPublishedAnswer

            for answer, question in published_rows:
                published_answer_views.append(
                    StudentPublishedAnswer(
                        answer_id=answer.id,
                        question_id=answer.question_id,
                        question_content=question.content if question else None,
                        answer=answer.answer,
                        citations=await citation_views(
                            db, citations_by_answer.get(answer.id, [])
                        ),
                        published_at=answer.published_at,
                    )
                )

    return Snapshot(
        id=classroom.id,
        title=classroom.title,
        join_code=classroom.join_code,
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
        rag_answers=rag_answer_views,
        published_answers=published_answer_views,
    )


async def resolve_student(
    db: AsyncSession, session_id: str, authorization: str | None
) -> Participant:
    token = bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=403, detail="access_denied")
    digest = token_digest(token)
    record = await db.scalar(
        select(ParticipantToken).where(ParticipantToken.token_hash == digest)
    )
    if record is not None:
        verify_access_token(record.token_hash, authorization, record.expires_at)
        participant = await db.get(Participant, record.participant_id)
        if participant is None or participant.session_id != session_id:
            raise HTTPException(status_code=403, detail="access_denied")
        return participant
    # 兼容多令牌之前签发的会话：仍按参与者上的单个 digest 校验。
    participant = await db.scalar(
        select(Participant).where(
            Participant.session_id == session_id,
            Participant.access_token_hash == digest,
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


VIEWER_HEARTBEAT_SECONDS = 30


def mark_viewer_present(participant: Participant) -> bool:
    """记录一次“这个学生还在课堂里”的心跳，返回是否真的需要写库。

    学生端每 3 秒拉一次快照，如果每次都写库对 MySQL 是个没必要的负担，
    所以 30 秒内的重复心跳直接跳过。写库成功即代表学生确实在看，
    报告里的“观看人数”以此为准，而不是只看有没有 join 过。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    last = participant.last_seen_at
    if last is not None and (now - last).total_seconds() < VIEWER_HEARTBEAT_SECONDS:
        return False
    participant.last_seen_at = now
    return True


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
    revealed = reveal_answer or own is not None
    return CheckQuestionView(
        id=check.id,
        cluster_id=check.cluster_id,
        feedback_round=check.feedback_round,
        status=check.status,
        stem=check.stem,
        options=[CheckOptionView(key=item.option_key, content=item.content) for item in options],
        source=check.source,
        knowledge_backed=check.knowledge_backed,
        explanation=check.explanation if revealed else None,
        correct_option_key=check.correct_option_key if revealed else None,
        target_count=target_count or 0,
        response_count=len(responses),
        # How many classmates already got it right is a hint the student has not
        # earned yet; keep it at 0 until they answer (or the caller is a teacher).
        correct_count=sum(item.is_correct for item in responses) if revealed else 0,
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
