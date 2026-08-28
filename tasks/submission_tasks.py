"""后台异步评测任务。"""

from __future__ import annotations

import json
import threading
import traceback

from models import Assignment, Submission, SystemLog, TestCase as TC, User, db
from services.demo_database import activate_demo_run, is_active_demo_run
from utils.code_evaluator import evaluate_cpp_code, llm_evaluator
from utils.sandbox_runner import run_test_cases


def _demo_database_is_available(demo_run_id: str | None) -> bool:
    """Return whether this worker may still use its temporary database."""

    return not demo_run_id or is_active_demo_run(demo_run_id)


def _normalise_score(score) -> int:
    """Keep every persisted submission score inside the product's 0–5 scale."""

    try:
        raw_score = float(score)
        # The current heuristic evaluator already returns 0–5. The LLM and
        # legacy evaluator paths return 0–100, while a few older integrations
        # used 0–10. Normalize those representations before rounding instead
        # of clipping every value above 5 to a false perfect score.
        if raw_score > 10:
            raw_score /= 20.0
        elif raw_score > 5:
            raw_score /= 2.0
        return max(0, min(5, int(round(raw_score))))
    except (TypeError, ValueError):
        raise ValueError("评测器未返回有效分数")


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


def _mark_submission_failed(submission_id: int, message: str) -> None:
    """Mark one submission failed in the already-bound database."""

    submission = db.session.get(Submission, submission_id)
    if submission is None:
        return
    submission.status = "failed"
    submission.feedback = message
    db.session.commit()


def evaluate_submission_async(app, submission_id, assignment_title, demo_run_id=None):
    """异步评测学生提交的代码。

    ``demo_run_id`` 为空时使用正式数据库；公开体验传入该值后，线程会
    先切换到对应的临时数据库，并在会话失效时直接停止。
    """

    def _evaluate():
        with app.app_context():
            if demo_run_id and not activate_demo_run(demo_run_id):
                print(f"公开体验会话已失效，跳过提交评测: {demo_run_id}")
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

                print(f"开始后台评估提交 {submission_id}，题目: {assignment_title}")

                # 1. AI 基础评估。公开体验不接受默认分数，AI 失败必须
                # 让提交进入 failed，方便前端提示用户重新提交。
                try:
                    score, feedback = evaluate_cpp_code(
                        code, assignment_title=assignment_title
                    )
                    score = _normalise_score(score)

                    if hasattr(llm_evaluator, "_last_structured_data"):
                        structured_data = llm_evaluator._last_structured_data
                        if structured_data:
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
                    print(f"AI 评估过程出错: {ai_error}")
                    if demo_run_id:
                        raise RuntimeError("AI 评测失败，请稍后重试") from ai_error
                    # 正式账户保留历史兼容行为；公开体验永远不会走到这条
                    # 默认分支，避免把失败伪装成成功分数。
                    submission.score = 1
                    submission.feedback = f"AI 评估过程中出错: {ai_error}"

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
                                * 5
                            )
                            final_score = sandbox_score
                            if sandbox_result["status"] == "error":
                                final_score = min(final_score, 1)
                            submission.score = _normalise_score(final_score)
                            print(
                                "沙箱评判完成: "
                                f"{submission.sandbox_passed}/{submission.sandbox_total}, "
                                f"最终得分: {submission.score}"
                            )
                except Exception as sandbox_error:
                    print(f"沙箱评判过程出错: {sandbox_error}")
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
                                assignment_score=submission.score * 20,
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
                                    assignment_score=submission.score * 20,
                                    difficulty=kp_data.get("difficulty", 1.0),
                                    weight=kp_data.get("weight", 1.0),
                                )
                except Exception as kp_error:
                    print(f"更新知识点评分失败: {kp_error}")
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
                    print(f"已触发学生 {student_id} 的能力分析刷新")
                except Exception as ability_error:
                    print(f"触发能力分析失败: {ability_error}")
                    if demo_run_id:
                        raise RuntimeError("能力分析任务启动失败") from ability_error

                if not _demo_database_is_available(demo_run_id):
                    return
                db.session.commit()

                # 公开体验不写正式系统日志，也不把临时访客动作混入
                # 管理端审计数据。
                if not demo_run_id:
                    SystemLog.add_log(
                        log_type="评测完成",
                        content=(
                            f"提交 {submission_id} 评测已完成，"
                            f"得分：{submission.score}/5"
                        ),
                        user_id=student_id,
                        icon="bi bi-check-circle-fill",
                    )
                print(f"提交 {submission_id} 评测全部完成")

            except Exception as error:
                print(f"评测线程崩溃: {error}")
                traceback.print_exc()
                if not _demo_database_is_available(demo_run_id):
                    return
                try:
                    db.session.rollback()
                    _mark_submission_failed(
                        submission_id,
                        "AI 评测失败，请稍后重试。" if demo_run_id else f"后台评测发生严重错误: {error}",
                    )
                except Exception:
                    db.session.rollback()
                    traceback.print_exc()

    thread = threading.Thread(target=_evaluate)
    thread.daemon = True
    thread.start()
    print(f"已启动后台评测线程 - 提交 ID: {submission_id}")
    return thread
