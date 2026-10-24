"""RAG answer drafting orchestration.

Runs after a question has been clustered (or promoted from chat), as a
background task: retrieval + LLM answer generation take seconds and must not
block the student's HTTP request. Failures persist a 'failed' RagAnswer row so
the teacher sees a visible degraded state instead of silence.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.knowledge.retrieval import (
    citation_summaries,
    generate_rag_answer,
    search_classroom_knowledge,
)
from app.models.classroom import Question
from app.models.knowledge import RagAnswer, RagCitation
from app.models.session import ClassroomSession

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def draft_answer_for_question(db: AsyncSession, session_id: str, question_id: str) -> None:
    settings = get_settings()
    classroom = await db.get(ClassroomSession, session_id)
    question = await db.get(Question, question_id)
    if classroom is None or question is None:
        return

    # One live draft per question: a newer attempt replaces the old draft.
    existing = (
        await db.execute(
            select(RagAnswer)
            .where(
                RagAnswer.question_id == question_id,
                RagAnswer.answer_status.in_(["draft", "approved", "published"]),
            )
            .order_by(RagAnswer.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if existing is not None and existing.answer_status in ("approved", "published"):
        return
    if existing is not None:
        await db.delete(existing)
        await db.commit()
    question_cluster_id = question.cluster_id

    # Retrieval and generation happen BEFORE any answer row exists: the
    # snapshot freeze inside retrieval commits this session, and a row flushed
    # early would leak out as an empty draft every teacher poll would see.
    try:
        if not settings.llm_api_key:
            raise RuntimeError("deepseek_not_configured")
        retrieved = await search_classroom_knowledge(db, session_id, question.content)
        if not retrieved:
            rag_answer = RagAnswer(
                session_id=session_id,
                question_id=question_id,
                cluster_id=question.cluster_id,
                answer="本课堂未绑定知识资料或资料中没有相关内容。",
                confidence=0.0,
                insufficient_evidence=True,
                error_code="no_knowledge_bound",
                answer_status="draft",
            )
            db.add(rag_answer)
            await db.commit()
            return
        draft, usage = await generate_rag_answer(
            db,
            session_id,
            classroom.title,
            question.content,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            retrieved=retrieved,
        )
        rag_answer = RagAnswer(
            session_id=session_id,
            question_id=question_id,
            cluster_id=question.cluster_id,
            answer=draft.answer,
            confidence=draft.confidence,
            insufficient_evidence=draft.insufficient_evidence,
            answer_status="draft",
            model=settings.llm_model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        db.add(rag_answer)
        await db.flush()
        for order, citation in enumerate(await citation_summaries(db, retrieved, draft), start=1):
            db.add(
                RagCitation(
                    rag_answer_id=rag_answer.id,
                    chunk_id=citation["chunk_id"],
                    document_version_id=citation.get("document_version_id", ""),
                    citation_order=order,
                    retrieval_score=citation.get("score"),
                    quoted_text=(citation.get("content") or "")[:500],
                )
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - visible failure beats silence
        # question.cluster_id must be captured before the try: rollback expires
        # the ORM object and touching it here would raise in the handler.
        failed = RagAnswer(
            session_id=session_id,
            question_id=question_id,
            cluster_id=question_cluster_id,
            answer_status="failed",
            error_code=type(exc).__name__[:100],
        )
        db.add(failed)
        await db.commit()
        logger.exception("rag answer drafting failed for question %s", question_id)


async def draft_answers_in_background(bind, session_id: str, question_ids: list[str]) -> None:
    """Background entry mirroring classify_messages_in_background."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    if not question_ids or bind is None:
        return
    async with async_sessionmaker(bind, expire_on_commit=False)() as db:
        for question_id in question_ids:
            try:
                await draft_answer_for_question(db, session_id, question_id)
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("rag draft failed for %s", question_id)


async def queue_draft_if_knowledge_bound(
    background_tasks, db: AsyncSession, session_id: str, question_id: str
) -> bool:
    """Schedule RAG drafting only when the classroom has bound knowledge and
    an LLM key exists; returns whether a draft was queued."""
    from fastapi import BackgroundTasks  # noqa: F401 - typing only
    from sqlalchemy import select

    from app.models.knowledge import SessionKnowledgeBinding

    settings = get_settings()
    if not settings.llm_api_key:
        return False
    bound = await db.scalar(
        select(SessionKnowledgeBinding.id)
        .where(SessionKnowledgeBinding.session_id == session_id)
        .limit(1)
    )
    if bound is None:
        return False
    background_tasks.add_task(draft_answers_in_background, db.bind, session_id, [question_id])
    return True
