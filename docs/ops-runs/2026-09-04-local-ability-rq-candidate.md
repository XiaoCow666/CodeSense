# CodeSense 本地优化运行报告：正式账号能力分析 RQ 先导切片

## Run metadata

- run_id：`codesense-local-20260904-1112`
- 运行时间：2026-09-04 10:08–11:12（Asia/Shanghai）
- 续跑验证：2026-09-04 13:43–13:49（Asia/Shanghai）
- parent commit：`5bd66e72cb51a9d4853e834f6b94078cf1a0e928`
- candidate branch/worktree：`codex/local-opt-20260904` / `E:\CodeSense\local-optimization-20260904`
- candidate tree（不含本报告）：`95ed3a9722011c145be000ac8aafc203000dffa7`
- candidate diff hash（不含本报告）：`ef379aff2f5b67c05813e3393c42e52e1a965e0d`
- 最新脱敏服务器报告：`2026-09-04-automation-0331-observe-only.md`
- 服务器报告中的线上 HEAD：`5bbd262822ede77a3a502eb2afbbd461c8e51396`
- 本地 `origin/main` 观测值（本次续跑 fetch 后）：`dc5bda8dcfebb5f965a97013fad26fb0b8e33cf4`
- 实际服务器写变更 / 部署 / 数据迁移：0 / 0 / 0
- Coordinator decision：保留为本地待合并候选；启用和部署为 `needs_human`
- stop_reason：`needs_human`（真实 Redis 已在隔离端口核验；仍未核验线上 MySQL、独立 OS 进程故障和完整 L0 链路）

## 当日事实与优先级

服务器侧仍应优先保持只读、可比较的 24 小时观测，并补齐无需暴露凭据的只读数据库聚合路径；监听面、root 运行、systemd、网络与数据库仍属于人工审批范围。本地侧 L0 继续是最高优先级：最新真实窗口中 Stage1/2/3 p95 约 91–101 秒，`code_advice` p95 约 45 秒，`/api/stream/ability-analysis` 有 169 次请求、p95 约 9.67 秒；journal 同时有大量 rate-limit/retry/provider-failure 命中。

本轮只实现 L0 的一个先导切片：**正式账号能力分析从进程内 daemon thread 切换到可选的 RQ/Redis 持久队列与独立 worker**。公开体验继续使用原线程和临时数据库，不扩展到 Stage1/2/3、forum、companion 或 code advice，因此不能宣称完整 L0 已完成。

## 公开实践来源、版本与采用机制

1. [RQ 2.11.0 PyPI](https://pypi.org/project/rq/)：2026-08-17 发布，要求 Python >=3.10；项目说明当前运行时要求 Redis >=5 或 Valkey >=7.2。候选固定 `rq==2.11.0`，线上启用前必须另行核验 Redis 版本。
2. [RQ Jobs 官方文档](https://python-rq.org/docs/jobs/)：定义 queued/started/finished/failed 等生命周期、job timeout、queue TTL、result/failure TTL、heartbeat 和持久化查询。候选把这些状态映射为应用的 queued/started/completed/failed/expired。
3. [RQ Workers 官方文档](https://python-rq.org/docs/workers/)：worker 在独立生命周期内领取任务、登记 StartedJobRegistry/heartbeat 并在完成后写入终态。候选增加独立 `tasks.ability_worker`，强制关闭旧进程内线程与 preset scanner，并复用单个 production app 实例。
4. [RQ 官方仓库与 v2.8+ unique jobs](https://github.com/rq/rq)：显式 `job_id` + `unique=True` 提供原子去重。候选同时使用短 Redis lock 串行化“删除旧终态并显式重试”的边界。
5. [RQ JSON serializer 文档](https://python-rq.org/docs/jobs/)：默认 pickle 不适合不可信数据；JSON serializer 只支持基本类型。候选队列与 worker 都固定 JSON serializer，只传不透明的 `AbilityTrend.id`，任务描述和 meta 不含学生 ID、prompt 或代码。

## 假设、变更点与可验证机制

### 假设

把正式账号能力分析改为 Web 进程只做“状态预留 + Redis 入队”，独立 worker 再查询数据库并调用 provider，可以让请求快速返回、跨 Web worker 去重，并在刷新或 Web 进程重启后保留 job 状态；不需要把代码正文复制进 Redis。

### 最小变更

- 新增 RQ queue adapter：持久状态、唯一 operation id、短锁、TTL、JSON serializer、稳定错误映射。
- 新增独立 worker 入口：只运行 ability queue，禁用旧 async thread/preset scan/access log 初始化。
- 正式账号在 feature flag 为 `rq` 时走 durable queue；demo 始终保留临时库线程路径。
- 入队前用 `status + last_updated` 条件更新预留 `processing`，防止并发 stale request 和 MySQL 秒级时间戳竞态；入队失败落到 `failed`。
- failed 任务只有用户显式刷新（`force=True`）才重试，普通页面/SSE 不自动重放整项 provider 调用。
- 刷新与 SSE 给出可恢复提示；Redis/RQ 原始错误、学生 ID、provider 正文不写入该链路日志或响应。
- 固定生产依赖 `rq==2.11.0`；固定测试依赖 `fakeredis[lua]==2.31.3`。

### 数据与运行隔离

- 未读取或复制 `.env`，未打印凭据。
- 测试数据库：`E:\CodeSense\local-optimization-20260904\instance\automation_test.db`（worktree 内，Git ignored）。
- session：`E:\CodeSense\local-optimization-20260904\flask_session`。
- uploads/logs：候选 worktree 自己的目录；未复用主 checkout 可写目录。
- Redis evaluator：单元测试使用进程内 `fakeredis[lua]` 独立 server object；续跑另以临时 Redis 8.10.1 进程（`127.0.0.1:6398`、隔离 DB）完成真实写入/读取/worker 测试，未连接主 Redis。
- 主 worktree 的既有未提交改动未被写入。`routes/users.py` 的用户改动位于 276 行以后，本候选位于 267–275；仍要求人工合并时复核邻接 hunk。

## Baseline / candidate evaluator

### Baseline

- detached baseline worktree：parent `5bd66e7`。
- 同一既有回归集：9 passed / 1 failed，43.88 秒。
- 失败分类：`baseline_only_test_failure`。`test_demo_analysis_is_real_refreshable_and_stays_out_of_formal_db` 被旧的 SharedLLMClient availability gate 阻断；candidate 保留 demo 注入 evaluator 契约后通过。
- 基线 worktree 已在确认 clean 后移除；结果保留在本报告中，可由 parent commit 重新生成。

### Candidate

- RQ/状态/隐私核心 evaluator：13/13 passed。
- 完整选定集：23/23 passed，47.34 秒（新增 13 个核心测试，不能与 baseline 用总时长直接比较）。
- 既有同集回归：10/10 passed；demo/正式库隔离未回归。
- 完整仓库回归：`373 passed`，191.73 秒（`pytest -q --disable-warnings`）。
- 真实 Redis 8.10.1 smoke：连接/版本读取、12 路并发去重（1 created）、独立 `SimpleWorker` 完成、失败 job 持久化、显式 requeue 恢复均通过。
- 覆盖：持久 job fetch、并发重复提交去重、终态后显式重试、真实 `redis.ConnectionError` 脱敏、新 worker 对象领取既有任务、Web 不启动 provider thread、failed 不自动重放、completed 刷新状态、同秒完成竞态、worker 单 app/关闭旧线程、demo 临时库隔离、SSE/code-advice 回归。
- Python 3.10.18：目标文件 import/grammar 与 `compileall` 通过。
- `git diff --check`：通过。
- Interaction Reviewer：approve。
- Test Reviewer：approve（仅限本先导切片）。

## 失败分类与修正记录

- `test_harness_dependency`：fakeredis 基础安装不支持 RQ unique/lock 的 Lua；固定 `fakeredis[lua]` 后通过。
- `flask_proxy_boundary`：初版传递 `current_app` LocalProxy；改为真实 app object。
- `duplicate_paid_call_risk`：初版 failed 会被普通刷新自动重放；改为只有显式 force 可重试。
- `sensitive_error_propagation`：初版部分 Redis 异常可能逃逸；所有 queue/status 错误统一为无连接详情的稳定异常。
- `queued_state_ux`：初版排队期间 DB 仍为 failed/outdated；改为入队前条件预留 processing。
- `mysql_timestamp_race`：初版入队后条件更新可能被秒级时间戳误命中；状态预留移到入队前，新增同秒完成测试。
- `worker_double_init`：初版 worker 可能构造第二 app；改为设置 `FLASK_CONFIG` 后复用 `app.py` 唯一 module app，并强制关闭旧线程开关。

## 已知边界、回滚与下一步

RQ/Redis 只提供 at-least-once 类型的工作基础；provider 已成功但数据库 commit 前 worker 崩溃时，不能严格证明重试不会重复计费。因此本候选关闭 RQ whole-job automatic retry，失败后要求用户显式重试。尚未验证：真实线上 MySQL 秒精度、独立 OS 进程 kill/restart、slow provider、hard timeout，以及 Stage1/2/3/forum/code-advice 全链路；429、断流和错误脱敏已用模拟 provider 覆盖。

回滚方式：不设置 `ABILITY_ANALYSIS_QUEUE_BACKEND=rq` 即继续使用原线程路径；代码回滚只需撤销本候选 diff。没有 schema 迁移、生产数据改写或服务器配置需要反向操作。启用前人工门禁必须包括：核验线上 Redis 版本与隔离 DB/namespace、准备 worker systemd proposal、真实 seed/MySQL+Redis 故障测试、确认线上 HEAD/rebase、再决定是否合并。
