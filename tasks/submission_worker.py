"""Standalone RQ worker for formal-account submission evaluations."""

from __future__ import annotations

import os

from tasks.submission_queue import get_submission_queue


def build_worker(app):
    from rq import Worker
    from rq.serializers import JSONSerializer

    queue = get_submission_queue(app)
    return Worker(
        [queue],
        connection=queue.connection,
        serializer=JSONSerializer,
        log_job_description=False,
    )


def main() -> int:
    # This process owns only the durable submission worker.  Do not also start
    # the legacy in-process task threads or preset scanner while building app.
    config_name = os.environ.get("CODESENSE_CONFIG", "production")
    os.environ["FLASK_CONFIG"] = config_name
    os.environ["ASYNC_TASKS_ENABLED"] = "0"
    os.environ["PRESET_SCAN_ENABLED"] = "0"
    os.environ["ACCESS_LOG_ENABLED"] = "0"

    # app.py owns a module-level app instance; reuse it so DB/session setup is
    # not duplicated in the worker process.
    from app import app

    if app.config.get("SUBMISSION_EVALUATION_QUEUE_BACKEND") != "rq":
        app.logger.error(
            "submission worker requires SUBMISSION_EVALUATION_QUEUE_BACKEND=rq"
        )
        return 2

    worker = build_worker(app)
    with app.app_context():
        worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
