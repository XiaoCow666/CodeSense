# CodeSense 项目理解与学习记录

## 一、项目定位

CodeSense 是一个面向高校编程教学的 AI 辅助评测与学习平台。它把代码提交、受限执行、AI 辅导、分阶段练习、学情分析放进同一条学习链路。核心定位是：引导学生自己学会，而不是替学生写出答案。

### 主要用户

1. 学生：提交 C++ 程序、查看测试结果和反馈，进入三阶段引导式学习流程，记录自己的思路与解释。
2. 教师：创建和管理作业、组织班级与花名册，查看提交记录、作业完成情况、知识点和能力趋势。
3. 开发者/研究者：在 Flask、SQLAlchemy 和可替换的 AI 服务接口上继续扩展评测、教学和数据分析能力。

### 核心问题

传统 OJ 的两个痛点正是这个项目要解决的核心问题：

1. 对学生：只看到"对/错"，不知道问题出在哪。传统评测只给二元结果，学生无法定位问题究竟在思路、实现、边界条件还是调试过程。CodeSense 引入受限评测（Causal Sandbox）+ AI 辅导，并把一次练习拆成三阶段，强制学生先讲思路、再组装步骤、最后用自己的话解释（费曼教学），让"理解"过程可见、可评估。
2. 对教师：反馈零散、共性问题难发现。教师要在大量提交记录里人工找共性问题，再把零散反馈整理成教学安排，成本高。CodeSense 用两层画像体系沉淀学情：AI 反馈与能力分析文本按算法、代码风格、功能完整性、执行效率、可读性等维度组织（综述存于 `AbilityTrend` 的能力分析内容），可量化的画像则以 C 知识点为单位、经贝叶斯权重更新为 0–100 的 `KnowledgePointScore`。教师端据此把学生表现沉淀为可统计、可下钻的学情数据，辅助教师定位需要补练的内容。

## 二、总体结构与目录分层

### 顶层文件（入口与配置）

- `run.py`：开发启动入口，默认走开发配置。
- `app.py`：应用工厂，`create_app()` 注册 Blueprint、初始化 DB/会话/登录态、ProxyFix、后台任务、访问日志与压缩中间件。
- `wsgi.py`：生产 WSGI 入口，配合 `gunicorn_config.py`。
- `config.py`：development / testing / production 三套配置，读取 `.env`。
- `models.py`：全部 ORM 模型（见下）。
- `forms.py`：Flask-WTF 表单定义。
- `database_maintenance.py`：生产一次性建表/迁移/索引维护。
- `deploy.sh` / `update.sh`：部署与运维脚本。

### routes/ — Web 与 API 路由层（Blueprint）

- `auth.py`：登录/登出/注册/教师邀请，角色认证。
- `main.py`：首页、关于、帮助等基础页面。
- `assignments.py`：作业 CRUD、测试用例与提交管理。
- `thinking.py`：三阶段引导式学习（思路/积木/费曼）与阶段 Agent API。
- `classes.py`：班级、花名册、导入与班级统计。
- `users.py`：用户资料、学生/教师/管理员页面。
- `grades.py`：成绩视图与课程评分。
- `api.py`：提交评测、代码建议、能力分析 SSE 等 REST 接口。

路由层只做参数解析、权限校验与业务编排，不承载核心逻辑。

### services/ — 面向业务的"较厚"服务层

- `llm_client.py`：统一 LLM 客户端（`SharedLLMClient`），智谱/OpenAI 多 provider 重试、限流与熔断。
- `ai_evaluator.py`：AI 评测（含流式能力分析）。
- `api_keys.py`：API 密钥管理器（不落库明文）。
- `course_grading.py`：课程成绩计算。
- `teacher_analytics.py`：教师端班级/知识点学情统计。
- `teacher_ai_advisor.py`：AI 学情建议。
- `demo_database.py` / `demo_experience.py`：公开体验入口的临时 SQLite 会话隔离与演示数据。

### utils/ — 底层工具与核心引擎

- `sandbox_runner.py`：Causal Sandbox：g++ C++17 受限编译/运行、超时与输出限制。
- `code_evaluator.py`：启发式评分 + 可选 LLM 评估叠加。
  （早期版本曾使用 CodeBERT + TextCNN 本地模型评分，当前 main 已移除，相关描述仅见于历史文档/提交。）
- `llm_evaluator.py`：旧版 LLM 评估器 `LLMEvaluator`。注意：它仍自行初始化 provider 客户端并选择 api_type（`zhipu`/`openai`），仅在发请求时委托给 `services/llm_client.py::SharedLLMClient`。
- `guidance_generator.py`：启发式引导提示生成（不直接给答案）。
- `code_advisor.py`：代码建议。
- `ability_scorer.py` / `maturity_calculator.py`：贝叶斯能力画像与成熟度。
- `async_tasks.py` / `sse.py`：线程池任务队列 + SSE 流式推送。
- `thinking_ai.py`：三阶段引导 AI 交互。
- `markdown_formatter.py`：格式化输出。
- `prompts.py`：提示词模板。
- `auth.py` / `api.py` / `validate_testcases.py`：权限装饰器、通用 API 辅助与测试用例校验。

### utils/agents/ — 阶段三费曼/论坛 Agent 子系统

- `feynman.py`：双角色（教师/学生上下文）Agent 运行时。
- `loop.py`：Agent 主循环；`tools.py`：工具；`model.py`：模型适配。
- `orchestrator.py`：编排；`intent.py`：意图路由；`memory.py`：记忆；
  `coverage.py`：知识点覆盖判定；`goal.py`：目标管理；`contracts.py`：数据契约。

### tasks/ — 异步任务

- `submission_tasks.py`：提交后评测、AI 分析等后台任务。
- `ability_analysis.py`：能力画像的异步计算与分析。

### 前端

- `templates/`：Jinja2 页面，含按角色区分的首页/详情页，以及 `templates/thinking/arena.html`（三阶段竞技场）、组件化的多种代码编辑器片段。
- `static/`：CSS、JS（Monaco 按需加载、SSE 客户端、编辑器/提交/思路对话脚本、安全输出处理器）、图片与第三方库（Sortable、require.min.js）。

### 核心数据模型一览（models.py）

- 用户与组织：`User`（学生/教师/管理员 + RBAC）、`Class`、`StudentRoster`、`InviteToken`。
- 教学资源：`Assignment`、`AssignmentKnowledgePoint`、`TestCase`、`AssignmentThinkingPreset`。
- 学习记录：`Submission`、`ThinkingSession`、`ThinkingStageLog`、`StudentQuestion`、`CodeAdviceRequest`。
- 画像与学情：`AbilityTrend`、`KnowledgePointScore`、`TeacherAISuggestion`。
- 平台支撑：`SystemLog`、`SystemConfig`、`CodeSenseSession`。

### 测试（tests/）

覆盖面较广，突出三类特色域：沙箱演示特性（`test_sandbox_features`，实为演示数据装载/免密登录/生产禁用三项用例，见附录 B，不直接覆盖 C++ 编译执行）、演示会话隔离（`test_demo_*`）、阶段三 Agent/论坛（`test_stage3_*`），另有 SSE、成绩、班级花名册、HTTPS 代理与性能基线等测试。

## 三、核心运行流程与调用链

### 1. 应用启动与请求生命周期

`run.py` / `wsgi.py` → `app.py::create_app`：加载 `config.py`、初始化 db、注册所有 Blueprint（routes/）、接入 Flask-Login / Flask-Session、ProxyFix、后台任务队列与压缩/日志中间件。请求进入 Blueprint 路由，经 services/ 编排，落到 utils/ 引擎与数据库。

说明：development 环境在启动时自动建表；production 环境 `DB_AUTO_INIT=False`，需先运行 `database_maintenance.py` 建表/维护索引。

### 2. 代码提交 → 评测调用链（最重要的一条）

代码提交有两条平行通路：

**A. 网页表单路径（异步，主流）**

`POST /submit/<assignment_id>`（`routes/assignments.py::submit_code`，蓝图无 url_prefix）→ 创建 `Submission(status=pending)` → 把任务投进后台线程 `tasks/submission_tasks.py::evaluate_submission_async` → 页面跳转到"评测中"，前端经 `get_submission_status`（`routes/api.py`）/ SSE 轮询进度。

后台线程按序执行：

1. AI 基础评估：`utils/code_evaluator.py::evaluate_cpp_code`，内部为启发式评分 `calculate_heuristic_score` + 可选 LLM 反馈，产出 score/feedback 并经 `_normalise_score` 统一归一到 0–5。（LLM 叠加经 `utils/llm_evaluator.py::LLMEvaluator`，其网络请求再委托 `services/llm_client.py::SharedLLMClient`。）
2. 沙箱用例评判：`utils/sandbox_runner.py::run_test_cases` → `compile_cpp` 用 g++ 按 C++17 编译（15s 超时）→ `run_single_test` 逐用例运行（5s 超时、输出长度限制）→ 写回 `sandbox_passed/total/detail`；存在测试用例时以沙箱通过率重算最终 0–5 分。
3. 状态置为 evaluated，并 `_refresh_assignment_stats` / `_refresh_user_stats` 基于全量历史重算，避免种子数据重复累加。
4. 知识点画像：用作业绑定或 AI 探测出的知识点调 `KnowledgePointScore.update_score`。
5. 触发能力分析：`AbilityTrend.mark_as_outdated` + `trigger_analysis_if_needed()`（内部按键去重防并发）。
6. 写 `SystemLog`（公开体验会话不写正式库审计日志）。

**B. API 路径（同步）**

`POST /api/submit`（`routes/api.py::submit_code`）：同步 `evaluate_cpp_code` + 更新作业统计 + 触发能力分析，直接 JSON 返回 submission_id/score/status。

**数据落库**：`Submission`（含 sandbox_*、ai_feedback）→ `Assignment`/`User` 聚合 → `KnowledgePointScore` → `AbilityTrend`。

### 3. 三阶段引导式学习调用链

入口 `GET /thinking/<assignment_id>`（`routes/thinking.py`）加载 `templates/thinking/arena.html`：

1. 会话初始化：`POST /thinking/api/start_session`（thinking 蓝图 `url_prefix='/thinking'`）创建 `ThinkingSession`，装载 `AssignmentThinkingPreset`（目标、关键步骤、提示语）；无预设时走 AI 生成并 lazy 回填。
2. 阶段一（思路）：`POST /thinking/api/stage1/submit` → `utils/thinking_ai.py::evaluate_description` 先做本地快速检查、必要时请求 AI，按 key_steps 匹配打分；≥50 分放行至阶段二，逐条写 `ThinkingStageLog`。
3. 阶段二（组装）：`POST /thinking/api/stage2/verify` 验证步骤顺序并把组装结果规整成可编译代码、生成预览；AI 回应统一经 `utils/thinking_ai.py::sanitize_response` 做物理级代码过滤——这是提示词约束之外的第二层防泄漏。
4. 阶段三（费曼/论坛）：`POST /thinking/api/stage3/forum/message` → `utils/agents/orchestrator.py::Stage3Orchestrator.handle_user_message` → intent 意图识别、目标角色仲裁（学生/教师双 Agent）、loop 多轮、tools 追问/探测、coverage 判定掌握度，SSE 流式返回；`POST /thinking/api/stage3/forum/trace` 提供轨迹复盘，`POST /thinking/api/complete_session` 收尾归档。

**AI 调用现状（重点）**：仓库当前处于新老两层并存的迁移状态。

- 新链路（三阶段对话、能力分析、教师建议等）直接使用 `services/llm_client.py::SharedLLMClient`（多 provider 重试、限流、熔断集中在此）。
- 旧链路（提交评测中的 LLM 叠加）仍先经 `utils/llm_evaluator.py::LLMEvaluator`：该对象在 `_init_client` 里自行初始化 ZhipuAI/OpenAI 客户端并选择 api_type，仅真正发请求的 `_chat_completions_create` 委托给 `SharedLLMClient`。因此"所有 AI 请求统一出口为 SharedLLMClient"的表述不完整，准确说法是：**实际网络请求统一委托 SharedLLMClient，但旧评估器的对象初始化/选型逻辑仍保留在 LLMEvaluator**。

### 4. 能力画像与教师端学情链路

提交评测成功后（异步/同步两通路一致）即触发能力分析刷新：`AbilityTrend.mark_as_outdated` → `trigger_analysis_if_needed()`（防并发 key 去重）→ 后台线程 `tasks/ability_analysis.py::generate_ability_analysis_async` → 拉最近 20 条提交 → `services/ai_evaluator.py::AIEvaluator.analyze_ability_trend_stream` → 前端经 `/api/stream/ability-analysis`（SSE，`routes/api.py::stream_ability_analysis`）流式渲染 Markdown → 结果落回 `AbilityTrend`。教师端 `teacher_analytics` / `teacher_ai_advisor` 再从班级、知识点维度做聚合视图与建议。

**公开体验隔离**：`services/demo_database.py` 为每次体验建临时 SQLite，demo_run_id 沿提交、沙箱、能力分析各后台线程传递；线程执行前二次校验会话存活，退出即清理，绝不写正式库。

**失败可见性**：AI/沙箱失败在体验中一律置 failed，前端显示"失败/重试"，不允许用默认分数伪装成功。

## 四、架构理解

CodeSense 是一个 Flask 单体 Web 应用（Python），核心是「C 语言/C++ 编程教学」：学生交代码 → 受限沙箱编译运行 → AI 启发式引导学习 → 沉淀能力画像；教师端管理班级/作业并查看学情。架构上采用「路由 → 服务 → 引擎/任务 → 模型」的分层，并配了一套会话级临时 SQLite 的公开演示隔离机制。

### 分层思路

- **routes/**（蓝图/路由层）：页面 + JSON/SSE API，只做参数解析、权限校验、编排服务。
- **services/**：业务服务层，偏纯逻辑、易单测（LLM 客户端抽象、AI 评估、密钥管理、成绩册、教师分析、演示数据隔离）。
- **utils/**：引擎/工具层（代码评测、沙箱执行、提示词、能力画像、SSE、权限装饰器，以及三阶段 Agent 引擎 `utils/agents/`）。
- **tasks/**：后台任务（异步评测、能力分析）。
- **models.py**：单一 ORM 文件（约 1500 行、19 个模型）；**templates/**、**static/**：Jinja2 模板与前端资源；**tests/**：pytest 测试。

### 启动链路与关键机制

`app.py` 是唯一入口，`create_app()` 应用工厂：加载 `config.py`（development/testing/production 三套）→ 配置数据库连接池、Session（优先 Redis，失败降级文件系统）→ 初始化 db、Flask-Login、Flask-Session → 注册 8 个蓝图 → 初始化异步任务系统 → 自动建表（development）。根级挂了全局 `before_request`：单点登录校验 + demo 临时库激活。

### 核心子系统

1. **代码评测执行链（Causal Sandbox）**：以 g++ C++17 编译，15s 编译 / 5s 运行超时、临时工作目录、限输出长度、标准化输出比对。调用链：
   `routes (submit) → tasks/submission_tasks.evaluate_submission_async → utils/code_evaluator（启发式评分 + 可选 LLM 叠加）→ utils/sandbox_runner.run_test_cases（受限编译运行）`。
   注意：当前 main 的 `code_evaluator.py` 模块说明为"启发式评分和大模型评估"，不再依赖本地 CodeBERT/TextCNN 模型（后者为早期版本实现，仅见于 AGENTS.md 等历史描述）。
2. **AI 服务抽象**：`services/llm_client.py::SharedLLMClient` 统一封装智谱/OpenAI，含 provider 健康状态、故障切换、退避重试；`services/api_keys.py` 统一管理密钥。新链路只依赖这一层；旧评估器 `utils/llm_evaluator.py::LLMEvaluator` 的初始化/选型逻辑仍在旧模块内（见三.3"AI 调用现状"）。
3. **异步 + SSE**：提交后不阻塞请求，任务由线程池执行，前端通过 `utils/sse.py` 的 SSE 流（如 `/api/stream/ability-analysis`）拿进度。
4. **三阶段引导式学习（thinking）**：一次练习 = 思路描述 → 步骤组装 → 费曼教学（stage3）。费曼部分是一套较重的多角色 Agent 系统，全在 `utils/agents/`；入口路由在 `routes/thinking.py`，页面在 `templates/thinking/arena.html`。
5. **公开演示体验隔离（重点设计）**：不注册真实账号也能体验。每次进入 `/login` 的体验入口会生成一个带随机 run_id 的独立临时 SQLite（`services/demo_database.py`），由 `before_request` 按会话激活该库；演示账号（`demo:*`）走 Flask-Login 的独立 user_loader。`services/demo_experience.py` 负责向临时库播种演示学生/作业/提交等数据，退出或超时（空闲 1h / 最长 2h）即删除，与 AGENTS.md 的 PR worktree 数据隔离约定一致。
6. **成绩与画像**：作业提交分 0–5 分；知识点/能力 0–100 分（贝叶斯权重，`ability_scorer` + `AbilityTrend`/`KnowledgePointScore`）。`routes/grades.py` + `services/course_grading.py` 汇总成绩册并导出 Excel；教师 AI 建议在 `services/teacher_ai_advisor.py`。

### 安全/运维要点

- 权限分三类装饰器：`login_required` / `teacher_required` / `admin_required`。
- 单点登录：`before_request` 比对 session 与库内 `current_session_id`，发现并发登录强制登出。
- Session 优先 Redis，失败自动降级文件系统；生产强制 `SECRET_KEY` ≥32、`DB_AUTO_INIT=False`（需先跑 `database_maintenance.py` 建表/索引）。
- 提供 `/healthz`、`/readyz` 探针、ProxyFix 反代协议还原、gzip 压缩与慢请求日志。

---

## 附录 A：个人理解与后续设想（【非现状】，仅代表个人想法）

> 以下内容不属于当前仓库现状，是学习过程中产生的问题记录与改进设想。

1. **对 AI 助手回复过滤的设想**：当前只在 `utils/thinking_ai.py` 内对回复做"物理级代码屏蔽"。我认为不应完全屏蔽：可以做一个 agent 专门监测回复，把与答案直接相关的代码屏蔽掉，而保留与知识点相关的示例代码来帮助学生理解；同时检查回复是否正确，提高回复正确率。
2. **第三阶段三元角色设想**：目前费曼是"教师/学生"双 Agent。我认为可以让老师 agent 给我一个任务，让我给学生 agent 讲这个知识点，把我的理解完整讲完；学生 agent 再提问。如果我讲的知识点有错误、模糊或缺失，就由学生 agent 多角度追问检查；如果我回答不上来，就转向老师 agent 提问。进一步，希望两个智能体共享数据：老师给我讲解和提问、我给学生讲解、学生指出我讲不清楚处并给出代码修复，构成"老师—我—学生"三元关系，用算法适配这套数据流通。
3. **自适应选题设想**：可依据 AI 助手互动中生成的追问问题来优化题目并沉淀进题库，再用深度学习/自适应算法按学生水平分配题目。
4. **情感分析与学习积极性设想**：希望纳入学习态度与积极性评估，指标可包括：对 AI 助手的使用程度；对作业开设习题复习处、设置复习环节并评估复习效果；最后用算法综合评价学生的学习积极性。
5. **使用中发现的体验问题**：
   - 引导式学习第二部分给出的题目会多出一些无关内容，中间完整代码展示处的代码并不完整（左侧按题拼凑的代码完整，中间展示的有所缺失，但能正常运行出正确结果）。
   - 代码页右侧的 AI 助手回答会重复。
   - 代码提交后的评估多是 C++ 向，对 C 语言的评估不够准确。
   - AI 响应较慢，且因 prompt 缘故回复略显臃肿。
   - 第二阶段"请求提示"无法定位学生具体卡在哪个问题：它通常从第一阶段的问题继续从头解释并提问，难以直接帮学生解决当前卡点。设想把请求提示精确到具体问题，直接给该问题的提示并提问与当前题目相关的问题。
6. **学习计划**：后续需要逐步学习项目相关技术栈，积累实践经验，目前对项目内不少内容理解还不到位，希望能逐步赶上学长进度。

## 附录 B：个人安装、运行与测试记录（个人环境备忘）

- 记录时间：2026-09-03（2026-09-05 按 PR 评审意见补充真实 C++ 编译运行验证与范围说明）；环境：Windows，Python 3.11（项目虚拟环境 .venv），g++ 16.1.0（MSYS2，路径位于 MSYS2 的 mingw64/bin 下，与 `utils/sandbox_runner.py` 的编译器候选路径一致）；项目：CodeSense（v1.0.0）。

### 安装

按 README「快速开始」在项目根目录完成：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

依赖安装成功，共 60 个包，核心版本为 Flask 2.2.3、SQLAlchemy 2.0.52、python-docx 1.2.0、openai 3.7.0、cryptography 41.0.3 等。随后安装 C++ 编译器 g++ 16.1.0（MSYS2）。

过程中遇到的问题与解决：

1. Python 3.14 兼容性问题：系统 Python 为 3.14，Flask 依赖的 Werkzeug 2.2.3 使用已被 3.12+ 移除的 `ast.Str`，启动即报 `AttributeError: module 'ast' has no attribute 'Str'`。改用 Python 3.11 创建虚拟环境后解决。
2. `.env` 残留 MySQL 配置：`.env` 中的 `DATABASE_URL` 实际仍指向本地 MySQL（user:password@127.0.0.1:3306），启动时 `db.create_all()` 连接 MySQL 被拒（WinError 10061）。注释该行后回退到本地 SQLite 数据库。

### 运行

开发配置启动（未设置 DATABASE_URL 时使用本地 SQLite，首次启动自动建表）：

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

启动结果：数据库初始化成功，异步任务系统初始化成功；Running on http://127.0.0.1:5000。本机未安装 Redis，会话自动降级为文件系统存储（filesystem），不影响使用。浏览器访问 http://127.0.0.1:5000/login，登录页提供免注册的学生体验与教师体验入口。

说明：启动日志中的"生产模式：启用 INFO 级别日志"字样由 `.env` 内 `FLASK_DEBUG='False'` 引起，实际运行配置为 development（日志显示 Debug mode: on），不构成问题。

### 测试

**1. 沙箱演示特性自动化测试（pytest）**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sandbox_features.py -q
```

结果：3 passed, 26 warnings（2026-09-05 本机复测约 60s）。三项用例分别为 `test_seed_demo_data_creation`（演示数据装载）、`test_sandbox_login_flows`（免密登录）、`test_security_prevents_sandbox_in_production`（生产环境禁用沙箱），属于"沙箱（演示）登录与安全特性"测试，**并未调用 g++ 编译运行代码**。另经核对，`tests/test_demo_submission_isolation.py` 中同样对 `run_test_cases` 做了 mock，即 tests/ 目录当前不存在覆盖真实 C++ 编译运行链路的端到端用例。因此此前"通过沙箱评测相关测试即可说明代码评测链路可用"的表述不准确，见下方补充验证。

**2. 真实 C++ 编译运行链路验证（2026-09-05 补充，回应评审意见）**

直接调用 `utils/sandbox_runner.py::run_test_cases`，对一段 C++17 加法程序（`cin` 读入、`cout` 输出）用本机 g++ 编译后运行 3 个用例（含公开与隐藏用例），结果：

```text
compiler = C:\msys64\mingw64\bin\g++.exe   # g++ (MSYS2) 16.1.0，与沙箱候选路径一致
compiler_available = true, compile_success = true, compile_error = ""
passed 3 / total 3, status = passed
# 各用例 actual_output 与 expected_output 经 _normalize_output 比对一致，单例运行 33–510ms
```

验证方式为临时脚本（用后即删）：

```python
from utils.sandbox_runner import run_test_cases

source = '''#include <iostream>
using namespace std;
int main() { int a, b; cin >> a >> b; cout << a + b << endl; return 0; }'''

run_test_cases(source, [
    {'input_data': '3 5\n',   'expected_output': '8',   'id': 1, 'is_public': True},
    {'input_data': '-1 1\n',  'expected_output': '0',   'id': 2, 'is_public': False},
    {'input_data': '100 200\n', 'expected_output': '300', 'id': 3, 'is_public': False},
])
```

由此可确认：在具备 g++ 的本机环境下，C++17 源码可经沙箱完成编译→运行→输出标准化比对→判定。该验证覆盖引擎层单次编译与运行，**未覆盖完整 Web 提交→后台任务→SSE/轮询→落库链路**（该链路中的 AI 叠加评分依赖真实 AI 密钥）。

### 结论

本项目已在本地 Windows 环境完成安装、成功启动；沙箱（演示）登录与安全特性 3 项自动化测试通过；并额外经真实 g++ 16.1.0 编译运行验证了 `utils/sandbox_runner` 的 C++17 编译/运行/输出比对链路可用。AI 辅助功能需在 `.env` 配置智谱或 OpenAI 密钥后启用；Web 端完整提交评测链路（含 LLM 叠加评分）与依赖真实 AI 密钥的部分测试不在本次验证范围内，属未验证事项。

### 个人工具与参考资料

- AI 工具：Trae（接入 ds-v4-flash）。
- 参考资料：
  - MSYS2 安装相关：<https://blog.csdn.net/byxdaz/article/details/147084976>
  - Git 命令入门相关：<https://blog.csdn.net/qq_45712124/article/details/159283588>
