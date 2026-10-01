import itertools
import json

from services.knowledge_eval import evaluate_fixture


def test_fixed_knowledge_eval_reports_vector_fallback_and_no_result_modes():
    metrics = evaluate_fixture()

    assert metrics["query_count"] == 5
    assert metrics["relevant_query_count"] == 4
    assert metrics["recall_at_1"] == 0.875
    assert metrics["recall_at_k"] == 0.875
    assert metrics["mode_counts"] == {
        "keyword_fallback": 1,
        "no_result": 1,
        "vector": 3,
    }
    assert metrics["expected_mode_mismatch_count"] == 0
    assert metrics["mean_build_latency_ms"] >= 0
    assert metrics["mean_query_latency_ms"] >= 0
    assert metrics["mean_total_latency_ms"] >= metrics["mean_query_latency_ms"]
    assert metrics["performance_sample"]["document_count"] == 64
    assert metrics["performance_sample"]["chunk_count"] == 64
    assert metrics["case_results"][-1]["retrieved_document_ids"] == [
        "array-boundary"
    ]
    assert metrics["case_results"][-1]["recall_at_k"] == 0.5


def _write_fixture(tmp_path, documents, queries):
    path = tmp_path / "knowledge_eval.json"
    path.write_text(
        json.dumps(
            {
                "documents": documents,
                "queries": queries,
                "performance": {"document_count": 1, "runs": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_recall_uses_relevant_document_denominator(tmp_path):
    path = _write_fixture(
        tmp_path,
        [
            {
                "document_id": "array",
                "title": "数组",
                "content": "数组边界。",
            },
            {
                "document_id": "pointer",
                "title": "指针",
                "content": "指针生命周期。",
            },
        ],
        [
            {
                "query": "数组",
                "relevant_document_ids": ["array", "pointer"],
                "expected_mode": "vector",
                "top_k": 1,
            }
        ],
    )

    metrics = evaluate_fixture(path)

    assert metrics["recall_at_1"] == 0.5
    assert metrics["recall_at_k"] == 0.5


def test_recall_deduplicates_multiple_chunks_from_one_document(tmp_path):
    path = _write_fixture(
        tmp_path,
        [
            {
                "document_id": "long-array",
                "title": "数组",
                "content": " ".join("数组边界。" for _ in range(100)),
            },
            {
                "document_id": "pointer",
                "title": "指针",
                "content": "指针生命周期。",
            },
        ],
        [
            {
                "query": "数组",
                "relevant_document_ids": ["long-array", "pointer"],
                "expected_mode": "vector",
                "top_k": 3,
            }
        ],
    )

    metrics = evaluate_fixture(path)

    assert metrics["recall_at_k"] == 0.5
    assert metrics["case_results"][0]["retrieved_document_ids"] == ["long-array"]


def test_evaluation_total_latency_includes_index_build_time():
    ticks = itertools.count()

    def fake_clock():
        return next(ticks) / 1000

    metrics = evaluate_fixture(clock=fake_clock)

    assert metrics["mean_build_latency_ms"] > 0
    assert metrics["mean_total_latency_ms"] > metrics["mean_query_latency_ms"]
