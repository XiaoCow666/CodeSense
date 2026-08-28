import json
import hashlib
import os
import sqlite3
import unittest
from unittest.mock import patch

from sqlalchemy import text

from models import Assignment, Class, Submission, User, db
from services.demo_database import _db_path
from services.demo_experience import get_demo_assignment_id
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

    def _formal_snapshot(self):
        """Capture formal rows and content hashes before/after a demo flow."""

        tables = (
            'users',
            'classes',
            'student_rosters',
            'assignments',
            'assignment_knowledge_points',
            'submissions',
            'knowledge_point_scores',
            'ability_trends',
            'teacher_ai_suggestions',
            'thinking_sessions',
            'thinking_stage_logs',
            'system_logs',
        )
        snapshot = {}
        with self.app.app_context(), db.engine.connect() as connection:
            for table in tables:
                rows = connection.execute(
                    text(f'SELECT * FROM "{table}" ORDER BY rowid')
                ).fetchall()
                normalized = [
                    [
                        value.isoformat() if hasattr(value, 'isoformat') else value
                        for value in row
                    ]
                    for row in rows
                ]
                serialized = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    default=str,
                    separators=(',', ':'),
                ).encode('utf-8')
                snapshot[table] = {
                    'count': len(rows),
                    'sha256': hashlib.sha256(serialized).hexdigest(),
                }
        return snapshot

    @staticmethod
    def _run_id_for(client):
        with client.session_transaction() as demo_session:
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

    def test_complete_demo_flows_preserve_formal_snapshot_and_delete_runs(self):
        formal_before = self._formal_snapshot()
        student_client = self.client
        teacher_client = self.app.test_client()

        with patch('tasks.ability_analysis.trigger_analysis_if_needed', return_value=False):
            student_login = student_client.get('/demo-login/student')
            student_run_id = self._run_id_for(student_client)
            student_path = str(_db_path(student_run_id))
            self.assertEqual(student_login.status_code, 302)
            self.assertTrue(os.path.exists(student_path))

            arena = student_client.get(student_login.headers['Location'])
            self.assertEqual(arena.status_code, 200)
            student_home = student_client.get('/home', follow_redirects=True)
            self.assertEqual(student_home.status_code, 200)
            student_profile = student_client.get('/user_profile/student_demo_good')
            self.assertEqual(student_profile.status_code, 200)

            with self.app.app_context():
                from services.demo_database import activate_demo_run

                self.assertTrue(activate_demo_run(student_run_id))
                assignment_id = get_demo_assignment_id(student_run_id)

            started = student_client.post('/thinking/api/start_session', json={
                'assignment_id': assignment_id,
            })
            self.assertEqual(started.status_code, 200)
            session_id = started.get_json()['session_id']
            completed = student_client.post('/thinking/api/debug/jump_stage', json={
                'session_id': session_id,
                'stage': 4,
            })
            self.assertEqual(completed.status_code, 200)

            teacher_login = teacher_client.get('/demo-login/teacher')
            teacher_run_id = self._run_id_for(teacher_client)
            teacher_path = str(_db_path(teacher_run_id))
            self.assertEqual(teacher_login.status_code, 302)
            self.assertNotEqual(student_run_id, teacher_run_id)
            self.assertTrue(os.path.exists(teacher_path))

            teacher_home = teacher_client.get('/home', follow_redirects=True)
            self.assertEqual(teacher_home.status_code, 200)
            class_list = teacher_client.get('/classes/')
            self.assertEqual(class_list.status_code, 200)
            teacher_assignments = teacher_client.get('/teacher')
            self.assertEqual(teacher_assignments.status_code, 200)
            teacher_suggestions = teacher_client.get('/teacher/ai_suggestions')
            self.assertEqual(teacher_suggestions.status_code, 200)

            with self.app.app_context():
                from services.demo_database import activate_demo_run

                self.assertTrue(activate_demo_run(teacher_run_id))
                demo_class = Class.query.filter_by(teacher_id='demo_t_001').first()
                self.assertIsNotNone(demo_class)
                class_id = demo_class.id

            class_detail = teacher_client.get(f'/classes/{class_id}')
            self.assertEqual(class_detail.status_code, 200)

            connection = sqlite3.connect(student_path)
            try:
                demo_submission_count = connection.execute(
                    "SELECT COUNT(*) FROM submissions "
                    "WHERE code LIKE '/* codesense-demo-guided-session:%'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(demo_submission_count, 1)

        student_client.get('/logout')
        teacher_client.get('/logout')

        self.assertFalse(os.path.exists(student_path))
        self.assertFalse(os.path.exists(f'{student_path}.meta'))
        self.assertFalse(os.path.exists(teacher_path))
        self.assertFalse(os.path.exists(f'{teacher_path}.meta'))
        self.assertEqual(self._formal_snapshot(), formal_before)


if __name__ == '__main__':
    unittest.main()
