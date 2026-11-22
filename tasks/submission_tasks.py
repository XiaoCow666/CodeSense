"""后台异步评测任务。"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import nullcontext
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from models import Assignment, Submission, SystemLog, TestCase as TC, User, db
from services.demo_database import activate_demo_run, is_active_demo_run
from services.learning_capture import get_annotation_revision, record_submission_event
from utils import code_evaluator
from utils.code_evaluator import evaluate_cpp_code
from utils.sandbox_runner import run_test_cases
from utils.scoring import (
    normalize_evaluation_score,
    normalize_feedback_text,
    normalize_structured_feedback_scores,
)


logger = logging.getLogger(__name__)


def _log_submission_evaluation_event(
    event: str,
    submission_id: int,
    started_at: float,
    *,
    level: int = logging.INFO,
    **fields,
) -> None:
    """Write a bounded lifecycle signal without logging submission content."""

    try:
        from flask import current_app, has_app_context

        target_logger = current_app.logger if has_app_context() else logger
    except RuntimeError:
        target_logger = logger
    if not target_logger.isEnabledFor(level):
        return
    parts = [
        "submission_evaluation",
        f"event={event}",
        f"submission_id={int(submission_id)}",
        f"elapsed_ms={int((time.perf_counter() - started_at) * 1000)}",
    ]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    target_logger.log(level, " ".join(parts))


def _demo_database_is_available(demo_run_id: str | None) -> bool:
    """Return whether this worker may still use its temporary database."""

    return not demo_run_id or is_active_demo_run(demo_run_id)


def _normalise_score(score) -> int:
    """Keep every persisted submission score inside the 0–100 scale."""

    return normalize_evaluation_score(score, scale=100)


def _refresh_assignment_stats(assignment: Assignment) -> None:
    """Recalculate aggregates from evaluated submissions, including history."""

    scores = [
        score
        for (score,) in db.session.query(Submission.score)
        .filter(
            Submission.assignment_id == assignment.id,
            Submission.status == "evaluated",
            Submission.score.isnot(None),
        )
        .all()
    ]
    assignment.count = len(scores)
    assignment.total_score = sum(scores)
    assignment.average_score = sum(scores) / len(scores) if scores else 0.0


def _refresh_user_stats(student_id: str) -> None:
    """Recalculate the student's summary from all evaluated submissions."""

    user = db.session.get(User, student_id)
    if user is None:
        return

    scores = [
        score
        for (score,) in db.session.query(Submission.score)
        .filter(
            Submission.student_id == student_id,
            Submission.status == "evaluated",
            Submission.score.isnot(None),
        )
        .all()
    ]
    user.submit_count = len(scores)
    user.user_tscore = sum(scores)
    user.user_ascore = sum(scores) / len(scores) if scores else 0.0


def refresh_student_learning_index(student_id):
    """Refresh the persisted learning index after a submission is evaluated."""

    from services.student_vector_store import rebuild_student_vector_index_with_retry

    return rebuild_student_vector_index_with_retry(student_id)


def mark_submission_failed(submission_id: int, message: str) -> None:
    """Mark one submission failed in the already-bound database."""

    submission = db.session.get(Submission, submission_id)
    if submission is None:
        return
    submission.status = "failed"
    submission.feedback = message
    db.session.commit()


def _record_queue_event(app, submission_id, demo_run_id, status):
    """Write dispatch status using the submission's own database."""

    if "sqlalchemy" not in getattr(app, "extensions", {}):
        return
    with app.app_context():
        if demo_run_id and not activate_demo_run(demo_run_id):
            return
        try:
            if db.session.get(Submission, submission_id) is None:
                return
            if status == "failed":
                record_submission_event(
                    submission_id, "queue_failed", status="failed",
                    error_code="queue_unavailable",
                )
                mark_submission_failed(submission_id, "后台评测启动失败，请稍后重试。")
            else:
                event_type = "queued" if status == "queued" else "queue_requested"
                record_submission_event(submission_id, event_type, status=status)
                db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("无法写入提交调度事件 submission_id=%s status=%s", submission_id, status)


def _record_sandbox_result(submission_id, run_id, revision_id, result):
    status = result["status"]
    compile_error = result.get("compile_error")
    if status == "unavailable":
        compile_status, error_code = "unavailable", "compiler_unavailable"
    elif status == "compile_error":
        compile_status, error_code = "failed", "compile_error"
        if compile_error and compile_error.startswith("编译过程出错"):
            compile_status, error_code = "error", "compiler_process_error"
        elif compile_error and compile_error.startswith("编译超时"):
            error_code = "compile_timeout"
        elif compile_error and compile_error.startswith("编译器 ") and "输出超过限制" in compile_error:
            error_code = "compiler_output_limit"
    elif result.get("compile_success", status in {"passed", "partial", "failed"}):
        compile_status, error_code = "passed", None
    else:
        compile_status, error_code = "unknown", None

    record_submission_event(
        submission_id, "compile", run_id=run_id,
        status=compile_status, error_code=error_code, message=compile_error,
        annotation_revision_id=revision_id,
    )
    platform_failures = {"launch_error", "read_error"}
    case_errors = 0
    for index, case in enumerate(result["details"], start=1):
        reason = case.get("termination_reason")
        case_code = None if case.get("passed") else (reason or "wrong_answer")
        case_status = "passed" if case.get("passed") else "failed"
        if case_code in platform_failures:
            case_status = "error"
            case_errors += 1
        record_submission_event(
            submission_id, "test_case", run_id=run_id,
            event_key=f"test_case:{index}",
            status=case_status, error_code=case_code, message=case.get("error"),
            details={
                "case_id": case.get("case_id"),
                "order_index": case.get("order_index", index),
                "is_public": case.get("is_public"),
                "time_ms": case.get("time_ms"),
                "actual_output": case.get("actual_output"),
            },
            annotation_revision_id=revision_id,
        )
    record_submission_event(
        submission_id, "sandbox", run_id=run_id,
        status="error" if case_errors or compile_status == "error" else status,
        error_code="sandbox_case_error" if case_errors else error_code,
        details={
            "passed": result["passed"], "total": result["total"], "platform_case_errors": case_errors,
        },
        annotation_revision_id=revision_id,
    )
    db.session.commit()


def observe_submission_sandbox(submission_id, assignment_id, code, *, run_id, language="cpp"):
    """Persist sandbox observations without committing an unfinished grade."""

    if language not in {None, "c", "c++", "cpp"}:
        record_submission_event(
            submission_id, "sandbox", run_id=run_id, status="skipped",
            error_code="unsupported_sandbox_language", details={"language": language},
        )
        db.session.commit()
        return None

    committed_revision_id = None
    try:
        cases = [
            case.to_dict()
            for case in TC.query.filter_by(assignment_id=assignment_id)
            .order_by(TC.order_index, TC.id)
            .all()
        ]
        revision_id = get_annotation_revision(assignment_id, test_cases=cases).id
        if not cases:
            record_submission_event(
                submission_id, "sandbox", run_id=run_id, status="skipped",
                error_code="no_test_cases", annotation_revision_id=revision_id,
            )
            db.session.commit()
            return None

        record_submission_event(
            submission_id, "sandbox_started", run_id=run_id, status="running",
            annotation_revision_id=revision_id,
        )
        db.session.commit()
        committed_revision_id = revision_id
        result = run_test_cases(code, cases)
        _record_sandbox_result(submission_id, run_id, revision_id, result)
        return result
    except Exception as error:
        db.session.rollback()
        record_submission_event(
            submission_id, "sandbox", run_id=run_id, status="error",
            error_code="sandbox_error", details={"error_type": type(error).__name__},
            annotation_revision_id=committed_revision_id,
        )
        db.session.commit()
        raise


def evaluate_submission_async(
    app, submission_id, assignment_title, demo_run_id=None, *, run_inline=False
):
    """异步评测学生提交的代码。

    ``demo_run_id`` 为空时使用正式数据库；公开体验传入该值后，线程会
    先切换到对应的临时数据库，并在会话失效时直接停止。
    """

    if (
        not run_inline
        and not demo_run_id
        and app.config.get("SUBMISSION_EVALUATION_QUEUE_BACKEND", "thread")
        == "rq"
    ):
        from tasks.submission_queue import (
            SubmissionQueueUnavailable,
            enqueue_submission_evaluation,
        )

        _record_queue_event(app, submission_id, demo_run_id, "requested")
        try:
            queued = enqueue_submission_evaluation(app, submission_id)
        except SubmissionQueueUnavailable:
            _record_queue_event(app, submission_id, demo_run_id, "failed")
            raise
        _record_queue_event(app, submission_id, demo_run_id, "queued")
        return queued

    def _evaluate():
        started_at = time.perf_counter()
        run_id = uuid4().hex
        from flask import current_app, has_app_context

        evaluation_context = (
            nullcontext()
            if has_app_context() and current_app._get_current_object() is app
            else app.app_context()
        )
        with evaluation_context:
            _log_submission_evaluation_event("started", submission_id, started_at)
            if demo_run_id and not activate_demo_run(demo_run_id):
                print("公开体验会话已失效，跳过提交评测")
                _log_submission_evaluation_event(
                    "skipped",
                    submission_id,
                    started_at,
                    reason="demo_run_unavailable",
                )
                return

            try:
                if not _demo_database_is_available(demo_run_id):
                    return

                submission = db.session.get(Submission, submission_id)
                if not submission:
                    print(f"找不到提交记录: {submission_id}")
                    return

                assignment = db.session.get(Assignment, submission.assignment_id)
                if assignment is None:
                    raise RuntimeError("提交对应的作业不存在")

                code = submission.code
                student_id = submission.student_id

                print(f"开始后台评估提交 {submission_id}")
                record_submission_event(
                    submission_id, "evaluation_started", run_id=run_id, status="running",
                )
                db.session.commit()

                # 1. AI 基础评估。公开体验不接受默认分数，AI 失败必须
                # 让提交进入 failed，方便前端提示用户重新提交。
                try:
                    ai_feedback = None
                    score, feedback = evaluate_cpp_code(
                        code, assignment_title=assignment_title
                    )
                    score = _normalise_score(score)
                    feedback = normalize_feedback_text(feedback)

                    structured_data = code_evaluator.get_last_structured_data()
                    if structured_data:
                        structured_data = normalize_structured_feedback_scores(
                            structured_data
                        )
                        for field, value in structured_data.items():
                            if isinstance(value, str):
                                structured_data[field] = normalize_feedback_text(value)
                        ai_feedback = json.dumps(structured_data, ensure_ascii=False)
                    elif isinstance(feedback, str) and (
                        "【" in feedback or "改进建议" in feedback
                    ):
                        ai_feedback = feedback
                except Exception as ai_error:
                    print(f"AI 评估过程出错: {type(ai_error).__name__}")
                    record_submission_event(
                        submission_id, "ai_evaluation", run_id=run_id, status="failed",
                        error_code="ai_evaluation_failed",
                        details={"error_type": type(ai_error).__name__},
                    )
                    record_submission_event(
                        submission_id, "sandbox", run_id=run_id, status="skipped",
                        error_code="ai_evaluation_failed",
                    )
                    db.session.commit()
                    raise RuntimeError("AI 评测失败，请稍后重试") from ai_error
                record_submission_event(
                    submission_id, "ai_evaluation", run_id=run_id, status="completed"
                )
                db.session.commit()

                # 2. 沙箱测试用例评判。
                sandbox_result = None
                try:
                    sandbox_result = observe_submission_sandbox(
                        submission_id, assignment.id, code, run_id=run_id, language=submission.language,
                    )
                except Exception as sandbox_error:
                    db.session.rollback()
                    print(f"沙箱评判过程出错: {type(sandbox_error).__name__}")
                    if demo_run_id:
                        raise RuntimeError("沙箱评测失败，请稍后重试") from sandbox_error

                if not _demo_database_is_available(demo_run_id):
                    return

                submission.score = score
                submission.feedback = feedback
                if ai_feedback is not None:
                    submission.ai_feedback = ai_feedback
                if sandbox_result is not None:
                    submission.sandbox_status = sandbox_result["status"]
                    submission.sandbox_passed = sandbox_result["passed"]
                    submission.sandbox_total = sandbox_result["total"]
                    submission.sandbox_detail = json.dumps(
                        sandbox_result["details"], ensure_ascii=False
                    )
                    if sandbox_result["total"] > 0:
                        final_score = sandbox_result["passed"] / sandbox_result["total"] * 100
                        if sandbox_result["status"] in {"compile_error", "error"}:
                            final_score = min(final_score, 20)
                        submission.score = _normalise_score(final_score)

                # 3. 提交和统计信息均从完整历史重新计算，避免累加种子
                # 数据时出现重复统计或 100 分制残留。
                submission.status = "evaluated"
                _refresh_assignment_stats(assignment)
                _refresh_user_stats(student_id)
                db.session.commit()

                # 4. 更新本次提交覆盖的知识点。
                try:
                    from models import AssignmentKnowledgePoint, KnowledgePointScore
                    from services.ai_evaluator import AIEvaluator

                    assignment_kps = AssignmentKnowledgePoint.query.filter_by(
                        assignment_id=assignment.id
                    ).all()

                    if assignment_kps:
                        for knowledge_point in assignment_kps:
                            KnowledgePointScore.update_score(
                                student_id=student_id,
                                knowledge_point=knowledge_point.knowledge_point,
                                assignment_score=submission.score,
                                difficulty=knowledge_point.difficulty,
                                weight=knowledge_point.weight,
                            )
                    else:
                        api_key = app.config.get("ZHIPU_API_KEY")
                        if api_key:
                            ai_evaluator = AIEvaluator(api_key)
                            detected_kps = ai_evaluator.detect_code_knowledge_points(
                                code, assignment.title
                            )
                            for kp_data in detected_kps:
                                AssignmentKnowledgePoint.add_to_assignment(
                                    assignment_id=assignment.id,
                                    knowledge_point=kp_data["knowledge_point"],
                                    weight=kp_data.get("weight", 1.0),
                                    difficulty=kp_data.get("difficulty", 1.0),
                                    auto_detected=True,
                                )
                                KnowledgePointScore.update_score(
                                    student_id=student_id,
                                    knowledge_point=kp_data["knowledge_point"],
                                    assignment_score=submission.score,
                                    difficulty=kp_data.get("difficulty", 1.0),
                                    weight=kp_data.get("weight", 1.0),
                                )
                except Exception as kp_error:
                    print(f"更新知识点评分失败: {type(kp_error).__name__}")
                    if demo_run_id:
                        raise RuntimeError("知识点画像更新失败，请稍后重试") from kp_error

                # 5. 每次成功提交都让能力分析进入刷新链路；demo run id
                # 必须继续向下传递，异步分析不会误读正式库。
                try:
                    from tasks.ability_analysis import trigger_analysis_if_needed

                    from models import AbilityTrend

                    AbilityTrend.mark_as_outdated(student_id)
                    trigger_analysis_if_needed(
                        student_id, demo_run_id=demo_run_id
                    )
                    print("已触发能力分析刷新")
                except Exception as ability_error:
                    print(f"触发能力分析失败: {type(ability_error).__name__}")
                    if demo_run_id:
                        raise RuntimeError("能力分析任务启动失败") from ability_error

                if not _demo_database_is_available(demo_run_id):
                    return
                db.session.commit()

                from services.student_vector_store import StudentVectorRebuildError

                try:
                    vector_snapshot = refresh_student_learning_index(student_id)
                    print(
                        f"学生 {student_id} 学习索引已更新 revision="
                        f"{vector_snapshot['revision']}"
                    )
                except StudentVectorRebuildError as vector_error:
                    print(
                        f"学生 {student_id} 学习索引更新失败: "
                        f"{type(vector_error).__name__}"
                    )
                    if demo_run_id:
                        raise RuntimeError("学习记录索引更新失败") from vector_error

                # 公开体验不写正式系统日志，也不把临时访客动作混入
                # 管理端审计数据。
                if not demo_run_id:
                    SystemLog.add_log(
                        log_type="评测完成",
                        content=(
                            f"提交 {submission_id} 评测已完成，"
                            f"得分：{submission.score}/100"
                        ),
                        user_id=student_id,
                        icon="bi bi-check-circle-fill",
                    )
                record_submission_event(
                    submission_id, "evaluation_finished", run_id=run_id, status="evaluated",
                )
                db.session.commit()
                _log_submission_evaluation_event(
                    "finished",
                    submission_id,
                    started_at,
                    state=submission.status,
                    sandbox_status=submission.sandbox_status or "none",
                )
                print(f"提交 {submission_id} 评测全部完成")
                return "evaluated"

            except Exception as error:
                print(f"评测线程崩溃: {type(error).__name__}")
                _log_submission_evaluation_event(
                    "failed",
                    submission_id,
                    started_at,
                    level=logging.WARNING,
                    error_type=type(error).__name__,
                )
                if not _demo_database_is_available(demo_run_id):
                    return
                try:
                    db.session.rollback()
                    if db.session.get(Submission, submission_id) is not None:
                        record_submission_event(
                            submission_id, "evaluation_finished", run_id=run_id, status="failed",
                            error_code="evaluation_failed",
                            details={"error_type": type(error).__name__},
                        )
                    mark_submission_failed(
                        submission_id,
                        "AI 评测失败，请稍后重试。" if demo_run_id else "后台评测发生严重错误，请稍后重试。",
                    )
                except Exception:
                    db.session.rollback()

            return "failed"

    if run_inline:
        return _evaluate()

    _record_queue_event(app, submission_id, demo_run_id, "requested")
    thread = threading.Thread(target=_evaluate)
    thread.daemon = True
    try:
        thread.start()
    except Exception:
        _record_queue_event(app, submission_id, demo_run_id, "failed")
        raise
    _record_queue_event(app, submission_id, demo_run_id, "queued")
    print(f"已启动后台评测线程 - 提交 ID: {submission_id}")
    return thread


def run_submission_evaluation(app, submission_id, assignment_title=None, demo_run_id=None):
    """Run one submission evaluation inline inside a worker or app context."""

    result = evaluate_submission_async(
        app,
        submission_id,
        assignment_title,
        demo_run_id=demo_run_id,
        run_inline=True,
    )
    if result == "failed":
        raise RuntimeError("submission evaluation failed")
    return result or "evaluated"


def run_formal_submission_evaluation(submission_id):
    """RQ entry point; resolve all business data inside the worker context."""

    from flask import current_app

    submission_id = int(submission_id)
    submission = db.session.get(Submission, submission_id)
    if submission is None:
        raise RuntimeError("提交记录不存在")
    assignment = db.session.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise RuntimeError("提交对应的作业不存在")
    return run_submission_evaluation(
        current_app._get_current_object(),
        submission_id,
        assignment.title,
        None,
    )
