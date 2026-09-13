# CodeSense 每日产品与系统自主迭代候选报告：提交复核协作集成

## 运行元数据

- 运行日期：2026-09-13；时区：Asia/Shanghai
- 候选工作树：`E:\CodeSense\源代码\.worktrees\daily-review-inbox-20260913`
- 候选分支：`codex/daily-review-inbox-20260913`
- 代码基线：`b0f9450fb618b30dddce7479d31115ecce5435d8`（当前 `origin/main`）
- 代码候选提交：`b6df5965f68425b9399b3ebbd85a1782aa51999d`
- 主要集成提交：`4c4bae0`、`95a9ad6`、`b6df596`；候选功能提交沿用已验证的复核协作提交链。
- 本轮只在隔离工作树中操作；`E:\CodeSense\源代码` 主工作区和其他 worktree 未修改。
- 数据边界：不新增表/字段/迁移，不写生产数据库、Redis、凭据或外部 provider；复核事件、通知和 AI 反馈信号复用已有 `SystemLog`，不调用模型。

## 结论

本轮将学生—教师“提交复核协作”闭环整合到最新主线：学生从提交详情发起复核，所属教师在受管队列中处理并留言，学生通过站内通知补充信息；状态、时间线、历史列表和教师仪表盘同步展示。学生还可以对已有 AI 建议记录“有帮助/需要澄清”，该信号不改分、不触发模型调用。

候选在隔离工作树中完成自动化、静态和浏览器验证，最终全量测试通过。发布状态为 `needs_human`：本轮没有可用的远程 SSH/部署连接器，无法重新完成服务器脏工作树、服务状态、健康检查和上线后的回滚门禁；因此没有 push、`update.sh`、迁移或生产写入。

## 14 个独立交付项

| # | 类别 | 用户价值 | 受影响表面 | 主要改动文件 | 独立验收证据 | 发布状态 |
|---:|---|---|---|---|---|---|
| 1 | 跨端/核心 | 复核请求、留言和状态变化有 `schema_version=1` 事件记录，便于审计和回退。 | 提交详情、教师队列、`SystemLog` | `services/submission_reviews.py`、`tests/test_submission_review_collaboration.py` | 版本化字段、状态历史、无 code snapshot 断言通过；正文上限 2,000 字符。 | 本地完成；生产待人工发布 |
| 2 | 跨端/核心 | 学生重复申请会复用同一复核线程，避免重复业务请求。 | 学生提交详情、复核服务、通知链路 | `routes/assignments.py`、`services/submission_reviews.py` | 幂等复核请求、路由和服务测试通过。 | 本地完成；生产待人工发布 |
| 3 | 跨端/核心 | 复核只能沿有限状态推进，避免跳级和错误的“直接解决”。 | 教师队列、提交详情、审计事件 | `services/submission_reviews.py`、`templates/teacher_review_queue.html` | `requested → in_review`、`in_review → waiting_student/resolved`、`waiting_student → in_review` 通过；非法跳转被拒绝。 | 本地完成；生产待人工发布 |
| 4 | 跨端/核心 | 学生、所属班级教师和管理员只看到授权范围，跨班教师不能推断提交正文。 | 详情页、队列、学生列表、管理员入口 | `services/submission_reviews.py`、`routes/assignments.py`、`routes/users.py` | 班级范围、管理员全量、跨班 403/空结果、列表摘要不含正文测试通过。 | 本地完成；生产待人工发布 |
| 5 | 跨端/学生—教师 | 教师留言等待学生回应；学生回复或对已解决复核追问时可重新打开线程。 | 提交详情时间线、消息表单 | `routes/assignments.py`、`services/submission_reviews.py`、`templates/submission_detail.html` | 浏览器完成教师回复、学生回复、解决和重新打开；转义、长度、权限测试通过。 | 本地完成；生产待人工发布 |
| 6 | 跨端/教师 | 教师拥有按状态筛选的班级复核队列，管理员可查看全部。 | `/teacher/reviews`、教师导航 | `routes/assignments.py`、`templates/teacher_review_queue.html`、`templates/layout.html` | 队列筛选、空状态、按钮状态和无权限 403 测试通过；浏览器队列操作通过。 | 本地完成；生产待人工发布 |
| 7 | 跨端/教师 | 仪表盘直接显示待处理数量，减少漏掉学生求助。 | 教师仪表盘、导航入口 | `routes/main.py`、`templates/teacher_home.html`、`templates/layout.html` | `open_review_count` 与队列状态同步；浏览器可进入队列。 | 本地完成；生产待人工发布 |
| 8 | 服务/通知 | 复核申请、留言和状态变化只通知其他参与者，通知可幂等复用。 | 站内通知收件箱、复核事件 | `services/notifications.py`、`services/submission_reviews.py`、`templates/notifications.html` | 参与者归属、幂等 key、已读权限、本地详情链接和浏览器收件箱断言通过；外部邮件/SMS 未启用。 | 本地完成；生产待人工发布 |
| 9 | AI/数据 | 学生可反馈已有 AI 建议是否有帮助，但不会改分或触发新模型调用。 | 提交详情 AI 区块、信号日志 | `services/submission_reviews.py`、`routes/assignments.py`、`templates/submission_detail.html` | owner-only、allowlist、upsert、无 AI 反馈拒绝、分数不变测试通过；diff 无新增模型/provider 调用。 | 本地完成；生产待人工发布 |
| 10 | AI/学习数据 | 学生在历史和提交列表看到复核状态及下一步；旧提交保持原有展示。 | `/submission-history/<id>`、`/view_submission` | `routes/assignments.py`、`routes/users.py`、`templates/submission_history.html`、`templates/submissions.html` | 学生列表状态摘要、actor scope 和无事件回退测试通过。 | 本地完成；生产待人工发布 |
| 11 | 前端/内容 | 提交详情集中展示申请、状态、留言和时间线，同时保留下载与重提交入口。 | 提交详情时间线、表单、状态提示 | `templates/submission_detail.html`、`static/modern.css` | 时间线顺序、角色/时间、body 转义、空状态和原入口测试通过。 | 本地完成；生产待人工发布 |
| 12 | 前端/交互 | 表单有可见标签、帮助文字、长度提示、live status 和清晰队列表头，移动端可用。 | 详情、队列、列表、移动布局 | `templates/submission_detail.html`、`templates/teacher_review_queue.html`、`templates/submissions.html`、`static/modern.css` | WCAG 2.2 对应标记、390px 无横向溢出、消息控件在视口内；浏览器业务检查通过。 | 本地完成；生产待人工发布 |
| 13 | 服务/质量 | 复核写入在单进程并发和生产数据库中降低“检查后插入”的重复风险，日志查询按提交范围过滤。 | 复核事件、AI 信号、通知写入 | `services/submission_reviews.py`、`services/notifications.py` | 进程锁、MySQL/PostgreSQL 行锁、SQLite 回退和 bounded scan 测试通过；目标字段边界过滤覆盖。 | 本地完成；生产待人工发布 |
| 14 | 前端/质量 | 页面离开时取消主动 AI SSE；公共页面不再请求缺失 favicon。 | 学生首页 SSE、公共静态资源 | `templates/student_home.html`、`templates/base.html`、`app.py`、`static/img/favicon.svg` | `AbortController`/`pagehide`、`/favicon.ico` SVG 200、浏览器页面和控制台错误为 0。 | 本地完成；生产待人工发布 |

### 分类配额核对

- 跨端/核心：1–7，共 7 项（要求至少 3）。
- 前端/内容/交互：6、7、10–12、14，共 7 项（要求至少 3）。
- AI/数据/学生—教师：1、5、9、10，共 4 项（要求至少 2）。
- 服务/质量/观测：8、13、14，共 3 项（要求至少 2）。

以上按可独立验证的用户或系统价值计数；同一处样式或基础设施改动没有重复拆项。测试隔离修复属于质量门禁，不额外计入 14 项。

## 研究与适配边界

| 来源（直接 URL） | 本轮采用 | 明确不采用 |
|---|---|---|
| [W3C Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/) | 可见 label、键盘可达控件、清晰焦点/状态、`role="status"`/`aria-live` 和移动端不依赖 hover。 | 未宣称完整 WCAG 或辅助技术合规；局部标记测试不等同于正式无障碍审计。 |
| [GitHub inbox filters](https://docs.github.com/en/subscriptions-and-notifications/reference/inbox-filters)、[about notifications](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications)、[managing notifications](https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox) | 借鉴按原因、已读/未读和状态整理通知的可 triage 心智模型；CodeSense 使用 `submission_review` 本地站内通知和本地详情链接。 | 不复制 GitHub 的 mention、订阅、邮件、外部推送或组织级规则。 |
| [Exploring the Potential of Large Language Models to Generate Formative Programming Feedback](https://arxiv.org/abs/2309.00029) | 将 AI 建议作为可反馈的形成性起点，保留教师复核入口；只记录 helpful/needs_clarification 信号。 | 未改模型、prompt、provider 或评分算法；未据此声称教学效果或模型准确率提升。 |
| [Replit Agent build workflow](https://docs.replit.com/learn/build-with-agent)、[plan vs. build mode](https://docs.replit.com/learn/plan-vs-build-mode)、[GitHub Copilot research/plan/iterate](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/research-plan-iterate) | 采用“先计划、再分层实现、可见检查点、测试后交付/回滚”的 agentic 工作流。 | 未引入第三方 agent、托管执行器或外部构建依赖。 |

## 验证证据

### 自动化与静态检查

- 当前主线基线全量：`538 passed, 1586206 warnings in 341.19s (0:05:41)`。
- 首次集成回归：`554 passed, 1 failed`；失败发生在测试 teardown 删除短生命周期 SQLite 文件时，业务断言已完成，Windows 后台 daemon 线程仍持有文件句柄。
- 系统化定位：登录路由会触发能力趋势任务；`/view_submission` 的历史加载还会触发 `generate_ability_analysis_async`。两条新增回归测试分别锁定这两个入口。
- 修复：`routes/auth.py` 在测试应用中不排队登录后的趋势任务；`tasks/ability_analysis.py` 在测试应用且非 demo 运行中不启动 daemon 分析线程。生产应用路径和显式 worker 入口不变。
- 修复后针对性验证：`3 passed`；完整复核协作文件：`13 passed`。
- 最终全量：`557 passed, 1920799 warnings in 428.14s (0:07:08)`，退出码 0。
- `py -3.13 -m compileall -q app.py forms.py models.py services routes tasks`：exit 0。
- `node --check static/js/sse-client.js` 与 `node --check static/js/browser-compatibility.js`：exit 0。
- `git diff --check`（含基线比较）：exit 0。

全量 warning 主要来自既有依赖和测试环境：Werkzeug `ast.Str`、`datetime.utcnow`、SQLAlchemy legacy API、Flask-Session/Redis fallback，以及测试夹具的异步/数据库生命周期提示。本轮没有通过静默 warning 或修改生产配置掩盖它们。

### 临时环境浏览器验收

使用临时 SQLite、临时 Flask server 和本机 Chromium/Playwright 完成学生—教师闭环：学生申请 → 教师队列 → `in_review` → 教师留言 → 学生回复/AI 信号 → `resolved` → 学生追问重新打开 → 通知收件箱 → 全部已读。

- 11 项业务流程检查全部通过，包含学生/教师登录、队列显示、状态推进、双向消息、解决后重开、通知收件箱和 AI `needs_clarification` 信号。
- 390px 视口：`documentScrollWidth=375`、`bodyScrollWidth=375`，无横向溢出；消息 textarea 宽 295px、右边界 335px，复核控件右边界 359px，均在视口内。
- 浏览器页面错误：`[]`；控制台错误：`[]`；仅有 1 条 warning。
- 临时数据库、server、浏览器上下文和 harness 已清理；没有写入线上数据库、Redis、模型或通知 provider。

## 发布门禁与状态

- 当前本地候选基于 `origin/main=b0f9450fb618b30dddce7479d31115ecce5435d8`，分支相对基线 ahead 13；未 force push。
- 已核对仓库内 `update.sh`：上线会执行 `git pull origin main`、依赖安装、systemd 服务/worker 重启和服务状态检查。
- 本轮无可用远程 SSH/服务器读写连接器，无法重新验证服务器 HEAD、tracked/untracked 脏状态、`codesense`/worker/Nginx/Redis/MySQL 状态、`/healthz`、`/readyz`、`/login`、`/forgot-password`、`/register/email`、`nginx -t` 或上线后复核路由。
- 上一轮 2026-09-12 的记忆记录显示服务器最后已发布密码找回候选 `788882f`，且当时存在需保留的密码找回/环境维护脏改动；当前 `origin/main` 已推进到 `b0f9450`。这条记录不是本轮线上复核，不据此宣称当前服务器状态。
- 结论：`release=needs_human`，`stop_reason=online_gate_unavailable_and_last_known_server_dirty`。本轮没有执行 push、`update.sh`、迁移、生产数据库/Redis 写入或外部通知发送。

## 回滚与后续动作

- 候选仍保留在隔离分支，可在审查后使用非破坏性的 `git revert` 回滚 `b0f9450..b6df596` 范围内的候选提交；不对共享主工作区执行 `reset --hard` 或 `checkout`。
- 本轮没有 schema/迁移，因此没有数据库结构回滚；已产生的本地 `SystemLog` 事件会被旧版本忽略。
- 人工下一步：先盘点并提交/隔离服务器上的密码找回改动，建立干净集成工作树，重新执行线上只读门禁；随后在远端仍未推进时 fast-forward push，运行现有 `update.sh`，再验证健康、就绪、登录和复核闭环。
- 邮件、短信、push 和真实 SMTP E2E 仍未启用；这是设计边界，不是本轮失败。

## 文件索引

- 复核服务：[services/submission_reviews.py](E:/CodeSense/源代码/.worktrees/daily-review-inbox-20260913/services/submission_reviews.py)
- 通知适配器：[services/notifications.py](E:/CodeSense/源代码/.worktrees/daily-review-inbox-20260913/services/notifications.py)
- 复核路由：[routes/assignments.py](E:/CodeSense/源代码/.worktrees/daily-review-inbox-20260913/routes/assignments.py)
- 复核测试：[tests/test_submission_review_collaboration.py](E:/CodeSense/源代码/.worktrees/daily-review-inbox-20260913/tests/test_submission_review_collaboration.py)
- 集成计划：[docs/superpowers/plans/2026-09-13-submission-review-integration.md](E:/CodeSense/源代码/.worktrees/daily-review-inbox-20260913/docs/superpowers/plans/2026-09-13-submission-review-integration.md)
