"""后台能力分析任务。

公开体验的分析任务必须携带自己的 demo run id。这样后台线程即使在
请求结束后才执行，也只会查询和写入该体验会话的临时数据库。
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime

from models import AbilityTrend, Submission, db
from services.ai_evaluator import AIEvaluator
from services.api_keys import api_keys
from services.demo_database import activate_demo_run, is_active_demo_run


def _demo_database_is_available(demo_run_id: str | None) -> bool:
    """Return whether a demo worker may still touch its temporary database."""

    return not demo_run_id or is_active_demo_run(demo_run_id)


def _mark_analysis_failed(student_id: str) -> None:
    """Persist an explicit failure without leaving stale AI text visible."""

    trend = AbilityTrend.get_or_create(student_id)
    if trend is None:
        return
    trend.status = "failed"
    trend.analysis_markdown = None
    trend.last_updated = datetime.utcnow()
    db.session.commit()


def generate_ability_analysis_async(app, student_id, demo_run_id=None):
    """异步生成学生能力分析。

    ``demo_run_id`` 为空时保持正式账户的原有行为；传入时，线程启动后
    会先绑定对应的临时数据库，若会话已经退出或过期则直接结束，不触碰
    正式数据库。
    """

    def _generate():
        with app.app_context():
            if demo_run_id and not activate_demo_run(demo_run_id):
                print(f"公开体验会话已失效，跳过能力分析任务: {demo_run_id}")
                return

            try:
                # 任何业务查询前都再次确认临时库仍然存在。退出体验时，
                # destroy_demo_run 会把运行从缓存移除，避免后台线程继续写入。
                if not _demo_database_is_available(demo_run_id):
                    return

                AbilityTrend.mark_as_processing(student_id)

                submissions = (
                    Submission.query.filter_by(student_id=student_id)
                    .order_by(Submission.submitted_at.desc())
                    .limit(20)
                    .all()
                )

                if not submissions:
                    if _demo_database_is_available(demo_run_id):
                        AbilityTrend.update_analysis(
                            student_id=student_id,
                            analysis_markdown="暂无提交记录，请先完成一些作业。",
                            submissions_count=0,
                        )
                    return

                submission_data = []
                for submission in submissions:
                    if submission.code and submission.assignment:
                        submission_data.append(
                            {
                                "assignment_title": submission.assignment.title,
                                "code": submission.code[:500],
                                "score": submission.score,
                                "submitted_at": (
                                    submission.submitted_at.strftime("%Y-%m-%d %H:%M")
                                    if submission.submitted_at
                                    else "未知时间"
                                ),
                            }
                        )

                if not submission_data:
                    raise RuntimeError("没有可供 AI 分析的有效提交内容")

                api_key = api_keys.zhipu_key
                if not api_key:
                    raise RuntimeError("AI 服务未配置")

                ai_evaluator = AIEvaluator(api_key)
                analysis_markdown = ""
                print(f"开始后台生成能力分析 - 学生 {student_id}")

                last_error = None
                for attempt in range(2):
                    try:
                        analysis_markdown = ""
                        for chunk in ai_evaluator.analyze_ability_trend_stream(
                            submission_data
                        ):
                            if chunk:
                                analysis_markdown += chunk

                        if not analysis_markdown.strip():
                            raise RuntimeError("AI 未返回有效分析内容")
                        last_error = None
                        break
                    except Exception as chunk_error:
                        last_error = chunk_error
                        print(
                            f"生成能力分析失败（尝试 {attempt + 1}/2）: "
                            f"{chunk_error}"
                        )
                        if attempt == 0:
                            time.sleep(3)

                if last_error is not None:
                    raise last_error

                if not _demo_database_is_available(demo_run_id):
                    return

                AbilityTrend.update_analysis(
                    student_id=student_id,
                    analysis_markdown=analysis_markdown.strip(),
                    submissions_count=len(submissions),
                )
                print(
                    f"能力分析生成完成 - 学生 {student_id}, "
                    f"长度: {len(analysis_markdown)} 字符"
                )

            except Exception as error:
                print(f"生成能力分析失败 - 学生 {student_id}: {error}")
                traceback.print_exc()

                # 失败处理仍在已经绑定的会话中执行。临时库被销毁时，
                # 直接结束，绝不重新打开默认正式数据库。
                if not _demo_database_is_available(demo_run_id):
                    return
                try:
                    db.session.rollback()
                    _mark_analysis_failed(student_id)
                except Exception:
                    db.session.rollback()
                    traceback.print_exc()

    thread = threading.Thread(target=_generate)
    thread.daemon = True
    thread.start()
    print(f"已启动后台分析任务 - 学生 {student_id}")
    return thread


def trigger_analysis_if_needed(student_id, force=False, demo_run_id=None):
    """检查并触发能力分析。

    对公开体验而言，调用方必须显式传入当前 run id。未找到该临时库时
    返回 ``False``，不会因为查询不到临时数据而误读正式库。
    """

    from flask import current_app

    if demo_run_id and not _demo_database_is_available(demo_run_id):
        return False

    trend = AbilityTrend.query.filter_by(student_id=student_id).first()

    if force or not trend or trend.status in ["pending", "outdated", "failed"]:
        generate_ability_analysis_async(
            current_app._get_current_object(),
            student_id,
            demo_run_id=demo_run_id,
        )
        return True

    if trend.status == "processing":
        return False

    return False
