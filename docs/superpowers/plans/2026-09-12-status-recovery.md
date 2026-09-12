# 全站状态与恢复体验 v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, accessible recovery states across public errors, forms, teacher AI streaming, and student evaluation without schema or provider changes.

**Architecture:** Keep request correlation in Flask's existing request lifecycle, split HTML/API error rendering at the application boundary, and use the existing layout/SSE/template patterns for UI states. Dynamic AI content is sanitized at the browser boundary; all new tests use the existing temporary testing database and do not call real providers.

**Tech Stack:** Flask 3.1.x, Jinja2, existing Bootstrap/DOMPurify, vanilla JavaScript, pytest/unittest, Node syntax checks.

**Spec:** `docs/superpowers/specs/2026-09-12-status-recovery-design.md`

## Global Constraints

- No database schema, migration, model, provider, queue, session, permission, credential, or production-data changes.
- Generate request IDs server-side; never trust or echo a client-supplied correlation header.
- Keep HTML error messages generic; API errors must be stable JSON and preserve the HTTP status.
- Use the existing isolated worktree database/session/cache conventions; never copy `.env` or print secrets.
- Every production behavior change requires a failing test before implementation.

---

### Task 1: Correlated safe error responses

**Files:**
- Modify: `app.py`
- Create: `templates/404.html`
- Create: `templates/500.html`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces `X-Request-ID` on responses and stable HTML/JSON handlers for 404, 405, and 500.

- [ ] **Step 1: Write failing tests**

Add tests for `X-Request-ID`, HTML 404 recovery links, JSON `/api/` 404/405, and a non-debug 500 that never exposes the raised exception text.

- [ ] **Step 2: Run the focused tests**

Run: `py -3.13 -m pytest tests/test_app.py -q`

Expected: the new tests fail because no response header or custom handlers exist.

- [ ] **Step 3: Implement the smallest application boundary**

Use `g.codesense_request_id` in `after_request`, add a helper that selects JSON for `/api/` or JSON-only Accept headers, and register handlers that return explicit 404/405/500 status codes. Pass only the opaque request ID and safe navigation URLs to the templates.

- [ ] **Step 4: Re-run focused tests**

Run: `py -3.13 -m pytest tests/test_app.py -q`

Expected: all focused tests pass with the existing warnings only.

### Task 2: Favicon and shared shell semantics

**Files:**
- Create: `static/img/favicon.svg`
- Modify: `templates/layout.html`
- Modify: `templates/base.html`
- Modify: `static/modern.css`
- Create: `tests/test_status_recovery_ui.py`

**Interfaces:**
- Produces a local SVG favicon and consistent shell-level live-region/reduced-motion hooks.

- [ ] **Step 1: Write failing tests**

Assert the SVG is served with status 200, both shells link the SVG, the layout contains a global live region, toast roles remain explicit, and reduced-motion rules disable the shared spin/pulse animations.

- [ ] **Step 2: Run the focused UI tests**

Run: `py -3.13 -m pytest tests/test_status_recovery_ui.py -q`

Expected: the new asset/link/live-region assertions fail.

- [ ] **Step 3: Implement the asset and shell hooks**

Add a small brand SVG, update both favicon links, add `#codesense-live-region` and reduced-motion CSS. Keep external CDN dependencies and existing layout structure unchanged.

- [ ] **Step 4: Re-run focused UI tests**

Run: `py -3.13 -m pytest tests/test_status_recovery_ui.py -q`

Expected: all asset and shell assertions pass.

### Task 3: Keyboard-safe mobile navigation

**Files:**
- Modify: `templates/layout.html`
- Extend: `tests/test_status_recovery_ui.py`

**Interfaces:**
- Produces one close path for toggle, outside click, and Escape; closing restores focus to the menu button.

- [ ] **Step 1: Write failing static behavior tests**

Assert the layout script stores the previously focused element, handles `Escape`, sets `aria-expanded=false`, and calls `.focus()` when closing.

- [ ] **Step 2: Run the focused test**

Run: `py -3.13 -m pytest tests/test_status_recovery_ui.py -q`

Expected: the new script assertions fail.

- [ ] **Step 3: Implement the shared close function**

Refactor only the existing navigation script so all close paths update the icon/ARIA state and restore focus without trapping desktop navigation.

- [ ] **Step 4: Re-run the focused test and Node syntax check**

Run: `py -3.13 -m pytest tests/test_status_recovery_ui.py -q` and `node --check static/js/sse-client.js`

Expected: pass.

### Task 4: Feedback field errors and focus recovery

**Files:**
- Modify: `templates/feedback.html`
- Extend: `tests/test_feedback_center.py`

**Interfaces:**
- Produces per-field `aria-invalid`, field-level error descriptions, and a focusable error summary that receives focus after validation failure.

- [ ] **Step 1: Write failing tests**

Post invalid feedback data and assert the response contains `aria-invalid="true"`, an error ID referenced by `aria-describedby`, a field-level error, and a summary focus hook.

- [ ] **Step 2: Run feedback tests**

Run: `py -3.13 -m pytest tests/test_feedback_center.py -q`

Expected: the new accessibility assertions fail.

- [ ] **Step 3: Implement field-level semantics**

Keep the existing validation and summary, add stable IDs/classes to fields with errors, and add a small DOM-ready script that focuses the summary only when it exists. Do not alter payload validation limits.

- [ ] **Step 4: Re-run feedback tests**

Run: `py -3.13 -m pytest tests/test_feedback_center.py -q`

Expected: all feedback tests pass.

### Task 5: Teacher AI stream status and safe rendering

**Files:**
- Modify: `templates/teacher_ai_suggestions.html`
- Extend: `tests/test_teacher_ai_suggestions.py`
- Extend: `tests/test_status_recovery_ui.py`

**Interfaces:**
- Produces accessible busy/status states, focusable retry errors, preserved partial output, and sanitized dynamic report rendering.

- [ ] **Step 1: Write failing tests**

Assert the template has live/busy status attributes, an accessible retry control, a safe DOMPurify boundary, and an escaping helper for structured suggestion strings.

- [ ] **Step 2: Run focused tests**

Run: `py -3.13 -m pytest tests/test_teacher_ai_suggestions.py tests/test_status_recovery_ui.py -q`

Expected: the new template assertions fail.

- [ ] **Step 3: Implement minimal client-side changes**

Set `aria-busy` during streaming, announce success/failure through the global live region, replace the fallback `alert()` with a focusable alert node, sanitize Markdown through existing DOMPurify, and escape structured values before concatenating HTML.

- [ ] **Step 4: Re-run tests and syntax checks**

Run: `py -3.13 -m pytest tests/test_teacher_ai_suggestions.py tests/test_status_recovery_ui.py -q` and `node --check static/js/sse-client.js`

Expected: pass.

### Task 6: Student evaluation recovery controls

**Files:**
- Modify: `templates/submission_evaluating.html`
- Extend: `tests/test_submission_api_queue.py`
- Extend: `tests/test_status_recovery_ui.py`

**Interfaces:**
- Produces progressbar semantics, live status updates, manual status retry, and a submission-history escape route without a duplicate submit.

- [ ] **Step 1: Write failing tests**

Assert the waiting template has a labelled progressbar, `aria-live` status, a retry-status button, and a link to submission history.

- [ ] **Step 2: Run focused tests**

Run: `py -3.13 -m pytest tests/test_submission_api_queue.py tests/test_status_recovery_ui.py -q`

Expected: the new UI assertions fail.

- [ ] **Step 3: Implement bounded polling recovery**

Update progress ARIA values, show a retry button on timeout/API failure, reset the poll counter only for an explicit retry, and keep the existing result redirect and resubmit action.

- [ ] **Step 4: Re-run focused tests**

Run: `py -3.13 -m pytest tests/test_submission_api_queue.py tests/test_status_recovery_ui.py -q`

Expected: pass.

### Task 7: Research/report and integrated verification

**Files:**
- Create: `docs/ops-runs/2026-09-12-status-recovery-candidate.md`

- [ ] **Step 1: Record the candidate evidence**

Document the parent/candidate commits, the 12 independently verifiable delivery items, the research URLs and adaptation boundaries, changed files, tests, browser/static checks, release gate, rollback, and the server password-recovery blocker.

- [ ] **Step 2: Run complete verification**

Run: `py -3.13 -m pytest -q`, `py -3.13 -m compileall -q app.py forms.py models.py services routes tasks`, `node --check static/js/sse-client.js`, and `git diff --check`.

Expected: baseline and candidate both have zero test failures; warnings are classified, not hidden.

- [ ] **Step 3: Review the final diff**

Run: `git status --short --branch`, `git diff --stat origin/main...HEAD`, and inspect all changed templates/scripts for secret, schema, provider, or unescaped model-content changes.

Expected: only the documented candidate files are changed and the release decision is explicit.
