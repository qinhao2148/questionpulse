import hmac
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.shared import (
    Authorization,
    Database,
    build_snapshot,
    mark_viewer_present,
    require_active_session,
    require_session,
    require_student,
    require_teacher,
    require_teacher_portal,
    resolve_student,
)
from app.core.auth import (
    issue_access_token,
    issue_join_code,
    issue_polyv_identity_auth,
    pseudonymize_external_viewer,
    teacher_portal_token,
    token_digest,
)
from app.core.config import get_settings
from app.models.classroom import (
    CheckQuestion,
    Cluster,
    ClusterEvent,
    Participant,
    ParticipantToken,
    Question,
)
from app.models.session import ClassroomSession
from app.schemas.classroom import (
    JoinCodeUpdate,
    JoinRequest,
    SessionCreate,
    Snapshot,
    StudentEntryRequest,
    TeacherClassroomSummary,
    TeacherLogin,
)

router = APIRouter()



@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate, db: Database, authorization: Authorization = None
) -> dict:
    require_teacher_portal(authorization)
    settings = get_settings()
    teacher_token = issue_access_token("qpt")
    # join_code 有唯一索引。8 位 × 32 个字符几乎不可能撞，但真撞上会让建课直接
    # 500，老师只会看到一句"创建失败"而无从下手。先挑一个没人用的再生效。
    join_code = issue_join_code()
    for _ in range(5):
        taken = await db.scalar(
            select(ClassroomSession.id).where(ClassroomSession.join_code == join_code)
        )
        if taken is None:
            break
        join_code = issue_join_code()
    classroom = ClassroomSession(
        title=payload.title,
        status="live",
        teacher_token_hash=token_digest(teacher_token),
        teacher_token_expires_at=datetime.now(UTC)
        + timedelta(hours=settings.access_token_ttl_hours),
        join_code=join_code,
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


@router.post("/teacher/login")
async def teacher_login(payload: TeacherLogin) -> dict:
    settings = get_settings()
    username_ok = hmac.compare_digest(payload.username, settings.teacher_username)
    password_ok = hmac.compare_digest(payload.password, settings.teacher_password)
    if not username_ok or not password_ok:
        raise HTTPException(status_code=403, detail="invalid_teacher_credentials")
    return {
        "data": {
            "access_token": teacher_portal_token(
                settings.teacher_username, settings.teacher_portal_secret
            )
        }
    }


@router.get("/teacher/sessions", response_model=list[TeacherClassroomSummary])
async def list_teacher_sessions(
    db: Database, authorization: Authorization = None
) -> list[TeacherClassroomSummary]:
    require_teacher_portal(authorization)
    # Classrooms created before role binding have no teacher digest, so nobody
    # can open them any more. Keep the rows for the historical record but hide
    # them from the console instead of offering links that always 403.
    classrooms = list(
        await db.scalars(
            select(ClassroomSession)
            .where(ClassroomSession.teacher_token_hash.is_not(None))
            .order_by(
                case((ClassroomSession.status == "live", 0), else_=1),
                ClassroomSession.created_at.desc(),
            )
        )
    )
    result = []
    for classroom in classrooms:
        question_count = await db.scalar(
            select(func.count()).select_from(Question).where(Question.session_id == classroom.id)
        )
        cluster_count = await db.scalar(
            select(func.count()).select_from(Cluster).where(Cluster.session_id == classroom.id)
        )
        result.append(
            TeacherClassroomSummary(
                id=classroom.id,
                title=classroom.title,
                status=classroom.status,
                polyv_channel_id=classroom.polyv_channel_id,
                join_code=classroom.join_code,
                question_count=question_count or 0,
                cluster_count=cluster_count or 0,
                created_at=classroom.created_at,
                ended_at=classroom.ended_at,
            )
        )
    return result


@router.patch("/sessions/{session_id}/join-code")
async def update_join_code(
    session_id: str,
    payload: JoinCodeUpdate,
    db: Database,
    authorization: Authorization = None,
) -> dict:
    classroom = await require_active_session(db, session_id)
    require_teacher(classroom, authorization)
    classroom.join_code = payload.join_code.upper()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="join_code_in_use") from exc
    return {"data": {"join_code": classroom.join_code}}


MAX_STUDENT_TOKENS = 5


async def issue_student_token(db: AsyncSession, participant: Participant) -> str:
    """签发一个新的学生令牌，同时保留此前的令牌直到它们自然过期。

    多标签页场景下两个页面会各自加入课堂，如果像以前那样覆盖
    access_token_hash，先打开的标签页会立刻收到 403。这里把令牌写进
    participant_tokens，老令牌继续可用。
    """
    token = issue_access_token("qps")
    expires_at = datetime.now(UTC) + timedelta(hours=get_settings().access_token_ttl_hours)
    digest = token_digest(token)
    participant.access_token_hash = digest
    participant.access_token_expires_at = expires_at
    db.add(
        ParticipantToken(
            participant_id=participant.id,
            token_hash=digest,
            expires_at=expires_at.astimezone(UTC).replace(tzinfo=None),
        )
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    await db.execute(
        delete(ParticipantToken).where(
            ParticipantToken.participant_id == participant.id,
            ParticipantToken.expires_at.is_not(None),
            ParticipantToken.expires_at < now,
        )
    )
    issued = list(
        await db.scalars(
            select(ParticipantToken)
            .where(ParticipantToken.participant_id == participant.id)
            .order_by(ParticipantToken.created_at.desc(), ParticipantToken.token_hash)
        )
    )
    for stale in issued[MAX_STUDENT_TOKENS:]:
        await db.delete(stale)
    return token


@router.post("/student/join")
async def join_session_by_code(payload: StudentEntryRequest, db: Database) -> dict:
    classroom = await db.scalar(
        select(ClassroomSession).where(
            ClassroomSession.join_code == payload.join_code.upper()
        )
    )
    if classroom is None:
        raise HTTPException(status_code=404, detail="join_code_not_found")
    if classroom.status == "ended":
        raise HTTPException(status_code=409, detail="session_ended")
    existing = await db.scalar(
        select(Participant).where(
            Participant.session_id == classroom.id,
            Participant.viewer_key == payload.viewer_key,
        )
    )
    participant = existing or Participant(
        session_id=classroom.id,
        viewer_key=payload.viewer_key,
        display_name=payload.display_name.strip(),
    )
    participant.display_name = payload.display_name.strip()
    if existing is None:
        db.add(participant)
        await db.flush()
    student_token = await issue_student_token(db, participant)
    await db.commit()
    await db.refresh(participant)
    settings = get_settings()
    polyv_viewer_id = pseudonymize_external_viewer(
        participant.id, settings.participant_pseudonym_key
    )
    polyv_identity_auth = None
    if settings.polyv_app_secret:
        polyv_identity_auth = issue_polyv_identity_auth(
            polyv_viewer_id,
            participant.display_name,
            settings.polyv_app_secret,
        )
    # 本地墙上时间（与 end_session 的约定一致）：观看端浏览器用本地时区
    # Date.parse 还原为毫秒，避免服务端/数据库时区差异。
    return {
        "data": {
            "session_id": classroom.id,
            "session_title": classroom.title,
            "session_created_at": classroom.created_at.isoformat(),
            "participant_id": participant.id,
            "access_token": student_token,
            "join_code": classroom.join_code,
            "polyv_channel_id": classroom.polyv_channel_id or settings.polyv_channel_id or None,
            "polyv_session_id": classroom.polyv_session_id or settings.polyv_session_id or None,
            "polyv_viewer_id": polyv_viewer_id,
            "polyv_identity_auth": polyv_identity_auth,
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
    if existing is None:
        db.add(participant)
        await db.flush()
    student_token = await issue_student_token(db, participant)
    await db.commit()
    await db.refresh(participant)
    return {
        "data": {
            "participant_id": participant.id,
            "display_name": participant.display_name,
            "access_token": student_token,
        }
    }


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
    participant_id = participant.id
    if mark_viewer_present(participant):
        await db.commit()
    return await build_snapshot(db, classroom, participant_id)


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
        await require_student(db, participant, authorization)
    return await build_snapshot(
        db, classroom, participant_id, include_teacher_insights=participant_id is None
    )


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
