"""Read-only, role-scoped action aggregation for the logged-in workspace."""

from __future__ import annotations

import logging
import hashlib
import hmac
import time
from datetime import datetime, timezone

from flask import current_app, g, url_for
from sqlalchemy.orm import joinedload

from models import (
    AbilityTrend,
    Class,
    Submission,
    TeacherAISuggestion,
    ThinkingSession,
    db,
)
from services.feedback import list_feedback
from services.notifications import list_notifications
from services.session_lifecycle import latest_session_activity, session_lifecycle_payload
from services.submission_reviews import (
    list_review_queue,
    list_student_review_queue,
)
from utils.access import can_access_assignment


ACTION_CENTER_SCHEMA_VERSION = 1
ACTION_CENTER_MAX_ITEMS = 50
ACTION_CENTER_SOURCE_LIMIT = 50
ACTION_CENTER_PRIORITIES = ("urgent", "next", "info")
ACTION_CENTER_PRIORITY_RANK = {name: index for index, name in enumerate(ACTION_CENTER_PRIORITIES)}

_LOGGER = logging.getLogger(__name__)
_ROLE_LABELS = {"student": "学生", "teacher": "教师", "admin": "管理员"}
_SUBMISSION_STATUS_LABELS = {
    "pending": "等待评测",
    "failed": "评测失败",
}
_REVIEW_STATUS_LABELS = {
    "requested": "待教师查看",
    "in_review": "复核中",
    "waiting_student": "等待学生回应",
}
_SESSION_STATUS_LABELS = {
    "active": "正在学习",
    "idle": "等待继续",
}
_TEACHER_AI_STATUS_LABELS = {
    "pending": "等待生成",
    "processing": "生成中",
    "failed": "生成失败",
    "outdated": "等待刷新",
}
_ABILITY_STATUS_LABELS = {
    "processing": "分析中",
    "failed": "分析失败",
    "outdated": "等待刷新",
}


def _logger():
    try:
        return current_app.logger
    except RuntimeError:
        return _LOGGER


def _request_id() -> str | None:
    try:
        return str(getattr(g, "codesense_request_id", "") or "")[:64] or None
    except RuntimeError:
        return None


def _actor_role(actor) -> str | None:
    if getattr(actor, "is_admin", False) or getattr(actor, "usertype", None) == "管理员":
        return "admin"
    if getattr(actor, "is_teacher", False) or getattr(actor, "usertype", None) == "教师":
        return "teacher"
    if getattr(actor, "usertype", None) == "学生":
        return "student"
    return None


def _safe_limit(value, default=20) -> int:
    try:
        return max(1, min(int(value), ACTION_CENTER_MAX_ITEMS))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_source_limit(value=ACTION_CENTER_SOURCE_LIMIT) -> int:
    try:
        return max(1, min(int(value), ACTION_CENTER_SOURCE_LIMIT))
    except (TypeError, ValueError, OverflowError):
        return ACTION_CENTER_SOURCE_LIMIT


def _safe_text(value, *, limit=160, fallback="") -> str:
    text = str(value or "").strip()
    return text[:limit] if text else fallback


def _safe_href(value, fallback="/") -> str:
    href = str(value or "").strip()
    if not href.startswith("/") or href.startswith("//"):
        return fallback
    return href[:300]


def _opaque_id(kind: str, value) -> str:
    """Return a stable, non-enumerable identifier for the UI contract."""

    try:
        secret = str(current_app.config.get("SECRET_KEY") or "codesense-action-center")
    except RuntimeError:
        secret = "codesense-action-center"
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{kind}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{kind}:{digest}"


def _known_status(value, labels: dict[str, str], fallback: str) -> str:
    status = _safe_text(value, limit=40).lower()
    return status if status in labels else fallback


def _route(endpoint: str, fallback: str, **values) -> str:
    """Build a local URL in requests and remain testable in app contexts."""

    try:
        return _safe_href(url_for(endpoint, **values), fallback)
    except RuntimeError:
        return _safe_href(fallback)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    text = _safe_text(value, limit=64)
    return text or None


def _item(
    *,
    item_id,
    kind: str,
    priority: str,
    title: str,
    summary: str,
    status: str,
    status_label: str,
    href: str,
    source: str,
    occurred_at=None,
) -> dict:
    safe_priority = priority if priority in ACTION_CENTER_PRIORITIES else "info"
    return {
        "id": _safe_text(item_id, limit=100, fallback=f"{source}:unknown"),
        "kind": _safe_text(kind, limit=40, fallback="action"),
        "priority": safe_priority,
        "title": _safe_text(title, limit=120, fallback="待处理事项"),
        "summary": _safe_text(summary, limit=240, fallback="打开查看详情。"),
        "status": _safe_text(status, limit=40, fallback="pending"),
        "status_label": _safe_text(status_label, limit=80, fallback="待处理"),
        "href": _safe_href(href),
        "source": _safe_text(source, limit=40, fallback="action_center"),
        "occurred_at": _iso(occurred_at),
    }


def _assignment_title(assignment) -> str:
    return _safe_text(getattr(assignment, "title", ""), limit=100, fallback="未命名作业")


def _read_student_submissions(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "student":
        return []
    submissions = (
        Submission.query.options(joinedload(Submission.assignment))
        .filter(
            Submission.student_id == getattr(actor, "student_id", None),
            Submission.status.in_(tuple(_SUBMISSION_STATUS_LABELS)),
        )
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(_safe_source_limit(source_limit))
        .all()
    )
    items = []
    for submission in submissions:
        assignment = submission.assignment
        if assignment is None or not can_access_assignment(assignment, actor):
            continue
        status = str(submission.status or "pending").strip().lower()
        priority = "urgent" if status == "failed" else "next"
        summary = (
            "评测失败，打开提交详情查看并重新提交。"
            if status == "failed"
            else "评测尚未完成，稍后可从这里继续查看。"
        )
        items.append(_item(
            item_id=_opaque_id("submission", submission.id),
            kind="submission",
            priority=priority,
            title=f"作业「{_assignment_title(assignment)}」",
            summary=summary,
            status=status,
            status_label=_SUBMISSION_STATUS_LABELS.get(status, "待处理"),
            href=_route(
                "assignments.view_submission",
                f"/view_submission/{submission.id}",
                submission_id=submission.id,
            ),
            source="submissions",
            occurred_at=submission.submitted_at,
        ))
    return items


def _read_student_reviews(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "student":
        return []
    items = []
    for review in list_student_review_queue(actor, limit=_safe_source_limit(source_limit)):
        status = _known_status(review.get("status"), _REVIEW_STATUS_LABELS, "in_review")
        if status == "resolved":
            continue
        assignment = review.get("assignment")
        submission_id = review.get("submission_id")
        items.append(_item(
            item_id=_opaque_id("review", review.get("review_id") or submission_id),
            kind="review",
            priority="urgent" if status == "requested" else "next",
            title=f"提交复核：{_assignment_title(assignment)}",
            summary="打开提交详情查看复核进展或回应教师。",
            status=status,
            status_label=_REVIEW_STATUS_LABELS.get(status, "复核处理中"),
            href=_route(
                "assignments.view_submission",
                f"/view_submission/{submission_id}",
                submission_id=submission_id,
            ),
            source="reviews",
            occurred_at=review.get("last_updated_at"),
        ))
    return items


def _read_student_sessions(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "student":
        return []
    sessions = (
        ThinkingSession.query.options(joinedload(ThinkingSession.assignment))
        .filter_by(student_id=getattr(actor, "student_id", None), status="in_progress")
        .order_by(ThinkingSession.started_at.desc(), ThinkingSession.id.desc())
        .limit(_safe_source_limit(source_limit))
        .all()
    )
    activity_by_session = latest_session_activity([session.id for session in sessions])
    items = []
    for session in sessions:
        lifecycle = session_lifecycle_payload(
            session,
            last_activity_at=activity_by_session.get(session.id),
        )
        if not lifecycle.get("is_resumable"):
            continue
        status = str(lifecycle.get("status") or "idle")
        items.append(_item(
            item_id=_opaque_id("session", session.id),
            kind="session",
            priority="next",
            title=f"继续学习：{_assignment_title(session.assignment)}",
            summary=_safe_text(lifecycle.get("next_action"), limit=200, fallback="回到学习页面继续。"),
            status=status,
            status_label=_SESSION_STATUS_LABELS.get(status, "可继续"),
            href=_route(
                "thinking.arena",
                f"/thinking/{session.assignment_id}",
                assignment_id=session.assignment_id,
            ),
            source="sessions",
            occurred_at=lifecycle.get("last_activity_at") or lifecycle.get("started_at"),
        ))
    return items


def _read_notifications(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) not in {"student", "teacher", "admin"}:
        return []
    items = []
    for notification in list_notifications(
        getattr(actor, "student_id", None),
        unread_only=True,
        limit=_safe_source_limit(source_limit),
    ):
        is_learning_memory_refresh = (
            notification.get("kind") == "learning_memory_refresh"
        )
        items.append(_item(
            item_id=_opaque_id("notification", notification.get("id")),
            kind=("learning_memory_refresh" if is_learning_memory_refresh else "notification"),
            priority="next" if is_learning_memory_refresh else "info",
            title=notification.get("title", "站内通知"),
            summary=notification.get("message", "打开通知查看详情。"),
            status="unread",
            status_label="需要更新" if is_learning_memory_refresh else "未读",
            href=notification.get("url") or _route("main.notifications", "/notifications"),
            source="notifications",
            occurred_at=notification.get("created_at"),
        ))
    return items


def _read_teacher_reviews(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "teacher":
        return []
    items = []
    for review in list_review_queue(actor, limit=_safe_source_limit(source_limit)):
        status = _known_status(review.get("status"), _REVIEW_STATUS_LABELS, "in_review")
        if status == "resolved":
            continue
        submission = review.get("submission")
        assignment = review.get("assignment")
        items.append(_item(
            item_id=_opaque_id("review", review.get("review_id") or review.get("submission_id")),
            kind="review",
            priority="urgent" if status == "requested" else "next",
            title=f"待处理复核：{_assignment_title(assignment)}",
            summary="打开提交详情查看学生的复核请求。",
            status=status,
            status_label=_REVIEW_STATUS_LABELS.get(status, "复核处理中"),
            href=_route(
                "assignments.view_submission",
                f"/view_submission/{getattr(submission, 'id', 0)}",
                submission_id=getattr(submission, "id", 0),
            ),
            source="teacher_reviews",
            occurred_at=review.get("last_updated_at"),
        ))
    return items


def _read_teacher_ai(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "teacher":
        return []
    classrooms = (
        Class.query.filter_by(teacher_id=getattr(actor, "student_id", None))
        .order_by(Class.id.asc())
        .limit(_safe_source_limit(source_limit))
        .all()
    )
    class_ids = [classroom.id for classroom in classrooms]
    if not class_ids:
        return []
    names = {classroom.id: _safe_text(classroom.name, limit=80, fallback="当前班级") for classroom in classrooms}
    suggestions = (
        TeacherAISuggestion.query.filter(
            TeacherAISuggestion.teacher_id == getattr(actor, "student_id", None),
            TeacherAISuggestion.class_id.in_(class_ids),
            TeacherAISuggestion.status.in_(tuple(_TEACHER_AI_STATUS_LABELS)),
        )
        .order_by(TeacherAISuggestion.last_updated.desc(), TeacherAISuggestion.id.desc())
        .limit(_safe_source_limit(source_limit))
        .all()
    )
    items = []
    for suggestion in suggestions:
        status = str(suggestion.status or "pending")
        items.append(_item(
            item_id=_opaque_id("teacher-ai", suggestion.id),
            kind="teacher_ai",
            priority="urgent" if status == "failed" else "next",
            title=f"班级建议：{names.get(suggestion.class_id, '当前班级')}",
            summary="AI 建议需要查看或刷新，请打开班级工作区。",
            status=status,
            status_label=_TEACHER_AI_STATUS_LABELS.get(status, "待处理"),
            href=_route(
                "classes.class_detail",
                f"/classes/{suggestion.class_id}",
                class_id=suggestion.class_id,
            ),
            source="teacher_ai",
            occurred_at=suggestion.last_updated,
        ))
    return items


def _read_admin_feedback(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "admin":
        return []
    items = []
    for record in list_feedback(limit=_safe_source_limit(source_limit)):
        status = str(record.get("status") or "received")
        if status in {"closed", "resolved"}:
            continue
        items.append(_item(
            item_id=_opaque_id("feedback", record.get("feedback_id")),
            kind="feedback",
            priority="urgent" if status == "received" else "next",
            title=f"反馈：{record.get('subject') or '未命名反馈'}",
            summary="打开反馈中心推进处理状态。",
            status=status,
            status_label=str(record.get("status_label") or "待处理"),
            href=_route("main.admin_feedback", "/admin/feedback"),
            source="admin_feedback",
            occurred_at=record.get("last_updated_at") or record.get("submitted_at"),
        ))
    return items


def _read_admin_ability(actor, *, source_limit=ACTION_CENTER_SOURCE_LIMIT) -> list[dict]:
    if _actor_role(actor) != "admin":
        return []
    rows = (
        db.session.query(AbilityTrend)
        .filter(AbilityTrend.status.in_(tuple(_ABILITY_STATUS_LABELS)))
        .order_by(AbilityTrend.last_updated.desc(), AbilityTrend.id.desc())
        .limit(_safe_source_limit(source_limit))
        .all()
    )
    items = []
    for trend in rows:
        status = str(trend.status or "failed")
        items.append(_item(
            item_id=_opaque_id("ability", trend.id),
            kind="ability",
            priority="urgent" if status == "failed" else "next",
            title="能力分析：系统队列",
            summary="能力分析需要管理员查看或重新安排。",
            status=status,
            status_label=_ABILITY_STATUS_LABELS.get(status, "待处理"),
            href=_route("main.admin_dashboard", "/admin_dashboard"),
            source="admin_ability",
            occurred_at=trend.last_updated,
        ))
    return items


def _read_sources(role: str, actor):
    if role == "student":
        return (
            ("submissions", _read_student_submissions),
            ("reviews", _read_student_reviews),
            ("sessions", _read_student_sessions),
            ("notifications", _read_notifications),
        )
    if role == "teacher":
        return (
            ("teacher_reviews", _read_teacher_reviews),
            ("teacher_ai", _read_teacher_ai),
            ("notifications", _read_notifications),
        )
    if role == "admin":
        return (
            ("admin_feedback", _read_admin_feedback),
            ("admin_ability", _read_admin_ability),
            ("notifications", _read_notifications),
        )
    return ()


def build_action_center(
    actor,
    *,
    priority="all",
    limit=20,
    source_limit=ACTION_CENTER_SOURCE_LIMIT,
    emit_log=True,
) -> dict:
    """Build one bounded action payload without mutating application state."""

    started = time.perf_counter()
    role = _actor_role(actor)
    role = role or "unknown"
    selected_priority = str(priority or "all").strip().lower()
    if selected_priority not in {"all", *ACTION_CENTER_PRIORITIES}:
        selected_priority = "all"
    safe_limit = _safe_limit(limit)
    safe_source_limit = _safe_source_limit(source_limit)
    items = []
    degraded_sources = []

    for source, reader in _read_sources(role, actor):
        try:
            items.extend(reader(actor, source_limit=safe_source_limit))
        except Exception as error:
            degraded_sources.append(source)
            try:
                db.session.rollback()
            except Exception:
                pass
            _logger().warning(
                "action_center_source_failed source=%s role=%s request_id=%s error_type=%s",
                source,
                role,
                _request_id(),
                type(error).__name__,
            )

    items.sort(
        key=lambda item: (item.get("occurred_at") or "", item.get("id") or ""),
        reverse=True,
    )
    items.sort(
        key=lambda item: ACTION_CENTER_PRIORITY_RANK.get(
            item["priority"], len(ACTION_CENTER_PRIORITIES)
        ),
    )
    counts = {
        priority_name: sum(1 for item in items if item["priority"] == priority_name)
        for priority_name in ACTION_CENTER_PRIORITIES
    }
    counts["total"] = len(items)
    visible_items = (
        items
        if selected_priority == "all"
        else [item for item in items if item["priority"] == selected_priority]
    )
    payload = {
        "schema_version": ACTION_CENTER_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "role": role,
        "data_scope": {
            "student": "actor-owned",
            "teacher": "managed-classes",
            "admin": "system-queue",
        }.get(role, "none"),
        "degraded_sources": sorted(set(degraded_sources)),
        "items": visible_items[:safe_limit],
        "counts": counts,
    }
    if emit_log:
        _logger().info(
            "action_center_built role=%s request_id=%s item_count=%s visible_count=%s degraded_sources=%s duration_ms=%.2f",
            role,
            _request_id(),
            counts["total"],
            len(payload["items"]),
            ",".join(payload["degraded_sources"]) or "none",
            (time.perf_counter() - started) * 1000,
        )
    return payload


def count_action_center_items(actor) -> int:
    """Return a bounded nav badge count without emitting a second build log."""

    if _actor_role(actor) is None:
        return 0
    payload = build_action_center(
        actor,
        limit=ACTION_CENTER_MAX_ITEMS,
        source_limit=ACTION_CENTER_SOURCE_LIMIT,
        emit_log=False,
    )
    return min(int(payload["counts"].get("total", 0)), 99)
