from datetime import datetime

import pytest

from app import create_app
from config import TestingConfig
from models import (
    Assignment,
    KnowledgePointScore,
    Submission,
    StudentLearningVector,
    StudentVectorIndexState,
    StudentVectorRetrievalLog,
    User,
    db,
)
from services.student_vector_store import (
    StudentVectorRebuildError,
    get_student_vector_snapshot,
    rebuild_student_vector_index,
    revoke_student_vector_source,
    search_student_learning_vectors,
)


@pytest.fixture
def vector_context(tmp_path, monkeypatch):
    database_path = tmp_path / "student_vectors.db"
    monkeypatch.setattr(
        TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_student_vector_lifecycle_tables_store_source_version_and_revoke_state(
    vector_context,
):
    app = vector_context
    with app.app_context():
        vector = StudentLearningVector(
            student_id="vector-student",
            scope_type="student_private",
            source_type="submission_feedback",
            source_id="submission:11",
            source_version="version-a",
            assignment_id=7,
            source_title="数组边界反馈",
            content="请检查空数组和下标边界。",
            embedding='{"数组": 0.5}',
            index_revision=1,
            status="active",
        )
        state = StudentVectorIndexState(
            student_id="vector-student",
            revision=1,
            status="ready",
            source_count=1,
            last_built_at=datetime.utcnow(),
        )
        log = StudentVectorRetrievalLog(
            student_id="vector-student",
            assignment_id=7,
            query_hash="abc123",
            result_count=1,
            index_revision=1,
            retrieval_mode="vector",
            status="grounded",
        )
        db.session.add_all([vector, state, log])
        db.session.commit()

        stored = StudentLearningVector.query.one()
        assert stored.scope_type == "student_private"
        assert stored.source_version == "version-a"
        assert stored.status == "active"
        assert StudentVectorIndexState.query.one().revision == 1
        assert StudentVectorRetrievalLog.query.one().query_hash == "abc123"

        stored.status = "revoked"
        stored.revoked_at = datetime.utcnow()
        db.session.commit()

        assert StudentLearningVector.query.one().status == "revoked"


@pytest.fixture
def seeded_student_vector_context(vector_context):
    app = vector_context
    with app.app_context():
        student_one = User(
            student_id="vector-student-1",
            username="vector-student-1",
            usertype="学生",
            full_name="学生一",
        )
        student_two = User(
            student_id="vector-student-2",
            username="vector-student-2",
            usertype="学生",
            full_name="学生二",
        )
        student_one.password = "password"
        student_two.password = "password"
        assignment_one = Assignment(
            title="递归边界练习",
            description="检查递归终止条件。",
            creator_id=student_one.student_id,
        )
        assignment_two = Assignment(
            title="指针生命周期练习",
            description="检查指针生命周期。",
            creator_id=student_two.student_id,
        )
        db.session.add_all([student_one, student_two, assignment_one, assignment_two])
        db.session.flush()
        submission_one = Submission(
            student_id=student_one.student_id,
            assignment_id=assignment_one.id,
            code="int main() { return 0; }",
            score=55,
            status="evaluated",
            feedback="请检查递归边界和终止条件。",
            ai_feedback="可以先手动追踪空输入。",
        )
        submission_two = Submission(
            student_id=student_two.student_id,
            assignment_id=assignment_two.id,
            code="int main() { return 0; }",
            score=45,
            status="evaluated",
            feedback="请检查指针生命周期。",
        )
        db.session.add_all([
            submission_one,
            submission_two,
            KnowledgePointScore(
                student_id=student_one.student_id,
                knowledge_point="recursion",
                score=55,
                total_attempts=2,
                correct_attempts=1,
            ),
        ])
        db.session.commit()
        ids = {
            "student_one": student_one.student_id,
            "student_two": student_two.student_id,
            "assignment_one": assignment_one.id,
            "assignment_two": assignment_two.id,
            "submission_one": submission_one.id,
        }
    return app, ids


def test_rebuild_creates_versioned_sources_for_only_the_current_student(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        result = rebuild_student_vector_index(ids["student_one"])

        assert result["status"] == "ready"
        assert result["revision"] == 1
        active = StudentLearningVector.query.filter_by(
            student_id=ids["student_one"],
            status="active",
        ).all()
        assert {item.source_type for item in active} == {
            "submission_feedback",
            "knowledge_point_score",
        }
        assert all(item.scope_type == "student_private" for item in active)
        assert not StudentLearningVector.query.filter_by(
            student_id=ids["student_two"]
        ).count()


def test_search_filters_student_and_assignment_scope_before_similarity(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        rebuild_student_vector_index(ids["student_one"])
        rebuild_student_vector_index(ids["student_two"])

        own = search_student_learning_vectors(
            ids["student_one"],
            "递归边界",
            assignment_id=ids["assignment_one"],
        )
        other_student = search_student_learning_vectors(
            ids["student_one"],
            "指针生命周期",
            assignment_id=ids["assignment_one"],
        )
        other_assignment = search_student_learning_vectors(
            ids["student_one"],
            "递归边界",
            assignment_id=ids["assignment_two"],
        )

        assert own["status"] == "grounded"
        assert own["evidence"][0]["assignment_id"] == ids["assignment_one"]
        assert other_student["status"] == "no_result"
        assert other_assignment["status"] == "no_result"


def test_rebuild_revokes_changed_source_and_search_logs_have_no_query_text(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        rebuild_student_vector_index(ids["student_one"])
        submission = db.session.get(Submission, ids["submission_one"])
        submission.feedback = "修订后请检查递归终止条件。"
        db.session.commit()

        rebuilt = rebuild_student_vector_index(ids["student_one"])
        result = search_student_learning_vectors(
            ids["student_one"],
            "修订后递归终止",
            assignment_id=ids["assignment_one"],
        )
        old_rows = StudentLearningVector.query.filter_by(
            student_id=ids["student_one"],
            source_type="submission_feedback",
            source_id=f"submission:{ids['submission_one']}",
        ).all()
        logs = StudentVectorRetrievalLog.query.filter_by(
            student_id=ids["student_one"]
        ).all()
        snapshot = get_student_vector_snapshot(ids["student_one"])

        assert rebuilt["revision"] == 2
        assert len([row for row in old_rows if row.status == "active"]) == 1
        assert len({row.source_version for row in old_rows}) == 2
        assert result["status"] == "grounded"
        assert logs
        assert all("修订后递归终止" not in log.query_hash for log in logs)
        assert snapshot["status"] == "ready"
        assert snapshot["revision"] == 2

        revoke_student_vector_source(
            ids["student_one"],
            "submission_feedback",
            f"submission:{ids['submission_one']}",
        )
        revoked = search_student_learning_vectors(
            ids["student_one"],
            "修订后递归终止",
            assignment_id=ids["assignment_one"],
        )

        assert revoked["status"] == "no_result"
        assert all(
            row.status == "revoked"
            for row in StudentLearningVector.query.filter_by(
                student_id=ids["student_one"],
                source_type="submission_feedback",
                source_id=f"submission:{ids['submission_one']}",
            ).all()
        )


def test_user_revoked_source_is_excluded_from_rebuild_source_count(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        rebuild_student_vector_index(ids["student_one"])
        revoke_student_vector_source(
            ids["student_one"],
            "submission_feedback",
            f"submission:{ids['submission_one']}",
        )

        rebuilt = rebuild_student_vector_index(ids["student_one"])

        assert rebuilt["source_count"] == rebuilt["active_count"]
        assert rebuilt["source_count"] == 1


def test_user_revocation_survives_source_version_change(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        rebuild_student_vector_index(ids["student_one"])
        revoke_student_vector_source(
            ids["student_one"],
            "submission_feedback",
            f"submission:{ids['submission_one']}",
        )
        submission = db.session.get(Submission, ids["submission_one"])
        submission.feedback = "更新后的反馈仍然包含递归边界。"
        db.session.commit()

        rebuilt = rebuild_student_vector_index(ids["student_one"])
        result = search_student_learning_vectors(
            ids["student_one"],
            "更新后的递归边界",
            assignment_id=ids["assignment_one"],
        )

        assert rebuilt["source_count"] == rebuilt["active_count"] == 1
        assert result["status"] == "no_result"


def test_failed_rebuild_keeps_previous_active_revision_and_can_retry(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        first = rebuild_student_vector_index(ids["student_one"])

        with pytest.raises(StudentVectorRebuildError):
            rebuild_student_vector_index(ids["student_one"], embedder=object())

        failed_state = StudentVectorIndexState.query.filter_by(
            student_id=ids["student_one"]
        ).one()
        active_after_failure = StudentLearningVector.query.filter_by(
            student_id=ids["student_one"],
            status="active",
        ).count()
        failed_status = failed_state.status
        failed_revision = failed_state.revision

        retried = rebuild_student_vector_index(ids["student_one"])

        assert first["revision"] == 1
        assert failed_status == "failed"
        assert failed_revision == 1
        assert active_after_failure == first["source_count"]
        assert retried["status"] == "ready"
        assert retried["revision"] == 2


def test_submission_refresh_entrypoint_builds_the_same_student_index(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    from tasks.submission_tasks import refresh_student_learning_index

    with app.app_context():
        result = refresh_student_learning_index(ids["student_one"])

        assert result["status"] == "ready"
        assert result["active_count"] == result["source_count"]


def test_student_home_shows_vector_state_and_rebuilds_only_for_the_student(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    client = app.test_client()

    login = client.post(
        "/login",
        data={"username": ids["student_one"], "password": "password"},
        follow_redirects=True,
    )
    assert login.status_code == 200
    assert "我的学习记忆" in login.get_data(as_text=True)
    assert "尚未建立" in login.get_data(as_text=True)

    rebuilt = client.post(
        "/student/rebuild-learning-memory",
        follow_redirects=True,
    )

    assert rebuilt.status_code == 200
    body = rebuilt.get_data(as_text=True)
    assert "我的学习记忆" in body
    assert "已建立" in body
    assert ids["student_two"] not in body
