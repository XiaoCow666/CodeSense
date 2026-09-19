"""后台异步评测任务。"""

from __future__ import annotations

import json
import logging
import threading
import time

from models import Assignment, Submission, SystemLog, TestCase as TC, User, db
from services.demo_database import activate_demo_run, is_active_demo_run
from utils.code_evaluator import evaluate_cpp_code, llm_evaluator
from utils.sandbox_runner import run_test_cases
from utils.scoring import normalize_evaluation_score, normalize_feedback_text


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

    parts = [
        "submission_evaluation",
        f"event={event}",
        f"submission_id={int(submission_id)}",
        f"elapsed_ms={int((time.perf_counter() - started_at) * 1000)}",
    ]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    try:
        from flask import current_app, has_app_context

        target_logger = current_app.logger if has_app_context() else logger
    except RuntimeError:
        target_logger = logger
    target_logger.log(level, " ".join(parts))


def _demo_database_is_available(demo_run_id: str | None) -> bool:
    """Return whether this worker may still use its temporary database."""

    return not demo_run_id or is_active_demo_run(demo_run_id)


def _normalise_score(score) -> int:
    """Keep every persisted submission score inside the 0–100 scale."""

    return normalize_evaluation_score(score)


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

    from services.student_vector_store import rebuild_student_vector_index

    return rebuild_student_vector_index(student_id)


def _mark_submission_failed(submission_id: int, message: str) -> None:
    """Mark one submission failed in the already-bound database."""

    submission = db.session.get(Submission, submission_id)
    if submission is None:
        return
    submission.status = "failed"
    submission.feedback = message
    db.session.commit()


def mark_submission_failed(submission_id: int, message: str) -> None:
    """Expose the shared failure transition to submission entry points."""

    _mark_submission_failed(submission_id, message)


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

        try:
            return enqueue_submission_evaluation(app, submission_id)
        except SubmissionQueueUnavailable:
            with app.app_context():
                try:
                    _mark_submission_failed(
                        submission_id,
                        "提交评测队列暂时不可用，请稍后重试",
                    )
                except Exception:
                    db.session.rollback()
            raise

    def _evaluate():
        started_at = time.perf_counter()
        with app.app_context():
            _log_submission_evaluation_event("started", submission_id, started_at)
            if demo_run_id and not activate_demo_run(demo_run_id):
                print("公开体验会话已失效，跳过提交评测")
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

                # 1. AI 基础评估。公开体验不接受默认分数，AI 失败必须
                # 让提交进入 failed，方便前端提示用户重新提交。
                try:
                    score, feedback = evaluate_cpp_code(
                        code, assignment_title=assignment_title
                    )
                    score = _normalise_score(score)
                    feedback = normalize_feedback_text(feedback)

                    if hasattr(llm_evaluator, "_last_structured_data"):
                        structured_data = llm_evaluator._last_structured_data
                        if structured_data:
                            structured_data = dict(structured_data)
                            for field in (
                                "overall_score",
                                "algorithm_score",
                                "style_score",
                                "functionality_score",
                                "efficiency_score",
                                "readability_score",
                            ):
                                if field in structured_data and structured_data[field] is not None:
                                    structured_data[field] = normalize_evaluation_score(
                                        structured_data[field]
                                    )
                            for field, value in structured_data.items():
                                if isinstance(value, str):
                                    structured_data[field] = normalize_feedback_text(value)
                            submission.ai_feedback = json.dumps(
                                structured_data, ensure_ascii=False
                            )
                    elif isinstance(feedback, str) and (
                        "【" in feedback or "改进建议" in feedback
                    ):
                        submission.ai_feedback = feedback

                    submission.score = score
                    submission.feedback = feedback
                except Exception as ai_error:
                    print(f"AI 评估过程出错: {type(ai_error).__name__}")
                    if demo_run_id:
                        raise RuntimeError("AI 评测失败，请稍后重试") from ai_error
                    # 正式账户保留历史兼容行为；公开体验永远不会走到这条
                    # 默认分支，避免把失败伪装成成功分数。
                    submission.score = 20
                    submission.feedback = "AI 评估过程中出错，请稍后重试。"

                # 2. 沙箱测试用例评判。
                try:
                    test_cases = (
                        TC.query.filter_by(assignment_id=submission.assignment_id)
                        .order_by(TC.order_index)
                        .all()
                    )
                    if test_cases:
                        tc_list = [test_case.to_dict() for test_case in test_cases]
                        sandbox_result = run_test_cases(code, tc_list)

                        submission.sandbox_status = sandbox_result["status"]
                        submission.sandbox_passed = sandbox_result["passed"]
                        submission.sandbox_total = sandbox_result["total"]
                        submission.sandbox_detail = json.dumps(
                            sandbox_result["details"], ensure_ascii=False
                        )

                        if sandbox_result["total"] > 0:
                            sandbox_score = (
                                sandbox_result["passed"]
                                / sandbox_result["total"]
                                * 100
                            )
                            final_score = sandbox_score
                            if sandbox_result["status"] == "compile_error":
                                final_score = min(final_score, 20)
                            elif sandbox_result["status"] == "error":
                                final_score = min(final_score, 20)
                            submission.score = _normalise_score(final_score)
                            print(
                                "沙箱评判完成: "
                                f"{submission.sandbox_passed}/{submission.sandbox_total}, "
                                f"最终得分: {submission.score}"
                            )
                except Exception as sandbox_error:
                    print(f"沙箱评判过程出错: {type(sandbox_error).__name__}")
                    if demo_run_id:
                        raise RuntimeError("沙箱评测失败，请稍后重试") from sandbox_error

                if not _demo_database_is_available(demo_run_id):
                    return

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
                    _mark_submission_failed(
                        submission_id,
                        "AI 评测失败，请稍后重试。" if demo_run_id else "后台评测发生严重错误，请稍后重试。",
                    )
                except Exception:
                    db.session.rollback()

            return "failed"

    if run_inline:
        return _evaluate()

    thread = threading.Thread(target=_evaluate)
    thread.daemon = True
    thread.start()
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
