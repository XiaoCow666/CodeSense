from threading import Event

import fakeredis
import pytest
import redis
from rq import SimpleWorker
from rq.serializers import JSONSerializer

from app import create_app
from config import TestingConfig
from models import Assignment, Submission, SubmissionEvent, User, db
from routes import api as api_routes
from routes import assignments as assignments_routes
from tasks import ability_analysis, submission_queue, submission_tasks


CODE = "int main() { return 0; }"
REQUEST_ID = "resume-evaluation"


@pytest.fixture
def recovery_context(tmp_path, monkeypatch):
    database = (tmp_path / "dispatch_recovery.db").as_posix()
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database}")
    monkeypatch.setenv("SESSION_FILE_DIR", str(tmp_path / "sessions"))
    app = create_app("testing")
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "thread"
    with app.app_context():
        student = User(student_id="recovery-student", username="recovery-student", usertype="学生")
        student.password = "test-password"
        assignment = Assignment(title="提交恢复题", description="完成程序。", creator_id=student.student_id)
        db.session.add_all([student, assignment])
        db.session.commit()
        assignment_id = assignment.id

    client = app.test_client()
    login = client.post("/login", data={"username": "recovery-student", "password": "test-password"})
    assert login.status_code in {302, 303}
    attempt = client.post("/learning/attempts/ensure", json={"assignment_id": assignment_id})
    assert attempt.status_code == 200
    monkeypatch.setattr(ability_analysis, "trigger_analysis_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(submission_tasks, "refresh_student_learning_index", lambda _: {"revision": 1})
    monkeypatch.setattr(submission_tasks.code_evaluator, "get_last_structured_data", lambda: None)
    return app, client, assignment_id, attempt.json["attempt_id"]


def _exit_before_dispatch(*_args, **_kwargs):
    raise SystemExit("simulated exit after saving the submission")


def _assert_waiting_submission(app, attempt_id):
    with app.app_context():
        submission = Submission.query.one()
        assert submission.capture_request_id == REQUEST_ID
        assert submission.attempt_id == attempt_id
        assert submission.status == "pending"
        assert submission.code == CODE
        assert submission.code_version_id is not None
        events = SubmissionEvent.query.filter_by(submission_id=submission.id).order_by(SubmissionEvent.id)
        assert [(event.event_type, event.status) for event in events] == [
            ("submitted", "accepted"),
            ("evaluation_pending", "pending"),
        ]
        return submission.id


def _assert_evaluated_once(app, submission_id, evaluation_calls, *, finished_status):
    with app.app_context():
        submission = Submission.query.one()
        assert submission.id == submission_id
        assert submission.status == "evaluated"
        assert submission.score == 85
        events = SubmissionEvent.query.filter_by(submission_id=submission_id)
        assert events.filter_by(event_type="submitted").count() == 1
        assert events.filter_by(event_type="evaluation_pending").count() == 1
        assert events.filter_by(event_type="evaluation_started").one().status == "running"
        assert events.filter_by(event_type="evaluation_finished").one().status == finished_status
    assert evaluation_calls == [CODE]


def test_api_inline_retry_recovers_committed_submission(recovery_context, monkeypatch):
    app, client, assignment_id, attempt_id = recovery_context
    payload = {"assignment_id": assignment_id, "attempt_id": attempt_id, "code": CODE, "request_id": REQUEST_ID}
    evaluation_calls = []

    def evaluate(*, code_str, **_kwargs):
        evaluation_calls.append(code_str)
        return 85, "已评测"

    monkeypatch.setattr(api_routes, "evaluate_cpp_code", evaluate)
    with monkeypatch.context() as crash:
        crash.setattr(api_routes, "claim_submission_evaluation", _exit_before_dispatch)
        with pytest.raises(SystemExit, match="simulated exit"):
            client.post("/api/submit", json=payload)

    submission_id = _assert_waiting_submission(app, attempt_id)
    assert evaluation_calls == []
    for _ in range(2):
        response = client.post("/api/submit", json=payload)
        assert response.status_code == 200
        assert response.json["data"]["submission_id"] == submission_id
        assert response.json["data"]["status"] == "evaluated"
    _assert_evaluated_once(app, submission_id, evaluation_calls, finished_status="completed")


def test_api_rq_retry_recovers_and_enqueues_one_job(recovery_context, monkeypatch):
    app, client, assignment_id, attempt_id = recovery_context
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/0",
        SUBMISSION_EVALUATION_QUEUE_NAME="dispatch-recovery",
    )
    connection = fakeredis.FakeRedis()
    monkeypatch.setattr(redis, "from_url", lambda *_args, **_kwargs: connection)
    payload = {"assignment_id": assignment_id, "attempt_id": attempt_id, "code": CODE, "request_id": REQUEST_ID}
    evaluation_calls = []

    def evaluate(code, **_kwargs):
        evaluation_calls.append(code)
        return 85, "已评测"

    monkeypatch.setattr(submission_tasks, "evaluate_cpp_code", evaluate)
    monkeypatch.setattr(api_routes, "evaluate_cpp_code", lambda **_: pytest.fail("RQ must evaluate in the worker"))
    with monkeypatch.context() as crash:
        crash.setattr(api_routes, "evaluate_submission_async", _exit_before_dispatch)
        with pytest.raises(SystemExit, match="simulated exit"):
            client.post("/api/submit", json=payload)

    submission_id = _assert_waiting_submission(app, attempt_id)
    queue = submission_queue.get_submission_queue(app)
    assert queue.count == 0
    for _ in range(2):
        response = client.post("/api/submit", json=payload)
        assert response.status_code == 202
        assert response.json["data"]["submission_id"] == submission_id
        assert response.json["data"]["operation_id"] == f"submission-evaluation-{submission_id}"
    assert queue.count == 1
    assert evaluation_calls == []

    with app.app_context():
        worker = SimpleWorker([queue], connection=connection, serializer=JSONSerializer, log_job_description=False)
        assert worker.work(burst=True, logging_level="CRITICAL") is True
    replay = client.post("/api/submit", json=payload)
    assert replay.status_code == 200
    assert replay.json["data"]["submission_id"] == submission_id
    assert queue.count == 0
    _assert_evaluated_once(app, submission_id, evaluation_calls, finished_status="evaluated")


def test_web_form_retry_recovers_even_if_repeated_during_evaluation(recovery_context, monkeypatch):
    app, client, assignment_id, attempt_id = recovery_context
    url = f"/submit/{assignment_id}"
    payload = {"attempt_id": attempt_id, "capture_request_id": REQUEST_ID, "code": CODE, "language": "cpp"}
    workers = []
    evaluation_calls = []
    running = Event()
    release = Event()

    def evaluate(code, **_kwargs):
        evaluation_calls.append(code)
        running.set()
        assert release.wait(10), "evaluation did not receive the test's release signal"
        return 85, "已评测"

    def start_worker(*args, **kwargs):
        worker = submission_tasks.evaluate_submission_async(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(submission_tasks, "evaluate_cpp_code", evaluate)
    with monkeypatch.context() as crash:
        crash.setattr(assignments_routes, "evaluate_submission_async", _exit_before_dispatch)
        with pytest.raises(SystemExit, match="simulated exit"):
            client.post(url, data=payload)

    submission_id = _assert_waiting_submission(app, attempt_id)
    assert evaluation_calls == []
    monkeypatch.setattr(assignments_routes, "evaluate_submission_async", start_worker)
    try:
        first_replay = client.post(url, data=payload)
        assert first_replay.status_code == 302
        assert first_replay.location.endswith(f"/submission/{submission_id}/evaluating")
        assert running.wait(10), "replaying the form did not start evaluation"
        active_replay = client.post(url, data=payload)
        assert active_replay.status_code == 302
        assert active_replay.location == first_replay.location
    finally:
        release.set()
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive()

    completed_replay = client.post(url, data=payload)
    assert completed_replay.status_code == 302
    assert completed_replay.location == first_replay.location
    _assert_evaluated_once(app, submission_id, evaluation_calls, finished_status="evaluated")
