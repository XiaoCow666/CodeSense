# CodeSense 阶段十一：可演进知识流水线契约与离线验证

能力主题键：`CodeSense:knowledge-rag:stage11`
验证角度：可替换性、性能、资源与边界条件

本次交付建立在阶段十已经合并到 `main` 的作业级显式知识证据之上。范围限定为“定义可替换契约 + 接入一个不依赖外部服务的默认实现”，不接入生产密钥、向量数据库、新表或新的权限规则。

## 1. 先观察，再提出假设

变更前直接检查 `origin/main` 得到以下事实：

- `services/knowledge_rag.py::retrieve_assignment_knowledge()` 直接查询 `AssignmentKnowledgePoint`，按权重和记录 ID 排序，没有独立的切分、嵌入、候选召回、重排或引用构造接口。
- `routes/api.py::_retrieve_knowledge_context()` 只传入 `assignment_id`，学生问题没有进入知识证据排序阶段；因此多个知识点时只能按来源权重返回。
- 阶段十已经规定了作业隔离、最多 8 条证据、不读取学生私有评分和无结果回退，这些是本轮必须保持的兼容边界。

可证伪假设：如果把流水线阶段拆成标准输入/输出契约，并用透明的离线词法实现接入，那么学生问题可以优先得到相关的作业知识证据；在没有匹配词时仍按来源优先级稳定排序，不需要改变数据库、权限、部署或学生端响应字段。

成功指标：

1. 每个阶段都能通过构造函数替换，并且离线样本可独立运行。
2. 相同输入得到相同 chunk ID、证据 ID、引用序号和排序。
3. 有匹配词时相关证据优先；无匹配词时保留原有权重/记录 ID 的稳定顺序。
4. 作业范围、最多 8 条最终证据、学生私有评分隔离和既有回退行为不变。

## 2. 流水线系统地图

```text
AssignmentKnowledgePoint
        │  adapter: KnowledgeDocument
        ▼
DocumentChunker ──► TextEmbedder ──► CandidateRetriever
                                           │
                                           ▼
                                    CandidateReranker
                                           │
                                           ▼
                                     CitationBuilder
                                           │
                                           ▼
              /api/ask_question 的 knowledge_retrieval.evidence
```

代码边界在 `services/knowledge_pipeline.py`：

| 阶段 | 契约 | 当前离线实现 | 后续可替换项 |
| --- | --- | --- | --- |
| 切分 | `DocumentChunker.split()` | `ParagraphChunker` | Markdown/代码感知切分 |
| 嵌入 | `TextEmbedder.embed()` | `TokenCountEmbedder` | 本地模型或受控向量服务 |
| 候选召回 | `CandidateRetriever.retrieve()` | `LexicalCandidateRetriever` | 倒排索引/向量索引 |
| 重排 | `CandidateReranker.rerank()` | `StablePriorityReranker` | 相关性模型或规则组合 |
| 引用 | `CitationBuilder.build()` | `StableCitationBuilder` | 版本化来源/审计字段 |

`services/knowledge_rag.py` 只负责数据库边界和旧响应结构适配：仍然先按当前作业查询，再把记录转换为文档；`routes/api.py` 将学生问题传给检索适配器。默认实现只使用 Python 标准库，不读取环境中的 AI 凭据。

## 3. 变更范围与兼容边界

- 新增 `services/knowledge_pipeline.py`：数据对象、五类契约、默认离线流水线和可替换组件。
- 修改 `services/knowledge_rag.py`：通过流水线生成证据，增加可选 `query` 参数；不传问题时仍按来源优先级工作。
- 修改 `routes/api.py`：在学生提问链路传递已完成输入校验的问题文本，用于当前作业内的稳定重排。
- 新增 `tests/test_knowledge_pipeline.py`，并在 `tests/test_knowledge_rag.py` 增加真实入口回归。
- 没有数据库结构、权限、部署、Redis、外部模型或核心响应字段变更；`answer` 和现有 `knowledge_retrieval` 结构继续保留。

采纳的 AI 辅助建议：采用小型 Protocol/数据类分层，让切分、嵌入、召回、重排、引用可以单独替换；采用纯标准库词法实现，便于离线复现。拒绝直接引入向量数据库、生产模型密钥和自然语言相关性模型，因为这些会扩大依赖、权限、成本和部署边界，无法在本阶段隔离验证。这些取舍是设计判断，最终行为以源码和测试结果为准，不把 AI 总结当作系统理解证据。

## 4. 验证结果

定向命令：

```powershell
D:\xproject\新建文件夹\CodeSense-main\pr-student-learning-route-worktree\.venv\Scripts\python.exe -m pytest tests/test_knowledge_pipeline.py tests/test_knowledge_rag.py -q --disable-warnings
```

实测：`10 passed`，退出码 0，耗时 `27.68s`。

整仓命令：

```powershell
D:\xproject\新建文件夹\CodeSense-main\pr-student-learning-route-worktree\.venv\Scripts\python.exe -m pytest -q --disable-warnings
```

实测：`662 passed`，退出码 0，耗时 `14:13`。

离线容量样本使用 100 个文档、每次取 8 条、连续运行 100 次，实测：`mean=1.842 ms`、`P95=2.581 ms`。这是当前进程内的词法基线，不是生产端到端 SLA；它不代表真实向量服务、数据库或模型服务的延迟。

覆盖的事实边界：

- `array boundary` 问题会优先得到匹配证据，即使另一条证据的来源权重更高。
- 相同输入会产生相同 chunk/evidence ID 和 `[K1]`、`[K2]` 顺序。
- 替换重排组件不会改变流水线调用契约。
- `/api/ask_question` 的当前作业隔离、无结果回退和学生私有评分隔离测试保持通过。

## 5. 风险、回滚与后续建议

- 风险：当前词法嵌入不是语义模型，中文按字符粒度匹配，复杂同义表达可能召回不足。
- 风险：当前候选池仍受阶段十的作业级最多 8 条边界限制，不应据此推断大规模索引容量。
- 回滚：移除 `query` 传递并恢复 `knowledge_rag.py` 原有证据组装即可；不需要数据库回滚。
- 未解决：真实文档切分策略、向量索引更新生命周期、脱敏策略、相关性评估集和告警阈值仍需负责人决策，不在本 PR 直接接入。
- 后续建议：先用脱敏离线评估集比较词法基线与候选向量实现，再决定是否引入外部依赖和生产部署；若涉及 schema、权限、真实凭据或不可逆部署，应另开方案评审。
