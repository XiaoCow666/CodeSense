"""教师 AI 建议「真实入口」集成测试（阶段十五）。

与纯函数单元测试不同，本文件通过真实 HTTP 入口驱动完整链路：

    浏览器落地页 GET /teacher/ai_suggestions
        └─ POST/GET /api/teacher/stream_suggestions  (SSE，首次生成唯一路径)
    刷新按钮 POST /api/teacher/generate_suggestions (异步 + 状态轮询)

证明：
1. 阶段十四的低分标签口径说明与历史综合分确实随真实请求送达 LLM；
2. 旧功能（落地页、SSE 协议、状态接口、持久化）继续可用；
3. 失败处理：流式 LLM 抛错时走规则引擎兜底且状态不卡在 processing；
   异步任务意外出错时状态从 pending 翻成 failed。

沿用 tests/test_teacher_ai_suggestions.py 的既有方式：create_app('testing')
+ 临时 SQLite，测试结束即删除；不访问网络、不连 Redis。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime as dt, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import (
    Assignment,
    Class,
    KnowledgePointScore,
    Submission,
    TeacherAISuggestion,
    User,
    db,
)
from services.teacher_ai_advisor import generate_class_suggestions_async


class CapturingLLM:
    """记录真实发送的 messages；可模拟流式失败。"""

    def __init__(self, chunks=None, raise_exc=None):
        self.captured_messages = None
        self.captured_kwargs = None
        self._chunks = list(chunks) if chunks is not None else []
        self._raise_exc = raise_exc

    def is_available(self):
        return True

    def chat_stream(self, messages, **kwargs):
        self.captured_messages = messages
        self.captured_kwargs = kwargs
        if self._raise_exc is not None:
            raise self._raise_exc
        for chunk in self._chunks:
            yield chunk


class UnavailableLLM:
    def is_available(self):
        return False

    def chat_stream(self, messages, **kwargs):
        raise RuntimeError('LLM unavailable')
        yield  # pragma: no cover - make this a generator


class TeacherAdviceRealEntryTestCase(unittest.TestCase):
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

            teacher = User(
                student_id='teacher_015',
                username='teacher15',
                usertype='教师',
                full_name='李老师',
            )
            teacher.password = 'password123'
            cls = Class(
                name='计科2415',
                grade='2024',
                major='计算机科学与技术',
                teacher_id='teacher_015',
            )
            db.session.add_all([teacher, cls])
            db.session.flush()

            # 孙三型：历史综合分 44（低分标签来源），最近一次提交 100
            sun = User(
                student_id='20240003',
                username='student_sun',
                usertype='学生',
                class_id=cls.id,
                class_name=cls.name,
                full_name='孙三',
                user_ascore=44.0,
            )
            sun.password = 'password123'
            db.session.add(sun)
            db.session.flush()

            assignment = Assignment(
                title='循环结构练习',
                target_classes=cls.name,
                creator_id='teacher_015',
                created_time=dt.utcnow(),
            )
            db.session.add(assignment)
            db.session.flush()

            db.session.add(KnowledgePointScore(
                student_id='20240003',
                knowledge_point='loop',
                score=44.0,
                total_attempts=4,
            ))
            db.session.add(Submission(
                student_id='20240003',
                assignment_id=assignment.id,
                code='int main(){return 0;}',
                score=100.0,
                submitted_at=dt.utcnow() - timedelta(days=1),
                status='evaluated',
            ))
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
            'username': 'teacher15',
            'password': 'password123',
        }, follow_redirects=False)

    def parse_sse(self, response):
        events = []
        for line in response.get_data(as_text=True).splitlines():
            if line.startswith('data: '):
                events.append(json.loads(line[6:]))
        return events

    def stream_suggestions(self, fake_llm):
        with patch(
            'services.teacher_ai_advisor.SharedLLMClient',
            return_value=fake_llm,
        ):
            response = self.client.get(
                f'/api/teacher/stream_suggestions?class_id={self.class_id}'
            )
            # stream_with_context 惰性迭代：必须在 patch 生效期间强制消费
            response.get_data()
        return response, fake_llm

    # ---- 1. 阶段十四成果随真实入口送达 LLM ----

    def test_real_sse_entry_delivers_risk_tag_caliber_to_llm(self):
        fake_llm = CapturingLLM(chunks=['## 孙三近期进步明显\n\n建议继续巩固基础。'])
        self.login_teacher()

        response, fake_llm = self.stream_suggestions(fake_llm)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/event-stream')
        messages = fake_llm.captured_messages
        self.assertIsNotNone(messages)

        system_text = messages[0]['content']
        user_text = messages[1]['content']

        # 口径说明随 system prompt 送达
        self.assertIn('历史综合分', system_text)
        self.assertIn('低分', system_text)
        self.assertIn('60', system_text)
        # 孙三行同时含历史综合分 44、最近一次 100，且标注低分标签来源
        self.assertIn('孙三', user_text)
        self.assertIn('44', user_text)
        self.assertIn('100', user_text)
        self.assertIn('低分标签来自历史综合分', user_text)
        # 流式真实入口必须是 interactive 请求类型
        self.assertEqual(fake_llm.captured_kwargs['request_kind'], 'interactive')

    # ---- 2. 旧功能继续可用 ----

    def test_real_sse_entry_completes_persists_and_page_still_renders(self):
        fake_llm = CapturingLLM(chunks=['## 周报正文\n\n教学建议内容。'])
        self.login_teacher()

        response, _ = self.stream_suggestions(fake_llm)
        events = self.parse_sse(response)

        self.assertEqual(events[0]['type'], 'status')
        self.assertIn('start', [e['type'] for e in events])
        self.assertEqual(events[-1]['type'], 'done')

        # 落地页继续可读
        page = self.client.get('/teacher/ai_suggestions')
        self.assertEqual(page.status_code, 200)
        self.assertIn('计科2415', page.get_data(as_text=True))

        # 记录已持久化，状态接口继续可用
        status = self.client.get(f'/api/teacher/suggestion_status/{self.class_id}')
        self.assertEqual(status.status_code, 200)
        payload = json.loads(status.get_data(as_text=True))
        self.assertEqual(payload['status'], 'completed')
        self.assertIn('周报正文', payload['suggestion_markdown'])

        with self.app.app_context():
            row = TeacherAISuggestion.query.filter_by(class_id=self.class_id).one()
            self.assertEqual(row.status, 'completed')
            self.assertIsNotNone(row.suggestion_json)

    # ---- 3. 失败处理：流式 LLM 抛错 → 规则引擎兜底 ----

    def test_sse_stream_error_falls_back_without_stuck_processing(self):
        fake_llm = CapturingLLM(raise_exc=RuntimeError('provider connection reset'))
        self.login_teacher()

        response, _ = self.stream_suggestions(fake_llm)
        events = self.parse_sse(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1]['type'], 'done')
        visible = ''.join(e.get('content', '') for e in events if e['type'] == 'delta')
        # 非 demo 正式账户：走规则引擎兜底
        self.assertIn('规则引擎', visible)

        with self.app.app_context():
            row = TeacherAISuggestion.query.filter_by(class_id=self.class_id).one()
            self.assertEqual(row.status, 'completed')
            self.assertNotEqual(row.status, 'processing')

    def test_sse_llm_unavailable_uses_rules_fallback(self):
        self.login_teacher()
        response, _ = self.stream_suggestions(UnavailableLLM())
        events = self.parse_sse(response)

        self.assertEqual(events[-1]['type'], 'done')
        visible = ''.join(e.get('content', '') for e in events if e['type'] == 'delta')
        self.assertIn('规则引擎', visible)

    # ---- 4. 失败处理：异步任务意外出错不卡在 pending ----

    def test_async_entry_unexpected_error_marks_failed(self):
        with self.app.app_context():
            sug = TeacherAISuggestion.get_or_create(
                class_id=self.class_id,
                teacher_id=self.teacher_id,
            )
            sug.status = 'pending'
            db.session.commit()

            with patch(
                'services.teacher_ai_advisor.generate_class_suggestions',
                side_effect=RuntimeError('unexpected worker failure'),
            ):
                thread = generate_class_suggestions_async(
                    self.class_id,
                    self.teacher_id,
                    self.app,
                )
                thread.join(timeout=10)
            self.assertFalse(thread.is_alive())

            db.session.expire_all()
            row = TeacherAISuggestion.query.filter_by(class_id=self.class_id).one()
            self.assertEqual(row.status, 'failed')


if __name__ == '__main__':
    unittest.main()
