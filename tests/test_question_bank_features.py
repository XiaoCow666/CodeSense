import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import Assignment, Class, Submission, User, db


class QuestionBankFeaturesTestCase(unittest.TestCase):
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
                student_id='teacher_001',
                username='teacher',
                usertype='教师',
                full_name='王老师',
            )
            teacher.password = 'password123'
            other_teacher = User(
                student_id='teacher_002',
                username='other_teacher',
                usertype='教师',
                full_name='李老师',
            )
            other_teacher.password = 'password123'
            class_a = Class(name='软件工程24-1班', teacher_id='teacher_001')
            class_b = Class(name='软件工程24-2班', teacher_id='teacher_001')
            db.session.add_all([teacher, other_teacher, class_a, class_b])
            db.session.flush()

            students = [
                User(
                    student_id='student_a1',
                    username='student_a1',
                    usertype='学生',
                    full_name='学生甲一',
                    class_id=class_a.id,
                    class_name=class_a.name,
                ),
                User(
                    student_id='student_a2',
                    username='student_a2',
                    usertype='学生',
                    full_name='学生甲二',
                    class_id=class_a.id,
                    class_name=class_a.name,
                ),
                User(
                    student_id='student_b1',
                    username='student_b1',
                    usertype='学生',
                    full_name='学生乙一',
                    class_id=class_b.id,
                    class_name=class_b.name,
                ),
            ]
            for student in students:
                student.password = 'password123'

            assignment_one = Assignment(
                id=1001,
                title='循环结构练习',
                description='题目一',
                creator_id=teacher.student_id,
                target_classes=f'{class_a.name},{class_b.name}',
            )
            assignment_two = Assignment(
                id=1002,
                title='数组基础',
                description='题目二',
                creator_id=teacher.student_id,
            )
            outsider_assignment = Assignment(
                id=1003,
                title='其他教师题目',
                description='不应被教师导出或修改',
                creator_id=other_teacher.student_id,
            )
            db.session.add_all(students + [assignment_one, assignment_two, outsider_assignment])
            db.session.flush()

            # 学生甲一重复提交两次，完成统计应仍然只算 1 人。
            db.session.add_all([
                Submission(
                    student_id='student_a1',
                    assignment_id=assignment_one.id,
                    code='print(1)',
                    score=80,
                    status='evaluated',
                ),
                Submission(
                    student_id='student_a1',
                    assignment_id=assignment_one.id,
                    code='print(2)',
                    score=90,
                    status='evaluated',
                ),
                Submission(
                    student_id='student_b1',
                    assignment_id=assignment_one.id,
                    code='print(3)',
                    score=70,
                    status='evaluated',
                ),
            ])
            db.session.commit()

            self.assignment_one_id = assignment_one.id
            self.assignment_two_id = assignment_two.id
            self.outsider_assignment_id = outsider_assignment.id

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
        })

    def test_teacher_can_bulk_update_owned_question_deadlines_only(self):
        self.login_teacher()

        response = self.client.post('/teacher/bulk-due-date', data={
            'assignment_ids': [
                str(self.assignment_one_id),
                str(self.assignment_two_id),
                str(self.outsider_assignment_id),
            ],
            'due_date': '2026-10-01T18:00',
        })

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                Assignment.query.get(self.assignment_one_id).due_date.strftime('%Y-%m-%d %H:%M'),
                '2026-10-01 18:00',
            )
            self.assertEqual(
                Assignment.query.get(self.assignment_two_id).due_date.strftime('%Y-%m-%d %H:%M'),
                '2026-10-01 18:00',
            )
            self.assertIsNone(Assignment.query.get(self.outsider_assignment_id).due_date)

    def test_teacher_question_bank_exposes_bulk_edit_controls(self):
        self.login_teacher()

        response = self.client.get('/teacher')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('批量修改截止时间', body)
        self.assertIn('批量设置班级', body)
        self.assertIn('导出题库', body)
        self.assertIn('bulk-due-date-form', body)
        self.assertIn('bulk-class-form', body)

    def test_teacher_can_bulk_assign_classes_to_owned_questions_only(self):
        with self.app.app_context():
            foreign_class = Class(name='软件工程24-3班', teacher_id='teacher_002')
            db.session.add(foreign_class)
            db.session.flush()
            assignment = Assignment.query.get(self.assignment_one_id)
            assignment.set_target_classes([
                '软件工程24-1班',
                '软件工程24-3班',
            ])
            db.session.commit()

        self.login_teacher()

        response = self.client.post('/teacher/bulk-classes', data={
            'assignment_ids': [
                str(self.assignment_one_id),
                str(self.assignment_two_id),
                str(self.outsider_assignment_id),
            ],
            'class_names': ['软件工程24-1班', '软件工程24-2班'],
        })

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                set(Assignment.query.get(self.assignment_one_id).get_target_class_list()),
                {'软件工程24-1班', '软件工程24-2班', '软件工程24-3班'},
            )
            self.assertEqual(
                set(Assignment.query.get(self.assignment_two_id).get_target_class_list()),
                {'软件工程24-1班', '软件工程24-2班'},
            )
            self.assertEqual(
                Assignment.query.get(self.outsider_assignment_id).get_target_class_list(),
                [],
            )

    def test_teacher_can_export_own_question_bank_as_csv(self):
        self.login_teacher()

        response = self.client.get('/question-bank/export?format=csv')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('.csv', response.headers['Content-Disposition'])
        body = response.get_data(as_text=True)
        self.assertIn('循环结构练习', body)
        self.assertIn('数组基础', body)
        self.assertNotIn('其他教师题目', body)

        excel_response = self.client.get('/question-bank/export?format=xlsx')
        self.assertEqual(excel_response.status_code, 200)
        self.assertEqual(
            excel_response.mimetype,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertTrue(excel_response.data.startswith(b'PK'))

    def test_assignment_detail_shows_completion_by_class_and_deduplicates_submissions(self):
        self.login_teacher()

        response = self.client.get(f'/view_assignment/{self.assignment_one_id}')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('按班级查看完成情况', body)
        self.assertIn('软件工程24-1班', body)
        self.assertIn('软件工程24-2班', body)
        self.assertIn('1/2 人', body)
        self.assertIn('1/1 人', body)


if __name__ == '__main__':
    unittest.main()
