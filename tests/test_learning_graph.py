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
    build_student_learning_graph_context,
    build_teacher_knowledge_coverage,
    build_teacher_knowledge_focus,
)
from services import learning_graph


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
        admin = User(
            student_id="graph-admin",
            username="graph-admin",
            usertype="管理员",
            full_name="图谱管理员",
        )
        admin.password = "password"
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
        db.session.add_all([teacher, other_teacher, admin, class_a, class_b])
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
            "admin": admin.student_id,
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


def test_graph_edges_expose_source_references_and_versions(learning_graph_context):
    app, ids = learning_graph_context
    with app.app_context():
        student_graph = build_student_learning_graph(
            student_id=ids["student_one"],
            limit=8,
        )
        teacher_graph = build_teacher_knowledge_coverage(
            viewer_id=ids["teacher"],
            class_id=ids["class_a"],
            limit=8,
        )

    assert all(edge["source_refs"] and edge["source_version"] for edge in student_graph["edges"])
    assert all(edge["source_refs"] and edge["source_version"] for edge in teacher_graph["edges"])
    assert any(edge["scope"] == "student_private" for edge in student_graph["edges"])
    assert all("graph-student" not in repr(edge) for edge in teacher_graph["edges"])


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


def test_teacher_knowledge_focus_returns_only_managed_assignments(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        focus = build_teacher_knowledge_focus(
            viewer_id=ids["teacher"],
            knowledge_point="array",
            class_id=ids["class_a"],
        )

    assert focus["meta"]["class_id"] == ids["class_a"]
    assert [item["assignment_id"] for item in focus["assignments"]] == [
        ids["assignment_one"]
    ]
    assert focus["assignments"][0]["knowledge_point"] == "array"
    assert "graph-student" not in repr(focus)


def test_teacher_knowledge_focus_exposes_aggregate_action_signal(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        focus = build_teacher_knowledge_focus(
            viewer_id=ids["teacher"],
            knowledge_point="array",
            class_id=ids["class_a"],
        )

    signal = focus["meta"]["focus_signal"]
    assert signal["status"] == "needs_attention"
    assert signal["student_sample_size"] == 2
    assert signal["average_mastery"] == 62.5
    assert signal["low_mastery_count"] == 1
    assert "graph-student" not in repr(signal)


def test_student_graph_projection_keeps_scope_state_and_source_versions(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            assignment_id=ids["assignment_one"],
        )
        projection_builder = getattr(
            learning_graph,
            "project_student_learning_graph",
            None,
        )
        assert projection_builder is not None
        projection = projection_builder(graph)

    assert projection["status"] == "grounded"
    assert projection["scope"] == "student_private"
    assert projection["nodes"]
    assert all(node["source_versions"] for node in projection["nodes"])
    assert all(node["scope"] == "student_private" for node in projection["nodes"])
    assert ids["student_one"] not in repr(projection)


def test_teacher_can_create_tagged_focus_assignment_and_open_class_flow(
    learning_graph_context,
):
    app, ids = learning_graph_context
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["teacher"], "password": "password"},
    )
    assert login.status_code in {302, 303}

    focus = client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['class_a']}"
    )
    assert focus.status_code == 200
    assert "knowledge_point=array" in focus.get_data(as_text=True)

    response = client.post(
        f"/teacher/add?knowledge_point=array&class_id={ids['class_a']}",
        data={
            "assignment_id": "9001",
            "title": "数组巩固练习",
            "description": "围绕数组边界安排一次巩固练习。",
            "due_date": "",
        },
    )
    assert response.status_code in {302, 303}

    with app.app_context():
        assignment = db.session.get(Assignment, 9001)
        assert assignment is not None
        assert assignment.creator_id == ids["teacher"]
        assert assignment.get_target_class_list() == ["图谱班级A"]
        relation = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment.id,
            knowledge_point="array",
        ).one()
        assert relation.auto_detected is False
        assert response.headers["Location"].endswith(f"/assign/{assignment.id}")

    with app.app_context():
        with pytest.raises(LearningGraphAccessError):
            build_teacher_knowledge_focus(
                viewer_id=ids["teacher"],
                knowledge_point="tree",
                class_id=ids["class_b"],
            )


def test_student_graph_context_explains_current_knowledge_state(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            assignment_id=ids["assignment_one"],
        )
        context = build_student_learning_graph_context(graph)

    assert "当前作业知识点" in context
    assert "数组" in context
    assert "掌握度" in context
    assert "student_private" in context
    assert ids["student_one"] not in context


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
    assert "查看针对性练习" in html


def test_teacher_can_open_knowledge_focus_and_other_teacher_cannot(
    learning_graph_context,
):
    app, ids = learning_graph_context
    with app.app_context():
        classroom = db.session.get(Class, ids["class_a"])
        shared_assignment = Assignment(
            title="其他教师创建的数组练习",
            description="用于验证布置权限显示。",
            target_classes=classroom.name,
            creator_id=ids["other_teacher"],
            created_time=dt.utcnow(),
        )
        db.session.add(shared_assignment)
        db.session.flush()
        db.session.add(
            AssignmentKnowledgePoint(
                assignment_id=shared_assignment.id,
                knowledge_point="array",
            )
        )
        db.session.commit()

    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["teacher"], "password": "password"},
        follow_redirects=True,
    )
    assert login.status_code == 200

    focus = client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['class_a']}"
    )
    assert focus.status_code == 200
    body = focus.get_data(as_text=True)
    assert "数组与递归" in body
    assert "布置到班级" in body
    assert f"/assign/{ids['assignment_one']}" in body
    shared_start = body.index("其他教师创建的数组练习")
    shared_card = body[shared_start:body.index("</article>", shared_start)]
    assert "布置到班级" not in shared_card
    assert "当前账号无法布置此作业" in shared_card

    other_client = app.test_client()
    other_login = other_client.post(
        "/login",
        data={"username": ids["other_teacher"], "password": "password"},
    )
    assert other_login.status_code in {302, 303}
    forbidden = other_client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['class_a']}"
    )
    assert forbidden.status_code == 403


def test_admin_cannot_use_student_or_teacher_learning_actions(learning_graph_context):
    app, ids = learning_graph_context
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": ids["admin"], "password": "password"},
    )
    assert login.status_code in {302, 303}

    focus = client.get("/teacher/knowledge-focus/array")
    assert focus.status_code in {302, 303}
    revoke = client.post(
        "/student/learning-memory/revoke",
        data={"source_type": "submission_feedback", "source_id": "submission:1"},
    )
    assert revoke.status_code in {302, 303}
