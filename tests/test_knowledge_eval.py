from services.knowledge_eval import evaluate_fixture


def test_fixed_knowledge_eval_reports_vector_fallback_and_no_result_modes():
    metrics = evaluate_fixture()

    assert metrics["query_count"] == 4
    assert metrics["relevant_query_count"] == 3
    assert metrics["recall_at_1"] == 1.0
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mode_counts"] == {
        "keyword_fallback": 1,
        "no_result": 1,
        "vector": 2,
    }
    assert metrics["mean_latency_ms"] >= 0
    assert metrics["p95_latency_ms"] >= 0
