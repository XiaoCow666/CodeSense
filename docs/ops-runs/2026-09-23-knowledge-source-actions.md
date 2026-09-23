# 2026-09-23 教师知识动作与学生学习记忆闭环

运行时间：2026-09-23 10:39:28 +08:00  
候选工作树：`E:\CodeSense\源代码\.worktrees\knowledge-source-actions-20260923`  
候选分支：`codex/knowledge-source-actions-20260923`  
候选父提交：`f5d3f9483bbdf7fb380cd66ca8c3dfbfcfff9932`
候选代码提交：`82d297f9704bba0960e8befa566fdf137d220f87`

## 主方案与必要性

本轮主方案把教师班级知识覆盖、学生学习记忆索引状态、教师可执行动作和学生行动中心连接成一条受权限限制的流程：教师从班级聚合信号进入针对性练习，或发送每日幂等提醒；学生只在自己的行动中心看到提醒，并回到个人学习记忆更新入口。图谱和向量检索继续服务学习引导，不能参与作业评分。

目标用户与痛点：教师能看到知识覆盖和索引数量，却缺少下一步动作；学生个人学习记忆需要更新时，原有入口依赖学生自己发现；教师需要确认图谱关系来自哪些作业标签，学生需要在权限边界内处理自己的来源。

使用频率与影响范围：教师首页、班级详情和 AI 教学建议页属于教师高频入口；提醒按班级每天幂等发送；学生行动中心属于学生提交和学习后的常用入口。服务覆盖教师、学生和管理员三类角色。

成功指标：教师页面可产生带班级作用域、知识点、来源引用和来源版本的动作；提醒只触达当前教师管理班级中需要更新的学生；相同班级同一天重复发送不新增通知；撤回来源后真实向量查询不再返回该来源；学生行动中心可直接回到个人更新入口；全量测试通过。

依赖与恢复方式：复用现有 `AssignmentKnowledgePoint`、`StudentVectorIndexState`、`StudentLearningVector` 和站内通知记录，没有新增表、迁移、外部服务或生产凭据。恢复时创建新提交恢复候选父提交 `f5d3f94` 的代码，再按同一 `update.sh` 发布并核验；本轮未执行生产恢复操作。

## 研究依据与设计约束

- [Microsoft GraphRAG Query overview](https://microsoft.github.io/graphrag/query/overview/)（公开文档，2026-09-23 查阅）：图结构适合表达实体关系并支持受限查询。项目约束为教师查询只读取当前管理班级的聚合数据，边保留来源引用和版本，暂不引入全局图谱召回。
- [Qdrant payload filtering](https://qdrant.tech/documentation/concepts/payload/)（公开文档，2026-09-23 查阅）：检索前需要使用结构化 payload 过滤。项目约束为学生 ID、作业 ID、作用域和状态在数据库查询阶段完成过滤，撤回与过期状态不进入候选。
- [Deep Knowledge Tracing](https://arxiv.org/abs/1506.05908)（论文 arXiv:1506.05908，2015）：学习状态可以随时间更新。项目采用可重建的来源版本和状态计数，暂不使用未经评测的模型推断掌握度。
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)（W3C Recommendation，2023-10-05）：交互需要可感知、可操作、可理解和健壮。本轮动作区域使用语义标题、`role=status`、真实表单按钮、键盘可达链接和 640px 窄屏纵向布局。
- [GitHub Copilot research, plan, and iterate](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/research-plan-iterate)（GitHub 官方文档，2026-09-23 查阅）：AI 工作流适合经过研究、计划、执行和迭代。本轮将图谱建议转换为教师可检查的动作，并保留可回到现有页面的入口。
- [Replit version control](https://docs.replit.com/replit-workspace/workspace-features/version-control)（官方文档，2026-09-23 查阅）：可恢复检查点能降低连续编辑风险。项目采用隔离工作树、父提交记录和新提交恢复方式，生产发布仍须经过线上门禁。

上述资料提供通用证据；把教师动作限制为班级聚合、把学生记忆限制为本人来源、把来源撤回作为查询过滤条件，属于针对 CodeSense 现有数据模型和权限模型的工程推断。

本轮暂不引入 GraphRAG 全局召回、外部向量数据库、重排模型、Deep Knowledge Tracing 评分模型、AI 自动评分或新的消息供应商。这些方向需要独立的离线样本、权限评测和生产运行条件。

## 主工作区改动融合清单

- 主工作区 `E:\CodeSense\源代码` 保留原位修改：49 个 tracked 文件和 2 个未跟踪文件，未执行 `reset`、`checkout`、`clean`、stash 或覆盖操作。
- 本轮读取了主工作区 `git status --short`、staged/unstaged diff、未跟踪文件、`origin/main`、候选工作树和上一轮运行记忆。
- `origin/main` 已更新到 `f5d3f948`。主工作区从旧版本演进而来的差异集中在 `models.py`、`routes/api.py`、`routes/assignments.py`、`routes/main.py`、`routes/thinking.py`、`services/demo_experience.py`、`static/modern.css`、`tasks/submission_tasks.py`、多个模板、测试和 `utils/maturity_calculator.py`。这些修改保留在主工作区，未带入本轮候选，原因是候选必须从当前远端版本继续保留已发布的知识图谱和学生向量功能。
- 主工作区未跟踪的 `tests/test_question_bank_features.py` 与 `utils/scoring.py` 内容已经存在于 `origin/main`，本轮保留主工作区原位文件，候选直接使用远端版本。
- 本轮融合结论：主工作区改动全部保留；与当前远端基线存在版本差异的本地方案暂缓融合；本候选未覆盖主工作区未确认的业务改动。

## 十一项独立交付

### 1. 教师图谱补充直接覆盖关系

用户价值：教师查看知识点建议时，可以追溯到具体作业标签和来源版本。  
受影响端：教师知识覆盖、教师知识点练习页、图谱服务。  
变更文件：`services/learning_graph.py`、`tests/test_learning_graph.py`（既有回归）。  
融合入口：`/teacher_dashboard` 的班级知识覆盖和 `/teacher/knowledge-focus/<knowledge_point>`。  
真实验收证据：教师图谱边包含 `assignment_knowledge_point`、`source_refs`、`source_version`；相关图谱测试通过。  
必要性结论：保留；这是教师动作来源解释所需的数据基础。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除新增直接关系构建并恢复候选父提交。

### 2. 教师聚合教学动作服务

用户价值：教师可以在同一个动作列表中看到知识点练习和学习记忆更新提醒。  
受影响端：教师首页、班级详情、AI 教学建议。  
变更文件：`services/teacher_learning_actions.py`。  
融合入口：`build_teacher_learning_actions` 读取当前教师管理班级的图谱和索引健康状态。  
真实验收证据：服务测试确认返回班级聚合作用域、来源版本、学生数量和待更新人数；序列化结果不含学生 ID、姓名或 `student_private` 内容。  
必要性结论：保留；它提供了跨页面一致的用户动作数据。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除服务文件及其路由调用。

### 3. 教师首页知识动作入口

用户价值：教师登录后可以直接选择练习或发送提醒，减少在知识覆盖、索引状态和班级管理页面之间往返。  
受影响端：教师首页。  
变更文件：`routes/main.py`、`templates/teacher_home.html`、`templates/components/teacher_learning_actions.html`。  
融合入口：`/teacher_dashboard`。  
真实验收证据：教师登录后真实模板响应包含“可执行教学动作”、知识点入口和提醒表单；页面加载保持 200。  
必要性结论：保留；动作有明确入口和下一步反馈。  
发布状态：候选完成，等待发布门禁。  
恢复方式：删除首页上下文与组件包含语句。

### 4. 班级详情动作入口

用户价值：教师查看班级学生状态时，可以基于同一班级的聚合信号继续处理教学动作。  
受影响端：教师班级详情。  
变更文件：`routes/classes.py`、`templates/classes/class_detail.html`。  
融合入口：`/classes/<class_id>`。  
真实验收证据：教师真实角色请求返回班级动作区域和当前班级提醒地址；跨班级动作仍受访问检查保护。  
必要性结论：保留；该入口位于教师进行学情判断的实际页面。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除班级详情上下文和组件包含语句。

### 5. AI 教学建议连接依据与动作

用户价值：教师查看 AI 建议时可以看到知识图谱和索引状态支持的下一步，减少建议与实际操作之间的断点。  
受影响端：教师 AI 建议页。  
变更文件：`routes/main.py`、`templates/teacher_ai_suggestions.html`。  
融合入口：`/teacher/ai_suggestions`。  
真实验收证据：教师页面测试返回“依据与下一步”、知识点和现有班级范围内的动作。  
必要性结论：保留；动作连接已有建议页面，维护成本较低。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除 `learning_actions` 页面上下文和组件包含语句。

### 6. 教师提醒接口与班级权限边界

用户价值：教师可以向当前班级发送更新提醒，外部班级请求会被拒绝。  
受影响端：教师路由、站内通知。  
变更文件：`routes/main.py`、`services/teacher_learning_actions.py`。  
融合入口：`POST /teacher/classes/<class_id>/learning-memory-reminder`。  
真实验收证据：教师请求返回重定向并写入站内通知；外部教师班级返回 403；管理员请求返回 403。  
必要性结论：保留；接口提供明确的权限边界和可操作入口。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除路由和服务调用，保留原有学生自助更新入口。

### 7. 每日幂等站内提醒

用户价值：教师重复点击不会产生重复提醒，学生收到的内容保持单一且清晰。  
受影响端：通知服务、学生行动中心。  
变更文件：`services/teacher_learning_actions.py`、`tests/test_teacher_learning_actions.py`。  
融合入口：每日键 `teacher-learning-memory:<class_id>:<date>:<student_id>`。  
真实验收证据：同一班级同一天重复请求后，每名学生只保留一条通知；外部班级学生没有通知。  
必要性结论：保留；重复提交是教师日常使用中的常见情况。  
发布状态：候选完成，等待发布门禁。  
恢复方式：停用教师提醒入口，历史站内通知记录保留。

### 8. 学生行动中心承接提醒

用户价值：学生可从行动中心直接回到自己的学习记忆更新位置，知道提醒来源和下一步。  
受影响端：学生行动中心、全局导航。  
变更文件：`services/action_center.py`、`tests/test_teacher_learning_actions.py`。  
融合入口：`/action-center`、`/api/action-center`。  
真实验收证据：学生登录后 API 返回 `learning_memory_refresh`、`next` 优先级和本地锚点；HTML 页面显示教师提醒标题和链接。  
必要性结论：保留；通知只有进入学生工作流才形成完整闭环。  
发布状态：候选完成，等待发布门禁。  
恢复方式：删除该通知类型的行动投影，保留普通通知读取功能。

### 9. 学生来源撤回后的真实检索回归

用户价值：学生撤回个人学习来源后，AI 辅导检索不会继续使用该来源。  
受影响端：学生向量库、学生反馈来源、学习记忆治理。  
变更文件：`tests/test_teacher_learning_actions.py`，复用 `services/student_vector_store.py`。  
融合入口：`rebuild_student_vector_index`、`search_student_learning_vectors`、`revoke_student_vector_source`。  
真实验收证据：测试写入真实 `Submission` 反馈，完成索引重建，撤回后查询证据为空，来源状态为 `revoked` 且原因是 `user_revoked`。  
必要性结论：保留；这是学生个人数据撤回边界的直接验收。  
发布状态：候选完成，等待发布门禁。  
恢复方式：测试只写入临时 SQLite，生产恢复沿用现有索引来源状态。

### 10. 离线向量召回、撤回和作用域守护

用户价值：学生向量库的推荐质量和隔离边界可重复检查。  
受影响端：学生向量评测、AI 辅导检索。  
变更文件：`tests/test_teacher_learning_actions.py`，复用 `services/student_vector_eval.py`。  
融合入口：`evaluate_student_vector_fixture`。  
真实验收证据：固定 fixture 的 `recall_at_k` 为 1.0，跨作用域命中、撤回来源命中和状态不一致数量均为 0。  
必要性结论：保留；图谱和向量进入更多页面前必须有可复现的离线指标。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除本轮集成断言，保留现有独立评测服务。

### 11. 窄屏和键盘可用的动作组件

用户价值：教师在窄屏设备上仍能找到完整按钮，键盘用户可以按语义顺序访问动作。  
受影响端：教师首页、班级详情、AI 教学建议页。  
变更文件：`templates/components/teacher_learning_actions.html`、`static/modern.css`。  
融合入口：语义 `section`、标题、真实链接、POST 表单、`role=status` 和 640px 纵向布局。  
真实验收证据：模板渲染检查确认标题、按钮、表单、CSRF 注入点和状态区域存在；静态资源检查通过。受用户规则限制，本轮未执行主动截图检查。  
必要性结论：保留；动作入口属于教师主流程，窄屏可用性会直接影响使用完成率。  
发布状态：候选完成，等待发布门禁。  
恢复方式：移除组件样式并恢复原有页面区域。

## 真实角色走查与使用后复盘

- 教师路径：登录 → `/teacher_dashboard` → 读取班级知识覆盖 → 点击知识点练习或提交提醒 → 重复提交确认幂等 → `/classes/<class_id>` → `/teacher/ai_suggestions`。页面均返回 200，外部班级提交返回 403。
- 学生路径：教师提醒写入后退出教师会话 → 学生登录 → `/api/action-center` → `/action-center` → 跟随 `/#student-learning-memory-title` 回到个人学习记忆入口。学生只看到本人行动项和本人入口。
- 管理员路径：管理员登录 → `/classes/<class_id>` 查看班级摘要；管理员访问教师提醒 POST 返回 403，页面不出现教师动作组件。
- 空数据与错误边界：已有图谱和向量测试覆盖无作业、无知识点、无索引、失败索引、撤回来源和跨作用域访问；本轮新接口覆盖外部班级 403 与重复提醒。
- 最糟断点：通知写入后原行动中心只把它当普通未读消息，学生无法看到清晰的提醒优先级。本轮把 `learning_memory_refresh` 投影为 `next` 行动，并保留本地更新锚点。
- 下一步可见性：教师动作卡片直接显示按钮；学生行动中心显示提醒标题、摘要和跳转链接；页面保持班级聚合提示，不展示学生私有记忆。
- 浏览器证据：本轮按用户规则不主动使用截图和视觉检查，采用 Flask test client、真实模板响应、静态 CSS 检查和角色请求作为降级证据。正式发布仍需人工阅读信息图文字和裁切。

## 融合质量与测试

- 远端基线测试：从 `origin/main=f5d3f94` 建立候选，基线全量测试为 `856 passed`。
- 候选全量测试：`863 passed, 2309 warnings`，耗时约 261.81 秒，退出码 0。警告主要来自既有 Flask-Session、SQLAlchemy 弃用提示和测试数据库外键循环提示。
- 本轮重点测试：教师动作、图谱、学生向量评测、索引健康、行动中心和 AI 建议共 `39 passed`；新增角色页面与管理员边界测试包含在全量结果内。
- Python 检查：`python -m compileall -q services routes tasks models.py utils` 通过。
- 差异检查：`git diff --check` 通过。
- 没有新增数据库迁移、Redis 写入、外部消息供应商、AI 模型调用或评分路径。

## 生产门禁、发布状态与遗留风险

- 目标发现：Workbench 列出 `cn-heyuan` 实例 `i-f8zbujornnh55dsydozz`，状态 Running，目标目录 `/var/www/codesense`。
- 只读生产基线：线上提交 `60f1ee302dadbbea0379117d7e5c9a05420bec90`，远端地址正确，tracked 工作树干净，`update.sh` 存在，应用和两个 worker active。
- 只读健康检查：跟随本地 HTTP 重定向后 `/healthz=200`、`/readyz=200`、`/login=200`。
- `update.sh` 结果：本轮未执行。
- 远端 main：本轮未推送，仍为 `f5d3f948`。
- GitHub Release：本轮未创建。版本信息图尚未生成，用户规则要求的主动视觉检查条件当前不可用。
- 飞书群消息：本轮未发送，发送时点必须晚于生产脚本成功和部署后核验。
- 项目知识库：本轮未更新，避免在发布证据形成前写入外部版本记录；当前已知文档为 `https://hcnohkzwsogo.feishu.cn/docx/HyhsdpRUgomhknxEgCvcApgungd`，上一轮 revision 为 `31`。
- 自审结论：本地代码、数据作用域、页面融合、角色路径和测试门禁通过；发布门禁因信息图人工阅读核验条件缺失而暂停。
- 遗留风险：当前主工作区旧版本本地修改仍未融合；浏览器真实窄屏和键盘体验未执行截图走查；生产环境教师页面、学生行动中心和提醒接口尚未做部署后真实请求验证。

## 下一轮候选

1. 在具备人工视觉核验条件后生成版本化信息图，检查文字、裁切和主题一致性，再决定是否进入发布闭环。
2. 发布后使用教师和学生演示账号完成线上页面路径核验，重点检查站内提醒、学生更新入口和不同班级访问边界。
3. 继续完善知识图谱来源导入、撤回和离线评测入口，把教师动作来源从作业标签扩展到课程资源，同时保持班级和学生作用域过滤。
