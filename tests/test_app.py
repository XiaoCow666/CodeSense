"""
应用程序单元测试
"""
import unittest
import os
import sys
import tempfile
from unittest.mock import patch

# 确保正确导入项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User


class AppTestCase(unittest.TestCase):
    """应用测试类"""
    
    def setUp(self):
        """设置测试环境"""
        self.db_fd, db_path = tempfile.mkstemp()
        self.app = create_app('testing')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        with self.app.app_context():
            db.create_all()
            
            # 创建测试管理员用户
            admin = User(
                student_id='test_admin',
                username='test_admin',
                usertype='管理员',
                class_name='测试班级',
                full_name='测试管理员',
                submit_count=0,
                user_ascore=0.0,
                user_tscore=0
            )
            admin.password = 'test_password'
            
            # 创建测试学生用户
            student = User(
                student_id='test_student',
                username='test_student',
                usertype='学生',
                class_name='测试班级',
                full_name='测试学生',
                submit_count=0,
                user_ascore=0.0,
                user_tscore=0
            )
            student.password = 'test_password'
            
            db.session.add(admin)
            db.session.add(student)
            db.session.commit()
    
    def tearDown(self):
        """清理测试环境"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''))
    
    def test_login(self):
        """测试登录功能"""
        # 测试正确的登录
        response = self.client.post('/login', data={
            'username': 'test_admin',
            'password': 'test_password'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('管理员仪表盘'.encode('utf-8'), response.data)
        
        # 登出以便测试错误登录
        self.client.get('/logout', follow_redirects=True)
        
        # 测试错误的登录
        response = self.client.post('/login', data={
            'username': 'test_admin',
            'password': 'wrong_password'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # 检查是否包含错误提示（UTF-8编码）
        self.assertIn(b'\xe7\x94\xa8\xe6\x88\xb7\xe5\x90\x8d\xe6\x88\x96\xe5\xaf\x86\xe7\xa0\x81\xe9\x94\x99\xe8\xaf\xaf', response.data)  
    
    def test_home_page(self):
        """测试主页访问"""
        # 登录
        self.client.post('/login', data={
            'username': 'test_admin',
            'password': 'test_password'
        })
        
        # 访问主页 (管理员会重定向到仪表盘)
        response = self.client.get('/home', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('管理员仪表盘'.encode('utf-8'), response.data)

    def test_access_log_contains_opaque_request_id(self):
        import logging

        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        access_logger = logging.getLogger('access')
        access_logger.addHandler(handler)
        self.app.config['ACCESS_LOG_ENABLED'] = True
        try:
            response = self.client.get('/healthz')
            self.assertEqual(response.status_code, 200)
        finally:
            access_logger.removeHandler(handler)

        self.assertTrue(records)
        self.assertRegex(records[-1], r'request_id=[0-9a-f-]{32,36}')
        self.assertIn('GET /healthz', records[-1])

    def test_healthz_is_database_independent(self):
        """存活探针在数据库不可用时仍应只报告进程存活。"""
        with patch(
            'app.db.session.execute',
            side_effect=AssertionError('healthz touched database'),
        ) as execute:
            response = self.client.get('/healthz')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')
        self.assertGreaterEqual(response.get_json()['uptime_seconds'], 0)
        execute.assert_not_called()

    def test_readyz_reports_database_health(self):
        with patch('app.db.session.execute', wraps=db.session.execute) as execute:
            response = self.client.get('/readyz')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            'status': 'ready',
            'checks': {'database': 'ok'},
        })
        execute.assert_called_once()

    def test_readyz_rolls_back_and_reports_database_failure(self):
        with patch(
            'app.db.session.execute',
            side_effect=RuntimeError('database unavailable'),
        ) as execute, patch('app.db.session.rollback') as rollback:
            response = self.client.get('/readyz')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            'status': 'not_ready',
            'checks': {'database': 'unavailable'},
        })
        execute.assert_called_once()
        rollback.assert_called_once()

    def test_admin_access_teacher_route(self):
        """测试管理员访问教师专用路由"""
        from models import Assignment
        
        # 登录管理员
        self.client.post('/login', data={
            'username': 'test_admin',
            'password': 'test_password'
        })
        
        # 创建一个测试作业
        with self.app.app_context():
            assignment = Assignment(
                title='测试作业',
                description='这是一份测试作业',
                creator_id='test_admin'
            )
            db.session.add(assignment)
            db.session.commit()
            assignment_id = assignment.id
            
        # 访问编辑页面 (受 @teacher_required 保护)
        # 现在管理员应该可以直接访问
        response = self.client.get(f'/teacher/edit/{assignment_id}', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        # 检查是否渲染了编辑页面 (含有 '编辑作业' 字样)
        self.assertIn(b'\xe7\xbc\x96\xe8\xbe\x91\xe4\xbd\x9c\xe4\xb8\x9a', response.data)


if __name__ == '__main__':
    unittest.main()
