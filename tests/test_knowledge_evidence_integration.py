import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentKnowledgePoint, Submission, User, db
from routes import api as api_routes
from routes import assignments as assignment_routes


@pytest.fixture
def integrated_evidence_context(tmp_path, monkeypatch):
    database_path = tmp_path / "knowledge-evidence-integration.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="evidence-integration-student",
            username="evidence-integration-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="证据集成作业",
            description="请结合循环与数组边界完成程序。",
            creator_id=student.student_id,
        )
        db.session.add_all([student, assignment])
        db.session.commit()
        AssignmentKnowledgePoint.add_to_assignment(assignment.id, "array")
        submission = Submission(
            student_id=student.student_id,
            assignment_id=assignment.id,
            code="int main() { return 0; }",
            language="cpp",
            score=4,
            status="evaluated",
        )
        db.session.add(submission)
        db.session.commit()
        ids = {"assignment": assignment.id, "submission": submission.id}

    client = app.test_client()
    login = client.post(
        "/login",
        data={
            "username": "evidence-integration-student",
            "password": "password",
        },
    )
    assert login.status_code in {302, 303}
    yield app, client, ids

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _retrieval(*args, **kwargs):
    return {
        "status": "grounded",
        "evidence": [
            {
                "evidence_id": "assignment-kp:integration",
                "citation": "[K1]",
                "source_type": "assignment_knowledge_point",
                "title": "数组边界",
                "content": "只属于当前作业的知识证据。",
                "created_at": "2026-09-16T08:00:00",
                "private_score": 99,
            }
        ],
        "metrics": {
            "candidate_count": 1,
            "hit_count": 1,
            "indexed_chunk_count": 1,
            "retrieval_latency_ms": 1.25,
            "retrieval_mode": "vector",
            "citation_completeness": 1.0,
        },
        "fallback": None,
        "private_prompt": "must not be copied into view",
    }


class _FakeSharedClient:
    def is_available(self):
        return True

    def chat_stream(self, messages, **kwargs):
        return iter(["请先检查数组边界。"])


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def test_assignment_submission_api_and_code_advice_share_safe_evidence_projection(
    integrated_evidence_context, monkeypatch
):
    _, client, ids = integrated_evidence_context
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)
    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", _retrieval)
    monkeypatch.setattr(
        "services.llm_client.SharedLLMClient",
        lambda: _FakeSharedClient(),
    )

    assignment_page = client.get(f"/view_assignment/{ids['assignment']}")
    submit_page = client.get(f"/submit/{ids['assignment']}")
    submission_page = client.get(f"/view_submission/{ids['submission']}")
    evidence_api = client.get(
        f"/api/assignments/{ids['assignment']}/knowledge-evidence?q=数组边界"
    )
    advice = client.post(
        "/api/code_advice",
        json={
            "code": "int main(){return 0;}",
            "assignment_id": ids["assignment"],
            "question": "数组边界怎么检查？",
        },
        headers={"Accept": "text/event-stream"},
    )

    assert assignment_page.status_code == 200
    assert submit_page.status_code == 200
    assert submission_page.status_code == 200
    assert evidence_api.status_code == 200
    assert advice.status_code == 200
    assert "数组边界" in assignment_page.get_data(as_text=True)
    assert "数组边界" in submit_page.get_data(as_text=True)
    assert "不是本次评分依据" in submission_page.get_data(as_text=True)

    api_view = evidence_api.json["data"]["knowledge_evidence"]
    done = _events(advice)[-1]
    assert done["knowledge_evidence"] == api_view
    payload = json.dumps(
        {
            "assignment": assignment_page.get_data(as_text=True),
            "submit": submit_page.get_data(as_text=True),
            "submission": submission_page.get_data(as_text=True),
            "api": evidence_api.json,
            "advice": done,
        },
        ensure_ascii=False,
    )
    assert "private_score" not in payload
    assert "private_prompt" not in payload


def test_integration_keeps_evidence_api_non_cacheable_and_recoverable(
    integrated_evidence_context, monkeypatch
):
    _, client, ids = integrated_evidence_context
    monkeypatch.setattr(
        api_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: {
            "status": "no_result",
            "evidence": [],
            "metrics": {
                "candidate_count": 0,
                "hit_count": 0,
                "indexed_chunk_count": 1,
                "retrieval_latency_ms": 0.5,
                "retrieval_mode": "no_result",
            },
            "fallback": {"code": "NO_KNOWLEDGE_EVIDENCE", "message": "暂无证据。"},
        },
    )

    response = client.get(f"/api/assignments/{ids['assignment']}/knowledge-evidence")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    view = response.json["data"]["knowledge_evidence"]
    assert view["status"] == "no_result"
    assert "缩小问题" in view["next_step"]
