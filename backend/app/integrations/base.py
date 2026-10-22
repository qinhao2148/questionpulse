from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class NormalizedQuestion:
    source: str
    external_id: str
    viewer_key: str
    content: str
    occurred_at: datetime


class QuestionSourceAdapter(Protocol):
    async def fetch_questions(self, session_id: str) -> list[NormalizedQuestion]: ...
