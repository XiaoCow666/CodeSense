"""学生私有学习来源的版本化稀疏向量索引。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from datetime import datetime as dt, timedelta

from sqlalchemy import and_, or_

from models import (
    Assignment,
    AssignmentKnowledgePoint,
    KnowledgePointScore,
    StudentLearningVector,
    StudentVectorIndexState,
    StudentVectorRetrievalLog,
    Submission,
    User,
    db,
)
from services.knowledge_reliability import KnowledgePrivacyFilter
from services.knowledge_vector_store import NgramCountEmbedder


MAX_SUBMISSION_SOURCES = 24
MAX_CONTENT_LENGTH = 1200
MAX_RESULTS = 5
MIN_SIMILARITY = 0.2
MAX_SOURCE_PROJECTION = 100
SOURCE_VERSION_DISPLAY_LENGTH = 12
INDEX_STALE_AFTER_DAYS = 30
ACTIVE = "active"
REVOKED = "revoked"
STUDENT_SCOPE = "student_private"


class StudentVectorAccessError(PermissionError):
    """学生向量请求越过身份或作用域边界。"""


class StudentVectorRebuildError(RuntimeError):
    """学生向量重建失败，但上一版索引仍然保留。"""


@dataclass(frozen=True)
class _StudentSource:
    source_type: str
    source_id: str
    assignment_id: int | None
    title: str
    content: str
    source_version: str


def _student_id(value) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise StudentVectorAccessError("student scope is invalid")
    student = db.session.get(User, normalized)
    if student is None or student.usertype != "学生":
        raise StudentVectorAccessError("student scope is unavailable")
    return normalized


def _normalise_text(value, *, limit=MAX_CONTENT_LENGTH) -> str:
    text = " ".join(str(value or "").split())
    text = KnowledgePrivacyFilter.redact(text)
    return text[:limit].strip()


def _source_version(source_type, source_id, assignment_id, title, content) -> str:
    payload = "|".join(
        [
            source_type,
            source_id,
            str(assignment_id or ""),
            title,
            content,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_source(source_type, source_id, assignment_id, title, content):
    safe_title = _normalise_text(title, limit=255)
    safe_content = _normalise_text(content)
    if not safe_content:
        return None
    return _StudentSource(
        source_type=source_type,
        source_id=source_id,
        assignment_id=assignment_id,
        title=safe_title,
        content=safe_content,
        source_version=_source_version(
            source_type,
            source_id,
            assignment_id,
            safe_title,
            safe_content,
        ),
    )


def _submission_sources(student_id: str):
    rows = (
        Submission.query.filter_by(student_id=student_id, status="evaluated")
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(MAX_SUBMISSION_SOURCES)
        .all()
    )
    sources = []
    for submission in rows:
        feedback = _normalise_text(submission.feedback)
        ai_feedback = _normalise_text(submission.ai_feedback)
        if not feedback and not ai_feedback:
            continue
        assignment = db.session.get(Assignment, submission.assignment_id)
        title = assignment.title if assignment else f"作业 {submission.assignment_id}"
        pieces = [f"作业：{title}"]
        if feedback:
            pieces.append(f"评测反馈：{feedback}")
        if ai_feedback:
            pieces.append(f"AI 反馈：{ai_feedback}")
        source = _make_source(
            "submission_feedback",
            f"submission:{submission.id}",
            submission.assignment_id,
            title,
            "；".join(pieces),
        )
        if source:
            sources.append(source)
    return sources


def _knowledge_score_sources(student_id: str):
    rows = KnowledgePointScore.query.filter_by(student_id=student_id).order_by(
        KnowledgePointScore.id.asc()
    ).all()
    sources = []
    for score in rows:
        code = str(score.knowledge_point or "").strip()
        if not code:
            continue
        label = KnowledgePointScore.KNOWLEDGE_POINTS.get(code, code)
        content = (
            f"知识点：{label}；当前掌握度：{float(score.score or 0):.1f}/100；"
            f"尝试次数：{int(score.total_attempts or 0)}。"
        )
        source = _make_source(
            "knowledge_point_score",
            f"knowledge-point:{score.id}",
            None,
            label,
            content,
        )
        if source:
            sources.append(source)
    return sources


def _build_sources(student_id: str):
    sources = _submission_sources(student_id) + _knowledge_score_sources(student_id)
    return tuple(
        sorted(
            sources,
            key=lambda source: (
                source.source_type,
                source.assignment_id or 0,
                source.source_id,
            ),
        )
    )


def _embedding_payload(embedder, text: str) -> str:
    embedding = embedder.embed(text)
    normalized = {
        str(key): float(value)
        for key, value in dict(embedding).items()
        if math.isfinite(float(value)) and float(value) > 0
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_key(source_type, source_id, source_version):
    return source_type, source_id, source_version


def _mark_rebuild_failed(student_id: str, error: Exception) -> None:
    state = StudentVectorIndexState.query.filter_by(student_id=student_id).first()
    if state is None:
        state = StudentVectorIndexState(student_id=student_id, revision=0)
        db.session.add(state)
    state.status = "failed"
    state.failure_code = type(error).__name__[:64]
    state.updated_at = dt.utcnow()
    db.session.commit()


def rebuild_student_vector_index(student_id, *, embedder=None):
    """从学生自己的历史来源构建一个新的可检索 revision。"""

    normalized_student_id = _student_id(student_id)
    embedder = embedder or NgramCountEmbedder()
    sources = _build_sources(normalized_student_id)
    try:
        state = StudentVectorIndexState.query.filter_by(
            student_id=normalized_student_id
        ).first()
        next_revision = (state.revision if state else 0) + 1
        existing_rows = StudentLearningVector.query.filter_by(
            student_id=normalized_student_id,
            scope_type=STUDENT_SCOPE,
        ).all()
        existing_by_key = {
            _source_key(row.source_type, row.source_id, row.source_version): row
            for row in existing_rows
        }
        revoked_source_keys = {
            (row.source_type, row.source_id)
            for row in existing_rows
            if row.status == REVOKED and row.revoke_reason == "user_revoked"
        }
        current_keys = set()

        for source in sources:
            key = _source_key(
                source.source_type,
                source.source_id,
                source.source_version,
            )
            current_keys.add(key)
            if (source.source_type, source.source_id) in revoked_source_keys:
                continue
            row = existing_by_key.get(key)
            payload = _embedding_payload(embedder, source.content)
            if row is None:
                row = StudentLearningVector(
                    student_id=normalized_student_id,
                    scope_type=STUDENT_SCOPE,
                    source_type=source.source_type,
                    source_id=source.source_id,
                    source_version=source.source_version,
                    assignment_id=source.assignment_id,
                    source_title=source.title,
                    content=source.content,
                    embedding=payload,
                )
                db.session.add(row)
            else:
                row.scope_type = STUDENT_SCOPE
                row.assignment_id = source.assignment_id
                row.source_title = source.title
                row.content = source.content
                row.embedding = payload
                row.status = ACTIVE
                row.revoked_at = None
                row.revoke_reason = None
            row.index_revision = next_revision
            row.updated_at = dt.utcnow()

        for row in existing_rows:
            key = _source_key(row.source_type, row.source_id, row.source_version)
            if key not in current_keys and row.status == ACTIVE:
                row.status = REVOKED
                row.revoked_at = dt.utcnow()
                row.revoke_reason = "source_removed"
                row.updated_at = dt.utcnow()

        if state is None:
            state = StudentVectorIndexState(student_id=normalized_student_id)
            db.session.add(state)
        state.revision = next_revision
        state.status = "ready" if sources else "empty"
        state.source_count = StudentLearningVector.query.filter_by(
            student_id=normalized_student_id,
            scope_type=STUDENT_SCOPE,
            status=ACTIVE,
        ).count()
        state.last_built_at = dt.utcnow()
        state.failure_code = None
        state.updated_at = dt.utcnow()
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        _mark_rebuild_failed(normalized_student_id, error)
        raise StudentVectorRebuildError("student vector rebuild failed") from error

    return get_student_vector_snapshot(normalized_student_id)


def _cosine_similarity(left, right) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _index_is_stale(state, *, now=None):
    if state is None or state.status not in {"ready", "failed"}:
        return False
    if not state.last_built_at:
        return False
    now = now or dt.utcnow()
    return now - state.last_built_at > timedelta(days=INDEX_STALE_AFTER_DAYS)


def _student_vector_queries(student_id, assignment_id=None):
    """Build the private base query and its optional assignment projection."""

    base_query = StudentLearningVector.query.filter_by(
        student_id=student_id,
        scope_type=STUDENT_SCOPE,
        status=ACTIVE,
    )
    if assignment_id is None:
        return base_query, base_query, False

    assignment_codes = {
        row.knowledge_point
        for row in AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id
        ).all()
    }
    assignment_labels = {
        KnowledgePointScore.KNOWLEDGE_POINTS.get(code, code)
        for code in assignment_codes
    }
    conditions = [StudentLearningVector.assignment_id == assignment_id]
    if assignment_labels:
        conditions.append(
            and_(
                StudentLearningVector.source_type == "knowledge_point_score",
                StudentLearningVector.source_title.in_(assignment_labels),
            )
        )
    filtered_query = base_query.filter(or_(*conditions))
    return base_query, filtered_query, True


def _retrieval_log(
    student_id,
    assignment_id,
    query,
    result,
    revision,
    *,
    retrieval_mode=None,
    status=None,
):
    digest = hashlib.sha256(str(query or "").encode("utf-8")).hexdigest()
    db.session.add(
        StudentVectorRetrievalLog(
            student_id=student_id,
            assignment_id=assignment_id,
            query_hash=digest,
            result_count=len(result),
            index_revision=revision,
            retrieval_mode=retrieval_mode or ("vector" if result else "no_result"),
            status=status or ("grounded" if result else "no_result"),
        )
    )
    db.session.commit()


def search_student_learning_vectors(
    student_id,
    query,
    *,
    assignment_id=None,
    limit=MAX_RESULTS,
):
    """只在当前学生作用域内查询学习来源。"""

    normalized_student_id = _student_id(student_id)
    bounded_limit = max(1, min(int(limit), MAX_RESULTS))
    state = StudentVectorIndexState.query.filter_by(
        student_id=normalized_student_id
    ).first()
    revision = state.revision if state else 0
    if state is None or (
        state.status not in {"ready", "empty"}
        and not (state.status == "failed" and revision > 0)
    ):
        _retrieval_log(normalized_student_id, assignment_id, query, (), revision)
        return {
            "status": "not_built" if state is None else "unavailable",
            "evidence": [],
            "metrics": {
                "candidate_count": 0,
                "hit_count": 0,
                "retrieval_mode": "not_built" if state is None else "unavailable",
                "index_revision": revision,
                "freshness_status": "unknown",
                "revoked_count": 0,
                "scope_filter": "assignment" if assignment_id is not None else "student",
            },
            "fallback": {
                "code": "STUDENT_VECTOR_INDEX_NOT_READY"
                if state is None
                else "STUDENT_VECTOR_INDEX_UNAVAILABLE",
                "message": "你的学习记录索引还没有准备好。",
            },
        }

    revoked_count = StudentLearningVector.query.filter_by(
        student_id=normalized_student_id,
        scope_type=STUDENT_SCOPE,
        status=REVOKED,
    ).count()
    if _index_is_stale(state):
        _retrieval_log(
            normalized_student_id,
            assignment_id,
            query,
            (),
            revision,
            retrieval_mode="stale",
            status="stale",
        )
        return {
            "status": "stale",
            "evidence": [],
            "metrics": {
                "candidate_count": 0,
                "scope_candidate_count": 0,
                "hit_count": 0,
                "retrieval_mode": "stale",
                "index_revision": revision,
                "freshness_status": "stale",
                "revoked_count": revoked_count,
                "index_status": state.status,
                "scope_filter": "assignment" if assignment_id is not None else "student",
            },
            "fallback": {
                "code": "STUDENT_VECTOR_INDEX_STALE",
                "message": "你的学习记录索引需要更新，请更新后再使用个人学习记录。",
            },
        }

    scope_query, filtered_query, assignment_filter_applied = _student_vector_queries(
        normalized_student_id,
        assignment_id,
    )
    scope_candidate_count = scope_query.count()
    rows = filtered_query.all()
    query_vector = NgramCountEmbedder().embed(query)
    scored = []
    for row in rows:
        embedding = json.loads(row.embedding)
        score = _cosine_similarity(query_vector, embedding)
        if score < MIN_SIMILARITY:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    selected = scored[:bounded_limit]
    evidence = [
        {
            "evidence_id": f"student-vector:{row.id}",
            "citation": f"[L{index}]",
            "source_type": row.source_type,
            "source_id": row.source_id,
            "source_title": row.source_title,
            "title": row.source_title,
            "content": row.content[:360],
            "assignment_id": row.assignment_id,
            "scope": row.scope_type,
            "source_version": row.source_version,
            "index_revision": row.index_revision,
        }
        for index, (_, row) in enumerate(selected, start=1)
    ]
    _retrieval_log(normalized_student_id, assignment_id, query, evidence, revision)
    return {
        "status": "grounded" if evidence else "no_result",
        "evidence": evidence,
        "metrics": {
            "candidate_count": len(rows),
            "scope_candidate_count": scope_candidate_count,
            "hit_count": len(evidence),
            "retrieval_mode": "vector" if evidence else "no_result",
            "index_revision": revision,
            "freshness_status": "fresh",
            "revoked_count": revoked_count,
            "index_status": state.status,
            "scope_filter": "assignment" if assignment_filter_applied else "student",
        },
        "fallback": None
        if evidence
        else {
            "code": "NO_STUDENT_LEARNING_EVIDENCE",
            "message": "当前学习记录中没有与问题直接相关的内容。",
        },
    }


def revoke_student_vector_source(student_id, source_type, source_id):
    """撤回学生的一类来源，并让它立即停止参与检索。"""

    normalized_student_id = _student_id(student_id)
    rows = StudentLearningVector.query.filter_by(
        student_id=normalized_student_id,
        scope_type=STUDENT_SCOPE,
        source_type=str(source_type),
        source_id=str(source_id),
        status=ACTIVE,
    ).all()
    if not rows:
        return get_student_vector_snapshot(normalized_student_id)
    now = dt.utcnow()
    for row in rows:
        row.status = REVOKED
        row.revoked_at = now
        row.revoke_reason = "user_revoked"
        row.updated_at = now
    state = StudentVectorIndexState.query.filter_by(
        student_id=normalized_student_id
    ).first()
    if state is not None:
        state.revision += 1
        state.source_count = StudentLearningVector.query.filter_by(
            student_id=normalized_student_id,
            scope_type=STUDENT_SCOPE,
            status=ACTIVE,
        ).count()
        state.updated_at = now
    db.session.commit()
    return get_student_vector_snapshot(normalized_student_id)


def list_student_learning_sources(student_id):
    """返回当前学生可管理的学习来源摘要，不暴露正文或向量。"""

    normalized_student_id = _student_id(student_id)
    rows = (
        StudentLearningVector.query.filter_by(
            student_id=normalized_student_id,
            scope_type=STUDENT_SCOPE,
        )
        .order_by(
            StudentLearningVector.status.asc(),
            StudentLearningVector.source_type.asc(),
            StudentLearningVector.source_id.asc(),
            StudentLearningVector.source_version.asc(),
            StudentLearningVector.id.asc(),
        )
        .limit(MAX_SOURCE_PROJECTION)
        .all()
    )
    return [
        {
            "source_type": row.source_type,
            "source_id": row.source_id,
            "assignment_id": row.assignment_id,
            "title": row.source_title,
            "scope": row.scope_type,
            "status": row.status,
            "source_version": row.source_version[:SOURCE_VERSION_DISPLAY_LENGTH],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "revoke_reason": row.revoke_reason,
        }
        for row in rows
    ]


def get_student_vector_snapshot(student_id):
    """返回学生首页使用的索引摘要，不返回向量正文。"""

    normalized_student_id = _student_id(student_id)
    state = StudentVectorIndexState.query.filter_by(
        student_id=normalized_student_id
    ).first()
    if state is None:
        return {
            "status": "not_built",
            "revision": 0,
            "source_count": 0,
            "active_count": 0,
            "revoked_count": 0,
            "freshness_status": "unknown",
            "source_types": {},
            "last_built_at": None,
            "failure_code": None,
        }
    active_rows = StudentLearningVector.query.filter_by(
        student_id=normalized_student_id,
        scope_type=STUDENT_SCOPE,
        status=ACTIVE,
    ).all()
    revoked_count = StudentLearningVector.query.filter_by(
        student_id=normalized_student_id,
        scope_type=STUDENT_SCOPE,
        status=REVOKED,
    ).count()
    source_types = {}
    for row in active_rows:
        source_types[row.source_type] = source_types.get(row.source_type, 0) + 1
    effective_status = "stale" if _index_is_stale(state) else state.status
    return {
        "status": effective_status,
        "revision": int(state.revision or 0),
        "source_count": int(state.source_count or 0),
        "active_count": len(active_rows),
        "revoked_count": revoked_count,
        "freshness_status": "stale" if effective_status == "stale" else "fresh",
        "source_types": dict(sorted(source_types.items())),
        "last_built_at": state.last_built_at.isoformat() if state.last_built_at else None,
        "failure_code": state.failure_code,
    }


def build_student_learning_prompt_context(retrieval):
    """生成只含当前学生来源的 AI 上下文。"""

    if retrieval.get("status") == "stale":
        return "个人学习记录索引已经陈旧，请提示学生更新学习记忆；不要声称参考了陈旧记录。"
    if retrieval.get("status") != "grounded":
        return "当前没有可用的个人学习记录，不要声称参考了学生历史。"
    lines = [
        "以下是当前学生自己的学习记录，仅用于引导其反思；不得把记录当作评分依据，也不要泄露来源编号："
    ]
    lines.extend(
        f"{item['citation']} {item['content']}"
        for item in retrieval.get("evidence", [])
    )
    return "\n".join(lines)


def project_student_learning_evidence(retrieval):
    """把个人检索结果投影为学生可读的有限收据。"""

    return {
        "status": retrieval.get("status", "unavailable"),
        "has_evidence": bool(retrieval.get("evidence")),
        "retrieval_mode": (retrieval.get("metrics") or {}).get(
            "retrieval_mode", "unavailable"
        ),
        "index_revision": (retrieval.get("metrics") or {}).get("index_revision", 0),
        "fallback": retrieval.get("fallback"),
        "evidence": [
            {
                "citation": item.get("citation"),
                "title": item.get("title"),
                "content": item.get("content"),
                "assignment_id": item.get("assignment_id"),
                "scope": item.get("scope"),
                "source_type": item.get("source_type"),
                "source_version": item.get("source_version"),
            }
            for item in retrieval.get("evidence", [])
        ],
    }


def render_student_learning_receipt(retrieval):
    """Render a bounded receipt for the current student's learning sources."""

    if retrieval.get("status") == "stale":
        return (
            "\n\n### 个人学习记录\n"
            "当前索引需要更新，请在首页点击“更新我的学习记忆”后再次尝试。"
        )
    if retrieval.get("status") != "grounded":
        return ""
    lines = ["\n\n### 参考我的学习记录"]
    for item in retrieval.get("evidence", []):
        version = str(item.get("source_version") or "")[:12]
        lines.append(
            f"- {item.get('citation')} {item.get('title')}"
            f"（来源：{item.get('source_type')}；作用域：仅当前学生；"
            f"版本：{version}；索引版本：{item.get('index_revision', 0)}）"
        )
    return "\n".join(lines)
