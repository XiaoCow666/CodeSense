"""Write learning records on the same database bind as the current student."""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from models import (
    AIChatTurn,
    Assignment,
    AssignmentAnnotationRevision,
    AssignmentKnowledgePoint,
    AssignmentThinkingPreset,
    CodeVersion,
    LearningAttempt,
    LearningStageInterval,
    Submission,
    SubmissionEvent,
    TestCase,
    ThinkingSession,
    db,
)


GUIDED_STAGES = {1: "solution_description", 2: "block_programming", 3: "feynman"}
STAGES = frozenset((*GUIDED_STAGES.values(), "coding"))
INTERVAL_TIMEOUT = timedelta(seconds=45)
INTERVAL_END_REASONS = {"hidden", "idle", "leave", "stage_changed", "submitted"}


class LearningCaptureConflict(ValueError):
    """A stale attempt or a request identifier reused for different data."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("ID 无效")
    try:
        result = int(value)
    except ValueError:
        raise ValueError("ID 无效") from None
    if not 0 < result <= 2_147_483_647:
        raise ValueError("ID 无效")
    return result


def _request_key(value, label, *, required=False):
    if not required and value in (None, ""):
        return None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or not value.isascii()
        or not all(char.isalnum() or char in "-_.:" for char in value)
    ):
        raise ValueError(f"{label}无效")
    return value


def _insert_or_find(candidate, lookup):
    """On a unique collision, read the winning row in the current transaction."""
    _begin_sqlite_write()
    try:
        with db.session.begin_nested():
            db.session.add(candidate)
            db.session.flush()
    except IntegrityError:
        existing = lookup.with_for_update().first()
        if existing is None:
            raise
        return existing, False
    return candidate, True


def _begin_sqlite_write():
    connection = db.session.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        # Legacy sqlite3 transaction mode does not BEGIN before a SAVEPOINT.
        # Begin explicitly so releasing an insert's savepoint cannot commit the outer write.
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _case_snapshot(case):
    result = {
        key: case.get(key) for key in ("id", "input_data", "expected_output", "is_public", "order_index")
    }
    result["version"] = _digest(_json(result))
    return result


def _carry_annotation_links(snapshot, previous):
    steps = {(row["id"], _json(row)) for row in previous.get("steps", [])}
    case_versions = {row["id"]: row["version"] for row in previous.get("test_cases", [])}
    knowledge_ids = {row["id"] for row in snapshot["knowledge_points"]}
    old_links = previous.get("links", {})

    def valid_links(records, valid_ids):
        return {
            key: {**item, "knowledge_point_ids": [
                item_id for item_id in item["knowledge_point_ids"] if item_id in knowledge_ids
            ]}
            for key, item in records.items() if key in valid_ids
        }

    return {
        "steps": valid_links(old_links.get("steps", {}), {
            str(row["id"]) for row in snapshot["steps"] if (row["id"], _json(row)) in steps
        }),
        "test_cases": valid_links(old_links.get("test_cases", {}), {
            str(row["id"]) for row in snapshot["test_cases"]
            if case_versions.get(row["id"]) == row["version"]
        }),
    }


def _validate_annotation_links(snapshot, links):
    if not isinstance(links, dict) or set(links) - {"steps", "test_cases"}:
        raise ValueError("题目标注格式无效")
    knowledge_ids = {row["id"] for row in snapshot["knowledge_points"]}
    result = {}
    for name in ("steps", "test_cases"):
        incoming = links.get(name, {})
        ids = {str(row["id"]) for row in snapshot[name]}
        if not isinstance(incoming, dict) or incoming.keys() - ids:
            raise ValueError("标注包含未知的步骤或用例")
        result[name] = {}
        for key, item in incoming.items():
            allowed = {"knowledge_point_ids"} if name == "steps" else {"knowledge_point_ids", "category"}
            if not isinstance(item, dict) or item.keys() - allowed:
                raise ValueError("步骤或用例标注格式无效")
            points = item.get("knowledge_point_ids", [])
            if not isinstance(points, list) or any(
                type(point) is not int or point not in knowledge_ids for point in points
            ):
                raise ValueError("标注包含未知的题目知识点")
            result[name][key] = {"knowledge_point_ids": sorted(set(points))}
            if name == "test_cases" and "category" in item:
                if item["category"] not in ("normal", "boundary"):
                    raise ValueError("用例类别无效")
                result[name][key]["category"] = item["category"]
    return result


def get_annotation_revision(assignment_id, *, test_cases=None, links=None):
    """Snapshot the actual question, steps and cases used by a learning event."""
    _begin_sqlite_write()
    assignment = Assignment.query.filter_by(id=assignment_id).with_for_update().first()
    if assignment is None:
        raise ValueError("题目不存在")
    if test_cases is None:
        test_cases = TestCase.query.filter_by(assignment_id=assignment_id).order_by(
            TestCase.order_index, TestCase.id,
        ).all()
    preset = AssignmentThinkingPreset.query.filter_by(assignment_id=assignment_id).first()
    quiz_steps = preset.get_quiz_steps() if preset else []
    if not isinstance(quiz_steps, list):
        quiz_steps = []
    key_steps = preset.get_key_steps() if preset else []
    if not isinstance(key_steps, list):
        key_steps = []
    knowledge_points = AssignmentKnowledgePoint.query.filter_by(assignment_id=assignment_id).order_by(
        AssignmentKnowledgePoint.id,
    ).all()
    snapshot = {
        "title": assignment.title,
        "description": assignment.description,
        "difficulty": assignment.difficulty_level,
        "knowledge_points": [{"id": row.id, "name": row.knowledge_point, "weight": row.weight,
                              "difficulty": row.difficulty} for row in knowledge_points],
        "steps": [{"id": f"concept-{index}", "content": step} for index, step in enumerate(key_steps, 1)]
        + [{"id": f"quiz-{step.get('step_id', index) if isinstance(step, dict) else index}",
            "content": step} for index, step in enumerate(quiz_steps, 1)],
        "test_cases": [_case_snapshot(case.to_dict() if isinstance(case, TestCase) else case)
                       for case in test_cases],
    }
    revisions = AssignmentAnnotationRevision.query.filter_by(assignment_id=assignment_id)
    previous = revisions.order_by(AssignmentAnnotationRevision.revision_no.desc()).with_for_update().first()
    if links is None:
        links = _carry_annotation_links(snapshot, json.loads(previous.annotations_json)) if previous else {
            "steps": {}, "test_cases": {},
        }
    else:
        links = _validate_annotation_links(snapshot, links)
    snapshot["links"] = links
    body = _json(snapshot)
    digest = _digest(body)
    if previous is not None and previous.content_hash == digest:
        return previous
    revision = AssignmentAnnotationRevision(
        assignment_id=assignment_id, revision_no=previous.revision_no + 1 if previous else 1,
        content_hash=digest, annotations_json=body,
    )
    db.session.add(revision)
    db.session.flush()
    return revision


def _attempts(student_id, assignment_id):
    return LearningAttempt.query.filter_by(student_id=student_id, assignment_id=assignment_id)


def get_attempt(student_id, assignment_id, *, expected_attempt_id=None):
    """Resolve the current attempt and reject writes from a superseded page."""
    _begin_sqlite_write()
    attempts = _attempts(student_id, assignment_id)
    ordered = attempts.order_by(LearningAttempt.attempt_no.desc())
    latest = ordered.first()
    if latest is not None:
        latest = ordered.with_for_update().first()
    if expected_attempt_id is not None and (
        latest is None or latest.id != positive_id(expected_attempt_id) or latest.closed_at is not None
    ):
        raise LearningCaptureConflict("这次做题已被重新开始，请刷新页面")
    if latest is not None:
        return latest
    revision = get_annotation_revision(assignment_id)
    initial, _ = _insert_or_find(LearningAttempt(
        student_id=student_id, assignment_id=assignment_id, attempt_no=1,
        annotation_revision_id=revision.id,
    ), attempts.filter_by(attempt_no=1))
    return initial


def restart_attempt(student_id, assignment_id, expected_attempt_id, request_id):
    request_id = _request_key(request_id, "重开请求编号", required=True)
    expected_attempt_id = positive_id(expected_attempt_id)
    _begin_sqlite_write()
    attempts = _attempts(student_id, assignment_id)
    current = attempts.order_by(LearningAttempt.attempt_no.desc()).with_for_update().first()
    lookup = attempts.filter_by(restart_request_id=request_id)
    existing = lookup.first()
    if existing is not None:
        previous = attempts.filter_by(attempt_no=existing.attempt_no - 1).first()
        if previous is None or previous.id != expected_attempt_id:
            raise LearningCaptureConflict("重开请求编号已用于其他轮次")
        return existing

    if current is None or current.id != expected_attempt_id or current.closed_at is not None:
        raise LearningCaptureConflict("这次做题已被重新开始，请刷新页面")
    now = datetime.utcnow()
    revision = get_annotation_revision(assignment_id)
    next_attempt, created = _insert_or_find(LearningAttempt(
        student_id=student_id, assignment_id=assignment_id, attempt_no=current.attempt_no + 1,
        restart_request_id=request_id, started_at=now, annotation_revision_id=revision.id,
    ), lookup)
    if created:
        current.closed_at = now
        for interval in LearningStageInterval.query.filter_by(attempt_id=current.id, ended_at=None):
            interval.ended_at = interval.last_activity_at
            interval.end_reason = "restarted"
        session = ThinkingSession.query.filter_by(attempt_id=current.id, status="in_progress").first()
        if session is not None:
            session.status = "abandoned"
    return next_attempt


def record_interval(attempt, stage, event, interval_key, *, end_reason=None, now=None):
    if not isinstance(stage, str) or stage not in STAGES or event not in ("start", "heartbeat", "end"):
        raise ValueError("学习阶段或计时事件无效")
    interval_key = _request_key(interval_key, "计时区间编号", required=True)
    now = now or datetime.utcnow()
    close_expired_intervals(attempt.id, now=now)
    lookup = LearningStageInterval.query.filter_by(attempt_id=attempt.id, interval_key=interval_key)
    interval = lookup.with_for_update().first()
    if interval is None and event != "end":
        interval, _ = _insert_or_find(LearningStageInterval(
            attempt_id=attempt.id, stage=stage, interval_key=interval_key, started_at=now, last_activity_at=now,
        ), lookup)
    if interval is None:
        return False
    if stage != interval.stage:
        raise LearningCaptureConflict("计时区间已用于其他阶段")
    if interval.ended_at is not None:
        return False
    if event == "end":
        interval.ended_at = now
        interval.end_reason = end_reason if (
            isinstance(end_reason, str) and end_reason in INTERVAL_END_REASONS
        ) else "ended"
        return False
    if event == "heartbeat":
        interval.last_activity_at = max(now, interval.last_activity_at)
    return True


def close_expired_intervals(attempt_id, *, now=None):
    cutoff = (now or datetime.utcnow()) - INTERVAL_TIMEOUT
    LearningStageInterval.query.filter(
        LearningStageInterval.attempt_id == attempt_id,
        LearningStageInterval.ended_at.is_(None),
        LearningStageInterval.last_activity_at < cutoff,
    ).update({
        LearningStageInterval.ended_at: LearningStageInterval.last_activity_at,
        LearningStageInterval.end_reason: "timeout",
    }, synchronize_session="fetch")


def _code_version(attempt, code, language):
    if code is None:
        return None
    language = (language or "cpp").strip().lower()
    if not code or len(language) > 20:
        return None
    digest = _digest(code)
    versions = CodeVersion.query.filter_by(attempt_id=attempt.id)
    lookup = versions.filter_by(language=language, content_hash=digest)
    # Serialize version numbers within one attempt on server databases.
    LearningAttempt.query.filter_by(id=attempt.id).with_for_update().one()
    existing = lookup.with_for_update().first()
    if existing is None:
        latest = versions.order_by(CodeVersion.version_no.desc()).with_for_update().first()
        existing, _ = _insert_or_find(CodeVersion(
            attempt_id=attempt.id, language=language, content_hash=digest,
            source_code=code, version_no=latest.version_no + 1 if latest else 1,
        ), lookup)
    if existing.source_code != code:
        raise LearningCaptureConflict("代码快照校验失败")
    return existing


def record_submission(submission, *, attempt_id=None, request_id=None):
    attempt = get_attempt(submission.student_id, submission.assignment_id, expected_attempt_id=attempt_id)
    request_id = _request_key(request_id, "提交请求编号")
    submission.attempt_id = attempt.id
    submission.capture_request_id = request_id
    version = _code_version(attempt, submission.code, submission.language)
    submission.code_version_id = version.id if version else None
    lookup = Submission.query.filter_by(attempt_id=attempt.id, capture_request_id=request_id)
    if request_id is None:
        db.session.add(submission)
        db.session.flush()
        return submission, True
    existing = lookup.first()
    record, created = (existing, False) if existing is not None else _insert_or_find(submission, lookup)
    if not created and (record.code != submission.code or record.language != submission.language):
        raise LearningCaptureConflict("提交请求编号已用于其他代码")
    return record, created


def record_submission_event(
    submission_id, event_type, *, run_id="submission", status=None, error_code=None,
    message=None, details=None, annotation_revision_id=None, event_key=None,
):
    event_key = event_key or event_type
    lookup = SubmissionEvent.query.filter_by(submission_id=submission_id, run_id=run_id, event_key=event_key)
    existing = lookup.first()
    if existing is not None:
        return existing
    event, _ = _insert_or_find(SubmissionEvent(
        submission_id=submission_id, run_id=run_id, event_type=event_type, event_key=event_key,
        status=status, error_code=error_code, message=message, annotation_revision_id=annotation_revision_id,
        details_json=_json(details) if details is not None else None,
    ), lookup)
    return event


def start_ai_turn(
    student_id, assignment_id=None, *, channel, question=None, code=None, language=None,
    attempt_id=None, conversation_id=None, request_id=None, stage=None, context=None,
):
    request_id = _request_key(request_id, "对话请求编号") or uuid4().hex
    conversation_id = _request_key(conversation_id, "会话编号")
    attempt = get_attempt(student_id, assignment_id, expected_attempt_id=attempt_id) if assignment_id else None
    version = _code_version(attempt, code, language) if attempt is not None else None
    if not conversation_id:
        conversation_id = f"{attempt.id if attempt else 'general'}:{channel}"
    if isinstance(stage, int):
        stage = GUIDED_STAGES.get(stage)
    lookup = AIChatTurn.query.filter_by(student_id=student_id, conversation_id=conversation_id, request_id=request_id)
    row = AIChatTurn(
        student_id=student_id, attempt_id=attempt.id if attempt else None, channel=channel, stage=stage,
        code_version_id=version.id if version else None, question=question, conversation_id=conversation_id,
        request_id=request_id, context_json=_json(context) if context is not None else None,
    )
    existing = lookup.first()
    turn, created = (existing, False) if existing is not None else _insert_or_find(row, lookup)
    if not created and (
        turn.attempt_id != row.attempt_id or turn.channel != row.channel or turn.question != row.question
        or turn.code_version_id != row.code_version_id
    ):
        raise LearningCaptureConflict("对话请求编号已用于其他内容")
    return turn, created


def finish_ai_turn(turn_id, *, response=None, status="completed"):
    if status not in ("completed", "interrupted", "failed"):
        raise ValueError("对话状态无效")
    _begin_sqlite_write()
    turn = AIChatTurn.query.filter_by(id=turn_id).with_for_update().first()
    if turn is not None and turn.status == "generating":
        turn.response = response
        turn.status = status
        turn.answered_at = datetime.utcnow()
    return turn
