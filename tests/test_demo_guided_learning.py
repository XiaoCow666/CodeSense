import json
import unittest
from pathlib import Path
from unittest.mock import patch

from models import Assignment, AssignmentThinkingPreset, Submission, ThinkingSession, User, db
from services.demo_database import activate_demo_run
from services.demo_experience import get_demo_assignment_id
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoGuidedLearningTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(
                student_id='regular_teacher',
                username='regular_teacher',
                usertype='教师',
                full_name='普通教师',
            )
            teacher.password = 'password'
            student = User(
                student_id='regular_student',
                username='regular_student',
                usertype='学生',
                full_name='普通学生',
                class_name='普通班级',
            )
            student.password = 'password'
            regular_assignment = Assignment(
                title='普通作业',
                description='普通作业描述',
                creator_id='regular_teacher',
                target_classes='普通班级',
            )
            db.session.add_all([teacher, student, regular_assignment])
            db.session.flush()
            db.session.add(AssignmentThinkingPreset(
                assignment_id=regular_assignment.id,
                reference_code='int main() { return 0; }',
                key_steps=json.dumps(['完成输入、处理和输出'], ensure_ascii=False),
                code_blocks=json.dumps([{'id': 'regular-1', 'code': 'return 0;'}]),
                noise_blocks='[]',
                quiz_steps=json.dumps([{
                    'step_id': 1,
                    'type': 'fill',
                    'question': '填写返回值',
                    'correct_answer': '0',
                }]),
                difficulty_config=json.dumps({'feynman_rounds': 2}),
                status='ready',
            ))
            db.session.commit()
            self.regular_assignment_id = regular_assignment.id

    def _login_demo(self):
        response = self.client.get('/demo-login/student')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as client_session:
            return client_session['demo_run_id']

    def _demo_assignment_id(self, run_id, key='guided_fibonacci'):
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            return get_demo_assignment_id(run_id, key)

    def tearDown(self):
        destroy_test_app(self.app)

    def test_demo_student_arena_has_demo_marker(self):
        login_response = self.client.get('/demo-login/student')
        arena_response = self.client.get(login_response.headers['Location'])

        self.assertEqual(arena_response.status_code, 200)
        self.assertIn('data-demo-experience="1"'.encode('utf-8'), arena_response.data)
        self.assertIn('演示作业一：循环与斐波那契数列'.encode('utf-8'), arena_response.data)

    def test_demo_start_session_returns_all_three_stage_preset_data(self):
        run_id = self._login_demo()
        assignment_id = self._demo_assignment_id(run_id)
        response = self.client.post('/thinking/api/start_session', json={
            'assignment_id': assignment_id,
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['preset']['status'], 'ready')
        self.assertGreaterEqual(len(payload['preset']['key_steps']), 3)
        self.assertGreaterEqual(len(payload['preset']['blocks']), 6)
        self.assertGreaterEqual(len(payload['preset']['quiz_steps']), 3)
        self.assertTrue(payload['preset']['algorithm_summary'])
        self.assertEqual(payload['preset']['difficulty']['feynman_rounds'], 2)

    def test_regular_student_arena_has_no_demo_marker(self):
        self.client.post('/login', data={
            'username': 'regular_student',
            'password': 'password',
        })
        response = self.client.get(f'/thinking/{self.regular_assignment_id}')

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-demo-experience="0"'.encode('utf-8'), response.data)

    def test_frontend_exposes_four_demo_stage_shortcuts_but_keeps_auto_actions_local(self):
        source = Path('static/js/thinking.js').read_text(encoding='utf-8')

        self.assertIn("dataset.demoExperience === '1'", source)
        self.assertIn('if (!isLocal && !isDemo) return;', source)
        for stage in (1, 2, 3, 4):
            self.assertIn(f'window.ThinkingArena.debugJumpStage({stage})', source)
        self.assertIn('isDemo ?', source)
        self.assertIn('stage === 4 && isDemo', source)

    def test_public_demo_shortcuts_can_move_shared_session_through_all_stages(self):
        base_url = 'https://experience.codesense.test'
        self.client.get('/demo-login/student', base_url=base_url)
        with self.client.session_transaction() as client_session:
            run_id = client_session['demo_run_id']
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            demo_assignment_id = get_demo_assignment_id(run_id)
            shared_session = ThinkingSession(
                student_id='demo_s_001',
                assignment_id=demo_assignment_id,
            )
            db.session.add(shared_session)
            db.session.commit()
            session_id = shared_session.id

        for stage in (1, 2, 3, 4):
            response = self.client.post(
                '/thinking/api/debug/jump_stage',
                base_url=base_url,
                json={'session_id': session_id, 'stage': stage},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()['success'])

        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            updated = ThinkingSession.query.get(session_id)
            self.assertEqual(updated.status, 'completed')
            self.assertTrue(updated.stage3_completed)

    def test_public_shortcut_rejects_regular_student_other_assignment_and_anonymous(self):
        base_url = 'https://experience.codesense.test'
        with self.app.app_context():
            regular_session = ThinkingSession(
                student_id='regular_student',
                assignment_id=self.regular_assignment_id,
            )
            db.session.add(regular_session)
            db.session.commit()
            regular_session_id = regular_session.id

        self.client.post('/login', base_url=base_url, data={
            'username': 'regular_student',
            'password': 'password',
        })
        regular_response = self.client.post(
            '/thinking/api/debug/jump_stage',
            base_url=base_url,
            json={'session_id': regular_session_id, 'stage': 2},
        )
        self.assertEqual(regular_response.status_code, 403)

        self.client.get('/logout', base_url=base_url)
        self.client.get('/demo-login/student', base_url=base_url)
        with self.client.session_transaction() as client_session:
            run_id = client_session['demo_run_id']
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            other_assignment_session = ThinkingSession(
                student_id='demo_s_001',
                assignment_id=get_demo_assignment_id(run_id, 'guided_tree'),
            )
            db.session.add(other_assignment_session)
            db.session.commit()
            other_assignment_session_id = other_assignment_session.id
        other_assignment_response = self.client.post(
            '/thinking/api/debug/jump_stage',
            base_url=base_url,
            json={'session_id': other_assignment_session_id, 'stage': 2},
        )
        self.assertEqual(other_assignment_response.status_code, 200)

        self.client.get('/logout', base_url=base_url)
        anonymous_response = self.client.post(
            '/thinking/api/debug/jump_stage',
            base_url=base_url,
            json={'session_id': regular_session_id, 'stage': 2},
        )
        self.assertEqual(anonymous_response.status_code, 403)

    def test_demo_tree_preset_recovers_without_queueing_formal_ai_task(self):
        run_id = self._login_demo()
        assignment_id = self._demo_assignment_id(run_id, 'guided_tree')

        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            preset = AssignmentThinkingPreset.query.filter_by(
                assignment_id=assignment_id,
            ).one()
            preset.status = 'failed'
            preset.quiz_steps = '[]'
            db.session.commit()

        with patch('utils.async_tasks.add_generate_preset_task') as queue_task:
            arena_response = self.client.get(f'/thinking/{assignment_id}')
            self.assertEqual(arena_response.status_code, 200)
            queue_task.assert_not_called()

        start_response = self.client.post('/thinking/api/start_session', json={
            'assignment_id': assignment_id,
        })
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.get_json()['preset']['status'], 'ready')

    def test_demo_tree_assignment_supports_quick_jump(self):
        run_id = self._login_demo()
        assignment_id = self._demo_assignment_id(run_id, 'guided_tree')
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            thinking_session = ThinkingSession(
                student_id='demo_s_001',
                assignment_id=assignment_id,
            )
            db.session.add(thinking_session)
            db.session.commit()
            session_id = thinking_session.id

        response = self.client.post('/thinking/api/debug/jump_stage', json={
            'session_id': session_id,
            'stage': 3,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])

    def test_demo_guided_completion_creates_temporary_five_point_submission(self):
        run_id = self._login_demo()
        assignment_id = self._demo_assignment_id(run_id)
        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            thinking_session = ThinkingSession(
                student_id='demo_s_001',
                assignment_id=assignment_id,
            )
            db.session.add(thinking_session)
            db.session.commit()
            session_id = thinking_session.id

        with patch('tasks.ability_analysis.trigger_analysis_if_needed', return_value=False):
            response = self.client.post('/thinking/api/debug/jump_stage', json={
                'session_id': session_id,
                'stage': 4,
            })
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            self.assertTrue(activate_demo_run(run_id))
            submission = Submission.query.filter_by(
                student_id='demo_s_001',
                assignment_id=assignment_id,
            ).filter(Submission.code.like('/* codesense-demo-guided-session:%')).one()
            self.assertEqual(submission.status, 'evaluated')
            self.assertGreaterEqual(submission.score, 0)
            self.assertLessEqual(submission.score, 5)

        with self.app.app_context():
            self.assertEqual(Submission.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
