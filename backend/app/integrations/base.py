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
    # POLYV's own live session id. One channel can host many sessions over time,
    # so this is what keeps two overlapping classrooms from sharing messages.
    polyv_session_id: str | None = None


class QuestionSourceAdapter(Protocol):
    async def fetch_questions(self, session_id: str) -> list[NormalizedQuestion]: ...
