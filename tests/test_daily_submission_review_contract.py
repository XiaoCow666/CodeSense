import unittest

from tests.demo_test_utils import create_test_app, destroy_test_app


class DailySubmissionReviewContractTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def test_teacher_review_queue_is_available_after_integration(self):
        login = self.client.get('/demo-login/teacher')
        self.assertEqual(login.status_code, 302)

        response = self.client.get('/teacher/reviews')

        self.assertEqual(response.status_code, 200)

    def test_submission_review_service_exposes_request_contract(self):
        try:
            from services.submission_reviews import create_review_request
        except ImportError as exc:
            self.fail(f'submission review service is missing: {exc}')

        self.assertTrue(callable(create_review_request))


if __name__ == '__main__':
    unittest.main()
