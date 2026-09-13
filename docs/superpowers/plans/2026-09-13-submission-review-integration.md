# 提交复核协作兼容集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已在隔离环境验证过的学生—教师提交复核协作闭环安全整合到最新 `origin/main`，并保留已部署的密码找回、截止时间和 sandbox 子进程修复。

**Architecture:** 复核事件和站内通知继续复用 `SystemLog` 的版本化 JSON，不新增表或迁移。`services/submission_reviews.py` 只负责状态、权限、事件和 AI 信号；路由负责当前用户边界与重定向；模板负责时间线、队列和可访问状态，外部邮件/SMS provider 不启用。

**Tech Stack:** Flask 3.x、SQLAlchemy、Jinja2、现有 `SystemLog`/SQLite 测试数据库、原生 JavaScript、CSS、pytest/unittest、Chromium 临时浏览器验收。

**Spec:** `docs/ops-runs/2026-09-13-submission-review-integration.md`（实施完成后写入本轮事实、研究和门禁证据）。

## Completion Record

- Tasks 1–9 completed: RED/GREEN cycles, integration, focused regression, full regression, static checks, browser acceptance, and the run report are complete.
- Task 10 Step 1 completed in this isolated worktree from the then-current `origin/main` (`b0f9450`). Steps 2–3 remain intentionally open: this session has no remote deployment connector, and the last known server record contains unrelated password-recovery/environment dirty work. See the run report for the exact `needs_human` gate and rollback path.

## Global Constraints

- 仅在 `E:\CodeSense\源代码\.worktrees\daily-review-inbox-20260913` 开发；不修改 `E:\CodeSense\源代码` 主工作区和其他 worktree。
- 不新增数据库表/字段/迁移，不改变评分、AI prompt、provider、队列、权限模型或生产数据。
- 复核事件正文最多 2,000 字符；事件必须带 `schema_version=1`，不得保存代码正文或 code snapshot。
- 通知只走本地 `SystemLog` fake/in-app adapter；不发送真实邮件、短信或 push。
- 所有新行为先由失败测试证明缺失，再写最小实现；保持 `origin/main` 的密码找回、注册验证、截止时间和 sandbox 修复。
- 发布前必须通过受影响测试、完整回归、`compileall`、Node 语法检查、`git diff --check`、浏览器流程和只读服务器健康门禁。

## File Map

- `services/notifications.py`: 版本化、用户归属、幂等、已读状态的本地通知适配器。
- `services/profile.py`: 公开资料 allowlist 的既有配套，不覆盖密码/身份服务。
- `services/submission_reviews.py`: 提交复核状态机、权限范围、事件时间线、队列摘要、AI 反馈信号。
- `routes/assignments.py`: 学生申请/回复、教师变更状态和复核队列路由。
- `routes/main.py`: 通知页面、教师仪表盘待处理数量、已有反馈/资料入口兼容。
- `routes/users.py`: 学生提交列表的复核摘要与安全范围。
- `templates/layout.html`, `templates/base.html`: 全局入口、通知入口、favicon 与页面结构。
- `templates/submission_detail.html`, `templates/submission_history.html`, `templates/submissions.html`: 学生复核时间线、状态和 AI 建议反馈。
- `templates/teacher_review_queue.html`, `templates/teacher_home.html`, `templates/notifications.html`: 教师队列、仪表盘入口和通知收件箱。
- `static/modern.css`, `static/img/favicon.svg`, `templates/student_home.html`, `app.py`: 移动布局、焦点/状态样式、favicon 与离开页面时取消 SSE。
- `tests/test_daily_submission_review_contract.py`: 本轮先写的最小 RED 合约测试。
- `tests/test_feedback_lifecycle_notifications_profile.py`, `tests/test_submission_review_collaboration.py`: 候选服务、路由、权限、通知、AI 信号和 UI 回归。
- `docs/ops-runs/2026-09-13-submission-review-integration.md`: 最终交付清单、研究链接、证据、发布和回滚记录。

### Task 1: 建立 RED 合约与候选基线

**Files:**
- Create: `tests/test_daily_submission_review_contract.py`
- Create: `docs/ops-runs/2026-09-13-submission-review-integration.md`

**Interfaces:**
- Consumes: 当前 `origin/main` 的 `/demo-login/teacher` 和测试 app 工具。
- Produces: 一个在当前主线明确失败、在集成后通过的教师复核队列入口合约。

- [ ] **Step 1: Write the failing test**

```python
def test_teacher_review_queue_is_available_after_integration(self):
    login = self.client.get('/demo-login/teacher')
    self.assertEqual(login.status_code, 302)
    response = self.client.get('/teacher/reviews')
    self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run the RED test and verify the failure is the missing route**

Run: `py -3.13 -m pytest tests/test_daily_submission_review_contract.py -q`

Expected: FAIL with a `404 != 200` assertion for `/teacher/reviews`, not a collection/import error.

- [ ] **Step 3: Commit the RED test and run metadata check**

Run: `git diff --check`

Expected: exit 0; do not add production implementation in this task.

### Task 2: Integrate local notification/profile foundation without losing auth

**Files:**
- Modify: `app.py`, `forms.py`, `routes/main.py`, `routes/users.py`, `services/feedback.py`
- Create: `services/notifications.py`, `services/profile.py`, `templates/notifications.html`, `templates/public_profile.html`
- Modify: `templates/layout.html`, `templates/admin_feedback.html`, `templates/edit_profile.html`, `templates/feedback_receipt.html`, `static/modern.css`
- Test: `tests/test_feedback_lifecycle_notifications_profile.py`

**Interfaces:**
- Consumes: existing `SystemLog`, `User`, feedback v1 and password-recovery routes.
- Produces: `create_notification`, `list_notifications`, `count_unread`, `mark_notification_read`, `mark_all_notifications_read`; notification page and opt-in public profile behavior.

- [ ] **Step 1: Apply only the retained feedback/notification/profile candidate changes after the RED test exists**

Run: `git merge --no-commit --no-ff codex/local-opt-20260910`

Resolve only overlap by keeping current `origin/main` password-recovery/email-verification files and the newer sandbox/deadline changes; do not accept candidate-side deletions of auth files. Stage only the intended files after review.

- [ ] **Step 2: Run the foundation tests**

Run: `py -3.13 -m pytest tests/test_feedback_center.py tests/test_feedback_lifecycle_notifications_profile.py -q`

Expected: all feedback lifecycle, ownership, notification and public-profile tests pass.

- [ ] **Step 3: Verify auth compatibility**

Run: `py -3.13 -m pytest tests/test_password_recovery.py tests/test_email_registration.py tests/test_account_basics.py -q`

Expected: existing login, registration verification and password recovery behavior remains green.

### Task 3: Integrate versioned review event service and state machine

**Files:**
- Create: `services/submission_reviews.py`
- Create/Modify: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: `Submission`, `Assignment`, `Class`, `User`, `SystemLog`, and `services.notifications.create_notification`.
- Produces: `create_review_request`, `get_submission_review`, `transition_review`, `add_review_message`, `list_review_queue`, `count_open_reviews`, `get_review_summaries`, `save_ai_feedback_signal`, `get_ai_feedback_signal` plus `ReviewPermissionError`, `ReviewStatusError`, `ReviewValidationError`.

- [ ] **Step 1: Bring in the review service tests and confirm RED**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -q`

Expected before implementation: collection succeeds after Task 2 and service/routing assertions fail because the review service and endpoints are absent.

- [ ] **Step 2: Add the minimal versioned event/state implementation**

The implementation must:

```python
REVIEW_STATUSES = ('requested', 'in_review', 'waiting_student', 'resolved')

create_review_request(submission, student_id, body) -> tuple[dict, bool]
transition_review(submission, actor, status, note='') -> tuple[dict, bool]
add_review_message(submission, actor, body) -> tuple[dict, bool]
```

Use a bounded per-submission write lock, database row locks on MySQL/PostgreSQL, SQLite process-lock fallback, strict participant/class/admin checks, and no code snapshot in persisted events.

- [ ] **Step 3: Run service-only tests GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "idempotent or status_machine or queue_is_scoped or ai_feedback_signal or stored_events" -q`

Expected: all selected service tests pass.

### Task 4: Connect student review conversation to submission detail

**Files:**
- Modify: `routes/assignments.py`
- Modify: `templates/submission_detail.html`
- Test: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: Task 3 service methods and existing `/view_submission/<submission_id>` authorization.
- Produces: `POST /submission/<int:submission_id>/review/request`, `POST /submission/<int:submission_id>/review/message`, and the student/teacher-safe review timeline.

- [ ] **Step 1: Run route assertions before route implementation**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "submission_review_routes" -q`

Expected: RED with missing endpoint/expected UI assertions.

- [ ] **Step 2: Implement the two POST routes**

Use `login_required`, submission ownership/class authorization from the service, POST/redirect/GET, bounded body validation, and flash/status feedback. Render event bodies through Jinja escaping; retain download and resubmit controls.

- [ ] **Step 3: Run the route test GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "submission_review_routes" -q`

Expected: pass, including anonymous redirect, outsider 403, oversized body rejection and one persisted message.

### Task 5: Add teacher queue, status actions and dashboard signal

**Files:**
- Modify: `routes/assignments.py`, `routes/main.py`, `templates/layout.html`, `templates/teacher_home.html`
- Create: `templates/teacher_review_queue.html`
- Test: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: `list_review_queue`, `count_open_reviews`, `transition_review`, `add_review_message`.
- Produces: `GET /teacher/reviews`, `POST /submission/<int:submission_id>/review/status`, and `open_review_count` in the teacher dashboard.

- [ ] **Step 1: Run queue/status assertions RED**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "teacher_review_queue" -q`

Expected: RED while the queue route and status action are absent.

- [ ] **Step 2: Implement scoped queue and status action**

Filter by `status` allowlist; teachers see only managed-class submissions, administrators see all, students cannot mutate status. Show only the next valid action for each row and preserve empty/filter states.

- [ ] **Step 3: Run queue/status tests GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "teacher_review_queue" -q`

Expected: pass for requested/in-review filters, dashboard count, cross-teacher isolation, admin visibility and student 403.

### Task 6: Wire participant-scoped local notifications

**Files:**
- Modify: `routes/assignments.py`, `services/submission_reviews.py`, `templates/notifications.html`, `routes/main.py`, `templates/layout.html`
- Test: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: notification adapter and review event identity.
- Produces: notifications for the other participant only, local detail URLs, idempotency keys, unread badge, read and mark-all-read actions.

- [ ] **Step 1: Run notification assertions RED**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "review_notifications" -q`

Expected: RED because review actions do not yet create participant notifications.

- [ ] **Step 2: Implement notification calls and inbox actions**

Use keys shaped as `submission-review:<review_id>:<event_id>:<recipient_id>`, never notify the actor, cap message length, require user ownership for read mutations, and keep external delivery disabled.

- [ ] **Step 3: Run notification tests GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "review_notifications" -q`

Expected: pass with no duplicate notification on repeated request and participant-only visibility.

### Task 7: Surface AI feedback signals and next action in student history

**Files:**
- Modify: `routes/assignments.py`, `routes/users.py`, `templates/submission_detail.html`, `templates/submission_history.html`, `templates/submissions.html`
- Test: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: `save_ai_feedback_signal`, `get_ai_feedback_signal`, `get_review_summaries`.
- Produces: `POST /submission/<int:submission_id>/ai-feedback-signal`, owner-only helpful/needs-clarification upsert, and scoped review summaries in student lists.

- [ ] **Step 1: Run AI/list assertions RED**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "ai_signal_route" -q`

Expected: RED because the signal route and list status are absent.

- [ ] **Step 2: Implement owner-only signal route and list joins**

Allow only `helpful` and `needs_clarification`; update one signal event for the owner; do not change `Submission.score`, call an LLM, or expose another student’s review body. When no review exists, preserve old list rendering.

- [ ] **Step 3: Run AI/list tests GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "ai_signal_route" -q`

Expected: pass for upsert, owner scope, unchanged score and next-action labels.

### Task 8: Finish shared layout, mobile, SSE and static quality

**Files:**
- Modify: `templates/base.html`, `templates/student_home.html`, `static/modern.css`, `static/img/favicon.svg`, `app.py`
- Modify: `templates/submission_detail.html`, `templates/teacher_review_queue.html`, `templates/submissions.html`
- Test: `tests/test_submission_review_collaboration.py`

**Interfaces:**
- Consumes: existing shared layout and SSE controller.
- Produces: visible labels/help text/live statuses, focusable controls, mobile-safe review controls, `/favicon.ico` SVG response, and `pagehide` abort for the ability stream.

- [ ] **Step 1: Run static/layout assertions RED**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "shared_pages" -q`

Expected: RED for missing favicon/SSE or review layout markers.

- [ ] **Step 2: Add the minimal accessible markup and styles**

Use visible `<label>` associations, `role="status"`/`aria-live` for async state, keyboard-visible focus, no hover-only action, bounded mobile grid/flex layout, and no new CDN/provider dependency.

- [ ] **Step 3: Run static/layout tests GREEN**

Run: `py -3.13 -m pytest tests/test_submission_review_collaboration.py -k "shared_pages" -q`

Expected: pass, including local SVG `GET /favicon.ico`.

### Task 9: Integration verification and evidence

**Files:**
- Modify: `docs/ops-runs/2026-09-13-submission-review-integration.md`

- [ ] **Step 1: Run affected regression**

Run: `py -3.13 -m pytest tests/test_feedback_center.py tests/test_feedback_lifecycle_notifications_profile.py tests/test_submission_review_collaboration.py tests/test_password_recovery.py tests/test_email_registration.py tests/test_submission_api_queue.py tests/test_teacher_analytics.py tests/test_student_home_history.py -q`

Expected: 0 failures; classify any pre-existing warning without suppressing it.

- [ ] **Step 2: Run full regression and static checks**

Run: `py -3.13 -m pytest -q`; `py -3.13 -m compileall -q app.py forms.py models.py services routes tasks`; `node --check static/js/sse-client.js`; `node --check static/js/browser-compatibility.js`; `git diff --check`

Expected: full suite has 0 failures; all static commands exit 0.

- [ ] **Step 3: Run browser acceptance in isolated temporary environment**

Exercise student request → teacher queue → in-review → teacher message → student reply/AI signal → resolved → student reopen → notification inbox, then check 390px width, no horizontal overflow, console errors and page errors.

Expected: every business assertion passes, no console/page errors, and temporary database/server/log/browser data is removed afterward.

- [ ] **Step 4: Write the report**

Record the 14 independent items, research URLs and adaptation boundaries, baseline/candidate commits, files, test counts, browser checks, release state, server read-only facts, rollback order and remaining SMTP/online-provider limitations. Do not claim production release before the online gate passes.

### Task 10: Qualified release or explicit needs-human handoff

**Files:**
- Modify: `docs/ops-runs/2026-09-13-submission-review-integration.md`

- [ ] **Step 1: Re-fetch and create a clean integration worktree from latest `origin/main`**

Reapply only the verified candidate commits, rerun the affected/full checks, and confirm no unrelated files or password-recovery changes are dropped.

- [ ] **Step 2: Run server read-only gate**

Confirm server HEAD/origin relation, tracked/untracked state without reading secret contents, app and both workers, Nginx, Redis, MySQL, `/healthz`, `/readyz`, `/login`, affected public routes, and `nginx -t` through the existing read-only mechanism.

- [ ] **Step 3: Publish only if every gate is green**

Push a non-force fast-forward to remote `main`, run the existing `/var/www/codesense/update.sh`, and verify deployed commit, services, health/readiness/login, affected review routes and rollback availability. If any server compatibility, browser, database, or deployment prerequisite is not verifiable, keep the candidate local and mark `needs_human` with exact evidence.

## Plan Self-Review

- Coverage: core request/state/permission/queue/dashboard actions are Tasks 3–5; student/teacher notification and AI loop are Tasks 6–7; whole-site accessibility/content/static behavior is Task 8; service/quality evidence is Tasks 2, 3, 6, 9; release and rollback are Task 10.
- No schema or external provider work is included; password recovery and current `origin/main` fixes are explicitly preserved.
- Every production behavior is preceded by a RED test in Tasks 1 and 3–8; full and browser regression are separate from the focused cycles.
