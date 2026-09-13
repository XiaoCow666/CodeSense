import json
from types import SimpleNamespace

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentThinkingPreset, User, ThinkingSession, db
from routes import api as api_routes
from routes import thinking as thinking_routes


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
