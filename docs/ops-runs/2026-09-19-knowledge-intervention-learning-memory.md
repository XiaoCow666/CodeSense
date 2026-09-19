# CodeSense v1.6.0 知识点干预与学习记忆治理

## 运行信息

- 运行时间：2026-09-19（Asia/Shanghai）
- 自动化任务：`codesense-2`
- 候选分支：`codex/weak-point-guidance-20260919`
- 候选目录：`E:\CodeSense\源代码\.worktrees\weak-point-guidance-20260919`
- 初始候选基线：`4af13b13681735b156bd7342dbbbb0a55b4c1317`
- 远端最新基线：`96650592e19e1ab379f1ee3e74a3041e0a1f8e95`
- 候选代码提交：`39704d2a347914626c35958f9d88917b604113fb`
- 远端融合提交：`b8b78f0`
- 目标版本：`v1.6.0`

## 主方案与必要性判断

本轮主方案是把知识图谱、学生私有向量库和教师教学建议接成可操作的学习闭环：学生能够管理来源并处理陈旧索引，AI 辅导同时读取当前作业的图谱与学生个人记录，教师能够从班级知识点提醒和 AI 建议进入作业动作。成功指标包括：学生作用域查询无跨学生命中；撤回来源不再进入检索；失败重建继续提供上一版可用结果；陈旧索引给出更新动作；教师作业动作只属于本人管理范围；JSON 与 SSE 保持已有字段和状态。

本方案保留的理由是它直接处理上一轮发现的三个主流程断点：学生无法撤回来源，失败重建会阻断上一版索引，图谱和教师建议缺少后续动作入口。维护成本主要是现有服务、模板和测试增量，无数据库迁移、无新外部服务、无公开资料范围变化。回滚采用候选提交回退并按相同部署脚本重新核验。

## 研究依据

研究日期为 2026-09-19。来源中的实现证据与面向 CodeSense 的工程推断分别记录如下：

- [Microsoft GraphRAG 默认数据流](https://microsoft.github.io/graphrag/index/default_dataflow/)说明实体、关系和声明应保留来源信息，再由图结构产出检索表示。CodeSense 采用作业知识点关系的来源引用、版本指纹和学生作业作用域；图谱只提供学习引导上下文。
- [Qdrant 索引与过滤文档](https://qdrant.tech/documentation/manage-data/indexing/)说明检索过滤需要可索引的载荷字段，并应在过滤条件下执行查询。CodeSense 继续在数据库查询阶段限定 `student_id`、`scope_type` 和 `status`，再进行向量排序。
- [Deep Knowledge Tracing 论文](https://arxiv.org/abs/1506.05908)展示了使用时间交互记录估计知识掌握变化的方法。CodeSense 将它转化为低风险的个人练习提示，保留教师判断和程序评测作为结果依据。
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)要求焦点顺序、错误识别、可操作控件和一致导航。新增撤回按钮、教师行动链接、警告状态和窄屏样式均使用现有按钮、表单和可访问名称。

## 工作区融合

主工作区 `E:\CodeSense\源代码` 在本轮开始时保留 48 个跟踪文件改动和 2 个未跟踪文件。逐项核对后，能确认与远端已有内容相同的改动继续由最新 `origin/main` 提供；本地旧基线中会覆盖 v1.5.0 图谱和向量能力的文件没有直接复制。主工作区所有改动均保持原位，未进入本轮候选，原因是它们无法在本轮逐项完成融合验证，且覆盖会影响最新远端能力。

候选从最新远端 `9665059` 合并，远端更新包含 Cloudflare 自动关联保护、生命周期测试和阶段任务更新，未产生冲突。候选新增和修改内容均在隔离目录完成，测试数据库、Redis 数据库、会话和日志路径沿用候选隔离设置。

## 独立交付项

每项均有单独入口或单独验收条件，当前发布状态为“已部署，外部资料待收口”。

1. **学生来源摘要投影**：学生痛点是无法知道个人学习记忆由哪些来源组成；学生端受影响；文件为 `services/student_vector_store.py`、`routes/main.py`；入口为学生首页“我的学习记忆”；实测投影只返回类型、标题、版本和状态，省略正文与向量；保留理由是让学生能理解并管理个人数据；回滚删除来源投影调用即可。
2. **学生来源自助撤回**：学生可撤回一条来源并保持个人作用域；学生端与向量服务受影响；文件为 `routes/main.py`、`services/student_vector_store.py`、`templates/components/student_learning_memory.html`；入口为来源列表的撤回表单；实测当前学生撤回后状态变为 `revoked`，其他学生来源和未知编号使用相同响应，后续查询命中数为零；必要性为满足来源生命周期和隐私边界；回滚恢复原有来源列表和服务调用。
3. **学生来源治理状态展示**：学生可看到 active、revoked、source_removed 的来源状态与版本；学生首页和 CSS 受影响；文件为 `templates/components/student_learning_memory.html`、`static/modern.css`；入口为首页来源区域；实测空态、陈旧提示、撤回状态和窄屏布局均有模板测试；保留理由是让用户知道下一步；回滚移除来源状态区域。
4. **陈旧索引状态**：过期个人索引会给出明确更新动作；学生向量服务、首页和 AI 收据受影响；文件为 `services/student_vector_store.py`、`templates/components/student_learning_memory.html`；入口为检索服务、学生首页和回答收据；实测超过 30 天的索引返回 `stale`、空证据和更新提示；必要性来自上一轮缺少新鲜度边界；回滚关闭陈旧判断并保留数据库字段。
5. **失败重建继续读取上一版索引**：重建失败时学生仍可使用上一版成功索引；向量服务、问答和 Code Studio 受影响；文件为 `services/student_vector_store.py`、`tests/test_student_vector_store.py`；入口为评测刷新、手动更新、问答和代码辅导；实测 `failed + revision > 0` 可查询旧 active rows，初次失败仍返回不可用；保留理由是恢复已有用户能力；回滚恢复失败状态的服务判断。
6. **学生向量检索质量字段**：教师和运维可区分候选数量、作用域候选数、撤回数量、新鲜度和索引状态；向量检索收据受影响；文件为 `services/student_vector_store.py`、`services/student_vector_eval.py`；入口为 AI 返回的学习证据和离线评测；实测旧字段保留，新增字段可序列化，过期来源样本进入评测；必要性为支持检索效果与隐私验收；回滚移除新增指标字段。
7. **教师知识点行动链接**：教师从班级提醒直接进入针对性练习；教师仪表盘和知识图谱模板受影响；文件为 `services/learning_graph.py`、`templates/components/learning_graph_panel.html`、`routes/main.py`；入口为教师首页教学提醒；实测链接包含知识点和班级参数，非教师被导回首页；保留理由是消除图谱到教学动作的断点；回滚恢复静态提醒。
8. **教师知识点行动页**：教师可筛选管理班级、查看带知识点的作业、打开作业和进入布置流程；教师端、作业端受影响；文件为 `services/learning_graph.py`、`routes/main.py`、`templates/teacher_knowledge_focus.html`、`static/modern.css`；入口为 `/teacher/knowledge-focus/<knowledge_point>`；实测只返回管理范围内作业，其他教师访问返回 `403`，共享作业只显示查看动作并隐藏布置按钮，空态提供创建练习入口；必要性为形成图谱到作业的真实闭环；回滚删除路由和模板调用。
9. **学生作业图谱进入 AI 辅导**：学生问答和 Code Studio 可获得当前作业知识点与本人掌握提示；学生端、AI API、图谱服务受影响；文件为 `routes/api.py`、`services/learning_graph.py`、`utils/code_advisor.py`；入口为 `/api/ask_question` 与 `/api/code_advice` 的聊天和分析 JSON/SSE 流程；实测提示词包含图谱标记，Code Studio 分析请求把图谱上下文传入 `CodeAdvisor`，当前作业和学生作用域均通过测试，公共知识不可用时仍会独立尝试图谱并在数据依赖故障时保持 answer-only 响应；保留理由是完成图谱消费闭环；回滚移除图谱上下文拼接。
10. **教师 AI 建议作业动作**：教师建议保留服务端作业编号，并可查看或布置到班级；教师 AI 页面和作业流程受影响；文件为 `services/teacher_ai_advisor.py`、`templates/teacher_ai_suggestions.html`；入口为同步建议、SSE 建议、初始卡片和刷新后的卡片；实测跨教师作业不会进入候选，模型提供的未知编号会被移除，合法编号在两种渲染路径均显示查看与布置链接；必要性为把建议转成教师可执行动作；回滚保留旧文字卡片。
11. **离线过期来源评测样本**：评测可覆盖 expired 来源、查询命中边界和状态字段；评测服务与 fixture 受影响；文件为 `services/student_vector_eval.py`、`tests/fixtures/student_vector_eval.json`、`tests/test_student_vector_eval.py`；入口为离线评测命令与测试；实测过期样本不会污染目标查询，已有 recall 和跨作用域检查保持通过；保留理由是让陈旧策略有可复现样本；回滚移除 fixture 扩展。
12. **角色和响应兼容回归**：学生、教师、管理员入口以及 JSON/SSE 状态保持已有行为；受影响端为三类角色、AI 接口和作业页面；文件为相关测试文件及模板；入口为学生首页、教师仪表盘、教师建议、管理员跳转、问答和代码辅导；实测完整测试 832 项通过，重点场景覆盖空态、错误、陈旧、撤回、权限和 SSE；保留理由是发布前确认融合质量；回滚仅恢复本轮测试与入口改动。
13. **版本说明与信息图资产**：用户能通过 README、CHANGELOG 和版本信息图理解 v1.6.0 的直接收益；公共文档受影响；文件为 `README.md`、`README.en.md`、`CHANGELOG.md`、`docs/assets/codesense-v1.6.0-knowledge-intervention.png`；入口为仓库首页和 Release 资产；实测资源已保存，文件大小约 2.1 MB，SHA-256 为 `204254f01a43bda69cd34b21252c6843951a6b7c28f35f007b0b7c782687c9c6`；保留理由是版本用户说明完整；回滚删除新增版本说明和资源引用。
14. **Windows 沙箱清理竞态回归**：服务质量门禁能够处理后代进程在 PID 文件写入期间被终止的情况；本地质量测试受影响；文件为 `tests/test_sandbox_process_cleanup.py`；入口为完整 Python 测试；实测新增空 PID 文件场景与沙箱清理测试共 `8 passed`，完整测试恢复为 `832 passed`；必要性是避免测试清理阶段产生误报并持续验证进程隔离；回滚恢复原清理辅助函数和测试场景。

## 真实角色走查与融合审查

- 学生路径：测试客户端登录学生、打开首页、读取来源摘要、提交撤回、查看陈旧状态、触发个人学习记忆更新、进入问答和 Code Studio 辅导；撤回后检索不命中，陈旧索引返回更新动作，公共知识不可用时保留回答。
- 教师路径：登录教师、打开仪表盘知识提醒、筛选班级、进入知识点行动页、查看作业、进入布置入口、读取 AI 建议卡片；服务层和路由均限制管理班级与本人创建作业。
- 管理员路径：访问教师知识点入口和学生来源入口，验证角色跳转与拒绝边界；管理员不会获得学生私有来源。
- 融合结果：新增服务均有现有页面或 AI 路由调用；旧 JSON/SSE 字段保留；撤回、陈旧和失败重建都能回到用户可理解的更新动作。使用复盘中最高影响断点为“图谱提醒没有后续动作”和“来源撤回缺少入口”，已由第 2、7、8、10 项处理。
- Flask test client、模板渲染和静态检查覆盖桌面与窄屏结构、空态、错误态、权限和返回状态。当前环境按 `AGENTS.md` 约束未调用主动视觉检查工具，未记录截图坐标；发布材料中的图像文件已生成并纳入版本资源。

## 验证结果

- 候选初始基线：`817 passed`。
- 定向回归：学生向量与评测 `13 passed`；知识检索与 Code Studio `17 passed`；教师建议完整集合 `8 passed`；异常兼容补充 `3 passed`。
- 最新远端合并、审查修正和竞态修复后的全量测试：`832 passed, 2183 warnings`，耗时约 263 秒。
- Cloudflare 自动化测试：`34 passed`；沙箱清理定向测试：`8 passed`。
- `python -m compileall -q services routes tasks models.py utils`：通过。
- `git diff --check`：通过。
- 警告分类：既有 Flask-Session 弃用提示、SQLAlchemy `Query.get` 弃用提示、循环外键删除排序提示和测试类收集提示；没有新增失败。

## 发布门禁

- 候选代码发布状态：本地验证通过，自审结论 PASS，代码已提交并推送为 `39704d2`；生产部署已完成。
- 目标服务器：`cn-heyuan`、实例 `i-f8zbujornnh55dsydozz`、目录 `/var/www/codesense`；本轮在生产服务器执行前仍需重新完成只读门禁。
- Workbench CLI：`v1.0.1`；已确认目标实例、生产目录、分支和部署前工作树状态。
- `update.sh`：已执行完成，退出码 `0`；生产拉取目标为 `39704d2`，数据库维护和服务重启均完成。
- 线上 HEAD：`39704d2a347914626c35958f9d88917b604113fb`；应用、submission worker、ability worker 均 active；本机和公开 `/healthz`、`/readyz`、`/login` 均返回 `200`。
- 信息图：已由内置 ImageGen 生成并保存为 `docs/assets/codesense-v1.6.0-knowledge-intervention.png`；当前环境按 `AGENTS.md` 约束未调用主动视觉检查工具，文字可读性与裁切复核保留为人工门禁。
- GitHub Release：待创建，Release 正文只包含用户可见更新和信息图。
- 飞书消息：尚未发送，等待部署核验通过后使用“小牛顿”对应机器人身份向实际项目群和 CoDeBuGo 总群发送同版用户介绍与信息图。
- 项目知识库：尚未更新，等待部署核验通过后写入版本、信息图、Release 链接和内部证据并复读核验。

## 回滚与遗留风险

- 回滚方式：恢复生产部署前稳定提交 `3c58c32ca0193666fe0015c09d5239987092ed06`，按相同 `update.sh` 部署并核验应用、worker、`/healthz` 和 `/readyz`；本轮没有执行回滚。
- 数据范围：没有新增数据库迁移，没有修改生产数据库，没有改变学生、教师、管理员权限边界。
- 遗留风险：学生向量行当前采用状态撤回，删除后的历史行仍保留；embedding 算法版本字段仍未建立；30 天陈旧窗口属于当前规则；信息图文字可读性与裁切仍需人工复核；服务器保留既有 `pkg_resources` 弃用提示。
- 维护决定：代码、本地验证、生产部署和健康核验均通过；完成信息图人工复核后创建 Release、发送飞书消息并更新项目知识库。
