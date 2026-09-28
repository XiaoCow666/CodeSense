"""统一的百分制评分约定。

新提交分、作业平均分、班级平均分和学生综合分使用 0–100。
评测器转换时明确声明来源的分值范围。
"""

from __future__ import annotations

import math
import re
import json
from datetime import datetime
from sqlalchemy import and_, case


SCORE_MAX = 100.0
LOW_SCORE_THRESHOLD = 60.0
EXCELLENT_SCORE_THRESHOLD = 80.0
# submissions.submitted_at 使用 UTC；对应生产环境百分制版本启用时间。
PERCENT_SCORE_DEPLOYED_AT = datetime(2026, 9, 18, 5, 15, 38)
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


def normalize_evaluation_score(value, *, scale: int) -> int:
    """按来源的明确分值范围转换为整数百分制。"""

    try:
        raw = float(value)
    except (TypeError, ValueError):
        raise ValueError("评测器未返回有效分数")
    if not math.isfinite(raw):
        raise ValueError("评测器未返回有效分数")
    if scale not in (5, 10, 100) or not 0 <= raw <= scale:
        raise ValueError("评测器分数超出来源范围")
    return int(round(raw * SCORE_MAX / scale))


def normalize_structured_feedback_scores(data):
    """按 LLMEvaluator 返回字段各自的分值范围转换评分。"""

    result = dict(data)
    if result.get("overall_score") is not None:
        result["overall_score"] = normalize_evaluation_score(
            result["overall_score"], scale=5
        )
    for field in (
        "algorithm_score",
        "style_score",
        "functionality_score",
        "efficiency_score",
        "readability_score",
    ):
        if result.get(field) is not None:
            result[field] = normalize_evaluation_score(result[field], scale=100)
    return result


def legacy_five_to_percent(value):
    """显式转换历史 0–5 值，供一次性数据迁移使用。"""

    return clamp_percent(float(value) * 20) if value is not None else None


def normalize_mixed_score(value):
    """读取已经使用百分制的结构化反馈字段。"""

    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    return clamp_percent(raw, default=None)


def normalize_submission_score(value, submitted_at: datetime):
    """依据提交时间读取历史五分制和当前百分制记录。"""

    if submitted_at is None:
        raise ValueError("提交记录缺少时间，无法确定分值范围")
    score = normalize_mixed_score(value)
    if score is None:
        return None
    if submitted_at < PERCENT_SCORE_DEPLOYED_AT and score <= 5:
        return score * 20
    return score


def normalized_submission_score_sql(score_column, submitted_at_column):
    """按提交时间构造与提交记录读取规则相同的数据库表达式。"""

    return case(
        (
            and_(submitted_at_column < PERCENT_SCORE_DEPLOYED_AT, score_column <= 5),
            score_column * 20,
        ),
        else_=score_column,
    )


def display_submission_ai_feedback(value):
    """将已保存的评估内容整理为页面可展示的分项。"""

    if not isinstance(value, str):
        raise ValueError("AI 反馈内容格式错误")
    if not value.lstrip().startswith("{"):
        return {"overall_feedback": value, "dimension_feedback": "", "dimensions": {}}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("AI 反馈内容格式错误")
    overall_feedback = data.get("overall_feedback") or data.get("feedback") or ""
    dimension_feedback = data.get("dimension_feedback") or ""
    if not isinstance(overall_feedback, str) or not isinstance(dimension_feedback, str):
        raise ValueError("AI 反馈内容格式错误")
    dimensions = {}
    if dimension_feedback:
        for name in ("algorithm", "style", "functionality", "efficiency", "readability"):
            score = data.get(f"{name}_score")
            if score is not None:
                dimensions[name] = normalize_evaluation_score(score, scale=100)
    return {
        "overall_feedback": overall_feedback,
        "dimension_feedback": dimension_feedback,
        "dimensions": dimensions,
    }


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
