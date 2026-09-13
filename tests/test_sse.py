import json

from flask import Flask

from utils.sse import (
    sse_blocking_events,
    sse_event,
    sse_response,
    sse_text_events,
    stream_text_chunks,
    wants_sse,
)


def test_wants_sse_requires_explicit_request():
    app = Flask(__name__)
    with app.test_request_context("/answer"):
        assert wants_sse() is False
    with app.test_request_context(
        "/answer", headers={"Accept": "text/event-stream"}
    ):
        assert wants_sse() is True
    with app.test_request_context("/answer?stream=1"):
        assert wants_sse() is True


def test_sse_event_is_json_and_utf8_safe():
    raw = sse_event({"type": "delta", "content": "你好"})
    assert raw.startswith("data: ")
    assert raw.endswith("\n\n")
    assert json.loads(raw.removeprefix("data: ").strip())["content"] == "你好"


def test_sse_text_events_include_incremental_and_final_payload():
    body = "".join(sse_text_events(["第一段", "第二段"], start_message="开始"))
    events = [
        json.loads(part.removeprefix("data: ").strip())
        for part in body.strip().split("\n\n")
    ]
    assert events[0] == {"type": "start", "message": "开始"}
    assert events[1]["type"] == "delta"
    assert events[2]["content"] == "第二段"
    assert events[-1]["type"] == "done"
    assert events[-1]["done"] is True
    assert events[-1]["content"] == "第一段第二段"


def test_sse_blocking_events_flatten_structured_result():
    body = "".join(sse_blocking_events(lambda: {"success": True, "score": 88}))
    assert '"type":"start"' in body
    assert '"type":"done"' in body
    assert '"score":88' in body


def test_sse_response_sets_streaming_headers():
    app = Flask(__name__)
    with app.test_request_context("/"):
        response = sse_response([sse_event({"ok": True})])
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache, no-transform"
        assert response.headers["X-Accel-Buffering"] == "no"


def test_stream_text_chunks_preserve_cached_text_without_character_pacing():
    text = "第一段内容。" + "第二段内容，继续说明。" * 20
    chunks = list(stream_text_chunks(text, max_chars=32))

    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= 32 for chunk in chunks)
    assert len(chunks) < len(text) / 2
