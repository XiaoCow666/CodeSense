import pytest

from services.knowledge_optimization import (
    BudgetedEmbedder,
    EmbeddingBudgetExceeded,
    build_default_embedding_registry,
)
from services.knowledge_optimization_eval import compare_embedders


class _CountingEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        return {str(text): 1.0}


def test_budgeted_embedder_rejects_call_before_cost_cap_is_exceeded():
    provider = _CountingEmbedder()
    embedder = BudgetedEmbedder(
        provider,
        provider_name="test-paid",
        estimated_cost_per_call=0.02,
        max_calls=3,
        max_estimated_cost=0.02,
    )

    assert embedder.embed("first") == {"first": 1.0}
    with pytest.raises(EmbeddingBudgetExceeded):
        embedder.embed("second")

    usage = embedder.snapshot()
    assert provider.calls == 1
    assert usage["calls"] == 1
    assert usage["estimated_cost"] == 0.02
    assert usage["budget_rejections"] == 1
    assert usage["budget_exceeded"] is True


def test_comparison_reports_quality_cost_and_selected_provider():
    report = compare_embedders()

    assert report["baseline_provider"] == "cjk_ngram"
    assert report["selected_provider"] == "cjk_ngram"
    assert set(report["providers"]) == {"cjk_ngram", "token"}
    for provider_report in report["providers"].values():
        assert provider_report["recall_at_k"] >= 0.0
        assert provider_report["embedding_usage"]["calls"] > 0
        assert provider_report["embedding_usage"]["estimated_cost"] == 0.0
        assert provider_report["quality_gate"] is True
        assert provider_report["cost_gate"] is True


def test_registry_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown embedding provider"):
        build_default_embedding_registry().build("not-installed")
