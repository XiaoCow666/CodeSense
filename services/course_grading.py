from datetime import datetime

from utils.access import authoritative_class_name


POLICY_NAME = 'trial_usage_friendly_v1'


def _safe_score(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _log_metric_for(session_id, thinking_log_counts):
    raw = (thinking_log_counts or {}).get(session_id, 0)
    if isinstance(raw, dict):
        return {
            'count': int(raw.get('count') or 0),
            'first_at': raw.get('first_at'),
            'last_at': raw.get('last_at'),
        }
    return {'count': int(raw or 0), 'first_at': None, 'last_at': None}


def _minutes_between(start, end):
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return 0
    seconds = int((end - start).total_seconds())
    if seconds <= 0:
        return 0
    return max(1, round(seconds / 60))


def _guided_minutes(session, log_metric):
    seconds = int(getattr(session, 'total_time_seconds', None) or 0)
    if seconds > 0:
        return max(1, round(seconds / 60))

    completed_minutes = _minutes_between(
        getattr(session, 'started_at', None),
        getattr(session, 'completed_at', None),
    )
    if completed_minutes:
        return completed_minutes

    log_minutes = _minutes_between(log_metric.get('first_at'), log_metric.get('last_at'))
    if log_minutes:
        return log_minutes

    return 1 if log_metric.get('count', 0) > 0 else 0


def _has_guided_evidence(session, log_metric):
    return any([
        getattr(session, 'started_at', None),
        getattr(session, 'completed_at', None),
        getattr(session, 'total_time_seconds', 0),
        getattr(session, 'stage1_score', None) is not None,
        getattr(session, 'current_stage', 1) and getattr(session, 'current_stage', 1) > 1,
        getattr(session, 'stage2_completed', False),
        getattr(session, 'stage3_completed', False),
        getattr(session, 'status', '') == 'completed',
        log_metric.get('count', 0) > 0,
    ])


def _format_best_score(score):
    if score is None:
        return '-'
    if float(score).is_integer():
        return str(int(score))
    return f'{score:.1f}'


def trial_usage_friendly_v1(student, submissions, thinking_sessions, thinking_log_counts=None):
    submissions = list(submissions or [])
    thinking_sessions = list(thinking_sessions or [])
    thinking_log_counts = thinking_log_counts or {}

    assignment_ids = {
        getattr(submission, 'assignment_id', None)
        for submission in submissions
        if getattr(submission, 'assignment_id', None) is not None
    }
    scored_values = [
        score for score in (_safe_score(getattr(submission, 'score', None)) for submission in submissions)
        if score is not None
    ]
    best_formal_score = max(scored_values) if scored_values else None

    guided_sessions = []
    guided_minutes = 0
    guided_log_count = 0
    completed_guided = False
    reached_stage_three = False
    passed_stage_two = False

    for session in thinking_sessions:
        session_id = getattr(session, 'id', None)
        log_metric = _log_metric_for(session_id, thinking_log_counts)
        if not _has_guided_evidence(session, log_metric):
            continue

        guided_sessions.append(session)
        guided_minutes += _guided_minutes(session, log_metric)
        guided_log_count += log_metric.get('count', 0)
        completed_guided = completed_guided or bool(
            getattr(session, 'stage3_completed', False) or getattr(session, 'status', '') == 'completed'
        )
        passed_stage_two = passed_stage_two or bool(getattr(session, 'stage2_completed', False))
        reached_stage_three = reached_stage_three or bool(getattr(session, 'current_stage', 1) >= 3)

    formal_submission_count = len(submissions)
    formal_assignment_count = len(assignment_ids)
    guided_session_count = len(guided_sessions)
    has_formal = formal_submission_count > 0
    has_guided = guided_session_count > 0

    if not has_formal and not has_guided:
        return {
            'student': student,
            'student_id': getattr(student, 'student_id', ''),
            'student_name': getattr(student, 'full_name', None) or getattr(student, 'username', ''),
            'class_name': authoritative_class_name(student) or '未分班',
            'course_score': 0,
            'formal_assignment_count': 0,
            'formal_submission_count': 0,
            'best_formal_score': None,
            'guided_session_count': 0,
            'guided_minutes': 0,
            'guided_log_count': 0,
            'used': False,
            'policy': POLICY_NAME,
            'reason': '暂无使用记录',
        }

    score = 8.0
    reason_parts = []

    if has_formal:
        score += min(1.0, formal_assignment_count * 0.35)
        if formal_submission_count >= 2:
            score += 0.2
        if formal_submission_count >= 4:
            score += 0.2
        if best_formal_score is not None:
            if best_formal_score >= 80:
                score += 0.4
            elif best_formal_score >= 60:
                score += 0.2
        reason_parts.append(
            f'完成 {formal_assignment_count} 个正式作业，提交 {formal_submission_count} 次，最高正式分 {_format_best_score(best_formal_score)}'
        )

    if has_guided:
        score += min(0.8, guided_session_count * 0.4)
        if guided_minutes >= 5:
            score += 0.4
        if guided_minutes >= 15:
            score += 0.4
        if passed_stage_two:
            score += 0.3
        if reached_stage_three:
            score += 0.3
        if completed_guided:
            score += 0.6
        guided_reason = f'参与 {guided_session_count} 次引导式学习，用时 {guided_minutes} 分钟'
        if completed_guided:
            guided_reason += '，已完成引导式学习'
        reason_parts.append(guided_reason)

    # 评分簿对外统一使用百分制；内部仍按原有 0–10 权重累加，最后只在出口换算。
    course_score = round(min(10.0, score) * 10, 1)

    return {
        'student': student,
        'student_id': getattr(student, 'student_id', ''),
        'student_name': getattr(student, 'full_name', None) or getattr(student, 'username', ''),
        'class_name': authoritative_class_name(student) or '未分班',
        'course_score': course_score,
        'formal_assignment_count': formal_assignment_count,
        'formal_submission_count': formal_submission_count,
        'best_formal_score': best_formal_score,
        'guided_session_count': guided_session_count,
        'guided_minutes': guided_minutes,
        'guided_log_count': guided_log_count,
        'used': True,
        'policy': POLICY_NAME,
        'reason': '；'.join(reason_parts),
    }


def build_gradebook(
    students,
    submissions_by_student,
    thinking_sessions_by_student,
    thinking_log_counts_by_session=None,
):
    records = [
        trial_usage_friendly_v1(
            student,
            submissions_by_student.get(getattr(student, 'student_id', ''), []),
            thinking_sessions_by_student.get(getattr(student, 'student_id', ''), []),
            thinking_log_counts_by_session or {},
        )
        for student in students
    ]

    records.sort(key=lambda item: (-item['course_score'], item['class_name'], item['student_id']))

    student_count = len(records)
    used_count = len([record for record in records if record['used']])
    total_score = sum(record['course_score'] for record in records)
    average_score = round(total_score / student_count, 1) if student_count else 0

    return records, {
        'student_count': student_count,
        'used_count': used_count,
        'unused_count': student_count - used_count,
        'average_score': average_score,
        'policy': POLICY_NAME,
    }
