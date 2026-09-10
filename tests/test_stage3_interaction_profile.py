import json
from dataclasses import dataclass, field

from utils.agents.contracts import AgentDecision, AgentRole, FeynmanState
from utils.agents.feynman import FeynmanCallbacks, build_feynman_runtime
from utils.agents.interaction import build_interaction_profile
from utils.agents.memory import MemorySnapshot


class EmptyEventStore:
    def list_events(self, session_id, stage=3):
        return []

    def append(self, event):
        return event


@dataclass
class SessionStudent:
    full_name: str = "学习者"


@dataclass
class Session:
    id: int = 71
    student_id: str = "student-71"
    student: SessionStudent = field(default_factory=SessionStudent)
    status: str = "in_progress"
    stage1_description: str = ""
    stage2_completed: bool = True


@dataclass
class Assignment:
    title: str = "循环边界"
    description: str = "理解循环边界。"


@dataclass
class Preset:
    key_steps: list = field(default_factory=lambda: ["循环边界", "输出"])
    reference_code: str = ""
    difficulty_config: dict = field(default_factory=dict)

    def get_key_steps(self):
        return list(self.key_steps)

    def get_difficulty_config(self):
        return dict(self.difficulty_config)


class FallbackModel:
    fallback_used = True

    def decide(self, **kwargs):
        return AgentDecision(message="请再用自己的话解释一下这一步。")


def _student_message(content, event_type="agent_user_message"):
    return {"role": "student", "event_type": event_type, "content": content}


def test_profile_detects_beginner_uncertainty_without_retaining_content():
    profile = build_interaction_profile([
        _student_message("嗯"),
        _student_message("我不会"),
        _student_message("不太懂这个循环边界"),
    ])

    assert profile.mode == "needs_scaffold"
    assert profile.sample_size == 3
    assert profile.uncertainty_count == 2
    assert profile.uncertainty_streak == 2
    assert "我不会" not in json.dumps(profile.to_prompt_dict(), ensure_ascii=False)


def test_profile_asks_for_a_smaller_check_for_short_replies():
    profile = build_interaction_profile([
        _student_message("好的"),
        _student_message("嗯"),
        _student_message("可以"),
        _student_message("输出结果是 3，循环已经结束"),
    ])

    assert profile.mode == "concise_check"
    assert profile.short_reply_count == 3


def test_stage3_context_contains_only_profile_signals():
    runtime = build_feynman_runtime(
        Session(),
        Assignment(),
        Preset(),
        model=FallbackModel(),
        callbacks=FeynmanCallbacks(
            event_store=EmptyEventStore(),
            persist_session=lambda session: None,
        ),
    )
    snapshot = MemorySnapshot(
        state=FeynmanState(session_id=71, unresolved_concepts=["循环边界"]),
        student_messages=[_student_message("我还不懂")],
    )

    context = runtime._context_for(AgentRole.TEACHER_AGENT, snapshot, "teacher_help")

    assert context["interaction_profile"]["mode"] == "needs_scaffold"
    assert context["interaction_profile"]["sample_size"] == 1
    assert "我还不懂" not in json.dumps(context["interaction_profile"], ensure_ascii=False)


def test_teacher_fallback_explains_a_concrete_example_for_teacher_help():
    runtime = build_feynman_runtime(
        Session(),
        Assignment(),
        Preset(),
        model=FallbackModel(),
        callbacks=FeynmanCallbacks(
            event_store=EmptyEventStore(),
            persist_session=lambda session: None,
        ),
    )
    loop = runtime._loop_for(AgentRole.TEACHER_AGENT, runtime.model)
    loop._active_teacher_help_target = {
        "concept": "循环边界",
        "dimension": "edge_case",
    }
    snapshot = MemorySnapshot(
        state=FeynmanState(
            session_id=71,
            pending_probe={"concept": "循环边界", "dimension": "edge_case"},
        ),
        student_messages=[_student_message("不会")],
    )

    decision = loop._fallback_protocol_decision(
        AgentDecision(message="请再用自己的话解释一下这一步。"),
        user_message="不会",
        input_kind="teacher_help",
        request_id="fallback-1",
        snapshot=snapshot,
        tool_results=[],
    )

    assert "n=3" in decision.message
    assert "请再用自己的话解释一下这一步" not in decision.message
