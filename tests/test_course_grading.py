from datetime import datetime, timedelta
from types import SimpleNamespace

from services.course_grading import build_gradebook, trial_usage_friendly_v1


def student(student_id='s1', username='student1', full_name='Student One', class_name='Class A'):
    return SimpleNamespace(
        student_id=student_id,
        username=username,
        full_name=full_name,
        class_name=class_name,
    )


def submission(assignment_id=1, score=80):
    return SimpleNamespace(assignment_id=assignment_id, score=score)


def thinking_session(
    session_id=1,
    stage=1,
    total_time_seconds=0,
    status='in_progress',
    stage2_completed=False,
    stage3_completed=False,
    started_at=None,
    completed_at=None,
    stage1_score=None,
):
    return SimpleNamespace(
        id=session_id,
        current_stage=stage,
        total_time_seconds=total_time_seconds,
        status=status,
        stage2_completed=stage2_completed,
        stage3_completed=stage3_completed,
        started_at=started_at,
        completed_at=completed_at,
        stage1_score=stage1_score,
    )


def test_trial_policy_gives_zero_without_any_activity():
    result = trial_usage_friendly_v1(student(), [], [], {})

    assert result['course_score'] == 0
    assert result['formal_submission_count'] == 0
    assert result['guided_session_count'] == 0
    assert '暂无使用记录' in result['reason']


def test_trial_policy_gives_high_score_for_formal_submission_only():
    result = trial_usage_friendly_v1(
        student(),
        [submission(assignment_id=1, score=72)],
        [],
        {},
    )

    assert result['course_score'] >= 80
    assert result['formal_assignment_count'] == 1
    assert result['formal_submission_count'] == 1
    assert result['best_formal_score'] == 72
    assert '正式作业' in result['reason']


def test_trial_policy_gives_high_score_for_guided_learning_only_with_log_evidence():
    session = thinking_session(session_id=10, stage=1, total_time_seconds=0)

    result = trial_usage_friendly_v1(student(), [], [session], {10: 3})

    assert result['course_score'] >= 80
    assert result['guided_session_count'] == 1
    assert result['guided_log_count'] == 3
    assert '引导式学习' in result['reason']


def test_trial_policy_rewards_completed_guided_learning_near_full_score():
    started = datetime(2026, 7, 6, 9, 0, 0)
    completed = started + timedelta(minutes=24)
    session = thinking_session(
        session_id=11,
        stage=3,
        total_time_seconds=1440,
        status='completed',
        stage2_completed=True,
        stage3_completed=True,
        started_at=started,
        completed_at=completed,
        stage1_score=90,
    )

    result = trial_usage_friendly_v1(student(), [], [session], {11: 8})

    assert result['course_score'] >= 95
    assert result['course_score'] <= 100
    assert result['guided_minutes'] == 24
    assert '已完成引导式学习' in result['reason']


def test_trial_policy_caps_combined_activity_at_ten():
    session = thinking_session(
        session_id=12,
        stage=3,
        total_time_seconds=3600,
        status='completed',
        stage2_completed=True,
        stage3_completed=True,
    )
    formal_submissions = [
        submission(assignment_id=1, score=100),
        submission(assignment_id=1, score=95),
        submission(assignment_id=2, score=98),
        submission(assignment_id=3, score=92),
    ]

    result = trial_usage_friendly_v1(student(), formal_submissions, [session], {12: 12})

    assert result['course_score'] == 100
    assert '正式作业' in result['reason']
    assert '引导式学习' in result['reason']


def test_build_gradebook_returns_records_and_summary():
    students = [student('s1'), student('s2')]
    submissions_by_student = {'s1': [submission(assignment_id=1, score=88)]}
    thinking_by_student = {'s2': [thinking_session(session_id=20, total_time_seconds=600)]}

    records, summary = build_gradebook(
        students,
        submissions_by_student,
        thinking_by_student,
        {20: 2},
    )

    assert len(records) == 2
    assert summary['student_count'] == 2
    assert summary['used_count'] == 2
    assert summary['unused_count'] == 0
    assert summary['average_score'] >= 80
