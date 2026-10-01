from services.student_vector_eval import evaluate_student_vector_fixture
import json


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


def test_offline_eval_does_not_count_weak_overlap_as_a_runtime_hit(tmp_path):
    fixture = tmp_path / 'weak-overlap.json'
    fixture.write_text(json.dumps({
        'sources': [{'source_id': 'weak', 'student_id': 's', 'status': 'active',
                     'source_type': 'submission_feedback',
                     'content': 'shared ' + ' '.join('token' + str(i) for i in range(100))}],
        'queries': [{'student_id': 's', 'query': 'shared', 'top_k': 100,
                     'expected_status': 'no_result', 'relevant_source_ids': []}],
    }), encoding='utf-8')
    result = evaluate_student_vector_fixture(fixture)
    assert result['case_results'][0]['retrieved_source_ids'] == []
    assert result['status_mismatch_count'] == 0
