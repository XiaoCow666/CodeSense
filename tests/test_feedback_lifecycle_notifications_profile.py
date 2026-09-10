import json
import os
import tempfile
import unittest

from app import create_app
from config import config
from models import SystemLog, User, db
from services.feedback import list_feedback, update_feedback_status
from services.profile import get_profile_settings


class FeedbackLifecycleNotificationsProfileTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        os.close(self.db_fd)
        config['testing'].SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            admin = User(
                student_id='lifecycle_admin',
                username='lifecycle_admin',
                usertype='管理员',
                full_name='生命周期管理员',
            )
            admin.password = 'admin_password'
            student = User(
                student_id='lifecycle_student',
                username='lifecycle_student',
                usertype='学生',
                full_name='生命周期学生',
                email='lifecycle@example.com',
            )
            student.password = 'student_password'
            db.session.add_all([admin, student])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def login(self, username, password):
        return self.client.post(
            '/login',
            data={'username': username, 'password': password},
            follow_redirects=False,
        )

    def logout(self):
        self.client.get('/logout', follow_redirects=False)

    def submit_feedback(self):
        response = self.client.post(
            '/feedback',
            data={
                'category': 'bug',
                'subject': '状态变更通知测试',
                'message': '提交后需要由管理员推进状态，并通知提交人。',
                'reproduction_steps': '打开反馈中心，提交表单后等待处理。',
                'page_context': '/feedback',
                'contact_email': 'lifecycle@example.com',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        return response.headers['Location'].rstrip('/').split('/')[-1]

    def test_feedback_status_flow_updates_receipt_and_owned_notifications(self):
        self.assertEqual(self.login('lifecycle_student', 'student_password').status_code, 302)
        feedback_id = self.submit_feedback()

        with self.app.app_context():
            self.assertEqual(SystemLog.query.filter_by(log_type='反馈提交').count(), 1)
            self.assertEqual(SystemLog.query.filter_by(log_type='站内通知').count(), 1)

        self.logout()
        self.assertEqual(self.login('lifecycle_admin', 'admin_password').status_code, 302)
        review = self.client.get('/admin/feedback?status=received&category=bug')
        self.assertEqual(review.status_code, 200)
        self.assertIn('状态变更通知测试'.encode('utf-8'), review.data)
        self.assertIn('应用筛选'.encode('utf-8'), review.data)

        update = self.client.post(
            f'/admin/feedback/{feedback_id}/status',
            data={'status': 'triaged', 'note': '已分派给支持人员'},
            follow_redirects=False,
        )
        self.assertEqual(update.status_code, 302)

        review_after = self.client.get('/admin/feedback')
        self.assertIn('已分派'.encode('utf-8'), review_after.data)
        self.assertNotIn('已分派给支持人员'.encode('utf-8'), review_after.data)
        self.assertIn(
            '状态变更通知测试'.encode('utf-8'),
            self.client.get('/admin/feedback?status=triaged').data,
        )
        self.assertNotIn(
            '状态变更通知测试'.encode('utf-8'),
            self.client.get('/admin/feedback?status=received').data,
        )

        with self.app.app_context():
            notification_id = (
                SystemLog.query.filter_by(
                    log_type='站内通知', user_id='lifecycle_student'
                )
                .order_by(SystemLog.id.asc())
                .first()
                .id
            )
        cross_user = self.client.post(
            f'/notifications/{notification_id}/read',
            follow_redirects=False,
        )
        self.assertEqual(cross_user.status_code, 404)

        self.logout()
        self.assertEqual(self.login('lifecycle_student', 'student_password').status_code, 302)
        receipt = self.client.get(f'/feedback/receipt/{feedback_id}')
        self.assertEqual(receipt.status_code, 200)
        self.assertIn('当前状态是“已分派”'.encode('utf-8'), receipt.data)
        self.assertIn('处理进度'.encode('utf-8'), receipt.data)
        self.assertNotIn('已分派给支持人员'.encode('utf-8'), receipt.data)

        inbox = self.client.get('/notifications')
        self.assertEqual(inbox.status_code, 200)
        self.assertIn('反馈已收到'.encode('utf-8'), inbox.data)
        self.assertIn('反馈状态已更新'.encode('utf-8'), inbox.data)
        self.assertIn('2 条未读'.encode('utf-8'), inbox.data)

        with self.app.app_context():
            first_notification = (
                SystemLog.query.filter_by(
                    log_type='站内通知', user_id='lifecycle_student'
                )
                .order_by(SystemLog.id.asc())
                .first()
            )
            self.assertIsNotNone(first_notification)
            notification_id = first_notification.id

        marked = self.client.post(
            f'/notifications/{notification_id}/read',
            data={'next': 'https://external.example/not-allowed'},
            follow_redirects=False,
        )
        self.assertEqual(marked.status_code, 302)
        self.assertEqual(marked.headers['Location'], '/notifications')

        self.client.post('/notifications/read-all', follow_redirects=False)
        unread = self.client.get('/notifications?filter=unread')
        self.assertEqual(unread.status_code, 200)
        self.assertIn('当前没有未读通知'.encode('utf-8'), unread.data)

    def test_status_transition_is_bounded_and_admin_only(self):
        feedback_id = self.submit_feedback()
        anonymous = self.client.post(
            f'/admin/feedback/{feedback_id}/status',
            data={'status': 'closed'},
            follow_redirects=False,
        )
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn('/login', anonymous.headers['Location'])

        self.assertEqual(self.login('lifecycle_admin', 'admin_password').status_code, 302)
        skipped = self.client.post(
            f'/admin/feedback/{feedback_id}/status',
            data={'status': 'closed'},
            follow_redirects=True,
        )
        self.assertEqual(skipped.status_code, 200)
        self.assertIn('不能将'.encode('utf-8'), skipped.data)

        with self.app.app_context():
            record = list_feedback()[0]
            self.assertEqual(record['status'], 'received')
            self.assertEqual(SystemLog.query.filter_by(log_type='反馈状态更新').count(), 0)

    def test_profile_public_scope_is_explicit_and_reversible(self):
        self.assertEqual(self.login('lifecycle_student', 'student_password').status_code, 302)
        edit = self.client.get('/edit_profile')
        self.assertEqual(edit.status_code, 200)
        self.assertIn('profile_visibility'.encode('utf-8'), edit.data)

        saved = self.client.post(
            '/edit_profile',
            data={
                'username': 'lifecycle_student',
                'full_name': '公开资料学生',
                'email': 'lifecycle@example.com',
                'class_name': '',
                'bio': '专注于算法学习和可解释的代码反馈。',
                'profile_visibility': 'public',
            },
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 302)

        public = self.client.get('/public_profile/lifecycle_student')
        self.assertEqual(public.status_code, 200)
        self.assertIn('公开资料学生'.encode('utf-8'), public.data)
        self.assertIn('可解释的代码反馈'.encode('utf-8'), public.data)
        public_card = public.data.split(b'<section class="public-profile-card"', 1)[1].split(
            b'</section>', 1
        )[0]
        self.assertNotIn('lifecycle@example.com'.encode('utf-8'), public_card)
        self.assertNotIn('lifecycle_student'.encode('utf-8'), public_card)

        with self.app.app_context():
            settings = get_profile_settings('lifecycle_student')
            self.assertEqual(settings['profile_visibility'], 'public')
            self.assertEqual(
                SystemLog.query.filter_by(log_type='个人资料设置').count(),
                1,
            )

        private = self.client.post(
            '/edit_profile',
            data={
                'username': 'lifecycle_student',
                'full_name': '公开资料学生',
                'email': 'lifecycle@example.com',
                'class_name': '',
                'bio': '专注于算法学习和可解释的代码反馈。',
                'profile_visibility': 'private',
            },
            follow_redirects=False,
        )
        self.assertEqual(private.status_code, 302)
        self.assertEqual(self.client.get('/public_profile/lifecycle_student').status_code, 404)

        about = self.client.get('/about')
        self.assertIn('aria-current="page"'.encode('utf-8'), about.data)
        self.assertIn('授权范围内用于教学改进'.encode('utf-8'), about.data)

    def test_legacy_feedback_record_is_normalized_without_rewrite(self):
        with self.app.app_context():
            legacy = {
                'schema_version': 1,
                'feedback_id': 'FB-ABCDEF123456',
                'submitted_at': '2026-09-10T00:00:00Z',
                'category': 'other',
                'category_label': '其他',
                'subject': '旧记录',
                'message': '这是发布前已经存在的反馈记录。',
                'context': {'page': '/contact'},
            }
            db.session.add(SystemLog(
                log_type='反馈提交',
                content=json.dumps(legacy, ensure_ascii=False),
            ))
            db.session.commit()

            record = list_feedback()[0]
            self.assertEqual(record['status'], 'received')
            self.assertEqual(record['status_label'], '已收到')
            self.assertEqual(len(record['status_history']), 1)

            updated, owner_id = update_feedback_status(
                'FB-ABCDEF123456',
                'triaged',
                actor_id='lifecycle_admin',
            )
            self.assertEqual(updated['status'], 'triaged')
            self.assertIsNone(owner_id)
            stored = SystemLog.query.filter_by(log_type='反馈提交').first()
            stored_record = json.loads(stored.content)
            self.assertEqual(stored_record['status'], 'triaged')
            self.assertEqual(SystemLog.query.filter_by(log_type='反馈状态更新').count(), 1)


if __name__ == '__main__':
    unittest.main()
