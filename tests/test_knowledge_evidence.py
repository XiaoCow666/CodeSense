import math

import pytest

from services.knowledge_evidence import (
    build_knowledge_evidence_view,
    build_public_knowledge_retrieval,
)


def test_public_retrieval_keeps_compatibility_shape_without_internal_fields():
    public = build_public_knowledge_retrieval(
        {
            "status": "grounded",
            "evidence": [
                {
                    "evidence_id": "assignment-kp:7",
                    "citation": "[K1]",
                    "source_type": "assignment_knowledge_point",
                    "title": "数组边界",
                    "content": "证据正文",
                    "private_score": 99,
                }
            ],
            "metrics": {
                "candidate_count": 2,
                "hit_count": 1,
                "retrieval_mode": "vector",
                "private_metric": "drop me",
            },
            "fallback": None,
            "private_prompt": "must not cross the response boundary",
        }
    )

    assert public["status"] == "grounded"
    assert public["evidence"][0]["citation"] == "[K1]"
    assert public["evidence"][0]["source_type"] == "assignment_knowledge_point"
    assert "private_score" not in repr(public)
    assert "private_metric" not in repr(public)
    assert "private_prompt" not in repr(public)


def test_grounded_view_keeps_only_safe_evidence_fields():
    retrieval = {
        "status": "grounded",
        "evidence": [
            {
                "evidence_id": "assignment-kp:7",
                "citation": "[K1]",
                "source_type": "assignment_knowledge_point",
                "title": "数组边界",
                "content": "当前作业显式绑定知识点：数组边界（array）。",
                "created_at": "2026-09-16T08:00:00",
                "private_score": 99,
                "unexpected": "must not cross the projection boundary",
            }
        ],
        "metrics": {
            "candidate_count": 2,
            "hit_count": 1,
            "indexed_chunk_count": 2,
            "retrieval_latency_ms": 4.5,
            "retrieval_mode": "vector",
            "private_metric": "drop me",
        },
        "fallback": None,
        "raw_prompt": "do not expose this",
    }

    view = build_knowledge_evidence_view(retrieval)

    assert view["status"] == "grounded"
    assert view["status_label"] == "已找到作业知识证据"
    assert view["has_evidence"] is True
    assert view["fallback_code"] is None
    assert view["retrieval_mode"] == "vector"
    assert set(view["evidence"][0]) == {
        "evidence_id",
        "citation",
        "title",
        "content",
        "source_label",
        "created_at",
    }
    assert view["evidence"][0] == {
        "evidence_id": "assignment-kp:7",
        "citation": "[K1]",
        "title": "数组边界",
        "content": "当前作业显式绑定知识点：数组边界（array）。",
        "source_label": "作业知识点",
        "created_at": "2026-09-16T08:00:00",
    }
    assert "private_score" not in repr(view)
    assert "raw_prompt" not in repr(view)


@pytest.mark.parametrize(
    "retrieval",
    [
        {"status": "no_result", "evidence": []},
        {"status": "grounded"},
        {"status": "grounded", "evidence": []},
    ],
)
def test_missing_or_empty_evidence_is_safe_no_result(retrieval):
    view = build_knowledge_evidence_view(retrieval)

    assert view["status"] == "no_result"
    assert view["has_evidence"] is False
    assert view["evidence"] == []
    assert view["fallback_code"] == "NO_KNOWLEDGE_EVIDENCE"
    assert "暂无匹配证据" in view["status_label"]


def test_unavailable_preserves_only_the_known_fallback_code():
    view = build_knowledge_evidence_view(
        {
            "status": "unavailable",
            "evidence": [],
            "fallback": {
                "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
                "message": "database details must not be displayed",
            },
            "metrics": {"retrieval_mode": "unavailable"},
        }
    )

    assert view["status"] == "unavailable"
    assert view["fallback_code"] == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    assert view["has_evidence"] is False
    assert "暂时不可用" in view["summary"]
    assert "稍后重试" in view["next_step"]


@pytest.mark.parametrize("audience", ["teacher", "admin"])
def test_teacher_and_admin_receive_bounded_diagnostics(audience):
    view = build_knowledge_evidence_view(
        {
            "status": "grounded",
            "evidence": [
                {
                    "evidence_id": "assignment-kp:1",
                    "citation": "[K1]",
                    "title": "指针",
                    "content": "指针内容",
                    "source_type": "assignment_knowledge_point",
                }
            ],
            "metrics": {
                "candidate_count": 3,
                "hit_count": 1,
                "indexed_chunk_count": 3,
                "retrieval_latency_ms": 2.25,
                "retrieval_mode": "keyword_fallback",
            },
        },
        audience=audience,
    )

    assert view["diagnostics"] == {
        "candidate_count": 3,
        "hit_count": 1,
        "indexed_chunk_count": 3,
        "retrieval_latency_ms": 2.25,
        "retrieval_mode": "keyword_fallback",
    }


def test_student_does_not_receive_diagnostics():
    view = build_knowledge_evidence_view(
        {
            "status": "grounded",
            "evidence": [
                {
                    "evidence_id": "assignment-kp:1",
                    "citation": "[K1]",
                    "title": "递归",
                    "content": "递归内容",
                    "source_type": "assignment_knowledge_point",
                }
            ],
            "metrics": {
                "candidate_count": 4,
                "hit_count": 1,
                "indexed_chunk_count": 4,
                "retrieval_latency_ms": 1.0,
                "retrieval_mode": "vector",
            },
        },
        audience="student",
    )

    assert "diagnostics" not in view


def test_malformed_counts_latency_and_mode_cannot_leak_or_become_invalid():
    view = build_knowledge_evidence_view(
        {
            "status": "unexpected-private-status",
            "evidence": [
                {
                    "evidence_id": "private-id",
                    "citation": "private-citation",
                    "title": "private-title",
                    "content": "private-content",
                    "source_type": "private_score",
                }
            ],
            "fallback": {
                "code": "PRIVATE_ERROR_CODE",
                "message": "private exception details",
            },
            "metrics": {
                "candidate_count": -3,
                "hit_count": "private-hit-count",
                "indexed_chunk_count": -1,
                "retrieval_latency_ms": math.inf,
                "retrieval_mode": "private-mode",
            },
        },
        audience="teacher",
    )

    assert view["status"] == "unknown"
    assert view["status_label"] == "证据状态不可用"
    assert view["evidence"] == []
    assert view["fallback_code"] is None
    assert view["retrieval_mode"] == "unknown"
    assert view["diagnostics"] == {
        "candidate_count": 0,
        "hit_count": 0,
        "indexed_chunk_count": 0,
        "retrieval_latency_ms": 0.0,
        "retrieval_mode": "unknown",
    }
    assert "private" not in repr(view)


def test_text_and_fallback_copy_are_plain_strings_not_html():
    view = build_knowledge_evidence_view(
        {
            "status": "grounded",
            "evidence": [
                {
                    "evidence_id": "assignment-kp:2",
                    "citation": "[K1]",
                    "title": "<b>数组</b>",
                    "content": "<script>alert('xss')</script>",
                    "source_type": "assignment_knowledge_point",
                    "created_at": None,
                }
            ],
        }
    )

    assert type(view["evidence"][0]["title"]) is str
    assert type(view["evidence"][0]["content"]) is str
    assert view["evidence"][0]["title"] == "<b>数组</b>"
    assert view["evidence"][0]["content"] == "<script>alert('xss')</script>"
    assert type(view["summary"]) is str
    assert type(view["next_step"]) is str
    assert "<" not in view["summary"]
    assert "<" not in view["next_step"]


def test_missing_retrieval_uses_unknown_state_without_raw_fallback():
    view = build_knowledge_evidence_view(None, audience="teacher")

    assert view["status"] == "unknown"
    assert view["has_evidence"] is False
    assert view["evidence"] == []
    assert view["fallback_code"] is None
    assert view["diagnostics"]["retrieval_mode"] == "unknown"
