"""Embedding providers for knowledge retrieval.

Two implementations behind one Protocol:

- ``FastEmbedProvider``: in-process ONNX model (bge-small-zh-v1.5 by default),
  no model serving, no GPU. First use downloads and caches the model.
- ``HashEmbeddingProvider``: deterministic 256-dim blake2b feature hashing on
  char n-grams. Low quality but dependency-free; it keeps the knowledge
  pipeline usable when fastembed cannot be loaded, matching the project's
  local-degradation philosophy.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app.services.embedding import normalize

logger = logging.getLogger(__name__)

_NGRAM_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_EMBED_CACHE: dict[tuple[str, str], EmbeddingProvider] = {}


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int
    degraded: bool

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbeddingProvider:
    """Fallback embedder, deliberately identical in spirit to the classroom
    clustering embedder so behavior is predictable without any model files."""

    model_name = "hash-256"
    dimensions = 256
    degraded = True

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = normalize(text)
        if not normalized:
            raise ValueError("empty_content")
        tokens = _NGRAM_RE.findall(normalized.lower())
        grams: list[str] = []
        for token in tokens:
            grams.append(token)
            for size in (2, 3):
                for i in range(len(token) - size + 1):
                    grams.append(token[i : i + size])
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            sign = 1.0 if digest[0] % 2 == 0 else -1.0
            vector[index] += sign
        norm = sum(value * value for value in vector) ** 0.5
        if norm == 0:
            raise ValueError("empty_content")
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class FastEmbedProvider:
    """In-process ONNX text embedder served by the fastembed package."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name)
        self.dimensions = len(next(iter(self._model.embed(["维度探测"]))))
        self.degraded = False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [(text or "空").strip()[:2000] for text in texts]
        return [list(map(float, vec)) for vec in self._model.embed(cleaned)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@dataclass
class EmbeddingStatus:
    provider: str
    model_name: str
    dimensions: int
    degraded: bool
    error_code: str | None = None


def get_embedding_provider(settings) -> EmbeddingProvider:
    """Return a cached provider instance.

    fastembed is imported lazily and failures fall back to the hash embedder
    with ``degraded=True`` so callers can surface the state to the teacher.
    """
    cache_key = (settings.embedding_provider, settings.embedding_model)
    if cache_key in _EMBED_CACHE:
        return _EMBED_CACHE[cache_key]
    if settings.embedding_provider == "fastembed":
        try:
            provider: EmbeddingProvider = FastEmbedProvider(settings.embedding_model)
        except Exception as exc:  # noqa: BLE001 - any load failure degrades
            logger.warning(
                "fastembed load failed (%s: %s); knowledge retrieval degrades "
                "to the hash embedder", type(exc).__name__, exc,
            )
            provider = HashEmbeddingProvider()
            provider.model_name = f"{provider.model_name} (degraded: {type(exc).__name__})"
            _EMBED_CACHE[cache_key] = provider
            return provider
        _EMBED_CACHE[cache_key] = provider
        return provider
    provider = HashEmbeddingProvider()
    _EMBED_CACHE[cache_key] = provider
    return provider


def embedding_status(settings) -> EmbeddingStatus:
    provider = get_embedding_provider(settings)
    return EmbeddingStatus(
        provider=settings.embedding_provider,
        model_name=provider.model_name,
        dimensions=provider.dimensions,
        degraded=provider.degraded,
    )
