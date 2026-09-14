# CodeSense 阶段十：知识检索与 RAG 系统地图、指标基线

主题键：`CodeSense:knowledge-rag:stage10`  
验证角度：性能、资源与边界条件  
本次实现是有界的显式证据检索基线，不是向量数据库或生产级 RAG 索引。

## 1. 变更前的事实基线

以下结论来自当前仓库代码，而不是对线上系统的推测：

- 仓库没有独立的 RAG、向量索引或 retriever 模块。
- `models.AssignmentKnowledgePoint` 是已有的作业级知识点关联表；
  `add_to_assignment()` 是教师/自动检测流程写入知识点的现有入口。
- `models.KnowledgePointScore` 保存学生个人知识点评分，属于私有画像，不能作为跨学生检索内容。
- `POST /api/ask_question` 原先把作业标题、描述、学生代码和问题交给答案生成器，返回答案，但没有返回知识证据、引用或“没有检索结果”的明确状态。

在实现前先加入了一个期望新行为的红灯用例：
`tests/test_knowledge_rag.py::test_ask_question_exposes_retrieval_evidence_and_fallback_state`。
未修改路由时该用例以 `KeyError: 'knowledge_retrieval'` 失败，说明旧响应没有该字段；修复后转为通过。

## 2. 当前系统地图

```text
教师/已有自动检测流程
        │  AssignmentKnowledgePoint.add_to_assignment()
        ▼
assignment_knowledge_points  ──(当前 assignment_id，有界最多 8 条)──┐
                                                                  ▼
学生 POST /api/ask_question ──► services/knowledge_rag.py
        │                              │
        │                              ├─ grounded：生成 [K1]...[Kn] 证据
        │                              └─ no_result：NO_KNOWLEDGE_EVIDENCE 回退
        ▼                              ▼
guidance_generator  ◄── 有界知识上下文（禁止编造引用）
        │
        ├─ 普通 JSON：answer + knowledge_retrieval
        └─ SSE：delta + done.answer + done.data.knowledge_retrieval
```

## 3. 生命周期与边界

1. 作业创建或后续识别流程绑定知识点，写入现有 `assignment_knowledge_points` 表。
2. 学生提问时只按当前作业 ID读取显式绑定知识点，按权重降序、主键升序排序，最多取 8 条。
3. 生成器只收到这组有限上下文；回答末尾追加确定性的证据回执。
4. 没有知识点时不猜测、不读取任何学生画像，返回 `NO_KNOWLEDGE_EVIDENCE`，并说明回答仅基于题目和代码。
5. 日志只记录状态、候选数、命中数、延迟、引用完整度和是否回退，不记录学生代码、问题或知识点私有分数。

本次没有新增数据库表/字段、权限规则、部署配置、Redis 依赖或外部向量服务；因此不改变数据库结构、权限、部署和现有接口的必需字段。原有 `answer` 字段仍保留，新增信息仅位于响应数据和答案末尾的证据回执中。

## 4. 指标定义与本地验证

| 指标 | 定义 |
| --- | --- |
| `candidate_count` | 当前作业查询到的候选绑定数 |
| `hit_count` | 生成有效证据的条数 |
| `retrieval_hit_rate` | `hit_count / candidate_count`；无候选时为 `0.0` |
| `retrieval_latency_ms` | 单次显式查询从开始到结果构建的本地耗时 |
| `citation_completeness` | 具有稳定 `evidence_id` 和 `[K]` 标记的证据占比 |
| `fallback` | 无结果时的可解释回退对象；当前代码为 `NO_KNOWLEDGE_EVIDENCE` |

验证命令：

```powershell
D:\xproject\新建文件夹\CodeSense-main\pr-student-learning-route-worktree\.venv\Scripts\python.exe -m pytest tests/test_knowledge_rag.py -q --disable-warnings
```

覆盖结果：4 passed。用例包含无知识点回退、有知识点 `[K1]` 引用与指标、SSE 首尾事件兼容，以及不读取学生私有评分的边界。

另外在隔离的 SQLite 测量环境中对同一作业的 2 条显式知识点连续检索 50 次，实测结果为：
`status=grounded`、`candidate_count=2`、`hit_count=2`、`retrieval_hit_rate=1.0`、
`citation_completeness=1.0`、平均 `0.39 ms`、P95 `0.79 ms`。这是本机进程内的
检索基线，不是生产端到端 SLA；测试启动时 Redis 不可用并自动回退到文件系统会话，
该环境现象也不纳入检索延迟结论。

## 5. 风险、回滚与未解决问题

- 主要取舍：复用现有显式绑定，换取低改动和可解释性；当前不做自然语言相关性排序、向量搜索或大规模召回。
- 性能边界：每次最多读取 8 条当前作业知识点；`retrieval_latency_ms` 是应用内基线，不等同于生产端到端延迟。
- 兼容性边界：普通 JSON 保留原有答案字段；SSE 保留 `start/delta/done` 事件，新增字段只在 `done` 中出现。
- 未验证：真实 Redis、外部 AI 服务、生产数据库、并发压力和浏览器全流程；这些不应被本地单元测试结果替代。
- 若后续发现答案展示不适配，可回滚本次提交；不需要数据库回滚或迁移。下一步再引入向量索引前，应先确定数据来源、脱敏、权限、更新策略和相关性评估集。

## 6. 后续维护说明

先运行上面的定向测试，再运行完整测试集。新增检索源时必须保持作业范围、证据 ID、回退码和学生隐私边界；任何需要数据库、权限、部署或外部索引变更的方案先作为待决策项，不在本小范围 PR 内直接落地。
