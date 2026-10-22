import asyncio
import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import classroom as classroom_routes
from app.api.routes.classroom import confusion_signal
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas.classroom import FeedbackSummary

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


class RoleAwareTestClient(TestClient):
    """Keeps existing workflow tests concise while exercising real bearer credentials."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.classrooms: dict[str, dict] = {}
        self.student_tokens: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs):
        match = re.search(r"/sessions/([^/?]+)", str(url))
        session_id = match.group(1) if match else None
        payload = kwargs.get("json") or {}
        if session_id and session_id in self.classrooms:
            classroom = self.classrooms[session_id]
            if str(url).endswith("/join"):
                payload = {**payload, "join_code": classroom["join_code"]}
                kwargs["json"] = payload
            else:
                participant_id = payload.get("participant_id")
                params = kwargs.get("params") or {}
                participant_id = participant_id or params.get("participant_id")
                token = self.student_tokens.get(participant_id) if participant_id else None
                token = token or classroom["teacher_token"]
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("Authorization", f"Bearer {token}")
                kwargs["headers"] = headers
        response = super().request(method, url, **kwargs)
        if method.upper() == "POST" and str(url).endswith("/sessions") and response.is_success:
            classroom = response.json()["data"]
            self.classrooms[classroom["id"]] = classroom
        if method.upper() == "POST" and str(url).endswith("/join") and response.is_success:
            student = response.json()["data"]
            self.student_tokens[student["participant_id"]] = student["access_token"]
        return response


async def override_db():
    async with session_factory() as session:
        yield session


async def reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


def test_confusion_signal_exposes_factual_components_and_check_errors() -> None:
    feedback = FeedbackSummary(
        round=1,
        targets=4,
        responses=4,
        understood=2,
        still_confused=2,
    )
    low_score, _, low = confusion_signal(
        participant_count=2,
        total_participants=10,
        recent_question_count=1,
        feedback=feedback,
        created_at=datetime.now() - timedelta(minutes=3),
        check_responses=4,
        check_correct=4,
    )
    high_score, _, high = confusion_signal(
        participant_count=2,
        total_participants=10,
        recent_question_count=1,
        feedback=feedback,
        created_at=datetime.now() - timedelta(minutes=3),
        check_responses=4,
        check_correct=0,
    )
    assert high_score > low_score
    assert low.check_error_ratio == 0
    assert high.check_error_ratio == 1
    assert high.participant_ratio == 0.2


def test_local_question_pipeline_is_idempotent_and_clustered() -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = RoleAwareTestClient(app)

    classroom = client.post("/api/v1/sessions", json={"title": "算法课"}).json()["data"]
    session_id = classroom["id"]
    first = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={"viewer_key": "student-a", "display_name": "学生 A"},
    ).json()["data"]
    second = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={"viewer_key": "student-b", "display_name": "学生 B"},
    ).json()["data"]

    first_payload = {
        "participant_id": first["participant_id"],
        "client_request_id": "request-1",
        "content": "递归为什么一定要有结束条件？",
    }
    response = client.post(f"/api/v1/sessions/{session_id}/questions", json=first_payload)
    assert response.status_code == 202
    first_question = response.json()["data"]
    assert first_question["processing_status"] == "clustered"
    assert first_question["embedding_model"] == "questionpulse-zh-semantic-hash-v1"

    repeated = client.post(f"/api/v1/sessions/{session_id}/questions", json=first_payload)
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["data"]["id"] == first_question["id"]

    second_response = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        json={
            "participant_id": second["participant_id"],
            "client_request_id": "request-2",
            "content": "没有 base case 程序是不是停不下来？",
        },
    )
    second_question = second_response.json()["data"]
    assert second_question["cluster_id"] == first_question["cluster_id"]
    assert second_question["assignment_method"] == "semantic_high_confidence"

    snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert len(snapshot["clusters"]) == 1
    assert snapshot["clusters"][0]["participant_count"] == 2
    assert snapshot["clusters"][0]["question_count"] == 2

    third = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "student-c"}
    ).json()["data"]
    distinct = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        json={
            "participant_id": third["participant_id"],
            "client_request_id": "request-3",
            "content": "为什么递归太深会发生栈溢出？",
        },
    ).json()["data"]
    assert distinct["cluster_id"] != first_question["cluster_id"]
    assert distinct["assignment_method"] == "new_cluster_low_confidence"

    detached = client.post(
        f"/api/v1/sessions/{session_id}/questions/{second_question['id']}/detach",
        json={"title": "教师手动拆分"},
    )
    assert detached.status_code == 200
    after_detach = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert len(after_detach["clusters"]) == 3
    original_cluster = next(
        item for item in after_detach["clusters"] if item["id"] == first_question["cluster_id"]
    )
    assert original_cluster["version"] == 2
    events = client.get(f"/api/v1/sessions/{session_id}/events").json()["data"]
    assert events[-1]["event_type"] == "question_detached"

    app.dependency_overrides.clear()


def test_embedding_failure_keeps_question_pending(monkeypatch) -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = RoleAwareTestClient(app)
    session_id = client.post("/api/v1/sessions", json={"title": "降级测试"}).json()["data"]["id"]
    participant_id = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "failure-user"}
    ).json()["data"]["participant_id"]

    def fail_embedding(_: str) -> list[float]:
        raise RuntimeError("embedding_unavailable")

    monkeypatch.setattr("app.api.routes.classroom.embed", fail_embedding)
    response = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        json={
            "participant_id": participant_id,
            "client_request_id": "failure-request",
            "content": "模型不可用时这条问题不能丢失",
        },
    )
    assert response.status_code == 202
    assert response.json()["data"]["processing_status"] == "pending"
    snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert len(snapshot["pending_questions"]) == 1
    question_id = response.json()["data"]["id"]
    monkeypatch.undo()
    retried = client.post(f"/api/v1/sessions/{session_id}/questions/retry-pending")
    assert retried.status_code == 200
    assert retried.json()["data"] == {"attempted": 1, "recovered": 1, "remaining": 0}
    recovered = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert recovered["pending_questions"] == []
    assert recovered["clusters"][0]["questions"][0]["id"] == question_id
    app.dependency_overrides.clear()


def test_state_feedback_and_report_loop() -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = RoleAwareTestClient(app)
    classroom = client.post("/api/v1/sessions", json={"title": "反馈闭环"}).json()["data"]
    session_id = classroom["id"]
    participants = []
    for key in ("loop-a", "loop-b"):
        participant = client.post(
            f"/api/v1/sessions/{session_id}/join", json={"viewer_key": key}
        ).json()["data"]
        participants.append(participant["participant_id"])
    for index, (participant_id, content) in enumerate(
        zip(
            participants,
            ("递归为什么需要结束条件？", "没有 base case 会怎么样？"),
            strict=True,
        )
    ):
        response = client.post(
            f"/api/v1/sessions/{session_id}/questions",
            json={
                "participant_id": participant_id,
                "client_request_id": f"loop-{index}",
                "content": content,
            },
        )
        assert response.status_code == 202

    snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    cluster = snapshot["clusters"][0]
    cluster_id = cluster["id"]
    first_question_id = cluster["questions"][0]["id"]
    addressing = client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "addressing", "expected_version": 1},
    )
    assert addressing.status_code == 200
    assert addressing.json()["data"]["version"] == 2

    stale = client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "awaiting_feedback", "expected_version": 1},
    )
    assert stale.status_code == 409
    awaiting = client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "awaiting_feedback", "expected_version": 2},
    )
    assert awaiting.status_code == 200
    assert awaiting.json()["data"]["feedback_round"] == 1

    feedback_url = f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/feedback"
    first_feedback = {
        "participant_id": participants[0],
        "round": 1,
        "result": "understood",
    }
    assert client.put(feedback_url, json=first_feedback).status_code == 200
    first_feedback["result"] = "still_confused"
    assert client.put(feedback_url, json=first_feedback).status_code == 200

    student_snapshot = client.get(
        f"/api/v1/sessions/{session_id}/snapshot",
        params={"participant_id": participants[0]},
    ).json()
    assert len(student_snapshot["clusters"][0]["questions"]) == 1
    summary = student_snapshot["clusters"][0]["feedback"]
    assert summary == {
        "round": 1,
        "targets": 2,
        "responses": 1,
        "understood": 0,
        "still_confused": 1,
        "my_result": "still_confused",
    }

    late_participant = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "loop-late"}
    ).json()["data"]["participant_id"]
    rejected = client.put(
        feedback_url,
        json={
            "participant_id": late_participant,
            "round": 1,
            "result": "understood",
        },
    )
    assert rejected.status_code == 403

    closed = client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "closed", "expected_version": 3},
    )
    assert closed.status_code == 200
    assert client.put(feedback_url, json=first_feedback).status_code == 409
    report = client.get(f"/api/v1/sessions/{session_id}/report").json()
    assert report["question_count"] == 2
    assert report["participant_count"] == 2
    assert report["feedback_coverage"] == 0.5
    assert report["still_confused"] == 1
    assert len(report["follow_ups"]) == 1
    assert any(item["kind"] == "status_changed" for item in report["timeline"])
    assert any(item["kind"] == "question_received" for item in report["timeline"])

    reopened = client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "open", "expected_version": 4},
    )
    assert reopened.status_code == 200
    ended = client.post(f"/api/v1/sessions/{session_id}/end")
    assert ended.status_code == 200
    assert ended.json()["data"]["status"] == "ended"
    ended_report = client.get(f"/api/v1/sessions/{session_id}/report").json()
    assert ended_report["status"] == "ended"
    rejected_join = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={"viewer_key": "late-student", "join_code": classroom["join_code"]},
    )
    assert rejected_join.status_code == 409
    assert rejected_join.json()["detail"] == "session_ended"
    rejected_question = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        json={
            "participant_id": participants[0],
            "client_request_id": "after-end",
            "content": "结束后不能继续提问",
        },
    )
    assert rejected_question.status_code == 409
    assert client.patch(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
        json={"status": "addressing", "expected_version": 5},
    ).status_code == 409
    assert client.put(
        feedback_url,
        json=first_feedback,
    ).status_code == 409
    assert client.post(
        f"/api/v1/sessions/{session_id}/questions/{first_question_id}/detach",
        json={},
    ).status_code == 409
    assert client.post(
        f"/api/v1/sessions/{session_id}/questions/retry-pending",
        json={},
    ).status_code == 409

    next_session = client.post(
        "/api/v1/sessions", json={"title": "下一堂课"}
    )
    assert next_session.status_code == 201
    assert next_session.json()["data"]["status"] == "live"
    app.dependency_overrides.clear()


def test_polyv_contract_fixture_maps_and_deduplicates_without_live_call() -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = RoleAwareTestClient(app)
    session_id = client.post("/api/v1/sessions", json={"title": "接入契约"}).json()["data"]["id"]
    payload = {
        "environment": "contract_test",
        "channel_id": "contract-channel",
        "polyv_session_id": "contract-session",
        "events": [
            {
                "external_id": "qa-1001",
                "viewer_key": "polyv-viewer-a",
                "content": "递归出口为什么必须存在？",
                "occurred_at": "2026-10-20T14:00:00Z",
                "source": "polyv_qa",
            }
        ],
    }
    url = f"/api/v1/sessions/{session_id}/integrations/polyv/events"
    first = client.post(url, json=payload)
    assert first.status_code == 200
    assert first.json()["data"]["accepted"] == 1
    repeated = client.post(url, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["accepted"] == 0
    assert repeated.json()["data"]["duplicates"] == 1
    snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert snapshot["integration_status"] == "contract_verified"
    assert snapshot["polyv_channel_id"] == "contract-channel"
    question = snapshot["clusters"][0]["questions"][0]
    assert question["source"] == "polyv_qa"
    assert question["external_id"] == "qa-1001"
    degraded = client.post(
        f"/api/v1/sessions/{session_id}/integrations/polyv/drill",
        json={"environment": "contract_test", "action": "degrade", "reason": "timeout"},
    )
    assert degraded.json()["data"]["integration_status"] == "degraded"
    degraded_snapshot = client.get(f"/api/v1/sessions/{session_id}/snapshot").json()
    assert degraded_snapshot["integration_error"] == "timeout"
    recovered = client.post(
        f"/api/v1/sessions/{session_id}/integrations/polyv/drill",
        json={"environment": "contract_test", "action": "recover"},
    )
    assert recovered.json()["data"]["integration_status"] == "contract_verified"
    app.dependency_overrides.clear()


def test_formative_check_is_reviewed_targeted_and_frozen_after_class() -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = RoleAwareTestClient(app)
    classroom = client.post("/api/v1/sessions", json={"title": "形成性评价"}).json()["data"]
    session_id = classroom["id"]
    student = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "target-student"}
    ).json()["data"]
    outsider = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "outsider"}
    ).json()["data"]
    question = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        json={
            "participant_id": student["participant_id"],
            "client_request_id": "check-source",
            "content": "递归的退出条件怎样判断？",
        },
    ).json()["data"]
    cluster_id = question["cluster_id"]
    snapshot = client.get(f"/api/v1/sessions/{session_id}/teacher-snapshot").json()
    version = snapshot["clusters"][0]["version"]
    for state in ("addressing", "awaiting_feedback"):
        changed = client.patch(
            f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/status",
            json={"status": state, "expected_version": version},
        )
        assert changed.status_code == 200
        version = changed.json()["data"]["version"]

    generated = client.post(
        f"/api/v1/sessions/{session_id}/clusters/{cluster_id}/checks/generate"
    )
    assert generated.status_code == 200
    check = generated.json()
    assert check["status"] == "draft"
    assert check["correct_option_key"] == "A"
    target_headers = {"Authorization": f"Bearer {student['access_token']}"}
    outsider_headers = {"Authorization": f"Bearer {outsider['access_token']}"}
    assert client.get(
        f"/api/v1/sessions/{session_id}/checks/active", headers=target_headers
    ).json() == []

    approved = client.post(f"/api/v1/sessions/{session_id}/checks/{check['id']}/approve")
    assert approved.status_code == 200
    active = client.get(
        f"/api/v1/sessions/{session_id}/checks/active", headers=target_headers
    ).json()[0]
    assert active["correct_option_key"] is None
    assert active["explanation"] is None
    assert client.get(
        f"/api/v1/sessions/{session_id}/checks/active", headers=outsider_headers
    ).json() == []

    answer_url = f"/api/v1/sessions/{session_id}/checks/{check['id']}/answer"
    answer = client.put(
        answer_url,
        headers=target_headers,
        json={"participant_id": student["participant_id"], "option_key": "A"},
    )
    assert answer.status_code == 200
    assert answer.json()["data"]["is_correct"] is True
    assert answer.json()["data"]["explanation"]
    repeated_answer = client.put(
        answer_url,
        headers=target_headers,
        json={"participant_id": student["participant_id"], "option_key": "B"},
    )
    assert repeated_answer.status_code == 409
    assert repeated_answer.json()["detail"] == "check_already_answered"
    assert client.put(
        answer_url,
        headers=outsider_headers,
        json={"participant_id": outsider["participant_id"], "option_key": "A"},
    ).status_code == 403

    report = client.get(f"/api/v1/sessions/{session_id}/report").json()
    assert report["check_targets"] == 1
    assert report["check_responses"] == 1
    assert report["check_correct"] == 1
    assert report["check_accuracy"] == 1.0
    assert any(item["kind"] == "check_created" for item in report["timeline"])
    assert client.post(f"/api/v1/sessions/{session_id}/end").status_code == 200
    assert client.put(
        answer_url,
        headers=target_headers,
        json={"participant_id": student["participant_id"], "option_key": "B"},
    ).status_code == 409
    app.dependency_overrides.clear()


def test_role_boundaries_reject_cross_role_access(monkeypatch) -> None:
    asyncio.run(reset_database())
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    classroom = client.post("/api/v1/sessions", json={"title": "权限边界"}).json()["data"]
    session_id = classroom["id"]
    teacher_headers = {"Authorization": f"Bearer {classroom['teacher_token']}"}

    missing_code = client.post(
        f"/api/v1/sessions/{session_id}/join", json={"viewer_key": "student-a"}
    )
    assert missing_code.status_code == 403
    student = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={"viewer_key": "student-a", "join_code": classroom["join_code"]},
    ).json()["data"]
    student_headers = {"Authorization": f"Bearer {student['access_token']}"}

    assert client.get(
        f"/api/v1/sessions/{session_id}/teacher-snapshot", headers=student_headers
    ).status_code == 403
    assert client.get(
        f"/api/v1/sessions/{session_id}/report", headers=student_headers
    ).status_code == 403
    assert client.post(
        f"/api/v1/sessions/{session_id}/end", headers=student_headers, json={}
    ).status_code == 403
    teacher_snapshot = client.get(
        f"/api/v1/sessions/{session_id}/teacher-snapshot", headers=teacher_headers
    )
    assert teacher_snapshot.status_code == 200
    student_snapshot = client.get(
        f"/api/v1/sessions/{session_id}/student-snapshot", headers=student_headers
    )
    assert student_snapshot.status_code == 200
    assert all("ai_semantic_reason" not in item for item in student_snapshot.json()["clusters"])
    assert all("ai_normalized_intent" in item for item in teacher_snapshot.json()["clusters"])
    expired_settings = classroom_routes.get_settings().model_copy(
        update={"access_token_ttl_hours": 0}
    )
    monkeypatch.setattr(classroom_routes, "get_settings", lambda: expired_settings)
    expired_student = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={"viewer_key": "expired-student", "join_code": classroom["join_code"]},
    ).json()["data"]
    expired_headers = {"Authorization": f"Bearer {expired_student['access_token']}"}
    expired_snapshot = client.get(
        f"/api/v1/sessions/{session_id}/student-snapshot", headers=expired_headers
    )
    assert expired_snapshot.status_code == 403
    assert expired_snapshot.json()["detail"] == "access_expired"
    app.dependency_overrides.clear()
