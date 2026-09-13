"""Durable queue adapter for formal-account submission evaluations.

Only the opaque ``Submission`` row id is persisted as a job argument.  Code,
student identity, prompts, and provider responses remain in the application
database or worker process and never enter queue metadata.
"""

from __future__ import annotations

from dataclasses import dataclass


QUEUE_SCHEMA_VERSION = 1
ACTIVE_STATUSES = {"created", "queued", "started", "deferred", "scheduled"}


class SubmissionQueueUnavailable(RuntimeError):
    """Raised when the durable submission queue cannot be used."""


@dataclass(frozen=True)
class SubmissionJobState:
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
        raise SubmissionQueueUnavailable(
            "RQ backend requires the pinned rq dependency"
        ) from exc
    return redis, Queue, NoSuchJobError, Job, JSONSerializer


def _redis_url(app) -> str:
    url = str(app.config.get("SUBMISSION_EVALUATION_REDIS_URL") or "").strip()
    if not url:
        raise SubmissionQueueUnavailable(
            "SUBMISSION_EVALUATION_REDIS_URL is required for the RQ backend"
        )
    return url


def get_submission_queue(app):
    """Build an RQ queue with JSON rather than pickle serialization."""

    redis, Queue, _, _, JSONSerializer = _rq_modules()
    connection = redis.from_url(
        _redis_url(app),
        socket_connect_timeout=1,
        socket_timeout=2,
    )
    return Queue(
        name=str(app.config.get(
            "SUBMISSION_EVALUATION_QUEUE_NAME", "submission-evaluation"
        )),
        connection=connection,
        serializer=JSONSerializer,
        default_timeout=int(app.config.get(
            "SUBMISSION_EVALUATION_JOB_TIMEOUT", 300
        )),
    )


def _operation_id(submission_id: int) -> str:
    return f"submission-evaluation-{int(submission_id)}"


def submission_operation_id(submission_id: int) -> str:
    """Return the stable public operation id for one submission."""

    return _operation_id(submission_id)


def _status_value(job) -> str:
    status = job.get_status(refresh=True)
    return getattr(status, "value", status)


def _public_status(status: str) -> str:
    if status == "finished":
        return "completed"
    if status in {"failed", "stopped", "canceled"}:
        return "failed"
    return status


def _enqueue_submission_evaluation(app, submission_id: int, *, force=False):
    _, _, NoSuchJobError, Job, JSONSerializer = _rq_modules()
    queue = get_submission_queue(app)
    submission_id = int(submission_id)
    operation_id = _operation_id(submission_id)
    lock = queue.connection.lock(
        f"codesense:submission-evaluation:enqueue:{submission_id}",
        timeout=5,
        blocking_timeout=5,
    )
    if not lock.acquire():
        raise SubmissionQueueUnavailable("submission evaluation enqueue is busy")

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
                return SubmissionJobState(operation_id, status, False)
            if not force:
                return SubmissionJobState(
                    operation_id, _public_status(status), False
                )
            existing.delete()

        try:
            job = queue.enqueue_call(
                "tasks.submission_tasks.run_formal_submission_evaluation",
                args=(submission_id,),
                timeout=int(app.config.get(
                    "SUBMISSION_EVALUATION_JOB_TIMEOUT", 300
                )),
                ttl=int(app.config.get(
                    "SUBMISSION_EVALUATION_QUEUE_TTL", 300
                )),
                result_ttl=int(app.config.get(
                    "SUBMISSION_EVALUATION_RESULT_TTL", 3600
                )),
                failure_ttl=int(app.config.get(
                    "SUBMISSION_EVALUATION_FAILURE_TTL", 86400
                )),
                description="formal submission evaluation",
                job_id=operation_id,
                meta={
                    "schema_version": QUEUE_SCHEMA_VERSION,
                    "request_kind": "submission_evaluation",
                },
                retry=None,
                unique=True,
            )
            return SubmissionJobState(operation_id, _status_value(job), True)
        except Exception as exc:
            # The unique job id is the final atomic guard against a race after
            # the advisory per-submission lock is released or expires.
            try:
                existing = Job.fetch(
                    operation_id,
                    connection=queue.connection,
                    serializer=JSONSerializer,
                )
            except NoSuchJobError:
                raise SubmissionQueueUnavailable(
                    "unable to enqueue submission evaluation"
                ) from exc
            status = _status_value(existing)
            if status not in ACTIVE_STATUSES:
                raise SubmissionQueueUnavailable(
                    "unable to enqueue submission evaluation"
                ) from exc
            return SubmissionJobState(operation_id, status, False)
    finally:
        try:
            lock.release()
        except Exception:
            # An expired lock must not turn a successful enqueue into a 500;
            # RQ's unique job id still protects the queue operation itself.
            pass


def enqueue_submission_evaluation(app, submission_id: int, *, force=False):
    """Enqueue one formal submission while hiding Redis/RQ details."""

    try:
        return _enqueue_submission_evaluation(app, submission_id, force=force)
    except SubmissionQueueUnavailable:
        raise
    except Exception:
        raise SubmissionQueueUnavailable(
            "submission evaluation queue unavailable"
        ) from None


def _get_submission_job_status(app, submission_id: int) -> str:
    _, _, NoSuchJobError, Job, JSONSerializer = _rq_modules()
    queue = get_submission_queue(app)
    try:
        job = Job.fetch(
            _operation_id(submission_id),
            connection=queue.connection,
            serializer=JSONSerializer,
        )
    except NoSuchJobError:
        return "expired"
    return _public_status(_status_value(job))


def get_submission_job_status(app, submission_id: int) -> str:
    """Return a stable status while hiding Redis/RQ exception details."""

    try:
        return _get_submission_job_status(app, submission_id)
    except SubmissionQueueUnavailable:
        raise
    except Exception:
        raise SubmissionQueueUnavailable(
            "submission evaluation queue unavailable"
        ) from None
