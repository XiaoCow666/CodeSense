# CodeSense 酷森思

> 面向高校编程教学的 AI 辅助评测与学习平台。

[English](README.en.md) · [提交 Issue](https://github.com/XiaoCow666/CodeSense/issues)

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.2.3-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)

> **发布状态：正式版** · **当前版本：`v1.0.0`**
>
> `v1.0.0` 是 CodeSense 标准版的首个正式版本。版本号不写入项目标题；后续发布使用 `vMAJOR.MINOR.PATCH` 格式，并以 GitHub Release/Tag 和 [CHANGELOG.md](CHANGELOG.md) 为准。

## 目录

- [项目背景](#项目背景)
- [项目定位](#项目定位)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 入口](#api-入口)
- [安全边界与已知限制](#安全边界与已知限制)
- [发布与版本](#发布与版本)
- [参与贡献](#参与贡献)

## 项目背景

传统 OJ 能快速判断程序是否通过测试，但学生往往只能看到“对”或“错”，不知道问题出在思路、实现、边界条件还是调试过程。教师也需要在大量提交记录中寻找共性问题，再把零散的反馈整理成下一步教学安排。

CodeSense 把代码提交、受限执行、AI 辅导、分阶段练习和学情分析放在同一条学习链路里。它的重点不是替学生写出答案，而是让学生先说明思路，再逐步构造程序，最后用自己的话解释实现过程；教师则可以从班级、作业和学生画像中了解学习进展。

项目适合用于高校程序设计课程、编程实训、作业辅导和教学试点。它既可以作为带有 AI 辅助能力的评测平台，也可以作为研究引导式编程学习流程的工程基础。

## 项目定位

| 使用者 | 可以完成的事情 |
| --- | --- |
| 学生 | 提交 C++ 程序、查看测试结果和反馈，进入三阶段引导式学习流程，记录自己的思路与解释。 |
| 教师 | 创建和管理作业、组织班级与花名册，查看提交记录、作业完成情况、知识点和能力趋势。 |
| 开发者 / 研究者 | 在 Flask、SQLAlchemy 和可替换的 AI 服务接口上继续扩展评测、教学和数据分析能力。 |

## 核心功能

### 1. 代码评测与受限执行

项目内部将这条执行链路称为 **Causal Sandbox**。当前实现以应用层的受限执行为主：

- 使用 `g++` 按 C++17 标准编译学生代码；
- 编译超时为 15 秒，单个测试用例运行超时为 5 秒；
- 编译和运行子进程的 stdout/stderr 都在运行期间按每路 4096 字节读取；超过上限会及时终止子进程并返回明确的失败结果，不会把截断前缀误判为通过；
- 对正常输出进行换行、行尾空白和末尾空行规范化后比对；
- 使用临时工作目录保存编译产物，执行结束后清理；
- 将编译错误、运行时错误、超时和测试用例结果返回给评测与辅导流程。

这套机制适合课程内的受控实验。它不是对抗恶意代码的完整操作系统级隔离方案，面向公网部署时仍应补充容器或虚拟机隔离、低权限账户、网络限制和资源配额。

### 2. 三阶段引导式学习

CodeSense 将一次编程练习拆成三个相互衔接的阶段：

1. **思路描述**：学生用自然语言写出算法思路，系统根据作业目标进行评估，并提供启发式提示。
2. **步骤组装**：学生选择或填写程序步骤，系统验证顺序与内容，并实时生成代码预览。
3. **费曼教学**：学生尝试向对话中的 AI 角色解释程序原理，在多轮问答、追问和修正中检查自己是否真正理解。

引导式流程中的提示词约束和 `sanitize_response` 过滤器用于减少 AI 直接输出完整答案代码的情况，但 AI 输出仍可能出错，不能替代程序评测和教师判断。

### 3. 学习过程与能力画像

- 记录代码提交、评测结果、提示请求和引导式学习过程；
- 从算法、代码风格、功能完整性、执行效率、可读性等维度呈现能力信息；
- 提供知识点得分、个人趋势和班级视图，帮助教师定位需要继续练习的内容；
- 区分作业课程分数和能力画像分数：前者当前按 0–5 分记录，后者按 0–100 分记录。

### 4. 教师端教学管理

- 作业创建、编辑、测试用例和提交记录管理；
- 班级、学生花名册和教师邀请流程；
- 学生完成情况、班级统计、知识点与能力趋势查看；
- AI 辅助作业格式化和学情建议；
- 学生、教师和管理员的角色权限分离。

### 5. 交互与体验

- 浏览器内代码编辑器，支持 Monaco Editor 的页面会按需加载；
- 引导式学习页面提供步骤选择、代码预览和对话交互；
- 部分流程支持语音转文字及文本优化；
- `/login` 页面提供公开体验入口时，演示业务数据可以使用独立的临时 SQLite 会话，避免与正式业务数据混用。

## 从提交到理解

```mermaid
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
```

## 三阶段学习流程

```mermaid
flowchart LR
    S1[阶段一<br/>思路描述] --> V1[思路评估<br/>启发式提示]
    V1 --> S2[阶段二<br/>步骤或积木组装]
    S2 --> V2[顺序验证<br/>代码预览]
    V2 --> S3[阶段三<br/>费曼教学]
    S3 --> V3[多轮对话<br/>解释与追问]
    V3 --> P[学习记录<br/>能力画像]
```

## 公开体验入口

启动服务后打开 `/login`，登录页会提供两个无需注册的体验入口：

* **学生体验**：直接进入“演示作业一：循环与斐波那契数列”，可以查看思路描述、积木编程和费曼教学三个阶段；竞技场内的“体验进度快捷入口”可以按需跳到任意阶段或查看完成效果。
* **教师体验**：进入教师首页，查看演示班级、学生学习状态、作业完成矩阵和 AI 学情建议，再进入班级详情查看具体记录。

### 体验数据与账号边界

公开体验每次进入都会生成新的随机会话和独立临时 SQLite 数据库。演示学生、教师、班级、作业、提交、引导过程、知识点画像和 AI 分析都只写入这次会话；不会创建正式用户，也不会写入正式数据库、系统日志或学校的 RBAC 数据。

退出体验后，临时数据库及其旁路文件会立即删除；如果浏览器直接关闭，服务会按空闲超时和最长生命周期清理遗留会话，并在启动时再次清理。下一次进入会重新获得预设的初始状态，不会继承上一位访客的修改。

体验中的真实 AI 分析会调用当前配置的 AI 服务。没有可用密钥、服务调用失败或返回内容异常时，页面会显示“失败/重试”状态，不会把预设文字伪装成 AI 结果。

页面中的口径分为两类：作业提交得分为 **0–5 分**；知识点画像、五维能力和多维度贝叶斯权重评估为 **0–100 分**。两者不会混用。

演示数据由公开入口按会话自动准备。旧的 `/sandbox-login/<id>` 和 `/classes/seed-demo-data` 仍只用于开发/测试环境，不作为对外入口。

---

## 系统架构

```mermaid
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
```

### 演示数据边界

```mermaid
flowchart LR
    Entry[公开体验入口] --> Demo[演示会话]
    Demo --> Temp[(临时 SQLite 数据库)]
    Demo -. 不写入 .-> Formal[(正式业务数据库)]
    Demo --> Exit[退出或超时]
    Exit --> Cleanup[清理临时数据]
```

## 技术栈

| 层次 | 当前实现 |
| --- | --- |
| Web 后端 | Python、Flask 2.2.3、Flask-SQLAlchemy、Flask-Login、Flask-WTF |
| 数据存储 | 开发环境默认 SQLite；生产环境通过 `DATABASE_URL` 配置数据库，项目示例使用 MySQL + PyMySQL |
| AI 接口 | 智谱和 OpenAI 的可选接口适配；未配置密钥时，相关 AI 功能不可用 |
| 前端 | Jinja 模板、HTML/CSS/JavaScript、Bootstrap、Monaco Editor、Chart.js |
| 异步处理 | 应用内后台线程和任务队列，用于提交后的处理与能力分析 |
| 代码执行 | `g++`、C++17、临时工作目录、编译/运行超时和输出长度限制 |

## 快速开始

### 环境要求

- Python 3.8 或更高版本；
- C++ 评测需要可执行的 `g++`，并确保它在 `PATH` 中；
- 开发环境可以使用 SQLite；生产环境需要配置 `DATABASE_URL`；
- AI 引导、代码建议和部分学情分析需要配置智谱或 OpenAI API 密钥。

### 1. 安装依赖

```bash
git clone https://github.com/XiaoCow666/CodeSense.git
cd CodeSense
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### 2. 配置环境变量

编辑 `.env`。如果只想快速使用 SQLite 开发环境，请删除或注释 `DATABASE_URL`，让 `development` 配置使用默认 SQLite：

```dotenv
FLASK_CONFIG=development

# SQLite 开发模式：删除或注释 DATABASE_URL
# DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/codesense

# 生产环境必须设置长度足够的随机密钥
SECRET_KEY=replace-with-a-random-secret

# 至少配置一个，AI 功能才会启用
ZHIPU_API_KEY=
OPENAI_API_KEY=

```

开发/测试配置会在启动时创建数据库表。生产配置要求显式设置 `DATABASE_URL` 和 `SECRET_KEY`；生产 WSGI 默认跳过启动期建表和迁移，请先运行一次 `python database_maintenance.py`，再启动 Web worker。请不要把 `.env`、API 密钥或本地数据库文件提交到 Git。

### 3. 安装 C++ 编译器

Windows 请安装 MinGW 或 MSYS2，并将 `g++` 加入 `PATH`。Ubuntu / Debian 可以使用：

```bash
sudo apt update
sudo apt install g++
```

### 4. 启动开发服务

```bash
python run.py
```

打开 <http://127.0.0.1:5000/login>。如果未配置 AI 密钥，登录、基础页面和不依赖 AI 的功能仍可用于本地检查，但 AI 相关操作会不可用或返回失败状态。

### 5. 运行测试

```bash
python -m pytest tests -q
```

涉及 C++ 评测的测试需要 `g++`；涉及真实 AI 服务的测试还需要相应的环境配置。

### 生产部署入口

生产环境需要重新检查数据库、密钥、会话、日志、反向代理和代码执行隔离配置。仓库中的 WSGI 对象名为 `wsgi:application`，可按服务器环境使用 Gunicorn 或其他 WSGI 服务启动。

```bash
# 首次部署或数据库结构发生变化时执行一次
python database_maintenance.py

# 2 vCPU / 2 GiB 的保守默认值：2 个 gthread worker，每个 4 个线程
gunicorn -c gunicorn_config.py wsgi:application
```

生产配置默认不会让每个 Web worker 重复执行建表、历史列迁移和预设扫描；
需要临时自动维护时才设置 `AUTO_INIT_DB=1`。连接池、AI 并发、后台任务和
静态响应压缩等参数均可通过环境变量调整，具体容量边界见
[性能与容量评估报告](PERFORMANCE_CAPACITY.md)。

### HTTPS 反向代理配置

如果由 Nginx 负责 HTTPS 证书，再把请求转发给本机 Gunicorn，HTTPS 的
`server` 块至少要保留原始主机和协议头。当前线上 Gunicorn 监听
`127.0.0.1:8000`，示例配置如下：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect off;
    proxy_buffering off;
    proxy_read_timeout 180s;
}
```

线上 `.env` 建议设置 `FLASK_CONFIG=production`、
`SECURE_COOKIES=true`、`TRUST_PROXY_HEADERS=true` 和
`PROXY_FIX_HOPS=1`，然后执行 `nginx -t && systemctl reload nginx`。
应用会通过 `ProxyFix` 恢复 HTTPS scheme，确保登录后的会话 Cookie、
重定向和外部链接使用同一套 HTTPS 地址。

## 配置说明

| 变量 | 用途 |
| --- | --- |
| `FLASK_CONFIG` | `development`、`testing` 或 `production`。直接运行 `app.py` 默认开发配置；`wsgi.py` 默认生产配置。 |
| `DATABASE_URL` | 生产环境数据库连接；开发环境也可以用它覆盖默认 SQLite。 |
| `DEV_DATABASE_URL` | 开发环境数据库连接，不设置时使用 SQLite。 |
| `TEST_DATABASE_URL` | 测试环境数据库连接，不设置时使用独立 SQLite。 |
| `SECRET_KEY` | Flask 会话和签名密钥；生产环境必须设置，且至少 32 个字符。 |
| `ZHIPU_API_KEY` / `OPENAI_API_KEY` | AI 服务密钥，至少配置一个才能使用对应的 AI 功能。 |
| `AI_PROVIDER_ORDER` | 多 provider 的优先顺序，例如 `zhipu,openai`；请求失败时自动切换。 |
| `ZHIPU_MODEL` / `OPENAI_MODEL` | 各 provider 的默认对话模型。 |
| `AI_RETRY_ATTEMPTS` | 瞬时网络错误、限流和 5xx 的最大尝试次数，默认 3。 |
| `AI_MAX_CONCURRENT_REQUESTS` | 进程内同时进行的 AI 请求上限，默认 3。 |
| `AI_CIRCUIT_FAILURE_THRESHOLD` / `AI_CIRCUIT_COOLDOWN_SECONDS` | provider 连续失败多少次后进入冷却，以及冷却时长。 |
| `AI_SINGLEFLIGHT_WAIT_SECONDS` | 相同 AI 请求在进程内合并时，跟随请求等待共享结果的最长时间。 |
| `REDIS_URL` | 可选 Redis 地址；用于会话或缓存相关能力。 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 每个 Web worker 的数据库连接池基线和溢出上限；总连接数会随 worker 数相乘。 |
| `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | 获取连接最长等待时间和连接回收周期，减少断线连接占用。 |
| `AUTO_INIT_DB` / `DB_ENSURE_INDEXES` | 是否在应用启动时建表/维护索引；生产建议使用 `database_maintenance.py` 一次性执行。 |
| `ASYNC_TASKS_ENABLED` / `ASYNC_WORKER_COUNT` | 进程内后台任务队列开关和线程数；多 worker 大规模部署应迁移到独立队列。 |
| `PRESET_SCAN_ENABLED` / `PRESET_SCAN_BATCH_SIZE` | 是否启动预设补全扫描及单次扫描上限；生产默认关闭重复扫描。 |
| `ACCESS_LOG_ENABLED` / `SLOW_REQUEST_MS` | 应用访问日志开关和慢请求阈值；生产建议交给 Gunicorn/Nginx 记录普通访问。 |
| `STATIC_CACHE_SECONDS` / `ENABLE_RESPONSE_COMPRESSION` | 静态资源缓存时长及 HTML/JSON 压缩开关，用于降低 3 Mbps 带宽压力。 |
| `SECURE_COOKIES` | 生产 HTTPS 部署应设为 `true`；本地 HTTP 调试可设为 `false`。 |
| `TRUST_PROXY_HEADERS` / `PROXY_FIX_HOPS` | HTTPS 反向代理协议头信任开关和代理层数；当前 Nginx -> Gunicorn 拓扑使用 `true` / `1`。 |

## API 入口

以下是常用入口，完整路由以 `routes/` 中的实现为准：

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/api/submit` | `POST` | 提交代码并开始评测。 |
| `/api/code_advice` | `POST` | 获取代码建议。 |
| `/api/get_programming_guidance` | `POST` | 获取编程引导。 |
| `/api/stream/ability-analysis` | `GET` | 流式获取能力分析。 |
| `/thinking/<assignment_id>` | `GET` | 进入三阶段引导式学习页面。 |
| `/thinking/api/stage1/submit` | `POST` | 提交阶段一思路。 |
| `/thinking/api/stage2/verify` | `POST` | 验证阶段二步骤组装。 |
| `/thinking/api/stage3/chat` | `POST` | 进行阶段三对话。 |

## 安全边界与已知限制

- 学生提交的代码会进入受限编译和运行流程，但当前实现不应被理解为完整的恶意代码隔离系统；公网部署必须增加操作系统或容器级隔离。
- 编译器、运行时、AI 服务和数据库都可能不可用。页面应展示失败或重试状态，不能把默认文字当成真实 AI 结果。
- AI 输出具有不确定性。提示词约束和文本过滤只能降低直接泄露答案的风险，不能替代评测结果、权限控制和人工复核。
- 生产环境必须使用随机 `SECRET_KEY`、受保护的数据库凭据和安全的会话配置，并限制日志、上传目录和数据库的访问权限。
- 不要在公开仓库、Issue、日志或截图中提交 API 密钥、用户隐私和生产数据库信息。

## 发布与版本

CodeSense 采用语义化版本号：

- `MAJOR`：不兼容的接口或行为变化；
- `MINOR`：向后兼容的功能增加；
- `PATCH`：向后兼容的问题修复和小幅调整。

当前版本为 **`v1.0.0`**，代表标准版首个正式版本。后续版本应同时更新 [CHANGELOG.md](CHANGELOG.md)，并使用同名的 Git tag 和 GitHub Release；已发布版本的记录不应被静默改写。

## 参与贡献

欢迎通过 Issue 反馈问题或提交 Pull Request。改动应放在独立分支中，并在 PR 中写明改动内容、测试结果和注意事项。`main` 的合并由项目负责人审核后进行。

## 许可证

本项目采用 [MIT License](LICENSE)。

感谢参与 CodeSense 试点和课程实践的师生。
