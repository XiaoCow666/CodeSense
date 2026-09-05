import unittest
from unittest.mock import patch

from models import AbilityTrend, db
from services.api_keys import api_keys
from services.demo_database import activate_demo_run
from services.demo_experience import DEMO_STUDENT_ID
from tasks.ability_analysis import generate_ability_analysis_async
from tests.demo_test_utils import create_test_app, destroy_test_app


class ImmediateThread:
    """Run an async worker inline so the test can inspect its committed result."""

    def __init__(self, target, *args, **kwargs):
        self.target = target
        self.daemon = False

    def start(self):
        self.target()


class RecordingEvaluator:
    calls = 0
    should_fail = False

    def __init__(self, api_key):
        self.api_key = api_key

    def analyze_ability_trend_stream(self, submission_data):
        type(self).calls += 1
        if type(self).should_fail:
            raise RuntimeError('模拟 AI 服务失败')
        yield f'真实 AI 分析第 {type(self).calls} 次：共处理 {len(submission_data)} 条提交。'


class DemoAIRefreshTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()
        self.client.get('/demo-login/student')
        with self.client.session_transaction() as client_session:
            self.run_id = client_session['demo_run_id']
        RecordingEvaluator.calls = 0
        RecordingEvaluator.should_fail = False

    def tearDown(self):
        destroy_test_app(self.app)

    def test_demo_analysis_is_real_refreshable_and_stays_out_of_formal_db(self):
        with patch('tasks.ability_analysis.threading.Thread', ImmediateThread), \
                patch('tasks.ability_analysis.AIEvaluator', RecordingEvaluator), \
                patch.object(api_keys, '_zhipu_key', 'demo-test-key'), \
                patch('services.llm_client.SharedLLMClient.is_available', return_value=True):
            generate_ability_analysis_async(self.app, DEMO_STUDENT_ID, demo_run_id=self.run_id)

            with self.app.app_context():
                self.assertTrue(activate_demo_run(self.run_id))
                trend = AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one()
                self.assertEqual(trend.status, 'completed')
                self.assertIn('真实 AI 分析第 1 次', trend.analysis_markdown)
                first_updated = trend.last_updated

                trend.status = 'outdated'
                db.session.commit()

            generate_ability_analysis_async(self.app, DEMO_STUDENT_ID, demo_run_id=self.run_id)

            with self.app.app_context():
                self.assertTrue(activate_demo_run(self.run_id))
                trend = AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one()
                self.assertEqual(trend.status, 'completed')
                self.assertIn('真实 AI 分析第 2 次', trend.analysis_markdown)
                self.assertGreaterEqual(trend.last_updated, first_updated)

        with self.app.app_context():
            self.assertEqual(AbilityTrend.query.count(), 0)
        self.assertEqual(RecordingEvaluator.calls, 2)

    def test_demo_ai_failure_is_explicitly_marked_failed(self):
        RecordingEvaluator.should_fail = True
        with patch('tasks.ability_analysis.threading.Thread', ImmediateThread), \
                patch('tasks.ability_analysis.AIEvaluator', RecordingEvaluator), \
                patch.object(api_keys, '_zhipu_key', 'demo-test-key'), \
                patch('services.llm_client.SharedLLMClient.is_available', return_value=True):
            generate_ability_analysis_async(self.app, DEMO_STUDENT_ID, demo_run_id=self.run_id)

        with self.app.app_context():
            self.assertTrue(activate_demo_run(self.run_id))
            trend = AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one()
            self.assertEqual(trend.status, 'failed')
            self.assertFalse(trend.analysis_markdown)


if __name__ == '__main__':
    unittest.main()
