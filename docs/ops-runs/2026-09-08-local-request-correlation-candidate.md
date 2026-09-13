# CodeSense 本地优化候选：请求与 LLM 轨迹关联

## 运行元数据

- automation：`codesense-2`
- run id：`codesense-20260908-local-request-correlation`
- 运行时间：`2026-09-08 10:23:45 +08:00` 起，报告在本轮结束前归档
- 候选 worktree：`E:\CodeSense\源代码\.worktrees\local-opt-20260908`
- 候选分支：`codex/local-opt-20260908`
- parent commit：`1c2356ce399b7b2aefed785afacee706c2e65647`
- candidate code commit：`3283b0a0477ae75df21015783c22ce8b71127bf8`
- parent → candidate code diff SHA-1：`8d49b74316235c4f27079eeebcf1fe88d910ff16`
- 代码 diff：`app.py`、`services/llm_client.py`、`tests/test_app.py`、`tests/test_llm_client.py`；`+67/-4` 行
- 结果：`keep local candidate`
- release：`needs_human`
- stop_reason：`preexisting_full_suite_failures_block_observability_exception`

本轮没有修改主工作树、生产数据库、生产 Redis、服务器文件、Nginx、systemd 或凭据。主工作树 `E:\CodeSense\源代码` 的既有未提交改动保持不变。

## 观测复盘与选题

最新服务器报告为 [`2026-09-08-automation-0333-version-drift-observe-only.md`](2026-09-08-automation-0333-version-drift-observe-only.md)。服务器资源、5xx 和服务状态正常，但仍有 `125.733s` 最大请求、2 条超过 30 秒；当前 journal 没有稳定的 `request_id`、`attempt`、provider latency 或 fallback 字段。线上 HEAD 与 `origin/main` 均为 `1c2356ce399b7b2aefed785afacee706c2e65647`，版本门禁在服务器侧仍要求只读，未执行服务器优化写入。

更高优先级的 L0 durable-job 候选（Stage1/2/3、forum、companion、STT 等长调用完整移出 Gunicorn）仍需要真实 Redis/worker/生产 MySQL、进程重启、权限和完整交互门禁，不能用本地单元测试替代。本轮选择同一服务器缺口对应的一个可在当天隔离验证的 L1 小切片：让 Flask 请求内生成的 opaque id 自动关联现有脱敏 `llm_trace` 与访问/慢请求日志。

## Planner / Implementer / Interaction Reviewer / Test Reviewer / Coordinator

### Planner

- 假设：`SharedLLMClient.chat` 和 `chat_stream` 在 Flask 请求线程内可读取 request-local `g`；独立 RQ/线程 worker 没有 Flask request context，应继续使用现有随机 opaque id。
- 影响面：只有应用日志相关字段和 LLM trace 关联字段；不改变 provider 顺序、重试/退避、cache、single-flight、SSE、队列、数据库、Redis、session、upload、模型调用次数或 UI。
- 回滚点：反向移除 `3283b0a`；不涉及 schema、配置、依赖、数据清理或迁移。
- 明确边界：这是应用内关联 id，不是完整 W3C Trace Context 传播，也不接受或回显客户端 `X-Request-ID`。

### Implementer

- `app.py` 在现有 `before_request` 计时 hook 中生成 `str(uuid.uuid4())`，写入 Flask `g.codesense_request_id`。
- `app.py` 在既有 access/slow-request 日志末尾增加 `request_id=<uuid>`；没有加入请求体、header、用户身份或响应 header。
- `services/llm_client.py` 增加 `_flask_request_id()`，只有 `has_request_context()` 为真时读取 `g`；`chat` 和 `chat_stream` 仅在 caller 未显式传 `request_id` 时使用该值。
- `tests/test_llm_client.py` 验证 request-local id 继承且 prompt 不进入日志；`tests/test_app.py` 验证访问日志出现 bounded UUID-shaped id。

### Interaction Reviewer

结论：候选代码范围内通过。

- 不接收或回显客户端 request id；id 为应用生成的 UUID，低可预测且不含用户文本。
- 现有显式 `request_id` 优先级保留；没有增加模型调用、重试、fallback、缓存或回复内容变化。
- trace 与访问日志只增加 opaque correlation id；没有写入 prompt、代码、响应、邮箱、用户身份、token、凭据或异常正文。
- 后台 worker 没有 Flask context 时沿用原有每次调用随机 id；未改变 durable worker 的队列参数或数据库边界。

### Test Reviewer

隔离运行设置：

- Python：`E:\anaconda\envs\student-eval\python.exe`。
- seed：从 `E:\CodeSense\源代码\instance\dev_student_code_review.db` 复制到候选 worktree 的临时 `.run-data` 目录；测试写入只发生在候选临时 SQLite。
- Redis：使用候选专用 DB `6/7/8/9/10/13/14/15` 做分次运行；一次错误尝试使用 DB16，因本机 Redis DB 数量限制自动降级为 worktree 文件 session/cache，未接触 DB0。
- session/log/upload：均在候选 worktree 临时目录；未读取或打印 `.env`。

验证结果：

| 检查 | parent baseline | candidate | 结果 |
| --- | --- | --- | --- |
| 相关回归（LLM/app/SSE/teacher） | `31 passed, 1 failed` / `45.59s` | `34 passed` / `89.16s` | candidate target pass；parent 的既有 SSE 失败被分类 |
| 完整 pytest | `405 passed, 1 failed` / `97.81s` | `407 passed, 1 failed` / `95.65s` | 同一既有 SSE 失败仍存在 |
| 完整 pytest，排除两个已确认的既有/fixture failure | — | `406 passed, 2 deselected` / `173.95s` | pass with explicit exclusions |
| request-correlation focused tests | — | `2 passed` / `2.27s` | pass |
| submission worker 单项复跑 | — | `1 passed` / `2.43s` | 全套中的失败未能在单项复现 |
| `python -m compileall -q app.py services tests` | — | exit `0` | pass |
| `node --check static/js/sse-client.js` | — | exit `0` | pass |
| `git diff --check` | — | exit `0` | pass |

失败分类：

1. `preexisting_regression`：`tests/test_ai_sse_routes.py::test_assignment_generation_streams_model_tokens` 在 parent 和 candidate 均失败，测试期望两个 `delta`，当前远端已有的统一流式实现返回一个合并 `delta`；本候选没有修改 SSE 文件。该失败阻塞“全套测试通过”门禁。
2. `fixture_isolation`：在排除上述 SSE 项后，全套曾出现 `tests/test_submission_worker.py::test_formal_worker_updates_submission_in_isolated_database` 的 pending/evaluated 断言失败；同一测试以正确 seed 单项重跑 `1 passed`，并且候选没有修改 worker/queue 文件，归类为全套异步 fixture 干扰，仍需后续修复测试隔离。
3. `not_exercised`：未访问真实 provider、未启动 Gunicorn、未采集部署后真实 `llm_trace`，未接入 OTel collector；本候选只验证现有 logger 和 Flask test context。

### Coordinator

- 代码候选 `keep`，因为相关测试、静态检查、脱敏审查和隔离单项验证通过。
- 不能以“排除失败后 406 passed”代替完整 suite 绿灯；因此不适用纯 observability 自动发布例外。
- 不合并到本地 dirty `main`，不 push remote `main`，不执行服务器 `update.sh`。
- 后续人工需要先处理/固定上述两个现有测试门禁，再重新在最新 remote main 上运行完整 suite；之后才能重新评估该候选的自动发布资格。

## 公开实践、版本和可验证机制

实施前复查了直接来源（2026-09-08）：

1. [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)：官方页面标记 `Stable`；LogRecord 将 `TraceId`、`SpanId`、`EventName` 和 `Attributes` 作为可关联的字段。适配机制是保留现有日志库，在日志事件中增加受限 correlation id；本实现不声称已经产生 OTel TraceId/SpanId。
2. [OpenTelemetry Logging](https://opentelemetry.io/docs/specs/otel/logs/)：官方当前日志规范页面（2026-09-08 复查）；说明现有日志系统可映射到统一日志模型，并强调通过执行上下文和结构化事件做日志关联。适配机制是沿用现有 Python logger，不引入 SDK 或 collector 依赖。
3. [Flask 3.1.x Request Context](https://flask.palletsprojects.com/en/stable/reqcontext/)：官方 3.1.x 文档；请求期间 `g`、`request` 等 context-local 对当前处理线程可用，请求结束后 context 被弹出。适配机制是只在 `has_request_context()` 为真时读取 `g.codesense_request_id`，worker/独立测试不依赖 Flask context。
4. [W3C Trace Context Recommendation](https://www.w3.org/TR/trace-context/)：W3C Recommendation 页面；定义 HTTP context 信息传播和请求的唯一标识。适配边界是本轮只生成应用内 opaque id，不接受客户端 header，不冒充跨服务 Trace Context；若未来接入真正分布式 trace，需单独增加 header 校验/传播和 exporter 门禁。

## Server read-only gate and release decision

本轮通过现有 Workbench 只读核对：

- server HEAD：`1c2356ce399b7b2aefed785afacee706c2e65647`。
- server `origin/main`：`1c2356ce399b7b2aefed785afacee706c2e65647`。
- server tracked worktree：clean；未读取或记录既有未跟踪条目名称/内容。
- `codesense.service`、ability worker、submission worker、nginx、redis、mysqld：均 `active`。
- `healthz=200`、`readyz=200`、`login=200`；readyz database check 为 `ok`。
- 未执行 server write lock、snapshot、reload/restart/deploy、数据库/Redis/IAM/网络/凭据写入。

候选是纯 observability 方向，但发布例外的必要条件包含“本地隔离全套测试通过”；当前 parent/candidate 仍有上面记录的完整 suite failure。因此：

- release：`needs_human`
- push remote main：`no`
- execute `/var/www/codesense/update.sh`：`no`
- rollback：`not_applicable`；候选尚未进入 remote/server，若人工批准后发现问题，优先回到 parent `1c2356c` 或 `git revert 3283b0a`，无数据回滚。

## Stop reason

`preexisting_full_suite_failures_block_observability_exception`

## 后续隔离修复（2026-09-08）

复跑确认 SSE 失败的根因是测试污染了本机 Redis DB0：固定 prompt 的 provider 响应被缓存，后续测试命中缓存后按 64 字符重放，因而只有一个 `delta`，并非生产流式逻辑改变。`tests/test_ai_sse_routes.py::test_assignment_generation_streams_model_tokens` 现对该 provider 分片断言禁用共享 cache 读写，确保测试始终调用 fake provider 并验证真实分片边界；没有修改线上 SSE 行为。

修复后的验证：SSE 文件 `6 passed`；submission worker 单项 `1 passed`；使用不可达的本地 Redis 地址隔离外部缓存后完整 pytest `408 passed`（`322.10s`）。
