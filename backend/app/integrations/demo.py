from datetime import UTC, datetime

from app.integrations.base import NormalizedQuestion


class DemoQuestionAdapter:
    def __init__(self, questions: list[tuple[str, str, str]]) -> None:
        self.questions = questions

    async def fetch_questions(self, session_id: str) -> list[NormalizedQuestion]:
        del session_id
        return [
            NormalizedQuestion(
                source="demo",
                external_id=external_id,
                viewer_key=viewer_key,
                content=content,
                occurred_at=datetime.now(UTC),
            )
            for external_id, viewer_key, content in self.questions
        ]
