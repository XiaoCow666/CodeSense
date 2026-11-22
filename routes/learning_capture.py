"""Student timing endpoints and teacher-managed assessment annotations."""

import json
from datetime import datetime

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user

from models import Assignment, AssignmentAnnotationRevision, ThinkingSession, ThinkingStageLog, db
from services.learning_capture import (
    GUIDED_STAGES,
    LearningCaptureConflict,
    close_expired_intervals,
    get_annotation_revision,
    get_attempt,
    positive_id,
    record_interval,
    restart_attempt,
)
from utils.access import can_access_assignment, can_manage_assignment
from utils.auth import login_required, student_required


learning_capture = Blueprint("learning_capture", __name__, url_prefix="/learning")


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("请求格式无效")
    return data


def _assignment(assignment_id, *, manage=False):
    assignment = db.session.get(Assignment, positive_id(assignment_id))
    if assignment is None:
        abort(404)
    check = can_manage_assignment if manage else can_access_assignment
    if not check(assignment, current_user):
        abort(403)
    return assignment


@learning_capture.errorhandler(ValueError)
def _invalid_request(error):
    db.session.rollback()
    status = 409 if isinstance(error, LearningCaptureConflict) else 400
    return jsonify(success=False, error=str(error)), status


@learning_capture.post("/attempts/ensure")
@login_required
@student_required
def ensure_attempt():
    data = _payload()
    assignment = _assignment(data.get("assignment_id"))
    attempt = get_attempt(
        current_user.student_id, assignment.id, expected_attempt_id=data.get("attempt_id"),
    )
    close_expired_intervals(attempt.id)
    payload = {"success": True, "attempt_id": attempt.id, "attempt_no": attempt.attempt_no}
    db.session.commit()
    return jsonify(payload)


@learning_capture.post("/attempts/restart")
@login_required
@student_required
def start_next_attempt():
    data = _payload()
    assignment = _assignment(data.get("assignment_id"))
    attempt = restart_attempt(
        current_user.student_id, assignment.id, data.get("attempt_id"), data.get("request_id"),
    )
    payload = {"success": True, "attempt_id": attempt.id, "attempt_no": attempt.attempt_no}
    db.session.commit()
    return jsonify(payload)


@learning_capture.post("/intervals")
@login_required
@student_required
def update_interval():
    data = _payload()
    assignment = _assignment(data.get("assignment_id"))
    attempt = get_attempt(
        current_user.student_id, assignment.id, expected_attempt_id=positive_id(data.get("attempt_id")),
    )
    stage = data.get("stage")
    event = data.get("event")
    if stage in GUIDED_STAGES.values() and event != "end":
        session = ThinkingSession.query.filter_by(attempt_id=attempt.id).first()
        if session is None or session.status != "in_progress" or GUIDED_STAGES.get(session.current_stage) != stage:
            return jsonify(success=True, active=False)
    active = record_interval(
        attempt, stage, event, data.get("interval_key"), end_reason=data.get("end_reason"),
    )
    db.session.commit()
    return jsonify(success=True, active=active)


@learning_capture.post("/hints/shown")
@login_required
@student_required
def hint_shown():
    data = _payload()
    session = db.session.get(ThinkingSession, positive_id(data.get("session_id")))
    if session is None or session.student_id != current_user.student_id:
        abort(404)
    _assignment(session.assignment_id)
    hint = ThinkingStageLog.query.filter_by(
        id=positive_id(data.get("hint_event_id")), session_id=session.id,
        stage=positive_id(data.get("stage")), event_type="hint_request",
    ).with_for_update().first_or_404()
    metadata = hint.get_metadata()
    if "shown_at" not in metadata:
        previous = hint.metadata_json
        metadata["shown_at"] = datetime.utcnow().isoformat() + "Z"
        ThinkingStageLog.query.filter(
            ThinkingStageLog.id == hint.id, ThinkingStageLog.metadata_json == previous,
        ).update({ThinkingStageLog.metadata_json: json.dumps(metadata, ensure_ascii=False)}, synchronize_session=False)
        db.session.commit()
    return jsonify(success=True)


@learning_capture.route("/annotations/<int:assignment_id>", methods=["GET", "POST"])
@login_required
def assignment_annotations(assignment_id):
    assignment = _assignment(assignment_id, manage=True)
    if request.method == "POST":
        data = _payload()
        if not isinstance(data.get("links"), dict):
            raise ValueError("缺少题目标注")
        revision = get_annotation_revision(assignment.id, links=data["links"])
    else:
        revision = AssignmentAnnotationRevision.query.filter_by(assignment_id=assignment.id).order_by(
            AssignmentAnnotationRevision.revision_no.desc()
        ).first()
    payload = {
        "revision_id": revision.id,
        "revision_no": revision.revision_no,
        "annotations": json.loads(revision.annotations_json),
    } if revision else None
    if request.method == "POST":
        db.session.commit()
    return jsonify(success=True, revision=payload)
