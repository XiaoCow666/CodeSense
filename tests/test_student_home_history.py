from datetime import datetime, timedelta

import pytest
from flask import template_rendered

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, Submission, User, db


@pytest.fixture
def student_home_context(tmp_path, monkeypatch):
    database_path = tmp_path / "student_home_history.db"
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="student-1",
            username="student-1",
            usertype="学生",
            class_name="软件2401",
            full_name="测试学生",
        )
        student.password = "password"
        expired = Assignment(
            title="历史循环练习",
            description="已经过期但仍属于学生历史数据",
            target_classes="软件2401",
            due_date=datetime.utcnow() - timedelta(days=1),
            creator_id="student-1",
        )
        active = Assignment(
            title="当前循环练习",
            description="当前作业",
            target_classes="软件2401",
            due_date=datetime.utcnow() + timedelta(days=1),
            creator_id="student-1",
        )
        db.session.add_all([student, expired, active])
        db.session.flush()
        db.session.add(Submission(
            student_id=student.student_id,
            assignment_id=expired.id,
            code="int main() { return 0; }",
            score=100,
            status="evaluated",
        ))
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"username": "student-1", "password": "password"})
    yield app, client
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_student_home_counts_historical_assignments_and_submissions(student_home_context):
    app, client = student_home_context
    rendered = []

    def capture(sender, template, context, **kwargs):
        rendered.append((template.name, context))

    with template_rendered.connected_to(capture, app):
        response = client.get("/home")

    assert response.status_code == 200
    template_name, context = rendered[-1]
    assert template_name == "student_home.html"
    assert context["assignments_count"] == 2
    assert context["submissions_count"] == 1
    assert context["active_assignments_count"] == 1
