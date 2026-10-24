"""Vector store abstraction over Qdrant with an in-process fallback.

``QdrantVectorStore`` talks to the local Qdrant container; every query filters
by the classroom's frozen document-version set plus organization, so cross-
classroom or cross-company leakage is impossible even if similarity is high.
``InMemoryVectorStore`` mirrors the same contract for tests and for running
without the Qdrant container (data lives only for the process lifetime).
"""

from __future__ import annotations

import logging
import threading
import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Protocol

from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)


class KnowledgeVectorError(Exception):
    pass


@dataclass
class UpsertPoint:
    point_id: str
    vector: list[float]
    payload: dict


@dataclass
class SearchHit:
    point_id: str
    score: float
    payload: dict


class VectorStore(Protocol):
    def ensure_collection(self, dimensions: int) -> None: ...

    def upsert(self, points: list[UpsertPoint]) -> None: ...

    def delete_by_version(self, document_version_id: str) -> int: ...

    def delete_points(self, point_ids: list[str]) -> None: ...

    def search(
        self,
        vector: list[float],
        document_version_ids: list[str],
        organization_id: str,
        limit: int,
    ) -> list[SearchHit]: ...

    def count_for_version(self, document_version_id: str) -> int: ...


_FILTERABLE_FIELDS = (
    "organization_id",
    "knowledge_base_id",
    "document_id",
    "document_version_id",
    "status",
)


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, api_key: str = "", timeout: float = 10.0) -> None:
        self.collection = collection
        self._client = QdrantClient(url=url, api_key=api_key or None, timeout=timeout)

    def ensure_collection(self, dimensions: int) -> None:
        if self._client.collection_exists(self.collection):
            info = self._client.get_collection(self.collection)
            vector_size = None
            cfg = info.config.params.vectors
            vector_size = getattr(cfg, "size", None)
            if vector_size is not None and vector_size != dimensions:
                raise KnowledgeVectorError(
                    f"qdrant_dimension_mismatch:{vector_size}!={dimensions}"
                )
            return
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=dimensions, distance=models.Distance.COSINE
            ),
        )
        # Payload indexes keep version/org filters fast as the corpus grows.
        for field_name in _FILTERABLE_FIELDS:
            self._client.create_payload_index(
                collection_name=self.collection,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    def upsert(self, points: list[UpsertPoint]) -> None:
        if not points:
            return
        self._client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id=point.point_id, vector=point.vector, payload=point.payload
                )
                for point in points
            ],
        )

    def delete_by_version(self, document_version_id: str) -> int:
        self._client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_version_id",
                            match=models.MatchValue(value=document_version_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        return 1

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        valid = []
        for point_id in point_ids:
            try:
                valid.append(uuid_module.UUID(str(point_id)))
            except ValueError:
                continue
        if valid:
            self._client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=valid),
                wait=True,
            )

    def search(
        self,
        vector: list[float],
        document_version_ids: list[str],
        organization_id: str,
        limit: int,
    ) -> list[SearchHit]:
        if not document_version_ids:
            return []
        result = self._client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="organization_id",
                        match=models.MatchValue(value=organization_id),
                    ),
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchAny(any=document_version_ids),
                    ),
                    models.FieldCondition(
                        key="status",
                        match=models.MatchValue(value="ready"),
                    ),
                ]
            ),
            with_payload=True,
        )
        return [
            SearchHit(point_id=str(point.id), score=point.score, payload=dict(point.payload or {}))
            for point in result.points
        ]

    def count_for_version(self, document_version_id: str) -> int:
        result = self._client.count(
            collection_name=self.collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchValue(value=document_version_id),
                    )
                ]
            ),
            exact=True,
        )
        return result.count


class InMemoryVectorStore:
    """Process-local store for tests and Qdrant-less degraded operation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._points: dict[str, tuple[list[float], dict]] = {}

    def ensure_collection(self, dimensions: int) -> None:
        return None

    def upsert(self, points: list[UpsertPoint]) -> None:
        with self._lock:
            for point in points:
                self._points[point.point_id] = (point.vector, point.payload)

    def delete_by_version(self, document_version_id: str) -> int:
        with self._lock:
            doomed = [
                pid
                for pid, (_, payload) in self._points.items()
                if payload.get("document_version_id") == document_version_id
            ]
            for pid in doomed:
                del self._points[pid]
            return len(doomed)

    def delete_points(self, point_ids: list[str]) -> None:
        with self._lock:
            for pid in point_ids:
                self._points.pop(pid, None)

    def search(
        self,
        vector: list[float],
        document_version_ids: list[str],
        organization_id: str,
        limit: int,
    ) -> list[SearchHit]:
        allowed = set(document_version_ids)
        hits: list[SearchHit] = []
        with self._lock:
            for point_id, (candidate, payload) in self._points.items():
                if payload.get("organization_id") != organization_id:
                    continue
                if payload.get("document_version_id") not in allowed:
                    continue
                if payload.get("status") != "ready":
                    continue
                score = sum(a * b for a, b in zip(vector, candidate, strict=False))
                hits.append(SearchHit(point_id=point_id, score=score, payload=payload))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def count_for_version(self, document_version_id: str) -> int:
        with self._lock:
            return sum(
                1
                for _, payload in self._points.values()
                if payload.get("document_version_id") == document_version_id
            )


@dataclass
class VectorStoreHolder:
    """Lazily constructed singleton shared by API process and worker."""

    store: VectorStore | None = field(default=None)
    kind: str = "unavailable"
    error_code: str | None = None


_holder_lock = threading.Lock()
_holder = VectorStoreHolder()


def get_vector_store(settings, dimensions: int) -> VectorStore:
    """Return the process-wide vector store, creating the collection lazily.

    ``dimensions`` must come from the actual embedding provider in use: the
    collection is created at that size, and a later provider with a different
    dimensionality raises instead of silently writing unusable vectors.

    Degradation policy: a cross-process in-memory store cannot work with the
    separate worker process (the worker writes where the API never reads), so
    it is only allowed when explicitly enabled for tests. Otherwise a Qdrant
    failure raises and ingestion marks the version failed instead of pretending
    it is ready.
    """
    global _holder
    with _holder_lock:
        if _holder.store is not None:
            # Re-assert dimensions: a provider change must not reuse the old
            # collection size silently.
            _holder.store.ensure_collection(dimensions)
            return _holder.store
        try:
            store: VectorStore = QdrantVectorStore(
                url=settings.qdrant_url,
                collection=settings.qdrant_collection,
                api_key=settings.qdrant_api_key,
                timeout=settings.qdrant_timeout_seconds,
            )
            store.ensure_collection(dimensions)
            _holder = VectorStoreHolder(store=store, kind="qdrant")
        except Exception as exc:  # noqa: BLE001
            if getattr(settings, "knowledge_allow_memory_vector_store", False):
                logger.warning(
                    "qdrant unavailable (%s: %s); using test-only in-process "
                    "vector store", type(exc).__name__, exc,
                )
                _holder = VectorStoreHolder(
                    store=InMemoryVectorStore(), kind="memory"
                )
                return _holder.store
            logger.error(
                "qdrant unavailable (%s: %s); knowledge ingestion and retrieval "
                "are unavailable until Qdrant is reachable",
                type(exc).__name__, exc,
            )
            _holder = VectorStoreHolder(kind="unavailable", error_code="qdrant_unavailable")
            raise KnowledgeVectorError("qdrant_unavailable") from exc
        return _holder.store


def vector_store_kind() -> str:
    return _holder.kind


def vector_store_error_code() -> str | None:
    return _holder.error_code


def reset_vector_store() -> None:
    """Test helper: drop the cached store so a new backend is constructed."""
    global _holder
    with _holder_lock:
        _holder = VectorStoreHolder()


def new_point_id(document_version_id: str, chunk_index: int, content_sha256: str) -> str:
    """Deterministic point id: retrying a version overwrites the same points
    instead of leaving orphan vectors from the failed attempt behind."""
    return str(
        uuid_module.uuid5(
            uuid_module.NAMESPACE_URL,
            f"{document_version_id}:{chunk_index}:{content_sha256}",
        )
    )
