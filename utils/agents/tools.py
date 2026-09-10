"""Server-authoritative Stage 3 agent tools.

Tool schemas and permissions live here rather than in model prompts.  Handler
results deliberately keep private artifacts out of ``model_content``.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional

from .coverage import CoverageConfig, apply_coverage_assessment
from .contracts import AgentRole, ToolCall, ToolResult
from .memory import MemorySnapshot


MAX_CONCEPT_CHARS = 200
MAX_EVIDENCE_CHARS = 2_000
MAX_FIXED_CODE_CHARS = 8_000
MAX_GOAL_CHARS = 300
MAX_PROBE_DIMENSION_CHARS = 64
MAX_PROBE_QUESTION_CHARS = 500
_SAFE_CODE_REVIEW_MESSAGE = "我写了一版代码，请帮我检查。"
_SAFE_PASSED_FEEDBACK = "修复已通过检查。"
_SAFE_FAILED_FEEDBACK = "请继续检查代码逻辑。"
_ASSESSMENT_ALIASES = {
    "covered": "covered",
    "correct": "covered",
    "complete": "covered",
    "understood": "covered",
    "mastered": "covered",
    "正确": "covered",
    "掌握": "covered",
    "已掌握": "covered",
    "partial": "partial",
    "partially": "partial",
    "partially_correct": "partial",
    "incomplete": "partial",
    "部分": "partial",
    "不完整": "partial",
    "off_topic": "off_topic",
    "off-topic": "off_topic",
    "irrelevant": "off_topic",
    "跑题": "off_topic",
    "无关": "off_topic",
}
_PROBE_CONCEPT_SEMANTICS = (
    ("input", ("输入", "读入", "input", "read")),
    ("boundary", ("边界", "特殊", "极端", "异常", "n=0", "n=1", "n0", "n1")),
    ("loop", ("循环", "迭代", "相邻", "前两项", "变量", "更新", "下一项", "loop")),
    ("output", ("输出", "打印", "顺序", "output", "print")),
)
_PROBE_DIMENSION_SEMANTICS = {
    "core": ("core", "核心", "基础", "基本", "原理"),
    "edge_case": ("edge_case", "edge case", "边界", "特殊", "异常", "极端"),
    "application": ("application", "应用", "场景", "实例", "实践"),
}
_SELF_CONFIRMING_PROBE_PATTERNS = (
    re.compile(r"我也(?:懂了|明白了|会了)"),
    re.compile(r"我知道答案"),
    re.compile(r"\b(?:i\s+also\s+understand|i\s+know\s+the\s+answer)\b", re.IGNORECASE),
)
_QUESTION_HINT_PATTERNS = (
    re.compile(r"[?？]\s*$"),
    re.compile(r"(为什么|怎么|如何|是否|能否|能不能|请问)"),
    re.compile(r"\b(why|how|what|which|when|where|could|can|would|do|does|did|is|are)\b", re.IGNORECASE),
)

ToolHandler = Callable[["ToolContext", Dict[str, Any]], ToolResult]
BuggyCodeGenerator = Callable[["ToolContext"], Mapping[str, Any]]
FixEvaluator = Callable[["ToolContext", str], Any]


@dataclass
class ToolContext:
    session_id: int
    request_id: str
    role: AgentRole
    memory: MemorySnapshot
    assignment_title: str = ""
    key_concepts: List[str] = field(default_factory=list)
    reference_code: str = ""
    executed_results: Dict[str, ToolResult] = field(default_factory=dict)
    input_kind: str = "chat"
    target_role: str = ""
    coverage_config: CoverageConfig = field(default_factory=CoverageConfig)
    trigger: Optional[Dict[str, Any]] = None
    recent_public_questions: List[str] = field(default_factory=list)
    learner_name: str = "学习者"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    allowed_roles: FrozenSet[AgentRole]
    handler: ToolHandler
    side_effect: bool = False

    def public_spec(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._definitions[definition.name] = definition

    def specs_for(self, role: AgentRole) -> List[Dict[str, Any]]:
        return [
            definition.public_spec()
            for definition in self._definitions.values()
            if role in definition.allowed_roles
        ]

    def is_side_effect(self, name: str) -> bool:
        definition = self._definitions.get(name)
        return bool(definition and definition.side_effect)

    def execute(self, role: AgentRole, call: ToolCall, context: ToolContext) -> ToolResult:
        definition = self._definitions.get(call.name)
        if definition is None:
            return _error("UNKNOWN_TOOL")
        if role is not context.role or role not in definition.allowed_roles:
            return _error("TOOL_NOT_ALLOWED")
        if not self._arguments_match_schema(definition.input_schema, call.arguments):
            return _error("INVALID_TOOL_ARGUMENTS")
        if definition.side_effect and call.call_id in context.executed_results:
            return context.executed_results[call.call_id]

        try:
            result = definition.handler(context, call.arguments)
        except Exception:
            result = _error("TOOL_EXECUTION_FAILED")
        if not isinstance(result, ToolResult):
            result = _error("TOOL_EXECUTION_FAILED")
        if definition.side_effect:
            context.executed_results[call.call_id] = result
        return result

    @staticmethod
    def _arguments_match_schema(schema: Mapping[str, Any], arguments: Any) -> bool:
        if not isinstance(arguments, dict) or schema.get("type", "object") != "object":
            return False
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            return False
        if any(key not in properties for key in arguments):
            return False
        if any(key not in arguments for key in required):
            return False
        return all(
            _value_matches_schema(arguments[key], property_schema)
            for key, property_schema in properties.items()
            if key in arguments
        )


def build_feynman_tool_registry(
    *,
    buggy_code_generator: Optional[BuggyCodeGenerator] = None,
    fix_evaluator: Optional[FixEvaluator] = None,
) -> ToolRegistry:
    generator = buggy_code_generator or _default_buggy_code_generator
    evaluator = fix_evaluator or _default_fix_evaluator
    registry = ToolRegistry()
    both_roles = frozenset({AgentRole.TEACHER_AGENT, AgentRole.STUDENT_AGENT})
    teacher_only = frozenset({AgentRole.TEACHER_AGENT})
    student_only = frozenset({AgentRole.STUDENT_AGENT})

    registry.register(ToolDefinition(
        "inspect_learning_state", "Inspect the current public learning state.",
        _object_schema(), both_roles, _inspect_learning_state,
    ))
    registry.register(ToolDefinition(
        "recall_memory", "Recall messages visible to the current role.",
        _object_schema(), both_roles, _recall_memory,
    ))
    registry.register(ToolDefinition(
        "record_learning_evidence", "Record concrete evidence of learning.",
        _object_schema(
            properties={
                "concept": _string_schema(MAX_CONCEPT_CHARS),
                "evidence": _string_schema(MAX_EVIDENCE_CHARS),
            },
            required=["concept", "evidence"],
        ), both_roles, _record_learning_evidence, side_effect=True,
    ))
    registry.register(ToolDefinition(
        "request_student_probe", "Request one bounded student probe intervention.",
        _object_schema(
            properties={
                "concept": _string_schema(MAX_CONCEPT_CHARS),
                "dimension": _string_schema(MAX_PROBE_DIMENSION_CHARS),
                "goal": _string_schema(MAX_GOAL_CHARS),
            },
            required=["concept", "dimension", "goal"],
        ), teacher_only, _request_student_probe, side_effect=True,
    ))
    registry.register(ToolDefinition(
        "ask_student_probe", "Ask the user one bounded probe question.",
        _object_schema(
            properties={"question": _string_schema(MAX_PROBE_QUESTION_CHARS)},
            required=["question"],
        ), student_only, _ask_student_probe, side_effect=True,
    ))
    registry.register(ToolDefinition(
        "assess_teaching_progress",
        "Assess learning coverage from the current student explanation. Use covered, partial, or off_topic.",
        _object_schema(
            properties={
                "assessment": {
                    **_string_schema(32),
                    "enum": ["covered", "partial", "off_topic"],
                },
                "evidence": _string_schema(MAX_EVIDENCE_CHARS),
            },
            required=["assessment", "evidence"],
        ), student_only, _assess_teaching_progress, side_effect=True,
    ))
    registry.register(ToolDefinition(
        "generate_buggy_attempt", "Generate a student code attempt for review.",
        _object_schema(), student_only, _generate_buggy_attempt(generator), side_effect=True,
    ))
    registry.register(ToolDefinition(
        "evaluate_fix", "Evaluate a submitted code fix.",
        _object_schema(
            properties={"fixed_code": _string_schema(MAX_FIXED_CODE_CHARS)},
            required=["fixed_code"],
        ), student_only, _evaluate_fix(evaluator), side_effect=True,
    ))
    registry.register(ToolDefinition(
        "complete_goal", "Complete the goal after server-side readiness checks.",
        _object_schema(), both_roles, _complete_goal, side_effect=True,
    ))
    return registry


def _object_schema(
    *, properties: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {"type": "object", "properties": properties or {}, "required": required or []}


def _string_schema(maximum: int) -> Dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _value_matches_schema(value: Any, schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    if schema.get("type") != "string" or not isinstance(value, str):
        return False
    minimum = schema.get("minLength", 0)
    maximum = schema.get("maxLength")
    return len(value) >= minimum and (maximum is None or len(value) <= maximum)


def _inspect_learning_state(context: ToolContext, _: Dict[str, Any]) -> ToolResult:
    state = context.memory.state
    content = {
        "phase": state.phase,
        "key_concepts": list(context.key_concepts),
        "learning_evidence": list(state.learning_evidence),
    }
    return ToolResult(ok=True, model_content=content, public_content=content)


def _recall_memory(context: ToolContext, _: Dict[str, Any]) -> ToolResult:
    messages = list(context.memory.visible_messages.get(context.role, []))[-10:]
    content = {"messages": messages}
    return ToolResult(ok=True, model_content=content, public_content=content)


def _record_learning_evidence(context: ToolContext, arguments: Dict[str, Any]) -> ToolResult:
    evidence = {"concept": arguments["concept"], "evidence": arguments["evidence"]}
    if (
        evidence["concept"] not in _allowed_concepts(context)
        or not _is_meaningful_evidence(evidence["evidence"])
    ):
        return _error("INVALID_LEARNING_EVIDENCE")
    all_evidence = [*context.memory.state.learning_evidence, evidence]
    return ToolResult(
        ok=True,
        model_content={"recorded": evidence},
        public_content={"recorded": evidence},
        state_patch={"learning_evidence": all_evidence},
        memory_events=[{"event_type": "learning_evidence", "metadata": {"evidence": evidence}}],
    )


def _request_student_probe(context: ToolContext, arguments: Dict[str, Any]) -> ToolResult:
    existing_intent = getattr(context.memory.state, "student_probe_intent", None)
    existing_probe = getattr(context.memory.state, "pending_probe", None)
    if isinstance(existing_intent, Mapping) or isinstance(existing_probe, Mapping):
        # A model may batch two requests, but the forum protocol admits only
        # one next Student target.  Treat later requests as harmless no-ops so
        # the valid first signal can still finish the current teacher turn.
        return ToolResult(
            ok=True,
            model_content={"accepted": False, "already_scheduled": True},
        )
    concept = _resolve_probe_concept(arguments["concept"], context)
    dimension = _resolve_probe_dimension(arguments["dimension"], context)
    goal = arguments["goal"].strip()
    if concept is None:
        return _error("INVALID_STUDENT_PROBE")
    if dimension is None:
        return _error("INVALID_STUDENT_PROBE")
    if not goal:
        return _error("INVALID_STUDENT_PROBE")
    return ToolResult(
        ok=True,
        model_content={"accepted": True},
        state_patch={
            "student_probe_intent": {
                "concept": concept,
                "dimension": dimension,
                "goal": goal,
            },
        },
        internal_content={
            "concept": concept,
            "dimension": dimension,
            "goal": goal,
        },
        signal_type="student_probe",
    )


def _ask_student_probe(context: ToolContext, arguments: Dict[str, Any]) -> ToolResult:
    target = _current_probe_target(context)
    question = arguments["question"].strip()
    if target is None or not _is_valid_probe_question(question):
        return _error("INVALID_STUDENT_PROBE")
    if _is_duplicate_probe_question(question, context.recent_public_questions):
        # Do not fail the whole turn because a model repeated the teacher's
        # wording.  Keep the turn single-speaker and replace it with a
        # bounded, server-generated new angle.
        question = _fallback_probe_question(target, context.learner_name)
    state_patch = {
        "pending_probe": {
            **target,
            # Keep the exact public wording in server memory so a restored
            # session can tell an unanswered peer question from a merely
            # scheduled Student turn.
            "question": question,
        }
    }
    if isinstance(getattr(context.memory.state, "student_probe_intent", None), Mapping):
        state_patch["student_probe_intent"] = None
    return ToolResult(
        ok=True,
        model_content={"accepted": True, "new_angle": question},
        public_content={"message": question},
        state_patch=state_patch,
    )


def _assess_teaching_progress(context: ToolContext, arguments: Dict[str, Any]) -> ToolResult:
    target = _current_probe_target(context)
    if target is None:
        return _error("INVALID_TEACHING_ASSESSMENT")
    assessment = _normalize_assessment(arguments["assessment"])
    if assessment is None:
        return _error("INVALID_TEACHING_ASSESSMENT")
    evidence = _latest_user_explanation(context) or arguments["evidence"]
    try:
        decision = apply_coverage_assessment(
            context.memory.state,
            context.key_concepts,
            config=context.coverage_config,
            concept=target["concept"],
            dimension=target["dimension"],
            assessment=assessment,
            evidence=evidence,
            event_id=context.request_id,
        )
    except ValueError:
        return _error("INVALID_TEACHING_ASSESSMENT")
    state_patch = dict(decision.state_patch)
    # The current user message has now been consumed by this probe intent.
    if isinstance(getattr(context.memory.state, "student_probe_intent", None), Mapping):
        state_patch["student_probe_intent"] = None
    if decision.concept_status == "covered":
        evidence_item = {
            "concept": target["concept"],
            "evidence": evidence,
        }
        existing_evidence = [
            item
            for item in context.memory.state.learning_evidence
            if isinstance(item, Mapping)
        ]
        if not any(
            item.get("concept") == evidence_item["concept"]
            and item.get("evidence") == evidence_item["evidence"]
            for item in existing_evidence
        ):
            state_patch["learning_evidence"] = [*existing_evidence, evidence_item]
    return ToolResult(
        ok=True,
        model_content={
            "concept_status": decision.concept_status,
            "attempts": decision.attempts,
            "next_concept": decision.next_concept,
            "next_dimension": decision.next_dimension,
            "ready_for_code": decision.ready_for_code,
            "coverage_score": decision.coverage_score,
        },
        state_patch=state_patch,
    )


def _generate_buggy_attempt(generator: BuggyCodeGenerator) -> ToolHandler:
    def handler(context: ToolContext, _: Dict[str, Any]) -> ToolResult:
        recover_with_deterministic_attempt = generator is _default_buggy_code_generator
        try:
            generated = generator(context)
        except Exception:
            if not recover_with_deterministic_attempt:
                return _error("BUGGY_ATTEMPT_FAILED", retryable=True)
            generated = _deterministic_buggy_attempt(context)
        if not isinstance(generated, Mapping):
            if not recover_with_deterministic_attempt:
                return _error("BUGGY_ATTEMPT_FAILED", retryable=True)
            generated = _deterministic_buggy_attempt(context)
        buggy_code = generated.get("buggy_code")
        message = generated.get("message", "")
        bugs = generated.get("bugs", [])
        if not isinstance(buggy_code, str) or not isinstance(message, str) or not isinstance(bugs, list):
            if not recover_with_deterministic_attempt:
                return _error("BUGGY_ATTEMPT_FAILED", retryable=True)
            generated = _deterministic_buggy_attempt(context)
            buggy_code = generated.get("buggy_code")
            message = generated.get("message", "")
            bugs = generated.get("bugs", [])
        if not _generated_code_is_safe(context, buggy_code, bugs):
            if not recover_with_deterministic_attempt:
                return _error("BUGGY_ATTEMPT_INVALID")
            generated = _deterministic_buggy_attempt(context)
            buggy_code = generated.get("buggy_code")
            message = generated.get("message", "")
            bugs = generated.get("bugs", [])
            if not _generated_code_is_safe(context, buggy_code, bugs):
                return _error("BUGGY_ATTEMPT_INVALID")
        visible = {"buggy_code": buggy_code, "message": _SAFE_CODE_REVIEW_MESSAGE}
        return ToolResult(
            ok=True,
            model_content=dict(visible),
            public_content={**visible, "ui_action": "show_code_review"},
            state_patch={"phase": "code_review", "code_review_status": "pending"},
            memory_events=[{
                "event_type": "buggy_attempt",
                "content": message,
                "metadata": {"artifact": {"buggy_code": buggy_code, "bugs": bugs}},
            }],
        )
    return handler


def _deterministic_buggy_attempt(context: ToolContext) -> Mapping[str, Any]:
    """Recover a reviewable mutation when the default model output is unusable."""
    from utils.thinking_ai import _deterministic_buggy_attempt as mutate_reference_code

    return mutate_reference_code(context.reference_code)


def _evaluate_fix(evaluator: FixEvaluator) -> ToolHandler:
    def handler(context: ToolContext, arguments: Dict[str, Any]) -> ToolResult:
        if not _fix_evaluation_is_ready(context):
            return _error("FIX_NOT_READY")
        try:
            evaluation = evaluator(context, arguments["fixed_code"])
        except Exception:
            return _error("FIX_EVALUATION_FAILED", retryable=True)
        correct, _ = _evaluation_fields(evaluation)
        if correct is None:
            return _error("FIX_EVALUATION_FAILED", retryable=True)
        content = {
            "correct": correct,
            "feedback": _SAFE_PASSED_FEEDBACK if correct else _SAFE_FAILED_FEEDBACK,
        }
        patch = {"code_review_status": "passed" if correct else "failed"}
        return ToolResult(ok=True, model_content=content, public_content=content, state_patch=patch)
    return handler


def _evaluation_fields(evaluation: Any) -> tuple[Optional[bool], str]:
    if isinstance(evaluation, Mapping):
        correct = evaluation.get("correct")
        feedback = evaluation.get("feedback", "")
    elif isinstance(evaluation, tuple) and len(evaluation) >= 2:
        correct, feedback = evaluation[0], evaluation[1]
    else:
        return None, ""
    return (correct, str(feedback)) if isinstance(correct, bool) else (None, "")


def _allowed_concepts(context: ToolContext) -> frozenset[str]:
    return frozenset(
        concept.strip()
        for concept in context.key_concepts
        if isinstance(concept, str) and concept.strip()
    )


def _resolve_probe_concept(value: Any, context: ToolContext) -> Optional[str]:
    """Map a model's semantic label to one server-authorized concept.

    The model sees the exact key-concept list, but it may still return a short
    label such as ``边界条件处理``.  The returned value must always be one of
    the server-provided concepts; this helper only bridges that naming gap.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    allowed = [
        concept.strip()
        for concept in context.key_concepts
        if isinstance(concept, str) and concept.strip()
    ]
    text = value.strip()
    if text in allowed:
        return text

    compact = _compact_probe_label(text)
    compact_matches = [
        concept for concept in allowed
        if compact and compact == _compact_probe_label(concept)
    ]
    if len(compact_matches) == 1:
        return compact_matches[0]

    ranked = []
    for concept in allowed:
        candidate = _compact_probe_label(concept)
        score = 0
        if compact and (compact in candidate or candidate in compact):
            score += 8
        for _, aliases in _PROBE_CONCEPT_SEMANTICS:
            query_hit = _contains_probe_alias(compact, aliases)
            candidate_hit = _contains_probe_alias(candidate, aliases)
            if query_hit and candidate_hit:
                score += 3
        if score:
            ranked.append((score, concept))

    if not ranked:
        return None
    best_score = max(score for score, _ in ranked)
    best = [concept for score, concept in ranked if score == best_score]
    return best[0] if len(best) == 1 else None


def _resolve_probe_dimension(value: Any, context: ToolContext) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    allowed = [str(item).strip() for item in context.coverage_config.probe_dimensions]
    text = value.strip()
    if text in allowed:
        return text

    compact = _compact_probe_label(text)
    compact_matches = [
        dimension for dimension in allowed
        if compact and compact == _compact_probe_label(dimension)
    ]
    if len(compact_matches) == 1:
        return compact_matches[0]

    for canonical, aliases in _PROBE_DIMENSION_SEMANTICS.items():
        if not _contains_probe_alias(compact, aliases):
            continue
        canonical_matches = [
            dimension for dimension in allowed
            if _compact_probe_label(dimension) == _compact_probe_label(canonical)
        ]
        if len(canonical_matches) == 1:
            return canonical_matches[0]

    ranked = []
    for dimension in allowed:
        candidate = _compact_probe_label(dimension)
        score = 8 if compact and (compact in candidate or candidate in compact) else 0
        for aliases in _PROBE_DIMENSION_SEMANTICS.values():
            if _contains_probe_alias(compact, aliases) and _contains_probe_alias(candidate, aliases):
                score += 3
        if score:
            ranked.append((score, dimension))
    if not ranked:
        return None
    best_score = max(score for score, _ in ranked)
    best = [dimension for score, dimension in ranked if score == best_score]
    return best[0] if len(best) == 1 else None


def _compact_probe_label(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.strip().casefold())


def _contains_probe_alias(value: str, aliases: Any) -> bool:
    return any(
        _compact_probe_label(alias) and _compact_probe_label(alias) in value
        for alias in aliases
    )


def _latest_user_explanation(context: ToolContext) -> Optional[str]:
    messages = context.memory.visible_messages.get(context.role, [])
    for message in reversed(messages):
        if not isinstance(message, Mapping):
            continue
        if message.get("role") != "student":
            continue
        if message.get("event_type") not in {"agent_user_message", "chat"}:
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _is_meaningful_evidence(value: str) -> bool:
    text = value.strip()
    if len(text) < 5:
        return False
    normalized = text.casefold()
    return normalized not in {"none", "n/a", "不知道", "无", "没有"}


def _normalize_assessment(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace(" ", "_")
    return _ASSESSMENT_ALIASES.get(normalized)


def _generated_code_is_safe(context: ToolContext, buggy_code: str, bugs: List[Any]) -> bool:
    reference_code = context.reference_code.strip()
    if not buggy_code.strip() or not bugs or not all(_structured_bug(bug) for bug in bugs):
        return False
    if reference_code and _semantic_code_key(buggy_code) == _semantic_code_key(reference_code):
        return False
    return not any(
        sensitive in buggy_code
        for sensitive in _internal_artifact_strings(bugs)
    )


def _current_probe_target(context: ToolContext) -> Optional[Dict[str, str]]:
    for candidate in (
        context.trigger,
        getattr(context.memory.state, "pending_probe", None),
        getattr(context.memory.state, "student_probe_intent", None),
    ):
        if not isinstance(candidate, Mapping):
            continue
        concept = candidate.get("concept")
        dimension = candidate.get("dimension")
        if isinstance(concept, str) and concept.strip() and isinstance(dimension, str) and dimension.strip():
            return {"concept": concept.strip(), "dimension": dimension.strip()}
    return None


def _is_duplicate_probe_question(question: str, previous_questions: List[str]) -> bool:
    normalized = _normalize_probe_text(question)
    if not normalized:
        return False
    for previous in previous_questions:
        previous_normalized = _normalize_probe_text(previous)
        if not previous_normalized:
            continue
        if normalized == previous_normalized:
            return True
        if difflib.SequenceMatcher(None, normalized, previous_normalized).ratio() >= 0.78:
            return True
    return False


def _normalize_probe_text(value: Any) -> str:
    return re.sub(r"[\s\u3000，。！？、；：,.!?;:‘’“”\"'()（）]", "", str(value or "")).casefold()


def _fallback_probe_question(target: Mapping[str, str], learner_name: str) -> str:
    dimension = str(target.get("dimension") or "").strip()
    name = str(learner_name or "学习者").strip() or "学习者"
    questions = {
        "core": f"{name}，请用自己的话说明这条规则在代码中具体负责什么？",
        "edge_case": f"{name}，如果输入处在边界值，你认为程序会先执行哪一步？为什么？",
        "application": f"{name}，你能举一个真实场景说明什么时候会用到这条规则吗？",
    }
    return questions.get(dimension, f"{name}，请换一个具体例子说明这条规则如何应用？")


def _is_valid_probe_question(question: str) -> bool:
    if not question:
        return False
    if any(pattern.search(question) for pattern in _SELF_CONFIRMING_PROBE_PATTERNS):
        return False
    return any(pattern.search(question) for pattern in _QUESTION_HINT_PATTERNS)


def _structured_bug(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    description = value.get("description")
    anchors = (
        value.get("fix"),
        value.get("correct_version"),
        value.get("line"),
        value.get("line_hint"),
    )
    return (
        isinstance(description, str)
        and bool(description.strip())
        and any(anchor is not None and str(anchor).strip() for anchor in anchors)
    )


def _semantic_code_key(value: str) -> str:
    without_comments = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", value)
    return re.sub(r"\s+", "", without_comments).casefold()


def _internal_artifact_strings(value: Any) -> List[str]:
    if isinstance(value, Mapping):
        return [item for nested in value.values() for item in _internal_artifact_strings(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _internal_artifact_strings(nested)]
    return [value] if isinstance(value, str) and len(value) >= 8 else []


def _complete_goal(context: ToolContext, _: Dict[str, Any]) -> ToolResult:
    state = context.memory.state
    if (
        not _base_completion_is_ready(context)
        or state.code_review_status not in {"passed", "approved", "complete"}
    ):
        return _error("GOAL_NOT_READY")
    return ToolResult(
        ok=True,
        model_content={"goal_status": "complete"},
        public_content={"goal_status": "complete"},
        state_patch={"status": "complete"},
    )


def _fix_evaluation_is_ready(context: ToolContext) -> bool:
    return (
        _base_completion_is_ready(context)
        and _latest_buggy_artifact(context) is not None
    )


def _base_completion_is_ready(context: ToolContext) -> bool:
    state = context.memory.state
    return state.phase == "code_review" and bool(state.learning_evidence)


def _default_buggy_code_generator(context: ToolContext) -> Mapping[str, Any]:
    from utils.thinking_ai import student_agent_write_code

    messages = context.memory.visible_messages.get(AgentRole.STUDENT_AGENT, [])
    return student_agent_write_code(
        context.assignment_title,
        list(context.key_concepts),
        context.reference_code,
        messages,
    )


def _default_fix_evaluator(context: ToolContext, fixed_code: str) -> Dict[str, Any]:
    from utils.thinking_ai import evaluate_feynman_code_fix

    artifact = _latest_buggy_artifact(context)
    if artifact is None:
        raise ValueError("missing buggy attempt")
    deterministic_confirmed = _deterministic_fix_confirms(
        artifact["buggy_code"], fixed_code, artifact["bugs"], context.reference_code,
    )
    if deterministic_confirmed:
        # The server reference and structured bug fixes are authoritative for
        # the final gate; a model must not be able to reject an exact answer.
        correct, feedback = True, "修复已通过确定性检查。"
    else:
        correct, feedback = evaluate_feynman_code_fix(
            artifact["buggy_code"], fixed_code, artifact["bugs"], context.reference_code,
        )
    if correct and not deterministic_confirmed:
        correct = False
        feedback = "修复尚未通过确定性检查。"
    return {"correct": correct, "feedback": feedback}


def _deterministic_fix_confirms(
    buggy_code: str,
    fixed_code: str,
    bugs: List[Any],
    reference_code: str,
) -> bool:
    fixed_key = _semantic_code_key(fixed_code)
    if not fixed_key or fixed_key == _semantic_code_key(buggy_code):
        return False
    reference_key = _semantic_code_key(reference_code)
    if reference_key and fixed_key == reference_key:
        return True
    compact_fixed = re.sub(r"\s+", "", fixed_code).casefold()
    for bug in bugs:
        if not isinstance(bug, Mapping):
            return False
        corrections = [
            str(bug.get(name) or "").strip()
            for name in ("correct_version", "fix")
        ]
        corrections = [item for item in corrections if item]
        if not corrections or not any(
            re.sub(r"\s+", "", item).casefold() in compact_fixed
            for item in corrections
        ):
            return False
    return True


def _latest_buggy_artifact(context: ToolContext) -> Optional[Dict[str, Any]]:
    for item in reversed(list(context.memory.code_artifact_index.values())):
        artifact = item.get("artifact") if isinstance(item, Mapping) else None
        if not isinstance(artifact, Mapping):
            continue
        buggy_code = artifact.get("buggy_code")
        bugs = artifact.get("bugs")
        if isinstance(buggy_code, str) and isinstance(bugs, list):
            return {"buggy_code": buggy_code, "bugs": bugs}
    return None


def _error(code: str, *, retryable: bool = False) -> ToolResult:
    return ToolResult(ok=False, error_code=code, retryable=retryable)
