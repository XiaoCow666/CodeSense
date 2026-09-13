"""Provider-neutral structured decision adapter for Stage 3 agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol

from .contracts import AgentDecision, GoalStatus, UIAction


MAX_MODEL_RESPONSE_CHARS = 12_000
_FENCED_JSON = re.compile(r"\A```json\s*\n(?P<payload>.*?)\n?```\s*\Z", re.DOTALL)
_REPAIRABLE_ERRORS = frozenset({"INVALID_JSON", "INVALID_DECISION"})
_DECISION_SCHEMA = {
    "message": {"type": "string", "default": ""},
    "tool_calls": {
        "type": "array",
        "default": [],
        "items": {
            "type": "object",
            "required": ["id", "name", "arguments"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "arguments": {"type": "object"},
            },
        },
    },
    "goal_status": {
        "type": "string",
        "enum": [status.value for status in GoalStatus],
        "default": GoalStatus.IN_PROGRESS.value,
    },
    "ui_action": {
        "type": "string",
        "enum": [action.value for action in UIAction],
        "default": UIAction.CONTINUE_CHAT.value,
    },
}
_DECISION_SCHEMA_TEXT = json.dumps(_DECISION_SCHEMA, ensure_ascii=False)


@dataclass(frozen=True)
class ModelError(Exception):
    """Sanitized model error suitable for event logging and public error codes."""

    code: str

    def __str__(self) -> str:
        return self.code


class DecisionModel(Protocol):
    def decide(
        self,
        *,
        system_prompt: str,
        context: str,
        tool_specs: List[Dict[str, Any]],
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentDecision:
        raise NotImplementedError


def parse_json_decision(response: Any) -> AgentDecision:
    """Parse one complete JSON decision, optionally in a single JSON fence."""
    if not isinstance(response, str) or not response.strip():
        raise ModelError("EMPTY_RESPONSE")
    if len(response) > MAX_MODEL_RESPONSE_CHARS:
        raise ModelError("RESPONSE_TOO_LONG")

    text = response.strip()
    fenced = _FENCED_JSON.fullmatch(text)
    if fenced:
        text = fenced.group("payload").strip()
    elif text.startswith("```") or "```" in text:
        raise ModelError("INVALID_JSON")

    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ModelError("INVALID_JSON") from exc
    if not isinstance(payload, Mapping):
        raise ModelError("INVALID_DECISION")
    try:
        return AgentDecision.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise ModelError("INVALID_DECISION") from exc


class StructuredDecisionModel:
    """Ask the shared client for a JSON decision, with one bounded repair attempt."""

    def __init__(
        self,
        client: Any = None,
        *,
        fallback_decision: Optional[AgentDecision] = None,
        fallback_message: str = "请继续说明你的思路。",
        temperature: float = 0.2,
        max_tokens: int = 1200,
        request_kind: str = "interactive",
    ) -> None:
        if client is None:
            from services.llm_client import llm_client

            client = llm_client
        self.client = client
        self.fallback_decision = fallback_decision or AgentDecision(message=fallback_message)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_kind = request_kind
        self.last_error: Optional[ModelError] = None
        self.fallback_used = False

    def decide(
        self,
        *,
        system_prompt: str,
        context: str,
        tool_specs: List[Dict[str, Any]],
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentDecision:
        self.last_error = None
        self.fallback_used = False
        if not self._is_available():
            return self._fallback("CLIENT_UNAVAILABLE")

        messages = self._decision_messages(system_prompt, context, tool_specs, tool_results)
        try:
            response = self._client_chat(messages)
            return parse_json_decision(response)
        except ModelError as error:
            if error.code not in _REPAIRABLE_ERRORS:
                return self._fallback(error.code)
            return self._repair_once(messages)
        except Exception:
            return self._fallback("CLIENT_ERROR")

    def _repair_once(self, messages: List[Dict[str, str]]) -> AgentDecision:
        repair_messages = list(messages)
        repair_messages.append({
            "role": "user",
            "content": (
                "上一次输出无效。只输出符合 schema 的 JSON。\n\n"
                "[DECISION_SCHEMA]\n" + _DECISION_SCHEMA_TEXT
            ),
        })
        try:
            response = self._client_chat(repair_messages)
            return parse_json_decision(response)
        except ModelError:
            return self._fallback("INVALID_DECISION")
        except Exception:
            return self._fallback("CLIENT_ERROR")

    def _chat_with_trace_kind(self, messages: List[Dict[str, str]]):
        """Keep injected legacy clients usable while labeling real calls."""
        try:
            return self.client.chat(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                request_kind="stage3",
            )
        except TypeError as error:
            # Tests and integrations may inject an older client whose method
            # predates the optional trace keyword.  A Python signature error
            # happens before the provider call, so this fallback cannot replay
            # a partially completed model request.
            if "unexpected keyword argument 'request_kind'" not in str(error):
                raise
            legacy_chat = self.client.chat
            return legacy_chat(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

    def _is_available(self) -> bool:
        try:
            return bool(self.client.is_available())
        except Exception:
            return False

    def _client_chat(self, messages: List[Dict[str, str]]) -> Any:
        """Pass request priority to the shared client without breaking fakes."""

        try:
            return self.client.chat(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                request_kind=self.request_kind,
            )
        except TypeError as error:
            # A few integrations and older test doubles implement the
            # historical chat signature.  Only retry for that specific
            # compatibility failure; do not hide a provider TypeError.
            if "request_kind" not in str(error):
                raise
            legacy_chat = self.client.chat
            return legacy_chat(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

    def _fallback(self, code: str) -> AgentDecision:
        self.last_error = ModelError(code)
        self.fallback_used = True
        return self.fallback_decision

    @staticmethod
    def _decision_messages(
        system_prompt: str,
        context: str,
        tool_specs: List[Dict[str, Any]],
        tool_results: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, str]]:
        prompt_sections = [
            "[ROLE_RULES_AND_GOAL]\n" + str(system_prompt),
            "[ROLE_MEMORY]\n" + str(context),
            "[TOOL_SCHEMA]\n" + json.dumps(tool_specs, ensure_ascii=False),
            "[DECISION_SCHEMA]\n" + _DECISION_SCHEMA_TEXT,
            "Return exactly one JSON object matching [DECISION_SCHEMA].",
        ]
        for result in tool_results or []:
            prompt_sections.append(
                "[TOOL_RESULT]\n" + json.dumps(result, ensure_ascii=False)
            )
        return [
            {"role": "system", "content": "You return structured agent decisions."},
            {"role": "user", "content": "\n\n".join(prompt_sections)},
        ]
