# 2026-09-21 学习记忆恢复运行报告

## 主方案与必要性

- 主方案：把学生向量索引的无变化短路、有限次重试、上一版记录保留、撤回来源过期治理和教师班级汇总接入学生首页、提交评测、AI 问答与教师教学入口。
- 目标用户：学生需要在索引更新失败时继续获得有来源的学习提示；教师需要知道管理班级中哪些学生的学习记录需要更新；AI 辅导需要明确记录来源、索引状态和学生作用域。
- 当前痛点：提交评测成功后，学习记忆更新失败会让后续回答缺少状态说明；撤回来源长期保留会增加治理负担；教师只能从多个页面间接判断学生记录状态。
- 使用频率与影响范围：学生提交、学生提问和教师查看班级数据属于每日高频流程；索引状态影响学生辅导可信度和教师干预顺序。
- 成功指标：无变化重建不增加 revision；构建失败保留上一版 active 记录；重试次数最多两次；撤回和过期来源检索命中为零；学生 JSON/SSE 回执包含状态与作用域；教师汇总只包含管理班级聚合数量；离线评测 `recall_at_1=0.75`、`recall_at_k=1.0`、跨作用域命中为零。
- 依赖：当前 SQLAlchemy 学生向量表、索引状态表、既有学生首页、提交 worker、AI JSON/SSE 接口和教师知识覆盖页面。没有新增数据库迁移、外部向量服务或生产队列。
- 回退方式：回退代码提交后，保留已有 active 向量和索引状态表；删除本轮新增的教师汇总调用不会影响学生向量查询；版本化信息图和文档可以随代码提交一起回退。

## 研究依据与项目推断

- [Qdrant Filtering](https://qdrant.tech/documentation/search/filtering/) 与 [Qdrant Indexing](https://qdrant.tech/documentation/manage-data/indexing/)：官方文档说明过滤条件与 payload 索引可用于限定检索范围。项目约束据此规定学生、作业和来源状态过滤先于相似度计算，并让 `active` 成为唯一可查询状态。
- [SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)：官方文档说明异常后应显式回退当前事务。项目据此保留旧 revision，并让失败重建回退事务后继续抛出 `StudentVectorRebuildError`。
- [WCAG 2.2 Status Messages](https://www.w3.org/TR/WCAG22/#status-messages)：标准要求状态变化可被辅助技术识别。项目据此使用 `role=status` 和 `role=alert` 呈现索引状态、重试提示与过期来源说明。
- [RQ Exceptions](https://python-rq.org/docs/exceptions/) 与 [RQ Jobs](https://python-rq.org/docs/jobs/)：官方文档提供失败处理与任务状态边界。项目据此把索引重建重试限制为两次，避免无界循环，并让提交 worker 在应用上下文内复用已有数据库会话。
- 针对 CodeSense 的推断：学生个人记录需要比公共知识更严格的作用域；失败时显示上一版来源比返回无来源回答更有帮助；教师只需要班级级别的数量与行动入口，页面不能展示学生私有来源。

## 工作区输入与融合清单

- 主工作区 `E:\CodeSense\源代码` 的用户改动已读取并保留：48 个 tracked 文件有未提交改动，另有 `tests/test_question_bank_features.py` 与 `utils/scoring.py` 两个未跟踪文件。改动内容集中在评分范围、题库批量功能、教师快照筛选与相关模板测试。
- 上述主工作区改动没有复制到本轮候选，也没有执行覆盖、清理、暂存或回退操作。它们仍属于用户候选，待后续独立融合。
- 候选工作树：`E:\CodeSense\源代码\.worktrees\learning-memory-rebuild-20260921`，基于 `9a6b635` 创建，当前候选提交包含文档、服务、路由、模板、worker 与测试。
- 运行期间远端 `main` 前进至 `aeba547b3df089ff27a8a7bd6db14d7617bd0a06`，新增内容位于 `cloudflare/automation`，与本轮学习记忆文件无文件重叠。集成工作树需要以该远端提交为基础。

## 独立交付项

1. 学生学习索引无变化短路。用户价值：重复刷新不会改变 revision，也不会造成无意义的重新计算。受影响端：学生首页、提交后的索引更新服务。变更文件：`services/student_vector_store.py`、`tests/test_student_vector_store.py`。融合入口：`rebuild_student_vector_index()`。验收证据：`test_rebuild_keeps_revision_when_sources_are_unchanged`，主流程测试组通过。必要性：高频提交路径需要幂等刷新。发布状态：候选完成，等待集成。回退方式：恢复索引服务的旧构建分支。
2. 学习索引有限次重试。用户价值：短暂 embedding 或数据库错误不会立即中断学习记忆更新。受影响端：学生首页重建路由、提交 worker。变更文件：`services/student_vector_store.py`、`routes/main.py`、`tasks/submission_tasks.py`。融合入口：`rebuild_student_vector_index_with_retry()`。验收证据：`test_retry_entrypoint_retries_after_a_build_failure`、`test_student_rebuild_route_uses_bounded_retry_entrypoint`。必要性：学生和 worker 共用同一更新边界。发布状态：候选完成，等待集成。回退方式：恢复单次构建调用。
3. 失败重建保留上一版 active revision。用户价值：索引更新失败时，学生仍可获得上一版个人学习记录。受影响端：向量服务、AI 问答。变更文件：`services/student_vector_store.py`、`tests/test_student_vector_store.py`、`tests/test_knowledge_rag.py`。融合入口：`search_student_learning_vectors()` 与 `project_student_learning_evidence()`。验收证据：`test_failed_rebuild_keeps_previous_active_revision_and_can_retry`。必要性：避免一次更新失败造成学习上下文完全中断。发布状态：候选完成，等待集成。回退方式：恢复旧状态写入逻辑，保留现有表数据。
4. 撤回来源过期治理。用户价值：过期来源保留审计信息，同时永久退出 AI 查询。受影响端：学生来源管理、向量查询。变更文件：`services/student_vector_store.py`、`templates/components/student_learning_memory.html`、`tests/test_student_vector_store.py`。融合入口：`rebuild_student_vector_index()` 与学生来源投影。验收证据：`test_rebuild_marks_old_revoked_rows_expired_without_querying_them`。必要性：撤回后的来源需要长期可审计，查询需要保持清晰边界。发布状态：候选完成，等待集成。回退方式：恢复 `revoked` 查询排除逻辑并保留数据库记录。
5. 用户撤回状态跨版本保留。用户价值：学生撤回的记录不会因来源版本变化重新进入个人检索。受影响端：学生来源管理、提交更新。变更文件：`services/student_vector_store.py`、`tests/test_student_vector_store.py`。融合入口：来源键与 `user_revoked` 标记。验收证据：`test_user_revocation_survives_source_version_change`。必要性：保护学生对个人学习记录的控制。发布状态：候选完成，等待集成。回退方式：恢复来源版本比较前的状态逻辑。
6. 学生首页显示失败、过期和重试状态。用户价值：学生能知道当前回答使用上一版记录，也能找到重试入口。受影响端：学生首页、键盘操作和辅助技术状态提示。变更文件：`templates/components/student_learning_memory.html`、`tests/test_student_vector_store.py`。融合入口：学生首页索引状态卡与来源列表。验收证据：`test_student_home_explains_expired_sources_without_offering_revoke` 及渲染 HTML 检查。必要性：状态信息需要回到学生可执行的动作。发布状态：候选完成，等待集成。回退方式：恢复旧状态文案与按钮渲染。
7. 提交评测接入同一重建入口。用户价值：提交完成后学生学习记忆使用与首页相同的重试和事务边界。受影响端：提交 worker、学生历史和后续 AI 辅导。变更文件：`tasks/submission_tasks.py`、`tests/test_submission_worker.py`。融合入口：`refresh_student_learning_index()`。验收证据：`test_formal_worker_updates_submission_in_isolated_database` 和 worker 文件 6 项测试通过。必要性：提交是学习记忆最常见的来源入口。发布状态：候选完成，等待集成。回退方式：恢复 worker 的单次索引更新调用。
8. worker 复用已有应用上下文。用户价值：RQ worker 提交完成后，外层页面会立即读取到 `evaluated` 状态和 `ready` 索引状态。受影响端：RQ worker、提交详情与学生首页。变更文件：`tasks/submission_tasks.py`。融合入口：`evaluate_submission_async()`。验收证据：完整测试首次发现旧会话读取问题，修复后 `850 passed`，worker 文件 `6 passed`。必要性：避免后台任务提交成功与页面状态不一致。发布状态：候选完成，等待集成。回退方式：恢复应用上下文创建方式，并同步回退 worker 修复提交。
9. AI JSON 回执传递索引状态。用户价值：学生问答能够分辨当前记录、上一版记录和查询范围。受影响端：学生 AI 问答、学习证据面板。变更文件：`services/student_vector_store.py`、`routes/api.py`、`tests/test_knowledge_rag.py`。融合入口：`/api/ask_question`。验收证据：`test_ask_question_exposes_previous_revision_after_index_failure`。必要性：AI 输出需要可解释的来源状态。发布状态：候选完成，等待集成。回退方式：新增字段可随 API 投影回退，旧回答字段保持兼容。
10. AI SSE 回执传递索引状态。用户价值：流式辅导与普通 JSON 请求拥有相同的来源和状态说明。受影响端：Code Studio AI、流式问答。变更文件：`services/student_vector_store.py`、`routes/api.py`、`tests/test_knowledge_rag.py`、`tests/test_code_advice_knowledge.py`。融合入口：AI SSE `done` 事件。验收证据：`test_ask_question_sse_exposes_previous_revision_after_index_failure` 与跨协议测试通过。必要性：流式入口不能丢失个人记录状态。发布状态：候选完成，等待集成。回退方式：移除新增投影字段，保留原有事件结构。
11. 教师班级学习记录汇总。用户价值：教师从一个入口看到管理班级内 ready、stale、failed 和未构建数量。受影响端：教师首页、班级知识覆盖。变更文件：`services/student_vector_health.py`、`routes/main.py`、`templates/teacher_home.html`、`tests/test_student_vector_health.py`。融合入口：教师首页 `班级学习记录索引` 面板。验收证据：`test_teacher_learning_memory_health_uses_managed_class_aggregate`、`test_teacher_dashboard_renders_learning_memory_health_and_scope`。必要性：教师需要行动优先级，页面只提供聚合数字。发布状态：候选完成，等待集成。回退方式：移除教师首页聚合上下文与面板。
12. 教师与管理员作用域隔离。用户价值：教师只看到管理班级汇总，管理员首页不会意外获得教师专用数据。受影响端：教师首页、管理员首页、权限过滤。变更文件：`services/student_vector_health.py`、`routes/main.py`、`templates/teacher_home.html`、`tests/test_student_vector_health.py`、`tests/test_learning_graph.py`。融合入口：managed class 查询与 dashboard 角色分支。验收证据：`test_teacher_dashboard_renders_learning_memory_health_and_scope`、`test_admin_dashboard_does_not_receive_teacher_learning_memory_panel`。必要性：学生私有来源不能跨角色展示。发布状态：候选完成，等待集成。回退方式：恢复教师页面原有上下文。
13. 学生向量离线检索评测。用户价值：每次重建和查询规则变化都能复现召回与作用域安全结果。受影响端：向量服务、发布复审。变更文件：`services/student_vector_eval.py`、`tests/test_student_vector_eval.py`。融合入口：离线 fixture 评测命令。验收证据：`1 passed`；5 条来源中 active 3、revoked 1、expired 1，4 次查询 `recall_at_1=0.75`、`recall_at_k=1.0`、跨作用域命中 0、撤回命中 0、状态不匹配 0。必要性：向量检索结果需要可重复检查。发布状态：候选完成，等待集成。回退方式：保留评测 fixture，回退查询实现后重新比较指标。

## 三条主流程闭环

1. 学生提交代码后，RQ worker 完成评测，调用学生索引重建入口；索引成功进入 `ready`，失败保留上一版；学生首页显示状态与重试入口。
2. 学生从首页或 Code Studio 发起 AI 请求，JSON 与 SSE 都经过学生和作业作用域过滤，返回来源、版本、状态与作用域；索引失败时回答说明正在使用上一版个人记录。
3. 教师打开首页，服务先过滤管理班级，再读取学生索引状态并生成聚合数量；教师沿已有知识覆盖入口继续查看教学重点，页面不输出学生来源标识。

## 真实角色走查与融合验收

- 学生路径：使用 Flask test client 与隔离数据库验证首页加载、空记录、失败重建、过期来源、撤回来源、学生个人重建路由、提交 worker、AI JSON 和 AI SSE。`64 passed` 的主流程组与完整套件均通过。
- 教师路径：验证管理班级与未管理班级的过滤、ready/stale/failed/not-built 数量、已有知识覆盖入口和返回后的页面状态。教师页面仅出现聚合字段。
- 管理员路径：验证管理员首页不会接收教师学习记录汇总；教师专用面板没有进入管理员模板。
- 状态与权限：检索只读取 `active`，撤回和过期来源不参与查询；失败状态使用上一版记录时，回执包含 `index_status` 与 `freshness_status`。
- 页面可用性：模板检查包含 `role=status`、`role=alert`、键盘可操作按钮和既有响应式容器。当前执行环境没有浏览器自动化，本轮采用 Flask 渲染、静态 HTML 和接口回执检查作为窄屏与辅助技术验收证据，实际设备宽度仍列入后续风险。
- 使用后复盘：原有最大断点是 worker 已完成评测、页面仍读取 `pending`。复用活动应用上下文后，提交、索引和页面读取状态一致；过期来源仍显示审计保留信息，学生不会得到撤回操作入口。

## 测试与质量分类

- 基线：候选初始完整套件为 `837 passed`。
- 失败分类：首次完整套件出现 1 个 worker 会话状态失败；确认是嵌套 Flask 应用上下文产生旧会话对象，已通过复用同一应用上下文修复。
- 当前完整套件：`850 passed`，退出代码 0，耗时 8 分 40 秒。
- 受影响主流程组：`64 passed`，退出代码 0，耗时 2 分 11 秒。
- 离线评测：`1 passed`，召回、撤回过滤、跨作用域过滤与状态一致性均通过。
- 静态检查：`compileall`、`node --check static/js/knowledge-evidence.js`、`git diff --check` 均通过。
- 警告分类：现有 Werkzeug/AST、SQLAlchemy Query API、UTC 时间接口、Flask session 属性、fakeredis 和表删除外键循环提示；本轮没有关闭警告或修改测试以制造通过结果。

## 版本材料

- 版本：`v1.8.0`。
- README：增加学习记忆恢复与教学闭环信息图、学生与教师可见收益说明。
- CHANGELOG：增加学生重试、上一版记录、撤回/过期过滤、教师聚合入口说明。
- 信息图：`docs/assets/codesense-v1.8.0-learning-memory-recovery.png`。使用 GPT Image/ImageGen 生成，已通过原生媒体结果检查文字可读性、裁切、错字和主题一致性。
- 当前候选代码提交：`f973b7f`；发布材料和运行报告提交完成后，以集成工作树的完整提交作为部署候选。

## 发布、部署与外部同步

- 远端基线：`origin/main=aeba547b3df089ff27a8a7bd6db14d7617bd0a06`，集成工作树必须从此提交创建。
- 生产目标：已通过 Workbench 列出 `cn-heyuan` 的 `i-f8zbujornnh55dsydozz`，实例状态为 `Running`；部署目录固定为 `/var/www/codesense`。
- 预部署只读检查、`update.sh`、线上 commit、应用与 worker 状态、`/healthz`、`/readyz`、公开探针：待集成提交完成后执行并记录结果。
- GitHub Release：待部署核验通过后创建 `v1.8.0`，正文只描述学生、教师和 AI 辅导收到的用户收益。
- 飞书消息：待部署核验通过后，用“小牛顿”对应机器人身份向当前项目群与 CoDeBuGo 总群发送同版用户介绍和信息图；发送前重新解析群成员与群身份。
- 项目知识库：待部署核验通过后写入版本、更新说明、最终信息图、GitHub Release 链接和内部部署证据，并回读核对。
- 当前发布判定：候选代码与本地测试通过，集成、生产部署、Release、飞书和知识库仍未完成，不能宣称已上线。

## 遗留风险与下一轮候选

- 需要继续观察 UTC 时间接口、SQLAlchemy legacy API、Werkzeug AST 兼容提示，当前不影响本轮行为验收。
- 当前没有浏览器设备宽度与真实辅助技术读屏证据，下一轮应补充学生首页、Code Studio 和教师首页的窄屏键盘走查。
- 主工作区评分、题库和教师快照用户改动需要单独完成冲突检查与测试融合。
- 下一轮候选：继续扩大知识图谱来源导入与撤回评测；把教师聚合状态连接到可执行的教学建议；补充学生向量索引重建失败样本的可复现记录。
