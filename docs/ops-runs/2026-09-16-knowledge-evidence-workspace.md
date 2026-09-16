# CodeSense 知识证据工作区验收记录

## 本轮结论

- 日期：2026-09-16（Asia/Shanghai）
- 隔离分支：`codex/local-opt-20260916`
- 基线：`origin/main` at `3cd20ea`
- 候选提交：`bddf47b` → `0629462`
- 最终决策：`keep`（保留在隔离分支）；生产发布为 `needs_human`
- 发布原因：本地 HTTP 健康检查可用，但内置浏览器和 Chrome 对 localhost 均返回客户端拦截；Workbench CLI 可用但实例列表为空，无法确认安全的生产目标。

本轮没有数据库迁移、依赖变更、模型供应商变更或生产数据库写入。候选保留在独立 worktree，未修改本地 `main`。

## 研究输入与落地原则

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)：采用可见键盘焦点、焦点内区域、窄屏布局和 reduced-motion 规则。
- [WCAG 3.3.3 Error Suggestion](https://www.w3.org/WAI/WCAG22/Understanding/error-suggestion.html)：无结果/不可用状态提供明确的下一步，而不是让学生面对空白面板。
- [Retrieval-Augmented Generation](https://arxiv.org/abs/2005.11401)：回答上下文只追加当前作业范围内的显式证据，并保留无结果回退。
- [GitHub Copilot code review](https://docs.github.com/en/copilot/concepts/agents/code-review)：将代码建议拆成可审查的增量契约，并在完成前保留静态、集成和回归证据。

## 独立可验证迭代

| # | 假设与受益角色 | 实现位置与验证 | 决策、回滚点与风险 |
| --- | --- | --- | --- |
| 1 | 学生看到的知识证据必须是稳定且不含内部字段的投影。 | `services/knowledge_evidence.py`；`tests/test_knowledge_evidence.py`。 | keep；回滚 `0ed002e`；风险是未知检索状态会收敛为安全状态。 |
| 2 | 学生、教师和管理员都需要一个作业范围内的只读证据 API。 | `routes/api.py`；`tests/test_knowledge_evidence_api.py`。 | keep；回滚 `d0c7807`；无跨作业检索。 |
| 3 | 缺失作业和无权作业不能被接口用于枚举。 | API 权限分支；缺失/禁止访问测试。 | keep；同一 403 响应；风险为调用方无法区分两种错误。 |
| 4 | 查询词和数量参数必须有界且不可缓存。 | API `q`/`limit` 校验、`no-store`/`nosniff`；参数回归测试。 | keep；回滚 API commit；风险为过长问题被拒绝。 |
| 5 | 检索异常不应把问题、代码或异常文本写入日志。 | `_retrieve_knowledge_context` 安全回退与有界指标日志；失败路径测试。 | keep；回滚 API commit；保留 assignment ID 作为诊断键。 |
| 6 | 教师/管理员需要运行诊断，学生只需学习下一步。 | `build_knowledge_evidence_view(audience=...)` 与角色 API 测试。 | keep；删除 `diagnostics` 即可回滚展示；风险是诊断字段仍需避免扩展为私有分数。 |
| 7 | 作业详情页应先展示“知识焦点”，再让学生开始行动。 | `routes/assignments.py`、`templates/assignment_detail.html`、知识证据宏/CSS；页面/UI 测试。 | keep；回滚 `a5df3d5`；Jinja 自动转义正文。 |
| 8 | 提交详情页需要说明证据不是评分依据，避免误解。 | `templates/submission_detail.html`；提交视图测试。 | keep；回滚 `ed0ce97`；不改变评分数据。 |
| 9 | Code Studio 的提问入口应提供与证据一致的快速自检提示。 | `templates/submit_code.html`；页面/UI 测试。 | keep；回滚 `ed0ce97`；提示不生成答案或代码。 |
| 10 | AI 代码建议必须只接收当前作业的有界检索上下文。 | `routes/api.py`、`build_knowledge_prompt_context`；AI grounding 测试。 | keep；回滚 `701226c`；无 assignment ID 时不做跨作业检索。 |
| 11 | SSE 增量事件保持轻量，完成事件和旧 JSON 共享证据契约。 | `/api/code_advice` 的 done/JSON 字段；`tests/test_code_advice_knowledge.py`、SSE 回归。 | keep；回滚 `701226c`；证据只在完成时传输。 |
| 12 | 动态收据必须可访问、可恢复且不能把正文当 HTML；旧 JSON 路径也必须有挂载点。 | `static/js/knowledge-evidence.js`、CSS 和 Code Studio hooks；Node syntax/UI/XSS 测试。 | keep；回滚 `0d33cf5`、`2b274b7`、`0629462`；渲染器只使用 `textContent`/DOM 节点。 |
| 13 | 兼容字段不能绕过安全投影泄露私有分数或私有提示。 | `build_public_knowledge_retrieval`；集成测试覆盖作业页、提交页、证据 API、代码建议，并加入提问回答出口。 | keep；回滚 `aea965d`；保留旧顶层名称，但只序列化白名单字段。 |
| 14 | 质量评估和跨页面契约必须可重复。 | `tests/test_knowledge_evidence_integration.py`、本报告、`python -m services.knowledge_eval`。 | keep；删除本报告和集成测试即可回滚文档/测试层；发布仍受环境门阻塞。 |

## 验证矩阵

```text
相关知识证据回归：65 passed
集成/投影/API/AI 回归：28 passed
孤立 submission worker：1 passed
候选全量 pytest：729 passed, 2,668,773 warnings, 0 failed
离线评估：5 queries, 4 relevant; Recall@1=0.875; Recall@k=0.875
模式：vector=3, keyword_fallback=1, no_result=1; expected mismatch=0
性能样本：64 documents/chunks; 100 runs; query p95=0.643 ms; total p95=1.586 ms
静态检查：py_compile、compileall、node --check、git diff --check 均通过
本地健康：GET /healthz -> HTTP 200, {"status":"ok"}
```

全量回归中的 warnings 数量很大，但本次运行没有失败。此前 origin 基线记录过一次 SQLite session-cache 相关失败；本次候选在独立进程中全量通过，因此没有把旧基线问题伪装成新回归。

## 浏览器、远端与发布门

- 使用隔离实例和测试数据库启动本地 Flask；PowerShell 健康检查返回 200。
- 内置浏览器尝试 `http://127.0.0.1:5055/healthz` 和 `http://localhost:5055/healthz` 均被客户端阻止；Chrome 连接同样被阻止。没有绕过安全策略，也没有输入生产凭证。
- `workbench list --output json` 返回空实例列表；没有可确认的生产 ECS 目标，因此没有执行上传、远程命令、部署、合并或 release。
- `README.md`、`CHANGELOG.md`、版本号、GitHub Release、飞书同步均未改动；待人工确认远端目标并完成浏览器冒烟后再进行版本化发布。

## 回滚与风险

候选变更按提交可逆：`0ed002e`、`d0c7807`、`a5df3d5`、`ed0ce97`、`701226c`、`0d33cf5`、`aea965d`、`2b274b7`、`0629462`，以及本报告提交。回滚优先使用对应提交的 `git revert`，不删除用户数据库或运行时文件。

剩余风险是生产环境无法在本轮被浏览器和 Workbench 双重确认；因此“功能候选保留”与“生产发布”明确分离，发布状态必须保持 `needs_human`。
