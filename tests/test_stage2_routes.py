import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentThinkingPreset, ThinkingSession, User, db
from routes import thinking as thinking_routes


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
def stage2_context(tmp_path, monkeypatch):
    database_path = tmp_path / "stage2_routes.db"
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(student_id="stage2-student", username="stage2-student", usertype="学生")
        student.password = "password"
        assignment = Assignment(
            title="阶段二循环题",
            description="按步骤构建一个循环程序。",
            creator_id="stage2-student",
        )
        preset = AssignmentThinkingPreset(
            assignment=assignment,
            reference_code="int main() { return 0; }",
            key_steps=json.dumps(["输出结果"], ensure_ascii=False),
            quiz_steps=json.dumps([{
                "step_id": 1,
                "type": "fill",
                "question": "填写返回值",
                "correct_answer": "0",
            }], ensure_ascii=False),
            status="ready",
        )
        session = ThinkingSession(
            student=student,
            assignment=assignment,
            current_stage=2,
        )
        db.session.add_all([student, assignment, preset, session])
        db.session.commit()
        session_id = session.id

    client = app.test_client()
    login = client.post("/login", data={"username": "stage2-student", "password": "password"})
    assert login.status_code in {302, 303}
    yield app, client, session_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_stage2_verify_rejects_sessions_outside_stage2(stage2_context):
    app, client, session_id = stage2_context
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        session.current_stage = 1
        db.session.commit()

    response = client.post(
        "/thinking/api/stage2/verify",
        json={"session_id": session_id, "quiz_answers": {"1": "0"}},
    )

    assert response.status_code == 409
    assert response.json["error_code"] == "STAGE2_NOT_ACTIVE"
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.current_stage == 1
        assert session.stage2_completed is False


def test_stage2_hint_rejects_sessions_outside_stage2(stage2_context, monkeypatch):
    app, client, session_id = stage2_context
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        session.current_stage = 3
        session.stage2_completed = True
        db.session.commit()

    monkeypatch.setattr(thinking_routes, "generate_stage2_hint", lambda *args: "提示")
    response = client.post(
        "/thinking/api/stage2/hint",
        json={"session_id": session_id, "current_blocks": []},
    )

    assert response.status_code == 409
    assert response.json["error_code"] == "STAGE2_NOT_ACTIVE"
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.stage2_hint_count == 0


def test_stage2_hint_works_for_active_session(stage2_context, monkeypatch):
    app, client, session_id = stage2_context
    monkeypatch.setattr(thinking_routes, "generate_stage2_hint", lambda *args: "先检查循环边界")

    response = client.post(
        "/thinking/api/stage2/hint",
        json={"session_id": session_id, "current_blocks": ["1"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "success": True,
        "hint": "先检查循环边界",
        "hint_count": 1,
    }
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.stage2_hint_count == 1


def test_stage2_verify_rejects_missing_quiz_data(stage2_context):
    app, client, session_id = stage2_context
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        preset = AssignmentThinkingPreset.query.filter_by(assignment_id=session.assignment_id).first()
        preset.quiz_steps = "[]"
        db.session.commit()

    response = client.post(
        "/thinking/api/stage2/verify",
        json={"session_id": session_id, "quiz_answers": {}},
    )

    assert response.status_code == 503
    assert response.json["error_code"] == "STAGE2_UNAVAILABLE"
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.current_stage == 2
        assert session.stage2_completed is False


def test_stage2_verify_passes_and_persists_progress(stage2_context):
    app, client, session_id = stage2_context
    response = client.post(
        "/thinking/api/stage2/verify",
        json={"session_id": session_id, "quiz_answers": {"1": "0"}},
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["passed"] is True
    with app.app_context():
        session = db.session.get(ThinkingSession, session_id)
        assert session.current_stage == 3
        assert session.stage2_completed is True
        assert json.loads(session.stage2_block_order) == {"1": "0"}


def test_stage2_verify_keeps_sse_contract(stage2_context):
    _, client, session_id = stage2_context
    response = client.post(
        "/thinking/api/stage2/verify",
        json={"session_id": session_id, "quiz_answers": {"1": "0"}},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    events = _events(response)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert events[-1]["passed"] is True
