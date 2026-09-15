"""Fixed, offline evaluation for the stage 12 knowledge retrieval prototype."""

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
    return documents, tuple(payload["queries"])


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1))]


def evaluate_fixture(path: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Run the fixed query set and report recall, modes, and latency."""

    documents, queries = load_fixture(path)
    by_id = {document.document_id: document for document in documents}
    chunker = ParagraphChunker()
    mode_counts: Counter[str] = Counter()
    latencies = []
    recall_at_1_hits = 0
    recall_at_k_hits = 0
    relevant_case_count = 0
    total_indexed_chunks = 0

    for case in queries:
        scoped_ids = case.get("document_ids")
        scoped_documents = (
            [by_id[item] for item in scoped_ids if item in by_id]
            if scoped_ids is not None
            else list(documents)
        )
        chunks = tuple(
            chunk
            for document in scoped_documents
            for chunk in chunker.split(document)
        )
        index = HybridKnowledgeIndex(chunks)
        total_indexed_chunks += index.indexed_chunk_count
        started_at = time.perf_counter()
        result = index.search(case["query"], top_k=int(case.get("top_k", 3)))
        latencies.append((time.perf_counter() - started_at) * 1000.0)
        mode_counts[result.mode] += 1

        actual_ids = [candidate.chunk.document_id for candidate in result.candidates]
        expected_ids = set(case.get("relevant_document_ids", []))
        if not expected_ids:
            continue
        relevant_case_count += 1
        if actual_ids and actual_ids[0] in expected_ids:
            recall_at_1_hits += 1
        if expected_ids.intersection(actual_ids):
            recall_at_k_hits += 1

    return {
        "query_count": len(queries),
        "relevant_query_count": relevant_case_count,
        "recall_at_1": round(recall_at_1_hits / relevant_case_count, 3)
        if relevant_case_count
        else 0.0,
        "recall_at_k": round(recall_at_k_hits / relevant_case_count, 3)
        if relevant_case_count
        else 0.0,
        "mode_counts": dict(sorted(mode_counts.items())),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 3)
        if latencies
        else 0.0,
        "p95_latency_ms": round(_p95(latencies), 3),
        "indexed_chunks_total": total_indexed_chunks,
    }


def main() -> None:
    print(json.dumps(evaluate_fixture(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
