"""Small, privacy-preserving interaction signals for Stage 3 prompts.

The profile is derived from the already persisted learner messages.  It is
deliberately a deterministic summary: building it never calls a model, stores
new learner text, or tries to infer identity or ability beyond the current
conversation shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any, Iterable, Mapping


_UNCERTAINTY_MARKERS = (
    "不会",
    "不太会",
    "不懂",
    "不太懂",
    "不明白",
    "不知道",
    "没懂",
    "不理解",
    "不清楚",
    "答不上",
    "不会做",
    "不会写",
)
_QUESTION_MARKERS = ("?", "？", "怎么", "如何", "为什么", "吗", "能不能", "是不是")
_EXPLANATION_MARKERS = (
    "因为",
    "所以",
    "表示",
    "负责",
    "输出",
    "等于",
    "循环",
    "边界",
    "下标",
    "先",
    "然后",
    "最后",
)
_ACKNOWLEDGEMENT_MARKERS = ("好的", "好", "嗯", "明白", "懂了", "知道了", "可以", "行")


@dataclass(frozen=True)
class InteractionProfile:
    """A bounded description of the learner's recent interaction pattern."""

    sample_size: int = 0
    average_message_chars: int = 0
    short_reply_count: int = 0
    uncertainty_count: int = 0
    uncertainty_streak: int = 0
    question_count: int = 0
    explanation_count: int = 0
    acknowledgement_count: int = 0
    mode: str = "guided"
    guidance: str = "先回应最新内容，再提出一个具体、单一的问题。"

    def to_prompt_dict(self) -> dict[str, Any]:
        """Return only stable, non-content signals for model context."""

        return asdict(self)


def _message_texts(messages: Iterable[Any] | None) -> list[str]:
    """Keep the last ten learner messages and discard everything else."""

    values: list[str] = []
    for item in messages or []:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        event_type = str(item.get("event_type") or "").strip().lower()
        if role not in {"student", "user"}:
            continue
        if event_type and event_type not in {"agent_user_message", "chat"}:
            continue
        text = " ".join(str(item.get("content") or "").split()).strip()
        if text:
            values.append(text[:1000])
    return values[-10:]


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def build_interaction_profile(messages: Iterable[Any] | None) -> InteractionProfile:
    """Build a deterministic profile from recent student-facing messages.

    The mode is intentionally conservative.  A single recent uncertainty
    signal is enough to request scaffolding, while short answers ask for a
    smaller check rather than a broad explanatory prompt.
    """

    texts = _message_texts(messages)
    if not texts:
        return InteractionProfile()

    lengths = [len(text) for text in texts]
    short_reply_count = sum(length <= 12 for length in lengths)
    uncertainty_flags = [_has_marker(text, _UNCERTAINTY_MARKERS) for text in texts]
    uncertainty_count = sum(uncertainty_flags)
    uncertainty_streak = 0
    for flag in reversed(uncertainty_flags):
        if not flag:
            break
        uncertainty_streak += 1
    question_count = sum(_has_marker(text, _QUESTION_MARKERS) for text in texts)
    explanation_count = sum(
        len(text) >= 6 and _has_marker(text, _EXPLANATION_MARKERS)
        for text in texts
    )
    acknowledgement_count = sum(_has_marker(text, _ACKNOWLEDGEMENT_MARKERS) for text in texts)

    if uncertainty_streak or uncertainty_count >= max(2, ceil(len(texts) / 3)):
        mode = "needs_scaffold"
        guidance = (
            "先承接用户的卡点，用一个最小输入或具体例子解释；然后只问一个确认问题，"
            "不要让用户重新完整讲一遍。"
        )
    elif short_reply_count >= max(2, ceil(len(texts) * 0.4)):
        mode = "concise_check"
        guidance = (
            "用户近期回复偏短，把问题缩成一个可观察点，优先让用户说明一个输出、"
            "边界或判断依据。"
        )
    elif explanation_count:
        mode = "explain_then_probe"
        guidance = (
            "用户已经给出解释，先确认其依据，再推进到一个尚未覆盖的角度；"
            "不要重复原问题。"
        )
    else:
        mode = "guided"
        guidance = "先回应最新内容，再提出一个具体、单一的问题。"

    return InteractionProfile(
        sample_size=len(texts),
        average_message_chars=round(sum(lengths) / len(lengths)),
        short_reply_count=short_reply_count,
        uncertainty_count=uncertainty_count,
        uncertainty_streak=uncertainty_streak,
        question_count=question_count,
        explanation_count=explanation_count,
        acknowledgement_count=acknowledgement_count,
        mode=mode,
        guidance=guidance,
    )


__all__ = ["InteractionProfile", "build_interaction_profile"]
