from datetime import datetime, timedelta

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from forms import SubmissionForm
from models import Assignment, AssignmentKnowledgePoint, Submission, User, db
from routes import assignments as assignment_routes


@pytest.fixture
def submission_knowledge_context(tmp_path, monkeypatch):
    database_path = tmp_path / "submission-knowledge-views.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="submission-evidence-student",
            username="submission-evidence-student",
            usertype="学生",
        )
        outsider = User(
            student_id="submission-evidence-outsider",
            username="submission-evidence-outsider",
            usertype="学生",
        )
        for user in (student, outsider):
            user.password = "password"
        assignment = Assignment(
            title="提交证据作业",
            description="请解释指针和数组边界。",
            creator_id=student.student_id,
        )
        db.session.add_all([student, outsider, assignment])
        db.session.commit()
        AssignmentKnowledgePoint.add_to_assignment(
            assignment.id,
            "pointer",
            weight=1.0,
        )
        submission = Submission(
            student_id=student.student_id,
            assignment_id=assignment.id,
            code="int main() { return 0; }",
            language="cpp",
            score=4,
            status="evaluated",
            submitted_at=datetime.utcnow() - timedelta(minutes=2),
        )
        db.session.add(submission)
        db.session.commit()
        ids = {"assignment": assignment.id, "submission": submission.id}

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


def _retrieval(*args, **kwargs):
    return {
        "status": "grounded",
        "evidence": [
            {
                "evidence_id": "assignment-kp:1",
                "citation": "[K1]",
                "source_type": "assignment_knowledge_point",
                "title": "指针与数组边界",
                "content": "当前作业显式绑定知识点：指针。",
                "created_at": "2026-09-16T08:00:00",
            }
        ],
        "metrics": {
            "candidate_count": 1,
            "hit_count": 1,
            "indexed_chunk_count": 1,
            "retrieval_latency_ms": 2.5,
            "retrieval_mode": "vector",
        },
        "fallback": None,
    }


def test_submission_detail_shows_knowledge_focus_and_scoring_boundary(
    submission_knowledge_context, monkeypatch
):
    _, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-student")
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)

    response = client.get(f"/view_submission/{ids['submission']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "这道作业使用的知识焦点" in html
    assert "指针与数组边界" in html
    assert "不是本次评分依据" in html


def test_submission_detail_does_not_present_unavailable_sandbox_as_failed_score(
    submission_knowledge_context, monkeypatch
):
    app, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-student")
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)

    with app.app_context():
        submission = db.session.get(Submission, ids["submission"])
        submission.sandbox_status = "unavailable"
        submission.sandbox_passed = 0
        submission.sandbox_total = 2
        db.session.commit()

    response = client.get(f"/view_submission/{ids['submission']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "测试环境未就绪" in html
    assert "通过 0/2" not in html


def test_submission_detail_keeps_passed_sandbox_badge(
    submission_knowledge_context, monkeypatch
):
    app, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-student")
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)

    with app.app_context():
        submission = db.session.get(Submission, ids["submission"])
        submission.sandbox_status = "passed"
        submission.sandbox_passed = 2
        submission.sandbox_total = 2
        db.session.commit()

    response = client.get(f"/view_submission/{ids['submission']}")

    assert response.status_code == 200
    assert "通过 2/2" in response.get_data(as_text=True)


def test_submission_access_is_checked_before_knowledge_retrieval(
    submission_knowledge_context, monkeypatch
):
    _, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-outsider")

    def must_not_run(*args, **kwargs):
        pytest.fail("submission access must be checked before retrieval")

    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", must_not_run)

    response = client.get(f"/view_submission/{ids['submission']}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_submit_code_get_shows_initial_knowledge_focus(
    submission_knowledge_context, monkeypatch
):
    _, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-student")
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)

    response = client.get(f"/submit/{ids['assignment']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AI编程助手" in html
    assert "作业知识焦点" in html
    assert "指针与数组边界" in html
    assert "ai-quick-prompt-btn" in html
    assert "请用问题引导我检查" in html


def test_submit_validation_render_keeps_knowledge_focus(
    submission_knowledge_context, monkeypatch
):
    _, client, ids = submission_knowledge_context
    _login(client, "submission-evidence-student")
    monkeypatch.setattr(assignment_routes, "retrieve_assignment_knowledge", _retrieval)
    monkeypatch.setattr(SubmissionForm, "validate_on_submit", lambda self: True)

    response = client.post(
        f"/submit/{ids['assignment']}",
        data={"code": "int main() { return 0; }", "language": "rust"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "不支持的编程语言" in html
    assert "指针与数组边界" in html
