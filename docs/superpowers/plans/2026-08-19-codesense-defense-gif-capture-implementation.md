# CodeSense 答辩核心 GIF 录制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 Flask 环境中构建一套可重复运行的录制工具，自动生成学生端、教师端、能力评测、风险提示和长页面巡览的 14 条答辩 GIF，并输出 MP4、PNG、元数据和校验报告。

**Architecture:** 使用 Python Playwright 驱动 Chromium，使用隔离 SQLite 数据库和固定演示数据，使用浏览器路由拦截异步 AI/SSE 接口。Playwright 先保存 30 FPS WebM，FFmpeg 再转成 1120×630 的 12 FPS GIF 和 MP4，校验器检查媒体文件及关键页面状态。

**Tech Stack:** Flask 2.2、SQLAlchemy、Python Playwright、PyYAML、Chromium、FFmpeg、pytest/unittest。

## Global Constraints

- 录制只连接本地 Flask 服务，不读取生产数据或真实用户账号。
- 完整素材包必须覆盖 14 个编号：S01–S09、T01–T05。
- 浏览器视口固定为 `1280×720`，原始录制为 30 FPS WebM。
- GIF 主规格为 12 FPS、`1120×630`；超过 8 MB 时降为 `960×540`，并在报告中标记。
- 输出目录固定为 `E:\CodeSense\outputs\codesense-defense-gifs\`。
- 固定学生、教师、班级、作业、提交、能力评分和风险状态由独立 SQLite 数据库提供。
- S08、T03 以及其他异步 AI 页面使用本地固定响应，不调用外部大模型 API。
- Chart.js、marked、Bootstrap 等页面依赖在录制前进入本地缓存；缓存缺失时直接失败。
- 正式页面只允许增加测试所需的最小稳定定位标记，不做无关重构或视觉改版。
- 每个任务先写可独立运行的测试，再实现最小代码并提交一次。

---

### Task 1: 建立录制包、类型和 14 条素材清单

**Files:**
- Create: `requirements-capture.txt`
- Create: `scripts/demo_capture/__init__.py`
- Create: `scripts/demo_capture/types.py`
- Create: `scripts/demo_capture/manifest.py`
- Create: `scripts/demo_capture/manifest.yaml`
- Create: `tests/test_demo_capture_manifest.py`

**Interfaces:**
- `FlowSpec`: 不可变数据类，字段为 `id: str`、`role: str`、`route: str`、`mode: str`、`fixture: str`、`actions: tuple[dict, ...]`、`ready: tuple[dict, ...]`、`output: str`。
- `load_manifest(path: Path) -> dict[str, FlowSpec]`：读取 YAML，按素材编号返回流程。
- `validate_manifest(flows: Mapping[str, FlowSpec]) -> None`：发现重复编号、非法角色、非法模式、空路由或重复输出名时抛出 `ValueError`。
- `select_flows(flows: Mapping[str, FlowSpec], ids: Sequence[str] | None, role: str | None) -> list[FlowSpec]`：按编号或角色筛选，保持清单顺序。

**Implementation details:**
- `requirements-capture.txt` 添加 `playwright>=1.40,<2` 和 `PyYAML>=6.0,<7`；FFmpeg 作为外部命令由预检器检查，不放入 Python 依赖。
- `manifest.yaml` 写入 S01–S09、T01–T05，使用设计文档中的路由、模式和输出名。
- S05–S07 共用 `/thinking/<assignment_id>`，通过 `stage` 字段区分第一、第二、第三阶段。
- S09、T02、T04 的 `mode` 为 `page_tour`，其余为 `interaction`。

- [ ] **Step 1: 写清单解析的失败测试**

```python
from pathlib import Path

from scripts.demo_capture.manifest import load_manifest, select_flows


MANIFEST = Path("scripts/demo_capture/manifest.yaml")


def test_manifest_contains_all_defense_flows():
    flows = load_manifest(MANIFEST)
    assert list(flows) == [
        "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09",
        "T01", "T02", "T03", "T04", "T05",
    ]
    assert flows["S08"].mode == "interaction"
    assert flows["T04"].mode == "page_tour"


def test_select_flows_filters_by_role_and_id():
    flows = load_manifest(MANIFEST)
    assert [flow.id for flow in select_flows(flows, None, "student")] == [
        "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09"
    ]
    assert [flow.id for flow in select_flows(flows, ["T04", "S08"], None)] == ["S08", "T04"]
```

- [ ] **Step 2: 运行测试，确认当前模块缺失**

Run: `python -m pytest tests/test_demo_capture_manifest.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing manifest implementation.

- [ ] **Step 3: 实现 `FlowSpec`、YAML 读取、校验和筛选**

使用 `yaml.safe_load`，把 `actions` 和 `ready` 转成 tuple，按 YAML 中的顺序写入有序字典。对清单中的 14 个编号运行 `validate_manifest`，让启动阶段即可发现配置错误。

- [ ] **Step 4: 运行单元测试**

Run: `python -m pytest tests/test_demo_capture_manifest.py -q`

Expected: PASS，至少 2 个测试通过。

- [ ] **Step 5: 提交**

```bash
git add requirements-capture.txt scripts/demo_capture tests/test_demo_capture_manifest.py
git commit -m "feat: add defense capture manifest"
```

### Task 2: 增加录制模式和隔离演示数据

**Files:**
- Modify: `app.py`，在 `create_app()` 的会话初始化和异步任务初始化处增加 `CAPTURE_MODE` 分支。
- Create: `scripts/demo_capture/fixtures/__init__.py`
- Create: `scripts/demo_capture/fixtures/seed_demo.py`
- Create: `scripts/demo_capture/fixtures/data.py`
- Create: `tests/demo_capture_test_utils.py`
- Create: `tests/test_demo_capture_fixtures.py`
- Create: `tests/test_capture_submit_route.py`
- Create: `tests/test_capture_mode.py`

**Interfaces:**
- `DemoIds`: 不可变数据类，字段为 `student_username`、`teacher_username`、`student_password`、`teacher_password`、`class_id`、`assignment_id`、`submission_id`、`risk_student_ids`。
- `seed_demo_data() -> DemoIds`：在当前 Flask 应用上下文中清空并写入演示数据，返回后续流程所需的数据库 ID。
- `seed_database(db_path: Path) -> DemoIds`：命令行入口，设置 `TEST_DATABASE_URL` 后创建测试应用、建表、播种数据并输出 JSON ID 文件。
- `capture_mode_enabled() -> bool`：只从 `CAPTURE_MODE` 读取 `1/true/yes`。
- `build_capture_test_app(db_path: Path) -> tuple[Flask, DemoIds]`：测试辅助函数，使用指定 SQLite 文件创建测试应用并播种数据，不读取开发数据库。

**Implementation details:**
- 录制进程使用 `FLASK_CONFIG=testing`、`TEST_DATABASE_URL`、`SECRET_KEY=capture-test-key`、`LOAD_LOCAL_MODEL=False`、`CAPTURE_MODE=1` 和 `FLASK_DEBUG=False`。
- `CAPTURE_MODE=1` 时，`app.py` 使用文件系统会话，不连接 Redis；不启动 `utils.async_tasks.init_async_tasks`，异步页面由浏览器路由桩提供响应。
- 数据只写入运行目录中的 SQLite 文件，不修改 `instance/` 中的开发数据库。
- 演示数据至少包含：学生 `demo_student`、教师 `demo_teacher`、一个示例班级、一个 C 语言作业、一个已提交记录、一个待关注学生、低分和未提交状态、五维能力评分、知识点评分，以及一个 `status="ready"` 的 `AssignmentThinkingPreset`，其中写入 `key_steps`、`code_blocks`、`noise_blocks`、`quiz_steps` 和 `algorithm_summary`。
- 密码使用 `werkzeug.security.generate_password_hash`，不在模板或日志中输出明文密码。
- `seed_demo.py` 必须在导入 `app` 前解析 `--db` 参数并设置环境变量，避免 `TestingConfig` 提前读取错误的数据库路径。
- `routes/assignments.py` 在 `CAPTURE_MODE=1` 且提交记录已写入后，跳过真实异步评测，直接跳转到 `evaluating_submission`；这样 S03 可以展示评测等待状态，S04 使用预置的已完成提交详情。

- [ ] **Step 1: 写演示数据契约测试**

```python
def test_seed_demo_data_contains_both_roles_and_risk_states(app):
    with app.app_context():
        ids = seed_demo_data()
        assert ids.student_username == "demo_student"
        assert ids.teacher_username == "demo_teacher"
        assert ids.assignment_id > 0
        assert ids.submission_id > 0
        assert ids.risk_student_ids

        student = User.query.filter_by(username="demo_student").one()
        teacher = User.query.filter_by(username="demo_teacher").one()
        assert student.usertype == "学生"
        assert teacher.usertype == "教师"
        assert KnowledgePointScore.query.count() >= 5
        assert AssignmentThinkingPreset.query.filter_by(
            assignment_id=ids.assignment_id, status="ready"
        ).count() == 1
```

- [ ] **Step 2: 运行测试，确认播种函数尚未存在**

Run: `python -m pytest tests/test_demo_capture_fixtures.py -q`

Expected: FAIL because `seed_demo_data` is not implemented.

- [ ] **Step 3: 写录制模式配置测试**

```python
def test_capture_mode_uses_filesystem_session(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPTURE_MODE", "1")
    monkeypatch.setenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'capture.db'}")
    from config import TestingConfig
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'capture.db'}")
    from app import create_app
    app = create_app("testing")
    assert app.config["CAPTURE_MODE"] is True
    assert app.config["SESSION_TYPE"] == "filesystem"
```

- [ ] **Step 4: 实现配置分支和固定数据播种**

在 `create_app()` 中保留默认 Redis 路径，仅在 `CAPTURE_MODE` 下跳过 Redis 探测并关闭后台异步任务。`seed_demo_data()` 只使用 `models.py` 中已有的 `User`、`Class`、`Assignment`、`TestCase`、`Submission`、`KnowledgePointScore`、`AbilityTrend` 和 `AssignmentThinkingPreset` 模型，不修改模型字段。

- [ ] **Step 5: 验证录制模式下提交不启动真实评测**

```python
def test_capture_submit_redirects_to_evaluating_without_async_worker(tmp_path):
    app, ids = build_capture_test_app(tmp_path / "capture.db")
    client = app.test_client()
    client.post("/login", data={"username": "demo_student", "password": "student123"})
    response = client.post(
        f"/submit/{ids.assignment_id}",
        data={"code": "int main(){return 0;}", "language": "cpp"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/submission/" in response.headers["Location"]
    assert response.headers["Location"].endswith("/evaluating")
```

- [ ] **Step 6: 运行测试**

Run: `python -m pytest tests/test_demo_capture_fixtures.py tests/test_capture_submit_route.py tests/test_capture_mode.py -q`

Expected: PASS，数据库中存在两个角色、一个作业、一个提交和风险数据。

- [ ] **Step 7: 提交**

```bash
git add app.py routes/assignments.py scripts/demo_capture/fixtures tests/test_demo_capture_fixtures.py tests/test_capture_submit_route.py tests/test_capture_mode.py
git commit -m "feat: add isolated capture demo data"
```

### Task 3: 实现静态资源缓存和浏览器 API 桩

**Files:**
- Create: `scripts/demo_capture/assets.py`
- Create: `scripts/demo_capture/stubs.py`
- Create: `tests/test_demo_capture_assets.py`
- Create: `tests/test_demo_capture_stubs.py`

**Interfaces:**
- `AssetEntry`: 数据类，字段为 `url: str`、`path: Path`、`content_type: str`、`sha256: str`。
- `AssetManifest`: 数据类，字段为 `entries: tuple[AssetEntry, ...]` 和 `created_at: str`。
- `discover_external_assets(template_root: Path) -> tuple[str, ...]`：扫描答辩涉及模板中的 CDN URL，去重并保持出现顺序。
- `prepare_asset_cache(template_root: Path, cache_dir: Path, refresh: bool) -> AssetManifest`：下载或读取缓存文件，生成带 SHA-256 的清单；缺失且 `refresh=False` 时抛出 `AssetCacheError`。
- `install_asset_routes(context: BrowserContext, manifest: AssetManifest) -> None`：把 CDN URL 映射到本地缓存文件。
- `install_api_stubs(context: BrowserContext, ids: DemoIds) -> None`：安装评测、能力分析、三阶段学习和教师建议的固定 API 响应。
- `sse_body(events: Sequence[dict[str, object]]) -> str`：把事件编码成合法的 `text/event-stream` 内容，每个事件以空行分隔。

**Implementation details:**
- 缓存目录使用 `E:\CodeSense\outputs\codesense-defense-gifs\asset-cache\`，清单记录 URL、文件路径、内容类型和 SHA-256。
- 只缓存模板实际引用的 Chart.js、marked、Bootstrap、Bootstrap Icons、Markdown CSS 和其他答辩页面依赖；不把接口响应当作静态资源缓存。
- API 桩只拦截 `/api/` 和 `/thinking/api/` 端点，不拦截页面路由。对异步结果返回固定进度、雷达图数据、AI 分析文本、阶段验证结果和教师风险建议。
- `/api/stream/ability-analysis` 返回 `progress`、`knowledge_profile`、`analysis_section` 和 `complete` 事件。
- `/api/teacher/stream_suggestions` 返回重点关注学生、薄弱知识点、补练作业和诊断报告。
- 提交和三阶段接口返回与 `DemoIds` 对应的固定提交 ID，确保 S03–S08 可以从同一套演示数据继续播放。

- [ ] **Step 1: 写资源扫描和 SSE 编码测试**

```python
def test_discover_external_assets_deduplicates_urls(tmp_path):
    template = tmp_path / "page.html"
    template.write_text(
        '<script src="https://cdn.example/chart.js"></script>'
        '<script src="https://cdn.example/chart.js"></script>',
        encoding="utf-8",
    )
    assert discover_external_assets(tmp_path) == ("https://cdn.example/chart.js",)


def test_sse_body_separates_events_with_blank_lines():
    body = sse_body([{"type": "progress", "percent": 50}, {"type": "complete"}])
    assert 'data: {"type": "progress", "percent": 50}' in body
    assert body.endswith("\n\n")
```

- [ ] **Step 2: 运行测试，确认资源模块尚未实现**

Run: `python -m pytest tests/test_demo_capture_assets.py tests/test_demo_capture_stubs.py -q`

Expected: FAIL with missing module or missing function.

- [ ] **Step 3: 实现缓存清单、路由映射和 API 桩**

所有缓存文件写入临时文件后再替换目标文件，避免中断时留下半个资源。API 桩统一使用 `route.fulfill`，响应头明确设置 `application/json` 或 `text/event-stream`。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_demo_capture_assets.py tests/test_demo_capture_stubs.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/demo_capture/assets.py scripts/demo_capture/stubs.py tests/test_demo_capture_assets.py tests/test_demo_capture_stubs.py
git commit -m "feat: add deterministic capture assets and API stubs"
```

### Task 4: 实现本地 Flask 服务生命周期

**Files:**
- Create: `scripts/demo_capture/server.py`
- Create: `tests/test_demo_capture_server.py`

**Interfaces:**
- `ServerHandle`: 数据类，字段为 `base_url: str`、`process: subprocess.Popen`、`db_path: Path`、`run_dir: Path`，提供 `stop() -> None`。
- `start_local_server(run_dir: Path, python_executable: str = sys.executable) -> ServerHandle`：创建数据库、播种数据、启动 Flask 子进程并等待 `/login` 返回 200。
- `wait_until_ready(base_url: str, timeout_seconds: float = 30.0) -> None`：每 0.25 秒轮询健康页面，超时抛出 `ServerStartError` 并附带最近 80 行进程输出。

**Implementation details:**
- 运行目录形如 `E:\CodeSense\outputs\codesense-defense-gifs\runs\<timestamp>-<uuid>\`，其中保存 SQLite 文件、服务日志和原始 WebM。
- 使用空闲 TCP 端口，环境变量设置为 `HOST=127.0.0.1`、`PORT=<port>`、`FLASK_CONFIG=testing`、`TEST_DATABASE_URL=sqlite:///...`、`CAPTURE_MODE=1` 和 `FLASK_DEBUG=False`。
- 先调用 `seed_database`，再启动 `python app.py`，避免页面启动后先显示空数据库。
- `stop()` 必须先 `terminate()`，等待 5 秒，仍未退出时调用 `kill()`，并关闭 stdout/stderr 文件句柄。
- 启动失败时不删除运行目录，保留日志供报告引用。

- [ ] **Step 1: 写服务句柄和超时行为测试**

```python
def test_wait_until_ready_raises_after_timeout(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "scripts.demo_capture.server.requests.get",
        lambda *a, **k: SimpleNamespace(status_code=503),
    )
    with pytest.raises(ServerStartError, match="timed out"):
        wait_until_ready("http://127.0.0.1:9", timeout_seconds=0.01)
```

- [ ] **Step 2: 运行测试，确认服务模块尚未实现**

Run: `python -m pytest tests/test_demo_capture_server.py -q`

Expected: FAIL with missing module or missing exception.

- [ ] **Step 3: 实现启动、健康检查和清理**

使用 `subprocess.Popen(..., cwd=source_root, env=env, stdout=log_file, stderr=subprocess.STDOUT)`，不要调用 `shell=True`。健康检查使用已存在的 `/login` 页面，不能依赖需要登录的路由。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_demo_capture_server.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/demo_capture/server.py tests/test_demo_capture_server.py
git commit -m "feat: manage local capture server"
```

### Task 5: 实现媒体编码、压缩降级和校验器

**Files:**
- Create: `scripts/demo_capture/media.py`
- Create: `scripts/demo_capture/validator.py`
- Create: `tests/test_demo_capture_media.py`
- Create: `tests/test_demo_capture_validator.py`

**Interfaces:**
- `CaptureProfile`: 数据类，字段为 `width: int`、`height: int`、`fps: int`、`max_bytes: int`。
- `MediaInfo`: 数据类，字段为 `source: Path`、`mp4: Path`、`gif: Path`、`poster: Path`、`width: int`、`height: int`、`fps: float`、`duration_seconds: float`、`frame_count: int`、`compression_fallback: bool`。
- `PRIMARY_GIF_PROFILE = CaptureProfile(1120, 630, 12, 8_000_000)`。
- `FALLBACK_GIF_PROFILE = CaptureProfile(960, 540, 12, 8_000_000)`。
- `encode_capture(source: Path, mp4: Path, gif: Path, poster: Path, ffmpeg_bin: str = "ffmpeg") -> MediaInfo`。
- `validate_media(flow: FlowSpec, media: MediaInfo) -> list[str]`：返回错误列表，空列表表示通过。
- `should_use_fallback(gif_path: Path) -> bool`：GIF 大于 8 MB 时返回 True。

**Implementation details:**
- MP4 使用 H.264 编码，GIF 使用 12 FPS、Lanzcos 缩放和 128 色调色板。
- 主 GIF 过滤链固定为：

```text
fps=12,scale=1120:630:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=sierra2_4a
```

- 超过 8 MB 时用 `960:540` 重新编码，并将 `compression_fallback=true` 写入 JSON 元数据。
- 首帧 PNG 使用 FFmpeg 的 `-frames:v 1` 生成，不依赖 Pillow。
- 校验器调用 `ffprobe` 检查宽高、时长和帧数；如果本机没有 FFmpeg，预检阶段返回明确安装提示。

- [ ] **Step 1: 写纯函数测试**

```python
def test_primary_profile_is_16_by_9():
    assert PRIMARY_GIF_PROFILE.width == 1120
    assert PRIMARY_GIF_PROFILE.height == 630
    assert PRIMARY_GIF_PROFILE.fps == 12


def test_large_gif_requests_fallback(tmp_path):
    gif = tmp_path / "large.gif"
    gif.write_bytes(b"0" * 8_000_001)
    assert should_use_fallback(gif) is True
```

- [ ] **Step 2: 运行测试，确认媒体模块尚未实现**

Run: `python -m pytest tests/test_demo_capture_media.py tests/test_demo_capture_validator.py -q`

Expected: FAIL with missing module or missing profile.

- [ ] **Step 3: 实现 FFmpeg 命令、降级重编码和 ffprobe 校验**

所有外部命令使用参数列表调用 `subprocess.run(..., check=True)`，捕获 stderr，并在异常中附带完整命令和 stderr 最后 40 行。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_demo_capture_media.py tests/test_demo_capture_validator.py -q`

Expected: PASS；若机器没有 FFmpeg，媒体集成测试标记为 skip，纯函数测试仍必须通过。

- [ ] **Step 5: 提交**

```bash
git add scripts/demo_capture/media.py scripts/demo_capture/validator.py tests/test_demo_capture_media.py tests/test_demo_capture_validator.py
git commit -m "feat: encode and validate defense media"
```

### Task 6: 实现动作执行器、等待条件和录制报告

**Files:**
- Create: `scripts/demo_capture/actions.py`
- Create: `scripts/demo_capture/report.py`
- Create: `tests/test_demo_capture_actions.py`
- Create: `tests/test_demo_capture_report.py`

**Interfaces:**
- `execute_action(page: Page, action: Mapping[str, object], ids: DemoIds) -> None`：支持 `goto`、`fill`、`click`、`wait_for_url`、`wait_for_selector`、`wait_for_text`、`pause`、`set_editor_content`、`scroll_section`、`scroll_to_bottom`。
- `wait_until_ready(page: Page, checks: Sequence[Mapping[str, object]]) -> None`：支持 selector、text、URL、canvas-size 和 scroll-bottom 检查。
- `run_action_list(page: Page, actions: Sequence[Mapping[str, object]], ids: DemoIds) -> None`：按清单顺序执行并在失败时附加动作编号。
- `CaptureResult`: 数据类，字段为 `flow_id`、`status`、`files`、`error`、`duration_seconds`。
- `CaptureActionError`: `RuntimeError` 子类，消息必须包含从 1 开始的动作编号和原始异常。
- `write_report(results: Sequence[CaptureResult], path: Path) -> None`：输出 JSON 报告和一份 Markdown 汇总。

**Implementation details:**
- 所有 selector 支持 `{assignment_id}`、`{submission_id}` 和 `{class_id}` 占位符，执行前使用 `DemoIds` 替换。
- `set_editor_content` 先点击 `.monaco-editor textarea`，执行 `Control+A`，再输入固定 C 代码；如果 Monaco 不可用，抛出明确错误，不直接写隐藏表单。
- `scroll_section` 使用 `locator.scroll_into_view_if_needed()`，再等待 0.8 秒；`scroll_to_bottom` 使用 `page.mouse.wheel` 分段滚动并最终检查 `scrollY + innerHeight >= scrollHeight - 4`。
- `run_action_list` 不吞异常；runner 捕获异常后保存页面截图、HTML 和控制台日志。
- 报告同时记录缓存版本、演示数据版本、Git commit、浏览器版本和 FFmpeg 版本。

- [ ] **Step 1: 写动作分派和滚动完成条件测试**

```python
def test_scroll_bottom_check_uses_four_pixel_tolerance():
    page = MagicMock()
    page.evaluate.return_value = True
    wait_until_ready(page, [{"kind": "scroll_bottom"}])
    page.evaluate.assert_called_once()


def test_unknown_action_reports_action_index():
    page = MagicMock()
    with pytest.raises(CaptureActionError, match="action 2"):
        run_action_list(page, [{"kind": "pause", "seconds": 0}, {"kind": "bad"}], object())
```

- [ ] **Step 2: 运行测试，确认动作模块尚未实现**

Run: `python -m pytest tests/test_demo_capture_actions.py tests/test_demo_capture_report.py -q`

Expected: FAIL with missing action implementation.

- [ ] **Step 3: 实现动作和等待条件**

对页面操作使用 Playwright 的 locator API；固定等待只允许用于 GIF 节奏，页面完成状态必须使用 selector、文本、URL 或页面计算值判断。

- [ ] **Step 4: 实现报告写入和失败附件路径**

报告使用 UTF-8 JSON，`files` 保存绝对路径，`error` 保存异常类型和消息；Markdown 汇总按通过、失败分组。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest tests/test_demo_capture_actions.py tests/test_demo_capture_report.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/demo_capture/actions.py scripts/demo_capture/report.py tests/test_demo_capture_actions.py tests/test_demo_capture_report.py
git commit -m "feat: execute capture actions and write reports"
```

### Task 7: 实现浏览器上下文和学生端 S01–S09

**Files:**
- Create: `scripts/demo_capture/browser.py`
- Create: `scripts/demo_capture/flows/student_flows.py`
- Create: `tests/test_demo_capture_student_flows.py`
- Modify only if required for stable selectors: `templates/components/code_editor_new.html`、`templates/student_home.html`、`templates/profile.html`、`templates/thinking/arena.html`。

**Interfaces:**
- `create_recording_context(browser: Browser, run_dir: Path) -> BrowserContext`：固定 `1280×720`、`device_scale_factor=1`、`locale="zh-CN"`、`timezone_id="Asia/Shanghai"`，设置 `record_video_dir`。
- `login_as(page: Page, username: str, password: str, expected_path: str) -> None`。
- `run_student_flow(flow: FlowSpec, page: Page, ids: DemoIds) -> None`。
- `STUDENT_FLOW_IDS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09")`。

**Flow details:**
- S01 使用 `#username`、`#password` 和登录按钮，等待跳转到学生首页。
- S02 从学生首页进入作业列表，再打开固定作业详情。
- S03 使用 Monaco 编辑器输入固定 C 代码，点击 `#submit-code-btn`，等待提交状态。
- S04 打开固定提交详情，等待运行结果、评分和 AI 反馈区域。
- S05 使用 `#description-input` 和 `#stage1-submit`，等待 `#score-result`。
- S06 等待 `#stage2-quiz-container`，选择固定步骤并调用验证按钮，等待代码预览。
- S07 使用 `#teacher-chat-input` 或 `#student-chat-input`，发送固定解释，等待对话消息出现。
- S08 等待 `#knowledgeRadarChart`、`#analysis-progress` 和 `#analysis-status-badge` 完成，并停留在雷达图与分析输出。
- S09 点击 `a[href="#statistics"]`，依次巡览统计卡片、`#abilityChart` 和 `#submissionTrendChart`，最后到达页尾。

- [ ] **Step 1: 写学生流程契约测试**

```python
def test_student_flow_ids_match_manifest():
    flows = load_manifest(Path("scripts/demo_capture/manifest.yaml"))
    assert tuple(flow_id for flow_id in flows if flow_id.startswith("S")) == STUDENT_FLOW_IDS


def test_student_manifest_has_required_ready_selectors():
    flows = load_manifest(Path("scripts/demo_capture/manifest.yaml"))
    assert "#knowledgeRadarChart" in repr(flows["S08"].ready)
    assert "#abilityChart" in repr(flows["S09"].ready)
```

- [ ] **Step 2: 运行测试，确认学生流程未注册**

Run: `python -m pytest tests/test_demo_capture_student_flows.py -q`

Expected: FAIL because browser/flow registration is missing.

- [ ] **Step 3: 实现浏览器上下文、学生登录和 S01–S09 动作**

每条流程使用新的 context；S03 的编辑器输入、S06 的步骤选择和 S07 的对话发送使用专用 hook，普通点击和滚动继续由 `actions.py` 处理。

- [ ] **Step 4: 仅在 selector 缺失时增加 `data-capture` 标记**

标记只放在编辑器根节点、阶段容器和统计图表容器，不改变 CSS、文案和业务行为。新增标记必须在模板测试中断言一次。

- [ ] **Step 5: 运行学生单元测试**

Run: `python -m pytest tests/test_demo_capture_student_flows.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/demo_capture/browser.py scripts/demo_capture/flows/student_flows.py templates/components/code_editor_new.html templates/student_home.html templates/profile.html templates/thinking/arena.html tests/test_demo_capture_student_flows.py
git commit -m "feat: add student defense capture flows"
```

### Task 8: 实现教师端 T01–T05

**Files:**
- Create: `scripts/demo_capture/flows/teacher_flows.py`
- Create: `tests/test_demo_capture_teacher_flows.py`
- Modify only if required for stable selectors: `templates/teacher_home.html`、`templates/classes/class_detail.html`、`templates/teacher_ai_suggestions.html`。

**Interfaces:**
- `run_teacher_flow(flow: FlowSpec, page: Page, ids: DemoIds) -> None`。
- `TEACHER_FLOW_IDS = ("T01", "T02", "T03", "T04", "T05")`。

**Flow details:**
- T01 以教师账号进入 `/teacher_dashboard`，先停留在“今日需要关注”，点击低分或未提交学生 chip，再等待学生详情页。
- T02 从教师首页顶部开始，依次经过关注项、AI 个性化建议、近 14 天提交趋势、班级人数和平均分图表，最终到页尾。
- T03 打开 `/teacher/ai_suggestions`，点击 `.btn-refresh-sug`，等待重点关注学生、薄弱知识点和诊断报告出现。
- T04 打开固定班级详情，巡览作业进度、注册进度和学生表格，确认风险标签列可见并到达页尾。
- T05 以教师身份打开固定提交详情，停留在代码、评测结果和反馈区。

- [ ] **Step 1: 写教师流程契约测试**

```python
def test_teacher_flow_ids_match_manifest():
    flows = load_manifest(Path("scripts/demo_capture/manifest.yaml"))
    assert tuple(flow_id for flow_id in flows if flow_id.startswith("T")) == TEACHER_FLOW_IDS


def test_teacher_risk_tour_requires_risk_tags():
    flows = load_manifest(Path("scripts/demo_capture/manifest.yaml"))
    assert "risk" in repr(flows["T04"].ready).lower()
```

- [ ] **Step 2: 运行测试，确认教师流程未实现**

Run: `python -m pytest tests/test_demo_capture_teacher_flows.py -q`

Expected: FAIL because teacher flow registration is missing.

- [ ] **Step 3: 实现 T01–T05 和教师巡览停留点**

风险页使用现有“未提交、低分、长期未活跃、未注册”文案和风险标签；AI 建议页使用浏览器 API 桩，不触发真实 API。

- [ ] **Step 4: 仅在 selector 缺失时增加捕获标记**

优先复用 `.dashboard-section`、`.attention-card`、`.risk-tags`、`.btn-refresh-sug` 和现有链接，不为录制引入新的可见组件。

- [ ] **Step 5: 运行教师单元测试**

Run: `python -m pytest tests/test_demo_capture_teacher_flows.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/demo_capture/flows/teacher_flows.py templates/teacher_home.html templates/classes/class_detail.html templates/teacher_ai_suggestions.html tests/test_demo_capture_teacher_flows.py
git commit -m "feat: add teacher risk and analytics capture flows"
```

### Task 9: 组装 CLI、单条重录和使用文档

**Files:**
- Create: `scripts/demo_capture/runner.py`
- Create: `scripts/demo_capture/README.md`
- Create: `tests/test_demo_capture_cli.py`

**Interfaces:**
- `main(argv: Sequence[str] | None = None) -> int`：支持 `--all`、`--id S08`、`--id T01,T02,T04`、`--role student|teacher`、`--output-dir`、`--base-url`、`--no-server`、`--refresh-assets`。
- `CaptureSelection`: 数据类，字段为 `ids: tuple[str, ...] | None`、`role: str | None`、`output_dir: Path | None`、`base_url: str | None`、`start_server: bool`、`refresh_assets: bool`。
- `run_selected_flows(selection: CaptureSelection) -> list[CaptureResult]`：启动服务、加载缓存、运行浏览器流程、编码媒体并写报告。

**Implementation details:**
- 默认从 `Path(__file__).resolve().parents[3] / "outputs" / "codesense-defense-gifs"` 计算输出目录，不依赖当前 shell 工作目录。
- `--id` 和 `--role` 互斥时返回 exit code 2；不存在的编号显示可用编号。
- 默认执行完整流程并在一个 runner 运行目录中保存 raw、media 和 report；`--no-server` 用于连接用户已启动的本地 Flask 服务，但仍使用固定的 `--base-url`。
- 任意一条失败都写入报告；`--all` 最终返回 1，单条成功返回 0。
- README 写明 Python 依赖安装、`python -m playwright install chromium`、FFmpeg 检查、资源缓存、完整录制、单条重录和常见失败原因。

- [ ] **Step 1: 写 CLI 参数测试**

```python
def test_cli_rejects_unknown_flow_id(capsys):
    assert main(["--id", "S99"]) == 2
    assert "S99" in capsys.readouterr().err


def test_cli_help_is_available(capsys):
    assert main(["--help"]) == 0
    assert "--all" in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试，确认 CLI 尚未实现**

Run: `python -m pytest tests/test_demo_capture_cli.py -q`

Expected: FAIL because `runner.py` is missing.

- [ ] **Step 3: 实现 CLI 和主流程编排**

编排顺序固定为：预检依赖 → 解析清单 → 创建运行目录 → 启动/连接服务 → 准备资源缓存 → 安装 API 桩 → 运行流程 → 编码媒体 → 校验 → 写报告 → 清理服务。

- [ ] **Step 4: 编写 README 并运行 CLI 单元测试**

Run: `python -m pytest tests/test_demo_capture_cli.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/demo_capture/runner.py scripts/demo_capture/README.md tests/test_demo_capture_cli.py
git commit -m "feat: add defense capture CLI"
```

### Task 10: 完成端到端烟测和全量验收

**Files:**
- Create: `tests/test_demo_capture_e2e.py`
- Modify: `scripts/demo_capture/README.md`，补充实际运行结果和故障定位示例。

**Interfaces:**
- `run_capture_e2e(flow_ids: Sequence[str]) -> list[CaptureResult]`：在临时输出目录运行真实 Chromium 录制，供测试和人工验收复用。

**Implementation details:**
- 端到端测试默认 skip，只有设置 `RUN_CAPTURE_E2E=1` 且本机存在 Chromium、FFmpeg 时才运行，避免普通单元测试启动 Flask 和浏览器。
- 第一轮只跑 S08、T01、T04，覆盖学生能力评测、教师风险提示和长页面滚动。
- 第二轮执行全部 14 条并检查 `reports/summary.json` 中全部状态为 `passed`。
- 打开生成的 contact sheet 或逐条查看 PNG 首帧，确认没有空白图表、异常弹窗、敏感真实数据和浏览器地址栏。
- 对 GIF 使用 `ffprobe` 检查 16:9、时长和帧数；对超过 8 MB 的条目确认报告包含 `compression_fallback=true`。

- [ ] **Step 1: 写默认跳过的 E2E 测试入口**

```python
@pytest.mark.skipif(os.getenv("RUN_CAPTURE_E2E") != "1", reason="set RUN_CAPTURE_E2E=1")
def test_capture_visual_smoke_for_student_ability_and_teacher_risk():
    results = run_selected_flows(CaptureSelection(ids=("S08", "T01", "T04")))
    assert [result.status for result in results] == ["passed", "passed", "passed"]
```

- [ ] **Step 2: 运行普通测试套件**

Run: `python -m pytest tests/test_demo_capture_manifest.py tests/test_demo_capture_fixtures.py tests/test_capture_mode.py tests/test_demo_capture_assets.py tests/test_demo_capture_stubs.py tests/test_demo_capture_server.py tests/test_demo_capture_media.py tests/test_demo_capture_validator.py tests/test_demo_capture_actions.py tests/test_demo_capture_report.py tests/test_demo_capture_student_flows.py tests/test_demo_capture_teacher_flows.py tests/test_demo_capture_cli.py -q`

Expected: PASS；没有浏览器或 FFmpeg 的机器只跳过明确标记的媒体集成检查。

- [ ] **Step 3: 安装录制依赖并执行三条烟测**

```bash
pip install -r requirements-capture.txt
python -m playwright install chromium
ffmpeg -version
python scripts/demo_capture/runner.py --id S08,T01,T04
```

Expected: 输出 3 条 GIF、3 条 MP4、3 张 PNG 和一份通过报告。

- [ ] **Step 4: 执行全量录制**

```bash
python scripts/demo_capture/runner.py --all
```

Expected: S01–S09、T01–T05 全部通过，报告显示 14/14，输出目录含 GIF、MP4、PNG、JSON 元数据和日志。

- [ ] **Step 5: 运行完整项目测试**

Run: `python -m pytest -q`

Expected: 现有测试和录制相关测试全部通过；若既有测试因环境缺少外部服务失败，记录原始失败信息，不修改与录制无关的业务代码。

- [ ] **Step 6: 提交最终验收记录**

```bash
git add tests/test_demo_capture_e2e.py scripts/demo_capture/README.md
git commit -m "test: verify defense GIF capture pipeline"
```

## 完成定义

- `docs/superpowers/specs/2026-08-19-codesense-defense-gif-capture-design.md` 中的 14 条素材均有对应 manifest、动作和 ready 条件。
- `python scripts/demo_capture/runner.py --id S08,T01,T04` 能在本地生成并校验三条代表性素材。
- `python scripts/demo_capture/runner.py --all` 能生成 14 条素材并返回成功状态。
- 失败时有截图、HTML、控制台日志、原始 WebM 和报告，不会留下无声无内容的“成功” GIF。
- 当前工作区中原有的 `.claude/settings.local.json`、`static/images/generated/` 和 `static/uploads/` 变更不被暂存或覆盖。
