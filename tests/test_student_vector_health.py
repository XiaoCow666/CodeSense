from tests.test_learning_graph import learning_graph_context

from models import StudentVectorIndexState, User, db
from services.student_vector_health import build_teacher_learning_memory_health


def test_teacher_learning_memory_health_uses_managed_class_aggregate(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        from datetime import datetime

        now = datetime.utcnow()
        db.session.add_all(
            [
                StudentVectorIndexState(
                    student_id=ids["student_one"],
                    revision=2,
                    status="ready",
                    source_count=3,
                    last_built_at=now,
                ),
                StudentVectorIndexState(
                    student_id=ids["student_two"],
                    revision=1,
                    status="failed",
                    source_count=2,
                    last_built_at=now,
                    failure_code="EMBEDDING_FAILED",
                ),
                StudentVectorIndexState(
                    student_id=ids["outside_student"],
                    revision=5,
                    status="failed",
                    source_count=9,
                    last_built_at=now,
                    failure_code="OUTSIDE_CLASS",
                ),
            ]
        )
        db.session.commit()

        teacher = db.session.get(User, ids["teacher"])
        health = build_teacher_learning_memory_health(teacher, now=now)

    assert health["student_count"] == 2
    assert health["ready_count"] == 1
    assert health["failed_count"] == 1
    assert health["not_built_count"] == 0
    assert health["previous_revision_count"] == 1
    assert ids["outside_student"] not in repr(health)


def test_teacher_dashboard_renders_learning_memory_health_and_scope(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        from datetime import datetime

        now = datetime.utcnow()
        db.session.add_all(
            [
                StudentVectorIndexState(
                    student_id=ids["student_one"],
                    revision=2,
                    status="ready",
                    source_count=3,
                    last_built_at=now,
                ),
                StudentVectorIndexState(
                    student_id=ids["student_two"],
                    revision=1,
                    status="failed",
                    source_count=2,
                    last_built_at=now,
                    failure_code="EMBEDDING_FAILED",
                ),
            ]
        )
        db.session.commit()

    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["teacher"], "password": "password"},
        follow_redirects=True,
    )
    body = login.get_data(as_text=True)

    assert login.status_code == 200
    assert "班级学习记录索引" in body
    assert "仅统计当前管理班级" in body
    assert "需要更新" in body
    assert ids["outside_student"] not in body
