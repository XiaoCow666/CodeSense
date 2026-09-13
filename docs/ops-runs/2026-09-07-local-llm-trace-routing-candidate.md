# CodeSense 本地优化候选：LLM trace request_kind 路由

## 运行元数据

- automation：`codesense-2`
- run id：`codesense-20260907-llm-trace-routing`
- 运行时间：`2026-09-07 10:32:55 +08:00`
- 候选 worktree：`E:\CodeSense\local-optimization-20260907`
- 候选分支：`codex/local-opt-20260907`
- parent：`3453d66d344b5a3e277a9bab4ff16c0427c33100`
- candidate code commit：`0d8d37dc5b87c8fd00b0b9ba5bdeb6e53facffd3`
- parent → candidate diff SHA-1：`a2c224c612fd83d744fba037a71a7ff096b0dd49`
- 结果：`release candidate`
- release：`qualified_under_user_observability_exception`
- stop_reason：`none_predeploy; online_trace_canary_deferred_by_policy`

本轮没有修改主工作树、生产数据库、生产 Redis、服务器文件或凭据；主工作树 `E:\CodeSense\源代码` 的既有未提交改动保持不变。

## 选题与范围

最新服务器报告为 `E:\CodeSense\源代码\docs\ops-runs\2026-09-07-automation-0334-version-drift-observe-only.md`。报告记录了 24 小时 Gunicorn 最大延迟 `70.614101s`、超过 30 秒 `12` 条、超过 60 秒 `3` 条，同时当前日志没有 request id、attempt、provider latency、fallback 等可比较字段。更早的 L1 候选已经在 `SharedLLMClient` 写入脱敏 `llm_trace`，但大多数生产调用点仍使用默认的 `interactive` 标签，无法按 Stage、提交评测、STT、批处理等长尾来源聚合。

本轮只处理这个紧邻的 caller-routing slice：为生产 `chat`/`chat_stream` 调用补上已有白名单中的明确 `request_kind`，覆盖 `stage1`、`stage2`、`stage3`、`companion`、`stt`、`submission`、`ability_analysis`、`code_advice`、`batch`、`background` 和 `interactive`。没有改变 provider 顺序、重试/退避、cache、流式协议、数据库、Redis key、worker 配置、UI 或模型调用次数。

回滚点是单一提交 `0d8d37d`；该提交没有 schema 或依赖变化，回滚只需撤销调用点标签及兼容适配器，再按既有发布流程验证。

## Planner / Implementer / Interaction Reviewer / Test Reviewer / Coordinator

### Planner

- 保留已经存在但仍缺少生产运行时门禁的 L0 durable-job 候选，以及前一轮 L1 trace 基础候选，不重复实现。
- 选择当天可在隔离环境完整验证、且对线上行为无改变的 request-kind 路由补全。
- 明确假设：线上 parent 已支持可选 `request_kind` 并用 whitelist 归一化；历史注入 fake/第三方 client 可能仍没有该参数。

### Implementer

- 修改 11 个生产文件，新增 `tests/test_llm_request_kind_routing.py`。
- `StructuredDecisionModel` 对旧 client 仅在 Python 明确报告 `unexpected keyword argument 'request_kind'` 时走一次无参数兼容调用；该错误发生在函数签名绑定阶段，不会重放已开始的 provider 请求。
- 新增 AST 守门测试，检查列出的生产调用点都有 `request_kind`，并且字面值属于 `services.llm_client._REQUEST_KINDS`。

### Interaction Reviewer

- 结论：本地通过。
- 没有新增模型请求、前端交互或持久化状态；已有流式 chunk、fallback、cache、重试和错误脱敏路径保持原语义。
- trace 仍只使用低基数标签；不记录 prompt、代码、响应、身份或异常正文。

### Test Reviewer

目标与相关回归：

- `tests/test_llm_request_kind_routing.py`：`1 passed`。
- `tests/test_stage3_agent_contracts.py tests/test_llm_request_kind_routing.py tests/test_llm_client.py`：`32 passed`。
- AI SSE、Stage3、队列、worker、ability、teacher advisor 相关集合：`79 passed`，`32.83s`。
- 候选隔离全套：`399 passed`，`115.06s`；使用独立 seed SQLite 和 Redis DB12，运行时关闭 warning 输出以保持日志可读。
- parent 基线隔离全套：`398 passed`，`121.73s`；使用同一 seed SQLite 和 Redis DB11。
- 另一次带 warning 输出的候选全套为 `399 passed`，`1095 warnings`，`123.40s`。
- `compileall`、`node --check static/js/code_submission.js`、`git diff --check`：通过。

失败分类：最初复用 Redis DB2 的全套运行出现 9 个失败：8 个是已有 Stage3 fake client 不接受新 keyword，已由精确签名兼容适配器修复；1 个 assignment SSE 失败来自复用 Redis 中的旧 LLM cache 合并 chunk。切换全新 Redis DB14 后候选全套通过；该失败不是生产逻辑回归。

开发/测试使用 `E:\anaconda\envs\student-eval\python.exe`。没有读取或打印 `.env`；候选和基线只使用隔离 seed DB、Redis DB 与测试运行目录。临时基线 worktree 已移除，候选 worktree 保留供复核。

## 公开实践复查

在实现前复查了以下直接来源（2026-09-07）：

1. [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)：Stable；使用事件名和属性承载可过滤、可分组的结构化上下文，避免把 prompt/响应正文塞进日志。
2. [OpenTelemetry Events semantic conventions](https://opentelemetry.io/docs/specs/semconv/general/events/)：Development；事件名和低基数属性用于 checkpoint/outcome 聚合，错误类型适合稳定分类。
3. [OpenTelemetry GenAI client spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)：Development/current public repository；建议记录 operation/provider/model 等观测维度，并避免 prompt、输出和用户身份成为 telemetry 内容。

本候选的机制是把现有 trace 的默认标签替换为生产调用点的显式、有限集合；不引入新的 telemetry backend，也不把高基数业务内容写入日志。

## 服务器只读门禁与发布决定

服务器目标为 ECS `i-f8zbujornnh55dsydozz`，使用现有 Workbench 连接，只做了只读核验：

- `/var/www/codesense` HEAD：`950c233c8ff5c6ae8478bff0c64ed20c45e1f9a1`；服务器 `origin/main` 仍为同一 commit。
- 本地最新 `origin/main` 为 `3453d66d344b5a3e277a9bab4ff16c0427c33100`。`950c233c..3453d66c` 的差异仅为项目理解/README/图片等文档资源，没有运行时代码冲突；服务器仍未同步到目标 commit。
- 服务器 tracked worktree clean，但保留三个未跟踪条目：`Miniconda3-latest-Linux-x86_64.sh`、`backup_before_clean.sql`、`clean_scores.py`；未触碰。
- `codesense.service`、ability worker、submission worker、nginx、`redis.service`、`mysqld.service` 均 active。
- HTTPS `/healthz` 返回 `200 {"status":"ok"...}`，`/readyz` 返回 `200` 且 database `ok`，`/login` 返回 `200 text/html`。
- 三个服务近 24 小时 journal 中字面 `llm_trace` 计数均为 `0`；没有安全、可归因的线上 request-kind trace canary。未为取得 canary 发送真实 LLM 请求，避免生产数据/模型调用污染。
- 现有脚本为 `/var/www/codesense/update.sh`，服务器权限为 `0644`，hash 为 `2936c03923a86ac9e2e9ac37b78a2d7717d96588cebd4f58d056407546712ade`。只读检查确认它会 `git pull`、安装 requirements、安装/启停 systemd worker、调整 `.env` 权限和运行目录 owner、daemon-reload 并重启 app；若未来通过授权门禁，应显式用 `bash /var/www/codesense/update.sh`，并保存脚本影响范围与回滚证据。

用户在本轮明确调整了发布门禁：对无 UI、无 schema、无依赖、无运行时行为变化的纯 observability 候选，只要本地全套测试和服务器健康检查通过，即可自动发布；真实线上 trace canary 改为部署后的后续观测项，不阻塞发布。本候选满足该例外条件。服务器版本漂移已核查为文档/资源差异，无运行时代码冲突；发布前仍须在隔离整合树获取最新 remote `main`，并保留服务器三个未跟踪条目。主工作树和服务器未跟踪文件均未被覆盖。

## Coordinator 结论

`release candidate` / `release=qualified_under_user_observability_exception`。本地证据证明调用点标签和兼容适配器，服务器只读健康检查通过；线上 trace canary 不再是本类候选的发布前置条件。按用户新规则继续整合、推送和部署，部署后记录健康检查，并把 trace 聚合作为后续观测项。
