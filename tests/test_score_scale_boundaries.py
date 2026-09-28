import json
import pytest
from datetime import datetime
from flask import Flask

from models import Assignment, Submission, User, db
from services.ai_evaluator import _parse_code_assessment
from tasks.submission_tasks import (
    _normalise_score,
    _refresh_assignment_stats,
    _refresh_user_stats,
)
from utils.ability_scorer import AbilityScorer
from utils.scoring import (
    display_submission_ai_feedback,
    normalize_evaluation_score,
    normalize_structured_feedback_scores,
    normalize_submission_score,
)


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (1, 5, 20),
        (5, 5, 100),
        (1, 10, 10),
        (10, 10, 100),
        (1, 100, 1),
        (5, 100, 5),
        (10, 100, 10),
        (100, 100, 100),
    ],
)
def test_score_conversion_uses_source_scale(value, scale, expected):
    assert normalize_evaluation_score(value, scale=scale) == expected


def test_submission_worker_keeps_percent_scores():
    assert _normalise_score(100 * 1 / 20) == 5
    assert _normalise_score(5) == 5
    assert _normalise_score(20) == 20
    assert _normalise_score(100) == 100


@pytest.mark.parametrize(("value", "scale"), [(-1, 100), (101, 100), (6, 5), (float("nan"), 100)])
def test_score_conversion_rejects_invalid_range(value, scale):
    with pytest.raises(ValueError):
        normalize_evaluation_score(value, scale=scale)


def test_structured_feedback_keeps_percent_dimensions():
    source = {
        "overall_score": 1,
        "algorithm_score": 5,
        "style_score": 80,
        "feedback": "继续练习",
    }
    result = normalize_structured_feedback_scores(source)
    assert result["overall_score"] == 20
    assert result["algorithm_score"] == 5
    assert result["style_score"] == 80
    assert result["feedback"] == "继续练习"
    assert source["overall_score"] == 1


def test_historical_and_current_submissions_use_their_recorded_scale():
    assert normalize_submission_score(5, datetime(2026, 9, 17, 12, 0)) == 100
    assert normalize_submission_score(2, datetime(2026, 9, 18, 2, 0)) == 40
    assert normalize_submission_score(2, datetime(2026, 9, 18, 10, 0)) == 2
    assert normalize_submission_score(5, datetime(2026, 9, 27, 12, 0)) == 5
    assert normalize_submission_score(0, datetime(2026, 9, 27, 12, 0)) == 0


def test_real_provider_code_assessment_keeps_distinct_dimensions():
    response = '''```json
{
  "algorithm_score": 0,
  "style_score": 30,
  "functionality_score": 50,
  "efficiency_score": 100,
  "readability_score": 40,
  "feedback": "算法评分0分，因为程序没有实现任何算法逻辑。风格评分30分，代码过于简单。"
}
```'''
    result = _parse_code_assessment(response)
    assert result["algorithm_score"] == 0
    assert result["style_score"] == 30
    assert result["efficiency_score"] == 100


def test_code_assessment_rejects_missing_dimension():
    with pytest.raises(ValueError):
        _parse_code_assessment('{"algorithm_score": 60, "feedback": "缺少分项"}')


def test_structured_submission_feedback_has_readable_sections():
    stored = '''{"overall_score": 40, "overall_feedback": "检查循环条件。", "algorithm_score": 30, "dimension_feedback": "循环边界需要验证。"}'''
    view = display_submission_ai_feedback(stored)
    assert view["overall_feedback"] == "检查循环条件。"
    assert view["dimension_feedback"] == "循环边界需要验证。"
    assert view["dimensions"] == {"algorithm": 30}
    assert display_submission_ai_feedback("继续练习")["overall_feedback"] == "继续练习"


def test_submission_summaries_are_stable_after_recalculation(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'scores.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        student = User(student_id="score-student", username="score-student", usertype="学生")
        student.password = "score-password"
        assignment = Assignment(
            title="百分制练习",
            description="检查低分与重复计算",
            creator_id=student.student_id,
        )
        db.session.add_all([student, assignment])
        db.session.flush()
        db.session.add_all(
            [
                Submission(
                    student_id=student.student_id,
                    assignment_id=assignment.id,
                    code="int main() { return 0; }",
                    score=5,
                    status="evaluated",
                ),
                Submission(
                    student_id=student.student_id,
                    assignment_id=assignment.id,
                    code="int main() { return 1; }",
                    score=80,
                    status="evaluated",
                ),
            ]
        )
        db.session.flush()
        for _ in range(2):
            _refresh_assignment_stats(assignment)
            _refresh_user_stats(student.student_id)
        assert (assignment.count, assignment.total_score, assignment.average_score) == (2, 85, 42.5)
        assert (student.submit_count, student.user_tscore, student.user_ascore) == (2, 85, 42.5)
        db.session.remove()
        db.drop_all()


def test_class_comparison_reads_historical_and_current_scale_per_submission(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'class-scores.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        student = User(
            student_id="scale-student",
            username="scale-student",
            usertype="学生",
            class_name="示例班级",
            submit_count=2,
        )
        student.password = "score-password"
        assignment = Assignment(
            title="分值来源练习",
            description="核查班级平均分",
            creator_id=student.student_id,
        )
        db.session.add_all([student, assignment])
        db.session.flush()
        db.session.add_all([
            Submission(
                student_id=student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 0; }",
                score=5,
                status="evaluated",
                submitted_at=datetime(2026, 9, 17, 12, 0),
            ),
            Submission(
                student_id=student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 1; }",
                score=5,
                status="evaluated",
                submitted_at=datetime(2026, 9, 27, 12, 0),
            ),
        ])
        db.session.flush()
        comparison = AbilityScorer()._get_class_comparison_data("示例班级")
        assert comparison["avg_score"] == pytest.approx(2.625)
        db.session.remove()
        db.drop_all()


def test_ability_profiles_use_only_dimension_scores_with_model_reasons(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'dimension-sources.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        student = User(
            student_id="dimension-student",
            username="dimension-student",
            usertype="学生",
            class_name="分项来源班级",
        )
        student.password = "score-password"
        legacy_student = User(
            student_id="legacy-dimension-student",
            username="legacy-dimension-student",
            usertype="学生",
            class_name="旧记录班级",
        )
        legacy_student.password = "score-password"
        zero_student = User(
            student_id="zero-dimension-student",
            username="zero-dimension-student",
            usertype="学生",
            class_name="零分记录班级",
        )
        zero_student.password = "score-password"
        assignment = Assignment(
            title="分项来源练习",
            description="检查能力评分来源",
            creator_id=student.student_id,
        )
        db.session.add_all([student, legacy_student, zero_student, assignment])
        db.session.flush()
        db.session.add_all([
            Submission(
                student_id=student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 0; }",
                score=20,
                status="evaluated",
                submitted_at=datetime(2026, 9, 27, 10, 0),
                ai_feedback=json.dumps({"algorithm_score": 90}),
            ),
            Submission(
                student_id=student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 1; }",
                score=80,
                status="evaluated",
                submitted_at=datetime(2026, 9, 27, 11, 0),
                ai_feedback=json.dumps({
                    "algorithm_score": 40,
                    "dimension_feedback": "循环边界需要检查。",
                }),
            ),
            Submission(
                student_id=legacy_student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 2; }",
                score=20,
                status="evaluated",
                submitted_at=datetime(2026, 9, 27, 12, 0),
                ai_feedback=json.dumps({"algorithm_score": 90}),
            ),
            Submission(
                student_id=zero_student.student_id,
                assignment_id=assignment.id,
                code="int main() { return 3; }",
                score=0,
                status="evaluated",
                submitted_at=datetime(2026, 9, 27, 13, 0),
                ai_feedback=json.dumps({
                    "algorithm_score": 0,
                    "dimension_feedback": "算法要求尚未完成。",
                }),
            ),
        ])
        db.session.flush()
        assert AbilityScorer().calculate_detailed_ability_scores(student.student_id)["algorithm"] == 40
        assert AbilityScorer().calculate_detailed_ability_scores(legacy_student.student_id)["algorithm"] == 0
        assert User.get_class_average_scores()["分项来源班级"]["algorithm"] == 40
        assert User.get_class_average_scores()["零分记录班级"]["algorithm"] == 0
        assert "旧记录班级" not in User.get_class_average_scores()
        db.session.remove()
        db.drop_all()
