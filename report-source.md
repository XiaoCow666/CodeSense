# CodeSense 自迭代 Agent Team 与自治运维 Deep Research

## 研究元数据

- 日期：2026-09-04（Asia/Shanghai）
- 读者：CodeSense 项目负责人、服务器运维执行者、本地研发任务执行者
- 研究问题：哪些开源项目已经把 Agent Team、任务状态、自动迭代、评估、回滚和人工介入做成了可复用形式；哪些机制适合 CodeSense 的服务器与本地两条闭环。
- 研究范围：官方 GitHub 仓库、官方文档、官方论文；同时结合 2026-09-03/04 对 CodeSense 线上服务器的实际只读观测。
- 明确排除：把某个项目的 README 宣传语当成生产可靠性证明；未经验证就部署新框架、修改数据库 schema、开放端口或改变本地代码。
- 研究口径：
  - **实现证据**：官方代码、API 文档或论文可以直接支持的机制。
  - **项目自述**：项目 README 对自身能力、性能或成熟度的描述，需保守使用。
  - **工程映射**：将实现证据应用到 CodeSense 的设计推论，不等同于来源原话。

## Executive answer

没有一个开源项目可以原样复制成 CodeSense 的“自动优化大脑”。目前最可迁移的成熟形态是一个混合闭环：

1. **角色和 SOP** 用 MetaGPT、ChatDev 的做法：角色职责、阶段输入输出、交接对象、循环上限显式化。
2. **确定性编排和状态** 用 CrewAI Flow、AG2、OpenHands 的做法：任务状态、计划账本、进度账本、暂停/恢复、结构化完成状态独立于聊天文本。
3. **服务器执行安全** 用 Kubernetes Controller/Operator、Temporal、LangGraph 的做法：desired state、幂等 reconcile、锁/版本校验、超时/重试、补偿和审批不由 LLM 自己决定。
4. **自主迭代评估** 用 SWE-agent、OpenHands Benchmarks、autoresearch 的做法：隔离 candidate、冻结 evaluator、记录完整轨迹、和 baseline 比较后 keep/discard/rollback。
5. **观察真实使用** 用 OpenTelemetry 的 trace/metric/log 组合：把一次用户请求、模型调用、工具执行、验证和回滚串在同一条可脱敏轨迹里。

因此，CodeSense 当前不应把 CrewAI/Temporal/Kubernetes 等完整运行时直接塞进 2 核服务器。第一阶段用现有 Workbench + 定时 Codex 任务作为外层协调器，服务器上只执行白名单、可回滚的低风险操作；本地代码迭代另开任务，在隔离 worktree 中测试和验收。等任务频率、并发和变更复杂度达到阈值，再考虑引入持久化工作流运行时。

## 1. 开源项目调研

### 1.1 OPC 与“项目小组”形态

#### OpenOPC

[OpenOPC 官方仓库](https://github.com/HKUDS/OpenOPC)将自己定位为 Self-Built / Self-Run / Self-Grown 的一人公司操作系统。其 README 展示了公司/任务模式、工作区、通信邮箱、角色拥有的 work item、运行时会话和审批/停止控制。

可验证、值得借鉴的是它把“组织状态、任务状态、运行日志和工作空间文件”分开，而不是把所有上下文塞进一段对话。它更像产品形态参考；README 中的自治程度和成熟度属于项目自述，不作为 CodeSense 的可靠性证明。

#### OPC-Agents

[OPC-Agents 官方仓库](https://github.com/lulin70/OPC-Agents)展示了 Plan → Act → Observe → Reflect 的循环，并把 strategist、executor、reflector、consensus 和工具权限/审计拆开。它还提供跳过反思、记忆开关、加密 key 等运行配置。

这里最重要的不是“反思”这个词，而是把执行、观察、反思和共识拆成不同阶段，并为工具调用保留权限/审计边界。由于该仓库的稳定性与生产数据没有被本研究独立验证，不能直接照搬其自评质量指标。

#### OPC Team

[OPC Team 官方仓库](https://github.com/HeiGeAi/opc-team)明确把状态机、决策日志、风险评分、分层记忆、SLA、runbook、handoff、red-team gate 和审批列为核心机制，并支持由主 Agent 组织子 Agent。

它对 CodeSense 最有用的启发是：Agent Team 不是“让几个模型自由聊天”，而是任务状态、决策证据、风险和交接物的集合。其 README 的实现范围和成熟度仍需按项目自述看待。

#### OneManCompany

[OneManCompany 官方仓库](https://github.com/1mancompany/OneManCompany)是另一种一人公司/多智能体产品化尝试。它适合观察角色、任务和交付物如何被包装成工作流，但不把产品定位当作服务器自动变更安全性的证据。

### 1.2 软件公司式 Agent Team

#### MetaGPT

[MetaGPT 官方 README](https://github.com/FoundationAgents/MetaGPT/blob/main/README.md)和[官方 Team 实现](https://github.com/FoundationAgents/MetaGPT/blob/main/metagpt/team.py)把产品经理、架构师、项目经理、工程师等角色放进一个“软件公司”，核心理念是把团队行为沉淀为 SOP。官方代码中 Team 按轮次运行，Role 有记忆/消息缓冲/动作列表，并有 react loop 上限、预算和空闲终止条件。

CodeSense 应采用的是“职责、产物、循环和预算显式化”，不是照搬软件角色名称。MetaGPT 自身的停止条件主要说明运行结束，不等于业务结果正确，因此仍需要独立验收器。

#### ChatDev

[ChatDev 官方仓库](https://github.com/OpenBMB/ChatDev)及其[ACL 论文](https://arxiv.org/abs/2307.07924)展示了 CEO、CTO、程序员、审查者、测试者等角色，通过 Chat Chain 约束阶段和沟通对象。官方工作流包含 loop counter、最大迭代次数和结束信号，并保留 Human-Agent-Interaction 的 reviewer 模式。

可迁移的是阶段化交接：需求/计划、执行、审查、测试、文档各自产出结构化结果。局限是大量终止与质量判断依赖提示词、文本标记和固定链路，不能让自然语言“完成了”直接代表生产变更成功。

#### CrewAI

[CrewAI 官方文档](https://docs.crewai.com/)把 Crew/Task 和 Flow 分层。Task 可定义 expected output、context、结构化输出、工具限制和 human input；guardrail 失败时将反馈送回 Agent，并限制重试；Flow 提供 start/listen/router、条件分支、循环、状态共享、持久化、resume/fork 和人工反馈。

这与 CodeSense 的方向最接近：开放式 Agent 只负责分析和计划，确定性 Flow 负责顺序、状态、验证和重试。要锁定依赖版本，不能把 LLM guardrail 当成唯一正确性证明。

#### AutoGen 与 AG2

[Microsoft AutoGen 官方仓库](https://github.com/microsoft/autogen)提供 RoundRobin、Selector、Swarm、Magentic-One、GraphFlow 等协作方式，Magentic-One 还将任务账本和进度账本分开，并组合最大消息数、token、超时、文本标记和自定义终止条件。官方仓库目前已标记 maintenance mode，因此只借鉴机制，不作为新项目的默认依赖。

[AG2 官方仓库](https://github.com/ag2ai/ag2)则把任务生命周期、progress/result/error、typed handoff 和外部化状态结构化；反馈循环示例把 reviewer approve 设计成明确状态转换，同时设置 max turns。它提醒我们：批准应该是一个受策略约束的事件，不应只是模型在文本里写出“APPROVE”。

### 1.3 可恢复执行与安全边界

#### OpenHands

[OpenHands 官方运行时文档](https://docs.openhands.dev/openhands/usage/architecture/runtime)与[安全文档](https://docs.openhands.dev/sdk/api-reference/openhands.sdk.security)展示了事件流、状态持久化、崩溃恢复、执行状态、stuck detection、等待确认和风险分析。其[Docker sandbox 文档](https://docs.openhands.dev/openhands/usage/sandboxes/docker)强调隔离、一致性、资源控制和最小挂载；local runtime 不应被误认为安全隔离。

CodeSense 要分离“决策面”和“执行面”：只读诊断 Agent、计划 Agent 与真正拥有服务器写权限的执行器不能拥有相同权限；执行器要能在中断后恢复、验证目标版本并拒绝越权动作。

#### Junior / OpenCompany

[Junior 官方仓库](https://github.com/JHostalek/junior)把持久任务队列、并行执行、cron、worktree 隔离、review mode、权限模式、成本跟踪、重试和 crash recovery 放在 daemon-worker 结构中。它适合本地定时优化任务的参考：队列持久化、每个任务独立 worktree、日志和人工合并边界。

[OpenCompany 官方仓库](https://github.com/zeenie-ai/OpenCompany)展示了后台 listener、持久上下文、受限子 Agent 数量、lead acceptance 和 recurring/event-driven workflow。该项目仍应视为新兴实现，不能把 README 自述的 durability 直接外推为 CodeSense 的生产保证。

### 1.4 评估、迭代和可观测性

#### SWE-agent 与 mini-SWE-agent

[SWE-agent 的 ACI 文档](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)说明，工具界面本身需要限制文件查看范围、校验编辑语法、确认空输出和提供精确搜索结果；[trajectory 文档](https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md)保存每一步的 thought/action/observation/state/query、配置和退出状态。

[mini-SWE-agent v2 文档](https://mini-swe-agent.com/v2/usage/mini/)采用线性历史和独立 subprocess，并区分确认模式与高权限模式。可迁移原则是先使用最小、可重放的执行面，再逐步增加编排；每个 shell 动作记录退出码、耗时和脱敏输出。

#### OpenHands Benchmarks

[OpenHands Benchmarks 官方仓库](https://github.com/OpenHands/benchmarks/blob/main/README.md)将 SDK 固定到具体 commit，并为实例提供独立 workspace、丰富日志、工具调用数、错误数、patch 状态和结束原因。它体现了 baseline/candidate、评估器和执行环境必须绑定版本，不能只保存一个最终分数。

#### autoresearch

[Karpathy autoresearch 官方仓库](https://github.com/karpathy/autoresearch)是轻量实验循环：冻结数据和评估逻辑，Agent 只修改受限文件，运行固定时长，记录 baseline、指标、内存、keep/discard/crash 和实验描述，变差则回退。

它是“固定 evaluator + 候选 diff + 接纳/回退”的清晰示例，但不是生产运维系统；单一指标、固定时长和 NEVER STOP 不能直接用于服务器。

#### OpenTelemetry

[OpenTelemetry 观测性 primer](https://opentelemetry.io/docs/concepts/observability-primer/)和[官方规范](https://opentelemetry.io/docs/specs/otel/)将 trace、metrics、logs 及其关联作为统一观测模型。CodeSense 需要用 root trace 串起 `agent.run`、`llm.call`、`tool.exec`、`test.run`、`candidate.apply`、`candidate.revert` 和 `promotion`，但不应把完整 prompt、源码、凭据或用户身份明文放进高基数指标。

## 2. 横向证据结论

### 2.1 稳定的共同模式

| 问题 | 多个项目共同出现的机制 | CodeSense 采用方式 |
| --- | --- | --- |
| 谁做什么 | 角色职责、阶段、交接物显式化 | coordinator、observer、executor、reviewer、verifier 分工 |
| 如何推进 | 状态机/Flow/Task lifecycle，而非无限群聊 | `scheduled → observe → diagnose → policy → snapshot → apply → verify → keep/rollback` |
| 如何停止 | 成功条件 + 墙钟/调用/成本/迭代上限 | 每次 run 都有硬预算和 stop_reason |
| 如何避免自评 | 独立 reviewer、guardrail、固定 evaluator | 执行 Agent 无权单独批准自己的变更 |
| 如何恢复 | 持久状态、事件、checkpoint、queue | operation_id、计划 hash、目标版本、阶段状态可重放 |
| 如何防副作用 | 幂等键、锁、版本/CAS、补偿 | 执行前重新读取、按 server/resource 加锁、冲突即停止 |
| 如何评价 | baseline/candidate、固定测试、轨迹和资源 | 低风险变更也必须有基线、验证、回滚记录 |

### 2.2 服务器自治运维的硬边界

[Kubernetes Controller 文档](https://kubernetes.io/docs/concepts/architecture/controller/)把 controller 描述为持续观察 current state 并趋近 desired state；[Operator pattern](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/)强调把运维知识编码成控制器。其[幂等实践](https://book.kubebuilder.io/reference/good-practices)、队列限速/去重机制（[client-go workqueue](https://pkg.go.dev/k8s.io/client-go/util/workqueue)）以及版本和锁语义可迁移到 CodeSense，但 controller 本身不会判断 desired state 是否安全。

[Temporal 官方文档](https://docs.temporal.io/)说明持久 Workflow 可以从崩溃处恢复；[retry policy 文档](https://docs.temporal.io/encyclopedia/retry-policies)强调 timeout、retry 和 non-retryable error；Activity 可能重复执行，外部副作用必须用幂等键。它的 Saga/补偿也不是 ACID 回滚，补偿失败时必须进入人工处置。

[LangGraph interrupts 文档](https://docs.langchain.com/oss/python/langgraph/interrupts)与[Persistence 文档](https://docs.langchain.com/oss/python/langgraph/persistence)说明 checkpointer + thread_id 可以暂停、等待人工审批并恢复；恢复会从节点开始处重跑，所以 interrupt 前的副作用必须幂等。这个机制适合规划和审批，不替代外部策略层。

据此，以下动作不能交给 LLM 自己决定：删除数据/卷、数据库迁移、凭据/IAM、网络暴露/防火墙、内核/固件/重启、生产故障切换、超预算扩容、修改安全策略本身。它们只能生成 proposal，进入人工审批或显式变更窗口。

### 2.3 评估结论

不能只看“任务成功率”。应分别记录：Agent 决策错误、工具错误、应用错误、测试失败、基础设施失败、超时、成本耗尽、重复失败、回归、安全阻断和人工停止。每次 run 至少保留：

- run_id、operation_id、agent/配置/环境版本、baseline hash；
- 计划、候选 diff、执行命令摘要、退出码、耗时和 stop_reason；
- 测试/健康检查/业务 canary 结果；
- CPU、内存、磁盘、连接数、模型调用次数、token 和成本估算；
- keep、discard、rollback、needs_human 的决策及理由。

完整轨迹可能含 prompt、源码、凭据和个人信息，因此保存原始日志必须脱敏、限权、分层保留；指标标签不能直接使用无限制的用户 ID、commit 或请求正文。

## 3. CodeSense 当前真实基线

下列不是开源项目宣传数据，而是此前已授权的线上只读检查结果；定时任务第一次运行仍需重新采集，不把旧基线当成永远正确。

### 3.1 服务器和请求

- ECS：阿里云 `cn-heyuan`，实例 `i-f8zbujornnh55dsydozz`，2 vCPU，约 1.8 GiB RAM；检查时 load 约 0.01–0.24，根盘约 36% 使用。硬件资源当时不是主要瓶颈。
- Gunicorn：2 workers × 4 threads，timeout 180 秒，监听 `127.0.0.1:8000`，systemd 当前以 root 运行；Nginx 作为入口。
- 最近 24 小时 Gunicorn 访问约 4,851 次：200 为 1,469、302 为 605、304 为 24、404 为 2,750、405 为 3，没有 5xx。另一个 Nginx 样本约 12.4 小时的 404 比例约 65.6%，包含大量扫描探测。
- 最近 24 小时总体 p50 约 1.32 ms，p95 约 44.3 ms，p99 约 12.42 s，最长约 120.75 s；超过 800 ms 的约 115 次，超过 5 s 的约 77 次，超过 30 s 的约 19 次。
- 慢路径集中在 `/thinking/api/stage3/forum/message`（p50 约 20.4 s、p95 约 75.7 s）、`/thinking/api/companion/chat`（p50 约 13.1 s、p95 约 49.3 s）、`/home`（p95 约 117.8 s、最长约 396.7 s）、`/api/stream/ability-analysis`（p95 约 10.2 s）和 `/api/code_advice`（p50 约 12.3 s）。
- Zhipu 日志出现约 12 个 APIReachLimit/429、9 条 retry、30 秒 circuit open，以及 provider 全部失败/无有效分析内容。当前表现更像 AI 上游等待、重试和同步占用 worker，而不是 CPU/RAM 不够。
- Nginx 静态请求仍可能落到 Gunicorn；对 `/.env`、`/.git/config`、`/@fs/etc/passwd` 等探测目前观察到 404，未发现泄漏证据，但应在边缘层拦截。
- 观察到 MySQL `*:3306`/33060、FTP 21、SSH 22、面板 8888 等监听；云安全组和实际公网暴露状态尚未完成独立验证，不能直接改防火墙。

### 3.2 用户与 AI 交互

- 数据库约 214 个用户：207 学生、6 教师、1 管理员；最近 7 天推断约 60 名学生和 2 名教师有活动，最近 30 天约 79 名学生和 2 名教师有活动。当前没有专门的 last-login 指标，因此这些是从日志、会话和提交推断的活跃度。
- 约 568 个 thinking session，其中约 307 个仍标记进行中；大量 session 超过 6 小时/1 天，已完成 session 的 `total_time` 平均约 6.3 小时，说明会话生命周期与时长统计需要单独修复。
- 约 2,008 个 submission，约 2,007 个已评估；阶段三历史 teacher round 约 560、student round 约 2,038。
- 最近 30 天可识别到约 45 次 `agent_user_message` runtime 请求，其中 43 次有一次决策和一次回复，2 次没有决策/回复；约 6 次 fallback，未见 agent_decision_error。说明当前没有明显的模型调用倍增，主要问题是延迟、provider 限流、同步等待和 fallback 体验。
- 旧 chat 消息中的不确定性表达并非少数；此前已在本地增加了隐私保护的交互画像和更具体的教师兜底，但线上版本落后于本地，不能直接把本地未迁移改动视为线上能力。

### 3.3 Gap matrix

| 能力 | 当前证据 | 风险 | 决定 |
| --- | --- | --- | --- |
| 真实使用观测 | 有访问日志、数据库、AI 日志，但字段和 last-login 不完整 | 只能事后拼接，难以解释单次慢请求 | 先补 server-side redacted run report；完整 OTel 放本地 backlog |
| AI 请求隔离 | 有 retry/circuit/fallback 日志，AI 调用仍可能占 web worker | provider 慢时拖长请求尾部 | 服务器先限风险和观测；“LLM 移出 Gunicorn”列为本地高优先级 |
| Nginx 边缘层 | HTTPS 已修复，静态和扫描拦截仍有优化空间 | 无效 404 消耗 Gunicorn/日志 | 低风险候选：静态直出、敏感路径 deny，先备份和 nginx -t |
| 变更回滚 | 已有单次 Nginx 备份习惯，没有统一 operation ledger | 无法证明谁改了什么、如何回退 | 定时任务必须记录 operation_id、快照和反向操作 |
| 幂等/并发 | 未见统一服务器变更锁和版本校验 | 重复定时运行可能叠加副作用 | `flock`/lease + 当前版本二次读取；冲突即停止 |
| 权限边界 | systemd 以 root；端口暴露状态未核验 | agent 权限过大、误改安全面 | 自动化仅白名单；root/防火墙/数据库/凭据改动需人工 |
| 代码版本 | 线上 HEAD 落后本地，且本地有新增 schema 字段 | 直接部署会出现 schema/版本不一致 | 定时 server 任务禁止直接 deploy；本地任务先做兼容 PR |
| 会话生命周期 | 大量 stale/in-progress session | 统计和用户体验失真，潜在资源占用 | 本地 backlog；服务器只做观测/备份，不自动删数据 |

## 4. 方案决策

### 4.1 采用的最小架构

```text
定时触发
  → coordinator 读取 PRD 与最近基线
  → observer 只读采集服务器事实
  → diagnostician 生成 bounded proposal
  → policy gate（独立硬规则，不由 LLM 覆盖）
  → snapshot + operation lock
  → executor 只执行白名单中的一个低风险变更
  → verifier 做健康/业务/资源回归
  → keep 或 rollback/compensate
  → report + postmortem action
```

### 4.2 为什么暂不直接引入完整框架

- 服务器只有 2 vCPU/约 1.8 GiB RAM，当前瓶颈在上游 AI 等待和长尾，不在缺少一个 Agent SDK。
- CrewAI/Temporal/LangGraph/Kubernetes 各自解决不同层的问题；同时安装会增加依赖、运行时、升级和故障面。
- 当前最紧要的是边缘层无效流量、AI 长尾、运行版本漂移、变更审计和权限边界。先把这些事实和门禁做实，再决定是否需要持久化工作流服务。
- 研究结论不是拒绝框架，而是先采用其可迁移机制；当出现并发任务、跨天恢复、多人审批或需要多服务器协调时，再评估 Temporal/LangGraph 或独立 worker。

### 4.3 近期可执行的变更顺序

1. 只读基线、监听面和安全组状态核验；任何不确定项只出报告。
2. Nginx 低风险边缘优化：敏感点文件/探测路径 deny，静态目录直出；先检查真实静态根目录、备份、`nginx -t`、reload、健康和静态回归。
3. 日志轮转/保留策略，避免无界增长；只在确认路径和权限后改。
4. 对 AI 慢路由补充 provider、attempt、queue wait、latency、fallback、错误分类等脱敏字段；若线上版本不支持，进入本地 backlog，不能通过修改未知环境变量冒险启用。
5. 对 worker 数量、超时、数据库索引/迁移、进程用户、外网端口和防火墙只生成 proposal，等待专门审批。

## 5. 研究局限

- 开源项目的版本和 API 漂移很快，本报告冻结的是 2026-09-04 看到的官方内容；定时任务每次应重新检查目标文档/当前实现。
- OPC、OpenCompany、OPC Team 等项目的组织能力很多来自 README 自述，不能据此证明生产可靠性。
- 线上基线是窗口采样，且没有完整分布式 trace、独立 last-login、真实公网安全组审计；趋势判断需要定时采样后再校准。
- “低风险”不是“无风险”：Nginx、reload、日志策略也必须有备份、锁、验证和回滚。

## 6. Claim-to-source ledger

| ID | 结论 | 主要来源 |
| --- | --- | --- |
| C01 | 角色 + SOP + 轮次/预算/停止 | [MetaGPT README](https://github.com/FoundationAgents/MetaGPT/blob/main/README.md)、[Team](https://github.com/FoundationAgents/MetaGPT/blob/main/metagpt/team.py) |
| C02 | 阶段、专门角色、循环上限、人工 reviewer | [ChatDev README](https://github.com/OpenBMB/ChatDev)、[ChatDev 论文](https://arxiv.org/abs/2307.07924) |
| C03 | Task expected output、guardrail、Flow 持久化/恢复/人工反馈 | [CrewAI docs](https://docs.crewai.com/) |
| C04 | 任务生命周期、账本、终止条件、状态保存 | [AutoGen](https://github.com/microsoft/autogen)、[AG2](https://github.com/ag2ai/ag2) |
| C05 | 事件状态、崩溃恢复、风险确认、sandbox | [OpenHands runtime](https://docs.openhands.dev/openhands/usage/architecture/runtime)、[OpenHands security](https://docs.openhands.dev/sdk/api-reference/openhands.sdk.security) |
| C06 | desired state、reconcile、幂等、队列限速、版本/锁 | [Kubernetes Controller](https://kubernetes.io/docs/concepts/architecture/controller/)、[Kubebuilder good practices](https://book.kubebuilder.io/reference/good-practices)、[workqueue](https://pkg.go.dev/k8s.io/client-go/util/workqueue) |
| C07 | durable workflow、retry/timeout、不可重试错误、幂等副作用 | [Temporal docs](https://docs.temporal.io/)、[Retry Policies](https://docs.temporal.io/encyclopedia/retry-policies) |
| C08 | checkpoint、人工 interrupt、恢复前副作用幂等 | [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) |
| C09 | 受限工具接口、轨迹、成本/调用上限 | [SWE-agent ACI](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)、[trajectories](https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md) |
| C10 | 固定 evaluator、baseline、keep/discard/crash、回退 | [autoresearch](https://github.com/karpathy/autoresearch)、[OpenHands Benchmarks](https://github.com/OpenHands/benchmarks/blob/main/README.md) |
| C11 | trace/metrics/log 统一关联和脱敏观测 | [OpenTelemetry primer](https://opentelemetry.io/docs/concepts/observability-primer/)、[specification](https://opentelemetry.io/docs/specs/otel/) |
| C12 | OPC 组织、任务、审批、审计形态 | [OpenOPC](https://github.com/HKUDS/OpenOPC)、[OPC-Agents](https://github.com/lulin70/OPC-Agents)、[OPC Team](https://github.com/HeiGeAi/opc-team) |
| C13 | 本地 daemon、任务队列、cron、worktree/review | [Junior](https://github.com/JHostalek/junior)、[OpenCompany](https://github.com/zeenie-ai/OpenCompany) |
