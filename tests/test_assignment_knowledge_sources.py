from flask import template_rendered

from models import AssignmentKnowledgePoint, KnowledgePointScore
from services.knowledge_rag import retrieve_assignment_knowledge
from services.learning_graph import build_student_learning_graph
from services.student_vector_store import (
    rebuild_student_vector_index,
    search_student_learning_vectors,
)
from tests.test_learning_graph import learning_graph_context


def _login(client, username):
    response = client.post(
        "/login",
        data={"username": username, "password": "password"},
    )
    assert response.status_code in {302, 303}


def test_teacher_can_update_assignment_knowledge_sources_and_all_readers_refresh(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]

    with app.app_context():
        removed_source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).one()
        removed_source_id = removed_source.id
        rebuild_student_vector_index(ids["student_one"])
        before_vector_search = search_student_learning_vectors(
            ids["student_one"],
            "数组",
            assignment_id=assignment_id,
        )

    assert before_vector_search["status"] == "grounded"
    assert before_vector_search["evidence"][0]["source_title"] == "数组"

    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    app.config["WTF_CSRF_ENABLED"] = True
    rendered_forms = []

    def capture_form(sender, template, context, **kwargs):
        if template.name == "edit_assignment.html":
            rendered_forms.append(context["form"])

    with template_rendered.connected_to(capture_form, app):
        edit_page = teacher_client.get(f"/teacher/edit/{assignment_id}")

    assert edit_page.status_code == 200
    assert "管理作业知识点" in edit_page.get_data(as_text=True)
    csrf_token = rendered_forms[-1].csrf_token.current_token

    missing_token = teacher_client.post(
        f"/teacher/edit/{assignment_id}/knowledge-points",
        data={
            "remove_knowledge_point_ids": str(removed_source_id),
            "add_knowledge_point": "linked_list",
        },
    )
    assert missing_token.status_code == 400

    saved = teacher_client.post(
        f"/teacher/edit/{assignment_id}/knowledge-points",
        data={
            "remove_knowledge_point_ids": str(removed_source_id),
            "add_knowledge_point": "linked_list",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    app.config["WTF_CSRF_ENABLED"] = False

    assert saved.status_code in {302, 303}
    assert saved.headers["Location"].endswith(f"/teacher/edit/{assignment_id}")

    with app.app_context():
        current_sources = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id
        ).order_by(AssignmentKnowledgePoint.id.asc()).all()
        current_codes = {source.knowledge_point for source in current_sources}
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            assignment_id=assignment_id,
        )
        knowledge_evidence = retrieve_assignment_knowledge(assignment_id)
        after_vector_search = search_student_learning_vectors(
            ids["student_one"],
            "数组",
            assignment_id=assignment_id,
        )

    assert current_codes == {
        "recursion",
        "linked_list",
    }
    assert {
        node.get("code")
        for node in graph["nodes"]
        if node["type"] == "knowledge_point"
    } == {"recursion", "linked_list"}
    assert all(
        f"assignment-knowledge:{removed_source_id}" not in edge["source_refs"]
        for edge in graph["edges"]
    )
    assert {item["title"] for item in knowledge_evidence["evidence"]} == {
        "递归",
        "链表",
    }
    assert after_vector_search["status"] == "no_result"

    teacher_dashboard = teacher_client.get("/teacher_dashboard")
    assert teacher_dashboard.status_code == 200
    teacher_html = teacher_dashboard.get_data(as_text=True)
    teacher_graph_panel = teacher_html.split(
        'class="learning-graph-panel"',
        1,
    )[1].split("</section>", 1)[0]
    assert "链表" in teacher_graph_panel
    assert "数组" not in teacher_graph_panel

    student_client = app.test_client()
    _login(student_client, ids["student_one"])
    student_home = student_client.get("/home")

    assert student_home.status_code == 200
    student_html = student_home.get_data(as_text=True)
    graph_panel = student_html.split('class="learning-graph-panel"', 1)[1].split(
        "</section>",
        1,
    )[0]
    assert "链表" in graph_panel
    assert "数组" not in graph_panel
    with app.app_context():
        assert KnowledgePointScore.query.filter_by(
            student_id=ids["student_one"],
            knowledge_point="array",
        ).count() == 1


def test_only_assignment_owner_can_change_knowledge_sources(learning_graph_context):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]

    with app.app_context():
        source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).one()
        source_id = source.id

    client = app.test_client()
    _login(client, ids["other_teacher"])
    response = client.post(
        f"/teacher/edit/{assignment_id}/knowledge-points",
        data={"remove_knowledge_point_ids": str(source_id)},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith("/teacher")

    with app.app_context():
        assert AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).count() == 1


def test_admin_can_change_assignment_knowledge_sources(learning_graph_context):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]

    with app.app_context():
        source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).one()
        source_id = source.id

    client = app.test_client()
    _login(client, ids["admin"])
    response = client.post(
        f"/teacher/edit/{assignment_id}/knowledge-points",
        data={"remove_knowledge_point_ids": str(source_id)},
        follow_redirects=False,
    )

    assert response.status_code in {302, 303}
    assert response.headers["Location"].endswith(
        f"/teacher/edit/{assignment_id}"
    )
    with app.app_context():
        assert AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).count() == 0


def test_knowledge_source_update_rejects_foreign_rows_and_unknown_codes(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]

    with app.app_context():
        foreign_source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=ids["outside_assignment"],
            knowledge_point="tree",
        ).one()
        foreign_source_id = foreign_source.id

    client = app.test_client()
    _login(client, ids["teacher"])
    path = f"/teacher/edit/{assignment_id}/knowledge-points"
    foreign_removal = client.post(
        path,
        data={"remove_knowledge_point_ids": str(foreign_source_id)},
    )
    unknown_addition = client.post(
        path,
        data={"add_knowledge_point": "unregistered_private_label"},
    )

    assert foreign_removal.status_code == 400
    assert unknown_addition.status_code == 400
    with app.app_context():
        assert AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id,
            knowledge_point="array",
        ).count() == 1
        assert AssignmentKnowledgePoint.query.filter_by(
            assignment_id=ids["outside_assignment"],
            knowledge_point="tree",
        ).count() == 1
