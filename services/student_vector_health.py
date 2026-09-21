from datetime import datetime as dt, timedelta

from sqlalchemy import or_

from models import StudentVectorIndexState, User
from services.student_vector_store import INDEX_STALE_AFTER_DAYS
from utils.access import class_student_filter, managed_classes


def build_teacher_learning_memory_health(teacher, *, now=None):
    """返回教师所管理班级的学生学习索引聚合状态。"""

    current_time = now or dt.utcnow()
    classrooms = managed_classes(teacher)
    if not classrooms:
        return {
            "scope": "teacher_managed_classes",
            "stale_after_days": INDEX_STALE_AFTER_DAYS,
            "student_count": 0,
            "ready_count": 0,
            "stale_count": 0,
            "failed_count": 0,
            "not_built_count": 0,
            "empty_count": 0,
            "previous_revision_count": 0,
            "usable_count": 0,
        }

    student_filter = or_(
        *(class_student_filter(classroom) for classroom in classrooms)
    )
    students = User.query.filter(
        User.usertype == "学生",
        student_filter,
    ).all()
    student_ids = [student.student_id for student in students]
    states = (
        StudentVectorIndexState.query.filter(
            StudentVectorIndexState.student_id.in_(student_ids)
        ).all()
        if student_ids
        else []
    )
    state_by_student = {state.student_id: state for state in states}
    stale_before = current_time - timedelta(days=INDEX_STALE_AFTER_DAYS)
    counts = {
        "ready_count": 0,
        "stale_count": 0,
        "failed_count": 0,
        "not_built_count": 0,
        "empty_count": 0,
        "previous_revision_count": 0,
    }

    for student_id in student_ids:
        state = state_by_student.get(student_id)
        if state is None or state.status == "not_built":
            counts["not_built_count"] += 1
            continue
        if state.status == "failed":
            if state.last_built_at is not None and state.last_built_at <= stale_before:
                counts["stale_count"] += 1
            else:
                counts["failed_count"] += 1
            if state.revision > 0 and state.source_count > 0:
                counts["previous_revision_count"] += 1
            continue
        if state.status == "empty":
            counts["empty_count"] += 1
            continue
        if state.status == "stale" or (
            state.status == "ready"
            and state.last_built_at is not None
            and state.last_built_at <= stale_before
        ):
            counts["stale_count"] += 1
            continue
        if state.status == "ready":
            counts["ready_count"] += 1
            continue
        counts["failed_count"] += 1

    return {
        "scope": "teacher_managed_classes",
        "stale_after_days": INDEX_STALE_AFTER_DAYS,
        "student_count": len(student_ids),
        **counts,
        "usable_count": counts["ready_count"] + counts["previous_revision_count"],
    }
