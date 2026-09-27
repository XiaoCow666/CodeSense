"""教师 AI 个性化建议的 prompt 片段构造（纯函数，无 Flask/DB 依赖）。

口径事实与 ``services/teacher_analytics.py`` 的
``_risk_tags_for_student`` 保持一致：“低分”标签在历史综合分
（``User.user_ascore``）低于阈值 **或** 最近一次得分低于阈值时都会触发。
因此“低分标签 + 最近一次高分”不是数据矛盾，不能让 LLM 推断为系统异常。
"""

LOW_SCORE_THRESHOLD = 60

RISK_TAG_CALIBER_INSTRUCTION = (
    "数据口径说明：\n"
    "- 学生的历史综合分与最近一次得分是两个不同指标。\n"
    "- “低分”风险标签在历史综合分低于 60 或最近一次得分低于 60 时触发。\n"
    "- 因此“风险标签含低分”与“最近一次得分较高”同时出现并不矛盾，"
    "通常表示该生历史基础薄弱但近期有进步。禁止在没有证据时把这种情况"
    "描述为数据记录异常或系统误判，应结合历史趋势给出鼓励或巩固建议。"
)


def _score_text(value):
    return "无" if value is None else str(value)


def format_attention_student_line(info):
    """构造单个需关注学生的 prompt 行。

    Args:
        info: ``{name, student_id, risk_tags, latest_score, historical_score}``，
            分数可为 None（未提交 / 无历史评分）。

    行内同时给出最近一次得分与历史综合分；当“低分”标签实际来自历史
    综合分而最近一次已达阈值时，追加口径注释，避免 LLM 把两个分数误读
    为互相矛盾。
    """
    name = info["name"]
    student_id = info["student_id"]
    tags = "、".join(info.get("risk_tags") or []) or "无"
    latest = info.get("latest_score")
    historical = info.get("historical_score")

    line = (
        f"- {name} ({student_id}): 风险标签 {tags}，"
        f"最近一次得分 {_score_text(latest)}，"
        f"历史综合分 {_score_text(historical)}"
    )

    low_tag_from_history = (
        "低分" in tags
        and historical is not None
        and historical < LOW_SCORE_THRESHOLD
        and (latest is None or latest >= LOW_SCORE_THRESHOLD)
    )
    if low_tag_from_history:
        line += (
            f"（注：低分标签来自历史综合分 {historical} 低于 60，"
            f"最近一次已达 {_score_text(latest)}，不属数据矛盾，"
            "请按历史薄弱、近期进步给出建议）"
        )

    return line


def format_risk_reason(info):
    """构造结构化卡片中的 ``risk_reason`` 短文本。

    与 :func:`format_attention_student_line` 同一口径：低分标签来自历史
    综合分而最近一次已达阈值时，补充来源说明，避免教师误读为数据矛盾。
    """
    tags = "/".join(info.get("risk_tags") or [])
    latest = info.get("latest_score")
    historical = info.get("historical_score")

    reason = f"存在{tags}风险，最近得分 {_score_text(latest)}"

    low_tag_from_history = (
        "低分" in tags
        and historical is not None
        and historical < LOW_SCORE_THRESHOLD
        and (latest is None or latest >= LOW_SCORE_THRESHOLD)
    )
    if low_tag_from_history:
        reason += (
            f"；低分标签来自历史综合分 {historical} 低于 60，"
            f"最近一次已达 {_score_text(latest)}，属历史薄弱、近期提升"
        )

    return reason
