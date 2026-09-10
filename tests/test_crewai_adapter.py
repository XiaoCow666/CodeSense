import json

from utils.agents import crewai_adapter
from utils.agents.contracts import AgentDecision
from utils.agents.model import StructuredDecisionModel


class FakeClient:
    def is_available(self):
        return True


def _uninitialized_model(fallback_message="继续说明你的思路。"):
    """Build the decision wrapper without importing the optional dependency."""

    model = crewai_adapter.CrewAIDecisionModel.__new__(
        crewai_adapter.CrewAIDecisionModel
    )
    model.client = FakeClient()
    model.fallback_decision = AgentDecision(message=fallback_message)
    model.temperature = 0.2
    model.max_tokens = 1200
    model.last_error = None
    model.fallback_used = False
    return model


def test_native_framework_remains_the_default(monkeypatch):
    monkeypatch.delenv("STAGE3_AGENT_FRAMEWORK", raising=False)

    model = crewai_adapter.build_stage3_decision_model(client=FakeClient())

    assert isinstance(model, StructuredDecisionModel)


def test_crewai_configuration_falls_back_without_optional_package(monkeypatch):
    monkeypatch.setenv("STAGE3_AGENT_FRAMEWORK", "crewai")

    def unavailable(**_kwargs):
        raise crewai_adapter.CrewAIUnavailable("test")

    monkeypatch.setattr(crewai_adapter, "CrewAIDecisionModel", unavailable)

    model = crewai_adapter.build_stage3_decision_model(client=FakeClient())

    assert isinstance(model, StructuredDecisionModel)


def test_crewai_configuration_falls_back_on_initialization_error(monkeypatch):
    monkeypatch.setenv("STAGE3_AGENT_FRAMEWORK", "crewai")

    def broken(**_kwargs):
        raise RuntimeError("incompatible optional runtime")

    monkeypatch.setattr(crewai_adapter, "CrewAIDecisionModel", broken)

    model = crewai_adapter.build_stage3_decision_model(client=FakeClient())

    assert isinstance(model, StructuredDecisionModel)


def test_crewai_decision_wrapper_keeps_one_structured_decision(monkeypatch):
    model = _uninitialized_model()
    captured = {}
    response = json.dumps(
        {
            "message": "这个边界要先看 N 的含义。",
            "tool_calls": [],
            "goal_status": "in_progress",
            "ui_action": "continue_chat",
        },
        ensure_ascii=False,
    )

    def run_crew(description, context):
        captured["description"] = description
        captured["context"] = context
        return response

    monkeypatch.setattr(model, "_run_crew", run_crew)
    context = json.dumps(
        {"target_role": "student_agent", "learner_name": "赵一"},
        ensure_ascii=False,
    )

    decision = model.decide(
        system_prompt="只回应当前学习者，不替其他角色发言。",
        context=context,
        tool_specs=[{"name": "record_understanding", "arguments": {}}],
    )

    assert decision.message == "这个边界要先看 N 的含义。"
    assert decision.tool_calls == []
    assert "student_agent" in captured["description"]
    assert "record_understanding" in captured["description"]
    assert captured["context"] == context


def test_crewai_decision_wrapper_has_one_bounded_repair(monkeypatch):
    model = _uninitialized_model(fallback_message="fallback")
    responses = iter(
        [
            "not json",
            json.dumps(
                {
                    "message": "现在可以进入下一步。",
                    "tool_calls": [],
                    "goal_status": "in_progress",
                    "ui_action": "continue_chat",
                },
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    def run_crew(description, _context):
        calls.append(description)
        return next(responses)

    monkeypatch.setattr(model, "_run_crew", run_crew)

    decision = model.decide(
        system_prompt="只输出结构化决定。",
        context=json.dumps({"target_role": "teacher_agent"}),
        tool_specs=[],
    )

    assert decision.message == "现在可以进入下一步。"
    assert len(calls) == 2
    assert "[REPAIR]" in calls[1]


def test_role_detection_defaults_to_teacher():
    assert crewai_adapter._role_from_context("not-json") == "teacher_agent"
    assert (
        crewai_adapter._role_from_context(
            json.dumps({"target_role": "student_agent"})
        )
        == "student_agent"
    )
