import argparse
import json
import uuid
from pathlib import Path

import httpx

from app.core.config import get_settings

QUESTIONS = [
    ("student-a", "递归为什么一定要有结束条件？"),
    ("student-b", "没有 base case 程序是不是停不下来？"),
    ("student-c", "终止条件应该写在递归函数的哪里？"),
    ("student-d", "为什么递归太深会发生栈溢出？"),
    ("student-e", "Promise 回调为什么比 setTimeout 先执行？"),
    ("student-f", "事件循环如何安排异步任务的执行顺序？"),
]


def seed(base_url: str) -> dict[str, object]:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        settings = get_settings()
        login = client.post(
            "/teacher/login",
            json={
                "username": settings.teacher_username,
                "password": settings.teacher_password,
            },
        )
        login.raise_for_status()
        portal_token = login.json()["data"]["access_token"]
        classroom = client.post(
            "/sessions",
            headers={"Authorization": f"Bearer {portal_token}"},
            json={"title": "QuestionPulse 演示课堂"},
        )
        classroom.raise_for_status()
        access = classroom.json()["data"]
        session_id = access["id"]
        teacher_headers = {"Authorization": f"Bearer {access['teacher_token']}"}
        for viewer_key, content in QUESTIONS:
            joined = client.post(
                f"/sessions/{session_id}/join",
                json={"viewer_key": viewer_key, "join_code": access["join_code"]},
            )
            joined.raise_for_status()
            participant = joined.json()["data"]
            participant_id = participant["participant_id"]
            submitted = client.post(
                f"/sessions/{session_id}/questions",
                headers={"Authorization": f"Bearer {participant['access_token']}"},
                json={
                    "participant_id": participant_id,
                    "client_request_id": str(uuid.uuid4()),
                    "content": content,
                },
            )
            submitted.raise_for_status()
        snapshot = client.get(
            f"/sessions/{session_id}/teacher-snapshot", headers=teacher_headers
        )
        snapshot.raise_for_status()
        return {"snapshot": snapshot.json(), "access": access}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a local QuestionPulse classroom.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, help="Write machine-readable demo metadata.")
    args = parser.parse_args()
    result = seed(args.base_url)
    snapshot = result["snapshot"]
    access = result["access"]
    session_id = snapshot["id"]
    metadata = {
        "session_id": session_id,
        "join_code": access["join_code"],
        "teacher_token": access["teacher_token"],
        "student_url": (
            "http://127.0.0.1:15021/index.html"
            "?qpJoin=1&qpApiBase=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fv1"
        ),
        "teacher_url": "http://127.0.0.1:5173/",
        "report_url": "http://127.0.0.1:5173/",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"Student: {metadata['student_url']}")
    print(f"Teacher: {metadata['teacher_url']} (credentials stored in the private runtime file)")
    print(f"Report: {metadata['report_url']}")


if __name__ == "__main__":
    main()
