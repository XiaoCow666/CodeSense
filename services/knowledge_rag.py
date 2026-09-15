"""Bounded, assignment-scoped knowledge retrieval for student answers.

This is an explicit-evidence, request-scoped vector prototype, not a
persistent vector database.  It reads only the knowledge points attached to
the current assignment and returns stable, non-sensitive citations plus a
deterministic fallback state.  Keeping the index adapter here makes a future
persistent implementation interchangeable without changing the student-facing
answer route.
"""

from __future__ import annotations

import logging
import time

from models import AssignmentKnowledgePoint, KnowledgePointScore, db
from services.knowledge_pipeline import KnowledgeDocument, build_offline_pipeline
from services.knowledge_vector_store import HybridKnowledgeIndex, NgramCountEmbedder


MAX_EVIDENCE = 8
MAX_INDEX_DOCUMENTS = 64
logger = logging.getLogger(__name__)
knowledge_pipeline = build_offline_pipeline()
knowledge_vector_embedder = NgramCountEmbedder()
NO_KNOWLEDGE_EVIDENCE = {
    "code": "NO_KNOWLEDGE_EVIDENCE",
    "message": "当前作业没有已标注知识点，回答仅基于题目和代码。",
}
RETRIEVAL_UNAVAILABLE = {
    "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
    "message": "知识证据暂时不可用，回答仅基于题目和代码。",
}


def _created_at_value(record):
    created_at = getattr(record, "created_at", None)
    return created_at.isoformat() if created_at else None


def _result(
    status,
    evidence,
    candidate_count,
    started_at,
    fallback=None,
    *,
    retrieval_mode=None,
    indexed_chunk_count=0,
):
    hit_count = len(evidence)
    latency_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
    metrics = {
        "candidate_count": int(candidate_count),
        "hit_count": hit_count,
        "retrieval_hit_rate": round(hit_count / candidate_count, 3)
        if candidate_count
        else 0.0,
        "retrieval_latency_ms": round(latency_ms, 2),
        "citation_completeness": round(
            sum(1 for item in evidence if item.get("evidence_id") and item.get("citation"))
            / hit_count,
            3,
        ) if hit_count else 0.0,
        "no_result_fallback": bool(
            fallback and fallback.get("code") == NO_KNOWLEDGE_EVIDENCE["code"]
        ),
        "retrieval_error_fallback": bool(
            fallback and fallback.get("code") == RETRIEVAL_UNAVAILABLE["code"]
        ),
        "retrieval_mode": retrieval_mode or ("unavailable" if fallback else "unknown"),
        "indexed_chunk_count": int(indexed_chunk_count),
    }
    return {
        "status": status,
        "evidence": evidence,
        "metrics": metrics,
        "fallback": fallback,
    }


def retrieve_assignment_knowledge(
    assignment_id,
    *,
    limit=MAX_EVIDENCE,
    query="",
):
    """Retrieve bounded, explicit knowledge evidence for one assignment.

    The retrieval is intentionally assignment-scoped and does not inspect a
    student's private ``KnowledgePointScore`` rows.  With a query, the
    replaceable offline index first scores sparse-vector overlap, then tries a
    title/body keyword fallback, and finally uses the teacher/AI-maintained
    weight and stable row ID for the legacy priority fallback.  An empty query
    preserves priority order.
    """

    started_at = time.perf_counter()
    try:
        assignment_id = int(assignment_id)
    except (TypeError, ValueError):
        return _result(
            "no_result",
            [],
            0,
            started_at,
            NO_KNOWLEDGE_EVIDENCE.copy(),
            retrieval_mode="no_result",
        )

    try:
        bounded_limit = max(1, min(int(limit), MAX_EVIDENCE))
        records = (
            AssignmentKnowledgePoint.query
            .filter_by(assignment_id=assignment_id)
            .order_by(
                AssignmentKnowledgePoint.weight.desc(),
                AssignmentKnowledgePoint.id.asc(),
            )
            .limit(MAX_INDEX_DOCUMENTS)
            .all()
        )
    except Exception:
        db.session.rollback()
        logger.exception(
            "knowledge evidence retrieval failed; using safe answer-only fallback"
        )
        return _result(
            "unavailable",
            [],
            0,
            started_at,
            RETRIEVAL_UNAVAILABLE.copy(),
            retrieval_mode="unavailable",
        )

    documents = []
    for record in records:
        code = str(record.knowledge_point or "").strip()
        if not code:
            continue
        name = KnowledgePointScore.KNOWLEDGE_POINTS.get(code, code)
        documents.append(
            KnowledgeDocument(
                document_id=f"assignment-kp:{record.id}",
                title=name,
                content=f"当前作业显式绑定知识点：{name}（{code}）。",
                source_type="assignment_knowledge_point",
                priority=float(record.weight or 0.0),
                metadata={
                    "created_at": _created_at_value(record),
                    "evidence_id": f"assignment-kp:{record.id}",
                    "record_id": record.id,
                },
            )
        )

    try:
        chunks = tuple(
            chunk
            for document in documents
            for chunk in knowledge_pipeline.chunker.split(document)
        )
        index = HybridKnowledgeIndex(
            chunks,
            embedder=knowledge_vector_embedder,
        )
        search_result = index.search(query, top_k=bounded_limit)
        citations = tuple(
            knowledge_pipeline.citation_builder.build(candidate, rank)
            for rank, candidate in enumerate(search_result.candidates, start=1)
        )
    except Exception:
        db.session.rollback()
        logger.exception(
            "knowledge vector index failed; using safe answer-only fallback"
        )
        return _result(
            "unavailable",
            [],
            len(records),
            started_at,
            RETRIEVAL_UNAVAILABLE.copy(),
            retrieval_mode="unavailable",
        )
    evidence = [
        {
            "evidence_id": citation.evidence_id,
            "citation": citation.citation,
            "source_type": citation.source_type,
            "title": citation.title,
            "content": citation.content,
            "created_at": citation.metadata.get("created_at"),
        }
        for citation in citations
    ]

    if not evidence:
        return _result(
            "no_result",
            [],
            len(records),
            started_at,
            NO_KNOWLEDGE_EVIDENCE.copy(),
            retrieval_mode=search_result.mode,
            indexed_chunk_count=search_result.indexed_chunk_count,
        )
    return _result(
        "grounded",
        evidence,
        len(records),
        started_at,
        retrieval_mode=search_result.mode,
        indexed_chunk_count=search_result.indexed_chunk_count,
    )


def build_knowledge_prompt_context(retrieval):
    """Create a bounded prompt section that makes citation limits explicit."""

    if retrieval.get("status") != "grounded":
        fallback = retrieval.get("fallback") or NO_KNOWLEDGE_EVIDENCE
        return fallback["message"] + " 不要编造知识库引用。"

    lines = [
        "以下是当前作业已检索到的知识证据。只能使用这些证据，不要扩展为未提供的资料；引用时使用对应标记："
    ]
    lines.extend(
        f"{item['citation']} {item['content']}"
        for item in retrieval.get("evidence", [])
    )
    return "\n".join(lines)


def render_knowledge_receipt(retrieval):
    """Render a deterministic evidence receipt for the final student answer."""

    if retrieval.get("status") != "grounded":
        fallback = retrieval.get("fallback") or NO_KNOWLEDGE_EVIDENCE
        return f"\n\n> 知识证据回退：{fallback['message']}"

    lines = ["\n\n### 参考知识证据"]
    lines.extend(
        f"- {item['citation']} {item['title']}"
        for item in retrieval.get("evidence", [])
    )
    return "\n".join(lines)
