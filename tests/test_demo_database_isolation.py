import json
import os
import sqlite3
import unittest

from models import Assignment, Class, Submission, User
from services.demo_database import _db_path
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoDatabaseFixtureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def _run_id(self):
        with self.client.session_transaction() as demo_session:
            return demo_session['demo_run_id']

    def test_student_demo_starts_with_rich_realistic_fixture(self):
        response = self.client.get('/demo-login/student')

        self.assertEqual(response.status_code, 302)
        run_id = self._run_id()
        db_path = str(_db_path(run_id))
        self.assertTrue(os.path.exists(db_path))

        connection = sqlite3.connect(db_path)
        try:
            users = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            assignments = connection.execute('SELECT COUNT(*) FROM assignments').fetchone()[0]
            submissions = connection.execute('SELECT COUNT(*) FROM submissions').fetchone()[0]
            knowledge_points = connection.execute(
                "SELECT COUNT(*) FROM knowledge_point_scores WHERE student_id = 'demo_s_001'"
            ).fetchone()[0]
            presets = connection.execute(
                'SELECT COUNT(*) FROM assignment_thinking_presets'
            ).fetchone()[0]
            scores = [
                row[0]
                for row in connection.execute(
                    "SELECT score FROM submissions WHERE student_id = 'demo_s_001'"
                )
                if row[0] is not None
            ]
            feedback = connection.execute(
                "SELECT ai_feedback FROM submissions "
                "WHERE student_id = 'demo_s_001' AND ai_feedback IS NOT NULL LIMIT 1"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertGreaterEqual(users, 10)
        self.assertGreaterEqual(assignments, 6)
        self.assertGreaterEqual(submissions, 10)
        self.assertGreaterEqual(knowledge_points, 13)
        self.assertGreaterEqual(presets, 2)
        self.assertTrue(scores)
        self.assertGreaterEqual(min(scores), 0)
        self.assertLessEqual(max(scores), 5)
        feedback_data = json.loads(feedback)
        self.assertIn('algorithm_score', feedback_data)
        self.assertIn('readability_score', feedback_data)

        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)
            self.assertEqual(Class.query.count(), 0)
            self.assertEqual(Assignment.query.count(), 0)
            self.assertEqual(Submission.query.count(), 0)

    def test_teacher_demo_starts_with_roster_trend_and_suggestions(self):
        response = self.client.get('/demo-login/teacher')

        self.assertEqual(response.status_code, 302)
        run_id = self._run_id()
        db_path = str(_db_path(run_id))
        connection = sqlite3.connect(db_path)
        try:
            students = connection.execute(
                "SELECT COUNT(*) FROM users WHERE usertype = '学生'"
            ).fetchone()[0]
            assignments = connection.execute('SELECT COUNT(*) FROM assignments').fetchone()[0]
            submissions = connection.execute('SELECT COUNT(*) FROM submissions').fetchone()[0]
            trends = connection.execute('SELECT COUNT(*) FROM ability_trends').fetchone()[0]
            suggestions = connection.execute(
                'SELECT COUNT(*) FROM teacher_ai_suggestions'
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertGreaterEqual(students, 10)
        self.assertGreaterEqual(assignments, 6)
        self.assertGreaterEqual(submissions, 25)
        self.assertGreaterEqual(trends, 4)
        self.assertGreaterEqual(suggestions, 1)


if __name__ == '__main__':
    unittest.main()
