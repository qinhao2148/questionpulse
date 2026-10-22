from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class JoinRequest(BaseModel):
    viewer_key: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)
    join_code: str | None = Field(default=None, min_length=4, max_length=20)


class QuestionCreate(BaseModel):
    participant_id: str
    client_request_id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=500)


class PolyvQuestionEvent(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    viewer_key: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=500)
    occurred_at: datetime
    source: Literal["polyv_qa", "polyv_chat"] = "polyv_qa"


class PolyvEventBatch(BaseModel):
    environment: Literal["contract_test"]
    channel_id: str = Field(min_length=1, max_length=64)
    polyv_session_id: str = Field(min_length=1, max_length=100)
    events: list[PolyvQuestionEvent] = Field(min_length=1, max_length=100)


class IntegrationDrill(BaseModel):
    environment: Literal["contract_test"]
    action: Literal["degrade", "recover"]
    reason: str | None = Field(default=None, max_length=200)


class PolyvSyncRequest(BaseModel):
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)
    polyv_session_id: str | None = Field(default=None, min_length=1, max_length=100)


class DetachRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)


class StatusUpdate(BaseModel):
    status: Literal["open", "addressing", "awaiting_feedback", "closed"]
    expected_version: int = Field(ge=1)


class FeedbackUpdate(BaseModel):
    participant_id: str
    round: int = Field(ge=1)
    result: Literal["understood", "still_confused"]


class CheckAnswer(BaseModel):
    participant_id: str
    option_key: Literal["A", "B", "C", "D"]


class CheckOptionView(BaseModel):
    key: str
    content: str


class CheckQuestionView(BaseModel):
    id: str
    cluster_id: str
    feedback_round: int
    status: str
    stem: str
    options: list[CheckOptionView]
    source: str
    explanation: str | None = None
    correct_option_key: str | None = None
    target_count: int = 0
    response_count: int = 0
    correct_count: int = 0
    my_option_key: str | None = None
    my_is_correct: bool | None = None


class FeedbackSummary(BaseModel):
    round: int
    targets: int
    responses: int
    understood: int
    still_confused: int
    my_result: str | None = None


class ConfusionBreakdown(BaseModel):
    participant_ratio: float
    recent_activity: float
    wait_pressure: float
    still_confused_ratio: float
    check_error_ratio: float


class QuestionView(BaseModel):
    id: str
    participant_id: str
    content: str
    source: str
    external_id: str | None
    occurred_at: datetime | None
    cluster_id: str | None
    processing_status: str
    assignment_method: str | None
    similarity: float | None
    embedding_model: str | None
    created_at: datetime


class ClusterView(BaseModel):
    id: str
    title: str
    status: str
    version: int
    feedback_round: int
    feedback: FeedbackSummary
    participant_count: int
    question_count: int
    confusion_score: float
    confusion_level: Literal["low", "medium", "high"]
    confusion_breakdown: ConfusionBreakdown
    questions: list[QuestionView]


class Snapshot(BaseModel):
    id: str
    title: str
    status: str
    mode: str
    integration_status: str
    polyv_channel_id: str | None
    polyv_session_id: str | None
    last_synced_at: datetime | None
    integration_error: str | None
    degraded_at: datetime | None
    clusters: list[ClusterView]
    pending_questions: list[QuestionView]


class ReportCluster(BaseModel):
    id: str
    title: str
    status: str
    participant_count: int
    question_count: int
    feedback: FeedbackSummary
    questions: list[QuestionView]


class ReportTimelineEvent(BaseModel):
    kind: str
    cluster_id: str | None
    cluster_title: str | None
    detail: str
    occurred_at: datetime


class ReportAIInsight(BaseModel):
    cluster_id: str
    cluster_title: str
    normalized_intent: str
    semantic_reason: str
    recommendation: str
    model: str


class SessionReport(BaseModel):
    id: str
    title: str
    status: str
    ended_at: datetime | None
    generated_at: datetime
    question_count: int
    participant_count: int
    cluster_count: int
    status_counts: dict[str, int]
    feedback_targets: int
    feedback_responses: int
    feedback_coverage: float
    understood: int
    still_confused: int
    check_targets: int
    check_responses: int
    check_correct: int
    check_accuracy: float
    clusters: list[ReportCluster]
    follow_ups: list[ReportCluster]
    timeline: list[ReportTimelineEvent]
    ai_insights: list[ReportAIInsight]
