import unittest

from services.demo_experience import (
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    ensure_demo_experience,
)
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoLoginTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        with self.app.app_context():
            ensure_demo_experience()
        self.client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def test_student_demo_login_goes_to_guided_assignment(self):
        response = self.client.get('/demo-login/student')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/thinking/', response.headers['Location'])
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('student_id'), DEMO_STUDENT_ID)
            self.assertEqual(session.get('usertype'), '学生')

    def test_teacher_demo_login_goes_to_home(self):
        response = self.client.get('/demo-login/teacher')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/home'))
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('student_id'), DEMO_TEACHER_ID)
            self.assertEqual(session.get('usertype'), '教师')

    def test_public_demo_login_stays_available_outside_debug_mode(self):
        self.app.config.update(DEBUG=False, TESTING=False)

        response = self.client.get('/demo-login/student')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/thinking/', response.headers['Location'])

    def test_invalid_demo_role_does_not_login(self):
        self.client.get('/logout')
        response = self.client.get('/demo-login/admin', follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('该演示入口不可用'.encode('utf-8'), response.data)
        with self.client.session_transaction() as session:
            self.assertIsNone(session.get('student_id'))

    def test_login_page_exposes_public_experience_links_without_credentials(self):
        response = self.client.get('/login')

        self.assertEqual(response.status_code, 200)
        self.assertIn('/demo-login/student'.encode('utf-8'), response.data)
        self.assertIn('/demo-login/teacher'.encode('utf-8'), response.data)
        self.assertNotIn('123456'.encode('utf-8'), response.data)


if __name__ == '__main__':
    unittest.main()
