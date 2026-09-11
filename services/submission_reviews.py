"""Permission-scoped collaboration around a submitted program.

The application already has a durable ``SystemLog`` table and a local
notification adapter.  This module uses a small, versioned event envelope so
the review loop can ship without a schema migration while keeping submission
permissions in one place.
"""

from __future__ import annotations

import json
import secrets
from collections import defaultdict
from datetime import datetime, timezone

from models import Assignment, Class, Submission, SystemLog, User, db


REVIEW_LOG_TYPE = "提交复核"
REVIEW_SCHEMA_VERSION = 1
AI_FEEDBACK_SIGNAL_LOG_TYPE = "AI反馈信号"
AI_FEEDBACK_SIGNAL_SCHEMA_VERSION = 1
MAX_REVIEW_SCAN = 1000
MAX_REVIEW_BODY_LENGTH = 2000
MAX_REVIEW_NOTE_LENGTH = 500

REVIEW_STATUSES = (
    "requested",
    "in_review",
    "waiting_student",
    "resolved",
)
REVIEW_STATUS_LABELS = {
    "requested": "待教师查看",
    "in_review": "复核中",
    "waiting_student": "等待学生回应",
    "resolved": "已解决",
}
REVIEW_STATUS_OPTIONS = tuple(
    (status, REVIEW_STATUS_LABELS[status]) for status in REVIEW_STATUSES
)

# This table is intentionally explicit.  It is also used by the queue UI so
# users never see a control for an invalid transition.
REVIEW_ALLOWED_TRANSITIONS = {
    "requested": ("in_review",),
    "in_review": ("waiting_student", "resolved"),
    "waiting_student": ("in_review", "resolved"),
    "resolved": (),
}

AI_FEEDBACK_SIGNAL_VALUES = {
    "helpful": "有帮助",
    "needs_clarification": "需要澄清",
}

_EVENTS = {"request", "message", "status"}
_ROLE_LABELS = {
    "student": "学生",
    "teacher": "教师",
    "admin": "管理员",
}


class ReviewValidationError(ValueError):
    """Raised when a review body or signal is not valid."""


class ReviewPermissionError(PermissionError):
    """Raised when an actor is not a participant in a submission review."""


class ReviewStatusError(ValueError):
    """Raised when a requested status transition is not allowed."""


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _actor_id(actor) -> str | None:
    if isinstance(actor, str):
        return actor.strip() or None
    return str(getattr(actor, "student_id", "") or "").strip() or None


def _actor_role(actor) -> str | None:
    if getattr(actor, "is_admin", False) or getattr(actor, "usertype", None) == "管理员":
        return "admin"
    if getattr(actor, "is_teacher", False) or getattr(actor, "usertype", None) == "教师":
        return "teacher"
    if getattr(actor, "usertype", None) == "学生":
        return "student"
    return None


def _clean_body(value, *, field="复核内容", max_length=MAX_REVIEW_BODY_LENGTH) -> str:
    body = str(value or "").strip()
    if not body:
        raise ReviewValidationError(f"{field}不能为空。")
    if len(body) > max_length:
        raise ReviewValidationError(f"{field}不能超过 {max_length} 个字符。")
    return body


def _clean_note(value) -> str:
    note = str(value or "").strip()
    if len(note) > MAX_REVIEW_NOTE_LENGTH:
        raise ReviewValidationError(
            f"处理备注不能超过 {MAX_REVIEW_NOTE_LENGTH} 个字符。"
        )
    return note


def _parse_event(log) -> dict | None:
    try:
        payload = json.loads(log.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        return None
    if payload.get("event") not in _EVENTS:
        return None
    try:
        submission_id = int(payload.get("submission_id"))
    except (TypeError, ValueError):
        return None
    review_id = str(payload.get("review_id") or "").strip()
    if not submission_id or not review_id:
        return None
    event = dict(payload)
    event["submission_id"] = submission_id
    event["review_id"] = review_id
    event["log_id"] = log.id
    event["actor_id"] = str(event.get("actor_id") or log.user_id or "").strip() or None
    event["actor_role"] = event.get("actor_role") or "unknown"
    event["actor_role_label"] = _ROLE_LABELS.get(
        event["actor_role"], "参与者"
    )
    event["status_label"] = REVIEW_STATUS_LABELS.get(
        event.get("status") or event.get("to_status"), "处理中"
    )
    event["body"] = str(event.get("body") or "")
    event["created_at"] = event.get("created_at") or (
        log.created_at.isoformat() if log.created_at else ""
    )
    return event


def _review_events(submission_id: int) -> list[dict]:
    logs = (
        SystemLog.query.filter_by(log_type=REVIEW_LOG_TYPE)
        .order_by(SystemLog.id.desc())
        .limit(MAX_REVIEW_SCAN)
        .all()
    )
    events = []
    for log in logs:
        event = _parse_event(log)
        if event and event["submission_id"] == int(submission_id):
            events.append(event)
    return sorted(events, key=lambda event: event["log_id"])


def _review_from_events(events: list[dict]) -> dict | None:
    if not events:
        return None
    root = next((event for event in events if event["event"] == "request"), events[0])
    current_status = root.get("status") or "requested"
    history = [{
        "status": "requested",
        "status_label": REVIEW_STATUS_LABELS["requested"],
        "at": root.get("created_at", ""),
    }]
    for event in events:
        if event["event"] == "status":
            status = event.get("status") or event.get("to_status")
            if status in REVIEW_STATUS_LABELS:
                current_status = status
                history.append({
                    "status": status,
                    "status_label": REVIEW_STATUS_LABELS[status],
                    "at": event.get("created_at", ""),
                })
        elif event["event"] == "message" and event.get("status") in REVIEW_STATUS_LABELS:
            current_status = event["status"]

    return {
        "review_id": root["review_id"],
        "submission_id": root["submission_id"],
        "status": current_status,
        "status_label": REVIEW_STATUS_LABELS.get(current_status, "处理中"),
        "events": events,
        "status_history": history[-20:],
        "last_updated_at": events[-1].get("created_at", ""),
        "last_event_id": events[-1].get("log_id"),
        "next_statuses": list(REVIEW_ALLOWED_TRANSITIONS.get(current_status, ())),
    }


def get_submission_review(submission_id: int) -> dict | None:
    """Return the bounded, current review thread for one submission."""

    return _review_from_events(_review_events(submission_id))


def can_access_submission_review(submission, actor) -> bool:
    """Check participant access without relying on a caller-provided role."""

    actor_id = _actor_id(actor)
    role = _actor_role(actor)
    if not actor_id or not role or submission is None:
        return False
    if actor_id == str(submission.student_id):
        return True
    if role == "admin":
        return True
    if role != "teacher":
        return False

    student = db.session.get(User, submission.student_id)
    if student is None or not student.class_id:
        return False
    classroom = db.session.get(Class, student.class_id)
    return bool(classroom and classroom.teacher_id == actor_id)


def _event_payload(
    *,
    event: str,
    review_id: str,
    submission_id: int,
    actor_id: str,
    actor_role: str,
    status: str,
    body: str = "",
    **extra,
) -> dict:
    payload = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "event": event,
        "review_id": review_id,
        "submission_id": int(submission_id),
        "actor_id": actor_id,
        "actor_role": actor_role,
        "status": status,
        "body": body,
        "created_at": _now_iso(),
    }
    payload.update(extra)
    return payload


def _add_event(payload: dict, *, actor_id: str) -> SystemLog:
    log = SystemLog(
        log_type=REVIEW_LOG_TYPE,
        user_id=actor_id,
        icon="bi bi-chat-square-text",
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    db.session.add(log)
    return log


def create_review_request(submission, actor_id: str, body: str):
    """Create the one review thread allowed for a submission.

    Returns ``(review, created)``.  A repeated request reuses the existing
    thread and therefore cannot create duplicate business events.
    """

    actor_id = _actor_id(actor_id)
    if submission is None or not actor_id or actor_id != str(submission.student_id):
        raise ReviewPermissionError("只有提交学生可以申请教师复核。")
    body = _clean_body(body, field="复核说明")
    existing = get_submission_review(submission.id)
    if existing:
        return existing, False

    review_id = f"SR-{secrets.token_hex(6).upper()}"
    _add_event(
        _event_payload(
            event="request",
            review_id=review_id,
            submission_id=submission.id,
            actor_id=actor_id,
            actor_role="student",
            status="requested",
            body=body,
        ),
        actor_id=actor_id,
    )
    db.session.commit()
    return get_submission_review(submission.id), True


def transition_review(submission, actor, new_status: str, note: str = ""):
    """Apply one explicit teacher/admin status transition."""

    review = get_submission_review(submission.id if submission else 0)
    if review is None:
        raise ReviewStatusError("当前提交还没有教师复核请求。")
    if not can_access_submission_review(submission, actor):
        raise ReviewPermissionError("您无权处理此提交的复核请求。")
    if _actor_role(actor) not in {"teacher", "admin"}:
        raise ReviewPermissionError("只有教师或管理员可以推进复核状态。")

    new_status = str(new_status or "").strip()
    if new_status not in REVIEW_STATUS_LABELS:
        raise ReviewStatusError("复核状态无效。")
    current_status = review["status"]
    if new_status not in REVIEW_ALLOWED_TRANSITIONS.get(current_status, ()):
        raise ReviewStatusError(
            f"不能将“{REVIEW_STATUS_LABELS.get(current_status, current_status)}”直接改为“{REVIEW_STATUS_LABELS.get(new_status, new_status)}”。"
        )

    actor_id = _actor_id(actor)
    actor_role = _actor_role(actor)
    payload = _event_payload(
        event="status",
        review_id=review["review_id"],
        submission_id=submission.id,
        actor_id=actor_id,
        actor_role=actor_role,
        status=new_status,
        body=_clean_note(note),
        from_status=current_status,
        to_status=new_status,
    )
    log = _add_event(payload, actor_id=actor_id)
    db.session.commit()
    return get_submission_review(submission.id), _parse_event(log)


def add_review_message(submission, actor, body: str):
    """Append a participant message and update status when the role requires it."""

    review = get_submission_review(submission.id if submission else 0)
    if review is None:
        raise ReviewStatusError("请先申请教师复核，再发送追问。")
    if not can_access_submission_review(submission, actor):
        raise ReviewPermissionError("您无权参与此提交的复核。")
    body = _clean_body(body)
    actor_id = _actor_id(actor)
    actor_role = _actor_role(actor)
    if actor_role not in {"student", "teacher", "admin"}:
        raise ReviewPermissionError("当前账号不能参与提交复核。")

    current_status = review["status"]
    transitions = []
    if actor_role == "student":
        if current_status in {"waiting_student", "resolved"}:
            transitions = ["in_review"]
    else:
        if current_status == "resolved":
            raise ReviewStatusError("已解决的复核请由学生重新追问后再继续。")
        if current_status == "requested":
            # A first teacher reply acknowledges the request before waiting
            # for the student's concrete follow-up.
            transitions = ["in_review", "waiting_student"]
        elif current_status == "in_review":
            transitions = ["waiting_student"]

    for next_status in transitions:
        student_reopen = (
            actor_role == "student"
            and current_status == "resolved"
            and next_status == "in_review"
        )
        if (
            next_status not in REVIEW_ALLOWED_TRANSITIONS.get(current_status, ())
            and not student_reopen
        ):
            raise ReviewStatusError("复核状态转换不受支持。")
        _add_event(
            _event_payload(
                event="status",
                review_id=review["review_id"],
                submission_id=submission.id,
                actor_id=actor_id,
                actor_role=actor_role,
                status=next_status,
                from_status=current_status,
                to_status=next_status,
            ),
            actor_id=actor_id,
        )
        current_status = next_status

    message_log = _add_event(
        _event_payload(
            event="message",
            review_id=review["review_id"],
            submission_id=submission.id,
            actor_id=actor_id,
            actor_role=actor_role,
            status=current_status,
            body=body,
        ),
        actor_id=actor_id,
    )
    db.session.commit()
    return get_submission_review(submission.id), _parse_event(message_log)


def _all_review_event_groups() -> dict[str, list[dict]]:
    logs = (
        SystemLog.query.filter_by(log_type=REVIEW_LOG_TYPE)
        .order_by(SystemLog.id.desc())
        .limit(MAX_REVIEW_SCAN)
        .all()
    )
    groups = defaultdict(list)
    for log in logs:
        event = _parse_event(log)
        if event:
            groups[event["review_id"]].append(event)
    return {
        review_id: sorted(events, key=lambda event: event["log_id"])
        for review_id, events in groups.items()
    }


def list_review_queue(actor, *, status: str | None = None, limit: int = 100) -> list[dict]:
    """Return only reviews visible to the current teacher/admin."""

    safe_limit = max(1, min(int(limit), 200))
    if _actor_role(actor) not in {"teacher", "admin"}:
        return []
    rows = []
    for events in _all_review_event_groups().values():
        review = _review_from_events(events)
        if review is None or (status and review["status"] != status):
            continue
        submission = db.session.get(Submission, review["submission_id"])
        if submission is None or not can_access_submission_review(submission, actor):
            continue
        review["submission"] = submission
        review["student"] = db.session.get(User, submission.student_id)
        review["assignment"] = db.session.get(Assignment, submission.assignment_id)
        rows.append(review)
    rows.sort(key=lambda row: row.get("last_event_id") or 0, reverse=True)
    return rows[:safe_limit]


def count_open_reviews(actor) -> int:
    return sum(
        1 for review in list_review_queue(actor, limit=200)
        if review["status"] != "resolved"
    )


def get_review_summaries(submission_ids) -> dict[int, dict]:
    """Build bounded list-page summaries without exposing event bodies."""

    summaries = {}
    for submission_id in submission_ids or []:
        review = get_submission_review(submission_id)
        if review:
            summaries[int(submission_id)] = {
                "review_id": review["review_id"],
                "status": review["status"],
                "status_label": review["status_label"],
                "last_updated_at": review["last_updated_at"],
            }
    return summaries


def get_submission_review_participants(submission) -> dict[str, list[str] | str | None]:
    """Resolve the student and the one or two scoped teaching participants."""

    student_id = str(getattr(submission, "student_id", "") or "") or None
    teacher_ids = []
    student = db.session.get(User, student_id) if student_id else None
    if student and student.class_id:
        classroom = db.session.get(Class, student.class_id)
        if classroom and classroom.teacher_id:
            teacher_ids.append(str(classroom.teacher_id))
    assignment = db.session.get(Assignment, submission.assignment_id) if submission else None
    if assignment and assignment.creator_id:
        creator = db.session.get(User, assignment.creator_id)
        if creator and creator.usertype == "教师" and can_access_submission_review(submission, creator):
            teacher_ids.append(str(creator.student_id))
    return {
        "student_id": student_id,
        "teacher_ids": list(dict.fromkeys(teacher_ids)),
    }


def review_notification_recipients(submission, actor) -> list[str]:
    participants = get_submission_review_participants(submission)
    actor_id = _actor_id(actor)
    if _actor_role(actor) == "student":
        return [
            recipient for recipient in participants["teacher_ids"]
            if recipient != actor_id
        ]
    student_id = participants["student_id"]
    return [student_id] if student_id and student_id != actor_id else []


def _parse_ai_signal(log) -> dict | None:
    try:
        payload = json.loads(log.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != AI_FEEDBACK_SIGNAL_SCHEMA_VERSION:
        return None
    try:
        submission_id = int(payload.get("submission_id"))
    except (TypeError, ValueError):
        return None
    value = payload.get("value")
    if not submission_id or value not in AI_FEEDBACK_SIGNAL_VALUES:
        return None
    return {"submission_id": submission_id, "value": value, "log_id": log.id}


def get_ai_feedback_signal(submission_id: int, actor_id: str) -> str | None:
    logs = (
        SystemLog.query.filter_by(
            log_type=AI_FEEDBACK_SIGNAL_LOG_TYPE,
            user_id=_actor_id(actor_id),
        )
        .order_by(SystemLog.id.desc())
        .limit(MAX_REVIEW_SCAN)
        .all()
    )
    for log in logs:
        signal = _parse_ai_signal(log)
        if signal and signal["submission_id"] == int(submission_id):
            return signal["value"]
    return None


def save_ai_feedback_signal(submission_id: int, actor_id: str, value: str) -> str:
    submission = db.session.get(Submission, submission_id)
    actor_id = _actor_id(actor_id)
    if submission is None or not actor_id or actor_id != str(submission.student_id):
        raise ReviewPermissionError("只有提交学生可以评价这条 AI 反馈。")
    value = str(value or "").strip()
    if value not in AI_FEEDBACK_SIGNAL_VALUES:
        raise ReviewValidationError("AI 反馈评价选项无效。")

    existing = None
    logs = (
        SystemLog.query.filter_by(
            log_type=AI_FEEDBACK_SIGNAL_LOG_TYPE,
            user_id=actor_id,
        )
        .order_by(SystemLog.id.desc())
        .limit(MAX_REVIEW_SCAN)
        .all()
    )
    for log in logs:
        signal = _parse_ai_signal(log)
        if signal and signal["submission_id"] == int(submission_id):
            existing = log
            break

    payload = {
        "schema_version": AI_FEEDBACK_SIGNAL_SCHEMA_VERSION,
        "submission_id": int(submission_id),
        "value": value,
        "updated_at": _now_iso(),
    }
    if existing:
        existing.content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    else:
        db.session.add(SystemLog(
            log_type=AI_FEEDBACK_SIGNAL_LOG_TYPE,
            user_id=actor_id,
            icon="bi bi-hand-thumbs-up",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ))
    db.session.commit()
    return value
