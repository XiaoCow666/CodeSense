"""Assembly for the Stage 3 Teacher/Student Feynman runtime.

The runtime is deliberately a thin composition layer: :mod:`loop` remains the
only model/tool execution path and :mod:`memory` remains the source of truth
for request de-duplication and private code artifacts.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from .contracts import (
    AgentDecision,
    AgentResult,
    AgentRole,
    Stage3MessageKind,
    Stage3Target,
    ToolCall,
    ToolResult,
    UIAction,
)
from .coverage import (
    _evidence_covers_concept,
    _is_concrete_explanation,
    load_coverage_config,
)
from .goal import build_stage3_user_goal
from .interaction import build_interaction_profile
from .loop import (
    AgentLoop,
    AgentLoopSpec,
    _distributed_session_lock,
    _normalized_trigger,
    _sanitized_signal_metadata,
    _session_lock,
)
from .memory import EventRecord, EventStore, MemorySnapshot, MemoryStore, SqlAlchemyEventStore
from .model import DecisionModel, StructuredDecisionModel
from .crewai_adapter import build_stage3_decision_model
from .tools import (
    BuggyCodeGenerator,
    FixEvaluator,
    MAX_EVIDENCE_CHARS,
    ToolRegistry,
    _is_valid_probe_question,
    build_feynman_tool_registry,
)


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    goal: str
    system_prompt: str
    fallback_message: str
    max_output_chars: int = 1200


TEACHER_SPEC = AgentSpec(
    role=AgentRole.TEACHER_AGENT,
    goal="引导学习者清楚解释思路，并在通过服务端检查后完成学习目标。",
    system_prompt=(
        "你是教师 Agent。根据学习者的解释追问和纠偏，不直接泄露标准答案或隐藏修复。"
        "教师只能以教师身份回复，绝不能代替学生 Agent 发言，也不要在教师回复中写出小明的提问或‘小明介入’。"
        "如果需要学生 Agent 介入，必须只调用 request_student_probe 工具，由系统单独展示学生消息；工具调用失败时仍保持教师身份。"
        "调用 request_student_probe 时，concept 和 dimension 优先逐字复制上下文中的 key_concepts 与 probe_dimensions；"
        "不要自行创造新的概念或维度名称。每轮先回应学习者刚刚说的内容，再提出一个明确、可回答的问题；"
        "一次只能问一个问题，禁止把多个边界、多个概念或多个问题拼在同一轮，也不要只说‘请继续说明思路’这类没有方向的追问。"
        "上下文中的 interaction_profile 是根据最近用户回复生成的确定性互动信号；必须遵守其中的 guidance。"
        "当 input_kind 为 teacher_help 时，说明学习者刚刚无法回答小明的问题；此轮必须先讲清缺失知识，"
        "最好给一个具体输入例子，再只提出一个用于确认理解的问题，不得只把问题原样抛回给学习者。"
        "只有在工具返回的服务端条件满足时才调用 complete_goal。"
    ),
    fallback_message="请再用自己的话解释一下这一步。",
)
STUDENT_SPEC = AgentSpec(
    role=AgentRole.STUDENT_AGENT,
    goal="以同伴身份追问学习者的解释，并在需要时提交一份待检查的代码。",
    system_prompt=(
        "你是学生 Agent，扮演同伴小明；只基于题目、概念和学习者的解释追问。"
        "上下文中的 learner_name 是当前真实学习者的姓名，公开提问时直接称呼这个姓名；"
        "不要写‘小明，请……’、‘学生 Agent，请……’，也不要把自己当成被提问的学生。"
        "不要声称知道标准答案、隐藏缺陷或正确修复；需要代码时使用允许的工具。"
        "服务端上下文中的 coverage 是唯一的学习进度依据：收到具体解释后，优先调用 assess_teaching_progress，"
        "评估的是当前用户实际回答是否覆盖 pending_probe；不要只因为你上一轮提过问题就判为 partial。"
        "如果回答同时给出关键事实、代码关系和原因，应判为 covered；只有缺少关键事实或原因时才判为 partial。"
        "每个新的 student_probe_intent 首轮先以同学小明的口吻承认‘我还不太会’，"
        "请学习者用简单的话教你怎么处理这道题；这一轮不要先考察边界、循环或输出细节。"
        "如果学习者对小明的问题表示不会、不懂、答不完整或继续提问，不要重复同一个问题，"
        "交由老师补充缺失知识；只有学习者给出具体解释后，才调用 assess_teaching_progress。"
        "不要重复已经问过的问题；应按 pending_probe 的概念和维度切换到下一个尚未覆盖的检查。"
        "上下文中的 interaction_profile 是根据最近用户回复生成的确定性互动信号；必须遵守其中的 guidance。"
        "一次只提出一个简短、具体的问题；问题应从新的角度检查理解，例如边界、循环关系或真实应用场景，"
        "不要在同一轮同时问多个情形，也不要用‘我也懂了’代替对学习者的回应；当 ready_for_code 为 true 时停止追问，让系统自动调用 generate_buggy_attempt。"
    ),
    fallback_message="你能换一种说法解释这一段吗？",
)

_TEACHER_IMPERSONATION_MARKERS = (
    "小明",
    "学生 Agent",
    "学生Agent",
    "我也懂了",
    "我也明白了",
    "我也会了",
)
_TEACHER_SAFE_PUBLIC_MESSAGE = "我会继续从教师角度检查你的理解；如需同伴提问，系统会单独展示。"
_STUDENT_ASSESSMENT_RETRY_PROMPT = (
    "服务端约束：当前用户刚刚回复了学生探针，且这是一段具体解释。"
    "本轮必须先调用 assess_teaching_progress，再提出任何新的问题；"
    "assessment 只能是 covered、partial 或 off_topic，evidence 必须概括当前用户的实际解释。"
    "请使用上下文中的当前探针目标作为评估目标，不要只返回重复问题。"
)
_DUPLICATE_RESPONSE_RETRY_PROMPT = (
    "服务端约束：你刚才生成的公开回复与本角色上一条公开回复重复。"
    "本轮必须先回应用户刚刚提交的新内容，再推进到一个新的角度；"
    "不要复述上一轮问题，也不要连续追问同一个问题。"
    "一次只提出一个简短、具体的新问题；如果用户已经回答了上一问，先明确承认这一点。"
)
_DUPLICATE_RESPONSE_FALLBACK = (
    "我看到你已经回答了上一个问题。请换一个角度，结合一个具体输入例子说明这条规则会产生什么输出？"
)
_TEACHER_GENERIC_FALLBACK = (
    "我先把你的回答落到一个具体检查点上：请用一个输入例子说明这条规则会产生什么输出？"
)
_TEACHER_GENERIC_RESPONSES = frozenset({
    "请继续。",
    "请继续",
    "请继续说明。",
    "请继续说明",
    "请继续说明你的思路。",
    "请继续说明你的思路",
    "请详细说明。",
    "请详细说明",
})


@dataclass
class FeynmanCallbacks:
    """Inject persistence and domain callbacks without coupling unit tests to Flask."""

    event_store: Optional[EventStore] = None
    buggy_code_generator: Optional[BuggyCodeGenerator] = None
    fix_evaluator: Optional[FixEvaluator] = None
    persist_session: Optional[Callable[[Any], None]] = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc).replace(tzinfo=None)

    def memory_store(self) -> MemoryStore:
        if self.event_store is None:
            self.event_store = SqlAlchemyEventStore()
        return MemoryStore(self.event_store)

    def tool_registry(self) -> ToolRegistry:
        return build_feynman_tool_registry(
            buggy_code_generator=self.buggy_code_generator,
            fix_evaluator=self.fix_evaluator,
        )

    def save_session(self, session: Any) -> None:
        if self.persist_session is not None:
            self.persist_session(session)
            return
        from models import db

        db.session.add(session)
        db.session.commit()


class _RoleContextLoop(AgentLoop):
    """AgentLoop with a role-specific, explicitly allowlisted prompt context."""

    def __init__(self, *, context_builder: Callable[[MemorySnapshot, str], Dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._context_builder = context_builder

    def _build_context(self, snapshot: MemorySnapshot, *, input_kind: str) -> str:
        prompt = dict(self._context_builder(snapshot, input_kind))
        prompt["input_kind"] = input_kind
        prompt["target_role"] = self._active_target_role
        if input_kind == "intervention" and isinstance(self._active_trigger, Mapping):
            prompt["trigger"] = dict(self._active_trigger)
        return json.dumps(prompt, ensure_ascii=False)


class _ForumRoleContextLoop(_RoleContextLoop):
    """Role loop with metadata-aware persistence and ready-for-code escalation."""

    def __init__(self, **kwargs: Any) -> None:
        self._learner_name = _safe_learner_name(kwargs.pop("learner_name", None))
        super().__init__(**kwargs)
        self._active_event_metadata: Dict[str, Any] = {}
        self._active_user_event_id: Optional[str] = None
        self._active_user_message = ""
        self._active_input_kind = "chat"
        self._active_teacher_help_target: Optional[Dict[str, str]] = None

    def _tool_context(self, snapshot: MemorySnapshot, request_id: str, input_kind: str):
        context = super()._tool_context(snapshot, request_id, input_kind)
        context.learner_name = self._learner_name
        return context

    def _decide(
        self,
        input_kind: str,
        tool_results: List[Dict[str, Any]],
        request_id: str,
        snapshot: MemorySnapshot,
        step: int,
        *,
        system_prompt_suffix: str = "",
    ) -> AgentDecision | AgentResult:
        decision = super()._decide(
            input_kind,
            tool_results,
            request_id,
            snapshot,
            step,
            system_prompt_suffix=system_prompt_suffix,
        )
        if isinstance(decision, AgentResult) or not self._is_duplicate_public_reply(
            decision, snapshot
        ):
            return decision

        retry_decision = super()._decide(
            input_kind,
            tool_results,
            request_id,
            snapshot,
            step,
            system_prompt_suffix=self._append_prompt_suffix(
                system_prompt_suffix,
                _DUPLICATE_RESPONSE_RETRY_PROMPT,
            ),
        )
        if isinstance(retry_decision, AgentResult) or not self._is_duplicate_public_reply(
            retry_decision, snapshot
        ):
            return retry_decision
        return AgentDecision(message=self._duplicate_response_fallback(snapshot))

    @staticmethod
    def _append_prompt_suffix(current: str, extra: str) -> str:
        return f"{current}\n\n{extra}" if current else extra

    def _is_duplicate_public_reply(
        self,
        decision: AgentDecision,
        snapshot: MemorySnapshot,
    ) -> bool:
        if decision.tool_calls or not decision.message.strip():
            return False
        # Compare the final public form, not the raw model text.  Role-boundary
        # sanitization can turn several different model mistakes into the same
        # visible sentence (for example, Teacher impersonation or a generic
        # fallback), so comparing raw text lets duplicate replies leak out.
        normalized = _normalize_reply_text(self._sanitize_response(decision.message))
        if not normalized:
            return False
        previous_messages = snapshot.agent_messages.get(self.role, [])[-3:]
        return any(
            normalized == _normalize_reply_text(item.get("content", ""))
            for item in previous_messages
            if isinstance(item, Mapping)
        )

    def _is_duplicate_public_text(self, value: Any, snapshot: MemorySnapshot) -> bool:
        normalized = _normalize_reply_text(self._sanitize_response(value))
        if not normalized:
            return False
        return any(
            normalized == _normalize_reply_text(item.get("content", ""))
            for item in snapshot.agent_messages.get(self.role, [])[-3:]
            if isinstance(item, Mapping)
        )

    def _duplicate_response_fallback(self, snapshot: MemorySnapshot) -> str:
        if self.role is AgentRole.STUDENT_AGENT:
            target = self._student_probe_target(snapshot)
            if target is not None:
                candidates = (
                    _student_opening_question(target, self._learner_name),
                    _fallback_student_probe_question(target, self._learner_name),
                    "我们换一个角度：请举一个具体输入，说明这条规则会怎样处理？",
                )
                for candidate in candidates:
                    if not self._is_duplicate_public_text(candidate, snapshot):
                        return candidate
        contextual = (
            _contextual_teacher_fallback(self._active_user_message)
            if self.role is AgentRole.TEACHER_AGENT
            else _DUPLICATE_RESPONSE_FALLBACK
        )
        candidates = (
            contextual,
            _DUPLICATE_RESPONSE_FALLBACK,
            "这次我换一个角度确认：请指出刚才这个输入对应的实际输出，并说明你的判断依据。",
        )
        for candidate in candidates:
            if not self._is_duplicate_public_text(candidate, snapshot):
                return candidate
        return "我们先换一个新例子：请说明另一个输入下程序会输出什么，以及原因。"

    def _sanitize_response(self, value: Any) -> str:
        response = super()._sanitize_response(value)
        if self.role is AgentRole.TEACHER_AGENT and any(
            marker in response for marker in _TEACHER_IMPERSONATION_MARKERS
        ):
            if self._active_input_kind == "teacher_help":
                return _teacher_help_fallback(
                    self._active_user_message,
                    self._active_teacher_help_target,
                )
            return _TEACHER_SAFE_PUBLIC_MESSAGE
        if self.role is AgentRole.TEACHER_AGENT and _is_generic_teacher_response(response):
            if self._active_input_kind == "teacher_help":
                return _teacher_help_fallback(
                    self._active_user_message,
                    self._active_teacher_help_target,
                )
            return _contextual_teacher_fallback(self._active_user_message)
        if self.role is AgentRole.STUDENT_AGENT:
            # The Student Agent is the voice of Xiaoming, while the person
            # being questioned is the logged-in learner.  Normalize a common
            # self-addressing model mistake at the public boundary as a
            # second line of defense after the prompt instruction.
            response = _replace_student_self_reference(response, self._learner_name)
            if (
                _is_valid_probe_question(response)
                and self._learner_name not in response[: len(self._learner_name) + 4]
            ):
                response = f"{self._learner_name}，{response}"
        return response

    def handle_turn(
        self,
        user_message: str,
        *,
        request_id: str,
        input_kind: str = "chat",
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        lock = _session_lock(self.session_id)
        with lock:
            with _distributed_session_lock(self.session_id) as acquired:
                if not acquired:
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="SESSION_LOCK_UNAVAILABLE",
                    )
                self._active_user_message = str(user_message or "")
                self._set_active_event_metadata(event_metadata)
                return self._handle_turn_locked(
                    user_message,
                    request_id,
                    input_kind,
                    target_role=self.role.value,
                    trigger=None,
                    skip_user_message=False,
                )

    def handle_trigger(
        self,
        trigger: Mapping[str, Any],
        *,
        request_id: str,
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        lock = _session_lock(self.session_id)
        with lock:
            with _distributed_session_lock(self.session_id) as acquired:
                if not acquired:
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="SESSION_LOCK_UNAVAILABLE",
                    )
                self._active_user_message = ""
                existing = self.memory.find_request_result(self.session_id, request_id)
                if existing is not None:
                    return existing
                normalized_trigger = _normalized_trigger(trigger)
                if normalized_trigger is None:
                    return self._failure("INVALID_AGENT_TRIGGER", request_id)
                self._set_active_event_metadata(event_metadata)
                self.memory.append_event(
                    self.session_id,
                    "agent_trigger",
                    "system",
                    content=normalized_trigger["goal"],
                    metadata={
                        "request_id": request_id,
                        "source_role": AgentRole.TEACHER_AGENT.value,
                        "target_role": self.role.value,
                        "message_kind": Stage3MessageKind.AGENT_TRIGGER.value,
                        "visibility": "private",
                        "trigger": dict(normalized_trigger),
                        **self._filtered_event_metadata(),
                    },
                )
                return self._handle_turn_locked(
                    "",
                    request_id,
                    "intervention",
                    target_role=self.role.value,
                    trigger=normalized_trigger,
                    skip_user_message=True,
                )

    def handle_tool_action(
        self,
        *,
        request_id: str,
        input_kind: str,
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        lock = _session_lock(self.session_id)
        with lock:
            with _distributed_session_lock(self.session_id) as acquired:
                if not acquired:
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="SESSION_LOCK_UNAVAILABLE",
                    )
                self._active_user_message = ""
                self._set_active_event_metadata(event_metadata)
                return self._handle_turn_locked(
                    "",
                    request_id,
                    input_kind,
                    target_role=self.role.value,
                    trigger=None,
                    skip_user_message=True,
                )

    def _handle_turn_locked(
        self,
        user_message: str,
        request_id: str,
        input_kind: str,
        *,
        target_role: str,
        trigger: Optional[Dict[str, Any]],
        skip_user_message: bool,
    ) -> AgentResult:
        existing = self.memory.find_request_result(self.session_id, request_id)
        if existing is not None:
            return existing

        self._active_user_event_id = None
        if not skip_user_message:
            user_event = self.memory.append_event(
                self.session_id,
                "agent_user_message",
                "student",
                content=user_message,
                metadata={
                    "request_id": request_id,
                    "input_kind": input_kind,
                    **self._filtered_event_metadata(),
                },
            )
            self._active_user_event_id = user_event.event_id
        snapshot = self.memory.load(self.session_id)
        self._active_input_kind = input_kind
        self._active_teacher_help_target = (
            _normalize_probe_target(snapshot.state.pending_probe)
            if self.role is AgentRole.TEACHER_AGENT and input_kind == "teacher_help"
            else None
        )
        self._active_trigger = dict(trigger) if isinstance(trigger, Mapping) else None
        self._active_target_role = target_role
        if (
            input_kind == "intervention"
            and self.role is AgentRole.STUDENT_AGENT
            and isinstance(trigger, Mapping)
        ):
            # The teacher's accepted trigger is already a server-authorized
            # probe. Keep it pending even when the student model replies with
            # a plain question instead of calling ask_student_probe itself.
            snapshot.state.pending_probe = {
                "concept": str(trigger["concept"]).strip(),
                "dimension": str(trigger["dimension"]).strip(),
            }
        context = self._tool_context(snapshot, request_id, input_kind)
        tool_results: List[Dict[str, Any]] = []
        total_tool_calls = 0
        internal_signals: Dict[str, Any] = {}
        assessment_retry_needed = self._needs_assessment_retry(
            user_message,
            input_kind,
            snapshot,
        )
        assessment_retry_done = False

        if self._must_generate_code(snapshot, input_kind):
            # The coverage gate may have opened in a previous request (for
            # example after a failed browser retry). Do not spend another
            # provider call asking the Teacher or Student what to do: record
            # this current user event and let DualFeynmanRuntime perform the
            # single server-authorized code transition below.
            self._advance_successful_chat(snapshot, user_message, "", input_kind)
            self._persist_state_checkpoint(snapshot, request_id)
            return AgentResult(
                success=False,
                agent=self.role,
                error_code="READY_FOR_CODE_REQUIRED",
            )

        for step in range(self.config.max_model_steps):
            if step == 0 and self._should_open_student_probe(
                snapshot,
                input_kind=input_kind,
                user_message=user_message,
            ):
                target = self._student_probe_target(snapshot)
                decision = AgentDecision(
                    message=(
                        _student_opening_question(target, self._learner_name)
                        if target is not None
                        else f"{self._learner_name}，我还不太会这道题。你可以用简单的话告诉我应该怎么处理吗？"
                    )
                )
            else:
                decision = self._decide(
                    input_kind,
                    tool_results,
                    request_id,
                    snapshot,
                    step,
                )
            if isinstance(decision, AgentResult):
                return decision
            decision = self._fallback_protocol_decision(
                decision,
                user_message=user_message,
                input_kind=input_kind,
                request_id=request_id,
                snapshot=snapshot,
                tool_results=tool_results,
            )
            if assessment_retry_needed and self._has_tool_call(
                decision,
                "assess_teaching_progress",
            ):
                # Once the model has emitted the required assessment, do not
                # inject another assessment turn after that tool completes.
                assessment_retry_done = True
            if (
                assessment_retry_needed
                and not assessment_retry_done
                and not self._has_tool_call(decision, "assess_teaching_progress")
                and not bool(getattr(self.model, "fallback_used", False))
            ):
                assessment_retry_done = True
                retry_decision = self._decide(
                    input_kind,
                    tool_results,
                    request_id,
                    snapshot,
                    step,
                    system_prompt_suffix=_STUDENT_ASSESSMENT_RETRY_PROMPT,
                )
                if isinstance(retry_decision, AgentResult):
                    return retry_decision
                decision = retry_decision
            if (
                self.role is AgentRole.TEACHER_AGENT
                and internal_signals.get("student_probe")
                and decision.tool_calls
            ):
                bounded_decision = AgentDecision(
                    message=decision.message.strip()
                    or "我会继续从教师角度检查你的理解；如需同伴提问，系统会单独展示。",
                )
                return self._finish_public_response(
                    bounded_decision,
                    snapshot,
                    request_id,
                    internal_signals,
                )
            safe_decision_message = self._sanitize_public_response(
                decision.message,
                self.spec.max_output_chars,
            )
            decision_payload = decision.to_payload()
            decision_payload["message"] = safe_decision_message
            self.memory.append_event(
                self.session_id,
                "agent_decision",
                self.role.value,
                content=safe_decision_message,
                metadata={
                    "request_id": request_id,
                    "step": step,
                    "decision": decision_payload,
                },
            )
            if not decision.tool_calls:
                if self._must_generate_code(snapshot, input_kind):
                    self._advance_successful_chat(
                        snapshot,
                        user_message,
                        decision.message,
                        input_kind,
                    )
                    self._persist_state_checkpoint(snapshot, request_id)
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="READY_FOR_CODE_REQUIRED",
                    )
                self._advance_successful_chat(
                    snapshot,
                    user_message,
                    decision.message,
                    input_kind,
                )
                if (
                    self.role is AgentRole.STUDENT_AGENT
                    and self._is_duplicate_public_text(safe_decision_message, snapshot)
                ):
                    safe_decision_message = self._duplicate_response_fallback(snapshot)
                    decision = AgentDecision(
                        message=safe_decision_message,
                        goal_status=decision.goal_status,
                        ui_action=decision.ui_action,
                    )
                return self._finish_public_response(
                    decision,
                    snapshot,
                    request_id,
                    internal_signals,
                )
            batch_size = len(decision.tool_calls)
            if (
                batch_size > self.config.max_tool_calls_per_decision
                or total_tool_calls + batch_size > self.config.max_tool_calls_per_request
            ):
                return self._failure("TOOL_CALL_LIMIT", request_id)
            total_tool_calls += batch_size

            for call in decision.tool_calls:
                executions = self._execute_tool(call, context, request_id)
                for index, execution in enumerate(executions):
                    result = execution.result
                    terminal_failure = not result.ok and index == len(executions) - 1
                    if execution.persist:
                        if not result.ok:
                            self._persist_tool_result(call, result, request_id, terminal=terminal_failure)
                        if not result.ok:
                            if terminal_failure:
                                return self._failure(result.error_code or "TOOL_EXECUTION_FAILED", request_id)
                            continue
                    patch = self._validated_state_patch(call, result.state_patch)
                    if patch is None:
                        invalid = ToolResult(
                            ok=False,
                            error_code="INVALID_STATE_PATCH",
                            memory_events=list(result.memory_events),
                        )
                        if execution.persist:
                            self._persist_tool_result(call, invalid, request_id, terminal=True)
                        return self._failure("INVALID_STATE_PATCH", request_id)
                    self._apply_state_patch(snapshot, patch)
                    signal_metadata = _sanitized_signal_metadata(result)
                    if input_kind != "intervention" and not internal_signals and signal_metadata:
                        internal_signals[signal_metadata["signal_type"]] = dict(
                            signal_metadata["internal_content"]
                        )
                    terminal_kind = self._terminal_tool_kind(call, result)
                    terminal_success = terminal_kind is not None
                    if execution.persist:
                        self._persist_tool_result(call, result, request_id, patch=patch, terminal=terminal_success)
                    if patch and not terminal_success:
                        self._persist_state_checkpoint(snapshot, request_id)
                    tool_results.append(self._tool_result_for_model(call, result))
                    if self._coverage_became_ready(call, patch, snapshot, input_kind):
                        self._advance_successful_chat(
                            snapshot,
                            user_message,
                            safe_decision_message or call.name,
                            input_kind,
                        )
                        self._persist_state_checkpoint(snapshot, request_id)
                        return AgentResult(
                            success=False,
                            agent=self.role,
                            error_code="READY_FOR_CODE_REQUIRED",
                        )
                    if terminal_kind == "code_review":
                        self._advance_successful_chat(
                            snapshot,
                            user_message,
                            call.name,
                            input_kind,
                        )
                        return self._finish_code_review(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "complete_goal":
                        self._advance_successful_chat(
                            snapshot,
                            user_message,
                            call.name,
                            input_kind,
                        )
                        return self._finish_goal(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "fix_passed":
                        self._advance_successful_chat(
                            snapshot,
                            user_message,
                            call.name,
                            input_kind,
                        )
                        return self._finish_fix(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "student_probe":
                        return self._finish_probe(result, snapshot, request_id)
                    if (
                        self.role is AgentRole.TEACHER_AGENT
                        and result.signal_type == "student_probe"
                    ):
                        break

        return self._failure("MAX_AGENT_STEPS", request_id)

    def _fallback_protocol_decision(
        self,
        decision: AgentDecision,
        *,
        user_message: str,
        input_kind: str,
        request_id: str,
        snapshot: MemorySnapshot,
        tool_results: List[Dict[str, Any]],
    ) -> AgentDecision:
        """Keep the Stage 3 protocol moving when structured AI is unavailable.

        A provider outage must not turn the forum into a repeating generic
        prompt.  The fallback follows the same role boundary as a normal
        model decision and uses only server-derived state plus the recent
        interaction profile.  No learning credit is granted by this method
        itself.
        """
        if (
            self.role is AgentRole.TEACHER_AGENT
            and not decision.tool_calls
            and bool(getattr(self.model, "fallback_used", False))
        ):
            profile = build_interaction_profile(snapshot.student_messages)
            target = self._teacher_fallback_target(snapshot)
            if input_kind == "teacher_help" or profile.mode == "needs_scaffold":
                return AgentDecision(message=_teacher_help_fallback(
                    user_message,
                    self._active_teacher_help_target or target,
                ))
            return AgentDecision(message=_contextual_teacher_fallback(user_message))

        if (
            self.role is not AgentRole.STUDENT_AGENT
            or decision.tool_calls
            or not bool(getattr(self.model, "fallback_used", False))
        ):
            return decision

        target = self._fallback_probe_target(snapshot)
        if target is None:
            return decision

        if input_kind == "intervention":
            return AgentDecision(message=_fallback_student_probe_question(
                target,
                self._learner_name,
            ))

        if input_kind != "chat" or snapshot.state.phase != "student_dialogue":
            return decision

        if self._has_successful_assessment(tool_results):
            return AgentDecision(message=_fallback_student_probe_question(
                self._fallback_probe_target(snapshot) or target,
                self._learner_name,
            ))

        if _is_concrete_explanation(user_message):
            evidence = user_message.strip()[:MAX_EVIDENCE_CHARS]
            assessment = (
                "covered"
                if _evidence_covers_concept(target["concept"], user_message)
                else "partial"
            )
            return AgentDecision(
                tool_calls=[ToolCall(
                    call_id=f"{str(request_id)[:80]}:fallback-assess",
                    name="assess_teaching_progress",
                    arguments={
                        "assessment": assessment,
                        "evidence": evidence,
                    },
                )]
            )

        return AgentDecision(message=_fallback_student_probe_question(
            target,
            self._learner_name,
        ))

    @staticmethod
    def _has_successful_assessment(tool_results: List[Dict[str, Any]]) -> bool:
        return any(
            isinstance(item, Mapping)
            and item.get("name") == "assess_teaching_progress"
            and item.get("ok") is True
            for item in tool_results
        )

    @staticmethod
    def _fallback_probe_target(snapshot: MemorySnapshot) -> Optional[Dict[str, str]]:
        for candidate in (
            snapshot.state.pending_probe,
            snapshot.state.student_probe_intent,
        ):
            if not isinstance(candidate, Mapping):
                continue
            concept = str(candidate.get("concept") or "").strip()
            dimension = str(candidate.get("dimension") or "").strip()
            if concept and dimension:
                return {"concept": concept, "dimension": dimension}
        return None

    @staticmethod
    def _teacher_fallback_target(snapshot: MemorySnapshot) -> Optional[Dict[str, str]]:
        """Select the next server-known concept for a degraded Teacher reply."""

        for candidate in (
            snapshot.state.pending_probe,
            snapshot.state.student_probe_intent,
        ):
            normalized = _normalize_probe_target(candidate)
            if normalized is not None:
                return normalized

        for concept in snapshot.state.unresolved_concepts:
            value = str(concept or "").strip()
            if value:
                return {"concept": value, "dimension": "core"}

        for item in snapshot.state.concept_coverage:
            if not isinstance(item, Mapping) or item.get("status") == "covered":
                continue
            concept = str(item.get("concept") or "").strip()
            if concept:
                return {"concept": concept, "dimension": "core"}
        return None

    def _student_probe_target(self, snapshot: MemorySnapshot) -> Optional[Dict[str, str]]:
        """Return the one server-authorized target for this Student turn."""
        for candidate in (
            self._active_trigger,
            snapshot.state.pending_probe,
            snapshot.state.student_probe_intent,
        ):
            target = _normalize_probe_target(candidate)
            if target is not None:
                return target
        return None

    def _should_open_student_probe(
        self,
        snapshot: MemorySnapshot,
        *,
        input_kind: str,
        user_message: str,
    ) -> bool:
        """Keep the first peer turn in the learner-facing Xiaoming role.

        AutoGen's group-chat selector separates speaker selection from the
        selected agent's response.  We apply the same boundary here: an
        authorized Student turn gets one deterministic opening move before
        the model is allowed to assess an answer or choose another probe.
        """
        if self.role is not AgentRole.STUDENT_AGENT or snapshot.state.phase != "student_dialogue":
            return False
        if self._student_probe_target(snapshot) is None:
            return False
        if input_kind == "intervention":
            return True
        if isinstance(snapshot.state.student_probe_intent, Mapping):
            return True
        pending = snapshot.state.pending_probe
        if isinstance(pending, Mapping) and str(pending.get("question") or "").strip():
            return False
        # A concrete answer may come from a legacy session whose pending probe
        # predates the question field.  Let the normal assessment path consume
        # it instead of replacing the answer with a new opening question.
        if _is_concrete_explanation(str(user_message or "")):
            return False
        return not _looks_like_probe_answer(str(user_message or ""))

    def _needs_assessment_retry(
        self,
        user_message: str,
        input_kind: str,
        snapshot: MemorySnapshot,
    ) -> bool:
        return (
            self.role is AgentRole.STUDENT_AGENT
            and input_kind == "chat"
            and snapshot.state.phase == "student_dialogue"
            and (
                isinstance(snapshot.state.pending_probe, Mapping)
                or isinstance(snapshot.state.student_probe_intent, Mapping)
            )
            and _is_concrete_explanation(user_message)
        )

    @staticmethod
    def _has_tool_call(decision: AgentDecision, tool_name: str) -> bool:
        return any(call.name == tool_name for call in decision.tool_calls)

    def _persist_completion(
        self,
        result: AgentResult,
        snapshot: MemorySnapshot,
        request_id: str,
        *,
        message_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        message_metadata = dict(message_metadata or {})
        if self.role is AgentRole.STUDENT_AGENT and _is_valid_probe_question(result.response):
            target = self._student_probe_target(snapshot)
            if target is not None:
                # Persist the exact public question with the server-owned
                # target.  On a restored session this distinguishes "Xiaoming
                # is waiting for the learner's answer" from "Xiaoming has
                # only been scheduled and has not spoken yet".
                snapshot.state.pending_probe = {
                    **target,
                    "question": result.response,
                }
        is_intent_probe = (
            isinstance(snapshot.state.student_probe_intent, Mapping)
            and _is_valid_probe_question(result.response)
        )
        if (
            self.role is AgentRole.STUDENT_AGENT
            and "message_kind" not in message_metadata
            and (
                self._active_trigger is not None
                or (
                    isinstance(snapshot.state.pending_probe, Mapping)
                    and _is_valid_probe_question(result.response)
                    or is_intent_probe
                )
            )
        ):
            # A model may answer either an intervention or a follow-up
            # assessment with plain text instead of calling ask_student_probe.
            # It is still the server-authorized student probe and must remain
            # replyable in the forum.
            message_metadata["message_kind"] = "student_probe"
        if self.role is AgentRole.STUDENT_AGENT and self._active_trigger is None:
            # A student turn always consumes the intent that made it eligible.
            # The next turn will receive a fresh intent or a real pending
            # question; no stale scheduling token survives indefinitely.
            snapshot.state.student_probe_intent = None
        merged_message_metadata = {
            **self._default_message_metadata(request_id),
            **message_metadata,
        }
        super()._persist_completion(
            result,
            snapshot,
            request_id,
            message_metadata=merged_message_metadata,
        )

    @staticmethod
    def _sanitize_public_response(value: Any, maximum: int) -> str:
        from .loop import _sanitize_public_response

        return _sanitize_public_response(value, maximum)

    @staticmethod
    def _tool_result_for_model(call: ToolCall, result: ToolResult) -> Dict[str, Any]:
        from .loop import _tool_result_for_model

        return _tool_result_for_model(call, result)

    @staticmethod
    def _terminal_tool_kind(call: ToolCall, result: ToolResult) -> Optional[str]:
        from .loop import _terminal_tool_kind

        return _terminal_tool_kind(call, result)

    def _must_generate_code(self, snapshot: MemorySnapshot, input_kind: str) -> bool:
        return (
            self.role is AgentRole.STUDENT_AGENT
            and input_kind == "chat"
            and snapshot.state.phase != "code_review"
            and bool(snapshot.state.ready_for_code)
        )

    def _coverage_became_ready(
        self,
        call: ToolCall,
        patch: Mapping[str, Any],
        snapshot: MemorySnapshot,
        input_kind: str,
    ) -> bool:
        return (
            self.role is AgentRole.STUDENT_AGENT
            and input_kind == "chat"
            and call.name == "assess_teaching_progress"
            and patch.get("ready_for_code") is True
            and bool(snapshot.state.ready_for_code)
            and snapshot.state.phase != "code_review"
        )

    def _set_active_event_metadata(self, event_metadata: Optional[Mapping[str, Any]]) -> None:
        self._active_event_metadata = dict(event_metadata or {})

    def _filtered_event_metadata(self) -> Dict[str, Any]:
        allowed = {
            "source_role",
            "target_role",
            "message_kind",
            "visibility",
            "reply_to_event_id",
            "parent_request_id",
            "input_kind",
        }
        return {
            key: value
            for key, value in self._active_event_metadata.items()
            if key in allowed and value is not None
        }

    def _default_message_metadata(self, request_id: str) -> Dict[str, Any]:
        reply_to_event_id = self._active_user_event_id or self._active_event_metadata.get("reply_to_event_id")
        parent_request_id = self._active_event_metadata.get("parent_request_id")
        if parent_request_id is None and self._active_user_event_id:
            parent_request_id = request_id
        return {
            "source_role": self.role.value,
            "target_role": Stage3Target.USER.value,
            "message_kind": Stage3MessageKind.AGENT_MESSAGE.value,
            "visibility": "public",
            "reply_to_event_id": reply_to_event_id,
            "parent_request_id": parent_request_id,
        }

    @property
    def last_user_event_id(self) -> Optional[str]:
        return self._active_user_event_id


class _ForcedToolModel:
    """Use the normal AgentLoop path for non-chat runtime actions without an LLM."""

    def __init__(self, call: ToolCall) -> None:
        self.call = call
        self._returned_call = False
        self.last_error = None

    def decide(self, **_: Any) -> AgentDecision:
        if not self._returned_call:
            self._returned_call = True
            return AgentDecision(tool_calls=[self.call])
        return AgentDecision(message="")


class DualFeynmanRuntime:
    def __init__(
        self,
        *,
        session: Any,
        assignment: Any,
        preset: Any,
        model: DecisionModel,
        callbacks: FeynmanCallbacks,
    ) -> None:
        self.session = session
        self.assignment = assignment
        self.preset = preset
        self.model = model
        self.callbacks = callbacks
        self.memory = callbacks.memory_store()
        self.tools = callbacks.tool_registry()
        self.learner_name = _resolve_learner_name(session)
        self.specs = {TEACHER_SPEC.role: TEACHER_SPEC, STUDENT_SPEC.role: STUDENT_SPEC}

    def handle_chat(
        self,
        role: AgentRole,
        message: str,
        *,
        request_id: str,
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        if role not in self.specs:
            raise ValueError("unsupported agent role")
        input_kind = "chat"
        if isinstance(event_metadata, Mapping):
            requested_input_kind = event_metadata.get("input_kind")
            if requested_input_kind in {"chat", "teacher_help"}:
                input_kind = requested_input_kind
        loop = self._loop_for(role, self.model)
        result = loop.handle_turn(
            message,
            request_id=request_id,
            input_kind=input_kind,
            event_metadata=event_metadata,
        )
        if role is AgentRole.STUDENT_AGENT and result.error_code == "READY_FOR_CODE_REQUIRED":
            auto_request_id = f"{request_id}:generate_buggy_attempt"
            inbound_parent_request_id = (
                event_metadata.get("parent_request_id")
                if isinstance(event_metadata, Mapping)
                else None
            )
            result = self.generate_buggy_attempt(
                request_id=auto_request_id,
                event_metadata={
                    "source_role": AgentRole.STUDENT_AGENT.value,
                    "target_role": Stage3Target.USER.value,
                    "message_kind": Stage3MessageKind.AGENT_MESSAGE.value,
                    "visibility": "public",
                    "reply_to_event_id": loop.last_user_event_id,
                    "parent_request_id": (
                        inbound_parent_request_id
                        if inbound_parent_request_id is not None
                        else request_id
                    ),
                },
                enforce_ready=True,
            )
            if result.success:
                self._persist_request_alias(request_id, result)
        self._sync_compat_rounds(role, result)
        self._sync_completed_goal(role, result)
        return result

    def handle_trigger(
        self,
        trigger: Mapping[str, Any],
        *,
        request_id: str,
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        result = self._loop_for(AgentRole.STUDENT_AGENT, self.model).handle_trigger(
            trigger,
            request_id=request_id,
            event_metadata=event_metadata,
        )
        self._sync_compat_rounds(AgentRole.STUDENT_AGENT, result)
        self._sync_completed_goal(AgentRole.STUDENT_AGENT, result)
        return result

    def next_student_probe_trigger(self) -> Optional[Dict[str, str]]:
        """Return one server-authorized peer probe when the forum needs one.

        Teacher model output may request a probe, but it is not allowed to be
        the only way the Student Agent participates.  This deterministic
        fallback chooses the next uncovered concept/dimension and is bounded
        by the same coverage configuration used by the assessment tool.
        """

        snapshot = self.memory.load(self.session.id)
        state = snapshot.state
        if state.phase != "student_dialogue" or state.ready_for_code or state.status == "complete":
            return None

        config = self._coverage_config()
        concepts = self._key_concepts()
        if not concepts:
            return None

        max_budget = len(concepts) * config.max_probes_per_concept
        if state.student_rounds >= max_budget:
            return None

        pending = state.pending_probe
        if isinstance(pending, Mapping):
            concept = str(pending.get("concept") or "").strip()
            dimension = str(pending.get("dimension") or "").strip()
            if concept in concepts and dimension in config.probe_dimensions:
                # There is already an unanswered Student Agent question.
                # Never stack another intervention on top of it.
                return None

        coverage = self._coverage_for_prompt(state).get("concept_coverage", [])
        by_concept = {
            str(item.get("concept") or "").strip(): item
            for item in coverage
            if isinstance(item, Mapping)
        }
        for concept in concepts:
            entry = by_concept.get(concept, {})
            if str(entry.get("status") or "unseen") == "covered":
                continue
            try:
                attempts = int(entry.get("attempts") or 0)
            except (TypeError, ValueError):
                attempts = 0
            if attempts >= config.max_probes_per_concept:
                continue
            used_dimensions = entry.get("used_dimensions")
            if not isinstance(used_dimensions, (list, tuple)):
                used_dimensions = entry.get("asked_dimensions")
            used = {
                str(value).strip()
                for value in (used_dimensions or [])
                if isinstance(value, str) and value.strip()
            }
            dimension = next(
                (item for item in config.probe_dimensions if item not in used),
                None,
            )
            if dimension:
                return self._student_probe_trigger(concept, dimension)
        return None

    def has_pending_student_probe(self) -> bool:
        pending = self.memory.load(self.session.id).state.pending_probe
        if not isinstance(pending, Mapping):
            return False
        return (
            str(pending.get("concept") or "").strip() in self._key_concepts()
            and str(pending.get("dimension") or "").strip()
            in self._coverage_config().probe_dimensions
        )

    @staticmethod
    def _student_probe_trigger(concept: str, dimension: str) -> Dict[str, str]:
        return {
            "concept": concept,
            "dimension": dimension,
            "goal": f"由小明检查“{concept}”的{dimension}理解，提出一个具体问题。",
        }

    def public_user_goal(self) -> Dict[str, Any]:
        snapshot = self.memory.load(self.session.id)
        return self._user_goal_for_state(snapshot.state)

    def generate_buggy_attempt(
        self,
        *,
        request_id: str,
        event_metadata: Optional[Mapping[str, Any]] = None,
        enforce_ready: bool = False,
    ) -> AgentResult:
        if enforce_ready and not self._ready_for_code():
            return AgentResult(
                success=False,
                agent=AgentRole.STUDENT_AGENT,
                error_code="CODE_REVIEW_NOT_READY",
            )
        result = self._run_forced_tool(
            "generate_buggy_attempt",
            {},
            request_id,
            event_metadata=event_metadata,
        )
        if not result.success:
            return result
        content = self._tool_public_content(request_id, "generate_buggy_attempt")
        buggy_code = content.get("buggy_code")
        if not isinstance(buggy_code, str):
            artifact = self._artifact_for(request_id)
            if artifact is None:
                return AgentResult(success=False, agent=AgentRole.STUDENT_AGENT, error_code="BUGGY_ATTEMPT_FAILED")
            buggy_code = artifact.get("buggy_code")
            if not isinstance(buggy_code, str):
                return AgentResult(success=False, agent=AgentRole.STUDENT_AGENT, error_code="BUGGY_ATTEMPT_FAILED")
        message = str(content.get("message", "我写了一版代码，请帮我检查。"))
        return AgentResult(
            success=True,
            agent=AgentRole.STUDENT_AGENT,
            response=message,
            ui_action=UIAction.SHOW_CODE_REVIEW,
            ready_for_code=True,
            state=result.state,
            public_content={"buggy_code": buggy_code, "message": message},
        )

    def evaluate_fix(self, fixed_code: str, *, request_id: str) -> AgentResult:
        result = self._run_forced_tool("evaluate_fix", {"fixed_code": fixed_code}, request_id)
        if not result.success:
            return result
        content = self._tool_public_content(request_id, "evaluate_fix")
        if not isinstance(content.get("correct"), bool):
            return AgentResult(success=False, agent=AgentRole.STUDENT_AGENT, error_code="FIX_EVALUATION_FAILED")
        evaluation = AgentResult(
            success=True,
            agent=AgentRole.STUDENT_AGENT,
            response=str(content.get("feedback", "")),
            state=result.state,
            public_content={"correct": content["correct"], "feedback": str(content.get("feedback", ""))},
        )
        if content["correct"]:
            self._complete_session(str(content.get("feedback", "")), request_id, source="validated_evaluation")
        return evaluation

    def _loop_for(self, role: AgentRole, model: DecisionModel) -> _ForumRoleContextLoop:
        spec = self.specs[role]
        return _ForumRoleContextLoop(
            session_id=self.session.id,
            role=role,
            model=model,
            tools=self.tools,
            memory=self.memory,
            spec=AgentLoopSpec(
                system_prompt=_system_prompt(spec),
                assignment_title=str(getattr(self.assignment, "title", "") or ""),
                key_concepts=self._key_concepts(),
                reference_code=str(getattr(self.preset, "reference_code", "") or ""),
                coverage_config=self._coverage_config(),
                max_output_chars=spec.max_output_chars,
            ),
            context_builder=lambda snapshot, input_kind: self._context_for(role, snapshot, input_kind),
            learner_name=self.learner_name,
        )

    def _run_forced_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        request_id: str,
        *,
        event_metadata: Optional[Mapping[str, Any]] = None,
    ) -> AgentResult:
        return self._loop_for(
            AgentRole.STUDENT_AGENT,
            _ForcedToolModel(ToolCall(f"{request_id}:{name}", name, arguments)),
        ).handle_tool_action(request_id=request_id, input_kind=name, event_metadata=event_metadata)

    def _context_for(self, role: AgentRole, snapshot: MemorySnapshot, input_kind: str) -> Dict[str, Any]:
        view = self.memory.view_for(snapshot, role)
        state = snapshot.state
        common = {
            "goal": state.goal,
            "user_goal": self._user_goal_for_state(state),
            "phase": state.phase,
            "code_review_status": state.code_review_status,
            "input_kind": input_kind,
            "probe_dimensions": list(self._coverage_config().probe_dimensions),
            "interaction_profile": build_interaction_profile(
                snapshot.student_messages
            ).to_prompt_dict(),
        }
        if role is AgentRole.TEACHER_AGENT:
            return {
                **common,
                "assignment": {
                    "title": str(getattr(self.assignment, "title", "") or ""),
                    "description": str(getattr(self.assignment, "description", "") or ""),
                },
                "stage1_description": str(getattr(self.session, "stage1_description", "") or ""),
                "stage2_completed": bool(getattr(self.session, "stage2_completed", False)),
                "key_concepts": self._key_concepts(),
                "coverage": self._coverage_for_prompt(state),
                "learning_evidence": list(state.learning_evidence),
                "role_memory": {"agent_state": asdict(view.agent_state), "messages": list(view.messages)},
            }
        return {
            **common,
            "learner_name": self.learner_name,
            "assignment": {
                "title": str(getattr(self.assignment, "title", "") or ""),
                "description": str(getattr(self.assignment, "description", "") or ""),
            },
            "key_concepts": self._key_concepts(),
            "user_explanations": [
                dict(message)
                for message in view.messages
                if message.get("role") == "student"
                and message.get("event_type") in {"agent_user_message", "chat"}
            ],
            "coverage": self._coverage_for_prompt(state),
            "role_memory": {"agent_state": asdict(view.agent_state), "messages": list(view.messages)},
        }

    def _user_goal_for_state(self, state) -> Dict[str, Any]:
        return build_stage3_user_goal(
            key_concepts=self._key_concepts(),
            coverage_summary=self._coverage_for_prompt(state),
            phase=state.phase,
            state_status=state.status,
            session_status=getattr(self.session, "status", "in_progress"),
            code_review_status=state.code_review_status,
            min_coverage=self._coverage_config().min_coverage,
        )

    def _coverage_for_prompt(self, state) -> Dict[str, Any]:
        """Expose only the safe, server-derived progress needed by Student Agent."""
        raw_coverage = list(state.concept_coverage or [])
        if not raw_coverage:
            raw_coverage = [
                {
                    "concept": concept,
                    "status": "unseen",
                    "attempts": 0,
                    "used_dimensions": [],
                }
                for concept in self._key_concepts()
            ]
        unresolved = list(state.unresolved_concepts or [])
        if not unresolved:
            unresolved = [
                item["concept"]
                for item in raw_coverage
                if item.get("status") != "covered"
                and isinstance(item.get("concept"), str)
            ]
        pending_probe = state.pending_probe
        probe_source = "pending_probe" if isinstance(pending_probe, Mapping) else None
        if not isinstance(pending_probe, Mapping) and isinstance(state.student_probe_intent, Mapping):
            pending_probe = state.student_probe_intent
            probe_source = "student_probe_intent"
        return {
            "concept_coverage": raw_coverage,
            "coverage_score": float(state.coverage_score or 0.0),
            "unresolved_concepts": unresolved,
            "ready_for_code": bool(state.ready_for_code),
            "pending_probe": dict(pending_probe) if isinstance(pending_probe, Mapping) else None,
            "pending_probe_source": probe_source,
            "student_probe_intent": (
                dict(state.student_probe_intent)
                if isinstance(state.student_probe_intent, Mapping)
                else None
            ),
        }

    def prepare_student_probe_intent(self, *, request_id: str) -> Optional[Dict[str, str]]:
        """Authorize a Student turn without storing a stale user message."""
        snapshot = self.memory.load(self.session.id)
        for candidate in (
            snapshot.state.pending_probe,
            snapshot.state.student_probe_intent,
        ):
            normalized = _normalize_probe_target(candidate)
            if normalized is not None:
                return normalized
        trigger = self.next_student_probe_trigger()
        if trigger is None:
            return None
        snapshot.state.student_probe_intent = dict(trigger)
        self.memory.append_event(
            self.session.id,
            "state_snapshot",
            AgentRole.STUDENT_AGENT.value,
            metadata={
                "request_id": f"{request_id}:student_intent",
                "terminal": False,
                "state": asdict(snapshot.state),
                "agent_states": {
                    role.value: asdict(agent_state)
                    for role, agent_state in snapshot.agent_states.items()
                },
            },
        )
        return dict(trigger)

    def _key_concepts(self) -> list[str]:
        getter = getattr(self.preset, "get_key_steps", None)
        raw = getter() if callable(getter) else getattr(self.preset, "key_steps", [])
        return [item.strip() for item in raw if isinstance(item, str) and item.strip()] if isinstance(raw, list) else []

    def _coverage_config(self):
        getter = getattr(self.preset, "get_difficulty_config", None)
        raw = getter() if callable(getter) else getattr(self.preset, "difficulty_config", {})
        try:
            return load_coverage_config(raw, self._key_concepts())
        except ValueError:
            return load_coverage_config({}, self._key_concepts())

    def _artifact_for(self, request_id: str) -> Optional[Mapping[str, Any]]:
        for event in reversed(self._events()):
            if event.event_type != "buggy_attempt" or event.metadata.get("request_id") != request_id:
                continue
            artifact = event.metadata.get("artifact")
            if isinstance(artifact, Mapping):
                return artifact
        return None

    def _tool_public_content(self, request_id: str, tool_name: str) -> Dict[str, Any]:
        for event in reversed(self._events()):
            call = event.metadata.get("tool_call")
            if (
                event.event_type == "tool_result"
                and event.metadata.get("request_id") == request_id
                and isinstance(call, Mapping)
                and call.get("name") == tool_name
                and event.metadata.get("ok") is True
            ):
                content = event.metadata.get("public_content")
                return dict(content) if isinstance(content, Mapping) else {}
        return {}

    def _events(self) -> list[EventRecord]:
        return self.memory.event_store.list_events(self.session.id, stage=3)

    def _sync_completed_goal(self, role: AgentRole, result: AgentResult) -> None:
        if result.success and result.state.get("status") == "complete":
            self._complete_session("学习目标已通过服务端检查。", request_id=None, source="complete_goal")

    def _sync_compat_rounds(self, role: AgentRole, result: AgentResult) -> None:
        if not result.success:
            return
        state_field = (
            "teacher_rounds"
            if role is AgentRole.TEACHER_AGENT
            else "student_rounds"
        )
        session_field = (
            "stage3_teacher_rounds"
            if role is AgentRole.TEACHER_AGENT
            else "stage3_student_rounds"
        )
        value = result.state.get(state_field)
        if type(value) is not int or value < 0:
            return
        if getattr(self.session, session_field, 0) != value:
            setattr(self.session, session_field, value)
            self.callbacks.save_session(self.session)

    def _complete_session(self, feedback: str, request_id: Optional[str], *, source: str) -> None:
        has_validated_pass = any(
            event.event_type == "stage_pass"
            and event.metadata.get("validated") is True
            for event in self._events()
        )
        if not has_validated_pass:
            self.memory.append_event(
                self.session.id,
                "stage_pass",
                "system",
                content=feedback,
                metadata={
                    "request_id": request_id,
                    "source": source,
                    "validated": True,
                },
            )
        self.session.stage3_completed = True
        self.session.status = "completed"
        if getattr(self.session, "completed_at", None) is None:
            self.session.completed_at = self.callbacks.now()
        self.callbacks.save_session(self.session)

    def _ready_for_code(self) -> bool:
        snapshot = self.memory.load(self.session.id)
        return bool(snapshot.state.ready_for_code) and snapshot.state.phase != "code_review"

    def _persist_request_alias(self, request_id: str, result: AgentResult) -> None:
        self.memory.append_event(
            self.session.id,
            "agent_result",
            result.agent.value,
            metadata={
                "request_id": request_id,
                "agent_result": {
                    "success": result.success,
                    "agent": result.agent.value,
                    "response": result.response,
                    "ui_action": result.ui_action.value,
                    "ready_for_code": result.ready_for_code,
                    "state": dict(result.state),
                    "public_content": dict(result.public_content),
                    "error_code": result.error_code,
                },
            },
        )


def _system_prompt(spec: AgentSpec) -> str:
    return f"{spec.system_prompt}\n目标：{spec.goal}\n回复不超过 {spec.max_output_chars} 个字符。"


def _safe_learner_name(value: Any) -> str:
    text = str(value or "").strip()
    return text[:50] or "学习者"


def _resolve_learner_name(session: Any) -> str:
    """Resolve the logged-in learner's display name without hard-coupling tests to Flask."""

    candidates: List[Any] = []
    try:
        student = getattr(session, "student", None)
    except Exception:
        student = None
    if student is not None:
        candidates.extend([
            getattr(student, "full_name", None),
            getattr(student, "username", None),
        ])

    student_id = getattr(session, "student_id", None)
    if student_id:
        try:
            from models import User

            user = User.query.filter_by(student_id=str(student_id)).first()
        except Exception:
            user = None
        if user is not None:
            candidates.extend([
                getattr(user, "full_name", None),
                getattr(user, "username", None),
            ])
        candidates.append(student_id)

    for candidate in candidates:
        value = _safe_learner_name(candidate)
        if value != "学习者":
            return value
    return "学习者"


def _is_generic_teacher_response(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or "")).strip()
    normalized = normalized.rstrip("。！？?!")
    return normalized in {
        item.rstrip("。！？?!")
        for item in _TEACHER_GENERIC_RESPONSES
    }


def _contextual_teacher_fallback(user_message: Any) -> str:
    """Make degraded-mode Teacher replies acknowledge the current answer.

    The fallback is used when the model service is unavailable or returns a
    generic continuation.  It must still feel like a response to the newest
    learner turn, rather than replaying one fixed sentence forever.
    """
    compact = re.sub(r"\s+", " ", str(user_message or "")).strip()
    compact = compact.replace("```", "").replace("\x00", "")[:96]
    if not compact:
        return _TEACHER_GENERIC_FALLBACK
    lowered = compact.casefold()
    if "null" in lowered or "空" in compact:
        return (
            f"你提到“{compact}”。这里先区分一个容易混淆的点："
            "是完全没有输出，还是打印了字面量 null？请结合实际运行结果说明。"
        )
    if "0" in compact or "零" in compact:
        return (
            f"你提到“{compact}”。先把这个边界说清楚：输入为 0 时程序实际输出什么？"
            "请说明这个输出和‘没有项’之间的关系。"
        )
    return (
        f"我看到你刚才说的是“{compact}”。先确认一个具体点："
        "对这个输入，程序实际输出什么？请同时说明为什么。"
    )


def _teacher_help_fallback(
    user_message: Any,
    target: Optional[Mapping[str, str]],
) -> str:
    """Give a useful knowledge explanation when the Teacher model is down."""
    compact = re.sub(r"\s+", " ", str(user_message or "")).strip()
    compact = compact.replace("```", "").replace("\x00", "")[:96]
    concept = str((target or {}).get("concept") or "这个知识点").strip()
    if "循环" in concept or "边界" in concept or "索引" in concept:
        explanation = (
            "循环边界决定哪些位置会被处理。以数组长度 n 为例，合法下标是 0 到 n-1，"
            "所以条件通常写成 i < n；当 i 等于 n 时循环应停止，否则就会访问越界。"
            "例如 n=3 时只处理 0、1、2。"
        )
    elif "斐波那契" in concept or "数列" in concept:
        explanation = (
            "斐波那契数列从 0、1 开始，后面的每一项等于前两项之和。"
            "输出前 N 项时，N=0 表示没有任何项，N=1 只输出 0；先处理这两个边界，"
            "再从第三项开始用前两项更新当前项。"
        )
    else:
        explanation = (
            f"“{concept}”的关键是先明确输入，再说明程序中哪一步使用这个输入，"
            "最后对应到输出或状态变化。可以先用一个最小输入逐步跟踪，而不是只记结论。"
        )
    prefix = f"你刚才说“{compact}”，说明你已经注意到题目的输入和输出；" if compact else ""
    return f"{prefix}这里先补充一个关键知识点：{explanation}现在请你用自己的话说明这个例子为什么这样处理。"


def _replace_student_self_reference(response: str, learner_name: str) -> str:
    name = _safe_learner_name(learner_name)
    return response.replace("学生 Agent", name).replace("学生Agent", name).replace("小明", name)


def _student_opening_question(
    target: Mapping[str, str],
    learner_name: str,
) -> str:
    """Start Xiaoming's turn as a peer asking to be taught."""
    name = _safe_learner_name(learner_name)
    concept = str(target.get("concept") or "这道题").strip()
    return f"{name}，我还不太会“{concept}”。你可以用简单的话告诉我这道题应该怎么处理吗？"


def _looks_like_probe_answer(value: str) -> bool:
    text = re.sub(r"\s+", "", str(value or "")).casefold()
    if len(text) < 6:
        return False
    return any(
        marker in text
        for marker in (
            "我已经解释",
            "我理解",
            "我认为",
            "因为",
            "所以",
            "应该",
            "输出",
            "负责",
            "会在",
            "等于",
            "循环",
            "边界",
        )
    )


def _fallback_student_probe_question(target: Mapping[str, str], learner_name: str) -> str:
    """Create one learner-facing peer question without calling the provider."""
    name = _safe_learner_name(learner_name)
    concept = str(target.get("concept") or "这个概念").strip()
    dimension = str(target.get("dimension") or "").strip()
    questions = {
        "core": f"{name}，请用自己的话说明“{concept}”在这道题里具体负责什么？",
        "edge_case": f"{name}，换一个边界输入，说明“{concept}”会怎样处理，为什么？",
        "application": f"{name}，请举一个具体输入或真实场景，说明“{concept}”怎样应用？",
    }
    return questions.get(
        dimension,
        f"{name}，请换一个具体例子说明“{concept}”如何应用？",
    )


def _normalize_probe_target(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, Mapping):
        return None
    concept = value.get("concept")
    dimension = value.get("dimension")
    if not isinstance(concept, str) or not concept.strip():
        return None
    if not isinstance(dimension, str) or not dimension.strip():
        return None
    return {
        "concept": concept.strip(),
        "dimension": dimension.strip(),
    }


def _normalize_reply_text(value: Any) -> str:
    """Normalize harmless formatting differences before duplicate detection."""

    return "".join(str(value or "").split()).casefold()


def build_feynman_runtime(session, assignment, preset, *, model=None, callbacks=None):
    return DualFeynmanRuntime(
        session=session,
        assignment=assignment,
        preset=preset,
        model=model or build_stage3_decision_model(),
        callbacks=callbacks or FeynmanCallbacks(),
    )


__all__ = [
    "AgentSpec",
    "DualFeynmanRuntime",
    "FeynmanCallbacks",
    "build_feynman_runtime",
]
