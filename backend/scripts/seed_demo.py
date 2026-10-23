import argparse
import json
import uuid
from pathlib import Path

import httpx

from app.core.config import get_settings

DEMO_TITLE = "QuestionPulse 演示课堂"

QUESTIONS = [
    ("student-a", "递归为什么一定要有结束条件？"),
    ("student-b", "没有 base case 程序是不是停不下来？"),
    ("student-c", "终止条件应该写在递归函数的哪里？"),
    ("student-d", "为什么递归太深会发生栈溢出？"),
    ("student-e", "Promise 回调为什么比 setTimeout 先执行？"),
    ("student-f", "事件循环如何安排异步任务的执行顺序？"),
]


def portal_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def find_live_demo(client: httpx.Client, portal_token: str) -> dict | None:
    """Reuse the demo classroom that is already live.

    The launcher seeds on every start, so always creating a classroom piled up
    dozens of identical demo lessons and made the history list useless.
    """
    response = client.get("/teacher/sessions", headers=portal_headers(portal_token))
    response.raise_for_status()
    for item in response.json():
        if item.get("status") != "ended" and item.get("title") == DEMO_TITLE:
            return item
    return None


def create_classroom(client: httpx.Client, portal_token: str) -> tuple[str, str]:
    classroom = client.post(
        "/sessions", headers=portal_headers(portal_token), json={"title": DEMO_TITLE}
    )
    classroom.raise_for_status()
    access = classroom.json()["data"]
    return access["id"], access["join_code"]


def seed_questions(client: httpx.Client, session_id: str, join_code: str) -> int:
    for viewer_key, content in QUESTIONS:
        joined = client.post(
            f"/sessions/{session_id}/join",
            json={"viewer_key": viewer_key, "join_code": join_code},
        )
        joined.raise_for_status()
        participant = joined.json()["data"]
        submitted = client.post(
            f"/sessions/{session_id}/questions",
            headers={"Authorization": f"Bearer {participant['access_token']}"},
            json={
                "participant_id": participant["participant_id"],
                "client_request_id": str(uuid.uuid4()),
                "content": content,
            },
        )
        submitted.raise_for_status()
    return len(QUESTIONS)


def seed(base_url: str, *, reuse: bool = True) -> dict[str, object]:
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

        existing = find_live_demo(client, portal_token) if reuse else None
        if existing is not None:
            session_id = existing["id"]
            join_code = existing.get("join_code") or ""
            created = False
            # Only fill an empty demo classroom; re-adding six questions on every
            # launch would inflate the cluster counts instead of resetting them.
            seeded = seed_questions(client, session_id, join_code) if not existing.get(
                "question_count"
            ) else 0
        else:
            session_id, join_code = create_classroom(client, portal_token)
            created = True
            seeded = seed_questions(client, session_id, join_code)

        snapshot = client.get(
            f"/sessions/{session_id}/teacher-snapshot", headers=portal_headers(portal_token)
        )
        snapshot.raise_for_status()
        return {
            "snapshot": snapshot.json(),
            "join_code": snapshot.json().get("join_code") or join_code,
            "session_id": session_id,
            "created": created,
            "seeded": seeded,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a local QuestionPulse classroom.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, help="Write machine-readable demo metadata.")
    parser.add_argument(
        "--new",
        action="store_true",
        help="Create a fresh classroom instead of reusing the live demo one.",
    )
    args = parser.parse_args()
    result = seed(args.base_url, reuse=not args.new)
    metadata = {
        "session_id": result["session_id"],
        "join_code": result["join_code"],
        "reused": not result["created"],
        "seeded_questions": result["seeded"],
        "student_url": (
            "http://127.0.0.1:15021/index.html"
            "?qpJoin=1&qpApiBase=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fv1"
        ),
        "teacher_url": "http://127.0.0.1:5173/",
        "report_url": "http://127.0.0.1:5173/",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(result["snapshot"], ensure_ascii=False, indent=2))
    reused = "existing" if metadata["reused"] else "new"
    print(f"Classroom: {reused}, join code {metadata['join_code']}")
    print(f"Student: {metadata['student_url']}")
    print(f"Teacher: {metadata['teacher_url']}")
    print(f"Report: {metadata['report_url']}")


if __name__ == "__main__":
    main()
