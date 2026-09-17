from datetime import datetime as dt

import pytest
from flask import template_rendered

from app import create_app
from config import TestingConfig as _TestingConfig
from models import (
    Assignment,
    AssignmentKnowledgePoint,
    Class,
    KnowledgePointScore,
    User,
    db,
)
from services.learning_graph import (
    LearningGraphAccessError,
    build_student_learning_graph,
    build_teacher_knowledge_coverage,
)


@pytest.fixture
def learning_graph_context(tmp_path, monkeypatch):
    database_path = tmp_path / "learning_graph.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        teacher = User(
            student_id="graph-teacher",
            username="graph-teacher",
            usertype="教师",
            full_name="图谱教师",
        )
        teacher.password = "password"
        other_teacher = User(
            student_id="other-teacher",
            username="other-teacher",
            usertype="教师",
            full_name="其他教师",
        )
        other_teacher.password = "password"
        class_a = Class(
            name="图谱班级A",
            grade="2024",
            major="软件工程",
            teacher_id=teacher.student_id,
        )
        class_b = Class(
            name="图谱班级B",
            grade="2024",
            major="软件工程",
            teacher_id=other_teacher.student_id,
        )
        db.session.add_all([teacher, other_teacher, class_a, class_b])
        db.session.flush()

        student_one = User(
            student_id="graph-student-1",
            username="graph-student-1",
            usertype="学生",
            class_id=class_a.id,
            class_name=class_a.name,
            full_name="学生一",
        )
        student_one.password = "password"
        student_two = User(
            student_id="graph-student-2",
            username="graph-student-2",
            usertype="学生",
            class_id=class_a.id,
            class_name=class_a.name,
            full_name="学生二",
        )
        student_two.password = "password"
        outside_student = User(
            student_id="graph-student-outside",
            username="graph-student-outside",
            usertype="学生",
            class_id=class_b.id,
            class_name=class_b.name,
            full_name="外班学生",
        )
        outside_student.password = "password"
        empty_student = User(
            student_id="graph-student-empty",
            username="graph-student-empty",
            usertype="学生",
            full_name="空状态学生",
        )
        empty_student.password = "password"
        assignment_one = Assignment(
            title="数组与递归",
            description="数组边界和递归练习",
            target_classes=class_a.name,
            creator_id=teacher.student_id,
            created_time=dt.utcnow(),
        )
        assignment_two = Assignment(
            title="递归与指针",
            description="递归和指针练习",
            target_classes=class_a.name,
            creator_id=teacher.student_id,
            created_time=dt.utcnow(),
        )
        outside_assignment = Assignment(
            title="树结构",
            description="外班作业",
            target_classes=class_b.name,
            creator_id=other_teacher.student_id,
            created_time=dt.utcnow(),
        )
        db.session.add_all([
            student_one,
            student_two,
            outside_student,
            empty_student,
            assignment_one,
            assignment_two,
            outside_assignment,
        ])
        db.session.flush()
        db.session.add_all([
            AssignmentKnowledgePoint(
                assignment_id=assignment_one.id,
                knowledge_point="array",
                weight=1.5,
            ),
            AssignmentKnowledgePoint(
                assignment_id=assignment_one.id,
                knowledge_point="recursion",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=assignment_two.id,
                knowledge_point="recursion",
                weight=1.5,
            ),
            AssignmentKnowledgePoint(
                assignment_id=assignment_two.id,
                knowledge_point="pointer",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=outside_assignment.id,
                knowledge_point="tree",
                weight=1.0,
            ),
            KnowledgePointScore(
                student_id=student_one.student_id,
                knowledge_point="array",
                score=45,
                total_attempts=2,
                correct_attempts=1,
            ),
            KnowledgePointScore(
                student_id=student_one.student_id,
                knowledge_point="recursion",
                score=70,
                total_attempts=2,
                correct_attempts=2,
            ),
            KnowledgePointScore(
                student_id=student_two.student_id,
                knowledge_point="array",
                score=80,
                total_attempts=2,
                correct_attempts=2,
            ),
            KnowledgePointScore(
                student_id=student_two.student_id,
                knowledge_point="recursion",
                score=50,
                total_attempts=2,
                correct_attempts=1,
            ),
            KnowledgePointScore(
                student_id=outside_student.student_id,
                knowledge_point="tree",
                score=10,
                total_attempts=2,
                correct_attempts=0,
            ),
        ])
        db.session.commit()
        ids = {
            "teacher": teacher.student_id,
            "other_teacher": other_teacher.student_id,
            "student_one": student_one.student_id,
            "student_two": student_two.student_id,
            "outside_student": outside_student.student_id,
            "empty_student": empty_student.student_id,
            "class_a": class_a.id,
            "class_b": class_b.id,
            "assignment_one": assignment_one.id,
            "outside_assignment": outside_assignment.id,
        }

    yield app, ids

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_student_graph_returns_scoped_edges_and_next_actions(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            limit=8,
        )

    assert graph["meta"]["scope"] == "student"
    assert graph["meta"]["sample_size"] == 2
    assert {edge["relation_type"] for edge in graph["edges"]} >= {
        "covers",
        "mastery",
        "co_occurs",
    }
    assert {edge["scope"] for edge in graph["edges"]} >= {
        "student_assignments",
        "student_private",
    }
    assert all(edge["source"] != ids["outside_student"] for edge in graph["edges"])
    assert "graph-student-outside" not in repr(graph)
    assert all(
        node["id"].startswith(("assignment:", "knowledge:"))
        for node in graph["nodes"]
    )
    assert any(item["assignment_id"] == ids["assignment_one"] for item in graph["recommendations"])


def test_student_graph_rejects_assignment_outside_student_scope(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        with pytest.raises(LearningGraphAccessError):
            build_student_learning_graph(
                student_id=ids["student_one"],
                assignment_id=ids["outside_assignment"],
            )


def test_student_graph_has_stable_empty_state(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        graph = build_student_learning_graph(student_id=ids["empty_student"])

    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["recommendations"] == []
    assert graph["meta"]["scope"] == "student"
    assert graph["meta"]["sample_size"] == 0


def test_teacher_coverage_is_aggregate_and_class_scoped(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        coverage = build_teacher_knowledge_coverage(
            viewer_id=ids["teacher"],
            class_id=ids["class_a"],
            limit=8,
        )

    assert coverage["meta"]["scope"] == "teacher_class"
    assert coverage["meta"]["class_id"] == ids["class_a"]
    assert coverage["meta"]["sample_size"] == 2
    assert "graph-student-1" not in repr(coverage)
    assert "graph-student-outside" not in repr(coverage)
    array = next(item for item in coverage["nodes"] if item["code"] == "array")
    assert array["student_sample_size"] == 2
    assert array["average_mastery"] == 62.5
    assert array["low_mastery_count"] == 1
    assert any(item["code"] == "array" for item in coverage["recommendations"])


def test_teacher_cannot_read_unmanaged_class(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        with pytest.raises(LearningGraphAccessError):
            build_teacher_knowledge_coverage(
                viewer_id=ids["teacher"],
                class_id=ids["class_b"],
            )


def test_student_dashboard_renders_next_action_from_graph(learning_graph_context):
    app, ids = learning_graph_context
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["student_one"], "password": "password"},
        follow_redirects=False,
    )

    assert login.status_code in {302, 303}
    rendered = []

    def capture(sender, template, context, **kwargs):
        rendered.append((template.name, context))

    with template_rendered.connected_to(capture, app):
        response = client.get("/home")

    assert response.status_code == 200
    graph = rendered[-1][1]["learning_graph"]
    assert graph["meta"]["sample_size"] == 2
    html = response.get_data(as_text=True)
    assert "我的知识路径" in html
    assert "下一步先练什么" in html
    assert "仅本人数据" in html
    assert "数组" in html


def test_teacher_dashboard_renders_aggregate_graph(learning_graph_context):
    app, ids = learning_graph_context
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["teacher"], "password": "password"},
        follow_redirects=True,
    )

    assert login.status_code == 200
    html = login.get_data(as_text=True)
    assert "班级知识覆盖" in html
    assert "仅班级聚合" in html
    assert "数组" in html
