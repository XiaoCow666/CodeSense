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
ASSESSMENT_VERSION = 19
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
    "变量",
    "越界",
    "数组",
    "下标",
    "函数",
    "报错",
    "bug",
    "编译",
    "复杂度",
    "遍历",
    "递归",
    "迭代",
    "链表",
    "队列",
    "节点",
    "指针",
    "测试用例",
    "algorithm",
    "variable",
    "array",
    "function",
    "compile",
    "runtime",
    "pointer",
    "recursion",
    "complexity",
    "test case",
)
_AMBIGUOUS_TASK_CUES = (
    "输入",
    "输出",
    "循环",
    "边界",
    "条件",
    "判断",
    "错误",
    "运行",
    "排序",
    "查找",
    "栈",
    "树",
    "图",
    "索引",
    "引用",
    "参数",
    "返回",
    "初始化",
    "终止",
    "input",
    "output",
    "loop",
    "return",
    "index",
    "stack",
    "tree",
    "graph",
    "code",
    "program",
    "error",
    "queue",
)
_PROGRAMMING_CUE_PAIRS = (
    ("循环", "边界"),
    ("循环", "条件"),
    ("循环", "执行"),
    ("循环", "每轮"),
    ("循环", "更新"),
    ("循环", "退出"),
    ("循环", "终止"),
    ("循环", "次数"),
    ("输入", "边界"),
    ("输入", "为零"),
    ("输入", "初始值"),
    ("输入", "读入"),
    ("输入", "变量"),
    ("输出", "循环"),
    ("输出", "变量"),
    ("输出", "打印"),
    ("输出", "目标位置"),
    ("树", "节点"),
    ("图", "节点"),
    ("索引", "减一"),
    ("索引", "加一"),
    ("索引", "从零"),
    ("参数", "返回"),
    ("返回", "函数"),
    ("返回", "值"),
    ("初始化", "变量"),
    ("排序", "数组"),
    ("查找", "数组"),
    ("loop", "condition"),
    ("loop", "execute"),
    ("tree", "node"),
    ("graph", "node"),
    ("code", "compile"),
    ("code", "fail"),
    ("code", "run"),
    ("program", "compile"),
    ("program", "fail"),
    ("queue", "enqueue"),
    ("queue", "dequeue"),
    ("error", "compile"),
    ("error", "runtime"),
)
_TASK_CONTEXT_STOP_WORDS = frozenset({
    "a",
    "an",
    "and",
    "find",
    "for",
    "in",
    "of",
    "the",
    "to",
    "value",
    "with",
})
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
    is_question = bool(
        explicit_question
        or recognized.is_question
        or _has_question_fragment(raw_text)
    )
    has_task_cue = _has_task_signal(raw_text, task_context)
    question_has_task_cue = bool(
        is_question
        and _question_has_task_signal(raw_text, task_context)
    )
    effective_task_cue = question_has_task_cue if is_question else has_task_cue
    has_explanation = _contains_any(text, _EXPLANATION_CUES)

    valid_question = bool(
        is_question
        and question_has_task_cue
    )
    valid_message = bool(
        effective_task_cue
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


def _has_task_signal(text: str, task_context: Iterable[Any]) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    has_explicit_programming_cue = _contains_any(normalized, _TASK_CUES)
    has_specific_task_term = _contains_task_context(normalized, task_context)
    has_programming_cue_pair = _contains_programming_cue_pair(text)
    has_code_shape = _has_code_shape(
        normalized,
        allow_ambiguous_operators=bool(
            has_explicit_programming_cue
            or has_specific_task_term
            or has_programming_cue_pair
        ),
    )
    has_contextualized_ambiguous_cue = bool(
        _contains_ambiguous_task_cue(normalized)
        and (
            has_explicit_programming_cue
            or has_code_shape
            or has_specific_task_term
            or has_programming_cue_pair
        )
    )
    return bool(
        has_explicit_programming_cue
        or has_code_shape
        or has_specific_task_term
        or has_contextualized_ambiguous_cue
    )


def _question_has_task_signal(text: str, task_context: Iterable[Any]) -> bool:
    fragments = _message_fragments(text)
    question_indexes = [
        index
        for index, fragment in enumerate(fragments)
        if _fragment_is_question(fragment)
    ]
    if not question_indexes:
        return bool(
            fragments
            and _has_task_signal(fragments[-1], task_context)
        )
    for index in question_indexes:
        fragment = fragments[index]
        if _has_task_signal(fragment, task_context):
            return True
        if (
            index > 0
            and _is_short_anaphoric_question(fragment)
            and _has_task_signal(fragments[index - 1], task_context)
        ):
            return True
    return False


def _message_fragments(text: str) -> list[str]:
    not_equal_marker = "\ue000"
    protected_text = str(text or "").replace("!=", not_equal_marker)
    sentence_text = re.sub(
        r"\.(?=\s)",
        ".\n",
        protected_text,
    )
    return [
        fragment.replace(not_equal_marker, "!=").strip()
        for fragment in re.findall(
            r"[^。！？!?；;\r\n]+[。！？!?；;]?",
            sentence_text,
        )
        if fragment.strip()
    ]


def _fragment_is_question(fragment: str) -> bool:
    value = str(fragment or "").strip()
    if not value:
        return False
    if value.endswith(("?", "？")) or recognize_forum_intent(value).is_question:
        return True
    return bool(re.match(
        r"^(?:为什么|为何|怎么|如何|哪里|什么|是否|能否|可否|"
        r"请解释|请说明|请分析|请告诉|帮我|解释一下|说明一下|"
        r"why\b|how\b|what\b|when\b|where\b|who\b|which\b|"
        r"can\b|could\b|would\b|should\b|is\b|are\b|do\b|does\b|did\b|"
        r"explain\b|describe\b|tell\s+me\b|help\s+me\b)",
        value.casefold(),
    ))


def _has_question_fragment(text: str) -> bool:
    return any(_fragment_is_question(fragment) for fragment in _message_fragments(text))


def _is_short_anaphoric_question(text: str) -> bool:
    compact = _compact(text)
    if _substantive_length(text) > 12:
        return False
    return compact.startswith((
        "为什么会",
        "为什么这样",
        "怎么会",
        "怎么办",
        "怎么改",
        "哪里错",
        "为什么不对",
        "如何修复",
        "怎么修复",
        "whydidthis",
        "whydoesthis",
        "howdoifixthis",
        "whatiswrong",
    ))


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
    for raw_value in values:
        value = " ".join(str(raw_value or "").split()).strip().casefold()
        if not value:
            continue
        if re.fullmatch(r"[a-z0-9_ ]+", value):
            words = r"\s+".join(re.escape(part) for part in value.split())
            if re.search(rf"(?<![a-z0-9_]){words}(?![a-z0-9_])", lowered):
                return True
            continue
        if len(value) == 1:
            if re.search(
                rf"(?<![\w\u3400-\u9fff]){re.escape(value)}(?![\w\u3400-\u9fff])",
                lowered,
            ):
                return True
            continue
        if value in lowered:
            return True
    return False


def _contains_ambiguous_task_cue(text: str) -> bool:
    return _contains_any(text, _AMBIGUOUS_TASK_CUES)


def _contains_programming_cue_pair(text: str) -> bool:
    lowered = "\n".join(
        " ".join(fragment.split())
        for fragment in re.split(r"\r\n|\r|\n", str(text or ""))
    ).casefold()
    for first, second in _PROGRAMMING_CUE_PAIRS:
        first_spans = _cue_spans(lowered, first)
        second_spans = _cue_spans(lowered, second)
        for first_start, first_end in first_spans:
            for second_start, second_end in second_spans:
                if first_end <= second_start:
                    gap = lowered[first_end:second_start]
                elif second_end <= first_start:
                    gap = lowered[second_end:first_start]
                else:
                    gap = ""
                if len(gap) <= 12 and not re.search(r"[。！？!?；;.\r\n]", gap):
                    return True
    return False


def _cue_spans(text: str, cue: str) -> list[tuple[int, int]]:
    normalized = " ".join(str(cue or "").split()).strip().casefold()
    if not normalized:
        return []
    if re.fullmatch(r"[a-z0-9_ ]+", normalized):
        words = r"\s+".join(re.escape(part) for part in normalized.split())
        pattern = rf"(?<![a-z0-9_]){words}(?![a-z0-9_])"
    else:
        blocked_suffix = {"输入": "法"}.get(normalized)
        suffix_guard = rf"(?!{re.escape(blocked_suffix)})" if blocked_suffix else ""
        pattern = rf"{re.escape(normalized)}{suffix_guard}"
    return [match.span() for match in re.finditer(pattern, text)]


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


def _has_code_shape(
    value: str,
    *,
    allow_ambiguous_operators: bool = False,
) -> bool:
    text = str(value or "")
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    operand = rf"(?:{identifier}|\d+(?:\.\d+)?)"
    string_literal = r'''(?:"[^"\r\n]*"|'[^'\r\n]*')'''
    call_argument = rf"(?:{operand}|{string_literal})"
    function_call = rf"{identifier}\(\s*(?:{call_argument}(?:\s*,\s*{call_argument})*)?\s*\)"
    strong_shape = bool(
        _has_comparison_shape(
            text,
            operand,
            allow_word_operands=allow_ambiguous_operators,
        )
        or re.search(function_call, text)
        or _has_increment_or_decrement_shape(text, identifier)
    )
    if strong_shape:
        return True
    if not allow_ambiguous_operators:
        return False
    return bool(
        re.search(rf"{identifier}\s*->\s*{identifier}", text)
        or re.search(rf"{identifier}\s*::\s*{identifier}", text)
        or re.search(rf"{operand}\s*(?:&&|\|\|)\s*{operand}", text)
    )


def _has_comparison_shape(
    text: str,
    operand: str,
    *,
    allow_word_operands: bool,
) -> bool:
    pattern = rf"(?P<left>{operand})\s*(?P<operator><=|>=|==|!=|<|>)\s*(?P<right>{operand})"
    for match in re.finditer(pattern, text):
        operator = match.group("operator")
        if operator not in {"<", ">"} or allow_word_operands:
            return True
        left = match.group("left")
        right = match.group("right")
        if (
            left[:1].isdigit()
            or right[:1].isdigit()
            or re.fullmatch(r"[A-Za-z_]", left)
            or re.fullmatch(r"[A-Za-z_]", right)
        ):
            return True
    return False


def _has_increment_or_decrement_shape(text: str, identifier: str) -> bool:
    for match in re.finditer(
        rf"(?<![A-Za-z0-9_]){identifier}(?:\+\+|--)(?![A-Za-z0-9_])",
        text,
    ):
        trailing = text[match.end():].lstrip()
        if (
            not trailing
            or not re.match(r"[A-Za-z0-9_]", trailing)
            or _has_increment_or_decrement_question_context(text, match)
        ):
            return True
    for match in re.finditer(
        rf"(?<![A-Za-z0-9_])(?:\+\+|--){identifier}(?![A-Za-z0-9_])",
        text,
    ):
        leading = text[:match.start()].rstrip()
        if (
            not leading
            or not re.search(r"[A-Za-z0-9_]$", leading)
            or _has_increment_or_decrement_question_context(text, match)
        ):
            return True
    return False


def _has_increment_or_decrement_question_context(text: str, match: re.Match) -> bool:
    leading = text[:match.start()].casefold()
    trailing = text[match.end():].casefold()
    asks_about_expression = bool(re.search(
        r"(?:\bwhy\s+(?:does|do|will|would)|\bhow\s+(?:does|do|will|would))\s*$",
        leading,
    ))
    describes_code_behavior = bool(re.match(
        r"\s*(?:change|affect|modify|update|return|evaluate|work|behave)\b",
        trailing,
    ))
    return asks_about_expression and describes_code_behavior


def _contains_task_context(text: str, task_context: Iterable[Any]) -> bool:
    lowered = str(text or "").casefold()
    generic_cues = {
        str(value).casefold()
        for value in (*_TASK_CUES, *_AMBIGUOUS_TASK_CUES)
    }
    for raw_value in task_context:
        value = " ".join(str(raw_value or "").split()).strip().casefold()
        if not (2 <= len(value) <= 32) or value in generic_cues:
            continue
        ascii_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,31}", value)
        if ascii_tokens and all(ord(char) < 128 for char in value):
            meaningful_tokens = [
                token
                for token in ascii_tokens
                if token.casefold() not in _TASK_CONTEXT_STOP_WORDS
            ]
            if len(ascii_tokens) == 1:
                if not meaningful_tokens or len(meaningful_tokens[0]) < 6:
                    continue
            if len(ascii_tokens) > 1 and len(meaningful_tokens) < 2:
                continue
        if _contains_any(lowered, (value,)):
            return True
    return False


def _is_repeated(message: str, previous_messages: Iterable[Any]) -> bool:
    current = _compact(message)
    current_operators = _semantic_operators(message)
    if not current:
        return False
    for previous in previous_messages:
        raw_previous = str(previous or "")
        if len(raw_previous) > MAX_ENGAGEMENT_MESSAGE_CHARS:
            continue
        candidate = _compact(raw_previous)
        if not candidate:
            continue
        candidate_operators = _semantic_operators(raw_previous)
        if current_operators != candidate_operators and (
            current_operators or candidate_operators
        ):
            continue
        if current == candidate:
            return True
        if min(len(current), len(candidate)) >= 8:
            if SequenceMatcher(None, current, candidate).ratio() >= 0.9:
                return True
    return False


def _semantic_operators(value: str) -> tuple[tuple[str, str, str], ...]:
    """Keep each operator with its adjacent operands for fuzzy deduplication."""

    operator_pattern = r"<=|>=|==|!=|\+\+|--|->|::|&&|\|\||[<>=+\-*/%]"
    operand_pattern = r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?"
    token_pattern = rf"{operator_pattern}|{operand_pattern}"
    tokens = re.findall(token_pattern, str(value or "").casefold())
    contexts = []
    for index, token in enumerate(tokens):
        if not re.fullmatch(operator_pattern, token):
            continue
        left = tokens[index - 1] if index > 0 else ""
        right = tokens[index + 1] if index + 1 < len(tokens) else ""
        if left and re.fullmatch(operator_pattern, left):
            left = ""
        if right and re.fullmatch(operator_pattern, right):
            right = ""
        contexts.append((left, token, right))
    return tuple(contexts)


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
