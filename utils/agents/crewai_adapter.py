"""Optional CrewAI execution adapter for the Stage 3 decision model.

CrewAI is intentionally not a hard dependency of CodeSense.  The native
Stage 3 loop remains the source of truth for memory, tool permissions,
idempotency, and the one-public-speaker forum protocol.  When the optional
framework switch is enabled, this module uses one CrewAI Agent and one Task
to produce the same structured decision that the native model adapter expects.

This boundary is important: a CrewAI crew may improve role-specific
reasoning, but it must not commit events or decide that two agents should
speak in the same learner turn.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from .contracts import AgentDecision
from .model import (
    ModelError,
    StructuredDecisionModel,
    _REPAIRABLE_ERRORS,
    parse_json_decision,
)

logger = logging.getLogger(__name__)

_CREWAI_COMPONENTS: Optional[dict[str, Any]] = None
_CREWAI_IMPORT_ERROR: Optional[Exception] = None
_SHARED_LLM_CLASS: Any = None


class CrewAIUnavailable(RuntimeError):
    """Raised when the optional CrewAI runtime cannot be loaded."""


def _stage3_max_tokens() -> int:
    """Keep interactive Stage 3 JSON replies bounded and quick to emit."""

    try:
        value = int(os.environ.get("STAGE3_MODEL_MAX_TOKENS", 700))
    except (TypeError, ValueError):
        value = 700
    return max(400, min(2400, value))


def _load_crewai_components() -> dict[str, Any]:
    """Load CrewAI lazily so default app startup stays lightweight."""

    global _CREWAI_COMPONENTS, _CREWAI_IMPORT_ERROR
    if _CREWAI_COMPONENTS is not None:
        return _CREWAI_COMPONENTS
    if _CREWAI_IMPORT_ERROR is not None:
        raise CrewAIUnavailable("CrewAI import failed") from _CREWAI_IMPORT_ERROR

    # CrewAI initializes local RAG storage and telemetry listeners during
    # import. Keep its storage under the ignored Flask instance directory and
    # disable its extra telemetry; CodeSense already has its own observability.
    project_root = Path(__file__).resolve().parents[2]
    os.environ.setdefault("CREWAI_STORAGE_DIR", str(project_root / "instance" / "crewai"))
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    # CrewAI 1.15.x otherwise runs a first-use terminal consent flow even
    # when tracing=False. This flag only suppresses that CLI-oriented flow;
    # it does not change the Agent/Task execution semantics.
    os.environ.setdefault("CREWAI_TESTING", "true")
    try:
        from crewai import Agent, Crew, Process, Task
        from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages
        from crewai.llms.base_llm import BaseLLM
        from pydantic import PrivateAttr
    except Exception as exc:
        _CREWAI_IMPORT_ERROR = exc
        raise CrewAIUnavailable("CrewAI is not installed or is incompatible") from exc

    _CREWAI_COMPONENTS = {
        "Agent": Agent,
        "Crew": Crew,
        "Process": Process,
        "Task": Task,
        "BaseLLM": BaseLLM,
        "PrivateAttr": PrivateAttr,
        "set_suppress_tracing_messages": set_suppress_tracing_messages,
    }
    return _CREWAI_COMPONENTS


def crewai_available() -> bool:
    """Return whether CrewAI can be imported without breaking the app."""

    try:
        _load_crewai_components()
    except CrewAIUnavailable:
        return False
    return True


def _build_shared_client_llm(client: Any, *, temperature: float, max_tokens: int) -> Any:
    """Adapt CodeSense's failover/caching client to CrewAI's LLM contract."""

    global _SHARED_LLM_CLASS
    components = _load_crewai_components()
    if _SHARED_LLM_CLASS is None:
        base_llm = components["BaseLLM"]
        private_attr = components["PrivateAttr"]

        class SharedClientLLM(base_llm):
            _client: Any = private_attr()
            _request_temperature: float = private_attr()
            _request_max_tokens: int = private_attr()

            def __init__(self, wrapped_client: Any, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._client = wrapped_client
                self._request_temperature = float(kwargs.get("temperature") or 0.2)
                self._request_max_tokens = int(kwargs.get("max_tokens") or 1200)

            def call(
                self,
                messages: Any,
                tools: Any = None,
                callbacks: Any = None,
                available_functions: Any = None,
                from_task: Any = None,
                from_agent: Any = None,
                response_model: Any = None,
            ) -> str:
                del tools, callbacks, available_functions, from_task, from_agent, response_model
                normalized = _normalize_messages(messages)
                try:
                    response = self._client.chat(
                        normalized,
                        temperature=self._request_temperature,
                        max_tokens=self._request_max_tokens,
                        request_kind="interactive",
                    )
                except TypeError as error:
                    if "request_kind" not in str(error):
                        raise
                    response = self._client.chat(
                        normalized,
                        temperature=self._request_temperature,
                        max_tokens=self._request_max_tokens,
                    )
                if not response:
                    raise RuntimeError("empty LLM response")
                return str(response)

        _SHARED_LLM_CLASS = SharedClientLLM

    return _SHARED_LLM_CLASS(
        client,
        model="codesense-shared-client",
        temperature=temperature,
        max_tokens=max_tokens,
        provider="openai",
        is_litellm=False,
    )


def _normalize_messages(messages: Any) -> list[dict[str, str]]:
    """Convert CrewAI message objects into the shared client's format."""

    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    if not isinstance(messages, (list, tuple)):
        return [{"role": "user", "content": str(messages or "")}]

    normalized: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, Mapping):
            role = str(message.get("role") or "user")
            content = message.get("content")
        else:
            role = str(getattr(message, "role", "user") or "user")
            content = getattr(message, "content", "")
        normalized.append({"role": role, "content": str(content or "")})
    return normalized


class CrewAIDecisionModel:
    """DecisionModel-compatible wrapper backed by one CrewAI task.

    Tool calls remain JSON decisions and are validated/executed by AgentLoop
    after this class returns. This prevents a framework agent from bypassing
    server-side permissions or committing duplicate side effects.
    """

    framework_name = "crewai"

    def __init__(
        self,
        client: Any = None,
        *,
        fallback_message: str = "请继续说明你的思路。",
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> None:
        _load_crewai_components()
        if client is None:
            from services.llm_client import llm_client

            client = llm_client
        self.client = client
        self.fallback_decision = AgentDecision(message=fallback_message)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.last_error: Optional[ModelError] = None
        self.fallback_used = False
        self._llm = _build_shared_client_llm(
            client,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def decide(
        self,
        *,
        system_prompt: str,
        context: str,
        tool_specs: list[dict[str, Any]],
        tool_results: Optional[list[dict[str, Any]]] = None,
    ) -> AgentDecision:
        self.last_error = None
        self.fallback_used = False
        if not self._is_available():
            return self._fallback("CLIENT_UNAVAILABLE")

        messages = StructuredDecisionModel._decision_messages(
            system_prompt,
            context,
            tool_specs,
            tool_results,
        )
        task_description = messages[-1]["content"] if messages else ""
        try:
            response = self._run_crew(task_description, context)
            return parse_json_decision(response)
        except ModelError as error:
            if error.code not in _REPAIRABLE_ERRORS:
                return self._fallback(error.code)
            repair_description = (
                f"{task_description}\n\n"
                "[REPAIR]\n上一次输出无效。只输出符合 DECISION_SCHEMA 的单个 JSON 对象，"
                "不要输出 Markdown、解释或代码围栏。"
            )
            try:
                repaired = self._run_crew(repair_description, context)
                return parse_json_decision(repaired)
            except ModelError as repair_error:
                return self._fallback(repair_error.code)
            except Exception:
                return self._fallback("CREWAI_ERROR")
        except Exception:
            return self._fallback("CREWAI_ERROR")

    def _run_crew(self, task_description: str, context: str) -> str:
        components = _load_crewai_components()
        suppress_tracing_messages = components.get("set_suppress_tracing_messages")
        if callable(suppress_tracing_messages):
            # CrewAI's first-run tracing notice is designed for a terminal,
            # not for a browser request handled by Gunicorn.
            suppress_tracing_messages(True)
        role = _role_from_context(context)
        if role == "student_agent":
            role_label = "同伴学生 Agent（小明）"
            role_goal = "以同伴身份回应当前学习者，并只输出一项结构化决定。"
        else:
            role_label = "教师 Agent"
            role_goal = "以教师身份回应当前学习者，并只输出一项结构化决定。"

        agent = components["Agent"](
            role=role_label,
            goal=role_goal,
            backstory=(
                "你是 CodeSense 阶段3论坛中的唯一当前发言角色。"
                "你不能委派给其他角色，不能输出第二个角色的发言，"
                "必须严格遵守任务中给出的 JSON schema。"
            ),
            llm=self._llm,
            allow_delegation=False,
            max_iter=1,
            max_tokens=self.max_tokens,
            verbose=False,
            memory=False,
            cache=False,
        )
        task = components["Task"](
            description=task_description,
            expected_output="只输出一个符合 DECISION_SCHEMA 的 JSON 对象。",
            agent=agent,
        )
        crew = components["Crew"](
            agents=[agent],
            tasks=[task],
            process=components["Process"].sequential,
            verbose=False,
            memory=False,
            cache=False,
            tracing=False,
        )
        output = crew.kickoff()
        raw = getattr(output, "raw", output)
        if not raw:
            raise ModelError("EMPTY_RESPONSE")
        return str(raw)

    def _is_available(self) -> bool:
        try:
            return bool(self.client.is_available())
        except Exception:
            return False

    def _fallback(self, code: str) -> AgentDecision:
        self.last_error = ModelError(code)
        self.fallback_used = True
        return self.fallback_decision


def _role_from_context(context: str) -> str:
    try:
        payload = json.loads(context)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "teacher_agent"
    if isinstance(payload, Mapping):
        target_role = str(payload.get("target_role") or "")
        if target_role == "student_agent":
            return "student_agent"
    return "teacher_agent"


def build_stage3_decision_model(*, client: Any = None) -> Any:
    """Build the configured Stage 3 model, falling back safely to native."""

    framework = os.environ.get("STAGE3_AGENT_FRAMEWORK", "native").strip().lower()
    max_tokens = _stage3_max_tokens()
    if framework not in {"crewai", "crew-ai", "crew_ai"}:
        return StructuredDecisionModel(client=client, max_tokens=max_tokens)
    try:
        return CrewAIDecisionModel(client=client, max_tokens=max_tokens)
    except Exception as exc:
        # An optional framework must never make the native Stage 3 path
        # unavailable because of a version, storage, or import mismatch.
        logger.warning(
            "STAGE3_AGENT_FRAMEWORK=crewai but CrewAI is unavailable; using native model (%s)",
            type(exc).__name__,
        )
        return StructuredDecisionModel(client=client, max_tokens=max_tokens)


__all__ = [
    "CrewAIUnavailable",
    "CrewAIDecisionModel",
    "build_stage3_decision_model",
    "crewai_available",
]
