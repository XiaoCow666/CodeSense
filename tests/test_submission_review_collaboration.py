import json
import os
import tempfile
import unittest

from app import create_app
from config import config
from models import Assignment, Class, Submission, SystemLog, User, db
from services.submission_reviews import (
    ReviewPermissionError,
    ReviewStatusError,
    ReviewValidationError,
    add_review_message,
    create_review_request,
    get_ai_feedback_signal,
    get_submission_review,
    list_review_queue,
    save_ai_feedback_signal,
    transition_review,
)


class SubmissionReviewCollaborationTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        os.close(self.db_fd)
        config['testing'].SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            self.teacher = User(
                student_id='review_teacher',
                username='review_teacher',
                usertype='教师',
                full_name='复核教师',
            )
            self.teacher.password = 'teacher_password'
            self.other_teacher = User(
                student_id='other_teacher',
                username='other_teacher',
                usertype='教师',
                full_name='其他教师',
            )
            self.other_teacher.password = 'teacher_password'
            self.student = User(
                student_id='review_student',
                username='review_student',
                usertype='学生',
                full_name='复核学生',
                email='review@example.com',
            )
            self.student.password = 'student_password'
            self.outsider = User(
                student_id='review_outsider',
                username='review_outsider',
                usertype='学生',
                full_name='无关学生',
            )
            self.outsider.password = 'student_password'
            self.admin = User(
                student_id='review_admin',
                username='review_admin',
                usertype='管理员',
                full_name='复核管理员',
            )
            self.admin.password = 'admin_password'
            db.session.add_all([
                self.teacher,
                self.other_teacher,
                self.student,
                self.outsider,
                self.admin,
            ])
            db.session.flush()

            self.classroom = Class(
                name='复核测试班',
                teacher_id=self.teacher.student_id,
            )
            db.session.add(self.classroom)
            db.session.flush()
            self.student.class_id = self.classroom.id
            assignment = Assignment(
                title='复核测试作业',
                description='用于复核协作测试',
                target_classes=self.classroom.name,
                creator_id=self.teacher.student_id,
            )
            db.session.add(assignment)
            db.session.flush()
            self.submission = Submission(
                student_id=self.student.student_id,
                assignment_id=assignment.id,
                code='int main() { return 0; }',
                score=2,
                status='evaluated',
                ai_feedback='可以先检查边界条件，再比较测试输出。',
            )
            db.session.add(self.submission)
            db.session.commit()
            self.teacher_id = 'review_teacher'
            self.other_teacher_id = 'other_teacher'
            self.student_id = 'review_student'
            self.outsider_id = 'review_outsider'
            self.admin_id = 'review_admin'
            self.submission_id = self.submission.id
            self.assignment_id = assignment.id

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

    def test_request_is_idempotent_and_messages_reopen_resolved_review(self):
        with self.app.app_context():
            submission = db.session.get(Submission, self.submission_id)
            student = db.session.get(User, self.student_id)
            teacher = db.session.get(User, self.teacher_id)

            first, created = create_review_request(
                submission,
                student.student_id,
                '隐藏测试用例失败后，我想确认应该先检查哪个边界条件。',
            )
            second, duplicate = create_review_request(
                submission,
                student.student_id,
                '重复点击不应创建第二个复核线程。',
            )
            self.assertTrue(created)
            self.assertFalse(duplicate)
            self.assertEqual(first['review_id'], second['review_id'])
            self.assertEqual(
                SystemLog.query.filter_by(log_type='提交复核').count(),
                1,
            )

            review, _ = transition_review(submission, teacher, 'in_review')
            self.assertEqual(review['status'], 'in_review')
            review, _ = add_review_message(
                submission,
                teacher,
                '我会先看输入为空和重复值两类边界，请补充你的观察。',
            )
            self.assertEqual(review['status'], 'waiting_student')
            review, _ = add_review_message(
                submission,
                student,
                '我复现了空输入分支，下一步会补一个测试用例。',
            )
            self.assertEqual(review['status'], 'in_review')
            review, _ = transition_review(submission, teacher, 'resolved')
            self.assertEqual(review['status'], 'resolved')
            review, _ = add_review_message(
                submission,
                student,
                '我已经补测并重新提交，想继续确认结果。',
            )
            self.assertEqual(review['status'], 'in_review')
            self.assertEqual(
                [event['event'] for event in review['events']],
                ['request', 'status', 'status', 'message', 'status', 'message', 'status', 'status', 'message'],
            )

    def test_status_machine_rejects_skip_duplicate_and_student_mutation(self):
        with self.app.app_context():
            submission = db.session.get(Submission, self.submission_id)
            student = db.session.get(User, self.student_id)
            teacher = db.session.get(User, self.teacher_id)
            create_review_request(submission, student.student_id, '请帮我复核。')

            with self.assertRaises(ReviewStatusError):
                transition_review(submission, teacher, 'resolved')
            with self.assertRaises(ReviewStatusError):
                transition_review(submission, teacher, 'requested')
            transition_review(submission, teacher, 'in_review')
            with self.assertRaises(ReviewStatusError):
                transition_review(submission, teacher, 'in_review')
            with self.assertRaises(ReviewPermissionError):
                transition_review(submission, student, 'waiting_student')

    def test_queue_is_scoped_to_managed_class_and_filters_status(self):
        with self.app.app_context():
            submission = db.session.get(Submission, self.submission_id)
            student = db.session.get(User, self.student_id)
            teacher = db.session.get(User, self.teacher_id)
            other_teacher = db.session.get(User, self.other_teacher_id)
            admin = db.session.get(User, self.admin_id)
            create_review_request(submission, student.student_id, '需要教师复核。')

            teacher_queue = list_review_queue(teacher)
            self.assertEqual(len(teacher_queue), 1)
            self.assertEqual(teacher_queue[0]['submission'].id, self.submission_id)
            self.assertEqual(list_review_queue(other_teacher), [])
            self.assertEqual(len(list_review_queue(admin)), 1)
            self.assertEqual(list_review_queue(teacher, status='in_review'), [])
            transition_review(submission, teacher, 'in_review')
            self.assertEqual(len(list_review_queue(teacher, status='in_review')), 1)

    def test_ai_feedback_signal_is_owner_only_and_upserted(self):
        with self.app.app_context():
            save_ai_feedback_signal(
                self.submission_id,
                self.student_id,
                'helpful',
            )
            save_ai_feedback_signal(
                self.submission_id,
                self.student_id,
                'needs_clarification',
            )
            self.assertEqual(
                get_ai_feedback_signal(self.submission_id, self.student_id),
                'needs_clarification',
            )
            self.assertEqual(
                SystemLog.query.filter_by(log_type='AI反馈信号').count(),
                1,
            )
            with self.assertRaises(ReviewPermissionError):
                save_ai_feedback_signal(
                    self.submission_id,
                    self.outsider_id,
                    'helpful',
                )
            with self.assertRaises(ReviewValidationError):
                save_ai_feedback_signal(
                    self.submission_id,
                    self.student_id,
                    'unknown',
                )

    def test_stored_events_are_versioned_and_do_not_contain_code_snapshot(self):
        with self.app.app_context():
            submission = db.session.get(Submission, self.submission_id)
            create_review_request(submission, self.student_id, '请看一下边界条件。')
            log = SystemLog.query.filter_by(log_type='提交复核').first()
            payload = json.loads(log.content)
            self.assertEqual(payload['schema_version'], 1)
            self.assertNotIn('code', payload)
            self.assertNotIn('code_snapshot', payload)
            self.assertNotIn('int main()', log.content)

    def test_submission_review_routes_render_and_enforce_participants(self):
        anonymous = self.client.post(
            f'/submission/{self.submission_id}/review/request',
            data={'body': '未登录不能提交复核。'},
            follow_redirects=False,
        )
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn('/login', anonymous.headers['Location'])

        self.assertEqual(self.login('review_student', 'student_password').status_code, 302)
        detail = self.client.get(f'/view_submission/{self.submission_id}')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('申请教师复核', detail.get_data(as_text=True))

        request_response = self.client.post(
            f'/submission/{self.submission_id}/review/request',
            data={'body': '隐藏测试用例失败后，我想确认应该先检查哪个边界条件。'},
            follow_redirects=False,
        )
        duplicate_response = self.client.post(
            f'/submission/{self.submission_id}/review/request',
            data={'body': '重复点击不应创建第二个复核线程。'},
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)
        self.assertEqual(duplicate_response.status_code, 302)

        with self.app.app_context():
            self.assertEqual(
                SystemLog.query.filter_by(log_type='提交复核').count(),
                1,
            )

        self.client.get('/logout')
        self.assertEqual(self.login('review_teacher', 'teacher_password').status_code, 302)
        teacher_detail = self.client.get(f'/view_submission/{self.submission_id}')
        self.assertEqual(teacher_detail.status_code, 200)
        self.assertIn('待教师查看', teacher_detail.get_data(as_text=True))
        teacher_message = self.client.post(
            f'/submission/{self.submission_id}/review/message',
            data={'body': '请补充一个失败输入的最小复现。'},
            follow_redirects=False,
        )
        self.assertEqual(teacher_message.status_code, 302)

        self.client.get('/logout')
        self.assertEqual(self.login('other_teacher', 'teacher_password').status_code, 302)
        outsider_response = self.client.post(
            f'/submission/{self.submission_id}/review/message',
            data={'body': '无关班级教师不应写入复核。'},
            follow_redirects=False,
        )
        self.assertEqual(outsider_response.status_code, 403)

        self.client.get('/logout')
        self.assertEqual(self.login('review_student', 'student_password').status_code, 302)
        oversized = self.client.post(
            f'/submission/{self.submission_id}/review/message',
            data={'body': 'x' * 2001},
            follow_redirects=False,
        )
        self.assertEqual(oversized.status_code, 302)

        with self.app.app_context():
            review = get_submission_review(self.submission_id)
            self.assertEqual(review['status'], 'waiting_student')
            self.assertEqual(
                len([event for event in review['events'] if event['event'] == 'message']),
                1,
            )


if __name__ == '__main__':
    unittest.main()
