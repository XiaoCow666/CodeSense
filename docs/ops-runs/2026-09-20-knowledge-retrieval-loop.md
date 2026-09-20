# CodeSense 2026-09-20 脱敏运行报告

## 主方案与必要性判断

本轮主方案是把知识图谱和学生学习记忆接入学生作业问答、Code Studio AI 辅导、教师班级知识点干预三个真实入口，形成“来源导入—范围过滤—受限查询—用户行动—效果评估”的连续流程。

目标用户与痛点：学生需要知道当前作业对应的知识点和下一步练习；教师需要从班级聚合信号快速创建针对性练习；AI 辅导需要给出可追溯的学习依据并处理无匹配情况。使用频率覆盖每次作业问答、代码建议和教师备课，影响范围覆盖学生端、教师端与 AI 接口。

成功指标：学生问答和代码建议响应带有可解释的学习图谱投影；教师焦点页能够直接创建带知识点与班级范围的练习；向量查询在候选加载前执行学生与作业范围过滤；离线评估记录过滤候选数量和查询延迟；撤回、无结果和索引失败具有明确状态。

依赖与恢复方式：依赖现有 SQLAlchemy 向量存储、学习图谱模型、作业与班级权限检查、AI JSON/SSE 响应和教师模板。恢复时使用已验证提交 `9046c8a1130113571c3222c1df258b2fb6b983f0`，在生产目录重新执行 `bash /var/www/codesense/update.sh`，再复查服务状态与探针。

## 研究依据与设计约束

研究日期为 2026-09-20。以下内容区分公开证据与针对 CodeSense 的设计推断：

- [GitHub Copilot research-plan-iterate](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/research-plan-iterate)：公开说明支持研究、计划、执行、测试和检查点。采用可见的查询状态、来源状态和用户可继续的下一步；CodeSense 保留教师参与与学习引导边界，不直接替学生完成作业。
- [Qdrant filtering](https://qdrant.tech/documentation/search/filtering/) 与 [Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/)：公开说明检索条件过滤和索引字段会影响查询范围与性能。针对 CodeSense 的推断是将学生、作业和班级范围过滤放在候选加载之前，并记录过滤前后数量与延迟；当前使用 SQLAlchemy 存储，暂不引入 Qdrant、重排或 GraphRAG。
- [Microsoft GraphRAG default dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)：公开说明来源、文本单元、实体和关系需要保留可追溯链路。采用来源引用、版本、作用域和无结果状态；当前使用受限投影，暂不建立全量 GraphRAG 管道。
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)：公开标准强调可感知、可操作、可理解和兼容性。采用已有模板的键盘可用表单、明确状态文案和返回后参数保持；本轮不扩大到独立视觉改版。

## 主工作区与候选融合

- 主工作区 `E:\CodeSense\源代码` 在本轮开始时包含 49 个已修改跟踪文件和 2 个未跟踪文件，未提交改动没有进入候选分支，也没有执行覆盖、删除、清理或 Git 回退操作。
- 未跟踪文件为 `tests/test_question_bank_features.py` 与 `utils/scoring.py`；已修改文件涉及题库、评分、学生端、教师端、演示数据、服务任务和模板等现有工作，全部保持原样。
- 隔离候选工作树为 `E:\CodeSense\源代码\.worktrees\knowledge-retrieval-20260920`，从 `origin/main` 的 `b8e4072` 创建，使用候选数据库 `instance/pr_student_code_review.db`，没有读取主数据库写入状态。
- 产品代码提交为 `b48db2342206c9f855d89872ad5f48057bd58a23`，已推送到远端 `main`。本轮报告文件随后作为文档收尾提交进入远端，产品 Release 仍指向上述产品代码提交。

## 独立交付项与验收

### 交付项 1：学生作业问答返回学习图谱投影

- 用户价值：学生在当前作业问答中获得知识点、学习记录和下一步建议。
- 受影响端：学生端作业问答、AI API JSON。
- 变更文件：`routes/api.py`、`services/learning_graph.py`、`tests/test_knowledge_rag.py`。
- 融合入口：`/api/ask_question` 的完成响应增加 `student_learning_graph`。
- 真实验收证据：已覆盖 grounded 与 no-result JSON；图谱投影只输出白名单字段、来源引用、版本和学生私有作用域。
- 必要性结论：保留并发布，直接连接学生问答与知识图谱。
- 发布与恢复：随 v1.7.0 发布；恢复到前一稳定提交并执行生产更新脚本。

### 交付项 2：学生问答 SSE 保持同一图谱状态

- 用户价值：流式问答完成后，学生获得与 JSON 路径一致的知识依据，刷新或等待过程不会丢失下一步信息。
- 受影响端：学生端 AI 对话、SSE 客户端。
- 变更文件：`routes/api.py`、`tests/test_knowledge_rag.py`。
- 融合入口：`/api/ask_question` 的 SSE done 事件。
- 真实验收证据：测试读取 done 事件并检查图谱字段；没有匹配时返回可理解的 no-result 状态。
- 必要性结论：保留并发布，修复流式入口与普通入口的字段差异。
- 发布与恢复：同交付项 1。

### 交付项 3：Code Studio AI 建议接入学习图谱

- 用户价值：学生请求代码建议时，可以看到与当前作业相关的知识点和学习记忆，帮助学生理解错误来源。
- 受影响端：Code Studio、代码建议 JSON 与 SSE。
- 变更文件：`routes/api.py`、`tests/test_code_advice_knowledge.py`。
- 融合入口：`/api/code_advice` 的 chat 与 analyze 响应。
- 真实验收证据：已覆盖两类 JSON 响应与流式响应；响应使用同一学生范围过滤和图谱投影。
- 必要性结论：保留并发布，完成学生主流程的第二个消费入口。
- 发布与恢复：同交付项 1。

### 交付项 4：教师班级知识焦点增加聚合信号

- 用户价值：教师能够查看样本数量、平均掌握度、低掌握数量和信号状态，判断是否需要创建练习。
- 受影响端：教师知识点焦点页、班级聚合查询。
- 变更文件：`services/learning_graph.py`、`templates/teacher_knowledge_focus.html`、`tests/test_learning_graph.py`。
- 融合入口：教师知识点趋势与焦点页面。
- 真实验收证据：测试检查 aggregate scope、样本数量、平均掌握度和低掌握数量；页面显示空数据状态与创建练习入口。
- 必要性结论：保留并发布，直接改善教师对班级信号的理解。
- 发布与恢复：同交付项 1。

### 交付项 5：教师焦点到知识点与班级练习

- 用户价值：教师可以从知识焦点直接进入布置作业页面，保留知识点与班级范围，减少跨页重复选择。
- 受影响端：教师端焦点页、布置作业页、作业创建接口。
- 变更文件：`routes/assignments.py`、`templates/teacher_add_assignment.html`、`templates/teacher_knowledge_focus.html`、`tests/test_learning_graph.py`。
- 融合入口：教师焦点页的“创建针对性练习”链接与 `/teacher/add`。
- 真实验收证据：测试检查知识点关系、班级授权、事务写入和回到作业详情的流程；无权限班级被拒绝。
- 必要性结论：保留并发布，完成教师端主流程闭环。
- 发布与恢复：同交付项 1。

### 交付项 6：学生向量查询在候选加载前过滤作用域

- 用户价值：学生检索只接触本人有效学习记忆和当前作业相关内容，降低串读风险并减少无关候选。
- 受影响端：学生向量存储、作业反馈检索。
- 变更文件：`services/student_vector_store.py`、`tests/test_student_vector_store.py`。
- 融合入口：学生私有向量查询与作业过滤查询。
- 真实验收证据：SQL 事件测试确认学生与 active 条件在向量行加载前进入 SQL；作业过滤候选数与结果数符合测试数据。
- 必要性结论：保留并发布，属于学生向量库的权限底线。
- 发布与恢复：同交付项 1。

### 交付项 7：学生向量离线评估增加过滤与延迟指标

- 用户价值：后续可以复现空数据、过期数据、范围过滤和慢查询样本，支持索引质量判断。
- 受影响端：离线评估、向量检索质量报告。
- 变更文件：`services/student_vector_eval.py`、`tests/test_student_vector_eval.py`。
- 融合入口：离线检索评估服务。
- 真实验收证据：测试检查 scope candidate count、filtered candidate count、单样本延迟、平均延迟和 p95 延迟。
- 必要性结论：保留并发布，满足学生向量库的可复现评估要求。
- 发布与恢复：同交付项 1。

### 交付项 8：图谱投影建立来源、版本和隐私白名单

- 用户价值：学生和教师看到的图谱结果可以解释来源；私有学习记忆不会直接进入教师视图。
- 受影响端：知识图谱服务、学生 AI 响应、教师聚合响应。
- 变更文件：`services/learning_graph.py`、`tests/test_learning_graph.py`。
- 融合入口：`project_student_learning_graph` 与 `build_teacher_knowledge_focus`。
- 真实验收证据：测试检查 `student_private`、`class_aggregate`、source refs、source versions、grounded 和 no-result 状态。
- 必要性结论：保留并发布，直接满足知识图谱边的来源与作用域要求。
- 发布与恢复：同交付项 1。

### 交付项 9：学生图谱空结果与旧响应兼容

- 用户价值：没有学习记录或图谱来源时，页面仍然能够解释当前状态，旧客户端可以忽略新增字段继续运行。
- 受影响端：学生 AI JSON/SSE 客户端、旧接口调用方。
- 变更文件：`routes/api.py`、`tests/test_knowledge_rag.py`、`tests/test_code_advice_knowledge.py`。
- 融合入口：新增字段采用 additive JSON schema，保留原有回答字段和 SSE 事件结构。
- 真实验收证据：no-result、grounded、chat、analyze 与 SSE 测试通过；新增字段缺省时使用空投影。
- 必要性结论：保留并发布，降低旧页面和旧客户端的兼容风险。
- 发布与恢复：同交付项 1。

### 交付项 10：教师入口保留焦点参数与返回状态

- 用户价值：教师从焦点页面进入练习表单后，仍能看到当前知识点与班级上下文，提交后能够回到连续流程。
- 受影响端：教师焦点页、作业表单、窄屏表单状态。
- 变更文件：`templates/teacher_knowledge_focus.html`、`templates/teacher_add_assignment.html`、`tests/test_learning_graph.py`。
- 融合入口：焦点页查询参数、表单隐藏字段与提交后跳转。
- 真实验收证据：测试检查 query 参数传递、班级授权和保存结果；模板保留空数据与提示状态。
- 必要性结论：保留并发布，修复主流程的信息断点。
- 发布与恢复：同交付项 1。

### 交付项 11：版本说明与信息图进入发布资料

- 用户价值：学生、教师和项目协作者可以从 README、CHANGELOG 与 Release 直接理解此次更新的使用方式和收益。
- 受影响端：公开 README、CHANGELOG、GitHub Release、项目知识文档。
- 变更文件：`README.md`、`CHANGELOG.md`、`docs/assets/codesense-v1.7.0-knowledge-retrieval.png`。
- 融合入口：GitHub Release v1.7.0。
- 真实验收证据：Release 指向 `b48db23`，信息图上传成功，SHA-256 为 `16aedc4b036b9ce5773b6d1398f59b3e60562eda88ed4cdd6097bc9468984ac1`；原生生成结果已显示，保留人工视觉复核风险。
- 必要性结论：保留并发布；视觉复核列为 needs_human 遗留项，不能用自动化测试替代。
- 发布与恢复：Release 地址为 <https://github.com/XiaoCow666/CodeSense/releases/tag/v1.7.0>；恢复方式同交付项 1。

### 交付项 12：线上服务与公开入口核验

- 用户价值：确保知识闭环发布后，登录入口、健康检查、就绪检查和必要 worker 继续可用。
- 受影响端：生产应用、提交 worker、能力 worker、公开入口。
- 变更文件：`docs/ops-runs/2026-09-20-knowledge-retrieval-loop.md`。
- 融合入口：生产目录 `/var/www/codesense` 与公开探针。
- 真实验收证据：Workbench 执行 `bash /var/www/codesense/update.sh` 返回 0；应用服务、提交 worker、能力 worker 均 active；服务器本机和 `https://saucodesense.com` 的 `/healthz`、`/readyz`、`/login` 均返回 200。
- 必要性结论：保留并发布，确保产品功能与服务运行状态同步。
- 发布与恢复：恢复到已验证稳定提交，再执行同一更新脚本与探针核验。

## 真实角色走查与融合复盘

- 学生路径：作业问答 JSON、作业问答 SSE、Code Studio 代码建议 JSON/SSE 均由测试客户端走通；覆盖 grounded、no-result、空学习记录、来源字段和学生私有范围。
- 教师路径：知识点焦点聚合信号、创建针对性练习、知识点关系、班级授权和返回状态均由测试客户端走通；覆盖空数据与越权班级。
- 管理员路径：本轮没有修改管理员入口、权限配置和管理员数据，运行现有回归以确认角色注册与应用启动没有受到影响。
- 最差断点：知识图谱没有来源时，用户容易把空结果理解成系统故障。本轮增加 grounded/no-result 状态和来源版本字段，教师页面增加信号状态、样本数和低掌握数量。
- 返回后状态：教师焦点参数在表单中继续传递；学生 AI 新字段为 additive，旧响应字段保持可用。
- 桌面与窄屏：本轮只改动教师信息区和表单上下文传递，没有新增横向结构；现有模板回归通过。浏览器登录后的完整三角色手动操作未在本环境执行，保留为待人工复核项。

## 测试与自审

- 首次目标测试：实现前 7 个目标测试按预期失败，用于确认测试覆盖真实缺口。
- 目标测试：7 个通过；受影响测试文件合计 46 个通过；README 读取测试 2 个通过。
- 全量测试：`837 passed, 2199 warnings`。
- 代码检查：`python -m compileall -q services routes` 通过；`git diff --check` 通过。
- 警告分类：现有 Flask-Session 弃用提示、SQLAlchemy legacy Query.get 提示、drop ordering 提示和 collection warning；本轮没有关闭测试、修改断言或增加伪造数据。
- 自审结论：代码边界、学生权限过滤、教师班级权限、旧 schema 兼容、部署服务状态均通过；信息图人工视觉复核和登录后浏览器走查保留 needs_human。

## 发布与外部同步

- 远端：`origin/main` 已从 `b8e4072` 推送到产品提交 `b48db23`。
- 生产目标：region `cn-heyuan`，instance `i-f8zbujornnh55dsydozz`，目录 `/var/www/codesense`。
- 发布脚本：`bash /var/www/codesense/update.sh` 返回 0，耗时约 17.5 秒；服务重新启动并通过本机探针。
- GitHub Release：<https://github.com/XiaoCow666/CodeSense/releases/tag/v1.7.0>。
- 信息图：GitHub Release 附件与项目知识文档均已写入，消息上传 key 为 `img_v3_0215n_1026a0e2-97ba-4619-9fee-5d1ace4ae8eg`。
- Feishu 群消息：`CodeSense 研发协作` 消息 `om_x100b65c12e6ec0b0b305d40ad75b56d`；`CoDeBuGo 总群` 消息 `om_x100b65c12f9120a4b1d80ab77a6bd81`。两条消息均由 `牛顿不讲理·CodeX` 发送，内容与信息图一致。
- 项目知识文档：<https://hcnohkzwsogo.feishu.cn/docx/HyhsdpRUgomhknxEgCvcApgungd>，复读 revision `24`；v1.7.0 文本、Release 链接和图片 block `doxcnUm7DeRPE9H7EQ21ybR0o2g` 均存在。

## 必要性结论与下一轮候选

本轮 12 个交付项均有用户入口、数据范围或发布证据，保留 v1.7.0。图谱投影、学生向量范围过滤和教师练习入口均进入真实流程；没有新增孤立接口。现阶段维护成本主要来自 SQL 查询过滤与来源字段兼容，收益覆盖学生问答、Code Studio 和教师干预频率，继续保留。

下一轮候选：向量索引生命周期的重建任务与失败重试、过期学习记忆清理、图谱来源撤回后的离线回归集、学生与教师浏览器登录后的完整角色走查、信息图人工视觉复核。候选进入开发前继续检查数据权限、删除影响和离线指标。

