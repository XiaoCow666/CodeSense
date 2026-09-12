import os
import sys
import tempfile
import unittest
import json
from datetime import datetime as dt, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import Assignment, Class, Submission, User, KnowledgePointScore, TeacherAISuggestion, db
from services.teacher_ai_advisor import (
    _generate_rule_based_markdown,
    generate_class_suggestions,
    generate_class_suggestions_stream,
)

class TeacherAISuggestionsTestCase(unittest.TestCase):
    def setUp(self):
        from services.teacher_ai_advisor import _generation_locks
        _generation_locks.clear()

        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # 创建教师
            teacher = User(
                student_id='teacher_002',
                username='teacher2',
                usertype='教师',
                full_name='李老师',
            )
            teacher.password = 'password123'

            # 创建班级
            cls = Class(
                name='计科2405',
                grade='2024',
                major='计算机科学与技术',
                teacher_id='teacher_002',
            )
            db.session.add_all([teacher, cls])
            db.session.flush()

            # 创建学生
            s1 = User(
                student_id='20240001',
                username='student_good',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='赵一',
                user_ascore=4.8,
            )
            s2 = User(
                student_id='20240002',
                username='student_risk',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='钱二',
                user_ascore=2.1,
            )
            for s in (s1, s2):
                s.password = 'password123'

            # 创建知识点得分
            k1 = KnowledgePointScore(
                student_id='20240001',
                knowledge_point='pointer',
                score=85.0,
                total_attempts=6
            )
            k2 = KnowledgePointScore(
                student_id='20240002',
                knowledge_point='pointer',
                score=35.0,
                total_attempts=8
            )
            k3 = KnowledgePointScore(
                student_id='20240002',
                knowledge_point='array',
                score=50.0,
                total_attempts=4
            )

            # 创建作业
            assign1 = Assignment(
                title='指针进阶',
                target_classes=cls.name,
                creator_id='teacher_002',
                created_time=dt.utcnow(),
            )
            assign2 = Assignment(
                title='指针初探',
                target_classes='其他班级',
                creator_id='teacher_002',
                created_time=dt.utcnow(),
                difficulty_level=2
            )
            
            db.session.add_all([s1, s2, k1, k2, k3, assign1, assign2])
            db.session.flush()

            from models import AssignmentKnowledgePoint
            akp = AssignmentKnowledgePoint(
                assignment_id=assign2.id,
                knowledge_point='pointer',
                weight=1.0,
                difficulty=1.0
            )
            db.session.add(akp)
            db.session.flush()

            # 创建提交
            sub1 = Submission(
                student_id='20240001',
                assignment_id=assign1.id,
                code='int* p;',
                score=5.0,
                submitted_at=dt.utcnow() - timedelta(days=1),
                status='evaluated'
            )
            sub2 = Submission(
                student_id='20240002',
                assignment_id=assign1.id,
                code='int p;',
                score=2.0,
                submitted_at=dt.utcnow() - timedelta(days=2),
                status='evaluated'
            )
            db.session.add_all([sub1, sub2])
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
            'username': 'teacher2',
            'password': 'password123',
        }, follow_redirects=False)

    def test_database_model(self):
        with self.app.app_context():
            sug = TeacherAISuggestion.get_or_create(self.class_id, self.teacher_id)
            self.assertIsNotNone(sug)
            self.assertEqual(sug.class_id, self.class_id)
            self.assertEqual(sug.teacher_id, self.teacher_id)
            self.assertEqual(sug.status, 'pending')

    def test_rules_based_suggestion_generation(self):
        with self.app.app_context():
            sug = generate_class_suggestions(self.class_id, self.teacher_id)
            self.assertIsNotNone(sug)
            self.assertEqual(sug.status, 'completed')
            self.assertIsNotNone(sug.suggestion_markdown)
            self.assertIsNotNone(sug.suggestion_json)
            
            # 解析 json 并做断言
            details = sug.get_suggestion_dict()
            self.assertIn('attention_students', details)
            self.assertIn('weak_knowledge_points', details)
            
            # 钱二应该被识别为重点关注学生，因为他分数为 2.1 < 3.0 触发了低分风险
            attention_names = [s['name'] for s in details['attention_students']]
            self.assertIn('钱二', attention_names)

            # 指针的平均分应当是 (85 + 35) / 2 = 60.0，且在薄弱概念里
            weak_kps = [wp['point_name'] for wp in details['weak_knowledge_points']]
            self.assertIn('指针', weak_kps)

            # 指针初探应当在建议补练作业里，且难度是“较易”
            self.assertIn('suggested_assignments', details)
            suggested_titles = [a['title'] for a in details['suggested_assignments']]
            self.assertIn('指针初探', suggested_titles)
            
            # 找到指针初探
            assign_detail = [a for a in details['suggested_assignments'] if a['title'] == '指针初探'][0]
            self.assertEqual(assign_detail['difficulty'], '较易')

    def test_routes_accessibility(self):
        self.login_teacher()
        
        # 1. 访问 suggestions 落地页
        response = self.client.get('/teacher/ai_suggestions')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('计科2405', body)
        self.assertIn('AI 教学个性化建议', body)
        self.assertIn('role="status"', body)
        self.assertIn('aria-busy="true"', body)
        self.assertIn('DOMPurify.sanitize', body)
        self.assertIn('function escapeHtml', body)

        # 2. 触发 API 刷新建议
        response = self.client.post('/api/teacher/generate_suggestions', data=json.dumps({
            'class_id': self.class_id
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        res_json = json.loads(response.get_data(as_text=True))
        self.assertTrue(res_json['success'])

        # 3. 访问 API 获取状态
        response = self.client.get(f'/api/teacher/suggestion_status/{self.class_id}')
        self.assertEqual(response.status_code, 200)
        res_json = json.loads(response.get_data(as_text=True))
        self.assertIn('status', res_json)

        # 4. 访问流式建议接口 (SSE)
        response = self.client.get(f'/api/teacher/stream_suggestions?class_id={self.class_id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/event-stream')
        stream_data = response.get_data(as_text=True)
        self.assertIn('data:', stream_data)

    def test_stream_uses_common_protocol_and_keeps_markdown_before_split_delimiter(self):
        class FakeLLM:
            def is_available(self):
                return True

            def chat_stream(self, messages, **kwargs):
                self.request_kind = kwargs['request_kind']
                return iter([
                    '## JSON 只是正文里的词\n\n正文说明\n===JS',
                    'ON===\n{"attention_students":[],"weak_knowledge_points":[],"suggested_assignments":[]}',
                ])

        fake_llm = FakeLLM()
        with self.app.app_context(), patch(
            'services.teacher_ai_advisor.SharedLLMClient', return_value=fake_llm
        ):
            events = [
                json.loads(line[6:])
                for line in generate_class_suggestions_stream(self.class_id, self.teacher_id)
                if line.startswith('data: ')
            ]

        self.assertEqual(events[0]['type'], 'status')
        self.assertIn('start', [event['type'] for event in events])
        self.assertEqual(events[-1]['type'], 'done')
        self.assertNotIn('chunk', [event['type'] for event in events])
        self.assertNotIn('complete', [event['type'] for event in events])
        visible = ''.join(event.get('content', '') for event in events if event['type'] == 'delta')
        self.assertIn('JSON 只是正文里的词', visible)
        self.assertIn('正文说明', visible)
        self.assertNotIn('===JSON===', visible)
        self.assertEqual(fake_llm.request_kind, 'interactive')

    def test_stream_completes_with_markdown_when_legacy_json_tail_is_invalid(self):
        class FakeLLM:
            def is_available(self):
                return True

            def chat_stream(self, messages, **kwargs):
                return iter([
                    '## 可用的 AI 正文\n\n先给出教学建议。',
                    '===JSON===\n{"attention_students": [',
                ])

        fake_llm = FakeLLM()
        with self.app.app_context(), patch(
            'services.teacher_ai_advisor.SharedLLMClient', return_value=fake_llm
        ):
            events = [
                json.loads(line[6:])
                for line in generate_class_suggestions_stream(self.class_id, self.teacher_id)
                if line.startswith('data: ')
            ]

        self.assertEqual(events[-1]['type'], 'done')
        self.assertNotIn('error', [event['type'] for event in events])
        visible = ''.join(
            event.get('content', '') for event in events if event['type'] == 'delta'
        )
        self.assertIn('可用的 AI 正文', visible)
        self.assertNotIn('===JSON===', visible)
        self.assertIn('attention_students', events[-1]['suggestion_json'])

if __name__ == '__main__':
    unittest.main()

