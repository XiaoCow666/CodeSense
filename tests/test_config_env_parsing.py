"""Regression tests for the environment parsing helpers in ``config.py``.

``_env_bool`` and ``_env_int`` parse every ``*_ENABLED`` / pool-size / TTL
environment variable listed in ``config.py``. They are documented to never
raise on bad operator input: malformed values fall back to the coded default
and out-of-range integers are clamped to the declared ``minimum`` /
``maximum`` instead of crashing startup.

These helpers depend on the standard library only (``os.environ``) and do not
build a Flask app, touch the database, or open sockets, so ``monkeypatch`` is
enough to exercise them deterministically.
"""

import pytest

import config


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("default", [False, True])
def test_env_bool_returns_default_when_unset(monkeypatch, default):
    monkeypatch.delenv("TEST_ENV_BOOL_UNSET", raising=False)
    assert config._env_bool("TEST_ENV_BOOL_UNSET", default) is default


@pytest.mark.parametrize(
    "raw",
    ["1", "true", "TRUE", "True", "yes", "y", "on", " true ", "YES"],
)
def test_env_bool_accepts_documented_true_values(monkeypatch, raw):
    # Comparison is case/whitespace insensitive after strip().lower().
    monkeypatch.setenv("TEST_ENV_BOOL", raw)
    assert config._env_bool("TEST_ENV_BOOL", False) is True


@pytest.mark.parametrize(
    "raw",
    ["0", "false", "no", "off", "", "   ", "maybe", "2"],
)
def test_env_bool_treats_other_values_as_false(monkeypatch, raw):
    # Any value outside the accepted set must be False rather than raise,
    # so a typo in an environment file degrades to the safe "off" state.
    monkeypatch.setenv("TEST_ENV_BOOL", raw)
    assert config._env_bool("TEST_ENV_BOOL", True) is False


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------

def test_env_int_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("TEST_ENV_INT_UNSET", raising=False)
    assert config._env_int("TEST_ENV_INT_UNSET", 42) == 42


def test_env_int_parses_valid_integer(monkeypatch):
    monkeypatch.setenv("TEST_ENV_INT", "300")
    assert config._env_int("TEST_ENV_INT", 10) == 300


@pytest.mark.parametrize("raw", ["not-a-number", "", "   ", "12abc"])
def test_env_int_falls_back_to_default_on_bad_input(monkeypatch, raw):
    # int() raises ValueError on these; the helper must swallow it and use
    # the default instead of aborting startup.
    monkeypatch.setenv("TEST_ENV_INT", raw)
    assert config._env_int("TEST_ENV_INT", 180, minimum=30, maximum=900) == 180


def test_env_int_clamps_below_minimum(monkeypatch):
    # Mirrors the *_QUEUE_TTL lower bound of 30 in config.py.
    monkeypatch.setenv("TEST_ENV_INT", "1")
    assert config._env_int("TEST_ENV_INT", 300, minimum=30, maximum=86400) == 30


def test_env_int_clamps_above_maximum(monkeypatch):
    # Mirrors the *_QUEUE_TTL upper bound of 86400 in config.py.
    monkeypatch.setenv("TEST_ENV_INT", "999999")
    assert config._env_int("TEST_ENV_INT", 300, minimum=30, maximum=86400) == 86400


@pytest.mark.parametrize("raw,expected", [("30", 30), ("86400", 86400)])
def test_env_int_keeps_values_exactly_at_bounds(monkeypatch, raw, expected):
    # Boundary values are inside (not outside) the allowed interval.
    monkeypatch.setenv("TEST_ENV_INT", raw)
    assert (
        config._env_int("TEST_ENV_INT", 300, minimum=30, maximum=86400)
        == expected
    )


def test_env_int_without_bounds_returns_parsed_value(monkeypatch):
    monkeypatch.setenv("TEST_ENV_INT", "-5")
    assert config._env_int("TEST_ENV_INT", 0) == -5


def test_env_int_clamps_default_that_violates_bounds(monkeypatch):
    # Documenting actual behavior: clamping runs after parsing, so it applies
    # to the fallback default as well when the variable is unset.
    monkeypatch.delenv("TEST_ENV_INT", raising=False)
    assert config._env_int("TEST_ENV_INT", 1, minimum=30, maximum=86400) == 30
