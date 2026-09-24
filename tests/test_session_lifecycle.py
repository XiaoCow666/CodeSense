from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app import create_app
from config import TestingConfig
from models import Assignment, ThinkingSession, ThinkingStageLog, User, db


UTC_NOW = datetime(2026, 9, 14, 12, 0, 0)


def _session(**overrides):
    values = {
        "id": 7,
        "student_id": "student-1",
        "assignment_id": 11,
        "current_stage": 1,
        "stage1_description": None,
        "stage1_score": None,
        "stage1_hint_count": 0,
        "stage2_completed": False,
        "stage2_hint_count": 0,
        "stage3_completed": False,
        "total_time_seconds": 0,
        "started_at": UTC_NOW - timedelta(minutes=5),
        "completed_at": None,
        "status": "in_progress",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_active_and_idle_status_use_latest_activity_and_threshold():
    from services.session_lifecycle import session_lifecycle_status

    assert session_lifecycle_status(
        _session(started_at=UTC_NOW - timedelta(hours=1)),
        now=UTC_NOW,
        last_activity_at=UTC_NOW - timedelta(minutes=30),
    ) == "active"
    assert session_lifecycle_status(
        _session(started_at=UTC_NOW - timedelta(hours=1)),
        now=UTC_NOW,
        last_activity_at=UTC_NOW - timedelta(minutes=30, seconds=1),
    ) == "idle"


@pytest.mark.parametrize(
    ("persisted_status", "expected"),
    [("completed", "completed"), ("abandoned", "abandoned")],
)
def test_terminal_persisted_status_wins_over_clock(persisted_status, expected):
    from services.session_lifecycle import session_lifecycle_status

    assert session_lifecycle_status(
        _session(status=persisted_status),
        now=UTC_NOW,
        last_activity_at=UTC_NOW,
    ) == expected


def test_unknown_or_missing_dates_fail_closed_to_idle():
    from services.session_lifecycle import session_lifecycle_status

    assert session_lifecycle_status(_session(status="legacy", started_at=None), now=UTC_NOW) == "idle"
    assert session_lifecycle_status(_session(started_at=None), now=UTC_NOW) == "idle"


def test_elapsed_projection_handles_future_clock_and_legacy_client_timer():
    from services.session_lifecycle import session_elapsed_details

    future = _session(started_at=UTC_NOW + timedelta(minutes=2))
    assert session_elapsed_details(future, now=UTC_NOW) == {
        "elapsed_seconds": 0,
        "elapsed_source": "server_clock",
    }

    legacy = _session(
        status="completed",
        total_time_seconds=91,
        completed_at=UTC_NOW - timedelta(minutes=1),
    )
    assert session_elapsed_details(legacy, now=UTC_NOW) == {
        "elapsed_seconds": 91,
        "elapsed_source": "stored_client_timer",
    }


def test_elapsed_projection_falls_back_to_terminal_timestamps():
    from services.session_lifecycle import session_elapsed_details

    session = _session(
        status="completed",
        started_at=UTC_NOW - timedelta(minutes=4),
        completed_at=UTC_NOW - timedelta(minutes=1),
    )
    assert session_elapsed_details(session, now=UTC_NOW) == {
        "elapsed_seconds": 180,
        "elapsed_source": "timestamps",
    }


@pytest.mark.parametrize(
    ("updates", "expected_percent", "expected_next"),
    [
        ({}, 0, "完成本阶段的思路描述"),
        ({"current_stage": 2, "stage1_description": "先遍历再输出"}, 33, "完成代码块拼装与校验"),
        ({"current_stage": 3, "stage2_completed": True}, 67, "完成讲解、编写并修复代码"),
        ({"current_stage": 3, "stage2_completed": True, "stage3_completed": True, "status": "completed"}, 100, "查看本次学习记录"),
    ],
)
def test_payload_exposes_stage_progress_and_next_action(updates, expected_percent, expected_next):
    from services.session_lifecycle import session_lifecycle_payload

    payload = session_lifecycle_payload(
        _session(**updates),
        now=UTC_NOW,
        last_activity_at=UTC_NOW,
    )

    assert payload["progress_percent"] == expected_percent
    assert payload["next_action"] == expected_next
    assert len(payload["stages"]) == 3
    assert payload["last_activity_at"].endswith("Z")


def test_latest_session_activity_returns_one_bounded_aggregate_mapping(tmp_path, monkeypatch):
    database_path = tmp_path / "session-lifecycle.db"
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        student = User(student_id="student-1", username="student-1", usertype="学生")
        student.password = "password"
        assignment = Assignment(title="聚合测试", description="", creator_id="teacher-1")
        first = ThinkingSession(student_id="student-1", assignment=assignment)
        second = ThinkingSession(student_id="student-1", assignment=assignment)
        db.session.add_all([student, assignment, first, second])
        db.session.flush()
        db.session.add_all([
            ThinkingStageLog(
                session_id=first.id,
                stage=1,
                event_type="session_start",
                role="student",
                content="",
                created_at=UTC_NOW - timedelta(minutes=9),
            ),
            ThinkingStageLog(
                session_id=first.id,
                stage=1,
                event_type="description_submit",
                role="student",
                content="",
                created_at=UTC_NOW - timedelta(minutes=1),
            ),
        ])
        db.session.commit()

        from services.session_lifecycle import latest_session_activity

        statements = []

        def record_statement(connection, cursor, statement, parameters, context, executemany):
            if "thinking_stage_logs" in statement:
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", record_statement)
        try:
            activity = latest_session_activity([first.id, second.id, first.id, 999999])
        finally:
            event.remove(db.engine, "before_cursor_execute", record_statement)

        assert activity == {first.id: UTC_NOW - timedelta(minutes=1)}
        assert len(statements) == 1

        db.session.remove()
        db.drop_all()


def test_can_view_session_limits_teacher_to_owner_or_managed_class():
    from services.session_lifecycle import can_view_session

    owner = SimpleNamespace(student_id="student-1", is_admin=False, is_teacher=False)
    teacher = SimpleNamespace(student_id="teacher-1", is_admin=False, is_teacher=True)
    other_teacher = SimpleNamespace(student_id="teacher-2", is_admin=False, is_teacher=True)
    admin = SimpleNamespace(student_id="admin-1", is_admin=True, is_teacher=False)
    assignment = SimpleNamespace(creator_id="teacher-1")
    student = SimpleNamespace(student_id="student-1", class_id=None)
    session = SimpleNamespace(student_id="student-1", student=student, assignment=assignment)

    assert can_view_session(owner, session) is True
    assert can_view_session(admin, session) is True
    assert can_view_session(teacher, session) is True
    assert can_view_session(other_teacher, session) is False


def test_payload_self_fetches_latest_activity_when_omitted(monkeypatch):
    """单 session 调用者不传 last_activity_at 时，payload 应自查最近活动。

    维护痛点：此前每个单 session 调用者都要手写
    ``last_activity_at=latest_session_activity([id]).get(id)``，漏传就会
    退化成用 started_at 判 idle（刚活动的会话被误判 idle）。改为 payload
    内部自查后，调用者不再需要重复这行。
    """
    from services import session_lifecycle

    calls = []
    logged_activity = UTC_NOW - timedelta(minutes=2)

    def fake_latest_activity(ids):
        calls.append(list(ids))
        return {7: logged_activity}

    monkeypatch.setattr(
        session_lifecycle, "latest_session_activity", fake_latest_activity
    )

    payload = session_lifecycle.session_lifecycle_payload(
        _session(),  # id=7, started_at=UTC_NOW-5min
        now=UTC_NOW,
    )

    # 用 session.id 自查一次
    assert calls == [[7]]
    # last_activity_at 取日志时间，而非 started_at
    assert payload["last_activity_at"] == logged_activity.strftime("%Y-%m-%dT%H:%M:%SZ")
    # activity_age 基于日志时间计算（约 2 分钟），不是 started_at 的 5 分钟
    assert 110 <= payload["activity_age_seconds"] <= 130


def test_payload_keeps_provided_activity_without_extra_query(monkeypatch):
    """批量场景显式传 last_activity_at 时，不再自查，避免 N+1。"""
    from services import session_lifecycle

    calls = []

    def fake_latest_activity(ids):
        calls.append(list(ids))
        return {}

    monkeypatch.setattr(
        session_lifecycle, "latest_session_activity", fake_latest_activity
    )

    provided = UTC_NOW - timedelta(minutes=3)
    payload = session_lifecycle.session_lifecycle_payload(
        _session(),
        now=UTC_NOW,
        last_activity_at=provided,
    )

    assert calls == []  # 没有触发自查
    assert payload["last_activity_at"] == provided.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_payload_explicit_none_activity_skips_query_and_falls_back_to_started_at(monkeypatch):
    """显式传入 last_activity_at=None 不得触发自查。

    批量调用者先 latest_session_activity([...]) 一次查出映射，未命中的
    会话得到 None 后会显式传入。若 payload 把显式 None 当成"省略参数"
    再次自查，教师概览等列表就会为每个无活动记录的会话额外发一次查询
    （N+1）。显式 None 必须保留改前行为：不查询，按现有规则回退到
    started_at。
    """
    from services import session_lifecycle

    calls = []

    def fake_latest_activity(ids):
        calls.append(list(ids))
        return {}

    monkeypatch.setattr(
        session_lifecycle, "latest_session_activity", fake_latest_activity
    )

    payload = session_lifecycle.session_lifecycle_payload(
        _session(),  # started_at = UTC_NOW - 5min
        now=UTC_NOW,
        last_activity_at=None,
    )

    assert calls == []  # 显式 None 与省略参数不同：不执行查询
    # 回退到改前既有规则：以 started_at 作为活动时间
    assert payload["last_activity_at"] == (UTC_NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 290 <= payload["activity_age_seconds"] <= 310
