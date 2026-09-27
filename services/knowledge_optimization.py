"""Bounded, replaceable embedding providers for the knowledge RAG adapter.

The registry is intentionally offline-first. It makes provider selection
explicit, records only bounded cost/latency counters, and rejects a request
before a configured budget can be exceeded. A future model provider can be
added behind the same contract without changing the student-facing route.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Callable, Mapping

from services.knowledge_pipeline import TextEmbedder, TokenCountEmbedder
from services.knowledge_vector_store import NgramCountEmbedder


DEFAULT_EMBEDDING_MAX_COST = 0.0
MAX_EMBEDDING_COST = 1000.0


class EmbeddingBudgetExceeded(RuntimeError):
    """Raised before an embedding call would exceed its configured budget."""


@dataclass(frozen=True)
class EmbeddingProviderSpec:
    """Construction and offline cost metadata for one embedding provider."""

    name: str
    factory: Callable[[], TextEmbedder]
    estimated_cost_per_call: float = 0.0

    def __post_init__(self):
        if not str(self.name).strip():
            raise ValueError("embedding provider name is required")
        if self.estimated_cost_per_call < 0:
            raise ValueError("embedding provider cost cannot be negative")


class BudgetedEmbedder:
    """Wrap an embedder with per-request call, cost, and latency accounting."""

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        provider_name: str,
        estimated_cost_per_call: float = 0.0,
        max_calls: int | None = None,
        max_estimated_cost: float | None = None,
        clock=time.perf_counter,
    ):
        self._embedder = embedder
        self.provider_name = str(provider_name)
        self.estimated_cost_per_call = max(0.0, float(estimated_cost_per_call))
        self.max_calls = None if max_calls is None else max(1, int(max_calls))
        self.max_estimated_cost = (
            None
            if max_estimated_cost is None
            else max(0.0, float(max_estimated_cost))
        )
        self._clock = clock
        self._calls = 0
        self._failed_calls = 0
        self._budget_rejections = 0
        self._estimated_cost = 0.0
        self._total_latency_ms = 0.0
        self._lock = threading.Lock()

    def _reserve(self) -> None:
        with self._lock:
            next_cost = self._estimated_cost + self.estimated_cost_per_call
            if self.max_calls is not None and self._calls >= self.max_calls:
                self._budget_rejections += 1
                raise EmbeddingBudgetExceeded(
                    f"embedding call budget exceeded for {self.provider_name}"
                )
            if (
                self.max_estimated_cost is not None
                and next_cost > self.max_estimated_cost + 1e-12
            ):
                self._budget_rejections += 1
                raise EmbeddingBudgetExceeded(
                    f"embedding cost budget exceeded for {self.provider_name}"
                )
            self._calls += 1
            self._estimated_cost = next_cost

    def embed(self, text: str) -> Mapping[str, float]:
        self._reserve()
        started_at = self._clock()
        try:
            return self._embedder.embed(text)
        except Exception:
            with self._lock:
                self._failed_calls += 1
            raise
        finally:
            elapsed_ms = max(0.0, (self._clock() - started_at) * 1000.0)
            with self._lock:
                self._total_latency_ms += elapsed_ms

    def snapshot(self) -> dict[str, float | int | str | bool | None]:
        """Return bounded metrics without retaining text or query content."""

        with self._lock:
            return {
                "provider": self.provider_name,
                "calls": self._calls,
                "failed_calls": self._failed_calls,
                "budget_rejections": self._budget_rejections,
                "estimated_cost": round(self._estimated_cost, 8),
                "total_latency_ms": round(self._total_latency_ms, 3),
                "max_calls": self.max_calls,
                "max_estimated_cost": self.max_estimated_cost,
                "budget_exceeded": bool(self._budget_rejections),
            }


class KnowledgeEmbeddingRegistry:
    """Small explicit registry for offline and future embedding providers."""

    def __init__(self, specs: tuple[EmbeddingProviderSpec, ...] = ()):
        self._specs: dict[str, EmbeddingProviderSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: EmbeddingProviderSpec) -> None:
        name = str(spec.name).strip()
        if name in self._specs:
            raise ValueError(f"embedding provider already registered: {name}")
        self._specs[name] = spec

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def build(
        self,
        name: str,
        *,
        max_calls: int | None = None,
        max_estimated_cost: float | None = None,
        clock=time.perf_counter,
    ) -> BudgetedEmbedder:
        normalized = str(name).strip()
        try:
            spec = self._specs[normalized]
        except KeyError as exc:
            available = ", ".join(self.names()) or "<none>"
            raise ValueError(
                f"unknown embedding provider {normalized!r}; available: {available}"
            ) from exc
        return BudgetedEmbedder(
            spec.factory(),
            provider_name=spec.name,
            estimated_cost_per_call=spec.estimated_cost_per_call,
            max_calls=max_calls,
            max_estimated_cost=max_estimated_cost,
            clock=clock,
        )


def build_default_embedding_registry() -> KnowledgeEmbeddingRegistry:
    """Build the local registry; both providers are deterministic and free."""

    return KnowledgeEmbeddingRegistry(
        (
            EmbeddingProviderSpec("cjk_ngram", NgramCountEmbedder),
            EmbeddingProviderSpec("token", TokenCountEmbedder),
        )
    )


def default_embedding_max_cost() -> float:
    """Read a bounded per-request cost cap, defaulting to free local models."""

    try:
        value = float(
            os.environ.get(
                "KNOWLEDGE_RAG_EMBEDDING_MAX_COST",
                DEFAULT_EMBEDDING_MAX_COST,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_EMBEDDING_MAX_COST
    return max(0.0, min(MAX_EMBEDDING_COST, value))
