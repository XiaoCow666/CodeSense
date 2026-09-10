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


@pytest.fixture
def stage3_restore_context(tmp_path, monkeypatch):
    database_path = tmp_path / "stage3_forum_restore.db"
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
            difficulty_config=json.dumps({
                "feynman_coverage": {
                    "min_coverage": 0.8,
                    "max_probes_per_concept": 2,
                    "probe_dimensions": ["core", "edge_case", "application"],
                }
            }, ensure_ascii=False),
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
        assignment_id = assignment.id
    client = app.test_client()
    client.post("/login", data={"username": "student-1", "password": "password"})
    yield app, client, session_id, assignment_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _coverage_summary(payload):
    forum_state = payload["forum_state"]
    assert set(forum_state) == {"target_role", "reply_to_event_id", "coverage_summary"}
    return forum_state["coverage_summary"]


def test_start_session_restores_public_forum_state_and_safe_coverage_summary(stage3_restore_context):
    app, client, session_id, assignment_id = stage3_restore_context
    with app.app_context():
        legacy_teacher = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="chat",
            role="student",
            content="旧老师提问",
            metadata_json=json.dumps({"panel": "teacher_agent"}, ensure_ascii=False),
        )
        forum_question = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="agent_user_message",
            role="student",
            content="论坛提问",
            metadata_json=json.dumps({
                "request_id": "forum-1",
                "source_role": "user",
                "target_role": "teacher_agent",
                "message_kind": "user_message",
                "visibility": "public",
                "input_kind": "chat",
            }, ensure_ascii=False),
        )
        teacher_answer = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="agent_message",
            role="teacher_agent",
            content="论坛回答",
            metadata_json=json.dumps({
                "request_id": "forum-1",
                "source_role": "teacher_agent",
                "target_role": "user",
                "message_kind": "agent_message",
                "visibility": "public",
            }, ensure_ascii=False),
        )
        db.session.add_all([legacy_teacher, forum_question, teacher_answer])
        db.session.commit()

        reply_to_event_id = str(teacher_answer.id)
        student_probe = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="agent_message",
            role="student_agent",
            content="请你解释为什么最后一个索引不能取到 n。",
            metadata_json=json.dumps({
                "request_id": "probe-1",
                "parent_request_id": "forum-1",
                "reply_to_event_id": reply_to_event_id,
                "source_role": "student_agent",
                "target_role": "user",
                "message_kind": "student_probe",
                "visibility": "public",
            }, ensure_ascii=False),
        )
        private_tool = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="tool_result",
            role="teacher_agent",
            content="不会出现在论坛里",
            metadata_json=json.dumps({
                "request_id": "forum-1",
                "ui_action": "continue_chat",
                "tool_call": {
                    "name": "recall_memory",
                    "arguments": {"secret": True},
                },
                "artifact": {"standard_answer": "secret", "reference_code": "hidden"},
                "public_content": {"message": "公开提示"},
                "decision": {"full_prompt": "hidden"},
            }, ensure_ascii=False),
        )
        state_snapshot = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="state_snapshot",
            role="student_agent",
            content="",
            metadata_json=json.dumps({
                "state": {
                    "phase": "student_dialogue",
                    "concept_coverage": [{
                        "concept": "循环边界",
                        "status": "covered",
                        "used_dimensions": ["core", "edge_case"],
                        "accepted_evidence_count": 1,
                        "attempts": 2,
                        "last_evidence_event_id": "probe-1",
                    }],
                    "coverage_score": 0.5,
                    "unresolved_concepts": ["输出"],
                    "ready_for_code": False,
                    "pending_probe": {
                        "concept": "输出",
                        "dimension": "application",
                        "goal": "检查用户能否解释输出格式",
                    },
                }
            }, ensure_ascii=False),
        )
        legacy_student = ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="fix_code",
            role="student",
            content="修复代码",
            metadata_json="{}",
        )
        db.session.add_all([student_probe, private_tool, state_snapshot, legacy_student])
        db.session.commit()
        student_probe_id = str(student_probe.id)

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["resumed"] is True
    assert [item["content"] for item in response.json["forum_history"]] == [
        "旧老师提问",
        "论坛提问",
        "论坛回答",
        "请你解释为什么最后一个索引不能取到 n。",
    ]
    assert response.json["forum_state"] == {
        "target_role": "student_agent",
        "reply_to_event_id": student_probe_id,
        "coverage_summary": {
            "coverage_score": 0.5,
            "ready_for_code": False,
            "unresolved_concepts": ["输出"],
            "concept_coverage": [{
                "concept": "循环边界",
                "status": "covered",
                "asked_dimensions": ["core", "edge_case"],
                "accepted_evidence_count": 1,
                "attempts": 2,
            }],
        },
    }
    assert response.json["user_goal"]["id"] == "stage3-teach-and-repair"
    assert response.json["user_goal"]["progress_percent"] == 40
    assert response.json["user_goal"]["next_action"].startswith("请回答小明")
    assert {item["content"] for item in response.json["teacher_history"]} >= {"旧老师提问", "论坛提问", "论坛回答"}
    assert {item["content"] for item in response.json["student_history"]} >= {
        "请你解释为什么最后一个索引不能取到 n。",
        "【提交代码修复】\n修复代码",
    }
    body = json.dumps(response.json, ensure_ascii=False)
    for forbidden in (
        "tool_call",
        "arguments",
        "artifact",
        "standard_answer",
        "reference_code",
        "full_prompt",
        "secret",
    ):
        assert forbidden not in body


def test_start_session_seeds_one_task_specific_teacher_prompt_for_empty_stage3_session(stage3_restore_context):
    app, client, session_id, assignment_id = stage3_restore_context

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["resumed"] is True
    assert len(response.json["forum_history"]) == 1
    prompt = response.json["forum_history"][0]
    assert prompt["source_role"] == "teacher_agent"
    assert prompt["target_role"] == "user"
    assert prompt["message_kind"] == "agent_message"
    assert prompt["visibility"] == "public"
    assert prompt["request_id"] == f"stage3-initial:{session_id}"
    assert "循环练习" in prompt["content"]
    assert "循环边界" in prompt["content"]

    second_response = client.post(
        "/thinking/api/start_session",
        json={"assignment_id": assignment_id},
    )
    assert len(second_response.json["forum_history"]) == 1

    with app.app_context():
        initial_logs = ThinkingStageLog.query.filter_by(
            session_id=session_id,
            stage=3,
            event_type="agent_message",
        ).all()
        assert len(initial_logs) == 1


def test_start_session_safely_maps_production_and_malformed_coverage_fields(stage3_restore_context):
    app, client, session_id, assignment_id = stage3_restore_context
    with app.app_context():
        db.session.add(ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="state_snapshot",
            role="student_agent",
            content="",
            metadata_json=json.dumps({
                "state": {
                    "phase": "student_dialogue",
                    "concept_coverage": [
                        {
                            "concept": "循环边界",
                            "status": "partial",
                            "used_dimensions": "core",
                            "accepted_evidence_count": "oops",
                            "attempts": None,
                            "last_evidence_event_id": "private-event-1",
                        },
                        {
                            "concept": "输出",
                            "status": "covered",
                            "used_dimensions": ["application", "", None],
                            "accepted_evidence_count": float("inf"),
                            "attempts": float("-inf"),
                            "learning_evidence": [{"secret": True}],
                        },
                    ],
                    "coverage_score": float("inf"),
                    "unresolved_concepts": "malformed-not-a-list",
                    "ready_for_code": False,
                }
            }, ensure_ascii=False),
        ))
        db.session.commit()

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["forum_state"]["coverage_summary"] == {
        "coverage_score": 0.0,
        "ready_for_code": False,
        "unresolved_concepts": [],
        "concept_coverage": [
            {
                "concept": "循环边界",
                "status": "partial",
                "asked_dimensions": [],
                "accepted_evidence_count": 0,
                "attempts": 0,
            },
            {
                "concept": "输出",
                "status": "covered",
                "asked_dimensions": ["application"],
                "accepted_evidence_count": 0,
                "attempts": 0,
            },
        ],
    }
    body = json.dumps(response.json["forum_state"], ensure_ascii=False)
    for forbidden in ("used_dimensions", "last_evidence_event_id", "learning_evidence", "private-event-1"):
        assert forbidden not in body


def test_start_session_defaults_old_stage3_sessions_without_coverage(stage3_restore_context):
    app, client, session_id, assignment_id = stage3_restore_context
    with app.app_context():
        db.session.add_all([
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="chat",
                role="student",
                content="旧老师提问",
                metadata_json=json.dumps({"panel": "teacher_agent"}, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="agent_message",
                role="teacher_agent",
                content="旧老师回答",
                metadata_json=json.dumps({
                    "request_id": "legacy-1",
                    "source_role": "teacher_agent",
                    "target_role": "user",
                    "message_kind": "agent_message",
                    "visibility": "public",
                }, ensure_ascii=False),
            ),
        ])
        db.session.commit()

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["resumed"] is True
    assert response.json["forum_state"] == {
        "target_role": "auto",
        "reply_to_event_id": None,
        "coverage_summary": {
            "coverage_score": 0.0,
            "ready_for_code": False,
            "unresolved_concepts": [],
            "concept_coverage": [],
        },
    }
    assert response.json["teacher_history"]
    assert isinstance(response.json["student_history"], list)


def test_start_session_restores_teacher_probe_intent_as_student_target(stage3_restore_context):
    app, client, session_id, assignment_id = stage3_restore_context
    with app.app_context():
        db.session.add(ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="state_snapshot",
            role="teacher_agent",
            content="",
            metadata_json=json.dumps({
                "state": {
                    "phase": "student_dialogue",
                    "student_probe_intent": {
                        "concept": "循环边界",
                        "dimension": "core",
                    },
                    "ready_for_code": False,
                }
            }, ensure_ascii=False),
        ))
        db.session.commit()

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["forum_state"] == {
        "target_role": "student_agent",
        "reply_to_event_id": None,
        "coverage_summary": {
            "coverage_score": 0.0,
            "ready_for_code": False,
            "unresolved_concepts": [],
            "concept_coverage": [],
            "student_probe_intent": {
                "concept": "循环边界",
                "dimension": "core",
            },
        },
    }


def test_start_session_returns_stable_empty_forum_restore_for_new_session(tmp_path, monkeypatch):
    database_path = tmp_path / "stage3_forum_restore_new.db"
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
        db.session.add_all([student, assignment, preset])
        db.session.commit()
        assignment_id = assignment.id
    client = app.test_client()
    client.post("/login", data={"username": "student-1", "password": "password"})

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["resumed"] is False
    assert response.json["forum_history"] == []
    assert response.json["teacher_history"] == []
    assert response.json["student_history"] == []
    assert response.json["buggy_code_info"] is None
    assert response.json["forum_state"] == {
        "target_role": "auto",
        "reply_to_event_id": None,
        "coverage_summary": {
            "coverage_score": 0.0,
            "ready_for_code": False,
            "unresolved_concepts": [],
            "concept_coverage": [],
        },
    }


def test_stage3_forum_frontend_restores_safe_user_selected_target_and_reply_context_after_refresh():
    assert "codesense-stage3-forum-compose:" in THINKING_JS
    assert "function forumComposerStorageKey()" in THINKING_JS
    assert "function loadPersistedForumComposerState()" in THINKING_JS
    assert "function persistForumComposerState()" in THINKING_JS
    assert "function clearPersistedForumComposerState()" in THINKING_JS
    assert "sessionStorage.getItem(forumComposerStorageKey())" in THINKING_JS
    assert "sessionStorage.setItem(forumComposerStorageKey()" in THINKING_JS
    assert "sessionStorage.removeItem(forumComposerStorageKey())" in THINKING_JS
    assert "const restoredSelection = chooseRestoredForumComposerState(source);" in THINKING_JS
    assert "const persistedEvent = findForumEventById(replyEventId);" in THINKING_JS
    assert "if (!isPersistedForumEvent(persistedEvent))" in THINKING_JS
    assert "if (serverReplyEventId) {" in THINKING_JS
    assert "if (state.forumReplyContext) {" in THINKING_JS
