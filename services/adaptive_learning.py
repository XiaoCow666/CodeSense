"""Deterministic, read-only recommendations for the student home page.

The adaptive-learning foundation deliberately consumes already-authorized data
from a route instead of opening its own database session.  That keeps its
scope explicit: it neither persists a learning plan nor inspects submission
source code, feedback, prompts, or private session content.
"""

from datetime import datetime, timezone


NEEDS_PRACTICE_BELOW = 70.0
MIN_KNOWLEDGE_ATTEMPTS = 1
PASSING_SCORE = 60.0


def _value(item, name, default=None):
    """Read a named value from either a mapping or a lightweight object."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _positive_int(value):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 else None


def _non_negative_int(value, default=0):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return default


def _score(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return min(100.0, max(0.0, result))


def _display_score(value):
    normalized = _score(value)
    if normalized is None:
        return None
    return f"{normalized:g}"


def _assignment_id(assignment):
    return _positive_int(_value(assignment, "id"))


def _assignment_title(assignment):
    title = str(_value(assignment, "title", "") or "").strip()
    return title or "当前作业"


def _assignment_due_sort_key(assignment):
    due_date = _value(assignment, "due_date")
    if isinstance(due_date, datetime):
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=timezone.utc)
        return due_date.timestamp()
    return float("inf")


def _assignment_knowledge_weight(assignment, knowledge_key):
    """Return the strongest matching tag weight without exposing tag metadata."""
    weights = []
    for item in _value(assignment, "knowledge_points", ()) or ():
        if str(_value(item, "knowledge_point", "") or "").strip() != knowledge_key:
            continue
        try:
            weights.append(float(_value(item, "weight", 1.0) or 1.0))
        except (TypeError, ValueError, OverflowError):
            weights.append(1.0)
    return max(weights) if weights else None


def _base_plan(status, source, headline, summary, action, evidence):
    """Build the strictly content-free contract consumed by the template."""
    return {
        "schema_version": 1,
        "status": status,
        "source": source,
        "headline": headline,
        "summary": summary,
        "action": action,
        "evidence": evidence,
        "boundary": "建议仅使用当前账号已记录的学习、作业和知识点数据，不会保存为学习计划，也不替代教师判断。",
    }


def _resume_plan(recent_learning_sessions, active_assignment_ids):
    for item in recent_learning_sessions or ():
        assignment = _value(item, "assignment")
        assignment_id = _assignment_id(assignment)
        lifecycle = _value(item, "lifecycle", {}) or {}
        if assignment_id not in active_assignment_ids or not bool(_value(lifecycle, "is_resumable")):
            continue

        stage_label = str(_value(lifecycle, "stage_label", "当前阶段") or "当前阶段")
        next_action = str(_value(lifecycle, "next_action", "继续当前学习") or "继续当前学习")
        return _base_plan(
            "ready",
            "resumable_session",
            "先完成正在进行的学习",
            f"《{_assignment_title(assignment)}》仍可继续，先完成当前阶段能让后续建议建立在完整学习记录上。",
            {
                "kind": "resume_learning",
                "assignment_id": assignment_id,
                "label": "继续当前阶段",
            },
            [{
                "kind": "learning_session",
                "label": "可继续的学习会话",
                "detail": f"{stage_label}：{next_action}",
            }],
        )
    return None


def _knowledge_plan(active_assignments, knowledge_profile_rows):
    weak_rows = []
    for row in knowledge_profile_rows or ():
        key = str(_value(row, "key", "") or "").strip()
        score = _score(_value(row, "score"))
        attempts = _non_negative_int(_value(row, "total_attempts"))
        if not key or score is None or attempts < MIN_KNOWLEDGE_ATTEMPTS:
            continue
        if score < NEEDS_PRACTICE_BELOW:
            weak_rows.append((score, -attempts, key, row))

    for score, negative_attempts, key, row in sorted(
        weak_rows,
        key=lambda item: item[:3],
    ):
        candidates = []
        for assignment in active_assignments or ():
            assignment_id = _assignment_id(assignment)
            if assignment_id is None:
                continue
            weight = _assignment_knowledge_weight(assignment, key)
            if weight is None:
                continue
            candidates.append((-weight, _assignment_due_sort_key(assignment), assignment_id, assignment))
        if not candidates:
            continue

        _, _, assignment_id, assignment = min(candidates)
        attempts = -negative_attempts
        name = str(_value(row, "name", key) or key)
        return _base_plan(
            "ready",
            "knowledge_gap",
            f"优先巩固{name}",
            f"系统为你匹配了当前可提交、且标注为“{name}”的作业；完成后可用新的练习记录重新观察掌握情况。",
            {
                "kind": "practice_knowledge_point",
                "assignment_id": assignment_id,
                "label": "开始针对练习",
            },
            [
                {
                    "kind": "knowledge_point",
                    "label": "已有练习记录",
                    "detail": f"{name} 当前掌握度 {score:g} 分，已有 {attempts} 次练习记录。",
                },
                {
                    "kind": "assignment_match",
                    "label": "匹配当前作业",
                    "detail": _assignment_title(assignment),
                },
            ],
        )
    return None


def _needs_retry(submission):
    status = str(_value(submission, "status", "") or "").strip().lower()
    sandbox_status = str(_value(submission, "sandbox_status", "") or "").strip().lower()
    score = _score(_value(submission, "score"))
    return status == "failed" or sandbox_status in {"failed", "error", "partial"} or (
        score is not None and score < PASSING_SCORE
    )


def _retry_plan(recent_submissions, active_assignments_by_id):
    for submission in recent_submissions or ():
        assignment_id = _positive_int(_value(submission, "assignment_id"))
        assignment = active_assignments_by_id.get(assignment_id)
        if assignment is None or not _needs_retry(submission):
            continue

        score = _display_score(_value(submission, "score"))
        detail = "最近一次有效评测尚未达到通过目标。"
        if score is not None:
            detail = f"最近一次有效评测得分 {score} 分，尚未达到通过目标。"
        return _base_plan(
            "ready",
            "retry_submission",
            "回到最近一次尚未达标的作业",
            f"先复练《{_assignment_title(assignment)}》并重新提交，再根据新的评测结果安排下一步。",
            {
                "kind": "retry_submission",
                "assignment_id": assignment_id,
                "label": "复练并重新提交",
            },
            [{
                "kind": "submission_result",
                "label": "最近一次评测",
                "detail": detail,
            }],
        )
    return None


def _unstarted_assignment_plan(active_assignments, submitted_assignment_ids):
    candidates = [
        assignment for assignment in active_assignments or ()
        if _assignment_id(assignment) not in submitted_assignment_ids
    ]
    if not candidates:
        return None
    assignment = min(candidates, key=lambda item: (_assignment_due_sort_key(item), _assignment_id(item)))
    assignment_id = _assignment_id(assignment)
    return _base_plan(
        "ready",
        "unstarted_assignment",
        "从一份当前作业开始",
        f"《{_assignment_title(assignment)}》还没有提交记录；完成一次练习后，系统才能基于实际结果提供更具体的建议。",
        {
            "kind": "start_assignment",
            "assignment_id": assignment_id,
            "label": "开始编码",
        },
        [{
            "kind": "assignment_status",
            "label": "当前可提交作业",
            "detail": "尚无提交记录。",
        }],
    )


def build_adaptive_learning_plan(
    *,
    active_assignments,
    recent_learning_sessions,
    knowledge_profile_rows,
    recent_submissions,
    submitted_assignment_ids,
):
    """Return one deterministic, content-free next-step recommendation.

    Inputs must already be scoped to the current student and their currently
    accessible assignments.  The function makes no database, network, AI, or
    state-changing calls, which makes the precedence order fully testable.
    """
    active_assignments = list(active_assignments or ())
    active_assignments_by_id = {
        assignment_id: assignment
        for assignment in active_assignments
        if (assignment_id := _assignment_id(assignment)) is not None
    }
    active_assignment_ids = set(active_assignments_by_id)
    submitted_assignment_ids = {
        assignment_id
        for value in submitted_assignment_ids or ()
        if (assignment_id := _positive_int(value)) is not None
    }

    return (
        _resume_plan(recent_learning_sessions, active_assignment_ids)
        or _knowledge_plan(active_assignments, knowledge_profile_rows)
        or _retry_plan(recent_submissions, active_assignments_by_id)
        or _unstarted_assignment_plan(active_assignments, submitted_assignment_ids)
        or _base_plan(
            "starting_point",
            "no_current_evidence",
            "从作业列表选择下一步",
            "当前没有可用于排序的有效作业或学习记录；打开作业并完成一次练习后，系统会基于新的记录给出建议。",
            {
                "kind": "review_assignments",
                "assignment_id": None,
                "label": "查看作业列表",
            },
            [{
                "kind": "data_boundary",
                "label": "当前可用证据不足",
                "detail": "不会根据缺失记录推断你的真实掌握情况。",
            }],
        )
    )
