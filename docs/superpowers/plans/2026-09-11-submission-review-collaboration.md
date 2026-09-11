# 提交复核协作 v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改数据库 schema 或模型调用的前提下，把提交详情扩展为学生—教师可追踪的复核协作闭环。

**Architecture:** 使用一个独立的 `submission_reviews` 服务解析版本化 `SystemLog` 事件，并以提交学生/所属班级教师/管理员作为唯一参与者。路由只负责权限和重定向，站内通知复用现有幂等适配器，模板在原提交详情上增加时间线与可行动表单；旧提交无事件时保持原行为。

**Tech Stack:** Flask 2.2、Flask-Login、Flask-SQLAlchemy、现有 `SystemLog` JSON 事件、Jinja2、Bootstrap/现有 CSS、pytest/unittest。

**Spec:** `docs/superpowers/specs/2026-09-11-submission-review-collaboration-design.md`

## Global Constraints

- 不新增数据库表、迁移、外部 provider、模型调用、权限主体或生产数据写入。
- 复核正文最多 2,000 字符；AI 反馈信号只保存最新值，不修改分数。
- 提交参与者只能是提交学生、所属班级教师和管理员；教师权限必须按 `class_id` 校验。
- 状态只允许 `requested → in_review → waiting_student → resolved` 的明确转换，越权和跳级返回可恢复错误。
- 保留 `E:\CodeSense\源代码` 主工作区及所有既有 worktree；所有候选修改只发生在本 worktree。

---

### Task 1: 建立复核事件服务与失败测试

**Files:**
- Create: `services/submission_reviews.py`
- Create: `tests/test_submission_review_collaboration.py`
- Modify: `docs/superpowers/specs/2026-09-11-submission-review-collaboration-design.md`

**Interfaces:**
- Produces `get_submission_review(submission_id)`, `create_review_request(submission, actor_id, body)`, `add_review_message(submission, actor, body)`, `transition_review(submission, actor, new_status)`, `list_review_queue(actor, status=None)`, `can_access_submission_review(submission, actor)` and `save_ai_feedback_signal(submission_id, actor_id, value)`.

- [ ] **Step 1: Write failing tests** for a student request, duplicate request reuse, invalid status transition, teacher class permission, message ordering and AI signal upsert.
- [ ] **Step 2: Run the new test file** with `py -3.13 -m pytest tests/test_submission_review_collaboration.py -q`; expect import/attribute failures because the service does not exist.
- [ ] **Step 3: Implement the minimal versioned JSON parser/writer** with bounded scans, UTC timestamps, actor checks and explicit transition tables. Store only the stated business event fields; never log prompt, code snapshot or exception text.
- [ ] **Step 4: Run the new test file** and confirm the service-level tests pass.
- [ ] **Step 5: Commit** with `git add services/submission_reviews.py tests/test_submission_review_collaboration.py docs/superpowers/specs/2026-09-11-submission-review-collaboration-design.md && git commit -m "feat: add submission review event service"`.

### Task 2: Wire student request and participant messages

**Files:**
- Modify: `routes/assignments.py`
- Modify: `routes/users.py`
- Modify: `templates/submission_detail.html`
- Modify: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes the service interfaces from Task 1.
- Produces the POST routes `/submission/<id>/review/request` and `/submission/<id>/review/message` and passes `review` to the submission detail template.

- [ ] **Step 1: Add failing route tests** for anonymous rejection, student request redirect, student reply, teacher reply, cross-class rejection and bounded body validation.
- [ ] **Step 2: Run only those route tests** and confirm they fail because the endpoints/template context are absent.
- [ ] **Step 3: Add permission-aware routes** beside `view_submission`, use `get_or_404` only after login, redirect back with a safe local target, and render the event timeline plus request/reply forms.
- [ ] **Step 4: Add the accessible review section** with a visible label, `maxlength`, helper text, `role="status"` flash area and no code/identity expansion.
- [ ] **Step 5: Run the route tests and the existing submission detail tests**; keep the original download/resubmit links unchanged.
- [ ] **Step 6: Commit** with `git add routes/assignments.py templates/submission_detail.html tests/test_submission_review_collaboration.py && git commit -m "feat: connect submission review conversation"`.

### Task 3: Add teacher queue and bounded status workflow

**Files:**
- Modify: `routes/assignments.py`
- Create: `templates/teacher_review_queue.html`
- Modify: `routes/main.py`
- Modify: `templates/teacher_home.html`
- Modify: `templates/layout.html`
- Modify: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes `list_review_queue` and `transition_review`.
- Produces `GET /teacher/reviews`, `POST /submission/<id>/review/status`, a dashboard count and a stable navigation entry for teacher/admin users.

- [ ] **Step 1: Add failing tests** for teacher-only queue visibility, admin all-access, status filters, status audit records and dashboard count.
- [ ] **Step 2: Run those tests** and verify the expected route/template failures.
- [ ] **Step 3: Implement queue query filtering** by managed class and status; ensure a teacher cannot infer another class's submission from queue HTML.
- [ ] **Step 4: Implement status POST** with only the transition table from the spec and preserve filter query parameters after redirect.
- [ ] **Step 5: Add an empty state, status labels, table headings and a dashboard link** without changing existing dashboard metrics.
- [ ] **Step 6: Run the queue/status tests and template rendering tests**.
- [ ] **Step 7: Commit** with `git add routes/assignments.py routes/main.py templates/teacher_review_queue.html templates/teacher_home.html templates/layout.html tests/test_submission_review_collaboration.py && git commit -m "feat: add teacher submission review queue"`.

### Task 4: Deliver participant notifications with idempotency

**Files:**
- Modify: `routes/assignments.py`
- Modify: `templates/notifications.html`
- Modify: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes existing `create_notification` and Task 1 event IDs.
- Produces request, reply and status-change notifications with local submission links and stable idempotency keys.

- [ ] **Step 1: Add failing tests** for request-to-teacher, teacher-reply-to-student, student-reply-to-teacher and duplicate request notification counts.
- [ ] **Step 2: Run the notification tests** and confirm no review notifications exist yet.
- [ ] **Step 3: Add a narrow notification helper** that resolves only the submission owner, class teacher and admin actor as appropriate; catch notification failures after the business event is committed.
- [ ] **Step 4: Add reason/status text** to notification cards while preserving ownership-safe read routes and existing filters.
- [ ] **Step 5: Run notification and existing notification/profile tests**.
- [ ] **Step 6: Commit** with `git add routes/assignments.py templates/notifications.html tests/test_submission_review_collaboration.py && git commit -m "feat: notify submission review participants"`.

### Task 5: Add AI-feedback signal and learning next action

**Files:**
- Modify: `routes/assignments.py`
- Modify: `templates/submission_detail.html`
- Modify: `templates/submission_history.html`
- Modify: `templates/submissions.html`
- Modify: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes `save_ai_feedback_signal` and `get_submission_review`.
- Produces `POST /submission/<id>/ai-feedback-signal`, current review status on student submission lists and a clear next-step prompt that never changes score or invokes AI.

- [ ] **Step 1: Add failing tests** for owner-only AI signal values, upsert behavior, non-owner rejection and list status rendering.
- [ ] **Step 2: Run the focused tests** and confirm the route is absent.
- [ ] **Step 3: Implement the signal route** with `helpful`/`needs_clarification` allowlist and a local redirect; render two labeled controls only when AI feedback exists.
- [ ] **Step 4: Add status/next-action badges** to student history/list rows with safe empty-state copy.
- [ ] **Step 5: Run focused, related and accessibility markup tests**.
- [ ] **Step 6: Commit** with `git add routes/assignments.py templates/submission_detail.html templates/submission_history.html templates/submissions.html tests/test_submission_review_collaboration.py && git commit -m "feat: capture actionable AI feedback signals"`.

### Task 6: Whole-flow verification and candidate report

**Files:**
- Modify: `static/modern.css`
- Modify: `templates/submission_detail.html`
- Modify: `templates/teacher_review_queue.html`
- Create: `docs/ops-runs/2026-09-11-local-submission-review-candidate.md`

- [ ] **Step 1: Add responsive/focus styles** for review timeline, status badges, textarea and queue table; keep focus visible and avoid hover-only meaning.
- [ ] **Step 2: Run Python compile, Node syntax, diff check and the full pytest suite** in serial order; record baseline/candidate counts and classify any pre-existing failures.
- [ ] **Step 3: Run a browser flow** on a temporary SQLite app: student request → teacher queue → teacher reply/status → student notification/reply → resolved/reopen → AI signal; inspect console errors and mobile layout.
- [ ] **Step 4: Review the diff for privacy, permission and duplicate-call regressions** and verify `rg` shows no model/LLM or external provider changes.
- [ ] **Step 5: Write the candidate report** with the 10+ independently verifiable items, user value, affected surfaces, changed files, research links, evidence, release decision, rollback and server dirty-worktree blocker.
- [ ] **Step 6: Commit** with `git add static/modern.css templates/submission_detail.html templates/teacher_review_queue.html docs/ops-runs/2026-09-11-local-submission-review-candidate.md && git commit -m "docs: record submission review candidate"`.

## Completion Checklist

- [ ] At least 10 independent items are named and each has an independent test or interaction checkpoint.
- [ ] Candidate worktree is clean and based on yesterday's tested candidate; main worktree remains untouched.
- [ ] All fresh verification evidence is recorded before any completion claim.
- [ ] No push/deploy occurs while the server retains uncommitted password recovery changes; report remains `needs_human` until a human reconciles that state.
