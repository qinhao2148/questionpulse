import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("session_id", "viewer_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    viewer_key: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(String(100))
    access_token_hash: Mapped[str | None] = mapped_column(String(64))
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # student = 从学生端课堂码进入的人；polyv = 直播平台同步提问时派生的影子身份。
    # 报告里的“观看学生”只认前者，否则平台侧 viewer id 会把分母撑大。
    source: Mapped[str] = mapped_column(String(20), default="student")
    # 学生端每 3 秒拉一次快照，这里记录最后一次心跳，用来区分“加入了”和“真的在看”。
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class ParticipantToken(Base):
    """一个参与者可以同时持有多个有效令牌。

    同一浏览器开两个标签页时，两个页面各自加入都会签发新令牌。如果只在
    participants 上存一个 digest，后加入的会覆盖前一个，先打开的标签页
    立刻掉线。把令牌拆到独立表后，旧令牌在过期前依然可用。
    """

    __tablename__ = "participant_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(32), default="open")
    embedding_json: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    feedback_round: Mapped[int] = mapped_column(Integer, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("session_id", "source", "external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"), index=True)
    content: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(32), default="questionpulse")
    external_id: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    normalized_content: Mapped[str] = mapped_column(String(500))
    processing_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    assignment_method: Mapped[str | None] = mapped_column(String(50))
    similarity: Mapped[float | None] = mapped_column(Float)
    embedding_json: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("session_id", "participant_id", "client_request_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    client_request_id: Mapped[str] = mapped_column(String(80))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ClusterEvent(Base):
    __tablename__ = "cluster_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"))
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    is_automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FeedbackTarget(Base):
    __tablename__ = "feedback_targets"

    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), primary_key=True)
    round: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("cluster_id", "round", "participant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    result: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AIRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ai_run_id: Mapped[str] = mapped_column(ForeignKey("ai_runs.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    cluster_id: Mapped[str | None] = mapped_column(ForeignKey("clusters.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(500))
    normalized_intent: Mapped[str] = mapped_column(String(240))
    accepted_by: Mapped[str] = mapped_column(String(40), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CheckQuestion(Base):
    __tablename__ = "check_questions"
    __table_args__ = (UniqueConstraint("cluster_id", "feedback_round"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    feedback_round: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    stem: Mapped[str] = mapped_column(String(500))
    correct_option_key: Mapped[str] = mapped_column(String(1))
    explanation: Mapped[str] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(40), default="deepseek")
    # True when the quiz was generated over retrieved classroom knowledge
    # contexts; False means student questions only (knowledge gap signal).
    knowledge_backed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CheckOption(Base):
    __tablename__ = "check_options"
    __table_args__ = (UniqueConstraint("check_question_id", "option_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    check_question_id: Mapped[str] = mapped_column(
        ForeignKey("check_questions.id"), index=True
    )
    option_key: Mapped[str] = mapped_column(String(1))
    content: Mapped[str] = mapped_column(String(300))


class CheckTarget(Base):
    __tablename__ = "check_targets"

    check_question_id: Mapped[str] = mapped_column(
        ForeignKey("check_questions.id"), primary_key=True
    )
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), primary_key=True)


class CheckResponse(Base):
    __tablename__ = "check_responses"
    __table_args__ = (UniqueConstraint("check_question_id", "participant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    check_question_id: Mapped[str] = mapped_column(
        ForeignKey("check_questions.id"), index=True
    )
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), index=True)
    selected_option_key: Mapped[str] = mapped_column(String(1))
    is_correct: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    """A POLYV public chat message considered by the question detector."""

    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("session_id", "source", "external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="polyv_chat")
    external_id: Mapped[str] = mapped_column(String(100))
    polyv_session_id: Mapped[str | None] = mapped_column(String(100), index=True)
    content: Mapped[str] = mapped_column(String(500))
    normalized_content: Mapped[str] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    ingestion_method: Mapped[str] = mapped_column(String(32), default="sdk")
    official_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    promoted_question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChatClassification(Base):
    __tablename__ = "chat_classifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_message_id: Mapped[str] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True, index=True
    )
    ai_run_id: Mapped[str | None] = mapped_column(ForeignKey("ai_runs.id"), index=True)
    is_question: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    question_type: Mapped[str] = mapped_column(String(40))
    normalized_intent: Mapped[str] = mapped_column(String(240))
    suggested_question: Mapped[str | None] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(String(500))
    decision: Mapped[str] = mapped_column(String(40))
    decided_by: Mapped[str] = mapped_column(String(40), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
