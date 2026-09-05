# CodeSense 项目分析文档

> 分析对象：CodeSense 酷森思（面向高校编程教学的代码评测与学习平台）
> 分析方式：通读 `app.py`、`config.py`、`models.py`、`routes/`、`services/`、`utils/`、`tasks/`、`tests/`、`static/js`、`.env.example` 及 `README.md`
>
> **阅读约定**：
> - 【事实】= 可由当前仓库代码 / 配置文件 / README 直接验证（关键结论附文件定位）。
> - 【推断】= 基于代码特征的合理判断，仓库中无明文，标注为推断。
> - 【建议】= 后续行动项，非现状描述。

---

## 【事实】

### 一、项目定位与主要用户流程

**1. 定位**

CodeSense 是一个面向高校程序设计课程的代码评测与教学平台。核心不是传统 OJ 的"AC/WA"判定，而是把"代码提交 → 受限执行 → AI 辅导 → 分阶段练习 → 学情记录"串在同一条流程中。

**2. 三类使用者**

| 角色 | 可做的事（README 声明） |
| --- | --- |
| 学生 | 提交 C++ 代码、查看测试结果与反馈、完成三阶段引导式学习（思路描述 → 步骤组装 → 费曼教学） |
| 教师 | 创建作业、管理班级与花名册、查看提交/完成情况/知识点/能力趋势 |
| 开发者/研究者 | 在 Flask、SQLAlchemy、可替换 AI 接口上继续扩展 |

**3. 主要用户流程（按角色，均以路由实现为据）**

- **学生**：登录（`routes/auth.py`）→ 进入作业（`routes/assignments.py::submit_code`）→ 提交代码（表单 POST → `evaluate_submission_async` 后台沙箱评测）→ 查看分数/反馈（`submission_detail.html`）→ 能力画像/知识点刷新（`tasks/ability_analysis.py`）。另一条：`static/js/code_submission.js` 直接 `fetch('/api/submit')` 走同步 API。
- **教师**：创建/编辑作业并维护测试用例（`routes/assignments.py`）→ 管理班级与花名册导入（`routes/classes.py`、`routes/users.py`）→ 查看提交矩阵/班级统计（`routes/classes.py`）→ AI 学情建议（`services/teacher_ai_advisor.py`）。
- **体验访客**：登录页体验入口 → 每次访问创建独立临时 SQLite 库（`services/demo_database.py::create_demo_run`）→ 体验学生/教师视图 → 退出或超时后清理（`cleanup_expired_demo_runs`）。

**4. 版本状态**

- `README.md` 声明当前为 `v1.0.0`（Standard Edition 首个正式版）。
- `app.py` 文件头注释写的是"版本: v0.2.0"（与 README 不一致）。
- `models.py::init_db` 默认写入 `system_version = '1.0.0'`。

**5. 许可证**：MIT License。在线体验站点为 saucodesense.com。

### 二、技术栈

**后端**（`requirements.txt` 锁定/约束）：

| 层次 | 事实 |
| --- | --- |
| Web 框架 | Flask 2.2.3、Werkzeug 2.2.3 |
| ORM/迁移 | Flask-SQLAlchemy 3.0.3、Flask-Migrate 4.0.4 |
| 会话/认证 | Flask-Session 0.4.0、Flask-Login 0.6.2、Flask-WTF 1.1.1 |
| 数据库驱动 | PyMySQL 1.0.3、`pymysql[rsa]`；开发/测试默认 SQLite |
| AI 接口 | openai>=1.0.0、zhipuai>=2.0.1 |
| 部署 | gunicorn 20.1.0 |
| 缓存/会话 | redis>=5.0.0（可选） |
| 其他 | numpy、pandas、openpyxl、python-docx（Excel/Word 导入导出）、marshmallow、Markdown、cryptography、email-validator |

**前端**（`templates/` + `static/`）：Jinja2 模板 + HTML/CSS/JavaScript；Monaco Editor（`require.min.js` 按需加载）；Sortable.js（积木拖拽）；Bootstrap 图标/样式；README 另提 Chart.js（教师图表）。

**代码执行**：依赖系统级 `g++`，编译参数 `-std=c++17 -O2 -Wall`。

### 三、目录结构与模块职责

**目录树**（当前仓库实际结构，省略 `__pycache__` 与图片资源）：

```
CodeSense-main/
├── app.py                    # 应用工厂 create_app
├── config.py                 # 四套配置
├── models.py                 # 18 个数据模型 + demo 绑定 + 索引
├── run.py                    # 开发启动脚本
├── wsgi.py                   # 生产 WSGI 入口
├── database_maintenance.py   # 一次性建表/迁移/索引
├── gunicorn_config.py        # Gunicorn 配置
├── forms.py                  # WTForms 表单
├── requirements.txt
├── .env.example
├── routes/                   # 8 个 Blueprint
│   ├── auth.py  main.py  assignments.py  users.py
│   ├── api.py  classes.py  thinking.py  grades.py
├── services/                 # 8 个业务服务
│   ├── api_keys.py  llm_client.py  ai_evaluator.py  course_grading.py
│   ├── demo_database.py  demo_experience.py
│   ├── teacher_ai_advisor.py  teacher_analytics.py
├── utils/                    # 工具层
│   ├── sandbox_runner.py  code_evaluator.py  llm_evaluator.py
│   ├── ability_scorer.py  maturity_calculator.py
│   ├── guidance_generator.py  code_advisor.py  thinking_ai.py
│   ├── async_tasks.py  auth.py  api.py  sse.py
│   ├── markdown_formatter.py  prompts.py  validate_testcases.py
│   └── agents/               # 阶段三费曼双 Agent 子包
│       ├── contracts.py  feynman.py  orchestrator.py  intent.py
│       ├── goal.py  memory.py  coverage.py  loop.py  model.py  tools.py
├── tasks/                    # 后台任务
│   ├── submission_tasks.py   # 提交评测
│   └── ability_analysis.py   # 能力趋势分析
├── templates/  static/       # 前端页面与 JS/CSS
└── tests/                    # 60+ 测试文件
```

**顶层入口/配置**：

| 文件 | 职责 |
| --- | --- |
| `app.py` | 应用工厂：配置加载、反向代理头修复（ProxyFix）、SQLAlchemy 引擎、会话后端（Redis→文件降级）、Cookie 安全、日志、注册 8 蓝图、gzip 压缩、`/healthz`、`/readyz`、启动异步任务 |
| `config.py` | `Config`/`Development`/`Testing`/`Production` 四类配置，敏感值全走环境变量；生产配置强制校验 `DATABASE_URL` 与 `SECRET_KEY` |
| `wsgi.py` | 强制 `FLASK_CONFIG=production`，暴露 `application` |
| `database_maintenance.py` | 生产一次性建表/补列/索引维护（先设 `AUTO_INIT_DB=0` 等再导入 app） |
| `run.py` | 开发启动：`app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)` |

**数据层** `models.py`（约 1471 行）18 个模型：

- 核心业务：`Class`、`User`（`student_id` 为主键）、`StudentRoster`、`Assignment`、`TestCase`、`Submission`。
- 学情/画像：`AbilityTrend`、`KnowledgePointScore`、`AssignmentKnowledgePoint`、`SystemConfig`。
- 交互/AI：`StudentQuestion`、`CodeAdviceRequest`、`TeacherAISuggestion`。
- 三阶段：`AssignmentThinkingPreset`、`ThinkingSession`、`ThinkingStageLog`。
- 辅助：`SystemLog`、`InviteToken`。
- 基础设施：`CodeSenseSession`（重写 `get_bind` 实现 demo 请求级临时库绑定）、`PERFORMANCE_INDEXES`、`ensure_performance_indexes`。

**路由层** `routes/`（约 8474 行）8 个 Blueprint：

| Blueprint | URL 前缀 | 职责 |
| --- | --- | --- |
| `auth` | — | 登录/注册/登出、教师邀请、单点登录 |
| `main` | — | 首页/关于/帮助/个人资料 |
| `assignments` | — | 作业增删改查、学生提交（含后台评测入口） |
| `users` | — | 用户管理、花名册导入 |
| `classes` | — | 班级管理、详情/统计/对比 |
| `api` | `/api` | REST API（`/submit`、代码建议、编程引导、能力分析 SSE） |
| `thinking` | `/thinking` | 三阶段引导式学习 |
| `grades` | — | 成绩/知识点视图 |

**服务层** `services/`（约 4437 行）：

| 服务 | 职责 |
| --- | --- |
| `api_keys.py` | 统一 API 密钥管理（智谱/OpenAI） |
| `llm_client.py` | 共享 LLM 客户端单例：provider 选择、重试、熔断、缓存、single-flight、后台优先级 |
| `ai_evaluator.py` | 能力趋势分析、知识点检测 |
| `course_grading.py` | 课程评分 |
| `demo_database.py` | 公开体验 per-session 临时 SQLite 库生命周期管理 |
| `demo_experience.py` | 向临时库注入演示数据 |
| `teacher_ai_advisor.py` | 教师首页 AI 学情建议 |
| `teacher_analytics.py` | 教师统计分析 |

**工具层** `utils/`（约 13355 行）：

| 模块 | 职责 |
| --- | --- |
| `sandbox_runner.py` | C++ 受限编译运行（g++ 查找、编译、逐用例运行、输出标准化比对） |
| `code_evaluator.py` | 启发式评分 + LLM 评估综合 |
| `llm_evaluator.py` | LLM 结构化评估 |
| `ability_scorer.py` / `maturity_calculator.py` | 能力评分/成熟度计算 |
| `guidance_generator.py` | 编程引导生成（含流式） |
| `code_advisor.py` | 代码建议 |
| `thinking_ai.py` | 三阶段 AI 服务层（预设生成、阶段评判、双 Agent 对话、`sanitize_response` 代码物理过滤） |
| `async_tasks.py` | 进程内异步任务队列 `AsyncTaskManager` |
| `auth.py` / `api.py` / `sse.py` | 装饰器 / API 响应 / SSE 事件 |
| `markdown_formatter.py` / `prompts.py` / `validate_testcases.py` | 格式化、提示词、用例校验 |

**`utils/agents/` 子包**（阶段三费曼双 Agent 独立实现）：

| 模块 | 职责 |
| --- | --- |
| `contracts.py` | Agent 角色/结果/消息类型契约 |
| `feynman.py` | 双 Agent 费曼运行时 |
| `orchestrator.py` | `Stage3Orchestrator`：每轮仲裁单一发言角色 |
| `intent.py` | 论坛意图识别 |
| `goal.py` | 阶段三用户目标构建 |
| `memory.py` | `MemoryStore` / `SqlAlchemyEventStore` 事件记忆 |
| `coverage.py` / `loop.py` / `model.py` / `tools.py` | 覆盖配置、循环、模型、工具 |

**后台任务层** `tasks/`：

| 模块 | 职责 |
| --- | --- |
| `submission_tasks.py` | `evaluate_submission_async`：后台线程评测提交 |
| `ability_analysis.py` | 异步生成能力趋势分析，带 `_ACTIVE_ANALYSES` 去重 |

**测试**：`tests/` 含 60+ 测试文件，覆盖 demo 隔离、三阶段、SSE、沙箱、评分、性能等；无 `pytest.ini`/`pyproject.toml`/`conftest.py`（已核实）。

### 四、关键请求 / 任务 / 数据流

**1. 应用启动流**

```
config[env] → create_app() → 配置代理头/引擎/会话(Redis→文件降级) → 注册蓝图
  → init_db(建表+列迁移+索引+默认系统配置) → 清理过期 demo 库
  → init_async_tasks(任务线程 + 预设扫描线程) → 服务就绪
```

**2. 代码提交评测流（两条真实入口，均已核实）**

```
入口 A（表单，异步沙箱）：routes/assignments.py::submit_code (POST)
  → 创建 Submission(pending) → 启动后台线程 evaluate_submission_async
      ├─ evaluate_cpp_code（启发式 + LLM）→ 归一化为 0-5
      ├─ run_test_cases（g++ 编译 + 逐用例运行）→ sandbox_score = passed/total × 5，覆盖 AI 分数
      ├─ _refresh_assignment_stats / _refresh_user_stats（从完整历史重算）
      ├─ 更新知识点评分 / 自动检测 AssignmentKnowledgePoint
      └─ AbilityTrend.mark_as_outdated → trigger_analysis_if_needed
  → Submission.status = evaluated

入口 B（API，同步无沙箱）：static/js/code_submission.js fetch('/api/submit')
  → routes/api.py::submit_code → evaluate_cpp_code（同步，直接累加 total_score/average_score）
```

**3. 沙箱执行流（`utils/sandbox_runner.py`）**

```
run_test_cases(source, test_cases)
  → 临时目录 → _find_compiler（g++ 查找，含 Windows MinGW 路径）
  → compile_cpp（写入 solution.cpp，g++ -std=c++17 -O2 -Wall，15s 超时）
  → 逐用例 run_single_test（subprocess 运行，5s 超时，输出截断 4096 字符，_normalize_output 比对）
  → 返回 {status: passed/partial/failed/compile_error/no_cases/unavailable, details}
```

**4. 三阶段引导式学习流（`routes/thinking.py` + `utils/thinking_ai.py`）**

```
教师发布作业 → 后台生成 AssignmentThinkingPreset（标准答案/关键步骤/代码块/噪声块/quiz/难度配置）
阶段一（思路描述）：evaluate_description（先本地信号规则快速评判，兜底走 AI）→ 评分(0-100) + 提示
阶段二（步骤组装）：选择题/填空题逐步作答 → check_quiz_equivalence（AI 语义等价）/ 顺序+缩进校验 → 代码预览
阶段三（费曼教学）：Stage3Orchestrator 仲裁 → 老师 Agent + 坏学生 Agent（拟人提问/写带 bug 代码）
                    → evaluate_feynman_code_fix（AI 判断修复）→ 全部记录入 ThinkingStageLog
所有 AI 输出经 sanitize_response（双重代码过滤）后返回
```

**5. AI 调用流（`services/llm_client.py::SharedLLMClient`）**

```
业务层 → SharedLLMClient.chat / chat_stream
  → 缓存命中（Redis→本地）? 直接返回
  → single-flight 合并同进程并发相同请求
  → 按 provider 顺序（默认 zhipu,openai）+ 健康状态选择
  → 并发信号量限流 + 重试（指数退避+抖动）+ 熔断（cooldown）+ 限流时降级模型
  → 返回文本 / 流式生成
```

**6. 公开体验数据隔离流（`services/demo_database.py`）**

```
访客点击体验 → create_demo_run(role) → 新建独立临时 SQLite 库 → 注入演示数据
→ 每请求 before_request → activate_demo_request_database → CodeSenseSession.get_bind 重定向到临时库
→ 退出/空闲超时(1h)/最长寿命(2h) → destroy_demo_run → 清理 sqlite 及 -wal/-shm/-journal 旁路
→ 后台线程通过 demo_run_id 继续绑定临时库；失效即停止，绝不回退正式库
```

### 五、运行与测试方式

**环境要求**（README）：

- Python 3.8 或更高；
- 系统装有可执行的 `g++` 且在 `PATH` 中（Windows 建议 MinGW/MSYS2）；
- 开发/测试默认 SQLite，生产需配置 `DATABASE_URL`；
- AI 引导/建议/学情分析需智谱或 OpenAI API 密钥。

**安装与配置**：

```bash
git clone https://github.com/XiaoCow666/CodeSense.git
cd CodeSense
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1 ; macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env   # 编辑 .env，填入 SECRET_KEY、AI 密钥等
```

`.env.example` 已列出全部关键变量（数据库、`SECRET_KEY`、AI provider/模型、AI 稳定性参数、连接池、后台任务、Web 性能、安全开关等）。

**启动开发服务**：

```bash
python run.py          # run.py 内 app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
# 访问 http://127.0.0.1:5000/login
```

无 AI 密钥时，登录、基础页面和不依赖 AI 的功能仍可用，AI 相关操作返回不可用/失败状态。

**运行测试**：

```bash
python -m pytest tests -q
```

- 仓库无 `pytest.ini`/`pyproject.toml`/`conftest.py`（已核实）；测试通过 app factory 的 `TestingConfig`（独立 SQLite `test_student_code_review.db`、`WTF_CSRF_ENABLED=False`）运行。
- 涉及 C++ 评测的测试需要 `g++`；涉及真实 AI 服务的测试需要相应环境变量。

**生产部署/维护**：

```bash
# 首次部署或数据库结构变化后执行一次（建表/补列/索引，不启动 Web 与后台任务）
python database_maintenance.py

# Gunicorn（bind 127.0.0.1:5000，默认 workers=2 gthread，preload_app=False，timeout 180s）
gunicorn -c gunicorn_config.py wsgi:application
```

`wsgi.py` 强制走 `production` 配置；`gunicorn_config.py` 绑定回环地址（经 Nginx 反代）、`preload_app=False`（避免 fork 共享连接/demo 库绑定）、限制请求行/头字段大小。

---

## 【推断】

1. **两条提交评测路径并存会带来不一致风险**（事实是"两条入口都被使用"，风险是推断）：入口 A（`assignments.submit_code`→`evaluate_submission_async`）与入口 B（`/api/submit`→同步 `evaluate_cpp_code`）对分数的口径（0–5 vs 0–100）与统计方式（历史重算 vs 直接累加）不同，若同一用户先后经两条路径提交，可能出现"同一提交得分不一致"或"统计被重复累加/口径漂移"。

2. **评分口径存在三套并存**：作业提交 0–5 分、能力画像/知识点/贝叶斯权重 0–100 分；`code_evaluator.py` 启发式返回 0–5、LLM 路径返回 0–100、历史还有 0–10，靠 `submission_tasks._normalise_score` 事后归一。这种"入参口径不定 + 集中归一"是历史演进痕迹，也是未来出 bug 高发区。

3. **"沙箱"目前是应用层受限执行，非 OS 级隔离**：`sandbox_runner.py` 只有 `subprocess` + 超时 + 输出长度限制 + 临时目录，无容器/低权限账户/网络限制/资源配额。README 亦明确声明"不应被当作完整的操作系统级安全沙箱"。据此判断：本项目适合课程内受控环境，公网部署有被恶意代码（fork 炸弹、系统调用、资源耗尽）攻击的风险。

4. **demo 隔离机制设计完整且刻意**：`demo_database.py` 用 `run_id` 强校验（48 位 hex）、路径越界检查、`CodeSenseSession.get_bind` 覆盖、后台线程显式携带 `demo_run_id`、失效即停止，说明作者对"体验数据绝不污染正式库、失效会话绝不回退"有明确且反复强调的设计意图（大量英文注释强调此点）。这是工程成熟度较高的部分。

5. **AI 客户端是一套"生产级容错层"**：provider 顺序、熔断冷却、single-flight、并发信号量、后台线程优先级让路、Redis+本地双层缓存，远超教学演示所需。推断作者对"AI 服务不稳定、限流、成本"有真实生产经验，或为公网演示站 saucodesense.com 的稳定性特意加强。

6. **版本号不统一**：`app.py` 头部 v0.2.0、README/系统配置 v1.0.0，说明主程序入口头部注释未随版本发布同步更新，属维护疏漏而非行为差异。

7. **阶段三实现存在新旧并存**：`utils/agents/` 是完整、结构化、有契约/编排/记忆/意图识别的子包；`utils/thinking_ai.py` 中的 `teacher_agent_chat`/`student_agent_chat` 定义后**无任何调用点**（已核实为死代码），而 `student_agent_write_code`/`evaluate_feynman_code_fix` 仍被 `utils/agents/tools.py` 复用（已核实）。据此推断阶段三从"简单双函数"演进到"带仲裁的论坛式编排"，旧函数未清理干净。

8. **性能优化意识较强且有针对性**：`models.py` 多处注释明确"把 N+1 查询压缩为一次聚合"（`get_class_average_scores`、`Class.get_statistics`），并集中声明 `PERFORMANCE_INDEXES`。推断作者在实际部署中遇到过首页/班级视图查询性能问题并做了针对性修复。

### 未知项 / 待确认

> 以下问题在本次分析中无法仅凭仓库代码/README 完全确定，需进一步核对或由维护者确认：

1. **两条提交路径的取舍意图**：`/api/submit`（同步旧路径）与表单后台评测（异步沙箱）是否刻意共存，还是旧路径待下线？前端 `code_submission.js` 与模板表单分别服务哪些页面，是否存在同一用户跨两条路径提交的真实场景。
2. **生产数据库实际 schema 与数据规模**：仓库只体现 SQLAlchemy 模型，生产 MySQL 的实际表结构、数据量、是否有历史脏数据（如 0–10 分制残留）无法从代码确认。
3. **在线站点部署拓扑**：saucodesense.com 是否已加容器/OS 级沙箱隔离、是否真用 Nginx→Gunicorn、Redis 是否启用，均只能依据 `config.py`/`gunicorn_config.py` 的注释推断，无法从仓库验证。
4. **语音转文字的实现范围**：README 称"部分流程支持语音转文字与文本优化"，代码中 `routes/thinking.py`、`static/js/thinking.js`、`templates/thinking/arena.html` 含 speech/recognition 相关代码（已核实存在），但具体启用条件、降级策略未逐一核对。
5. **`Course`/课程评分模块的完整接线**：`services/course_grading.py`、`utils/maturity_calculator.py`、`utils/ability_scorer.py` 的实际调用点与数据入口未全部追踪（本次仅确认其在模型/服务中的存在）。

---

## 【建议】

> 按优先级排序，均为基于【事实】与【推断】的工程改进方向，未改动任何代码。

### 高优先级

1. **统一提交评测路径**。将 `/api/submit` 也接入 `evaluate_submission_async` 的沙箱 + 历史重算链路，消除"同一提交两种评分/两种统计"的不一致；否则应在文档/接口上明确标注 `/api/submit` 为 legacy 并规划下线。

2. **收敛评分口径**。在模块边界内强制单一分数制（如内部统一 0–100，仅落库时归一为 0–5），把 `_normalise_score` 这类"事后猜测量纲"的逻辑前移到评估器返回处，减少隐式 `×20`/`÷2` 的脆弱性。

3. **公网部署前补齐真正的执行隔离**。若 saucodesense.com 面向公网，建议接入容器（Docker/nsjail/firejail）或至少低权限账户 + rlimit（CPU/内存/进程数/文件数）+ 网络禁用 + 每次编译产物目录隔离，并将此列为上线 blocker。

4. **修正版本号不一致**。将 `app.py` 文件头 `版本: v0.2.0` 与 README/`system_version` 对齐为 v1.0.0。

### 中优先级

5. **清理阶段三死代码**。已核实 `teacher_agent_chat`/`student_agent_chat` 无调用点，建议删除或标注 deprecated，避免后续维护只改一处。

6. **为 `sanitize_response` 建立回归测试基线**。该函数是"防止 AI 直接给答案"的第二层物理防线，正则过滤易被新型代码形态绕过，建议积累漏过滤样本作 fixture 持续回归。

7. **为沙箱增加资源/目录白名单专项测试**。现有测试主要覆盖功能正确性；建议增加"编译超时、运行超时、输出超长截断、临时目录清理"的专项断言，确保安全边界在重构中不退化。

8. **评估多 worker 下的进程内缓存一致性**。`_CLASS_AVERAGE_CACHE_TTL=15s`、`SystemConfig._cache_ttl=30s` 是进程内缓存；Gunicorn 多 worker 下各进程独立，可能出现短暂不一致，建议评估是否可接受或收敛到 Redis。

### 低优先级 / 长期

9. **考虑将 `AsyncTaskManager` 迁移为外部队列**。代码注释已自述"生产建议 Celery + Redis/RabbitMQ"；当前线程队列多 worker 下各自复制，去重/重试/失败标记局限在进程内，横向扩展前应迁移。

10. **补充"双提交路径/评分口径/三阶段调用关系"的架构说明**。README 已有 mermaid 结构图，但缺少这些易踩坑细节，建议补入 `DEPLOYMENT.md` 或新增 `ARCHITECTURE.md`。

11. **统一演示数据种子与正式评分口径**。`demo_experience.py` 注入的演示提交/画像需与正式评分链路（0–5 提交分、0–100 画像分）严格一致，避免演示页展示的分数与正式用户看到的规则出现差异。

---

*（文档完）*
