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
from services.demo_database import activate_demo_run, create_demo_run, destroy_demo_run
from services.demo_experience import (
    DEMO_ASSIGNMENT_TITLE,
    DEMO_CLASS_NAME,
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    seed_demo_experience,
)
from tests.demo_test_utils import create_test_app, destroy_test_app


class DemoExperienceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        with self.app.app_context():
            self.run = create_demo_run('student')
            self.assertTrue(activate_demo_run(self.run.run_id))
            self.demo = seed_demo_experience(self.run)

    def tearDown(self):
        destroy_demo_run(self.run.run_id)
        destroy_test_app(self.app)

    def test_seed_is_complete_and_idempotent_inside_one_temporary_database(self):
        with self.app.app_context():
            self.assertTrue(activate_demo_run(self.run.run_id))
            first_session = ThinkingSession(
                student_id=DEMO_STUDENT_ID,
                assignment_id=self.demo.assignment_id,
                current_stage=2,
                stage1_description='我已经完成了循环分析。',
            )
            first_submission = Submission(
                student_id=DEMO_STUDENT_ID,
                assignment_id=self.demo.assignment_id,
                code='int main(void) { return 4; }',
                score=4,
                status='evaluated',
            )
            db.session.add_all([first_session, first_submission])
            db.session.commit()
            session_id = first_session.id
            submission_id = first_submission.id

            second = seed_demo_experience(self.run)

            self.assertEqual(self.demo.teacher_id, DEMO_TEACHER_ID)
            self.assertEqual(self.demo.student_id, DEMO_STUDENT_ID)
            self.assertEqual(self.demo.class_id, second.class_id)
            self.assertEqual(self.demo.assignment_id, second.assignment_id)
            self.assertNotEqual(self.demo.assignment_id, self.demo.second_assignment_id)
            self.assertEqual(User.query.count(), 13)  # 1 teacher + 12 students
            self.assertEqual(User.query.filter_by(student_id=DEMO_STUDENT_ID).count(), 1)
            self.assertEqual(Class.query.filter_by(name=DEMO_CLASS_NAME).count(), 1)
            self.assertEqual(Assignment.query.count(), 6)
            self.assertIsNotNone(ThinkingSession.query.get(session_id))
            self.assertIsNotNone(Submission.query.get(submission_id))
            self.assertGreaterEqual(Submission.query.filter_by(student_id=DEMO_STUDENT_ID).count(), 13)

            assignment = Assignment.query.get(self.demo.assignment_id)
            self.assertGreaterEqual(AssignmentTestCase.query.filter_by(assignment_id=assignment.id).count(), 2)
            presets = AssignmentThinkingPreset.query.order_by(AssignmentThinkingPreset.assignment_id).all()
            self.assertEqual(len(presets), 2)
            for preset in presets:
                self.assertEqual(preset.status, 'ready')
                self.assertTrue(preset.reference_code)
                self.assertTrue(json.loads(preset.key_steps))
                self.assertTrue(json.loads(preset.code_blocks))
                self.assertTrue(json.loads(preset.quiz_steps))

            trend = AbilityTrend.query.filter_by(student_id=DEMO_STUDENT_ID).one()
            self.assertIn(trend.status, ('pending', 'completed', 'processing', 'failed'))
            self.assertTrue(json.loads(trend.trend_data))

            suggestion = TeacherAISuggestion.query.filter_by(class_id=self.demo.class_id).one()
            self.assertIn(suggestion.status, ('pending', 'completed', 'processing', 'failed'))

        # The formal database is deliberately never used by the fixture.
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)
            self.assertEqual(Class.query.count(), 0)
            self.assertEqual(Assignment.query.count(), 0)
            self.assertEqual(Submission.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
