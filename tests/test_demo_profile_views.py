"""Regression tests for the public demo's student and teacher views."""

import re
import unittest

from models import Assignment, Class, KnowledgePointScore
from services.demo_database import activate_demo_run
from services.demo_experience import (
    C_LANGUAGE_POINTS,
    DEMO_CLASS_NAME,
    DEMO_ASSIGNMENT_TITLE,
    DEMO_SECOND_ASSIGNMENT_TITLE,
)
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoProfileViewsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def _login(self, role):
        response = self.client.get(f'/demo-login/{role}')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as client_session:
            run_id = client_session['demo_run_id']
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            demo_class = Class.query.filter_by(name=DEMO_CLASS_NAME).one()
            assignments = Assignment.query.order_by(Assignment.id).all()
            knowledge_count = KnowledgePointScore.query.filter_by(
                student_id='demo_s_001'
            ).count()
        return run_id, demo_class.id, assignments, knowledge_count

    def test_student_views_render_complete_profile_and_score_scale(self):
        _, _, _, knowledge_count = self._login('student')
        self.assertEqual(knowledge_count, len(C_LANGUAGE_POINTS))

        home = self.client.get('/home')
        self.assertEqual(home.status_code, 200)
        home_html = home.data.decode('utf-8')
        self.assertEqual(
            len(re.findall(r'data-knowledge-point="[a-z_]+"', home_html)),
            len(C_LANGUAGE_POINTS),
        )
        self.assertIn('提交评分 0–5 分', home_html)
        self.assertIn('多维度贝叶斯权重评估（0–100）', home_html)
        self.assertIn('AI 个性化分析', home_html)
        self.assertIn('data-analysis-status=', home_html)
        self.assertIn('/5', home_html)
        self.assertIn('基础语法', home_html)
        self.assertIn('递归', home_html)

        profile = self.client.get('/user_profile/student_demo_good')
        self.assertEqual(profile.status_code, 200)
        profile_html = profile.data.decode('utf-8')
        self.assertEqual(
            len(re.findall(r'data-knowledge-point="[a-z_]+"', profile_html)),
            len(C_LANGUAGE_POINTS),
        )
        self.assertIn('C语言知识点画像', profile_html)
        self.assertIn('提交分数 0–5 分', profile_html)
        for _, name in C_LANGUAGE_POINTS:
            self.assertIn(name, profile_html)

        assignment_list = self.client.get('/student_assignments')
        self.assertEqual(assignment_list.status_code, 200)
        assignment_html = assignment_list.data.decode('utf-8')
        self.assertIn('个人最高分（0–5）', assignment_html)
        self.assertIn(DEMO_ASSIGNMENT_TITLE, assignment_html)
        self.assertIn(DEMO_SECOND_ASSIGNMENT_TITLE, assignment_html)

    def test_student_analysis_status_api_exposes_temporary_state(self):
        self._login('student')
        response = self.client.get('/api/student/ability-trend-status')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        data = payload['data']
        self.assertIn(data['status'], {'pending', 'processing', 'completed', 'failed', 'outdated'})
        self.assertGreaterEqual(data['submissions_count'], 10)
        self.assertIn('last_updated', data)

    def test_teacher_views_render_roster_assignments_trend_and_ai_state(self):
        _, class_id, assignments, _ = self._login('teacher')
        self.assertGreaterEqual(len(assignments), 6)

        dashboard = self.client.get('/home', follow_redirects=True)
        self.assertEqual(dashboard.status_code, 200)
        dashboard_html = dashboard.data.decode('utf-8')
        self.assertIn('近 14 天提交趋势', dashboard_html)
        self.assertIn('data-trend-points="14"', dashboard_html)
        self.assertIn('提交评分 0–5 分', dashboard_html)
        self.assertIn('AI 建议状态', dashboard_html)
        self.assertIn('孙三（风险）', dashboard_html)

        class_list = self.client.get('/classes/')
        self.assertEqual(class_list.status_code, 200)
        class_list_html = class_list.data.decode('utf-8')
        self.assertIn('软件工程24-演示班', class_list_html)
        self.assertIn('班级平均分（0–5）', class_list_html)
        self.assertIn('data-class-id=', class_list_html)

        class_detail = self.client.get(f'/classes/{class_id}')
        self.assertEqual(class_detail.status_code, 200)
        class_detail_html = class_detail.data.decode('utf-8')
        self.assertIn('assignment-matrix', class_detail_html)
        self.assertIn('周四', class_detail_html)
        self.assertIn('李四（未注册）', class_detail_html)
        self.assertIn('提交得分（0–5）', class_detail_html)
        self.assertIn(DEMO_SECOND_ASSIGNMENT_TITLE, class_detail_html)

        assignments_page = self.client.get('/teacher')
        self.assertEqual(assignments_page.status_code, 200)
        assignments_html = assignments_page.data.decode('utf-8')
        self.assertIn('提交/平均分（0–5）', assignments_html)
        self.assertGreaterEqual(assignments_html.count('data-assignment-id='), 6)
        self.assertIn(DEMO_ASSIGNMENT_TITLE, assignments_html)

        suggestions = self.client.get('/teacher/ai_suggestions')
        self.assertEqual(suggestions.status_code, 200)
        suggestions_html = suggestions.data.decode('utf-8')
        self.assertIn('AI 个性化教学建议', suggestions_html)
        self.assertIn('data-ai-status=', suggestions_html)
        self.assertIn('最近更新', suggestions_html)


if __name__ == '__main__':
    unittest.main()
