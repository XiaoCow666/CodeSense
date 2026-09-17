import os
import sys
import tempfile
import unittest
from datetime import datetime as dt, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import Assignment, Class, StudentRoster, Submission, User, db
from services.teacher_analytics import (
    build_assignment_completion_matrix,
    build_class_learning_rows,
    build_submission_trend,
    build_teacher_dashboard_data,
)


class TeacherAnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            teacher = User(
                student_id='teacher_001',
                username='teacher',
                usertype='教师',
                full_name='王老师',
            )
            teacher.password = 'password123'

            cls = Class(
                name='软件2302',
                grade='2023',
                major='软件工程',
                teacher_id='teacher_001',
            )
            db.session.add_all([teacher, cls])
            db.session.flush()

            active = User(
                student_id='20230001',
                username='active_student',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='张三',
                submit_count=1,
                user_ascore=90.0,
            )
            low_score = User(
                student_id='20230002',
                username='low_score_student',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='李四',
                submit_count=1,
                user_ascore=40.0,
            )
            no_submission = User(
                student_id='20230003',
                username='quiet_student',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='王五',
                submit_count=0,
                user_ascore=0.0,
            )
            for student in (active, low_score, no_submission):
                student.password = 'password123'

            latest_assignment = Assignment(
                title='循环结构练习',
                description='for loop',
                target_classes=cls.name,
                creator_id='teacher_001',
                created_time=dt.utcnow(),
            )
            older_assignment = Assignment(
                title='数组基础',
                target_classes=cls.name,
                creator_id='teacher_001',
                created_time=dt.utcnow() - timedelta(days=10),
            )
            db.session.add_all([active, low_score, no_submission, latest_assignment, older_assignment])
            db.session.flush()

            db.session.add_all([
                Submission(
                    student_id='20230001',
                    assignment_id=latest_assignment.id,
                    code='print(1)',
                    score=100,
                    submitted_at=dt.utcnow() - timedelta(days=1),
                    status='evaluated',
                ),
                Submission(
                    student_id='20230002',
                    assignment_id=latest_assignment.id,
                    code='print(2)',
                    score=40,
                    submitted_at=dt.utcnow() - timedelta(days=2),
                    status='evaluated',
                ),
                Submission(
                    student_id='20230001',
                    assignment_id=older_assignment.id,
                    code='print(3)',
                    score=80,
                    submitted_at=dt.utcnow() - timedelta(days=10),
                    status='evaluated',
                ),
                StudentRoster(
                    student_id='20230004',
                    full_name='赵六',
                    class_id=cls.id,
                    class_name_snapshot=cls.name,
                    imported_by='teacher_001',
                    is_registered=False,
                ),
            ])
            db.session.commit()

            self.teacher_id = teacher.student_id
            self.class_id = cls.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login_teacher(self):
        return self.client.post('/login', data={
            'username': 'teacher',
            'password': 'password123',
        }, follow_redirects=False)

    def test_teacher_dashboard_data_summarizes_attention_and_class_cards(self):
        with self.app.app_context():
            teacher = User.query.get(self.teacher_id)

            dashboard = build_teacher_dashboard_data(teacher)

            self.assertEqual(dashboard['student_count'], 3)
            self.assertEqual(dashboard['total_submissions'], 3)
            self.assertEqual(dashboard['attention']['low_score_count'], 1)
            self.assertEqual(dashboard['attention']['inactive_count'], 1)
            self.assertEqual(dashboard['attention']['no_submission_count'], 1)
            self.assertEqual(dashboard['attention']['unregistered_roster_count'], 1)
            self.assertEqual(len(dashboard['submission_trend']), 14)
            self.assertEqual(sum(day['count'] for day in dashboard['submission_trend']), 3)

            card = dashboard['class_cards'][0]
            self.assertEqual(card['class'].name, '软件2302')
            self.assertEqual(card['student_count'], 3)
            self.assertEqual(card['risk_count'], 2)
            self.assertEqual(card['latest_assignment'].title, '循环结构练习')
            self.assertEqual(card['latest_completed'], 2)
            self.assertEqual(card['latest_total'], 3)
            self.assertEqual(card['completion_rate'], 66.7)

    def test_submission_trend_builds_daily_buckets(self):
        with self.app.app_context():
            trend = build_submission_trend(
                ['20230001', '20230002', '20230003'],
                days=14,
                now=dt.utcnow(),
            )

            self.assertEqual(len(trend), 14)
            self.assertEqual(trend[-2]['count'], 1)
            self.assertEqual(trend[-3]['count'], 1)
            self.assertEqual(trend[-11]['count'], 1)
            self.assertEqual(trend[-1]['count'], 0)

    def test_assignment_completion_matrix_marks_recent_assignment_cells(self):
        with self.app.app_context():
            cls = Class.query.get(self.class_id)

            matrix = build_assignment_completion_matrix(cls)

            self.assertEqual([assignment.title for assignment in matrix['assignments']], [
                '循环结构练习',
                '数组基础',
            ])
            self.assertEqual(matrix['summary'][0]['completed'], 2)
            self.assertEqual(matrix['summary'][0]['completion_rate'], 66.7)

            by_id = {row['student'].student_id: row for row in matrix['rows']}
            active_cells = {cell['assignment'].title: cell for cell in by_id['20230001']['cells']}
            low_cells = {cell['assignment'].title: cell for cell in by_id['20230002']['cells']}
            quiet_cells = {cell['assignment'].title: cell for cell in by_id['20230003']['cells']}

            self.assertEqual(active_cells['循环结构练习']['status'], '优秀')
            self.assertEqual(active_cells['数组基础']['status'], '优秀')
            self.assertEqual(low_cells['循环结构练习']['status'], '低分')
            self.assertEqual(quiet_cells['循环结构练习']['status'], '缺交')

    def test_class_learning_rows_label_student_statuses(self):
        with self.app.app_context():
            cls = Class.query.get(self.class_id)

            rows = build_class_learning_rows(cls)

            by_id = {row['student'].student_id: row for row in rows}
            self.assertEqual(by_id['20230001']['status'], '优秀')
            self.assertEqual(by_id['20230001']['risk_tags'], [])
            self.assertEqual(by_id['20230002']['status'], '需关注')
            self.assertIn('低分', by_id['20230002']['risk_tags'])
            self.assertEqual(by_id['20230003']['status'], '未开始')
            self.assertIn('未提交', by_id['20230003']['risk_tags'])
            self.assertIsNone(by_id['20230003']['latest_submission'])

    def test_teacher_dashboard_renders_learning_summary(self):
        self.login_teacher()

        response = self.client.get('/teacher_dashboard')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('今日需要关注', body)
        self.assertIn('班级学习概况', body)
        self.assertIn('近 14 天提交趋势', body)
        self.assertIn('软件2302', body)
        self.assertIn('studentSnapshotSearch', body)
        self.assertIn('studentSnapshotStatus', body)
        self.assertIn('studentSnapshotNext', body)

    def test_class_detail_renders_learning_rows(self):
        self.login_teacher()

        response = self.client.get(f'/classes/{self.class_id}')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('学生学情概览', body)
        self.assertIn('最近作业完成矩阵', body)
        self.assertIn('需关注', body)
        self.assertIn('未开始', body)


if __name__ == '__main__':
    unittest.main()
