# 密码找回与状态恢复集成候选

- 日期：2026-09-12（Asia/Shanghai）
- 决策：按用户确认保留密码找回、邮箱验证和学生登录功能，并与状态恢复/可访问性改进合并验证。
- 候选分支：`codex/status-password-deploy-20260912`
- 候选 HEAD：`cbc5710`（已合并推送前最新 `origin/main`）

## 纳入范围

密码找回与邮箱验证功能来自以下已审阅的聚焦提交，基于服务器当前基线 `5ee9367` 整理：

- `ae58001`：学生登录与密码找回
- `843c74a`：兼容旧部署的学号迁移
- `270280a`：邮箱注册验证

状态恢复与可访问性改进来自：

- `ee8ee9e`：状态恢复体验方案
- `334c4a8`：错误页、请求追踪、移动导航、反馈表单、AI 建议、提交评测状态等改进

## 验证结果

定向回归：`31 passed`。

全量回归：

```text
531 passed, 1577243 warnings in 306.93s (0:05:06)
```

辅助检查全部通过：

- Python `compileall`：通过
- `static/js/sse-client.js` Node 语法检查：通过
- `git diff --check`：通过

此前探索性全量运行曾出现一次提交评测 worker 的间歇性失败；单测和该测试文件单独运行均通过，随后完整回归通过，最终版本再次全量通过。该现象保留为后续测试隔离性观察项，不作为本候选的当前失败。

## 发布状态

候选已快进推送到远程 `main`，服务器发布到 `cbc5710`。发布前将服务器原有工作树的全部未提交/未跟踪改动保存为 `stash@{0}`：`codex-preserve-before-deploy-20260912`，并保留数据库备份 `/var/backups/codesense-predeploy-20260912.sql`（`600` 权限）。未覆盖或删除原有改动。

数据库维护成功创建/确认 `password_reset_tokens`、`email_verification_tokens`、`auth_identities` 表及用户验证字段；应用、两个 RQ worker、Nginx、Redis、MySQL 均 active，Nginx 配置检查通过。公开域名 `/healthz`、`/readyz`、`/login`、`/forgot-password`、`/register/email` 均返回 `200`；未知账号密码找回提交返回通用提示，未发送真实邮件或创建测试账号。当前发布结论为 `published`，SMTP 配置已存在但真实邮箱收发闭环仍需后续使用实际测试邮箱确认。
