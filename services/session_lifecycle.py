"""Read-only projections for durable guided-learning sessions.

The existing session table intentionally keeps its legacy status and timer
fields.  This module gives new surfaces a stable, explainable view without
rewriting those fields or pretending that wall-clock time is thinking time.
"""

from datetime import datetime, timezone
from typing import Iterable

from models import Assignment, Class, ThinkingStageLog, db


SESSION_IDLE_AFTER_SECONDS = 30 * 60
LIFECYCLE_STATUSES = ("active", "idle", "completed", "abandoned")
TERMINAL_STATUSES = {"completed", "abandoned"}

# 区分“调用者省略 last_activity_at”（payload 自查一次最近活动）与
# “显式传入 None”（批量查询未命中的会话，保留回退 started_at 的既有
# 行为且不执行查询，避免教师概览等列表产生 N+1）。
_LAST_ACTIVITY_UNSET = object()


def _utc_now(value=None) -> datetime:
    value = value or datetime.utcnow()
    normalized = _normalize_datetime(value)
    return normalized or datetime.utcnow()


def _normalize_datetime(value):
    """Convert naive/aware datetime values to naive UTC for safe comparison."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _latest_datetime(*values):
    normalized = [item for value in values if (item := _normalize_datetime(value))]
    return max(normalized) if normalized else None


def _safe_non_negative_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _iso_datetime(value):
    normalized = _normalize_datetime(value)
    return f"{normalized.isoformat(timespec='seconds')}Z" if normalized else None


def latest_session_activity(session_ids: Iterable[int]):
    """Return the latest log timestamp for each requested session in one query."""
    ids = set()
    for value in session_ids or ():
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}

    rows = db.session.query(
        ThinkingStageLog.session_id,
        db.func.max(ThinkingStageLog.created_at),
    ).filter(
        ThinkingStageLog.session_id.in_(ids),
    ).group_by(
        ThinkingStageLog.session_id,
    ).all()
    return {int(session_id): timestamp for session_id, timestamp in rows if session_id is not None}


def session_lifecycle_status(
    session,
    *,
    now=None,
    last_activity_at=None,
    idle_after_seconds=SESSION_IDLE_AFTER_SECONDS,
):
    """Project a persisted session into a user-facing lifecycle status."""
    persisted_status = str(getattr(session, "status", "") or "").strip().lower()
    if persisted_status in TERMINAL_STATUSES:
        return persisted_status
    if persisted_status not in {"", "in_progress"}:
        return "idle"

    activity_at = _latest_datetime(
        getattr(session, "started_at", None),
        last_activity_at,
    )
    if activity_at is None:
        return "idle"

    current_time = _utc_now(now)
    age_seconds = max(0.0, (current_time - activity_at).total_seconds())
    threshold = max(0.0, float(idle_after_seconds))
    return "active" if age_seconds <= threshold else "idle"


def session_elapsed_details(session, *, now=None):
    """Return elapsed seconds and the honest source of that number."""
    stored_seconds = _safe_non_negative_int(getattr(session, "total_time_seconds", 0))
    if stored_seconds > 0:
        return {
            "elapsed_seconds": stored_seconds,
            "elapsed_source": "stored_client_timer",
        }

    started_at = _normalize_datetime(getattr(session, "started_at", None))
    completed_at = _normalize_datetime(getattr(session, "completed_at", None))
    persisted_status = str(getattr(session, "status", "") or "").strip().lower()
    if persisted_status in TERMINAL_STATUSES:
        if started_at and completed_at:
            return {
                "elapsed_seconds": max(0, int((completed_at - started_at).total_seconds())),
                "elapsed_source": "timestamps",
            }
        return {"elapsed_seconds": 0, "elapsed_source": "timestamps"}

    if not started_at:
        return {"elapsed_seconds": 0, "elapsed_source": "server_clock"}
    current_time = _utc_now(now)
    return {
        "elapsed_seconds": max(0, int((current_time - started_at).total_seconds())),
        "elapsed_source": "server_clock",
    }


def session_elapsed_seconds(session, *, now=None):
    """Compatibility helper for callers that only need a number."""
    return session_elapsed_details(session, now=now)["elapsed_seconds"]


def _stage_progress(session, lifecycle_status):
    current_stage = _safe_non_negative_int(getattr(session, "current_stage", 1))
    current_stage = min(3, max(1, current_stage or 1))
    stage1_done = bool(
        getattr(session, "stage1_description", None)
        or getattr(session, "stage1_score", None) is not None
        or current_stage >= 2
    )
    stage2_done = bool(getattr(session, "stage2_completed", False) or current_stage >= 3)
    stage3_done = bool(getattr(session, "stage3_completed", False) or lifecycle_status == "completed")
    completed = [stage1_done, stage2_done, stage3_done]
    if lifecycle_status == "completed":
        progress_percent = 100
    elif stage2_done:
        progress_percent = 67
    elif stage1_done:
        progress_percent = 33
    else:
        progress_percent = 0

    labels = {
        1: "阶段一：描述思路",
        2: "阶段二：拼装代码",
        3: "阶段三：讲解与修复",
    }
    next_actions = {
        1: "完成本阶段的思路描述",
        2: "完成代码块拼装与校验",
        3: "完成讲解、编写并修复代码",
    }
    if lifecycle_status == "completed":
        next_action = "查看本次学习记录"
    elif lifecycle_status == "abandoned":
        next_action = "重新打开作业并开始新的学习会话"
    else:
        next_action = next_actions[current_stage]

    stage_rows = []
    for number, label in labels.items():
        stage_rows.append({
            "stage": number,
            "label": label,
            "status": "completed" if completed[number - 1] else (
                "current" if number == current_stage else "upcoming"
            ),
        })
    return {
        "current_stage": current_stage,
        "stage_label": labels[current_stage],
        "progress_percent": progress_percent,
        "next_action": next_action,
        "stages": stage_rows,
    }


def session_lifecycle_payload(session, *, now=None, last_activity_at=_LAST_ACTIVITY_UNSET):
    """Build a safe, content-free lifecycle payload for UI and teacher views.

    ``last_activity_at`` 通常由批量场景的调用者一次性查出再传入（未命中的
    会话显式传 None，保留回退 started_at 的既有行为，不触发查询，避免
    N+1）；单 session 调用者省略该参数时，函数内部基于 ``session.id``
    自查一次最近活动时间，调用者不必在每个调用点重复写
    ``last_activity_at=latest_session_activity([id]).get(id)``，也不会因为
    漏传而退化成用 started_at 判 idle（刚活动的会话被误判空闲）。
    """
    current_time = _utc_now(now)
    if last_activity_at is _LAST_ACTIVITY_UNSET:
        session_id = getattr(session, "id", None)
        if session_id is not None:
            last_activity_at = latest_session_activity([session_id]).get(session_id)
    lifecycle_status = session_lifecycle_status(
        session,
        now=current_time,
        last_activity_at=last_activity_at,
    )
    activity_at = _latest_datetime(
        getattr(session, "started_at", None),
        last_activity_at,
    )
    elapsed = session_elapsed_details(session, now=current_time)
    payload = {
        "id": getattr(session, "id", None),
        "student_id": getattr(session, "student_id", None),
        "assignment_id": getattr(session, "assignment_id", None),
        "status": lifecycle_status,
        "persisted_status": str(getattr(session, "status", "") or "in_progress"),
        "started_at": _iso_datetime(getattr(session, "started_at", None)),
        "last_activity_at": _iso_datetime(activity_at),
        "completed_at": _iso_datetime(getattr(session, "completed_at", None)),
        "elapsed_seconds": elapsed["elapsed_seconds"],
        "elapsed_source": elapsed["elapsed_source"],
        "elapsed_label": (
            "服务器观察时间"
            if elapsed["elapsed_source"] == "server_clock"
            else "历史保存计时"
            if elapsed["elapsed_source"] == "stored_client_timer"
            else "开始与结束时间差"
        ),
        "is_resumable": lifecycle_status in {"active", "idle"},
    }
    payload.update(_stage_progress(session, lifecycle_status))
    if activity_at:
        payload["activity_age_seconds"] = max(
            0,
            int((current_time - _normalize_datetime(activity_at)).total_seconds()),
        )
    else:
        payload["activity_age_seconds"] = None
    return payload


def can_view_session(actor, session):
    """Apply the narrower authorization boundary used by new lifecycle surfaces."""
    if not actor or not session:
        return False
    if bool(getattr(actor, "is_admin", False)):
        return True

    actor_id = getattr(actor, "student_id", None)
    if actor_id and str(actor_id) == str(getattr(session, "student_id", None)):
        return True
    if not bool(getattr(actor, "is_teacher", False)):
        return False

    assignment = getattr(session, "assignment", None)
    if assignment is None and getattr(session, "assignment_id", None):
        assignment = db.session.get(Assignment, session.assignment_id)
    if assignment is not None and str(getattr(assignment, "creator_id", "")) == str(actor_id):
        return True

    student = getattr(session, "student", None)
    class_id = getattr(student, "class_id", None) if student is not None else None
    if class_id is None:
        return False
    return db.session.query(Class.id).filter(
        Class.id == class_id,
        Class.teacher_id == actor_id,
    ).first() is not None


def can_view_assignment(actor, assignment):
    """Authorize the new teacher overview before exposing assignment metadata."""
    if not actor or not assignment:
        return False
    if bool(getattr(actor, "is_admin", False)):
        return True
    if not bool(getattr(actor, "is_teacher", False)):
        return False

    actor_id = getattr(actor, "student_id", None)
    if str(getattr(assignment, "creator_id", "")) == str(actor_id):
        return True

    getter = getattr(assignment, "get_target_class_list", None)
    target_classes = getter() if callable(getter) else []
    if not target_classes:
        return False
    return db.session.query(Class.id).filter(
        Class.teacher_id == actor_id,
        Class.name.in_(target_classes),
    ).first() is not None
