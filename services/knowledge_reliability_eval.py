"""Repeatable local capacity and index-lifecycle drill for stage 13."""

from __future__ import annotations

import json
import time

from services.knowledge_pipeline import KnowledgeDocument, ParagraphChunker
from services.knowledge_reliability import VersionedKnowledgeIndex


def _documents(count: int) -> tuple[KnowledgeDocument, ...]:
    return tuple(
        KnowledgeDocument(
            document_id=f"capacity-{index:03d}",
            title=f"容量样本 {index:03d}",
            content="固定样本用于边界条件检索和增量索引演练。",
            source_type="offline-capacity",
            priority=1.0,
        )
        for index in range(max(1, int(count)))
    )


def _chunks(documents):
    chunker = ParagraphChunker()
    return tuple(
        chunk
        for document in documents
        for chunk in chunker.split(document)
    )


def run_drill(*, document_count: int = 64, runs: int = 1000) -> dict:
    documents = _documents(document_count)
    chunks = _chunks(documents)
    started_at = time.perf_counter()
    index = VersionedKnowledgeIndex(chunks)
    build_ms = (time.perf_counter() - started_at) * 1000.0

    query_started_at = time.perf_counter()
    for _ in range(max(1, int(runs))):
        index.search("边界条件", top_k=8)
    query_ms = (time.perf_counter() - query_started_at) * 1000.0

    updated_document = KnowledgeDocument(
        document_id="capacity-000",
        title="容量样本 000（更新）",
        content="更新后的样本用于增量索引和版本回滚演练。",
        source_type="offline-capacity",
        priority=2.0,
    )
    updated_revision = index.upsert(
        _chunks((updated_document,)),
        remove_document_ids=("capacity-000",),
    )
    rolled_back_revision = index.rollback()

    return {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "query_runs": max(1, int(runs)),
        "build_ms": round(build_ms, 3),
        "query_total_ms": round(query_ms, 3),
        "query_mean_ms": round(query_ms / max(1, int(runs)), 3),
        "updated_revision": updated_revision.number,
        "rolled_back_revision": rolled_back_revision.number if rolled_back_revision else None,
        "final_revision": index.revision.number,
        "final_chunk_count": index.indexed_chunk_count,
        "rollback_history_depth": index.history_depth,
    }


def main() -> None:
    print(json.dumps(run_drill(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
