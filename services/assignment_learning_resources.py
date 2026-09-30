"""教师作业学习资料的来源、版本和撤回。"""

import hashlib
from datetime import datetime as dt

from models import (
    AssignmentKnowledgePoint,
    AssignmentLearningResource,
    AssignmentLearningResourceRevision,
    db,
)
from services.knowledge_reliability import KnowledgePrivacyFilter
from utils.access import can_manage_assignment


MAX_TITLE_LENGTH = 120
MAX_CONTENT_LENGTH = 2400
MAX_RESOURCES_PER_ASSIGNMENT = 24


def _validate_text(value, limit):
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        raise ValueError("学习资料的标题或正文长度无效")
    if KnowledgePrivacyFilter.redact(text) != text:
        raise ValueError("学习资料包含联系方式或凭据，请移除后保存")
    return text


def _validate_knowledge_point(assignment_id, knowledge_point):
    code = str(knowledge_point or "").strip()
    if not AssignmentKnowledgePoint.query.filter_by(
        assignment_id=assignment_id,
        knowledge_point=code,
    ).first():
        raise ValueError("请先给作业关联这个知识点")
    return code


def _version(resource):
    payload = "|".join(
        str(value) for value in (
            resource.id,
            resource.assignment_id,
            resource.revision,
            resource.knowledge_point,
            resource.title,
            resource.content,
            resource.status,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_revision(resource, actor, action):
    resource.source_version = _version(resource)
    db.session.add(AssignmentLearningResourceRevision(
        resource_id=resource.id,
        revision=resource.revision,
        title=resource.title,
        content=resource.content,
        knowledge_point=resource.knowledge_point,
        source_version=resource.source_version,
        action=action,
        editor_id=actor.student_id,
    ))


def list_assignment_learning_resources(assignment_id, *, include_withdrawn=False):
    query = AssignmentLearningResource.query.filter_by(assignment_id=assignment_id)
    if not include_withdrawn:
        current_codes = {
            row.knowledge_point
            for row in AssignmentKnowledgePoint.query.filter_by(
                assignment_id=assignment_id,
            ).all()
        }
        if not current_codes:
            return []
        query = query.filter(
            AssignmentLearningResource.status == "active",
            AssignmentLearningResource.knowledge_point.in_(current_codes),
        )
    return query.order_by(AssignmentLearningResource.id.asc()).all()


def list_assignment_resource_revisions(assignment_id, resource_ids):
    if not resource_ids:
        return {}
    rows = AssignmentLearningResourceRevision.query.join(
        AssignmentLearningResource,
        AssignmentLearningResourceRevision.resource_id == AssignmentLearningResource.id,
    ).filter(
        AssignmentLearningResource.assignment_id == assignment_id,
        AssignmentLearningResource.id.in_(resource_ids),
    ).order_by(
        AssignmentLearningResourceRevision.resource_id.asc(),
        AssignmentLearningResourceRevision.revision.desc(),
    ).limit(240).all()
    grouped = {}
    for row in rows:
        history = grouped.setdefault(row.resource_id, [])
        if len(history) < 10:
            history.append(row)
    return grouped


def save_assignment_learning_resource(
    assignment, actor, *, title, content, knowledge_point, resource_id=None,
    expected_revision=None,
):
    if not can_manage_assignment(assignment, actor):
        raise PermissionError("没有权限修改这份作业的学习资料")
    title = _validate_text(title, MAX_TITLE_LENGTH)
    content = _validate_text(content, MAX_CONTENT_LENGTH)
    knowledge_point = _validate_knowledge_point(assignment.id, knowledge_point)
    now = dt.utcnow()
    if resource_id is None:
        if AssignmentLearningResource.query.filter_by(
            assignment_id=assignment.id,
            status="active",
        ).count() >= MAX_RESOURCES_PER_ASSIGNMENT:
            raise ValueError("这份作业的学习资料已达到数量上限")
        resource = AssignmentLearningResource(
            assignment_id=assignment.id,
            knowledge_point=knowledge_point,
            title=title,
            content=content,
            creator_id=actor.student_id,
            revision=1,
            source_version="",
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.session.add(resource)
        db.session.flush()
        action = "created"
    else:
        resource = AssignmentLearningResource.query.filter_by(
            id=resource_id,
            assignment_id=assignment.id,
            status="active",
        ).first()
        if resource is None:
            raise ValueError("学习资料不存在或已经撤回")
        if expected_revision is not None and resource.revision != expected_revision:
            raise ValueError("学习资料已经更新，请刷新页面后重新编辑")
        if (resource.title, resource.content, resource.knowledge_point) == (
            title, content, knowledge_point,
        ):
            return resource
        resource.title = title
        resource.content = content
        resource.knowledge_point = knowledge_point
        resource.revision += 1
        resource.updated_at = now
        action = "updated"
    _record_revision(resource, actor, action)
    db.session.commit()
    return resource


def withdraw_assignment_learning_resource(
    assignment, actor, resource_id, *, expected_revision=None,
):
    if not can_manage_assignment(assignment, actor):
        raise PermissionError("没有权限撤回这份作业的学习资料")
    resource = AssignmentLearningResource.query.filter_by(
        id=resource_id,
        assignment_id=assignment.id,
        status="active",
    ).first()
    if resource is None:
        raise ValueError("学习资料不存在或已经撤回")
    if expected_revision is not None and resource.revision != expected_revision:
        raise ValueError("学习资料已经更新，请刷新页面后重新撤回")
    now = dt.utcnow()
    resource.status = "withdrawn"
    resource.revision += 1
    resource.withdrawn_at = now
    resource.updated_at = now
    _record_revision(resource, actor, "withdrawn")
    db.session.commit()
    return resource


def withdraw_assignment_resources_for_codes(assignment, actor, removed_codes):
    if not can_manage_assignment(assignment, actor):
        raise PermissionError("没有权限撤回这份作业的学习资料")
    if not removed_codes:
        return 0
    rows = AssignmentLearningResource.query.filter(
        AssignmentLearningResource.assignment_id == assignment.id,
        AssignmentLearningResource.knowledge_point.in_(removed_codes),
        AssignmentLearningResource.status == "active",
    ).all()
    now = dt.utcnow()
    for resource in rows:
        resource.status = "withdrawn"
        resource.revision += 1
        resource.withdrawn_at = now
        resource.updated_at = now
        _record_revision(resource, actor, "withdrawn")
    return len(rows)
