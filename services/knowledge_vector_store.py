"""Small, request-scoped vector retrieval and keyword fallback primitives.

The store is deliberately in-memory and sparse.  It writes only the chunks
passed by the caller, computes cosine similarity with a replaceable embedder,
and never shares index state between requests.  That makes it suitable for an
offline evaluation and a safe adapter prototype before selecting a persistent
vector service.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import time
from typing import Mapping, Sequence

from services.knowledge_pipeline import (
    KnowledgeChunk,
    RetrievalCandidate,
    StablePriorityReranker,
    TextEmbedder,
    _stable_chunk_key,
)


@dataclass(frozen=True)
class RetrievalResult:
    """A bounded result set plus the path that produced it."""

    mode: str
    candidates: tuple[RetrievalCandidate, ...]
    indexed_chunk_count: int


class KnowledgeRetrievalTimeout(TimeoutError):
    """Raised when bounded indexing or retrieval exceeds its local budget."""


def _check_deadline(deadline, clock) -> None:
    if deadline is not None and clock() > deadline:
        raise KnowledgeRetrievalTimeout("knowledge retrieval deadline exceeded")


def _cosine_similarity(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    """Calculate cosine similarity for two sparse, non-negative vectors."""

    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


class NgramCountEmbedder:
    """Transparent sparse vectors with CJK bigrams and whole ASCII tokens."""

    _TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")

    def embed(self, text: str) -> Mapping[str, float]:
        tokens = []
        for match in self._TOKEN_RE.findall(str(text or "").lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                tokens.extend(
                    match[index:index + 2]
                    for index in range(max(1, len(match) - 1))
                )
            else:
                tokens.append(match)
        counts = Counter(tokens)
        total = sum(counts.values()) or 1
        return {token: count / total for token, count in counts.items()}


class InMemoryVectorStore:
    """Write and query one isolated sparse vector index."""

    def __init__(
        self,
        embedder: TextEmbedder | None = None,
        *,
        clock=time.monotonic,
    ):
        self.embedder = embedder or NgramCountEmbedder()
        self._clock = clock
        self._chunks: tuple[KnowledgeChunk, ...] = ()
        self._embeddings: dict[str, Mapping[str, float]] = {}

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return self._chunks

    def clone(self) -> "InMemoryVectorStore":
        """Copy index state without re-embedding existing chunks."""

        cloned = InMemoryVectorStore(self.embedder, clock=self._clock)
        cloned._chunks = self._chunks
        cloned._embeddings = dict(self._embeddings)
        return cloned

    def write(self, chunks: Sequence[KnowledgeChunk], *, deadline=None) -> int:
        """Replace this index with caller-owned chunks and their embeddings."""

        normalized = tuple(chunks)
        embeddings = {}
        for chunk in normalized:
            _check_deadline(deadline, self._clock)
            embeddings[chunk.chunk_id] = self.embedder.embed(chunk.text)
        _check_deadline(deadline, self._clock)
        self._chunks = normalized
        self._embeddings = embeddings
        return len(normalized)

    def upsert(self, chunks: Sequence[KnowledgeChunk], *, deadline=None) -> int:
        """Embed only changed chunks and atomically add or replace them."""

        current = list(self._chunks)
        positions = {chunk.chunk_id: index for index, chunk in enumerate(current)}
        embeddings = dict(self._embeddings)
        for chunk in chunks:
            _check_deadline(deadline, self._clock)
            position = positions.get(chunk.chunk_id)
            if position is None:
                positions[chunk.chunk_id] = len(current)
                current.append(chunk)
            else:
                current[position] = chunk
            embeddings[chunk.chunk_id] = self.embedder.embed(chunk.text)
        _check_deadline(deadline, self._clock)
        self._chunks = tuple(current)
        self._embeddings = embeddings
        return len(self._chunks)

    def remove_documents(self, document_ids: Sequence[str], *, deadline=None) -> int:
        """Remove all chunks belonging to the supplied document IDs."""

        blocked = {str(document_id) for document_id in document_ids}
        if not blocked:
            return len(self._chunks)
        kept = []
        for chunk in self._chunks:
            _check_deadline(deadline, self._clock)
            if chunk.document_id not in blocked:
                kept.append(chunk)
        self._chunks = tuple(kept)
        self._embeddings = {
            chunk.chunk_id: self._embeddings.get(chunk.chunk_id, {})
            for chunk in self._chunks
        }
        return len(self._chunks)

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        deadline=None,
    ) -> tuple[RetrievalCandidate, ...]:
        """Return only positive cosine matches, in deterministic top-k order."""

        _check_deadline(deadline, self._clock)
        query_embedding = self.embedder.embed(query)
        if not query_embedding:
            return ()

        candidates = []
        query_terms = set(query_embedding)
        for chunk in self._chunks:
            _check_deadline(deadline, self._clock)
            embedding = self._embeddings.get(chunk.chunk_id, {})
            score = _cosine_similarity(query_embedding, embedding)
            if score <= 0.0:
                continue
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    score=score,
                    matched_terms=tuple(sorted(query_terms & set(embedding))),
                )
            )

        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                -candidate.chunk.priority,
                *_stable_chunk_key(candidate.chunk),
            ),
        )
        _check_deadline(deadline, self._clock)
        return tuple(ordered[: max(1, int(top_k))])


class KeywordFallbackRetriever:
    """Find title/body matches when the vector index has no positive hit."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock

    def retrieve(
        self,
        query: str,
        chunks: Sequence[KnowledgeChunk],
        *,
        top_k: int = 8,
        deadline=None,
    ) -> tuple[RetrievalCandidate, ...]:
        _check_deadline(deadline, self._clock)
        query_terms = set(NgramCountEmbedder().embed(query))
        if not query_terms:
            return ()

        candidates = []
        for chunk in chunks:
            _check_deadline(deadline, self._clock)
            # Titles are intentionally included here: metadata-only labels can
            # be useful fallback evidence even when the body vector is sparse.
            searchable_terms = set(
                NgramCountEmbedder().embed(f"{chunk.title} {chunk.text}")
            )
            matched = tuple(sorted(query_terms & searchable_terms))
            if not matched:
                continue
            candidates.append(
                RetrievalCandidate(
                    chunk=chunk,
                    score=len(matched) / len(query_terms),
                    matched_terms=matched,
                )
            )

        result = tuple(
            StablePriorityReranker().rerank({}, candidates)[: max(1, int(top_k))]
        )
        _check_deadline(deadline, self._clock)
        return result


class HybridKnowledgeIndex:
    """Combine vector top-k, keyword fallback, and legacy priority fallback."""

    def __init__(
        self,
        chunks: Sequence[KnowledgeChunk],
        *,
        embedder: TextEmbedder | None = None,
        deadline=None,
        clock=time.monotonic,
    ):
        self._clock = clock
        self._deadline = deadline
        self.vector_store = InMemoryVectorStore(embedder, clock=clock)
        self.vector_store.write(chunks, deadline=deadline)
        self.keyword_fallback = KeywordFallbackRetriever(clock=clock)

    @property
    def indexed_chunk_count(self) -> int:
        return len(self.vector_store.chunks)

    def replace(self, chunks: Sequence[KnowledgeChunk], *, deadline=None) -> int:
        return self.vector_store.write(
            chunks,
            deadline=self._deadline if deadline is None else deadline,
        )

    def clone(self) -> "HybridKnowledgeIndex":
        """Clone the current index state without rebuilding embeddings."""

        cloned = object.__new__(HybridKnowledgeIndex)
        cloned._clock = self._clock
        cloned._deadline = self._deadline
        cloned.vector_store = self.vector_store.clone()
        cloned.keyword_fallback = KeywordFallbackRetriever(clock=self._clock)
        return cloned

    def upsert(self, chunks: Sequence[KnowledgeChunk], *, deadline=None) -> int:
        return self.vector_store.upsert(
            chunks,
            deadline=self._deadline if deadline is None else deadline,
        )

    def remove_documents(
        self,
        document_ids: Sequence[str],
        *,
        deadline=None,
    ) -> int:
        return self.vector_store.remove_documents(
            document_ids,
            deadline=self._deadline if deadline is None else deadline,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        deadline=None,
    ) -> RetrievalResult:
        """Search with explicit mode reporting and a compatibility fallback."""

        effective_deadline = self._deadline if deadline is None else deadline
        _check_deadline(effective_deadline, self._clock)
        vector_candidates = self.vector_store.search(
            query,
            top_k=top_k,
            deadline=effective_deadline,
        )
        if vector_candidates:
            return RetrievalResult("vector", vector_candidates, self.indexed_chunk_count)

        keyword_candidates = self.keyword_fallback.retrieve(
            query,
            self.vector_store.chunks,
            top_k=top_k,
            deadline=effective_deadline,
        )
        if keyword_candidates:
            return RetrievalResult(
                "keyword_fallback",
                keyword_candidates,
                self.indexed_chunk_count,
            )

        # Preserve the stage 11 behavior for an existing assignment with an
        # empty or unmatched question: return stable priority evidence instead
        # of changing the student-facing no-result contract.
        priority_candidates = tuple(
            sorted(
                (
                    RetrievalCandidate(chunk=chunk, score=0.0)
                    for chunk in self.vector_store.chunks
                ),
                key=lambda candidate: (
                    -candidate.chunk.priority,
                    *_stable_chunk_key(candidate.chunk),
                ),
            )[: max(1, int(top_k))]
        )
        _check_deadline(effective_deadline, self._clock)
        return RetrievalResult(
            "priority_fallback" if priority_candidates else "no_result",
            priority_candidates,
            self.indexed_chunk_count,
        )
