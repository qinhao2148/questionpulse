from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClusterCandidate(BaseModel):
    id: str
    title: str
    representative_questions: list[str] = Field(default_factory=list, max_length=5)


class SemanticDecision(BaseModel):
    decision: Literal["join_existing", "create_new"]
    cluster_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    normalized_intent: str = Field(min_length=1, max_length=240)
    suggested_title: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_cluster_for_join(self):
        if self.decision == "join_existing" and not self.cluster_id:
            raise ValueError("cluster_id is required when joining an existing cluster")
        return self


class QuizOptionDraft(BaseModel):
    key: Literal["A", "B", "C", "D"]
    content: str = Field(min_length=1, max_length=300)


class QuizDraft(BaseModel):
    stem: str = Field(min_length=1, max_length=500)
    options: list[QuizOptionDraft] = Field(min_length=4, max_length=4)
    correct_option_key: Literal["A", "B", "C", "D"]
    explanation: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_options(self):
        keys = [option.key for option in self.options]
        if len(set(keys)) != 4 or self.correct_option_key not in keys:
            raise ValueError("quiz options must contain unique A-D keys")
        return self


class ChatQuestionDecision(BaseModel):
    is_question: bool
    confidence: float = Field(ge=0, le=1)
    question_type: str = Field(min_length=1, max_length=40)
    normalized_intent: str = Field(min_length=1, max_length=240)
    suggested_question: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
