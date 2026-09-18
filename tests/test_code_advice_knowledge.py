import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentKnowledgePoint, Submission, User, db
from routes import api as api_routes
from services.student_vector_store import rebuild_student_vector_index


@pytest.fixture
def code_advice_knowledge_context(tmp_path, monkeypatch):
    database_path = tmp_path / "code-advice-knowledge.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="code-advice-knowledge-student",
            username="code-advice-knowledge-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="代码建议知识作业",
            description="请关注数组边界和循环条件。",
            creator_id=student.student_id,
        )
        db.session.add_all([student, assignment])
        db.session.commit()
        AssignmentKnowledgePoint.add_to_assignment(assignment.id, "array")
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post(
        "/login",
        data={
            "username": "code-advice-knowledge-student",
            "password": "password",
        },
    )
    assert login.status_code in {302, 303}
    yield app, client, assignment_id

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def _grounded_retrieval(*args, **kwargs):
    return {
        "status": "grounded",
        "evidence": [
            {
                "evidence_id": "assignment-kp:1",
                "citation": "[K1]",
                "source_type": "assignment_knowledge_point",
                "title": "数组边界",
                "content": "当前作业显式绑定知识点：数组边界。",
                "created_at": "2026-09-16T08:00:00",
            }
        ],
        "metrics": {
            "candidate_count": 1,
            "hit_count": 1,
            "indexed_chunk_count": 1,
            "retrieval_latency_ms": 2.5,
            "retrieval_mode": "vector",
            "citation_completeness": 1.0,
        },
        "fallback": None,
    }


class _FakeSharedClient:
    captured_messages = None

    def is_available(self):
        return True

    def chat_stream(self, messages, **kwargs):
        type(self).captured_messages = messages
        return iter(["先检查边界条件。", "再手动追踪一次。"])


def test_chat_advice_is_grounded_and_emits_evidence_only_on_done(
    code_advice_knowledge_context, monkeypatch
):
    _, client, assignment_id = code_advice_knowledge_context
    captured = {}

    def fake_retrieval(assignment_id, *, query="", limit=8):
        captured.update(assignment_id=assignment_id, query=query, limit=limit)
        return _grounded_retrieval()

    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", fake_retrieval)
    monkeypatch.setattr(
        "services.llm_client.SharedLLMClient",
        lambda: _FakeSharedClient(),
    )

    response = client.post(
        "/api/code_advice",
        json={
            "code": "int main(){return 0;}",
            "assignment_id": assignment_id,
            "question": "数组边界为什么重要？",
        },
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == ["start", "delta", "delta", "done"]
    assert captured == {
        "assignment_id": assignment_id,
        "query": "数组边界为什么重要？",
        "limit": 8,
    }
    assert all("knowledge_evidence" not in event for event in events if event["type"] == "delta")
    done = events[-1]
    assert done["knowledge_retrieval"]["status"] == "grounded"
    assert done["knowledge_evidence"]["evidence"][0]["citation"] == "[K1]"
    assert done["data"]["knowledge_evidence"]["status"] == "grounded"
    prompt = _FakeSharedClient.captured_messages[-1]["content"]
    assert "[K1]" in prompt
    assert "只能使用这些证据" in prompt


def test_chat_advice_includes_current_student_learning_memory(
    code_advice_knowledge_context, monkeypatch
):
    app, client, assignment_id = code_advice_knowledge_context
    with app.app_context():
        db.session.add(
            Submission(
                student_id="code-advice-knowledge-student",
                assignment_id=assignment_id,
                code="int main(){return 0;}",
                score=72,
                status="evaluated",
                feedback="上次提交仍然需要检查数组边界。",
            )
        )
        db.session.commit()
        rebuild_student_vector_index("code-advice-knowledge-student")

    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", _grounded_retrieval)
    monkeypatch.setattr(
        "services.llm_client.SharedLLMClient",
        lambda: _FakeSharedClient(),
    )

    response = client.post(
        "/api/code_advice",
        json={
            "code": "int main(){return 0;}",
            "assignment_id": assignment_id,
            "question": "上次提交的数组边界问题怎么继续检查？",
        },
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    done = _events(response)[-1]
    evidence = done["student_learning_evidence"]
    assert evidence["status"] == "grounded"
    assert evidence["evidence"][0]["scope"] == "student_private"
    assert evidence["evidence"][0]["source_version"]
    assert "上次提交仍然需要检查数组边界" in _FakeSharedClient.captured_messages[-1]["content"]
    assert "参考我的学习记录" in done["answer"]


def test_code_advice_without_assignment_does_not_create_cross_assignment_retrieval(
    code_advice_knowledge_context, monkeypatch
):
    _, client, _ = code_advice_knowledge_context
    monkeypatch.setattr(
        api_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: pytest.fail("retrieval must be assignment-scoped"),
    )
    monkeypatch.setattr(
        "services.llm_client.SharedLLMClient",
        lambda: _FakeSharedClient(),
    )

    response = client.post(
        "/api/code_advice",
        json={"code": "int main(){return 0;}", "question": "怎么检查？"},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    done = _events(response)[-1]
    assert done["type"] == "done"
    assert "knowledge_retrieval" not in done
    assert "knowledge_evidence" not in done


def test_analysis_sse_and_json_expose_the_same_additive_evidence_contract(
    code_advice_knowledge_context, monkeypatch
):
    _, client, assignment_id = code_advice_knowledge_context
    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", _grounded_retrieval)
    monkeypatch.setattr(
        api_routes,
        "generate_code_advice",
        lambda **kwargs: {
            "overall_feedback": "可以继续手动追踪。",
            "algorithm_score": 80,
            "style_score": 82,
            "functionality_score": 78,
            "efficiency_score": 76,
            "suggestions": ["检查边界"],
        },
    )
    payload = {"code": "int main(){return 0;}", "assignment_id": assignment_id}

    streamed = client.post(
        "/api/code_advice",
        json=payload,
        headers={"Accept": "text/event-stream"},
    )
    legacy = client.post("/api/code_advice", json=payload)

    assert streamed.status_code == 200
    assert legacy.status_code == 200
    stream_done = _events(streamed)[-1]
    legacy_data = legacy.json["data"]
    assert stream_done["knowledge_evidence"]["status"] == "grounded"
    assert stream_done["data"]["knowledge_retrieval"]["status"] == "grounded"
    assert legacy_data["knowledge_evidence"]["status"] == "grounded"
    assert legacy_data["knowledge_retrieval"]["evidence"][0]["citation"] == "[K1]"
    assert legacy_data["advice"]


def test_unavailable_knowledge_keeps_code_advice_answer_available(
    code_advice_knowledge_context, monkeypatch
):
    _, client, assignment_id = code_advice_knowledge_context

    def broken_retrieval(*args, **kwargs):
        raise RuntimeError("do not surface this")

    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", broken_retrieval)
    monkeypatch.setattr(
        "services.llm_client.SharedLLMClient",
        lambda: _FakeSharedClient(),
    )

    response = client.post(
        "/api/code_advice",
        json={
            "code": "int main(){return 0;}",
            "assignment_id": assignment_id,
            "question": "为什么？",
        },
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    done = _events(response)[-1]
    assert done["type"] == "done"
    assert done["knowledge_evidence"]["status"] == "unavailable"
    assert "先检查边界条件" in done["answer"]
