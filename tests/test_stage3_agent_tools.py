import json

import pytest

from utils.agents.contracts import AgentRole, FeynmanState, ToolCall
from utils.agents.coverage import CoverageConfig
from utils.agents.memory import MemorySnapshot
from utils.agents.tools import ToolContext, build_feynman_tool_registry


def fake_tool_context(role, *, state=None):
    return ToolContext(
        session_id=12,
        request_id="request-1",
        role=role,
        memory=MemorySnapshot(state=state or FeynmanState(session_id=12)),
        key_concepts=["循环边界", "不变量"],
        coverage_config=CoverageConfig(),
    )


def test_tool_context_preserves_legacy_positional_constructor_order():
    snapshot = MemorySnapshot(state=FeynmanState(session_id=12))
    executed_results = {"call-1": "stored"}

    context = ToolContext(
        12,
        "request-1",
        AgentRole.TEACHER_AGENT,
        snapshot,
        "循环练习",
        ["循环边界"],
        "reference code",
        executed_results,
    )

    assert context.session_id == 12
    assert context.request_id == "request-1"
    assert context.role is AgentRole.TEACHER_AGENT
    assert context.memory is snapshot
    assert context.assignment_title == "循环练习"
    assert context.key_concepts == ["循环边界"]
    assert context.reference_code == "reference code"
    assert context.executed_results is executed_results
    assert context.input_kind == "chat"
    assert context.target_role == ""
    assert context.trigger is None


def ready_fix_context():
    state = FeynmanState(
        session_id=12,
        phase="code_review",
        code_review_status="pending",
        learning_evidence=[{"concept": "循环边界", "evidence": "能够解释边界条件。"}],
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT, state=state)
    context.reference_code = "int main() { return 0; }"
    context.memory.code_artifact_index["artifact-1"] = {"artifact": {
        "buggy_code": "int main() { return 1; }",
        "bugs": [{"description": "返回值错误", "correct_version": "return 0;"}],
    }}
    return context


def test_student_agent_cannot_call_evaluate_fix_as_teacher():
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: {},
        fix_evaluator=lambda context, fixed_code: {"correct": True},
    )

    result = registry.execute(
        role=AgentRole.TEACHER_AGENT,
        call=ToolCall("c1", "evaluate_fix", {"fixed_code": "answer"}),
        context=fake_tool_context(AgentRole.TEACHER_AGENT),
    )

    assert result.ok is False
    assert result.error_code == "TOOL_NOT_ALLOWED"


def test_buggy_attempt_keeps_hidden_bugs_out_of_model_content():
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: {
            "buggy_code": "code",
            "bugs": [{"line": 1, "description": "hidden"}],
            "message": "我写了一版。",
        },
        fix_evaluator=lambda context, fixed_code: {"correct": False},
    )

    result = registry.execute(
        role=AgentRole.STUDENT_AGENT,
        call=ToolCall("c1", "generate_buggy_attempt", {}),
        context=fake_tool_context(AgentRole.STUDENT_AGENT),
    )

    assert result.public_content["buggy_code"] == "code"
    assert "hidden" not in json.dumps(result.model_content, ensure_ascii=False)
    assert result.memory_events[0]["metadata"]["artifact"]["bugs"] == [{"line": 1, "description": "hidden"}]


def test_callback_message_and_feedback_are_replaced_with_server_safe_text():
    hidden_bug = "HIDDEN_BUG_SENTINEL"
    standard_answer = "STANDARD_ANSWER_SENTINEL"
    correct_fix = "CORRECT_FIX_SENTINEL"
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: {
            "buggy_code": "safe public code",
            "bugs": [{"description": hidden_bug, "fix": correct_fix}],
            "message": f"{hidden_bug} {standard_answer} {correct_fix}",
        },
        fix_evaluator=lambda context, fixed_code: {
            "correct": False,
            "feedback": f"{hidden_bug} {standard_answer} {correct_fix}",
        },
    )

    generation = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("generate", "generate_buggy_attempt", {}),
        fake_tool_context(AgentRole.STUDENT_AGENT, state=FeynmanState(session_id=12)),
    )
    evaluation = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("evaluate", "evaluate_fix", {"fixed_code": "answer"}),
        ready_fix_context(),
    )

    exposed = json.dumps(
        [generation.model_content, generation.public_content, evaluation.model_content, evaluation.public_content],
        ensure_ascii=False,
    )
    assert generation.public_content["buggy_code"] == "safe public code"
    assert generation.public_content["message"] == "我写了一版代码，请帮我检查。"
    assert evaluation.public_content["feedback"] == "请继续检查代码逻辑。"
    for sentinel in (hidden_bug, standard_answer, correct_fix):
        assert sentinel not in exposed


def test_generated_code_with_server_or_hidden_values_is_rejected_without_disclosure():
    hidden_bug = "HIDDEN_BUG_SENTINEL"
    standard_answer = "STANDARD_ANSWER_SENTINEL"
    correct_fix = "CORRECT_FIX_SENTINEL"
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: {
            "buggy_code": f"{standard_answer} {hidden_bug} {correct_fix}",
            "bugs": [{"description": hidden_bug, "fix": correct_fix}],
            "message": "unsafe callback message",
        },
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.reference_code = standard_answer

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("generate", "generate_buggy_attempt", {}),
        context,
    )

    assert (result.ok, result.error_code) == (False, "BUGGY_ATTEMPT_INVALID")
    exposed = json.dumps([result.model_content, result.public_content], ensure_ascii=False)
    for sentinel in (hidden_bug, standard_answer, correct_fix):
        assert sentinel not in exposed


def test_default_buggy_attempt_recovers_when_model_returns_an_unchanged_code(monkeypatch):
    from utils import thinking_ai

    monkeypatch.setattr(
        thinking_ai,
        "student_agent_write_code",
        lambda *args: {
            "buggy_code": "int main() { return 0; }",
            "bugs": [{"description": "看起来有问题", "correct_version": "return 0;"}],
            "message": "模型没有真正改动代码。",
        },
    )
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.reference_code = "int main() { return 0; }"

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("generate", "generate_buggy_attempt", {}),
        context,
    )

    assert result.ok is True
    assert result.public_content["buggy_code"] == "int main() { return 1; }"
    assert result.public_content["message"] == "我写了一版代码，请帮我检查。"


@pytest.mark.parametrize("generated", [
    {
        "buggy_code": "int main() { return 1; }",
        "bugs": [],
        "message": "empty bugs",
    },
    {
        "buggy_code": "int main() { return 0; } // added comment",
        "bugs": [{"description": "只有注释不同", "correct_version": "将返回值恢复为零"}],
        "message": "comment only",
    },
])
def test_buggy_attempt_requires_structured_nontrivial_mutation(generated):
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: generated,
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.reference_code = "int main() { return 0; }"

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("generate", "generate_buggy_attempt", {}),
        context,
    )

    assert (result.ok, result.error_code) == (False, "BUGGY_ATTEMPT_INVALID")


def test_default_fix_evaluator_requires_deterministic_bug_elimination(monkeypatch):
    from utils import thinking_ai

    monkeypatch.setattr(
        thinking_ai,
        "evaluate_feynman_code_fix",
        lambda *args: (True, "模型声称正确"),
    )
    registry = build_feynman_tool_registry()
    state = FeynmanState(
        session_id=12,
        phase="code_review",
        code_review_status="pending",
        learning_evidence=[{"concept": "循环边界", "evidence": "能够解释边界条件。"}],
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT, state=state)
    context.reference_code = "int main() { return 0; }"
    context.memory.code_artifact_index["artifact-1"] = {"artifact": {
        "buggy_code": "int main() { return 1; }",
        "bugs": [{"description": "返回值错误", "correct_version": "return 0;"}],
    }}

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("evaluate", "evaluate_fix", {
            "fixed_code": "int main() { return 99; }",
        }),
        context,
    )

    assert result.ok is True
    assert result.public_content["correct"] is False


def test_default_fix_evaluator_accepts_exact_reference_when_model_misjudges(monkeypatch):
    from utils import thinking_ai

    monkeypatch.setattr(
        thinking_ai,
        "evaluate_feynman_code_fix",
        lambda *args: (False, "模型误判为错误"),
    )
    registry = build_feynman_tool_registry()
    state = FeynmanState(
        session_id=12,
        phase="code_review",
        code_review_status="pending",
        learning_evidence=[{"concept": "循环边界", "evidence": "已完成覆盖评估。"}],
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT, state=state)
    context.reference_code = "int main() { return 0; }"
    context.memory.code_artifact_index["artifact-1"] = {"artifact": {
        "buggy_code": "int main() { return 1; }",
        "bugs": [{"line": 1, "description": "返回值错误", "correct_version": "return 0;"}],
    }}

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("evaluate-exact-reference", "evaluate_fix", {
            "fixed_code": "int main() { return 0; }",
        }),
        context,
    )

    assert result.ok is True
    assert result.public_content["correct"] is True


def test_no_key_buggy_code_fallback_is_never_the_reference(monkeypatch):
    from utils import thinking_ai

    class UnavailableClient:
        def is_available(self):
            return False

    monkeypatch.setattr(thinking_ai, "SharedLLMClient", UnavailableClient)
    reference = "int main() { return 0; }"

    generated = thinking_ai.student_agent_write_code(
        "返回值练习", ["返回值"], reference, [],
    )

    assert generated["buggy_code"] != reference
    assert generated["bugs"]
    assert all(isinstance(bug, dict) and bug.get("description") for bug in generated["bugs"])


def test_default_evaluator_rejects_string_boolean(monkeypatch):
    from utils import thinking_ai

    class FakeClient:
        def is_available(self):
            return True

        def chat(self, *args, **kwargs):
            return '{"correct":"false","feedback":"仍有错误","identified_bugs":0}'

    monkeypatch.setattr(thinking_ai, "SharedLLMClient", FakeClient)

    with pytest.raises(RuntimeError, match="格式"):
        thinking_ai.evaluate_feynman_code_fix(
            "return 1;",
            "return 0;",
            [{"description": "返回值错误", "correct_version": "return 0;"}],
            "return 0;",
        )


def test_unknown_tool_returns_structured_error():
    result = build_feynman_tool_registry().execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("c1", "does_not_exist", {}),
        fake_tool_context(AgentRole.TEACHER_AGENT),
    )

    assert result.ok is False
    assert result.error_code == "UNKNOWN_TOOL"


def test_schema_rejects_unknown_missing_and_oversized_arguments():
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)

    for arguments in (
        {},
        {"fixed_code": "ok", "unexpected": True},
        {"fixed_code": "x" * 8001},
    ):
        result = registry.execute(
            AgentRole.STUDENT_AGENT,
            ToolCall("c1", "evaluate_fix", arguments),
            context,
        )
        assert result.ok is False
        assert result.error_code == "INVALID_TOOL_ARGUMENTS"


def test_side_effect_tool_reuses_cached_result_for_duplicate_call_id():
    calls = []
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: calls.append(context.request_id) or {
            "buggy_code": "code", "bugs": [{"line": 1, "description": "错误"}], "message": "请看看。"
        },
    )
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    call = ToolCall("same-id", "generate_buggy_attempt", {})

    first = registry.execute(AgentRole.STUDENT_AGENT, call, context)
    second = registry.execute(AgentRole.STUDENT_AGENT, call, context)

    assert first.ok is True
    assert second == first
    assert calls == ["request-1"]


def test_callback_failures_are_sanitized():
    registry = build_feynman_tool_registry(
        buggy_code_generator=lambda context: (_ for _ in ()).throw(RuntimeError("secret generator error")),
        fix_evaluator=lambda context, fixed_code: (_ for _ in ()).throw(RuntimeError("secret evaluator error")),
    )

    generation = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("generate", "generate_buggy_attempt", {}),
        fake_tool_context(AgentRole.STUDENT_AGENT),
    )
    evaluation = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("evaluate", "evaluate_fix", {"fixed_code": "answer"}),
        ready_fix_context(),
    )

    assert (generation.ok, generation.error_code) == (False, "BUGGY_ATTEMPT_FAILED")
    assert (evaluation.ok, evaluation.error_code) == (False, "FIX_EVALUATION_FAILED")
    assert "secret" not in json.dumps(generation.model_content)
    assert "secret" not in json.dumps(evaluation.model_content)


def test_learning_evidence_and_completion_are_server_validated():
    registry = build_feynman_tool_registry()
    state = FeynmanState(session_id=12, phase="code_review", code_review_status="passed")
    context = fake_tool_context(AgentRole.TEACHER_AGENT, state=state)

    evidence = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("evidence", "record_learning_evidence", {
            "concept": "循环边界", "evidence": "能够解释 i < n 的原因。",
        }),
        context,
    )
    context.memory.state.learning_evidence = evidence.state_patch["learning_evidence"]
    completion = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("complete", "complete_goal", {}),
        context,
    )

    assert evidence.ok is True
    assert evidence.state_patch["learning_evidence"][-1]["concept"] == "循环边界"
    assert completion.ok is True
    assert completion.state_patch == {"status": "complete"}


def test_student_agent_can_record_valid_learning_evidence():
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("student-evidence", "record_learning_evidence", {
            "concept": "循环边界", "evidence": "我能解释为什么循环条件使用 i < n。",
        }),
        context,
    )

    assert result.ok is True
    assert result.state_patch["learning_evidence"] == [{
        "concept": "循环边界", "evidence": "我能解释为什么循环条件使用 i < n。",
    }]
    assert result.memory_events == [{
        "event_type": "learning_evidence",
        "metadata": {"evidence": result.state_patch["learning_evidence"][0]},
    }]


def test_unknown_concept_cannot_create_evidence_or_enable_completion():
    registry = build_feynman_tool_registry()
    state = FeynmanState(session_id=12, phase="code_review", code_review_status="passed")
    context = fake_tool_context(AgentRole.TEACHER_AGENT, state=state)

    evidence = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("unknown", "record_learning_evidence", {
            "concept": "伪造概念", "evidence": "我随便写了一段看起来足够长的话。",
        }),
        context,
    )
    completion = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("complete", "complete_goal", {}),
        context,
    )

    assert (evidence.ok, evidence.error_code, evidence.state_patch) == (
        False, "INVALID_LEARNING_EVIDENCE", {},
    )
    assert (completion.ok, completion.error_code) == (False, "GOAL_NOT_READY")


def test_meaningless_evidence_for_known_concept_is_rejected():
    registry = build_feynman_tool_registry()

    result = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("empty-evidence", "record_learning_evidence", {
            "concept": "循环边界", "evidence": "不知道",
        }),
        fake_tool_context(AgentRole.TEACHER_AGENT),
    )

    assert (result.ok, result.error_code, result.state_patch) == (
        False, "INVALID_LEARNING_EVIDENCE", {},
    )


def test_teacher_probe_request_only_returns_redacted_internal_signal():
    registry = build_feynman_tool_registry()

    result = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("probe-1", "request_student_probe", {
            "concept": "循环边界",
            "dimension": "edge_case",
            "goal": "检查用户能否解释边界情况",
        }),
        fake_tool_context(AgentRole.TEACHER_AGENT),
    )

    assert result.ok is True
    assert result.signal_type == "student_probe"
    assert result.internal_content == {
        "concept": "循环边界",
        "dimension": "edge_case",
        "goal": "检查用户能否解释边界情况",
    }
    assert result.public_content == {}
    assert result.memory_events == []
    assert result.model_content == {"accepted": True}


def test_teacher_probe_request_normalizes_model_semantic_labels_to_server_values():
    registry = build_feynman_tool_registry()

    result = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("probe-semantic-labels", "request_student_probe", {
            "concept": "边界条件处理",
            "dimension": "特殊情况分析",
            "goal": "检查用户能否解释边界情况",
        }),
        fake_tool_context(AgentRole.TEACHER_AGENT),
    )

    assert result.ok is True
    assert result.internal_content == {
        "concept": "循环边界",
        "dimension": "edge_case",
        "goal": "检查用户能否解释边界情况",
    }


@pytest.mark.parametrize("question", [
    "   ",
    "我也懂了。",
    "我知道答案了。",
    "最后一个索引是 n - 1。",
])
def test_student_probe_question_must_be_a_real_question_without_self_confirmation(question):
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.trigger = {
        "concept": "循环边界",
        "dimension": "core",
        "goal": "检查用户能否解释为什么不会越界",
    }

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("probe-ask", "ask_student_probe", {"question": question}),
        context,
    )

    assert (result.ok, result.error_code) == (False, "INVALID_STUDENT_PROBE")
    assert result.public_content == {}
    assert result.memory_events == []


def test_student_probe_question_uses_server_target_and_persists_pending_probe():
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.trigger = {
        "concept": "循环边界",
        "dimension": "core",
        "goal": "检查用户能否解释为什么不会越界",
    }

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("probe-ask", "ask_student_probe", {
            "question": "你能解释一下为什么 i < n 不会越界吗？",
        }),
        context,
    )

    assert result.ok is True
    assert result.public_content == {
        "message": "你能解释一下为什么 i < n 不会越界吗？",
    }
    assert result.state_patch == {
        "pending_probe": {
            "concept": "循环边界",
            "dimension": "core",
            "question": "你能解释一下为什么 i < n 不会越界吗？",
        }
    }


def test_assess_teaching_progress_is_student_only_and_uses_reducer_state_patch():
    registry = build_feynman_tool_registry()
    state = FeynmanState(session_id=12, pending_probe={
        "concept": "循环边界",
        "dimension": "core",
    })
    student_context = fake_tool_context(AgentRole.STUDENT_AGENT, state=state)
    teacher_context = fake_tool_context(AgentRole.TEACHER_AGENT, state=state)

    forbidden = registry.execute(
        AgentRole.TEACHER_AGENT,
        ToolCall("assess-teacher", "assess_teaching_progress", {
            "assessment": "covered",
            "evidence": "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
        }),
        teacher_context,
    )
    allowed = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("assess-student", "assess_teaching_progress", {
            "assessment": "covered",
            "evidence": "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
        }),
        student_context,
    )

    assert (forbidden.ok, forbidden.error_code, forbidden.public_content, forbidden.memory_events) == (
        False, "TOOL_NOT_ALLOWED", {}, [],
    )
    assert allowed.ok is True
    assert allowed.state_patch["concept_coverage"][0]["concept"] == "循环边界"
    assert allowed.state_patch["coverage_score"] == pytest.approx(0.5)
    assert allowed.state_patch["pending_probe"] == {
        "concept": "不变量",
        "dimension": "core",
    }


def test_assess_teaching_progress_normalizes_common_model_labels():
    registry = build_feynman_tool_registry()
    state = FeynmanState(session_id=12, pending_probe={
        "concept": "循环边界",
        "dimension": "core",
    })
    context = fake_tool_context(AgentRole.STUDENT_AGENT, state=state)

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("assess-alias", "assess_teaching_progress", {
            "assessment": "correct",
            "evidence": "因为 i < n 会在到达非法索引前停止，所以最后一个合法位置是 n - 1。",
        }),
        context,
    )

    assert result.ok is True
    assert result.state_patch["concept_coverage"][0]["status"] == "covered"
def test_assess_teaching_progress_uses_the_current_user_explanation_as_evidence():
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.trigger = {
        "concept": "循环边界",
        "dimension": "core",
        "goal": "检查用户能否解释边界条件",
    }
    context.memory.visible_messages[AgentRole.STUDENT_AGENT] = [{
        "role": "student",
        "event_type": "agent_user_message",
        "content": "我会先读入 N；N=0 没有项，N=1 只有 0，从 i=2 循环到 i<n，用前两项相加得到下一项。",
    }]

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("assess-user-text", "assess_teaching_progress", {
            "assessment": "covered",
            "evidence": "模型判断用户还没有解释清楚。",
        }),
        context,
    )

    assert result.ok is True
    assert result.state_patch["concept_coverage"][0]["status"] == "covered"


def test_partial_assessment_is_promoted_when_user_explanation_covers_the_probe():
    registry = build_feynman_tool_registry()
    context = fake_tool_context(AgentRole.STUDENT_AGENT)
    context.trigger = {
        "concept": "循环边界",
        "dimension": "core",
        "goal": "检查用户能否解释边界条件",
    }
    context.memory.visible_messages[AgentRole.STUDENT_AGENT] = [{
        "role": "student",
        "event_type": "agent_user_message",
        "content": (
            "先读入 N，输出下标 0 到 N-1 的前 N 项；N=0 不输出，N=1 只输出 0。"
            "循环从 i=2 且 i<n 开始，计算 next=a+b 后更新 a=b、b=next，最后按顺序输出，避免越界。"
        ),
    }]

    result = registry.execute(
        AgentRole.STUDENT_AGENT,
        ToolCall("assess-partial-but-complete", "assess_teaching_progress", {
            "assessment": "partial",
            "evidence": "模型认为用户还需要继续说明。",
        }),
        context,
    )

    assert result.ok is True
    assert result.state_patch["concept_coverage"][0]["status"] == "covered"
