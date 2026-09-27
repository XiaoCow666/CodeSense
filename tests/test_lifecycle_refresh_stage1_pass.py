"""Regression: the lifecycle lamp must refresh when stage 1 is passed.

During a real guided-learning run the "学习会话状态" strip is populated once
at ``start_session`` and otherwise only by the manual 同步状态 button or a
tab-visibility change. After stage 1 is submitted and passed, the backend has
already moved the session to stage 2, but the strip keeps the session-start
snapshot: 服务器观察时间 frozen at 0分0秒 and 下一步 still pointing at the
stage-1 description. A student entering stage 2 is shown a backward state.

The existing read-only endpoint ``/thinking/api/session/<id>/status`` already
returns a fresh lifecycle, and ``refreshSessionLifecycle()`` already renders
it without reloads/redirects. The missing piece is one call at the stage-1
pass branch -- wiring an existing lamp, not a new mechanism.

Stdlib only (mirrors tests/test_session_lifecycle_ui.py): no Flask,
database/Redis, or application startup.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
THINKING_JS = (PROJECT_ROOT / "static" / "js" / "thinking.js").read_text(
    encoding="utf-8"
)


def _stage1_submit_handler():
    start = THINKING_JS.index("fetchAIStream('/thinking/api/stage1/submit'")
    end = THINKING_JS.index("function showScoreResult", start)
    return THINKING_JS[start:end]


def test_stage1_pass_refreshes_lifecycle_without_page_reload():
    handler = _stage1_submit_handler()
    pass_block = handler[handler.index("if (data.passed)"):]

    # The pass branch must pull the server-side stage-2 lifecycle so the
    # elapsed time and next action update at the transition.
    assert "refreshSessionLifecycle" in pass_block
    # The signal arrives in place: no reload, no navigation away from inputs.
    assert "location.reload" not in pass_block
    assert "window.location" not in pass_block


def test_stage1_lifecycle_refresh_uses_existing_status_endpoint():
    # The refreshed signal is read from the existing read-only status route;
    # the stage-1 submit response contract stays unchanged.
    start = THINKING_JS.index("function refreshSessionLifecycle")
    end = THINKING_JS.index("function init()", start)
    sync_block = THINKING_JS[start:end]
    assert "/thinking/api/session/${state.sessionId}/status" in sync_block
