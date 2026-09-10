import json
from dataclasses import dataclass, field
from datetime import datetime

from utils.agents.contracts import AgentDecision, AgentRole, Stage3Target, ToolCall, ToolResult, UIAction
from utils.agents.feynman import FeynmanCallbacks, build_feynman_runtime
from utils.agents.model import StructuredDecisionModel
from utils.agents.memory import EventRecord
from utils.agents.orchestrator import ForumTurnResult, Stage3Orchestrator


class FakeEventStore:
    def __init__(self):
        self.events = []

    def list_events(self, session_id, stage=3):
        return [event for event in self.events if event.session_id == session_id and event.stage == stage]

    def append(self, event):
        if event.event_id is None:
            event.event_id = str(len(self.events) + 1)
        self.events.append(event)
        return event

    def append_many(self, events):
        return [self.append(event) for event in events]


class SequencedModel:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []
        self.last_error = None

    def decide(self, **kwargs):
        self.calls.append(kwargs)
        return self.decisions.pop(0)


class UnavailableClient:
    def is_available(self):
        return False


@dataclass
class FakeAssignment:
    title: str = "循环练习"
    description: str = "解释循环边界并在理解后检查代码。"


@dataclass
class FakePreset:
    reference_code: str = "int main() { return 0; }"
    key_steps: list = field(default_factory=lambda: ["循环边界", "不变量"])
    difficulty_config: dict = field(default_factory=lambda: {
        "feynman_coverage": {
            "min_coverage": 0.8,
            "max_probes_per_concept": 2,
            "probe_dimensions": ["core", "edge_case", "application"],
        }
    })

    def get_key_steps(self):
        return list(self.key_steps)

    def get_difficulty_config(self):
        return dict(self.difficulty_config)


@dataclass
class FakeStudent:
    full_name: str = "赵一"


@dataclass
class FakeSession:
    id: int = 12
    student_id: str = "student-1"
    student: FakeStudent = field(default_factory=FakeStudent)
    stage1_description: str = "我会先读取输入。"
    stage2_completed: bool = True
    stage3_completed: bool = False
    status: str = "in_progress"
    completed_at: datetime | None = None
    stage3_teacher_rounds: int = 0
    stage3_student_rounds: int = 0


def make_runtime(*, decisions=None, buggy_code_generator=None, model=None):
    event_store = FakeEventStore()
    model = model or SequencedModel(decisions or [])
    runtime = build_feynman_runtime(
        FakeSession(),
        FakeAssignment(),
        FakePreset(),
        model=model,
        callbacks=FeynmanCallbacks(
            event_store=event_store,
            buggy_code_generator=buggy_code_generator,
            persist_session=lambda session: None,
        ),
    )
    return runtime, model, event_store


def _coverage_entry(
    concept,
    *,
    status="unseen",
    attempts=0,
    used_dimensions=None,
    attempt_event_ids=None,
    accepted_evidence_count=0,
    evidence_event_ids=None,
    last_evidence_event_id=None,
):
    return {
        "concept": concept,
        "status": status,
        "attempts": attempts,
        "used_dimensions": list(used_dimensions or []),
        "attempt_event_ids": list(attempt_event_ids or []),
        "accepted_evidence_count": accepted_evidence_count,
        "evidence_event_ids": list(evidence_event_ids or []),
        "last_evidence_event_id": last_evidence_event_id,
    }


def test_teacher_signal_sets_next_student_intent_and_next_turn_uses_current_message():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[
                ToolCall("probe-1", "request_student_probe", {
                    "concept": "循环边界",
                    "dimension": "edge_case",
                    "goal": "检查用户能否解释边界情况",
                }),
                ToolCall("probe-2", "request_student_probe", {
                    "concept": "不变量",
                    "dimension": "core",
                    "goal": "这条信号不应进入公开结果",
                }),
            ]),
            AgentDecision(message="因为 `i <= n` 会多走一步，所以会访问到越界索引。"),
            AgentDecision(tool_calls=[ToolCall("assess-1", "assess_teaching_progress", {
                "assessment": "covered",
                "evidence": "因为 i < n 会在碰到非法索引前停止，所以最后一个合法位置是 n - 1。",
            })]),
            AgentDecision(tool_calls=[ToolCall("ask-1", "ask_student_probe", {
                "question": "你能解释一下为什么最后一个合法索引是 n - 1 吗？",
            })]),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    result = orchestrator.handle_user_message(
        "老师，为什么这里会越界？",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-1",
    )

    assert result.primary.success is True
    assert "i <= n" in result.primary.response
    assert "越界索引" in result.primary.response
    assert result.primary.internal_signals == {
        "student_probe": {
            "concept": "循环边界",
            "dimension": "edge_case",
            "goal": "检查用户能否解释边界情况",
        }
    }
    assert result.interventions == []
    assert len(model.calls) == 2
    state = runtime.memory.load(runtime.session.id).state
    assert state.student_probe_intent == {
        "concept": "循环边界",
        "dimension": "edge_case",
        "goal": "检查用户能否解释边界情况",
    }

    second = orchestrator.handle_user_message(
        "因为 i < n 会在碰到非法索引前停止，所以最后一个合法位置是 n - 1。",
        target_role=Stage3Target.AUTO,
        request_id="student-1",
    )
    assert second.primary.success is True
    assert second.primary.agent is AgentRole.STUDENT_AGENT
    assert second.primary.response == "赵一，你能解释一下为什么最后一个合法索引是 n - 1 吗？"
    student_context = json.loads(model.calls[-1]["context"])
    assert "i <= n" in json.dumps(student_context, ensure_ascii=False)
    assert "越界索引" in json.dumps(student_context, ensure_ascii=False)
    assert "老师，为什么这里会越界？" in json.dumps(student_context, ensure_ascii=False)

    forum_events = runtime.memory.forum_events(runtime.session.id)
    user_event = next(item for item in forum_events if item["request_id"] == "teacher-1" and item["source_role"] == "user")
    teacher_event = next(item for item in forum_events if item["request_id"] == "teacher-1" and item["source_role"] == "teacher_agent")
    student_user_event = next(item for item in forum_events if item["request_id"] == "student-1" and item["source_role"] == "user")
    student_event = next(item for item in forum_events if item["request_id"] == "student-1" and item["source_role"] == "student_agent")

    assert user_event["target_role"] == "teacher_agent"
    assert teacher_event["reply_to_event_id"] == user_event["event_id"]
    assert teacher_event["parent_request_id"] == "teacher-1"
    assert student_user_event["target_role"] == "student_agent"
    assert student_event["reply_to_event_id"] == student_user_event["event_id"]
    assert student_event["parent_request_id"] == "student-1"
    assert not any(event.event_type == "student_probe_queued" for event in runtime.memory.event_store.events)


def test_teacher_context_exposes_server_allowed_concepts_for_probe_tool():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="我会继续检查这个概念。")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "老师，请继续。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-concepts-1",
    )

    assert result.primary.success is True
    context = json.loads(model.calls[0]["context"])
    assert context["key_concepts"] == ["循环边界", "不变量"]
    assert context["coverage"]["unresolved_concepts"] == ["循环边界", "不变量"]


def test_auto_mode_chooses_one_speaker_and_does_not_create_a_second_reply():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="赵一，请从边界情况举一个具体例子？")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "我已经想明白循环边界了。",
        target_role=Stage3Target.AUTO,
        request_id="auto-speaker-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.interventions == []
    assert result.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    assert len(model.calls) == 0
    assert runtime.memory.load(runtime.session.id).state.pending_probe["question"] == result.primary.response
    forum_events = runtime.memory.forum_events(runtime.session.id)
    assert len([item for item in forum_events if item["request_id"] == "auto-speaker-1"]) == 2
    assert not any(event.event_type == "student_probe_queued" for event in runtime.memory.event_store.events)


def test_auto_intent_routes_a_teacher_question_before_scheduler_fallback():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="老师会从一个真实例子讲清楚这个概念。")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "老师，请给我一个循环边界的例子。",
        target_role=Stage3Target.AUTO,
        request_id="intent-teacher-1",
    )

    assert result.primary.agent is AgentRole.TEACHER_AGENT
    assert result.routing is not None
    assert result.routing.intent.name == "ask_teacher"
    assert result.routing.selection_source == "intent"
    assert len(model.calls) == 1


def test_auto_intent_routes_a_student_question_with_a_server_owned_probe():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="赵一，请说说这个边界在实际场景中怎么用？")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "小明，请给我一个实际应用场景。",
        target_role=Stage3Target.AUTO,
        request_id="intent-student-1",
    )

    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.routing is not None
    assert result.routing.intent.name == "ask_student"
    assert result.routing.selection_source == "intent"
    assert result.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    assert len(model.calls) == 0
    assert runtime.memory.load(runtime.session.id).state.pending_probe["question"] == result.primary.response


def test_auto_mode_yields_after_two_consecutive_public_teacher_turns():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="先确认循环的边界。"),
            AgentDecision(message="再看每一轮保存的两个相邻值。"),
            AgentDecision(message="小明，请用一个具体输入说说下一项如何得到。"),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    orchestrator.handle_user_message(
        "老师，先帮我梳理一下边界。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="fairness-teacher-1",
    )
    orchestrator.handle_user_message(
        "我已经理解 N=0 和 N=1 的处理了。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="fairness-teacher-2",
    )
    result = orchestrator.handle_user_message(
        "继续。",
        target_role=Stage3Target.AUTO,
        request_id="fairness-student-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    assert len(model.calls) == 2


def test_auto_mode_does_not_let_teacher_answer_intent_monopolize_forum():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="先确认这个边界的含义。"),
            AgentDecision(message="再说明它和循环条件的关系。"),
            AgentDecision(tool_calls=[ToolCall("fairness-assess", "assess_teaching_progress", {
                "assessment": "partial",
                "evidence": "我理解循环条件会阻止访问越界位置。",
            })]),
            AgentDecision(message="赵一，请换一个具体输入说明这个规则如何应用？"),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    orchestrator.handle_user_message(
        "请先帮我解释循环边界。",
        target_role=Stage3Target.AUTO,
        request_id="answer-fairness-1",
    )
    orchestrator.handle_user_message(
        "应该在索引到达长度时停止，因为最后一个合法位置是长度减一。",
        target_role=Stage3Target.AUTO,
        request_id="answer-fairness-2",
    )
    result = orchestrator.handle_user_message(
        "我理解了，循环条件会阻止访问越界位置。",
        target_role=Stage3Target.AUTO,
        request_id="answer-fairness-3",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.routing is not None
    assert result.routing.selection_source == "fairness_after_teacher_answer"
    assert len(model.calls) == 4


def test_unavailable_model_uses_server_assessment_and_keeps_student_flow_moving():
    runtime, _, event_store = make_runtime(
        model=StructuredDecisionModel(
            UnavailableClient(),
            fallback_message="请继续说明你的思路。",
        ),
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={
            "state": {
                "concept_coverage": [
                    _coverage_entry("循环边界", status="unseen"),
                    _coverage_entry("不变量", status="unseen"),
                ],
                "coverage_score": 0.0,
                "unresolved_concepts": ["循环边界", "不变量"],
                "ready_for_code": False,
                "pending_probe": {"concept": "循环边界", "dimension": "core"},
            }
        },
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "每轮循环都先检查索引是否小于长度，达到长度时停止，所以最后一个合法位置是长度减一。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="fallback-student-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.primary.response.startswith("赵一，")
    assert "循环边界" in result.primary.response
    assert result.primary.ui_action is UIAction.CONTINUE_CHAT
    assert runtime.memory.load(runtime.session.id).state.coverage_score == 0.25
    assert [event.event_type for event in event_store.events].count("agent_fallback") >= 1


def test_ready_for_code_auto_mode_cannot_fall_back_to_another_teacher_question():
    runtime, model, event_store = make_runtime(
        decisions=[AgentDecision(message="请继续说明你的思路。")],
        buggy_code_generator=lambda context: {
            "buggy_code": "int main() { return 1; }",
            "bugs": [{"line": 1, "description": "返回值错误", "correct_version": "return 0;"}],
            "message": "内部代码说明",
        },
    )
    runtime.memory.append_event(
        runtime.session.id,
        "agent_message",
        "teacher_agent",
        content="请继续回答这个问题。",
        metadata={
            "source_role": "teacher_agent",
            "target_role": "user",
            "visibility": "public",
        },
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={
            "state": {
                "phase": "student_dialogue",
                "concept_coverage": [
                    _coverage_entry("循环边界", status="covered"),
                    _coverage_entry("不变量", status="covered"),
                ],
                "coverage_score": 1.0,
                "unresolved_concepts": [],
                "ready_for_code": True,
                "learning_evidence": [{"concept": "循环边界", "evidence": "已解释"}],
                "pending_probe": None,
            }
        },
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "我准备好检查代码了。",
        target_role=Stage3Target.AUTO,
        request_id="ready-auto-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.primary.ui_action is UIAction.SHOW_CODE_REVIEW
    assert result.routing is not None
    assert result.routing.selection_source == "ready_for_code"
    assert len(model.calls) == 0
    assert [event.event_type for event in event_store.events].count("buggy_attempt") == 1


def test_teacher_public_response_cannot_impersonate_student_agent():
    runtime, _, _ = make_runtime(
        decisions=[AgentDecision(message="小明，请解释一下边界；我也懂了。")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "老师，请继续检查边界。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-impersonation-1",
    )

    assert result.primary.success is True
    assert result.primary.response
    assert "小明" not in result.primary.response
    assert "我也懂了" not in result.primary.response
    teacher_event = next(
        item
        for item in runtime.memory.forum_events(runtime.session.id)
        if item["request_id"] == "teacher-impersonation-1"
        and item["source_role"] == "teacher_agent"
    )
    assert teacher_event["content"] == result.primary.response


def test_student_public_response_addresses_the_real_learner_not_its_own_persona():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="小明，请用一个真实场景说明这个边界。")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "请让小明问我一个应用场景。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-name-1",
    )

    assert result.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    assert model.calls == []
    assert runtime.memory.load(runtime.session.id).state.pending_probe["question"] == result.primary.response


def test_student_opens_as_a_peer_and_waits_for_the_learner_answer():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="不应在小明首轮调用模型。")],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "小明，请先问我。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-peer-opening-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.STUDENT_AGENT
    assert result.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    assert model.calls == []
    state = runtime.memory.load(runtime.session.id).state
    assert state.student_probe_intent is None
    assert state.pending_probe == {
        "concept": "循环边界",
        "dimension": "core",
        "question": result.primary.response,
    }


def test_incomplete_student_answer_is_handed_to_teacher_without_repeating_student_question():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="这里先把缺失的知识讲清楚，再看一个具体例子。")],
    )
    orchestrator = Stage3Orchestrator(runtime)

    opening = orchestrator.handle_user_message(
        "小明，请先问我。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-help-opening-1",
    )
    assert opening.primary.agent is AgentRole.STUDENT_AGENT

    result = orchestrator.handle_user_message(
        "负责输入输出",
        target_role=Stage3Target.AUTO,
        request_id="student-help-answer-1",
    )

    assert result.primary.success is True
    assert result.primary.agent is AgentRole.TEACHER_AGENT
    assert result.primary.response == "这里先把缺失的知识讲清楚，再看一个具体例子。"
    assert result.routing is not None
    assert result.routing.selection_source == "teacher_help_after_student"
    assert len(model.calls) == 1
    context = json.loads(model.calls[0]["context"])
    assert context["input_kind"] == "teacher_help"
    assert context["coverage"]["pending_probe"]["question"] == opening.primary.response
    assert "负责输入输出" in json.dumps(context, ensure_ascii=False)

    current_events = [
        item
        for item in runtime.memory.forum_events(runtime.session.id)
        if item["request_id"] == "student-help-answer-1"
    ]
    assert [item["source_role"] for item in current_events] == ["user", "teacher_agent"]
    assert not any(item["source_role"] == "student_agent" for item in current_events)


def test_legacy_student_probe_history_also_hands_incomplete_answer_to_teacher():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="先补充这里的关键知识，再继续。")],
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={
            "state": {
                "pending_probe": {
                    "concept": "循环边界",
                    "dimension": "core",
                }
            }
        },
    )
    runtime.memory.append_event(
        runtime.session.id,
        "agent_message",
        "student_agent",
        content="赵一，请解释一下这个边界。",
        metadata={
            "request_id": "legacy-student-probe",
            "source_role": "student_agent",
            "target_role": "user",
            "message_kind": "student_probe",
            "visibility": "public",
        },
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "输出null",
        target_role=Stage3Target.AUTO,
        request_id="legacy-student-answer-1",
    )

    assert result.primary.agent is AgentRole.TEACHER_AGENT
    assert result.routing is not None
    assert result.routing.selection_source == "teacher_help_after_student"
    assert result.primary.response == "先补充这里的关键知识，再继续。"
    assert len(model.calls) == 1
    assert json.loads(model.calls[0]["context"])["input_kind"] == "teacher_help"


def test_repeated_public_reply_is_retried_with_a_new_angle():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="请解释一下 N=1 时应该输出什么。"),
            AgentDecision(message="请解释一下 N=1 时应该输出什么。"),
            AgentDecision(message="很好，你已经说明了 N=1 的输出；请再用 N=2 举例。"),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    first = orchestrator.handle_user_message(
        "老师，请问 N=1 怎么处理？",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-duplicate-1",
    )
    second = orchestrator.handle_user_message(
        "应该输出 0，因为这是第一项。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-duplicate-2",
    )

    assert first.primary.response == "请解释一下 N=1 时应该输出什么。"
    assert second.primary.response == "很好，你已经说明了 N=1 的输出；请再用 N=2 举例。"
    assert len(model.calls) == 3
    assert "公开回复与本角色上一条公开回复重复" in model.calls[2]["system_prompt"]


def test_duplicate_guard_compares_sanitized_teacher_replies():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="小明，我也懂了。"),
            AgentDecision(message="我也会了。"),
            AgentDecision(message="我会根据你刚刚的回答换一个角度检查。"),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    first = orchestrator.handle_user_message(
        "老师，请继续。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-sanitized-duplicate-1",
    )
    second = orchestrator.handle_user_message(
        "输入 0 时我认为没有输出。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-sanitized-duplicate-2",
    )

    assert first.primary.response == "我会继续从教师角度检查你的理解；如需同伴提问，系统会单独展示。"
    assert second.primary.response == "我会根据你刚刚的回答换一个角度检查。"
    assert len(model.calls) == 3
    assert "公开回复与本角色上一条公开回复重复" in model.calls[2]["system_prompt"]


def test_teacher_fallback_acknowledges_new_input_instead_of_replaying_one_template():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="请继续说明你的思路。"),
            AgentDecision(message="请继续说明。"),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    first = orchestrator.handle_user_message(
        "输出空，因为 N=0 时没有项。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-fallback-context-1",
    )
    second = orchestrator.handle_user_message(
        "输入 0，输出为空 null。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-fallback-context-2",
    )

    assert first.primary.response != second.primary.response
    assert "N=0" in first.primary.response
    assert "字面量 null" in second.primary.response
    assert len(model.calls) == 2


def test_repeated_teacher_probe_calls_are_bounded_with_a_public_reply():
    probe_decisions = [
        AgentDecision(tool_calls=[ToolCall(
            f"probe-{index}",
            "request_student_probe",
            {
                "concept": "循环边界",
                "dimension": "edge_case",
                "goal": "检查用户能否解释边界情况",
            },
        )])
        for index in range(1, 5)
    ]
    runtime, _, _ = make_runtime(decisions=probe_decisions)

    result = Stage3Orchestrator(runtime).handle_user_message(
        "老师，请让小明检查这个边界。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-repeated-probe-1",
    )

    assert result.primary.success is True
    assert result.primary.response
    assert result.primary.error_code is None
    assert result.interventions == []


def test_teacher_probe_intent_is_consumed_by_the_next_current_student_turn():
    runtime, _, _ = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("probe-1", "request_student_probe", {
                "concept": "循环边界",
                "dimension": "edge_case",
                "goal": "检查用户能否解释边界情况",
            })]),
            AgentDecision(message="老师已安排我从当前边界继续检查。"),
            AgentDecision(message="赵一，请结合一个具体输入说说 N=0 时会输出什么，以及为什么。"),
        ],
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "老师，请让小明检查这个边界。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-trigger-plain-student-1",
    )

    assert result.primary.success is True
    assert result.interventions == []
    state = runtime.memory.load(runtime.session.id).state
    assert state.student_probe_intent == {
        "concept": "循环边界",
        "dimension": "edge_case",
        "goal": "检查用户能否解释边界情况",
    }
    second = Stage3Orchestrator(runtime).handle_user_message(
        "好的，我来回应这个问题。",
        target_role=Stage3Target.AUTO,
        request_id="teacher-trigger-current-2",
    )
    assert second.primary.success is True
    assert second.primary.agent is AgentRole.STUDENT_AGENT
    assert second.primary.response == (
        "赵一，我还不太会“循环边界”。你可以用简单的话告诉我这道题应该怎么处理吗？"
    )
    # The Teacher's first decision requests the probe; its bounded public
    # response is the second Teacher decision.  The Student opening itself is
    # deterministic and does not consume a provider call.
    assert len(runtime.model.calls) == 2
    assert runtime.memory.load(runtime.session.id).state.pending_probe["question"] == second.primary.response
    assert len([item for item in runtime.memory.forum_events(runtime.session.id) if item["request_id"] == "teacher-trigger-current-2"]) == 2


def test_student_targeted_explanation_enters_student_context_with_server_side_provenance():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("probe-1", "request_student_probe", {
                "concept": "循环边界",
                "dimension": "core",
                "goal": "先检查用户能否解释边界条件",
            })]),
            AgentDecision(message="先看循环边界。"),
            AgentDecision(tool_calls=[ToolCall("assess-1", "assess_teaching_progress", {
                "assessment": "covered",
                "evidence": "因为 i < n 会在碰到非法索引前停止，所以最后一个合法位置是 n - 1。",
            })]),
            AgentDecision(tool_calls=[ToolCall("ask-1", "ask_student_probe", {
                "question": "你再说说这个边界为什么不会漏掉最后一个元素？",
            })]),
        ],
    )
    orchestrator = Stage3Orchestrator(runtime)

    first = orchestrator.handle_user_message(
        "老师，我先问一下这个边界。",
        target_role=AgentRole.TEACHER_AGENT,
        request_id="teacher-1",
    )
    assert first.interventions == []
    second = orchestrator.handle_user_message(
        "因为 i < n 会在碰到非法索引前停止，所以最后一个合法位置是 n - 1。",
        target_role=Stage3Target.STUDENT_AGENT,
        request_id="student-1",
    )

    assert first.primary.response == "先看循环边界。"
    assert second.primary.success is True
    assert second.primary.response == "赵一，你再说说这个边界为什么不会漏掉最后一个元素？"

    student_context = model.calls[2]["context"]
    assert "因为 i < n 会在碰到非法索引前停止，所以最后一个合法位置是 n - 1。" in student_context
    assert "先看循环边界。" in student_context

    forum_events = runtime.memory.forum_events(runtime.session.id)
    user_event = next(item for item in forum_events if item["request_id"] == "student-1" and item["source_role"] == "user")
    assert user_event["target_role"] == "student_agent"
    assert user_event["reply_to_event_id"] is None
    assert user_event["parent_request_id"] == "student-1"
    student_reply_event = next(
        item
        for item in forum_events
        if item["request_id"] == "student-1"
        and item["source_role"] == "student_agent"
    )
    assert student_reply_event["reply_to_event_id"] == user_event["event_id"]
    assert student_reply_event["parent_request_id"] == "student-1"

    state = runtime.memory.load(runtime.session.id).state
    assert state.concept_coverage[0]["concept"] == "循环边界"
    assert state.concept_coverage[0]["last_evidence_event_id"] == "student-1"


def test_student_context_exposes_coverage_progress_and_pending_probe_to_model():
    runtime, model, _ = make_runtime(
        decisions=[AgentDecision(message="收到，我会检查下一个维度。")],
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={"state": {
            "concept_coverage": [
                _coverage_entry(
                    "循环边界",
                    status="covered",
                    attempts=1,
                    used_dimensions=["core"],
                    attempt_event_ids=["covered-1"],
                    accepted_evidence_count=1,
                    evidence_event_ids=["covered-1"],
                    last_evidence_event_id="covered-1",
                ),
                _coverage_entry("不变量", status="partial", attempts=1, used_dimensions=["core"]),
            ],
            "coverage_score": 0.5,
            "unresolved_concepts": ["不变量"],
            "ready_for_code": False,
            "pending_probe": {"concept": "不变量", "dimension": "edge_case"},
        }},
    )

    result = Stage3Orchestrator(runtime).handle_user_message(
        "我已经解释了这个边界。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-context-progress-1",
    )

    assert result.primary.success is True
    context = json.loads(model.calls[0]["context"])
    assert context["coverage"]["coverage_score"] == 0.5
    assert context["coverage"]["unresolved_concepts"] == ["不变量"]
    assert context["coverage"]["pending_probe"] == {
        "concept": "不变量",
        "dimension": "edge_case",
    }
    assert "assess_teaching_progress" in model.calls[0]["system_prompt"]
    assert "不要重复已经问过的问题" in model.calls[0]["system_prompt"]


def test_student_text_response_does_not_generate_code_before_coverage_is_ready():
    runtime, _, event_store = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("assess-1", "assess_teaching_progress", {
                "assessment": "partial",
                "evidence": "我知道它会在数组范围内停下，但还不能完整说明原因。",
            })]),
            AgentDecision(message="再解释一下为什么最后一个合法索引不是 n。"),
        ],
        buggy_code_generator=lambda context: {
            "buggy_code": "int main() { return 1; }",
            "bugs": [{"line": 1, "description": "返回值错误", "correct_version": "return 0;"}],
            "message": "内部代码说明",
        },
    )
    orchestrator = Stage3Orchestrator(runtime)
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={"state": {
            "concept_coverage": [
                _coverage_entry("循环边界", status="unseen"),
                _coverage_entry("不变量", status="unseen"),
            ],
            "coverage_score": 0.0,
            "unresolved_concepts": ["循环边界", "不变量"],
            "ready_for_code": False,
            "pending_probe": {"concept": "循环边界", "dimension": "core"},
        }},
    )

    result = orchestrator.handle_user_message(
        "我只知道它会在范围内停下，但还说不完整。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-partial-1",
    )

    assert result.primary.success is True
    assert result.primary.ui_action is UIAction.CONTINUE_CHAT
    assert result.primary.ready_for_code is False
    assert result.primary.response == "赵一，再解释一下为什么最后一个合法索引不是 n。"
    assert result.interventions == []
    assert [event.event_type for event in event_store.events].count("buggy_attempt") == 0


def test_student_ready_state_auto_generates_buggy_attempt_from_same_request_flow():
    runtime, model, event_store = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("assess-1", "assess_teaching_progress", {
                "assessment": "covered",
                "evidence": "每轮循环都先检查索引是否小于长度，所以到达 length 时就会停下，最后一个合法位置只能是 length - 1。",
            })]),
        ],
        buggy_code_generator=lambda context: {
            "buggy_code": "int main() { return 1; }",
            "bugs": [{"line": 1, "description": "返回值错误", "correct_version": "return 0;"}],
            "message": "不应公开这段内部说明。",
        },
    )
    orchestrator = Stage3Orchestrator(runtime)
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={"state": {
            "concept_coverage": [
                _coverage_entry(
                    "循环边界",
                    status="covered",
                    attempts=1,
                    used_dimensions=["core"],
                    attempt_event_ids=["evt-covered"],
                    accepted_evidence_count=1,
                    evidence_event_ids=["evt-covered"],
                    last_evidence_event_id="evt-covered",
                ),
                _coverage_entry("不变量", status="unseen"),
            ],
            "coverage_score": 0.5,
            "unresolved_concepts": ["不变量"],
            "ready_for_code": False,
            "pending_probe": {"concept": "不变量", "dimension": "core"},
        }},
    )

    result = orchestrator.handle_user_message(
        "每轮进入循环前都保证条件成立，等索引到达 length 时就停止，所以不会读到数组外面。",
        target_role=AgentRole.STUDENT_AGENT,
        request_id="student-ready-1",
    )

    assert result.primary.success is True
    assert result.primary.ui_action is UIAction.SHOW_CODE_REVIEW
    assert result.primary.ready_for_code is True
    assert result.primary.response == "我写了一版代码，请帮我检查。"
    assert result.primary.public_content["buggy_code"] == "int main() { return 1; }"
    assert result.interventions == []
    assert [event.event_type for event in event_store.events].count("buggy_attempt") == 1
    assert len(model.calls) == 1
    triggering_event = next(
        item
        for item in runtime.memory.forum_events(runtime.session.id)
        if item["request_id"] == "student-ready-1" and item["source_role"] == "user"
    )
    code_review_event = next(
        item
        for item in runtime.memory.forum_events(runtime.session.id)
        if item["request_id"] == "student-ready-1:generate_buggy_attempt"
        and item["source_role"] == "student_agent"
    )
    assert code_review_event["target_role"] == "user"
    assert code_review_event["reply_to_event_id"] == triggering_event["event_id"]
    assert code_review_event["parent_request_id"] == "student-ready-1"


def test_runtime_signal_boundary_discards_extra_private_signal_keys():
    runtime, _, _ = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("probe-1", "request_student_probe", {
                "concept": "循环边界",
                "dimension": "core",
                "goal": "检查用户能否解释边界情况",
            })]),
            AgentDecision(message="请继续解释。"),
        ],
    )
    original_execute = runtime.tools.execute

    def leaky_execute(role, call, context):
        result = original_execute(role, call, context)
        if call.name != "request_student_probe" or not result.ok:
            return result
        return ToolResult(
            ok=result.ok,
            model_content=dict(result.model_content),
            public_content=dict(result.public_content),
            internal_content={
                **result.internal_content,
                "reference_code": "int secret() { return 1; }",
                "hidden_code": "return 1;",
                "tool_arguments": {"secret": True},
            },
            state_patch=dict(result.state_patch),
            memory_events=list(result.memory_events),
            error_code=result.error_code,
            signal_type=result.signal_type,
            retryable=result.retryable,
        )

    runtime.tools.execute = leaky_execute
    result = runtime.handle_chat(
        AgentRole.TEACHER_AGENT,
        "请继续。",
        request_id="signal-boundary-1",
    )

    assert result.internal_signals == {
        "student_probe": {
            "concept": "循环边界",
            "dimension": "core",
            "goal": "检查用户能否解释边界情况",
        }
    }
    dumped = json.dumps(result.internal_signals, ensure_ascii=False)
    assert "reference_code" not in dumped
    assert "hidden_code" not in dumped
    assert "tool_arguments" not in dumped


def test_forum_turn_result_public_dict_omits_internal_and_private_fields():
    result = ForumTurnResult(
        primary=build_feynman_runtime(
            FakeSession(),
            FakeAssignment(),
            FakePreset(),
            model=SequencedModel([AgentDecision(message="继续。")]),
            callbacks=FeynmanCallbacks(event_store=FakeEventStore(), persist_session=lambda session: None),
        ).handle_chat(
            AgentRole.TEACHER_AGENT,
            "请继续解释。",
            request_id="public-1",
        ),
    )
    result.primary.public_content.update({
        "tool_call": {"id": "secret-call", "arguments": {"hidden": True}},
        "trigger": {"concept": "不应公开"},
        "artifact": {"hidden_bug": "secret"},
        "decision": {"next": "private"},
    })

    public = result.to_public_dict()
    dumped = json.dumps(public, ensure_ascii=False)

    assert public["interventions"] == []
    assert "internal_signals" not in dumped
    assert "tool_call" not in dumped
    assert "trigger" not in dumped
    assert "artifact" not in dumped
    assert "decision" not in dumped
def test_plain_student_question_after_assessment_remains_replyable_in_forum():
    runtime, _, _ = make_runtime(
        decisions=[
            AgentDecision(tool_calls=[ToolCall("assess-plain-next", "assess_teaching_progress", {
                "assessment": "covered",
                "evidence": "模型评估用户的回答。",
            })]),
            AgentDecision(message="你能说明一下下一个概念吗？"),
        ],
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={"state": {
            "pending_probe": {"concept": "循环边界", "dimension": "core"},
        }},
    )

    result = runtime.handle_chat(
        AgentRole.STUDENT_AGENT,
        "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
        request_id="student-plain-next",
        event_metadata={
            "source_role": "user",
            "target_role": "student_agent",
            "message_kind": "user_message",
            "visibility": "public",
        },
    )

    assert result.success is True
    event = next(
        item for item in runtime.memory.forum_events(runtime.session.id)
        if item["request_id"] == "student-plain-next"
        and item["source_role"] == "student_agent"
    )
    assert event["message_kind"] == "student_probe"


def test_student_explanation_without_assessment_is_retried_once_with_server_constraint():
    runtime, model, _ = make_runtime(
        decisions=[
            AgentDecision(message="你再说说这个边界。"),
            AgentDecision(tool_calls=[ToolCall("assess-retry", "assess_teaching_progress", {
                "assessment": "covered",
                "evidence": "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
            })]),
            AgentDecision(message="我们再看下一个概念。"),
        ],
    )
    runtime.memory.append_event(
        runtime.session.id,
        "state_snapshot",
        "student_agent",
        metadata={"state": {
            "concept_coverage": [
                _coverage_entry("循环边界", status="unseen"),
                _coverage_entry("不变量", status="unseen"),
            ],
            "coverage_score": 0.0,
            "unresolved_concepts": ["循环边界", "不变量"],
            "ready_for_code": False,
            "pending_probe": {"concept": "循环边界", "dimension": "core"},
        }},
    )

    result = runtime.handle_chat(
        AgentRole.STUDENT_AGENT,
        "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
        request_id="student-assessment-retry-1",
    )

    assert result.success is True
    assert result.response == "我们再看下一个概念。"
    state = runtime.memory.load(runtime.session.id).state
    assert state.concept_coverage[0]["status"] == "covered"
    assert state.pending_probe == {"concept": "不变量", "dimension": "core"}
    assert len(model.calls) == 3
    assert "必须先调用 assess_teaching_progress" in model.calls[1]["system_prompt"]
