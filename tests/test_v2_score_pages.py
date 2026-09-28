from datetime import datetime

import pytest

from app import create_app
from config import config
from models import Assignment, Class, Submission, User, db
from services.teacher_analytics import build_assignment_completion_matrix, build_class_learning_rows


@pytest.fixture
def score_pages(tmp_path):
    config['testing'].SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'scores.db'}"
    app = create_app('testing')
    client = app.test_client()
    with app.app_context():
        db.create_all()
        classroom = Class(name='评分测试班', grade='2026', major='计算机')
        db.session.add(classroom)
        db.session.flush()
        admin = User(
            student_id='score-admin', username='score-admin',
            usertype='管理员', full_name='评分管理员',
        )
        admin.password = 'score-page-password'
        student = User(
            student_id='score-student', username='score-student',
            usertype='学生', full_name='评分学生',
            class_id=classroom.id, class_name=classroom.name,
            submit_count=2, user_ascore=5,
        )
        student.password = 'score-page-password'
        assignment = Assignment(
            id=709, title='评分范围练习', description='检查历史和当前分数',
            creator_id='score-admin', target_classes=classroom.name,
            count=2, average_score=5,
        )
        db.session.add_all([admin, student, assignment])
        db.session.flush()
        db.session.add_all([
            Submission(
                student_id=student.student_id, assignment_id=assignment.id,
                code='int main() { return 0; }', score=5,
                status='evaluated', submitted_at=datetime(2026, 9, 17, 12),
            ),
            Submission(
                student_id=student.student_id, assignment_id=assignment.id,
                code='int main() { return 1; }', score=5,
                status='evaluated', submitted_at=datetime(2026, 9, 27, 12),
            ),
        ])
        db.session.commit()
    response = client.post('/login', data={
        'username': 'score-admin', 'password': 'score-page-password',
    })
    assert response.status_code == 302
    yield client
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def test_admin_score_pages_use_recorded_scale(score_pages):
    dashboard = score_pages.get('/admin_dashboard')
    assert dashboard.status_code == 200
    assert b'52.5' in dashboard.data

    users = score_pages.get('/users?search=score-student')
    assert users.status_code == 200
    assert b'52.50' in users.data

    assignments = score_pages.get('/assignments?search=评分范围')
    assert assignments.status_code == 200
    assert b'52.50' in assignments.data

    high = score_pages.get('/all_submissions?min_score=80')
    assert high.status_code == 200
    assert b'100.0' in high.data
    assert b'score-low">5.0<' not in high.data


def test_admin_export_entry_and_submission_values(score_pages):
    entry = score_pages.get('/export_data')
    assert entry.status_code == 200

    export = score_pages.get('/download_data/submissions?student_id=score-student')
    assert export.status_code == 200
    rows = export.data.decode('utf-8-sig').splitlines()
    assert len(rows) == 3
    assert any(',100.0,' in row for row in rows[1:])
    assert any(',5.0,' in row for row in rows[1:])

    question_bank = score_pages.get('/question-bank/export?format=csv')
    assert question_bank.status_code == 200
    assert '52.5' in question_bank.data.decode('utf-8-sig')


def test_class_statistics_and_assignment_ranking_use_recorded_scale(score_pages):
    classroom = score_pages.get('/classes/')
    assert classroom.status_code == 200
    assert b'52.5' in classroom.data

    detail = score_pages.get('/classes/1')
    assert detail.status_code == 200
    assert b'52.5' in detail.data

    assignment = score_pages.get('/classes/1/assignment/709')
    assert assignment.status_code == 200
    assert b'100.0' in assignment.data

    assignment_detail = score_pages.get('/view_assignment/709')
    assert assignment_detail.status_code == 200
    assert b'52.5' in assignment_detail.data

    with score_pages.application.app_context():
        cls = db.session.get(Class, 1)
        learning_row = build_class_learning_rows(cls)[0]
        assert learning_row['average_score'] == 52.5
        assert learning_row['latest_score'] == 5
        completion_row = build_assignment_completion_matrix(cls)['rows'][0]
        assert completion_row['cells'][0]['best_score'] == 100


def test_student_score_pages_keep_current_five_as_five(score_pages):
    assert score_pages.get('/logout').status_code == 302
    assert score_pages.post('/login', data={
        'username': 'score-student', 'password': 'score-page-password',
    }).status_code == 302

    home = score_pages.get('/home')
    assert home.status_code == 200
    assert b'52.5' in home.data

    history = score_pages.get('/submission-history/709')
    assert history.status_code == 200
    assert b'52.5' in history.data
    assert b'100.0' in history.data
    assert b'5.0' in history.data

    assignment = score_pages.get('/view_assignment/709')
    assert assignment.status_code == 200
    assert b'52.5' in assignment.data
