# CodeSense 本地优化候选：反馈中心 v1

## 运行元数据

- automation：`codesense-2`
- run id：`codesense-20260909-feedback-center`
- 运行时间：`2026-09-09 10:39:07 +08:00` 起
- 候选 worktree：`E:\CodeSense\local-optimization-20260909`
- 候选分支：`codex/local-opt-20260909`
- parent commit：`329c56bf503af5fc941a945b6f79828f4f3d1138`
- 目标：为公开入口提供可追踪的反馈提交、管理员复核和一致的基础可访问性

主工作树 `E:\CodeSense\源代码` 保持原有未提交改动，未在本轮使用、覆盖或清理。候选也没有修改生产数据库、Redis、Nginx、systemd、凭据、外部通知账号或用户权限。

## 选题与边界

上一轮线上检查仍显示服务器代码落后于当前 `origin/main`，因此先从最新远端 `329c56b` 建立隔离候选。本轮选取产品 PRD 中的“反馈中心”小切片：

- 新增 `/feedback` 公开表单，生成不透明的 `FB-XXXXXXXXXXXX` 回执编号和初始 `received` 状态。
- 使用已有 `SystemLog` 作为版本化 JSON 存储，不新增表、迁移或外部邮件/SMS 依赖。
- 新增只读管理员复核页 `/admin/feedback`，保留现有 `@login_required` 与 `@admin_required` 保护。
- `/contact` 保留 GET/POST 路由，旧字段仍可提交并转入新的回执流程；页面文案将团队联系信息与产品反馈分开。
- 全局 active layout 增加跳过链接、明确导航标签、移动菜单 `aria-expanded`、键盘 focus-visible 样式和按严重性区分的动态消息角色。

明确不做：状态流转/通知发送、生产数据迁移、账号或权限模型调整、真实生产反馈写入、主工作树合并。

## Planner / Implementer / Interaction Reviewer / Test Reviewer / Coordinator

### Planner

- 假设：现有 `SystemLog` 表在正式库、演示临时库和测试库都可用；反馈首版只需可靠收件和人工复核。
- 回滚点：候选代码提交可整体反向移除；没有 schema、依赖、配置或外部状态回滚。
- 隐私边界：公开回执不展示主题、正文、邮箱或请求上下文；管理员页才展示反馈内容。表单提示用户不要提交密码、API key 或不必要的个人信息。
- 兼容边界：不删除 `/contact`，旧 POST 字段映射到新的记录结构；匿名记录不伪造不存在的用户外键。

### Implementer

- `services/feedback.py` 封装字段校验、长度上限、邮箱格式校验、opaque id、状态历史、请求上下文和现有日志持久化。
- `routes/main.py` 增加公开提交/回执和管理员复核路由，并将旧联系表单接入同一服务。
- `templates/feedback.html` 使用显式 label/id、fieldset/legend、字段级帮助文本和可定位的错误摘要；新增回执及管理员模板。
- `templates/layout.html`、`templates/contact.html`、`templates/admin_dashboard.html` 和 `static/modern.css` 完成入口、导航与键盘可用性收口。
- `tests/test_feedback_center.py` 覆盖匿名提交、拒绝无效字段、旧入口兼容、回执脱敏、管理员权限和上下文记录。

### Interaction Reviewer

结论：候选范围内通过。

- GET 表单、POST 成功重定向、回执 GET、旧 `/contact` POST、匿名管理员拦截和管理员复核均由测试客户端完成。
- 表单错误保留字段值并提供 `role="alert"` 与字段锚点；成功回执只显示编号、类型、时间和“已收到”。
- 模板使用 Jinja 默认转义，管理员展示正文使用 `white-space: pre-wrap`，没有拼接 HTML 或脚本。
- 生产线上不发送假反馈，避免在线验证污染真实业务数据；部署后仅做 GET/权限/健康探针。

### Test Reviewer

验证环境：Python `3.13.5`，pytest `8.3.4`；测试写入候选 worktree 的临时 SQLite。没有读取或输出 `.env`、密钥、用户正文或生产业务数据。

| 检查 | 结果 |
| --- | --- |
| 基线相关测试 `tests/test_app.py tests/test_account_basics.py tests/test_demo_profile_views.py` | `10 passed` |
| 反馈中心测试 `tests/test_feedback_center.py` | `5 passed` |
| 全量 pytest（候选） | `424 passed`，`208.43s` |
| `py -3.13 -m compileall -q app.py routes services tasks utils tests/test_feedback_center.py` | exit `0` |
| `git diff --check` | exit `0` |

### Coordinator

候选满足本地实现、回归、权限、兼容和静态检查门槛，进入干净集成 worktree。集成时必须以当时最新 `origin/main` 为基线并只 cherry-pick 候选提交；若远端发生漂移、集成冲突、依赖/运行时不一致或线上探针异常，则停止 push/deploy。

## 公开实践与可验证机制

- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)：支持跳过重复内容、可见键盘焦点和可操作控件可识别性；本轮对应 skip link、focus-visible 与导航/按钮语义。
- [WAI Forms: Notifications](https://www.w3.org/WAI/tutorials/forms/notifications/)：建议对成功/错误反馈使用清晰、简洁且可感知的通知；本轮对应错误摘要、字段链接和动态消息的 `role`/`aria-live`。
- [WAI Forms: Labels](https://www.w3.org/WAI/tutorials/forms/labels/)：显式 label 与控件 id 建立关联；本轮所有新增表单控件均使用显式关联。
- [Flask Flashing](https://flask.palletsprojects.com/en/stable/patterns/flashing/)：闪现消息适用于跨一次请求传递结果；本轮仅在旧入口异常路径使用通用提示，提交成功以 PRG 回执结束。

这些来源用于界面和框架机制的适配，不代表本轮已完成完整 WCAG 审计、邮件通知或多服务状态编排。

## Server read-only gate before release

通过现有 Workbench CLI 对目标 ECS `i-f8zbujornnh55dsydozz` / `cn-heyuan` 做只读检查，时间约 `2026-09-09 10:38`：

- 当前服务器 HEAD 与 `origin/main` 均为 `1b4d51e48abca55122a27809d16419c38bd1bd8e`，与候选 parent/当前远端不同，属于版本漂移，不能直接在服务器目录上改代码。
- tracked worktree clean；仅记录 dirty count 为 `3`，未读取或记录未跟踪条目名称/内容。
- `codesense`、两个 RQ worker、nginx、redis、mysqld 均 `active`。
- `healthz=200`、`readyz=200`、`login=200`；发布前 `/feedback=404`、`/admin/feedback=404`，符合旧版本预期。
- 未执行服务器写锁、快照、拉取、重启、迁移、数据库/Redis/IAM/网络/凭据写入。

## Release gate and rollback boundary

候选不属于纯 observability 例外：它新增业务数据写入与管理员可见内容，因此需要完整集成测试、版本快进、`update.sh` 成功和部署后 GET/权限/健康回归。发布动作限定为：

1. 在干净集成 worktree 以最新 `origin/main` 集成并复跑全量测试、编译和 diff 检查。
2. 非强制快进 push 到 `origin/main`，不接触 dirty 主工作树。
3. 在服务器执行已有 `/var/www/codesense/update.sh`；不执行额外迁移，不发真实反馈。
4. 验证服务器 HEAD、服务状态、HTTPS `healthz`/`readyz`/`login`/`feedback`，以及未授权管理员路由仍被拦截。

失败时停止继续重启；若已经更新且回归失败，使用前一已验证 commit 做人工批准的可逆恢复或 `git revert`，不删除反馈数据。

## Integration gate result

- integration worktree：`E:\CodeSense\release-integration-20260909`
- integration parent：`329c56bf503af5fc941a945b6f79828f4f3d1138`
- cherry-pick commit：`f5210e768eabe8be03875e6b0f009ed66a6ffeae`
- push 前功能与报告提交：`5c6ccb646a6d31fcc8ca304ab2296c88a14d9111`
- full pytest：`424 passed`，`204.92s`
- compileall：exit `0`
- `git diff --check`：exit `0`
- integration worktree：clean；push 前相对 `origin/main` 为两个快进提交

集成没有冲突，也没有发现数据库 schema、依赖锁定、路由导入、模板渲染或角色保护回归。

## Post-deploy verification

部署时间约 `2026-09-09 10:50:46 +08:00`，执行的是服务器已有 `/var/www/codesense/update.sh`，Workbench 命令 exit `0`：

- 远端 push：`329c56b..5c6ccb6`，非强制快进到 `main`。
- `update.sh`：Git fast-forward、依赖检查、systemd unit 安装/重载和主服务重启成功；没有运行数据库迁移，也没有提交生产反馈。
- 服务器 HEAD 与 `origin/main` 均为 `5c6ccb646a6d31fcc8ca304ab2296c88a14d9111`。
- `codesense`、ability worker、submission worker、nginx、redis、mysqld 均 `active`；主服务与两个 worker `NRestarts=0`。
- `nginx -t` 成功；HTTPS `healthz=200`、`readyz=200`、`login=200`、`contact=200`、`about=200`、`feedback=200`。
- 未授权 `/admin/feedback=302`，follow-up header 确认重定向到 `/login?next=%2Fadmin%2Ffeedback`；无效回执返回 `404`。
- 反馈页包含“提交一条反馈”，旧联系页包含“前往反馈中心”；没有对生产执行 POST canary。
- 服务器 dirty count 仍为 `3`，与部署前一致；未读取或记录未跟踪条目名称/内容。

第一次聚合验证命令因把“登录”正文断言用于 302 响应而返回命令级 exit `1`，未改变服务器状态；随后用 redirect header 复核并通过，业务状态保持正常。

## Current decision

- release：`published`
- push remote main：`done`（`5c6ccb646a6d31fcc8ca304ab2296c88a14d9111`）
- execute `update.sh`：`done`
- rollback：`not_used`；如后续回归失败，前一已验证服务器版本为 `1b4d51e48abca55122a27809d16419c38bd1bd8e`
- stop reason：`completed_release_product_slice`
- report finalized：`2026-09-09 11:02:52 +08:00`
