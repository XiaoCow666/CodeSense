# 任务四：提交失败恢复与可观测性证据

## 问题/目标

`POST /api/submit` 的旧调用仍使用 `code`、`assignment_id`，默认语言仍为 `cpp`。同步评估器抛出异常时，提交已经以 `pending` 写入数据库；目标是在不改变旧响应契约的前提下，保证记录可恢复为 `failed`，并留下可定位日志。

## 复现与证据

在测试中用 `patch('routes.api.evaluate_cpp_code', side_effect=RuntimeError(...))` 调用真实 `/api/submit` 路由。修复前异常分支没有回滚会话，也没有保存异常原因；这会让失败记录缺少恢复信息。测试验证 HTTP 仍为 `500`，同时检查数据库状态和应用日志。

## 计划改动

只修改 `routes/api.py:submit_code` 的同步评估异常分支：先 `db.session.rollback()`，再将同一提交标记为 `failed` 并保存反馈，最后用 `current_app.logger.exception` 记录 `submission_id`。不改请求字段、成功响应、错误状态码、队列接口或数据库结构。

## 学习总结

人工排查沿着 `pending -> evaluated/failed` 状态路径追踪，并把“评估器异常后是否可恢复”写成可证伪假设。拒绝统一错误码、幂等键和异步队列重构等过度设计，因为它们会改变公开契约，不能由当前故障证明必要。

## 验证结果

`python -m pytest tests/test_task4_submission_failure_recovery.py -q`：`1 passed`。回归测试覆盖旧请求字段、500 响应、`failed` 状态、异常反馈和带提交 ID 的应用日志。
