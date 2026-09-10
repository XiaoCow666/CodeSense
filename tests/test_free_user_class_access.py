import os
import tempfile
import unittest

from app import create_app
from models import Class, User, db


class FreeUserClassAccessTestCase(unittest.TestCase):
    """自由账号注册、受控入班以及教师加入码展示。"""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            teacher = User(
                student_id='teacher_free_01',
                username='teacher_free',
                usertype='教师',
                full_name='王老师',
            )
            teacher.password = 'password123'
            cls = Class(
                name='自由账号实验班',
                grade='2026',
                major='软件工程',
                teacher_id=teacher.student_id,
            )
            cls.ensure_student_join_code()
            db.session.add_all([teacher, cls])
            db.session.commit()
            self.class_id = cls.id
            self.join_code = cls.student_join_code

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, username):
        return self.client.post('/login', data={
            'username': username,
            'password': 'password123',
        }, follow_redirects=False)

    def test_blank_student_number_creates_unassigned_free_account(self):
        response = self.client.post('/register', data={
            'username': 'free_student',
            'student_id': '',
            'password': 'password123',
            'confirm_password': 'password123',
            'full_name': '自由同学',
            'email': 'free_student@example.com',
            'class_name': '',
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username='free_student').one()
            self.assertTrue(user.student_id.startswith('guest_'))
            self.assertEqual(user.account_kind, 'free')
            self.assertIsNone(user.student_number)
            self.assertIsNone(user.class_id)
            self.assertIsNone(user.class_name)

    def test_free_account_can_join_only_with_valid_student_join_code(self):
        self.client.post('/register', data={
            'username': 'free_joiner',
            'student_id': '',
            'password': 'password123',
            'confirm_password': 'password123',
            'full_name': '待入班同学',
            'class_name': '',
        }, follow_redirects=False)
        self.login('free_joiner')

        home_response = self.client.get('/home')
        self.assertEqual(home_response.status_code, 200)

        invalid_response = self.client.post('/classes/join', data={
            'join_code': 'JINVALID',
        }, follow_redirects=False)
        self.assertEqual(invalid_response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username='free_joiner').one()
            self.assertIsNone(user.class_id)

        valid_response = self.client.post('/classes/join', data={
            'join_code': self.join_code.lower(),
        }, follow_redirects=False)
        self.assertEqual(valid_response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username='free_joiner').one()
            self.assertEqual(user.account_kind, 'free')
            self.assertEqual(user.class_id, self.class_id)
            self.assertEqual(user.class_name, '自由账号实验班')

    def test_teacher_can_see_and_reset_student_join_code(self):
        self.login('teacher_free')

        detail_response = self.client.get(f'/classes/{self.class_id}')
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(self.join_code, detail_response.get_data(as_text=True))

        reset_response = self.client.post(
            f'/classes/{self.class_id}/reset-student-join-code',
            follow_redirects=False,
        )
        self.assertEqual(reset_response.status_code, 302)
        with self.app.app_context():
            cls = Class.query.get(self.class_id)
            self.assertNotEqual(cls.student_join_code, self.join_code)


if __name__ == '__main__':
    unittest.main()
