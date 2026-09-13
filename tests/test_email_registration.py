import os
import re
import tempfile
import unittest

from app import create_app
from models import AuthIdentity, EmailVerificationToken, User, db
from services.auth_identity import AuthIdentityConflict, bind_identity, find_user_by_identity


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


class EmailRegistrationTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI=f'sqlite:///{self.db_path}',
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            APP_BASE_URL='https://codesense.example.test',
            EMAIL_VERIFICATION_TOKEN_TTL_MINUTES=30,
            EMAIL_VERIFICATION_REQUEST_INTERVAL_SECONDS=0,
        )
        self.client = self.app.test_client()
        self.mailer = CapturingMailer()
        self.app.extensions['codesense_mailer'] = self.mailer

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _register(self, email='new@example.com', username='new_user'):
        return self.client.post(
            '/register/email',
            data={
                'email': email,
                'username': username,
                'full_name': '邮箱用户',
                'password': 'NewPassword123',
                'confirm_password': 'NewPassword123',
            },
            follow_redirects=True,
        )

    def _verification_token(self):
        match = re.search(
            rb'https://codesense\.example\.test/verify-email\?token=([A-Za-z0-9_-]+)',
            self.mailer.messages[-1]['text_body'].encode('utf-8'),
        )
        self.assertIsNotNone(match)
        return match.group(1).decode('ascii')

    def test_email_registration_page_is_reachable(self):
        response = self.client.get('/register/email')

        self.assertEqual(response.status_code, 200)
        self.assertIn('邮箱注册'.encode('utf-8'), response.data)
        self.assertIn('不需要提前导入学生名单'.encode('utf-8'), response.data)

    def test_email_registration_creates_pending_account_and_sends_verification(self):
        response = self._register()

        self.assertEqual(response.status_code, 200)
        self.assertIn('注册成功，请查收邮箱验证邮件'.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 1)
        self.assertEqual(self.mailer.messages[0]['recipient'], 'new@example.com')
        self.assertIn('邮箱验证'.encode('utf-8'), self.mailer.messages[0]['subject'].encode('utf-8'))

        with self.app.app_context():
            user = User.query.filter_by(username='new_user').one()
            self.assertTrue(user.student_id.startswith('e-'))
            self.assertEqual(len(user.student_id), 20)
            self.assertEqual(user.registration_method, 'email')
            self.assertTrue(user.email_verification_required)
            self.assertIsNone(user.email_verified_at)
            token = EmailVerificationToken.query.filter_by(user_id=user.student_id).one()
            self.assertIsNone(token.used_at)
            self.assertIsNone(token.revoked_at)

    def test_unverified_account_cannot_login_and_can_verify_once(self):
        self._register()
        token = self._verification_token()

        blocked = self.client.post(
            '/login',
            data={'username': 'new@example.com', 'password': 'NewPassword123'},
            follow_redirects=True,
        )
        self.assertIn('邮箱尚未验证'.encode('utf-8'), blocked.data)

        preview = self.client.get(f'/verify-email?token={token}')
        self.assertEqual(preview.status_code, 200)
        self.assertIn('点击下方按钮完成邮箱验证'.encode('utf-8'), preview.data)

        verified = self.client.post(
            '/verify-email',
            data={'token': token},
            follow_redirects=True,
        )
        self.assertEqual(verified.status_code, 200)
        self.assertIn('邮箱验证成功'.encode('utf-8'), verified.data)

        with self.app.app_context():
            user = User.query.filter_by(username='new_user').one()
            token_record = EmailVerificationToken.query.filter_by(user_id=user.student_id).one()
            self.assertFalse(user.email_verification_required)
            self.assertIsNotNone(user.email_verified_at)
            self.assertIsNotNone(token_record.used_at)

        logged_in = self.client.post(
            '/login',
            data={'username': 'new@example.com', 'password': 'NewPassword123'},
            follow_redirects=False,
        )
        self.assertEqual(logged_in.status_code, 302)
        self.assertEqual(logged_in.headers['Location'], '/home')

        second_attempt = self.client.post(
            '/verify-email',
            data={'token': token},
        )
        self.assertEqual(second_attempt.status_code, 200)
        self.assertIn('链接已失效'.encode('utf-8'), second_attempt.data)

    def test_duplicate_email_is_rejected(self):
        self._register()

        response = self._register(email='NEW@example.com', username='another_user')

        self.assertEqual(response.status_code, 200)
        self.assertIn('邮箱已被使用'.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 1)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)

    def test_resend_verification_replaces_previous_token(self):
        self._register()
        first_token = self._verification_token()

        response = self.client.post(
            '/resend-verification',
            data={'email': 'new@example.com'},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('系统会发送新的验证邮件'.encode('utf-8'), response.data)
        self.assertEqual(len(self.mailer.messages), 2)
        second_token = self._verification_token()
        self.assertNotEqual(first_token, second_token)

        old_preview = self.client.get(f'/verify-email?token={first_token}')
        self.assertIn('链接已失效'.encode('utf-8'), old_preview.data)
        new_preview = self.client.get(f'/verify-email?token={second_token}')
        self.assertIn('点击下方按钮完成邮箱验证'.encode('utf-8'), new_preview.data)

    def test_auth_identity_binds_one_provider_subject_to_one_user(self):
        with self.app.app_context():
            first = User(
                student_id='e-first',
                username='first',
                usertype='学生',
                full_name='第一用户',
            )
            first.password = 'Password123'
            second = User(
                student_id='e-second',
                username='second',
                usertype='学生',
                full_name='第二用户',
            )
            second.password = 'Password123'
            db.session.add_all([first, second])
            db.session.commit()

            identity = bind_identity(
                first,
                'Google',
                'google-subject-1',
                'FIRST@EXAMPLE.COM',
            )
            self.assertEqual(identity.provider, 'google')
            self.assertEqual(identity.provider_email, 'first@example.com')
            self.assertIs(find_user_by_identity('google', 'google-subject-1'), first)
            self.assertEqual(AuthIdentity.query.count(), 1)

            with self.assertRaises(AuthIdentityConflict):
                bind_identity(second, 'google', 'google-subject-1')


if __name__ == '__main__':
    unittest.main()
