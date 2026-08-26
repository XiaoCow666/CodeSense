import os
import sqlite3
import unittest

from models import Assignment, Class, Submission, User
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoSessionBindingTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.first_client = self.app.test_client()
        self.second_client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def _formal_snapshot(self):
        with self.app.app_context():
            return {
                'users': User.query.count(),
                'classes': Class.query.count(),
                'assignments': Assignment.query.count(),
                'submissions': Submission.query.count(),
            }

    def test_activating_a_run_binds_writes_to_the_run_file(self):
        from services.demo_database import activate_demo_run, create_demo_run, destroy_demo_run

        with self.app.app_context():
            run = create_demo_run('student')
            self.assertTrue(activate_demo_run(run.run_id))

            user = User(
                student_id='binding-test-student',
                username='binding-test-student',
                usertype='学生',
                full_name='绑定测试学生',
            )
            user.password = 'not-used'
            from models import db

            db.session.add(user)
            db.session.commit()
            db.session.remove()

            connection = sqlite3.connect(run.db_path)
            try:
                temp_users = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(temp_users, 1)
            self.assertEqual(User.query.count(), 0)
            destroy_demo_run(run.run_id)

    def test_each_demo_login_gets_a_distinct_run_without_formal_writes(self):
        before = self._formal_snapshot()

        first_response = self.first_client.get('/demo-login/student')
        second_response = self.second_client.get('/demo-login/student')

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)

        with self.first_client.session_transaction() as first_session:
            first_run_id = first_session.get('demo_run_id')
            self.assertEqual(first_session.get('usertype'), '学生')
        with self.second_client.session_transaction() as second_session:
            second_run_id = second_session.get('demo_run_id')
            self.assertEqual(second_session.get('usertype'), '学生')

        self.assertTrue(first_run_id)
        self.assertTrue(second_run_id)
        self.assertNotEqual(first_run_id, second_run_id)
        self.assertNotEqual(first_response.headers['Location'], '')
        self.assertNotEqual(second_response.headers['Location'], '')

        after = self._formal_snapshot()
        self.assertEqual(before, after)

    def test_demo_logout_deletes_only_the_current_run(self):
        self.first_client.get('/demo-login/student')
        self.second_client.get('/demo-login/student')
        with self.first_client.session_transaction() as first_session:
            first_run_id = first_session['demo_run_id']
        with self.second_client.session_transaction() as second_session:
            second_run_id = second_session['demo_run_id']

        from services.demo_database import _db_path

        first_path = str(_db_path(first_run_id))
        second_path = str(_db_path(second_run_id))
        self.assertTrue(os.path.exists(first_path))
        self.assertTrue(os.path.exists(second_path))

        response = self.first_client.get('/logout')

        self.assertEqual(response.status_code, 302)
        self.assertFalse(os.path.exists(first_path))
        self.assertTrue(os.path.exists(second_path))


if __name__ == '__main__':
    unittest.main()
