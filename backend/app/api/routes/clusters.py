import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from app.api.routes.shared import (
    Authorization,
    Database,
    cluster_audience_ids,
    require_active_session,
    require_student,
    require_teacher,
)
from app.models.classroom import (
    CheckQuestion,
    Cluster,
    ClusterEvent,
    Feedback,
    FeedbackTarget,
    Participant,
)
from app.schemas.classroom import (
    FeedbackUpdate,
    StatusUpdate,
)

router = APIRouter()


TRANSITIONS = {
    "open": {"addressing"},
    "addressing": {"awaiting_feedback", "open"},
    "awaiting_feedback": {"closed", "addressing", "open"},
    "closed": {"open"},
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
        participant_ids = await cluster_audience_ids(db, session_id, cluster_id)
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
    await require_student(db, participant, authorization)
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
