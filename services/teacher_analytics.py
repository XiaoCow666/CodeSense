from datetime import datetime as dt, time, timedelta

from models import Assignment, Class, StudentRoster, Submission, User, db


ACTIVE_WINDOW_DAYS = 7
LOW_SCORE_THRESHOLD = 3.0
EXCELLENT_SCORE_THRESHOLD = 4.0


def _student_ids(students):
    return [student.student_id for student in students]


def _latest_submissions_by_student(student_ids):
    if not student_ids:
        return {}

    submissions = Submission.query.filter(
        Submission.student_id.in_(student_ids)
    ).order_by(Submission.submitted_at.desc()).all()

    latest = {}
    for submission in submissions:
        latest.setdefault(submission.student_id, submission)
    return latest


def _submission_counts_by_student(student_ids):
    if not student_ids:
        return {}

    rows = db.session.query(
        Submission.student_id,
        db.func.count(Submission.id),
    ).filter(
        Submission.student_id.in_(student_ids)
    ).group_by(Submission.student_id).all()
    return {student_id: count for student_id, count in rows}


def _assigned_assignments_for_class(cls, limit=None):
    query = Assignment.query.filter(
        Assignment.target_classes.contains(cls.name)
    ).order_by(Assignment.created_time.desc())
    assignments = query.limit(limit).all() if limit else query.all()
    return [
        assignment for assignment in assignments
        if cls.name in assignment.get_target_class_list()
    ]


def _latest_assignment_for_class(cls):
    assignments = _assigned_assignments_for_class(cls, limit=10)
    return assignments[0] if assignments else None


def _assignment_completion(cls, assignment, students):
    total = len(students)
    if not assignment or total == 0:
        return 0, total, 0.0

    student_ids = _student_ids(students)
    completed = db.session.query(Submission.student_id).filter(
        Submission.assignment_id == assignment.id,
        Submission.student_id.in_(student_ids),
    ).distinct().count()
    rate = round(completed / total * 100, 1) if total else 0.0
    return completed, total, rate


def build_submission_trend(student_ids, days=14, now=None):
    """Build daily submission counts for the teacher dashboard trend chart."""
    now = now or dt.utcnow()
    end_date = now.date()
    start_date = end_date - timedelta(days=days - 1)
    buckets = {
        (start_date + timedelta(days=offset)): 0
        for offset in range(days)
    }

    if student_ids:
        submissions = Submission.query.filter(
            Submission.student_id.in_(student_ids),
            Submission.submitted_at >= dt.combine(start_date, time.min),
            Submission.submitted_at <= dt.combine(end_date, time.max),
        ).all()
        for submission in submissions:
            submitted_date = submission.submitted_at.date()
            if submitted_date in buckets:
                buckets[submitted_date] += 1

    return [
        {
            'date': day.isoformat(),
            'label': day.strftime('%m-%d'),
            'count': buckets[day],
        }
        for day in sorted(buckets)
    ]


def _cell_status(best_score, submitted):
    if not submitted:
        return '缺交'
    if best_score is not None and best_score < LOW_SCORE_THRESHOLD:
        return '低分'
    if best_score is not None and best_score >= EXCELLENT_SCORE_THRESHOLD:
        return '优秀'
    return '已交'


def build_assignment_completion_matrix(cls, students=None, assignment_limit=5):
    """Build a recent-assignment completion matrix for a class."""
    if students is None:
        students = cls.students.filter_by(usertype='学生')\
            .order_by(User.user_ascore.desc())\
            .all()
    else:
        students = list(students)

    assignments = _assigned_assignments_for_class(cls, limit=assignment_limit)
    student_ids = _student_ids(students)
    assignment_ids = [assignment.id for assignment in assignments]

    submissions_by_key = {}
    if student_ids and assignment_ids:
        submissions = Submission.query.filter(
            Submission.student_id.in_(student_ids),
            Submission.assignment_id.in_(assignment_ids),
        ).all()
        for submission in submissions:
            key = (submission.student_id, submission.assignment_id)
            current = submissions_by_key.get(key)
            if current is None:
                submissions_by_key[key] = submission
            elif submission.score is not None and (
                current.score is None or submission.score > current.score
            ):
                submissions_by_key[key] = submission

    rows = []
    for student in students:
        cells = []
        completed_count = 0
        for assignment in assignments:
            submission = submissions_by_key.get((student.student_id, assignment.id))
            submitted = submission is not None
            if submitted:
                completed_count += 1
            best_score = submission.score if submission else None
            status = _cell_status(best_score, submitted)
            cells.append({
                'assignment': assignment,
                'submitted': submitted,
                'best_score': best_score,
                'status': status,
                'status_class': {
                    '优秀': 'excellent',
                    '已交': 'submitted',
                    '低分': 'low',
                    '缺交': 'missing',
                }[status],
            })
        rows.append({
            'student': student,
            'cells': cells,
            'completed_count': completed_count,
            'total_count': len(assignments),
        })

    summary = []
    for assignment in assignments:
        completed = len([
            row for row in rows
            if any(cell['assignment'].id == assignment.id and cell['submitted'] for cell in row['cells'])
        ])
        total = len(students)
        summary.append({
            'assignment': assignment,
            'completed': completed,
            'total': total,
            'completion_rate': round(completed / total * 100, 1) if total else 0.0,
        })

    return {
        'assignments': assignments,
        'rows': rows,
        'summary': summary,
    }


def _risk_tags_for_student(student, latest_submission, submission_count, now):
    tags = []
    inactive_before = now - timedelta(days=ACTIVE_WINDOW_DAYS)

    if submission_count == 0:
        tags.append('未提交')
    elif latest_submission and latest_submission.submitted_at < inactive_before:
        tags.append('近期未活跃')

    latest_score = latest_submission.score if latest_submission else None
    if (
        student.user_ascore is not None
        and 0 < student.user_ascore < LOW_SCORE_THRESHOLD
    ) or (
        latest_score is not None
        and latest_score < LOW_SCORE_THRESHOLD
    ):
        tags.append('低分')

    return tags


def _status_for_student(student, tags):
    if '未提交' in tags:
        return '未开始'
    if tags:
        return '需关注'
    if student.user_ascore is not None and student.user_ascore >= EXCELLENT_SCORE_THRESHOLD:
        return '优秀'
    return '正常'


def build_class_learning_rows(cls, students=None, now=None):
    """Build per-student learning status rows for a class."""
    now = now or dt.utcnow()
    if students is None:
        students = cls.students.filter_by(usertype='学生')\
            .order_by(User.user_ascore.desc())\
            .all()
    else:
        students = list(students)

    student_ids = _student_ids(students)
    latest_by_student = _latest_submissions_by_student(student_ids)
    count_by_student = _submission_counts_by_student(student_ids)

    rows = []
    for student in students:
        latest_submission = latest_by_student.get(student.student_id)
        submission_count = count_by_student.get(student.student_id, 0)
        tags = _risk_tags_for_student(student, latest_submission, submission_count, now)
        rows.append({
            'student': student,
            'submit_count': submission_count,
            'latest_submission': latest_submission,
            'latest_score': latest_submission.score if latest_submission else None,
            'latest_submitted_at': latest_submission.submitted_at if latest_submission else None,
            'status': _status_for_student(student, tags),
            'risk_tags': tags,
        })
    return rows


def build_teacher_dashboard_data(teacher, now=None):
    """Aggregate teacher-facing learning data for dashboard rendering."""
    now = now or dt.utcnow()
    managed_classes = teacher.managed_classes.all()
    class_ids = [cls.id for cls in managed_classes]

    if class_ids:
        students = User.query.filter(
            User.usertype == '学生',
            User.class_id.in_(class_ids),
        ).all()
    else:
        students = []

    student_ids = _student_ids(students)
    recent_submissions = Submission.query.filter(
        Submission.student_id.in_(student_ids)
    ).order_by(Submission.submitted_at.desc()).limit(10).all() if student_ids else []
    total_submissions = Submission.query.filter(
        Submission.student_id.in_(student_ids)
    ).count() if student_ids else 0

    rows_by_student_id = {
        row['student'].student_id: row
        for cls in managed_classes
        for row in build_class_learning_rows(cls, now=now)
    }

    low_score_rows = [
        row for row in rows_by_student_id.values()
        if '低分' in row['risk_tags']
    ]
    inactive_rows = [
        row for row in rows_by_student_id.values()
        if '近期未活跃' in row['risk_tags'] or '未提交' in row['risk_tags']
    ]
    no_submission_rows = [
        row for row in rows_by_student_id.values()
        if '未提交' in row['risk_tags']
    ]
    unregistered_roster_count = StudentRoster.query.filter(
        StudentRoster.class_id.in_(class_ids),
        StudentRoster.is_registered.is_(False),
    ).count() if class_ids else 0

    class_cards = []
    for cls in managed_classes:
        class_students = cls.students.filter_by(usertype='学生').all()
        class_rows = build_class_learning_rows(cls, students=class_students, now=now)
        latest_assignment = _latest_assignment_for_class(cls)
        completed, total, completion_rate = _assignment_completion(
            cls, latest_assignment, class_students
        )
        active_count = len([
            row for row in class_rows
            if row['latest_submitted_at']
            and row['latest_submitted_at'] >= now - timedelta(days=ACTIVE_WINDOW_DAYS)
        ])
        risk_count = len([row for row in class_rows if row['risk_tags']])
        low_score_count = len([row for row in class_rows if '低分' in row['risk_tags']])
        inactive_count = len([
            row for row in class_rows
            if '近期未活跃' in row['risk_tags'] or '未提交' in row['risk_tags']
        ])
        class_cards.append({
            'class': cls,
            'student_count': len(class_students),
            'active_count': active_count,
            'active_rate': round(active_count / len(class_students) * 100, 1) if class_students else 0.0,
            'risk_count': risk_count,
            'low_score_count': low_score_count,
            'inactive_count': inactive_count,
            'latest_assignment': latest_assignment,
            'latest_completed': completed,
            'latest_total': total,
            'completion_rate': completion_rate,
        })

    chart_data = {
        'labels': [cls.name for cls in managed_classes],
        'sizes': [card['student_count'] for card in class_cards],
        'scores': [round(cls.get_statistics().get('avg_score', 0), 1) for cls in managed_classes],
    }

    return {
        'managed_classes': managed_classes,
        'student_count': len(students),
        'student_rows': sorted(
            rows_by_student_id.values(),
            key=lambda row: (row['student'].user_ascore or 0),
            reverse=True,
        ),
        'total_submissions': total_submissions,
        'recent_submissions': recent_submissions,
        'submission_trend': build_submission_trend(student_ids, days=14, now=now),
        'class_cards': class_cards,
        'attention': {
            'low_score_count': len(low_score_rows),
            'inactive_count': len(inactive_rows),
            'no_submission_count': len(no_submission_rows),
            'unregistered_roster_count': unregistered_roster_count,
            'low_score_rows': low_score_rows[:6],
            'inactive_rows': inactive_rows[:6],
            'no_submission_rows': no_submission_rows[:6],
        },
        'chart_data': chart_data,
    }
