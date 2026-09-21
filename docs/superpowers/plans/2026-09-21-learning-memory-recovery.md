# 学生学习记忆索引恢复与来源治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让学生学习记忆索引在重复更新、构建失败、撤回来源过期和 AI 消费过程中保持可用、可解释且作用域受控。

**Architecture:** 继续使用现有 SQLAlchemy 学生向量表和索引状态表，使用事务保证一次构建的完整性；在服务层增加无变化短路、有界重试与 revoked 行的软过期治理。学生页面、学生 AI 回执、submission worker 和教师班级汇总共用同一状态来源，教师只接收聚合结果。

**Tech Stack:** Flask 2.3、Flask-SQLAlchemy、SQLAlchemy ORM、pytest、Jinja2、既有 JSON/SSE API。

**Spec:** `docs/superpowers/specs/2026-09-21-learning-memory-recovery-design.md`

## Global Constraints

- 不增加数据库迁移、外部向量服务、embedding provider 或新的生产队列。
- 只在当前学生作用域内构建和查询；教师只读取其管理班级的聚合状态。
- `active` 才能进入检索；`revoked` 与 `expired` 永久排除检索。
- 构建异常必须 rollback 并保留上一版 active 行；重试最多两次。
- 学习记忆只用于引导反思，不参与评分。
- 所有新生产行为先由失败测试证明缺口，再写最小实现。

---

### Task 1: 建立索引生命周期的红色测试

**Files:**
- Modify: `tests/test_student_vector_store.py`
- Modify: `tests/test_knowledge_rag.py`

**Interfaces:**
- Consumes: 现有 `seeded_student_vector_context`、`rebuild_student_vector_index`、`search_student_learning_vectors`、`project_student_learning_evidence`。
- Produces: 可证明无变化短路、软过期、失败后上一版可用、AI 回执状态字段的失败测试。

- [ ] **Step 1: Write the failing tests**

在 `tests/test_student_vector_store.py` 增加以下行为：

```python
def test_rebuild_keeps_revision_when_sources_are_unchanged(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        first = rebuild_student_vector_index(ids["student_one"])
        second = rebuild_student_vector_index(ids["student_one"])
        assert second["revision"] == first["revision"]


def test_rebuild_marks_old_revoked_rows_expired_without_querying_them(
    seeded_student_vector_context,
):
    app, ids = seeded_student_vector_context
    with app.app_context():
        rebuild_student_vector_index(ids["student_one"])
        revoke_student_vector_source(
            ids["student_one"], "submission_feedback", f"submission:{ids['submission_one']}"
        )
        row = StudentLearningVector.query.filter_by(
            student_id=ids["student_one"], source_type="submission_feedback"
        ).first()
        row.revoked_at = datetime.utcnow() - timedelta(days=31)
        db.session.commit()
        snapshot = rebuild_student_vector_index(ids["student_one"])
        result = search_student_learning_vectors(ids["student_one"], "递归边界")
        assert snapshot["expired_count"] >= 1
        assert result["status"] == "grounded"
        assert all(item.status != "expired" for item in result["evidence"])


def test_retry_entrypoint_retries_after_a_build_failure(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        calls = {"count": 0}

        class RetryEmbedder:
            def embed(self, text):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ValueError("transient embedding error")
                return {"递": 1.0}

        result = rebuild_student_vector_index_with_retry(
            ids["student_one"], embedder=RetryEmbedder(), max_attempts=2
        )
        assert result["status"] == "ready"
        assert calls["count"] >= 2
```

在 `tests/test_knowledge_rag.py` 增加一个失败状态检索投影测试，构造已有 revision 后把 `StudentVectorIndexState.status` 写为 `failed`，断言查询仍返回旧 evidence，投影包含 `index_status == "failed"` 和 `freshness_status == "previous_revision"`。

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_student_vector_store.py tests/test_knowledge_rag.py -q`

Expected: FAIL because the retry entrypoint, expired count, idempotent revision behavior and receipt status fields do not exist yet.

- [ ] **Step 3: Commit the red tests**

Run: `git add tests/test_student_vector_store.py tests/test_knowledge_rag.py && git commit -m "test: define learning memory recovery behavior"`

### Task 2: Implement transactional index recovery

**Files:**
- Modify: `services/student_vector_store.py`
- Modify: `tests/test_student_vector_store.py`

**Interfaces:**
- Consumes: existing source builders, `StudentVectorIndexState`, `StudentLearningVector`, `StudentVectorRebuildError`。
- Produces: `EXPIRED`、`REVOKED_SOURCE_RETENTION_DAYS`、`rebuild_student_vector_index_with_retry()`、snapshot `expired_count` and `has_usable_previous_revision`。

- [ ] **Step 1: Implement the minimum service behavior**

在 `services/student_vector_store.py` 中：

1. 增加 `EXPIRED = "expired"` 和三次以内的 `REBUILD_MAX_ATTEMPTS` 上限。
2. 在重建事务中把超过保留期限的 revoked 行标记为 expired，保留来源版本、撤回时间和撤回原因。
3. 将 `expired + user_revoked` 纳入重新构建时的禁止来源键集合。
4. 对来源键、状态可用、索引未陈旧且无过期状态变化的情况直接返回当前快照，不增加 revision。
5. 增加只捕获 `StudentVectorRebuildError` 的有界重试函数；最后一次失败继续抛出原错误。
6. 让快照返回 expired 数量和上一版是否可用；检索候选仍只来自 active 行。

- [ ] **Step 2: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_student_vector_store.py -q`

Expected: PASS for the lifecycle, scope, retry, stale and source governance cases.

- [ ] **Step 3: Commit the service change**

Run: `git add services/student_vector_store.py tests/test_student_vector_store.py && git commit -m "feat: recover student learning indexes safely"`

### Task 3: Carry recovery state into AI answers

**Files:**
- Modify: `services/student_vector_store.py`
- Modify: `tests/test_knowledge_rag.py`

**Interfaces:**
- Consumes: retrieval `metrics.index_status` and `metrics.freshness_status`。
- Produces: JSON/SSE evidence projection fields and readable receipt text for previous-revision fallback.

- [ ] **Step 1: Implement projection and receipt assertions**

Extend `project_student_learning_evidence()` with `index_status` and `freshness_status`. Extend `render_student_learning_receipt()` so a grounded result whose state is `failed` says that the previous usable version is being used and the student can retry from the home page. Preserve the existing response keys and SSE done event shape.

- [ ] **Step 2: Run the AI focused tests**

Run: `python -m pytest tests/test_knowledge_rag.py tests/test_code_advice_knowledge.py -q`

Expected: PASS with both JSON and SSE consumers retaining the original answer fields and receiving the new additive receipt fields.

- [ ] **Step 3: Commit the AI integration**

Run: `git add services/student_vector_store.py tests/test_knowledge_rag.py && git commit -m "feat: explain learning index recovery in AI receipts"`

### Task 4: Connect student update and submission paths

**Files:**
- Modify: `routes/main.py`
- Modify: `tasks/submission_tasks.py`
- Modify: `templates/components/student_learning_memory.html`
- Modify: `tests/test_student_vector_store.py`
- Modify: `tests/test_submission_worker.py`

**Interfaces:**
- Consumes: `rebuild_student_vector_index_with_retry()`。
- Produces: student home retry action, failure/expired state copy, and submission refresh using the same service entrypoint.

- [ ] **Step 1: Implement route, worker and template wiring**

Use the retry entrypoint in `rebuild_student_learning_memory()` and `refresh_student_learning_index()`. In the student panel, show expired source count, label expired sources as retained for audit and excluded from AI queries, and keep the update button keyboard accessible with `role=status`/`role=alert` state containers.

- [ ] **Step 2: Run route and worker tests**

Run: `python -m pytest tests/test_student_vector_store.py tests/test_submission_worker.py -q`

Expected: PASS, including the existing formal submission refresh and student source revoke paths.

- [ ] **Step 3: Commit the student workflow**

Run: `git add routes/main.py tasks/submission_tasks.py templates/components/student_learning_memory.html tests/test_student_vector_store.py tests/test_submission_worker.py && git commit -m "feat: connect learning index retry to student workflows"`

### Task 5: Add teacher aggregate learning-memory health

**Files:**
- Create: `services/student_vector_health.py`
- Modify: `routes/main.py`
- Modify: `templates/teacher_home.html`
- Create: `tests/test_student_vector_health.py`
- Modify: `tests/test_learning_graph.py`

**Interfaces:**
- Consumes: managed class membership, `StudentVectorIndexState` and `INDEX_STALE_AFTER_DAYS`。
- Produces: `build_teacher_learning_memory_health(teacher, now=None)` with only aggregate counts and a teacher dashboard panel.

- [ ] **Step 1: Write the failing service and route tests**

Create a fixture with two students in a managed class, one ready state, one failed state with a previous revision, and one student in an unmanaged class. Assert the result contains total, ready, stale, failed and not-built counts, while no student identifier or source identifier appears in the returned structure or rendered teacher page. Add an admin request check that the teacher-only aggregate does not appear on the admin home.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_student_vector_health.py tests/test_learning_graph.py -q`

Expected: FAIL because the service, dashboard context and panel do not exist.

- [ ] **Step 3: Implement the aggregate service and page**

Filter students by the teacher's managed classes before reading index states. Treat a recent ready state as ready, a ready or failed state older than the stale window as stale, a failed state with a revision as failed-with-previous, and missing state as not-built. Pass the result only to the teacher dashboard and render aggregate counts with a link to the existing knowledge coverage panel.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_student_vector_health.py tests/test_learning_graph.py -q`

Expected: PASS with no private source fields in the service result or HTML.

- [ ] **Step 5: Commit the teacher workflow**

Run: `git add services/student_vector_health.py routes/main.py templates/teacher_home.html tests/test_student_vector_health.py tests/test_learning_graph.py && git commit -m "feat: show teacher learning memory coverage"`

### Task 6: Full integration verification and release materials

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Create: `docs/ops-runs/2026-09-21-learning-memory-recovery.md`
- Create: `docs/assets/codesense-v1.8.0-learning-memory-recovery.png`

**Interfaces:**
- Consumes: completed student, AI and teacher workflows plus test evidence。
- Produces: user-facing v1.8.0 description and redacted internal run record.

- [ ] **Step 1: Run focused and full verification**

Run: `python -m pytest tests/test_student_vector_store.py tests/test_student_vector_health.py tests/test_knowledge_rag.py tests/test_code_advice_knowledge.py tests/test_learning_graph.py tests/test_submission_worker.py -q`, `python -m pytest -q`, `python -m compileall -q services routes tasks tests`, `node --check static/js/knowledge-evidence.js`, and `git diff --check`.

Expected: all affected tests and the full tracked suite exit with code 0; existing warning classes are recorded without suppressing them.

- [ ] **Step 2: Perform role and fusion checks**

Use Flask test clients with isolated databases for student, teacher and administrator paths. Check empty, failed, stale, revoked and expired states; verify JSON/SSE additive fields, worker refresh, teacher aggregation, unauthorized source access and absence of private identifiers. Check rendered HTML for keyboard form controls, status roles and narrow-width-safe text structure without using image inspection.

- [ ] **Step 3: Update release documents and run report**

Update README and CHANGELOG with v1.8.0 user benefits. Generate the required information graphic, inspect the generated result through the native media result, then record the final checksum, release link, deployment checks, rollback point and any unresolved visual or production gate in the redacted run report.

- [ ] **Step 4: Commit the release materials**

Run: `git add README.md CHANGELOG.md docs/assets/codesense-v1.8.0-learning-memory-recovery.png docs/ops-runs/2026-09-21-learning-memory-recovery.md && git commit -m "docs: record v1.8.0 learning memory recovery"`
