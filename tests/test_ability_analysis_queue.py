from datetime import datetime
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import pytest
import redis
from flask import Flask

from tasks.ability_queue import AbilityJobState, AbilityQueueUnavailable


def _app_config():
    return SimpleNamespace(
        config={
            "ABILITY_ANALYSIS_REDIS_URL": "redis://isolated.invalid:6399/0",
            "ABILITY_ANALYSIS_QUEUE_NAME": "test-ability-analysis",
            "ABILITY_ANALYSIS_JOB_TIMEOUT": 60,
            "ABILITY_ANALYSIS_QUEUE_TTL": 60,
            "ABILITY_ANALYSIS_RESULT_TTL": 120,
            "ABILITY_ANALYSIS_FAILURE_TTL": 300,
        }
    )


def test_rq_queue_persists_state_and_deduplicates_without_sensitive_arguments(monkeypatch):
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    from rq.job import Job
    from rq.serializers import JSONSerializer
    from tasks.ability_queue import enqueue_formal_ability_analysis

    app = _app_config()
    first = enqueue_formal_ability_analysis(app, trend_id=17)
    second = enqueue_formal_ability_analysis(app, trend_id=17)

    assert first == AbilityJobState("ability-analysis-17", "queued", True)
    assert second == AbilityJobState("ability-analysis-17", "queued", False)

    # A fresh Job object observes the Redis-persisted state.  Only the opaque
    # trend row id is serialized; descriptions / metadata stay low-cardinality.
    persisted = Job.fetch(
        first.operation_id,
        connection=connection,
        serializer=JSONSerializer,
    )
    assert persisted.func_name == "tasks.ability_analysis.run_formal_ability_analysis"
    assert persisted.args == [17]
    assert persisted.description == "formal ability analysis"
    assert persisted.meta == {
        "schema_version": 1,
        "request_kind": "ability_analysis",
    }
    assert persisted.retries_left is None


def test_rq_terminal_state_is_mapped_and_can_be_explicitly_requeued(monkeypatch):
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    from rq.job import Job, JobStatus
    from rq.serializers import JSONSerializer
    from tasks.ability_queue import (
        enqueue_formal_ability_analysis,
        get_ability_queue,
        get_formal_ability_job_status,
    )

    app = _app_config()
    first = enqueue_formal_ability_analysis(app, trend_id=23)
    queue = get_ability_queue(app)
    job = Job.fetch(
        first.operation_id,
        connection=connection,
        serializer=JSONSerializer,
    )
    queue.remove(job.id)
    job.set_status(JobStatus.FAILED)
    job.save()

    assert get_formal_ability_job_status(app, 23) == "failed"

    retried = enqueue_formal_ability_analysis(app, trend_id=23)
    assert retried == AbilityJobState("ability-analysis-23", "queued", True)


def test_fresh_worker_process_object_can_finish_a_persisted_job(monkeypatch):
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: connection)

    import tasks.ability_analysis as analysis
    from rq import SimpleWorker
    from rq.job import Job
    from rq.serializers import JSONSerializer
    from tasks.ability_queue import enqueue_formal_ability_analysis, get_ability_queue

    app = _app_config()
    state = enqueue_formal_ability_analysis(app, trend_id=29)
    queue = get_ability_queue(app)
    flask_app = Flask(__name__)
    trend = SimpleNamespace(student_id="student-private")

    with patch.object(
        analysis.db,
        "session",
        SimpleNamespace(get=lambda model, trend_id: trend),
    ), patch.object(analysis, "_run_analysis", return_value="completed") as run, \
            flask_app.app_context():
        # This worker object is created only after the web-side enqueue, which
        # verifies that execution does not depend on an in-process thread.
        worker = SimpleWorker(
            [queue],
            connection=connection,
            serializer=JSONSerializer,
            log_job_description=False,
        )
        assert worker.work(burst=True, logging_level="WARNING") is True

    persisted = Job.fetch(
        state.operation_id,
        connection=connection,
        serializer=JSONSerializer,
    )
    assert persisted.get_status(refresh=True).value == "finished"
    assert persisted.return_value() == "completed"
    run.assert_called_once_with("student-private", propagate_failure=True)


def test_formal_trigger_returns_after_enqueue_without_starting_provider_thread():
    import tasks.ability_analysis as analysis

    previous_updated = datetime(2026, 9, 4, 1, 2, 3)
    trend = SimpleNamespace(id=31, status="outdated", last_updated=previous_updated)
    fake_model = SimpleNamespace(
        query=SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(first=lambda: trend)
        ),
        get_or_create=lambda student_id: trend,
    )
    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"

    with app.app_context(), \
            patch.object(analysis, "AbilityTrend", fake_model), \
            patch(
                "tasks.ability_queue.enqueue_formal_ability_analysis",
                return_value=AbilityJobState("ability-analysis-31", "queued", True),
            ) as enqueue, \
            patch.object(
                analysis, "_mark_analysis_queued", return_value=True
            ) as mark_queued, \
            patch.object(analysis, "generate_ability_analysis_async") as legacy_thread:
        assert analysis.trigger_analysis_if_needed("student-private") is True

    enqueue.assert_called_once_with(app, 31)
    mark_queued.assert_called_once_with(
        31,
        previous_status="outdated",
        previous_updated=previous_updated,
    )
    legacy_thread.assert_not_called()


def test_stale_processing_job_becomes_failed_without_automatic_model_replay():
    import tasks.ability_analysis as analysis

    trend = SimpleNamespace(id=41, status="processing", last_updated=None)
    fake_model = SimpleNamespace(
        query=SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(first=lambda: trend)
        )
    )
    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"

    with app.app_context(), \
            patch.object(analysis, "AbilityTrend", fake_model), \
            patch(
                "tasks.ability_queue.get_formal_ability_job_status",
                return_value="failed",
            ), \
            patch.object(analysis, "_mark_analysis_failed") as mark_failed, \
            patch("tasks.ability_queue.enqueue_formal_ability_analysis") as enqueue:
        assert analysis.trigger_analysis_if_needed("student-private") is False

    mark_failed.assert_called_once_with("student-private")
    enqueue.assert_not_called()


def test_failed_analysis_requires_explicit_refresh_before_requeue():
    import tasks.ability_analysis as analysis

    previous_updated = datetime(2026, 9, 4, 2, 3, 4)
    trend = SimpleNamespace(id=47, status="failed", last_updated=previous_updated)
    fake_model = SimpleNamespace(
        query=SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(first=lambda: trend)
        )
    )
    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"

    with app.app_context(), \
            patch.object(analysis, "AbilityTrend", fake_model), \
            patch(
                "tasks.ability_queue.enqueue_formal_ability_analysis",
                return_value=AbilityJobState("ability-analysis-47", "queued", True),
            ) as enqueue, \
            patch.object(
                analysis, "_mark_analysis_queued", return_value=True
            ) as mark_queued:
        assert analysis.trigger_analysis_if_needed("student-private") is False
        assert analysis.trigger_analysis_if_needed(
            "student-private", force=True
        ) is True

    enqueue.assert_called_once_with(app, 47)
    mark_queued.assert_called_once_with(
        47,
        previous_status="failed",
        previous_updated=previous_updated,
    )


def test_completed_analysis_refresh_publishes_queued_state_with_version_guard():
    import tasks.ability_analysis as analysis

    previous_updated = datetime(2026, 9, 4, 3, 4, 5)
    trend = SimpleNamespace(
        id=59,
        status="completed",
        last_updated=previous_updated,
    )
    fake_model = SimpleNamespace(
        query=SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(first=lambda: trend)
        )
    )
    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"

    with app.app_context(), \
            patch.object(analysis, "AbilityTrend", fake_model), \
            patch(
                "tasks.ability_queue.enqueue_formal_ability_analysis",
                return_value=AbilityJobState("ability-analysis-59", "queued", True),
            ), patch.object(
                analysis, "_mark_analysis_queued", return_value=True
            ) as mark_queued:
        assert analysis.trigger_analysis_if_needed(
            "student-private", force=True
        ) is True

    mark_queued.assert_called_once_with(
        59,
        previous_status="completed",
        previous_updated=previous_updated,
    )


def test_queued_state_is_reserved_before_same_second_worker_completion():
    import tasks.ability_analysis as analysis
    from models import AbilityTrend, db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        db.create_all()
        previous_updated = datetime(2026, 9, 4, 4, 5, 6)
        trend = AbilityTrend(
            student_id="queue-guard-student",
            status="completed",
            last_updated=previous_updated,
        )
        db.session.add(trend)
        db.session.commit()

        analysis._mark_analysis_queued(
            trend.id,
            previous_status="completed",
            previous_updated=previous_updated,
        )
        db.session.refresh(trend)
        assert trend.status == "processing"

        # MySQL DATETIME may round both writes to the same second.  The queued
        # transition has already happened, so no post-enqueue write can turn
        # this real completion back into processing.
        worker_completed_at = previous_updated
        trend.status = "completed"
        trend.last_updated = worker_completed_at
        db.session.commit()
        db.session.refresh(trend)
        assert trend.status == "completed"
        assert trend.last_updated == worker_completed_at


def test_queue_state_reservation_happens_before_enqueue():
    import tasks.ability_analysis as analysis

    previous_updated = datetime(2026, 9, 4, 5, 6, 7)
    trend = SimpleNamespace(
        id=71,
        status="completed",
        last_updated=previous_updated,
    )
    fake_model = SimpleNamespace(
        query=SimpleNamespace(
            filter_by=lambda **kwargs: SimpleNamespace(first=lambda: trend)
        )
    )
    events = []
    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"

    def reserve(*args, **kwargs):
        events.append("reserve")
        return True

    def enqueue(*args, **kwargs):
        events.append("enqueue")
        return AbilityJobState("ability-analysis-71", "queued", True)

    with app.app_context(), patch.object(analysis, "AbilityTrend", fake_model), \
            patch.object(analysis, "_mark_analysis_queued", side_effect=reserve), \
            patch(
                "tasks.ability_queue.enqueue_formal_ability_analysis",
                side_effect=enqueue,
            ):
        assert analysis.trigger_analysis_if_needed(
            "student-private", force=True
        ) is True

    assert events == ["reserve", "enqueue"]


def test_worker_entry_reuses_single_module_app_and_forces_worker_only_flags(monkeypatch):
    import sys
    import tasks.ability_worker as worker_module

    app = Flask(__name__)
    app.config["ABILITY_ANALYSIS_QUEUE_BACKEND"] = "rq"
    fake_app_module = ModuleType("app")
    fake_app_module.app = app
    fake_worker = SimpleNamespace(work=lambda **kwargs: True)

    monkeypatch.setenv("CODESENSE_CONFIG", "testing")
    monkeypatch.setenv("ASYNC_TASKS_ENABLED", "1")
    monkeypatch.setenv("PRESET_SCAN_ENABLED", "1")
    monkeypatch.setenv("ACCESS_LOG_ENABLED", "1")
    with patch.dict(sys.modules, {"app": fake_app_module}), patch.object(
        worker_module, "build_worker", return_value=fake_worker
    ) as build:
        assert worker_module.main() == 0

    assert worker_module.os.environ["FLASK_CONFIG"] == "testing"
    assert worker_module.os.environ["ASYNC_TASKS_ENABLED"] == "0"
    assert worker_module.os.environ["PRESET_SCAN_ENABLED"] == "0"
    assert worker_module.os.environ["ACCESS_LOG_ENABLED"] == "0"
    build.assert_called_once_with(app)


def test_queue_adapter_never_exposes_raw_connection_errors():
    import tasks.ability_queue as queue_module

    raw_detail = "redis://user:secret@private-host:6379/9"
    with patch.object(
        queue_module,
        "_enqueue_formal_ability_analysis",
        side_effect=RuntimeError(raw_detail),
    ):
        with pytest.raises(AbilityQueueUnavailable) as exc_info:
            queue_module.enqueue_formal_ability_analysis(_app_config(), 61)

    assert str(exc_info.value) == "ability analysis queue unavailable"
    assert raw_detail not in str(exc_info.value)


def test_real_redis_connection_error_is_normalized(monkeypatch):
    import tasks.ability_queue as queue_module

    raw_detail = "redis://user:secret@private-host:6379/9"

    class BrokenConnection:
        def lock(self, *args, **kwargs):
            raise redis.ConnectionError(raw_detail)

    monkeypatch.setattr(
        queue_module,
        "get_ability_queue",
        lambda app: SimpleNamespace(connection=BrokenConnection()),
    )
    with pytest.raises(AbilityQueueUnavailable) as exc_info:
        queue_module.enqueue_formal_ability_analysis(_app_config(), 67)

    assert str(exc_info.value) == "ability analysis queue unavailable"
    assert raw_detail not in str(exc_info.value)

    with patch.object(
        queue_module,
        "_get_formal_ability_job_status",
        side_effect=RuntimeError(raw_detail),
    ):
        with pytest.raises(AbilityQueueUnavailable) as exc_info:
            queue_module.get_formal_ability_job_status(_app_config(), 61)

    assert str(exc_info.value) == "ability analysis queue unavailable"
    assert raw_detail not in str(exc_info.value)


def test_worker_resolves_opaque_trend_reference_inside_database_context():
    import tasks.ability_analysis as analysis

    trend = SimpleNamespace(student_id="student-private")
    with patch.object(
        analysis.db,
        "session",
        SimpleNamespace(get=lambda model, trend_id: trend),
    ), patch.object(analysis, "_run_analysis", return_value="completed") as run:
        assert analysis.run_formal_ability_analysis(53) == "completed"

    run.assert_called_once_with("student-private", propagate_failure=True)
