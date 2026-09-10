"""Structured feedback intake built on the existing system log table.

The first feedback-center slice deliberately avoids a schema migration.  A
versioned JSON record gives the support workflow a stable contract today;
later status transitions can migrate the same fields into a dedicated table
without changing the public form contract.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from models import SystemLog, db


FEEDBACK_SCHEMA_VERSION = 1
FEEDBACK_STATUS_RECEIVED = "received"
FEEDBACK_STATUS_OPTIONS = (
    ("received", "已收到"),
    ("triaged", "已分派"),
    ("in_progress", "处理中"),
    ("resolved", "已解决"),
    ("closed", "已关闭"),
)
FEEDBACK_STATUS_LABELS = dict(FEEDBACK_STATUS_OPTIONS)
FEEDBACK_CATEGORIES = (
    ("bug", "功能异常"),
    ("content", "内容或评测"),
    ("experience", "使用体验"),
    ("privacy", "隐私与数据"),
    ("other", "其他"),
)
FEEDBACK_CATEGORY_LABELS = dict(FEEDBACK_CATEGORIES)
FEEDBACK_ID_PATTERN = re.compile(r"^FB-[0-9A-F]{12}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FEEDBACK_STATUS_TRANSITIONS = {
    "received": {"triaged"},
    "triaged": {"in_progress"},
    "in_progress": {"resolved"},
    "resolved": {"closed", "in_progress"},
    "closed": set(),
}


class FeedbackValidationError(ValueError):
    """Raised when a feedback submission cannot be accepted safely."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("feedback validation failed")
        self.errors = errors


class FeedbackStatusError(ValueError):
    """Raised when an administrator requests an invalid status transition."""

    def __init__(self, message: str, *, code: str = "invalid_status"):
        super().__init__(message)
        self.code = code


def _clean(value, *, max_length: int) -> str:
    """Normalize a user-provided field without changing its meaning."""

    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_feedback_payload(data) -> dict[str, str]:
    """Validate and normalize the public feedback form fields."""

    data = data or {}
    category = _text(data.get("category"))
    subject = _text(data.get("subject"))
    message = _text(data.get("message"))
    reproduction_steps = _text(data.get("reproduction_steps"))
    page_context = _text(data.get("page_context"))
    contact_email = _text(data.get("contact_email"))

    errors = {}
    if category not in FEEDBACK_CATEGORY_LABELS:
        errors["category"] = "请选择一个反馈类型。"
    if len(subject) < 3:
        errors["subject"] = "主题至少需要 3 个字符。"
    elif len(subject) > 120:
        errors["subject"] = "主题不能超过 120 个字符。"
    if len(message) < 10:
        errors["message"] = "请提供至少 10 个字符的具体描述。"
    elif len(message) > 4000:
        errors["message"] = "具体描述不能超过 4000 个字符。"
    if len(reproduction_steps) > 2000:
        errors["reproduction_steps"] = "复现步骤不能超过 2000 个字符。"
    if len(page_context) > 200:
        errors["page_context"] = "页面或请求上下文不能超过 200 个字符。"
    if len(contact_email) > 120:
        errors["contact_email"] = "联系邮箱不能超过 120 个字符。"
    elif contact_email and not _EMAIL_PATTERN.fullmatch(contact_email):
        errors["contact_email"] = "请输入有效的电子邮箱，或留空。"

    if errors:
        raise FeedbackValidationError(errors)

    return {
        "category": category,
        "subject": subject,
        "message": message,
        "reproduction_steps": reproduction_steps,
        "page_context": page_context or "/feedback",
        "contact_email": contact_email,
    }


def create_feedback_record(
    data,
    *,
    request_context: dict[str, str | None],
) -> dict:
    """Create a versioned record with opaque request correlation fields."""

    payload = normalize_feedback_payload(data)
    submitted_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    feedback_id = f"FB-{uuid.uuid4().hex[:12].upper()}"
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "feedback_id": feedback_id,
        "status": FEEDBACK_STATUS_RECEIVED,
        "status_history": [
            {"status": FEEDBACK_STATUS_RECEIVED, "at": submitted_at}
        ],
        "submitted_at": submitted_at,
        "category": payload["category"],
        "category_label": FEEDBACK_CATEGORY_LABELS[payload["category"]],
        "subject": payload["subject"],
        "message": payload["message"],
        "reproduction_steps": payload["reproduction_steps"],
        "contact_email": payload["contact_email"],
        "context": {
            "page": payload["page_context"],
            "request_id": _clean(request_context.get("request_id"), max_length=64),
            "endpoint": _clean(request_context.get("endpoint"), max_length=120),
            "method": _clean(request_context.get("method"), max_length=12),
        },
    }


def _feedback_record_from_log(log) -> dict | None:
    """Parse a feedback event and normalize records created by older releases."""

    try:
        record = json.loads(log.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or not record.get("feedback_id"):
        return None

    status = record.get("status")
    if status not in FEEDBACK_STATUS_LABELS:
        status = FEEDBACK_STATUS_RECEIVED
    history = record.get("status_history")
    if not isinstance(history, list) or not history:
        history = [{
            "status": status,
            "at": record.get("submitted_at") or "",
        }]

    normalized_history = []
    for item in history:
        if not isinstance(item, dict):
            continue
        item_status = item.get("status")
        if item_status not in FEEDBACK_STATUS_LABELS:
            continue
        normalized_history.append({
            "status": item_status,
            "status_label": FEEDBACK_STATUS_LABELS[item_status],
            "at": str(item.get("at") or ""),
        })
    if not normalized_history:
        normalized_history = [{
            "status": status,
            "status_label": FEEDBACK_STATUS_LABELS[status],
            "at": str(record.get("submitted_at") or ""),
        }]

    record["status"] = status
    record["status_label"] = FEEDBACK_STATUS_LABELS[status]
    record["status_history"] = normalized_history[-20:]
    return record


def _find_feedback_log(feedback_id: str):
    if not FEEDBACK_ID_PATTERN.fullmatch(feedback_id or ""):
        return None

    marker = f'"feedback_id": "{feedback_id}"'
    logs = (
        SystemLog.query.filter(
            SystemLog.log_type == "反馈提交",
            SystemLog.content.like(f"%{marker}%"),
        )
        .order_by(SystemLog.id.desc())
        .all()
    )
    for log in logs:
        record = _feedback_record_from_log(log)
        if record and record.get("feedback_id") == feedback_id:
            return log
    return None


def save_feedback(record: dict, *, user_id: str | None = None) -> dict:
    """Persist one feedback submission as an existing system-log event."""

    log = SystemLog(
        log_type="反馈提交",
        user_id=user_id,
        icon="bi bi-chat-left-text",
        content=json.dumps(record, ensure_ascii=False, sort_keys=True),
    )
    db.session.add(log)
    db.session.commit()
    return record


def find_feedback(feedback_id: str) -> dict | None:
    """Find a receipt-safe record by its opaque public identifier."""

    log = _find_feedback_log(feedback_id)
    return _feedback_record_from_log(log) if log else None


def update_feedback_status(
    feedback_id: str,
    new_status: str,
    *,
    actor_id: str | None = None,
    note: str = "",
) -> tuple[dict, str | None]:
    """Advance one feedback item and append a small audit event.

    The JSON event remains the source of truth for compatibility with the v1
    release.  The transition graph deliberately prevents an administrator
    from skipping the triage and resolution steps or reopening a closed item.
    """

    new_status = str(new_status or "").strip()
    if new_status not in FEEDBACK_STATUS_LABELS:
        raise FeedbackStatusError("请选择有效的反馈状态。")

    log = _find_feedback_log(feedback_id)
    if log is None:
        raise FeedbackStatusError("反馈不存在或已被移除。", code="not_found")

    record = _feedback_record_from_log(log)
    if record is None:
        raise FeedbackStatusError("反馈记录无法读取。", code="invalid_record")
    current_status = record["status"]
    if current_status == new_status:
        raise FeedbackStatusError("反馈已经处于这个状态。", code="unchanged")
    if new_status not in _FEEDBACK_STATUS_TRANSITIONS.get(current_status, set()):
        raise FeedbackStatusError(
            f"不能将“{FEEDBACK_STATUS_LABELS[current_status]}”直接改为“{FEEDBACK_STATUS_LABELS[new_status]}”。",
            code="invalid_transition",
        )

    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    history = list(record.get("status_history") or [])
    history.append({"status": new_status, "at": updated_at})
    record["status"] = new_status
    record["status_history"] = history[-20:]
    record["last_updated_at"] = updated_at
    record.pop("status_label", None)
    log.content = json.dumps(record, ensure_ascii=False, sort_keys=True)

    audit = {
        "schema_version": 1,
        "feedback_id": feedback_id,
        "from_status": current_status,
        "to_status": new_status,
        "note": _clean(note, max_length=500),
        "at": updated_at,
    }
    db.session.add(SystemLog(
        log_type="反馈状态更新",
        user_id=actor_id,
        icon="bi bi-arrow-repeat",
        content=json.dumps(audit, ensure_ascii=False, sort_keys=True),
    ))
    db.session.commit()
    return _feedback_record_from_log(log), log.user_id


def list_feedback(
    *,
    limit: int = 100,
    status: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Return recent structured records for the administrator review page."""

    safe_limit = max(1, min(int(limit), 200))
    logs = (
        SystemLog.query.filter_by(log_type="反馈提交")
        .order_by(SystemLog.id.desc())
        .limit(safe_limit)
        .all()
    )
    records = []
    for log in logs:
        record = _feedback_record_from_log(log)
        if record is None:
            continue
        if status and record.get("status") != status:
            continue
        if category and record.get("category") != category:
            continue
        record["submitted_by"] = log.user_id
        records.append(record)
    return records
