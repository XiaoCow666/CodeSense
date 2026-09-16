"""Bounded reliability controls for the request-scoped knowledge index.

The controls in this module deliberately keep state in memory and make every
mutation explicit.  They provide a small seam for incremental updates,
rollback, privacy filtering, rate limiting, time budgets, and quality
monitoring without introducing a database table, a deployment dependency, or
cross-assignment index state.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import os
import re
import threading
import time
from typing import Sequence

from services.knowledge_pipeline import KnowledgeChunk, KnowledgeDocument
from services.knowledge_vector_store import HybridKnowledgeIndex


DEFAULT_RETRIEVAL_TIMEOUT_MS = 250
DEFAULT_RATE_LIMIT_REQUESTS = 120
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
MAX_RATE_LIMIT_KEYS = 4096
MAX_MONITOR_SAMPLES = 512
MAX_MONITOR_LABELS = 32
MONITOR_OVERFLOW_LABEL = "__other__"


class KnowledgePrivacyFilter:
    """Redact common contact and credential patterns before indexing."""

    SAFE_METADATA_KEYS = frozenset({"created_at", "evidence_id", "record_id"})
    _PATTERNS = (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        re.compile(
            r"\b(?:ghp_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_-]{8,}\b",
            re.I,
        ),
        re.compile(
            r"\b(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+",
            re.I,
        ),
    )

    @classmethod
    def redact(cls, value: object) -> str:
        redacted = str(value or "")
        for pattern in cls._PATTERNS:
            redacted = pattern.sub("[已过滤]", redacted)
        return redacted

    @classmethod
    def sanitize_document(cls, document: KnowledgeDocument) -> KnowledgeDocument:
        metadata = {
            key: value
            for key, value in dict(document.metadata).items()
            if key in cls.SAFE_METADATA_KEYS
        }
        return KnowledgeDocument(
            document_id=str(document.document_id),
            title=cls.redact(document.title),
            content=cls.redact(document.content),
            source_type=str(document.source_type),
            priority=float(document.priority),
            metadata=metadata,
        )


class SlidingWindowRateLimiter:
    """Thread-safe, bounded per-key request limiter for one process."""

    def __init__(
        self,
        max_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
        window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        *,
        max_keys: int = MAX_RATE_LIMIT_KEYS,
        clock=time.monotonic,
    ):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(0.001, float(window_seconds))
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: object) -> bool:
        normalized_key = str(key or "anonymous")[:128]
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events.get(normalized_key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    oldest_key = min(
                        self._events,
                        key=lambda item: self._events[item][-1],
                    )
                    del self._events[oldest_key]
                events = deque()
                self._events[normalized_key] = events
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_requests:
                return False
            events.append(now)
            return True


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def build_default_rate_limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(
        max_requests=_env_int(
            "KNOWLEDGE_RAG_RATE_LIMIT", 
            DEFAULT_RATE_LIMIT_REQUESTS,
            minimum=1,
            maximum=10000,
        ),
        window_seconds=_env_float(
            "KNOWLEDGE_RAG_RATE_WINDOW_SECONDS",
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
            minimum=1.0,
            maximum=3600.0,
        ),
    )


def default_retrieval_timeout_ms() -> int:
    return _env_int(
        "KNOWLEDGE_RAG_TIMEOUT_MS",
        DEFAULT_RETRIEVAL_TIMEOUT_MS,
        minimum=1,
        maximum=5000,
    )


@dataclass(frozen=True)
class IndexRevision:
    number: int
    indexed_chunk_count: int


class VersionedKnowledgeIndex:
    """Apply explicit chunk updates and retain bounded rollback history."""

    def __init__(
        self,
        chunks: Sequence[KnowledgeChunk],
        *,
        embedder=None,
        history_limit: int = 2,
        deadline=None,
        clock=time.monotonic,
    ):
        self._embedder = embedder
        self._deadline = deadline
        self._clock = clock
        self._history: deque[tuple[int, HybridKnowledgeIndex]] = deque(
            maxlen=max(1, int(history_limit))
        )
        self._index = HybridKnowledgeIndex(
            chunks,
            embedder=embedder,
            deadline=deadline,
            clock=clock,
        )
        self._revision = 1

    @property
    def revision(self) -> IndexRevision:
        return IndexRevision(self._revision, self._index.indexed_chunk_count)

    @property
    def indexed_chunk_count(self) -> int:
        return self._index.indexed_chunk_count

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return self._index.vector_store.chunks

    @property
    def history_depth(self) -> int:
        return len(self._history)

    def search(self, query: str, *, top_k: int = 8, deadline=None):
        return self._index.search(query, top_k=top_k, deadline=deadline)

    def upsert(
        self,
        chunks: Sequence[KnowledgeChunk],
        *,
        remove_document_ids: Sequence[str] = (),
        deadline=None,
    ) -> IndexRevision:
        """Publish a changed chunk set atomically as the next revision."""

        effective_deadline = self._deadline if deadline is None else deadline
        candidate = self._index.clone()
        candidate.remove_documents(
            remove_document_ids,
            deadline=effective_deadline,
        )
        candidate.upsert(chunks, deadline=effective_deadline)
        self._history.append((self._revision, self._index.clone()))
        self._index = candidate
        self._revision += 1
        return self.revision

    def rollback(self, *, deadline=None) -> IndexRevision | None:
        """Restore the most recent published snapshot, if one exists."""

        del deadline
        if not self._history:
            return None
        _, previous_index = self._history.pop()
        self._index = previous_index
        self._revision += 1
        return self.revision


class KnowledgeQualityMonitor:
    """Bounded counters and latency samples without retaining query content."""

    def __init__(
        self,
        *,
        max_samples: int = MAX_MONITOR_SAMPLES,
        max_labels: int = MAX_MONITOR_LABELS,
    ):
        self._max_samples = max(1, int(max_samples))
        self._max_labels = max(2, int(max_labels))
        self._counts: Counter[str] = Counter()
        self._mode_counts: Counter[str] = Counter()
        self._latencies: deque[float] = deque(maxlen=self._max_samples)
        self._lock = threading.Lock()

    def _increment_bounded(self, counter: Counter[str], label: str) -> None:
        """Keep caller-controlled status and mode cardinality bounded."""

        normalized = str(label)
        if normalized in counter or MONITOR_OVERFLOW_LABEL in counter:
            counter[normalized if normalized in counter else MONITOR_OVERFLOW_LABEL] += 1
            return

        # Reserve one slot for the overflow bucket so new labels can never
        # grow the counter beyond the configured bound.
        if len(counter) < self._max_labels - 1:
            counter[normalized] += 1
        else:
            counter[MONITOR_OVERFLOW_LABEL] += 1

    def record(
        self,
        *,
        status: str,
        mode: str | None,
        latency_ms: float,
        fallback_code: str | None = None,
    ) -> None:
        with self._lock:
            self._counts["requests"] += 1
            self._increment_bounded(self._counts, str(status))
            if fallback_code:
                self._increment_bounded(
                    self._counts,
                    f"fallback:{fallback_code}",
                )
            if mode:
                self._increment_bounded(self._mode_counts, str(mode))
            self._latencies.append(max(0.0, float(latency_ms)))

    def snapshot(self) -> dict:
        with self._lock:
            sample_count = len(self._latencies)
            return {
                "requests": self._counts["requests"],
                "status_counts": dict(sorted(self._counts.items())),
                "mode_counts": dict(sorted(self._mode_counts.items())),
                "latency_sample_count": sample_count,
                "mean_latency_ms": round(
                    sum(self._latencies) / sample_count,
                    3,
                ) if sample_count else 0.0,
            }

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._mode_counts.clear()
            self._latencies.clear()
