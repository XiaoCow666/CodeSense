"""Current-turn arbitration for the Stage 3 Teacher/Student forum.

The forum deliberately commits one public speaker per learner turn.  Both
agents share the public event memory, while a small server-side arbiter chooses
which role gets to act.  This avoids racing two side-effectful model calls and
prevents a deferred Student response from answering an old user message.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .contracts import AgentResult, AgentRole, Stage3MessageKind, Stage3Target
from .coverage import _evidence_covers_concept, _is_concrete_explanation
from .intent import (
    ForumIntent,
    ForumRouting,
    INTENT_ANSWER_TEACHER,
    INTENT_EXPLAIN_CONCEPT,
    recognize_forum_intent,
)


_STUDENT_WEIGHT_PERCENT = 45
_MAX_AUTO_SAME_SPEAKER_TURNS = 2


@dataclass
class ForumTurnResult:
    primary: AgentResult
    # Kept as a compatibility field for older callers.  A forum turn never
    # contains a second public response.
    interventions: List[AgentResult] = field(default_factory=list)
    routing: Optional[ForumRouting] = None

    def to_public_dict(self) -> Dict[str, Any]:
        payload = {
            "primary": _sanitize_public_payload(self.primary.to_public_dict()),
            "interventions": [],
        }
        if self.routing is not None:
            payload["routing"] = self.routing.to_public_dict()
        return payload


class Stage3Orchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def handle_user_message(
        self,
        message: str,
        *,
        target_role: AgentRole | Stage3Target | str,
        request_id: str,
        reply_to_event_id: Optional[str] = None,
    ) -> ForumTurnResult:
        requested_role = _normalize_target_role(target_role)
        intent = self._recognize_intent(message, reply_to_event_id)
        if requested_role is Stage3Target.AUTO and self._ready_for_code():
            # Once the server-side teaching gate is open, no new Teacher
            # question is allowed to reopen the dialogue. Route the current
            # turn to Student so the normal runtime can perform the single,
            # idempotent code-generation transition.
            role, selection_source = AgentRole.STUDENT_AGENT, "ready_for_code"
        else:
            role, selection_source = self._select_role_with_source(
                requested_role,
                message,
                request_id,
                intent,
            )
        if role is AgentRole.STUDENT_AGENT:
            if not self._ready_for_code() and not self._ensure_student_turn_target(request_id):
                # A Student answer/ask without a server-authorized target is
                # not safe to invent.  Keep the turn single-speaker and fall
                # back to Teacher when no concept remains available.
                role = AgentRole.TEACHER_AGENT
                selection_source = "student_target_unavailable"
        input_kind = "chat"
        if role is AgentRole.STUDENT_AGENT and self._student_answer_needs_teacher(message):
            # Xiaoming is a peer, not a second teacher.  Once the learner's
            # reply shows a knowledge gap, hand this same current turn to the
            # Teacher.  The Student does not get a chance to repeat its old
            # question, and the forum still commits exactly one public reply.
            role = AgentRole.TEACHER_AGENT
            selection_source = "teacher_help_after_student"
            input_kind = "teacher_help"
        # A learner message without an explicit reply target starts a new
        # forum turn, so its request id is also the root used to group the
        # single public reply.  Replies to an existing message inherit that
        # message's original turn id instead.
        parent_request_id = (
            self._parent_request_id(reply_to_event_id)
            if reply_to_event_id is not None
            else request_id
        )
        primary = self.runtime.handle_chat(
            role,
            message,
            request_id=request_id,
            event_metadata={
                "source_role": Stage3Target.USER.value,
                "target_role": role.value,
                "message_kind": Stage3MessageKind.USER_MESSAGE.value,
                "visibility": "public",
                "reply_to_event_id": reply_to_event_id,
                "parent_request_id": parent_request_id,
                "input_kind": input_kind,
            },
        )
        return ForumTurnResult(
            primary=primary,
            interventions=[],
            routing=ForumRouting(
                intent=intent,
                selected_role=role,
                selection_source=selection_source,
            ),
        )

    def _ready_for_code(self) -> bool:
        try:
            state = self.runtime.memory.load(self.runtime.session.id).state
        except (AttributeError, TypeError, ValueError):
            return False
        return bool(state.ready_for_code) and str(state.phase or "") != "code_review"

    def _student_answer_needs_teacher(self, message: str) -> bool:
        """Return whether the current reply is a knowledge request to Teacher.

        ``pending_probe.question`` is server-owned and is written when the
        Student has actually asked a public question.  A Student intent alone
        means that Xiaoming has not spoken yet, so it must not reroute the
        learner's message to Teacher before the opening peer question exists.
        """
        try:
            snapshot = self.runtime.memory.load(self.runtime.session.id)
        except (AttributeError, TypeError, ValueError):
            return False
        pending = snapshot.state.pending_probe
        if not _pending_probe_has_question(pending) and not self._legacy_student_question_exists():
            return False

        text = str(message or "").strip()
        if not text:
            return True
        normalized = re.sub(r"\s+", "", text).casefold()
        if any(marker in normalized for marker in _STUDENT_HELP_MARKERS):
            return True
        if _looks_like_question(text) and not _is_concrete_explanation(text):
            return True
        if not _is_concrete_explanation(text):
            return True
        concept = str(pending.get("concept") or "").strip()
        return bool(concept) and not _evidence_covers_concept(concept, text)

    def _legacy_student_question_exists(self) -> bool:
        """Recognize a Student question saved before ``pending_probe.question``.

        Older Stage 3 sessions persisted only the server-selected concept and
        dimension.  Their public event is still authoritative: when the last
        Student event is a probe, the next learner message is its answer and
        must be eligible for the Teacher hand-off path.
        """
        try:
            events = self.runtime.memory.forum_events(self.runtime.session.id)
        except (AttributeError, TypeError, ValueError):
            return False
        for event in reversed(events):
            if event.get("event_type") != Stage3MessageKind.AGENT_MESSAGE.value:
                continue
            if event.get("visibility") != "public":
                continue
            if event.get("source_role") != AgentRole.STUDENT_AGENT.value:
                return False
            return (
                event.get("message_kind") == Stage3MessageKind.STUDENT_PROBE.value
                and bool(str(event.get("content") or "").strip())
            )
        return False

    def _ensure_student_turn_target(self, request_id: str) -> bool:
        """Give an explicitly selected Student turn one server-owned target.

        The normal auto path already has either an intent or a pending probe.
        This guard keeps the visible "直接回答小明" control safe on an empty
        or restored session without letting the model invent a concept.
        """
        snapshot = self.runtime.memory.load(self.runtime.session.id)
        if _valid_probe_target(snapshot.state.pending_probe) or _valid_probe_target(
            snapshot.state.student_probe_intent
        ):
            return True
        prepare_intent = getattr(self.runtime, "prepare_student_probe_intent", None)
        if callable(prepare_intent):
            prepared = prepare_intent(request_id=f"{request_id}:explicit")
            return _valid_probe_target(prepared)
        return False

    def _recognize_intent(
        self,
        message: str,
        reply_to_event_id: Optional[str],
    ) -> ForumIntent:
        snapshot = self.runtime.memory.load(self.runtime.session.id)
        state = snapshot.state
        reply_role = self._reply_role(reply_to_event_id)
        last_agent_role = self._last_public_agent_role()
        return recognize_forum_intent(
            message,
            reply_source_role=reply_role,
            last_agent_role=last_agent_role,
            has_student_probe=_valid_probe_target(state.pending_probe),
            has_student_intent=_valid_probe_target(state.student_probe_intent),
            phase=str(state.phase or "student_dialogue"),
        )

    def _reply_role(self, reply_to_event_id: Optional[str]) -> Optional[AgentRole]:
        if reply_to_event_id is None:
            return None
        for event in self.runtime.memory.forum_events(self.runtime.session.id):
            if str(event.get("event_id") or "") != str(reply_to_event_id):
                continue
            for key in ("source_role", "target_role"):
                raw_role = event.get(key)
                try:
                    role = AgentRole(raw_role)
                except (TypeError, ValueError):
                    continue
                return role
            return None
        return None

    def _last_public_agent_role(self) -> Optional[AgentRole]:
        try:
            events = self.runtime.memory.forum_events(self.runtime.session.id)
        except (AttributeError, TypeError, ValueError):
            return None
        for event in reversed(events):
            if (
                event.get("event_type") != Stage3MessageKind.AGENT_MESSAGE.value
                or event.get("visibility") != "public"
            ):
                continue
            try:
                role = AgentRole(event.get("source_role") or event.get("role"))
            except (TypeError, ValueError):
                continue
            if role in {AgentRole.TEACHER_AGENT, AgentRole.STUDENT_AGENT}:
                return role
        return None

    def _select_role(
        self,
        requested_role: AgentRole | Stage3Target,
        message: str,
        request_id: str,
        intent: Optional[ForumIntent] = None,
    ) -> AgentRole:
        role, _ = self._select_role_with_source(
            requested_role,
            message,
            request_id,
            intent or self._recognize_intent(message, None),
        )
        return role

    def _select_role_with_source(
        self,
        requested_role: AgentRole | Stage3Target,
        message: str,
        request_id: str,
        intent: ForumIntent,
    ) -> tuple[AgentRole, str]:
        if requested_role is not Stage3Target.AUTO:
            if not isinstance(requested_role, AgentRole):
                raise ValueError(f"invalid target_role: {requested_role!r}")
            return requested_role, "explicit"

        if intent.target_role is AgentRole.TEACHER_AGENT:
            if intent.name == INTENT_ANSWER_TEACHER:
                # Do not let the reply-to-Teacher intent defeat fairness
                # forever. After two consecutive Teacher replies, hand the
                # current learner answer to Xiaoming through a fresh,
                # server-owned probe target.
                fairness_role = self._fairness_role()
                if fairness_role is AgentRole.STUDENT_AGENT:
                    prepare_intent = getattr(self.runtime, "prepare_student_probe_intent", None)
                    if callable(prepare_intent) and prepare_intent(
                        request_id=f"{request_id}:fairness-answer"
                    ) is not None:
                        return AgentRole.STUDENT_AGENT, "fairness_after_teacher_answer"
            return AgentRole.TEACHER_AGENT, "intent"

        snapshot = self.runtime.memory.load(self.runtime.session.id)
        student_ready = _valid_probe_target(snapshot.state.pending_probe) or _valid_probe_target(
            snapshot.state.student_probe_intent
        )
        if intent.target_role is AgentRole.STUDENT_AGENT and student_ready:
            return AgentRole.STUDENT_AGENT, "intent"
        if student_ready:
            # A pending target is the protocol's highest-confidence signal:
            # this newest learner message is the answer the Student should
            # assess.  It is still one current turn, never a queued reply.
            return AgentRole.STUDENT_AGENT, "pending_student_probe"

        if intent.target_role is AgentRole.STUDENT_AGENT:
            # A direct request for Xiaoming may start the next server-owned
            # probe.  The target is selected from the bounded coverage plan;
            # the model never gets to invent a concept or dimension here.
            prepare_intent = getattr(self.runtime, "prepare_student_probe_intent", None)
            if callable(prepare_intent) and prepare_intent(
                request_id=f"{request_id}:intent"
            ) is not None:
                return AgentRole.STUDENT_AGENT, "intent"
            return AgentRole.TEACHER_AGENT, "student_target_unavailable"

        fairness_role = self._fairness_role()
        if fairness_role is AgentRole.STUDENT_AGENT:
            # The weighted roll below keeps auto mode varied, but it must not
            # allow one role to monopolize the forum.  The Student still gets
            # a server-owned target before acting; this is scheduling, not a
            # deferred answer to an older turn.
            prepare_intent = getattr(self.runtime, "prepare_student_probe_intent", None)
            if callable(prepare_intent) and prepare_intent(
                request_id=f"{request_id}:fairness"
            ) is not None:
                return AgentRole.STUDENT_AGENT, "fairness"
        elif fairness_role is AgentRole.TEACHER_AGENT:
            return AgentRole.TEACHER_AGENT, "fairness"

        if intent.name == INTENT_EXPLAIN_CONCEPT:
            roll = _stable_roll(self.runtime.session.id, request_id, str(message or "").strip())
            if roll < _STUDENT_WEIGHT_PERCENT:
                prepare_intent = getattr(self.runtime, "prepare_student_probe_intent", None)
                if callable(prepare_intent) and prepare_intent(
                    request_id=f"{request_id}:arbiter"
                ) is not None:
                    return AgentRole.STUDENT_AGENT, "probability"

        return AgentRole.TEACHER_AGENT, "default"

    def _fairness_role(self) -> Optional[AgentRole]:
        """Return the other role after two consecutive public turns.

        Auto mode is intentionally probabilistic, but a pure weighted roll
        can produce an unhelpful run of four or five teacher turns.  Looking
        only at committed public replies gives the scheduler a small fairness
        guarantee without racing two model calls or inspecting private tool
        traces.
        """
        try:
            events = self.runtime.memory.forum_events(self.runtime.session.id)
        except (AttributeError, TypeError, ValueError):
            return None

        speakers: List[AgentRole] = []
        for event in reversed(events):
            if event.get("event_type") != Stage3MessageKind.AGENT_MESSAGE.value:
                continue
            if event.get("visibility") != "public":
                continue
            raw_role = event.get("source_role") or event.get("role")
            try:
                role = AgentRole(raw_role)
            except (TypeError, ValueError):
                continue
            if role not in {AgentRole.TEACHER_AGENT, AgentRole.STUDENT_AGENT}:
                continue
            speakers.append(role)
            if len(speakers) >= _MAX_AUTO_SAME_SPEAKER_TURNS:
                break

        if len(speakers) < _MAX_AUTO_SAME_SPEAKER_TURNS:
            return None
        if len(set(speakers[:_MAX_AUTO_SAME_SPEAKER_TURNS])) != 1:
            return None
        return (
            AgentRole.STUDENT_AGENT
            if speakers[0] is AgentRole.TEACHER_AGENT
            else AgentRole.TEACHER_AGENT
        )

    def _parent_request_id(self, reply_to_event_id: Optional[str]) -> Optional[str]:
        if reply_to_event_id is None:
            return None
        for event in self.runtime.memory.forum_events(self.runtime.session.id):
            if str(event.get("event_id") or "") == str(reply_to_event_id):
                request_id = event.get("parent_request_id") or event.get("request_id")
                return str(request_id) if request_id else None
        raise ValueError("reply_to_event_id not found in current session")


def _normalize_target_role(value: AgentRole | Stage3Target | str) -> AgentRole | Stage3Target:
    if isinstance(value, AgentRole):
        return value
    text = value.value if isinstance(value, Stage3Target) else str(value)
    if text == Stage3Target.AUTO.value:
        return Stage3Target.AUTO
    try:
        return AgentRole(text)
    except ValueError as exc:
        raise ValueError(f"invalid target_role: {value!r}") from exc


def _valid_probe_target(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("concept"), str)
        and bool(value.get("concept", "").strip())
        and isinstance(value.get("dimension"), str)
        and bool(value.get("dimension", "").strip())
    )


def _pending_probe_has_question(value: Any) -> bool:
    return (
        _valid_probe_target(value)
        and isinstance(value.get("question"), str)
        and bool(value.get("question", "").strip())
    )


def _looks_like_question(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        text.endswith(("?", "？", "吗", "呢"))
        or text.startswith(("为什么", "为何", "怎么", "如何", "什么", "请问", "能不能", "可不可以"))
    )


_STUDENT_HELP_MARKERS = (
    "不知道",
    "不懂",
    "不会",
    "不太会",
    "不清楚",
    "没学会",
    "看不懂",
    "听不懂",
    "怎么处理",
    "怎么做",
)


def _stable_roll(session_id: Any, request_id: str, message: str) -> int:
    seed = f"{session_id}:{request_id}:{message}".encode("utf-8", "ignore")
    return int(hashlib.sha256(seed).hexdigest()[:8], 16) % 100


_PRIVATE_PUBLIC_KEYS = frozenset({
    "internal_signals",
    "trigger",
    "topic_signal",
    "tool_arguments",
    "tool_call",
    "tool_calls",
    "decision",
    "state_decision",
    "artifact",
    "artifacts",
})


def _sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_public_payload(item)
            for key, item in value.items()
            if str(key) not in _PRIVATE_PUBLIC_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_public_payload(item) for item in value]
    return value
