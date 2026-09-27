# CodeSense 2026-09-17 脱敏运行报告：v1.4.0 RAG 证据恢复与质量闭环

## 运行事实

- 自动化：`codesense-2`
- 工作区：`E:\CodeSense\源代码\.worktrees\local-opt-20260917`
- 候选分支：`codex/local-opt-20260917`
- 远端基线：`origin/main` 在本轮开始时为 `7dccdfd`
- 用户可见目标提交：`9562123073ea2f9f552891cd678ba3ebe2248f19`
- 版本：`v1.4.0`
- 生产目标：region `cn-heyuan`，实例 `i-f8zbujornnh55dsydozz`，目录 `/var/www/codesense`
- 生产回滚点：`35af7b53140c32ced91da8edee1a9d79e61152d0`

本轮只增加可恢复的知识证据状态、诊断和操作性界面；没有新增数据库迁移、依赖、provider、队列、权限边界或隐私范围，也没有删除既有功能。旧版教师/管理员 `diagnostics` 字段保持兼容，新质量字段放在独立的 `quality_diagnostics` 中。

## 主方案与研究约束

主方案是把知识检索从“有/无结果”扩展为可解释、可恢复的证据回执：学生看到状态和下一步，教师看到不参与评分的质量诊断，管理员看到不含查询/代码/学生身份的聚合服务信号；超时和限流只允许受控重试，并对日志字段做低基数约束。

研究证据与本项目推断分开记录：

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) 直接要求可感知、可操作、可理解和可健壮；本项目据此把重试控件、焦点、键盘目标、状态播报和减少动效纳入验收。
- [GitHub Copilot 的 research-plan-iterate 工作流](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/research-plan-iterate) 与 [Agent sessions](https://docs.github.com/en/copilot/how-tos/github-copilot-app/agent-sessions) 直接支持可见状态和可回看的执行过程；本项目推断为可展开的证据回执和明确的恢复动作，不复制其代码代理权限。
- [Replit checkpoints 说明](https://docs.replit.com/updates/2025/05/16/changelog) 提供可回看/可恢复状态的产品证据；本项目只采用“状态可见、失败可恢复”的交互约束，不引入工作区快照。
- [RAG 原始研究](https://arxiv.org/abs/2005.11401) 和 [Self-RAG](https://arxiv.org/abs/2310.11511) 支持让检索证据参与生成并表达检索/批评信号；本项目推断为 evidence receipt、引用完整度、索引版本和不确定性展示，不把检索质量直接变成评分。
- [OpenTelemetry 语义约定](https://opentelemetry.io/docs/specs/semconv/how-to-write-conventions/) 与 [metrics 约定](https://opentelemetry.io/docs/specs/semconv/general/metrics/) 支持稳定命名和低基数聚合；本项目据此只记录白名单状态、模式、耗时、命中数、隐私过滤数和 fallback code，不记录 query、代码、答案或学生身份。

## 独立交付清单

| # | 独立交付件与用户价值 | 受影响端 | 变更文件 | 验收证据 | 发布状态 |
|---|---|---|---|---|---|
| 1 | 超时状态投影：用户知道服务未及时完成，并获得可解释的下一步 | 学生端、AI 问答、Code Studio | `services/knowledge_evidence.py`、`routes/api.py`、`static/js/knowledge-evidence.js` | JSON/SSE/静态契约测试通过；页面显示 timeout 状态和安全 fallback | 已上线 v1.4.0 |
| 2 | 限流状态投影：临时拥塞不会被误报成“没有知识” | 学生端、教师端、AI 服务 | `services/knowledge_evidence.py`、`routes/api.py`、`static/js/knowledge-evidence.js` | rate_limited 状态、文案和测试通过；不会暴露内部异常文本 | 已上线 v1.4.0 |
| 3 | AI 问答 JSON 证据回执：回答旁可展开查看来源状态和边界 | 学生端、AI 问答 | `routes/api.py`、`tests/test_knowledge_rag.py` | JSON 响应保留旧字段并新增 `knowledge_evidence`；回归测试通过 | 已上线 v1.4.0 |
| 4 | AI 问答 SSE 证据回执：流式完成后同样保留证据状态 | 学生端、AI 问答 | `routes/api.py`、`tests/test_knowledge_rag.py` | SSE done 事件包含证据回执；流式测试通过 | 已上线 v1.4.0 |
| 5 | 服务端页面恢复链接：作业/提交知识面板在可重试状态提供明确入口 | 学生端、作业、提交 | `templates/components/knowledge_evidence.html`、`templates/assignment_detail.html`、`templates/submission_detail.html`、`templates/submit_code.html` | 页面模板契约和路由测试通过；只有 retryable 状态显示链接 | 已上线 v1.4.0 |
| 6 | Code Studio 安全重试：异步重试不刷新工作区，期间有 busy/live 状态和失败恢复 | 学生端、Code Studio | `static/js/knowledge-evidence.js`、`static/css/knowledge-evidence.css` | DOM 安全渲染契约、键盘/焦点/错误路径测试通过；无 `innerHTML` | 已上线 v1.4.0 |
| 7 | 教师/管理员质量诊断：引用完整度、延迟、索引版本和隐私过滤可复核 | 教师端、管理员端 | `services/knowledge_evidence.py`、`templates/components/knowledge_evidence.html` | 兼容旧 `diagnostics` 结构；新增 `quality_diagnostics` 测试通过 | 已上线 v1.4.0 |
| 8 | 管理员质量 API：聚合服务状态可观察且不泄露查询、代码或身份 | 管理员端、运维 | `routes/api.py`、`tests/test_knowledge_evidence_api.py` | 登录和管理员权限边界、`no-store`、白名单字段测试通过 | 已上线 v1.4.0 |
| 9 | 管理员质量卡片：状态、延迟、索引和恢复分布集中可读 | 管理员端 | `templates/admin_dashboard.html`、`static/js/knowledge-quality.js`、`static/css/knowledge-quality.css`、`tests/test_knowledge_quality_ui.py` | 加载/错误/空状态、响应式和无障碍静态契约通过 | 已上线 v1.4.0 |
| 10 | 低基数检索日志：服务筛查可定位问题而不记录敏感输入 | 运维、AI 服务 | `routes/api.py`、`tests/test_knowledge_operability_contract.py` | 日志白名单和敏感字段排除测试通过 | 已上线 v1.4.0 |
| 11 | 恢复边界与隐私过滤：fallback code 只来自白名单，索引修订和过滤数可追溯 | AI/RAG、学生—教师协同 | `services/knowledge_evidence.py`、`tests/test_knowledge_reliability.py` | 未知异常不下沉；超时、限流、隐私过滤和公共投影测试通过 | 已上线 v1.4.0 |
| 12 | 更新说明与帮助：用户能理解证据状态、重试含义和“不作为评分依据”的边界 | 公共页面、全站内容 | `templates/help.html`、`README.md`、`CHANGELOG.md`、`docs/assets/codesense-v1.4.0-rag-quality-loop.png` | 信息图人工检查文字、裁切、主题一致性通过；帮助页公开探针 200 | 已上线 v1.4.0 |

## 代码、测试与自审

- 主要变更：`services/knowledge_evidence.py`、`routes/api.py`、知识证据组件/模板、Code Studio 重试脚本与样式、管理员质量卡片、帮助页、测试、README、CHANGELOG、版本信息图及设计/计划文档。
- 完整 tracked Python 测试：`746 passed, 1962 warnings`；初次发现的 4 个兼容性失败已通过保留旧 `diagnostics` 形状、隔离新增字段后修复，并重新跑完整套件。
- 额外门禁：`compileall` 通过；`node --check static/js/knowledge-evidence.js` 通过；`node --check static/js/knowledge-quality.js` 通过；`git diff --check` 通过。
- 自审结论：PASS。未发现新增权限/隐私边界、迁移风险、未受控重试、敏感日志、未知 fallback 泄露或未覆盖的旧接口兼容问题。
- 已知非阻塞警告：部署输出含 pip root 警告和 Gunicorn `pkg_resources` 弃用警告；不影响本轮脚本退出码或健康探针。

## 发布与线上核验

- 生产部署前只读检查确认目标实例、目录、分支、origin、工作区和 `update.sh`；服务器此前在 `35af7b5`，工作区干净。
- 按固定流程执行 `cd /var/www/codesense && bash /var/www/codesense/update.sh`，脚本真实等待结束并退出 `0`；部署到目标提交 `9562123`。
- 部署后：`codesense.service`、`codesense-submission-worker.service`、`codesense-ability-worker.service` 均 active；服务器 HTTPS `/healthz` 和 `/readyz` 均为 200；公开 `/login`、`/help`、`/healthz` 均为 200；质量卡片 CSS/JS 资源探针为 200。
- GitHub Release：[v1.4.0](https://github.com/XiaoCow666/CodeSense/releases/tag/v1.4.0)，Release tag 指向目标提交并包含 [版本信息图](https://github.com/XiaoCow666/CodeSense/releases/download/v1.4.0/codesense-v1.4.0-rag-quality-loop.png)。
- 飞书同步：机器人“牛顿不讲理·CodeX”已确认在两个群内并发送同一版用户介绍与信息图；CodeSense 研发协作消息 `om_x100b65817af92534b205b18d2e2b467`，CoDeBuGo 总群消息 `om_x100b65810e2140b4b1690906b6b80cc`。
- 项目知识库：文档 [CodeSense 项目接管](https://hcnohkzwsogo.feishu.cn/docx/HyhsdpRUgomhknxEgCvcApgungd) revision `16`；重新读取已确认 v1.4.0 章节、信息图资源、Release 链接、部署证据和回滚点。

## 回滚与遗留风险

- 回滚方式：保留当前版本；如需回滚，先恢复已知稳定提交 `35af7b53140c32ced91da8edee1a9d79e61152d0`，再按同一 `update.sh` 流程部署并重新核验服务、worker、`healthz`、`readyz` 和受影响页面。未执行回滚。
- 遗留风险：管理员质量卡片当前以接口契约和静态 UI 契约为主，后续可补充真实浏览器交互回归；应继续观察超时/限流分布、fallback code 和索引修订变化，不把聚合质量指标解释为评分结论。
- 下一轮候选：补充真实浏览器端证据回执 E2E、持续对低基数检索指标做趋势告警，并评估个人/项目/课程知识库的来源撤回和评测入口；不改变本轮已上线的权限边界。
