import unittest

from tests.demo_test_utils import create_test_app, destroy_test_app


class PublicEditorDemoTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_test_app()
        self.client = self.app.test_client()

    def tearDown(self):
        destroy_test_app(self.app)

    def test_public_editor_pages_render_working_editor_assets(self):
        for path, heading in (
            ('/test_editor', '代码编辑器体验'),
            ('/cpp_editor_demo', 'C++ 编辑器演示'),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.data.decode('utf-8')
                self.assertIn(heading, html)
                self.assertIn('id="editor-demo-code"', html)
                self.assertIn('js/cpp-editor.js', html)
                self.assertIn('css/cpp-editor.css', html)
