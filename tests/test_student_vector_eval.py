from services.student_vector_eval import evaluate_student_vector_fixture


def test_student_vector_fixture_measures_recall_and_scope_safety():
    metrics = evaluate_student_vector_fixture()

    assert metrics["query_count"] == 6
    assert metrics["source_count"] == 6
    assert metrics["active_source_count"] == 4
    assert metrics["revoked_source_count"] == 1
    assert metrics["expired_source_count"] == 1
    assert metrics["recall_at_1"] == 0.833
    assert metrics["recall_at_k"] == 1.0
    assert metrics["cross_scope_hit_count"] == 0
    assert metrics["revoked_hit_count"] == 0
    assert metrics["unlinked_knowledge_score_hit_count"] == 0
    assert metrics["status_mismatch_count"] == 0
    assert metrics["mean_query_latency_ms"] >= 0
    assert metrics["p95_query_latency_ms"] >= metrics["mean_query_latency_ms"]
    assert all(
        case["filtered_candidate_count"] <= case["scope_candidate_count"]
        for case in metrics["case_results"]
    )
    assert metrics["case_results"][4]["actual_status"] == "no_result"
    assert metrics["case_results"][5]["retrieved_source_ids"] == ["a-score-array"]
