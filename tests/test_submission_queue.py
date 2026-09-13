from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import pytest
import redis

try:
    import tasks.submission_queue as submission_queue
    from tasks.submission_queue import (
        SubmissionJobState,
        SubmissionQueueUnavailable,
        enqueue_submission_evaluation,
        get_submission_job_status,
    )
    _IMPORT_ERROR = None
except ImportError as exc:  # Keep the RED phase as an assertion failure.
    submission_queue = None
    SubmissionJobState = None
    SubmissionQueueUnavailable = RuntimeError
    enqueue_submission_evaluation = None
    get_submission_job_status = None
    _IMPORT_ERROR = str(exc)


def _require_queue_contract():
    assert submission_queue is not None, (
        "submission queue contract is not available: " + str(_IMPORT_ERROR)
    )


def _app_config():
    return SimpleNamespace(
        config={
            "SUBMISSION_EVALUATION_REDIS_URL": "redis://isolated.invalid:6399/0",
            "SUBMISSION_EVALUATION_QUEUE_NAME": "test-submission-evaluation",
            "SUBMISSION_EVALUATION_JOB_TIMEOUT": 60,
            "SUBMISSION_EVALUATION_QUEUE_TTL": 60,
            "SUBMISSION_EVALUATION_RESULT_TTL": 120,
            "SUBMISSION_EVALUATION_FAILURE_TTL": 300,
        }
    )


def test_submission_queue_deduplicates_and_never_serializes_code(monkeypatch):
    _require_queue_contract()
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    from rq.job import Job
    from rq.serializers import JSONSerializer

    app = _app_config()
    first = enqueue_submission_evaluation(app, 17)
    second = enqueue_submission_evaluation(app, 17)

    assert first == SubmissionJobState("submission-evaluation-17", "queued", True)
    assert second == SubmissionJobState("submission-evaluation-17", "queued", False)
    job = Job.fetch(
        "submission-evaluation-17",
        connection=connection,
        serializer=JSONSerializer,
    )
    assert job.args == [17]
    assert "secret code" not in repr(job.args)
    assert job.description == "formal submission evaluation"
    assert job.meta == {
        "schema_version": 1,
        "request_kind": "submission_evaluation",
    }


def test_submission_queue_maps_terminal_and_expired_states(monkeypatch):
    _require_queue_contract()
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    from rq.job import Job
    from rq.serializers import JSONSerializer

    app = _app_config()
    state = enqueue_submission_evaluation(app, 23)
    job = Job.fetch(state.operation_id, connection=connection, serializer=JSONSerializer)

    job.set_status("finished")
    assert get_submission_job_status(app, 23) == "completed"
    job.delete()
    assert get_submission_job_status(app, 23) == "expired"


def test_submission_queue_hides_redis_connection_details(monkeypatch):
    _require_queue_contract()
    raw_detail = "redis://user:secret@private-host:6379/9"
    monkeypatch.setattr(
        submission_queue,
        "_enqueue_submission_evaluation",
        lambda app, submission_id: (_ for _ in ()).throw(RuntimeError(raw_detail)),
    )

    with pytest.raises(SubmissionQueueUnavailable) as exc_info:
        enqueue_submission_evaluation(_app_config(), 31)

    assert str(exc_info.value) == "submission evaluation queue unavailable"
    assert raw_detail not in str(exc_info.value)
