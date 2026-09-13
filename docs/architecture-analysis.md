# CodeSense 项目理解与架构分析

> 阶段一交付物 | 分析人：张诗若 | 分析版本：v1.0.0 (main @ 1d81744)

---

## 一、项目定位

### 1.1 是什么

CodeSense（酷森思）是一个**面向高校编程教学的代码评测与 AI 引导学习平台**。它不是传统意义上只给 AC/WA 判定的 OJ（Online Judge），而是把"代码提交 → AI 评分辅导 → 三阶段引导式学习 → 学情分析"串联在同一条流程中，帮助学生从"写对代码"走向"理解代码"。网页提交路径额外包含受限沙箱编译运行与测试用例评判（详见 §3.1）。

项目当前版本为 **v1.0.0**（首个正式版），采用 MIT 许可证开源，在线体验站点为 saucodesense.com。

### 1.2 解决什么问题

README 明确指出了传统 OJ 的痛点：

> 普通 OJ 很擅长判断程序是否通过测试，但学生看到的通常只有 AC 或 WA。他们不一定知道问题出在算法、实现、边界条件还是调试过程。教师面对大量提交记录，也很难手工归纳每个班级反复出现的问题。

CodeSense 的应对方式是：
- **学生侧**：先写思路 → 再组装步骤 → 最后向 AI 解释代码（费曼教学法），AI 通过追问而非直接给答案来引导
- **教师侧**：自动汇总班级完成情况、知识点得分、能力趋势，AI 生成学情建议
- **评测侧**：网页提交路径包含受限沙箱编译运行 C++17 代码，给出编译错误、运行时错误、超时和测试用例结果；API 提交路径仅做 AI/启发式评分，不执行沙箱测试

### 1.3 适用对象

| 角色 | 核心场景 |
|------|----------|
| 学生 | 提交 C++ 程序、查看评测反馈、完成三阶段引导学习 |
| 教师 | 创建作业、管理班级花名册、查看提交与学情趋势 |
| 开发者/研究者 | 基于 Flask + SQLAlchemy + 可替换 AI 接口扩展评测与教学功能 |

---

## 二、目录与模块职责

### 2.1 整体架构分层

项目采用经典的 Flask 分层架构。`models.py` 是路由、服务、任务三层共享的数据访问层；`tasks/` 为可选异步执行分支，路由可直接调用工具层同步执行，也可启动后台任务异步执行。

```
浏览器 (HTTP/SSE)
    ↓
routes/          路由层（8 个 Blueprint，处理 HTTP 请求）
    ├──→ services/    服务层（8 个业务服务，封装核心逻辑）
    ├──→ utils/       工具层（15+ 模块 + agents/ 多 Agent 子系统）
    ├──→ tasks/       异步任务层（可选，后台线程队列）
    │       └──→ utils/  （任务内部调用工具层执行评测/分析）
    └──→ models.py    数据模型层（18 个 db.Model，SQLAlchemy ORM，各层共享）
                ↓
          SQLite / MySQL   数据存储
```

> 注：API 提交入口（`routes/api.py`）直接同步调用 `utils/code_evaluator.py` 并写入 `models.py`，不经过 `tasks/`；网页提交入口（`routes/assignments.py`）启动 `tasks/submission_tasks.py` 后台线程异步执行。

外部依赖包括：g++（C++17 编译执行）、智谱/OpenAI LLM 服务、Redis（可选，会话存储）。

### 2.2 根目录核心文件

| 文件 | 行数级 | 职责 |
|------|--------|------|
| `app.py` | ~600 行 | **应用工厂**。`create_app()` 初始化 Flask、注册 8 个 Blueprint、配置数据库引擎、初始化异步任务与日志。模块末尾直接实例化 `app = create_app(...)` |
| `run.py` | 极小 | 开发启动入口，`python run.py` 即可启动 |
| `wsgi.py` | 极小 | 生产 WSGI 入口，暴露 `application` 对象供 Gunicorn 调用 |
| `config.py` | ~170 行 | 三套环境配置：`DevelopmentConfig` / `TestingConfig` / `ProductionConfig`，包含 30+ 配置项（数据库、AI、连接池、异步任务、安全等） |
| `models.py` | ~1500 行 | **全部数据模型**，18 个 db.Model 类的 SQLAlchemy 定义，含 `init_db()` 和 `ensure_performance_indexes()` |
| `forms.py` | ~60 行 | WTForms 表单：登录、注册、作业、提交、编辑资料、改密码 |
| `database_maintenance.py` | ~30 行 | 生产环境数据库维护脚本，强制使用 production 配置，执行建表和索引维护 |
| `gunicorn_config.py` | ~90 行 | Gunicorn 生产配置，含 worker 数量、超时、生命周期钩子 |

### 2.3 路由层（routes/）

8 个 Blueprint，按业务领域拆分：

| 模块 | 大小 | 核心职责 |
|------|------|----------|
| `auth.py` | 16KB | 登录/注册/登出、演示体验登录（`demo_login`）、教师邀请注册 |
| `main.py` | 56KB | 首页、学生/教师/管理员仪表盘、个人资料、AI 学情建议、数据导出、系统设置、关于/帮助/联系页 |
| `assignments.py` | 53KB | 作业 CRUD、代码提交、提交历史、作业分配给班级、AI 自动生成作业题 |
| `classes.py` | 29KB | 班级管理、花名册导入（Excel/CSV）、班级统计、班级码绑定 |
| `users.py` | 20KB | 用户管理、个人资料编辑、头像上传、密码修改、用户导出、教师邀请 |
| `api.py` | 66KB | **REST API 层**。代码提交、AI 代码建议、编程引导、能力分析流式推送、测试用例验证、作业格式化等 |
| `thinking.py` | **97KB** | **全项目最大文件**。三阶段引导式学习的全部路由，含阶段一思路评估、阶段二步骤验证、阶段三多 Agent 费曼对话 |
| `grades.py` | 5.5KB | 成绩册页面与 Excel 导出 |

### 2.4 服务层（services/）

| 模块 | 大小 | 核心职责 |
|------|------|----------|
| `llm_client.py` | 37KB | **LLM 统一客户端**。封装智谱/OpenAI 调用，含熔断、重试、并发控制、Singleflight 请求合并、多 provider 优先级切换 |
| `ai_evaluator.py` | 23KB | AI 评测器。五维度代码评估、AI 自动出题、能力趋势分析、知识点检测 |
| `demo_database.py` | 15KB | **演示数据隔离**。为每次公开体验创建独立临时 SQLite 数据库，退出后自动清理 |
| `demo_experience.py` | 44KB | 演示数据播种。预置演示用户、班级、作业、提交、知识点得分、能力趋势等完整模拟数据 |
| `teacher_ai_advisor.py` | 27KB | 教师 AI 学情顾问。生成班级学情建议（AI + 规则降级方案） |
| `teacher_analytics.py` | 13KB | 教师数据分析。提交趋势、作业完成矩阵、学习状态行、风险标签 |
| `course_grading.py` | 7.7KB | 课程成绩计算。综合正式提交得分 + 引导学习参与度 |
| `api_keys.py` | 3.7KB | API 密钥统一管理器 |

### 2.5 工具层（utils/）

| 模块 | 大小 | 核心职责 |
|------|------|----------|
| `code_evaluator.py` | 43KB | **代码质量评估**。启发式规则评分（基础结构/质量/复杂度/题目匹配度四维度加权），支持特定算法（冒泡/快排）特征检测，0-5 分制 |
| `llm_evaluator.py` | 49KB | LLM 深度代码评估 |
| `code_advisor.py` | 43KB | 代码建议生成 |
| `guidance_generator.py` | 30KB | 启发式编程引导，通过提问引导学生而非直接给答案 |
| `thinking_ai.py` | 62KB | **三阶段学习 AI 核心逻辑**。思路评估、步骤提示、多角色对话、辅助写代码、费曼代码修复评估、`sanitize_response()` 过滤 AI 直接输出答案 |
| `sandbox_runner.py` | 8.2KB | **C++ 编译运行沙箱**。`compile_cpp()`（15s 超时）、`run_single_test()`（5s 超时）、临时目录隔离 |
| `ability_scorer.py` | 12KB | 贝叶斯加权能力评分，跟踪 13 个 C 语言知识点 |
| `async_tasks.py` | 23KB | 异步任务队列。线程池执行、SSE 进度推送、任务去重、有界队列 |
| `sse.py` | 3.4KB | SSE 流式响应工具 |
| `prompts.py` | 6.3KB | Prompt 模板集中管理 |
| `validate_testcases.py` | 11KB | 测试用例验证与自动生成预期输出 |

### 2.6 Agent 子系统（utils/agents/）

这是阶段三"费曼教学"背后的多 Agent 协作框架，共 10 个文件、约 220KB，是项目中最复杂的子系统：

| 模块 | 职责 |
|------|------|
| `contracts.py` | 契约定义：角色枚举、消息类型、事件结构 |
| `model.py` | Agent 决策模型抽象层，封装 LLM 调用 |
| `intent.py` | 学生意图识别（提问/解释/求助等） |
| `goal.py` | 用户目标跟踪，动态更新当前学习目标 |
| `memory.py` | Agent 记忆系统。事件存储、状态快照、多 Agent 消息隔离、学生视图过滤（隐藏教师内部信号和答案工件） |
| `tools.py` | Agent 可调用工具集：代码审查、问题生成、知识点检测、代码修复建议 |
| `loop.py` | **Agent 主循环**。ReAct 模式：决策→工具执行→观察→再决策，含最大轮次限制、错误重试 |
| `coverage.py` | 学习覆盖度评估 |
| `feynman.py` | **59KB，子系统最大**。费曼教学运行时，整合所有模块实现多 Agent 对话（学生 Agent + 教师 Agent + 代码评审 Agent） |
| `orchestrator.py` | Agent 编排器，协调多 Agent 消息路由 |

### 2.7 异步任务（tasks/）

| 模块 | 职责 |
|------|------|
| `submission_tasks.py` | 代码提交异步评测：AI 基础评估（evaluate_cpp_code）→ 沙箱测试（run_test_cases，内部含 g++ 编译）→ 按测试结果覆盖分数 → 更新得分 → 刷新统计 |
| `ability_analysis.py` | 能力分析异步生成，按需触发避免重复计算 |

### 2.8 数据模型（models.py）

共 18 个 `db.Model` 类，核心实体关系：

- **User**（用户，含 usertype：学生/教师/管理员）
- **Class**（班级）↔ **StudentRoster**（花名册）
- **Assignment**（作业）↔ **TestCase**（测试用例）↔ **AssignmentKnowledgePoint**（作业知识点关联）
- **Submission**（提交记录，关联学生和作业）
- **AbilityTrend**（能力趋势，五维度按日记录）
- **KnowledgePointScore**（知识点得分）
- **ThinkingSession**（引导学习会话）↔ **ThinkingStageLog**（阶段日志）
- **AssignmentThinkingPreset**（引导学习预设）
- **TeacherAISuggestion**（教师 AI 建议）
- **InviteToken**（教师邀请令牌）
- **SystemLog** / **SystemConfig**（系统日志与配置）
- **StudentQuestion** / **CodeAdviceRequest**（学生提问与代码建议记录）

---

## 三、核心流程

### 3.1 代码提交流程（两个入口：API 同步 / 网页异步）

项目存在**两个独立的代码提交入口**，执行模式不同，需明确区分：

#### 入口 A：API 提交 `POST /api/submit`（同步）

`routes/api.py::submit_code()`（第 271 行）在请求线程内**同步执行**评测，HTTP 响应返回时已包含评分结果。

```
前端发送 JSON { code, assignment_id, language }
    ↓
POST /api/submit  →  routes/api.py → submit_code()  [第271行]
    ├── 参数校验（作业 ID、代码内容、登录态）
    ├── 创建 Submission 记录（status="pending"）[第289行]
    ├── db.session.commit() 保存获取 ID
    ├── 同步调用 utils/code_evaluator.py → evaluate_cpp_code()  [第303行]
    │     └── 启发式评分 + LLM 五维度评估（阻塞等待返回）
    ├── 更新 submission.score / feedback / status="evaluated"  [第310-312行]
    ├── 解析 AI 反馈 JSON，写入 submission.ai_feedback
    ├── 累加更新作业统计（total_score / count / average_score）
    ├── 触发能力分析刷新（trigger_analysis_if_needed）
    └── 返回 JSON：{ submission_id, score, status: "evaluated" }  [第358行]
```

**特点**：请求-响应周期内完成 AI 评分，无后台线程，无状态轮询。AI 调用耗时会直接体现在 HTTP 响应延迟上。

**评分语义**：
- **是否编译运行**：否。仅调用 `evaluate_cpp_code()` 做静态分析，不调用 g++ 编译，不执行沙箱测试
- **评分依据**：启发式规则 + LLM 五维度评估（代码结构、逻辑正确性、风格、效率、可读性），分数范围 0-5
- **`status="evaluated"` 含义**：AI/启发式评分已完成，**不代表代码经过编译或测试用例验证**
- **与网页入口的差异**：API 入口不产生 `sandbox_status` / `sandbox_passed` / `sandbox_total` 字段

#### 入口 B：网页提交 `POST /assignment/<id>/submit`（异步）

`routes/assignments.py::submit_code()`（第 483 行）通过后台线程**异步执行**评测，提交后立即重定向到等待页面。

```
学生在 submit_code.html 填写表单并提交（form.validate_on_submit）
    ↓
POST /assignment/<id>/submit  →  routes/assignments.py → submit_code()  [第483行]
    ├── 参数校验（代码长度 ≥ 10 字符）
    ├── 创建 Submission 记录（status="pending"）[第533行]
    ├── db.session.commit()
    ├── 调用 tasks/submission_tasks.py → evaluate_submission_async()  [第546行]
    │     └── 内部 threading.Thread(target=_evaluate).start()  [第291行]
    └── 立即重定向到 /submission/<id>/evaluating 等待页  [第555行]
    ↓（HTTP 响应已返回，以下在 daemon 后台线程异步执行）
_evaluate()  [submission_tasks.py 第96行]
    ├── AI 基础评估：evaluate_cpp_code() → score/feedback  [第123行]
    ├── 沙箱测试用例评判（仅当作业有测试用例时执行）：run_test_cases() → sandbox_status/passed/total  [第157-159行]
    │     └── 有用例且 total>0 时以沙箱结果覆盖 AI 分数（passed/total × 5）
    ├── submission.status = "evaluated"  [第193行，无论沙箱是否执行]
    ├── _refresh_assignment_stats() / _refresh_user_stats() 重新聚合统计
    ├── 知识点得分更新（KnowledgePointScore.update_score）
    ├── 能力分析刷新（trigger_analysis_if_needed）
    └── SystemLog.add_log("评测完成")（非 demo 模式）
    ↓
等待页 submission_evaluating.html 自动检测 status 变化，
完成后跳转到 /submission/<id> 详情页
```

**特点**：提交接口不阻塞，评测在 daemon 线程中执行；前端通过等待页面轮询或自动跳转获取结果。

**评分语义**：
- **是否编译运行**：视作业配置而定。后台线程先做 AI 评估；仅当作业配置了测试用例时，才调用 `run_test_cases()` 内部通过 g++ 编译并逐用例运行（5s 超时）
- **评分依据**：
  - 无测试用例：分数为 `evaluate_cpp_code()` 的 AI 基础分（0-5），不执行沙箱
  - 有测试用例且 `total > 0`：以沙箱通过率（passed/total × 5）覆盖 AI 分数
  - 编译错误（`sandbox_status="compile_error"`）：分数受限（代码中判断 `status=="error"` 时最高 1 分，注：sandbox_runner 实际返回 `"compile_error"`，与判断值存在不一致）
  - 沙箱异常：非 demo 模式下静默跳过，分数保持 AI 评分
- **`status="evaluated"` 含义**：评测流程已结束（AI 评估已执行），**不代表沙箱测试一定执行了**。具体编译和测试执行情况以 `sandbox_status` 等字段为准
- **沙箱字段含义**：
  - `sandbox_status=None`：作业无测试用例，未执行沙箱测试，分数为 AI 评分
  - `sandbox_status="passed"/"partial"/"failed"`：沙箱测试执行完成，分数为通过率
  - `sandbox_status="compile_error"`：编译失败，未运行测试用例
  - `sandbox_status="unavailable"`：沙箱不可用
  - `sandbox_passed` / `sandbox_total`：通过用例数 / 总用例数（无测试用例时为 None）
  - `sandbox_detail`：各用例执行详情的 JSON 字符串

#### 默认配置与队列后端差异

> **重要**：当前代码中**仅存在 thread 模式一种实现**。下表中 RQ 列描述的是未来可能的扩展方向，**当前不可通过配置启用**。代码中不存在 `SUBMISSION_EVALUATION_QUEUE_BACKEND` 配置项，也没有 RQ worker 的实现分支。

| 维度 | 默认配置（thread，已实现） | RQ 队列后端（未来方案，未实现） |
|------|---------------------------|--------------------------------|
| 实现方式 | `threading.Thread` daemon 线程 | 需额外开发 Redis Queue worker 进程，当前代码无此分支 |
| 代码位置 | `tasks/submission_tasks.py` 第 291 行 | 不存在，需新增 worker 入口与任务分发逻辑 |
| 进程隔离 | 与 Flask 主进程同进程 | （规划中）独立 worker 进程，崩溃不影响主服务 |
| 任务持久化 | 进程重启后丢失，无重试 | （规划中）需引入 Redis 持久化与失败重试机制 |
| 配置方式 | 无需配置，默认启用 | （规划中）需新增配置项并实现条件分支 |
| 当前状态 | **默认且唯一已实现路径** | **未实现**，不可通过环境变量启用 |

> **验证结论修正**：此前文档将 `/api/submit` 误描述为异步主链。经核对 `routes/api.py` 第 303 行，该入口在请求内直接同步调用 `evaluate_cpp_code()`；异步后台线程仅由网页入口 `routes/assignments.py` 第 546 行触发。`utils/async_tasks.py` 的 `AsyncTaskManager` 是另一个独立的任务队列系统，用于能力趋势分析等耗时任务，不参与代码提交评测。

### 3.2 三阶段引导式学习流程

这是项目的核心创新，入口为 `/thinking/<assignment_id>`：

**阶段一：思路描述**
- 学生用自然语言写出算法思路
- `thinking_ai.py → evaluate_description()` 评估思路完整性
- AI 生成提示（`generate_stage1_hint()`），不直接给答案

**阶段二：步骤组装**
- 学生从预设代码块中选择并排序，构造程序步骤
- `stage2_verify()` 检查步骤顺序正确性
- 生成代码预览

**阶段三：费曼教学**
- 进入 `utils/agents/feynman.py` 多 Agent 运行时
- 学生 Agent、教师 Agent、代码评审 Agent 协作
- `loop.py` ReAct 循环：学生解释代码 → Agent 追问 → 学生修正 → AI 辅助写/修代码
- `memory.py` 确保学生视图看不到教师内部推理和答案工件
- `sanitize_response()` 过滤 AI 直接输出完整答案

### 3.3 演示体验流程

```
用户点击"学生体验/教师体验"
    ↓
routes/auth.py → demo_login(role)
    ↓
services/demo_database.py → create_demo_run()  [创建独立临时SQLite]
    ↓
services/demo_experience.py → seed_demo_experience()  [播种完整模拟数据]
    ↓
切换数据库连接到临时库 → 用户操作全部写入临时库
    ↓
退出/超时 → cleanup_expired_demo_runs()  [销毁临时数据]
```

**关键设计**：每次体验完全隔离，不写入正式数据库，退出后自动清理。演示数据包含完整的用户、班级、作业、提交、知识点得分和能力趋势，确保体验真实。

---

## 四、运行与测试

### 4.1 本地运行

**环境要求**：
- Python：原始固定依赖（Flask 2.2.3 等）在 **3.10 / 3.11** 上已验证可直接运行；**3.12 / 3.13 未验证**（`ast.Str` 仅被废弃未移除，可能可运行但会触发 deprecation warning）；**3.14 已验证需升级依赖**（本次验证使用 3.14.7）
- g++（C++17 编译器，需在 PATH 中）
- 智谱或 OpenAI API 密钥（可选，不配置时 AI 功能不可用但基础功能正常）

**支持的 Python 版本**：项目 `requirements.txt` 固定依赖（Flask 2.2.3 / Werkzeug 2.2.3 / Flask-Session 0.4.0）在 **Python 3.10 / 3.11** 上已验证可直接安装运行。`ast.Str` 在 Python 3.12 中被废弃（deprecated）、在 Python 3.14 中才被移除（removed），因此：
- **Python 3.14**：原始依赖导入时报 `AttributeError: module 'ast' has no attribute 'Str'`，必须升级依赖（见下方兼容流程）
- **Python 3.12 / 3.13**：`ast.Str` 仍存在，理论上可能可直接运行，但会触发 deprecation warning；本次未实测验证，需使用者自行确认
- **Python 3.10 / 3.11**：已验证可直接运行，推荐使用

**快速开始（Python 3.10 / 3.11，原始依赖，已验证可直接运行）**：

```bash
# 1. 创建虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 2. 安装依赖（原始固定版本，无需额外升级）
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env   # Windows: Copy-Item .env.example .env
# 编辑 .env：开发环境注释掉 DATABASE_URL 即可使用 SQLite

# 4. 启动
python run.py
# 打开 http://127.0.0.1:5000/login
```

**Python 3.14 兼容验证流程（临时兼容方案，非项目官方支持配置，仅适用于 Python 3.14）**：

由于 Python 3.14 已移除 `ast.Str`（3.12 中仅废弃、3.14 中正式移除），原始固定依赖无法直接导入。以下为本次分析在 Python 3.14.7 上实际验证时使用的覆盖安装顺序，仅用于在 Python 3.14 上完成本地启动验证：

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows

# 2. 先安装原始依赖（安装 Flask 2.2.3 / Werkzeug 2.2.3 / Flask-Session 0.4.0）
pip install -r requirements.txt

# 3. 覆盖当前虚拟环境中的三个依赖版本（不修改 requirements.txt 文件；重建环境需重复此步骤）
pip install Flask==2.3.3 Werkzeug==2.3.7 Flask-Session==0.8.0

# 4. 配置 .env 并启动
python run.py
```

> 注意：
> - 上述升级仅为在 **Python 3.14** 上完成本地验证的临时手段，不属于项目官方支持的依赖组合
> - 升级后未运行完整 pytest 套件，仅验证了应用启动和基础页面可访问
> - **已验证可运行**：Python 3.10 / 3.11 + 原始依赖；Python 3.14 + 升级后依赖（仅启动验证）
> - **未验证**：Python 3.12 / 3.13（ast.Str 仍存在但已废弃，可能可运行但需实测）
> - **项目正式支持范围**：README 未明确声明，建议以 Python 3.10 / 3.11 + 原始依赖为准

**实际运行验证**：在 Windows 11 + Python 3.14.7 环境下，按上述 Python 3.14 兼容流程完成依赖安装与 `.env` 配置后，`python run.py` 成功启动，`/login` 返回 HTTP 200（页面 21KB），`/about`、`/help`、`/contact` 均正常返回，`/` 未登录时正确 302 重定向。

### 4.2 运行测试

```bash
python -m pytest tests -q
```

测试目录 `tests/` 包含 43 个 `test_*.py` 文件（另有 1 个 `demo_test_utils.py` 工具文件），覆盖：

| 测试领域 | 代表文件 | 覆盖内容 |
|----------|----------|----------|
| 基础功能 | `test_app.py`, `test_account_basics.py` | 应用启动、账户基本操作 |
| 演示体验 | `test_demo_*.py`（10 个文件） | 演示登录、数据库隔离、数据播种、AI刷新、引导学习 |
| 阶段三 Agent | `test_stage3_*.py`（15 个文件） | Agent循环、记忆、工具、论坛模式、目标跟踪、覆盖度 |
| 班级管理 | `test_class_*.py`, `test_roster_features.py` | 班级层级、绑定、花名册 |
| 成绩 | `test_course_grading.py`, `test_grades_route.py` | 成绩计算、成绩页路由 |
| AI/SSE | `test_ai_sse_routes.py`, `test_llm_client.py` | AI流式响应、LLM客户端韧性 |
| 教师端 | `test_teacher_analytics.py`, `test_teacher_ai_suggestions.py` | 数据分析、AI建议 |

**注意**：涉及 C++ 评测的测试需要 g++；涉及真实 AI 服务的测试需要相应环境变量。

### 4.3 关键配置项

| 配置 | 作用 | 开发环境建议 |
|------|------|-------------|
| `FLASK_CONFIG` | 环境选择 | `development` |
| `DATABASE_URL` | 数据库连接 | 留空使用 SQLite |
| `SECRET_KEY` | 会话签名密钥 | 必须设置随机值 |
| `ZHIPU_API_KEY` / `OPENAI_API_KEY` | AI 服务密钥 | 至少配一个才能用 AI 功能 |
| `AUTO_INIT_DB` | 启动时自动建表 | 开发环境设为 `1` |
| `ASYNC_TASKS_ENABLED` | 异步任务开关 | 开发环境设为 `1` |

---

## 五、风险与未知项

### 5.1 已识别风险

**1. 代码执行安全边界**
- README 明确声明：当前沙箱"主要依靠应用层限制，适合课程内的受控实验，不应当被当作完整的操作系统级安全沙箱"
- 学生代码通过 `subprocess` 调用 g++ 编译并运行，仅有超时和输出长度限制，没有容器/虚拟机隔离
- **风险**：公网部署时恶意代码可能导致资源耗尽或系统入侵
- **建议**：公网部署必须增加 Docker 容器隔离、低权限账户、网络限制和资源配额

**2. AI 输出可靠性**
- 项目多处依赖 AI 生成内容（代码评估、学情建议、自动出题、引导对话）
- 虽然有 `sanitize_response()` 过滤和提示词约束，但 README 承认"AI 仍可能出错"
- `ai_evaluator.py` 中有大量 JSON 解析容错和正则回退逻辑，侧面说明 AI 返回格式不稳定是常见问题

**3. Python 版本兼容性**
- `requirements.txt` 固定了 `Flask==2.2.3`、`Werkzeug==2.2.3`、`Flask-Session==0.4.0`
- `ast.Str` 在 Python 3.12 中被废弃（deprecated），在 Python 3.14 中才被移除（removed）
- **已验证**：Python 3.10 / 3.11 + 原始依赖可正常运行；Python 3.14.7 上原始依赖报 `AttributeError: module 'ast' has no attribute 'Str'`，升级 Flask 2.3.3 / Werkzeug 2.3.7 / Flask-Session 0.8.0 后可启动（仅启动验证，未跑完整测试）
- **未验证**：Python 3.12 / 3.13，`ast.Str` 仍存在但已废弃，可能可直接运行但会触发 deprecation warning，需实测确认
- **风险**：项目未明确声明支持的 Python 版本范围；Python 3.14 用户必须手动升级依赖才能运行；3.12/3.13 兼容性未知
- **建议**：项目应升级最低依赖版本以兼容 Python 3.14，或在 README 中明确声明已验证支持的 Python 版本（3.10 / 3.11），并将 3.12+ 标记为未验证/需额外配置

**4. 单文件过大**
- `routes/thinking.py` 97KB、`utils/thinking_ai.py` 62KB、`utils/agents/feynman.py` 59KB、`models.py` 62KB
- 大文件增加维护难度，核心逻辑（三阶段学习）集中在少数文件中

**5. 异步任务架构局限**
- `utils/async_tasks.py` 使用进程内线程池，README 注明"多 worker 会各自拥有一套队列"
- 生产环境用 Gunicorn 多 worker 时，任务状态不共享，可能导致重复执行

**6. 演示数据清理依赖超时**
- 演示会话的清理依赖空闲超时和最长生命周期，如果服务异常退出，临时数据库可能残留

### 5.2 未知项（需进一步确认）

1. **生产环境实际部署规模**：`PERFORMANCE_CAPACITY.md` 提到性能容量评估，但未看到实际压测数据，不确定单实例支持的并发用户数
2. **AI 服务成本**：三阶段学习和代码评估都调用 LLM，未看到 token 用量统计和成本控制机制
3. **数据库迁移方案**：项目使用 Flask-Migrate，但未看到 `migrations/` 目录，生产环境 schema 变更如何管理尚不明确
4. **移动端适配**：模板使用 Bootstrap 5，理论上响应式，但未实际验证移动端体验
5. `utils/agents/` 子系统的 `feynman.py` 和 `loop.py` 复杂度较高，完整的 Agent 状态机转换逻辑需要更深入的代码阅读才能完全掌握

---

## 六、个人理解

### 6.1 项目的核心价值

CodeSense 最有价值的设计不是"又一个 OJ"，而是**把学习过程本身产品化**。传统 OJ 只记录"提交-结果"这个二元状态，而 CodeSense 通过三阶段引导式学习，把学生从"看到题目"到"理解代码"的中间过程全部结构化记录下来——思路描述、步骤选择、对话追问、代码修复——这些数据不仅能给学生更精准的反馈，也能让教师看到"学生到底卡在哪一步"。

`utils/agents/memory.py` 中的"学生视图过滤"设计值得注意：教师 Agent 的内部推理、代码审查的中间结果、答案工件都对学生不可见，这保证了费曼教学中"学生是教的人，AI 是被教的人"这一角色定位不被破坏。

### 6.2 架构上的亮点

1. **LLM 客户端的企业级韧性设计**（`services/llm_client.py`）：熔断、重试、并发控制、Singleflight、多 provider 切换——这不是简单的 API 调用封装，而是考虑了生产环境 AI 服务不稳定的完整方案。

2. **演示数据隔离**（`services/demo_database.py`）：每次体验创建独立 SQLite 数据库，既保证了演示数据的真实性，又不会污染正式数据库，是一个很巧妙的设计。

3. **启发式评分作为 AI 的降级方案**（`utils/code_evaluator.py`）：当 AI 不可用时，基于规则的启发式评分仍能给出基本反馈，保证了核心功能的可用性。

### 6.3 可以改进的方向

1. **依赖版本升级**：将 Flask/Werkzeug/Flask-Session 升级到兼容 Python 3.14 的版本（当前固定版本在 3.14 上因 `ast.Str` 移除而报错），降低新用户部署门槛
2. **大文件拆分**：`thinking.py` 和 `thinking_ai.py` 可以按阶段拆分为多个模块
3. **沙箱容器化**：用 Docker 替代 subprocess，提升公网部署安全性
4. **异步任务外部化**：用 Celery/RQ 替代进程内线程池，支持多 worker 部署
5. **增加集成测试**：当前测试以单元测试为主，缺少端到端的完整流程测试（提交代码→评测→查看结果）

### 6.4 总结

CodeSense 是一个工程完成度较高的教学平台项目，从 README 文档、配置管理、错误处理到测试覆盖都比较规范。它的差异化在于"三阶段引导式学习 + 多 Agent 费曼教学"，这部分代码复杂度最高但也最有价值。对于高校编程教学场景，它提供了比传统 OJ 更丰富的学习数据和反馈机制，是一个有实际教学应用潜力的项目。

---

*本文档基于 CodeSense v1.0.0 (main @ 1d81744) 源码分析与实际运行验证撰写。*
