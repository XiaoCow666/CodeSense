"""Guard the low-cardinality LLM trace labels at production call sites."""

import ast
from pathlib import Path

from services.llm_client import _REQUEST_KINDS


PRODUCTION_FILES = (
    "routes/api.py",
    "routes/assignments.py",
    "routes/thinking.py",
    "services/ai_evaluator.py",
    "services/teacher_ai_advisor.py",
    "utils/agents/model.py",
    "utils/code_advisor.py",
    "utils/llm_evaluator.py",
    "utils/thinking_ai.py",
    "utils/validate_testcases.py",
)


def _llm_call_sites(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute):
            continue
        if function.attr not in {"chat", "chat_stream"}:
            continue
        yield node


def test_production_llm_calls_use_explicit_bounded_trace_kinds():
    root = Path(__file__).resolve().parents[1]
    missing = []
    invalid = []
    for relative_path in PRODUCTION_FILES:
        path = root / relative_path
        for node in _llm_call_sites(path):
            request_keywords = [
                keyword for keyword in node.keywords if keyword.arg == "request_kind"
            ]
            if not request_keywords:
                missing.append(f"{relative_path}:{node.lineno}")
                continue
            value = request_keywords[0].value
            if isinstance(value, ast.Constant) and value.value not in _REQUEST_KINDS:
                invalid.append(f"{relative_path}:{node.lineno}={value.value!r}")

    assert not missing, "LLM trace request_kind missing at: " + ", ".join(missing)
    assert not invalid, "LLM trace request_kind is not whitelisted at: " + ", ".join(invalid)
