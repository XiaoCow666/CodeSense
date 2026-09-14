import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentKnowledgePoint, KnowledgePointScore, User, db
from routes import api as api_routes
from services import knowledge_rag
from services.knowledge_rag import retrieve_assignment_knowledge


@pytest.fixture
def knowledge_context(tmp_path, monkeypatch):
    database_path = tmp_path / "knowledge_rag.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="rag-student",
            username="rag-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="数组边界题",
            description="请处理数组输入并说明边界条件。",
            creator_id="rag-student",
        )
        db.session.add_all([student, assignment])
        db.session.commit()
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": "rag-student", "password": "password"},
    )
    assert login.status_code in {302, 303}
    yield app, client, assignment_id

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_ask_question_exposes_retrieval_evidence_and_fallback_state(
    knowledge_context, monkeypatch
):
    _, client, assignment_id = knowledge_context
    monkeypatch.setattr(
        api_routes,
        "generate_answer_to_question",
        lambda **_: "请检查数组下标与边界条件。",
    )

    response = client.post(
        "/api/ask_question",
        json={
            "assignment_id": assignment_id,
            "code": "int main(){return 0;}",
            "question": "数组边界怎么检查？",
        },
    )

    assert response.status_code == 200
    data = response.json["data"]
    assert data["knowledge_retrieval"]["status"] == "no_result"
    assert data["knowledge_retrieval"]["fallback"]["code"] == "NO_KNOWLEDGE_EVIDENCE"
    assert data["knowledge_retrieval"]["metrics"]["no_result_fallback"] is True
    assert "没有已标注知识点" in data["answer"]


def test_ask_question_returns_scoped_citations_and_metrics(knowledge_context, monkeypatch):
    app, client, assignment_id = knowledge_context
    with app.app_context():
        AssignmentKnowledgePoint.add_to_assignment(
            assignment_id,
            "array",
            weight=1.5,
            auto_detected=True,
        )

    captured = {}

    def fake_answer(**kwargs):
        captured.update(kwargs)
        return "先检查数组下标是否始终落在有效范围内。"

    monkeypatch.setattr(api_routes, "generate_answer_to_question", fake_answer)
    response = client.post(
        "/api/ask_question",
        json={
            "assignment_id": assignment_id,
            "code": "int main(){return 0;}",
            "question": "数组边界怎么检查？",
        },
    )

    assert response.status_code == 200
    data = response.json["data"]
    retrieval = data["knowledge_retrieval"]
    assert retrieval["status"] == "grounded"
    assert retrieval["metrics"]["candidate_count"] == 1
    assert retrieval["metrics"]["hit_count"] == 1
    assert retrieval["metrics"]["retrieval_hit_rate"] == 1.0
    assert retrieval["metrics"]["citation_completeness"] == 1.0
    assert retrieval["metrics"]["no_result_fallback"] is False
    assert retrieval["evidence"][0]["citation"] == "[K1]"
    assert "数组" in captured["knowledge_context"]
    assert "[K1]" in data["answer"]
    assert "参考知识证据" in data["answer"]


def test_ask_question_sse_includes_retrieval_receipt(knowledge_context, monkeypatch):
    _, client, assignment_id = knowledge_context
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return iter(["先手动追踪边界值。"])

    monkeypatch.setattr(api_routes, "generate_answer_to_question_stream", fake_stream)
    response = client.post(
        "/api/ask_question",
        json={
            "assignment_id": assignment_id,
            "code": "int main(){return 0;}",
            "question": "边界值怎么检查？",
        },
        headers={"Accept": "text/event-stream"},
    )

    events = [
        json.loads(line[6:])
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["start", "delta", "done"]
    done = events[-1]
    assert done["knowledge_retrieval"]["status"] == "no_result"
    assert done["knowledge_retrieval"]["metrics"]["no_result_fallback"] is True
    assert done["data"]["knowledge_retrieval"]["fallback"]["code"] == (
        "NO_KNOWLEDGE_EVIDENCE"
    )
    assert "没有已标注知识点" in done["answer"]
    assert "不要编造知识库引用" in captured["knowledge_context"]


def test_retriever_does_not_read_student_private_scores(knowledge_context):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        db.session.add(
            KnowledgePointScore(
                student_id="rag-student",
                knowledge_point="array",
                score=99.0,
            )
        )
        db.session.commit()
        retrieval = retrieve_assignment_knowledge(assignment_id)

    assert retrieval["status"] == "no_result"
    assert retrieval["metrics"]["candidate_count"] == 0
    assert retrieval["metrics"]["hit_count"] == 0


def test_retriever_returns_safe_fallback_when_knowledge_source_is_unavailable(
    knowledge_context, monkeypatch
):
    app, _, assignment_id = knowledge_context

    class BrokenQuery:
        def filter_by(self, **_kwargs):
            raise RuntimeError("knowledge table unavailable")

    with app.app_context():
        monkeypatch.setattr(
            knowledge_rag.AssignmentKnowledgePoint,
            "query",
            BrokenQuery(),
        )
        retrieval = retrieve_assignment_knowledge(assignment_id)

    assert retrieval["status"] == "unavailable"
    assert retrieval["fallback"]["code"] == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    assert retrieval["metrics"]["no_result_fallback"] is False
    assert retrieval["metrics"]["retrieval_error_fallback"] is True
    assert "暂时不可用" in knowledge_rag.build_knowledge_prompt_context(retrieval)
    assert "暂时不可用" in knowledge_rag.render_knowledge_receipt(retrieval)


def test_ask_question_continues_with_answer_only_when_knowledge_source_is_unavailable(
    knowledge_context, monkeypatch
):
    app, client, assignment_id = knowledge_context

    class BrokenQuery:
        def filter_by(self, **_kwargs):
            raise RuntimeError("knowledge table unavailable")

    with app.app_context():
        monkeypatch.setattr(
            knowledge_rag.AssignmentKnowledgePoint,
            "query",
            BrokenQuery(),
        )

    monkeypatch.setattr(
        api_routes,
        "generate_answer_to_question",
        lambda **_: "请先检查边界条件。",
    )
    response = client.post(
        "/api/ask_question",
        json={
            "assignment_id": assignment_id,
            "code": "int main(){return 0;}",
            "question": "边界值怎么检查？",
        },
    )

    assert response.status_code == 200
    retrieval = response.json["data"]["knowledge_retrieval"]
    assert retrieval["status"] == "unavailable"
    assert retrieval["fallback"]["code"] == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    assert retrieval["metrics"]["retrieval_error_fallback"] is True
    assert "知识证据暂时不可用" in response.json["data"]["answer"]


def test_retriever_is_scoped_to_one_assignment(knowledge_context):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        other_assignment = Assignment(
            title="其他作业",
            description="不应被当前作业检索到。",
            creator_id="rag-student",
        )
        db.session.add(other_assignment)
        db.session.commit()
        AssignmentKnowledgePoint.add_to_assignment(
            other_assignment.id,
            "other-only",
        )
        retrieval = retrieve_assignment_knowledge(assignment_id)

    assert retrieval["status"] == "no_result"
    assert all("other-only" not in item["content"] for item in retrieval["evidence"])


def test_retriever_caps_evidence_and_orders_by_weight(knowledge_context):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        db.session.add_all(
            [
                AssignmentKnowledgePoint(
                    assignment_id=assignment_id,
                    knowledge_point=f"custom-{index}",
                    weight=float(index),
                )
                for index in range(10)
            ]
        )
        db.session.commit()
        retrieval = retrieve_assignment_knowledge(assignment_id)

    assert retrieval["status"] == "grounded"
    assert len(retrieval["evidence"]) == 8
    assert "custom-9" in retrieval["evidence"][0]["content"]
    assert "custom-2" in retrieval["evidence"][-1]["content"]
    assert retrieval["metrics"]["candidate_count"] == 8


def test_knowledge_receipt_escapes_untrusted_title():
    receipt = knowledge_rag.render_knowledge_receipt(
        {
            "status": "grounded",
            "evidence": [
                {
                    "citation": "[K1]",
                    "title": "<script>alert('x')</script> [unsafe]",
                }
            ],
        }
    )

    assert "<script>" not in receipt
    assert "&lt;script&gt;" in receipt
    assert "\\[unsafe\\]" in receipt
