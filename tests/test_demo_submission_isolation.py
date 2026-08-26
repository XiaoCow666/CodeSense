import unittest
from unittest.mock import patch

from models import AbilityTrend, Submission, SystemLog, db
from services.demo_database import activate_demo_run
from services.demo_experience import DEMO_STUDENT_ID, get_demo_assignment_id
from tasks.submission_tasks import evaluate_submission_async
from tests.demo_test_utils import create_test_app, destroy_test_app


class ImmediateThread:
    def __init__(self, target, *args, **kwargs):
        self.target = target
        self.daemon = False

    def start(self):
        self.target()


class DemoSubmissionIsolationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()
        self.client.get('/demo-login/student')
        with self.client.session_transaction() as client_session:
            self.run_id = client_session['demo_run_id']

    def tearDown(self):
        destroy_test_app(self.app)

    def test_evaluation_updates_only_current_demo_database(self):
        with self.app.app_context():
            self.assertTrue(activate_demo_run(self.run_id))
            assignment_id = get_demo_assignment_id(self.run_id)
            submission = Submission(
                student_id=DEMO_STUDENT_ID,
                assignment_id=assignment_id,
                code='#include <stdio.h>\nint main(void) { return 0; }',
                status='pending',
            )
            db.session.add(submission)
            db.session.commit()
            submission_id = submission.id

        sandbox_result = {
            'status': 'passed',
            'passed': 3,
            'total': 3,
            'details': [{'index': 1, 'status': 'passed'}],
        }
        with patch('tasks.submission_tasks.threading.Thread', ImmediateThread), \
                patch('tasks.submission_tasks.evaluate_cpp_code', return_value=(4, '评测完成')), \
                patch('tasks.submission_tasks.run_test_cases', return_value=sandbox_result), \
                patch('tasks.ability_analysis.trigger_analysis_if_needed', return_value=True):
            evaluate_submission_async(
                self.app,
                submission_id,
                '演示作业一：循环与斐波那契数列',
                demo_run_id=self.run_id,
            )

        with self.app.app_context():
            self.assertTrue(activate_demo_run(self.run_id))
            updated = Submission.query.get(submission_id)
            self.assertEqual(updated.status, 'evaluated')
            self.assertEqual(updated.score, 5)
            self.assertEqual(updated.sandbox_passed, 3)
            self.assertIsNotNone(AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one())
            self.assertEqual(SystemLog.query.count(), 0)

        with self.app.app_context():
            self.assertEqual(Submission.query.count(), 0)
            self.assertEqual(AbilityTrend.query.count(), 0)
            self.assertEqual(SystemLog.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
