"""Bounded, server-authoritative execution loop for Stage 3 agents."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional

from .coverage import CoverageConfig
from .contracts import (
    MAX_TOOL_CALLS_PER_DECISION,
    AgentDecision,
    AgentResult,
    AgentRole,
    AgentState,
    GoalStatus,
    ToolCall,
    ToolResult,
    UIAction,
)
from .memory import EventRecord, MemorySnapshot, MemoryStore
from .model import DecisionModel, ModelError
from .tools import ToolContext, ToolRegistry


_SESSION_LOCKS: Dict[int, threading.RLock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()
_REDIS_LOCK_TTL_SECONDS = 120
_REDIS_LOCK_BLOCKING_SECONDS = 5
_READ_ONLY_TOOLS = frozenset({"inspect_learning_state", "recall_memory"})
_PUBLIC_STATE_FIELDS = frozenset({
    "goal", "phase", "teacher_rounds", "student_rounds", "learning_evidence",
    "misconceptions", "code_review_status", "status",
})
_PATCHABLE_STATE_FIELDS = frozenset({
    "phase", "learning_evidence", "concept_coverage", "coverage_score",
    "unresolved_concepts", "ready_for_code", "pending_probe",
    "student_probe_intent",
    "code_review_status", "status",
})
_VALID_PHASES = frozenset({"student_dialogue", "code_review"})
_VALID_CODE_REVIEW_STATUSES = frozenset({"pending", "passed", "failed", "approved", "complete"})


class AgentLoopError(Exception):
    """An expected bounded-loop failure represented by a public error code."""


@dataclass(frozen=True)
class AgentLoopConfig:
    max_model_steps: int = 4
    max_tool_calls_per_decision: int = MAX_TOOL_CALLS_PER_DECISION
    max_tool_calls_per_request: int = 4

    def __post_init__(self) -> None:
        if self.max_model_steps != 4:
            raise ValueError("max_model_steps must be exactly 4")
        if not 1 <= self.max_tool_calls_per_decision <= MAX_TOOL_CALLS_PER_DECISION:
            raise ValueError("invalid per-decision tool-call limit")
        if not 1 <= self.max_tool_calls_per_request <= 16:
            raise ValueError("invalid per-request tool-call limit")


@dataclass(frozen=True)
class AgentLoopSpec:
    system_prompt: str
    assignment_title: str = ""
    key_concepts: List[str] = field(default_factory=list)
    reference_code: str = ""
    coverage_config: CoverageConfig = field(default_factory=CoverageConfig)
    max_output_chars: int = 1200


class AgentLoop:
    def __init__(
        self,
        *,
        session_id: int,
        role: AgentRole,
        model: DecisionModel,
        tools: ToolRegistry,
        memory: MemoryStore,
        spec: AgentLoopSpec,
        config: Optional[AgentLoopConfig] = None,
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.model = model
        self.tools = tools
        self.memory = memory
        self.spec = spec
        self.config = config or AgentLoopConfig()
        self._active_trigger: Optional[Dict[str, Any]] = None
        self._active_target_role = role.value

    def handle_turn(
        self,
        user_message: str,
        *,
        request_id: str,
        input_kind: str = "chat",
    ) -> AgentResult:
        """Handle one idempotent user request without exposing private artifacts."""
        lock = _session_lock(self.session_id)
        with lock:
            with _distributed_session_lock(self.session_id) as acquired:
                if not acquired:
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="SESSION_LOCK_UNAVAILABLE",
                    )
                return self._handle_turn_locked(
                    user_message,
                    request_id,
                    input_kind,
                    target_role=self.role.value,
                    trigger=None,
                    skip_user_message=False,
                )

    def handle_trigger(self, trigger: Mapping[str, Any], *, request_id: str) -> AgentResult:
        lock = _session_lock(self.session_id)
        with lock:
            with _distributed_session_lock(self.session_id) as acquired:
                if not acquired:
                    return AgentResult(
                        success=False,
                        agent=self.role,
                        error_code="SESSION_LOCK_UNAVAILABLE",
                    )
                existing = self.memory.find_request_result(self.session_id, request_id)
                if existing is not None:
                    return existing
                normalized_trigger = _normalized_trigger(trigger)
                if normalized_trigger is None:
                    return self._failure("INVALID_AGENT_TRIGGER", request_id)
                self.memory.append_event(
                    self.session_id,
                    "agent_trigger",
                    "system",
                    content=normalized_trigger["goal"],
                    metadata={
                        "request_id": request_id,
                        "source_role": AgentRole.TEACHER_AGENT.value,
                        "target_role": self.role.value,
                        "message_kind": "agent_trigger",
                        "visibility": "private",
                        "trigger": dict(normalized_trigger),
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

        if not skip_user_message:
            self.memory.append_event(
                self.session_id, "agent_user_message", "student", content=user_message,
                metadata={"request_id": request_id, "input_kind": input_kind},
            )
        snapshot = self.memory.load(self.session_id)
        self._active_trigger = dict(trigger) if isinstance(trigger, Mapping) else None
        self._active_target_role = target_role
        context = self._tool_context(snapshot, request_id, input_kind)
        tool_results: List[Dict[str, Any]] = []
        total_tool_calls = 0
        internal_signals: Dict[str, Any] = {}

        for step in range(self.config.max_model_steps):
            decision = self._decide(input_kind, tool_results, request_id, snapshot, step)
            if isinstance(decision, AgentResult):
                return decision
            if (
                self.role is AgentRole.TEACHER_AGENT
                and internal_signals.get("student_probe")
                and decision.tool_calls
            ):
                # A successful probe request already hands control to the
                # orchestrator. Do not let a model keep issuing tools while
                # trying to manufacture the student's follow-up in this turn.
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
            safe_decision_message = _sanitize_public_response(
                decision.message, self.spec.max_output_chars,
            )
            decision_payload = decision.to_payload()
            decision_payload["message"] = safe_decision_message
            self.memory.append_event(
                self.session_id, "agent_decision", self.role.value,
                content=safe_decision_message,
                metadata={
                    "request_id": request_id,
                    "step": step,
                    "decision": decision_payload,
                },
            )
            if not decision.tool_calls:
                self._advance_successful_chat(
                    snapshot, user_message, decision.message, input_kind,
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
                    if (
                        input_kind != "intervention"
                        and not internal_signals
                        and signal_metadata
                    ):
                        internal_signals[signal_metadata["signal_type"]] = dict(
                            signal_metadata["internal_content"]
                        )
                    terminal_kind = _terminal_tool_kind(call, result)
                    terminal_success = terminal_kind is not None
                    if execution.persist:
                        self._persist_tool_result(call, result, request_id, patch=patch, terminal=terminal_success)
                    if patch and not terminal_success:
                        self._persist_state_checkpoint(snapshot, request_id)
                    tool_results.append(_tool_result_for_model(call, result))
                    if terminal_kind == "code_review":
                        self._advance_successful_chat(
                            snapshot, user_message, call.name, input_kind,
                        )
                        return self._finish_code_review(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "complete_goal":
                        self._advance_successful_chat(
                            snapshot, user_message, call.name, input_kind,
                        )
                        return self._finish_goal(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "fix_passed":
                        self._advance_successful_chat(
                            snapshot, user_message, call.name, input_kind,
                        )
                        return self._finish_fix(result, snapshot, request_id, internal_signals)
                    if terminal_kind == "student_probe":
                        return self._finish_probe(result, snapshot, request_id)
                    if (
                        self.role is AgentRole.TEACHER_AGENT
                        and result.signal_type == "student_probe"
                    ):
                        # Emit at most one student intervention for a teacher
                        # turn, even if the model batches multiple requests.
                        break

        return self._failure("MAX_AGENT_STEPS", request_id)

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
        try:
            system_prompt = self.spec.system_prompt
            if system_prompt_suffix:
                system_prompt = f"{system_prompt}\n\n{system_prompt_suffix}"
            decision = self.model.decide(
                system_prompt=system_prompt,
                context=self._build_context(snapshot, input_kind=input_kind),
                tool_specs=self.tools.specs_for(self.role),
                tool_results=tool_results,
            )
        except ModelError as error:
            return self._decision_failure(error.code, request_id, step)
        except Exception:
            return self._decision_failure("MODEL_ERROR", request_id, step)
        error = getattr(self.model, "last_error", None)
        if isinstance(error, ModelError):
            if (
                getattr(self.model, "fallback_used", False)
                and isinstance(decision, AgentDecision)
                and not decision.tool_calls
                and decision.message.strip()
            ):
                self.memory.append_event(
                    self.session_id,
                    "agent_fallback",
                    self.role.value,
                    metadata={
                        "request_id": str(request_id)[:80],
                        "role": self.role.value,
                        "step": int(step),
                        "error_code": _safe_error_code(error.code),
                    },
                )
            else:
                return self._decision_failure(error.code, request_id, step)
        if not isinstance(decision, AgentDecision):
            return self._decision_failure("INVALID_DECISION", request_id, step)
        return decision

    def _decision_failure(
        self, error_code: str, request_id: str, step: int,
    ) -> AgentResult:
        safe_code = _safe_error_code(error_code)
        self.memory.append_event(
            self.session_id,
            "agent_decision_error",
            self.role.value,
            metadata={
                "request_id": str(request_id)[:80],
                "role": self.role.value,
                "step": int(step),
                "error_code": safe_code,
            },
        )
        return self._failure(safe_code, request_id=request_id)

    def _build_context(self, snapshot: MemorySnapshot, *, input_kind: str) -> str:
        prompt = self.memory.view_for(snapshot, self.role).to_prompt_dict()
        prompt["input_kind"] = input_kind
        prompt["target_role"] = self._active_target_role
        if input_kind == "intervention" and isinstance(self._active_trigger, Mapping):
            prompt["trigger"] = dict(self._active_trigger)
        return json.dumps(prompt, ensure_ascii=False)

    def _tool_context(self, snapshot: MemorySnapshot, request_id: str, input_kind: str) -> ToolContext:
        recent_public_questions = [
            str(item.get("content") or "")
            for item in snapshot.visible_messages.get(AgentRole.STUDENT_AGENT, [])
            if isinstance(item, Mapping)
            and item.get("event_type") == "agent_message"
            and str(item.get("content") or "").strip()
        ][-8:]
        return ToolContext(
            session_id=self.session_id,
            request_id=request_id,
            role=self.role,
            memory=snapshot,
            input_kind=input_kind,
            target_role=self._active_target_role,
            assignment_title=self.spec.assignment_title,
            key_concepts=list(self.spec.key_concepts),
            reference_code=self.spec.reference_code,
            coverage_config=self.spec.coverage_config,
            trigger=dict(self._active_trigger) if isinstance(self._active_trigger, Mapping) else None,
            recent_public_questions=recent_public_questions,
        )

    def _execute_tool(
        self, call: ToolCall, context: ToolContext, request_id: str,
    ) -> List["_ToolExecution"]:
        side_effect = self.tools.is_side_effect(call.name)
        if side_effect:
            stored = self.memory.find_tool_result(
                self.session_id, request_id, call.call_id,
            )
            if stored is not None:
                context.executed_results[call.call_id] = stored
                return [_ToolExecution(stored, persist=False)]
            if self.memory.has_tool_call_claim(
                self.session_id, request_id, call.call_id,
            ):
                return [_ToolExecution(
                    ToolResult(ok=False, error_code="TOOL_CALL_UNFINISHED"),
                    persist=True,
                )]

        self.memory.append_event(
            self.session_id,
            "tool_call",
            self.role.value,
            metadata={
                "request_id": request_id,
                "tool_call": call.to_payload(),
                "claim": side_effect,
                "side_effect": side_effect,
            },
        )
        result = self.tools.execute(self.role, call, context)
        if result.ok or not result.retryable or call.name not in _READ_ONLY_TOOLS:
            return [_ToolExecution(result, persist=True)]
        retry = self.tools.execute(self.role, call, context)
        return [
            _ToolExecution(result, persist=True),
            _ToolExecution(retry, persist=True),
        ]

    def _persist_tool_result(
        self, call: ToolCall, result: ToolResult, request_id: str, *,
        patch: Optional[Dict[str, Any]] = None, terminal: bool = False,
    ) -> None:
        signal_metadata = _sanitized_signal_metadata(result)
        metadata = {
            "request_id": request_id,
            "tool_call": call.to_payload(),
            "ok": result.ok,
            "error_code": result.error_code,
            "terminal": terminal,
            "ui_action": result.public_content.get("ui_action"),
            "model_content": dict(result.model_content),
            "public_content": dict(result.public_content),
            "state_patch": dict(patch or {}),
        }
        metadata.update(signal_metadata)
        if not result.ok:
            metadata["agent_result"] = _result_payload(
                AgentResult(success=False, agent=self.role, error_code=result.error_code)
            )
        self.memory.append_event(self.session_id, "tool_result", self.role.value, metadata=metadata)
        for event in result.memory_events:
            if not isinstance(event, Mapping) or not isinstance(event.get("event_type"), str):
                continue
            event_metadata = event.get("metadata")
            self.memory.append_event(
                self.session_id,
                event["event_type"],
                self.role.value,
                content=str(event.get("content", "")),
                metadata={
                    "request_id": request_id,
                    **(dict(event_metadata) if isinstance(event_metadata, Mapping) else {}),
                },
            )

    def _validated_state_patch(self, call: ToolCall, patch: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(patch, Mapping):
            return None
        clean = dict(patch)
        if any(name not in _PATCHABLE_STATE_FIELDS for name in clean):
            return None
        for name, value in clean.items():
            if name == "phase" and (
                not isinstance(value, str) or value not in _VALID_PHASES
            ):
                return None
            if name == "learning_evidence" and not _valid_entries(value, {"concept", "evidence"}):
                return None
            if name == "concept_coverage" and not _valid_concept_coverage(value):
                return None
            if name == "coverage_score" and not _valid_coverage_score(value):
                return None
            if name == "unresolved_concepts" and not _valid_string_list(value):
                return None
            if name == "ready_for_code" and type(value) is not bool:
                return None
            if name in {"pending_probe", "student_probe_intent"} and not _valid_pending_probe(value):
                return None
            if name == "code_review_status" and (
                not isinstance(value, str) or value not in _VALID_CODE_REVIEW_STATUSES
            ):
                return None
            if name == "status" and (
                not isinstance(value, str)
                or call.name != "complete_goal"
                or value != "complete"
            ):
                return None
        return clean

    @staticmethod
    def _apply_state_patch(snapshot: MemorySnapshot, patch: Mapping[str, Any]) -> None:
        for name, value in patch.items():
            setattr(snapshot.state, name, value)

    def _persist_state_checkpoint(self, snapshot: MemorySnapshot, request_id: str) -> None:
        self.memory.append_event(
            self.session_id, "state_snapshot", self.role.value,
            metadata={
                "request_id": request_id,
                "terminal": False,
                "state": asdict(snapshot.state),
                "agent_states": {role.value: asdict(state) for role, state in snapshot.agent_states.items()},
            },
        )

    def _finish_public_response(
        self,
        decision: AgentDecision,
        snapshot: MemorySnapshot,
        request_id: str,
        internal_signals: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        state = snapshot.agent_states.setdefault(self.role, AgentState())
        response = self._sanitize_response(decision.message)
        state.last_decision = response
        state.goal_status = GoalStatus.COMPLETE if snapshot.state.status == "complete" else GoalStatus.IN_PROGRESS
        result = AgentResult(
            success=True, agent=self.role, response=response,
            ui_action=UIAction.CONTINUE_CHAT,
            ready_for_code=False,
            state=self._public_state(snapshot),
            internal_signals=dict(internal_signals or {}),
        )
        self._persist_completion(result, snapshot, request_id)
        return result

    def _sanitize_response(self, value: Any) -> str:
        return _sanitize_public_response(value, self.spec.max_output_chars)

    def _advance_successful_chat(
        self,
        snapshot: MemorySnapshot,
        user_message: str,
        last_decision: str,
        input_kind: str,
    ) -> None:
        if input_kind not in {"chat", "teacher_help"}:
            return
        if self.role is AgentRole.TEACHER_AGENT:
            snapshot.state.teacher_rounds += 1
        else:
            snapshot.state.student_rounds += 1
        state = snapshot.agent_states.setdefault(self.role, AgentState())
        state.agent_id = self.role.value
        state.turn_index += 1
        state.last_user_message = user_message
        state.last_decision = self._sanitize_response(last_decision)
        evidence = snapshot.state.learning_evidence
        state.current_focus = (
            str(evidence[-1].get("concept") or snapshot.state.phase)
            if evidence and isinstance(evidence[-1], Mapping)
            else snapshot.state.phase
        )
        state.goal_status = (
            GoalStatus.COMPLETE
            if snapshot.state.status == "complete"
            else GoalStatus.IN_PROGRESS
        )

    def _finish_code_review(
        self,
        tool_result: ToolResult,
        snapshot: MemorySnapshot,
        request_id: str,
        internal_signals: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        public_content = dict(tool_result.public_content)
        response = str(public_content.pop("message", ""))
        result = AgentResult(
            success=True, agent=self.role, response=response,
            ui_action=UIAction.SHOW_CODE_REVIEW, ready_for_code=True,
            state=self._public_state(snapshot), public_content=public_content,
            internal_signals=dict(internal_signals or {}),
        )
        self._persist_completion(result, snapshot, request_id)
        return result

    def _finish_goal(
        self,
        tool_result: ToolResult,
        snapshot: MemorySnapshot,
        request_id: str,
        internal_signals: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        result = AgentResult(
            success=True,
            agent=self.role,
            response=str(tool_result.public_content.get("message", "")),
            state=self._public_state(snapshot),
            public_content={"goal_status": "complete"},
            internal_signals=dict(internal_signals or {}),
        )
        self._persist_completion(result, snapshot, request_id)
        return result

    def _finish_fix(
        self,
        tool_result: ToolResult,
        snapshot: MemorySnapshot,
        request_id: str,
        internal_signals: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        public_content = dict(tool_result.public_content)
        feedback = _sanitize_public_response(
            str(public_content.get("feedback", "")), self.spec.max_output_chars,
        )
        public_content["feedback"] = feedback
        result = AgentResult(
            success=True,
            agent=self.role,
            response=feedback,
            state=self._public_state(snapshot),
            public_content=public_content,
            internal_signals=dict(internal_signals or {}),
        )
        self._persist_completion(result, snapshot, request_id)
        return result

    def _finish_probe(
        self, tool_result: ToolResult, snapshot: MemorySnapshot, request_id: str,
    ) -> AgentResult:
        message = self._sanitize_response(
            str(tool_result.public_content.get("message", ""))
        )
        result = AgentResult(
            success=True,
            agent=self.role,
            response=message,
            state=self._public_state(snapshot),
            public_content={"message": message},
        )
        self._persist_completion(
            result,
            snapshot,
            request_id,
            message_metadata={
                "source_role": self.role.value,
                "target_role": "user",
                "message_kind": "student_probe",
                "visibility": "public",
            },
        )
        return result

    def _persist_completion(
        self,
        result: AgentResult,
        snapshot: MemorySnapshot,
        request_id: str,
        *,
        message_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = _result_payload(result)
        signal_metadata = _sanitized_result_signal_metadata(result)
        events = [
            EventRecord(
                session_id=self.session_id,
                stage=3,
                event_type="agent_message",
                role=self.role.value,
                content=result.response,
                metadata={
                    "request_id": request_id,
                    "terminal": False,
                    "agent_result": payload,
                    "ready_for_code": result.ready_for_code,
                    **dict(message_metadata or {}),
                },
            ),
            EventRecord(
                session_id=self.session_id,
                stage=3,
                event_type="state_snapshot",
                role=self.role.value,
                metadata={
                    "request_id": request_id,
                    "terminal": True,
                    "state": asdict(snapshot.state),
                    "agent_states": {
                        role.value: asdict(state)
                        for role, state in snapshot.agent_states.items()
                    },
                    "agent_result": payload,
                    **signal_metadata,
                },
            ),
        ]
        append_events = getattr(self.memory, "append_events", None)
        if callable(append_events):
            append_events(events)
            return
        for event in events:
            self.memory.append_event(
                event.session_id,
                event.event_type,
                event.role,
                content=event.content,
                metadata=event.metadata,
            )

    def _failure(self, error_code: str, request_id: Optional[str]) -> AgentResult:
        result = AgentResult(success=False, agent=self.role, error_code=error_code)
        if request_id is not None:
            self.memory.append_event(
                self.session_id, "agent_result", self.role.value,
                metadata={"request_id": request_id, "agent_result": _result_payload(result)},
            )
        return result

    @staticmethod
    def _public_state(snapshot: MemorySnapshot) -> Dict[str, Any]:
        state = asdict(snapshot.state)
        return {name: value for name, value in state.items() if name in _PUBLIC_STATE_FIELDS}


def _session_lock(session_id: int) -> threading.RLock:
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id, threading.RLock())


@contextmanager
def _distributed_session_lock(session_id: int) -> Iterator[bool]:
    try:
        from flask import current_app, has_app_context

        redis_client = (
            current_app.config.get("SESSION_REDIS")
            if has_app_context()
            else None
        )
    except (ImportError, RuntimeError):
        redis_client = None
    if redis_client is None:
        yield True
        return

    redis_lock = None
    acquired = False
    try:
        redis_lock = redis_client.lock(
            f"stage3-agent-session:{session_id}",
            timeout=_REDIS_LOCK_TTL_SECONDS,
            blocking_timeout=_REDIS_LOCK_BLOCKING_SECONDS,
        )
        acquired = bool(redis_lock.acquire(blocking=True))
    except Exception:
        yield False
        return
    try:
        yield acquired
    finally:
        if acquired and redis_lock is not None:
            try:
                redis_lock.release()
            except Exception:
                pass


@dataclass(frozen=True)
class _ToolExecution:
    result: ToolResult
    persist: bool


def _sanitize_public_response(value: Any, maximum: int) -> str:
    from utils.thinking_ai import sanitize_response

    safe = sanitize_response(str(value or ""))
    return safe[:maximum]


def _safe_error_code(value: Any) -> str:
    text = str(value or "MODEL_ERROR")[:80]
    return text if text.replace("_", "").isalnum() else "MODEL_ERROR"


def _result_payload(result: AgentResult) -> Dict[str, Any]:
    payload = {
        "success": result.success,
        "agent": result.agent.value,
        "response": result.response,
        "ui_action": result.ui_action.value,
        "ready_for_code": result.ready_for_code,
        "state": dict(result.state),
        "public_content": dict(result.public_content),
        "error_code": result.error_code,
    }
    payload.update(_sanitized_result_signal_metadata(result))
    return payload


def _sanitized_result_signal_metadata(result: AgentResult) -> Dict[str, Any]:
    signals = result.internal_signals
    if not isinstance(signals, Mapping):
        return {}
    return _sanitized_signal_parts("student_probe", signals.get("student_probe"))


def _tool_result_for_model(call: ToolCall, result: ToolResult) -> Dict[str, Any]:
    return {
        "tool_call_id": call.call_id,
        "name": call.name,
        "ok": result.ok,
        "content": dict(result.model_content),
    }


def _terminal_tool_kind(call: ToolCall, result: ToolResult) -> Optional[str]:
    """Only server-recognized tool outcomes may end an AgentLoop turn."""
    if not result.ok:
        return None
    if (
        call.name == "generate_buggy_attempt"
        and result.public_content.get("ui_action") == UIAction.SHOW_CODE_REVIEW.value
    ):
        return "code_review"
    if call.name == "complete_goal" and result.state_patch.get("status") == "complete":
        return "complete_goal"
    if (
        call.name == "evaluate_fix"
        and result.public_content.get("correct") is True
        and result.state_patch.get("code_review_status") == "passed"
    ):
        return "fix_passed"
    if call.name == "ask_student_probe" and isinstance(result.public_content.get("message"), str):
        return "student_probe"
    return None


def _valid_entries(value: Any, required_keys: set[str]) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(item, Mapping)
            and required_keys.issubset(item)
            and all(isinstance(item[key], str) and item[key].strip() for key in required_keys)
            for item in value
        )
    )


def _valid_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _valid_pending_probe(value: Any) -> bool:
    if value is None:
        return True
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("concept"), str)
        and bool(value["concept"].strip())
        and isinstance(value.get("dimension"), str)
        and bool(value["dimension"].strip())
    )


def _valid_coverage_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0


def _valid_concept_coverage(value: Any) -> bool:
    required_keys = {
        "concept", "status", "attempts", "used_dimensions",
        "attempt_event_ids", "accepted_evidence_count",
        "evidence_event_ids", "last_evidence_event_id",
    }
    return (
        isinstance(value, list)
        and all(
            isinstance(item, Mapping)
            and required_keys.issubset(item)
            and isinstance(item["concept"], str)
            and item["concept"].strip()
            and isinstance(item["status"], str)
            and item["status"].strip()
            and type(item["attempts"]) is int
            and item["attempts"] >= 0
            and _valid_string_list(item["used_dimensions"])
            and _valid_string_list(item["attempt_event_ids"])
            and type(item["accepted_evidence_count"]) is int
            and item["accepted_evidence_count"] >= 0
            and _valid_string_list(item["evidence_event_ids"])
            and (item["last_evidence_event_id"] is None or isinstance(item["last_evidence_event_id"], str))
            for item in value
        )
    )


def _normalized_trigger(value: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(value, Mapping):
        return None
    concept = value.get("concept")
    dimension = value.get("dimension")
    goal = value.get("goal")
    if not all(isinstance(item, str) and item.strip() for item in (concept, dimension, goal)):
        return None
    return {
        "concept": concept.strip(),
        "dimension": dimension.strip(),
        "goal": goal.strip(),
    }


def _sanitized_signal_metadata(result: ToolResult) -> Dict[str, Any]:
    return _sanitized_signal_parts(result.signal_type, result.internal_content)


def _sanitized_signal_parts(signal_type: Any, internal_content: Any) -> Dict[str, Any]:
    if signal_type != "student_probe" or not isinstance(internal_content, Mapping):
        return {}
    allowed = {}
    for key in ("concept", "dimension", "goal"):
        value = internal_content.get(key)
        if not isinstance(value, str) or not value.strip():
            return {}
        allowed[key] = value.strip()
    return {
        "signal_type": "student_probe",
        "internal_content": allowed,
    }
