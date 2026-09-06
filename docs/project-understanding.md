# CodeSense 酷森思 — 项目接管理解文档

> 本文档基于对公开仓库代码的实际阅读、本地安装运行和测试验证整理而成，用于项目接管前的基础理解。仅作文档交付，不修改任何业务逻辑。

---

## 1. 项目定位、主要用户与核心问题

### 1.1 项目定位

CodeSense（酷森思）是一个**面向高校编程教学的代码评测与学习平台**，当前版本 v1.0.0（Standard Edition）。它不只是一个传统 OJ（Online Judge），而是把"代码提交—受限执行—AI 辅导—分阶段练习—学情记录"整合在同一条流程里，目标是让学生不仅知道 AC 或 WA，还能理解问题出在哪里、如何改进。

技术栈以 Python + Flask 2.2.3 为核心，数据层支持 SQLite（开发/演示）和 MySQL（生产），前端为 Jinja2 模板 + Bootstrap + Monaco Editor，代码执行依赖系统 g++（C++17）。

### 1.2 主要用户

| 角色 | 核心诉求 | 系统中的对应能力 |
|------|----------|------------------|
| **学生** | 写代码、知道错在哪、逐步学会解题 | 代码提交与评测、三阶段引导式学习（思路描述→步骤组装→费曼教学）、AI 代码建议、能力画像 |
| **教师** | 发布作业、管理班级、掌握学情 | 作业与测试用例管理、班级与花名册、提交完成矩阵、知识点与五维能力趋势、AI 学情建议 |
| **管理员** | 系统配置与用户管理 | 用户管理、系统配置（SystemConfig 表）、邀请 Token、全局日志 |
| **开发者/研究者** | 扩展评测与教学流程 | Flask 蓝图结构、可替换 AI 接口、启发式规则评估、异步任务与 SSE |

### 1.3 核心问题

项目要解决的核心矛盾可以概括为三点：

1. **传统 OJ 反馈粒度太粗**：学生只能看到通过/不通过，不知道是算法思路错、实现有 bug、边界条件没处理，还是调试能力不足。CodeSense 通过沙箱运行证据 + AI 反馈 + 三阶段引导来细化反馈。
2. **教师难以归纳班级共性问题**：面对大量提交记录，人工归纳每个班级反复出现的知识点盲区成本很高。CodeSense 通过能力画像（五维能力 + 13 个 C 语言知识点贝叶斯评分）和教师端 AI 建议来自动化这一过程。
3. **AI 直接给答案会削弱学习效果**：如果 AI 直接输出完整代码，学生可能复制粘贴而不理解。CodeSense 通过提示词约束、`sanitize_response` 过滤器和三阶段引导式学习（先写思路、再组装步骤、最后用自己的话解释）来尽量避免 AI 直接给答案。

---

## 2. 目录结构与主要模块职责

### 2.1 顶层结构

```
CodeSense/
├── app.py                  # 应用工厂 create_app()，蓝图注册、中间件、会话、日志、启动期初始化
├── run.py                  # 开发服务器入口（固定 0.0.0.0:5000）
├── wsgi.py                 # 生产 WSGI 入口（gunicorn 使用）
├── config.py               # 三环境配置：DevelopmentConfig / TestingConfig / ProductionConfig
├── models.py               # 全部 SQLAlchemy 数据模型（约 15 张表）+ init_db + 索引维护
├── forms.py                # Flask-WTF 表单定义
├── database_maintenance.py # 生产环境一次性建表/迁移脚本
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板
├── routes/                 # Flask 蓝图（HTTP 路由层）
├── services/               # 业务服务层（AI、学情、演示隔离等）
├── utils/                  # 工具与核心引擎（沙箱、异步任务、能力评分等）
├── tasks/                  # 后台任务定义（提交处理、能力分析）
├── templates/              # Jinja2 模板
├── static/                 # 静态资源（CSS/JS/图片）
├── tests/                  # pytest 测试套件（40+ 测试文件）
├── uploads/                # 用户上传文件目录
└── docs/                   # 项目文档（含本文档）
```

### 2.2 路由层（routes/）— 8 个蓝图

| 蓝图文件 | 前缀/职责 | 关键端点 |
|----------|-----------|----------|
| `auth.py` | 登录、登出、注册、演示体验入口 | `/login`, `/logout`, `/register`, 演示登录 |
| `main.py` | 首页、关于、帮助等公共页面 | `/`, `/about`, `/help` |
| `assignments.py` | 作业 CRUD、作业详情、提交列表 | `/assignments`, `/assignment/<id>` |
| `users.py` | 用户资料、密码修改、头像上传 | `/profile`, `/change_password` |
| `api.py` | REST API：代码提交、AI 建议、编程引导、能力分析 SSE | `/api/submit`, `/api/code_advice`, `/api/stream/ability-analysis` |
| `classes.py` | 教师端班级管理、花名册、绑定码 | `/classes`, `/classes/<id>` |
| `thinking.py` | 三阶段引导式学习页面与 API | `/thinking/<id>`, `/thinking/api/stage[1-3]/*` |
| `grades.py` | 成绩与评分相关路由 | `/grades/*` |

### 2.3 服务层（services/）

| 文件 | 职责 |
|------|------|
| `api_keys.py` | 统一 API 密钥管理器，封装智谱/OpenAI 密钥的读取与可用性判断 |
| `llm_client.py` | LLM 客户端，支持多 Provider（智谱/OpenAI）、熔断、重试、并发控制、singleflight 请求合并 |
| `ai_evaluator.py` | AI 评估服务，调用 LLM 对代码进行多维度评估 |
| `demo_database.py` | **公开体验数据库隔离核心**：为每次演示创建独立临时 SQLite，请求级别切换数据库引擎，过期清理 |
| `demo_experience.py` | 演示体验数据播种与流程控制 |
| `teacher_analytics.py` | 教师端学情分析：班级统计、知识点趋势、完成矩阵 |
| `teacher_ai_advisor.py` | 教师端 AI 个性化建议生成（重点学生、弱势知识点、推荐补练） |
| `course_grading.py` | 课程评分与成绩计算 |

### 2.4 工具与核心引擎（utils/）

| 文件 | 职责 |
|------|------|
| `sandbox_runner.py` | **C++ 代码执行沙箱**：g++ 编译（15s 超时）、逐用例运行（5s 超时）、输出标准化与比对、临时目录清理 |
| `async_tasks.py` | 进程内异步任务队列（ThreadPool），提交后异步处理与 SSE 流式进度推送 |
| `ability_scorer.py` | 贝叶斯加权能力追踪，覆盖 13 个 C 语言知识点，计算五维能力得分 |
| `code_evaluator.py` | 代码评估器（启发式规则 + 已配置 AI 服务，不依赖本地训练模型） |
| `code_advisor.py` | 代码建议与反馈生成 |
| `guidance_generator.py` | 启发式引导提示词生成，通过提问引导学生而非直接给答案 |
| `llm_evaluator.py` | LLM 评估封装 |
| `thinking_ai.py` | 三阶段学习的 AI 交互逻辑 |
| `agents/` | 阶段三费曼教学的多 Agent 系统（教师 Agent、学生 Agent、论坛 Agent 等） |
| `sse.py` | Server-Sent Events 流式响应工具 |
| `prompts.py` | AI 交互提示词模板 |
| `validate_testcases.py` | 测试用例校验 |
| `markdown_formatter.py` | Markdown 渲染与格式化 |
| `maturity_calculator.py` | 成熟度计算 |
| `auth.py` | 认证辅助工具 |

### 2.5 数据模型（models.py）

核心表约 15 张，可分为几组：

- **用户与组织**：`users`（学生/教师/管理员，主键为 student_id）、`classes`（班级，含教师绑定码）、`student_rosters`（教师导入的花名册）
- **作业与评测**：`assignments`（作业，含目标班级、难度、截止日期）、`test_cases`（测试用例，含公开/隐藏）、`submissions`（提交记录，含沙箱结果与 AI 反馈）
- **引导式学习**：`assignment_thinking_presets`（AI 预设数据：标准答案、关键步骤、代码块、噪声块、费曼难度配置）、`thinking_sessions`（一次三阶段学习过程）、`thinking_stage_logs`（交互过程日志）
- **能力与学情**：`ability_trends`（学生能力趋势缓存，Markdown + JSON）、`knowledge_point_scores`（13 个知识点贝叶斯评分）、`assignment_knowledge_points`（作业知识点标签）
- **系统与辅助**：`system_logs`（活动日志）、`system_config`（系统配置键值对，含 30s 进程内缓存）、`invite_tokens`（教师邀请 Token，24h 过期单次使用）、`student_questions`（学生提问记录）、`code_advice_requests`（代码建议请求记录）、`teacher_ai_suggestions`（教师端 AI 建议缓存）

---

## 3. 核心运行流程与关键调用链

### 3.1 应用启动流程

```
run.py / wsgi.py
  └─ app.create_app(config_name)
       ├─ 加载配置（config.py，development/testing/production）
       ├─ 配置反向代理头（ProxyFix，生产环境信任 1 跳 Nginx）
       ├─ 配置数据库引擎（SQLite: check_same_thread=False + 15s busy timeout；MySQL: 连接池）
       ├─ 会话后端：优先 Redis，连接失败降级为文件系统（flask_session/）
       ├─ Cookie 安全配置（生产默认 Secure Cookie）
       ├─ 初始化日志（app.log 按日轮转、error.log 按大小轮转、access.log 可开关）
       ├─ db.init_app(app)
       ├─ 注册蓝图（auth/main/assignments/users/api/classes/thinking/grades）
       ├─ 注册 before_request：演示数据库切换 + 单点登录校验
       ├─ 注册 after_request：访问日志 + 慢请求统计 + 可选 gzip 压缩
       ├─ 注册健康探针：/healthz（存活）、/readyz（数据库就绪）
       ├─ 启动期数据库初始化（create_all + 列迁移 + 索引维护 + 默认配置 + 班级绑定码）
       ├─ 启动期清理过期演示临时库
       └─ 初始化异步任务系统（进程内 ThreadPool，可配置关闭）
```

### 3.2 代码提交与评测流程

这是系统最核心的数据流：

```
学生在编辑器写代码
  │
  ▼
POST /api/submit (routes/api.py)
  │  1. 校验登录与作业权限
  │  2. 创建 Submission 记录（status=pending）
  │  3. 提交到异步任务队列
  │
  ▼
utils/async_tasks.py（ThreadPool 异步执行）
  │
  ▼
tasks/submission_tasks.py
  │  1. 从作业加载测试用例（test_cases 表）
  │  2. 调用 utils/sandbox_runner.run_test_cases()
  │
  ▼
utils/sandbox_runner.py
  │  ├─ _find_compiler()：查找 g++（PATH + Windows 常见路径）
  │  ├─ compile_cpp()：写入 solution.cpp → g++ -std=c++17 -O2 -Wall 编译（15s 超时）
  │  │     └─ 编译失败 → 返回 compile_error
  │  └─ 逐用例 run_single_test()：subprocess 运行（5s 超时，注入编译器 PATH 解决 DLL 依赖）
  │        ├─ 输出截断至 4096 字符
  │        ├─ _normalize_output()：统一换行、去行尾空白、去末尾空行
  │        └─ 与期望输出比对 → passed/failed
  │
  ▼
更新 Submission 记录
  │  ├─ sandbox_status: passed/partial/failed/compile_error/unavailable
  │  ├─ sandbox_passed / sandbox_total
  │  ├─ sandbox_detail（JSON：每个用例的实际输出、错误、耗时）
  │  ├─ score（0-5 分，按通过比例计算）
  │  └─ status: evaluated
  │
  ▼
AI 评估（可选，需配置 API 密钥）
  │  ├─ services/ai_evaluator.py → services/llm_client.py
  │  ├─ 五维能力评分（algorithm/style/functionality/efficiency/readability）
  │  └─ 结果存入 Submission.ai_feedback（JSON）
  │
  ▼
能力画像更新
  │  ├─ utils/ability_scorer.py：13 个知识点贝叶斯加权更新
  │  ├─ 更新 User.user_ascore / submit_count
  │  └─ 标记 AbilityTrend 为 outdated（有新提交需重新分析）
  │
  ▼
SSE 流式推送结果给前端（/api/stream/...）
```

### 3.3 三阶段引导式学习流程

这是 CodeSense 区别于普通 OJ 的核心教学流程：

```
学生进入 /thinking/<assignment_id>
  │
  ├─ 阶段一：思路描述
  │   ├─ 学生用自然语言写出算法思路
  │   ├─ POST /thinking/api/stage1/submit
  │   ├─ 系统与 AssignmentThinkingPreset.algorithm_summary（AI 预设的标准算法简述）比对
  │   ├─ 给出思路匹配度评分（0-100）和提示
  │   └─ 学生可多次请求提示（stage1_hint_count 计数）
  │
  ├─ 阶段二：步骤组装
  │   ├─ 系统展示预设的代码块（code_blocks）和噪声块（noise_blocks）
  │   ├─ 学生拖拽/选择代码块，按正确顺序组装
  │   ├─ POST /thinking/api/stage2/verify
  │   ├─ 系统检查顺序正确性，生成代码预览
  │   └─ 也支持逐步选择/填空题（quiz_steps）
  │
  └─ 阶段三：费曼教学
      ├─ 学生向对话中的 AI 角色解释程序
      ├─ POST /thinking/api/stage3/chat
      ├─ 多 Agent 系统（utils/agents/）：
      │   ├─ 教师 Agent：追问、检查理解、纠正错误
      │   ├─ "坏学生" Agent：模拟学生常见误解
      │   └─ 论坛 Agent：讨论式交互
      ├─ AI 在追问和修正中检查学生是否真正理解
      └─ 完成后标记 stage3_completed，记录总用时
```

所有交互过程记录在 `thinking_stage_logs` 表（event_type: chat/hint_request/block_move/stage_pass 等），供教师查看学习过程。

### 3.4 公开体验（Demo）数据库隔离流程

这是一个设计精巧的特性，确保公开体验用户的数据完全隔离：

```
访客点击"学生体验"/"教师体验"入口
  │
  ▼
routes/auth.py 演示登录
  │  ├─ 生成随机会话 ID
  │  ├─ 创建独立临时 SQLite 数据库文件（instance/demo_*.db）
  │  ├─ 在临时库中播种演示数据（用户、班级、作业、提交、知识点画像）
  │  └─ 会话绑定临时库路径
  │
  ▼
每次请求 before_request（app.py check_single_session）
  │  └─ services/demo_database.activate_demo_request_database()
  │       ├─ 检查当前会话是否为演示会话
  │       ├─ 若是，将 SQLAlchemy session 的 bind 切换到临时库引擎
  │       │   （通过自定义 CodeSenseSession.get_bind() 实现请求级别路由）
  │       └─ 若临时库已失效，清除 demo 身份，绝不回退到正式库
  │
  ▼
请求处理完成 → 所有读写都在临时库中，与正式业务数据库完全隔离
  │
  ▼
退出体验 / 会话超时 / 服务启动时清理
  └─ cleanup_expired_demo_runs()：删除临时库文件和旁路文件
```

关键技术点：自定义 `CodeSenseSession` 继承 `FlaskSQLAlchemySession`，重写 `get_bind()` 方法，在请求级别动态切换数据库引擎，而不需要修改应用配置。这是一种优雅的多租户隔离实现。

### 3.5 单点登录校验

```
用户登录成功
  │  └─ 生成 current_session_id，写入 User 表和 Flask session
  │
每次请求 before_request
  │  ├─ 若 current_user 已登录且非演示用户
  │  ├─ 比较 session['current_session_id'] 与数据库中 User.current_session_id
  │  └─ 若不一致 → 说明账号在别处登录 → 强制 logout + 提示"账号已在其他地方登录"
```

---

## 4. 安装、运行与测试记录

### 4.1 环境

- **操作系统**：Windows 11
- **Python**：3.10.1（系统通过 py launcher 提供；默认 Python 3.14 与 Flask 2.2.3 等老依赖不兼容，故选用 3.10）
- **C++ 编译器**：MinGW-w64 g++ 16.1.0（通过 winget 安装 WinLibs POSIX UCRT 版本）
- **数据库**：SQLite（开发模式，未配置 DATABASE_URL）
- **Redis**：未安装，会话自动降级为文件系统
- **AI 密钥**：未配置，AI 相关功能不可用（基础功能正常）

### 4.2 安装步骤与结果

| 步骤 | 命令/操作 | 结果 |
|------|-----------|------|
| 1. 创建虚拟环境 | `py -3.10 -m venv .venv` | ✅ 成功 |
| 2. 安装依赖 | `pip install -r requirements.txt` | ✅ 全部安装成功（Flask 2.2.3、SQLAlchemy、numpy、pandas、openai、zhipuai、redis 等） |
| 3. 安装 g++ | `winget install BrechtSanders.WinLibs.POSIX.UCRT` | ✅ g++ 16.1.0，加入用户 PATH |
| 4. 配置环境变量 | 复制 `.env.example` 为 `.env`，注释 DATABASE_URL（SQLite 模式），生成随机 SECRET_KEY，AI 密钥留空 | ✅ 完成 |
| 5. 初始化数据库 | `python database_maintenance.py`（FLASK_CONFIG=development） | ✅ SQLite 数据库创建，表结构完整，默认系统配置播种 |
| 6. 启动开发服务 | `python run.py` | ✅ 服务运行在 http://127.0.0.1:5000 |

### 4.3 运行验证

- **登录页**：`GET /login` → HTTP 200，页面大小 21850 字节 ✅
- **根路径**：`GET /` → HTTP 302（重定向到登录页，符合预期）✅
- **健康探针**：`/healthz` 返回 `{"status":"ok"}` ✅
- **服务稳定性**：持续运行无崩溃，日志正常写入 `logs/app.log` ✅

### 4.4 测试结果

运行了核心测试子集（完整测试套件 40+ 文件，部分依赖 AI 服务/Redis，未全部运行）：

| 测试文件 | 结果 | 说明 |
|----------|------|------|
| `tests/test_app.py` | 3 passed | 首页、登录、管理员权限校验 |
| `tests/test_account_basics.py` | 3 passed | 邮箱登录、密码修改、资料更新 |
| `tests/test_sandbox_features.py` | 3 passed | 沙箱登录流程、演示数据创建（验证 g++ 集成） |
| **合计** | **9 passed** | 全部通过，无失败 |

测试中出现的警告（不影响功能）：
- `Flask-Session` 的 `session_cookie_name` 弃用警告（Flask 2.3 迁移问题）
- `SQLAlchemy` 的 `Query.get()` 弃用警告（SQLAlchemy 2.0 迁移问题，代码中大量使用 `User.query.get()`）
- SQLite 外键依赖循环警告（classes 与 users 之间的循环外键）

---

## 5. 风险、疑问与待确认事项

### 5.1 安全风险

1. **代码执行沙箱不是 OS 级隔离**：当前 `sandbox_runner.py` 仅依靠应用层限制（编译/运行超时、输出长度限制、临时目录），没有容器/虚拟机隔离、低权限账户、网络限制和资源配额。README 明确指出"不应当被当作完整的操作系统级安全沙箱"。**公网部署必须增加容器或虚拟机级隔离**，否则恶意代码可能读取文件、访问网络或消耗资源。
2. **AI 输出可能不准确**：提示词约束和 `sanitize_response` 过滤器不能完全避免 AI 给出错误信息或直接输出完整代码。最终结果必须以程序评测和教师判断为准。
3. **SECRET_KEY 管理**：开发环境若未设置 SECRET_KEY 会自动生成临时密钥（每次重启失效，导致会话失效）。生产环境必须设置强随机密钥。
4. **演示体验数据隔离**：虽然设计了临时 SQLite 隔离，但如果 `CodeSenseSession.get_bind()` 切换逻辑有漏洞，演示数据可能泄漏到正式库。需要重点测试边界情况。

### 5.2 架构与运维风险

5. **进程内异步任务在多 worker 生产环境会重复**：`async_tasks.py` 使用进程内 ThreadPool，每个 Gunicorn worker 各自拥有一套任务队列和预扫描线程。生产环境多 worker 时可能重复执行任务。README 建议改用 Celery/RQ 等独立队列。
6. **gunicorn 20.1.0 不支持 Windows**：`requirements.txt` 固定了 gunicorn 20.1.0，它依赖 `fcntl` 等 Unix 特性，在 Windows 上无法运行。开发环境用 `run.py`（Flask 内置服务器），生产部署需 Linux。
7. **SQLite 并发限制**：开发/演示使用 SQLite，虽然设置了 15s busy timeout，但高并发写入仍可能出现"database is locked"。生产环境必须用 MySQL。
8. **文件系统会话的 I/O 瓶颈**：Redis 不可用时降级为文件系统会话，高并发时磁盘 I/O 和文件锁可能成为瓶颈。

### 5.3 代码质量与技术债务

9. **SQLAlchemy 2.0 弃用警告**：代码中大量使用 `Model.query.get()`（已在 SQLAlchemy 2.0 中标记为 legacy），应迁移到 `db.session.get(Model, id)`。测试中出现大量此类警告。
10. **Flask-Session 弃用警告**：`app.session_cookie_name` 已弃用，应使用 `app.config['SESSION_COOKIE_NAME']`。
11. **版本号不一致**：`app.py` 头部注释写 `版本: v0.2.0`，而 README 和系统配置写 `v1.0.0`。需要统一。
12. **`run.py` 硬编码端口**：`run.py` 固定 `host='0.0.0.0', port=5000`，忽略 `.env` 中的 `PORT` 和 `HOST` 配置。而 `app.py` 的 `__main__` 块会读取环境变量。两个入口行为不一致。
13. **外键循环依赖**：`classes.teacher_id` 引用 `users.student_id`，`users.class_id` 引用 `classes.id`，形成循环外键。SQLite 不支持 ALTER TABLE 删表时的依赖排序，测试中出现警告。

### 5.4 待确认事项

14. **AI Provider 模型配置**：`.env.example` 中 `ZHIPU_MODEL='glm-4.5-flash'`，需确认该模型是否为智谱当前可用模型名称（智谱模型命名可能已更新）。
15. **完整测试套件通过率**：仅运行了 9 个核心测试，完整 40+ 测试文件的通过率未知。部分测试依赖真实 AI 服务和 Redis，可能需要 mock 或特殊配置。
16. **生产部署验证**：`DEPLOYMENT.md` 描述了 Linux + Gunicorn + Systemd + Nginx + HTTPS + MySQL + Redis 的完整部署流程，但未在实际生产环境验证。
17. **阶段三多 Agent 系统的稳定性**：`utils/agents/` 包含教师 Agent、学生 Agent、论坛 Agent 等多个子模块，交互逻辑复杂，需确认在无 AI 密钥时的降级行为和异常处理。
18. **数据迁移策略**：`init_db()` 中的列迁移是硬编码的 ALTER TABLE 语句（`column_migrations` 字典），新增表结构变化时需要手动维护。未使用 Flask-Migrate/Alembic 的自动迁移（虽然 requirements 中有 Flask-Migrate）。

---

## 6. 整体架构理解（个人总结）

用自己的话来概括，CodeSense 的架构可以理解为**"一个以 Flask 为骨架、以代码沙箱为执行核心、以 AI 为教学辅助、以数据隔离为安全边界的教学评测一体化系统"**。

从分层角度看：

- **表现层**是传统的服务端渲染（Jinja2 + Bootstrap），不是前后端分离。Monaco Editor 提供代码编辑体验，Chart.js 做学情可视化，SSE 做异步进度推送。这种架构的好处是开发简单、SEO 友好，适合教学工具这种交互不算极度复杂的场景。
- **路由层**用 8 个蓝图做了清晰的职责拆分，`api.py` 专门处理 AJAX/REST 请求，`thinking.py` 独立处理三阶段学习，这种模块化设计使得功能扩展不需要改动核心文件。
- **服务层**是业务逻辑的核心，其中 `demo_database.py` 的请求级数据库切换是整个系统最精巧的设计——通过自定义 SQLAlchemy Session 的 `get_bind()`，在不修改应用配置的前提下实现了多租户数据隔离。这比为每个演示用户创建独立 Flask 应用实例要轻量得多。
- **引擎层**有两个核心：`sandbox_runner.py`（代码执行）和 `ability_scorer.py`（能力评分）。沙箱是"应用级"的——靠超时和输出截断来限制，而不是真正的容器隔离，这是当前最大的安全短板。能力评分用贝叶斯加权更新 13 个知识点，配合五维能力（算法/风格/功能/效率/可读性），形成了比"分数"更丰富的学情画像。
- **异步层**是进程内 ThreadPool + SSE，提交代码后立即返回，后台编译运行，结果通过 SSE 推给前端。这种设计避免了 HTTP 请求阻塞在编译上，但在多 worker 生产环境会有重复执行的问题。
- **数据层**用 SQLAlchemy ORM，开发用 SQLite、生产用 MySQL。模型设计比较完整，从用户、班级、作业、提交到引导式学习的预设/会话/日志，再到能力趋势和知识点评分，覆盖了教学流程的各个环节。`system_config` 表做了运行时可配置的系统参数，带 30s 进程内缓存。

从数据流角度看，最核心的一条链是**"学生写代码 → 提交 → 沙箱编译运行 → 测试用例比对 → AI 评估 → 能力画像更新 → 教师端学情展示"**。这条链上的每个环节都有明确的职责和数据结构，AI 是可插拔的（没有密钥时沙箱评测和基础功能仍然可用），这使得系统在无 AI 环境下也能作为一个基础 OJ 运行。

从教学理念角度看，三阶段引导式学习（思路描述→步骤组装→费曼教学）是这个项目的灵魂。它不是让学生直接写代码然后看对错，而是先让学生用自然语言表达思路（检验是否理解问题），再通过代码块组装降低入门门槛（检验是否掌握程序结构），最后通过向 AI 解释程序来深化理解（费曼学习法）。这种设计体现了"过程性评价"而非"结果性评价"的教学理念。

总的来说，CodeSense 是一个功能完整、设计用心的教学平台代码库。它的优势在于教学流程设计的完整性和数据隔离的精巧实现；主要短板在于代码执行沙箱的安全性不足、技术栈版本偏老（Flask 2.2.3 + SQLAlchemy 2.0 混用导致大量弃用警告）、以及生产环境的异步任务架构需要升级。接管后优先关注的应该是**沙箱安全加固**和**技术债务清理**，其次是**完整测试覆盖**和**生产部署验证**。

---

## 附录：验证环境与工具

- **AI 辅助工具**：豆包（Doubao）代码理解与文档生成
- **查阅的核心文件**：`README.md`、`app.py`、`config.py`、`models.py`、`utils/sandbox_runner.py`、`requirements.txt`、`.env.example`、`AGENTS.md`、`database_maintenance.py`、`run.py`、`routes/`（8 个蓝图）、`services/`（9 个服务）、`utils/`（核心引擎）
- **执行的验证命令**：
  - `py -3.10 -m venv .venv`（创建虚拟环境）
  - `pip install -r requirements.txt`（安装依赖）
  - `python database_maintenance.py`（初始化数据库）
  - `python run.py`（启动开发服务）
  - `curl http://127.0.0.1:5000/login`（验证服务）
  - `python -m pytest tests/test_app.py tests/test_account_basics.py tests/test_sandbox_features.py -v`（核心测试）
- **未解决问题**：完整测试套件（40+ 文件）未全部运行；生产环境部署未验证；AI 功能因无密钥未测试
