# Knowledge Evidence Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有作业范围知识检索结果做成可追溯、可访问、可恢复的学生/教师证据工作区，并让 Code Studio 的 AI 回答携带同一份证据收据。

**Architecture:** 新增纯函数安全投影服务；新增作业权限保护的 no-store 证据 API；在三个服务端页面复用 Jinja evidence macro；在 `/api/code_advice` 中复用现有 assignment-scoped 检索和 prompt context；由无依赖的 DOM 渲染器处理 SSE 完成事件。检索器、评分、提交、权限主逻辑保持不变。

**Tech Stack:** Flask、SQLAlchemy、Jinja、现有 CSS/Vanilla JS、pytest；使用仓库规定的 `E:\anaconda\python.exe` 和 worktree-local SQLite/Redis/session/upload/log 路径；不新增依赖或迁移。

**Spec:** docs/superpowers/specs/2026-09-16-knowledge-evidence-workspace-design.md

## Global Constraints

1. 所有实现必须在 `E:\CodeSense\源代码\.worktrees\local-opt-20260916`，不得改外层 `E:\CodeSense` 或本地 `main`。
2. 每个任务先写能失败的测试，再写最小实现；任务完成后由独立 reviewer 只读检查，发现问题则在同一任务内修复并重新验证。
3. 不改变现有 API 字段、SSE 事件顺序、评分/提交语义和既有权限行为；新增字段只能 additive。
4. 检索仍然限制在当前作业，最多读取 64 个索引文档、最多返回 8 条证据；不读取 `KnowledgePointScore` 私有评分，不做外部网络或模型调用。
5. 新证据 API：未登录沿用认证错误；不存在/无权作业统一 403；`q` 最长 2000 字符；`limit` 只能是 1–8 的正整数；响应 `Cache-Control: no-store`。
6. 动态知识正文必须用 DOM `textContent`；Jinja 使用自动转义；日志禁止问题、代码、姓名、正文和异常堆栈中的敏感上下文。
7. 每个任务至少运行自己的测试和相关回归；总体验收运行完整测试、固定离线评估、Python 编译检查、静态 diff 检查和可行的本地浏览器 smoke。已知的基线失败必须原样记录。

---

## Task 1: 建立安全的知识证据显示投影

**Files:** Create `services/knowledge_evidence.py`, create `tests/test_knowledge_evidence.py`.

**Purpose:** 把检索原始字典变成模板和客户端都能安全消费的白名单结构，统一 grounded/no-result/unavailable/unknown 四种状态和 student/teacher/admin 三种受众。

**Step 1 — Write the failing tests.**

在 `tests/test_knowledge_evidence.py` 覆盖：

- grounded 结果保留证据 ID、citation、标题、正文、来源标签和创建时间，去掉任意额外原始键；
- 缺失/空证据得到 `no_result`，unavailable 保留安全 fallback code；
- teacher/admin 获得有限 diagnostics，student 不获得 diagnostics；负数、字符串和未知模式不会泄露；
- 正文、标题和 fallback 文本按普通字符串返回，不生成 HTML。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence.py`.

Expected: collection succeeds but the new service import/function assertions fail because the module does not exist.

**Step 2 — Implement the smallest projection.**

实现 `build_knowledge_evidence_view(retrieval, *, audience="student")` 及内部白名单/状态映射。只读取 `status`、`evidence`、`fallback`、`metrics` 中规格允许的字段；把未知输入收敛到安全状态；限制证据条数为 8、文本为有限字符串，并为教师诊断输出非负整数/有限数值。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence.py` and `E:\anaconda\python.exe -m py_compile services/knowledge_evidence.py`.

Expected: all new projection tests pass. Commit with message `feat: add safe knowledge evidence projection` and request a read-only task review.

---

## Task 2: 提供作业权限保护的 no-store 证据 API

**Files:** Modify `routes/api.py`; extend `tests/test_knowledge_evidence.py` or create `tests/test_knowledge_evidence_api.py`.

**Purpose:** 让 assignment detail、Code Studio 和未来客户端可以按问题刷新证据，同时阻止未授权枚举与缓存泄露。

**Step 1 — Write the failing tests.**

使用现有 app/test fixture 覆盖：

- 未登录返回现有认证错误；学生可访问自己的/公开作业，教师/管理员按现有 `can_access_assignment` 规则访问；
- 不存在作业和无权作业都是 403 且响应形态不区分；检索器不会在权限失败时被调用；
- `q` 超过 2000 字符、`limit=0`、`limit=9`、非整数和重复冲突输入返回 400；合法查询把 q/limit 传给检索器；
- 成功 payload 同时包含 `knowledge_retrieval` 与 `knowledge_evidence`，不包含 `KnowledgePointScore`、私有分数字段或查询正文；
- 成功和参数错误响应带 `Cache-Control: no-store`；日志只含角色/作业 ID/状态/模式/计数/耗时，不含 query、code、姓名、证据正文。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence_api.py`.

Expected: route-not-found or missing-payload failures.

**Step 2 — Implement the route.**

在 `routes/api.py` 复用现有登录、角色和 `can_access_assignment` helper；权限检查先于 `retrieve_assignment_knowledge`。解析并验证 q/limit 后调用检索器和 Task 1 投影服务，使用现有 `api_response`；统一设置 no-store 和 `X-Content-Type-Options: nosniff`，以现有错误响应工厂返回 400/403。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence_api.py tests/test_knowledge_rag.py` and `E:\anaconda\python.exe -m py_compile routes/api.py`.

Expected: all route/security tests pass and existing knowledge RAG tests remain green. Commit with message `feat: expose protected knowledge evidence endpoint` and request review.

---

## Task 3: 在作业详情中加入学生/教师证据工作区

**Files:** Modify `routes/assignments.py`, create `templates/components/knowledge_evidence.html`, create `static/css/knowledge-evidence.css`, modify `templates/assignment_detail.html`; create `tests/test_assignment_knowledge_views.py` and `tests/test_knowledge_evidence_ui.py` as needed.

**Purpose:** 让用户在打开作业时立即知道作业知识焦点；教师可看到有限诊断，学生只看到学习相关信息。

**Step 1 — Write the failing tests.**

覆盖服务端页面上下文和 HTML 合同：

- `view_assignment` 对学生、教师、管理员传入 `knowledge_evidence`，作业不可访问仍在检索前被拒绝；
- 学生页面包含状态、证据标题/正文和下一步，教师页面包含 diagnostics；学生 HTML 没有 diagnostics、私有分数或 `KnowledgePointScore`；
- grounded/no-result/unavailable 三种 fixture 都有可理解的状态文本；证据正文以转义文本输出；
- macro 包含 heading 关联、`details/summary`、可见 focus 样式 hook、`role=status`/`aria-live`；移动宽度和 reduced-motion CSS 合同存在。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_assignment_knowledge_views.py tests/test_knowledge_evidence_ui.py`.

Expected: missing context/macro/markup failures.

**Step 2 — Implement server context and shared component.**

在 `assignments.py` 的 assignment detail 分支中，在已有访问检查后调用检索器（空 query）和投影服务；教师/admin 使用相应 audience，学生使用 student。新增组件 macro 只渲染安全投影，grounded 使用 details 展开证据，失败状态展示 summary/next_step；在 assignment detail 的合适位置复用 macro。新增 CSS 使用墨蓝/证据蓝/纸白/青绿/琥珀设计 token、可见键盘焦点和 reduced-motion。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_assignment_knowledge_views.py tests/test_knowledge_evidence_ui.py tests/test_knowledge_rag.py` and `git diff --check`.

Expected: role-specific assignment page tests pass with no private fields. Commit with message `feat: add role-aware assignment evidence panel` and request review.

---

## Task 4: 把证据边界带到提交详情和 Code Studio 初始状态

**Files:** Modify `routes/assignments.py`, `templates/submission_detail.html`, `templates/submit_code.html`; extend `tests/test_assignment_knowledge_views.py` and `tests/test_knowledge_evidence_ui.py`.

**Purpose:** 让提交复盘和写代码页面始终显示同一作业知识焦点，并清楚区分学习参考与评分依据。

**Step 1 — Write the failing tests.**

覆盖：

- `view_submission` 在提交权限检查通过后传入作业知识投影；无权提交不触发检索；
- submission detail 显示“不是本次评分依据”边界说明；
- `submit_code` 的 GET、截止时间错误和表单校验失败渲染都保留 evidence context；
- Code Studio 初始面板渲染 evidence 容器和最多前三个证据驱动的引导式 quick prompt，仍保留原有静态 quick prompt；用户正文没有未经转义的 HTML 注入点。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_submission_knowledge_views.py tests/test_knowledge_evidence_ui.py`.

Expected: missing context/markup assertions fail.

**Step 2 — Implement the page integration.**

在 submission detail 和 submit_code 的既有 assignment 访问成功后构造投影；对所有 render 分支传递默认安全 view，避免校验错误路径出现未定义变量。submission 使用 compact/边界说明；Code Studio 在 AI header 下放 compact evidence macro，并从投影的前 3 条标题生成固定模板文本，标题作为转义字符串，不把用户内容拼进 HTML。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_submission_knowledge_views.py tests/test_knowledge_evidence_ui.py tests/test_ai_sse_routes.py` and `git diff --check`.

Expected: all page contracts pass, existing AI route tests remain green. Commit with message `feat: surface evidence context in code studio and submissions` and request review.

---

## Task 5: 让 `/api/code_advice` 使用同一份作业证据

**Files:** Modify `routes/api.py`; create or extend `tests/test_code_advice_knowledge.py`.

**Purpose:** 让 Code Studio 的 AI 指导与页面证据一致，避免一个回答使用了作业知识、另一个界面却无法解释来源。

**Step 1 — Write the failing tests.**

覆盖聊天和分析两条路径：

- 有 assignment ID 时，访问检查后按 user question（分析模式为空 query）调用 assignment-scoped retrieval；无 assignment ID 不调用；
- 聊天 prompt 包含 bounded `build_knowledge_prompt_context()`，明确只使用给定 evidence 且不编造引用；代码和问题仍按既有长度/权限规则处理；
- SSE `delta` 事件不携带 evidence，唯一 `done` 事件同时带 raw retrieval 和 safe view；JSON 分支同样添加 additive data 字段；
- no-result/unavailable 不阻断回答，检索异常被安全降级；检索器调用发生在权限检查之后且最多一次；
- 任意证据正文含 `<script>` 时，服务端 JSON 是数据而非 HTML，并由前端 Task 6 负责 textContent 渲染。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_code_advice_knowledge.py`.

Expected: missing retrieval calls/payload fields or prompt assertions fail.

**Step 2 — Implement additive backend grounding.**

在 `code_advice` assignment 已加载并通过 `can_access_assignment` 后，构造 retrieval/view。只在 chat prompt 追加现有 prompt context；不把 evidence 注入 `generate_code_advice` 的分析算法，避免改变原有评分/建议语义。修改 SSE done 和 JSON response 的 data 结构，保留现有 answer/content/advice 字段与事件顺序；使用安全 fallback 处理检索异常。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_code_advice_knowledge.py tests/test_ai_sse_routes.py tests/test_knowledge_rag.py` and `E:\anaconda\python.exe -m py_compile routes/api.py`.

Expected: new contract tests and existing SSE tests pass. Commit with message `feat: ground code advice in assignment evidence` and request review.

---

## Task 6: 实现安全、可访问的动态证据收据

**Files:** Create `static/js/knowledge-evidence.js`; modify `templates/submit_code.html`; modify `static/css/knowledge-evidence.css` if needed; extend `tests/test_knowledge_evidence_ui.py`.

**Purpose:** 在流式回答完成后显示与服务端页面一致的证据收据，明确无结果/不可用时的恢复动作，并阻断动态正文 XSS。

**Step 1 — Write the failing tests.**

静态合同测试检查：

- `window.CodeSenseKnowledgeEvidence.render(container, payload, options)` 存在且使用 `textContent`/DOM 节点，不使用把证据正文拼入 `innerHTML` 的路径；
- grounded 会渲染标题、来源、details 和状态；no-result/unavailable 会渲染安全状态文案与 next step；null/未知 payload 不抛异常；
- `submit_code.html` 加载脚本并在 SSE `done` 和 JSON 完成分支调用 renderer，局部 delta 不渲染证据；
- 状态容器有 `role=status`/`aria-live`，按钮可键盘聚焦，CSS 对 reduced-motion 有明确处理。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence_ui.py`.

Expected: missing script or integration assertions fail.

**Step 2 — Implement the renderer and hooks.**

使用 `document.createElement`、`textContent`、`replaceChildren` 构建完整面板；只从 `knowledge_evidence` 读取白名单字段。为每个 assistant message 创建 evidence mount，done 事件后传入 view；保持现有 Markdown answer 渲染逻辑不变，证据正文不经过 Markdown/HTML parser。无证据时显示恢复按钮/quick prompt 的可操作文案，但不自动重复请求。

**Step 3 — Verify and review.**

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence_ui.py tests/test_code_advice_knowledge.py tests/test_ai_sse_routes.py` and `git diff --check`.

Expected: static UI/XSS contracts and AI integration tests pass. Commit with message `feat: render accessible knowledge receipts in code studio` and request review.

---

## Task 7: 离线质量评估、报告和端到端验收

**Files:** Modify `services/knowledge_eval.py` only if a new fixed contract is needed; create `tests/test_knowledge_evidence_integration.py`; create `docs/ops-runs/2026-09-16-knowledge-evidence-workspace.md`; update `CHANGELOG.md` and `README.md` only if release gate passes.

**Purpose:** 证明 10+ 个独立可验证迭代都能回归，并留下可供下一轮自动化读取的质量记录。

**Step 1 — Write the failing integration/quality tests.**

覆盖一个登录学生和教师 fixture 的完整路径：assignment detail、submission detail、submit page、evidence API、code advice SSE；断言权限边界、payload 一致性、fallback 可恢复、私有字段不出现在 HTML/JSON/日志。对固定离线评估增加不变量断言：样本数/相关样本数、Recall@1、Recall@k、vector/keyword/no-result 模式和延迟字段均存在且不劣于 origin/main 基线。

Run: `E:\anaconda\python.exe -m pytest -q tests/test_knowledge_evidence_integration.py`.

Expected: integration test fails until all previous contracts are wired together.

**Step 2 — Run the full verification matrix.**

从 worktree-local环境运行：

```powershell
$env:DEV_DATABASE_URL='sqlite:///E:/CodeSense/源代码/.worktrees/local-opt-20260916/instance/pr_student_code_review.db'
$env:REDIS_URL='redis://127.0.0.1:6379/1'
$env:SESSION_FILE_DIR='E:/CodeSense/源代码/.worktrees/local-opt-20260916/.runtime/sessions'
$env:UPLOAD_FOLDER='E:/CodeSense/源代码/.worktrees/local-opt-20260916/.runtime/uploads'
$env:LOG_DIR='E:/CodeSense/源代码/.worktrees/local-opt-20260916/.runtime/logs'
& 'E:\anaconda\python.exe' -m pytest -q --disable-warnings
& 'E:\anaconda\python.exe' -m services.knowledge_eval
& 'E:\anaconda\python.exe' -m compileall -q routes services tasks utils
git diff --check
```

把孤立运行的 `tests/test_submission_worker.py::test_formal_worker_updates_submission_in_isolated_database` 结果与全量串行结果分开记录；全量若仍出现远端基线的 SQLite session-cache 失败，标为 pre-existing baseline，不声称全绿。

**Step 3 — Browser smoke and artifact review.**

若本地浏览器工具可用，启动 worktree-local app 并验证学生 assignment → submit → Code Studio done receipt、教师 assignment diagnostics、无结果恢复态、窄 viewport 和键盘焦点；不使用生产账号/生产数据库。随后审查 `git diff --stat`、敏感字段扫描、工作树状态和所有任务 reviewer 结论。

**Step 4 — Release decision.**

只有当 targeted/related/integration checks、离线评估、静态检查、内部两类 reviewer 和浏览器 smoke（若环境可用）均通过，且 diff 没有迁移/依赖/私有数据泄露时，才把本次 10+ 项候选标记为 `keep` 并准备版本化发布；否则保留在隔离分支，报告 `needs_human`，不自动部署。若发布门通过，按现有自动化记忆中的流程更新版本、README/CHANGELOG、图文发布物、GitHub Release、飞书同步和生产健康验证；任何外部连接不可用都明确列为阻塞，不伪造完成。

**Step 5 — Commit report and final review.**

报告必须列出每项的 assumption、代码/测试位置、验证命令、结果、回滚点、风险和最终 keep/discard/needs_human；同时列出研究链接、离线评估数字、浏览器路径和已知基线失败。提交消息：`docs: record knowledge evidence workspace validation`，再请求一次整体只读 code review。

---

## 独立迭代清单

本计划至少产生以下 13 个可单独验收的产品/系统迭代：安全投影、no-store API、非枚举权限边界、参数校验、脱敏日志、教师诊断、学生知识焦点、提交详情边界、Code Studio 初始证据、AI bounded grounding、SSE/JSON 收据契约、可访问动态收据与恢复态、固定离线评估与报告。每项都有对应测试或可重复命令，不以文档数量冒充功能迭代。
