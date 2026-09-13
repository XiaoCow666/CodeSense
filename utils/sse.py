"""Small helpers for consistent Server-Sent Events responses.

All AI SSE endpoints use the same small envelope: ``start``, optional
``status``/``data``, text ``delta`` events with a ``content`` field, and one
terminal ``done`` or ``error`` event.
"""

import json
from typing import Any, Callable, Iterable, Optional

from flask import Response, request, stream_with_context


def wants_sse(req=None) -> bool:
    """Return whether a request explicitly asks for an SSE response."""

    req = req or request
    stream_flag = str(req.args.get("stream", "")).strip().lower()
    if stream_flag in {"1", "true", "yes", "on"}:
        return True
    accept = str(req.headers.get("Accept", "")).lower()
    return "text/event-stream" in accept


def sse_event(payload: Any, event: Optional[str] = None) -> str:
    """Serialize one JSON SSE event and terminate it with a blank line."""

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {encoded}\n\n"


def stream_text_chunks(text: str, *, max_chars: int = 160) -> Iterable[str]:
    """Split already-available text into readable, bounded stream chunks.

    Provider streams should be forwarded as they arrive.  This helper is for
    cached or precomputed text, where a one-character-at-a-time animation only
    adds artificial latency.  Prefer paragraph/punctuation boundaries when a
    reasonably sized chunk is available, including for Chinese text.
    """

    if not text:
        return
    max_chars = max(1, int(max_chars))
    boundaries = "\n。！？；.!?;:："
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(text_length, start + max_chars)
        if end < text_length:
            candidate = text[start:end]
            boundary = max(candidate.rfind(char) for char in boundaries)
            if boundary >= max_chars // 2:
                end = start + boundary + 1
        yield text[start:end]
        start = end


def sse_response(events: Iterable[str]) -> Response:
    """Create a cache-safe Flask response for an SSE event iterable."""

    return Response(
        stream_with_context(events),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def sse_text_events(
    chunks: Iterable[str],
    *,
    start_message: str = "正在生成回答...",
    done_payload: Optional[dict] = None,
) -> Iterable[str]:
    """Wrap text chunks in the common start/delta/done protocol."""

    yield sse_event({"type": "start", "message": start_message})
    collected = []
    try:
        for chunk in chunks:
            if chunk is None:
                continue
            text = str(chunk)
            if not text:
                continue
            collected.append(text)
            yield sse_event({"type": "delta", "content": text})
        payload = {"type": "done", "done": True, "content": "".join(collected)}
        if done_payload:
            payload.update(done_payload)
        yield sse_event(payload)
    except Exception as exc:
        yield sse_event({"type": "error", "error": str(exc), "message": str(exc)})

def sse_blocking_events(
    work: Callable[[], Any],
    *,
    start_message: str = "正在处理...",
) -> Iterable[str]:
    """Expose a structured/blocking operation through the same SSE envelope.

    Structured evaluations still need to finish before their JSON result can
    be trusted.  Sending a start event immediately keeps the browser
    responsive and gives those operations the same transport contract as
    token streams.
    """

    yield sse_event({"type": "start", "message": start_message})
    try:
        result = work()
        if isinstance(result, dict):
            payload = {"type": "done", "done": True, "result": result}
            payload.update(result)
        else:
            payload = {"type": "done", "done": True, "result": result}
        yield sse_event(payload)
    except Exception as exc:
        yield sse_event({"type": "error", "error": str(exc), "message": str(exc)})
