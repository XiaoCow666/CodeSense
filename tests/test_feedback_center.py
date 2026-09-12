import json
import os
import tempfile
import unittest

from app import create_app
from config import config
from models import SystemLog, User, db


class FeedbackCenterTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        os.close(self.db_fd)
        self.db_fd = None
        config['testing'].SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_feedback_form_has_contextual_receipt_and_structured_log(self):
        response = self.client.post(
            '/feedback',
            data={
                'category': 'bug',
                'subject': '提交后页面没有刷新',
                'message': '在提交作业后页面一直显示旧状态，刷新后才看到结果。',
                'reproduction_steps': '进入作业详情，提交一次代码，然后观察提交列表。',
                'page_context': '/submit/42',
                'contact_email': 'student@example.com',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        receipt_url = response.headers['Location']
        feedback_id = receipt_url.rstrip('/').split('/')[-1]
        self.assertRegex(feedback_id, r'^FB-[0-9A-F]{12}$')

        receipt = self.client.get(receipt_url)
        self.assertEqual(receipt.status_code, 200)
        self.assertIn(feedback_id.encode(), receipt.data)
        self.assertIn('已收到'.encode('utf-8'), receipt.data)
        self.assertNotIn('提交后页面没有刷新'.encode('utf-8'), receipt.data)
        self.assertNotIn('student@example.com'.encode(), receipt.data)

        with self.app.app_context():
            log = (
                SystemLog.query.filter_by(log_type='反馈提交')
                .order_by(SystemLog.id.desc())
                .first()
            )
            self.assertIsNotNone(log)
            record = json.loads(log.content)
            self.assertEqual(record['schema_version'], 1)
            self.assertEqual(record['feedback_id'], feedback_id)
            self.assertEqual(record['status'], 'received')
            self.assertEqual(record['status_history'][0]['status'], 'received')
            self.assertEqual(record['context']['page'], '/submit/42')
            self.assertEqual(record['category'], 'bug')
            self.assertIsNone(log.user_id)

    def test_invalid_feedback_is_explained_without_creating_log(self):
        with self.app.app_context():
            before = SystemLog.query.filter_by(log_type='反馈提交').count()

        response = self.client.post(
            '/feedback',
            data={
                'category': 'unknown',
                'subject': 'x',
                'message': '太短',
                'contact_email': 'not-an-email',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('role="alert"'.encode(), response.data)
        self.assertIn('feedback-category'.encode(), response.data)
        self.assertIn('feedback-message'.encode(), response.data)
        self.assertIn('aria-invalid="true"'.encode(), response.data)
        self.assertIn('aria-describedby="feedback-category-help feedback-category-error"'.encode(), response.data)
        self.assertIn('id="feedback-category-error"'.encode(), response.data)
        self.assertIn('id="feedback-message-error"'.encode(), response.data)
        with self.app.app_context():
            self.assertEqual(
                SystemLog.query.filter_by(log_type='反馈提交').count(),
                before,
            )

    def test_footer_and_contact_route_point_to_feedback_center(self):
        from flask import url_for

        about = self.client.get('/about')
        self.assertEqual(about.status_code, 200)
        self.assertIn('跳转到主要内容'.encode('utf-8'), about.data)
        self.assertIn('id="main-content"'.encode(), about.data)
        self.assertIn('aria-expanded="false"'.encode(), about.data)
        self.assertIn('反馈中心'.encode('utf-8'), about.data)
        with self.app.test_request_context():
            about_feedback_url = url_for('main.feedback', from_page='/about')
            contact_feedback_url = url_for('main.feedback', from_page='/contact')
        self.assertIn(about_feedback_url.encode(), about.data)

        contact = self.client.get('/contact')
        self.assertEqual(contact.status_code, 200)
        self.assertIn('前往反馈中心'.encode('utf-8'), contact.data)
        self.assertIn(contact_feedback_url.encode(), contact.data)

    def test_legacy_contact_post_is_compatible_with_new_receipt(self):
        response = self.client.post(
            '/contact',
            data={
                'name': '访客',
                'email': 'visitor@example.com',
                'subject': '旧入口仍可提交',
                'message': '这是旧版联系表单的兼容性测试消息。',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/feedback/receipt/FB-', response.headers['Location'])

        with self.app.app_context():
            log = (
                SystemLog.query.filter_by(log_type='反馈提交')
                .order_by(SystemLog.id.desc())
                .first()
            )
            record = json.loads(log.content)
            self.assertEqual(record['context']['page'], '/contact')
            self.assertEqual(record['category'], 'other')

    def test_admin_can_review_feedback_and_anonymous_users_cannot(self):
        with self.app.app_context():
            admin = User(
                student_id='feedback_admin',
                username='feedback_admin',
                usertype='管理员',
                full_name='反馈管理员',
            )
            admin.password = 'admin_password'
            db.session.add(admin)
            db.session.commit()

        anonymous_response = self.client.get('/admin/feedback')
        self.assertEqual(anonymous_response.status_code, 302)

        login = self.client.post(
            '/login',
            data={'username': 'feedback_admin', 'password': 'admin_password'},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)
        self.client.post(
            '/feedback',
            data={
                'category': 'experience',
                'subject': '管理员查看反馈',
                'message': '这条反馈用于验证管理员可以看到具体描述和上下文。',
                'page_context': '/about',
            },
            follow_redirects=False,
        )

        review = self.client.get('/admin/feedback')
        self.assertEqual(review.status_code, 200)
        self.assertIn('管理员查看反馈'.encode('utf-8'), review.data)
        self.assertIn('/about'.encode(), review.data)


if __name__ == '__main__':
    unittest.main()
