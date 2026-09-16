# 阶段十三：知识检索与 RAG｜生产级可靠性与容量演练

能力主题键：`CodeSense:knowledge-rag:stage13`

## 系统地图

```text
AssignmentKnowledgePoint rows
          |
          v
  privacy filter + safe metadata
          |
          v
  chunk -> request-local versioned index
          |             |
          |             +--> bounded rate limiter
          |             +--> bounded timeout/deadline
          v
  vector -> keyword -> priority fallback
          |
          v
  citation builder -> JSON / SSE answer receipt
          |
          +--> bounded quality counters (no query/student content)
```

阶段十二已经解决了请求内稀疏向量检索、关键词回退和 64/8 资源边界，但每次索引只能整体创建，没有显式的增量发布/回滚；检索过程也没有超时、限流或可观察的失败分类。本阶段围绕“性能、资源与边界条件”补齐这些控制点，同时保持学生端 answer-only 降级路径。

## 观察、假设与成功指标

### 已确认观察

1. `services/knowledge_rag.py::retrieve_assignment_knowledge()` 读取当前作业知识点后在请求内构建索引；阶段十二的候选读取上限为 64，最终证据上限为 8。
2. 原有 `HybridKnowledgeIndex` 只能整体写入和查询，无法在不重建已有 embedding 的情况下替换一个切片，也没有版本快照。
3. 原有异常回退能够保护 answer-only，但无法区分检索超时和一般索引异常，也没有限制同一作业的突发检索请求。
4. 引用构造只应暴露作业知识证据；知识文本和 metadata 不能把邮箱、手机号、token 或非白名单字段带入学生端。

### 可证伪假设

在不改数据库结构、权限、部署和 JSON/SSE 核心接口的前提下，将更新先应用到克隆的请求内索引、成功后再发布，并保留有界旧快照，可以让单切片更新失败时旧版本继续可用；将隐私过滤、超时、限流和质量计数放在同一个适配器边界，可以把 RAG 异常稳定降级为 answer-only，而不阻塞 `/api/ask_question` 的正常响应。

成功指标：

- 单切片 upsert 只新增/替换对应 embedding，旧切片不重复计算；发布失败不改变当前 revision，rollback 能恢复上一快照。
- 隐私测试中邮箱、手机号、凭据值不出现在 citation，unsafe metadata 被丢弃。
- 超时和限流均返回 HTTP 200 的原有回答路径，状态有明确回退码，不抛出内部异常。
- 质量监控只保存有界计数和延迟样本，不保存 query、学生 ID 或答案正文。
- 64 文档容量演练可复现，原有知识 pipeline、评估、RAG 和 SSE 回归全部通过。

## 变更范围与边界

- `services/knowledge_vector_store.py`：增加可注入 deadline；为内存索引增加 clone、增量 upsert、按 document 删除和原子写入。
- `services/knowledge_reliability.py`：新增隐私过滤、滑动窗口限流、版本索引、有限 rollback history 和质量监控。
- `services/knowledge_rag.py`：接入隐私过滤/版本索引/超时/限流/监控，新增 `timeout`、`rate_limited` 回退码及只增字段 `index_revision`、`privacy_filtered_count`。
- `services/knowledge_reliability_eval.py`：提供 64 文档、1000 次查询、一次增量更新和一次回滚的离线容量演练。
- `tests/test_knowledge_reliability.py`：覆盖修复前缺口对应的故障、恢复和 answer-only 行为。

不做：数据库表或字段、生产权限、真实 Redis、外部 embedding、持久化向量库、跨作业缓存、部署变更、学生端既有字段删除或改名。限流器和索引版本当前是单进程/请求内状态，不宣称跨实例一致性。

## 关键设计

1. `InMemoryVectorStore.upsert()` 在临时结构中合并 chunk，只为新增或替换的 chunk 调用 embedder；任一 embedding 失败时不提交临时结构。
2. `VersionedKnowledgeIndex` 在当前索引 clone 上应用更新，成功后增加 revision 并保存有界旧快照；失败的候选不发布，rollback 直接恢复旧快照。
3. `KnowledgePrivacyFilter` 只保留经过类型/格式校验的 `created_at`、`evidence_id`、`record_id` metadata，并对常见邮箱、手机号、凭据格式做保守替换。它不是完整 DLP 系统。
4. `SlidingWindowRateLimiter` 按请求 key 保留固定时间窗事件，key 数有上限；默认配置可由 `KNOWLEDGE_RAG_RATE_LIMIT` 和 `KNOWLEDGE_RAG_RATE_WINDOW_SECONDS` 调整。检索 deadline 默认 250ms，范围限制在 1–5000ms，可由 `KNOWLEDGE_RAG_TIMEOUT_MS` 调整。
5. `KnowledgeQualityMonitor` 只保留有限的 status/mode/fallback 计数和最近延迟样本；标签基数也有上限，超出部分归入 `__other__`；不会记录原始问题、答案或学生隐私信息。

## 验证命令与结果

环境：隔离 worktree，使用共享 `student-eval` Python；未使用生产数据库、生产 Redis、外部 AI 或生产凭据。

- 定向兼容与可靠性测试：
  `python -m pytest tests/test_knowledge_pipeline.py tests/test_knowledge_vector_store.py tests/test_knowledge_eval.py tests/test_knowledge_rag.py tests/test_knowledge_reliability.py -q --disable-warnings`
  当前结果：`36 passed`，退出码 0；包含 13 条阶段十三测试。
- 容量与生命周期演练：`python -m services.knowledge_reliability_eval`
  当前结果：64 文档、64 切片、1000 次查询；构建 1.720ms，查询总计 406.098ms、均值 0.406ms；更新 revision 2，回滚 revision 3，最终 revision 3、64 切片、rollback history depth 0。
- 全量回归：`python -m pytest -q --disable-warnings`
  当前结果：`694 passed`，退出码 0，902.45s（15:02）；输出包含既有测试环境 warnings，本次没有失败用例。
- 静态检查：`python -m py_compile services/knowledge_vector_store.py services/knowledge_reliability.py services/knowledge_rag.py services/knowledge_reliability_eval.py`、`git diff --check`。

### 故障与恢复证据

- `test_versioned_index_does_not_publish_a_failed_update`：embedding 失败时 revision 和旧文本保持不变。
- `test_ask_question_timeout_returns_answer_only_response`：索引超时仍返回 200、超时回退码和 answer-only 内容。
- `test_retriever_rate_limit_stays_on_answer_only_path`：超过窗口容量进入 rate-limited 回退，不进入索引查询。
- `test_ask_question_rate_limit_returns_answer_only_response`：API 限流仍返回 200、答案和明确回退码。
- `test_retriever_privacy_filter_is_applied_before_citation`：敏感文本在 citation 之前已过滤。
- `test_quality_monitor_bounds_caller_controlled_label_cardinality`：任意外部标签不会令 status/mode 计数键无限增长，延迟样本仍保持有界。
- `test_privacy_filter_validates_whitelisted_metadata_types_and_formats`：白名单 metadata 只接受受约束的 ID 和 ISO 时间格式。
- `test_vector_store_upsert_only_embeds_changed_chunks`：初始 2 个切片加 1 次变更只产生 3 次 embedding 调用，证明变更切片不会重复计算旧 embedding。

## 事实、推断与未解决问题

- 已确认事实：本阶段的索引更新、回滚、过滤、deadline、限流和质量监控均为标准库内存实现；失败分支返回 answer-only；代码没有写入数据库、磁盘或 Redis；测试使用可注入时钟/故障对象。
- 仅属推断：本地容量演练的毫秒级耗时不能代表生产 SLA；正则隐私过滤能覆盖常见格式，但不能等同于企业级敏感信息识别；单进程限流不能解决多实例全局配额。
- 未解决：数据库查询本身仍是同步调用，deadline 只能在查询返回后和索引阶段检查；索引不跨请求持久化；没有管理端质量指标页面；未验证真实 Redis、生产数据库、外部 AI、并发压力、浏览器全流程和多实例一致性。

## AI 建议边界、回滚与后续

- 采纳：使用可注入时钟、有限 history、临时 clone、明确 fallback code 和故障测试，原因是可复现且不扩大部署边界。
- 拒绝：直接引入 Redis rate limit、外部向量服务、数据库版本表或跨进程缓存，原因是会涉及权限、数据隔离、部署和迁移决策；这些只能作为后续待决策事项。
- 回滚：移除 `knowledge_reliability.py`、`knowledge_reliability_eval.py`、Stage13 测试和文档；将 `knowledge_rag.py` 恢复为阶段十二的 `HybridKnowledgeIndex` 调用，并撤回 vector store 的 deadline/upsert/clone 扩展。不需要数据库或部署回滚。
- 后续：先由维护者决定是否需要跨实例限流和持久化索引，再基于脱敏固定集评估成本、失效策略、权限和容量；不要把本阶段单进程原型直接当生产基础设施。
