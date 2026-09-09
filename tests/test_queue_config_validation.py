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


def test_default_thread_backends_pass_validation():
    # The local development default: in-process threads, no Redis required.
    assert config.Config.init_app(_app()) is None


@pytest.mark.parametrize("backend_key", _BACKEND_KEYS)
def test_unknown_backend_value_is_rejected(backend_key):
    app = _app(**{backend_key: "redis"})
    with pytest.raises(RuntimeError, match="must be either thread or rq"):
        config.Config.init_app(app)


@pytest.mark.parametrize("backend_key,url_key", tuple(zip(_BACKEND_KEYS, _URL_KEYS)))
def test_rq_backend_without_redis_url_is_rejected(backend_key, url_key):
    app = _app(**{backend_key: "rq", url_key: ""})
    with pytest.raises(
        RuntimeError, match="is required when the RQ backend is enabled"
    ):
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
