<p align="center">
  <img src="docs/assets/caifusi-logo-wordmark-v1.png" alt="财赋思品牌标志" width="480">
</p>

<h1 align="center">CodeSense 酷森思</h1>

<p align="center">
  面向高校编程教学的代码评测与学习平台。
</p>

<p align="center">
  <a href="https://saucodesense.com">在线体验</a> ·
  <a href="#在线体验">学生 / 教师 Demo</a> ·
  <a href="#快速开始">本地运行</a> ·
  <a href="DEPLOYMENT.md">部署指南</a> ·
  <a href="https://github.com/XiaoCow666/CodeSense/issues">提交 Issue</a> ·
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/XiaoCow666/CodeSense/stargazers"><img src="https://img.shields.io/github/stars/XiaoCow666/CodeSense?style=flat-square&logo=github" alt="GitHub stars"></a>
  <a href="https://github.com/XiaoCow666/CodeSense/network/members"><img src="https://img.shields.io/github/forks/XiaoCow666/CodeSense?style=flat-square&logo=github" alt="GitHub forks"></a>
  <a href="https://github.com/XiaoCow666/CodeSense/blob/main/LICENSE"><img src="https://img.shields.io/github/license/XiaoCow666/CodeSense?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/version-v1.0.0-2563eb?style=flat-square" alt="v1.0.0">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/Flask-2.2.3-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask 2.2.3">
</p>

> 当前版本：<a href="https://github.com/XiaoCow666/CodeSense/releases/tag/v1.0.0"><code>v1.0.0</code></a>。
>
> 这是 CodeSense Standard Edition 的首个正式版本。后续版本会同时更新 [CHANGELOG.md](CHANGELOG.md)、Git tag 和 GitHub Release。

## 目录

- [产品预览](#产品预览)
- [为什么做这个项目](#为什么做这个项目)
- [适用对象](#适用对象)
- [主要功能](#主要功能)
- [从提交到理解](#从提交到理解)
- [在线体验](#在线体验)
- [系统结构](#系统结构)
- [快速开始](#快速开始)
- [生产部署](#生产部署)
- [配置说明](#配置说明)
- [API 入口](#api-入口)
- [安全边界与已知限制](#安全边界与已知限制)
- [发布与版本](#发布与版本)
- [Star History](#star-history)
- [参与贡献](#参与贡献)

## 产品预览

下面的截图来自当前应用页面。

<p align="center">
  <img src="docs/assets/codesense-login.png" alt="CodeSense 登录页与体验入口" width="100%">
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <p align="center">学生：三阶段引导式学习</p>
      <img src="docs/assets/codesense-student-demo.png" alt="CodeSense 学生体验：思路描述阶段" width="100%">
    </td>
    <td width="50%" valign="top">
      <p align="center">教师：班级与学情视图</p>
      <img src="docs/assets/codesense-teacher-dashboard.png" alt="CodeSense 教师仪表盘" width="100%">
    </td>
  </tr>
</table>

## 为什么做这个项目

普通 OJ 很擅长判断程序是否通过测试，但学生看到的通常只有 AC 或 WA。他们不一定知道问题出在算法、实现、边界条件还是调试过程。教师面对大量提交记录，也很难手工归纳每个班级反复出现的问题。

CodeSense 把代码提交、受限执行、AI 辅导、分阶段练习和学情记录放在同一条流程里。学生先写出思路，再逐步构造程序，最后用自己的话解释实现过程。教师可以从作业、班级和学生记录中查看学习进展。

这个项目目前适合高校程序设计课程、编程实训和教学试点，也可以作为研究引导式编程学习流程的工程起点。

## 适用对象

| 使用者 | 可以完成的事情 |
| --- | --- |
| 学生 | 提交 C++ 程序，查看测试结果和反馈，完成思路描述、步骤组装与费曼教学 |
| 教师 | 创建作业，管理班级和花名册，查看提交、完成情况、知识点和能力趋势 |
| 开发者 / 研究者 | 在 Flask、SQLAlchemy 和可替换的 AI 接口上继续扩展评测、教学和数据分析 |

## 主要功能

### 代码评测与受限执行

项目内部把这条执行链称为 Causal Sandbox。当前实现主要依靠应用层限制，适合课程内的受控实验，不应当被当作完整的操作系统级安全沙箱。

- 使用 <code>g++</code> 按 C++17 编译学生代码；
- 编译超时为 15 秒，单个测试用例运行超时为 5 秒；
- 编译和运行子进程的 stdout/stderr 都在运行期间按每路 4096 字节读取；超过上限会及时终止子进程并返回明确的失败结果，不会把截断前缀误判为通过；
- 对正常输出进行换行、行尾空白和末尾空行规范化后比对；
- 使用临时工作目录保存编译产物，执行结束后清理；
- 将编译错误、运行时错误、超时和测试结果交给评测与辅导流程。

如果要面向公网运行，还需要增加容器或虚拟机隔离、低权限账户、网络限制和资源配额。

### 三阶段引导式学习

一次练习分成三个阶段：

1. **思路描述**：学生先用自然语言写出算法，系统根据作业要求给出评估和提示。
2. **步骤组装**：学生填写或选择程序步骤，系统检查顺序并生成代码预览。
3. **费曼教学**：学生向对话中的 AI 角色解释程序，在追问和修正中检查自己是否理解。

提示词约束和 <code>sanitize_response</code> 过滤器会尽量减少 AI 直接给出完整答案代码的情况，但 AI 仍可能出错。最终结果要以程序评测和教师判断为准。

### 学习记录与能力画像

系统会记录代码提交、评测结果、提示请求和引导式学习过程，并从算法、代码风格、功能完整性、执行效率和可读性等维度整理能力信息。教师端可以查看知识点得分、个人趋势和班级视图。

作业提交得分与能力画像不是同一个指标：前者当前按 0–5 分记录，后者按 0–100 分记录。

### 教师端

教师可以创建和编辑作业，维护测试用例和提交记录，组织班级与花名册，查看完成情况和知识点趋势。学生、教师和管理员使用不同的角色权限。

### 编辑器与交互

浏览器内提供代码编辑器，使用 Monaco Editor 的页面会按需加载。引导式学习页面包含步骤选择、代码预览和对话交互，部分流程支持语音转文字与文本优化。

## 从提交到理解

~~~mermaid
flowchart LR
    A[作业与学习目标] --> B[学生描述思路]
    B --> C[步骤组装与代码提交]
    C --> D[受限编译与运行]
    D --> E[评测结果与运行证据]
    E --> F[AI 提示与教师反馈]
    F --> G[修正、解释与再提交]
    G --> C
    E --> H[能力画像与知识点记录]
    H --> I[教师学情视图]
~~~

## 在线体验

可以直接打开 [在线体验站点](https://saucodesense.com)，也可以在本地启动服务后访问 <code>/login</code>。登录页提供两个无需注册的体验入口。

- 学生体验进入“演示作业一：循环与斐波那契数列”，可以依次查看思路描述、步骤组装和费曼教学。
- 教师体验进入教师首页，可以查看演示班级、学生状态、作业完成矩阵和 AI 学情建议，再进入班级详情查看记录。

### 体验数据边界

公开体验会为每次访问创建随机会话和独立的临时 SQLite 数据库。演示用户、班级、作业、提交、引导过程、知识点画像和 AI 分析只写入本次会话，不会创建正式用户，也不会写入正式业务数据库。

退出体验后，临时数据库及旁路文件会清理。浏览器直接关闭时，服务会按空闲超时和最长生命周期清理遗留会话，并在启动时再次检查。下一次进入会重新获得预设状态。

体验中的 AI 分析会调用当前配置的 AI 服务。没有可用密钥、服务调用失败或返回内容异常时，页面会显示失败或重试状态，不会把预设文字当成 AI 结果。

页面中的分数口径也不同：作业提交为 0–5 分；知识点画像、五维能力和贝叶斯权重评估为 0–100 分。

旧的 <code>/sandbox-login/&lt;id&gt;</code> 和 <code>/classes/seed-demo-data</code> 只用于开发和测试，不作为公开入口。

## 系统结构

~~~mermaid
flowchart TB
    Browser[浏览器]

    subgraph Server[Flask 应用]
        Routes[Blueprint 路由]
        Services[业务服务]
        Tasks[后台任务线程]
        Routes --> Services
        Services --> Tasks
    end

    DB[(SQL 数据库)]
    Sandbox[C++17 评测执行器]
    LLM[可选 AI 服务<br/>智谱或 OpenAI]
    Session[Redis 或文件会话]

    Browser -->|HTTP / SSE| Routes
    Services --> DB
    Services --> Sandbox
    Services -. AI 请求 .-> LLM
    Tasks --> DB
    Tasks -. 异步 AI 分析 .-> LLM
    Routes --> Session
~~~

### 演示数据如何隔离

~~~mermaid
flowchart LR
    Entry[公开体验入口] --> Demo[演示会话]
    Demo --> Temp[(临时 SQLite 数据库)]
    Demo -. 不写入 .-> Formal[(正式业务数据库)]
    Demo --> Exit[退出或超时]
    Exit --> Cleanup[清理临时数据]
~~~

## 技术栈

| 层次 | 当前实现 |
| --- | --- |
| Web 后端 | Python、Flask 2.2.3、Flask-SQLAlchemy、Flask-Login、Flask-WTF |
| 数据存储 | 开发环境默认 SQLite；生产环境通过 <code>DATABASE_URL</code> 配置数据库，示例使用 MySQL + PyMySQL |
| AI 接口 | 智谱和 OpenAI 的可选接口；未配置密钥时，相关功能不可用 |
| 前端 | Jinja 模板、HTML/CSS/JavaScript、Bootstrap、Monaco Editor、Chart.js |
| 异步处理 | 应用内后台线程和任务队列，用于提交后的处理与能力分析 |
| 代码执行 | <code>g++</code>、C++17、临时工作目录、编译/运行超时和输出长度限制 |

## 快速开始

### 环境要求

- Python 3.8 或更高版本；
- C++ 评测需要可执行的 <code>g++</code>，并确保它在 <code>PATH</code> 中；
- 开发环境可以使用 SQLite，生产环境需要配置 <code>DATABASE_URL</code>；
- AI 引导、代码建议和部分学情分析需要智谱或 OpenAI API 密钥。

### 1. 安装依赖

~~~bash
git clone https://github.com/XiaoCow666/CodeSense.git
cd CodeSense
python -m venv .venv
~~~

Windows PowerShell：

~~~powershell
.venvScriptsActivate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
~~~

macOS / Linux：

~~~bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
~~~

### 2. 配置环境变量

编辑 <code>.env</code>。只想用 SQLite 开发环境时，删除或注释 <code>DATABASE_URL</code>：

~~~dotenv
FLASK_CONFIG=development

# SQLite 开发模式
# DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/codesense

# 生产环境请替换成随机密钥
SECRET_KEY=replace-with-a-random-secret

# 至少配置一个，AI 功能才会启用
ZHIPU_API_KEY=
OPENAI_API_KEY=
~~~

开发和测试配置会在启动时创建数据库表。生产配置要显式设置 <code>DATABASE_URL</code> 和 <code>SECRET_KEY</code>；生产 WSGI 默认跳过启动期建表和迁移，请先执行 <code>python database_maintenance.py</code>。不要把 <code>.env</code>、API 密钥或本地数据库文件提交到 Git。

### 3. 安装 C++ 编译器

Windows 请安装 MinGW 或 MSYS2，并把 <code>g++</code> 加入 <code>PATH</code>。Ubuntu / Debian 可以运行：

~~~bash
sudo apt update
sudo apt install g++
~~~

### 4. 启动开发服务

~~~bash
python run.py
~~~

打开 <http://127.0.0.1:5000/login>。没有 AI 密钥时，登录、基础页面和不依赖 AI 的功能仍可用于本地检查，AI 相关操作会返回不可用或失败状态。

### 5. 运行测试

~~~bash
python -m pytest tests -q
~~~

涉及 C++ 评测的测试需要 <code>g++</code>；涉及真实 AI 服务的测试还需要相应环境变量。

## 生产部署

生产环境至少要重新检查数据库、密钥、会话、日志、反向代理和代码执行隔离。仓库通过 <code>wsgi:application</code> 暴露 WSGI 对象，可按服务器环境使用 Gunicorn 或其他 WSGI 服务。

~~~bash
# 首次部署或数据库结构变化后执行一次
python database_maintenance.py

# 使用仓库自带配置，默认监听 127.0.0.1:5000
gunicorn -c gunicorn_config.py wsgi:application
~~~

完整的 Linux、Gunicorn、Systemd、Nginx、HTTPS、MySQL、Redis 和发布检查步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 配置说明

| 变量 | 用途 |
| --- | --- |
| <code>FLASK_CONFIG</code> | <code>development</code>、<code>testing</code> 或 <code>production</code> |
| <code>DATABASE_URL</code> | 生产数据库连接；开发环境也可以用它覆盖 SQLite |
| <code>DEV_DATABASE_URL</code> | 开发环境数据库连接，不设置时使用 SQLite |
| <code>TEST_DATABASE_URL</code> | 测试数据库连接，不设置时使用独立 SQLite |
| <code>SECRET_KEY</code> | Flask 会话和签名密钥；生产环境必须设置随机值 |
| <code>ZHIPU_API_KEY</code> / <code>OPENAI_API_KEY</code> | AI 服务密钥，至少配置一个 |
| <code>AI_PROVIDER_ORDER</code> | 多 provider 的优先顺序，例如 <code>zhipu,openai</code> |
| <code>ZHIPU_MODEL</code> / <code>OPENAI_MODEL</code> | 各 provider 使用的模型 |
| <code>AI_RETRY_ATTEMPTS</code> | 网络错误、限流和 5xx 的最大重试次数 |
| <code>AI_MAX_CONCURRENT_REQUESTS</code> | 单个进程同时处理的 AI 请求上限 |
| <code>AI_CIRCUIT_FAILURE_THRESHOLD</code> / <code>AI_CIRCUIT_COOLDOWN_SECONDS</code> | provider 连续失败后的冷却条件和时长 |
| <code>AI_SINGLEFLIGHT_WAIT_SECONDS</code> | 相同请求合并时等待共享结果的最长时间 |
| <code>REDIS_URL</code> | 可选 Redis 地址，用于会话或缓存相关能力 |
| <code>DB_POOL_SIZE</code> / <code>DB_MAX_OVERFLOW</code> | 每个 Web worker 的连接池基线和溢出上限 |
| <code>DB_POOL_TIMEOUT</code> / <code>DB_POOL_RECYCLE</code> | 获取连接的最长等待时间和连接回收周期 |
| <code>AUTO_INIT_DB</code> / <code>DB_ENSURE_INDEXES</code> | 启动时是否建表和维护索引；生产建议单独执行维护脚本 |
| <code>ASYNC_TASKS_ENABLED</code> / <code>ASYNC_WORKER_COUNT</code> | 进程内任务队列的开关和线程数 |
| <code>PRESET_SCAN_ENABLED</code> / <code>PRESET_SCAN_BATCH_SIZE</code> | 预设补全扫描开关和单次扫描上限 |
| <code>ACCESS_LOG_ENABLED</code> / <code>SLOW_REQUEST_MS</code> | 应用访问日志开关和慢请求阈值 |
| <code>STATIC_CACHE_SECONDS</code> / <code>ENABLE_RESPONSE_COMPRESSION</code> | 静态资源缓存时长和响应压缩开关 |
| <code>SECURE_COOKIES</code> | HTTPS 生产部署应设为 <code>true</code> |
| <code>TRUST_PROXY_HEADERS</code> / <code>PROXY_FIX_HOPS</code> | 反向代理协议头信任开关和代理层数；当前 Nginx → Gunicorn 使用 <code>true</code> / <code>1</code> |

## API 入口

以下是常用入口，完整路由以 <code>routes/</code> 中的实现为准：

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| <code>/api/submit</code> | <code>POST</code> | 提交代码并开始评测 |
| <code>/api/code_advice</code> | <code>POST</code> | 获取代码建议 |
| <code>/api/get_programming_guidance</code> | <code>POST</code> | 获取编程引导 |
| <code>/api/stream/ability-analysis</code> | <code>GET</code> | 流式获取能力分析 |
| <code>/thinking/&lt;assignment_id&gt;</code> | <code>GET</code> | 进入三阶段引导式学习页面 |
| <code>/thinking/api/stage1/submit</code> | <code>POST</code> | 提交阶段一思路 |
| <code>/thinking/api/stage2/verify</code> | <code>POST</code> | 验证阶段二步骤组装 |
| <code>/thinking/api/stage3/chat</code> | <code>POST</code> | 进行阶段三对话 |

## 安全边界与已知限制

- 学生代码会进入受限编译和运行流程，但当前实现不是完整的恶意代码隔离系统。公网部署必须增加操作系统或容器级隔离。
- 编译器、运行时、AI 服务和数据库都可能不可用。页面应显示失败或重试状态，不能把默认文字当成真实 AI 结果。
- AI 输出可能出错。提示词约束和文本过滤不能替代程序评测、权限控制或教师复核。
- 生产环境要使用随机 <code>SECRET_KEY</code>、受保护的数据库凭据和安全会话配置，并限制日志、上传目录和数据库的访问权限。
- 不要在公开仓库、Issue、日志或截图中提交 API 密钥、用户隐私和生产数据库信息。

## 发布与版本

CodeSense 使用语义化版本号：

- <code>MAJOR</code>：不兼容的接口或行为变化；
- <code>MINOR</code>：向后兼容的功能增加；
- <code>PATCH</code>：向后兼容的问题修复和小幅调整。

当前版本是 [v1.0.0](https://github.com/XiaoCow666/CodeSense/releases/tag/v1.0.0)，对应标准版首个正式发布。后续版本请同时更新 [CHANGELOG.md](CHANGELOG.md)，并使用同名 Git tag 和 GitHub Release。

## Star History

顶部徽章显示当前 star 数。这里没有嵌入第三方历史图，因为 GitHub 对公开 stargazers 时间线接口的限制会让 Star History 返回错误页面。等仓库自己的趋势数据生成流程准备好后，再把图放回 README。

- [查看 CodeSense 仓库](https://github.com/XiaoCow666/CodeSense)
- [Star History 官方说明](https://www.star-history.com/blog/github-stargazer-api-restriction/)

## 参与贡献

欢迎通过 [Issue](https://github.com/XiaoCow666/CodeSense/issues) 反馈问题或提交 Pull Request。改动请说明原因、验证方式，以及是否影响密钥、数据库或代码执行边界。默认分支的合并由项目维护者审核。

## 许可证

本项目采用 [MIT License](LICENSE)。
