"""Fixed, offline evaluation for the knowledge retrieval prototype."""

from __future__ import annotations

from collections import Counter
import json
from math import ceil
from pathlib import Path
import time
from typing import Any

from services.knowledge_pipeline import KnowledgeDocument, ParagraphChunker
from services.knowledge_vector_store import HybridKnowledgeIndex


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "knowledge_rag_eval.json"
)


def load_fixture(path: str | Path = DEFAULT_FIXTURE):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    documents = tuple(
        KnowledgeDocument(
            document_id=str(item["document_id"]),
            title=str(item["title"]),
            content=str(item["content"]),
            source_type=str(item.get("source_type", "offline-eval")),
            priority=float(item.get("priority", 0.0)),
            metadata=dict(item.get("metadata", {})),
        )
        for item in payload["documents"]
    )
    return documents, tuple(payload["queries"]), dict(payload.get("performance", {}))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1))]


def _unique_document_ids(candidates, *, limit: int | None = None) -> list[str]:
    """Deduplicate chunk hits before calculating document-level recall."""

    document_ids = []
    seen = set()
    for candidate in candidates:
        document_id = candidate.chunk.document_id
        if document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
        if limit is not None and len(document_ids) >= limit:
            break
    return document_ids


def _build_performance_documents(spec: dict[str, Any]) -> tuple[KnowledgeDocument, ...]:
    """Create a deterministic fixed-size sample without external files."""

    count = max(1, int(spec.get("document_count", 64)))
    return tuple(
        KnowledgeDocument(
            document_id=f"performance-{index:03d}",
            title=f"性能样本 {index:03d}",
            content="固定样本用于边界条件检索和索引性能测量。",
            source_type="offline-performance",
            priority=1.0,
        )
        for index in range(count)
    )


def evaluate_fixture(
    path: str | Path = DEFAULT_FIXTURE,
    *,
    clock=time.perf_counter,
    embedder=None,
) -> dict[str, Any]:
    """Run the fixed query set with an optional replaceable embedder."""

    documents, queries, performance_spec = load_fixture(path)
    by_id = {document.document_id: document for document in documents}
    chunker = ParagraphChunker()
    mode_counts: Counter[str] = Counter()
    build_latencies = []
    query_latencies = []
    total_latencies = []
    recall_at_1_values = []
    recall_at_k_values = []
    relevant_case_count = 0
    total_indexed_chunks = 0
    mode_mismatch_count = 0
    case_results = []

    for case in queries:
        scoped_ids = case.get("document_ids")
        scoped_documents = (
            [by_id[item] for item in scoped_ids if item in by_id]
            if scoped_ids is not None
            else list(documents)
        )
        total_started_at = clock()
        build_started_at = clock()
        chunks = tuple(
            chunk
            for document in scoped_documents
            for chunk in chunker.split(document)
        )
        index = HybridKnowledgeIndex(chunks, embedder=embedder)
        build_latencies.append((clock() - build_started_at) * 1000.0)
        total_indexed_chunks += index.indexed_chunk_count
        query_started_at = clock()
        result = index.search(case["query"], top_k=int(case.get("top_k", 3)))
        query_latencies.append((clock() - query_started_at) * 1000.0)
        total_latencies.append((clock() - total_started_at) * 1000.0)
        mode_counts[result.mode] += 1
        expected_mode = case.get("expected_mode")
        if expected_mode and result.mode != expected_mode:
            mode_mismatch_count += 1

        top_k = int(case.get("top_k", 3))
        actual_ids = _unique_document_ids(result.candidates, limit=top_k)
        expected_ids = set(case.get("relevant_document_ids", []))
        case_result = {
            "query": case["query"],
            "expected_mode": expected_mode,
            "actual_mode": result.mode,
            "retrieved_document_ids": actual_ids,
        }
        if not expected_ids:
            case_result["recall_at_1"] = None
            case_result["recall_at_k"] = None
            case_results.append(case_result)
            continue
        relevant_case_count += 1
        recall_at_1 = len(set(actual_ids[:1]) & expected_ids) / len(expected_ids)
        recall_at_k = len(set(actual_ids[:top_k]) & expected_ids) / len(expected_ids)
        recall_at_1_values.append(recall_at_1)
        recall_at_k_values.append(recall_at_k)
        case_result["recall_at_1"] = round(recall_at_1, 3)
        case_result["recall_at_k"] = round(recall_at_k, 3)
        case_results.append(case_result)

    performance_documents = _build_performance_documents(performance_spec)
    performance_total_started_at = clock()
    performance_build_started_at = clock()
    performance_chunks = tuple(
        chunk
        for document in performance_documents
        for chunk in chunker.split(document)
    )
    performance_index = HybridKnowledgeIndex(performance_chunks, embedder=embedder)
    performance_build_ms = (clock() - performance_build_started_at) * 1000.0
    performance_query_latencies = []
    performance_runs = max(1, int(performance_spec.get("runs", 100)))
    performance_query = str(performance_spec.get("query", "边界条件"))
    performance_top_k = max(1, int(performance_spec.get("top_k", 8)))
    for _ in range(performance_runs):
        query_started_at = clock()
        performance_index.search(performance_query, top_k=performance_top_k)
        performance_query_latencies.append((clock() - query_started_at) * 1000.0)
    performance_total_ms = (clock() - performance_total_started_at) * 1000.0

    result = {
        "query_count": len(queries),
        "relevant_query_count": relevant_case_count,
        "recall_at_1": round(sum(recall_at_1_values) / relevant_case_count, 3)
        if relevant_case_count
        else 0.0,
        "recall_at_k": round(sum(recall_at_k_values) / relevant_case_count, 3)
        if relevant_case_count
        else 0.0,
        "mode_counts": dict(sorted(mode_counts.items())),
        "expected_mode_mismatch_count": mode_mismatch_count,
        "mean_build_latency_ms": round(sum(build_latencies) / len(build_latencies), 3)
        if build_latencies
        else 0.0,
        "p95_build_latency_ms": round(_p95(build_latencies), 3),
        "mean_query_latency_ms": round(sum(query_latencies) / len(query_latencies), 3)
        if query_latencies
        else 0.0,
        "p95_query_latency_ms": round(_p95(query_latencies), 3),
        "mean_total_latency_ms": round(sum(total_latencies) / len(total_latencies), 3)
        if total_latencies
        else 0.0,
        "p95_total_latency_ms": round(_p95(total_latencies), 3),
        "indexed_chunks_total": total_indexed_chunks,
        "case_results": case_results,
        "performance_sample": {
            "document_count": len(performance_documents),
            "chunk_count": len(performance_chunks),
            "runs": performance_runs,
            "top_k": performance_top_k,
            "build_ms": round(performance_build_ms, 3),
            "query_mean_ms": round(sum(performance_query_latencies) / performance_runs, 3),
            "query_p95_ms": round(_p95(performance_query_latencies), 3),
            "total_ms": round(performance_total_ms, 3),
            "total_per_run_ms": round(
                performance_total_ms / performance_runs,
                3,
            ),
        },
    }
    if embedder is not None and hasattr(embedder, "snapshot"):
        result["embedding_usage"] = embedder.snapshot()
    return result


def main() -> None:
    print(json.dumps(evaluate_fixture(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
