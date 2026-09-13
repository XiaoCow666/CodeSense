# CodeSense 本地优化运行报告：脱敏 LLM 请求轨迹

## Run metadata

- 运行时间：2026-09-06 10:12:48–10:17:36（Asia/Shanghai）
- 运行类型：local optimization / isolated worktree
- 隔离 worktree：`E:\CodeSense\local-optimization-20260906`
- 分支：`codex/local-opt-20260906`
- parent commit：`6f0738a6f360d804f47d5169e97c5342c83f1e4d`
- candidate code commit：`d6529726b8ea533537a1fbcf649d423fc12e6c3e`
- parent→candidate code diff SHA-1：`1432d9da1e6e4e7d080822debf995c040fb4074e`
- candidate diff：`services/llm_client.py`、`tests/test_llm_client.py`；`+369/-2` 行
- 数据边界：未读取或打印 `.env`，未连接生产数据库/Redis，未修改服务器；测试使用 worktree 本地运行时资源

## 选择与假设

最新服务器报告 `2026-09-06-automation-0333-version-drift-observe-only.md` 确认线上 HEAD 在跨轮之间漂移，服务器侧候选停留在 observe-only。服务器仍将 L0 “移出 Gunicorn 的持久化 AI job”列为最高优先级；此前 RQ 提交候选仍因 Redis/worker/生产兼容门禁未完成而保留 `needs_human`，本轮不重复实现。

本轮选择一个可在本地完成、且不改变请求行为的 L1 小切片：在共享 LLM 客户端形成版本化、脱敏的单次逻辑请求事件。假设是：以现有 Python logger 输出一条结构化 JSON 消息，已经能够让脱敏运行报告按 request kind、provider/model、重试、队列等待、调用耗时和稳定错误分类聚合，而无需先引入 OpenTelemetry SDK 或改变线上依赖。

明确不在本轮完成的内容：完整调用方 request-kind 迁移、真实 OTel exporter/collector、`safe_zhipu_post` 的独立轨迹、图像生成轨迹、生产部署和真实 provider 访问。这些边界避免把低风险观测切片误报为完整 L1/L0 交付。

## 公开实践与可验证机制

实施前复查了直接来源（检索日 2026-09-06）：

1. [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/) 当前标记为 Stable，定义了 EventName、TraceId/SpanId、Severity、Body 和 Attributes；事件属性应承载具体发生时的上下文。本实现保留等价的事件名、版本、opaque request id 和受限属性，但不记录 body/prompt。
2. [OpenTelemetry semantic conventions for events](https://opentelemetry.io/docs/specs/semconv/general/events/) 当前标记为 Development，建议把状态变化、检查点和异步流程结果作为命名事件，并使用 occurrence-specific attributes。本实现为成功、缓存命中、provider error、流式中断和不可用状态分别写 `stop_reason`。
3. [OpenTelemetry GenAI semantic conventions for client spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md) 当前以仓库 `main` 的 Development 文档为准，要求逻辑 GenAI 调用覆盖自动重试的总时长，并在失败时使用 `error.type` 类别。本实现将每次逻辑调用汇总为一条事件，记录 attempts/retry_count、duration、error_class；没有复制尚未稳定的完整 prompt/output 属性。

这些来源只证明字段与生命周期的可验证机制，不证明 CodeSense 已完成线上可观测性。线上证明仍需部署后采集真实脱敏事件并比较基线。

## 角色产物

- Planner：确定 L1 低风险观测切片、白名单字段、回滚点为移除共享客户端 trace 逻辑；确认不触碰用户 dirty files。
- Implementer：仅修改共享客户端和定向测试；保留原有 provider 顺序、缓存、single-flight、重试、熔断、failover 和用户返回值。
- Interaction Reviewer：检查事件不含 prompt、代码、响应、邮箱、异常文本；成功重试不残留 error_class；fallback 只在 provider/model 改变时成立；调用方没有新增 UI 文案或额外模型调用。结论：pass。
- Test Reviewer：运行定向、相关回归、完整回归（含依赖阻断记录）、compileall 和 diff check。结论：候选代码门禁 pass，完整 suite 仍有环境依赖缺口。
- Coordinator：保留候选供人工审阅；不合并到 main、不推送、不部署。

## 实施内容

- `SharedLLMClient.chat` 和 `chat_stream` 增加可选 `request_kind`、`request_id` 参数，旧调用保持兼容。
- 记录一次逻辑请求的 `event_name`、`schema_version`、opaque `request_id`、白名单 `request_kind`、provider/model、stream/cache/fallback、attempts/retry_count、queue_wait_ms、llm_latency_ms、duration_ms 和 `stop_reason`。
- request id 无输入时使用随机 UUID；非 UUID 输入只保留 SHA-256 截断值，避免任意 caller 文本进入日志。
- provider/model 只保留最多 4 个已尝试值；错误只映射到 `AUTH_FAILED`、`RATE_LIMITED`、`TIMEOUT`、`NETWORK_UNAVAILABLE`、`UPSTREAM_ERROR`、`LLM_UNAVAILABLE` 等低基数类别。
- 日志事件使用现有 logger 的 `llm_trace {json}` 消息，不引入新包，不写 prompt、代码、响应或异常 message。

## 验证与 baseline 对比

| 检查 | parent baseline | candidate | 结果 |
| --- | --- | --- | --- |
| `tests/test_llm_client.py` | 7 passed / 0.48s | 11 passed / 0.65s | pass |
| 相关回归（LLM/SSE/Stage1/demo） | 未改动前通过 | 20 passed / 16.05s | pass |
| 完整 pytest 首次执行 | — | collection error：缺少 `fakeredis` | blocked by environment |
| 完整 pytest（排除 `tests/test_ability_analysis_queue.py`） | — | 364 passed / 125.41s | pass with scoped exclusion |
| `py_compile` / `compileall -q .` | — | exit 0 | pass |
| `git diff --check` | — | exit 0 | pass |

`fakeredis` 缺口来自现有 `requirements-test.txt` 的 `fakeredis[lua]==2.31.3` 声明，不是本候选新增依赖；本轮没有为了通过测试修改依赖或安装包。完整队列测试需在补齐声明依赖后重跑。

固定 evaluator 的场景覆盖：provider 瞬时连接错误后成功、primary 连续失败后 failover、鉴权失败、首 token 后流式中断、缓存/请求 kind/request id 脱敏。没有真实 API key、真实 provider、真实 Redis 或生产 MySQL 访问。

## 失败分类与资源对比

- `environment_failure`：`fakeredis` 未安装导致一个测试文件无法收集。
- `not_exercised`：真实 provider latency、429/断线、真实队列等待、进程重启、生产日志采集和 OTel collector 未验证。
- `version_drift`：服务器当前观察到的 HEAD `1d81744…` 与本地 `origin/main` 当前 `c2c3136…` 及本地 parent 不一致，来源未核验。
- `regression`：未发现；定向和排除阻断后的完整回归均通过。

本候选不改变网络调用数量、重试等待、数据库连接、Redis key 或进程资源策略；因此没有可宣称的线上 CPU/内存/延迟改善。新增成本是每次共享 chat/chat_stream 请求一条小型 JSON logger 消息，需部署后用实际日志量评估磁盘和轮转影响。

## 发布门禁与回滚

结论：`keep` local candidate，发布状态 `needs_human`，`stop_reason=version_drift_and_missing_online_trace_canary`。

不能发布的原因：

1. 服务器自治报告已明确线上版本漂移，且没有本轮候选在当前服务器代码上的兼容复核。
2. trace 是后端运行时行为，尚未在服务器现有 `update.sh` 流程、systemd/Gunicorn 日志和真实脱敏报告中验证字段可采集、轮转影响和健康回归。
3. 完整队列测试的 `fakeredis` 环境缺口尚未修复；虽然与本候选无直接依赖，但每日发布门禁要求最终候选回归集可复现。

回滚点：候选仅有两个代码文件；若后续获准整合，回滚为恢复到 parent commit，或反向移除 `d6529726` 的共享客户端 trace 改动，不涉及数据库迁移、Redis 清理、配置写入或数据删除。

本轮实际服务器写变更：0。没有合并、push、执行 `update.sh` 或生产数据迁移。

## stop_reason

`needs_human`：本地代码候选可复现并通过已可用测试，但缺少 fakeredis 完整环境、线上版本来源确认和部署后真实事件采集；保留候选，等待下一轮兼容验证/人工发布决策。
