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

- 每次使用 Browser 时，读取当前会话提供的 Browser skill 路径，并从该安装目录载入 `browser-client.mjs`。不要在本文件或运行配置中保存插件缓存目录的版本号。
- `NODE_REPL_TRUSTED_SERVICES.browser` 使用 Codex 运行环境提供的包入口；当前桌面环境使用 `@oai/browser-desktop/service`。插件升级后检查该入口仍可解析，避免配置指向某次安装的缓存目录。
- 修改 `NODE_REPL_TRUSTED_SERVICES` 后，重新启动 Codex，并验证 Browser 文档读取和页面访问。

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
