# 学生向量库最小闭环实施计划

> **For agentic workers:** 本计划按任务逐项执行，每个任务都需要先写失败测试，再写最小实现并复跑相关测试。

**目标：** 建立学生作用域明确、来源可追溯、可撤回和可重建的学习记录向量索引，并接入学生首页与 AI 辅导。

**架构：** 使用新增 SQLAlchemy 表保存学生学习来源、脱敏稀疏向量、revision、状态和检索日志。服务层负责来源构建、权限过滤、相似度检索、撤回和事务回滚；学生首页展示状态与重建入口，`ask_question` 和 `code_advice` 只接收当前学生的受限上下文。

**技术：** Flask、Flask-SQLAlchemy、SQLite/MySQL、现有 `NgramCountEmbedder`、现有知识证据投影、pytest、Jinja2、现有 Bootstrap 样式。

**设计文档：** `docs/superpowers/specs/2026-09-18-student-vector-library-design.md`

## 全局约束

- 所有索引查询必须按当前 `student_id` 过滤，作业查询还必须按 `assignment_id` 过滤。
- 索引文本不得包含学生提交代码，查询日志不得包含问题原文、代码、回答和身份明文。
- 学生向量只服务学习提示和 AI 辅导，不参与评分、排名或能力判定。
- 新增数据库表必须支持 SQLite 与 MySQL，历史表和历史数据保持兼容。
- 撤回使用状态过滤，重建写入失败时事务回滚并保留上一版 active 记录。
- 每个新行为必须有真实数据库测试，禁止使用 mock 伪造通过结果。

### 任务一：新增学生向量生命周期模型

**文件：**

- 修改：`models.py`
- 测试：`tests/test_student_vector_store.py`

**接口：**

- 提供 `StudentLearningVector`、`StudentVectorIndexState`、`StudentVectorRetrievalLog` 三个 SQLAlchemy model。
- `StudentLearningVector` 提供学生、来源、版本、作业作用域、脱敏文本、向量 JSON、revision、状态和撤回时间字段。

- [ ] 写失败测试：创建真实测试数据库，写入同一学生的一条向量记录，断言三张表可以创建并保留来源字段、状态字段和唯一来源版本约束。
- [ ] 运行 `python -m pytest tests/test_student_vector_store.py -q`，确认新增 model 尚未定义导致失败。
- [ ] 修改 `models.py`，添加三个 model、外键、索引和唯一约束；不修改既有字段。
- [ ] 重新运行同一测试，确认表创建、写入、查询和约束通过。
- [ ] 提交 `feat: add student vector lifecycle models`。

### 任务二：实现来源构建、检索、撤回和日志

**文件：**

- 创建：`services/student_vector_store.py`
- 测试：`tests/test_student_vector_store.py`

**接口：**

- `rebuild_student_vector_index(student_id, *, embedder=None)`：从当前学生的评测反馈和知识点评分构建或更新索引。
- `search_student_learning_vectors(student_id, query, *, assignment_id=None, limit=5)`：返回状态、来源收据、revision、检索模式和低基数指标。
- `revoke_student_vector_source(student_id, source_type, source_id)`：撤回当前学生的一类来源。
- `get_student_vector_snapshot(student_id)`：返回首页可显示的状态摘要，不返回学生编号和向量正文。

- [ ] 写失败测试：真实数据库中创建两个学生、两个作业、提交反馈和知识点评分；断言重建只生成目标学生记录，检索只返回目标学生和允许作业作用域的来源。
- [ ] 运行目标测试，确认 service 尚未定义导致失败。
- [ ] 写失败测试：撤回来源后再次检索为空，且检索日志只保存 query hash、revision、模式和数量。
- [ ] 运行目标测试，确认撤回和日志行为失败。
- [ ] 实现有界来源读取、`KnowledgePrivacyFilter` 脱敏、`NgramCountEmbedder` 向量保存、事务性 revision 更新和余弦检索。
- [ ] 实现旧 active 来源撤回、同版本来源复用和失败事务恢复；返回 `not_built`、`no_result`、`ready`、`failed`、`unavailable` 状态。
- [ ] 重新运行目标测试，确认来源、作用域、撤回、重建和日志全部通过。
- [ ] 运行离线评测扩展，确认个人来源过滤与撤回指标可复现。
- [ ] 提交 `feat: add scoped student learning vector store`。

### 任务三：把提交评测接入索引重建

**文件：**

- 修改：`routes/api.py`
- 修改：`tasks/submission_tasks.py`
- 测试：`tests/test_student_vector_store.py`
- 测试：`tests/test_submission_worker.py`

**接口：**

- 正式提交评测成功并完成知识点评分后调用 `rebuild_student_vector_index(student_id)`。
- 重建状态写入日志，提交结果和 AI 评测结果保持原有响应兼容。

- [ ] 写失败测试：通过现有提交评测流程完成一条真实反馈后，断言学生向量快照有 active 来源。
- [ ] 运行测试，确认提交流程没有触发索引重建。
- [ ] 在同步提交与 RQ/线程 worker 的共同收口位置调用 service，保留提交成功响应字段。
- [ ] 重新运行提交、worker 和向量目标测试，确认重建被调用且旧字段保持不变。
- [ ] 提交 `feat: refresh student vectors after evaluation`。

### 任务四：加入学生首页状态与重建入口

**文件：**

- 修改：`routes/main.py`
- 创建：`templates/components/student_learning_memory.html`
- 修改：`templates/student_home.html`
- 修改：`static/modern.css`
- 测试：`tests/test_student_vector_store.py`
- 测试：`tests/test_learning_graph_ui.py`

**接口：**

- `GET /home` 读取 `student_vector_snapshot`。
- `POST /student/rebuild-learning-memory` 只允许学生本人触发重建并返回首页。

- [ ] 写失败测试：登录学生访问首页，断言存在“我的学习记忆”、来源数量、状态文本和重建按钮；教师首页不得出现学生向量正文。
- [ ] 运行测试，确认模板与路由尚未接入导致失败。
- [ ] 在首页加入状态面板、空状态、失败状态、键盘可操作重建按钮和窄屏样式。
- [ ] 实现重建路由的身份校验、成功提示、失败提示和返回路径。
- [ ] 重新运行首页、权限和图谱 UI 测试，确认学生、教师和未登录路径通过。
- [ ] 提交 `feat: surface student learning memory status`。

### 任务五：把个人检索接入 AI 辅导 JSON 与 SSE

**文件：**

- 修改：`services/student_vector_store.py`
- 修改：`routes/api.py`
- 测试：`tests/test_student_vector_store.py`
- 测试：`tests/test_knowledge_rag.py`
- 测试：`tests/test_code_advice_knowledge.py`

**接口：**

- `ask_question` 和 `code_advice` 调用当前学生的受限检索。
- 完成响应增加 `student_learning_retrieval` 和 `student_learning_evidence`，增量字段不影响旧客户端。
- SSE 只在 `done` 事件返回收据，`delta` 不携带个人来源正文。

- [ ] 写失败测试：学生对当前作业提问时，真实检索结果进入 AI 上下文并出现在 JSON 完成数据；其他学生来源和其他作业来源不出现。
- [ ] 运行测试，确认 AI 路由没有个人检索字段。
- [ ] 写失败测试：SSE `start`、`delta`、`done` 顺序保持稳定，个人收据只出现在 `done`。
- [ ] 运行 SSE 测试，确认收据边界失败。
- [ ] 实现私有检索上下文、收据投影、无索引和超时回退；复用已有 assignment evidence 状态。
- [ ] 重新运行 AI 相关测试和现有知识证据回归，确认 JSON/SSE 兼容、权限过滤和安全回退通过。
- [ ] 提交 `feat: ground tutoring in private learning history`。

### 任务六：扩展离线评测与真实角色走查证据

**文件：**

- 修改：`services/knowledge_eval.py`
- 修改：`tests/test_knowledge_eval.py`
- 创建：`tests/fixtures/student_vector_eval.json`
- 创建：`docs/ops-runs/2026-09-18-student-vector-library.md`

- [ ] 写失败测试：固定学生来源、作业作用域和撤回事件，断言 Recall@1、Recall@k、cross_student_hits、revoked_hits 和 mode mismatch 指标。
- [ ] 运行评测测试，确认指标字段尚未存在。
- [ ] 扩展评测 fixture 与评测函数，保留既有 assignment RAG 指标。
- [ ] 运行向量、图谱、AI、提交和首页相关回归。
- [ ] 使用真实测试客户端走学生首页、学生重建、Code Studio AI 提问、教师仪表盘和管理员健康页面；覆盖空状态、失败状态、权限拒绝、返回后状态和窄屏静态检查。
- [ ] 记录最严重断点、修复内容、10 项可独立验收交付、主工作区改动融合清单、测试分类、回滚方式和发布决定。
- [ ] 提交 `docs: record student vector loop validation`。

### 任务七：发布门禁与后续决策

**文件：**

- 修改：`README.md`
- 修改：`CHANGELOG.md`
- 创建：`docs/assets/codesense-v1.5.0-student-vector-loop.png`
- 修改：`docs/ops-runs/2026-09-18-student-vector-library.md`

- [ ] 运行全量 Python 测试、`compileall`、受影响 JavaScript 语法检查和 `git diff --check`。
- [ ] 复查主工作区所有用户改动是否进入候选，保留未进入项及原因。
- [ ] 仅在自审、隔离测试、角色走查、作用域和部署前只读门禁全部通过后，推送远端 main 并执行固定 `update.sh`。
- [ ] 部署后确认线上 commit、应用与 worker 状态、`/healthz`、`/readyz`、登录页和本轮入口。
- [ ] 通过部署门禁后生成用户说明信息图、GitHub Release、项目群消息和项目知识库版本记录；失败时保留候选并记录 `needs_human`。
- [ ] 记录稳定回滚点和遗留风险，完成自动化记忆更新。
