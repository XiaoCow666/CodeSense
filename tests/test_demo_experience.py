import json
import unittest

from models import (
    AbilityTrend,
    Assignment,
    AssignmentThinkingPreset,
    Class,
    Submission,
    ThinkingSession,
    TestCase as AssignmentTestCase,
    TeacherAISuggestion,
    User,
    db,
)
from services.demo_experience import (
    DEMO_ASSIGNMENT_TITLE,
    DEMO_CLASS_NAME,
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    ensure_demo_experience,
)
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoExperienceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()

    def tearDown(self):
        destroy_test_app(self.app)

    def test_seed_is_complete_and_idempotent(self):
        with self.app.app_context():
            first = ensure_demo_experience()
            first_session = ThinkingSession(
                student_id=DEMO_STUDENT_ID,
                assignment_id=first.assignment_id,
                current_stage=2,
                stage1_description='我已经完成了循环分析。',
            )
            first_submission = Submission(
                student_id=DEMO_STUDENT_ID,
                assignment_id=first.assignment_id,
                code='int main() { return 0; }',
                score=88,
                status='evaluated',
            )
            db.session.add_all([first_session, first_submission])
            db.session.commit()
            session_id = first_session.id
            submission_id = first_submission.id

            second = ensure_demo_experience()

            self.assertEqual(first.teacher_id, DEMO_TEACHER_ID)
            self.assertEqual(first.student_id, DEMO_STUDENT_ID)
            self.assertEqual(first.class_id, second.class_id)
            self.assertEqual(first.assignment_id, second.assignment_id)
            self.assertEqual(User.query.filter_by(student_id=DEMO_TEACHER_ID).count(), 1)
            self.assertEqual(User.query.filter_by(student_id=DEMO_STUDENT_ID).count(), 1)
            self.assertEqual(Class.query.filter_by(name=DEMO_CLASS_NAME).count(), 1)
            self.assertEqual(Assignment.query.filter_by(title=DEMO_ASSIGNMENT_TITLE).count(), 1)
            self.assertIsNotNone(ThinkingSession.query.get(session_id))
            self.assertIsNotNone(Submission.query.get(submission_id))

            assignment = Assignment.query.get(first.assignment_id)
            self.assertGreaterEqual(AssignmentTestCase.query.filter_by(assignment_id=assignment.id).count(), 2)
            preset = AssignmentThinkingPreset.query.filter_by(assignment_id=assignment.id).one()
            self.assertEqual(preset.status, 'ready')
            self.assertTrue(preset.reference_code)
            self.assertTrue(json.loads(preset.key_steps))
            self.assertTrue(json.loads(preset.code_blocks))
            self.assertTrue(json.loads(preset.quiz_steps))

            trend = AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one()
            self.assertEqual(trend.status, 'completed')
            self.assertTrue(trend.analysis_markdown)
            self.assertTrue(json.loads(trend.trend_data))

            suggestion = TeacherAISuggestion.query.filter_by(class_id=first.class_id).one()
            self.assertEqual(suggestion.status, 'completed')
            self.assertIn('演示', suggestion.suggestion_markdown)


if __name__ == '__main__':
    unittest.main()
