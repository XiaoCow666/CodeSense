# 阶段十二：知识检索与 RAG 复杂企划落地与离线评估

能力主题键：`CodeSense:knowledge-rag:stage12`

## 系统地图（先于实现）

```text
AssignmentKnowledgePoint
        |
        v
assignment-scoped adapter (services/knowledge_rag.py)
        |
        v
KnowledgeDocument -> chunk -> embed -> candidate retrieve -> rerank -> citation
        |                                                       |
        v                                                       v
  prompt context --------------------------------------> /api/ask_question
                                                              |
                                                              v
                                                        JSON / SSE receipt
```

当前主干已经有可替换的切分、嵌入、召回、重排和引用契约，但此前它仍是每次请求重建的内存流水线，不是可单独验证的最小向量索引；固定离线问题集和关键词回退也尚未落地。

## 观察与可证伪假设

### 已确认观察

1. `services/knowledge_rag.py::retrieve_assignment_knowledge()` 只读取当前作业的 `AssignmentKnowledgePoint`，并在适配器层最多取 8 条记录。
2. `services/knowledge_pipeline.py::OfflineKnowledgePipeline.search()` 每次从文档重新切分并计算 embedding，没有独立的向量写入/查询对象，因此无法单独测量索引规模、top-k 命中和回退路径。
3. 当前没有固定问题集；现有测试能验证排序、引用和安全回退，但不能报告固定样本的 Recall@k 或向量检索耗时。
4. 查询没有向量命中时没有独立的标题/正文关键词回退；已有作业记录仍按旧优先级结果返回，空作业才进入 `NO_KNOWLEDGE_EVIDENCE`。

### 可证伪假设

在不改变数据库结构、权限、部署和学生端 JSON/SSE 字段的前提下，引入“每次请求隔离的稀疏内存向量索引 + 有界 top-k + 关键词回退”，可以找回旧 8 条截断会漏掉的后置匹配证据，并让固定问题集中至少一条已知证据命中，同时保持引用完整性和安全无结果回退；索引构建和查询的本地 P95 应保持在可接受的毫秒级范围内。

若实验显示索引构建或候选扩展造成明显延迟，保留原有 assignment-scoped 读取和 answer-only 回退，不引入跨请求缓存或外部向量服务。

## 目标与边界

- 目标：提供可替换的最小内存向量库、top-k 检索、引用输出和关键词回退；用固定 JSON 问题集报告 Recall@1/Recall@k、回退次数和延迟。
- 真实行为改进：当前最多 8 条候选会漏掉后置但匹配的作业知识点；新索引把读取范围扩大到一个明确的有界上限，再在索引内做 top-k，仍最多返回 8 条证据。
- 保留：作业隔离、学生私有评分隔离、既有 JSON/SSE 字段、引用 ID、无结果和数据源异常时的 answer-only 回退。
- 不做：数据库表/字段、权限、生产密钥、部署配置、跨作业索引、外部 embedding、向量数据库和不可逆迁移。

## 计划改动

1. 新增 `services/knowledge_vector_store.py`：标准库 `NgramCountEmbedder`、显式 `write()` 的 `InMemoryVectorStore`、标题/正文 `KeywordFallbackRetriever` 和 `HybridKnowledgeIndex`。
2. 在 `knowledge_rag` 中将作业范围候选读取限制为 `MAX_INDEX_DOCUMENTS=64`，构建请求内隔离索引并返回 `retrieval_mode`、`indexed_chunk_count` 等只增不破坏既有字段的指标；最终证据仍由 `MAX_EVIDENCE=8` 限制。
3. 新增 `tests/fixtures/knowledge_rag_eval.json` 和 `python -m services.knowledge_eval` 评估命令；补充向量命中、关键词回退、top-k、索引隔离、固定评估和异常回退测试。
4. 保留旧的优先级回退行为，避免未匹配问题改变学生端结果；只有空索引才进入原有 no-result 回退。

## 验证计划

- 修复前：运行当前基线测试，并用后置第 10 条唯一命中样本证明原有 8 条候选边界会漏检。
- 修复后：运行定向测试、固定评估集、全量测试、`git diff --check`；报告 Recall@1、Recall@k、fallback 次数和索引查询/构建耗时。
- 故障实验：让向量索引构建或查询抛出异常，确认原有 answer-only 回退，不向学生暴露内部异常或伪造引用。

## AI 建议边界

本阶段先基于源码和可运行基线形成观察、假设和指标；实现阶段不接入外部 AI、真实凭据或外部向量服务。若后续比较模型/向量数据库方案，只作为待决策事项，不能替代本地测试和固定评估证据。

## 实际结果

- 修复前基线：阶段 11 定向命令 `python -m pytest tests/test_knowledge_pipeline.py tests/test_knowledge_rag.py -q --disable-warnings` 为 `13 passed`；其中 10 条作业知识点只读取前 8 条，唯一匹配的第 10 条证据被漏掉。
- 本次审查指定定向命令：`python -m pytest tests/test_knowledge_eval.py tests/test_knowledge_vector_store.py tests/test_knowledge_rag.py -q --disable-warnings` 为 `19 passed`，退出码 0，42.57s。
- 全量回归（前一提交 `d370b5f`）：`python -m pytest -q --disable-warnings` 为 `681 passed`，退出码 0，13:26；该结果未在本次标签修订后重跑，warnings 为既有项目噪音和测试环境输出。
- 固定评估命令：`python -m services.knowledge_eval`；5 个固定问题，4 个有标注问题，最后一题的两个相关文档现在均为真实的数组下标文档（`array-boundary`、`array-indexing`），不再把排序稳定性文档误标为相关文档。按“每题前 k 个去重文档命中数 / 该题相关文档数”计算 Recall@1=0.875、Recall@k=0.875；模式为 3 次 vector、1 次 keyword fallback、1 次 no-result，期望模式不匹配数为 0；共索引 16 个切片。
- 固定评估的普通问题耗时：切分/索引构建 mean 0.400ms、P95 1.736ms；查询 mean 0.053ms、P95 0.111ms；合计 mean 0.454ms、P95 1.797ms。
- 固定 64 文档性能样本、64 个切片、100 次查询、top-k=8：构建 1.101ms；查询 mean 0.454ms、P95 0.573ms；总耗时 46.522ms，按运行摊销 0.465ms/次。
- 行为回归：查询第 10 条唯一知识点时从旧的“前 8 条漏检”变为返回 `assignment-kp:10`；最终结果仍最多 8 条。超过 64 条时第 65 条及以后保持明确的资源边界。
- 故障实验：向量 embedding 抛出异常时返回 `KNOWLEDGE_RETRIEVAL_UNAVAILABLE`，学生端继续 answer-only，不暴露内部异常或伪造引用。
- `git diff --check`：通过。

### 维护者抽查答复

- ID10 能命中、ID70 不能进入结果，是因为 `MAX_INDEX_DOCUMENTS=64` 控制从数据库读取并建立索引的候选文档数：ID10 在前 64 条范围内，ID70 超出范围会被有意截断。`MAX_EVIDENCE=8` 是另一层边界，只控制最终返回给调用方的证据最多 8 条；它不决定是否建立索引。
- 查询“数据库迁移”时，空索引走 `no_result`，返回 `NO_KNOWLEDGE_EVIDENCE`，保持原有 answer-only 回退；索引含数组/指针文档但没有匹配时走 `priority_fallback`，按稳定优先级返回已有证据，避免有作业知识记录时把学生端结果突然变成无证据。只有索引为空时才进入 no-result 分支。

## 事实、推断与未解决问题

- 已确认事实：索引只存在于单次调用创建的 `HybridKnowledgeIndex`；未写入数据库、磁盘、Redis 或跨请求全局缓存；候选读取上限为 64，最终证据上限为 8；固定集和回归测试均在无生产凭据的隔离环境运行。
- 仅属推断：字符 bigram 稀疏向量能减少中文单字误匹配，但不等同于语义 embedding；固定集 Recall=0.875 只说明这 5 个样本，不能代表线上知识库质量。
- 未解决：每次请求仍会重建索引；64 条是保守资源上限，不是线上容量结论；未验证真实 Redis、外部 AI、生产数据库、并发压力、浏览器全流程或持久化向量库迁移。

## 取舍、回滚与后续建议

- 采纳：标准库 sparse vector、请求内索引、固定离线集和显式模式指标，原因是可复现、可注入、无需新凭据和迁移。
- 拒绝：跨请求缓存、外部向量数据库、真实 embedding API 和数据库字段，原因是会扩大数据隔离、权限、成本、部署和回滚边界。
- 回滚：删除 `knowledge_vector_store.py` 和评估文件，并将 `knowledge_rag.py` 的索引调用恢复为 `knowledge_pipeline.search()`；数据库和部署不需要回滚。
- 后续：若要提高语义召回，先用脱敏固定集比较候选模型与成本/延迟，再单独评审持久化索引、失效策略、权限和数据迁移；不要把本 PR 的内存原型直接当作生产向量库。
