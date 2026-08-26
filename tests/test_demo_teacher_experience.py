import unittest

from models import Class
from services.demo_experience import DEMO_CLASS_NAME, ensure_demo_experience
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoTeacherExperienceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()
        with self.app.app_context():
            self.demo = ensure_demo_experience()
            self.class_id = Class.query.filter_by(name=DEMO_CLASS_NAME).one().id

    def tearDown(self):
        destroy_test_app(self.app)

    def test_teacher_can_browse_dashboard_class_detail_and_ai_suggestions(self):
        login_response = self.client.get('/demo-login/teacher')
        self.assertEqual(login_response.status_code, 302)

        dashboard = self.client.get('/home', follow_redirects=True)
        class_detail = self.client.get(f'/classes/{self.class_id}')
        suggestions = self.client.get('/teacher/ai_suggestions')

        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('软件工程24-演示班'.encode('utf-8'), dashboard.data)
        self.assertIn('孙三（风险）'.encode('utf-8'), dashboard.data)
        self.assertIn('演示作业一：循环与斐波那契数列'.encode('utf-8'), dashboard.data)

        self.assertEqual(class_detail.status_code, 200)
        self.assertIn('钱二（中等）'.encode('utf-8'), class_detail.data)
        self.assertIn('李四（未注册）'.encode('utf-8'), class_detail.data)
        self.assertIn('演示作业一：循环与斐波那契数列'.encode('utf-8'), class_detail.data)

        self.assertEqual(suggestions.status_code, 200)
        self.assertIn('学情建议'.encode('utf-8'), suggestions.data)
        self.assertIn('边界条件'.encode('utf-8'), suggestions.data)
        self.assertIn('孙三'.encode('utf-8'), suggestions.data)


if __name__ == '__main__':
    unittest.main()
