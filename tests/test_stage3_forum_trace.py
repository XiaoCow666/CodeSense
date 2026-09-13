import json
from pathlib import Path

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import (
    Assignment,
    AssignmentThinkingPreset,
    ThinkingSession,
    ThinkingStageLog,
    User,
    db,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
THINKING_JS = (PROJECT_ROOT / "static" / "js" / "thinking.js").read_text(encoding="utf-8")
THINKING_CSS = (PROJECT_ROOT / "static" / "css" / "thinking.css").read_text(encoding="utf-8")


@pytest.fixture
def stage3_trace_context(tmp_path, monkeypatch):
    database_path = tmp_path / "stage3_forum_trace.db"
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    with app.app_context():
        assert db.engine.url.database == str(database_path)
        db.create_all()
        student = User(student_id="student-1", username="student-1", usertype="学生")
        student.password = "password"
        assignment = Assignment(
            title="循环练习",
            description="解释循环边界并修复错误代码",
            creator_id="student-1",
        )
        preset = AssignmentThinkingPreset(
            assignment=assignment,
            reference_code="int main() { return 0; }",
            key_steps=json.dumps(["输入", "循环边界", "输出"], ensure_ascii=False),
            difficulty_config=json.dumps({}, ensure_ascii=False),
            quiz_steps='[{"step": "循环边界"}]',
            status="ready",
        )
        session = ThinkingSession(
            student=student,
            assignment=assignment,
            current_stage=3,
            stage2_completed=True,
        )
        db.session.add_all([student, assignment, preset, session])
        db.session.commit()
        session_id = session.id
    client = app.test_client()
    client.post("/login", data={"username": "student-1", "password": "password"}, base_url="http://example.com")
    yield app, client, session_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_stage3_forum_trace_returns_only_the_safe_local_debug_mapping(stage3_trace_context):
    app, client, session_id = stage3_trace_context
    with app.app_context():
        db.session.add_all([
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="agent_user_message",
                role="student",
                content="为什么这里会越界？",
                metadata_json=json.dumps({
                    "request_id": "forum-1",
                    "target_role": "teacher_agent",
                    "input_kind": "chat",
                    "decision": {"full_prompt": "hidden"},
                    "internal_signals": {"student_probe": {"goal": "hidden"}},
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="tool_result",
                role="teacher_agent",
                content="",
                metadata_json=json.dumps({
                    "request_id": "forum-1",
                    "target_role": "teacher_agent",
                    "input_kind": "chat",
                    "tool_call": {
                        "name": "request_student_probe",
                        "arguments": {"concept": "循环边界", "goal": "hidden"},
                    },
                    "artifact": {"reference_code": "hidden", "bugs": ["secret"]},
                    "decision": {"next": "hidden"},
                    "prompt": "hidden",
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="tool_result",
                role="student_agent",
                content="",
                metadata_json=json.dumps({
                    "request_id": "probe-1",
                    "target_role": "user",
                    "input_kind": "intervention",
                    "tool_call": {"name": "assess_teaching_progress", "arguments": {"assessment": "covered"}},
                    "ui_action": "show_code_review",
                    "state_patch": {"coverage_score": 0.5},
                    "state_decision": {"full": "hidden"},
                    "trigger": {"concept": "循环边界"},
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="agent_message",
                role="student_agent",
                content="请解释一下边界条件。",
                metadata_json=json.dumps({
                    "request_id": "probe-1",
                    "target_role": "user",
                    "message_kind": "student_probe",
                    "visibility": "public",
                    "tool_arguments": {"question": "hidden"},
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="state_snapshot",
                role="system",
                content="",
                metadata_json=json.dumps({
                    "state_patch": {"coverage_score": float("nan")},
                }, ensure_ascii=False),
            ),
        ])
        db.session.commit()

    response = client.post(
        "/thinking/api/stage3/forum/trace",
        json={"session_id": session_id},
        base_url="http://localhost",
    )

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "session_id": session_id,
        "trace": [
            {
                "event_type": "agent_user_message",
                "role": "student",
                "target_role": "teacher_agent",
                "input_kind": "chat",
                "tool_name": None,
                "coverage_score": None,
                "ui_action": None,
            },
            {
                "event_type": "tool_result",
                "role": "teacher_agent",
                "target_role": "teacher_agent",
                "input_kind": "chat",
                "tool_name": "request_student_probe",
                "coverage_score": None,
                "ui_action": None,
            },
            {
                "event_type": "tool_result",
                "role": "student_agent",
                "target_role": "user",
                "input_kind": "intervention",
                "tool_name": "assess_teaching_progress",
                "coverage_score": 0.5,
                "ui_action": "show_code_review",
            },
            {
                "event_type": "agent_message",
                "role": "student_agent",
                "target_role": "user",
                "input_kind": None,
                "tool_name": None,
                "coverage_score": None,
                "ui_action": None,
            },
            {
                "event_type": "state_snapshot",
                "role": "system",
                "target_role": None,
                "input_kind": None,
                "tool_name": None,
                "coverage_score": None,
                "ui_action": None,
            },
        ],
    }
    body = json.dumps(response.json, ensure_ascii=False)
    for forbidden in (
        "artifact",
        "reference_code",
        "bugs",
        "decision",
        "prompt",
        "internal_signals",
        "tool_arguments",
        "trigger",
        "arguments",
        "hidden",
    ):
        assert forbidden not in body


def test_stage3_forum_trace_allows_local_peer_even_with_non_loopback_host(stage3_trace_context):
    app, client, session_id = stage3_trace_context
    app.debug = False

    response = client.post(
        "/thinking/api/stage3/forum/trace",
        json={"session_id": session_id},
        base_url="http://example.com",
    )

    assert response.status_code == 200
    assert response.json["success"] is True


def test_stage3_forum_trace_returns_stable_missing_session_error(stage3_trace_context):
    _, client, _ = stage3_trace_context

    response = client.post(
        "/thinking/api/stage3/forum/trace",
        json={"session_id": 999999},
        base_url="http://localhost",
    )

    assert response.status_code == 403
    assert response.json["error_code"] == "SESSION_NOT_FOUND"


def test_stage3_forum_trace_rejects_remote_peer_even_with_loopback_host(stage3_trace_context):
    _, client, session_id = stage3_trace_context

    response = client.post(
        "/thinking/api/stage3/forum/trace",
        json={"session_id": session_id},
        base_url="http://localhost",
        environ_overrides={"REMOTE_ADDR": "203.0.113.9"},
    )

    assert response.status_code == 403
    assert response.json["error_code"] == "DEV_TRACE_DISABLED"


def test_stage3_forum_trace_rejects_remote_peer_even_when_debug_enabled(stage3_trace_context):
    app, client, session_id = stage3_trace_context
    app.debug = True

    response = client.post(
        "/thinking/api/stage3/forum/trace",
        json={"session_id": session_id},
        base_url="http://localhost",
        environ_overrides={"REMOTE_ADDR": "198.51.100.24"},
    )

    assert response.status_code == 403
    assert response.json["error_code"] == "DEV_TRACE_DISABLED"


def test_stage3_trace_debug_panel_contract_is_collapsible_and_uses_safe_text_rendering():
    assert "dev-debug-trace" in THINKING_JS
    assert "dev-debug-trace-list" in THINKING_JS
    assert "dev-debug-trace-empty" in THINKING_JS
    assert "traceValue.textContent" in THINKING_JS
    assert "traceItem.innerHTML" not in THINKING_JS
    assert "codesense-dev-debug-panel-collapsed" in THINKING_JS
    assert ".dev-debug-panel.is-collapsed .dev-debug-content" in THINKING_CSS
    assert ".dev-debug-trace-list" in THINKING_CSS
