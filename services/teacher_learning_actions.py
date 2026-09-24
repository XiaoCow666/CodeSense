from __future__ import annotations

from datetime import datetime as dt, timedelta
from urllib.parse import quote

from models import StudentVectorIndexState, User
from services.learning_graph import build_teacher_knowledge_coverage
from services.notifications import create_notification
from services.student_vector_health import (
    INDEX_STALE_AFTER_DAYS,
    build_teacher_learning_memory_health,
)
from utils.access import can_access_class, class_student_filter, managed_classes


MAX_ACTIONS = 20


class TeacherLearningActionAccessError(PermissionError):
    """教师请求超出自己管理的班级范围。"""


def _bounded_limit(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 12
    return max(1, min(value, MAX_ACTIONS))


def _classroom_scope(teacher, class_id=None):
    classrooms = managed_classes(teacher)
    if class_id is None:
        return classrooms
    classroom = next(
        (item for item in classrooms if int(item.id) == int(class_id)),
        None,
    )
    if classroom is None or not can_access_class(classroom, teacher):
        raise TeacherLearningActionAccessError("class is outside the teacher scope")
    return [classroom]


def _graph_source_details(graph, knowledge_point):
    target = f"knowledge:{knowledge_point}"
    refs = set()
    versions = set()
    for edge in graph.get("edges", []):
        if edge.get("target") != target:
            continue
        refs.update(str(item) for item in edge.get("source_refs", []) if str(item).strip())
        versions.update(
            str(item)
            for item in edge.get("source_versions") or [edge.get("source_version")]
            if str(item).strip()
        )
    return sorted(refs), sorted(versions)


def build_teacher_learning_actions(
    teacher,
    *,
    class_id=None,
    limit=12,
    now=None,
):
    """组合班级知识图谱信号与学生索引状态，返回安全的教师动作。"""

    current_time = now or dt.utcnow()
    classrooms = _classroom_scope(teacher, class_id)
    actions = []
    for classroom in classrooms:
        graph = build_teacher_knowledge_coverage(
            viewer_id=teacher.student_id,
            class_id=classroom.id,
            limit=4,
        )
        for recommendation in graph.get("recommendations", [])[:2]:
            knowledge_point = str(
                recommendation.get("knowledge_point")
                or recommendation.get("code")
                or ""
            ).strip()
            if not knowledge_point:
                continue
            source_refs, source_versions = _graph_source_details(
                graph,
                knowledge_point,
            )
            label = recommendation.get("label") or knowledge_point
            actions.append(
                {
                    "kind": "knowledge_practice",
                    "class_id": classroom.id,
                    "class_name": classroom.name,
                    "title": f"{classroom.name}：安排{label}练习",
                    "summary": recommendation.get(
                        "reason",
                        "班级聚合掌握度需要通过练习继续确认。",
                    ),
                    "href": (
                        f"/teacher/knowledge-focus/{quote(knowledge_point, safe='')}"
                        f"?class_id={classroom.id}"
                    ),
                    "method": "GET",
                    "knowledge_point": knowledge_point,
                    "knowledge_label": label,
                    "source_refs": source_refs,
                    "source_versions": source_versions,
                    "scope": "class_aggregate",
                }
            )

        health = build_teacher_learning_memory_health(
            teacher,
            class_id=classroom.id,
            now=current_time,
        )
        needs_refresh_count = sum(
            int(health.get(key, 0) or 0)
            for key in ("failed_count", "stale_count", "not_built_count")
        )
        if needs_refresh_count:
            actions.append(
                {
                    "kind": "learning_memory_refresh",
                    "class_id": classroom.id,
                    "class_name": classroom.name,
                    "title": f"{classroom.name}：提醒学生更新学习记忆",
                    "summary": (
                        f"有 {needs_refresh_count} 人的个人学习记录索引需要更新；"
                        "更新只读取本人记录。"
                    ),
                    "action_url": (
                        f"/teacher/classes/{classroom.id}/"
                        "learning-memory-reminder"
                    ),
                    "method": "POST",
                    "student_count": health.get("student_count", 0),
                    "needs_refresh_count": needs_refresh_count,
                    "previous_revision_count": health.get(
                        "previous_revision_count",
                        0,
                    ),
                    "scope": "class_aggregate",
                }
            )

    return {
        "schema_version": 1,
        "scope": "teacher_class" if class_id is not None else "teacher_managed_classes",
        "privacy": "class_aggregate",
        "class_count": len(classrooms),
        "action_count": len(actions),
        "actions": actions[:_bounded_limit(limit)],
        "generated_at": current_time.isoformat(),
    }


def _student_needs_refresh(state, *, now):
    if state is None:
        return True
    if state.status in {"not_built", "failed", "stale"}:
        return True
    return bool(
        state.status == "ready"
        and state.last_built_at is not None
        and state.last_built_at <= now - timedelta(days=INDEX_STALE_AFTER_DAYS)
    )


def send_learning_memory_refresh_reminders(
    teacher,
    class_id,
    *,
    now=None,
    url="/#student-learning-memory-title",
):
    """向需要更新的班级学生发送幂等的站内提醒。"""

    current_time = now or dt.utcnow()
    classroom = _classroom_scope(teacher, class_id)[0]
    students = (
        User.query.filter(
            class_student_filter(classroom),
            User.usertype == "学生",
        )
        .order_by(User.student_id.asc())
        .all()
    )
    student_ids = [student.student_id for student in students]
    states = (
        StudentVectorIndexState.query.filter(
            StudentVectorIndexState.student_id.in_(student_ids)
        ).all()
        if student_ids
        else []
    )
    state_by_student = {state.student_id: state for state in states}
    targets = [
        student
        for student in students
        if _student_needs_refresh(
            state_by_student.get(student.student_id),
            now=current_time,
        )
    ]
    key_prefix = (
        f"teacher-learning-memory:{classroom.id}:"
        f"{current_time.date().isoformat()}"
    )
    for student in targets:
        create_notification(
            student.student_id,
            kind="learning_memory_refresh",
            title="教师提醒：更新学习记忆",
            message=(
                "请更新自己的学习记忆，帮助 AI 辅导使用最新的反思线索。"
                "更新只读取本人提交反馈和知识点记录，不会改变作业分数。"
            ),
            url=url,
            idempotency_key=f"{key_prefix}:{student.student_id}",
        )

    return {
        "scope": "class_aggregate",
        "class_id": classroom.id,
        "student_count": len(students),
        "needs_refresh_count": len(targets),
        "notification_count": len(targets),
        "idempotency": "daily_class_reminder",
    }
