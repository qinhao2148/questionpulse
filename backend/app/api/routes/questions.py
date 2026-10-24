import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.api.routes.shared import (
    Authorization,
    Database,
    assign_question,
    is_current_classroom_event,
    mean_unit_vector,
    question_view,
    require_active_session,
    require_session,
    require_student,
    require_teacher,
    store_external_question,
)
from app.core.config import get_settings
from app.core.session_gate import session_cluster_gate
from app.integrations.polyv import PolyvApiError, PolyvNotConfiguredError, PolyvQuestionAdapter
from app.models.classroom import (
    Cluster,
    ClusterEvent,
    Participant,
    Question,
    Submission,
)
from app.models.session import ClassroomSession
from app.schemas.classroom import (
    DetachRequest,
    IntegrationDrill,
    PolyvEventBatch,
    PolyvSyncRequest,
    QuestionCreate,
)
from app.services.embedding import MODEL_NAME, normalize

router = APIRouter()



@router.post("/sessions/{session_id}/questions", status_code=status.HTTP_202_ACCEPTED)
async def submit_question(
    session_id: str,
    payload: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_session(db, session_id)
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    participant = await db.get(Participant, payload.participant_id)
    if participant is None or participant.session_id != session_id:
        raise HTTPException(status_code=403, detail="participant_not_in_session")
    await require_student(db, participant, authorization)

    async with session_cluster_gate(session_id):
        # Close the read-only transaction opened by the checks above. Under
        # REPEATABLE READ the next query otherwise reuses that older snapshot
        # and misses a cluster committed while this request was waiting.
        await db.commit()
        existing = await db.scalar(
            select(Submission).where(
                Submission.session_id == session_id,
                Submission.participant_id == payload.participant_id,
                Submission.client_request_id == payload.client_request_id,
            )
        )
        if existing:
            question = await db.get(Question, existing.question_id)
            return {
                "data": question_view(question).model_dump(mode="json"),
                "idempotent": True,
            }

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
        from app.knowledge.answering import queue_draft_if_knowledge_bound

        await queue_draft_if_knowledge_bound(background_tasks, db, session_id, question.id)
        return {"data": question_view(question).model_dump(mode="json"), "idempotent": False}


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
    reconciled = 0
    duplicates = 0
    pending = 0
    question_ids = []
    async with session_cluster_gate(session_id):
        await db.commit()
        for event in payload.events:
            question, outcome = await store_external_question(db, session_id, event)
            if outcome == "duplicate":
                duplicates += 1
                question_ids.append(question.id)
                continue
            accepted += 1
            reconciled += outcome == "reconciled"
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
            "reconciled": reconciled,
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

    fetched = len(events)
    seen_on_channel = set(
        (
            await db.execute(
                select(Question.source, Question.external_id)
                .join(ClassroomSession, ClassroomSession.id == Question.session_id)
                .where(
                    ClassroomSession.polyv_channel_id == channel_id,
                    Question.session_id != session_id,
                    Question.external_id.is_not(None),
                )
            )
        ).all()
    )
    events = [
        event
        for event in events
        if is_current_classroom_event(event, classroom.created_at)
        and (event.source, event.external_id) not in seen_on_channel
    ]
    skipped_history = fetched - len(events)
    accepted = duplicates = pending = reconciled = 0
    async with session_cluster_gate(session_id):
        await db.commit()
        for event in events:
            question, outcome = await store_external_question(db, session_id, event)
            if outcome == "duplicate":
                duplicates += 1
                continue
            accepted += 1
            reconciled += outcome == "reconciled"
            pending += question.processing_status == "pending"
        classroom.polyv_channel_id = channel_id
        classroom.polyv_session_id = (
            payload.polyv_session_id
            or classroom.polyv_session_id
            or settings.polyv_session_id
            or None
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
            "reconciled": reconciled,
            "duplicates": duplicates,
            "pending": pending,
            "fetched": fetched,
            "eligible": len(events),
            "skipped_history": skipped_history,
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
    async with session_cluster_gate(session_id):
        await db.commit()
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
    async with session_cluster_gate(session_id):
        await db.commit()
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
    # Splitting rewrites both clusters' centroids. Without the per-session gate a
    # question being clustered at the same moment could land in the old cluster
    # after its members were already recomputed.
    async with session_cluster_gate(session_id):
        await db.commit()
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
