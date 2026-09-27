# 阶段十四：知识检索与 RAG｜嵌入替换、成本上限与可观测优化

能力主题键：`CodeSense:knowledge-rag:stage14`

## 系统地图

```text
AssignmentKnowledgePoint rows
          |
          v
privacy filter -> chunker -> request-scoped VersionedKnowledgeIndex
                                      |
                                      v
                         embedding provider boundary
                         (cjk_ngram default / token candidate)
                                      |
                                      +--> call and cost budget
                                      +--> bounded latency counters
                                      v
                         vector -> keyword -> priority fallback
                                      |
                                      v
                         safe citations -> answer-only fallback
                                      |
                                      +--> public bounded metrics
                                      +--> offline quality comparison
```

## 先验观察、假设与成功指标

### 已确认观察

1. `services/knowledge_rag.py::retrieve_assignment_knowledge()` 在当前作业知识点范围内按请求构建索引，阶段十三已提供隐私过滤、版本控制、限流、deadline 和质量监控。
2. 学生端默认固定使用 `NgramCountEmbedder`；`services/knowledge_pipeline.py` 已有可独立运行的 `TokenCountEmbedder`，但此前没有统一 provider 选择、成本边界或对比报告。
3. `services/knowledge_eval.py` 已有固定离线集和 recall/latency 统计，可以作为 provider 替换前后的可复现基线。
4. 对阶段十三主线合并结果做 API 回归时发现：内部 `timeout`、`rate_limited` 状态被 `services/knowledge_evidence.py` 的旧白名单投影成 `unknown`，导致 answer-only 回退的状态丢失。

### 可证伪假设

在不改数据库结构、权限、部署和核心 JSON/SSE 字段的前提下，把嵌入器放入显式 registry，并对每个请求限制调用次数和预估成本，可以支持离线 provider 替换，同时让 provider、调用数、成本和预算回退可观测；若候选 provider 在固定集上的 `recall_at_k` 不低于基线，则可以作为后续候选。修复公共投影白名单后，超时和限流状态应原样到达 API，而不是变成 `unknown`。

### 成功指标

- 固定集基线 `recall_at_k=0.875`；候选 provider 的 `recall_at_k` 不低于基线，且通过成本门槛。
- 当前本地 provider 的预估成本为 `0`；RAG 请求默认成本上限为 `0`，未来付费 provider 必须显式登记单次成本并在上限内运行。
- 单个请求最多为 64 个索引切片加 1 次查询调用，即 `65` 次 embedding；超限在调用前拒绝并回到 answer-only。
- provider、调用数、成本、预算拒绝和延迟只以有界计数返回，不保存问题文本、答案或学生隐私。
- `timeout`、`rate_limited` 继续返回原有 HTTP 200 answer-only 路径，并保留明确回退码。

## 变更范围

- `services/knowledge_optimization.py`：新增 provider spec/registry、请求级 `BudgetedEmbedder`、调用/成本/延迟快照和环境成本上限 `KNOWLEDGE_RAG_EMBEDDING_MAX_COST`。
- `services/knowledge_optimization_eval.py`：使用现有固定集比较 `cjk_ngram` 与 `token`，输出 recall、延迟、调用数、成本和质量/成本门禁结果。
- `services/knowledge_eval.py`：为固定评估增加可注入 embedder，不改变默认评估结果。
- `services/knowledge_rag.py`：默认仍使用 `cjk_ngram`；显式设置 `KNOWLEDGE_RAG_EMBEDDER=token` 才切换，返回新增的安全 embedding 指标，预算拒绝沿用 unavailable/answer-only 回退。
- `services/knowledge_evidence.py`：补齐 `timeout`、`rate_limited` 状态、回退码和公共安全指标白名单，避免可靠性状态被投影成 `unknown`。
- `routes/api.py`：在既有无查询内容日志中补充 provider、调用数、成本和预算状态。
- `tests/test_knowledge_optimization.py`、`tests/test_knowledge_rag.py`、`tests/test_knowledge_evidence.py`：覆盖预算拒绝、provider 切换、质量/成本对比和可靠性状态投影。

不做：数据库表/字段、生产权限、真实 Redis、外部 embedding API、持久化向量库、跨作业缓存、部署变更、学生端既有字段删除或改名。当前 registry 只登记两个标准库离线 provider；它是替换边界和评估工具，不代表已接入生产模型。

## 学习总结与 AI 辅助边界

本阶段的关键学习是把“模型替换”和“模型一定更好”分开：registry 只解决构造和边界，固定集才负责比较质量，预算封装负责成本和失败前置，回退路径负责兼容性。嵌入调用应按请求隔离，不能把预算计数放到跨请求全局对象，否则一次演练会耗尽后续请求额度。

采纳的 AI 辅助建议：保留旧 provider 为默认值；使用固定离线集和可注入时钟/故障对象；把质量门禁和成本门禁写成可测试数据；把超限作为安全回退而不是把异常传播给学生端。未采纳的扩大方案：直接接入外部模型、Redis 全局计费或持久化索引，因为这些会引入凭据、权限、部署、跨实例一致性和数据迁移决策。

## 验证命令与结果

环境：`pr-stage14-rag-optimization` 隔离 worktree，使用共享 `student-eval` Python；未使用生产数据库、生产 Redis、外部 AI 或生产凭据。

基线（改动前）：

```text
python -m services.knowledge_eval
recall_at_1=0.875, recall_at_k=0.875
mode_counts=keyword_fallback:1, no_result:1, vector:3
```

阶段十四对比：

```text
python -m services.knowledge_optimization_eval
cjk_ngram: recall_at_k=0.875, calls=181, estimated_cost=0.0,
           quality_gate=True, cost_gate=True, selected=True
token:     recall_at_k=0.875, calls=181, estimated_cost=0.0,
           quality_gate=True, cost_gate=True, selected=False
```

测试与静态检查：

```text
python -m pytest tests/test_knowledge_evidence.py tests/test_knowledge_reliability.py tests/test_knowledge_rag.py tests/test_knowledge_optimization.py tests/test_knowledge_eval.py -q --disable-warnings
46 passed, exit code 0

python -c "from pathlib import Path; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in [Path('services/knowledge_optimization.py'), Path('services/knowledge_optimization_eval.py'), Path('services/knowledge_eval.py'), Path('services/knowledge_rag.py'), Path('services/knowledge_evidence.py')]]"
git diff --check
通过
```

另外，阶段十三既有可靠性集合在本阶段回归中包含限流和超时 API 用例；修复前两例因公共投影返回 `unknown` 失败，修复后与阶段十四测试一起为 `46 passed`。本地日志中的 Redis 未安装/连接失败属于测试环境降级提示，不是本阶段新增失败。

## 事实、推断与未解决问题

- 已确认事实：默认 provider 未改变；`token` 通过环境变量显式切换；固定集两个 provider 均达到 `recall_at_k=0.875`；成本和调用预算由请求级封装执行；可靠性状态现在能通过公共投影；所有改动不触碰数据库 schema、权限或部署。
- 仅属推断：固定集只有 5 个查询，不能推出生产数据上的模型优劣；标准库 provider 的零成本不等于外部模型零成本；单次本地延迟不能代表生产 SLA。
- 未解决：没有接入真实 embedding 模型、生产账单或多实例全局配额；没有管理端质量趋势页面；当前 registry 仅包含离线候选；阶段十三的单进程限流、请求内索引和未验证的真实 Redis/生产数据库边界仍然成立。

## 回滚与后续建议

回滚只需撤回本阶段新增的两个 optimization 模块、相关测试/文档，并将 `knowledge_eval.py` 的可选 embedder、`knowledge_rag.py` 的请求级 wrapper 和 `knowledge_evidence.py` 的状态白名单恢复到本 PR 前版本；不需要数据库或部署回滚。阶段十三的 `timeout`/`rate_limited` 投影修复应保留，除非维护者明确恢复旧 API 行为。

后续建议：先由维护者提供脱敏、规模更大的评估集和真实成本口径，再决定是否登记外部 embedding provider；若需要跨实例配额，应单独评审 Redis/账单/权限方案，不把本阶段的进程内计数直接扩展成生产全局配额。
