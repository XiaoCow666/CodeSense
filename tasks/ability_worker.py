"""Standalone RQ worker for formal-account ability analysis.

Run this as a separate process from Gunicorn after configuring the RQ backend.
The worker deliberately disables argument-bearing job descriptions in logs.
"""

from __future__ import annotations

import os

from tasks.ability_queue import get_ability_queue


def build_worker(app):
    from rq import Worker
    from rq.serializers import JSONSerializer

    queue = get_ability_queue(app)
    return Worker(
        [queue],
        connection=queue.connection,
        serializer=JSONSerializer,
        log_job_description=False,
    )


def main() -> int:
    # This process owns only the durable RQ worker.  Do not also start the
    # legacy in-process task threads or preset scanner while building the app.
    config_name = os.environ.get("CODESENSE_CONFIG", "production")
    os.environ["FLASK_CONFIG"] = config_name
    os.environ["ASYNC_TASKS_ENABLED"] = "0"
    os.environ["PRESET_SCAN_ENABLED"] = "0"
    os.environ["ACCESS_LOG_ENABLED"] = "0"
    # app.py owns a module-level factory call.  Import and reuse that single
    # configured instance rather than constructing a second app/DB lifecycle.
    from app import app

    if app.config.get("ABILITY_ANALYSIS_QUEUE_BACKEND") != "rq":
        app.logger.error("ability worker requires ABILITY_ANALYSIS_QUEUE_BACKEND=rq")
        return 2

    worker = build_worker(app)
    with app.app_context():
        worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
