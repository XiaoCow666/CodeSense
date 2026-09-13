# CodeSense 本地优化候选：反馈生命周期、站内通知与隐私公开资料

## 运行元数据

- automation：`codesense-2`
- run id：`codesense-20260910-feedback-lifecycle`
- 运行时间：`2026-09-10 10:28:02 +08:00`
- 候选 worktree：`E:\CodeSense\local-optimization-20260910`
- 候选分支：`codex/local-opt-20260910`
- parent commit：`5ee9367039a80a783daa8677150ecdf717df3de1`
- `origin/main`：`5ee9367039a80a783daa8677150ecdf717df3de1`
- 目标：把反馈中心 v1 从“提交/人工查看”推进为可追踪的状态生命周期，并补齐用户通知、隐私可控的公开资料与全站交互收口。

主工作树 `E:\CodeSense\源代码` 保持原有未提交改动，未在本轮使用、覆盖或清理。所有开发、测试和浏览器验收均在候选 worktree 完成；没有写入生产数据库、Redis、Nginx、systemd、凭据、外部通知账号或用户权限。

## 选题与边界

上一轮已经交付反馈中心 v1。本轮选择一个连续的端到端切片：提交人能够看到状态进度，管理员能够按受控流程推进处理，系统能够在站内通知提交人，同时让用户明确决定是否公开基础资料。

实现仍复用已有 `SystemLog`，没有新增数据库表或迁移；通知只存在站内，不伪装成邮件、短信或 Push 已送达。公开资料默认私有，只有用户主动切换为公开后才可通过链接查看，并且模板只允许展示姓名、头像、角色和简介。

## 10+ 个独立可验证的功能迭代

| # | 迭代 | 独立验证点 | 分类 |
|---|---|---|---|
| 1 | 反馈状态机 | `received → triaged → in_progress → resolved → closed` 按顺序推进；允许 `resolved → in_progress`，禁止跳级、重复状态和关闭后重开；每次变更写入 `反馈状态更新` 审计事件。 | 跨端核心流 / 服务质量 |
| 2 | 提交成功通知 | 登录用户提交反馈后收到幂等的“反馈已收到”站内通知；游客提交仍保持原有回执流程。 | 跨端核心流 / 学生用户 |
| 3 | 管理员筛选与分派 | `/admin/feedback` 支持按状态、类型筛选；状态更新表单保留筛选条件，并可记录仅管理员可见的处理备注。 | 跨端核心流 / 教师管理员 |
| 4 | 状态变化通知 | 管理员推进状态后，反馈归属用户收到带回执链接的通知；通知键包含反馈、状态和更新时间，避免重复投递。 | 跨端核心流 / 学生-教师协同 |
| 5 | 回执进度时间线 | 回执页从单一“已收到”升级为当前状态和处理时间线；仍不暴露主题、正文、邮箱或内部备注。 | 跨端核心流 / 隐私 |
| 6 | 通知收件箱 | 新增全部/未读筛选、未读数量徽标、空状态、单条标记已读和全部标记已读；未读数读取失败不会让其他页面不可用。 | 全站交互 / 服务质量 |
| 7 | 通知归属与安全跳转 | 读取和标记已读均限定当前用户；通知链接和 `next` 只接受站内单斜杠路径，拒绝跨站跳转。 | 服务质量 / 安全 |
| 8 | 公开资料开关 | 编辑资料增加简介和公开范围，默认 `private`；公开/私有切换写入版本化设置事件，不改数据库结构。 | 数据隐私 / 学生用户 |
| 9 | 公开资料白名单 | 私有资料的公开 URL 返回 404；公开后页面只显示主动公开的基础资料，并明确不包含邮箱、学号、班级和学习记录。 | 全站内容 / 数据隐私 |
| 10 | 全站导航与页脚收口 | 导航增加站内通知入口和可读未读标签；关于、帮助、反馈页脚链接使用 `aria-current`；页脚增加数据使用边界说明。 | 全站前端 / 可访问性 |
| 11 | 移动菜单键盘闭环 | 移动菜单支持 Escape 关闭并把焦点还给触发按钮，同时复用外部点击关闭逻辑。 | 全站交互 / 可访问性 |
| 12 | 旧反馈兼容 | 缺少新状态字段的 v1 JSON 在读取时规范化为 `received`，不做在线批量迁移；首次状态变更才回写该条记录并追加审计。 | 服务质量 / 兼容性 |

分类覆盖：1–5 为跨端核心流；6、7、9–11 为全站前端/内容/交互；2、4、8、9 覆盖学生—教师协同和数据隐私；1、6、7、12 覆盖服务可靠性、审计、边界和兼容性。本轮没有修改模型、Prompt、LLM 调用或 AI 评分逻辑，避免把“AI 功能”误写成已实现能力。

## 关键实现

- [`services/feedback.py`](E:/CodeSense/local-optimization-20260910/services/feedback.py)：状态常量、有限状态转移、旧记录规范化、状态历史和审计写入；列表支持状态/类型筛选。
- [`services/notifications.py`](E:/CodeSense/local-optimization-20260910/services/notifications.py)：基于现有日志表的本地通知适配器；包含幂等键、用户归属、有限扫描、已读状态和站内 URL 边界。
- [`services/profile.py`](E:/CodeSense/local-optimization-20260910/services/profile.py)：以版本化日志事件保存个人简介和公开范围，默认私有。
- [`routes/main.py`](E:/CodeSense/local-optimization-20260910/routes/main.py)：公开资料、反馈状态更新、通知收件箱和安全重定向路由。
- [`routes/users.py`](E:/CodeSense/local-optimization-20260910/routes/users.py)、[`forms.py`](E:/CodeSense/local-optimization-20260910/forms.py)：把公开资料设置与现有资料保存放在同一事务边界内。
- [`app.py`](E:/CodeSense/local-optimization-20260910/app.py)、[`templates/layout.html`](E:/CodeSense/local-optimization-20260910/templates/layout.html)、[`static/modern.css`](E:/CodeSense/local-optimization-20260910/static/modern.css)：全局未读数、导航徽标、页脚提示和菜单键盘交互。
- [`templates/admin_feedback.html`](E:/CodeSense/local-optimization-20260910/templates/admin_feedback.html)、[`templates/feedback_receipt.html`](E:/CodeSense/local-optimization-20260910/templates/feedback_receipt.html)、[`templates/notifications.html`](E:/CodeSense/local-optimization-20260910/templates/notifications.html)：管理员处理、用户回执和通知收件箱界面。
- [`templates/edit_profile.html`](E:/CodeSense/local-optimization-20260910/templates/edit_profile.html)、[`templates/public_profile.html`](E:/CodeSense/local-optimization-20260910/templates/public_profile.html)：用户可控的公开范围和白名单展示。
- [`tests/test_feedback_lifecycle_notifications_profile.py`](E:/CodeSense/local-optimization-20260910/tests/test_feedback_lifecycle_notifications_profile.py)：新增 4 组覆盖端到端生命周期、权限、通知归属、开放重定向、隐私开关和旧记录兼容的测试。

## 公开实践与本地适配

- [Flask Flashing](https://flask.palletsprojects.com/en/stable/patterns/flashing/)：闪现消息适合跨一次请求传递操作结果；本轮将它用于状态更新和“全部已读”后的短提示，持久通知则单独存储，避免把 session flash 当成收件箱。
- [W3C WCAG 2.2 Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)：成功/进度信息使用非打断式 `role="status"`，错误和状态更新没有做过度播报；回执和通知空状态保持可感知但不抢焦点。
- [W3C WCAG 2.2 Error Identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification)：管理员筛选、状态表单和公开资料字段保留可识别的标签/错误语义。
- [W3C WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/)：移动菜单 Escape 关闭并恢复焦点，页脚当前页链接提供位置反馈；这属于针对本页面结构的适配，不代表完整 WCAG 审计。
- [GitHub notification inbox concepts](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications) 和 [inbox triage](https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox)：借鉴“未读/已读/处理后完成”的用户心智模型，但本轮只实现本地站内通知，不复制 GitHub 的外部订阅或邮件能力。
- [MDN Web Storage API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API)：确认浏览器本地存储适合客户端数据；本轮没有使用 `localStorage` 保存通知或隐私设置，因为这些状态需要绑定登录用户、跨设备一致并由服务端权限检查。

以上来源用于框架和交互机制的适配；它们不代表本轮完成完整无障碍审计、外部通知投递或跨服务工作流编排。

## 验证证据

验证环境：Python `3.13.5`、pytest `8.3.4`；候选测试使用临时 SQLite；没有读取或输出 `.env`、密钥、生产用户正文或生产业务数据。

| 检查 | 结果 |
|---|---|
| 反馈中心基线 `tests/test_feedback_center.py` | `5 passed` |
| 候选测试 + 反馈中心 | `9 passed` |
| 账户基础 `tests/test_account_basics.py` | `3 passed` |
| 应用基础 `tests/test_app.py` | `4 passed` |
| 全量 pytest（候选生产代码版本） | `428 passed` |
| Python `py_compile`（app、forms、main/users routes、3 个新增/修改 service） | exit `0` |
| Node `--check`（`static/js/sse-client.js`、`browser-compatibility.js`） | exit `0` |
| `git diff --check` | exit `0` |
| 浏览器 E2E（本地 127.0.0.1:5180、testing 配置、临时 SQLite） | 通过 |

浏览器 E2E 顺序验证了匿名反馈提交与回执、管理员分派并记录备注、登录用户提交反馈、两条站内通知出现、全部标记已读、公开资料切换和匿名公开资料页。公开页快照确认只出现“浏览器学生”、角色和主动填写的简介，不出现邮箱、学号、班级或学习记录；最终页面控制台为 `0 errors`、`1 warning`。临时服务、日志和 SQLite 文件已清理。

全量测试期间曾尝试并行启动多个历史测试文件，因测试套件共享 `config['testing']` 的 SQLite 配置出现过 `no such table` 的并发竞态；随后按串行方式重跑相关测试及全量套件并通过。该现象没有出现在候选生产代码的串行验证结果中。

## 发布门禁与回滚边界

已执行 `git fetch origin main`，候选 parent 与当前 `origin/main` 一致，没有发现远端漂移。已审阅仓库已有 [`update.sh`](E:/CodeSense/local-optimization-20260910/update.sh)：包含 Git 更新、依赖安装、systemd 服务安装/重启和状态检查，但不包含数据库迁移步骤。

本轮没有可用的服务器 Workbench/SSH 只读连接，无法完成发布前必须的服务器 HEAD、服务状态、HTTPS health/ready/login、管理员权限和旧入口回归检查。因此：

- release：`needs_human`
- push remote main：`not_run`
- execute `update.sh`：`not_run`
- stop reason：`server_runtime_verification_unavailable`
- candidate：保留在 `codex/local-opt-20260910`，不触碰主工作树

候选没有 schema migration 或依赖锁定变化，回滚边界是反向提交候选 commit 或恢复到 parent `5ee9367`；已写入的 `SystemLog` 通知/资料事件不会要求删除，旧版本会忽略这些新日志类型。若要发布，下一步应在干净集成 worktree 以最新 `origin/main` 集成、复跑全量测试，并取得服务器只读门禁后再按既有 `update.sh` 流程执行。

## 当前决定

- 本地实现：`ready_for_integration`
- 生产发布：`needs_human`
- 主工作树：`preserved`
- 报告完成：`2026-09-10 10:28:02 +08:00`
