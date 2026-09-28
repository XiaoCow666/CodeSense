from collections import defaultdict
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from flask_login import current_user, login_required
from openpyxl import Workbook
from sqlalchemy import and_, func, or_
from werkzeug.utils import secure_filename

from models import Class, Submission, ThinkingSession, ThinkingStageLog, User
from services.course_grading import build_gradebook
from utils.auth import admin_or_teacher_required
from utils.export_safety import safe_export_cell


grades = Blueprint('grades', __name__)


def _accessible_classes():
    if current_user.is_admin:
        return Class.query.order_by(Class.name.asc()).all()
    return current_user.managed_classes.order_by(Class.name.asc()).all()


def _students_for_classes(classes, selected_class_id=None):
    if selected_class_id:
        classes = [cls for cls in classes if cls.id == selected_class_id]

    class_ids = [cls.id for cls in classes]
    class_names = [cls.name for cls in classes]
    if not class_ids and not class_names:
        return []

    filters = []
    if class_ids:
        filters.append(User.class_id.in_(class_ids))
    if class_names:
        # class_id is authoritative for newer records.  Only fall back to
        # the legacy class_name field when no foreign-key relationship exists;
        # a stale name must not make a student appear in another teacher's
        # gradebook.
        filters.append(and_(User.class_id.is_(None), User.class_name.in_(class_names)))

    return User.query.filter(
        User.usertype == '学生',
        or_(*filters),
    ).order_by(User.class_name.asc(), User.student_id.asc()).all()


def _group_by_student(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.student_id].append(row)
    return grouped


def _thinking_log_metrics(session_ids):
    if not session_ids:
        return {}

    rows = (
        ThinkingStageLog.query.with_entities(
            ThinkingStageLog.session_id,
            func.count(ThinkingStageLog.id).label('log_count'),
            func.min(ThinkingStageLog.created_at).label('first_at'),
            func.max(ThinkingStageLog.created_at).label('last_at'),
        )
        .filter(ThinkingStageLog.session_id.in_(session_ids))
        .group_by(ThinkingStageLog.session_id)
        .all()
    )

    return {
        row.session_id: {
            'count': row.log_count,
            'first_at': row.first_at,
            'last_at': row.last_at,
        }
        for row in rows
    }


def _gradebook_context():
    classes = _accessible_classes()
    selected_class_id = request.args.get('class_id', type=int)
    selected_class = None
    if selected_class_id:
        selected_class = next((cls for cls in classes if cls.id == selected_class_id), None)
        if selected_class is None:
            selected_class_id = None

    students = _students_for_classes(classes, selected_class_id)
    student_ids = [student.student_id for student in students]

    submissions = []
    thinking_sessions = []
    if student_ids:
        submissions = Submission.query.filter(Submission.student_id.in_(student_ids)).all()
        thinking_sessions = ThinkingSession.query.filter(ThinkingSession.student_id.in_(student_ids)).all()

    records, summary = build_gradebook(
        students,
        _group_by_student(submissions),
        _group_by_student(thinking_sessions),
        _thinking_log_metrics([session.id for session in thinking_sessions]),
    )

    return classes, selected_class_id, selected_class, records, summary


@grades.route('/grades')
@login_required
@admin_or_teacher_required
def grade_statistics():
    classes, selected_class_id, selected_class, records, summary = _gradebook_context()

    return render_template(
        'grades.html',
        classes=classes,
        selected_class_id=selected_class_id,
        selected_class=selected_class,
        records=records,
        summary=summary,
    )


@grades.route('/grades/export')
@login_required
@admin_or_teacher_required
def export_grade_statistics():
    _, selected_class_id, selected_class, records, summary = _gradebook_context()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '成绩统计'
    sheet.append([
        '学号', '姓名', '班级', '正式作业数', '提交次数', '最高正式分',
        '引导式次数', '引导式用时(分钟)', '课设分(100分制)', '评分说明'
    ])

    for record in records:
        sheet.append([
            safe_export_cell(record['student_id']),
            safe_export_cell(record['student_name']),
            safe_export_cell(record['class_name']),
            safe_export_cell(record['formal_assignment_count']),
            safe_export_cell(record['formal_submission_count']),
            safe_export_cell(
                record['best_formal_score']
                if record['best_formal_score'] is not None else ''
            ),
            safe_export_cell(record['guided_session_count']),
            safe_export_cell(record['guided_minutes']),
            safe_export_cell(record['course_score']),
            safe_export_cell(record['reason']),
        ])

    sheet.append([])
    sheet.append(['统计', '学生总数', summary['student_count']])
    sheet.append(['统计', '有使用记录', summary['used_count']])
    sheet.append(['统计', '暂无记录', summary['unused_count']])
    sheet.append(['统计', '平均课设分', summary['average_score']])

    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or '')) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 10), 40)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    suffix = selected_class.name if selected_class_id and selected_class else '全部班级'
    safe_suffix = secure_filename(suffix) or 'all_classes'
    return send_file(
        output,
        as_attachment=True,
        download_name=f'grade_statistics-{safe_suffix}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
