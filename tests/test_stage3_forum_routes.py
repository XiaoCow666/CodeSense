import json
from types import SimpleNamespace

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import (
    AIChatTurn,
    Assignment,
    AssignmentThinkingPreset,
    LearningAttempt,
    ThinkingSession,
    ThinkingStageLog,
    User,
    db,
)
from routes import thinking as thinking_routes
from utils.agents.contracts import AgentDecision, AgentResult, AgentRole
from utils.agents.feynman import FeynmanCallbacks, build_feynman_runtime
from utils.agents.orchestrator import ForumTurnResult


@pytest.fixture
def stage3_forum_context(tmp_path, monkeypatch):
    database_path = tmp_path / "stage3_forum_routes.db"
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


def _stub_runtime_factory():
    def factory(session, assignment, preset):
        return SimpleNamespace(session=SimpleNamespace(id=session.id))

    return factory


def _assert_stage3_validation_contract(client, path, payload, *, start_message, status, error_body):
    response = client.post(path, json=payload)
    assert response.status_code == status
    assert response.get_json() == error_body

    streamed = client.post(path, json=payload, headers={"Accept": "text/event-stream"})
    assert streamed.status_code == 200
    assert streamed.mimetype == "text/event-stream"
    events = [
        json.loads(line[6:]) for line in streamed.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    assert events == [
        {"type": "start", "message": start_message},
        {"type": "error", "error": "STAGE3_REQUEST_FAILED", "message": "阶段3处理失败，请稍后重试"},
    ]
    with client.application.app_context():
        assert AIChatTurn.query.first() is None
        assert LearningAttempt.query.first() is None


def test_stage3_forum_message_requires_authenticated_user(stage3_forum_context):
    app, _, session_id, _ = stage3_forum_context

    response = app.test_client().post(
        "/thinking/api/stage3/forum/message",
        json={
            "session_id": session_id,
            "message": "请解释循环边界。",
            "target_role": "teacher_agent",
        },
    )

    assert response.status_code in {302, 401}


@pytest.mark.parametrize(
    ("endpoint", "start_message"),
    [
        ("chat", "老师Agent正在整理回复..."),
        ("teach", "小明Agent正在思考追问..."),
        ("forum/message", "论坛Agent正在协同分析..."),
        ("write_code", "小明Agent正在准备一份待检查代码..."),
        ("fix_code", "老师Agent正在验证你的修复..."),
    ],
)
def test_stage3_invalid_session_preserves_sse_error_envelope(stage3_forum_context, endpoint, start_message):
    _, client, session_id, _ = stage3_forum_context
    _assert_stage3_validation_contract(
        client, f"/thinking/api/stage3/{endpoint}",
        {"session_id": session_id + 1, "message": "请解释循环边界。"},
        start_message=start_message,
        status=403,
        error_body={"error": "会话不存在", "error_code": "SESSION_NOT_FOUND"},
    )


def test_stage3_missing_message_preserves_sse_error_envelope(stage3_forum_context):
    _, client, session_id, _ = stage3_forum_context
    _assert_stage3_validation_contract(
        client, "/thinking/api/stage3/chat", {"session_id": session_id},
        start_message="老师Agent正在整理回复...",
        status=400,
        error_body={"error": "缺少消息"},
    )


@pytest.mark.parametrize(
    ("payload", "error_code", "error_message"),
    [
        ({"message": "请解释循环边界。"}, "TARGET_ROLE_REQUIRED", "缺少目标对象"),
        ({"message": "请解释循环边界。", "target_role": "grader_agent"}, "TARGET_ROLE_INVALID", "目标对象无效"),
    ],
)
def test_stage3_forum_message_validates_target_role(
    stage3_forum_context, monkeypatch, payload, error_code, error_message,
):
    _, client, session_id, _ = stage3_forum_context
    monkeypatch.setattr(thinking_routes, "build_feynman_runtime", _stub_runtime_factory())

    _assert_stage3_validation_contract(
        client, "/thinking/api/stage3/forum/message",
        {"session_id": session_id, "request_id": "forum-target-1", **payload},
        start_message="论坛Agent正在协同分析...",
        status=400,
        error_body={"error": error_message, "error_code": error_code},
    )


def test_stage3_forum_message_rejects_cross_session_reply_event(stage3_forum_context, monkeypatch):
    app, client, session_id, assignment_id = stage3_forum_context
    with app.app_context():
        other_session = ThinkingSession(
            student_id="student-1",
            assignment_id=assignment_id,
            current_stage=3,
            stage2_completed=True,
        )
        db.session.add(other_session)
        db.session.commit()
        db.session.add(ThinkingStageLog(
            session_id=other_session.id,
            stage=3,
            event_type="agent_message",
            role="teacher_agent",
            content="另一个会话里的消息",
            metadata_json=json.dumps({
                "request_id": "other-forum-1",
                "source_role": "teacher_agent",
                "target_role": "user",
                "message_kind": "agent_message",
                "visibility": "public",
            }, ensure_ascii=False),
        ))
        db.session.commit()
        reply_to_event_id = str(
            ThinkingStageLog.query.filter_by(session_id=other_session.id, event_type="agent_message").first().id
        )

    monkeypatch.setattr(thinking_routes, "build_feynman_runtime", _stub_runtime_factory())
    monkeypatch.setattr(
        thinking_routes,
        "Stage3Orchestrator",
        lambda runtime: pytest.fail("orchestrator must not run for a cross-session reply target"),
    )

    _assert_stage3_validation_contract(
        client, "/thinking/api/stage3/forum/message",
        {
            "session_id": session_id,
            "message": "回复当前会话外的消息。",
            "target_role": "teacher_agent",
            "reply_to_event_id": reply_to_event_id,
            "request_id": "forum-reply-miss-1",
        },
        start_message="论坛Agent正在协同分析...",
        status=400,
        error_body={"error": "回复目标不存在", "error_code": "REPLY_EVENT_NOT_FOUND"},
    )


@pytest.mark.parametrize("stored_status", ["generating", "completed", "failed", "interrupted"])
def test_stage3_forum_replay_binds_request_to_role_and_reply(stage3_forum_context, monkeypatch, stored_status):
    app, client, session_id, _ = stage3_forum_context
    with app.app_context():
        targets = [
            ThinkingStageLog(
                session_id=session_id, stage=3, event_type="agent_message", role="teacher_agent",
                content=f"先前的论坛回复 {number}",
                metadata_json=json.dumps({
                    "request_id": f"parent-{number}",
                    "source_role": "teacher_agent",
                    "target_role": "user",
                    "message_kind": "agent_message",
                    "visibility": "public",
                }),
            ) for number in (1, 2)
        ]
        db.session.add_all(targets)
        db.session.commit()
        first_target, other_target = [str(event.id) for event in targets]

    calls = []

    def decide(**kwargs):
        calls.append(kwargs)
        return AgentDecision(message="判断循环边界时，试着手算最后一次迭代。")

    def runtime_factory(session, assignment, preset):
        return build_feynman_runtime(session, assignment, preset, model=SimpleNamespace(decide=decide))

    monkeypatch.setattr(thinking_routes, "build_feynman_runtime", runtime_factory)
    path = "/thinking/api/stage3/forum/message"
    payload = {
        "session_id": session_id,
        "message": "如何判断循环边界？",
        "target_role": "teacher_agent",
        "reply_to_event_id": first_target,
        "request_id": "forum-routing-replay",
    }
    first = client.post(path, json=payload)
    assert first.status_code == 200
    assert first.json["primary"]["success"] is True
    assert len(calls) == 1
    with app.app_context():
        turn = AIChatTurn.query.one()
        assert turn.status == "completed"
        turn_id = turn.id
        log_ids = {item.id for item in ThinkingStageLog.query.filter_by(session_id=session_id)}
        turn.status = stored_status
        db.session.commit()

    for changed in ({"target_role": "student_agent"}, {"reply_to_event_id": other_target}):
        response = client.post(path, json={**payload, **changed})
        assert response.status_code == 409
        assert response.json["error_code"] == "LEARNING_ATTEMPT_CONFLICT"

    if stored_status == "completed":
        retry = client.post(path, json={**payload, "reply_to_event_id": int(first_target)})
        assert retry.status_code == 200
        assert retry.json["primary"] == first.json["primary"]

    with app.app_context():
        turn = AIChatTurn.query.one()
        assert turn.id == turn_id
        assert turn.status == stored_status
        assert {item.id for item in ThinkingStageLog.query.filter_by(session_id=session_id)} == log_ids
    assert len(calls) == 1


def test_forum_student_reply_is_not_blocked_by_legacy_fuzzy_repetition_guard(stage3_forum_context):
    app, _, session_id, _ = stage3_forum_context
    with app.app_context():
        db.session.add_all([
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="agent_user_message",
                role="student",
                content="我已经说明了 N=0 和 N=1 的边界条件。",
                metadata_json=json.dumps({"request_id": "student-old-1"}),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="agent_message",
                role="student_agent",
                content="那再说说循环。",
                metadata_json=json.dumps({"request_id": "student-old-1"}),
            ),
        ])
        db.session.commit()

        guarded = thinking_routes._stage3_student_message_guard(
            session_id,
            "我已经说明了 N=0 和 N=1 的边界条件。",
            "student-new-1",
            reply_to_event_id="student-probe-1",
        )

    assert guarded is None


def test_stage3_forum_message_forwards_routing_metadata_and_filters_private_fields(stage3_forum_context, monkeypatch):
    app, client, session_id, _ = stage3_forum_context
    with app.app_context():
        db.session.add(ThinkingStageLog(
            session_id=session_id,
            stage=3,
            event_type="agent_message",
            role="teacher_agent",
            content="现有公开消息",
            metadata_json=json.dumps({
                "request_id": "existing-1",
                "source_role": "teacher_agent",
                "target_role": "user",
                "message_kind": "agent_message",
                "visibility": "public",
            }, ensure_ascii=False),
        ))
        db.session.commit()
        reply_to_event_id = str(
            ThinkingStageLog.query.filter_by(session_id=session_id, event_type="agent_message").first().id
        )

    recorded = {}

    class FakeOrchestrator:
        def __init__(self, runtime):
            recorded["session_id"] = runtime.session.id

        def handle_user_message(self, message, *, target_role, request_id, reply_to_event_id=None):
            recorded["message"] = message
            recorded["target_role"] = target_role
            recorded["request_id"] = request_id
            recorded["reply_to_event_id"] = reply_to_event_id
            primary = AgentResult(
                success=True,
                agent=AgentRole.TEACHER_AGENT,
                response="老师回答",
                public_content={
                    "message": "公开主回复",
                    "tool_call": {"id": "secret-call", "arguments": {"hidden": True}},
                    "trigger": {"concept": "循环边界"},
                    "artifact": {"hidden_bug": "secret"},
                    "decision": {"next": "private"},
                },
                internal_signals={"student_probe": {"concept": "循环边界"}},
            )
            intervention = AgentResult(
                success=True,
                agent=AgentRole.STUDENT_AGENT,
                response="再解释一下为什么最后一个索引不是 n。",
                public_content={"tool_arguments": {"hidden": True}},
            )
            return ForumTurnResult(primary=primary, interventions=[intervention])

    monkeypatch.setattr(thinking_routes, "build_feynman_runtime", _stub_runtime_factory())
    monkeypatch.setattr(thinking_routes, "Stage3Orchestrator", FakeOrchestrator)

    response = client.post(
        "/thinking/api/stage3/forum/message",
        json={
            "session_id": session_id,
            "message": "为什么这里会越界？",
            "target_role": "teacher_agent",
            "reply_to_event_id": reply_to_event_id,
            "request_id": "forum-route-1",
        },
    )

    assert response.status_code == 200
    assert recorded == {
        "session_id": session_id,
        "message": "为什么这里会越界？",
        "target_role": AgentRole.TEACHER_AGENT,
        "request_id": "forum-route-1",
        "reply_to_event_id": reply_to_event_id,
    }
    assert response.json["primary"]["response"] == "老师回答"
    assert response.json["primary"]["message"] == "公开主回复"
    assert response.json["user_goal"]["id"] == "stage3-teach-and-repair"
    assert response.json["user_goal"]["progress_percent"] == 0
    assert response.json["session_lifecycle"]["id"] == session_id
    assert response.json["session_lifecycle"]["status"] == "active"
    assert response.json["forum_state"]["coverage_summary"]["ready_for_code"] is False
    assert response.json["interventions"] == []
    dumped = json.dumps(response.json, ensure_ascii=False)
    assert "internal_signals" not in dumped
    assert "tool_call" not in dumped
    assert "tool_arguments" not in dumped
    assert "trigger" not in dumped
    assert "artifact" not in dumped
    assert "decision" not in dumped


def test_legacy_stage3_routes_default_targets_and_keep_flat_shape(stage3_forum_context, monkeypatch):
    _, client, session_id, _ = stage3_forum_context
    calls = []

    class FakeRuntime:
        def __init__(self, session_id):
            self.session = SimpleNamespace(id=session_id)

        def handle_chat(self, role, message, *, request_id, event_metadata=None):
            calls.append((message, role, request_id, dict(event_metadata or {}), self.session.id))
            return AgentResult(
                success=True,
                agent=role,
                response=f"{role.value}: {message}",
            )

    monkeypatch.setattr(
        thinking_routes,
        "build_feynman_runtime",
        lambda session, assignment, preset: FakeRuntime(session.id),
    )

    teacher_response = client.post(
        "/thinking/api/stage3/chat",
        json={"session_id": session_id, "message": "老师端当前消息", "request_id": "legacy-chat-1"},
    )
    student_response = client.post(
        "/thinking/api/stage3/teach",
        json={"session_id": session_id, "message": "学生端解释循环边界。", "request_id": "legacy-teach-1"},
    )

    assert teacher_response.status_code == 200
    assert student_response.status_code == 200
    assert teacher_response.json == {
        "success": True,
        "response": "teacher_agent: 老师端当前消息",
        "agent": "teacher_agent",
        "ui_action": "continue_chat",
        "ready_for_code": False,
        "state": {},
    }
    assert student_response.json == {
        "success": True,
        "response": "student_agent: 学生端解释循环边界。",
        "agent": "student_agent",
        "ui_action": "continue_chat",
        "ready_for_code": False,
        "state": {},
    }
    assert calls == [
        (
            "老师端当前消息",
            AgentRole.TEACHER_AGENT,
            "legacy-chat-1",
            {
                "source_role": "user",
                "target_role": "teacher_agent",
                "message_kind": "user_message",
                "visibility": "public",
            },
            session_id,
        ),
        (
            "学生端解释循环边界。",
            AgentRole.STUDENT_AGENT,
            "legacy-teach-1",
            {
                "source_role": "user",
                "target_role": "student_agent",
                "message_kind": "user_message",
                "visibility": "public",
            },
            session_id,
        ),
    ]


def test_legacy_stage3_chat_does_not_trigger_student_intervention(stage3_forum_context, monkeypatch):
    _, client, session_id, _ = stage3_forum_context

    class FakeRuntime:
        def __init__(self):
            self.session = SimpleNamespace(id=session_id)
            self.chat_calls = []
            self.trigger_calls = []

        def handle_chat(self, role, message, *, request_id, event_metadata=None):
            self.chat_calls.append((role, message, request_id, dict(event_metadata or {})))
            return AgentResult(
                success=True,
                agent=AgentRole.TEACHER_AGENT,
                response="老师回答",
                internal_signals={
                    "student_probe": {
                        "concept": "循环边界",
                        "dimension": "edge_case",
                        "goal": "检查边界解释",
                    }
                },
            )

        def handle_trigger(self, trigger, *, request_id, event_metadata=None):
            self.trigger_calls.append((trigger, request_id, dict(event_metadata or {})))
            raise AssertionError("legacy chat must not create a Student intervention")

    fake_runtime = FakeRuntime()
    monkeypatch.setattr(
        thinking_routes,
        "build_feynman_runtime",
        lambda *args, **kwargs: fake_runtime,
    )
    monkeypatch.setattr(
        thinking_routes,
        "Stage3Orchestrator",
        lambda *args, **kwargs: pytest.fail("legacy chat must not invoke Stage3Orchestrator"),
    )

    response = client.post(
        "/thinking/api/stage3/chat",
        json={
            "session_id": session_id,
            "message": "请解释循环边界。",
            "request_id": "legacy-probe-1",
        },
    )

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "response": "老师回答",
        "agent": "teacher_agent",
        "ui_action": "continue_chat",
        "ready_for_code": False,
        "state": {},
    }
    assert response.json["agent"] == AgentRole.TEACHER_AGENT.value
    assert "interventions" not in response.json
    assert fake_runtime.chat_calls == [(
        AgentRole.TEACHER_AGENT,
        "请解释循环边界。",
        "legacy-probe-1",
        {
            "source_role": "user",
            "target_role": "teacher_agent",
            "message_kind": "user_message",
            "visibility": "public",
        },
    )]
    assert fake_runtime.trigger_calls == []


def test_start_session_returns_sanitized_forum_history_and_recovery_fields(stage3_forum_context):
    app, client, session_id, assignment_id = stage3_forum_context
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
                event_type="agent_user_message",
                role="student",
                content="论坛提问",
                metadata_json=json.dumps({
                    "request_id": "forum-1",
                    "source_role": "user",
                    "target_role": "teacher_agent",
                    "message_kind": "user_message",
                    "visibility": "public",
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
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
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="tool_result",
                role="teacher_agent",
                content="不会出现在论坛里",
                metadata_json=json.dumps({
                    "request_id": "forum-1",
                    "public_content": {"message": "公开提示"},
                    "artifact": {"standard_answer": "secret", "public_hint": "检查边界"},
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="tool_result",
                role="student_agent",
                content="代码说明",
                metadata_json=json.dumps({
                    "request_id": "code-1",
                    "public_content": {"buggy_code": "buggy", "message": "代码说明"},
                }, ensure_ascii=False),
            ),
            ThinkingStageLog(
                session_id=session_id,
                stage=3,
                event_type="fix_code",
                role="student",
                content="修复代码",
                metadata_json="{}",
            ),
        ])
        db.session.commit()

    response = client.post("/thinking/api/start_session", json={"assignment_id": assignment_id})

    assert response.status_code == 200
    assert response.json["resumed"] is True
    assert [item["content"] for item in response.json["forum_history"]] == [
        "旧老师提问",
        "论坛提问",
        "论坛回答",
    ]
    assert {item["content"] for item in response.json["teacher_history"]} >= {"旧老师提问", "论坛提问", "论坛回答"}
    assert {item["content"] for item in response.json["student_history"]} >= {"代码说明", "【提交代码修复】\n修复代码"}
    assert response.json["buggy_code_info"] == {"buggy_code": "buggy", "message": "代码说明"}
    assert "standard_answer" not in json.dumps(response.json["forum_history"], ensure_ascii=False)
    assert "secret" not in json.dumps(response.json["forum_history"], ensure_ascii=False)


def test_write_code_still_enforces_coverage_gate(stage3_forum_context, monkeypatch):
    _, client, session_id, _ = stage3_forum_context
    calls = []

    def runtime_factory(session, assignment, preset):
        callbacks = FeynmanCallbacks(
            buggy_code_generator=lambda context: calls.append(context) or {
                "buggy_code": "int main() { return 1; }",
                "bugs": [{"description": "隐藏 Bug", "fix": "return 0;"}],
                "message": "不应在未就绪时调用。",
            },
        )
        return build_feynman_runtime(session, assignment, preset, callbacks=callbacks)

    monkeypatch.setattr(thinking_routes, "build_feynman_runtime", runtime_factory)

    response = client.post(
        "/thinking/api/stage3/write_code",
        json={"session_id": session_id, "request_id": "write-gate-1"},
    )

    assert response.status_code == 200
    assert response.json["success"] is False
    assert response.json["error_code"] == "CODE_REVIEW_NOT_READY"
    assert response.json["ready_for_code"] is False
    assert calls == []


def test_stage3_forum_message_checks_session_ownership_before_runtime(stage3_forum_context, monkeypatch):
    app, _, session_id, _ = stage3_forum_context
    with app.app_context():
        other = User(student_id="student-2", username="student-2", usertype="学生")
        other.password = "password"
        db.session.add(other)
        db.session.commit()

    other_client = app.test_client()
    other_client.post("/login", data={"username": "student-2", "password": "password"})
    monkeypatch.setattr(
        thinking_routes,
        "build_feynman_runtime",
        lambda *args, **kwargs: pytest.fail("runtime must not be constructed for a non-owner"),
    )

    response = other_client.post(
        "/thinking/api/stage3/forum/message",
        json={
            "session_id": session_id,
            "message": "无权访问",
            "target_role": "teacher_agent",
            "request_id": "owner-forum-1",
        },
    )

    assert response.status_code == 403
