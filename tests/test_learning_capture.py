import json
import re
from datetime import datetime, timedelta

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
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
    TestCase as _TestCase,
    ThinkingSession,
    ThinkingStageLog,
    User,
    db,
)
from services.learning_capture import (
    get_annotation_revision,
    get_attempt,
    record_interval,
    record_submission,
    record_submission_event,
    start_ai_turn,
    finish_ai_turn,
)
from routes import api as api_routes
from tasks import submission_tasks


@pytest.fixture
def capture_context(tmp_path, monkeypatch):
    path = (tmp_path / "learning_capture.db").as_posix()
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{path}")
    app = create_app("testing")
    with app.app_context():
        student = User(student_id="learning-student", username="learning-student", usertype="学生")
        student.password = "test-password"
        assignment = Assignment(title="数组求和", description="逐项求和", creator_id=student.student_id)
        db.session.add_all([student, assignment])
        db.session.flush()
        preset = AssignmentThinkingPreset(
            assignment_id=assignment.id, status="ready", key_steps=json.dumps(["检查数组下标"]),
        )
        case = _TestCase(assignment_id=assignment.id, input_data="1\n7", expected_output="7")
        point = AssignmentKnowledgePoint(assignment_id=assignment.id, knowledge_point="数组")
        db.session.add_all([preset, case, point])
        db.session.commit()
        assignment_id = assignment.id
    client = app.test_client()
    assert client.post(
        "/login", data={"username": "learning-student", "password": "test-password"},
    ).status_code in (200, 302)
    return app, client, assignment_id


def test_turn_submission_and_restart_share_the_right_records(capture_context):
    app, client, assignment_id = capture_context
    start = client.post("/learning/attempts/ensure", json={"assignment_id": assignment_id})
    assert start.status_code == 200
    attempt_id = start.json["attempt_id"]
    original = "for (int i = 0; i <= n; ++i) sum += a.at(i);"
    corrected = "for (int i = 0; i < n; ++i) sum += a.at(i);"
    student_id = "learning-student"

    with app.app_context():
        attempt = get_attempt(student_id, assignment_id, expected_attempt_id=attempt_id)
        session = ThinkingSession(student_id=student_id, assignment_id=assignment_id, attempt_id=attempt.id)
        db.session.add(session)
        clock = datetime(2026, 11, 22, 10, 0)
        for stage, minutes in (("solution_description", 2), ("block_programming", 3), ("feynman", 4), ("coding", 6)):
            assert record_interval(attempt, stage, "start", stage, now=clock)
            for seconds in range(15, minutes * 60, 15):
                assert record_interval(attempt, stage, "heartbeat", stage, now=clock + timedelta(seconds=seconds))
            clock += timedelta(minutes=minutes)
            assert not record_interval(attempt, stage, "end", stage, now=clock)

        turn, created = start_ai_turn(
            student_id, assignment_id, attempt_id=attempt_id, channel="code_assistant", stage="coding",
            question="最后一轮会越界吗？", code=original, request_id="question-1",
        )
        assert created
        turn_id = turn.id
        first, created = record_submission(Submission(
            student_id=student_id, assignment_id=assignment_id, code=original, language="cpp",
        ), request_id="submit-1")
        assert created and first.code_version_id == turn.code_version_id
        duplicate, created = record_submission(Submission(
            student_id=student_id, assignment_id=assignment_id, code=original, language="cpp",
        ), request_id="submit-1")
        assert not created and duplicate.id == first.id
        second, created = record_submission(Submission(
            student_id=student_id, assignment_id=assignment_id, code=corrected, language="cpp",
        ), request_id="submit-2")
        assert created and second.code_version_id != first.code_version_id
        record_submission_event(first.id, "case", status="runtime_error", message="out_of_range")
        record_submission_event(second.id, "case", status="passed")
        db.session.commit()

    payload = {"assignment_id": assignment_id, "attempt_id": attempt_id, "request_id": "restart-1"}
    restarted = client.post("/learning/attempts/restart", json=payload)
    assert restarted.status_code == 200
    assert client.post("/learning/attempts/restart", json=payload).json == restarted.json
    assert client.post("/learning/intervals", json={
        "assignment_id": assignment_id, "attempt_id": attempt_id,
        "event": "heartbeat", "stage": "coding", "interval_key": "coding",
    }).status_code == 409

    with app.app_context():
        finish_ai_turn(turn_id, response="先检查合法下标范围。")
        db.session.commit()
        assert LearningAttempt.query.count() == 2
        assert db.session.get(LearningAttempt, attempt_id).closed_at is not None
        assert ThinkingSession.query.filter_by(attempt_id=attempt_id).one().status == "abandoned"
        assert Submission.query.filter_by(attempt_id=attempt_id).count() == 2
        assert CodeVersion.query.filter_by(attempt_id=attempt_id).count() == 2
        assert AIChatTurn.query.one().attempt_id == attempt_id
        assert AIChatTurn.query.one().response == "先检查合法下标范围。"
        assert {event.status for event in SubmissionEvent.query} == {"runtime_error", "passed"}
        intervals = LearningStageInterval.query.filter_by(attempt_id=attempt_id).all()
        assert sorted(int((row.ended_at - row.started_at).total_seconds()) for row in intervals) == [120, 180, 240, 360]


def test_legacy_session_restart_closes_first_round_and_starts_a_new_session(capture_context):
    app, client, assignment_id = capture_context
    student_id = "learning-student"
    with app.app_context():
        other_student = User(student_id="other-student", username="other-student", usertype="学生")
        other_student.password = "test-password"
        other_assignment = Assignment(title="另一个作业", description="保留其他作业的会话", creator_id=student_id)
        db.session.add_all([other_student, other_assignment])
        db.session.flush()
        legacy = ThinkingSession(student_id=student_id, assignment_id=assignment_id)
        unrelated = [
            ThinkingSession(student_id=other_student.student_id, assignment_id=assignment_id),
            ThinkingSession(student_id=student_id, assignment_id=other_assignment.id),
        ]
        db.session.add_all([legacy, *unrelated])
        db.session.commit()
        legacy_id = legacy.id
        unrelated_ids = [session.id for session in unrelated]

    ensured = client.post("/learning/attempts/ensure", json={"assignment_id": assignment_id})
    assert ensured.status_code == 200
    first_attempt_id = ensured.json["attempt_id"]
    with app.app_context():
        assert db.session.get(ThinkingSession, legacy_id).attempt_id is None

    interval = client.post("/learning/intervals", json={
        "assignment_id": assignment_id, "attempt_id": first_attempt_id,
        "event": "start", "stage": "coding", "interval_key": "before-restart",
    })
    assert interval.status_code == 200 and interval.json["active"]
    restart_payload = {
        "assignment_id": assignment_id, "attempt_id": first_attempt_id, "request_id": "legacy-restart",
    }
    restarted = client.post("/learning/attempts/restart", json=restart_payload)
    assert restarted.status_code == 200
    assert restarted.json["attempt_no"] == 2
    second_attempt_id = restarted.json["attempt_id"]
    assert client.post("/learning/attempts/restart", json=restart_payload).json == restarted.json

    started = client.post("/thinking/api/start_session", json={
        "assignment_id": assignment_id, "attempt_id": second_attempt_id,
    })
    assert started.status_code == 200
    assert started.json["attempt_id"] == second_attempt_id
    assert started.json["session_id"] != legacy_id

    with app.app_context():
        legacy = db.session.get(ThinkingSession, legacy_id)
        assert legacy.attempt_id == first_attempt_id and legacy.status == "abandoned"
        assert db.session.get(LearningAttempt, first_attempt_id).closed_at is not None
        interval = LearningStageInterval.query.filter_by(attempt_id=first_attempt_id).one()
        assert interval.end_reason == "restarted" and interval.ended_at == interval.last_activity_at
        new_session = db.session.get(ThinkingSession, started.json["session_id"])
        assert new_session.attempt_id == second_attempt_id and new_session.status == "in_progress"
        assert LearningAttempt.query.filter_by(student_id=student_id, assignment_id=assignment_id).count() == 2
        for unrelated_id in unrelated_ids:
            unrelated_session = db.session.get(ThinkingSession, unrelated_id)
            assert unrelated_session.attempt_id is None and unrelated_session.status == "in_progress"

    stale_update = client.post("/thinking/api/stage1/submit", json={
        "session_id": legacy_id, "description": "逐项读取输入并累加求和",
    })
    assert stale_update.status_code == 409


def test_expired_stage_and_real_hint_display_are_recorded_once(capture_context):
    app, client, assignment_id = capture_context
    with app.app_context():
        attempt = get_attempt("learning-student", assignment_id)
        clock = datetime(2026, 11, 22, 10, 0)
        assert record_interval(attempt, "coding", "start", "lost-tab", now=clock)
        assert not record_interval(attempt, "coding", "heartbeat", "lost-tab", now=clock + timedelta(minutes=2))
        interval = LearningStageInterval.query.one()
        assert interval.ended_at == clock and interval.end_reason == "timeout"
        session = ThinkingSession(
            student_id=attempt.student_id, assignment_id=assignment_id, attempt_id=attempt.id,
        )
        db.session.add(session)
        db.session.flush()
        hint = ThinkingStageLog(session_id=session.id, stage=1, event_type="hint_request", content="先检查循环")
        db.session.add(hint)
        db.session.commit()
        display = {"session_id": session.id, "stage": 1, "hint_event_id": hint.id}

    assert client.post("/learning/hints/shown", json=display).status_code == 200
    with app.app_context():
        first_display = db.session.get(ThinkingStageLog, display["hint_event_id"]).get_metadata()["shown_at"]
    assert client.post("/learning/hints/shown", json=display).status_code == 200
    with app.app_context():
        assert db.session.get(ThinkingStageLog, display["hint_event_id"]).get_metadata()["shown_at"] == first_display


def test_annotation_revision_keeps_its_original_case_and_links(capture_context):
    app, _, assignment_id = capture_context
    with app.app_context():
        case = _TestCase.query.one()
        point = AssignmentKnowledgePoint.query.one()
        initial = get_annotation_revision(assignment_id, links={
            "steps": {"concept-1": {"knowledge_point_ids": [point.id]}},
            "test_cases": {str(case.id): {"knowledge_point_ids": [point.id], "category": "boundary"}},
        })
        db.session.commit()
        assert get_annotation_revision(assignment_id).id == initial.id
        case.expected_output = "8"
        db.session.flush()
        updated = get_annotation_revision(assignment_id)
        db.session.commit()
        before = json.loads(initial.annotations_json)
        afterward = json.loads(updated.annotations_json)
        assert updated.revision_no == initial.revision_no + 1
        assert before["test_cases"][0]["expected_output"] == "7"
        assert afterward["test_cases"][0]["expected_output"] == "8"
        assert afterward["links"]["steps"] == before["links"]["steps"]
        assert afterward["links"]["test_cases"] == {}


def test_editor_and_submission_api_persist_versioned_records(capture_context, monkeypatch):
    app, client, assignment_id = capture_context
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "thread"
    first_code = "int main() { return 1; }"
    second_code = "int main() { return 0; }"

    class FakeClient:
        def is_available(self):
            return True

        def chat_stream(self, *args, **kwargs):
            return iter(["请检查循环最后一次迭代。"])

    def sandbox(code, cases):
        passed = code == second_code
        return {
            "status": "passed" if passed else "failed",
            "compile_success": True,
            "passed": int(passed),
            "total": 1,
            "details": [{
                "case_id": cases[0]["id"],
                "passed": passed,
                "actual_output": "7" if passed else "",
                "termination_reason": None if passed else "runtime_error",
            }],
        }

    monkeypatch.setattr("services.llm_client.SharedLLMClient", FakeClient)
    monkeypatch.setattr(api_routes, "evaluate_cpp_code", lambda **kwargs: (85, "请检查边界"))
    monkeypatch.setattr(submission_tasks, "run_test_cases", sandbox)
    attempt = client.post("/learning/attempts/ensure", json={"assignment_id": assignment_id}).json
    identity = {"assignment_id": assignment_id, "attempt_id": attempt["attempt_id"], "language": "cpp"}
    response = client.post(
        "/api/code_advice",
        json={**identity, "code": first_code, "question": "如何检查边界？", "request_id": "first-question"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.data.decode().splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"

    for code, key in ((first_code, "first-submit"), (second_code, "second-submit")):
        response = client.post("/api/submit", json={**identity, "code": code, "request_id": key})
        assert response.status_code == 200, response.json
    with app.app_context():
        first, second = Submission.query.order_by(Submission.id).all()
        turn = AIChatTurn.query.one()
        assert first.attempt_id == second.attempt_id == turn.attempt_id == attempt["attempt_id"]
        assert first.code_version_id == turn.code_version_id != second.code_version_id
        assert turn.status == "completed" and "循环" in turn.response
        failed = SubmissionEvent.query.filter_by(submission_id=first.id, event_type="test_case").one()
        passed = SubmissionEvent.query.filter_by(submission_id=second.id, event_type="test_case").one()
        assert failed.error_code == "runtime_error"
        assert passed.status == "passed"
        assert failed.annotation_revision_id == passed.annotation_revision_id

    interrupted = client.post(
        "/api/code_advice",
        json={**identity, "code": second_code, "question": "这个版本呢？", "request_id": "second-question"},
        headers={"Accept": "text/event-stream"}, buffered=False,
    )
    assert any(b'"delta"' in chunk for chunk in interrupted.response)
    interrupted.close()
    with app.app_context():
        turn = AIChatTurn.query.filter_by(request_id="second-question").one()
        assert turn.status == "interrupted"
        assert "循环" in turn.response


def test_learning_routes_require_csrf_and_scope_attempts_to_the_account(capture_context):
    app, client, assignment_id = capture_context
    with app.app_context():
        # Both accounts can open the public assignment, so the attempt check
        # must still prevent one of them from writing to the other's record.
        db.session.get(Assignment, assignment_id).creator_id = None
        another = User(student_id="other-student", username="other-student", usertype="学生")
        another.password = "other-password"
        db.session.add(another)
        db.session.commit()

    def csrf_token(browser, path):
        markup = browser.get(path).get_data(as_text=True)
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', markup).group(1)

    app.config["WTF_CSRF_ENABLED"] = True
    editor_token = csrf_token(client, f"/assignments/submit/{assignment_id}")
    payload = {"assignment_id": assignment_id}
    assert client.post("/learning/attempts/ensure", json=payload).status_code == 400
    allowed = client.post("/learning/attempts/ensure", json=payload, headers={"X-CSRFToken": editor_token})
    assert allowed.status_code == 200

    other = app.test_client()
    app.config["WTF_CSRF_ENABLED"] = False
    assert other.post("/login", data={
        "username": "other-student", "password": "other-password",
    }).status_code == 302
    app.config["WTF_CSRF_ENABLED"] = True
    other_token = csrf_token(other, f"/assignments/submit/{assignment_id}")
    result = other.post("/learning/intervals", headers={"X-CSRFToken": other_token}, json={
        **payload, "attempt_id": allowed.json["attempt_id"], "stage": "coding",
        "event": "start", "interval_key": "other-attempt",
    })
    assert result.status_code == 409
    assert other.get(f"/learning/annotations/{assignment_id}").status_code == 403


@pytest.mark.parametrize("owner", ("student", "assignment"))
def test_deleting_capture_owner_removes_private_learning_data(capture_context, owner):
    app, _, _ = capture_context
    student_id = "learning-student"
    code = "int main() { return 0; }"
    with app.app_context():
        db.session.execute(db.text("PRAGMA foreign_keys = OFF"))
        assignment = Assignment(title="练习")
        db.session.add(assignment)
        db.session.flush()
        attempt = get_attempt(student_id, assignment.id)
        record_interval(attempt, "coding", "start", "coding-interval")
        start_ai_turn(student_id, assignment.id, channel="code_assistant", question="怎么修正？", code=code)
        start_ai_turn(student_id, channel="code_assistant", question="通用问题")
        submission, _ = record_submission(Submission(
            student_id=student_id, assignment_id=assignment.id, code=code,
        ))
        record_submission_event(submission.id, "submitted")
        db.session.commit()

        target = db.session.get(User, student_id) if owner == "student" else assignment
        db.session.delete(target)
        db.session.commit()

        assert LearningAttempt.query.count() == 0
        assert LearningStageInterval.query.count() == 0
        assert CodeVersion.query.count() == 0
        assert Submission.query.count() == 0
        assert SubmissionEvent.query.count() == 0
        if owner == "student":
            assert AIChatTurn.query.count() == 0
            assert AssignmentAnnotationRevision.query.count() == 1
        else:
            assert AIChatTurn.query.one().attempt_id is None
            assert AssignmentAnnotationRevision.query.count() == 0


@pytest.mark.parametrize("language", ("python", "java"))
def test_worker_does_not_run_other_languages_in_cpp_sandbox(capture_context, monkeypatch, language):
    app, _, assignment_id = capture_context
    monkeypatch.setattr(submission_tasks, "evaluate_cpp_code", lambda *args, **kwargs: (85, "反馈"))
    monkeypatch.setattr(submission_tasks.code_evaluator, "get_last_structured_data", lambda: None)
    monkeypatch.setattr(submission_tasks, "refresh_student_learning_index", lambda student_id: {"revision": 1})
    monkeypatch.setattr("tasks.ability_analysis.trigger_analysis_if_needed", lambda *args, **kwargs: None)
    monkeypatch.setattr(submission_tasks, "run_test_cases", lambda *args: pytest.fail("unexpected C++ run"))
    with app.app_context():
        submission, _ = record_submission(Submission(
            student_id="learning-student", assignment_id=assignment_id, code="example", language=language,
        ))
        submission_id = submission.id
        db.session.commit()

        assert submission_tasks.run_submission_evaluation(app, submission_id) == "evaluated"
        event = SubmissionEvent.query.filter_by(submission_id=submission_id, event_type="sandbox").one()
        assert event.status == "skipped"
        assert event.error_code == "unsupported_sandbox_language"
    with app.app_context():
        assert LearningAttempt.query.count() == 1
        assert LearningStageInterval.query.count() == 0
