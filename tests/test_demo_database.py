import os
import sqlite3
import unittest
from datetime import datetime, timedelta

import services.demo_database as demo_database
from services.demo_database import (
    DEMO_IDLE_TIMEOUT,
    cleanup_expired_demo_runs,
    create_demo_run,
    destroy_demo_run,
    is_demo_login_id,
)
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoDatabaseLifecycleTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()

    def tearDown(self):
        destroy_test_app(self.app)

    def test_create_demo_run_creates_isolated_schema_without_formal_rows(self):
        with self.app.app_context():
            from models import User

            formal_users_before = User.query.count()

            run = create_demo_run('student')

            self.assertTrue(run.run_id)
            self.assertEqual(run.role, 'student')
            self.assertTrue(os.path.isfile(run.db_path))
            self.assertTrue(is_demo_login_id(f'demo:{run.run_id}'))

            connection = sqlite3.connect(run.db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()

            self.assertIn('users', tables)
            self.assertIn('assignments', tables)
            self.assertIn('submissions', tables)
            self.assertIn('ability_trends', tables)

            self.assertEqual(User.query.count(), formal_users_before)
            destroy_demo_run(run.run_id)

    def test_destroying_one_run_does_not_remove_another_run(self):
        with self.app.app_context():
            first = create_demo_run('student')
            second = create_demo_run('teacher')
            first_path = first.db_path
            second_path = second.db_path

            self.assertNotEqual(first.run_id, second.run_id)
            self.assertNotEqual(first_path, second_path)
            self.assertTrue(os.path.exists(first_path))
            self.assertTrue(os.path.exists(second_path))

            self.assertTrue(destroy_demo_run(first.run_id))

            self.assertFalse(os.path.exists(first_path))
            self.assertTrue(os.path.exists(second_path))
            self.assertFalse(destroy_demo_run(first.run_id))

            destroy_demo_run(second.run_id)

    def test_cleanup_removes_idle_run_and_its_metadata(self):
        with self.app.app_context():
            run = create_demo_run('student')
            stale_at = datetime.utcnow() - DEMO_IDLE_TIMEOUT - timedelta(seconds=1)
            with demo_database._LOCK:
                demo_database._RUN_LAST_ACCESS[run.run_id] = stale_at

            self.assertEqual(cleanup_expired_demo_runs(datetime.utcnow()), 1)
            self.assertFalse(os.path.exists(run.db_path))
            self.assertFalse(os.path.exists(f'{run.db_path}.meta'))


if __name__ == '__main__':
    unittest.main()
