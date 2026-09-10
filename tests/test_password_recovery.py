import os
import re
import tempfile
import unittest

from app import create_app
from models import User, db


class CapturingMailer:
    def __init__(self):
        self.messages = []

    def send(self, recipient, subject, text_body, html_body=None):
        self.messages.append({
            'recipient': recipient,
            'subject': subject,
            'text_body': text_body,
            'html_body': html_body,
        })


class PasswordRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI=f'sqlite:///{self.db_path}',
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            PASSWORD_RESET_TOKEN_TTL_MINUTES=30,
            APP_BASE_URL='https://codesense.example.test',
        )
        self.client = self.app.test_client()
        self.mailer = CapturingMailer()
        self.app.extensions['codesense_mailer'] = self.mailer

        with self.app.app_context():
            db.create_all()
            admin = User(
                student_id='admin-1',
                username='admin',
                usertype='管理员',
                full_name='测试管理员',
            )
            admin.password = 'admin-password'
            student = User(
                student_id='20240001',
                student_number='253401040105',
                username='student_user',
                usertype='学生',
                full_name='学生一号',
                email='student@example.com',
            )
            student.password = 'old_password'
            student_without_email = User(
                student_id='20240002',
                student_number='253401040106',
                username='student_without_email',
                usertype='学生',
                full_name='无邮箱学生',
            )
            student_without_email.password = 'old_password'
            db.session.add_all([admin, student, student_without_email])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_login_page_links_to_password_recovery(self):
        response = self.client.get('/login')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<a href="/forgot-password" class="forgot-link">', response.data)
        self.assertIn('用户名、学号或邮箱'.encode('utf-8'), response.data)

    def test_forgot_password_page_is_reachable(self):
        response = self.client.get('/forgot-password')

        self.assertEqual(response.status_code, 200)
        self.assertIn('用户名、学号或邮箱'.encode('utf-8'), response.data)

    def test_password_reset_request_sends_link_to_bound_email(self):
        response = self.client.post(
            '/forgot-password',
            data={'identifier': '253401040105'},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('如果账号存在且已绑定邮箱'.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 1)
        self.assertEqual(self.mailer.messages[0]['recipient'], 'student@example.com')
        match = re.search(
            rb'https://codesense\.example\.test/reset-password\?token=([A-Za-z0-9_-]+)',
            self.mailer.messages[0]['text_body'].encode('utf-8'),
        )
        self.assertIsNotNone(match)

    def test_password_reset_email_uses_configured_expiry(self):
        self.app.config['PASSWORD_RESET_TOKEN_TTL_MINUTES'] = 15

        self.client.post(
            '/forgot-password',
            data={'identifier': 'student@example.com'},
        )

        self.assertEqual(len(self.mailer.messages), 1)
        self.assertIn('15 分钟'.encode('utf-8'), self.mailer.messages[0]['text_body'].encode('utf-8'))

    def test_forgot_password_does_not_send_for_account_without_email(self):
        response = self.client.post(
            '/forgot-password',
            data={'identifier': '253401040106'},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('如果账号存在且已绑定邮箱'.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 0)

    def test_password_reset_link_changes_password_once(self):
        self.client.post(
            '/forgot-password',
            data={'identifier': 'student@example.com'},
        )
        token_match = re.search(
            rb'token=([A-Za-z0-9_-]+)',
            self.mailer.messages[0]['text_body'].encode('utf-8'),
        )
        token = token_match.group(1).decode('ascii')

        response = self.client.post(
            '/reset-password',
            data={
                'token': token,
                'password': 'new_password123',
                'confirm_password': 'new_password123',
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.get(User, '20240001')
            reset_token = db.session.execute(
                db.text('SELECT used_at FROM password_reset_tokens')
            ).first()
            self.assertTrue(user.verify_password('new_password123'))
            self.assertIsNotNone(reset_token[0])

        second_response = self.client.post(
            '/reset-password',
            data={
                'token': token,
                'password': 'another_password123',
                'confirm_password': 'another_password123',
            },
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertIn('链接已失效'.encode('utf-8'), second_response.data)

    def test_admin_can_generate_reset_link_for_student_without_email(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin-password',
        })

        response = self.client.post(
            '/users/reset_password/20240002',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('/reset-password?token='.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 0)

    def test_admin_reset_action_accepts_csrf_protected_form(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin-password',
        })
        self.app.config['WTF_CSRF_ENABLED'] = True

        page = self.client.get('/users')
        token_match = re.search(
            rb'name="csrf_token" type="hidden" value="([^"]+)"',
            page.data,
        )
        self.assertIsNotNone(token_match)

        response = self.client.post(
            '/users/reset_password/20240002',
            data={'csrf_token': token_match.group(1).decode('ascii')},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('/reset-password?token='.encode('utf-8'), response.data)

    def test_admin_user_list_offers_password_reset_action(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin-password',
        })

        response = self.client.get('/users')

        self.assertEqual(response.status_code, 200)
        self.assertIn('生成重置链接'.encode('utf-8'), response.data)
        self.assertIn('/users/reset_password/20240002'.encode('utf-8'), response.data)

    def test_admin_can_find_student_by_student_number(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin-password',
        })

        response = self.client.get('/users?search=253401040105')

        self.assertEqual(response.status_code, 200)
        self.assertIn('253401040105'.encode('utf-8'), response.data)
        self.assertIn('/users/reset_password/20240001'.encode('utf-8'), response.data)


if __name__ == '__main__':
    unittest.main()
