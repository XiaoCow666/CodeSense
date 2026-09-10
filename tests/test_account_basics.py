import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import User, db


class AccountBasicsTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.upload_dir = tempfile.mkdtemp()
        self.app = create_app('testing')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['UPLOAD_FOLDER'] = self.upload_dir
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            student = User(
                student_id='20240001',
                student_number='2024-0001',
                username='student_user',
                usertype='学生',
                class_name='软件2302',
                full_name='学生一号',
            )
            student.email = 'student@example.com'
            student.password = 'old_password'
            db.session.add(student)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username='student_user', password='old_password'):
        return self.client.post('/login', data={
            'username': username,
            'password': password,
        }, follow_redirects=False)

    def test_login_accepts_email_identifier(self):
        response = self.login(username='student@example.com')

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('student_id'), '20240001')

    def test_login_accepts_student_id_identifier(self):
        response = self.login(username='20240001')

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('student_id'), '20240001')

    def test_login_accepts_student_number_identifier(self):
        response = self.login(username='2024-0001')

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('student_id'), '20240001')

    def test_logged_in_user_can_change_password(self):
        self.login()

        response = self.client.post('/change_password', data={
            'current_password': 'old_password',
            'new_password': 'new_password123',
            'confirm_password': 'new_password123',
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.get('20240001')
            self.assertTrue(user.verify_password('new_password123'))
            self.assertIsNotNone(user.password_changed_at)

        self.client.get('/logout')
        login_response = self.login(password='new_password123')
        self.assertEqual(login_response.status_code, 302)

    def test_profile_update_saves_email_and_avatar(self):
        self.login()
        avatar_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'

        response = self.client.post('/edit_profile', data={
            'username': 'student_user',
            'full_name': '学生一号',
            'class_name': '',
            'email': 'new-student@example.com',
            'avatar': (io.BytesIO(avatar_bytes), 'avatar.png'),
        }, content_type='multipart/form-data', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.get('20240001')
            self.assertEqual(user.email, 'new-student@example.com')
            self.assertTrue(user.avatar_path.endswith('.png'))
            saved_path = os.path.join(self.app.root_path, user.avatar_path)
            self.assertTrue(os.path.exists(saved_path))


if __name__ == '__main__':
    unittest.main()
