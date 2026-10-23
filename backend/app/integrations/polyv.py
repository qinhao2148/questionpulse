import hashlib
import html
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.integrations.base import NormalizedQuestion


class PolyvNotConfiguredError(RuntimeError):
    pass


class PolyvApiError(RuntimeError):
    pass


def build_sign(params: dict[str, Any], app_secret: str) -> str:
    values = ((key, value) for key, value in params.items() if key != "sign" and value is not None)
    canonical = "".join(f"{key}{value}" for key, value in sorted(values))
    return hashlib.md5(f"{app_secret}{canonical}{app_secret}".encode()).hexdigest().upper()


class PolyvQuestionAdapter:
    qa_endpoint = "https://api.polyv.net/live/v4/chat/list-qa"
    legacy_ask_endpoint = "https://api.polyv.net/live/v2/chat/{channel_id}/getQuestion"
    chat_history_endpoint = "https://api.polyv.net/live/v3/channel/chat/get-history-page"

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = client
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    @staticmethod
    def normalize_event(payload: dict[str, Any]) -> NormalizedQuestion:
        occurred_at = payload.get("occurred_at") or payload.get("createdAt")
        timestamp = payload.get("createTime") or payload.get("timestamp") or payload.get("time")
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        elif timestamp is not None:
            occurred_at = datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC)
        return NormalizedQuestion(
            source=payload.get("source", "polyv_qa"),
            external_id=str(payload["id"]),
            viewer_key=str(
                payload.get("viewerId")
                or payload.get("s_userId")
                or (payload.get("user") or {}).get("userId")
                or f"polyv-anonymous-{payload['id']}"
            ),
            content=html.unescape(str(payload["content"])).replace("\u00a0", " ").strip(),
            occurred_at=occurred_at or datetime.now(UTC),
        )

    async def _signed_get(
        self, client: httpx.AsyncClient, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        signed_params = {"appId": self.app_id, **params, "timestamp": str(int(time.time() * 1000))}
        signed_params["sign"] = build_sign(signed_params, self.app_secret)
        try:
            response = await client.get(url, params=signed_params)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise PolyvApiError(
                f"POLYV HTTP status: {exc.response.status_code}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise PolyvApiError(f"POLYV transport failed: {type(exc).__name__}") from exc
        if body.get("code") != 200 or body.get("status") == "error":
            error = body.get("error") or {}
            raise PolyvApiError(
                f"POLYV API rejected request: {error.get('code', body.get('code', 'unknown'))}"
            )
        return body

    async def fetch_questions(
        self, channel_id: str, *, page_number: int = 1, page_size: int = 100
    ) -> list[NormalizedQuestion]:
        if not self.configured:
            raise PolyvNotConfiguredError("POLYV credentials are not configured")
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        qa_body: dict[str, Any] = {}
        ask_body: dict[str, Any] = {}
        failures = []
        try:
            try:
                qa_body = await self._signed_get(
                    client,
                    self.qa_endpoint,
                    {
                        "channelId": channel_id,
                        "pageNumber": page_number,
                        "pageSize": page_size,
                    },
                )
            except PolyvApiError as exc:
                failures.append(f"qa={exc}")
            try:
                ask_body = await self._signed_get(
                    client,
                    self.legacy_ask_endpoint.format(channel_id=channel_id),
                    {"begin": 0, "end": -1},
                )
            except PolyvApiError as exc:
                failures.append(f"legacy={exc}")
        finally:
            if owns_client:
                await client.aclose()
        if not qa_body and not ask_body:
            raise PolyvApiError("POLYV question sources unavailable: " + "; ".join(failures))

        qa_contents = (qa_body.get("data") or {}).get("contents") or []
        ask_data = ask_body.get("data") or []
        ask_contents = ask_data if isinstance(ask_data, list) else []
        normalized = [
            self.normalize_event({**item, "source": "polyv_qa"})
            for item in qa_contents
            if item.get("content")
        ]
        normalized.extend(
            self.normalize_event({**item, "source": "polyv_ask"})
            for item in ask_contents
            if item.get("content") and item.get("event") == "S_QUESTION"
        )
        return normalized

    async def fetch_chat_messages(
        self,
        channel_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        page_size: int = 1000,
        max_pages: int = 5,
    ) -> list[NormalizedQuestion]:
        """Fetch public, text-only learner messages for server-side reconciliation."""
        if not self.configured:
            raise PolyvNotConfiguredError("POLYV credentials are not configured")
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        messages: list[NormalizedQuestion] = []
        try:
            for page in range(1, max_pages + 1):
                body = await self._signed_get(
                    client,
                    self.chat_history_endpoint,
                    {
                        "channelId": channel_id,
                        "startDay": start_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "endDay": end_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "page": page,
                        "pageSize": page_size,
                        "userType": "slice,viewer,attendee,student",
                        "status": "pass",
                        "hasTotal": "N",
                    },
                )
                contents = (body.get("data") or {}).get("contents") or []
                messages.extend(
                    self.normalize_event({**item, "source": "polyv_chat"})
                    for item in contents
                    if item.get("content")
                    and not item.get("msgType")
                    and item.get("sourceType", "public") == "public"
                )
                if len(contents) < page_size:
                    break
        finally:
            if owns_client:
                await client.aclose()
        return messages
