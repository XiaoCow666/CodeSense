# Request Correlation Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correlate one Flask request with its existing redacted LLM trace and access/slow-request log lines using a locally generated opaque request identifier.

**Architecture:** Generate a UUID at the start of every Flask request and store it only in Flask's request-local `g`. Add the identifier to the existing access/slow-request log line, and let `SharedLLMClient` use that request-local value only when a caller did not provide an explicit opaque request id. Non-Flask worker calls retain the existing per-call UUID behavior.

**Tech Stack:** Flask request context, Python `uuid`, existing `logging`, pytest, existing `SharedLLMClient` trace event.

**Spec:** `docs/PRD-local-optimization-backlog.md`, L1 “OpenTelemetry 风格的 AI 请求轨迹”.

## Global Constraints

- Do not record prompt, code, response, identity, credentials, or exception text in observability output.
- Do not change provider order, retry/backoff, cache, queue, database, Redis, session, upload, model-call count, UI, or schema behavior.
- Generate the id inside the application; do not trust or echo a user-supplied request id.
- Keep non-request-context worker and test calls compatible with the current random opaque id behavior.
- Validate with isolated worktree-local runtime directories and no `.env` reads or production database/Redis access.

---

### Task 1: Lock the request-correlation contract with tests

**Files:**
- Modify: `tests/test_llm_client.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `SharedLLMClient.chat`, Flask `g`, the testing app factory, and the existing `trace_records` helper.
- Produces: tests proving the request-local id is inherited by an LLM trace and included in the existing access-log line without leaking request data.

- [ ] **Step 1: Add the failing LLM request-context test**

Add a test that sets `g.codesense_request_id` inside `app.test_request_context`, invokes a fake `SharedLLMClient` without `request_id`, and asserts the emitted trace has exactly that opaque id. Keep the prompt private and assert it is absent from captured logs.

```python
def test_chat_trace_inherits_flask_request_id_without_logging_prompt(caplog):
    fake = FakeProviderClient(["请求内回答"])
    client = make_client({LLMProvider.ZHIPU: fake})
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    from flask import Flask, g

    app = Flask(__name__)
    with app.test_request_context("/private/path"):
        g.codesense_request_id = "11111111-1111-4111-8111-111111111111"
        assert client.chat(
            [{"role": "user", "content": "private prompt body"}],
            request_kind="stage3",
        ) == "请求内回答"

    trace = trace_records(caplog)[-1]
    assert trace["request_id"] == "11111111-1111-4111-8111-111111111111"
    assert "private prompt body" not in caplog.text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/test_llm_client.py::test_chat_trace_inherits_flask_request_id_without_logging_prompt -q`

Expected: FAIL because the current client creates a new UUID when no explicit `request_id` is supplied.

- [ ] **Step 3: Add the failing access-log assertion**

Add a Flask test route in `tests/test_app.py` only through the existing test app object, call it with the test client, and capture the `access` logger with a temporary handler. Assert the line contains the generated UUID-shaped request id and the path, while no request body is logged.

```python
def test_access_log_contains_opaque_request_id(self):
    import logging

    records = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    access_logger = logging.getLogger("access")
    access_logger.addHandler(handler)
    self.app.config["ACCESS_LOG_ENABLED"] = True
    try:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
    finally:
        access_logger.removeHandler(handler)

    self.assertTrue(records)
    self.assertRegex(records[-1], r"request_id=[0-9a-f-]{32,36}")
    self.assertIn('GET /healthz', records[-1])
```

- [ ] **Step 4: Run the focused app test and verify the new assertion fails**

Run: `python -m pytest tests/test_app.py::AppTestCase::test_access_log_contains_opaque_request_id -q`

Expected: FAIL because the current access-log format has no `request_id=` field.

### Task 2: Implement the minimal request-local correlation

**Files:**
- Modify: `app.py`
- Modify: `services/llm_client.py`

**Interfaces:**
- Consumes: Flask `g`, `uuid.uuid4`, the existing `start_request_timer`, `log_response_info`, `_trace_request_id`, `chat`, and `chat_stream` paths.
- Produces: `g.codesense_request_id` for the lifetime of a request and automatic inheritance by LLM traces without changing explicit caller ids.

- [ ] **Step 1: Generate an opaque id at request start**

Extend `start_request_timer` so it stores `str(uuid.uuid4())` in `g.codesense_request_id` before view code runs. Add `import uuid` beside the existing standard-library imports. Do not read `X-Request-ID` or any other client header.

- [ ] **Step 2: Include only the id in the existing access/slow-request line**

Extend the existing `line` string in `log_response_info` with `request_id=<g.codesense_request_id>`. Use a fallback UUID only if a test or unusual hook calls the after-request function without the start hook. Keep remote address, method, path, status, and duration semantics unchanged.

- [ ] **Step 3: Resolve an active Flask request id in the shared client**

Add a helper next to `_trace_request_id` that returns `g.codesense_request_id` only when `flask.has_request_context()` is true; catch import/context errors and return `None` outside Flask. Change both `chat` and `chat_stream` to call `_trace_request_id(request_id or _flask_request_id())`. Explicit caller ids keep their current precedence and worker calls still receive a fresh UUID.

```python
def _flask_request_id() -> Optional[str]:
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, "codesense_request_id", None)
    except (ImportError, RuntimeError):
        return None
    return None
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_llm_client.py::test_chat_trace_inherits_flask_request_id_without_logging_prompt tests/test_app.py::AppTestCase::test_access_log_contains_opaque_request_id -q`

Expected: 2 passed, with the trace id matching the request-local UUID and no prompt text in logs.

### Task 3: Regression, reviewer gates, and candidate report

**Files:**
- Create: `docs/ops-runs/2026-09-08-local-request-correlation-candidate.md`

**Interfaces:**
- Consumes: parent/candidate hashes, focused and full test output, public source URLs, and the release gate.
- Produces: a reproducible candidate report with baseline comparison, failure classification, rollback point, and `keep`/`needs_human` decision.

- [ ] **Step 1: Run the relevant regression set**

Run: `python -m pytest tests/test_llm_client.py tests/test_app.py tests/test_ai_sse_routes.py tests/test_sse.py tests/test_teacher_ai_suggestions.py -q`

Expected: exit code 0 and no new failures; classify any pre-existing environment collection failure separately.

- [ ] **Step 2: Run repository-wide static and formatting checks**

Run: `python -m compileall -q app.py services tests`; `git diff --check`; `node --check static/js/sse-client.js`

Expected: all commands exit 0.

- [ ] **Step 3: Run the full isolated evaluator**

Use a worktree-local seeded SQLite path, a distinct Redis DB or filesystem fallback, and worktree-local session/log/upload directories. Run: `python -m pytest -q`.

Expected: record exact pass/fail counts and duration; no test may resolve to the main checkout database or production services.

- [ ] **Step 4: Perform the two read-only reviewer checks**

Interaction Reviewer: inspect the diff and trace tests for prompt/code/response/identity/exception leakage, explicit-id precedence, and no model-call changes.

Test Reviewer: inspect the fresh command outputs, compare parent and candidate counts/durations, and verify `git diff --check` and compile checks.

- [ ] **Step 5: Write the candidate report and verify its claims**

Record parent commit, candidate diff hash, selected backlog item, public source URLs and status, assumptions, isolated runtime paths, commands/results, baseline comparison, failure categories, rollback (`git revert <candidate-commit>`), server health gate, release decision, and `stop_reason`. Do not claim release until the integration worktree, remote main, server commit, health checks, and eligible online-flow gate are freshly verified.

- [ ] **Step 6: Commit only the candidate diff after all checks**

Run: `git status --short`; `git diff --check`; `git add app.py services/llm_client.py tests/test_llm_client.py tests/test_app.py docs/ops-runs/2026-09-08-local-request-correlation-candidate.md docs/superpowers/plans/2026-09-08-request-correlation.md`; `git commit -m "feat: correlate request and LLM traces"`.

Expected: the commit contains only the planned observability code, tests, plan, and report; no `.env`, database, Redis, session, upload, log, or generated runtime files.
