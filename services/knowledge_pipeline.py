"""Composable, offline-first contracts for the knowledge retrieval pipeline.

The default implementation deliberately uses only the Python standard library.
It gives the assignment-scoped retriever a replaceable boundary for chunking,
embedding, candidate retrieval, reranking, and citation construction without
requiring a model key, vector database, schema change, or deployment change.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Protocol, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
DEFAULT_CHUNK_SIZE = 320


@dataclass(frozen=True)
class KnowledgeDocument:
    """A source document presented to the pipeline."""

    document_id: str
    title: str
    content: str
    source_type: str
    priority: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeChunk:
    """A deterministic chunk that can be embedded and cited."""

    chunk_id: str
    document_id: str
    title: str
    text: str
    ordinal: int
    source_type: str
    priority: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _stable_chunk_key(chunk: KnowledgeChunk):
    """Keep assignment record IDs numeric while generic IDs stay deterministic."""

    record_id = chunk.metadata.get("record_id")
    try:
        return (0, int(record_id), chunk.ordinal, chunk.chunk_id)
    except (TypeError, ValueError):
        return (1, chunk.document_id, chunk.ordinal, chunk.chunk_id)


@dataclass(frozen=True)
class RetrievalCandidate:
    """A chunk returned by candidate retrieval before final reranking."""

    chunk: KnowledgeChunk
    score: float
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeCitation:
    """Stable, student-safe citation output from the citation stage."""

    evidence_id: str
    citation: str
    source_type: str
    title: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class DocumentChunker(Protocol):
    def split(self, document: KnowledgeDocument) -> Sequence[KnowledgeChunk]:
        """Split one source document into deterministic chunks."""


class TextEmbedder(Protocol):
    def embed(self, text: str) -> Mapping[str, float]:
        """Map text to an implementation-defined embedding."""


class CandidateRetriever(Protocol):
    def retrieve(
        self,
        query_embedding: Mapping[str, float],
        chunks: Sequence[KnowledgeChunk],
        chunk_embeddings: Mapping[str, Mapping[str, float]],
        limit: int,
    ) -> Sequence[RetrievalCandidate]:
        """Return a bounded candidate set for reranking."""


class CandidateReranker(Protocol):
    def rerank(
        self,
        query_embedding: Mapping[str, float],
        candidates: Sequence[RetrievalCandidate],
    ) -> Sequence[RetrievalCandidate]:
        """Apply the final deterministic ordering to candidates."""


class CitationBuilder(Protocol):
    def build(self, candidate: RetrievalCandidate, rank: int) -> KnowledgeCitation:
        """Convert a ranked candidate into a stable citation."""


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize English identifiers and individual CJK characters offline."""

    return tuple(_TOKEN_RE.findall(str(text or "").lower()))


class ParagraphChunker:
    """Split short documents on sentence boundaries with a size guard."""

    def __init__(self, max_chars: int = DEFAULT_CHUNK_SIZE):
        self.max_chars = max(1, int(max_chars))

    def split(self, document: KnowledgeDocument) -> Sequence[KnowledgeChunk]:
        text = " ".join(str(document.content or "").split())
        if not text:
            return ()

        segments = [segment for segment in re.split(r"(?<=[。！？.!?；;])\s*", text) if segment]
        chunks: list[str] = []
        current = ""
        for segment in segments:
            if current and len(current) + 1 + len(segment) > self.max_chars:
                chunks.append(current)
                current = ""
            if len(segment) <= self.max_chars:
                current = f"{current} {segment}".strip()
                continue
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                segment[index:index + self.max_chars]
                for index in range(0, len(segment), self.max_chars)
            )
        if current:
            chunks.append(current)

        return tuple(
            KnowledgeChunk(
                chunk_id=f"{document.document_id}#chunk-{ordinal}",
                document_id=document.document_id,
                title=document.title,
                text=chunk,
                ordinal=ordinal,
                source_type=document.source_type,
                priority=float(document.priority),
                metadata=dict(document.metadata),
            )
            for ordinal, chunk in enumerate(chunks)
        )


class TokenCountEmbedder:
    """A transparent offline embedding based on normalized token counts."""

    def embed(self, text: str) -> Mapping[str, float]:
        counts = Counter(tokenize(text))
        total = sum(counts.values()) or 1
        return {token: count / total for token, count in counts.items()}


class LexicalCandidateRetriever:
    """Retrieve chunks by query-token overlap, without external services."""

    def retrieve(
        self,
        query_embedding: Mapping[str, float],
        chunks: Sequence[KnowledgeChunk],
        chunk_embeddings: Mapping[str, Mapping[str, float]],
        limit: int,
    ) -> Sequence[RetrievalCandidate]:
        query_terms = set(query_embedding)
        candidates = []
        for chunk in chunks:
            chunk_terms = set(chunk_embeddings.get(chunk.chunk_id, {}))
            matched = tuple(sorted(query_terms & chunk_terms))
            score = len(matched) / len(query_terms) if query_terms else 0.0
            candidates.append(RetrievalCandidate(chunk, score, matched))
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                -candidate.chunk.priority,
                *_stable_chunk_key(candidate.chunk),
            ),
        )
        return tuple(ordered[:max(1, int(limit))])


class StablePriorityReranker:
    """Prefer lexical matches, then source priority, then stable IDs."""

    def rerank(
        self,
        query_embedding: Mapping[str, float],
        candidates: Sequence[RetrievalCandidate],
    ) -> Sequence[RetrievalCandidate]:
        del query_embedding
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.score,
                    -candidate.chunk.priority,
                    *_stable_chunk_key(candidate.chunk),
                ),
            )
        )


class StableCitationBuilder:
    """Build citations without exposing scores or private student data."""

    def build(self, candidate: RetrievalCandidate, rank: int) -> KnowledgeCitation:
        evidence_id = candidate.chunk.metadata.get(
            "evidence_id",
            candidate.chunk.chunk_id,
        )
        return KnowledgeCitation(
            evidence_id=str(evidence_id),
            citation=f"[K{rank}]",
            source_type=candidate.chunk.source_type,
            title=candidate.chunk.title,
            content=candidate.chunk.text,
            metadata=dict(candidate.chunk.metadata),
        )


class OfflineKnowledgePipeline:
    """Orchestrate replaceable pipeline stages over in-memory documents."""

    def __init__(
        self,
        *,
        chunker: DocumentChunker | None = None,
        embedder: TextEmbedder | None = None,
        retriever: CandidateRetriever | None = None,
        reranker: CandidateReranker | None = None,
        citation_builder: CitationBuilder | None = None,
    ):
        self.chunker = chunker or ParagraphChunker()
        self.embedder = embedder or TokenCountEmbedder()
        self.retriever = retriever or LexicalCandidateRetriever()
        self.reranker = reranker or StablePriorityReranker()
        self.citation_builder = citation_builder or StableCitationBuilder()

    def search(
        self,
        query: str,
        documents: Sequence[KnowledgeDocument],
        *,
        limit: int = 8,
    ) -> tuple[KnowledgeCitation, ...]:
        bounded_limit = max(1, int(limit))
        chunks = tuple(
            chunk
            for document in documents
            for chunk in self.chunker.split(document)
        )
        if not chunks:
            return ()

        query_embedding = self.embedder.embed(query)
        chunk_embeddings = {
            chunk.chunk_id: self.embedder.embed(chunk.text) for chunk in chunks
        }
        candidates = self.retriever.retrieve(
            query_embedding,
            chunks,
            chunk_embeddings,
            max(bounded_limit, len(chunks)),
        )
        ranked = self.reranker.rerank(query_embedding, candidates)
        return tuple(
            self.citation_builder.build(candidate, rank)
            for rank, candidate in enumerate(ranked[:bounded_limit], start=1)
        )


def build_offline_pipeline() -> OfflineKnowledgePipeline:
    """Return the default pipeline used by the assignment-scoped adapter."""

    return OfflineKnowledgePipeline()
