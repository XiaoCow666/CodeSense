# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## PR worktree runtime isolation

PR branches and temporary worktrees must share reusable capabilities with the main development setup, but must not share writable state with the main runtime.

- Code and dependencies: run the checked-out PR code with the shared Anaconda `student-eval` environment. Do not copy source files from the main checkout into the worktree; rebase or merge the branch when main-code updates are needed.
- AI access: API credentials may be supplied through process/user environment variables or a secrets file outside Git. Never copy `.env` into a worktree, print secret values, or commit credentials. The AI provider account/quota is shared, while its database/cache state must remain isolated.
- SQLite: create a one-time seed copy of the main development database inside the PR worktree, for example `instance/pr_student_code_review.db`, and set `DEV_DATABASE_URL` to that absolute path. Never point a PR process at the main database path. Refresh the seed only intentionally, with the source application stopped; normal PR runs write only to the PR copy.
- Real-account and real-assignment testing: the seed copy is expected to contain the main database's real password hashes, users, assignments, presets, and relevant history. This is how a PR tests real data without a live main-database connection. An empty default SQLite database is not a valid PR test setup.
- Latest-data refresh: if main receives new users or assignments, stop the PR process and intentionally recreate or refresh its seed snapshot before testing. Do not add runtime read-through queries to the main database as a shortcut.
- Live main reads with PR-local writes require an explicitly designed and tested dual-database repository boundary (including authentication, foreign keys, transactions, migrations, and cache/session isolation); until that exists, it is prohibited.
- MySQL or another server database: use a separate database/schema and credentials for the PR. A different branch or process is not a database isolation boundary.
- Redis: use a distinct Redis database or instance for the PR, such as `redis://127.0.0.1:6379/1` when main uses database 0. If Redis is unavailable, keep filesystem sessions/cache under the worktree-local directories.
- Filesystem state: keep sessions, uploads, logs, generated artifacts, and test databases under the worktree. Do not reuse main's writable directories.
- Migrations: test schema changes against the PR database first. Apply them to the main database only as a separate, explicitly reviewed deployment step.

Canonical PowerShell startup for a seeded PR worktree:

```powershell
conda activate student-eval
$worktreePath = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $worktreePath "app.py"))) { throw "请在 PR worktree 根目录运行此命令。" }
$gitDirectory = (git -C $worktreePath rev-parse --absolute-git-dir).Trim()
$commonGitDirectory = (git -C $worktreePath rev-parse --path-format=absolute --git-common-dir).Trim()
if (-not $gitDirectory -or -not $commonGitDirectory -or $gitDirectory -eq $commonGitDirectory) { throw "请在 PR worktree 根目录运行此命令。" }
$databasePath = Join-Path $worktreePath "instance\pr_student_code_review.db"
if (-not (Test-Path -LiteralPath $databasePath)) { throw "请先创建 PR worktree 的 SQLite seed copy。" }
$env:DEV_DATABASE_URL = "sqlite:///$($databasePath.Replace('\', '/'))"
$env:REDIS_URL = "redis://127.0.0.1:6379/1"
$env:HOST = "127.0.0.1"
$env:PORT = "5000"
$env:FLASK_DEBUG = "0"
python .\app.py
```

Before starting, verify that the seed database exists and that `DEV_DATABASE_URL` does not resolve to the main checkout. Keep the seed database untracked; it is already covered by the repository's `instance/` and `*.db` ignore rules.

## Browser 插件版本一致性

- 每次使用 Browser 时，读取当前会话提供的 Browser skill 路径，并检查 `codex mcp get node_repl --json` 返回的 `NODE_REPL_TRUSTED_SERVICES.browser`。不要在本文件中保存插件缓存目录的版本号。
- Codex 桌面应用启动时会更新 Browser service 路径。确认该路径中的文件存在、缓存目录中的插件清单版本与路径版本一致，且 `browser-client.mjs` 来自相同版本。只修改 `config.toml` 无法修复缺少插件文件的问题。
- 当前版本缓存缺失时，从已安装 Codex 桌面应用随附的 `resources/plugins/openai-bundled/plugins/browser` 恢复清单版本完全相同的插件内容，逐项核对文件校验值，再验证 Browser 文档读取和页面访问。不要把其他版本的文件放进当前版本目录。

## 发布版本一致性

- 发布前读取 GitHub `origin/main`、候选提交、服务器 `/var/www/codesense` 的 `HEAD` 和服务器 `origin/main`。核对服务器目录与工作区状态，确认候选包含最新远端 `main`，并逐项处理主工作区尚未提交的改动。
- 发布版本号同时检查 `README.md`、`README.en.md`、`CHANGELOG.md`、版本信息图文件名和 GitHub Release 标签。用户看到的版本介绍必须对应准备发布的提交。
- 候选通过审查和测试后，向远端 `main` 推送候选提交，再读取远端提交确认推送结果。服务器只在目标实例和目录核验通过后执行 `/var/www/codesense/update.sh`。
- 等待 `update.sh` 完整结束，随后确认服务器 `HEAD` 与远端 `main` 是同一提交，应用及必要 worker 正常运行，`/healthz` 与 `/readyz` 均返回 200。完成这些检查后才能创建 Release、发送更新消息和修改项目知识文档。
- 报告分别记录候选、远端、服务器和 Release 的版本与提交。任一位置不同步时，停止对外发布并记录实际状态。

## Project Overview

CodeSense 酷森思 is an intelligent programming education platform for universities. It uses a "Causal Sandbox" for code execution and "Heuristic LLM" for AI-powered programming guidance that leads students to answers through questioning rather than providing direct solutions.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python run.py
# or
python app.py

# Run tests
python -m pytest tests/test_app.py
# or
python tests/test_app.py

# Initialize database (in Python shell)
from models import db, app
with app.app_context():
    db.create_all()

# Production deployment
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
```

## Architecture

### Application Entry Point
- `app.py` - Main application factory (`create_app()`), registers blueprints, initializes models and async tasks
- `run.py` - Simple wrapper that imports and runs `app.py`
- `wsgi.py` - Production WSGI entry point

### Configuration
- `config.py` - Config class with three environments: `development`, `testing`, `production`
  - Database: `DATABASE_URL` env var (MySQL in production, SQLite in development)
  - AI APIs: `ZHIPU_API_KEY` and/or `OPENAI_API_KEY`
  - `LOAD_LOCAL_MODEL=False` for cloud deployments (saves ~1GB memory)

### Blueprints (Routes)
| Blueprint | Purpose |
|-----------|---------|
| `routes/auth.py` | Login, logout, registration |
| `routes/main.py` | Main pages (home, about, help) |
| `routes/assignments.py` | Assignment CRUD operations |
| `routes/users.py` | User profile management |
| `routes/classes.py` | Class management for teachers |
| `routes/api.py` | REST API for code submission, AI evaluation, ability scoring |

### Core Services (`utils/`)
- `code_evaluator.py` - CodeBERT embedding + TextCNN scoring, initializes local ML models
- `sandbox_runner.py` - subprocess-based code execution sandbox with timeout
- `llm_evaluator.py` - GLM-4/GPT-4 API calls for code evaluation
- `guidance_generator.py` - Heuristic prompts that guide students through questioning
- `code_advisor.py` - Code advice and feedback generation
- `async_tasks.py` - ThreadPool-based async task queue with SSE streaming
- `ability_scorer.py` - Bayesian-weighted ability tracking across 13 C programming concepts
- `prompts.py` - Prompt templates for AI interactions

### Models (`models/`)
- `CNN.py` - TextCNN model using CodeBERT embeddings
- `codebert.py` - CodeBERT model wrapper
- `codebertcnn.pth` - Pretrained weights

### Key Patterns
1. **AI-only mode**: Set `LOAD_LOCAL_MODEL=False` to skip PyTorch model loading
2. **Async evaluation**: Code submissions go through `async_tasks.py` with SSE progress updates
3. **Sandbox security**: 15s compile timeout, 5s run timeout, subprocess isolation
4. **Session management**: Flask-Session with filesystem backend

## Database

SQLAlchemy ORM with models in `models.py`. Uses Flask-Migrate for schema migrations. Key models: User (with usertype: 学生/教师/管理员), Assignment, Submission, Class, AbilityScore.

## Frontend

Bootstrap 5 + Monaco Editor for code editing. Jinja2 templates in `templates/`. Static assets in `static/` with CSS, JS, and images.
