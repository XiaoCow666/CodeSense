import pytest

from services import llm_client
from utils.thinking_ai import check_quiz_equivalence


class FakeLLMClient:
    def __init__(self, response, *, available=True):
        self.response = response
        self.available = available

    def is_available(self):
        return self.available

    def chat(self, messages, **kwargs):
        return self.response


def _run_check(monkeypatch, response, *, available=True):
    monkeypatch.setattr(
        llm_client,
        "SharedLLMClient",
        lambda: FakeLLMClient(response, available=available),
    )
    return check_quiz_equivalence("cin >> n;", "cin >> n;", "读取 n", "int n;\ncin >> n;")


def test_quiz_equivalence_accepts_json_boolean(monkeypatch):
    result = _run_check(monkeypatch, '{"equivalent": true, "reason": ""}')

    assert result == {"equivalent": True, "reason": ""}


def test_quiz_equivalence_accepts_fenced_json_boolean(monkeypatch):
    result = _run_check(
        monkeypatch,
        '```json\n{"equivalent": false, "reason": "变量名与上下文不一致"}\n```',
    )

    assert result == {
        "equivalent": False,
        "reason": "变量名与上下文不一致",
    }


@pytest.mark.parametrize(
    "response",
    [
        '{"equivalent": "false", "reason": ""}',
        '{"equivalent": 1, "reason": ""}',
        '{"equivalent": true, "reason": 123}',
        '[]',
        '{"reason": ""}',
        '{"equivalent": null, "reason": ""}',
        '{"equivalent": true, "reason": null}',
        'not-json',
        '{"equivalent": "true", "reason": ""}',
        '{"equivalent": 0, "reason": ""}',
        'null',
        '"text"',
        '1',
    ],
)
def test_quiz_equivalence_rejects_invalid_response_schema(
    monkeypatch, response
):
    result = _run_check(monkeypatch, response)

    assert result == {"equivalent": False, "reason": "检查失败"}


def test_quiz_equivalence_defaults_missing_reason_to_empty_string(monkeypatch):
    result = _run_check(monkeypatch, '{"equivalent": true}')

    assert result == {"equivalent": True, "reason": ""}


def test_quiz_equivalence_reports_unavailable_service(monkeypatch):
    result = _run_check(monkeypatch, None, available=False)

    assert result == {"equivalent": False, "reason": "AI 评估服务不可用"}
