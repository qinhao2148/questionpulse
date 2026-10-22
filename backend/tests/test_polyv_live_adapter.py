import hashlib

import httpx
import pytest

from app.integrations.polyv import PolyvApiError, PolyvQuestionAdapter, build_sign


def test_build_sign_matches_polyv_documented_algorithm() -> None:
    params = {
        "channelIds": "2477096,2272655",
        "startDay": "2022-05-20",
        "endDay": "2022-06-18",
        "appId": "g4rqgmmjuo",
        "timestamp": "1660270926732",
        "page": None,
    }
    secret = "fsq2k5weced1h8vui657xtdva66whf0g"
    canonical = (
        "appIdg4rqgmmjuochannelIds2477096,2272655endDay2022-06-18"
        "startDay2022-05-20timestamp1660270926732"
    )
    expected = hashlib.md5(f"{secret}{canonical}{secret}".encode()).hexdigest().upper()
    assert build_sign(params, secret) == expected


@pytest.mark.asyncio
async def test_fetch_questions_signs_maps_and_uses_https() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        assert request.url.scheme == "https"
        assert query["sign"] == build_sign(
            {key: value for key, value in query.items() if key != "sign"}, "secret"
        )
        if request.url.path.endswith("/getQuestion"):
            return httpx.Response(200, json={"code": 200, "status": "success", "data": []})
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "data": {
                    "contents": [
                        {
                            "id": 6283,
                            "sessionId": "session-a",
                            "viewerId": "viewer-a",
                            "content": "为什么需要递归出口？",
                            "timestamp": 1722912874624,
                        }
                    ]
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PolyvQuestionAdapter("app", "secret", client=client)
        questions = await adapter.fetch_questions("4146015")
    assert questions[0].external_id == "6283"
    assert questions[0].viewer_key == "viewer-a"
    assert questions[0].source == "polyv_qa"


@pytest.mark.asyncio
async def test_fetch_questions_maps_watch_sdk_ask_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getQuestion"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "status": "success",
                    "data": [
                        {
                            "id": "ask-1",
                            "event": "S_QUESTION",
                            "content": "QuestionPulse&nbsp;E2E&nbsp;验收",
                            "time": 1722912874624,
                            "user": {"userId": "viewer-watch-sdk"},
                        },
                        {
                            "id": "answer-1",
                            "event": "T_ANSWER",
                            "content": "避免无限调用。",
                            "time": 1722912875624,
                            "user": {"userId": "teacher"},
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "success": True,
                "status": "success",
                "data": {"contents": []},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PolyvQuestionAdapter("app", "secret", client=client)
        questions = await adapter.fetch_questions("4146015")
    assert len(questions) == 1
    assert questions[0].external_id == "ask-1"
    assert questions[0].viewer_key == "viewer-watch-sdk"
    assert questions[0].source == "polyv_ask"
    assert questions[0].content == "QuestionPulse E2E 验收"


@pytest.mark.asyncio
async def test_fetch_questions_hides_remote_error_details() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 400,
                "success": False,
                "error": {"code": 20001, "desc": "application not found"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PolyvQuestionAdapter("app", "secret", client=client)
        with pytest.raises(PolyvApiError, match="20001"):
            await adapter.fetch_questions("4146015")
