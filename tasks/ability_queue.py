"""Durable queue adapter for formal-account ability analysis jobs.

Only opaque ``AbilityTrend`` row ids are persisted as job arguments.  The
student id, submissions, prompts, and generated analysis stay in the
application database / worker process and are not copied into queue metadata
or job descriptions.
"""

from __future__ import annotations

from dataclasses import dataclass


QUEUE_SCHEMA_VERSION = 1
ACTIVE_STATUSES = {"created", "queued", "started", "deferred", "scheduled"}


class AbilityQueueUnavailable(RuntimeError):
    """Raised when the durable queue is enabled but cannot be used."""


@dataclass(frozen=True)
class AbilityJobState:
    operation_id: str
    status: str
    created: bool


def _rq_modules():
    try:
        import redis
        from rq import Queue
        from rq.exceptions import NoSuchJobError
        from rq.job import Job
        from rq.serializers import JSONSerializer
    except ImportError as exc:  # pragma: no cover - depends on deployment env
        raise AbilityQueueUnavailable(
            "RQ backend requires the pinned rq dependency"
        ) from exc
    return redis, Queue, NoSuchJobError, Job, JSONSerializer


def _redis_url(app) -> str:
    url = str(app.config.get("ABILITY_ANALYSIS_REDIS_URL") or "").strip()
    if not url:
        raise AbilityQueueUnavailable(
            "ABILITY_ANALYSIS_REDIS_URL is required for the RQ backend"
        )
    return url


def get_ability_queue(app):
    """Build an RQ queue using JSON rather than pickle serialization."""

    redis, Queue, _, _, JSONSerializer = _rq_modules()
    connection = redis.from_url(
        _redis_url(app),
        socket_connect_timeout=1,
        socket_timeout=2,
    )
    return Queue(
        name=str(app.config.get("ABILITY_ANALYSIS_QUEUE_NAME", "ability-analysis")),
        connection=connection,
        serializer=JSONSerializer,
        default_timeout=int(app.config.get("ABILITY_ANALYSIS_JOB_TIMEOUT", 180)),
    )


def _operation_id(trend_id: int) -> str:
    return f"ability-analysis-{int(trend_id)}"


def _status_value(job) -> str:
    status = job.get_status(refresh=True)
    return getattr(status, "value", status)


def _enqueue_formal_ability_analysis(app, trend_id: int) -> AbilityJobState:

    _, _, NoSuchJobError, Job, JSONSerializer = _rq_modules()
    queue = get_ability_queue(app)
    operation_id = _operation_id(trend_id)
    lock = queue.connection.lock(
        f"codesense:ability-analysis:enqueue:{int(trend_id)}",
        timeout=5,
        blocking_timeout=1,
    )
    if not lock.acquire():
        raise AbilityQueueUnavailable("ability analysis enqueue is busy")

    try:
        try:
            existing = Job.fetch(
                operation_id,
                connection=queue.connection,
                serializer=JSONSerializer,
            )
        except NoSuchJobError:
            existing = None

        if existing is not None:
            status = _status_value(existing)
            if status in ACTIVE_STATUSES:
                return AbilityJobState(operation_id, status, False)
            # Terminal records have a bounded TTL.  Delete one deliberately
            # under the Redis lock before a user-requested refresh.
            existing.delete()

        try:
            job = queue.enqueue_call(
                "tasks.ability_analysis.run_formal_ability_analysis",
                args=(int(trend_id),),
                timeout=int(app.config.get("ABILITY_ANALYSIS_JOB_TIMEOUT", 180)),
                ttl=int(app.config.get("ABILITY_ANALYSIS_QUEUE_TTL", 300)),
                result_ttl=int(app.config.get("ABILITY_ANALYSIS_RESULT_TTL", 3600)),
                failure_ttl=int(app.config.get("ABILITY_ANALYSIS_FAILURE_TTL", 86400)),
                description="formal ability analysis",
                job_id=operation_id,
                meta={
                    "schema_version": QUEUE_SCHEMA_VERSION,
                    "request_kind": "ability_analysis",
                },
                retry=None,
                unique=True,
            )
            return AbilityJobState(operation_id, _status_value(job), True)
        except Exception as exc:
            # RQ's unique insert remains the final atomic guard.
            try:
                existing = Job.fetch(
                    operation_id,
                    connection=queue.connection,
                    serializer=JSONSerializer,
                )
            except NoSuchJobError:
                raise AbilityQueueUnavailable(
                    "unable to enqueue ability analysis"
                ) from exc
            status = _status_value(existing)
            if status not in ACTIVE_STATUSES:
                raise AbilityQueueUnavailable(
                    "unable to enqueue ability analysis"
                ) from exc
            return AbilityJobState(operation_id, status, False)
    finally:
        try:
            lock.release()
        except Exception:
            # Expired locks must not turn a successful enqueue into a 500.  The
            # RQ unique job id still protects the queue operation itself.
            pass


def enqueue_formal_ability_analysis(app, trend_id: int) -> AbilityJobState:
    """Enqueue once while hiding connection details from request callers."""

    try:
        return _enqueue_formal_ability_analysis(app, trend_id)
    except AbilityQueueUnavailable:
        raise
    except Exception:
        raise AbilityQueueUnavailable("ability analysis queue unavailable") from None


def _get_formal_ability_job_status(app, trend_id: int) -> str:

    _, _, NoSuchJobError, Job, JSONSerializer = _rq_modules()
    queue = get_ability_queue(app)
    try:
        job = Job.fetch(
            _operation_id(trend_id),
            connection=queue.connection,
            serializer=JSONSerializer,
        )
    except NoSuchJobError:
        return "expired"

    status = _status_value(job)
    if status == "finished":
        return "completed"
    if status in {"failed", "stopped", "canceled"}:
        return "failed"
    return status


def get_formal_ability_job_status(app, trend_id: int) -> str:
    """Return a stable status while hiding Redis/RQ exception details."""

    try:
        return _get_formal_ability_job_status(app, trend_id)
    except AbilityQueueUnavailable:
        raise
    except Exception:
        raise AbilityQueueUnavailable("ability analysis queue unavailable") from None
