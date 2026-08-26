"""Per-session temporary database support for the public demo experience."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import threading
import time
import gc
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from flask import g, has_request_context, session
from sqlalchemy import create_engine

from models import db


DEMO_SESSION_KEY = "demo_run_id"
DEMO_ROLE_SESSION_KEY = "demo_role"
DEMO_ID_PREFIX = "demo:"
DEMO_STUDENT_ID = "demo_s_001"
DEMO_TEACHER_ID = "demo_t_001"
DEMO_IDLE_TIMEOUT = timedelta(hours=1)
DEMO_MAX_LIFETIME = timedelta(hours=2)

_RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{48}$")
_LOCK = threading.RLock()
_ENGINES = {}
_RUN_CREATED_AT = {}
_RUN_LAST_ACCESS = {}


def _demo_root() -> Path:
    root = Path(tempfile.gettempdir()) / "codesense-demo-runs"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("无效的体验会话标识")
    return run_id


def _db_path(run_id: str) -> Path:
    run_id = _validate_run_id(run_id)
    root = _demo_root().resolve()
    path = (root / f"{run_id}.sqlite3").resolve()
    if path.parent != root:
        raise ValueError("体验数据库路径越界")
    return path


def _sqlite_uri(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@dataclass(frozen=True)
class DemoRun:
    """A single public-demo database and its stable temporary identities."""

    run_id: str
    role: str
    student_id: str
    teacher_id: str
    db_path: str
    created_at: datetime


class DemoPrincipal:
    """Flask-Login principal backed by a temporary-database User row."""

    is_demo = True
    is_active = True
    is_authenticated = True
    is_anonymous = False

    def __init__(self, user, run_id: str):
        self._user = user
        self.run_id = _validate_run_id(run_id)

    def get_id(self) -> str:
        return f"{DEMO_ID_PREFIX}{self.run_id}"

    def __getattr__(self, name):
        return getattr(self._user, name)

    def __repr__(self) -> str:
        return f"<DemoPrincipal {self.get_id()}>"


def is_demo_login_id(user_id: str) -> bool:
    """Return whether a Flask-Login id belongs to the demo namespace."""

    return (
        isinstance(user_id, str)
        and user_id.startswith(DEMO_ID_PREFIX)
        and bool(_RUN_ID_PATTERN.fullmatch(user_id[len(DEMO_ID_PREFIX) :]))
    )


def current_demo_run_id() -> str | None:
    """Read the current run id from the server-side Flask session."""

    if not has_request_context():
        return None
    run_id = session.get(DEMO_SESSION_KEY)
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        return None
    return run_id


def login_demo_run(run: DemoRun) -> DemoPrincipal:
    """Log in the temporary User row without creating a formal user."""

    from flask_login import login_user
    from models import User

    user_id = run.teacher_id if run.role == "teacher" else run.student_id
    user = db.session.get(User, user_id)
    if user is None:
        raise RuntimeError("临时体验用户初始化失败")

    principal = DemoPrincipal(user, run.run_id)
    login_user(principal)
    session[DEMO_SESSION_KEY] = run.run_id
    session[DEMO_ROLE_SESSION_KEY] = run.role
    session["current_session_id"] = f"{DEMO_ID_PREFIX}{run.run_id}"
    session["student_id"] = user.student_id
    session["username"] = user.username
    session["full_name"] = user.full_name or user.username
    session["usertype"] = user.usertype
    session["login"] = True
    return principal


def load_demo_principal(user_id: str) -> DemoPrincipal | None:
    """Load a temporary principal for Flask-Login's user loader."""

    if not is_demo_login_id(user_id):
        return None
    run_id = user_id[len(DEMO_ID_PREFIX) :]
    if not activate_demo_run(run_id):
        return None

    from models import User

    student_id = session.get("student_id")
    user = db.session.get(User, student_id) if student_id else None
    if user is None:
        return None
    return DemoPrincipal(user, run_id)


def _engine_for_run(run_id: str):
    run_id = _validate_run_id(run_id)
    path = _db_path(run_id)
    with _LOCK:
        engine = _ENGINES.get(run_id)
        if engine is not None:
            return engine
        if not path.exists():
            return None
        engine = create_engine(
            _sqlite_uri(path),
            connect_args={"check_same_thread": False},
        )
        _ENGINES[run_id] = engine
        return engine


def create_demo_run(role: str) -> DemoRun:
    """Create a fresh temporary SQLite database for one browser session."""

    if role not in {"student", "teacher"}:
        raise ValueError("体验角色必须是 student 或 teacher")

    created_at = datetime.utcnow()
    run_id = secrets.token_hex(24)
    path = _db_path(run_id)
    engine = create_engine(
        _sqlite_uri(path),
        connect_args={"check_same_thread": False},
    )

    # The model metadata is used only with this newly-created engine. The
    # application's configured engine is never passed to create_all here.
    db.metadata.create_all(bind=engine)

    with _LOCK:
        _ENGINES[run_id] = engine
        _RUN_CREATED_AT[run_id] = created_at
        _RUN_LAST_ACCESS[run_id] = created_at

    return DemoRun(
        run_id=run_id,
        role=role,
        student_id=DEMO_STUDENT_ID,
        teacher_id=DEMO_TEACHER_ID,
        db_path=str(path),
        created_at=created_at,
    )


def activate_demo_run(run_id: str) -> bool:
    """Bind the current Flask-SQLAlchemy scoped session to a demo engine."""

    engine = _engine_for_run(run_id)
    if engine is None:
        return False

    # A scoped session may have been materialized by Flask-Login or another
    # before-request hook. Remove it before assigning the temporary bind so no
    # production connection or identity map can leak into the demo request.
    db.session.remove()
    request_session = db.session()
    request_session._codesense_demo_bind = engine

    now = datetime.utcnow()
    with _LOCK:
        _RUN_LAST_ACCESS[run_id] = now
    path = _db_path(run_id)
    try:
        os.utime(path, None)
    except OSError:
        pass
    if has_request_context():
        g.demo_run_id = run_id
    return True


def is_active_demo_run(run_id: str) -> bool:
    """Return whether the current scoped session is bound to this demo run."""

    engine = _engine_for_run(run_id)
    if engine is None:
        return False
    try:
        return getattr(db.session(), '_codesense_demo_bind', None) is engine
    except RuntimeError:
        return False


def activate_demo_request_database() -> bool:
    """Activate the database selected by the current request's session."""

    run_id = current_demo_run_id()
    if not run_id:
        return False
    if activate_demo_run(run_id):
        return True

    # A stale browser session must never fall back to the formal database.
    session.pop(DEMO_SESSION_KEY, None)
    session.pop(DEMO_ROLE_SESSION_KEY, None)
    session.pop("_user_id", None)
    session.pop("login", None)
    return False


def destroy_demo_run(run_id: str) -> bool:
    """Dispose and delete one temporary database and its SQLite sidecars."""

    path = _db_path(run_id)
    with _LOCK:
        engine = _ENGINES.pop(run_id, None)
        _RUN_CREATED_AT.pop(run_id, None)
        _RUN_LAST_ACCESS.pop(run_id, None)
    if engine is not None:
        try:
            engine.dispose(close=True)
        except TypeError:
            engine.dispose()
        gc.collect()

    existed = False
    for candidate in (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    ):
        if candidate.exists():
            existed = True
            for attempt in range(3):
                try:
                    candidate.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.02)
    return existed or engine is not None


def cleanup_expired_demo_runs(now: datetime | None = None) -> int:
    """Delete stale demo files, including files left by a crashed worker."""

    now = now or datetime.utcnow()
    removed = 0
    root = _demo_root()
    for path in root.glob("*.sqlite3"):
        try:
            modified_at = datetime.utcfromtimestamp(path.stat().st_mtime)
        except FileNotFoundError:
            continue
        if now - modified_at <= DEMO_IDLE_TIMEOUT:
            continue
        run_id = path.stem
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            continue
        if destroy_demo_run(run_id):
            removed += 1
    return removed


def destroy_all_demo_runs() -> int:
    """Remove every valid demo run, primarily for deterministic test cleanup."""
    root = _demo_root()
    run_ids = set()
    with _LOCK:
        run_ids.update(_ENGINES)
    for path in root.glob('*.sqlite3'):
        if _RUN_ID_PATTERN.fullmatch(path.stem):
            run_ids.add(path.stem)

    removed = 0
    for run_id in run_ids:
        if destroy_demo_run(run_id):
            removed += 1
    return removed
