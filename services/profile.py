"""Privacy-scoped profile preferences stored without a schema migration."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from models import SystemLog, db


PROFILE_LOG_TYPE = "个人资料设置"
PROFILE_SCHEMA_VERSION = 1
PROFILE_VISIBILITY_PRIVATE = "private"
PROFILE_VISIBILITY_PUBLIC = "public"
PROFILE_VISIBILITY_OPTIONS = (
    (PROFILE_VISIBILITY_PRIVATE, "仅自己和有权限的教学人员可见"),
    (PROFILE_VISIBILITY_PUBLIC, "允许通过公开链接查看基础资料"),
)


def _default_profile_settings() -> dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_visibility": PROFILE_VISIBILITY_PRIVATE,
        "bio": "",
        "updated_at": None,
    }


def _parse(log) -> dict | None:
    try:
        payload = json.loads(log.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        return None
    visibility = payload.get("profile_visibility")
    if visibility not in {PROFILE_VISIBILITY_PRIVATE, PROFILE_VISIBILITY_PUBLIC}:
        visibility = PROFILE_VISIBILITY_PRIVATE
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_visibility": visibility,
        "bio": str(payload.get("bio") or "").strip()[:300],
        "updated_at": payload.get("updated_at"),
    }


def get_profile_settings(user_id: str | None) -> dict:
    if not user_id:
        return _default_profile_settings()
    logs = (
        SystemLog.query.filter_by(log_type=PROFILE_LOG_TYPE, user_id=user_id)
        .order_by(SystemLog.id.desc())
        .limit(20)
        .all()
    )
    for log in logs:
        payload = _parse(log)
        if payload:
            return payload
    return _default_profile_settings()


def save_profile_settings(
    user_id: str,
    *,
    bio: str | None,
    profile_visibility: str | None,
    commit: bool = True,
) -> dict:
    visibility = profile_visibility if profile_visibility in {
        PROFILE_VISIBILITY_PRIVATE,
        PROFILE_VISIBILITY_PUBLIC,
    } else PROFILE_VISIBILITY_PRIVATE
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_visibility": visibility,
        "bio": str(bio or "").strip()[:300],
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    db.session.add(SystemLog(
        log_type=PROFILE_LOG_TYPE,
        user_id=user_id,
        icon="bi bi-person-badge",
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    ))
    if commit:
        db.session.commit()
    return payload
