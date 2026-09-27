"""Offline quality/cost comparison for the stage 14 embedding seam."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.knowledge_eval import DEFAULT_FIXTURE, evaluate_fixture
from services.knowledge_optimization import build_default_embedding_registry


DEFAULT_PROVIDERS = ("cjk_ngram", "token")


def compare_embedders(
    path: str | Path = DEFAULT_FIXTURE,
    *,
    providers: tuple[str, ...] = DEFAULT_PROVIDERS,
    max_calls: int = 512,
    max_estimated_cost: float = 0.0,
    quality_floor: float = 1.0,
) -> dict[str, Any]:
    """Compare providers on the fixed set and apply quality/cost gates."""

    registry = build_default_embedding_registry()
    reports = {}
    baseline_name = providers[0] if providers else None
    for provider_name in providers:
        embedder = registry.build(
            provider_name,
            max_calls=max_calls,
            max_estimated_cost=max_estimated_cost,
        )
        metrics = evaluate_fixture(path, embedder=embedder)
        reports[provider_name] = {
            "recall_at_1": metrics["recall_at_1"],
            "recall_at_k": metrics["recall_at_k"],
            "mean_query_latency_ms": metrics["mean_query_latency_ms"],
            "p95_query_latency_ms": metrics["p95_query_latency_ms"],
            "mean_total_latency_ms": metrics["mean_total_latency_ms"],
            "embedding_usage": metrics["embedding_usage"],
        }

    baseline_recall = (
        reports[baseline_name]["recall_at_k"] if baseline_name in reports else 0.0
    )
    selected_provider = None
    for provider_name in providers:
        report = reports[provider_name]
        usage = report["embedding_usage"]
        quality_ok = report["recall_at_k"] >= baseline_recall * float(quality_floor)
        cost_ok = (
            not usage["budget_exceeded"]
            and usage["estimated_cost"] <= float(max_estimated_cost) + 1e-12
        )
        report["quality_gate"] = quality_ok
        report["cost_gate"] = cost_ok
        report["selected"] = selected_provider is None and quality_ok and cost_ok
        if report["selected"]:
            selected_provider = provider_name

    return {
        "fixture": str(Path(path)),
        "baseline_provider": baseline_name,
        "quality_floor": float(quality_floor),
        "max_calls": max(1, int(max_calls)),
        "max_estimated_cost": float(max_estimated_cost),
        "providers": reports,
        "selected_provider": selected_provider,
    }


def main() -> None:
    print(json.dumps(compare_embedders(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
