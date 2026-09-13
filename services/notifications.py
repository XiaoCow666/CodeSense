"""Small in-app notification adapter backed by existing system-log events.

This is intentionally local-only.  It gives the product a stable notification
contract without pretending that email, SMS, or push delivery is configured.
External providers can be added behind this module later.
"""

from __future__ import annotations

import json
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock

from models import SystemLog, User, db


NOTIFICATION_LOG_TYPE = "站内通知"
NOTIFICATION_SCHEMA_VERSION = 1
MAX_NOTIFICATION_SCAN = 500
_NOTIFICATION_LOCKS = defaultdict(RLock)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_local_url(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        return None
    return value[:300]


@contextmanager
def _notification_write_lock(user_id: str, idempotency_key: str | None):
    """Serialize duplicate checks and inserts for one recipient/key pair."""

    lock_key = f"{user_id}:{idempotency_key or 'unkeyed'}"
    with _NOTIFICATION_LOCKS[lock_key]:
        bind = db.session.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "")
        if dialect in {"mysql", "mariadb", "postgresql"}:
            # SystemLog has no uniqueness constraint by design. Locking the
            # recipient row makes the check-then-insert atomic on the
            # production databases without a migration.
            db.session.query(User).filter_by(student_id=user_id).with_for_update().first()
        yield


def _find_existing_notification(user_id: str, idempotency_key: str) -> dict | None:
    logs = (
        SystemLog.query.filter_by(
            log_type=NOTIFICATION_LOG_TYPE,
            user_id=user_id,
        )
        .order_by(SystemLog.id.desc())
        .limit(MAX_NOTIFICATION_SCAN)
        .all()
    )
    for log in logs:
        payload = _parse(log)
        if payload and payload.get("idempotency_key") == idempotency_key:
            return payload
    return None


def _parse(log) -> dict | None:
    try:
        payload = json.loads(log.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != NOTIFICATION_SCHEMA_VERSION:
        return None
    if not payload.get("title") or not payload.get("message"):
        return None
    payload["id"] = log.id
    payload["created_at"] = payload.get("created_at") or (
        log.created_at.isoformat() if log.created_at else ""
    )
    payload["read"] = bool(payload.get("read"))
    return payload


def create_notification(
    user_id: str | None,
    *,
    kind: str,
    title: str,
    message: str,
    url: str | None = None,
    idempotency_key: str | None = None,
) -> dict | None:
    """Persist one notification, returning an existing event for duplicate keys."""

    if not user_id:
        return None
    normalized_key = str(idempotency_key or "").strip()[:120] or None
    with _notification_write_lock(user_id, normalized_key):
        if normalized_key:
            existing = _find_existing_notification(user_id, normalized_key)
            if existing:
                return existing

        payload = {
            "schema_version": NOTIFICATION_SCHEMA_VERSION,
            "kind": str(kind or "general").strip()[:40] or "general",
            "title": str(title or "通知").strip()[:120] or "通知",
            "message": str(message or "").strip()[:400],
            "url": _safe_local_url(url),
            "read": False,
            "read_at": None,
            "created_at": _now_iso(),
        }
        if normalized_key:
            payload["idempotency_key"] = normalized_key

        log = SystemLog(
            log_type=NOTIFICATION_LOG_TYPE,
            user_id=user_id,
            icon="bi bi-bell",
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        db.session.add(log)
        db.session.commit()
        parsed = _parse(log)
        return parsed


def list_notifications(
    user_id: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Return bounded, user-owned notifications newest first."""

    safe_limit = max(1, min(int(limit), 100))
    logs = (
        SystemLog.query.filter_by(log_type=NOTIFICATION_LOG_TYPE, user_id=user_id)
        .order_by(SystemLog.id.desc())
        .limit(MAX_NOTIFICATION_SCAN)
        .all()
    )
    notifications = []
    for log in logs:
        payload = _parse(log)
        if payload is None or (unread_only and payload["read"]):
            continue
        notifications.append(payload)
        if len(notifications) >= safe_limit:
            break
    return notifications


def count_unread(user_id: str | None) -> int:
    if not user_id:
        return 0
    logs = (
        SystemLog.query.filter_by(log_type=NOTIFICATION_LOG_TYPE, user_id=user_id)
        .order_by(SystemLog.id.desc())
        .limit(MAX_NOTIFICATION_SCAN)
        .all()
    )
    return sum(1 for log in logs if (payload := _parse(log)) and not payload["read"])


def mark_notification_read(user_id: str, notification_id: int) -> bool:
    log = SystemLog.query.filter_by(
        id=notification_id,
        log_type=NOTIFICATION_LOG_TYPE,
        user_id=user_id,
    ).first()
    if log is None:
        return False
    payload = _parse(log)
    if payload is None:
        return False
    if not payload["read"]:
        payload["read"] = True
        payload["read_at"] = _now_iso()
        payload.pop("id", None)
        payload.pop("created_at", None)
        db.session.query(SystemLog).filter_by(id=notification_id).update({
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        })
        db.session.commit()
    return True


def mark_all_notifications_read(user_id: str) -> int:
    logs = (
        SystemLog.query.filter_by(log_type=NOTIFICATION_LOG_TYPE, user_id=user_id)
        .order_by(SystemLog.id.desc())
        .limit(MAX_NOTIFICATION_SCAN)
        .all()
    )
    updated = 0
    for log in logs:
        payload = _parse(log)
        if payload is None or payload["read"]:
            continue
        payload["read"] = True
        payload["read_at"] = _now_iso()
        payload.pop("id", None)
        payload.pop("created_at", None)
        log.content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        updated += 1
    if updated:
        db.session.commit()
    return updated
