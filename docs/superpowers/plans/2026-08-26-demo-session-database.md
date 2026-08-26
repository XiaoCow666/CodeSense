# Per-Session Demo Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为公开学生/教师体验创建每会话独立的临时 SQLite 数据库，支持真实 AI 分析和完整交互，同时保证正式数据库零写入。

**Architecture:** 使用随机 `demo_run_id` 关联专用临时 SQLite 文件。请求进入时在当前 Flask-SQLAlchemy scoped session 上绑定该临时引擎，因此既有模型查询、关系和大部分路由继续工作；后台线程显式携带 run id 并重新绑定。公开入口只创建临时库，退出、超时和启动清理负责释放并删除临时库。

**Tech Stack:** Flask, Flask-Login, Flask-SQLAlchemy, SQLAlchemy SQLite engine/session, Flask-Session, existing `AIEvaluator`/`SharedLLMClient`, pytest/unittest, Chart.js.

**Spec:** `docs/superpowers/specs/2026-08-26-demo-session-database-design.md`

## Global Constraints

- 体验会话数据只能写入当前会话的临时 SQLite 数据库，正式数据库零写入。
- 真实 AI 个性化分析必须调用现有 AI 客户端；失败时显示失败状态，不伪造成功结果。
- 提交分数使用 0–5；知识点画像、五维能力和贝叶斯评估使用 0–100。
- 正常账号、正常提交、正常后台任务和 RBAC 行为保持兼容。
- 临时库必须在主动退出、空闲/最长生命周期清理和服务器启动清理后可删除。
- 不提交 `static/uploads/` 中与本任务无关的既有未跟踪文件。

---

### Task 1: 建立临时库生命周期服务

**Files:**
- Create: `services/demo_database.py`
- Modify: `models.py` only if an engine/session metadata helper is required
- Test: `tests/test_demo_database.py`

**Interfaces:**
- `create_demo_run(role: str) -> DemoRun`
- `activate_demo_run(run_id: str) -> bool`
- `current_demo_run_id() -> str | None`
- `destroy_demo_run(run_id: str) -> bool`
- `cleanup_expired_demo_runs(now: datetime | None = None) -> int`
- `is_demo_login_id(user_id: str) -> bool`
- `DemoRun` exposes `run_id`, `role`, `student_id`, `teacher_id`, `db_path`, `created_at`.

- [ ] **Step 1: Write the failing lifecycle tests.**

  Assert that `create_demo_run('student')` creates a unique path below the dedicated temporary directory, creates all model tables, and leaves the application database unchanged. Assert that two runs have different paths and that `destroy_demo_run` removes a run file without removing the other run.

- [ ] **Step 2: Run the lifecycle tests and confirm they fail because the service does not exist.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_database.py -q`

  Expected: collection/import failure for `services.demo_database` or missing lifecycle functions.

- [ ] **Step 3: Implement the isolated engine/session lifecycle.**

  Use `secrets.token_hex(24)` for run ids, create `codesense-demo-runs` below the OS temporary directory, validate resolved paths before opening/deleting, call `db.metadata.create_all(bind=engine)`, and keep only the signed run id/role in Flask session. Track last access and dispose engines before deletion. Never call `db.create_all()` or `db.session.commit()` against the application’s configured engine from the manager.

- [ ] **Step 4: Run the lifecycle tests and confirm they pass.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_database.py -q`

- [ ] **Step 5: Commit the isolated lifecycle service.**

  Run: `git add services/demo_database.py tests/test_demo_database.py docs/superpowers/specs/2026-08-26-demo-session-database-design.md docs/superpowers/plans/2026-08-26-demo-session-database.md; git commit -m "feat: add per-session demo database lifecycle"`

### Task 2: Bind Flask requests and Flask-Login to the temporary database

**Files:**
- Modify: `app.py:163-305`
- Modify: `routes/auth.py:20-125,284-305`
- Modify: `services/demo_database.py`
- Test: `tests/test_demo_session_binding.py`
- Modify: `tests/demo_test_utils.py` for cleanup of demo runs

**Interfaces:**
- `activate_demo_request_database() -> None` runs before any `current_user` access.
- `DemoPrincipal` wraps the temporary `User` row and returns `demo:<run_id>` from `get_id()` while delegating role/profile attributes.
- `login_demo_run(run: DemoRun) -> DemoPrincipal` creates the Flask-Login session without a formal user row.

- [ ] **Step 1: Write failing tests for request binding and authentication.**

  Login two test clients through `/demo-login/student`, assert their `demo_run_id` values differ, assert the loaded principals are students, and assert a query made during the demo request reads from the temporary database. Snapshot row counts and a representative record in the application database before and after login/navigation.

- [ ] **Step 2: Run the binding tests and confirm the expected failure.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_session_binding.py -q`

  Expected: the current fixed demo login either writes the application database or does not provide `demo_run_id`.

- [ ] **Step 3: Implement request-scoped binding and temporary principal loading.**

  At the start of `check_single_session`, activate the demo engine before reading `current_user`; obtain the scoped SQLAlchemy session and set its bind to the run engine. Extend the Flask-Login loader to resolve `demo:<run_id>` from the temporary database. Skip formal single-session DB invalidation for demo principals. On normal requests retain the configured bind and normal user loader unchanged.

- [ ] **Step 4: Replace public demo login/logout mutations.**

  Make `/demo-login/<role>` create a fresh run, seed it, log in the temporary principal, and redirect to the temporary assignment/home. Make logout destroy only the current demo run and avoid writing a formal `SystemLog`. If initialization fails, dispose/delete the new run and return to login without touching the application database.

- [ ] **Step 5: Run binding, login, and prior demo tests.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_session_binding.py tests/test_demo_login.py -q`

  Expected: both isolation and login suites pass; update old tests that assumed fixed rows in the formal database.

- [ ] **Step 6: Commit the authentication boundary.**

  Run: `git add app.py routes/auth.py services/demo_database.py tests/test_demo_session_binding.py tests/demo_test_utils.py tests/test_demo_login.py; git commit -m "feat: bind demo sessions to isolated database"`

### Task 3: Move fixture seeding into each temporary database

**Files:**
- Rewrite: `services/demo_experience.py`
- Modify: `routes/auth.py` to call the temporary seeder
- Test: `tests/test_demo_experience.py`
- Test: `tests/test_demo_database_isolation.py`

**Interfaces:**
- `seed_demo_experience(run: DemoRun) -> DemoExperience`
- `get_demo_assignment_id(run_id: str, key: str = 'guided_fibonacci') -> int`
- `is_demo_guided_assignment(assignment: Assignment) -> bool`
- `is_demo_guided_session(thinking_session: ThinkingSession) -> bool`

- [ ] **Step 1: Write failing fixture and cross-client isolation tests.**

  Assert that a new temporary database contains the two assignments, 13 knowledge points for the student, at least 10 historical submissions scored between 0 and 5, structured five-dimensional feedback, multiple temporary teacher students, and ready presets for both guided assignments. Assert that the application database has no rows with the old `demo_*` identifiers created by public login. Submit or update a record in client A and assert client B’s temporary database and the application database remain unchanged.

- [ ] **Step 2: Run the tests and observe failure from the fixed-ID formal seeder.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_experience.py tests/test_demo_database_isolation.py -q`

- [ ] **Step 3: Implement a transaction-safe temporary seeder.**

  Reuse the existing fixture content but replace `ensure_demo_experience()` formal-database upserts with inserts into the active temporary session. Use synthetic IDs only inside the temporary database. Seed score values such as `2.2`, `2.9`, `3.4`, `3.8`, `4.1`, and `4.6`; keep assignment totals/display metadata separate from submission scores. Populate all 13 C-language points and valid JSON feedback keys for algorithm/style/functionality/efficiency/readability.

- [ ] **Step 4: Add realistic teacher data in the temporary database.**

  Seed 10–12 student rows, six assignments, 25+ submissions spread over recent dates, class roster records, knowledge-point scores, a 14-day trend, and a teacher suggestion row. Keep all relationships inside the same temporary database and set the temporary teacher as the only manager.

- [ ] **Step 5: Run the fixture and isolation tests green.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_experience.py tests/test_demo_database_isolation.py -q`

- [ ] **Step 6: Commit the temporary fixture migration.**

  Run: `git add services/demo_experience.py routes/auth.py tests/test_demo_experience.py tests/test_demo_database_isolation.py; git commit -m "feat: seed demo fixtures per temporary session"`

### Task 4: Make asynchronous evaluation and real AI analysis demo-aware

**Files:**
- Modify: `tasks/submission_tasks.py:10-171`
- Modify: `tasks/ability_analysis.py:10-137`
- Modify: `utils/async_tasks.py` only where a demo run id must be forwarded
- Modify: `routes/assignments.py:484-577`
- Modify: `routes/api.py:230-325,997-1123`
- Modify: `routes/main.py:617-697` and teacher suggestion trigger paths
- Test: `tests/test_demo_ai_refresh.py`
- Test: `tests/test_demo_submission_isolation.py`

**Interfaces:**
- `evaluate_submission_async(app, submission_id, assignment_title, demo_run_id=None)`
- `generate_ability_analysis_async(app, student_id, demo_run_id=None)`
- `trigger_analysis_if_needed(student_id, force=False, demo_run_id=None)`
- Teacher suggestion async entry points accept `demo_run_id=None` and rebind before database work.

- [ ] **Step 1: Write failing tests for real-AI storage and refresh.**

  Use a test AI evaluator/client that records the submission payload and returns a distinct Markdown result for each call. Assert that the first demo analysis is generated from seeded history and stored in the temporary `AbilityTrend`, that a successful new submission marks it outdated and causes a second AI call, and that the result is not present in the application database. Assert that a failed AI call produces `failed` status in the temporary database without crashing the request.

- [ ] **Step 2: Run the AI tests and confirm the missing run-id propagation failure.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_ai_refresh.py tests/test_demo_submission_isolation.py -q`

- [ ] **Step 3: Forward run ids into background threads.**

  Capture the current demo run id at the request boundary, pass it from form/API submission and analysis/suggestion triggers, and call `activate_demo_run(run_id)` inside each worker’s own `app.app_context()`. When the run no longer exists, exit without querying or writing the formal database. Remove the existing demo-path fallback that returns a successful fake AI analysis; expose unavailable/failed status instead.

- [ ] **Step 4: Ensure every successful demo submission updates all temporary aggregates.**

  Keep the evaluator’s 0–5 score, update temporary user/assignment counts, knowledge-point scores, structured feedback and `AbilityTrend`, then launch the real AI analysis. Cover both the HTML form path and `/api/submit`; do not regress normal-account behavior.

- [ ] **Step 5: Run AI refresh and submission isolation tests green.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_ai_refresh.py tests/test_demo_submission_isolation.py -q`

- [ ] **Step 6: Commit demo-aware asynchronous work.**

  Run: `git add tasks/submission_tasks.py tasks/ability_analysis.py utils/async_tasks.py routes/assignments.py routes/api.py routes/main.py tests/test_demo_ai_refresh.py tests/test_demo_submission_isolation.py; git commit -m "feat: isolate demo evaluation and real AI analysis"`

### Task 5: Stabilize guided assignment two and keep quick jumps temporary

**Files:**
- Modify: `services/demo_experience.py`
- Modify: `routes/thinking.py:54-135,141-269,276-1362`
- Modify: `utils/thinking_ai.py` only for explicit demo preset regeneration behavior
- Modify: `static/js/thinking.js:38-69,1326-1390`
- Test: `tests/test_demo_guided_learning.py`

**Interfaces:**
- Demo arena and all guided APIs continue using their existing URLs, with their model operations transparently bound to the current temporary database.
- Demo preset generation returns `ready` from the temporary database for assignment one and two without queueing a formal-database task.

- [ ] **Step 1: Write failing tests for assignment two, stage persistence, and isolation.**

  Enter the second demo assignment with AI unavailable and assert the arena reports `ready`, starts a session, and accepts stage operations. Use the quick jump endpoint and assert only the current run’s `ThinkingSession` changes; a second client remains at the initial stage. Assert a completed guided run creates the expected temporary submission/analysis trigger without any formal rows.

- [ ] **Step 2: Run the guided tests and confirm assignment two currently fails or writes formal rows.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_guided_learning.py -q`

- [ ] **Step 3: Seed both guided presets in the temporary database and guard regeneration.**

  Put the assignment-two teaching preset into the temporary database with `ready` status. In demo requests, use the temporary preset and avoid `add_generate_preset_task` against the formal task manager. Keep the existing real AI generation path for normal assignments; if a demo user explicitly regenerates, run it synchronously in the temporary database.

- [ ] **Step 4: Complete guided learning in the temporary database.**

  Keep stage-one through stage-three logs, hints, code writes, fixes, completion state and the final 0–5 demonstration submission in the temporary session. Pass the run id into any post-completion AI refresh.

- [ ] **Step 5: Preserve the demo quick jump and remove the old sandbox assistant.**

  Keep four arena shortcuts for demo users, ensure local developer auto-actions remain local-only, and delete the layout-level right-bottom “沙箱体验助手” panel/form/role switcher. Add a visible temporary-data notice near the demo navigation.

- [ ] **Step 6: Run guided tests green and commit.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_guided_learning.py -q`

  Then: `git add services/demo_experience.py routes/thinking.py utils/thinking_ai.py static/js/thinking.js templates/layout.html tests/test_demo_guided_learning.py; git commit -m "fix: keep guided demo state temporary and stable"`

### Task 6: Correct student profile, score presentation, and teacher demo views

**Files:**
- Modify: `routes/main.py:46-290,554-697,813-885`
- Modify: `routes/users.py:159-263` where demo history/refresh needs explicit support
- Modify: `templates/student_home.html:413-520,796-844,846-1105`
- Modify: `templates/sprofile.html` and `templates/teacher_home.html`
- Modify: `templates/classes/class_list.html`, `templates/classes/class_detail.html`, `templates/teacher_ai_suggestions.html`
- Test: `tests/test_demo_profile_views.py`

**Interfaces:**
- Student recent submissions render `score / 5` and use thresholds 4.0/3.0.
- Knowledge profile renders all 13 points with score, attempts, accuracy and status.
- AI card shows `processing`, `completed`, `failed`, last updated time and refresh action.
- Teacher pages render temporary roster, assignment progress, trend and suggestion data without changing normal templates’ role checks.

- [ ] **Step 1: Write failing HTML/API tests for the requested presentation.**

  Login as a demo student and assert the home/profile pages contain 13 C-language knowledge points, `/5` recent scores that are all within 0–5, four Bayesian metrics and an AI status/result. Login as a demo teacher and assert the dashboard/class/assignment/suggestion pages contain multiple students, assignments, trend points and recommendations. Assert the old sandbox assistant text is absent while the arena quick-jump text remains.

- [ ] **Step 2: Run the view tests and confirm current output is incomplete/wrong.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_profile_views.py -q`

- [ ] **Step 3: Make student data-driven views render the complete profile.**

  Use the temporary model queries to provide all knowledge-point rows, valid dimension data and maturity components. Change recent submission badges and labels from 80/60 thresholds to 4.0/3.0 and display one decimal plus `/5`. Show the distinct 0–100 Bayesian metrics separately from submission score.

- [ ] **Step 4: Make the AI card refresh from real temporary trend state.**

  Keep the SSE contract, include a temporary analysis version/last-updated marker, and expose a refresh action that marks only the current temporary trend outdated and starts the real AI task. Do not cache demo analysis in the formal database.

- [ ] **Step 5: Fill teacher pages with temporary realistic data and safe mutations.**

  Ensure class list/detail, teacher assignment list/detail, trend and suggestion pages use the temporary session’s expanded fixture. Demo mutations such as editing/creating assignments or changing class data must commit to the active temporary session; ordinary users continue to use formal RBAC and formal database queries.

- [ ] **Step 6: Run profile view tests and commit.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_profile_views.py -q`

  Then: `git add routes/main.py routes/users.py templates/student_home.html templates/sprofile.html templates/teacher_home.html templates/classes templates/teacher_ai_suggestions.html tests/test_demo_profile_views.py; git commit -m "feat: complete isolated demo analytics views"`

### Task 7: Full regression, cleanup, and final verification

**Files:**
- Modify: `tests/demo_test_utils.py` and any focused tests needed for deterministic cleanup
- Modify: `README.md` with the temporary-database behavior and score-scale note

- [ ] **Step 1: Add the final formal-database snapshot test.**

  Capture counts and hashes for users, classes, rosters, assignments, submissions, knowledge scores, trends, suggestions, thinking sessions/logs and system logs. Run a complete student and teacher demo flow, logout both clients, and assert all formal snapshots match and all run files are gone.

- [ ] **Step 2: Run focused suites.**

  Run: `E:\anaconda\python.exe -m pytest tests/test_demo_database.py tests/test_demo_session_binding.py tests/test_demo_database_isolation.py tests/test_demo_ai_refresh.py tests/test_demo_submission_isolation.py tests/test_demo_guided_learning.py tests/test_demo_profile_views.py -q`

- [ ] **Step 3: Run the full test suite and static checks.**

  Run: `E:\anaconda\python.exe -m pytest tests -q`

  Run: `E:\anaconda\python.exe -m compileall -q services routes tasks tests`

  Run: `git diff --check`

- [ ] **Step 4: Inspect the final diff for formal-database writes in demo paths.**

  Search: `Select-String -Path app.py,routes\*.py,services\*.py,tasks\*.py -Pattern 'demo_run_id|activate_demo_run|db\.session|SystemLog'`

  Confirm every demo background operation activates the run before accessing models and no public demo path calls the legacy formal seeder.

- [ ] **Step 5: Commit documentation and final cleanup.**

  Run: `git add README.md tests/demo_test_utils.py tests; git commit -m "test: verify demo sessions never persist to formal database"`

- [ ] **Step 6: Report only freshly verified results.**

  Include the exact focused/full test counts, compile/diff-check results, temporary database lifecycle behavior, real-AI availability behavior, and note that no push or PR is performed without separate authorization.
