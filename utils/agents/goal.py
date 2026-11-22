"""Public, finite learning-goal state for the Stage 3 forum.

The agent loop keeps the authoritative Feynman state private.  This module
turns the safe subset of that state into a small user-facing contract: a
bounded progress value, milestones, and one concrete next action.
"""

from __future__ import annotations

from typing import Any, Mapping


_DEFAULT_MIN_COVERAGE = 0.8
_COVERED_STATUS = "covered"
_CODE_REVIEW_STATUSES = frozenset({"passed", "approved", "complete"})
_DIMENSION_LABELS = {
    "core": "核心规则",
    "edge_case": "边界情况",
    "application": "实际应用",
}


def build_stage3_user_goal(
    *,
    key_concepts: Any,
    coverage_summary: Any,
    phase: Any = "student_dialogue",
    state_status: Any = "in_progress",
    session_status: Any = "in_progress",
    code_review_status: Any = "pending",
    min_coverage: Any = _DEFAULT_MIN_COVERAGE,
    engagement_summary: Any = None,
) -> dict[str, Any]:
    """Build the safe, finite UserGoal contract exposed to the browser.

    ``coverage_summary`` is intentionally treated as untrusted input.  The
    helper only copies the fields needed for the progress display and never
    returns evidence, prompts, artifacts, or model internals.
    """

    concepts = _unique_strings(key_concepts)
    summary = coverage_summary if isinstance(coverage_summary, Mapping) else {}
    entries = [
        item
        for item in (_safe_coverage_item(value) for value in summary.get("concept_coverage", []))
        if item is not None
    ]
    if not concepts:
        concepts = _unique_strings(item["concept"] for item in entries)

    total_concepts = len(concepts)
    covered_concepts = sum(item["status"] == _COVERED_STATUS for item in entries)
    try:
        score = float(summary.get("coverage_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = min(1.0, max(0.0, score))
    try:
        threshold = float(min_coverage)
    except (TypeError, ValueError):
        threshold = _DEFAULT_MIN_COVERAGE
    threshold = min(1.0, max(0.0, threshold))

    ready_for_code = summary.get("ready_for_code") is True
    phase_text = str(phase or "student_dialogue").strip()
    state_status_text = str(state_status or "in_progress").strip()
    session_status_text = str(session_status or "in_progress").strip()
    code_status_text = str(code_review_status or "pending").strip()
    engagement = engagement_summary if isinstance(engagement_summary, Mapping) else {}
    effective_question_count = _safe_non_negative_int(
        engagement.get("effective_question_count")
    )
    effective_question_target = max(
        1,
        _safe_non_negative_int(engagement.get("effective_question_target"), 4),
    )
    active_message_count = _safe_non_negative_int(engagement.get("active_message_count"))
    active_seconds = _safe_non_negative_int(engagement.get("active_seconds"))
    active_target_seconds = max(
        1,
        _safe_non_negative_int(engagement.get("active_target_seconds"), 600),
    )
    raw_completion_reasons = engagement.get("completion_reasons", [])
    if not isinstance(raw_completion_reasons, (list, tuple, set, frozenset)):
        raw_completion_reasons = []
    completion_reasons = {
        str(value).strip()
        for value in raw_completion_reasons
        if isinstance(value, str) and value.strip()
    }
    coverage_done = covered_concepts >= 3
    questions_done = effective_question_count >= effective_question_target
    active_done = (
        active_message_count >= 3
        and active_seconds >= active_target_seconds
    )
    engagement_progress = max(
        round(min(1.0, effective_question_count / effective_question_target) * 100),
        round(min(1.0, active_seconds / active_target_seconds) * 100),
        round(min(1.0, covered_concepts / 3) * 100),
    )
    completed = (
        session_status_text == "completed"
        or state_status_text == "complete"
        or code_status_text == "complete"
    )
    code_review_started = phase_text == "code_review" or code_status_text in _CODE_REVIEW_STATUSES

    if completed:
        progress_percent = 100
        current_milestone = "complete"
        next_action = "本阶段目标已完成，可以查看并回顾本次学习记录。"
        goal_status = "complete"
    elif code_review_started:
        progress_percent = max(90, min(99, engagement_progress))
        current_milestone = "repair"
        next_action = "请修复右侧这份待检查代码，然后提交验证。"
        goal_status = "in_progress"
    elif ready_for_code:
        progress_percent = max(80, min(99, engagement_progress))
        current_milestone = "buggy_code"
        next_action = "关键点已完成多角度检查，下一步生成一份错误代码来练习修复。"
        goal_status = "ready_for_code"
    else:
        progress_percent = min(99, max(round(score * 80), engagement_progress))
        current_milestone = "understanding"
        pending = summary.get("pending_probe")
        if isinstance(pending, Mapping) and str(pending.get("concept") or "").strip():
            concept = str(pending.get("concept")).strip()
            dimension = _DIMENSION_LABELS.get(
                str(pending.get("dimension") or "").strip(),
                str(pending.get("dimension") or "下一角度").strip(),
            )
            next_action = f"请回答小明关于“{concept}”的{dimension}问题。"
        elif isinstance(summary.get("student_probe_intent"), Mapping):
            intent = summary["student_probe_intent"]
            concept = str(intent.get("concept") or "").strip()
            dimension = _DIMENSION_LABELS.get(
                str(intent.get("dimension") or "").strip(),
                str(intent.get("dimension") or "下一角度").strip(),
            )
            next_action = (
                f"请先回应当前问题；下一轮小明会从“{concept}”的{dimension}角度检查。"
                if concept
                else "请先回应当前问题，下一轮小明会从新的角度检查。"
            )
        elif summary.get("unresolved_concepts"):
            concept = str(summary["unresolved_concepts"][0]).strip()
            next_action = f"请继续用自己的话说明“{concept}”，小明会换一个角度检查。"
        elif concepts:
            next_action = "先用自己的话说明一个关键知识点，系统会按检查点推进。"
        else:
            next_action = "等待学习数据准备好后开始关键点检查。"
        goal_status = "in_progress"

    legacy_completion = completed and not completion_reasons
    coverage_step_done = coverage_done or legacy_completion
    question_step_done = questions_done or legacy_completion
    active_step_done = active_done or legacy_completion
    completion_detail = _completion_detail(completion_reasons)
    if completed and not completion_detail:
        completion_detail = "已通过阶段三服务端校验，学习任务完成"
    progress_detail = completion_detail or (
        f"关键点 {min(covered_concepts, 3)}/3 · "
        f"有效提问 {min(effective_question_count, effective_question_target)}/{effective_question_target} · "
        f"连续活跃 {_duration_label(active_seconds)}/{_duration_label(active_target_seconds)}"
    )

    return {
        "id": "stage3-teach-and-repair",
        "title": "掌握关键思路并完成有效互动",
        "description": "覆盖3个关键点、完成4次有效提问或连续活跃对话10分钟，满足任一条件即可完成本阶段。",
        "status": goal_status,
        "progress_percent": progress_percent,
        "progress_detail": progress_detail,
        "coverage_score": round(score, 3),
        "coverage_threshold": round(threshold, 3),
        "covered_concepts": covered_concepts,
        "total_concepts": total_concepts,
        "current_milestone": current_milestone,
        "next_action": next_action,
        "steps": [
            {"id": "coverage", "label": "覆盖3个关键点（任选）", "status": "done" if coverage_step_done else "active"},
            {"id": "questions", "label": "完成4次有效提问（任选）", "status": "done" if question_step_done else "active"},
            {"id": "active_dialogue", "label": "连续活跃10分钟（任选）", "status": "done" if active_step_done else "active"},
            {"id": "complete", "label": "完成阶段三学习任务", "status": "done" if completed else "todo"},
        ],
    }


def _safe_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _duration_label(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    minutes, remainder = divmod(total, 60)
    return f"{minutes:02d}:{remainder:02d}"


def _completion_detail(reasons: set[str]) -> str:
    labels = []
    if "knowledge_coverage" in reasons:
        labels.append("已覆盖3个关键点")
    if "effective_questions" in reasons:
        labels.append("已完成4次有效提问")
    if "active_conversation" in reasons:
        labels.append("连续活跃对话已满10分钟")
    return "、".join(labels) + "，学习任务完成" if labels else ""


def _safe_coverage_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    concept = str(value.get("concept") or "").strip()
    status = str(value.get("status") or "").strip()
    if not concept or not status:
        return None
    return {"concept": concept, "status": status}


def _unique_strings(values: Any) -> list[str]:
    if isinstance(values, (str, bytes)) or values is None:
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in iterator:
        text = str(value).strip() if isinstance(value, str) else ""
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


__all__ = ["build_stage3_user_goal"]
