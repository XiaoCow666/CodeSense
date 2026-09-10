"""编译失败评分回归测试。

验证 submission_tasks.py 中 compile_error 状态的分数限制逻辑：
- 编译错误时最终分数不超过 1
- 正常通过/部分通过时分数不受此限制
"""

import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from config import TestingConfig
from models import Assignment, Submission, TestCase, User, db
import tasks.submission_tasks as worker_tasks


@pytest.fixture
def app_with_submission(tmp_path, monkeypatch):
    """创建带测试用例和提交记录的测试应用。"""
    database_path = tmp_path / "compile_error_scoring.db"
    monkeypatch.setattr(
        TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    monkeypatch.setattr(TestingConfig, "ASYNC_TASKS_ENABLED", False)
    monkeypatch.setattr(TestingConfig, "PRESET_SCAN_ENABLED", False)

    app = create_app("testing")
    app.config["SUBMISSION_EVALUATION_QUEUE_BACKEND"] = "thread"

    with app.app_context():
        db.create_all()
        student = User(
            student_id="test-student",
            username="test-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="compile error test",
            description="test compile error scoring",
            creator_id="test-student",
        )
        db.session.add_all([student, assignment])
        db.session.flush()

        # 创建两个测试用例
        tc1 = TestCase(
            assignment_id=assignment.id,
            input_data="1",
            expected_output="1",
            order_index=0,
        )
        tc2 = TestCase(
            assignment_id=assignment.id,
            input_data="2",
            expected_output="2",
            order_index=1,
        )
        db.session.add_all([tc1, tc2])

        submission = Submission(
            student_id="test-student",
            assignment=assignment,
            code="int main() { return 0; }",
            status="pending",
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.id
        assignment_title = assignment.title

    yield app, submission_id, assignment_title

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_compile_error_caps_score_at_1(app_with_submission):
    """编译错误时，即使沙箱计算分数大于 1，最终分数也不超过 1。"""
    app, submission_id, assignment_title = app_with_submission

    # AI 评估返回 80 分（归一化后为 4 分）
    with patch.object(
        worker_tasks,
        "evaluate_cpp_code",
        return_value=(80, "AI feedback"),
    ), patch.object(
        worker_tasks,
        "run_test_cases",
        return_value={
            "status": "compile_error",
            "passed": 1,  # 模拟异常情况：编译错误但有通过用例
            "total": 2,   # sandbox_score = 1/2*5 = 2.5
            "details": [],
        },
    ):
        with app.app_context():
            worker_tasks.run_submission_evaluation(
                app, submission_id, assignment_title
            )
            updated = db.session.get(Submission, submission_id)
            assert updated.status == "evaluated"
            assert updated.sandbox_status == "compile_error"
            # compile_error 时 final_score = min(2.5, 1) = 1
            assert updated.score <= 1
            assert updated.score == 1


def test_normal_passing_score_not_capped(app_with_submission):
    """正常通过时，分数不受 compile_error 限制影响。"""
    app, submission_id, assignment_title = app_with_submission

    with patch.object(
        worker_tasks,
        "evaluate_cpp_code",
        return_value=(80, "AI feedback"),
    ), patch.object(
        worker_tasks,
        "run_test_cases",
        return_value={
            "status": "passed",
            "passed": 2,
            "total": 2,  # sandbox_score = 2/2*5 = 5
            "details": [],
        },
    ):
        with app.app_context():
            worker_tasks.run_submission_evaluation(
                app, submission_id, assignment_title
            )
            updated = db.session.get(Submission, submission_id)
            assert updated.status == "evaluated"
            assert updated.sandbox_status == "passed"
            # 正常通过时 final_score = 5，不受限
            assert updated.score == 5


def test_partial_passing_score_not_capped(app_with_submission):
    """部分通过时，分数不受 compile_error 限制影响。"""
    app, submission_id, assignment_title = app_with_submission

    with patch.object(
        worker_tasks,
        "evaluate_cpp_code",
        return_value=(80, "AI feedback"),
    ), patch.object(
        worker_tasks,
        "run_test_cases",
        return_value={
            "status": "partial",
            "passed": 2,
            "total": 3,  # sandbox_score = 2/3*5 ≈ 3.333，归一化后为 3
            "details": [],
        },
    ):
        with app.app_context():
            worker_tasks.run_submission_evaluation(
                app, submission_id, assignment_title
            )
            updated = db.session.get(Submission, submission_id)
            assert updated.status == "evaluated"
            assert updated.sandbox_status == "partial"
            # 部分通过时 final_score ≈ 3.333，归一化后为 3，不受 compile_error 限制
            assert updated.score == 3
            assert updated.score > 1
