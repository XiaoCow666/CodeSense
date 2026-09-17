# CodeSense 2026-09-17 第一阶段运行报告：知识图谱学习路径投影

## 阶段边界

本阶段目标是把现有作业知识点和学生知识点评分投影为权限受控的学习路径，接入学生首页和教师仪表盘。今天不新增生产数据库表、不接外部向量服务、不把共同出现关系包装成前置依赖；学生向量库留到下一阶段。

候选工作树：`E:\CodeSense\源代码\.worktrees\knowledge-graph-stage1-20260917`
候选分支：`codex/knowledge-graph-stage1-20260917`
基线：`origin/main=52acab2`
融合基线提交：`019b77c`
计划提交：`eba9147`

## 主工作区改动融合清单

主工作区在开始时落后远端 30 个提交，并有 48 个 tracked 文件修改和 2 个未跟踪文件。所有改动均保留在主工作区原位，并复制到候选工作树进行融合；没有执行 reset、checkout、clean 或未经授权的 stash。

| disposition | paths | 处理 |
| --- | --- | --- |
| fused | `models.py`; `routes/main.py`; `routes/thinking.py`; `routes/users.py`; `services/course_grading.py`; `services/demo_experience.py`; `services/teacher_analytics.py`; `static/modern.css`; `tasks/submission_tasks.py`; `utils/ability_scorer.py`; `utils/code_evaluator.py`; `utils/maturity_calculator.py`; `utils/scoring.py` | 评分规范化、统计和演示数据改动进入候选，保留为后续图谱基础 |
| fused | `templates/admin_dashboard.html`; `templates/admin_profile.html`; `templates/all_submissions.html`; `templates/api_docs.html`; `templates/assign_form.html`; `templates/assignment_detail.html`; `templates/assignments.html`; `templates/classes/class_assignment_stats.html`; `templates/classes/class_comparison.html`; `templates/classes/class_detail.html`; `templates/classes/class_list.html`; `templates/grades.html`; `templates/profile.html`; `templates/s_assignments.html`; `templates/sprofile.html`; `templates/student_details.html`; `templates/student_home.html`; `templates/submission_detail.html`; `templates/submission_history.html`; `templates/submissions.html`; `templates/teacher_assignments.html`; `templates/teacher_home.html`; `templates/users.html` | 0–100 展示、学生快照、题库批量入口和相关页面改动进入候选 |
| fused | `tests/test_course_grading.py`; `tests/test_demo_database_isolation.py`; `tests/test_demo_experience.py`; `tests/test_demo_guided_learning.py`; `tests/test_demo_profile_views.py`; `tests/test_demo_submission_isolation.py`; `tests/test_student_home_history.py`; `tests/test_submission_review_collaboration.py`; `tests/test_submission_worker.py`; `tests/test_teacher_ai_suggestions.py`; `tests/test_teacher_analytics.py`; `tests/test_question_bank_features.py` | 测试和新增题库覆盖进入候选 |
| conflict-resolved | `routes/api.py`; `routes/assignments.py` | 最新 RAG/证据导入与用户评分规范化/题库导入合并；未丢弃任一侧的有效功能 |

## 基线验证

```text
pytest tests/test_question_bank_features.py tests/test_teacher_analytics.py tests/test_demo_experience.py tests/test_student_home_history.py -q --disable-warnings
13 passed, 70 warnings in 16.14s

compileall: exit 0
git diff --check: exit 0
```

警告尚未作为失败处理；后续若影响图谱流程会单独分类。评分规范化与题库改动在图谱阶段不得回归。

## 研究与设计约束

本轮查阅了以下公开资料，并把结论落成可测试约束：

| 来源（版本/日期） | 直接借鉴 | CodeSense 的差异与不采用部分 |
| --- | --- | --- |
| [WCAG 2.2 Recommendation](https://www.w3.org/TR/2024/REC-WCAG22-20241212/)（W3C，2024-12-12） | 交互必须能被辅助技术理解，状态、进度和空状态都要有可读文本；本轮使用语义标题、progressbar、status 和可见焦点样式验收。 | 不把图谱做成只能靠 Canvas/鼠标拖拽的可视化；本轮采用服务端卡片和列表，不增加新的 JavaScript 依赖。 |
| [GraphRAG](https://microsoft.github.io/graphrag/)（Microsoft Research 开源文档，持续更新） | 图结构适合补充纯文本相似检索，关系需要有来源和可解释的构建过程。 | GraphRAG 面向非结构化语料抽取实体、社区和摘要，成本与噪声都更高；本轮只投影已有结构化作业知识点，`co_occurs` 明确标为同作业推断，不宣称前置关系，也不接外部 LLM/图数据库。 |
| [Deep Knowledge Tracing](https://papers.nips.cc/paper/5654-deep-knowledge-tracing.pdf)（NeurIPS，2015）和 [Deep Knowledge Tracing on Programming Exercises](https://doi.org/10.1145/3051457.3053985)（ACM L@S，2017） | 学生知识状态应结合交互序列建模，程序练习的序列信息有个性化价值；因此后续向量库必须保留来源、版本和时间顺序。 | 本轮没有足够离线评测数据支撑 DKT/RNN，不把现有分数伪装成预测模型；当前只使用本人已有 `KnowledgePointScore` 快照。 |
| [HNSW 原始论文](https://arxiv.org/abs/1603.09320)（2016） | 学生向量库后续可以评估 HNSW 等近似近邻索引，但必须以召回率、隔离性和删除/重建成本实测后决定。 | 本轮不新增向量数据库、embedding provider 或不可逆 schema；先完成图谱边界和离线评测合同。 |

证据与项目推断已分开：上表“借鉴”是来源直接支持的设计方向；“CodeSense 差异”是结合当前表结构、权限 helper、无生产自动建表约束和演示数据做出的项目推断，并由下方测试验证。

## 本阶段已交付清单

| # | 独立交付件与用户价值 | 受影响端/主流程 | 变更文件 | 验收证据 | 发布状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 学生学习图谱投影：把作业和知识点组成稳定节点，学生能看到自己的学习路径。 | 学生首页、作业学习流 | `services/learning_graph.py` | 2 个作业、3 个知识点、节点 ID 和数量断言通过 | 候选 |
| 2 | 学生作业权限边界：图谱只取当前学生可见作业，越权 assignment 直接拒绝。 | 学生端、权限链路 | `services/learning_graph.py`, `tests/test_learning_graph.py` | 越权 assignment 测试通过；外班学生标识不出现在结果中 | 候选 |
| 3 | 学生私有掌握度边：只读取当前学生的知识点评分，不把学生 ID写进图谱输出。 | 学生画像、AI 数据基础 | `services/learning_graph.py` | `student_private` scope、`mastery` edge 和无 ID 断言通过 | 候选 |
| 4 | 同作业知识点关联：提供可解释的 `co_occurs` 关系，明确不是前置依赖。 | 学生路径、后续 RAG 图结构 | `services/learning_graph.py`, `templates/components/learning_graph_panel.html` | `same_assignment` provenance、`is_inferred=True` 与页面说明通过 | 候选 |
| 5 | 学生下一步练习：缺少掌握度或掌握度低时给出作业级建议，并能直接进入 Code Studio。 | 学生首页→提交/编码 | `services/learning_graph.py`, `templates/components/learning_graph_panel.html` | 推荐项含 `assignment_id`；浏览器演示链接可用 | 候选 |
| 6 | 学生空状态与容错：无班级/无作业时显示稳定说明，图谱故障不击穿原首页。 | 新用户、自由账号、异常恢复 | `routes/main.py`, `tests/test_learning_graph.py` | 空图谱测试通过；路由对预期权限和异常提供空状态 | 候选 |
| 7 | 教师班级知识覆盖：按授权班级汇总样本数、平均掌握度和需巩固人数。 | 教师仪表盘、教学决策 | `services/learning_graph.py` | 2 名学生的数组均值 62.5、低掌握 1 人断言通过 | 候选 |
| 8 | 教师隐私与样本门槛：不展示个人分数/学生 ID，少于 2 条记录只标记样本不足；部分学生薄弱也能提醒。 | 教师端、学生数据隔离 | `services/learning_graph.py`, `templates/components/learning_graph_panel.html` | 外班概念拒绝访问；教师输出 repr 不含学生 ID；聚合页面显示“仅班级聚合” | 候选 |
| 9 | 学生首页融合卡片：把图谱放在“继续学习”之后、近期作业之前，直接连接既有作业入口。 | 学生首页内容层级 | `templates/student_home.html`, `templates/components/learning_graph_panel.html`, `static/modern.css` | 真实演示学生首页可见 6 份作业、13 个知识点和隐私标识 | 候选 |
| 10 | 教师首页融合卡片：接在 AI 教学摘要后，不替换已有学生快照/趋势/班级入口。 | 教师首页内容层级 | `templates/teacher_home.html`, `templates/components/learning_graph_panel.html`, `static/modern.css` | 真实演示教师页可见 12 人班级样本、10 个知识点和教学提醒 | 候选 |
| 11 | 响应式与无障碍交互：语义 heading、progressbar、status、移动端单列布局和键盘可达链接。 | 全站前端、移动端 | `static/modern.css`, `templates/components/learning_graph_panel.html` | 390px 检查无横向溢出（scrollWidth 375，图谱卡 311px），控制台无 error | 候选 |
| 12 | 工作区改动融合与回归：将主工作区评分规范化、教师快照、题库等未提交改动带入隔离候选并保持兼容。 | 学生/教师/题库主流程 | 候选基线中的 48 个 tracked + 2 个 untracked 改动，冲突文件 `routes/api.py`, `routes/assignments.py` | 目标回归集 24 passed；全量 767 passed | 候选 |

## 图谱交付、融合与必要性结论

- 服务端、学生首页、教师首页、权限、空状态和真实演示数据走查均已完成；学生端图谱只使用当前账号数据，教师端只输出班级聚合。
- 实际页面检查没有发现卡片挤压、横向滚动、死链接或控制台错误；移动端导航保持折叠，图谱概念卡在 390px 宽度下变为单列。
- 这是有必要的主流程能力：它把既有“作业—知识点—掌握度”数据第一次变成学生可执行的下一步练习和教师可操作的班级概览，不是重复展示证据状态。当前演示数据掌握度偏高时建议区为空，这是正确的空建议状态，不人为制造薄弱点。
- 本阶段暂不实现学生向量库。下一阶段必须先定义个人/项目/课程边界、来源版本、删除/撤回、重建、召回评测和向量隔离，再选择索引实现；不能因为图谱页面可见就直接把私有提交送入共享 embedding 服务。

## 验证结果

```text
目标回归集：24 passed, 196 warnings in 30.25s
全量回归：767 passed, 2047 warnings in 295.97s
compileall app.py routes services utils tasks models.py tests：exit 0
git diff --check：exit 0
浏览器走查：演示学生首页、教师仪表盘；桌面 + 390px 移动宽度；控制台 error=0
```

警告均未被隐藏或改写；本轮没有发现图谱相关失败。`Query.get()` 等既有 SQLAlchemy 弃用告警留作后续维护项。

## 发布门禁与回滚

当前候选仍位于隔离工作树 `E:\CodeSense\源代码\.worktrees\knowledge-graph-stage1-20260917`，尚未推送、合并远端 main、执行 `update.sh`、创建 Release 或发送外部消息；因此不能宣称已上线。原因是本轮按“先完成可用阶段供查看”的边界保留候选，且当前环境未提供已确认的 Workbench/ECS 发布会话与 GitHub/飞书发布通道。

候选目标提交将在本报告提交后记录。回滚只需移除本阶段的服务、路由、共享模板、样式、测试和报告提交，不需要生产 schema 回滚；主工作区原有未提交改动不在候选回滚范围内。

## 回滚方式

本阶段新增内容只应是服务、路由上下文、模板、样式和测试；回滚时移除对应候选提交即可，不需要生产 schema 回滚。主工作区不属于候选回滚范围。
