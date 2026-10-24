"""Knowledge base tests: parser/chunker units, the upload -> ingest -> search
loop (hash embedder + in-memory vector store), snapshot freezing and the RAG
answer review flow. No network calls: llm_api_key is empty and the embedding
provider is forced to the deterministic hash embedder."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import teacher_portal_token
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.knowledge.chunker import approx_token_count, build_chunks
from app.knowledge.embeddings import HashEmbeddingProvider
from app.knowledge.parser import ParsedSection, parse_file
from app.knowledge.vector_store import InMemoryVectorStore, UpsertPoint, new_point_id
from app.main import app
from app.models.knowledge import (
    RagAnswer,
)

HANDBOOK_MD = """# 员工手册

## 年假制度

试用期员工同样享有年假。申请年假应至少提前两个工作日提交，由直属主管审批。

年假未休完的部分可以顺延到次年第一季度。

## 差旅报销

差旅报销需在出差结束后十五天内提交发票，逾期不予受理。
"""


def teacher_headers() -> dict[str, str]:
    settings = get_settings()
    token = teacher_portal_token(settings.teacher_username, settings.teacher_portal_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def knowledge_env(tmp_path, monkeypatch):
    """Dedicated sqlite file DB shared by async (API) and sync (ingestion)."""
    db_path = tmp_path / "knowledge-test.db"
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    import asyncio

    async def _create():
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    sync_engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    sync_factory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    import app.api.routes.knowledge as knowledge_routes
    import app.db.session as db_session
    import app.knowledge.answering as answering
    import app.knowledge.ingestion as ingestion
    import app.knowledge.retrieval as retrieval

    safe_settings = get_settings().model_copy(
        update={
            "llm_api_key": "",
            "embedding_provider": "hash",
            # The hash embedder is a low-similarity degraded mode; keep the
            # threshold low so the flow test exercises retrieval end to end.
            "rag_min_score": 0.05,
            "knowledge_storage_path": str(tmp_path / "storage"),
        }
    )
    for module in (knowledge_routes, answering, retrieval, ingestion):
        monkeypatch.setattr(module, "get_settings", lambda: safe_settings)
    monkeypatch.setattr(db_session, "sync_session_factory", sync_factory)

    from app.knowledge import vector_store as vector_store_module
    from app.knowledge.vector_store import VectorStoreHolder

    memory_store = InMemoryVectorStore()
    # One shared in-memory store for every code path (routes, retrieval,
    # ingestion): replace the module singleton and the cached holder.
    monkeypatch.setattr(
        vector_store_module,
        "_holder",
        VectorStoreHolder(store=memory_store, kind="memory"),
    )
    monkeypatch.setattr(
        vector_store_module, "get_vector_store", lambda settings, dimensions: memory_store
    )
    monkeypatch.setattr(ingestion, "get_vector_store", lambda settings, dimensions: memory_store)
    monkeypatch.setattr(retrieval, "get_vector_store", lambda settings, dimensions: memory_store)
    monkeypatch.setattr(
        knowledge_routes, "_vector_store", lambda dimensions: memory_store, raising=True
    )

    yield {"factory": factory, "sync_factory": sync_factory, "store": memory_store}
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client(knowledge_env) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------- unit tests


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    provider = HashEmbeddingProvider()
    first = provider.embed_query("试用期员工可以请年假吗")
    second = provider.embed_query("试用期员工可以请年假吗")
    assert first == second
    assert len(first) == provider.dimensions
    assert abs(sum(value * value for value in first) - 1.0) < 1e-6


def test_build_chunks_keeps_section_context_and_stable_keys() -> None:
    sections = [
        ParsedSection(title_path=["员工手册", "年假制度"], text="内容一", page_start=3),
        ParsedSection(title_path=["员工手册", "年假制度"], text="内容二", page_start=4),
    ]
    chunks = build_chunks("hr-handbook", "员工手册", sections)
    assert len(chunks) == 2
    assert chunks[0].logical_chunk_key != chunks[1].logical_chunk_key
    assert chunks[0].logical_chunk_key.startswith("hr-handbook/")
    assert "文档：员工手册" in chunks[0].content
    assert "章节：员工手册/年假制度" in chunks[0].content
    assert chunks[0].page_start == 3
    assert chunks[0].content_sha256 != chunks[1].content_sha256


def test_approx_token_count_counts_cjk_as_single_tokens() -> None:
    assert approx_token_count("年假申请") >= 4
    assert approx_token_count("abcd") >= 1


def test_markdown_parser_builds_heading_paths(tmp_path) -> None:
    path = tmp_path / "handbook.md"
    path.write_text(HANDBOOK_MD, encoding="utf-8")
    parsed = parse_file(path)
    assert parsed.title == "员工手册"
    paths = ["/".join(section.title_path) for section in parsed.sections]
    assert "员工手册/年假制度" in paths
    assert "员工手册/差旅报销" in paths


def test_memory_vector_store_filters_by_version_and_organization() -> None:
    store = InMemoryVectorStore()
    provider = HashEmbeddingProvider()
    vector = provider.embed_query("年假")
    store.upsert(
        [
            UpsertPoint(
                point_id=new_point_id("v1", 0, "hash"),
                vector=vector,
                payload={
                    "organization_id": "org-default",
                    "document_version_id": "v1",
                    "status": "ready",
                    "content": "年假制度",
                },
            ),
            UpsertPoint(
                point_id=new_point_id("v1", 1, "hash"),
                vector=vector,
                payload={
                    "organization_id": "org-other",
                    "document_version_id": "v1",
                    "status": "ready",
                    "content": "别的企业",
                },
            ),
            UpsertPoint(
                point_id=new_point_id("v1", 2, "hash"),
                vector=vector,
                payload={
                    "organization_id": "org-default",
                    "document_version_id": "v2",
                    "status": "ready",
                    "content": "别的版本",
                },
            ),
        ]
    )
    hits = store.search(vector, ["v1"], "org-default", limit=10)
    assert len(hits) == 1
    assert hits[0].payload["content"] == "年假制度"


# ---------------------------------------------------------------- API flow


def test_upload_ingest_search_snapshot_and_publish_flow(client, knowledge_env) -> None:
    # 1. Create a knowledge base.
    created = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "入职培训"},
        headers=teacher_headers(),
    )
    assert created.status_code == 201
    kb_id = created.json()["data"]["id"]

    # 2. Upload a markdown handbook; the inline background job ingests it.
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        data={"title": "员工手册", "document_key": "handbook", "tags": "hr,2026"},
        files={"file": ("handbook.md", HANDBOOK_MD.encode("utf-8"), "text/markdown")},
        headers=teacher_headers(),
    )
    assert upload.status_code == 202, upload.text
    version_id = upload.json()["data"]["version_id"]

    documents = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/documents", headers=teacher_headers()
    ).json()["data"]
    assert documents[0]["current_version"]["status"] == "ready"
    assert documents[0]["current_version"]["chunk_count"] >= 2

    # 3. Retrieval preview finds the annual-leave section.
    preview = client.post(
        "/api/v1/knowledge/search-preview",
        json={"query": "试用期怎么申请年假", "knowledge_base_ids": [kb_id]},
        headers=teacher_headers(),
    ).json()["data"]
    assert preview["results"], "expected at least one retrieval hit"
    assert "年假" in preview["results"][0]["content"]

    # 4. Bind the whole knowledge base to a fresh classroom.
    classroom = client.post(
        "/api/v1/sessions", json={"title": "入职培训第一课"}, headers=teacher_headers()
    ).json()["data"]
    session_id = classroom["id"]
    bound = client.put(
        f"/api/v1/sessions/{session_id}/knowledge/bindings",
        json={
            "bindings": [
                {"knowledge_base_id": kb_id, "binding_scope": "whole_knowledge_base"}
            ]
        },
        headers=teacher_headers(),
    )
    assert bound.status_code == 200, bound.text

    snapshot = client.get(
        f"/api/v1/sessions/{session_id}/knowledge", headers=teacher_headers()
    ).json()["data"]
    assert len(snapshot["bindings"]) == 1
    assert len(snapshot["snapshot_documents"]) == 1
    assert snapshot["snapshot_documents"][0]["document_version_id"] == version_id
    assert snapshot["frozen_at"] is None

    # 5. First real retrieval freezes the snapshot; edits are then rejected.
    import asyncio

    async def _freeze():
        from app.knowledge.retrieval import search_classroom_knowledge

        async with knowledge_env["factory"]() as db:
            retrieved = await search_classroom_knowledge(db, session_id, "年假怎么申请")
            return retrieved

    retrieved = asyncio.run(_freeze())
    assert retrieved, "classroom-scoped retrieval should hit the bound handbook"
    assert all("年假" in chunk.content or "报销" in chunk.content for chunk in retrieved)

    frozen = client.get(
        f"/api/v1/sessions/{session_id}/knowledge", headers=teacher_headers()
    ).json()["data"]
    assert frozen["frozen_at"] is not None

    conflict = client.put(
        f"/api/v1/sessions/{session_id}/knowledge/bindings",
        json={
            "bindings": [
                {"knowledge_base_id": kb_id, "binding_scope": "whole_knowledge_base"}
            ]
        },
        headers=teacher_headers(),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "knowledge_snapshot_frozen"

    # 6. A student joins and asks; teacher reviews the AI-drafted answer.
    student = client.post(
        f"/api/v1/sessions/{session_id}/join",
        json={
            "viewer_key": "vk-1",
            "display_name": "学员一",
            "join_code": classroom["join_code"],
        },
    ).json()["data"]
    answer_id = "rag-test-1"
    question_id = "q-test-1"

    async def _seed_answer():
        from app.models.classroom import Question
        from app.models.knowledge import KnowledgeChunk, RagCitation

        async with knowledge_env["factory"]() as db:
            db.add(
                KnowledgeChunk(
                    id="chunk-seed-1",
                    document_version_id=version_id,
                    logical_chunk_key="handbook/seed",
                    chunk_index=99,
                    section_path="员工手册/年假制度",
                    page_start=1,
                    content="试用期员工同样享有年假。",
                    content_sha256="seed-hash",
                )
            )
            db.add(
                Question(
                    id=question_id,
                    session_id=session_id,
                    participant_id=student["participant_id"],
                    content="试用期员工可以请年假吗？",
                    normalized_content="试用期员工可以请年假吗",
                )
            )
            db.add(
                RagAnswer(
                    id=answer_id,
                    session_id=session_id,
                    question_id=question_id,
                    answer="根据《员工手册》，试用期员工同样享有年假。",
                    confidence=0.9,
                    answer_status="draft",
                )
            )
            db.add(
                RagCitation(
                    rag_answer_id=answer_id,
                    chunk_id="chunk-seed-1",
                    document_version_id=version_id,
                    citation_order=1,
                    retrieval_score=0.8,
                )
            )
            await db.commit()

    asyncio.run(_seed_answer())

    approved = client.post(
        f"/api/v1/sessions/{session_id}/rag-answers/{answer_id}/action",
        json={"action": "approve"},
        headers=teacher_headers(),
    )
    assert approved.status_code == 200

    published = client.post(
        f"/api/v1/sessions/{session_id}/rag-answers/{answer_id}/action",
        json={"action": "publish"},
        headers=teacher_headers(),
    )
    assert published.status_code == 200

    # 7. The published answer is visible through the student endpoints.
    results = client.get(f"/api/v1/sessions/{session_id}/student/knowledge-results")
    assert results.status_code == 403  # no student token: isolated by design

    results = client.get(
        f"/api/v1/sessions/{session_id}/student/knowledge-results",
        headers={"Authorization": f"Bearer {student['access_token']}"},
    ).json()["data"]
    assert len(results) == 1
    assert results[0]["question_id"] == question_id
    assert "年假" in results[0]["answer"]

    student_snapshot = client.get(
        f"/api/v1/sessions/{session_id}/student-snapshot",
        headers={"Authorization": f"Bearer {student['access_token']}"},
    ).json()
    published_answers = student_snapshot["published_answers"]
    assert len(published_answers) == 1
    assert published_answers[0]["answer_id"] == answer_id

    # 8. Version archive is refused while a frozen snapshot references it.
    archived = client.post(
        f"/api/v1/knowledge-document-versions/{version_id}/archive",
        headers=teacher_headers(),
    )
    assert archived.status_code == 409
    assert archived.json()["detail"] == "version_referenced_by_snapshots"


def test_upload_rejects_unsupported_format(client) -> None:
    created = client.post(
        "/api/v1/knowledge-bases", json={"name": "格式校验"}, headers=teacher_headers()
    ).json()["data"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{created['id']}/documents",
        data={"title": "可执行文件"},
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        headers=teacher_headers(),
    )
    assert upload.status_code == 415
    assert upload.json()["detail"].startswith("unsupported_format")


def test_knowledge_endpoints_require_teacher_token(client) -> None:
    assert client.get("/api/v1/knowledge-bases").status_code == 403
    assert client.post("/api/v1/knowledge-bases", json={"name": "x"}).status_code == 403
    assert client.post(
        "/api/v1/knowledge/search-preview", json={"query": "q"}
    ).status_code == 403


POLICY_V1 = """# 请假制度

## 年假

正式员工每年享有五天带薪年假，需要提前两个工作日申请。
"""

POLICY_V2 = """# 请假制度

## 年假

正式员工每年享有十天带薪年假，需要提前三个工作日申请。

## 探亲假

异地任职员工每年可申请一次探亲假，路程假另计。
"""


def _upload(client, kb_id: str, name: str, key: str, content: str):
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        data={"title": name, "document_key": key},
        files={"file": (f"{key}.md", content.encode("utf-8"), "text/markdown")},
        headers=teacher_headers(),
    )
    assert upload.status_code == 202, upload.text
    return upload.json()["data"]


def test_version_replacement_reaches_new_classrooms_only(client, knowledge_env) -> None:
    """v1 replaced by v2: new classrooms and preview use v2 exclusively, while
    a classroom already frozen on v1 keeps retrieving v1."""
    import asyncio

    kb_id = client.post(
        "/api/v1/knowledge-bases", json={"name": "制度库"}, headers=teacher_headers()
    ).json()["data"]["id"]
    v1 = _upload(client, kb_id, "请假制度", "leave-policy", POLICY_V1)
    assert v1["status"] is not None

    # First classroom binds and freezes on v1.
    classroom_v1 = client.post(
        "/api/v1/sessions", json={"title": "旧制度课堂"}, headers=teacher_headers()
    ).json()["data"]
    client.put(
        f"/api/v1/sessions/{classroom_v1['id']}/knowledge/bindings",
        json={"bindings": [{"knowledge_base_id": kb_id, "binding_scope": "whole_knowledge_base"}]},
        headers=teacher_headers(),
    )

    async def _freeze_and_retrieve():
        from app.knowledge.retrieval import search_classroom_knowledge

        async with knowledge_env["factory"]() as db:
            return await search_classroom_knowledge(db, classroom_v1["id"], "年假几天")

    frozen_hits = asyncio.run(_freeze_and_retrieve())
    assert frozen_hits
    assert all(hit.document_version_id == v1["version_id"] for hit in frozen_hits)

    # Upload v2 with different policy content.
    v2 = _upload(client, kb_id, "请假制度", "leave-policy", POLICY_V2)

    # Frozen classroom still resolves to v1 only.
    still_frozen = asyncio.run(_freeze_and_retrieve())
    assert all(hit.document_version_id == v1["version_id"] for hit in still_frozen)

    # Search preview (what a NEW classroom would see) uses v2 only.
    preview = client.post(
        "/api/v1/knowledge/search-preview",
        json={"query": "探亲假怎么申请", "knowledge_base_ids": [kb_id]},
        headers=teacher_headers(),
    ).json()["data"]
    assert preview["results"], "v2-only content must be retrievable"
    assert all(hit["version_number"] == 2 for hit in preview["results"])

    # New binding snapshot resolves to v2 only.
    classroom_v2 = client.post(
        "/api/v1/sessions", json={"title": "新制度课堂"}, headers=teacher_headers()
    ).json()["data"]
    client.put(
        f"/api/v1/sessions/{classroom_v2['id']}/knowledge/bindings",
        json={"bindings": [{"knowledge_base_id": kb_id, "binding_scope": "whole_knowledge_base"}]},
        headers=teacher_headers(),
    )
    new_snapshot = client.get(
        f"/api/v1/sessions/{classroom_v2['id']}/knowledge", headers=teacher_headers()
    ).json()["data"]
    assert [doc["document_version_id"] for doc in new_snapshot["snapshot_documents"]] == [
        v2["version_id"]
    ]


def test_frozen_snapshot_unaffected_by_follow_latest_flag(client, knowledge_env) -> None:
    """follow_latest is removed from the product: the flag must never let a
    frozen snapshot silently switch versions."""
    kb_id = client.post(
        "/api/v1/knowledge-bases", json={"name": "跟随测试"}, headers=teacher_headers()
    ).json()["data"]["id"]
    _upload(client, kb_id, "手册", "manual", POLICY_V1)

    classroom = client.post(
        "/api/v1/sessions", json={"title": "冻结课堂"}, headers=teacher_headers()
    ).json()["data"]
    client.put(
        f"/api/v1/sessions/{classroom['id']}/knowledge/bindings",
        json={
            "bindings": [
                {
                    "knowledge_base_id": kb_id,
                    "binding_scope": "whole_knowledge_base",
                    "follow_latest": True,
                }
            ]
        },
        headers=teacher_headers(),
    )
    bindings = client.get(
        f"/api/v1/sessions/{classroom['id']}/knowledge", headers=teacher_headers()
    ).json()["data"]["bindings"]
    assert bindings and bindings[0]["follow_latest"] is False


def test_publish_blocked_without_citations(client, knowledge_env) -> None:
    import asyncio

    classroom = client.post(
        "/api/v1/sessions", json={"title": "无引用课堂"}, headers=teacher_headers()
    ).json()["data"]
    answer_id = "rag-no-cite"

    async def _seed():
        from app.models.classroom import Participant, Question
        from app.models.knowledge import RagAnswer

        async with knowledge_env["factory"]() as db:
            db.add(
                Participant(
                    session_id=classroom["id"], viewer_key="vk-nc", display_name="学员"
                )
            )
            db.add(
                Question(
                    id="q-no-cite",
                    session_id=classroom["id"],
                    participant_id="placeholder",
                    content="测试问题",
                    normalized_content="测试问题",
                )
            )
            db.add(
                RagAnswer(
                    id=answer_id,
                    session_id=classroom["id"],
                    question_id="q-no-cite",
                    answer="看起来合理的答案，但没有任何引用。",
                    confidence=0.9,
                    answer_status="draft",
                )
            )
            await db.commit()

    asyncio.run(_seed())
    blocked = client.post(
        f"/api/v1/sessions/{classroom['id']}/rag-answers/{answer_id}/action",
        json={"action": "publish"},
        headers=teacher_headers(),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "rag_answer_has_no_citations"


def test_retry_document_version_endpoint_requeues(client, knowledge_env) -> None:
    import asyncio

    kb_id = client.post(
        "/api/v1/knowledge-bases", json={"name": "重试测试"}, headers=teacher_headers()
    ).json()["data"]["id"]
    upload = _upload(client, kb_id, "手册", "retry-manual", POLICY_V1)

    async def _break_version():
        from sqlalchemy import select

        from app.models.knowledge import KnowledgeDocumentVersion, KnowledgeIngestionJob

        async with knowledge_env["factory"]() as db:
            version = await db.get(KnowledgeDocumentVersion, upload["version_id"])
            version.status = "failed"
            version.error_code = "simulated"
            job = (
                await db.execute(
                    select(KnowledgeIngestionJob).where(
                        KnowledgeIngestionJob.document_version_id == upload["version_id"]
                    )
                )
            ).scalars().first()
            job.status = "failed"
            await db.commit()

    asyncio.run(_break_version())

    retried = client.post(
        f"/api/v1/knowledge-document-versions/{upload['version_id']}/retry",
        headers=teacher_headers(),
    )
    assert retried.status_code == 200, retried.text

    for _ in range(10):
        documents = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/documents", headers=teacher_headers()
        ).json()["data"]
        if documents[0]["current_version"]["status"] == "ready":
            break
        import time

        time.sleep(0.5)
    assert documents[0]["current_version"]["status"] == "ready"


    from app.knowledge.ingestion import claim_next_job
    from app.models.knowledge import KnowledgeIngestionJob

    async def _seed_stale():
        async with knowledge_env["factory"]() as db:
            db.add(
                KnowledgeIngestionJob(
                    id="stale-job-1",
                    status="running",
                    attempt_count=1,
                    locked_by="worker-dead",
                    locked_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=4000),
                )
            )
            await db.commit()

    asyncio.run(_seed_stale())

    # claim_next_job is sync: run it against the fixture's sync factory, which
    # shares the sqlite file with the async engine.
    with knowledge_env["sync_factory"]() as session:
        job = claim_next_job(session, worker_id="test-worker")
        assert job is not None
        assert job.id == "stale-job-1"
        assert job.status == "running"


def test_dead_after_max_attempts(knowledge_env) -> None:
    import asyncio

    from app.knowledge.ingestion import process_job
    from app.models.knowledge import KnowledgeDocumentVersion, KnowledgeIngestionJob

    async def _seed():
        async with knowledge_env["factory"]() as db:
            db.add(
                KnowledgeDocumentVersion(
                    id="dead-version-1",
                    document_id="no-such-document",
                    version_number=1,
                    original_file_name="x.md",
                    status="uploaded",
                )
            )
            db.add(
                KnowledgeIngestionJob(
                    id="dead-job-1",
                    document_version_id="dead-version-1",
                    job_type="ingest",
                    status="running",
                    attempt_count=3,
                    locked_by="worker-x",
                    locked_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await db.commit()

    asyncio.run(_seed())
    with knowledge_env["sync_factory"]() as session:
        status = process_job("dead-job-1", session)
    assert status == "failed"

    async def _check():
        async with knowledge_env["factory"]() as db:
            job = await db.get(KnowledgeIngestionJob, "dead-job-1")
            return job.status

    assert asyncio.run(_check()) == "dead"


def test_archive_old_version_keeps_other_versions_file(client, knowledge_env) -> None:
    kb_id = client.post(
        "/api/v1/knowledge-bases", json={"name": "归档测试"}, headers=teacher_headers()
    ).json()["data"]["id"]
    _upload(client, kb_id, "制度", "archive-doc", POLICY_V1)
    v2 = _upload(client, kb_id, "制度", "archive-doc", POLICY_V2)

    import asyncio

    from sqlalchemy import select

    from app.models.knowledge import KnowledgeDocumentVersion

    async def _load():
        async with knowledge_env["factory"]() as db:
            rows = await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == v2["document_id"]
                )
            )
            return {v.version_number: v for v in rows.scalars().all()}

    versions = asyncio.run(_load())
    v1_row, v2_row = versions[1], versions[2]
    assert v2_row.id == v2["version_id"]

    # v1 is no longer current and unreferenced: archiving it must not touch
    # the v2 file on disk.
    archived = client.post(
        f"/api/v1/knowledge-document-versions/{v1_row.id}/archive",
        headers=teacher_headers(),
    )
    assert archived.status_code == 200

    # The fixture patches get_settings per-module; use the routes module's one
    # so the path matches where ingestion actually wrote the file.
    from app.api.routes import knowledge as knowledge_routes
    from app.knowledge.ingestion import storage_root

    v2_path = storage_root(knowledge_routes.get_settings()) / v2_row.storage_key
    assert v2_path.is_file(), "archiving v1 must not delete the v2 file"


def test_qdrant_unavailable_fails_loudly(monkeypatch) -> None:
    """Without the test-only memory fallback, an unreachable Qdrant must raise
    instead of handing back a cross-process in-memory store."""
    from types import SimpleNamespace

    from app.knowledge import vector_store as vs

    vs.reset_vector_store()
    broken = SimpleNamespace(
        qdrant_url="http://127.0.0.1:59999",
        qdrant_collection="unreachable",
        qdrant_api_key="",
        qdrant_timeout_seconds=0.3,
        knowledge_allow_memory_vector_store=False,
    )
    with pytest.raises(vs.KnowledgeVectorError, match="qdrant_unavailable"):
        vs.get_vector_store(broken, dimensions=512)
    assert vs.vector_store_kind() == "unavailable"
    vs.reset_vector_store()


def test_published_answer_reaches_students_when_asker_is_chat_shadow(client, knowledge_env) -> None:
    """Questions promoted from the POLYV chat belong to shadow participants no
    student logs in as. Publishing the answer must still deliver it to every
    student client (classroom-wide publication)."""
    import asyncio

    classroom = client.post(
        "/api/v1/sessions", json={"title": "聊天来源课堂"}, headers=teacher_headers()
    ).json()["data"]

    async def _seed():
        from app.models.classroom import Participant, Question
        from app.models.knowledge import KnowledgeChunk, RagAnswer, RagCitation

        async with knowledge_env["factory"]() as db:
            # The asker is a POLYV chat shadow identity (no token, no client).
            db.add(
                Participant(
                    id="shadow-chat-1",
                    session_id=classroom["id"],
                    viewer_key="polyv-shadow",
                    display_name=None,
                    source="polyv",
                )
            )
            db.add(
                Question(
                    id="q-chat-src",
                    session_id=classroom["id"],
                    participant_id="shadow-chat-1",
                    content="中级工每月有多少技能津贴？",
                    normalized_content="中级工每月有多少技能津贴",
                    source="polyv_chat",
                )
            )
            db.add(
                KnowledgeChunk(
                    id="chunk-chat-1",
                    document_version_id="any-version",
                    logical_chunk_key="doc/key",
                    chunk_index=98,
                    content="中级工技能津贴 300 元/月",
                    content_sha256="chat-hash",
                )
            )
            db.add(
                RagAnswer(
                    id="rag-chat-1",
                    session_id=classroom["id"],
                    question_id="q-chat-src",
                    answer="根据培训课件，中级工技能津贴为每月 300 元。",
                    confidence=0.9,
                    answer_status="published",
                    published_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            db.add(
                RagCitation(
                    rag_answer_id="rag-chat-1",
                    chunk_id="chunk-chat-1",
                    document_version_id="any-version",
                    citation_order=1,
                    retrieval_score=0.8,
                )
            )
            await db.commit()

    asyncio.run(_seed())

    # A real student joins and must see the published answer in the snapshot.
    student = client.post(
        f"/api/v1/sessions/{classroom['id']}/join",
        json={
            "viewer_key": "vk-real",
            "display_name": "真实学员",
            "join_code": classroom["join_code"],
        },
    ).json()["data"]
    snapshot = client.get(
        f"/api/v1/sessions/{classroom['id']}/student-snapshot",
        headers={"Authorization": f"Bearer {student['access_token']}"},
    ).json()
    published = snapshot["published_answers"]
    assert len(published) == 1
    assert published[0]["question_id"] == "q-chat-src"
    assert "300" in published[0]["answer"]

    results = client.get(
        f"/api/v1/sessions/{classroom['id']}/student/knowledge-results",
        headers={"Authorization": f"Bearer {student['access_token']}"},
    ).json()["data"]
    assert len(results) == 1
    assert results[0]["question_content"] == "中级工每月有多少技能津贴？"


def test_rejection_reason_feeds_knowledge_gap_report(client, knowledge_env) -> None:
    """Rejecting an answer with a reason must surface it in the session report
    as a knowledge-gap item, so the teacher knows what to fix or add."""
    import asyncio

    classroom = client.post(
        "/api/v1/sessions", json={"title": "缺口报告课堂"}, headers=teacher_headers()
    ).json()["data"]
    answer_id = "rag-gap-1"

    async def _seed():
        from app.models.classroom import Participant, Question
        from app.models.knowledge import RagAnswer

        async with knowledge_env["factory"]() as db:
            db.add(
                Participant(
                    session_id=classroom["id"],
                    viewer_key="vk-gap",
                    display_name="学员",
                )
            )
            db.add(
                Question(
                    id="q-gap",
                    session_id=classroom["id"],
                    participant_id="placeholder",
                    content="公积金按什么比例缴纳？",
                    normalized_content="公积金按什么比例缴纳",
                )
            )
            db.add(
                RagAnswer(
                    id=answer_id,
                    session_id=classroom["id"],
                    question_id="q-gap",
                    answer="公积金比例为 12%。",
                    confidence=0.8,
                    answer_status="draft",
                )
            )
            await db.commit()

    asyncio.run(_seed())

    rejected = client.post(
        f"/api/v1/sessions/{classroom['id']}/rag-answers/{answer_id}/action",
        json={"action": "reject", "reason": "员工手册里没有公积金条款，需要补充资料"},
        headers=teacher_headers(),
    )
    assert rejected.status_code == 200

    async def _check():
        from app.models.knowledge import RagAnswer

        async with knowledge_env["factory"]() as db:
            answer = await db.get(RagAnswer, answer_id)
            return answer.answer_status, answer.reject_reason

    status, reason = asyncio.run(_check())
    assert status == "rejected"
    assert reason == "员工手册里没有公积金条款，需要补充资料"

    report = client.get(
        f"/api/v1/sessions/{classroom['id']}/report", headers=teacher_headers()
    ).json()
    gaps = report.get("knowledge_gaps", [])
    assert len(gaps) == 1
    assert gaps[0]["question"] == "公积金按什么比例缴纳？"
    assert gaps[0]["kind"] == "rejected"
    assert "公积金" in gaps[0]["reason"]
