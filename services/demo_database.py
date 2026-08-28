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
_LAST_CLEANUP_AT = None
_CLEANUP_INTERVAL = timedelta(minutes=1)


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


def _metadata_path(run_id: str) -> Path:
    """Return the validated lifecycle metadata path beside a run database."""

    database_path = _db_path(run_id)
    metadata_path = Path(f"{database_path}.meta").resolve()
    if metadata_path.parent != database_path.parent:
        raise ValueError("体验数据库元数据路径越界")
    return metadata_path


def _pending_delete_path(run_id: str) -> Path:
    """Return the marker used to retry deletion after a transient file lock."""

    database_path = _db_path(run_id)
    pending_path = Path(f"{database_path}.pending").resolve()
    if pending_path.parent != database_path.parent:
        raise ValueError("体验数据库待删除标记路径越界")
    return pending_path


def _sqlite_uri(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _write_run_metadata(run_id: str, created_at: datetime) -> None:
    """Persist creation time so max lifetime survives a process restart."""

    _metadata_path(run_id).write_text(created_at.isoformat(), encoding="ascii")


def _read_run_created_at(run_id: str, database_path: Path) -> datetime:
    """Read creation time, with a filesystem fallback for old run files."""

    with _LOCK:
        created_at = _RUN_CREATED_AT.get(run_id)
    if created_at is not None:
        return created_at

    try:
        raw_value = _metadata_path(run_id).read_text(encoding="ascii").strip()
        return datetime.fromisoformat(raw_value)
    except (OSError, ValueError):
        stat = database_path.stat()
        birth_timestamp = getattr(stat, "st_birthtime", None)
        if birth_timestamp is None:
            birth_timestamp = stat.st_ctime
        return datetime.utcfromtimestamp(birth_timestamp)


def _run_last_access(run_id: str, database_path: Path) -> datetime:
    with _LOCK:
        last_access = _RUN_LAST_ACCESS.get(run_id)
    if last_access is not None:
        return last_access
    return datetime.utcfromtimestamp(database_path.stat().st_mtime)


def _is_expired(run_id: str, now: datetime) -> bool:
    database_path = _db_path(run_id)
    if not database_path.exists():
        return True
    try:
        created_at = _read_run_created_at(run_id, database_path)
        last_access = _run_last_access(run_id, database_path)
    except FileNotFoundError:
        return True
    return (
        now - last_access > DEMO_IDLE_TIMEOUT
        or now - created_at > DEMO_MAX_LIFETIME
    )


def _unlink_with_retry(path: Path) -> bool:
    """Delete one sidecar, returning false when another process still holds it."""

    for attempt in range(3):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == 2:
                return False
            time.sleep(0.02)
    return False


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
    try:
        db.metadata.create_all(bind=engine)
        _write_run_metadata(run_id, created_at)
    except Exception:
        try:
            engine.dispose(close=True)
        except TypeError:
            engine.dispose()
        for candidate in (path, _metadata_path(run_id)):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        raise

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
    if _is_expired(run_id, datetime.utcnow()):
        # An expired browser cookie must not be allowed to query a newly
        # created formal session. The run is best-effort deleted here and the
        # signed session markers are removed below regardless of cleanup I/O.
        try:
            destroy_demo_run(run_id)
        except Exception:
            pass
        finally:
            session.pop(DEMO_SESSION_KEY, None)
            session.pop(DEMO_ROLE_SESSION_KEY, None)
            session.pop("_user_id", None)
            session.pop("login", None)
        return False
    if activate_demo_run(run_id):
        _maybe_cleanup_expired_demo_runs(datetime.utcnow())
        return True

    # A stale browser session must never fall back to the formal database.
    session.pop(DEMO_SESSION_KEY, None)
    session.pop(DEMO_ROLE_SESSION_KEY, None)
    session.pop("_user_id", None)
    session.pop("login", None)
    return False


def destroy_demo_run(run_id: str) -> bool:
    """Dispose and delete one temporary database and its SQLite sidecars.

    A worker may still hold a connection briefly after the browser logs out.
    Windows refuses to unlink such a file, so cleanup is deliberately
    best-effort: a marker is left behind and the maintenance sweep retries it
    later instead of breaking the request or another test's teardown.
    """

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
    cleanup_failed = False
    for candidate in (
        path,
        _metadata_path(run_id),
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
        _pending_delete_path(run_id),
    ):
        if candidate.exists():
            existed = True
            if not _unlink_with_retry(candidate):
                cleanup_failed = True

    if cleanup_failed:
        try:
            _pending_delete_path(run_id).touch(exist_ok=True)
        except OSError:
            pass
        return False
    return existed or engine is not None


def cleanup_expired_demo_runs(now: datetime | None = None) -> int:
    """Delete stale demo files, including files left by a crashed worker."""

    now = now or datetime.utcnow()
    removed = 0
    root = _demo_root()
    run_ids = set()
    for path in root.glob("*.sqlite3"):
        if _RUN_ID_PATTERN.fullmatch(path.stem):
            run_ids.add(path.stem)
    pending_suffix = ".sqlite3.pending"
    for path in root.glob(f"*{pending_suffix}"):
        if path.name.endswith(pending_suffix):
            run_id = path.name[: -len(pending_suffix)]
            if _RUN_ID_PATTERN.fullmatch(run_id):
                run_ids.add(run_id)

    for run_id in run_ids:
        try:
            expired = _pending_delete_path(run_id).exists() or _is_expired(
                run_id,
                now,
            )
        except (OSError, ValueError):
            continue
        if not expired:
            continue
        try:
            deleted = destroy_demo_run(run_id)
        except OSError:
            # A different process can still own the SQLite handle. Continue
            # with other sessions and let the next sweep retry this one.
            continue
        if deleted:
            removed += 1
    return removed


def _maybe_cleanup_expired_demo_runs(now: datetime) -> None:
    """Throttle cross-session cleanup while checking the current run eagerly."""

    global _LAST_CLEANUP_AT
    with _LOCK:
        if (
            _LAST_CLEANUP_AT is not None
            and now - _LAST_CLEANUP_AT < _CLEANUP_INTERVAL
        ):
            return
        _LAST_CLEANUP_AT = now
    try:
        cleanup_expired_demo_runs(now)
    except Exception:
        # Cleanup is maintenance; a locked sidecar must not break an active
        # visitor request. The next interval will retry it.
        with _LOCK:
            _LAST_CLEANUP_AT = None


def destroy_all_demo_runs() -> int:
    """Remove runs owned by this process, primarily for test cleanup.

    Do not scan every file in the shared temp directory here: test teardown
    must never remove an active visitor's session from another process.
    Cross-process leftovers are handled by ``cleanup_expired_demo_runs``.
    """

    with _LOCK:
        run_ids = set(_ENGINES)

    removed = 0
    for run_id in run_ids:
        try:
            deleted = destroy_demo_run(run_id)
        except OSError:
            # A background worker may still be finishing a task for this run.
            # Leave the pending marker for a later maintenance sweep.
            continue
        if deleted:
            removed += 1
    return removed
