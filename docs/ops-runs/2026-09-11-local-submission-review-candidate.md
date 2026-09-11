# CodeSense 每日产品与系统自主迭代候选报告：提交复核协作 v1

## 运行元数据

- 运行日期：2026-09-11；报告整理时间：2026-09-11 11:27 Asia/Shanghai
- 候选工作树：`E:\CodeSense\local-optimization-20260911`
- 候选分支：`codex/local-opt-20260911`
- 代码基线：`936af910ab046a80fc8a622698f75497191efd52`（2026-09-10 已验证的本地候选）
- 当前代码提交：`8e0baee4921f82302abcb47420fa979f1207fd4c`（`fix: harden submission review collaboration`）
- 本轮提交范围：`22557f6`、`4a8a00d`、`52089e5`、`e7a8e25`、`4c45568`、`8b46bb9`、`8e0baee`
- 本轮只在隔离工作树开发；`E:\CodeSense\源代码` 主工作区及既有 worktree 未修改。
- 数据边界：不新增表/字段/迁移，不写生产数据库、Redis、凭据或外部 provider；复核和 AI 信号复用已有 `SystemLog`，不调用模型。

## 结论

本轮交付一个可回退的学生—教师“提交复核协作”闭环：学生从提交详情发起复核，受管教师在队列中处理并留言，学生收到站内通知后可以补充信息或重新打开已解决复核；提交详情、学生历史/列表和教师仪表盘同步显示状态；学生可以对已有 AI 建议标记“有帮助/需要澄清”，但不会改分或触发模型调用。

候选在本地已完成验证，但发布状态为 `needs_human`。服务器当前 HEAD 与 `origin/main` 均为 `5ee9367039a80a783daa8677150ecdf717df3de1`，健康检查可用（`/healthz` 返回 200，Nginx 配置检查通过），但服务器仍有密码找回批次的 tracked/untracked 未提交改动。为避免覆盖他人工作，本轮没有执行 `update.sh`、push、合并、迁移或生产写入。

## 14 个独立交付项

| # | 类别 | 用户价值 | 受影响表面 | 主要改动文件 | 独立验收证据 | 发布状态 |
|---:|---|---|---|---|---|---|
| 1 | 跨端/核心 | 复核请求、留言和状态变化有稳定的 `schema_version=1` 事件记录，后续可审计、可回退。 | 提交详情、教师队列、`SystemLog` | `services/submission_reviews.py`、`tests/test_submission_review_collaboration.py` | 版本化字段、状态历史、无 code snapshot 断言通过；事件正文上限 2,000 字符。 | 本地完成；生产待人工发布 |
| 2 | 跨端/核心 | 学生重复点击申请不会新建第二个复核线程或重复业务请求。 | 学生提交详情、复核服务、通知链路 | `routes/assignments.py`、`services/submission_reviews.py` | 重复申请复用同一 `review_id`；请求路由与服务测试通过。 | 本地完成；生产待人工发布 |
| 3 | 跨端/核心 | 复核只能按有限状态推进，避免跳级、重复状态和错误的“直接解决”。 | 教师队列、提交详情状态、审计事件 | `services/submission_reviews.py`、`templates/teacher_review_queue.html` | `requested → in_review`、`in_review → waiting_student/resolved`、`waiting_student → in_review` 通过；`waiting_student → resolved` 被拒绝。 | 本地完成；生产待人工发布 |
| 4 | 跨端/核心 | 学生、所属班级教师和管理员各自看到应有范围，跨班教师不能从队列或列表推断提交内容。 | 详情页、教师队列、学生列表、管理员入口 | `services/submission_reviews.py`、`routes/assignments.py`、`routes/users.py` | 受管班级过滤、管理员全量、跨班 403/空结果、列表摘要不含正文测试通过。 | 本地完成；生产待人工发布 |
| 5 | 跨端/学生—教师 | 教师留言会等待学生回应；学生回复会重新进入复核，已解决复核也能由学生追问后重开。 | 提交详情时间线、消息表单 | `routes/assignments.py`、`services/submission_reviews.py`、`templates/submission_detail.html` | 浏览器完成教师回复、学生回复、resolved/reopen；消息正文转义、上限和权限测试通过。 | 本地完成；生产待人工发布 |
| 6 | 跨端/教师 | 教师有按状态筛选的班级复核队列，管理员可查看全部且只看到可执行的下一状态。 | `/teacher/reviews`、教师/管理员导航 | `routes/assignments.py`、`templates/teacher_review_queue.html`、`templates/layout.html` | 队列行数、状态过滤、空状态、按钮状态和无权限 403 测试通过；浏览器队列操作通过。 | 本地完成；生产待人工发布 |
| 7 | 跨端/教师 | 仪表盘直接显示待处理数量，减少错过学生求助的概率。 | 教师仪表盘、导航入口 | `routes/main.py`、`templates/teacher_home.html`、`templates/layout.html` | `open_review_count` 与队列状态同步；浏览器可从仪表盘进入队列。 | 本地完成；生产待人工发布 |
| 8 | 服务/通知 | 复核申请、留言和状态变更只通知其他参与者，通知带本地详情链接且重复投递可复用。 | 站内通知收件箱、复核事件 | `routes/assignments.py`、`services/notifications.py`、`templates/notifications.html` | 学生/教师通知归属、idempotency key、读取权限和浏览器收件箱断言通过；外部邮件/SMS 未启用。 | 本地完成；生产待人工发布 |
| 9 | AI/数据 | 学生可以反馈已有 AI 建议是否有帮助，信号可更新但不污染分数或触发新模型调用。 | 提交详情 AI 区块、AI 信号日志 | `services/submission_reviews.py`、`routes/assignments.py`、`templates/submission_detail.html` | owner-only、allowlist、upsert、无 AI 反馈时拒绝、分数不变测试通过；全 diff 无新增模型/provider 调用。 | 本地完成；生产待人工发布 |
| 10 | AI/学习数据 | 学生在历史和提交列表能看到当前复核状态及下一步，旧提交仍显示原有页面。 | `/submission-history/<id>`、`/view_submission` | `routes/assignments.py`、`routes/users.py`、`templates/submission_history.html`、`templates/submissions.html` | 学生列表路由 200、状态摘要带 actor scope、无事件旧提交回退测试通过。 | 本地完成；生产待人工发布 |
| 11 | 前端/内容 | 提交详情集中展示申请、状态、留言和时间线，参与者只看到授权正文。 | 提交详情时间线、表单和状态提示 | `templates/submission_detail.html`、`static/modern.css` | 时间线顺序、角色/时间、escaped body、空状态和原下载/重提交入口测试通过。 | 本地完成；生产待人工发布 |
| 12 | 前端/交互 | 表单有可见标签、帮助文字、长度提示、live status 和清晰的队列表头，键盘/移动端更可用。 | 详情、队列、列表、移动布局 | `templates/submission_detail.html`、`templates/teacher_review_queue.html`、`templates/submissions.html`、`static/modern.css` | WCAG 2.2 对应标记检查、移动宽度 390px 无横向溢出、消息控件在视口内；浏览器 10/10 业务检查通过。 | 本地完成；生产待人工发布 |
| 13 | 服务/质量 | 复核写入在单进程并发和生产数据库中减少“检查后插入”的重复风险，日志查询按提交范围过滤。 | 复核事件、AI 信号、通知写入 | `services/submission_reviews.py`、`services/notifications.py` | 同提交写操作使用进程锁；MySQL/PostgreSQL 使用提交行/收件人行锁；SQLite 保留进程锁回退；目标字段有逗号/对象结束边界并经 11 项测试覆盖。 | 本地完成；生产待人工发布 |
| 14 | 前端/质量 | 页面导航不会把主动取消的 AI SSE 当成用户可见错误，公共页面不再请求缺失 favicon。 | 学生首页 SSE、公共页面静态资源 | `templates/student_home.html`、`templates/base.html`、`app.py`、`static/img/favicon.svg` | 页面离开取消 AbortController；`/favicon.ico` 返回 SVG 200；浏览器最终控制台错误 0、页面错误 0。 | 本地完成；生产待人工发布 |

### 分类配额核对

- 跨端/核心：1–7，共 7 项（要求至少 3）。
- 前端/内容/交互：6、7、10–12、14，共 7 项（要求至少 3）。
- AI/数据/学生—教师：1、5、9、10，共 4 项（要求至少 2）。
- 服务/质量/观测：8、13、14，共 3 项（要求至少 2）。

每项均有独立服务/路由断言、模板标记断言或浏览器交互检查；同一处样式变更没有拆成多个交付项重复计数。

## 研究与适配边界

| 来源（直接 URL） | 版本/复查日期 | 本轮采用 | 明确不采用 |
|---|---|---|---|
| [W3C Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/) | WCAG 2.2 Recommendation；官方页面 2026-09-11 复查 | 原生表单、可见 label、键盘可达控件、清晰焦点/状态、`role="status"`/`aria-live`、移动端不依赖 hover。 | 未宣称完整 WCAG/辅助技术合规；未把本轮局部标记测试等同于正式无障碍审计。 |
| [GitHub inbox filters](https://docs.github.com/en/subscriptions-and-notifications/reference/inbox-filters) 与 [about notifications](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications) | GitHub 官方文档当前页面；2026-09-11 复查 | 借鉴按原因、已读/未读和状态整理通知的心智模型；CodeSense 使用 `submission_review` 本地站内通知和本地详情链接。 | 不复制 GitHub 的订阅、mention、邮件、外部推送或组织级通知规则。 |
| [Exploring the Potential of Large Language Models to Generate Formative Programming Feedback](https://arxiv.org/abs/2309.00029) | Kiesler、Lohr、Keuning，2023；arXiv 摘要/论文页 2026-09-11 复查 | 把 AI 建议作为可反馈的起点，保留教师复核入口；只记录学生的 helpful/needs_clarification 信号，不把模型结果直接变成教师评价。 | 未改模型、prompt、provider 或评分算法；未据此声称教学效果或模型准确率提升。 |

## 验证证据

### 自动化与静态检查

- 既有候选基线（2026-09-10 记忆）：全量 `428 passed`。
- 本轮最终聚焦：`11 passed`，复核服务、路由、权限、通知、AI 信号、列表和公共资源契约均通过。
- 本轮最终全量：`439 passed`，`1426582 warnings`，`244.55s`（`0:04:04`）；无失败。
- `py -3.13 -m compileall -q app.py forms.py models.py services routes tasks`：exit 0。
- `node --check static/js/sse-client.js` 与 `node --check static/js/browser-compatibility.js`：exit 0。
- `git diff --check`：exit 0。
- 复核结果：新增服务/通知模块没有 provider、HTTP、LLM 或模型调用；候选 diff 未修改 `models.py`、迁移文件或生产配置。

全量 warning 主要来自既有依赖兼容提示（Werkzeug/SQLAlchemy legacy API、`datetime.utcnow`）、测试环境 Redis `HELLO` 回退和异步测试夹具启动时的缺表竞态；本轮没有通过静默 warning 或改生产配置掩盖它们。它们没有转化为本轮测试失败，后续可作为独立质量债务处理。

### 临时环境浏览器验收

使用临时 SQLite、临时 Flask server 和本机 Chromium 1223 完成：

```text
student_request_control             true
request_created                     true
teacher_queue_row                   true
status_to_in_review                 true
teacher_message                     true
student_reply_and_ai_signal         true
teacher_resolved                    true
notification_inbox                  true
mobile_no_horizontal_overflow       true
mobile_message_control_fits         true
console_errors                      []
page_errors                         []
all_checks_passed                   true
```

测试结束后临时数据库、server、浏览器上下文和测试日志已清理；没有向线上数据库、Redis、外部模型或通知 provider 写入数据。

## 服务器只读门禁与发布状态

- 只读事实：服务器 `HEAD=5ee9367039a80a783daa8677150ecdf717df3de1`，远端 `origin/main` 同值；`/healthz`（Host `saucodesense.com`）返回 200 JSON；Nginx `-t` 成功；CodeSense、两个 worker、Nginx、Redis、MySQL 处于 active/running。
- 服务器 tracked 脏改动涉及 `.env.example`、`DEPLOYMENT.md`、`README.md`、`config.py`、`forms.py`、`models.py`、`routes/auth.py`、`routes/users.py`、`templates/login.html`、`templates/register.html`、`templates/users.html`、`tests/test_account_basics.py`。
- 服务器 untracked 脏改动包括 `Miniconda3-latest-Linux-x86_64.sh`、`backup_before_clean.sql`、`clean_scores.py`、`services/auth_identity.py`、`services/email_verification.py`、`services/password_reset.py`、`templates/email_register.html`、`templates/forgot_password.html`、`templates/resend_verification.html`、`templates/reset_password.html`、`templates/verify_email.html`、`tests/test_password_recovery.py`。
- 这些改动属于密码找回/环境维护批次，不属于本候选；本轮没有读取其内容、没有覆盖、没有 `git reset`/`checkout`、没有执行 `/var/www/codesense/update.sh`。
- 因服务器工作树非干净，即使版本号表面一致，也不能把本候选直接合并或部署；`release=needs_human`，`stop_reason=server_dirty_password_recovery_worktree`。

## 回滚与后续动作

- 本地候选可通过逆序 `git revert` 回滚本轮代码提交：`8e0baee`、`8b46bb9`、`4c45568`、`e7a8e25`、`52089e5`、`4a8a00d`、`22557f6`。不对共享主工作区执行 destructive reset。
- 本轮没有 schema/迁移，因此没有数据库结构回滚；已产生的本地 `SystemLog` 事件由旧版本忽略，正式发布前应在干净集成环境确认兼容性。
- 下一步需要人工先盘点并提交/隔离服务器密码找回改动，再从 `origin/main` 建立干净集成工作树，应用本候选，重跑全量测试、登录/health/ready/复核链路和错误率检查，之后才决定 push/merge/deploy。

## 候选文件索引

- 复核服务：[services/submission_reviews.py](E:/CodeSense/local-optimization-20260911/services/submission_reviews.py)
- 复核测试：[tests/test_submission_review_collaboration.py](E:/CodeSense/local-optimization-20260911/tests/test_submission_review_collaboration.py)
- 计划：[docs/superpowers/plans/2026-09-11-submission-review-collaboration.md](E:/CodeSense/local-optimization-20260911/docs/superpowers/plans/2026-09-11-submission-review-collaboration.md)
