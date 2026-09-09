"""Regression tests for external-queue configuration validation.

``Config.init_app`` runs at application startup (app.py calls it before
``db.init_app``) and must fail fast when an external (RQ) queue backend is
misconfigured:

* a backend value other than ``thread`` / ``rq`` is rejected;
* ``backend='rq'`` without a Redis URL is rejected (the worker cannot run
  without a broker).

These guards are pure in-process checks: they neither touch the database nor
open network connections, so a plain object exposing a ``config`` mapping is
enough to exercise them.
"""

import re
from types import SimpleNamespace

import pytest

import config

_BACKEND_KEYS = (
    "ABILITY_ANALYSIS_QUEUE_BACKEND",
    "SUBMISSION_EVALUATION_QUEUE_BACKEND",
)
_URL_KEYS = (
    "ABILITY_ANALYSIS_REDIS_URL",
    "SUBMISSION_EVALUATION_REDIS_URL",
)


def _app(**overrides):
    """Build an app-like object carrying validated config values."""
    values = {
        "ABILITY_ANALYSIS_QUEUE_BACKEND": "thread",
        "ABILITY_ANALYSIS_REDIS_URL": "",
        "SUBMISSION_EVALUATION_QUEUE_BACKEND": "thread",
        "SUBMISSION_EVALUATION_REDIS_URL": "",
    }
    values.update(overrides)
    return SimpleNamespace(config=values)


def test_explicit_thread_backends_pass_validation():
    # An explicit all-thread / empty-URL combination (as used for local
    # development) passes validation. This asserts the combination is accepted,
    # not the class-level defaults read from the environment at import time.
    assert config.Config.init_app(_app()) is None


@pytest.mark.parametrize("backend_key", _BACKEND_KEYS)
def test_unknown_backend_value_is_rejected(backend_key):
    app = _app(**{backend_key: "redis"})
    # The message must name the exact backend key that is invalid AND state the
    # allowed values, so a guard accidentally pointing at the other queue's
    # backend variable fails here instead of silently passing.
    with pytest.raises(
        RuntimeError,
        match=re.escape(backend_key) + r".*must be either thread or rq",
    ):
        config.Config.init_app(app)


@pytest.mark.parametrize("backend_key,url_key", tuple(zip(_BACKEND_KEYS, _URL_KEYS)))
def test_rq_backend_without_redis_url_is_rejected(backend_key, url_key):
    app = _app(**{backend_key: "rq", url_key: ""})
    # The message must name the exact missing URL variable AND state the reason,
    # so a future change that points the guard at the wrong queue's URL fails here.
    with pytest.raises(
        RuntimeError,
        match=re.escape(url_key) + r".*is required when the RQ backend is enabled",
    ):
        config.Config.init_app(app)


@pytest.mark.parametrize(
    "empty_url_key,filled_url_key,expected_url_name",
    (
        (
            "ABILITY_ANALYSIS_REDIS_URL",
            "SUBMISSION_EVALUATION_REDIS_URL",
            "ABILITY_ANALYSIS_REDIS_URL",
        ),
        (
            "SUBMISSION_EVALUATION_REDIS_URL",
            "ABILITY_ANALYSIS_REDIS_URL",
            "SUBMISSION_EVALUATION_REDIS_URL",
        ),
    ),
)
def test_rq_without_url_does_not_reuse_other_queue_url(
    empty_url_key, filled_url_key, expected_url_name
):
    # One queue runs on RQ with an empty URL while the other queue runs on RQ
    # with a valid URL. The empty-URL queue must still be rejected and must not
    # silently reuse the other queue's Redis URL. The error message must name
    # the queue whose URL is actually missing.
    app = _app(
        ABILITY_ANALYSIS_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        **{
            empty_url_key: "",
            filled_url_key: "redis://broker.example.invalid:6379/9",
        },
    )
    with pytest.raises(RuntimeError, match=expected_url_name):
        config.Config.init_app(app)


@pytest.mark.parametrize("backend_key,url_key", tuple(zip(_BACKEND_KEYS, _URL_KEYS)))
def test_rq_backend_with_redis_url_passes(backend_key, url_key):
    app = _app(
        **{
            backend_key: "rq",
            url_key: "redis://broker.example.invalid:6379/0",
        }
    )
    assert config.Config.init_app(app) is None


def test_both_queues_on_rq_with_urls_pass():
    app = _app(
        ABILITY_ANALYSIS_QUEUE_BACKEND="rq",
        ABILITY_ANALYSIS_REDIS_URL="redis://broker.example.invalid:6379/1",
        SUBMISSION_EVALUATION_QUEUE_BACKEND="rq",
        SUBMISSION_EVALUATION_REDIS_URL="redis://broker.example.invalid:6379/2",
    )
    assert config.Config.init_app(app) is None
