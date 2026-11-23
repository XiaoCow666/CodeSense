"""Deterministic Stage 3 engagement assessment and progress tracking.

The forum already uses a bounded, server-side intent recognizer to route each
learner turn.  This module reuses those signals to decide whether a message is
meaningful enough to count towards the alternative completion paths without
adding another model call or trusting a browser-side counter.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

from utils.agents.intent import (
    INTENT_ANSWER_STUDENT,
    INTENT_ANSWER_TEACHER,
    INTENT_ASK_STUDENT,
    INTENT_ASK_TEACHER,
    INTENT_EXPLAIN_CONCEPT,
    recognize_forum_intent,
)


EFFECTIVE_QUESTION_TARGET = 4
ACTIVE_CONVERSATION_TARGET_SECONDS = 10 * 60
ACTIVE_CONVERSATION_MAX_GAP_SECONDS = 3 * 60
ACTIVE_CONVERSATION_MIN_MESSAGES = 3
MAX_ENGAGEMENT_MESSAGE_CHARS = 2_000
ASSESSMENT_VERSION = 3
ASSESSMENT_SOURCE = "server_stage3_engagement"

_QUESTION_INTENTS = frozenset({INTENT_ASK_TEACHER, INTENT_ASK_STUDENT})
_MEANINGFUL_INTENTS = frozenset({
    INTENT_ASK_TEACHER,
    INTENT_ASK_STUDENT,
    INTENT_ANSWER_TEACHER,
    INTENT_ANSWER_STUDENT,
    INTENT_EXPLAIN_CONCEPT,
})
_FILLER_MESSAGES = frozenset({
    "好",
    "好的",
    "好吧",
    "嗯",
    "哦",
    "行",
    "可以",
    "知道了",
    "明白了",
    "懂了",
    "继续",
    "下一步",
    "谢谢",
    "谢谢老师",
    "不知道",
    "不会",
    "不懂",
    "没懂",
    "你好",
    "您好",
    "在吗",
    "哈哈",
})
_OFF_TASK_SMALL_TALK = (
    "你是谁",
    "你叫什么",
    "今天天气",
    "天气怎么样",
    "你吃饭了吗",
    "你几岁",
    "讲个笑话",
)
_TASK_CUES = (
    "代码",
    "程序",
    "算法",
    "输入",
    "输出",
    "变量",
    "循环",
    "边界",
    "越界",
    "数组",
    "下标",
    "函数",
    "条件",
    "判断",
    "报错",
    "错误",
    "bug",
    "编译",
    "运行",
    "复杂度",
    "排序",
    "查找",
    "遍历",
    "递归",
    "迭代",
    "链表",
    "栈",
    "队列",
    "树",
    "图",
    "节点",
    "索引",
    "指针",
    "引用",
    "参数",
    "返回",
    "初始化",
    "终止",
    "测试用例",
    "code",
    "program",
    "algorithm",
    "input",
    "output",
    "variable",
    "loop",
    "array",
    "index",
    "function",
    "return",
    "error",
    "compile",
    "runtime",
    "pointer",
    "recursion",
    "stack",
    "queue",
    "tree",
    "graph",
    "complexity",
    "test case",
)
_EXPLANATION_CUES = (
    "因为",
    "所以",
    "表示",
    "应该",
    "先",
    "然后",
    "最后",
    "如果",
    "否则",
    "我的理解",
    "我认为",
    "会在",
    "等于",
)


@dataclass(frozen=True)
class EngagementAssessment:
    valid_message: bool
    valid_question: bool
    reason: str
    intent: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source": ASSESSMENT_SOURCE,
            "version": ASSESSMENT_VERSION,
            **asdict(self),
        }


def assess_stage3_message(
    message: Any,
    *,
    previous_messages: Iterable[Any] = (),
    intent_name: str | None = None,
    intent_is_question: bool | None = None,
    task_context: Iterable[Any] = (),
) -> EngagementAssessment:
    """Classify one learner message using bounded, explainable rules."""

    raw_text = str(message or "")
    if len(raw_text) > MAX_ENGAGEMENT_MESSAGE_CHARS:
        return EngagementAssessment(False, False, "too_long", intent_name or "")
    text = " ".join(raw_text.split()).strip()
    compact = _compact(text)
    if _substantive_length(text) < 5:
        return EngagementAssessment(False, False, "too_short", intent_name or "")
    if compact in {_compact(value) for value in _FILLER_MESSAGES}:
        return EngagementAssessment(False, False, "filler", intent_name or "")
    if any(marker in compact for marker in (_compact(value) for value in _OFF_TASK_SMALL_TALK)):
        return EngagementAssessment(False, False, "off_task_small_talk", intent_name or "")
    if _looks_like_gibberish(text):
        return EngagementAssessment(False, False, "low_information", intent_name or "")
    if _is_repeated(text, previous_messages):
        return EngagementAssessment(False, False, "duplicate", intent_name or "")

    recognized = recognize_forum_intent(text)
    intent = str(intent_name or recognized.name or "")
    explicit_question = (
        bool(intent_is_question)
        if intent_is_question is not None
        else bool(recognized.is_question)
    )
    is_question = explicit_question or intent in _QUESTION_INTENTS
    has_task_cue = (
        _contains_any(text, _TASK_CUES)
        or _has_code_shape(text)
        or _contains_task_context(text, task_context)
    )
    has_explanation = _contains_any(text, _EXPLANATION_CUES)

    valid_question = bool(
        is_question
        and has_task_cue
    )
    valid_message = bool(
        has_task_cue
        and (
            valid_question
            or intent in _MEANINGFUL_INTENTS
            or has_explanation
            or _substantive_length(text) >= 8
        )
    )
    return EngagementAssessment(
        valid_message=valid_message,
        valid_question=valid_question,
        reason="meaningful" if valid_message else "no_learning_signal",
        intent=intent,
    )


def summarize_stage3_engagement(
    events: Iterable[Mapping[str, Any]],
    *,
    task_context: Iterable[Any] = (),
) -> dict[str, Any]:
    """Summarize cumulative questions and the latest uninterrupted streak."""

    ordered = sorted(
        (event for event in events if isinstance(event, Mapping)),
        key=lambda event: (
            event.get("created_at") or datetime.min,
            int(event.get("id") or 0),
        ),
    )
    previous_messages: list[str] = []
    valid_events: list[tuple[datetime, EngagementAssessment]] = []
    effective_question_count = 0

    for event in ordered:
        created_at = event.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        text = str(event.get("content") or "")
        metadata = event.get("metadata")
        stored = metadata.get("engagement_assessment") if isinstance(metadata, Mapping) else None
        if (
            isinstance(stored, Mapping)
            and stored.get("source") == ASSESSMENT_SOURCE
            and stored.get("version") == ASSESSMENT_VERSION
            and isinstance(stored.get("valid_message"), bool)
            and isinstance(stored.get("valid_question"), bool)
        ):
            assessment = EngagementAssessment(
                valid_message=stored["valid_message"],
                valid_question=stored["valid_question"],
                reason=str(stored.get("reason") or "stored"),
                intent=str(stored.get("intent") or ""),
            )
        else:
            assessment = assess_stage3_message(
                text,
                previous_messages=previous_messages,
                task_context=task_context,
            )
        previous_messages.append(text)
        if not assessment.valid_message:
            continue
        valid_events.append((created_at, assessment))
        if assessment.valid_question:
            effective_question_count += 1

    active_streak: list[tuple[datetime, EngagementAssessment]] = []
    for event in valid_events:
        if (
            active_streak
            and (event[0] - active_streak[-1][0]).total_seconds()
            > ACTIVE_CONVERSATION_MAX_GAP_SECONDS
        ):
            active_streak = []
        active_streak.append(event)

    active_seconds = 0
    if len(active_streak) >= ACTIVE_CONVERSATION_MIN_MESSAGES:
        active_seconds = max(
            0,
            int((active_streak[-1][0] - active_streak[0][0]).total_seconds()),
        )

    return {
        "effective_message_count": len(valid_events),
        "effective_question_count": effective_question_count,
        "effective_question_target": EFFECTIVE_QUESTION_TARGET,
        "active_message_count": len(active_streak),
        "active_seconds": active_seconds,
        "active_target_seconds": ACTIVE_CONVERSATION_TARGET_SECONDS,
        "active_max_gap_seconds": ACTIVE_CONVERSATION_MAX_GAP_SECONDS,
        "questions_complete": effective_question_count >= EFFECTIVE_QUESTION_TARGET,
        "active_conversation_complete": (
            len(active_streak) >= ACTIVE_CONVERSATION_MIN_MESSAGES
            and active_seconds >= ACTIVE_CONVERSATION_TARGET_SECONDS
        ),
    }


def _contains_any(text: str, values: Iterable[str]) -> bool:
    lowered = text.casefold()
    return any(str(value).casefold() in lowered for value in values)


def _compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def _substantive_length(value: str) -> int:
    return len(re.findall(r"[\w\u3400-\u9fff]", str(value or "")))


def _looks_like_gibberish(value: str) -> bool:
    compact = _compact(value)
    if len(compact) >= 6 and len(set(compact)) <= 2:
        return True
    tokens = re.findall(r"[A-Za-z0-9_\u3400-\u9fff]+", str(value or "").casefold())
    return len(tokens) >= 3 and len(set(tokens)) == 1


def _has_code_shape(value: str) -> bool:
    text = str(value or "")
    return bool(
        re.search(r"[A-Za-z_]\w*\s*(?:<=|>=|==|!=|<|>)\s*[A-Za-z0-9_]", text)
        or re.search(r"[A-Za-z_]\w*\s*\([^\r\n]{0,80}\)", text)
        or re.search(r"(?:\+\+|--|->|::|&&|\|\|)", text)
    )


def _contains_task_context(text: str, task_context: Iterable[Any]) -> bool:
    lowered = str(text or "").casefold()
    for raw_value in task_context:
        value = " ".join(str(raw_value or "").split()).strip().casefold()
        if 2 <= len(value) <= 32 and value in lowered:
            return True
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,31}", value):
            if token in lowered:
                return True
    return False


def _is_repeated(message: str, previous_messages: Iterable[Any]) -> bool:
    current = _compact(message)
    if not current:
        return False
    for previous in previous_messages:
        candidate = _compact(str(previous or ""))
        if not candidate:
            continue
        if current == candidate:
            return True
        if min(len(current), len(candidate)) >= 8:
            if SequenceMatcher(None, current, candidate).ratio() >= 0.9:
                return True
    return False


__all__ = [
    "ACTIVE_CONVERSATION_MAX_GAP_SECONDS",
    "ACTIVE_CONVERSATION_MIN_MESSAGES",
    "ACTIVE_CONVERSATION_TARGET_SECONDS",
    "ASSESSMENT_SOURCE",
    "ASSESSMENT_VERSION",
    "EFFECTIVE_QUESTION_TARGET",
    "MAX_ENGAGEMENT_MESSAGE_CHARS",
    "EngagementAssessment",
    "assess_stage3_message",
    "summarize_stage3_engagement",
]
