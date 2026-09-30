# 2026-09-30 作业学习资料与知识路径

## 目标与决定

- 主方案：教师在已有作业知识点下发布简短学习资料，学生从知识路径阅读，AI 辅导引用当前来源；更新保留版本，撤回立即退出所有当前读路径。
- 目标用户：布置编程作业的教师及其学生。教师已有知识点标签，却无法把针对性资料接进学生练习；学生的图谱建议缺少可直接阅读的解释。
- 使用频率与指标：每份有知识点的作业可反复使用；成功指标为发布后学生与 AI 均可见同一当前来源，撤回后全部不再命中，跨作业与跨学生查询为零。
- 必要性：沿用现有作业、图谱、AI 证据和权限入口；新增两张可回滚表，不引入外部 embedding 服务。保留此候选，不扩展到自动评分。
- 研究： [W3C PROV-O](https://www.w3.org/TR/prov-o/)（2013 规范）支持来源与派生版本可追溯；[OpenAI Vector Stores API](https://platform.openai.com/docs/api-reference/vector-stores?lang=python)（2026-09-30 访问）说明文件生命周期与检索作用域的产品约束。针对 CodeSense 的推断是先做作业范围过滤、人工资料版本和撤回，再考虑混合检索；未采用自动生成关系或把 embedding 用于评分。

## 阶段与门禁（北京时间）

| 阶段 | 开始–结束 | 结束状态 |
| --- | --- | --- |
| 事实与范围复核 | 13:00–13:15 | 完成；主工作区 49 个已修改文件、2 个未跟踪文件、暂存区空，均未改动。远端 main 为 `b48a21f`。 |
| 隔离实现与定向回归 | 13:15–13:27 | 完成；69 项图谱/向量/资料回归通过；证据接口兼容修复后 46 项通过。 |
| 真实角色与窄屏走查 | 13:15–13:34 | 完成；教师发布、学生首页路径与作业阅读、管理员维护入口，390px 页面无横向溢出。测试客户端覆盖撤回、错误、空数据及越权。 |
| 完整回归 | 13:25–13:33 | 一次运行 433.32 秒，946 通过、2 失败。图谱入口回归与既有评测等待页 progressbar 问题已修复，受影响定向回归 22 通过；没有重复跑完整回归。 |
| 旧库兼容与静态检查 | 13:18–13:38 | 隔离复制库运行 `database_maintenance.py` 退出 0，新增表且保留原有用户；compileall 与 `git diff --check` 退出 0。 |
| 生产只读检查 | 13:28–13:31 | 实例 `cn-heyuan/i-f8zbujornnh55dsydozz`，目录 `/var/www/codesense` 干净，HEAD 与 origin/main 均为 `b48a21f`；应用、提交及能力 worker active；本机 HTTPS healthz/readyz 均 200。 |
| 发布材料 | 13:33–13:39 | README 中英版本介绍、CHANGELOG、v2.1.0 Release 正文与独立信息图已准备；图中文字、裁切、主题人工目视通过。 |

## 交付清单

每项均在隔离候选，发布状态以本报告末尾的发布门禁为准。回滚统一为回退候选代码；新增资料表保留只读历史，不执行生产数据删除。

| # | 用户价值与入口 | 影响端与文件 | 真实验收与必要性 |
| --- | --- | --- | --- |
| 1 | 教师可把资料绑定作业知识点并发布；作业编辑页 | 教师、数据：`models.py`、`services/assignment_learning_resources.py`、`routes/assignments.py`、`templates/edit_assignment.html` | 浏览器实际发布；独立库迁移通过。补足标签只有名称的断点，保留。 |
| 2 | 更新资料生成来源版本与修改记录；作业编辑页 | 教师、数据：同上 | 管理员更新、教师历史页可见版本 1/2；旧表不变，保留。 |
| 3 | 旧页面不能覆盖或撤回新版本；编辑/撤回表单 | 教师、可靠性：`routes/assignments.py`、`templates/edit_assignment.html`、`tests/test_assignment_learning_resources.py` | 过期 revision POST 被拒，当前版本保持 active；保留。 |
| 4 | 撤回后停止学生页面、图谱及 AI 引用；撤回按钮 | 教师→学生→AI：资料服务、图谱、RAG、页面 | Flask 真实角色请求和后续查询验证各读路径无旧内容；保留。 |
| 5 | 移除知识点标签自动撤回关联资料；知识点管理 | 教师→学生→AI：`routes/assignments.py`、资料服务 | 移除后来源修订、学生与检索均不命中；避免悬空资料，保留。 |
| 6 | 学生从首页知识路径直接打开资料再练习；首页与作业页 | 学生：`services/learning_graph.py`、`templates/components/learning_graph_panel.html`、`templates/assignment_detail.html` | 浏览器窄屏点击和返回路径；无资料时仍直达作答；保留。 |
| 7 | 学生在作业页读到中文知识点、正文和来源版本；作业详情 | 学生、AI 证据：作业路由、详情模板、证据组件 | 浏览器 AX 树和真实页面确认，修复原始 `array` 显示；保留。 |
| 8 | AI 辅导引用教师当前资料并附版本；现有作业辅导入口 | 学生→AI：`services/knowledge_rag.py`、`services/knowledge_evidence.py`、`services/knowledge_reliability.py` | 检索与学生证据 API 前后版本测试，旧证据 shape 兼容复测；保留。 |
| 9 | 教师在班级知识焦点看到对应资料入口；原教学建议路径 | 教师：`services/learning_graph.py`、`templates/teacher_knowledge_focus.html` | 教师范围图谱/焦点测试，权限先过滤；保留。 |
| 10 | 图谱离线样例验证资料节点、来源边与撤回；离线评测入口 | 图谱质量：`services/learning_graph_eval.py`、资料测试 | 节点/边精确及撤回失败样例复现，保留。 |
| 11 | 学生向量检索先核对作业范围；现有学习记忆检索 | 学生、权限：`services/student_vector_store.py`、`tests/test_student_vector_store.py` | 越权作业抛 `StudentVectorAccessError`，检索前拒绝；保留。 |
| 12 | 个人来源全部撤回时显示空状态；现有向量状态入口 | 学生、可靠性：向量服务与测试 | all-revoked 样例从 ready 降为 empty；避免误导，保留。 |
| 13 | 等待评测时辅助技术可识别进行中状态；现有评测等待页 | 学生、可靠性：`templates/submission_evaluating.html` | 全量回归发现原模板缺语义，增加不伪造百分比的进度角色；受影响定向回归通过，保留。 |

第 1–5、6–8、9–10 分别组成发布/撤回、学生学习/AI、教师教学/图谱的跨端主流程。第 10–12 项是可独立回归的图谱与向量质量改进；第 3、7、8、12 项来自实际使用或融合修复。没有把纯文字、监控或孤立状态算作交付。

## 主工作区用户改动融合审查

主工作区基于旧 `4f49d8f`，49 个跟踪差异 1078 增/337 删，未跟踪 `tests/test_question_bank_features.py` 与 `utils/scoring.py`。没有写入、覆盖或暂存主工作区。逐文件 diff 与 `origin/main` 比对：题库测试与远端字节一致；评分工具的远端实现以明确来源分值范围、历史时间界线和结构化分项替代主工作区旧启发式版本。49 文件中大部分新增行已在远端原样存在；剩余差异集中在评分归一化、分数显示和旧测试预期，远端新评分接口与模板已覆盖其用户意图。`routes/api.py` 的反馈归一化及统计刷新、worker 的百分制与错误回退亦在远端；本轮候选保留这些已发布实现。三方补丁预演在旧基线产生冲突，故未机械套用旧代码。详细仍需对余下不同语句做逐块签核；此项在发布门禁前必须完成。

## 融合与质量复盘

- 资料只绑定已存在的作业知识点；学生和 AI 只读当前 active 且标签仍存在的资料。教师和管理员沿用现有作业管理权限，学生沿用作业访问范围。来源哈希、修订及修改者可追溯。
- 隔离 SQLite 复制库的维护脚本验证新增表兼容旧 schema；没有生产迁移或大量数据重写。向量仍只用于学习参考，不用于评分。
- 最差使用断点：资料最初只显示原始代码 `array`；已改中文名称。图谱链接最初把无资料的练习也送到作业详情；已恢复无资料时直达作答。
- 现有评测等待页的 progressbar 模板断言失败原本也存在于 `origin/main`；本轮修复了该实际无障碍断点并做定向复测。全量运行仍如实记录原始 2 个失败，不标成全绿。
- 回滚：代码回退至线上 `b48a21f` 后重启应用和 worker；新增表不删，避免丢失教师已写内容，旧版本不会读取。

## 发布状态

自审结论：PASS。候选 `3d5d70d728768e8fa105262cd613c3a534c850d1` 基于最新远端 main `b48a21f`；主工作区差异逐文件列在下方，旧百分制语句由远端后续实现替代，候选没有覆盖用户工作区。权限沿用现有作业范围，schema 只新增表，旧库复制验收通过。完整回归原始两项失败均经修复并定向复测；没有重复全量测试。

待完成：推送、生产 update.sh 完整退出与后验、Release、两群消息、知识库 revision。任何步骤未完成前不宣称 v2.1.0 已上线。

### 主工作区逐文件处理记录
以下为主工作区相对旧 HEAD 的新增语句与最新远端对照；差异语句所在文件采用远端后续百分制实现，未把旧代码机械覆盖候选。
| 主工作区文件 | 处理 |
| --- | --- |
| `AGENTS.md` | 保留：新增语句已在远端 |
| `models.py` | 修复/保留：远端后续百分制实现取代旧语句（4/43 语句不同） |
| `routes/api.py` | 修复/保留：远端后续百分制实现取代旧语句（3/6 语句不同） |
| `routes/assignments.py` | 修复/保留：远端后续百分制实现取代旧语句（1/219 语句不同） |
| `routes/main.py` | 保留：新增语句已在远端 |
| `routes/thinking.py` | 保留：新增语句已在远端 |
| `routes/users.py` | 保留：新增语句已在远端 |
| `services/course_grading.py` | 保留：新增语句已在远端 |
| `services/demo_experience.py` | 保留：新增语句已在远端 |
| `services/teacher_analytics.py` | 保留：新增语句已在远端 |
| `static/modern.css` | 保留：新增语句已在远端 |
| `tasks/submission_tasks.py` | 修复/保留：远端后续百分制实现取代旧语句（13/26 语句不同） |
| `templates/admin_dashboard.html` | 保留：新增语句已在远端 |
| `templates/admin_profile.html` | 保留：新增语句已在远端 |
| `templates/all_submissions.html` | 修复/保留：远端后续百分制实现取代旧语句（5/8 语句不同） |
| `templates/api_docs.html` | 保留：新增语句已在远端 |
| `templates/assign_form.html` | 修复/保留：远端后续百分制实现取代旧语句（1/1 语句不同） |
| `templates/assignment_detail.html` | 修复/保留：远端后续百分制实现取代旧语句（3/68 语句不同） |
| `templates/assignments.html` | 保留：新增语句已在远端 |
| `templates/classes/class_assignment_stats.html` | 修复/保留：远端后续百分制实现取代旧语句（2/3 语句不同） |
| `templates/classes/class_comparison.html` | 保留：新增语句已在远端 |
| `templates/classes/class_detail.html` | 修复/保留：远端后续百分制实现取代旧语句（2/9 语句不同） |
| `templates/classes/class_list.html` | 修复/保留：远端后续百分制实现取代旧语句（1/3 语句不同） |
| `templates/grades.html` | 保留：新增语句已在远端 |
| `templates/profile.html` | 保留：新增语句已在远端 |
| `templates/s_assignments.html` | 保留：新增语句已在远端 |
| `templates/sprofile.html` | 保留：新增语句已在远端 |
| `templates/student_details.html` | 修复/保留：远端后续百分制实现取代旧语句（2/12 语句不同） |
| `templates/student_home.html` | 保留：新增语句已在远端 |
| `templates/submission_detail.html` | 修复/保留：远端后续百分制实现取代旧语句（6/11 语句不同） |
| `templates/submission_history.html` | 修复/保留：远端后续百分制实现取代旧语句（2/16 语句不同） |
| `templates/submissions.html` | 修复/保留：远端后续百分制实现取代旧语句（2/8 语句不同） |
| `templates/teacher_assignments.html` | 修复/保留：远端后续百分制实现取代旧语句（1/204 语句不同） |
| `templates/teacher_home.html` | 修复/保留：远端后续百分制实现取代旧语句（3/164 语句不同） |
| `templates/users.html` | 保留：新增语句已在远端 |
| `tests/test_course_grading.py` | 保留：新增语句已在远端 |
| `tests/test_demo_database_isolation.py` | 保留：新增语句已在远端 |
| `tests/test_demo_experience.py` | 保留：新增语句已在远端 |
| `tests/test_demo_guided_learning.py` | 保留：新增语句已在远端 |
| `tests/test_demo_profile_views.py` | 保留：新增语句已在远端 |
| `tests/test_demo_submission_isolation.py` | 修复/保留：远端后续百分制实现取代旧语句（2/6 语句不同） |
| `tests/test_student_home_history.py` | 保留：新增语句已在远端 |
| `tests/test_submission_review_collaboration.py` | 保留：新增语句已在远端 |
| `tests/test_submission_worker.py` | 保留：新增语句已在远端 |
| `tests/test_teacher_ai_suggestions.py` | 保留：新增语句已在远端 |
| `tests/test_teacher_analytics.py` | 保留：新增语句已在远端 |
| `utils/ability_scorer.py` | 修复/保留：远端后续百分制实现取代旧语句（12/39 语句不同） |
| `utils/code_evaluator.py` | 修复/保留：远端后续百分制实现取代旧语句（5/17 语句不同） |
| `utils/maturity_calculator.py` | 修复/保留：远端后续百分制实现取代旧语句（6/16 语句不同） |
| `tests/test_question_bank_features.py`（未跟踪） | 保留：与远端字节一致。 |
| `utils/scoring.py`（未跟踪） | 保留：远端明确评分来源范围与历史版本界线，取代旧启发式归一化。 |
