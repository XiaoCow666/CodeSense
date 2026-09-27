"""统一的百分制评分约定。

提交分、作业平均分、班级平均分和学生综合分统一使用 0–100。
评测器边界仍兼容历史的 0–5 和 0–10 返回值，避免旧任务把分数写成错误的满分。
"""

from __future__ import annotations

import math
import re


SCORE_MAX = 100.0
LOW_SCORE_THRESHOLD = 60.0
EXCELLENT_SCORE_THRESHOLD = 80.0
_LEGACY_SCORE_TEXT_PATTERN = re.compile(r"(?<!\d)([0-5])分(?!钟)")
_LEGACY_SCORE_LABEL_PATTERN = re.compile(
    r"((?:分数|评分|得分)\s*[：:]\s*)([0-5])"
    r"(?=(?:\s*(?:分|分制)|[\r\n，。,；;]|\\n|$))"
)


def clamp_percent(value, *, default=0.0):
    """将一个已经是百分制的值限制在 0–100。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(SCORE_MAX, number))


def normalize_evaluation_score(value) -> int:
    """把评测器可能返回的 0–5、0–10 或 0–100 统一成整数百分制。"""

    try:
        raw = float(value)
    except (TypeError, ValueError):
        raise ValueError("评测器未返回有效分数")
    if not math.isfinite(raw):
        raise ValueError("评测器未返回有效分数")

    # 评测器的历史接口使用过 5 分制和 10 分制；百分制值保持原值。
    if raw <= 5:
        raw *= 20
    elif raw <= 10:
        raw *= 10
    return int(round(clamp_percent(raw)))


def legacy_five_to_percent(value):
    """显式转换历史 0–5 值，供一次性数据迁移使用。"""

    return clamp_percent(float(value) * 20) if value is not None else None


def normalize_mixed_score(value):
    """读取仍可能包含旧 0–5 值的历史反馈字段。"""

    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 5:
        raw *= 20
    return clamp_percent(raw, default=None)


def normalize_feedback_text(value):
    """将评测器评语中仍使用旧 0–5 量纲的文字改成百分制。"""
    if not isinstance(value, str):
        return value

    value = _LEGACY_SCORE_TEXT_PATTERN.sub(
        lambda match: f"{int(match.group(1)) * 20}分",
        value,
    )
    return _LEGACY_SCORE_LABEL_PATTERN.sub(
        lambda match: f"{match.group(1)}{int(match.group(2)) * 20}",
        value,
    )
