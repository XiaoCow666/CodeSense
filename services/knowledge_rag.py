"""Bounded, assignment-scoped knowledge retrieval for student answers.

This is an explicit-evidence baseline, not a vector database.  It reads only
the knowledge points attached to the current assignment and returns stable,
non-sensitive citations plus a deterministic no-result state.  Keeping the
retriever here makes a future index interchangeable without changing the
student-facing answer route.
"""

from __future__ import annotations

import logging
import re
import time
from html import escape

from models import AssignmentKnowledgePoint, KnowledgePointScore, db


MAX_EVIDENCE = 8
logger = logging.getLogger(__name__)
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]{}()#+.!|>~-])")
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


def _safe_markdown_label(value):
    """Escape a knowledge label before inserting it into Markdown output."""

    escaped = escape(str(value or ""), quote=True)
    return _MARKDOWN_SPECIAL.sub(r"\\\1", escaped)


def _result(status, evidence, candidate_count, started_at, fallback=None):
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
    }
    return {
        "status": status,
        "evidence": evidence,
        "metrics": metrics,
        "fallback": fallback,
    }


def retrieve_assignment_knowledge(assignment_id, *, limit=MAX_EVIDENCE):
    """Retrieve bounded, explicit knowledge evidence for one assignment.

    The retrieval is intentionally assignment-scoped and does not inspect a
    student's private ``KnowledgePointScore`` rows.  Evidence order follows
    the teacher/AI-maintained weight and then the stable row id.
    """

    started_at = time.perf_counter()
    try:
        assignment_id = int(assignment_id)
    except (TypeError, ValueError):
        return _result("no_result", [], 0, started_at, NO_KNOWLEDGE_EVIDENCE.copy())

    try:
        bounded_limit = max(1, min(int(limit), MAX_EVIDENCE))
        records = (
            AssignmentKnowledgePoint.query
            .filter_by(assignment_id=assignment_id)
            .order_by(
                AssignmentKnowledgePoint.weight.desc(),
                AssignmentKnowledgePoint.id.asc(),
            )
            .limit(bounded_limit)
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
        )

    evidence = []
    for record in records:
        code = str(record.knowledge_point or "").strip()
        if not code:
            continue
        name = KnowledgePointScore.KNOWLEDGE_POINTS.get(code, code)
        evidence.append({
            "evidence_id": f"assignment-kp:{record.id}",
            "citation": f"[K{len(evidence) + 1}]",
            "source_type": "assignment_knowledge_point",
            "title": name,
            "content": f"当前作业显式绑定知识点：{name}（{code}）。",
            "created_at": _created_at_value(record),
        })

    if not evidence:
        return _result("no_result", [], len(records), started_at, NO_KNOWLEDGE_EVIDENCE.copy())
    return _result("grounded", evidence, len(records), started_at)


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
        f"- {item['citation']} {_safe_markdown_label(item['title'])}"
        for item in retrieval.get("evidence", [])
    )
    return "\n".join(lines)
