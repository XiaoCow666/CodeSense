import os
import tempfile
from unittest.mock import patch

from app import create_app
from models import Assignment, Submission, User, db


def test_sync_submission_failure_is_persisted_and_observable(caplog):
    fd, database_path = tempfile.mkstemp()
    app = create_app('testing')
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{database_path}',
        TESTING=True,
        SUBMISSION_EVALUATION_QUEUE_BACKEND='thread',
    )
    client = app.test_client()
    try:
        with app.app_context():
            db.drop_all()
            db.create_all()
            student = User(
                student_id='task4-student',
                username='task4-student',
                usertype='学生',
                full_name='任务四学生',
            )
            student.password = 'password'
            db.session.add(student)
            assignment = Assignment(title='任务四作业', creator_id=student.student_id)
            db.session.add(assignment)
            db.session.commit()
            assignment_id = assignment.id

        client.post('/login', data={'username': 'task4-student', 'password': 'password'})
        with patch(
            'routes.api.evaluate_cpp_code',
            side_effect=RuntimeError('temporary evaluator outage'),
        ):
            response = client.post(
                '/api/submit',
                json={'code': 'int main() { return 0; }', 'assignment_id': assignment_id},
            )

        assert response.status_code == 500
        assert response.get_json()['success'] is False
        with app.app_context():
            submission = Submission.query.one()
            assert submission.status == 'failed'
            assert 'temporary evaluator outage' in submission.feedback
        assert 'submission_id=' in caplog.text
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(fd)
        os.unlink(database_path)
