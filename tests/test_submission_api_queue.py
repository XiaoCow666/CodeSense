from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, Submission, User, db
from routes import api as api_routes
from routes import assignments as assignments_routes
from tasks.submission_queue import SubmissionJobState, SubmissionQueueUnavailable


@pytest.fixture
def queue_context(tmp_path, monkeypatch):
    database_path = tmp_path / "submission_queue_api.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="queue-student",
            username="queue-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="队列提交题",
            description="请完成一个最小程序。",
            creator_id="queue-student",
        )
        db.session.add_all([student, assignment])
        db.session.commit()
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": "queue-student", "password": "password"},
    )
    assert login.status_code in {302, 303}
    yield app, client, assignment_id

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_api_submit_returns_durable_operation_without_calling_evaluator(
    queue_context, monkeypatch
):
    app, client, assignment_id = queue_context
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/1",
    )
    monkeypatch.setattr(
        api_routes,
        "evaluate_cpp_code",
        lambda **_: pytest.fail("must not run in the Web process"),
    )
    enqueued = []

    def enqueue(app_object, submission_id, assignment_title, **_):
        enqueued.append(submission_id)
        return SubmissionJobState(
            f"submission-evaluation-{submission_id}", "queued", True
        )

    monkeypatch.setattr(api_routes, "evaluate_submission_async", enqueue, raising=False)

    response = client.post(
        "/api/submit",
        json={"assignment_id": assignment_id, "code": "int main(){}"},
    )

    assert response.status_code == 202
    assert response.json["success"] is True
    assert response.json["data"]["status"] == "queued"
    operation_id = response.json["data"]["operation_id"]
    assert operation_id.startswith("submission-evaluation-")
    with app.app_context():
        submission = Submission.query.one()
        assert submission.status == "pending"
        assert enqueued == [submission.id]


def test_regular_form_uses_durable_submission_evaluation_path(queue_context, monkeypatch):
    app, client, assignment_id = queue_context
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "rq"
    expected = SubmissionJobState("submission-evaluation-1", "queued", True)
    monkeypatch.setattr(
        assignments_routes,
        "evaluate_submission_async",
        lambda *args, **kwargs: expected,
    )

    response = client.post(
        f"/submit/{assignment_id}",
        data={"code": "int main() { return 0; }", "language": "cpp"},
    )

    assert response.status_code in {302, 303}
    assert "/submission/" in response.headers["Location"]
    assert "/evaluating" in response.headers["Location"]
    with app.app_context():
        submission = Submission.query.one()
        assert submission.status == "pending"


def test_regular_form_marks_submission_failed_when_evaluation_cannot_start(
    queue_context, monkeypatch
):
    app, client, assignment_id = queue_context

    def fail_to_start(*args, **kwargs):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(
        assignments_routes,
        "evaluate_submission_async",
        fail_to_start,
    )

    response = client.post(
        f"/submit/{assignment_id}",
        data={"code": "int main() { return 0; }", "language": "cpp"},
    )

    assert response.status_code in {302, 303}
    assert f"/submit/{assignment_id}" in response.headers["Location"]
    with app.app_context():
        submission = Submission.query.one()
        submission_id = submission.id
        assert submission.status == "failed"
        assert submission.feedback == "后台评测启动失败，请稍后重试。"

    status_response = client.get(f"/api/submissions/{submission_id}/status")
    assert status_response.status_code == 200
    assert status_response.json["status"] == "failed"


def test_regular_form_rejects_new_submission_after_deadline(queue_context, monkeypatch):
    app, client, assignment_id = queue_context
    with app.app_context():
        assignment = db.session.get(Assignment, assignment_id)
        assignment.due_date = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

    monkeypatch.setattr(
        assignments_routes,
        "evaluate_submission_async",
        lambda *args, **kwargs: pytest.fail(
            "an expired assignment must not start evaluation"
        ),
    )

    response = client.post(
        f"/submit/{assignment_id}",
        data={"code": "int main() { return 0; }", "language": "cpp"},
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/view_assignment/{assignment_id}"
    )
    with app.app_context():
        assert Submission.query.count() == 0


def test_api_rejects_new_submission_after_deadline(queue_context):
    app, client, assignment_id = queue_context
    with app.app_context():
        assignment = db.session.get(Assignment, assignment_id)
        assignment.due_date = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

    response = client.post(
        "/api/submit",
        json={"assignment_id": assignment_id, "code": "int main(){}"},
    )

    assert response.status_code == 409
    assert response.json["message"] == "该作业已截止，不再接受新的提交"
    with app.app_context():
        assert Submission.query.count() == 0


def test_owned_submission_status_exposes_safe_queue_state(queue_context, monkeypatch):
    app, client, assignment_id = queue_context
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/1",
    )
    with app.app_context():
        submission = Submission(
            student_id="queue-student",
            assignment_id=assignment_id,
            code="int main(){}",
            status="pending",
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id

    monkeypatch.setattr(
        api_routes,
        "get_submission_job_status",
        lambda app_object, current_submission_id: "queued",
        raising=False,
    )

    response = client.get(f"/api/submissions/{submission_id}/status")

    assert response.status_code == 200
    assert response.json["status"] == "pending"
    assert response.json["queue_status"] == "queued"
    assert response.json["operation_id"] == f"submission-evaluation-{submission_id}"


@pytest.mark.parametrize("queue_state", ["failed", "expired"])
def test_pending_submission_stops_polling_on_terminal_queue_state(
    queue_context, monkeypatch, queue_state
):
    app, client, assignment_id = queue_context
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/1",
    )
    with app.app_context():
        submission = Submission(
            student_id="queue-student",
            assignment_id=assignment_id,
            code="int main(){}",
            status="pending",
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id

    monkeypatch.setattr(
        api_routes,
        "get_submission_job_status",
        lambda app_object, current_submission_id: queue_state,
        raising=False,
    )

    response = client.get(f"/api/submissions/{submission_id}/status")

    assert response.status_code == 200
    assert response.json["status"] == "failed"
    assert response.json["queue_status"] == queue_state
    with app.app_context():
        updated = db.session.get(Submission, submission_id)
        assert updated.status == "failed"
        assert updated.feedback


def test_student_cannot_read_another_students_submission_queue_state(queue_context):
    app, client, assignment_id = queue_context
    with app.app_context():
        other = User(
            student_id="other-student",
            username="other-student",
            usertype="学生",
        )
        other.password = "password"
        submission = Submission(
            student_id="other-student",
            assignment_id=assignment_id,
            code="int main(){}",
            status="pending",
        )
        db.session.add_all([other, submission])
        db.session.commit()
        submission_id = submission.id

    response = client.get(f"/api/submissions/{submission_id}/status")

    assert response.status_code == 403


def test_queue_unavailability_is_a_stable_submission_error(queue_context, monkeypatch):
    app, client, assignment_id = queue_context
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/1",
    )
    monkeypatch.setattr(
        api_routes,
        "evaluate_submission_async",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SubmissionQueueUnavailable("submission evaluation queue unavailable")
        ),
        raising=False,
    )

    response = client.post(
        "/api/submit",
        json={"assignment_id": assignment_id, "code": "int main(){}"},
    )

    assert response.status_code == 503
    assert response.json["message"] == "提交评测队列暂时不可用，请稍后重试"
    assert "isolated.invalid" not in response.get_data(as_text=True)


def test_ajax_submission_client_handles_queued_status():
    source = Path(__file__).parents[1].joinpath("static", "js", "code_submission.js").read_text(
        encoding="utf-8"
    )
    assert "data.data.status === \"queued\"" in source
    assert "api/submissions/${submissionId}/status" in source
    assert "评测任务已过期" in source
    assert "评测队列暂时不可用" in source
