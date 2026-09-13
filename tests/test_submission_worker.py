import inspect
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import fakeredis
import pytest
import redis
from flask import Flask

try:
    import tasks.submission_tasks as worker_tasks
    import tasks.submission_queue as submission_queue
    from tasks.submission_tasks import (
        run_formal_submission_evaluation,
        run_submission_evaluation,
    )
    import tasks.submission_worker as worker_module
    _IMPORT_ERROR = None
except ImportError as exc:  # Keep the RED phase as an assertion failure.
    worker_tasks = None
    submission_queue = None
    run_formal_submission_evaluation = None
    run_submission_evaluation = None
    worker_module = None
    _IMPORT_ERROR = str(exc)


def _require_worker_contract():
    assert worker_module is not None and run_formal_submission_evaluation is not None, (
        "submission worker contract is not available: " + str(_IMPORT_ERROR)
    )


def test_formal_worker_resolves_assignment_from_opaque_submission_id():
    _require_worker_contract()
    app = Flask(__name__)
    submission = SimpleNamespace(assignment_id=9, student_id="student-private")
    assignment = SimpleNamespace(title="循环题")
    fake_submission_model = object()
    fake_assignment_model = object()

    def get(model, value):
        if model is fake_submission_model:
            assert value == 17
            return submission
        if model is fake_assignment_model:
            assert value == 9
            return assignment
        raise AssertionError("unexpected model lookup")

    fake_db = SimpleNamespace(session=SimpleNamespace(get=get))
    with app.app_context(), \
            patch.object(worker_tasks, "db", fake_db), \
            patch.object(worker_tasks, "Submission", fake_submission_model), \
            patch.object(worker_tasks, "Assignment", fake_assignment_model), \
            patch.object(
                worker_tasks, "run_submission_evaluation", return_value="evaluated"
            ) as run:
        assert run_formal_submission_evaluation(17) == "evaluated"

    run.assert_called_once_with(app, 17, "循环题", None)
    assert list(inspect.signature(run_formal_submission_evaluation).parameters) == [
        "submission_id"
    ]


def test_worker_entry_disables_web_threads_and_preset_scanner(monkeypatch):
    _require_worker_contract()
    app = Flask(__name__)
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "rq"
    fake_app_module = ModuleType("app")
    fake_app_module.app = app
    fake_worker = SimpleNamespace(work=lambda **kwargs: True)
    monkeypatch.setenv("CODESENSE_CONFIG", "testing")
    monkeypatch.setenv("ASYNC_TASKS_ENABLED", "1")
    monkeypatch.setenv("PRESET_SCAN_ENABLED", "1")
    monkeypatch.setenv("ACCESS_LOG_ENABLED", "1")
    with patch.dict(sys.modules, {"app": fake_app_module}), \
            patch.object(
                worker_module, "build_worker", return_value=fake_worker
            ) as build:
        assert worker_module.main() == 0

    assert worker_module.os.environ["FLASK_CONFIG"] == "testing"
    assert worker_module.os.environ["ASYNC_TASKS_ENABLED"] == "0"
    assert worker_module.os.environ["PRESET_SCAN_ENABLED"] == "0"
    assert worker_module.os.environ["ACCESS_LOG_ENABLED"] == "0"
    build.assert_called_once_with(app)


def test_rq_backend_enqueues_without_starting_legacy_thread():
    _require_worker_contract()
    app = Flask(__name__)
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "rq"
    expected = SimpleNamespace(
        operation_id="submission-evaluation-17", status="queued", created=True
    )

    with patch.object(
        submission_queue,
        "enqueue_submission_evaluation",
        return_value=expected,
    ), patch.object(worker_tasks.threading, "Thread") as thread:
        result = worker_tasks.evaluate_submission_async(app, 17, "循环题")

    assert result is expected
    thread.assert_not_called()


def test_simple_worker_handles_slow_completion_and_persists_failure(monkeypatch):
    _require_worker_contract()
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)
    from rq import SimpleWorker
    from rq.job import Job
    from rq.serializers import JSONSerializer

    app = SimpleNamespace(
        config={
            "SUBMISSION_EVALUATION_REDIS_URL": "redis://isolated.invalid:6399/0",
            "SUBMISSION_EVALUATION_QUEUE_NAME": "worker-submission-evaluation",
            "SUBMISSION_EVALUATION_JOB_TIMEOUT": 60,
            "SUBMISSION_EVALUATION_QUEUE_TTL": 60,
            "SUBMISSION_EVALUATION_RESULT_TTL": 120,
            "SUBMISSION_EVALUATION_FAILURE_TTL": 300,
        }
    )

    with ThreadPoolExecutor(max_workers=12) as executor:
        states = list(
            executor.map(
                lambda _: submission_queue.enqueue_submission_evaluation(app, 41),
                range(12),
            )
        )

    assert len({state.operation_id for state in states}) == 1
    assert sum(state.created for state in states) == 1

    queue = submission_queue.get_submission_queue(app)
    calls = []

    def slow_completion(submission_id):
        calls.append(submission_id)
        time.sleep(0.05)
        return "evaluated"

    with patch.object(
        worker_tasks,
        "run_formal_submission_evaluation",
        side_effect=slow_completion,
    ):
        worker = SimpleWorker(
            [queue],
            connection=connection,
            serializer=JSONSerializer,
            log_job_description=False,
        )
        assert worker.work(burst=True, logging_level="CRITICAL") is True

    completed = Job.fetch(
        "submission-evaluation-41",
        connection=connection,
        serializer=JSONSerializer,
    )
    assert completed.get_status() == "finished"
    assert completed.return_value() == "evaluated"
    assert calls == [41]

    submission_queue.enqueue_submission_evaluation(app, 42)
    with patch.object(
        worker_tasks,
        "run_formal_submission_evaluation",
        side_effect=RuntimeError("provider timeout"),
    ):
        worker = SimpleWorker(
            [queue],
            connection=connection,
            serializer=JSONSerializer,
            log_job_description=False,
        )
        assert worker.work(burst=True, logging_level="CRITICAL") is True

    failed = Job.fetch(
        "submission-evaluation-42",
        connection=connection,
        serializer=JSONSerializer,
    )
    assert failed.get_status() == "failed"
    assert submission_queue.get_submission_job_status(app, 42) == "failed"


def test_formal_worker_updates_submission_in_isolated_database(tmp_path, monkeypatch):
    _require_worker_contract()
    from app import create_app
    from config import TestingConfig as _TestingConfig
    from models import Assignment, Submission, User, db
    import tasks.ability_analysis as ability_analysis

    database_path = tmp_path / "formal_submission_worker.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    monkeypatch.setattr(_TestingConfig, "ASYNC_TASKS_ENABLED", False)
    monkeypatch.setattr(_TestingConfig, "PRESET_SCAN_ENABLED", False)
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    app = create_app("testing")
    app.config.update(
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://isolated.invalid:6399/0",
        SUBMISSION_EVALUATION_QUEUE_NAME="formal-worker-integration",
        SUBMISSION_EVALUATION_JOB_TIMEOUT=60,
        SUBMISSION_EVALUATION_QUEUE_TTL=60,
        SUBMISSION_EVALUATION_RESULT_TTL=120,
        SUBMISSION_EVALUATION_FAILURE_TTL=300,
    )
    with app.app_context():
        db.create_all()
        student = User(
            student_id="worker-student",
            username="worker-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="worker integration",
            description="evaluate a small submission",
            creator_id="worker-student",
        )
        submission = Submission(
            student_id="worker-student",
            assignment=assignment,
            code="int main() { return 0; }",
            status="pending",
        )
        db.session.add_all([student, assignment, submission])
        db.session.commit()
        submission_id = submission.id

    monkeypatch.setattr(
        worker_tasks,
        "evaluate_cpp_code",
        lambda code, assignment_title=None: (80, "worker feedback"),
    )
    monkeypatch.setattr(
        ability_analysis,
        "trigger_analysis_if_needed",
        lambda *args, **kwargs: None,
    )
    state = submission_queue.enqueue_submission_evaluation(app, submission_id)
    queue = submission_queue.get_submission_queue(app)
    from rq import SimpleWorker
    from rq.serializers import JSONSerializer

    with app.app_context():
        worker = SimpleWorker(
            [queue],
            connection=connection,
            serializer=JSONSerializer,
            log_job_description=False,
        )
        assert worker.work(burst=True, logging_level="CRITICAL") is True
        updated = db.session.get(Submission, submission_id)
        assert updated.status == "evaluated"
        assert updated.score == 4

    assert submission_queue.get_submission_job_status(app, submission_id) == "completed"
    assert state.operation_id == f"submission-evaluation-{submission_id}"
