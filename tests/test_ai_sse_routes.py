import json
from types import SimpleNamespace

import pytest
from flask import session

from app import create_app
from config import TestingConfig as _TestingConfig
from models import AIChatTurn, Assignment, AssignmentThinkingPreset, User, ThinkingSession, db
from routes import api as api_routes
from routes import thinking as thinking_routes
from services import demo_database
from services.learning_capture import captured_ai_sse_response, start_ai_turn


@pytest.fixture
def ai_sse_context(tmp_path, monkeypatch):
    database_path = tmp_path / "ai_sse_routes.db"
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(student_id="sse-student", username="sse-student", usertype="学生")
        student.password = "password"
        assignment = Assignment(
            title="SSE循环题",
            description="请解释循环边界并完成程序。",
            creator_id="sse-student",
        )
        preset = AssignmentThinkingPreset(
            assignment=assignment,
            reference_code="int main() { return 0; }",
            key_steps=json.dumps(["输入", "循环", "输出"], ensure_ascii=False),
            quiz_steps="[]",
            status="ready",
        )
        session = ThinkingSession(
            student=student,
            assignment=assignment,
            current_stage=1,
        )
        db.session.add_all([student, assignment, preset, session])
        db.session.commit()
        session_id = session.id
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post("/login", data={"username": "sse-student", "password": "password"})
    assert login.status_code in {302, 303}
    yield app, client, session_id, assignment_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def _post_without_iterating(app, client, path, payload):
    with client.session_transaction() as client_session:
        login_session = dict(client_session)
    with app.test_request_context(
        path, method="POST", json=payload, environ_base=client.environ_base,
        headers={"Accept": "text/event-stream"},
    ):
        session.update(login_session)
        # The test client's unbuffered WSGI helper reads the first SSE frame.
        return app.full_dispatch_request()


@pytest.mark.parametrize("channel", ["guidance", "companion", "feynman"])
def test_ai_stream_close_before_iteration_reuses_the_turn(ai_sse_context, monkeypatch, channel):
    app, client, session_id, assignment_id = ai_sse_context
    request_id = f"unstarted-{channel}"
    reply = "先检查循环边界。"
    calls = []

    def model_stream(*args, **kwargs):
        calls.append(channel)
        return iter([reply])

    payload = {"request_id": request_id}
    if channel == "guidance":
        path = "/api/get_programming_guidance"
        payload.update(assignment_id=assignment_id, code="int main(){return 0;}")
        monkeypatch.setattr(api_routes, "generate_guidance_stream", model_stream)
    elif channel == "companion":
        path = "/thinking/api/companion/chat"
        payload.update(session_id=session_id, messages=[{"role": "user", "content": "怎样开始？"}])
        monkeypatch.setattr(thinking_routes, "companion_agent_chat_stream", model_stream)
    else:
        path = "/thinking/api/stage3/forum/message"
        payload.update(session_id=session_id, message="为什么？", target_role="teacher_agent")
        with app.app_context():
            thinking_session = db.session.get(ThinkingSession, session_id)
            thinking_session.current_stage = 3
            thinking_session.stage2_completed = True
            db.session.commit()

        def forum_reply(*args, **kwargs):
            calls.append(channel)
            return {"success": True, "response": reply}

        monkeypatch.setattr(thinking_routes, "_run_stage3_forum_turn", forum_reply)

    first = _post_without_iterating(app, client, path, payload)
    assert first.status_code == 200
    assert first.mimetype == "text/event-stream"
    first.close()
    assert calls == []
    with app.app_context():
        turn = AIChatTurn.query.filter_by(request_id=request_id).one()
        turn_id = turn.id
        assert turn.status == "interrupted"
        assert turn.response is None
        assert json.loads(turn.context_json)["interrupted_before_stream_start"] is True

    if channel == "feynman":
        changed_target = client.post(path, json={**payload, "target_role": "student_agent"})
        assert changed_target.status_code == 409

    retry = _post_without_iterating(app, client, path, payload)
    assert retry.status_code == 200
    first.close()
    assert client.post(path, json=payload).status_code == 409
    with app.app_context():
        turn = AIChatTurn.query.filter_by(request_id=request_id).one()
        assert turn.id == turn_id
        assert turn.status == "generating"
        assert turn.answered_at is None

    assert _events(retry)[-1]["type"] == "done"
    retry.close()
    with app.app_context():
        turn = AIChatTurn.query.filter_by(request_id=request_id).one()
        assert turn.id == turn_id
        assert turn.status == "completed"
        assert reply in turn.response
        assert "interrupted_before_stream_start" not in json.loads(turn.context_json or "{}")
    assert calls == [channel]


@pytest.mark.parametrize("expired", [False, True])
def test_ai_stream_close_before_iteration_stays_in_demo_database(ai_sse_context, monkeypatch, expired):
    app, _, _, _ = ai_sse_context
    with app.app_context():
        formal, _ = start_ai_turn("sse-student", channel="code_assistant", question="formal")
        formal_id = formal.id
        db.session.commit()

    run = demo_database.create_demo_run("student")
    try:
        with app.test_request_context("/"):
            session[demo_database.DEMO_SESSION_KEY] = run.run_id
            assert demo_database.activate_demo_run(run.run_id)
            student = User(student_id=run.student_id, username=run.student_id, usertype="学生")
            student.password = "password"
            db.session.add(student)
            demo, _ = start_ai_turn(run.student_id, channel="code_assistant", question="demo")
            assert demo.id == formal_id
            db.session.commit()
            response = captured_ai_sse_response(demo.id, iter(()))

        if expired:
            monkeypatch.setattr(demo_database, "_is_expired", lambda *args: True)
        response.close()
        with app.app_context():
            assert db.session.get(AIChatTurn, formal_id).status == "generating"
            assert demo_database.activate_demo_run(run.run_id)
            assert db.session.get(AIChatTurn, formal_id).status == (
                "generating" if expired else "interrupted"
            )
    finally:
        demo_database.destroy_demo_run(run.run_id)


@pytest.fixture
def teacher_client(ai_sse_context):
    app, _, _, _ = ai_sse_context
    with app.app_context():
        teacher = User(
            student_id="sse-teacher",
            username="sse-teacher",
            usertype="教师",
        )
        teacher.password = "password"
        db.session.add(teacher)
        db.session.commit()
    client = app.test_client()
    login = client.post("/login", data={"username": "sse-teacher", "password": "password"})
    assert login.status_code in {302, 303}
    return client


def test_guidance_sse_streams_deltas_and_keeps_json_compatibility(ai_sse_context, monkeypatch):
    _, client, _, assignment_id = ai_sse_context
    monkeypatch.setattr(
        api_routes,
        "generate_guidance_stream",
        lambda **_: iter(["第一段", "第二段"]),
    )
    monkeypatch.setattr(api_routes, "generate_guidance", lambda **_: "完整指导")

    payload = {"code": "int main(){return 0;}", "assignment_id": assignment_id}
    streamed = client.post(
        "/api/get_programming_guidance",
        json=payload,
        headers={"Accept": "text/event-stream"},
    )
    assert streamed.status_code == 200
    assert streamed.mimetype == "text/event-stream"
    events = _events(streamed)
    assert [event["type"] for event in events] == ["start", "delta", "delta", "done"]
    assert events[-1]["guidance"]
    assert "第一段" in events[-1]["guidance"]

    legacy = client.post("/api/get_programming_guidance", json=payload)
    assert legacy.status_code == 200
    assert legacy.is_json
    assert legacy.json["data"]["guidance"] == "完整指导"


def test_assignment_generation_streams_model_tokens(monkeypatch, teacher_client):
    import openai
    from services.llm_client import SharedLLMClient

    # This test asserts provider chunk boundaries.  Keep the shared LLM cache
    # out of the scenario so a previous test run cannot replay the response in
    # its fixed-size cache chunks instead of exercising the fake provider.
    monkeypatch.setattr(SharedLLMClient, "_cache_get", lambda self, key: None)
    monkeypatch.setattr(SharedLLMClient, "_cache_set", lambda self, key, value: None)

    class FakeCompletions:
        def create(self, **kwargs):
            content = '{"title":"流式作业", "description":"流式描述"}'
            if kwargs.get("stream"):
                chunks = [
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content[:12]))]),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content[12:]))]),
                ]
                return iter(chunks)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "OpenAI", lambda **_: FakeClient())
    # The route now uses the shared resilient client.  Override process
    # credentials so its live configuration refresh selects the patched fake
    # OpenAI provider instead of the developer machine's real key.
    monkeypatch.setenv("ZHIPU_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    response = teacher_client.post(
        "/assignments/generate",
        json={"prompt": "循环和边界条件"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["start", "delta", "delta", "done"]
    assert events[-1]["title"] == "流式作业"
    assert events[-1]["description"] == "流式描述"


def test_code_advice_uses_shared_resilient_stream(ai_sse_context, monkeypatch):
    import services.llm_client as llm_module

    _, client, _, assignment_id = ai_sse_context

    class FakeSharedClient:
        def is_available(self):
            return True

        def chat_stream(self, messages, **kwargs):
            assert messages[-1]["role"] == "user"
            assert kwargs["max_tokens"] == 1000
            return iter(["先检查边界条件。", "再手动追踪一次。"])

    monkeypatch.setattr(llm_module, "SharedLLMClient", lambda: FakeSharedClient())
    response = client.post(
        "/api/code_advice",
        json={
            "code": "int main(){return 0;}",
            "assignment_id": assignment_id,
            "question": "循环边界为什么这样写？",
        },
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["start", "delta", "delta", "done"]
    assert events[-1]["answer"] == "先检查边界条件。再手动追踪一次。"


def test_stage1_structured_result_uses_same_sse_envelope(ai_sse_context, monkeypatch):
    _, client, session_id, _ = ai_sse_context
    monkeypatch.setattr(
        thinking_routes,
        "evaluate_description",
        lambda *_args, **_kwargs: (86, "思路清晰"),
    )

    response = client.post(
        "/thinking/api/stage1/submit",
        json={"session_id": session_id, "description": "先读取数据，再循环处理，最后输出结果。"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    events = _events(response)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["score"] == 86
    assert events[-1]["passed"] is True


def test_stage1_hint_stream_persists_final_hint(ai_sse_context, monkeypatch):
    _, client, session_id, _ = ai_sse_context
    monkeypatch.setattr(
        thinking_routes,
        "generate_stage1_hint_stream",
        lambda *_args, **_kwargs: iter(["先想输入", "再想循环"]),
    )

    response = client.post(
        "/thinking/api/stage1/hint",
        json={"session_id": session_id, "description": "我不知道下一步"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    events = _events(response)
    assert events[-1]["hint"] == "先想输入再想循环"
    with client.application.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.stage1_hint_count == 1


def test_ability_analysis_uses_common_sse_protocol(ai_sse_context, monkeypatch):
    _, client, _, _ = ai_sse_context
    from tasks import ability_analysis

    # Avoid starting a background job; the route contract is what is under test.
    monkeypatch.setattr(ability_analysis, 'trigger_analysis_if_needed', lambda *args, **kwargs: True)

    response = client.get('/api/stream/ability-analysis')
    assert response.status_code == 200
    events = _events(response)

    assert events[0]['type'] == 'status'
    assert events[0]['phase'] == 'progress'
    assert events[-1] == {'type': 'done', 'done': True}
    assert 'start' in [event['type'] for event in events]
    assert 'delta' in [event['type'] for event in events]
    assert not any(event['type'] in {'analysis_start', 'analysis_chunk', 'complete'} for event in events)
