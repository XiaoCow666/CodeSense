# Knowledge Graph Stage One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a permission-scoped knowledge-graph projection that turns existing assignment knowledge and student mastery data into usable student and teacher learning paths without a new production schema or external vector service.

**Architecture:** Add one read-only `services/learning_graph.py` projection service over `AssignmentKnowledgePoint`, `KnowledgePointScore`, `Assignment`, `Class`, `User`, and existing access helpers. Student and teacher dashboard routes consume separate, privacy-safe projections and shared Jinja components render accessible cards/lists with direct links to existing assignments, Code Studio, classes, and student detail pages. The fused workspace changes remain in the candidate branch and are tested as part of the same integration baseline.

**Tech Stack:** Flask, Flask-SQLAlchemy, existing `utils.access` authorization helpers, Jinja templates, Bootstrap classes, pytest with isolated SQLite fixtures.

**Spec:** `docs/superpowers/specs/2026-09-17-knowledge-graph-stage1-design.md`

## Global Constraints

- Preserve the main worktree and its uncommitted changes; all work happens in the isolated candidate worktree based on `origin/main=52acab2`.
- Do not add a database migration, vector database, embedding provider, external dependency, or production schema change in this stage.
- `KnowledgePointScore` is private student data; teacher output is authorized class aggregation only.
- `co_occurs` is an inferred same-assignment relation and must never be labeled as a prerequisite.
- Keep score presentation on the fused candidate's canonical 0–100 scale and do not weaken existing tests.
- Every task ends with a focused test or static check before the next task.

---

### Task 1: Verify and record the fused workspace baseline

**Files:**
- Modify: `docs/ops-runs/2026-09-17-knowledge-graph-stage1.md`
- Test: `tests/test_question_bank_features.py`, `tests/test_teacher_analytics.py`, `tests/test_demo_experience.py`, `tests/test_student_home_history.py`

**Interfaces:**
- Consumes: the integrated candidate commit `019b77c`, existing pytest fixtures, and the main-worktree diff inventory.
- Produces: a baseline result that identifies score normalization, question-bank, teacher snapshot, and any unrelated failure before graph code is added.

- [ ] **Step 1: Run the focused fused baseline.**

Run:

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_question_bank_features.py tests/test_teacher_analytics.py tests/test_demo_experience.py tests/test_student_home_history.py -q --disable-warnings
```

Expected: the command either passes or produces a concrete failure list; do not modify tests to hide failures.

- [ ] **Step 2: Run import and syntax checks for the integrated files.**

Run:

```powershell
& E:\anaconda\envs\student-eval\python.exe -m compileall -q models.py routes services tasks utils tests
git diff --check
```

Expected: no compile or whitespace errors. Classify any pre-existing warning separately from failures.

- [ ] **Step 3: Record the baseline and changed-file disposition.**

Add to the run report a table with every main-worktree changed path grouped as `fused`, `repaired`, `deferred`, or `conflict-resolved`; include the focused test command and exact result.

- [ ] **Step 4: Commit the baseline report only.**

```powershell
git add -f docs/ops-runs/2026-09-17-knowledge-graph-stage1.md
git commit -m "docs: record graph stage integration baseline"
```

### Task 2: Add failing tests for the scoped graph projection

**Files:**
- Create: `tests/test_learning_graph.py`
- Test: `tests/test_learning_graph.py`

**Interfaces:**
- Consumes: existing model factories/fixtures and `utils.access` scope rules.
- Produces: executable contracts for `build_student_learning_graph` and `build_teacher_knowledge_coverage`.

- [ ] **Step 1: Write student graph tests.**

Create tests that seed two assignments with overlapping knowledge points, one student with a private score, and another student in a different class. Assert:

```python
graph = build_student_learning_graph(student_id="student-1", limit=8)
assert graph["meta"]["scope"] == "student"
assert {edge["relation_type"] for edge in graph["edges"]} >= {"covers", "mastery", "co_occurs"}
assert all(edge["scope"] == "student_assignments" for edge in graph["edges"])
assert "student-2" not in repr(graph)
assert all(node["id"].startswith(("assignment:", "knowledge:")) for node in graph["nodes"])
```

Also cover no assignments, no scores, duplicate knowledge points, a bounded limit, and an assignment outside the student's class.

- [ ] **Step 2: Write teacher aggregation and permission tests.**

Seed an authorized teacher with two students in one class and one student outside it. Assert that the response contains aggregate sample counts and average mastery, never a student id or individual score, excludes the outside class, marks low-sample concepts as insufficient, and rejects an inaccessible `class_id` with the service's access error.

- [ ] **Step 3: Run the new tests to verify they fail.**

Run:

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph.py -q --disable-warnings
```

Expected: FAIL because `services.learning_graph` and its functions do not exist yet.

### Task 3: Implement the bounded projection service

**Files:**
- Create: `services/learning_graph.py`
- Modify: `tests/test_learning_graph.py`

**Interfaces:**
- Consumes: `Assignment`, `AssignmentKnowledgePoint`, `Class`, `KnowledgePointScore`, `User`, `db`, `can_access_assignment`, `can_access_class`, `class_student_filter`, and `managed_classes`.
- Produces:
  - `build_student_learning_graph(*, student_id: str, assignment_id: int | None = None, limit: int = 8) -> dict`
  - `build_teacher_knowledge_coverage(*, viewer_id: str, class_id: int | None = None, limit: int = 8) -> dict`
  - `LearningGraphAccessError` for a valid target outside the viewer's scope.

- [ ] **Step 1: Implement normalization and bounded result helpers.**

Use stable ids `assignment:<id>` and `knowledge:<code>`. Return `nodes`, `edges`, `recommendations`, and `meta` for every successful empty or non-empty result. Cap assignments, concepts, edges, and recommendations using one public `limit` bound. Use the existing `KnowledgePointScore.KNOWLEDGE_POINTS` mapping for labels, falling back to the stored code.

- [ ] **Step 2: Implement student scope.**

Resolve the student, require an authenticated/self or authorized teacher/admin caller at the route boundary, select only assignments accepted by `can_access_assignment`, optionally validate `assignment_id`, and load only the selected assignment knowledge rows plus the requested student's own scores. Add `covers`, `mastery`, and same-assignment `co_occurs` edges; set `is_inferred=True` only on `co_occurs`. Add recommendations only for visible assignments/concepts, prioritizing missing/low mastery and linking by `assignment_id`.

- [ ] **Step 3: Implement teacher class aggregation.**

Resolve the viewer's managed classes with `managed_classes(viewer)`, validate an optional class id using `can_access_class`, select assignments by exact class targeting, and aggregate `KnowledgePointScore` only for students matching `class_student_filter`. Return `student_sample_size`, `assignment_count`, `average_mastery`, and `low_mastery_count` without student ids or individual scores. Mark `insufficient_sample` when the sample is below the defined threshold instead of calling it weak.

- [ ] **Step 4: Run the focused tests and fix only implementation defects.**

Run:

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph.py -q --disable-warnings
```

Expected: PASS with no changes to assertion strength.

- [ ] **Step 5: Commit the service and tests.**

```powershell
git add services/learning_graph.py tests/test_learning_graph.py
git commit -m "feat: add scoped learning graph projection"
```

### Task 4: Connect the projection to existing dashboard routes

**Files:**
- Modify: `routes/main.py:122-373` student `home`
- Modify: `routes/main.py:498-525` `teacher_dashboard`
- Test: `tests/test_learning_graph_routes.py`

**Interfaces:**
- Consumes: the two service functions from Task 3.
- Produces: `learning_graph` in the student-home context and `knowledge_coverage` in the teacher-dashboard context, with safe empty fallback if the projection has no data.

- [ ] **Step 1: Write route-context tests.**

Assert that a seeded student request to `/home` renders the graph context without exposing another student's id, and a seeded authorized teacher request renders class coverage. Add a permission test that a teacher managing class A cannot receive class B's concepts through the dashboard context.

- [ ] **Step 2: Run the route tests to verify the missing-context failure.**

Run:

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph_routes.py -q --disable-warnings
```

Expected: FAIL on the missing context variables or missing service call.

- [ ] **Step 3: Add route calls without changing existing dashboard queries.**

Call the student projection after existing assignment scope is known and the teacher aggregation after `build_teacher_dashboard_data`. Catch only `LearningGraphAccessError`/empty-data cases for a safe empty view; log unexpected exceptions with the existing request id and keep the old dashboard response available.

- [ ] **Step 4: Run route tests and existing dashboard tests.**

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph_routes.py tests/test_student_home_history.py tests/test_teacher_analytics.py -q --disable-warnings
```

Expected: PASS.

- [ ] **Step 5: Commit route integration.**

```powershell
git add routes/main.py tests/test_learning_graph_routes.py
git commit -m "feat: connect learning graph to dashboards"
```

### Task 5: Render accessible student and teacher learning paths

**Files:**
- Create: `templates/components/learning_graph.html`
- Create: `static/css/learning-graph.css`
- Modify: `templates/student_home.html`
- Modify: `templates/teacher_home.html`
- Test: `tests/test_learning_graph_ui.py`

**Interfaces:**
- Consumes: `learning_graph` and `knowledge_coverage` route context dictionaries.
- Produces: server-rendered, no-JavaScript-required learning path panels with assignment/class links and explicit empty/insufficient/inferred states.

- [ ] **Step 1: Write template contract tests.**

Assert the shared component contains `role="region"`, an accessible heading, explicit `共同出现推断` copy, empty and insufficient-sample copy, and links built with `url_for`. Assert the pages include the component and CSS; reject raw student ids and `innerHTML`/inline script dependencies.

- [ ] **Step 2: Run UI tests to verify the component is absent.**

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph_ui.py -q --disable-warnings
```

Expected: FAIL because the component and page includes do not exist.

- [ ] **Step 3: Implement the shared accessible component.**

Render compact cards/list rows rather than a decorative node canvas. Student rows show concept label, mastery state, relation explanation, and a direct assignment/Code Studio action. Teacher rows show aggregate sample size and average mastery, with a neutral “样本不足” state. Use text-safe Jinja output, visible focus states, responsive wrapping, and no new JavaScript.

- [ ] **Step 4: Mount it into the existing pages.**

Place the student panel after the existing knowledge profile summary and the teacher panel near the existing student snapshot/AI teaching summary. Include the CSS through each page's existing `extra_css` block. Do not duplicate the existing student snapshot table or replace the action-center layout.

- [ ] **Step 5: Run UI and route regression.**

```powershell
& E:\anaconda\envs\student-eval\python.exe -m pytest tests/test_learning_graph_ui.py tests/test_learning_graph_routes.py tests/test_session_lifecycle_ui.py -q --disable-warnings
node --check static/js/knowledge-quality.js
git diff --check
```

Expected: PASS; the graph panel must not add JavaScript errors because it is server-rendered.

- [ ] **Step 6: Commit the user-facing slice.**

```powershell
git add templates/components/learning_graph.html static/css/learning-graph.css templates/student_home.html templates/teacher_home.html tests/test_learning_graph_ui.py
git commit -m "feat: show student and teacher learning paths"
```

### Task 6: Perform real seeded walkthrough and release-readiness review

**Files:**
- Modify: `docs/ops-runs/2026-09-17-knowledge-graph-stage1.md`
- Test: full relevant pytest set, seeded demo route checks, manual browser or Flask-client walkthrough

**Interfaces:**
- Consumes: all candidate commits and seeded demo data.
- Produces: fusion disposition, actual user-path evidence, necessity decision, rollback note, and a keep/discard/blocked result.

- [ ] **Step 1: Run the relevant regression set.**

```powershell
$testFiles = @(git ls-files 'tests/*.py')
& E:\anaconda\envs\student-eval\python.exe -m pytest @testFiles -q --disable-warnings
& E:\anaconda\envs\student-eval\python.exe -m compileall -q app.py routes services utils tasks models.py tests
git diff --check
```

Expected: all tracked tests pass or unrelated baseline failures are explicitly classified; no graph-related failure may be hidden.

- [ ] **Step 2: Walk the student path.**

Use isolated seeded demo data, open the student home, verify the graph panel shows only the current student's mastery and assigned concepts, follow one assignment/Code Studio link, then check the no-data state with a student who has no score. Repeat at narrow viewport and with keyboard focus.

- [ ] **Step 3: Walk the teacher path.**

Open the authorized teacher dashboard, verify class coverage and sample-size language, follow one class/assignment link, then request an inaccessible class and confirm no data crosses the boundary. Check that the fused 0–100 student snapshot remains consistent with graph labels.

- [ ] **Step 4: Review the fusion and necessity.**

Record whether every main-worktree change is fused, repaired, deferred, or blocked; list any mixed score copy or duplicate query found and fixed. Decide whether this graph slice creates a useful next action. If it only creates another dashboard without a learning action, keep it local and do not publish.

- [ ] **Step 5: Commit the run report.**

```powershell
git add -f docs/ops-runs/2026-09-17-knowledge-graph-stage1.md
git commit -m "docs: record knowledge graph stage one verification"
```

- [ ] **Step 6: Stop at the correct gate.**

Only if tests, role walkthroughs, fusion review, and necessity review all pass may the candidate enter the established release/deploy flow. If the graph slice is useful but the fused uncommitted changes remain unsafe, keep the candidate as a reviewable branch and report the exact blocker; never call it production-ready.
