import json
from types import SimpleNamespace

import pytest

import services.llm_client as llm_module
from services.llm_client import (
    LLMProvider,
    LLMServiceError,
    SharedLLMClient,
    _ProviderState,
    safe_zhipu_post,
)


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        if kwargs.get("stream"):
            return value
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=value))]
        )


class FakeProviderClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def make_client(provider_clients):
    client = object.__new__(SharedLLMClient)
    client._client = None
    client._provider = None
    client._model_name = ""
    client._available = True
    client._redis_cache = None
    client._provider_states = {}
    client._provider_order = list(provider_clients)
    for provider, fake in provider_clients.items():
        client._provider_states[provider] = _ProviderState(
            provider=provider,
            client=fake,
            model="test-model",
        )
    client._provider = client._provider_order[0]
    client._client = client._provider_states[client._provider].client
    client._model_name = client._provider_states[client._provider].model
    client._credentials_signature = ("", "")
    client._state_lock = llm_module.threading.RLock()
    client._cache_lock = llm_module.threading.RLock()
    client._local_cache = {}
    client._request_semaphore = llm_module.threading.BoundedSemaphore(2)
    client._retry_attempts = 3
    client._retry_base_delay = 0.0
    client._retry_max_delay = 1.0
    client._circuit_failure_threshold = 1
    client._circuit_cooldown = 30.0
    client._request_queue_timeout = 0.01
    client._background_priority_window = 0.0
    client._background_max_wait = 0.0
    client._cache_ttl = 60
    client._last_error = ""
    client._refresh_configuration = lambda: None
    return client


def chunk(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


def trace_records(caplog):
    records = []
    for record in caplog.records:
        message = record.getMessage()
        if "llm_trace " not in message:
            continue
        records.append(json.loads(message.split("llm_trace ", 1)[1]))
    return records


def test_chat_retries_transient_connection_error(monkeypatch):
    fake = FakeProviderClient([ConnectionError("connection reset"), "恢复后的回答"])
    client = make_client({LLMProvider.ZHIPU: fake})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    result = client.chat([{"role": "user", "content": "测试"}])

    assert result == "恢复后的回答"
    assert len(fake.completions.calls) == 2
    assert client._provider_states[LLMProvider.ZHIPU].health.consecutive_failures == 0


def test_chat_emits_redacted_trace_for_retry(caplog, monkeypatch):
    fake = FakeProviderClient([ConnectionError("private prompt body"), "恢复后的回答"])
    client = make_client({LLMProvider.ZHIPU: fake})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    result = client.chat(
        [{"role": "user", "content": "private prompt body"}],
        request_kind="stage3",
        request_id="student@example.com",
    )

    assert result == "恢复后的回答"
    trace = trace_records(caplog)[-1]
    assert trace["event_name"] == "codesense.llm.request"
    assert trace["schema_version"] == 1
    assert trace["request_kind"] == "stage3"
    assert trace["request_id"] != "student@example.com"
    assert len(trace["request_id"]) == 32
    assert trace["provider"] == "zhipu"
    assert trace["model"] == "test-model"
    assert trace["attempts"] == 2
    assert trace["retry_count"] == 1
    assert trace["fallback"] is False
    assert trace["stop_reason"] == "completed"
    assert "error_class" not in trace
    assert "private prompt body" not in caplog.text
    assert trace["duration_ms"] >= trace["llm_latency_ms"]


def test_chat_trace_inherits_flask_request_id_without_logging_prompt(caplog):
    fake = FakeProviderClient(["请求内回答"])
    client = make_client({LLMProvider.ZHIPU: fake})
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    from flask import Flask, g

    app = Flask(__name__)
    with app.test_request_context("/private/path"):
        g.codesense_request_id = "11111111-1111-4111-8111-111111111111"
        assert client.chat(
            [{"role": "user", "content": "private prompt body"}],
            request_kind="stage3",
        ) == "请求内回答"

    trace = trace_records(caplog)[-1]
    assert trace["request_id"] == "11111111-1111-4111-8111-111111111111"
    assert "private prompt body" not in caplog.text


def test_chat_fails_over_to_second_provider_after_primary_is_down(monkeypatch):
    primary = FakeProviderClient([ConnectionError("WinError 10013")] * 3)
    backup = FakeProviderClient(["备用回答"])
    client = make_client({LLMProvider.ZHIPU: primary, LLMProvider.OPENAI: backup})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    result = client.chat([{"role": "user", "content": "测试切换"}])

    assert result == "备用回答"
    assert len(primary.completions.calls) == 3
    assert len(backup.completions.calls) == 1
    assert client.provider == "openai"


def test_chat_trace_marks_provider_fallback(caplog, monkeypatch):
    primary = FakeProviderClient([ConnectionError("primary unavailable")] * 3)
    backup = FakeProviderClient(["备用回答"])
    client = make_client({LLMProvider.ZHIPU: primary, LLMProvider.OPENAI: backup})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    assert client.chat([{"role": "user", "content": "切换测试"}]) == "备用回答"

    trace = trace_records(caplog)[-1]
    assert trace["fallback"] is True
    assert trace["providers_tried"] == ["zhipu", "openai"]
    assert trace["attempts"] == 4
    assert trace["stop_reason"] == "completed"
    assert "error_class" not in trace


def test_provider_model_is_not_sent_to_a_different_failover_provider():
    primary = FakeProviderClient([ConnectionError("provider unavailable")])
    backup = FakeProviderClient(["备用模型回答"])
    client = make_client({LLMProvider.ZHIPU: primary, LLMProvider.OPENAI: backup})
    client._retry_attempts = 1

    result = client.chat(
        [{"role": "user", "content": "模型切换测试"}],
        provider="zhipu",
        model="glm-custom-model",
    )

    assert result == "备用模型回答"
    assert backup.completions.calls[0]["model"] == "test-model"


def test_non_retryable_auth_error_is_not_repeated():
    error = RuntimeError("invalid API key")
    error.status_code = 401
    fake = FakeProviderClient([error])
    client = make_client({LLMProvider.ZHIPU: fake})

    assert client.chat([{"role": "user", "content": "测试鉴权"}]) is None
    assert len(fake.completions.calls) == 1


def test_failed_chat_trace_uses_stable_error_class_without_exception_text(caplog):
    error = RuntimeError("secret prompt and account@example.com")
    error.status_code = 401
    fake = FakeProviderClient([error])
    client = make_client({LLMProvider.ZHIPU: fake})
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    assert client.chat([{"role": "user", "content": "secret prompt"}]) is None

    trace = trace_records(caplog)[-1]
    assert trace["stop_reason"] == "provider_error"
    assert trace["error_class"] == "AUTH_FAILED"
    assert "secret prompt" not in caplog.text
    assert "account@example.com" not in caplog.text


def test_stream_retries_before_first_token(monkeypatch):
    fake = FakeProviderClient([
        TimeoutError("timed out"),
        [chunk("第一段"), chunk("第二段")],
    ])
    client = make_client({LLMProvider.ZHIPU: fake})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    assert list(client.chat_stream([{"role": "user", "content": "流式测试"}])) == [
        "第一段",
        "第二段",
    ]
    assert len(fake.completions.calls) == 2


def test_stream_reports_network_diagnostic_after_all_providers_fail(monkeypatch):
    fake = FakeProviderClient([ConnectionError("connection error")] * 3)
    client = make_client({LLMProvider.ZHIPU: fake})
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(LLMServiceError) as exc_info:
        list(client.chat_stream([{"role": "user", "content": "诊断测试"}]))

    assert exc_info.value.code == "NETWORK_UNAVAILABLE"
    assert len(fake.completions.calls) == 3


def test_stream_reports_interruption_after_output_without_replaying_prefix():
    class BrokenStream:
        def __iter__(self):
            yield chunk("已经输出")
            raise ConnectionError("connection reset")

    fake = FakeProviderClient([BrokenStream()])
    client = make_client({LLMProvider.ZHIPU: fake})

    with pytest.raises(LLMServiceError, match="STREAM_INTERRUPTED"):
        list(client.chat_stream([{"role": "user", "content": "中断测试"}]))

    assert len(fake.completions.calls) == 1


def test_stream_trace_records_interruption_without_payload(caplog):
    class BrokenStream:
        def __iter__(self):
            yield chunk("已经输出")
            raise ConnectionError("private stream payload")

    fake = FakeProviderClient([BrokenStream()])
    client = make_client({LLMProvider.ZHIPU: fake})
    caplog.set_level(llm_module.logging.INFO, logger="services.llm_client")

    with pytest.raises(LLMServiceError, match="STREAM_INTERRUPTED"):
        list(client.chat_stream([{"role": "user", "content": "private stream payload"}]))

    trace = trace_records(caplog)[-1]
    assert trace["stream"] is True
    assert trace["stop_reason"] == "stream_interrupted"
    assert trace["error_class"] == "NETWORK_UNAVAILABLE"
    assert trace["time_to_first_chunk_ms"] is not None
    assert trace["stream_chunks"] == 1
    assert trace["output_chars"] == len("已经输出")
    assert "private stream payload" not in caplog.text


def test_safe_zhipu_post_retries_error_code_1305(monkeypatch):
    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code
            self.headers = {}
            self.closed = False

        def json(self):
            return self.payload

        def close(self):
            self.closed = True

    class FakeSession:
        def __init__(self):
            self.calls = []
            self.responses = [
                FakeResponse({"error": {"code": "1305", "message": "busy"}}),
                FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
            ]

        def post(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self.responses.pop(0)

    session = FakeSession()
    monkeypatch.setattr(llm_module, "_thread_http_session", lambda: session)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("AI_HTTP_RETRY_ATTEMPTS", "2")

    response = safe_zhipu_post(
        "https://example.invalid/chat",
        headers={"Authorization": "Bearer test"},
        json_data={"model": "glm-4.5-flash", "messages": []},
    )

    assert response.status_code == 200
    assert len(session.calls) == 2
    assert session.calls[0][1]["json"]["model"] == "glm-4.5-flash"
