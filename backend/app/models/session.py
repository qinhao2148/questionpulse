import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClassroomSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="demo")
    integration_status: Mapped[str] = mapped_column(String(32), default="not_configured")
    teacher_token_hash: Mapped[str | None] = mapped_column(String(64))
    join_code: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    polyv_channel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    polyv_session_id: Mapped[str | None] = mapped_column(String(100), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    integration_error: Mapped[str | None] = mapped_column(String(200))
    degraded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
