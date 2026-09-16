"""Build safe, role-aware views of assignment knowledge evidence.

The retrieval service returns an internal dictionary that is useful for
prompting and diagnostics.  This module deliberately exposes a smaller,
stable shape for templates and browser code.  It does not render HTML and it
does not read private knowledge-point scores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


MAX_EVIDENCE = 8
MAX_CANDIDATES = 64
MAX_INDEXED_CHUNKS = 64
MAX_LATENCY_MS = 600_000.0

_ALLOWED_STATUSES = frozenset({"grounded", "no_result", "unavailable"})
_ALLOWED_AUDIENCES = frozenset({"teacher", "admin"})
_ALLOWED_RETRIEVAL_MODES = frozenset(
    {
        "vector",
        "keyword_fallback",
        "priority_fallback",
        "no_result",
        "unavailable",
        "unknown",
    }
)
_SOURCE_LABELS = {
    "assignment_knowledge_point": "作业知识点",
}
_DEFAULT_SOURCE_LABEL = "作业知识证据"
_FALLBACK_CODES = {
    "no_result": "NO_KNOWLEDGE_EVIDENCE",
    "unavailable": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
}
_FALLBACK_MESSAGES = {
    "no_result": "当前作业没有已标注知识点，回答仅基于题目和代码。",
    "unavailable": "知识证据暂时不可用，回答仅基于题目和代码。",
}
_STATUS_COPY = {
    "grounded": {
        "status_label": "已找到作业知识证据",
        "summary": "已找到与当前作业相关的知识证据。",
        "next_step": "展开证据详情，把问题与对应概念联系起来。",
    },
    "no_result": {
        "status_label": "暂无匹配证据",
        "summary": "当前问题暂无可引用的作业知识证据。",
        "next_step": "缩小问题，或查看作业知识焦点后继续提问。",
    },
    "unavailable": {
        "status_label": "证据暂时不可用",
        "summary": "知识证据暂时不可用，但基础指导仍可继续。",
        "next_step": "继续查看基础指导，稍后重试证据检索。",
    },
    "unknown": {
        "status_label": "证据状态不可用",
        "summary": "当前无法确认知识证据状态。",
        "next_step": "继续使用基础指导，稍后重试。",
    },
}


def _safe_text(value: Any, *, limit: int, default: str = "") -> str:
    """Return bounded input text without preserving arbitrary object reprs."""

    if not isinstance(value, str):
        return default
    return value.strip()[:limit]


def _safe_created_at(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()[:64]
        return value or None

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            formatted = isoformat()
        except Exception:
            return None
        if isinstance(formatted, str):
            return formatted.strip()[:64] or None
    return None


def _safe_nonnegative_int(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(max(number, 0), maximum)


def _safe_nonnegative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(min(max(number, 0.0), MAX_LATENCY_MS), 2)


def _safe_retrieval_mode(value: Any, *, default: str = "unknown") -> str:
    if isinstance(value, str) and value in _ALLOWED_RETRIEVAL_MODES:
        return value
    return default


def _safe_rate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(min(max(number, 0.0), 1.0), 3)


def _project_evidence(raw_evidence: Any) -> list[dict[str, str | None]]:
    if not isinstance(raw_evidence, (list, tuple)):
        return []

    projected: list[dict[str, str | None]] = []
    for raw_item in raw_evidence[:MAX_EVIDENCE]:
        if not isinstance(raw_item, Mapping):
            continue

        evidence_id = _safe_text(raw_item.get("evidence_id"), limit=128)
        citation = _safe_text(raw_item.get("citation"), limit=32)
        if not evidence_id or not citation:
            continue

        source_type = _safe_text(raw_item.get("source_type"), limit=64)
        projected.append(
            {
                "evidence_id": evidence_id,
                "citation": citation,
                "title": _safe_text(raw_item.get("title"), limit=240),
                "content": _safe_text(raw_item.get("content"), limit=1200),
                "source_label": _SOURCE_LABELS.get(
                    source_type,
                    _DEFAULT_SOURCE_LABEL,
                ),
                "created_at": _safe_created_at(raw_item.get("created_at")),
            }
        )
    return projected


def build_public_knowledge_retrieval(
    retrieval: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep the legacy retrieval envelope while removing internal fields.

    The retrieval service is also used as an internal prompt/diagnostic
    boundary, so callers must not serialize its mapping directly.  This
    compatibility projection retains the established top-level names and
    metric types while allowing only bounded evidence, fallback, and metric
    fields to cross into a browser response.
    """

    if not isinstance(retrieval, Mapping):
        retrieval = None

    raw_status = retrieval.get("status") if retrieval else None
    status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in _ALLOWED_STATUSES
        else "unknown"
    )
    evidence = _project_evidence(
        retrieval.get("evidence") if retrieval else None
    ) if status == "grounded" else []
    if status == "grounded" and not evidence:
        status = "no_result"

    raw_metrics = retrieval.get("metrics") if retrieval else None
    metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}
    if status == "unknown":
        retrieval_mode = "unknown"
    elif status == "unavailable":
        retrieval_mode = "unavailable"
    else:
        retrieval_mode = _safe_retrieval_mode(metrics.get("retrieval_mode"))

    fallback_code = _fallback_code(retrieval, status=status)
    fallback = None
    if fallback_code:
        raw_fallback = retrieval.get("fallback") if retrieval else None
        raw_message = (
            raw_fallback.get("message")
            if isinstance(raw_fallback, Mapping)
            else None
        )
        fallback = {
            "code": fallback_code,
            "message": _safe_text(
                raw_message,
                limit=240,
                default=_FALLBACK_MESSAGES[status],
            ),
        }

    return {
        "status": status,
        "evidence": evidence,
        "metrics": {
            "candidate_count": _safe_nonnegative_int(
                metrics.get("candidate_count"),
                maximum=MAX_CANDIDATES,
            ),
            "hit_count": _safe_nonnegative_int(
                metrics.get("hit_count"),
                maximum=MAX_EVIDENCE,
            ),
            "retrieval_hit_rate": _safe_rate(metrics.get("retrieval_hit_rate")),
            "retrieval_latency_ms": _safe_nonnegative_float(
                metrics.get("retrieval_latency_ms")
            ),
            "citation_completeness": _safe_rate(
                metrics.get("citation_completeness")
            ),
            "no_result_fallback": (
                bool(metrics.get("no_result_fallback"))
                if isinstance(metrics.get("no_result_fallback"), bool)
                else status == "no_result"
            ),
            "retrieval_error_fallback": (
                bool(metrics.get("retrieval_error_fallback"))
                if isinstance(metrics.get("retrieval_error_fallback"), bool)
                else status == "unavailable"
            ),
            "retrieval_mode": retrieval_mode,
            "indexed_chunk_count": _safe_nonnegative_int(
                metrics.get("indexed_chunk_count"),
                maximum=MAX_INDEXED_CHUNKS,
            ),
        },
        "fallback": fallback,
    }


def _fallback_code(retrieval: Mapping[str, Any] | None, *, status: str) -> str | None:
    expected = _FALLBACK_CODES.get(status)
    if expected is None:
        return None

    raw_fallback = retrieval.get("fallback") if retrieval else None
    if isinstance(raw_fallback, Mapping) and raw_fallback.get("code") == expected:
        return expected
    return expected


def build_knowledge_evidence_view(
    retrieval: Mapping[str, Any] | None,
    *,
    audience: str = "student",
) -> dict[str, Any]:
    """Project retrieval output into a bounded view safe for UI consumers.

    Only the three known retrieval states are accepted.  Missing or malformed
    input becomes ``unknown``; a grounded result without usable evidence is
    represented as ``no_result``.  Teacher and admin views include bounded
    operational diagnostics, while student views do not.
    """

    if not isinstance(retrieval, Mapping):
        retrieval = None

    raw_status = retrieval.get("status") if retrieval else None
    status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in _ALLOWED_STATUSES
        else "unknown"
    )

    raw_evidence = retrieval.get("evidence") if retrieval else None
    evidence = _project_evidence(raw_evidence) if status == "grounded" else []
    if status == "grounded" and not evidence:
        status = "no_result"

    metrics = retrieval.get("metrics") if retrieval else None
    if not isinstance(metrics, Mapping):
        metrics = {}

    if status == "unknown":
        retrieval_mode = "unknown"
    elif status == "unavailable":
        retrieval_mode = "unavailable"
    else:
        retrieval_mode = _safe_retrieval_mode(metrics.get("retrieval_mode"))

    copy = _STATUS_COPY[status]
    view: dict[str, Any] = {
        "status": status,
        "status_label": copy["status_label"],
        "summary": copy["summary"],
        "next_step": copy["next_step"],
        "has_evidence": bool(evidence),
        "fallback_code": _fallback_code(retrieval, status=status),
        "retrieval_mode": retrieval_mode,
        "evidence": evidence,
    }

    if isinstance(audience, str) and audience in _ALLOWED_AUDIENCES:
        view["diagnostics"] = {
            "candidate_count": _safe_nonnegative_int(
                metrics.get("candidate_count"),
                maximum=MAX_CANDIDATES,
            ),
            "hit_count": _safe_nonnegative_int(
                metrics.get("hit_count"),
                maximum=MAX_EVIDENCE,
            ),
            "indexed_chunk_count": _safe_nonnegative_int(
                metrics.get("indexed_chunk_count"),
                maximum=MAX_INDEXED_CHUNKS,
            ),
            "retrieval_latency_ms": _safe_nonnegative_float(
                metrics.get("retrieval_latency_ms")
            ),
            "retrieval_mode": retrieval_mode,
        }

    return view
