from types import SimpleNamespace

import services.llm_client as llm_module
from services.llm_client import LLMProvider, SharedLLMClient, _ProviderState


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=value))]
        )


class FakeProviderClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def _client(fake):
    client = object.__new__(SharedLLMClient)
    client._client = fake
    client._provider = LLMProvider.ZHIPU
    client._model_name = "test-model"
    client._available = True
    client._redis_cache = None
    client._provider_states = {
        LLMProvider.ZHIPU: _ProviderState(
            provider=LLMProvider.ZHIPU,
            client=fake,
            model="test-model",
        )
    }
    client._provider_order = [LLMProvider.ZHIPU]
    client._state_lock = llm_module.threading.RLock()
    client._cache_lock = llm_module.threading.RLock()
    client._local_cache = {}
    client._inflight_lock = llm_module.threading.RLock()
    client._inflight = {}
    client._request_semaphore = llm_module.threading.BoundedSemaphore(1)
    client._retry_attempts = 3
    client._interactive_retry_attempts = 1
    client._background_retry_attempts = 2
    client._request_queue_timeout = 0.01
    client._interactive_queue_timeout = 0.01
    client._background_queue_timeout = 0.01
    client._background_priority_window = 0.0
    client._background_max_wait = 0.0
    client._cache_ttl = 60
    client._circuit_failure_threshold = 10
    client._circuit_cooldown = 30.0
    client._retry_base_delay = 0.0
    client._retry_max_delay = 1.0
    client._last_error = ""
    client._credentials_signature = ("", "")
    client._refresh_configuration = lambda: None
    return client


def test_interactive_and_background_requests_use_separate_retry_budgets(monkeypatch):
    fake = FakeProviderClient([
        ConnectionError("temporary"),
        "background eventually succeeds",
    ])
    client = _client(fake)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _seconds: None)

    assert client.chat(
        [{"role": "user", "content": "interactive"}],
        request_kind="interactive",
    ) is None
    assert len(fake.completions.calls) == 1

    assert client.chat(
        [{"role": "user", "content": "background"}],
        request_kind="background",
    ) == "background eventually succeeds"
    assert len(fake.completions.calls) == 2

    metrics = client.health_snapshot()["request_metrics"]
    assert metrics["by_kind"]["interactive"]["failures"] == 1
    assert metrics["by_kind"]["background"]["successes"] == 1
