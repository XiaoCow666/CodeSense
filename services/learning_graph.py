"""Small, permission-aware learning graph projections.

This module deliberately builds a graph from data that already exists in
CodeSense.  It is a projection layer, not a new storage engine: assignments
provide explicit ``covers`` edges, a student's own knowledge scores provide
private ``mastery`` edges, and concepts that occur in one assignment are
connected with an explicitly inferred ``co_occurs`` edge.

The returned values are plain dictionaries so they can be used by HTML views,
JSON endpoints, and later vector-retrieval jobs without leaking SQLAlchemy
objects or private identifiers into a shared teacher projection.
"""

from __future__ import annotations

import hashlib
from itertools import combinations

from models import (
    Assignment,
    AssignmentKnowledgePoint,
    Class,
    KnowledgePointScore,
    User,
)
from utils.access import (
    assignment_target_class_filter,
    can_access_assignment,
    can_access_class,
    class_student_filter,
    can_manage_assignment,
    managed_classes,
)


DEFAULT_LIMIT = 8
MAX_LIMIT = 50
LOW_MASTERY_THRESHOLD = 60.0
MIN_TEACHER_SAMPLE = 2


class LearningGraphAccessError(PermissionError):
    """Raised when a graph projection would cross a role or class boundary."""


def _bounded_limit(limit):
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _knowledge_label(code):
    code = str(code or "").strip()
    return KnowledgePointScore.KNOWLEDGE_POINTS.get(code, code)


def _knowledge_id(code):
    return f"knowledge:{code}"


def _assignment_id(assignment_id):
    return f"assignment:{assignment_id}"


def _source_version(*parts):
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_graph(scope, **meta):
    return {
        "nodes": [],
        "edges": [],
        "recommendations": [],
        "meta": {"scope": scope, **meta},
    }


def _normalise_score(score):
    try:
        return round(max(0.0, min(float(score), 100.0)), 1)
    except (TypeError, ValueError):
        return 0.0


def _assignment_knowledge_rows(assignment_ids):
    if not assignment_ids:
        return []
    return (
        AssignmentKnowledgePoint.query.filter(
            AssignmentKnowledgePoint.assignment_id.in_(assignment_ids)
        )
        .order_by(
            AssignmentKnowledgePoint.assignment_id.asc(),
            AssignmentKnowledgePoint.id.asc(),
        )
        .all()
    )


def _group_assignment_knowledge(rows):
    grouped = {}
    for row in rows:
        code = str(row.knowledge_point or "").strip()
        if not code:
            continue
        grouped.setdefault(row.assignment_id, {})
        current = grouped[row.assignment_id].get(code)
        weight = float(row.weight or 0.0)
        if current is None or weight > current["weight"]:
            grouped[row.assignment_id][code] = {
                "code": code,
                "weight": round(weight, 2),
                "difficulty": round(float(row.difficulty or 1.0), 2),
                "auto_detected": bool(row.auto_detected),
                "source_refs": [f"assignment-knowledge:{row.id}"],
                "source_versions": [
                    _source_version(
                        "assignment-knowledge",
                        row.id,
                        row.assignment_id,
                        row.knowledge_point,
                        row.weight,
                        row.difficulty,
                        row.auto_detected,
                    )
                ],
            }
    return grouped


def _co_occurrence_edges(grouped, *, scope):
    counts = {}
    pair_sources = {}
    for knowledge in grouped.values():
        codes = sorted(knowledge)
        for left, right in combinations(codes, 2):
            key = (left, right)
            counts[key] = counts.get(key, 0) + 1
            pair_sources.setdefault(key, []).append(
                (
                    knowledge[left]["source_refs"],
                    knowledge[left]["source_versions"],
                    knowledge[right]["source_refs"],
                    knowledge[right]["source_versions"],
                )
            )

    edges = []
    for (left, right), count in sorted(counts.items()):
        source_refs = set()
        source_versions = set()
        for refs_left, versions_left, refs_right, versions_right in pair_sources[(left, right)]:
            source_refs.update(refs_left)
            source_refs.update(refs_right)
            source_versions.update(versions_left)
            source_versions.update(versions_right)
        edges.append(
            {
                "source": _knowledge_id(left),
                "target": _knowledge_id(right),
                "relation_type": "co_occurs",
                "provenance": "same_assignment",
                "scope": scope,
                "is_inferred": True,
                "weight": count,
                "source_refs": sorted(source_refs),
                "source_version": _source_version(
                    "co_occurs",
                    scope,
                    left,
                    right,
                    *sorted(source_versions),
                ),
            }
        )
    return edges


def _student_assignments(student, assignment_id=None, limit=DEFAULT_LIMIT):
    if assignment_id is not None:
        assignment = Assignment.query.get(assignment_id)
        if assignment is None or not can_access_assignment(assignment, student):
            raise LearningGraphAccessError("assignment is outside the student's scope")
        return [assignment]

    visible = []
    assignments = Assignment.query.order_by(Assignment.created_time.desc()).all()
    for assignment in assignments:
        if can_access_assignment(assignment, student):
            visible.append(assignment)
            if len(visible) >= limit:
                break
    return visible


def build_student_learning_graph(*, student_id, assignment_id=None, limit=DEFAULT_LIMIT):
    """Build the student's private, assignment-scoped learning graph.

    Only assignments visible to ``student_id`` and that student's own
    ``KnowledgePointScore`` rows are read.  The service returns a stable empty
    projection when the student has no visible, tagged assignment yet.
    """

    student = User.query.filter_by(student_id=student_id).first()
    if student is None or getattr(student, "usertype", None) != "学生":
        raise LearningGraphAccessError("student is not available")

    limit = _bounded_limit(limit)
    assignments = _student_assignments(student, assignment_id, limit)
    if not assignments:
        return _empty_graph(
            "student",
            sample_size=0,
            assignment_count=0,
            knowledge_point_count=0,
            virtual_nodes=["student:mastery"],
        )

    assignment_ids = [assignment.id for assignment in assignments]
    grouped = _group_assignment_knowledge(
        _assignment_knowledge_rows(assignment_ids)
    )
    codes = sorted({code for knowledge in grouped.values() for code in knowledge})
    scores = (
        KnowledgePointScore.query.filter(
            KnowledgePointScore.student_id == student.student_id,
            KnowledgePointScore.knowledge_point.in_(codes),
        ).all()
        if codes
        else []
    )
    score_by_code = {str(score.knowledge_point).strip(): score for score in scores}

    nodes = []
    for assignment in assignments:
        nodes.append(
            {
                "id": _assignment_id(assignment.id),
                "type": "assignment",
                "assignment_id": assignment.id,
                "label": assignment.title,
                "title": assignment.title,
            }
        )

    for code in codes:
        score = score_by_code.get(code)
        node = {
            "id": _knowledge_id(code),
            "type": "knowledge_point",
            "code": code,
            "label": _knowledge_label(code),
            "mastery": _normalise_score(score.score) if score else None,
            "attempts": int(score.total_attempts or 0) if score else 0,
        }
        nodes.append(node)

    edges = []
    recommendations = []
    for assignment in assignments:
        assignment_knowledge = grouped.get(assignment.id, {})
        for code, detail in sorted(assignment_knowledge.items()):
            edges.append(
                {
                    "source": _assignment_id(assignment.id),
                    "target": _knowledge_id(code),
                    "relation_type": "covers",
                    "provenance": "assignment_knowledge_point",
                    "scope": "student_assignments",
                    "is_inferred": False,
                    "weight": detail["weight"],
                    "difficulty": detail["difficulty"],
                    "source_refs": detail["source_refs"],
                    "source_version": detail["source_versions"][0],
                }
            )
            score = score_by_code.get(code)
            mastery = _normalise_score(score.score) if score else None
            if mastery is None or mastery < LOW_MASTERY_THRESHOLD:
                recommendations.append(
                    {
                        "assignment_id": assignment.id,
                        "knowledge_point": code,
                        "label": _knowledge_label(code),
                        "reason": "尚未形成稳定掌握度" if mastery is None else "最近掌握度偏低",
                        "action": "practice_assignment",
                    }
                )

    edges.extend(_co_occurrence_edges(grouped, scope="student_assignments"))
    for code in codes:
        if code in score_by_code:
            edges.append(
                {
                    "source": "student:mastery",
                    "target": _knowledge_id(code),
                    "relation_type": "mastery",
                    "provenance": "knowledge_point_score",
                    "scope": "student_private",
                    "is_inferred": False,
                    "weight": _normalise_score(score_by_code[code].score),
                    "source_refs": [
                        f"knowledge-score:{score_by_code[code].id}"
                    ],
                    "source_version": _source_version(
                        "knowledge-score",
                        score_by_code[code].id,
                        score_by_code[code].student_id,
                        score_by_code[code].knowledge_point,
                        score_by_code[code].score,
                        score_by_code[code].total_attempts,
                        score_by_code[code].correct_attempts,
                        score_by_code[code].average_difficulty,
                        score_by_code[code].last_updated,
                    ),
                }
            )

    return {
        "nodes": nodes,
        "edges": edges,
        "recommendations": recommendations,
        "meta": {
            "scope": "student",
            "sample_size": len(assignments),
            "assignment_count": len(assignments),
            "knowledge_point_count": len(codes),
            "virtual_nodes": ["student:mastery"],
            "privacy": "student_private",
        },
    }


def project_student_learning_graph(graph):
    """把学生图谱转换为带来源版本的安全响应。"""

    if not isinstance(graph, dict):
        return {
            "status": "no_result",
            "scope": "student_private",
            "nodes": [],
            "edges": [],
            "recommendations": [],
            "meta": {"scope": "student_private", "privacy": "student_private"},
        }

    if (graph.get("meta") or {}).get("scope") != "student":
        raise LearningGraphAccessError("student graph scope is unavailable")

    raw_nodes = list(graph.get("nodes") or [])
    raw_edges = list(graph.get("edges") or [])
    node_ids = {str(node.get("id")) for node in raw_nodes if node.get("id")}
    node_sources = {}
    node_versions = {}
    for node_id in node_ids:
        node_sources[node_id] = set()
        node_versions[node_id] = set()

    for edge in raw_edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        refs = {
            str(value)
            for value in edge.get("source_refs", [])
            if str(value).strip()
        }
        versions = {
            str(value)
            for value in (
                edge.get("source_versions")
                or [edge.get("source_version")]
            )
            if str(value).strip()
        }
        for node_id in (source, target):
            if node_id in node_sources:
                node_sources[node_id].update(refs)
                node_versions[node_id].update(versions)

    nodes = []
    for raw_node in raw_nodes:
        node_id = str(raw_node.get("id") or "")
        versions = sorted(node_versions.get(node_id, set()))
        if not node_id or not versions:
            continue
        node = {
            "id": node_id,
            "type": raw_node.get("type"),
            "label": raw_node.get("label"),
            "scope": "student_private",
            "source_refs": sorted(node_sources.get(node_id, set())),
            "source_versions": versions,
        }
        for field in ("assignment_id", "title", "code", "mastery", "attempts"):
            if field in raw_node:
                node[field] = raw_node[field]
        nodes.append(node)

    kept_ids = {node["id"] for node in nodes}
    edges = []
    for raw_edge in raw_edges:
        source = str(raw_edge.get("source") or "")
        target = str(raw_edge.get("target") or "")
        if source not in kept_ids or target not in kept_ids:
            continue
        versions = sorted(
            {
                str(value)
                for value in (
                    raw_edge.get("source_versions")
                    or [raw_edge.get("source_version")]
                )
                if str(value).strip()
            }
        )
        if not versions:
            continue
        edge = {
            "source": source,
            "target": target,
            "relation_type": raw_edge.get("relation_type"),
            "provenance": raw_edge.get("provenance"),
            "scope": "student_private",
            "is_inferred": bool(raw_edge.get("is_inferred")),
            "source_refs": sorted(
                {
                    str(value)
                    for value in raw_edge.get("source_refs", [])
                    if str(value).strip()
                }
            ),
            "source_versions": versions,
        }
        for field in ("weight", "difficulty"):
            if field in raw_edge:
                edge[field] = raw_edge[field]
        edges.append(edge)

    knowledge_node_count = sum(
        node.get("type") == "knowledge_point" for node in nodes
    )
    status = "grounded" if knowledge_node_count and edges else "no_result"
    if status == "no_result":
        nodes = []
        edges = []

    recommendations = []
    for recommendation in graph.get("recommendations") or []:
        item = {
            "assignment_id": recommendation.get("assignment_id"),
            "knowledge_point": recommendation.get("knowledge_point"),
            "label": recommendation.get("label"),
            "reason": recommendation.get("reason"),
            "action": recommendation.get("action"),
            "scope": "student_private",
        }
        recommendations.append(item)

    source_versions = sorted(
        {
            version
            for node in nodes
            for version in node.get("source_versions", [])
        }
    )
    return {
        "status": status,
        "scope": "student_private",
        "nodes": nodes,
        "edges": edges,
        "recommendations": recommendations if status == "grounded" else [],
        "meta": {
            "scope": "student_private",
            "privacy": "student_private",
            "assignment_count": sum(
                node.get("type") == "assignment" for node in nodes
            ),
            "knowledge_point_count": knowledge_node_count
            if status == "grounded"
            else 0,
            "source_versions": source_versions,
        },
    }


def build_student_learning_graph_context(graph):
    """把当前学生的作业图谱投影为有界 AI 上下文。"""

    if not graph or (graph.get("meta") or {}).get("scope") != "student":
        return "当前作业没有可用知识点图谱。"

    nodes = [
        node
        for node in graph.get("nodes", [])
        if node.get("type") == "knowledge_point"
    ]
    if not nodes:
        return "当前作业没有可用知识点图谱。"

    lines = [
        "当前作业知识点（来源于作业知识点标签和本人的掌握记录，仅用于学习引导）："
    ]
    edges_by_target = {}
    for edge in graph.get("edges", []):
        edges_by_target.setdefault(edge.get("target"), []).append(edge)

    for node in nodes[:8]:
        mastery = node.get("mastery")
        if mastery is None:
            state = "尚未形成掌握度记录"
        elif mastery < LOW_MASTERY_THRESHOLD:
            state = f"当前掌握度 {mastery:.1f}/100，建议优先练习"
        else:
            state = f"当前掌握度 {mastery:.1f}/100"
        versions = sorted(
            {
                str(edge.get("source_version") or "")[:12]
                for edge in edges_by_target.get(node.get("id"), [])
                if edge.get("source_version")
            }
        )
        version_note = f"；来源版本 {versions[0]}" if versions else ""
        lines.append(f"- {node.get('label', node.get('code'))}：{state}{version_note}")

    lines.append("作用域：student_private；知识点关系只用于解释练习方向，不参与评分。")
    return "\n".join(lines)


def _teacher_classes(viewer, class_id=None):
    classes = managed_classes(viewer)
    if class_id is None:
        return classes

    classroom = Class.query.get(class_id)
    if classroom is None or not can_access_class(classroom, viewer):
        raise LearningGraphAccessError("class is outside the teacher's scope")
    return [classroom]


def _class_students(classes):
    students_by_id = {}
    for classroom in classes:
        students = User.query.filter(
            class_student_filter(classroom),
            User.usertype == "学生",
        ).all()
        for student in students:
            students_by_id[student.student_id] = student
    return students_by_id


def _teacher_assignments(classes):
    assignments_by_id = {}
    for classroom in classes:
        assignments = Assignment.query.filter(
            assignment_target_class_filter(classroom.name)
        ).all()
        for assignment in assignments:
            assignments_by_id[assignment.id] = assignment
    return sorted(
        assignments_by_id.values(),
        key=lambda assignment: (
            assignment.created_time is None,
            assignment.created_time,
            assignment.id,
        ),
        reverse=True,
    )


def build_teacher_knowledge_coverage(*, viewer_id, class_id=None, limit=DEFAULT_LIMIT):
    """Build class-level knowledge coverage without exposing student records."""

    viewer = User.query.filter_by(student_id=viewer_id).first()
    if viewer is None:
        raise LearningGraphAccessError("teacher is not available")

    classes = _teacher_classes(viewer, class_id)
    students_by_id = _class_students(classes)
    students = list(students_by_id.values())
    assignments = _teacher_assignments(classes)
    assignment_ids = [assignment.id for assignment in assignments]
    grouped = _group_assignment_knowledge(
        _assignment_knowledge_rows(assignment_ids)
    )
    codes = sorted({code for knowledge in grouped.values() for code in knowledge})
    student_ids = list(students_by_id)
    score_rows = (
        KnowledgePointScore.query.filter(
            KnowledgePointScore.student_id.in_(student_ids),
            KnowledgePointScore.knowledge_point.in_(codes),
        ).all()
        if student_ids and codes
        else []
    )

    scores_by_code = {}
    for row in score_rows:
        code = str(row.knowledge_point or "").strip()
        scores_by_code.setdefault(code, []).append(_normalise_score(row.score))

    limited_codes = sorted(
        codes,
        key=lambda code: (
            -(len(scores_by_code.get(code, []))),
            sum(scores_by_code.get(code, [])) / len(scores_by_code[code])
            if scores_by_code.get(code)
            else 101,
            code,
        ),
    )[: _bounded_limit(limit)]

    nodes = []
    recommendations = []
    for code in limited_codes:
        values = scores_by_code.get(code, [])
        average = round(sum(values) / len(values), 1) if values else None
        low_count = len([value for value in values if value < LOW_MASTERY_THRESHOLD])
        insufficient = len(values) < MIN_TEACHER_SAMPLE
        node = {
            "id": _knowledge_id(code),
            "type": "knowledge_point",
            "code": code,
            "label": _knowledge_label(code),
            "student_sample_size": len(values),
            "average_mastery": average,
            "low_mastery_count": low_count,
            "status": "insufficient_sample"
            if insufficient
            else "needs_attention"
            if average is not None and average < LOW_MASTERY_THRESHOLD
            else "covered",
        }
        nodes.append(node)
        if (
            not insufficient
            and average is not None
            and (
                average < LOW_MASTERY_THRESHOLD
                or low_count > 0
            )
        ):
            recommendations.append(
                {
                    "code": code,
                    "knowledge_point": code,
                    "label": _knowledge_label(code),
                    "reason": "班级掌握度偏低，可安排针对性练习"
                    if average < LOW_MASTERY_THRESHOLD
                    else "部分学生掌握不足，可安排分层练习",
                    "action": "review_knowledge_point",
                }
            )

    filtered_grouped = {
        assignment_id: {
            code: detail
            for code, detail in knowledge.items()
            if code in set(limited_codes)
        }
        for assignment_id, knowledge in grouped.items()
    }
    edges = _co_occurrence_edges(filtered_grouped, scope="teacher_class")
    return {
        "nodes": nodes,
        "edges": edges,
        "recommendations": recommendations,
        "meta": {
            "scope": "teacher_class",
            "class_id": class_id,
            "class_count": len(classes),
            "sample_size": len(students),
            "assignment_count": len(assignments),
            "knowledge_point_count": len(limited_codes),
            "privacy": "class_aggregate",
        },
    }


def build_teacher_knowledge_focus(
    *,
    viewer_id,
    knowledge_point,
    class_id=None,
    limit=DEFAULT_LIMIT,
):
    """返回当前教师可管理范围内的知识点练习作业。"""

    viewer = User.query.filter_by(student_id=viewer_id).first()
    if viewer is None:
        raise LearningGraphAccessError("teacher is not available")

    code = str(knowledge_point or "").strip()
    if not code:
        raise LearningGraphAccessError("knowledge point is not available")

    classes = _teacher_classes(viewer, class_id)
    class_names = {
        str(classroom.name).strip()
        for classroom in classes
        if str(classroom.name or "").strip()
    }
    assignments = _teacher_assignments(classes)
    assignments = [
        assignment
        for assignment in assignments
        if can_access_assignment(assignment, viewer)
    ]
    students_by_id = _class_students(classes)
    student_ids = list(students_by_id)
    score_rows = (
        KnowledgePointScore.query.filter(
            KnowledgePointScore.student_id.in_(student_ids),
            KnowledgePointScore.knowledge_point == code,
        ).all()
        if student_ids
        else []
    )
    mastery_values = [_normalise_score(row.score) for row in score_rows]
    average_mastery = (
        round(sum(mastery_values) / len(mastery_values), 1)
        if mastery_values
        else None
    )
    low_mastery_count = sum(
        value < LOW_MASTERY_THRESHOLD for value in mastery_values
    )
    if len(mastery_values) < MIN_TEACHER_SAMPLE:
        focus_status = "insufficient_sample"
    elif low_mastery_count or (
        average_mastery is not None and average_mastery < LOW_MASTERY_THRESHOLD
    ):
        focus_status = "needs_attention"
    else:
        focus_status = "covered"
    focus_signal = {
        "status": focus_status,
        "student_sample_size": len(mastery_values),
        "average_mastery": average_mastery,
        "low_mastery_count": low_mastery_count,
        "scope": "class_aggregate",
    }
    assignment_ids = [assignment.id for assignment in assignments]
    grouped = _group_assignment_knowledge(
        _assignment_knowledge_rows(assignment_ids)
    )

    result = []
    for assignment in assignments:
        detail = grouped.get(assignment.id, {}).get(code)
        if detail is None:
            continue
        target_classes = sorted(
            set(assignment.get_target_class_list()) & class_names
        )
        result.append(
            {
                "assignment_id": assignment.id,
                "title": assignment.title,
                "description": str(assignment.description or "").strip(),
                "difficulty_level": int(assignment.difficulty_level or 1),
                "target_classes": target_classes,
                "knowledge_point": code,
                "knowledge_label": _knowledge_label(code),
                "weight": detail["weight"],
                "difficulty": detail["difficulty"],
                "source_refs": detail["source_refs"],
                "source_version": detail["source_versions"][0],
                "can_manage": can_manage_assignment(assignment, viewer),
            }
        )
        if len(result) >= _bounded_limit(limit):
            break

    return {
        "assignments": result,
        "meta": {
            "scope": "teacher_knowledge_focus",
            "class_id": class_id,
            "class_count": len(classes),
            "knowledge_point": code,
            "knowledge_label": _knowledge_label(code),
            "assignment_count": len(result),
            "focus_signal": focus_signal,
            "privacy": "class_aggregate",
        },
    }
