<p align="center">
  <img src="docs/assets/codesense-mark.svg" alt="CodeSense logo" width="112">
</p>

<h1 align="center">CodeSense</h1>

<p align="center">
  <strong>Make Coding Intelligent</strong><br>
  An AI-assisted assessment and learning platform for university programming courses.<br>
  Turn every submission into a step toward deeper understanding.
</p>

<p align="center">
  <a href="https://saucodesense.com">Live demo</a> ·
  <a href="#public-demo">Student / teacher demo</a> ·
  <a href="#getting-started">Run locally</a> ·
  <a href="DEPLOYMENT.md">Deployment</a> ·
  <a href="https://github.com/XiaoCow666/CodeSense/issues">Open an issue</a> ·
  <a href="README.md">简体中文</a>
</p>

<p align="center">
  <a href="https://github.com/XiaoCow666/CodeSense/stargazers"><img src="https://img.shields.io/github/stars/XiaoCow666/CodeSense?style=flat-square&logo=github" alt="GitHub stars"></a>
  <a href="https://github.com/XiaoCow666/CodeSense/network/members"><img src="https://img.shields.io/github/forks/XiaoCow666/CodeSense?style=flat-square&logo=github" alt="GitHub forks"></a>
  <a href="https://github.com/XiaoCow666/CodeSense/blob/main/LICENSE"><img src="https://img.shields.io/github/license/XiaoCow666/CodeSense?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/version-v1.0.0-2563eb?style=flat-square" alt="v1.0.0">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/Flask-2.2.3-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask 2.2.3">
</p>

> **Release status: formal release** · **Current version: `v1.0.0`**
>
> `v1.0.0` is the first formal release of the CodeSense Standard Edition. Future releases use `vMAJOR.MINOR.PATCH` and are tracked in GitHub Releases/Tags and [CHANGELOG.md](CHANGELOG.md).

## Contents

- [Product preview](#product-preview)
- [Public demo](#public-demo)
- [Background](#background)
- [Project scope](#project-scope)
- [Core capabilities](#core-capabilities)
- [System architecture](#system-architecture)
- [Getting started](#getting-started)
- [Deployment guide](DEPLOYMENT.md)
- [Configuration](#configuration)
- [API entry points](#api-entry-points)
- [Security boundaries and limitations](#security-boundaries-and-limitations)
- [Releases and versioning](#releases-and-versioning)
- [Star History](#star-history)
- [Contributing](#contributing)

## Product preview

These screenshots are from the runnable pages in the repository, not concept mockups:

<p align="center">
  <img src="docs/assets/codesense-login.png" alt="CodeSense login page and demo entry points" width="100%">
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <p align="center"><strong>Student: guided learning</strong></p>
      <img src="docs/assets/codesense-student-demo.png" alt="CodeSense student demo: idea description stage" width="100%">
    </td>
    <td width="50%" valign="top">
      <p align="center"><strong>Teacher: class analytics</strong></p>
      <img src="docs/assets/codesense-teacher-dashboard.png" alt="CodeSense teacher dashboard" width="100%">
    </td>
  </tr>
</table>

## Public demo

Visit the [live demo site](https://saucodesense.com), or start the local server and open `/login`. The login page provides two no-registration entry points:

- **Student demo**: explore the three stages—idea description, step assembly, and Feynman-style explanation.
- **Teacher demo**: inspect a sample class, student learning states, assignment completion, and AI-assisted learning suggestions.

Each demo session uses isolated temporary data. AI responses are shown as failed/retry states when the configured provider is unavailable; preset text is not presented as a real AI result.

## Background

Traditional online judges are good at deciding whether a program passes a test, but a pass/fail result does not explain whether a student’s difficulty comes from the algorithm, implementation details, edge cases, or debugging process. Teachers also need to inspect many submissions before they can identify common problems and decide what to teach next.

CodeSense connects code submission, constrained execution, AI guidance, staged practice, and learning analytics in one workflow. It is designed to help students describe an idea first, construct a program step by step, and explain the result in their own words instead of receiving a finished answer. Teachers can review assignments, classes, submissions, knowledge points, and learning trends from the same platform.

The project is intended for university programming courses, practical labs, guided assignment support, and teaching pilots. It can serve as an engineering base for both AI-assisted assessment and research on guided programming learning.

## Project scope

| User | What they can do |
| --- | --- |
| Students | Submit C++ programs, inspect test results and feedback, follow the three-stage learning flow, and record their reasoning and explanations. |
| Teachers | Create and manage assignments, organize classes and rosters, inspect submissions, and review knowledge-point and ability trends. |
| Developers / researchers | Extend assessment, teaching, and analytics features on top of Flask, SQLAlchemy, and replaceable AI service adapters. |

## Core capabilities

### 1. Code assessment and constrained execution

The project calls this execution path **Causal Sandbox**. The current implementation provides application-level constraints:

- Compiles student code with `g++` using the C++17 standard;
- Uses a 15-second compilation timeout and a 5-second timeout for each test case;
- Reads each child-process stdout/stderr stream with a 4096-byte runtime bound; exceeding the limit terminates the child and returns an explicit failure instead of comparing a truncated prefix;
- Normalizes normal output for line endings, trailing whitespace, and trailing blank lines before comparison;
- Uses a temporary working directory for build artifacts and cleans it up after execution;
- Returns compilation errors, runtime errors, timeouts, and per-test results to the assessment and guidance flows.

This is suitable for controlled course experiments. It is not a complete operating-system-level isolation solution for hostile code. A public deployment should add container or virtual-machine isolation, least-privilege accounts, network restrictions, and resource quotas.

### 2. Three-stage guided learning

CodeSense divides a programming exercise into three connected stages:

1. **Thought description**: the student describes the algorithm in natural language; the system evaluates the explanation against the assignment and provides heuristic hints.
2. **Step assembly**: the student selects or fills in program steps; the system verifies the order and content and builds a live code preview.
3. **Feynman teaching**: the student explains the program to AI roles in a multi-turn conversation, using questions and corrections to check whether the implementation is understood.

Prompt constraints and the `sanitize_response` filter are used in guided-learning flows to reduce the chance of directly returning a complete answer. AI output can still be wrong and should not replace program evaluation or teacher judgment.

### 3. Learning records and ability profiles

- Records code submissions, assessment results, hint requests, and guided-learning sessions;
- Presents information across dimensions such as algorithm, style, functionality, efficiency, and readability;
- Provides knowledge-point scores, individual trends, and class views for follow-up teaching;
- Keeps course assignment scores and ability-profile scores separate: assignment scores are currently recorded on a 0–5 scale, while ability scores use a 0–100 scale.

### 4. Teacher management

- Assignment creation, editing, test-case, and submission management;
- Class, roster, and teacher invitation workflows;
- Student completion, class statistics, knowledge-point, and ability-trend views;
- AI-assisted assignment formatting and learning suggestions;
- Separate permissions for students, teachers, and administrators.

### 5. Interaction and experience

- Browser-based code editing; pages using Monaco Editor load it on demand;
- Step selection, code preview, and conversation interactions in guided-learning pages;
- Speech-to-text and text post-processing in selected flows;
- When the public demo entry is enabled, demo business records can use an isolated temporary SQLite session instead of the formal business database.

## From submission to understanding

```mermaid
flowchart LR
    A[Assignment and learning goal] --> B[Student describes an idea]
    B --> C[Step assembly and code submission]
    C --> D[Constrained compile and run]
    D --> E[Assessment result and runtime evidence]
    E --> F[AI hints and teacher feedback]
    F --> G[Correction, explanation, and resubmission]
    G --> C
    E --> H[Ability profile and knowledge records]
    H --> I[Teacher learning view]
```

## Three-stage learning flow

```mermaid
flowchart LR
    S1[Stage 1<br/>Thought description] --> V1[Idea evaluation<br/>Heuristic hints]
    V1 --> S2[Stage 2<br/>Step or block assembly]
    S2 --> V2[Order verification<br/>Code preview]
    V2 --> S3[Stage 3<br/>Feynman teaching]
    S3 --> V3[Multi-turn dialogue<br/>Explanation and questions]
    V3 --> P[Learning records<br/>Ability profile]
```

## System architecture

```mermaid
flowchart TB
    Browser[Browser]

    subgraph Server[Flask application]
        Routes[Blueprint routes]
        Services[Business services]
        Tasks[Background task threads]
        Routes --> Services
        Services --> Tasks
    end

    DB[(SQL database)]
    Sandbox[C++17 assessment runner]
    LLM[Optional AI service<br/>Zhipu or OpenAI]
    Session[Redis or filesystem session]

    Browser -->|HTTP / SSE| Routes
    Services --> DB
    Services --> Sandbox
    Services -. AI request .-> LLM
    Tasks --> DB
    Tasks -. asynchronous AI analysis .-> LLM
    Routes --> Session
```

### Demo data boundary

```mermaid
flowchart LR
    Entry[Public demo entry] --> Demo[Demo session]
    Demo --> Temp[(Temporary SQLite database)]
    Demo -. does not write to .-> Formal[(Formal business database)]
    Demo --> Exit[Exit or timeout]
    Exit --> Cleanup[Temporary-data cleanup]
```

## Technology stack

| Layer | Current implementation |
| --- | --- |
| Web backend | Python, Flask 2.2.3, Flask-SQLAlchemy, Flask-Login, Flask-WTF |
| Data storage | SQLite by default in development; production database configured with `DATABASE_URL`, with MySQL + PyMySQL used in the project example |
| AI interfaces | Optional Zhipu and OpenAI adapters; AI-dependent features are unavailable without a configured key |
| Frontend | Jinja templates, HTML/CSS/JavaScript, Bootstrap, Monaco Editor, and Chart.js |
| Background work | In-process background threads and task queues for post-submission processing and ability analysis |
| Code execution | `g++`, C++17, temporary workspaces, compile/run timeouts, and output-length limits |

## Getting started

### Requirements

- Python 3.8 or later;
- An executable `g++` on `PATH` for C++ assessment;
- SQLite for a simple development setup, or a configured `DATABASE_URL` for production;
- A Zhipu or OpenAI API key for AI guidance, code advice, and selected learning analytics.

### 1. Install dependencies

```bash
git clone https://github.com/XiaoCow666/CodeSense.git
cd CodeSense
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure the environment

Edit `.env`. For a quick SQLite development setup, remove or comment out `DATABASE_URL` so that the `development` configuration falls back to SQLite:

```dotenv
FLASK_CONFIG=development

# SQLite development mode: remove or comment out DATABASE_URL
# DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/codesense

# Use a sufficiently random secret in production
SECRET_KEY=replace-with-a-random-secret

# Configure at least one for AI features
ZHIPU_API_KEY=
OPENAI_API_KEY=

```

The application creates database tables at startup. Production configuration requires `DATABASE_URL` and `SECRET_KEY`. Do not commit `.env`, API keys, or local database files.

### 3. Install a C++ compiler

On Windows, install MinGW or MSYS2 and add `g++` to `PATH`. On Ubuntu / Debian:

```bash
sudo apt update
sudo apt install g++
```

### 4. Start the development server

```bash
python run.py
```

Open <http://127.0.0.1:5000/login>. Without an AI key, login, basic pages, and features that do not depend on AI can still be checked locally, while AI-dependent actions will be unavailable or report a failure state.

### 5. Run tests

```bash
python -m pytest tests -q
```

Tests involving C++ assessment require `g++`. Tests that call a real AI service also require the corresponding environment configuration.

### Production entry point

Before deploying, recheck the database, secret, session, logging, reverse-proxy, and code-execution isolation settings for the target server. The WSGI object exposed by this repository is `wsgi:application`; start it with Gunicorn or another WSGI server according to the target environment.

## Configuration

| Variable | Purpose |
| --- | --- |
| `FLASK_CONFIG` | `development`, `testing`, or `production`; development is the default. |
| `DATABASE_URL` | Production database connection; can also override the development SQLite default. |
| `DEV_DATABASE_URL` | Development database connection; SQLite is used when it is unset. |
| `TEST_DATABASE_URL` | Test database connection; a separate SQLite database is used when it is unset. |
| `SECRET_KEY` | Flask session and signing key; required in production and at least 32 characters long. |
| `ZHIPU_API_KEY` / `OPENAI_API_KEY` | AI service keys; configure at least one to enable the corresponding AI features. |
| `REDIS_URL` | Optional Redis URL for session or cache-related capabilities. |

## API entry points

These are common entry points. The implementations under `routes/` are the source of truth for the complete route set.

| Path | Method | Purpose |
| --- | --- | --- |
| `/api/submit` | `POST` | Submit code and start assessment. |
| `/api/code_advice` | `POST` | Request code advice. |
| `/api/get_programming_guidance` | `POST` | Request programming guidance. |
| `/api/stream/ability-analysis` | `GET` | Stream ability analysis. |
| `/thinking/<assignment_id>` | `GET` | Open the three-stage guided-learning page. |
| `/thinking/api/stage1/submit` | `POST` | Submit the Stage 1 explanation. |
| `/thinking/api/stage2/verify` | `POST` | Verify Stage 2 step assembly. |
| `/thinking/api/stage3/chat` | `POST` | Continue the Stage 3 conversation. |

## Security boundaries and limitations

- Student code enters a constrained compile-and-run flow, but the current implementation should not be treated as a complete hostile-code isolation system; public deployments must add OS- or container-level isolation.
- Compilers, runtime dependencies, AI services, and databases can be unavailable. The UI should show a failure or retry state rather than presenting fallback text as a real AI result.
- AI output is nondeterministic. Prompt constraints and text filtering reduce the risk of answer leakage but do not replace assessment, access control, or human review.
- Production deployments must use a random `SECRET_KEY`, protected database credentials, secure session settings, and restricted access to logs, uploads, and databases.
- Never put API keys, personal data, or production database details in the repository, issues, logs, or screenshots.

## Releases and versioning

CodeSense follows semantic versioning:

- `MAJOR`: incompatible API or behavior changes;
- `MINOR`: backward-compatible feature additions;
- `PATCH`: backward-compatible fixes and small adjustments.

The current version is **`v1.0.0`**, the first formal release of the CodeSense Standard Edition. Every future release should update [CHANGELOG.md](CHANGELOG.md) and use a matching Git tag and GitHub Release. Published release records should not be silently rewritten.

## Star History

The badge above shows the repository's current star count. We are not embedding a historical chart for now: GitHub has restricted the public stargazers timeline API, and Star History notes that hosted charts may return an error page as a result. To keep this README reliable, we do not present that error page as a chart; a future trend view should be generated and stored by this repository's own Actions workflow.

- [View the CodeSense repository](https://github.com/XiaoCow666/CodeSense)
- [Star History's explanation](https://www.star-history.com/blog/github-stargazer-api-restriction/)

## Contributing

Issues and pull requests are welcome. Put changes on an independent branch and describe the changes, test results, and notes in the pull request. Merges into `main` are made after maintainer review.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for Linux, Gunicorn, Systemd, Nginx, HTTPS, MySQL, Redis, and release checks.

## License

This project is released under the [MIT License](LICENSE).

Thanks to the teachers and students who have taken part in CodeSense pilots and course practice.
