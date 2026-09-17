import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentKnowledgePoint, KnowledgePointScore, User, db
from routes import api as api_routes


@pytest.fixture
def evidence_api_context(tmp_path, monkeypatch):
    database_path = tmp_path / "knowledge-evidence-api.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        student = User(
            student_id="evidence-student",
            username="evidence-student",
            usertype="学生",
            full_name="证据学生私密名",
        )
        outsider = User(
            student_id="evidence-outsider",
            username="evidence-outsider",
            usertype="学生",
        )
        teacher = User(
            student_id="evidence-teacher",
            username="evidence-teacher",
            usertype="教师",
        )
        admin = User(
            student_id="evidence-admin",
            username="evidence-admin",
            usertype="管理员",
        )
        for user in (student, outsider, teacher, admin):
            user.password = "password"

        student_assignment = Assignment(
            title="证据作业",
            description="请处理数组边界。",
            creator_id=student.student_id,
        )
        hidden_assignment = Assignment(
            title="隐藏作业",
            description="不应被枚举。",
            creator_id=outsider.student_id,
        )
        teacher_assignment = Assignment(
            title="教师证据作业",
            description="教师可查看诊断。",
            creator_id=teacher.student_id,
        )
        db.session.add_all(
            [student, outsider, teacher, admin, student_assignment, hidden_assignment, teacher_assignment]
        )
        db.session.commit()
        AssignmentKnowledgePoint.add_to_assignment(
            student_assignment.id,
            "array",
            weight=1.5,
            auto_detected=True,
        )
        AssignmentKnowledgePoint.add_to_assignment(
            teacher_assignment.id,
            "pointer",
            weight=1.0,
        )
        KnowledgePointScore(
            student_id=student.student_id,
            knowledge_point="array",
            score=99.0,
        )
        private_score = KnowledgePointScore(
            student_id=student.student_id,
            knowledge_point="array",
            score=99.0,
        )
        db.session.add(private_score)
        db.session.commit()
        ids = {
            "student": student_assignment.id,
            "hidden": hidden_assignment.id,
            "teacher": teacher_assignment.id,
        }

    client = app.test_client()
    yield app, client, ids

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _login(client, username):
    response = client.post(
        "/login",
        data={"username": username, "password": "password"},
    )
    assert response.status_code in {302, 303}


def _grounded_retrieval():
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
            "retrieval_hit_rate": 1.0,
            "citation_completeness": 1.0,
            "no_result_fallback": False,
            "retrieval_error_fallback": False,
        },
        "fallback": None,
    }


def test_student_can_fetch_bounded_evidence_with_query_and_limit(
    evidence_api_context, monkeypatch
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-student")
    captured = {}

    def fake_retrieval(assignment_id, *, query="", limit=8):
        captured.update(assignment_id=assignment_id, query=query, limit=limit)
        return _grounded_retrieval()

    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", fake_retrieval)

    response = client.get(
        f"/api/assignments/{ids['student']}/knowledge-evidence"
        "?q=%E6%95%B0%E7%BB%84%E8%BE%B9%E7%95%8C&limit=1"
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert captured == {
        "assignment_id": ids["student"],
        "query": "数组边界",
        "limit": 1,
    }
    data = response.json["data"]
    assert data["knowledge_retrieval"]["status"] == "grounded"
    assert data["knowledge_evidence"]["status"] == "grounded"
    assert "diagnostics" not in data["knowledge_evidence"]


def test_missing_and_forbidden_assignments_share_a_non_enumerating_403(
    evidence_api_context, monkeypatch
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-student")
    calls = []
    monkeypatch.setattr(
        api_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _grounded_retrieval(),
    )

    forbidden = client.get(f"/api/assignments/{ids['hidden']}/knowledge-evidence")
    missing = client.get("/api/assignments/999999/knowledge-evidence")

    assert forbidden.status_code == 403
    assert missing.status_code == 403
    assert forbidden.json == missing.json
    assert forbidden.headers["Cache-Control"] == "no-store"
    assert missing.headers["Cache-Control"] == "no-store"
    assert calls == []


@pytest.mark.parametrize(
    "query_string",
    [
        "?q=" + "x" * 2001,
        "?limit=0",
        "?limit=9",
        "?limit=not-an-integer",
        "?limit=1.5",
    ],
)
def test_invalid_query_or_limit_returns_no_store_400(
    evidence_api_context, query_string, monkeypatch
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-student")
    monkeypatch.setattr(
        api_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: pytest.fail("retrieval must not run for invalid input"),
    )

    response = client.get(
        f"/api/assignments/{ids['student']}/knowledge-evidence{query_string}"
    )

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_teacher_receives_diagnostics_but_private_scores_stay_out_of_payload(
    evidence_api_context
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-teacher")

    response = client.get(f"/api/assignments/{ids['teacher']}/knowledge-evidence")

    assert response.status_code == 200
    view = response.json["data"]["knowledge_evidence"]
    assert view["diagnostics"]["candidate_count"] == 1
    payload = json.dumps(response.json, ensure_ascii=False)
    assert "KnowledgePointScore" not in payload
    assert "private_score" not in payload
    assert "99.0" not in payload


def test_retrieval_failure_returns_safe_fallback_without_sensitive_log(
    evidence_api_context, monkeypatch, caplog
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-student")

    def broken_retrieval(*args, **kwargs):
        raise RuntimeError("SECRET_QUERY and SECRET_EVIDENCE")

    monkeypatch.setattr(api_routes, "retrieve_assignment_knowledge", broken_retrieval)
    caplog.set_level("INFO")

    response = client.get(
        f"/api/assignments/{ids['student']}/knowledge-evidence?q=SECRET_QUERY"
    )

    assert response.status_code == 200
    data = response.json["data"]
    assert data["knowledge_retrieval"]["status"] == "unavailable"
    assert (
        data["knowledge_evidence"]["fallback_code"]
        == "KNOWLEDGE_RETRIEVAL_UNAVAILABLE"
    )
    assert "SECRET_QUERY" not in caplog.text
    assert "SECRET_EVIDENCE" not in caplog.text


def test_timeout_response_keeps_timeout_status_in_public_projection(
    evidence_api_context, monkeypatch
):
    _, client, ids = evidence_api_context
    _login(client, "evidence-student")
    monkeypatch.setattr(
        api_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: {
            "status": "timeout",
            "evidence": [],
            "metrics": {
                "candidate_count": 1,
                "hit_count": 0,
                "retrieval_latency_ms": 250.0,
                "retrieval_mode": "timeout",
                "retrieval_timeout_fallback": True,
                "index_revision": 4,
            },
            "fallback": {
                "code": "KNOWLEDGE_RETRIEVAL_TIMEOUT",
                "message": "知识证据检索超时，回答仅基于题目和代码。",
            },
        },
    )

    response = client.get(f"/api/assignments/{ids['student']}/knowledge-evidence")

    assert response.status_code == 200
    data = response.json["data"]
    assert data["knowledge_retrieval"]["status"] == "timeout"
    assert data["knowledge_retrieval"]["fallback"]["code"] == (
        "KNOWLEDGE_RETRIEVAL_TIMEOUT"
    )
    assert data["knowledge_evidence"]["status"] == "timeout"
    assert data["knowledge_evidence"]["retryable"] is True


def test_unauthenticated_request_keeps_login_boundary(evidence_api_context):
    _, client, ids = evidence_api_context

    response = client.get(f"/api/assignments/{ids['student']}/knowledge-evidence")

    assert response.status_code in {302, 401}
