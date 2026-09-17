# RAG Evidence Recovery and Quality Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the Stage 13 RAG reliability surface so students see truthful recoverable evidence states, teachers/admins see bounded diagnostics, and admins can inspect process-local quality without privacy leakage.

**Architecture:** Keep the existing request-scoped RAG and safe projection boundary. Extend the fixed public status vocabulary and metrics, then reuse the existing evidence API for explicit retry links and the existing Code Studio renderer for dynamic retry. Add one admin-only read-only quality endpoint and a dashboard card backed by the already bounded in-process monitor.

**Tech Stack:** Flask blueprints, Jinja templates, vanilla JavaScript, existing knowledge services, pytest, Node syntax check.

**Spec:** `docs/superpowers/specs/2026-09-17-rag-evidence-recovery-design.md`

## Global Constraints

- No database schema, migration, Redis, queue, provider, dependency, or permission-boundary changes.
- Public evidence projection accepts only `grounded`, `no_result`, `unavailable`, `timeout`, `rate_limited`, and `unknown`.
- Student responses contain no teacher/admin diagnostics or process-wide quality counters.
- Retry is explicit and user-triggered; no polling loop or automatic request storm.
- Logs and quality endpoint contain fixed low-cardinality fields only; never query, code, answer, prompt, identity, or exception text.
- Preserve legacy `knowledge_retrieval` and rendered receipt response keys.

---

### Task 1: Lock the public reliability contract

**Files:**
- Modify: `services/knowledge_evidence.py`
- Test: `tests/test_knowledge_reliability.py`
- Test: `tests/test_knowledge_evidence_api.py`

**Interfaces:**
- Consumes: raw retrieval mappings from `services.knowledge_rag`.
- Produces: safe public retrieval and evidence-view mappings with six known statuses and bounded reliability metrics.

- [ ] **Step 1: Write the failing tests**

Add tests that pass raw `timeout` and `rate_limited` retrieval mappings through both `build_public_knowledge_retrieval()` and `build_knowledge_evidence_view()`, asserting the status, fallback code, retryable flag, and bounded metrics. Add a route-level assertion that a timeout response is not projected as `unknown`.

- [ ] **Step 2: Run the focused tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_reliability.py tests/test_knowledge_evidence_api.py -q --disable-warnings`

Expected: the existing timeout/rate-limit API assertions fail with `unknown`, and the new projection assertions fail because the states/fields are not yet allowed.

- [ ] **Step 3: Implement the minimal projection change**

Extend the fixed status/mode/copy tables. Map timeout and rate-limit fallback codes to bounded default messages. Add only the bounded reliability metrics to `build_public_knowledge_retrieval()`. Add `retryable` and `fallback_message` to the evidence view, with `retryable` true only for `unavailable`, `timeout`, and `rate_limited`.

- [ ] **Step 4: Run the focused tests to verify green**

Run the command from Step 2. Expected: all focused reliability/evidence API tests pass.

- [ ] **Step 5: Commit**

```powershell
git add services/knowledge_evidence.py tests/test_knowledge_reliability.py tests/test_knowledge_evidence_api.py
git commit -m "fix: preserve bounded rag fallback states"
```

### Task 2: Make ask-question evidence consistent in JSON and SSE

**Files:**
- Modify: `routes/api.py`
- Test: `tests/test_knowledge_rag.py`
- Test: `tests/test_knowledge_evidence_integration.py`

**Interfaces:**
- Consumes: `build_public_knowledge_retrieval()` and `build_knowledge_evidence_view()`.
- Produces: `data.knowledge_evidence` and top-level `knowledge_evidence` on JSON and SSE done responses.

- [ ] **Step 1: Write the failing tests**

Add assertions to the existing JSON and SSE ask-question tests that `knowledge_evidence.status` matches `knowledge_retrieval.status`, that the view is present both under `data` and at the done-event top level, and that a rate-limited response still has a truthful status.

- [ ] **Step 2: Run the tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_rag.py tests/test_knowledge_evidence_integration.py -q --disable-warnings`

Expected: the new structured-view assertions fail because ask-question currently emits only `knowledge_retrieval`.

- [ ] **Step 3: Implement the response projection**

Build a student evidence view once after the public retrieval projection. Add it to the non-stream JSON payload and to both `data` and top-level fields in the SSE done event. Keep the existing rendered receipt appended to `answer` for compatibility.

- [ ] **Step 4: Run the tests to verify green**

Run the command from Step 2. Expected: JSON/SSE evidence tests pass without changing the answer text contract.

- [ ] **Step 5: Commit**

```powershell
git add routes/api.py tests/test_knowledge_rag.py tests/test_knowledge_evidence_integration.py
git commit -m "feat: expose ask question evidence receipt"
```

### Task 3: Add explicit recovery links to server-rendered evidence panels

**Files:**
- Modify: `templates/components/knowledge_evidence.html`
- Modify: `templates/assignment_detail.html`
- Modify: `templates/submit_code.html`
- Modify: `static/css/knowledge-evidence.css`
- Test: `tests/test_knowledge_evidence_ui.py`

**Interfaces:**
- Consumes: `knowledge_evidence` view and the existing `/api/assignments/<id>/knowledge-evidence` GET route.
- Produces: keyboard-accessible retry link with truthful retry scope and no new write endpoint.

- [ ] **Step 1: Write the failing UI contract tests**

Assert that the macro accepts a retry URL, renders it only for retryable states, includes an accessible label, and that assignment/detail and submit templates pass the existing evidence API URL.

- [ ] **Step 2: Run the UI tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_evidence_ui.py -q --disable-warnings`

Expected: the retry URL/button assertions fail.

- [ ] **Step 3: Implement the macro and styles**

Add a bounded retry link below the recovery copy, use `rel` only when needed, keep the link out of grounded/no-result views, and add focus/mobile/reduced-motion styles. Pass `url_for('api.get_assignment_knowledge_evidence', assignment_id=assignment.id)` from the two existing templates.

- [ ] **Step 4: Run the UI tests to verify green**

Run the command from Step 2. Expected: all static UI contracts pass.

- [ ] **Step 5: Commit**

```powershell
git add templates/components/knowledge_evidence.html templates/assignment_detail.html templates/submit_code.html static/css/knowledge-evidence.css tests/test_knowledge_evidence_ui.py
git commit -m "feat: add recoverable knowledge evidence panels"
```

### Task 4: Add safe dynamic retry to Code Studio receipts

**Files:**
- Modify: `static/js/knowledge-evidence.js`
- Modify: `templates/submit_code.html`
- Test: `tests/test_knowledge_evidence_ui.py`

**Interfaces:**
- Consumes: structured `knowledge_evidence` view and a retry URL supplied by the Code Studio.
- Produces: safe DOM-only retry control that refreshes the existing evidence endpoint.

- [ ] **Step 1: Write the failing UI contract tests**

Assert the renderer exposes a `retryUrl`, uses `fetch` with GET and `no-store`, disables the retry control during the request, updates a live status, and continues to use `textContent`/`replaceChildren` without renderer `innerHTML`.

- [ ] **Step 2: Run the UI tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_evidence_ui.py -q --disable-warnings`

Expected: the retry-control assertions fail.

- [ ] **Step 3: Implement the minimal renderer extension**

Add a retry button only when `view.retryable` and `options.retryUrl` are true. On click, fetch the URL with `cache: 'no-store'`, parse the JSON envelope, call `render()` with the returned view while preserving the retry URL, and show a bounded failure message without clearing the existing receipt.

- [ ] **Step 4: Wire the Code Studio retry URL**

Pass `/api/assignments/{{ assignment.id }}/knowledge-evidence` from `renderKnowledgeReceipt()` and the analysis evidence render call. Do not pass the student question or code into the URL.

- [ ] **Step 5: Run syntax and UI tests**

Run: `node --check static/js/knowledge-evidence.js` and `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_evidence_ui.py -q --disable-warnings`. Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add static/js/knowledge-evidence.js templates/submit_code.html tests/test_knowledge_evidence_ui.py
git commit -m "feat: let code studio retry evidence safely"
```

### Task 5: Surface bounded teacher/admin diagnostics

**Files:**
- Modify: `services/knowledge_evidence.py`
- Modify: `templates/components/knowledge_evidence.html`
- Test: `tests/test_knowledge_evidence_api.py`
- Test: `tests/test_knowledge_evidence_ui.py`

**Interfaces:**
- Consumes: reliability metrics from the raw retrieval result.
- Produces: teacher/admin-only diagnostics for revision, privacy filtering, latency, citation completeness, and fallback state.

- [ ] **Step 1: Write failing projection/template tests**

Assert admin/teacher views contain the new bounded diagnostics while student views do not, and that the macro labels them as retrieval diagnostics rather than grading data.

- [ ] **Step 2: Run focused tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_evidence_api.py tests/test_knowledge_evidence_ui.py -q --disable-warnings`

Expected: new diagnostic assertions fail.

- [ ] **Step 3: Implement bounded diagnostics**

Add sanitized values to the existing teacher/admin diagnostics map and render them in a responsive grid. Keep source values capped by existing helpers and never include raw retrieval mappings.

- [ ] **Step 4: Verify green**

Run the command from Step 2. Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add services/knowledge_evidence.py templates/components/knowledge_evidence.html tests/test_knowledge_evidence_api.py tests/test_knowledge_evidence_ui.py
git commit -m "feat: show bounded rag diagnostics to educators"
```

### Task 6: Add the admin quality endpoint

**Files:**
- Modify: `routes/api.py`
- Modify: `services/knowledge_rag.py`
- Test: `tests/test_knowledge_quality_route.py`

**Interfaces:**
- Consumes: `get_knowledge_quality_snapshot()` and the existing `knowledge_rate_limiter` configuration.
- Produces: `GET /api/admin/knowledge-quality` with no-store bounded process metrics.

- [ ] **Step 1: Write the failing route tests**

Create an isolated admin/teacher/student fixture. Assert admin receives 200/no-store and fixed keys, teacher/student are denied, and serialized payload contains no query, answer, student ID, prompt, or exception text.

- [ ] **Step 2: Run the tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_quality_route.py -q --disable-warnings`

Expected: route returns 404 before implementation.

- [ ] **Step 3: Implement the endpoint**

Import `admin_required`, `get_knowledge_quality_snapshot`, and the process-local limiter/timeout configuration. Return `api_response(success=True, data={'quality': snapshot, 'limits': {...}})` through `_no_store`. Use fixed numeric limits and no environment/value echo.

- [ ] **Step 4: Verify green**

Run the command from Step 2. Expected: access and privacy tests pass.

- [ ] **Step 5: Commit**

```powershell
git add routes/api.py services/knowledge_rag.py tests/test_knowledge_quality_route.py
git commit -m "feat: add admin rag quality endpoint"
```

### Task 7: Add the admin dashboard quality card

**Files:**
- Modify: `templates/admin_dashboard.html`
- Create: `static/css/knowledge-quality.css`
- Create: `static/js/knowledge-quality.js`
- Test: `tests/test_knowledge_quality_route.py`

**Interfaces:**
- Consumes: `/api/admin/knowledge-quality`.
- Produces: keyboard-accessible admin card with loading, ready, empty, unavailable, and explicit refresh states.

- [ ] **Step 1: Write failing template/static tests**

Assert the dashboard includes the quality stylesheet/script, a labeled status region, a refresh button, and no student-facing template references.

- [ ] **Step 2: Run tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_quality_route.py -q --disable-warnings`

Expected: template assertions fail.

- [ ] **Step 3: Implement the dashboard card**

Add a compact card below system overview. The script loads the endpoint once on DOM ready and again only on button click; it renders fixed status counters and mean latency using text nodes/`textContent`, handles non-OK responses, and keeps a polite live status.

- [ ] **Step 4: Verify syntax and tests**

Run: `node --check static/js/knowledge-quality.js` and `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_quality_route.py -q --disable-warnings`. Expected: both pass.

- [ ] **Step 5: Commit**

```powershell
git add templates/admin_dashboard.html static/css/knowledge-quality.css static/js/knowledge-quality.js tests/test_knowledge_quality_route.py
git commit -m "feat: add admin rag quality card"
```

### Task 8: Enrich low-cardinality RAG logs and help content

**Files:**
- Modify: `routes/api.py`
- Modify: `templates/help.html`
- Test: `tests/test_knowledge_rag.py`
- Test: `tests/test_readme_setup.py`

**Interfaces:**
- Consumes: projected retrieval metrics and help navigation conventions.
- Produces: stable outcome log fields and a public explanation of evidence/fallback boundaries.

- [ ] **Step 1: Write failing log/content tests**

Assert logs contain fixed `timeout`/`rate_limited` outcome flags without query text, and help content explains evidence, answer-only fallback, and retry without promising a citation.

- [ ] **Step 2: Run tests to verify red**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_knowledge_rag.py tests/test_readme_setup.py -q --disable-warnings`

Expected: new log/content assertions fail.

- [ ] **Step 3: Implement logs and copy**

Extend the existing structured message with fixed status/fallback/revision/privacy fields. Add a short help section with plain-language states and an internal link to the feedback/help path already used by the site.

- [ ] **Step 4: Verify green**

Run the command from Step 2. Expected: focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add routes/api.py templates/help.html tests/test_knowledge_rag.py tests/test_readme_setup.py
git commit -m "docs: explain rag evidence recovery"
```

### Task 9: Regression, browser smoke, and release preparation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Create: `docs/ops-runs/2026-09-17-rag-evidence-recovery.md`
- Create: `docs/assets/codesense-v1.4.0-rag-evidence-recovery.png`

- [ ] **Step 1: Run the complete tracked regression**

Run: `E:\anaconda\envs\student-eval\python.exe -m pytest $(git ls-files 'tests/*.py') -q --disable-warnings` using a PowerShell-compatible file list if command substitution is unavailable. Record pass/fail classification without editing tests.

- [ ] **Step 2: Run static checks**

Run: `E:\anaconda\envs\student-eval\python.exe -m compileall -q services routes tests`, `node --check static/js/knowledge-evidence.js`, `node --check static/js/knowledge-quality.js`, and `git diff --check`.

- [ ] **Step 3: Run local interaction smoke**

Start the isolated app with a worktree-local database/session/log/upload directory, exercise student evidence status/retry, teacher diagnostics, and admin quality card, then stop the process. Check 390px layout and keyboard focus where the browser harness is available.

- [ ] **Step 4: Generate and inspect the versioned infographic**

Generate one readable `v1.4.0` user-facing infographic with the update theme, core changes, and role benefits; inspect it with the image viewer and include it in README/Release materials only after checking text, crop, and legibility.

- [ ] **Step 5: Write the internal run report**

Record research links, the twelve acceptance items, changed files, test classifications, review verdict, target commit, deployment gates, rollback, and remaining online risks. Keep user-facing copy separate from run evidence.

- [ ] **Step 6: Commit release preparation**

```powershell
git add README.md CHANGELOG.md docs/ops-runs/2026-09-17-rag-evidence-recovery.md docs/assets/codesense-v1.4.0-rag-evidence-recovery.png
git commit -m "docs: prepare v1.4.0 rag evidence release"
```

