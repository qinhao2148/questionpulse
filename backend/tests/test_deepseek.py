import asyncio

import httpx
import pytest

from app.ai import ClusterCandidate, DeepSeekAnalyzer, DeepSeekError


def analyzer() -> DeepSeekAnalyzer:
    return DeepSeekAnalyzer(
        api_key="test-key",
        base_url="https://api.deepseek.example",
        model="test-model",
    )


def test_deepseek_structured_decision_is_validated(monkeypatch) -> None:
    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"decision":"join_existing","cluster_id":"cluster-1",'
                                '"confidence":0.93,"normalized_intent":"递归终止条件",'
                                '"suggested_title":"为什么递归需要终止条件",'
                                '"reason":"核心困惑一致"}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 35},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    decision, usage = asyncio.run(
        analyzer().classify(
            "算法课",
            "没有 base case 会怎样？",
            [
                ClusterCandidate(
                    id="cluster-1",
                    title="递归终止条件",
                    representative_questions=["递归为什么需要出口？"],
                )
            ],
        )
    )
    assert decision.cluster_id == "cluster-1"
    assert decision.confidence == 0.93
    assert usage == {"prompt_tokens": 120, "completion_tokens": 35}


def test_deepseek_invalid_output_degrades_to_typed_error(monkeypatch) -> None:
    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepSeekError):
        asyncio.run(analyzer().classify("算法课", "问题", []))


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_deepseek_http_failures_are_typed(monkeypatch, status_code: int) -> None:
    async def fake_post(self, url, **kwargs):
        return httpx.Response(status_code, request=httpx.Request("POST", url), json={})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepSeekError, match="HTTPStatusError"):
        asyncio.run(analyzer().classify("算法课", "问题", []))


def test_deepseek_timeout_is_typed(monkeypatch) -> None:
    async def fake_post(self, url, **kwargs):
        raise httpx.ReadTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepSeekError, match="ReadTimeout"):
        asyncio.run(analyzer().classify("算法课", "问题", []))


@pytest.mark.parametrize("content", ["", "{", '{"decision":"join_existing"}'])
def test_deepseek_empty_truncated_or_incomplete_json_is_rejected(monkeypatch, content: str) -> None:
    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepSeekError):
        asyncio.run(analyzer().classify("算法课", "问题", []))


def test_deepseek_quiz_requires_four_unique_options(monkeypatch) -> None:
    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"stem":"题目","options":[{"key":"A","content":"一"}],'
                                '"correct_option_key":"A","explanation":"解析"}'
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepSeekError):
        asyncio.run(analyzer().generate_quiz("算法课", "递归", ["为什么需要出口？"]))
