from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import template_rendered

from app import create_app
from config import TestingConfig
from models import Assignment, AssignmentKnowledgePoint, KnowledgePointScore, User, db
from services.adaptive_learning import build_adaptive_learning_plan


def _assignment(assignment_id, title, *, due_in_days=1, knowledge_points=()):
    return SimpleNamespace(
        id=assignment_id,
        title=title,
        due_date=datetime.utcnow() + timedelta(days=due_in_days),
        knowledge_points=[
            SimpleNamespace(knowledge_point=key, weight=weight)
            for key, weight in knowledge_points
        ],
    )


def _plan(**overrides):
    values = {
        "active_assignments": [],
        "recent_learning_sessions": [],
        "knowledge_profile_rows": [],
        "recent_submissions": [],
        "submitted_assignment_ids": [],
    }
    values.update(overrides)
    return build_adaptive_learning_plan(**values)


def test_resumable_session_takes_precedence_over_other_signals():
    assignment = _assignment(11, "三阶段数组练习", knowledge_points=(("array", 1.0),))

    plan = _plan(
        active_assignments=[assignment],
        recent_learning_sessions=[{
            "assignment": assignment,
            "lifecycle": {
                "is_resumable": True,
                "stage_label": "阶段二：拼装代码",
                "next_action": "完成代码块拼装与校验",
            },
        }],
        knowledge_profile_rows=[{
            "key": "array",
            "name": "数组",
            "score": 42,
            "total_attempts": 3,
        }],
    )

    assert plan["source"] == "resumable_session"
    assert plan["action"] == {
        "kind": "resume_learning",
        "assignment_id": 11,
        "label": "继续当前阶段",
    }


def test_weak_knowledge_requires_existing_attempts_and_a_matching_active_assignment():
    array_assignment = _assignment(12, "数组巩固", knowledge_points=(("array", 1.5),))
    unrelated_assignment = _assignment(13, "函数练习", knowledge_points=(("function", 2.0),))

    plan = _plan(
        active_assignments=[unrelated_assignment, array_assignment],
        knowledge_profile_rows=[
            {"key": "pointer", "name": "指针", "score": 0, "total_attempts": 0},
            {"key": "array", "name": "数组", "score": 55, "total_attempts": 2},
        ],
    )

    assert plan["source"] == "knowledge_gap"
    assert plan["action"]["assignment_id"] == array_assignment.id
    assert plan["evidence"][0]["detail"] == "数组 当前掌握度 55 分，已有 2 次练习记录。"


def test_low_scoring_active_submission_becomes_retry_when_no_session_or_knowledge_match():
    assignment = _assignment(14, "循环复练")
    submission = SimpleNamespace(
        assignment_id=assignment.id,
        status="evaluated",
        sandbox_status="partial",
        score=78,
        code="int main() { return 0; }",
        feedback="private feedback",
    )

    plan = _plan(
        active_assignments=[assignment],
        recent_submissions=[submission],
        submitted_assignment_ids=[assignment.id],
    )

    assert plan["source"] == "retry_submission"
    assert plan["action"]["kind"] == "retry_submission"
    assert plan["action"]["assignment_id"] == assignment.id
    assert "code" not in repr(plan).lower()
    assert "private feedback" not in repr(plan)


def test_first_unsubmitted_active_assignment_is_a_safe_starting_recommendation():
    later = _assignment(15, "稍后截止", due_in_days=3)
    sooner = _assignment(16, "优先完成", due_in_days=1)

    plan = _plan(
        active_assignments=[later, sooner],
        submitted_assignment_ids=[later.id],
    )

    assert plan["source"] == "unstarted_assignment"
    assert plan["action"]["assignment_id"] == sooner.id


def test_missing_current_evidence_never_claims_a_mastery_inference():
    plan = _plan()

    assert plan["status"] == "starting_point"
    assert plan["source"] == "no_current_evidence"
    assert plan["action"]["kind"] == "review_assignments"
    assert "不会根据缺失记录推断" in plan["evidence"][0]["detail"]


@pytest.fixture
def adaptive_home_context(tmp_path, monkeypatch):
    database_path = tmp_path / "adaptive-learning.db"
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="adaptive-student",
            username="adaptive-student",
            usertype="学生",
            class_name="自适应班",
            full_name="自适应学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="数组定向练习",
            description="不会进入自适应建议的作业描述",
            creator_id="adaptive-student",
            target_classes="自适应班",
            due_date=datetime.utcnow() + timedelta(days=1),
        )
        db.session.add_all([student, assignment])
        db.session.flush()
        db.session.add_all([
            AssignmentKnowledgePoint(
                assignment_id=assignment.id,
                knowledge_point="array",
                weight=1.0,
            ),
            KnowledgePointScore(
                student_id=student.student_id,
                knowledge_point="array",
                score=48,
                total_attempts=2,
                correct_attempts=0,
            ),
        ])
        db.session.commit()
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post("/login", data={"username": "adaptive-student", "password": "password"})
    assert login.status_code in {302, 303}
    yield app, client, assignment_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_student_home_renders_an_explainable_server_generated_adaptive_action(adaptive_home_context):
    app, client, assignment_id = adaptive_home_context
    rendered = []

    def capture(sender, template, context, **kwargs):
        rendered.append((template.name, context))

    with template_rendered.connected_to(capture, app):
        response = client.get("/home")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "自适应下一步" in body
    assert "优先巩固数组" in body
    assert "数组 当前掌握度 48 分，已有 2 次练习记录。" in body
    assert f'href="/submit/{assignment_id}"' in body

    template_name, context = rendered[-1]
    plan = context["adaptive_learning_plan"]
    assert template_name == "student_home.html"
    assert plan["source"] == "knowledge_gap"
    assert plan["action"]["href"] == f"/submit/{assignment_id}"
    assert "student_id" not in plan
    assert "code" not in repr(plan).lower()
