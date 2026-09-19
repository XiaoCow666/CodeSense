# 知识点干预与学习记忆治理实施计划

> **For agentic workers:** 每项任务先写失败测试，再写最小实现，随后运行受影响测试与完整回归。

**目标：** 形成教师知识点提醒到布置练习、学生知识路径与 AI 辅导的闭环，并补齐学生学习记忆的来源治理和陈旧索引回退。

**设计文档：** `docs/superpowers/specs/2026-09-19-knowledge-intervention-learning-memory-design.md`

**技术：** Flask、Flask-SQLAlchemy、Jinja2、现有知识图谱投影、现有学生稀疏向量服务、pytest、独立 SQLite 测试数据库。

## 交付清单

1. 学生来源摘要服务：学生可以看到每条个人学习来源的类型、标题、作用域、版本和状态。
2. 学生本人撤回路由：撤回动作经过当前身份与来源边界检查，撤回后立即停止召回。
3. 学生来源治理界面：学生首页显示来源摘要、撤回按钮、成功状态、空状态和失败状态。
4. 陈旧索引状态：长期未更新的索引进入 `stale`，AI 检索走清晰回退，重建后恢复可用。
5. 向量检索质量指标：响应增加过滤候选数量、撤回数量和索引新鲜度，日志不保存问题原文。
6. 教师提醒行动链接：班级知识覆盖提醒带有受管范围内的知识点练习入口。
7. 教师知识点练习页：按班级作用域展示带有该知识点的可用作业，并复用既有布置入口。
8. 学生作业回流：教师布置完成后，学生可从现有首页知识路径进入对应练习。
9. 图谱到 AI 上下文：当前作业知识点关系、掌握度状态和来源指纹进入学生提问与 Code Studio 辅导上下文。
10. 离线评测扩展：加入陈旧来源、撤回来源和空数据样例，输出可复现的状态匹配与安全边界指标。
11. 角色与响应回归：学生、教师、管理员受影响入口完成真实测试客户端走查，确认权限、空状态、错误状态、返回状态和旧 JSON 字段兼容。
12. 发布资料与运行报告：更新 README、CHANGELOG、版本信息图、脱敏运行报告与自动化记忆；只有固定发布门禁全部通过才发布。
13. 教师 AI 建议动作：保留服务端作业编号，教师可从建议卡片进入查看作业与班级布置入口，候选作业限定为当前教师可管理的作业。

## 全局约束

- 测试数据库、Redis、session、日志和上传目录使用候选工作树配置，不能访问主工作区或生产数据库。
- 用户主工作区的未提交文件保持原样；只把已有远端内容和本轮候选带入隔离集成工作树。
- 每个检索入口先完成学生、作业和状态过滤，再计算相似度。
- 任何新增 AI 上下文只服务学习引导，不能写入分数或能力判定。
- 没有删除既有功能、权限扩大、不可逆迁移或生产凭据时继续完成候选；触及人工边界时记录 `needs_human`。

## 任务一：学生来源摘要与撤回接口

**文件：**

- 修改：`services/student_vector_store.py`
- 修改：`routes/main.py`
- 测试：`tests/test_student_vector_store.py`

**TDD 步骤：**

- 添加真实数据库失败测试：重建后能读取当前学生来源摘要，其他学生来源不出现。
- 添加失败测试：当前学生撤回来源后检索无结果；其他学生登录执行同一路由返回拒绝。
- 运行目标测试确认失败。
- 实现摘要投影、来源边界检查、POST 路由和稳定提示。
- 运行目标测试并确认撤回状态、作用域和旧重建规则保持。

## 任务二：学生首页来源治理界面

**文件：**

- 修改：`routes/main.py`
- 修改：`templates/components/student_learning_memory.html`
- 修改：`static/modern.css`
- 测试：`tests/test_student_vector_store.py`
- 测试：`tests/test_learning_graph_ui.py`

**TDD 步骤：**

- 添加失败测试：学生首页显示来源标题、类型、版本摘要和撤回按钮；教师首页不显示个人来源。
- 添加失败测试：来源为空、撤回成功和撤回失败状态均能显示可理解反馈。
- 运行目标测试确认失败。
- 在首页传入有界来源摘要，加入带标签表单、键盘可操作按钮、状态角色和窄屏样式。
- 运行目标测试并检查真实模板渲染。

## 任务三：陈旧索引与检索质量指标

**文件：**

- 修改：`services/student_vector_store.py`
- 修改：`tests/test_student_vector_store.py`
- 修改：`tests/fixtures/student_vector_eval.json`
- 修改：`services/student_vector_eval.py`

**TDD 步骤：**

- 添加失败测试：旧 `last_built_at` 的索引返回 `stale`，不会命中 active 来源；重建后恢复 `grounded`。
- 添加失败测试：指标包含作用域过滤候选数、撤回数和新鲜度状态，日志不包含问题原文。
- 添加失败测试：离线 fixture 的陈旧来源不会进入召回，状态匹配字段可复现。
- 运行目标测试确认失败。
- 添加陈旧阈值、状态回退、指标投影和评测字段。
- 运行向量生命周期测试与离线评测。

## 任务四：教师知识点干预入口

**文件：**

- 修改：`services/learning_graph.py`
- 修改：`routes/main.py`
- 创建：`templates/teacher_knowledge_focus.html`
- 修改：`templates/components/learning_graph_panel.html`
- 修改：`static/modern.css`
- 测试：`tests/test_learning_graph.py`
- 创建：`tests/test_teacher_knowledge_focus.py`

**TDD 步骤：**

- 添加失败测试：教师提醒带有知识点和练习入口；受管教师可以访问知识点页，其他教师收到拒绝。
- 添加失败测试：页面只显示受管班级的作业，作业卡片链接到既有班级布置入口。
- 添加失败测试：无作业时显示空状态和创建作业入口。
- 运行目标测试确认失败。
- 实现班级作用域查询、有限投影、模板和链接；不新增学生个人数据。
- 运行图谱与角色权限测试。

## 任务五：图谱与个人向量接入 AI

**文件：**

- 修改：`services/learning_graph.py`
- 修改：`routes/api.py`
- 修改：`tests/test_code_advice_knowledge.py`
- 修改：`tests/test_knowledge_rag.py`

**TDD 步骤：**

- 添加失败测试：学生提问和 Code Studio 请求的 AI 上下文包含当前作业知识点提示、个人向量来源和作用域说明。
- 添加失败测试：其他作业知识点与其他学生来源不会进入上下文；SSE 完成事件保留现有顺序与收据字段。
- 运行目标测试确认失败。
- 添加当前学生、当前作业的图谱提示函数；在 JSON/SSE 共用上下文收口处接入。
- 运行 AI、图谱和权限回归。

## 任务六：教师 AI 建议动作

**文件：**

- 修改：`services/teacher_ai_advisor.py`
- 修改：`templates/teacher_ai_suggestions.html`
- 测试：`tests/test_teacher_ai_suggestions.py`

**TDD 步骤：**

- 添加失败测试：规则建议和建议页面保留合法作业编号，并显示查看作业、布置到班级两个入口。
- 添加失败测试：建议候选只来自当前教师创建的作业，旧建议缺少作业编号时仍可显示文字。
- 运行目标测试确认失败。
- 实现服务端编号保留、历史 JSON 兼容、候选权限过滤和既有布置入口链接。
- 运行教师建议与作业权限回归。

## 任务七：真实角色路径与融合审查

**文件：**

- 修改：`tests/test_student_vector_store.py`
- 修改：`tests/test_learning_graph.py`
- 修改：`tests/test_teacher_knowledge_focus.py`
- 创建：`docs/ops-runs/2026-09-19-knowledge-intervention-learning-memory.md`

**验收路径：**

- 学生：登录 → 首页来源摘要 → 撤回来源 → 首页状态 → 当前作业 AI 提问/Code Studio → 回到首页确认撤回和索引状态。
- 教师：登录 → 仪表盘知识覆盖 → 知识点练习页 → 选择作业 → 既有班级布置页 → 学生首页知识路径。
- 管理员：登录 → 管理员首页 → 访问学生来源路由与教师知识点页 → 确认权限拒绝和不泄露个人内容。
- 覆盖首屏、空数据、错误/陈旧状态、窄屏静态样式、键盘表单标签、返回后状态和旧 API 字段。

## 任务八：发布门禁

**文件：**

- 修改：`README.md`
- 修改：`CHANGELOG.md`
- 创建：`docs/assets/codesense-v1.6.0-knowledge-intervention.png`
- 修改：`docs/ops-runs/2026-09-19-knowledge-intervention-learning-memory.md`

**门禁：**

- 运行目标测试、全量 pytest、`compileall`、静态资源语法检查和 `git diff --check`。
- 复查主工作区改动融合清单、候选差异、权限与数据边界。
- 只在隔离集成工作树合并最新远端 main、自审通过、服务器只读门禁通过后推送与部署。
- `update.sh` 完整结束并通过线上 HEAD、应用/worker、`/healthz`、`/readyz` 和受影响入口核验后，才创建 Release、发送飞书消息、更新项目知识库。
- 失败或缺少生产连接时保留候选、记录 `needs_human`、回滚点和遗留风险。
