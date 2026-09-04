"""后台能力分析任务。

公开体验的分析任务必须携带自己的 demo run id。这样后台线程即使在
请求结束后才执行，也只会查询和写入该体验会话的临时数据库。
"""

from __future__ import annotations

import threading
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import joinedload

from models import AbilityTrend, Submission, db
from services.ai_evaluator import AIEvaluator
from services.api_keys import api_keys
from services.demo_database import activate_demo_run, is_active_demo_run


_ACTIVE_ANALYSES = set()
_ACTIVE_ANALYSES_LOCK = threading.RLock()


def _analysis_key(student_id, demo_run_id=None):
    return (str(demo_run_id or "formal"), str(student_id))


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


def _mark_analysis_queued(trend_id: int, previous_status: str, previous_updated) -> bool:
    """Reserve the DB state before enqueueing, guarded by the observed version."""

    if previous_status not in {"pending", "outdated", "failed", "completed"}:
        return False

    updated_guard = (
        AbilityTrend.last_updated.is_(None)
        if previous_updated is None
        else AbilityTrend.last_updated == previous_updated
    )

    result = db.session.execute(
        update(AbilityTrend)
        .where(
            AbilityTrend.id == int(trend_id),
            AbilityTrend.status == previous_status,
            updated_guard,
        )
        .values(status="processing", last_updated=datetime.utcnow())
    )
    db.session.commit()
    return bool(result.rowcount)


def _run_analysis(student_id, demo_run_id=None, *, propagate_failure=False):
    """Run one analysis in the already-selected application/database context."""

    if demo_run_id and not activate_demo_run(demo_run_id):
        return "expired"

    try:
        # Any business query happens only after a demo database has been bound.
        if not _demo_database_is_available(demo_run_id):
            return "expired"

        AbilityTrend.mark_as_processing(student_id)
        submissions = (
            Submission.query.options(joinedload(Submission.assignment))
            .filter_by(student_id=student_id)
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
            return "completed"

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
            raise RuntimeError("no valid submissions for ability analysis")

        api_key = api_keys.zhipu_key or api_keys.openai_key
        if not api_key:
            raise RuntimeError("AI service unavailable")

        # Formal jobs use the shared provider router.  Demo tests / temporary
        # databases retain their injected evaluator contract and never enter
        # the external durable queue.
        if not demo_run_id:
            from services.llm_client import SharedLLMClient

            if not SharedLLMClient().is_available():
                raise RuntimeError("AI service unavailable")

        ai_evaluator = AIEvaluator(api_key)
        analysis_markdown = ""
        print("开始后台生成能力分析")

        # Provider retry/fallback stays in SharedLLMClient.  RQ deliberately
        # has no whole-job retry because a worker crash after provider success
        # cannot prove that replaying the model call is safe or free.
        for chunk in ai_evaluator.analyze_ability_trend_stream(submission_data):
            if chunk:
                analysis_markdown += chunk

        if not analysis_markdown.strip():
            raise RuntimeError("AI returned an empty ability analysis")

        if not _demo_database_is_available(demo_run_id):
            return "expired"

        AbilityTrend.update_analysis(
            student_id=student_id,
            analysis_markdown=analysis_markdown.strip(),
            submissions_count=len(submissions),
        )
        print("能力分析生成完成")
        return "completed"
    except Exception as error:
        # Do not copy provider error bodies, student ids, prompts, or code to
        # logs / RQ failure records.
        print(f"生成能力分析失败: {type(error).__name__}")
        if not _demo_database_is_available(demo_run_id):
            return "expired"
        try:
            db.session.rollback()
            _mark_analysis_failed(student_id)
        except Exception:
            db.session.rollback()
        if propagate_failure:
            raise RuntimeError("ability analysis failed") from None
        return "failed"


def run_formal_ability_analysis(trend_id):
    """RQ entry point; the standalone worker supplies the Flask app context."""

    trend = db.session.get(AbilityTrend, int(trend_id))
    if trend is None:
        raise RuntimeError("ability trend no longer exists")
    return _run_analysis(trend.student_id, propagate_failure=True)


def generate_ability_analysis_async(app, student_id, demo_run_id=None):
    """Keep the legacy thread runner for demo isolation and safe rollback."""

    key = _analysis_key(student_id, demo_run_id)
    with _ACTIVE_ANALYSES_LOCK:
        if key in _ACTIVE_ANALYSES:
            return None
        _ACTIVE_ANALYSES.add(key)

    def _generate():
        try:
            with app.app_context():
                _run_analysis(student_id, demo_run_id)
        finally:
            with _ACTIVE_ANALYSES_LOCK:
                _ACTIVE_ANALYSES.discard(key)

    thread = threading.Thread(target=_generate)
    thread.daemon = True
    thread.start()
    print("已启动后台分析任务")
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

    if not demo_run_id and current_app.config.get(
        "ABILITY_ANALYSIS_QUEUE_BACKEND", "thread"
    ) == "rq":
        from tasks.ability_queue import (
            AbilityQueueUnavailable,
            enqueue_formal_ability_analysis,
            get_formal_ability_job_status,
        )
        app = current_app._get_current_object()

        if trend and trend.status == "processing":
            try:
                job_status = get_formal_ability_job_status(app, trend.id)
            except AbilityQueueUnavailable:
                job_status = "failed"
            if job_status in {"created", "queued", "started", "deferred", "scheduled"}:
                return False
            _mark_analysis_failed(student_id)
            if not force:
                return False

        should_enqueue = (
            force
            or not trend
            or trend.status in ["pending", "outdated"]
        )
        # A failed provider/worker attempt requires the explicit refresh action.
        # Normal page loads must not replay a paid model call automatically.
        if trend and trend.status == "failed" and not force:
            should_enqueue = False

        if should_enqueue:
            trend = trend or AbilityTrend.get_or_create(student_id)
            previous_status = trend.status
            previous_updated = trend.last_updated
            # Reserve the domain state before the job can run.  A conditional
            # update prevents a stale request from enqueueing after another
            # process has already published a newer result.  Doing this before
            # enqueue also avoids MySQL DATETIME precision races where a fast
            # completion can share the same rounded timestamp.
            if not _mark_analysis_queued(
                trend.id,
                previous_status=previous_status,
                previous_updated=previous_updated,
            ):
                return False
            try:
                job = enqueue_formal_ability_analysis(app, trend.id)
            except AbilityQueueUnavailable:
                current_app.logger.warning(
                    "正式账号能力分析队列不可用；未回退到 Web 进程线程"
                )
                _mark_analysis_failed(student_id)
                return False
            return job.created
        return False

    key = _analysis_key(student_id, demo_run_id)
    with _ACTIVE_ANALYSES_LOCK:
        if key in _ACTIVE_ANALYSES:
            return False

    if force or not trend or trend.status in ["pending", "outdated", "failed"]:
        thread = generate_ability_analysis_async(
            current_app._get_current_object(),
            student_id,
            demo_run_id=demo_run_id,
        )
        return thread is not None

    if trend.status == "processing":
        return False

    return False
