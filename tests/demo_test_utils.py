"""测试用的 Flask 应用与临时 SQLite 数据库工具。"""

import os
import tempfile

from app import create_app
from models import db


def create_test_app():
    """创建一个隔离的测试应用，并初始化全部数据库表。"""
    db_fd, db_path = tempfile.mkstemp()
    app = create_app('testing')
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}',
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )

    with app.app_context():
        db.drop_all()
        db.create_all()

    app._demo_test_db_fd = db_fd
    app._demo_test_db_path = db_path
    return app


def destroy_test_app(app):
    """释放测试应用占用的临时数据库文件。"""
    with app.app_context():
        db.session.remove()
        db.drop_all()
    os.close(app._demo_test_db_fd)
    os.unlink(app._demo_test_db_path)
