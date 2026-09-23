from datetime import datetime as dt, timedelta
import json

import pytest

from app import create_app
from config import TestingConfig
from models import (
    Assignment,
    AssignmentKnowledgePoint,
    Class,
    KnowledgePointScore,
    StudentVectorIndexState,
    User,
    db,
)
from services.teacher_learning_actions import (
    build_teacher_learning_actions,
    send_learning_memory_refresh_reminders,
)
from services.notifications import list_notifications


@pytest.fixture
def learning_actions_context(tmp_path, monkeypatch):
    database_path = tmp_path / "teacher-learning-actions.db"
    monkeypatch.setattr(
        TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    now = dt.utcnow()

    with app.app_context():
        db.create_all()
        teacher = User(
            student_id="action-teacher",
            username="action-teacher",
            usertype="教师",
            full_name="教学动作教师",
        )
        outsider_teacher = User(
            student_id="outside-teacher",
            username="outside-teacher",
            usertype="教师",
            full_name="其他教师",
        )
        admin = User(
            student_id="action-admin",
            username="action-admin",
            usertype="管理员",
            full_name="动作管理员",
        )
        teacher.password = "password"
        outsider_teacher.password = "password"
        admin.password = "password"
        managed_class = Class(name="动作班", teacher_id=teacher.student_id)
        outside_class = Class(name="其他班", teacher_id=outsider_teacher.student_id)
        db.session.add_all([
            teacher,
            outsider_teacher,
            admin,
            managed_class,
            outside_class,
        ])
        db.session.flush()

        students = [
            User(
                student_id="action-student-1",
                username="action-student-1",
                usertype="学生",
                full_name="学生一",
                class_id=managed_class.id,
                class_name=managed_class.name,
            ),
            User(
                student_id="action-student-2",
                username="action-student-2",
                usertype="学生",
                full_name="学生二",
                class_id=managed_class.id,
                class_name=managed_class.name,
            ),
            User(
                student_id="outside-student",
                username="outside-student",
                usertype="学生",
                full_name="其他学生",
                class_id=outside_class.id,
                class_name=outside_class.name,
            ),
        ]
        for student in students:
            student.password = "password"

        assignment = Assignment(
            title="指针边界练习",
            description="检查指针和数组边界。",
            creator_id=teacher.student_id,
            target_classes=managed_class.name,
        )
        db.session.add_all(students + [assignment])
        db.session.flush()
        db.session.add(
            AssignmentKnowledgePoint(
                assignment_id=assignment.id,
                knowledge_point="pointer",
                weight=1.0,
                difficulty=1.5,
            )
        )
        db.session.add_all([
            KnowledgePointScore(
                student_id="action-student-1",
                knowledge_point="pointer",
                score=40,
                total_attempts=3,
            ),
            KnowledgePointScore(
                student_id="action-student-2",
                knowledge_point="pointer",
                score=50,
                total_attempts=2,
            ),
            StudentVectorIndexState(
                student_id="action-student-1",
                status="not_built",
                revision=0,
                source_count=0,
            ),
            StudentVectorIndexState(
                student_id="action-student-2",
                status="failed",
                revision=2,
                source_count=1,
                last_built_at=now - timedelta(days=1),
            ),
        ])
        db.session.commit()

        yield app, {
            "teacher_id": teacher.student_id,
            "outside_teacher_id": outsider_teacher.student_id,
            "admin_id": admin.student_id,
            "class_id": managed_class.id,
            "outside_class_id": outside_class.id,
            "student_id": students[0].student_id,
            "assignment_id": assignment.id,
            "now": now,
        }

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _login(client, username):
    response = client.post("/login", data={"username": username, "password": "password"})
    assert response.status_code in {302, 303}


def test_teacher_actions_join_graph_and_vector_health_without_private_records(
    learning_actions_context,
):
    app, ids = learning_actions_context
    with app.app_context():
        teacher = db.session.get(User, ids["teacher_id"])
        snapshot = build_teacher_learning_actions(teacher, now=ids["now"])

    assert snapshot["scope"] == "teacher_managed_classes"
    assert snapshot["privacy"] == "class_aggregate"
    assert snapshot["class_count"] == 1
    assert {item["kind"] for item in snapshot["actions"]} == {
        "knowledge_practice",
        "learning_memory_refresh",
    }
    knowledge_action = next(
        item for item in snapshot["actions"] if item["kind"] == "knowledge_practice"
    )
    assert knowledge_action["class_id"] == ids["class_id"]
    assert knowledge_action["knowledge_point"] == "pointer"
    assert knowledge_action["source_versions"]
    assert f"class_id={ids['class_id']}" in knowledge_action["href"]
    memory_action = next(
        item for item in snapshot["actions"] if item["kind"] == "learning_memory_refresh"
    )
    assert memory_action["student_count"] == 2
    assert memory_action["needs_refresh_count"] == 2
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "action-student-1" not in serialized
    assert "学生一" not in serialized
    assert "student_private" not in serialized


def test_teacher_dashboard_and_reminder_are_scoped_and_idempotent(
    learning_actions_context,
):
    app, ids = learning_actions_context
    teacher_client = app.test_client()
    _login(teacher_client, "action-teacher")

    dashboard = teacher_client.get("/teacher_dashboard")
    assert dashboard.status_code == 200
    dashboard_body = dashboard.get_data(as_text=True)
    assert "可执行教学动作" in dashboard_body
    assert "提醒学生更新学习记忆" in dashboard_body
    assert f"/teacher/classes/{ids['class_id']}/learning-memory-reminder" in dashboard_body
    assert "指针" in dashboard_body

    first = teacher_client.post(
        f"/teacher/classes/{ids['class_id']}/learning-memory-reminder",
        follow_redirects=False,
    )
    second = teacher_client.post(
        f"/teacher/classes/{ids['class_id']}/learning-memory-reminder",
        follow_redirects=False,
    )
    assert first.status_code == 302
    assert second.status_code == 302

    with app.app_context():
        first_notifications = list_notifications(ids["student_id"], limit=20)
        second_notifications = list_notifications("action-student-2", limit=20)
        outside_notifications = list_notifications("outside-student", limit=20)
    assert len(first_notifications) == 1
    assert len(second_notifications) == 1
    assert outside_notifications == []
    assert first_notifications[0]["kind"] == "learning_memory_refresh"
    assert first_notifications[0]["url"].endswith("#student-learning-memory-title")

    foreign = teacher_client.post(
        f"/teacher/classes/{ids['outside_class_id']}/learning-memory-reminder",
        follow_redirects=False,
    )
    assert foreign.status_code == 403
    teacher_client.post("/logout")

    student_client = app.test_client()
    _login(student_client, "action-student-1")
    student_payload = student_client.get("/api/action-center").get_json()
    assert any(
        item["title"] == "教师提醒：更新学习记忆"
        for item in student_payload["items"]
    )
    assert any(
        item["kind"] == "learning_memory_refresh"
        and item["priority"] == "next"
        for item in student_payload["items"]
    )
    action_center = student_client.get("/action-center")
    assert action_center.status_code == 200
    action_center_body = action_center.get_data(as_text=True)
    assert "教师提醒：更新学习记忆" in action_center_body
    assert "#student-learning-memory-title" in action_center_body


def test_class_detail_and_ai_suggestions_keep_the_same_scoped_actions(
    learning_actions_context,
):
    app, ids = learning_actions_context
    teacher_client = app.test_client()
    _login(teacher_client, "action-teacher")

    class_detail = teacher_client.get(f"/classes/{ids['class_id']}")
    assert class_detail.status_code == 200
    class_body = class_detail.get_data(as_text=True)
    assert "本班可执行教学动作" in class_body
    assert 'data-teacher-learning-actions' in class_body
    assert f"/teacher/classes/{ids['class_id']}/learning-memory-reminder" in class_body

    suggestions = teacher_client.get("/teacher/ai_suggestions")
    assert suggestions.status_code == 200
    suggestion_body = suggestions.get_data(as_text=True)
    assert "依据与下一步" in suggestion_body
    assert "指针" in suggestion_body


def test_admin_can_view_class_summary_without_teacher_actions(
    learning_actions_context,
):
    app, ids = learning_actions_context
    admin_client = app.test_client()
    _login(admin_client, "action-admin")

    class_detail = admin_client.get(f"/classes/{ids['class_id']}")
    assert class_detail.status_code == 200
    body = class_detail.get_data(as_text=True)
    assert "学生学情概览" in body
    assert "本班可执行教学动作" not in body
    assert "action-student-1" in body

    reminder = admin_client.post(
        f"/teacher/classes/{ids['class_id']}/learning-memory-reminder",
        follow_redirects=False,
    )
    assert reminder.status_code == 403


def test_direct_reminder_service_reports_deduplicated_recipients(learning_actions_context):
    app, ids = learning_actions_context
    with app.app_context():
        teacher = db.session.get(User, ids["teacher_id"])
        result = send_learning_memory_refresh_reminders(
            teacher,
            ids["class_id"],
            now=ids["now"],
            url="/#student-learning-memory-title",
        )
        repeated = send_learning_memory_refresh_reminders(
            teacher,
            ids["class_id"],
            now=ids["now"],
            url="/#student-learning-memory-title",
        )

    assert result["student_count"] == 2
    assert result["needs_refresh_count"] == 2
    assert result["notification_count"] == 2
    assert repeated["notification_count"] == 2
    assert repeated["idempotency"] == "daily_class_reminder"


def test_student_source_revoke_removes_real_indexed_feedback_from_retrieval(
    learning_actions_context,
):
    from models import Submission
    from services.student_vector_store import (
        list_student_learning_sources,
        rebuild_student_vector_index,
        revoke_student_vector_source,
        search_student_learning_vectors,
    )

    app, ids = learning_actions_context
    with app.app_context():
        submission = Submission(
            student_id=ids["student_id"],
            assignment_id=ids["assignment_id"],
            code="int main(void) { return 0; }",
            status="evaluated",
            feedback="数组边界访问错误，请检查循环终止条件。",
        )
        db.session.add(submission)
        db.session.commit()
        rebuild_student_vector_index(ids["student_id"])
        before = search_student_learning_vectors(
            ids["student_id"],
            "数组边界访问错误",
            assignment_id=ids["assignment_id"],
        )
        source = next(
            item
            for item in list_student_learning_sources(ids["student_id"])
            if item["source_id"] == f"submission:{submission.id}"
        )
        revoke_student_vector_source(
            ids["student_id"],
            source["source_type"],
            source["source_id"],
        )
        after = search_student_learning_vectors(
            ids["student_id"],
            "数组边界访问错误",
            assignment_id=ids["assignment_id"],
        )
        sources = list_student_learning_sources(ids["student_id"])

    assert before["evidence"]
    assert after["evidence"] == []
    revoked = next(item for item in sources if item["source_id"] == source["source_id"])
    assert revoked["status"] == "revoked"
    assert revoked["revoke_reason"] == "user_revoked"


def test_student_vector_fixture_keeps_recall_and_scope_guards():
    from services.student_vector_eval import evaluate_student_vector_fixture

    metrics = evaluate_student_vector_fixture()
    assert metrics["recall_at_k"] == 1.0
    assert metrics["cross_scope_hit_count"] == 0
    assert metrics["revoked_hit_count"] == 0
    assert metrics["status_mismatch_count"] == 0
