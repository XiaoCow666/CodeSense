from models import (
    Assignment,
    AssignmentKnowledgePoint,
    AssignmentLearningResource,
    AssignmentLearningResourceRevision,
    User,
    db,
)
from services.knowledge_rag import retrieve_assignment_knowledge
from services.learning_graph import (
    build_student_learning_graph,
    build_teacher_knowledge_coverage,
)
from services.learning_graph_eval import evaluate_student_learning_graph
from tests.test_learning_graph import learning_graph_context


def _login(client, username):
    response = client.post(
        "/login", data={"username": username, "password": "password"},
    )
    assert response.status_code in {302, 303}


def _create_resource(app, ids, *, title="数组边界提示", content="先检查空数组，再核对数组下标范围。"):
    with app.app_context():
        assignment = db.session.get(Assignment, ids["assignment_one"])
        teacher = db.session.get(User, ids["teacher"])
        from services.assignment_learning_resources import save_assignment_learning_resource

        resource = save_assignment_learning_resource(
            assignment, teacher, title=title, content=content,
            knowledge_point="array",
        )
        return resource.id


def test_teacher_resource_reaches_student_graph_page_and_ai_evidence(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    edit_page = teacher_client.get(f"/teacher/edit/{assignment_id}")
    assert edit_page.status_code == 200
    assert "添加学习资料" in edit_page.get_data(as_text=True)

    response = teacher_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "create",
            "title": "数组边界提示",
            "content": "先检查空数组，再核对数组下标范围。",
            "knowledge_point": "array",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        resource = AssignmentLearningResource.query.one()
        resource_id = resource.id
        assert len(resource.source_version) == 64
        assert AssignmentLearningResourceRevision.query.count() == 1
        student_graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
        teacher_graph = build_teacher_knowledge_coverage(viewer_id=ids["teacher"])
        retrieval = retrieve_assignment_knowledge(
            assignment_id, query="空数组下标范围",
        )
    resource_edges = [
        edge for edge in student_graph["edges"]
        if f"assignment-resource:{resource_id}" in edge["source_refs"]
    ]
    assert {edge["relation_type"] for edge in resource_edges} == {
        "provides", "explains",
    }
    assert all(edge["source_version"] == resource.source_version for edge in resource_edges)
    assert student_graph["meta"]["resource_count"] == 1
    assert teacher_graph["meta"]["resource_count"] == 1
    assert student_graph["recommendations"][0]["resource_id"] == resource_id
    assert any(
        item["source_type"] == "assignment_learning_resource"
        and item["source_version"] == resource.source_version
        for item in retrieval["evidence"]
    )

    student_client = app.test_client()
    _login(student_client, ids["student_one"])
    assignment_page = student_client.get(f"/view_assignment/{assignment_id}")
    student_home = student_client.get("/home")
    assert assignment_page.status_code == 200
    assert "先检查空数组" in assignment_page.get_data(as_text=True)
    assert f"#learning-resource-{resource_id}" in student_home.get_data(as_text=True)


def test_edit_then_withdraw_removes_old_content_from_every_reader(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    updated = teacher_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "update", "resource_id": resource_id, "expected_revision": 1,
            "title": "数组边界新版", "content": "用一个空数组验证终止条件。",
            "knowledge_point": "array",
        },
    )
    assert updated.status_code == 302
    with app.app_context():
        resource = db.session.get(AssignmentLearningResource, resource_id)
        assert resource.revision == 2
        versions = AssignmentLearningResourceRevision.query.filter_by(
            resource_id=resource_id,
        ).order_by(AssignmentLearningResourceRevision.revision).all()
        assert [row.action for row in versions] == ["created", "updated"]
        assert versions[0].source_version != versions[1].source_version
        evidence = retrieve_assignment_knowledge(
            assignment_id, query="空数组终止条件",
        )["evidence"]
        assert any("用一个空数组" in item["content"] for item in evidence)
        assert all("再核对数组下标范围" not in item["content"] for item in evidence)

    withdrawn = teacher_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={"action": "withdraw", "resource_id": resource_id, "expected_revision": 2},
    )
    assert withdrawn.status_code == 302
    with app.app_context():
        resource = db.session.get(AssignmentLearningResource, resource_id)
        assert resource.status == "withdrawn"
        assert resource.revision == 3
        assert AssignmentLearningResourceRevision.query.filter_by(
            resource_id=resource_id,
        ).count() == 3
        graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
        evidence = retrieve_assignment_knowledge(
            assignment_id, query="空数组终止条件",
        )["evidence"]
    assert all(node.get("resource_id") != resource_id for node in graph["nodes"])
    assert all(item["source_type"] != "assignment_learning_resource" for item in evidence)
    student_client = app.test_client()
    _login(student_client, ids["student_one"])
    html = student_client.get(f"/view_assignment/{assignment_id}").get_data(as_text=True)
    assert "用一个空数组验证终止条件" not in html


def test_resources_follow_assignment_permissions_and_reject_sensitive_text(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    outsider_client = app.test_client()
    _login(outsider_client, ids["outside_student"])
    outside_page = outsider_client.get(f"/view_assignment/{assignment_id}")
    assert outside_page.status_code == 302
    assert "数组边界提示" not in outside_page.get_data(as_text=True)

    other_teacher = app.test_client()
    _login(other_teacher, ids["other_teacher"])
    denied = other_teacher.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={"action": "withdraw", "resource_id": resource_id},
    )
    assert denied.status_code == 403
    with app.app_context():
        assert db.session.get(AssignmentLearningResource, resource_id).status == "active"

    owner = app.test_client()
    _login(owner, ids["teacher"])
    rejected = owner.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "create", "title": "私密资料",
            "content": "联系 13800138000 获取答案", "knowledge_point": "array",
        },
        follow_redirects=True,
    )
    assert rejected.status_code == 200
    assert "请移除后保存" in rejected.get_data(as_text=True)
    with app.app_context():
        assert AssignmentLearningResource.query.count() == 1


def test_removing_knowledge_point_withdraws_linked_resources(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    with app.app_context():
        source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id, knowledge_point="array",
        ).one()
        source_id = source.id
    client = app.test_client()
    _login(client, ids["teacher"])
    response = client.post(
        f"/teacher/edit/{assignment_id}/knowledge-points",
        data={"remove_knowledge_point_ids": str(source_id)},
    )
    assert response.status_code == 302
    with app.app_context():
        resource = db.session.get(AssignmentLearningResource, resource_id)
        assert resource.status == "withdrawn"
        assert AssignmentLearningResourceRevision.query.filter_by(
            resource_id=resource_id, action="withdrawn",
        ).count() == 1
        graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
    assert graph["meta"]["resource_count"] == 0


def test_offline_graph_evaluation_tracks_resource_and_withdrawal(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    expected = {
        "knowledge_points": ["array", "recursion"],
        "mastery_points": ["array", "recursion"],
        "co_occurrence_pairs": [["array", "recursion"]],
        "allowed_edge_scopes": ["student_assignments", "student_private"],
        "learning_resources": [
            {"resource_id": resource_id, "knowledge_point": "array"},
        ],
    }
    with app.app_context():
        graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
        metrics = evaluate_student_learning_graph(
            graph, assignment_id=assignment_id, expected=expected,
        )
        assert metrics["node_recall"] == 1.0
        assert metrics["edge_recall"] == 1.0
        assert metrics["source_completeness"] == 1.0
        assert metrics["scope_leak_count"] == 0

        assignment = db.session.get(Assignment, assignment_id)
        teacher = db.session.get(User, ids["teacher"])
        from services.assignment_learning_resources import withdraw_assignment_learning_resource

        withdraw_assignment_learning_resource(assignment, teacher, resource_id)
        withdrawn_graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
        withdrawn_metrics = evaluate_student_learning_graph(
            withdrawn_graph, assignment_id=assignment_id, expected=expected,
        )
        assert withdrawn_metrics["failure_samples"]["missing_node_ids"] == [
            f"resource:{resource_id}",
        ]
        expected["learning_resources"] = []
        current_metrics = evaluate_student_learning_graph(
            withdrawn_graph, assignment_id=assignment_id, expected=expected,
        )
        assert current_metrics["node_precision"] == 1.0
        assert current_metrics["edge_precision"] == 1.0


def test_teacher_history_and_admin_access_follow_existing_assignment_scope(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    admin_client = app.test_client()
    _login(admin_client, ids["admin"])
    updated = admin_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "update", "resource_id": resource_id, "expected_revision": 1,
            "title": "数组边界复习", "content": "检查空数组长度和边界。",
            "knowledge_point": "array",
        },
    )
    assert updated.status_code == 302
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    html = teacher_client.get(f"/teacher/edit/{assignment_id}").get_data(as_text=True)
    assert "查看修改记录" in html
    assert "版本 2" in html
    assert "版本 1" in html
    assert "检查空数组长度和边界" in html


def test_stale_teacher_form_cannot_overwrite_newer_resource_revision(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    resource_url = f"/teacher/edit/{assignment_id}/learning-resources"
    first = teacher_client.post(resource_url, data={
        "action": "update", "resource_id": resource_id,
        "expected_revision": 1, "title": "更新后的提示",
        "content": "先核对空数组。", "knowledge_point": "array",
    })
    assert first.status_code == 302
    stale = teacher_client.post(resource_url, data={
        "action": "withdraw", "resource_id": resource_id,
        "expected_revision": 1,
    }, follow_redirects=True)
    assert stale.status_code == 200
    assert "学习资料已经更新，请刷新页面后重新撤回" in stale.get_data(as_text=True)
    with app.app_context():
        resource = db.session.get(AssignmentLearningResource, resource_id)
        assert resource.revision == 2
        assert resource.status == "active"
        assert resource.title == "更新后的提示"


def test_resource_request_enforces_csrf_and_current_knowledge_link(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    app.config["WTF_CSRF_ENABLED"] = True
    missing_token = teacher_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "create", "title": "数组资料",
            "content": "核对数组边界。", "knowledge_point": "array",
        },
    )
    app.config["WTF_CSRF_ENABLED"] = False
    assert missing_token.status_code == 400

    unknown_code = teacher_client.post(
        f"/teacher/edit/{assignment_id}/learning-resources",
        data={
            "action": "create", "title": "范围外资料",
            "content": "核对范围外概念。", "knowledge_point": "tree",
        },
        follow_redirects=True,
    )
    assert unknown_code.status_code == 200
    assert "请先给作业关联这个知识点" in unknown_code.get_data(as_text=True)
    with app.app_context():
        assert AssignmentLearningResource.query.count() == 0


def test_orphaned_resource_is_hidden_before_graph_and_retrieval(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    with app.app_context():
        source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=assignment_id, knowledge_point="array",
        ).one()
        db.session.delete(source)
        db.session.commit()
        graph = build_student_learning_graph(
            student_id=ids["student_one"], assignment_id=assignment_id,
        )
        retrieval = retrieve_assignment_knowledge(
            assignment_id, query="空数组下标范围",
        )
    assert all(node.get("resource_id") != resource_id for node in graph["nodes"])
    assert all(
        item["source_type"] != "assignment_learning_resource"
        for item in retrieval["evidence"]
    )
    client = app.test_client()
    _login(client, ids["student_one"])
    html = client.get(f"/view_assignment/{assignment_id}").get_data(as_text=True)
    assert "先检查空数组，再核对数组下标范围" not in html


def test_teacher_knowledge_focus_links_current_resource(
    learning_graph_context,
):
    app, ids = learning_graph_context
    resource_id = _create_resource(app, ids)
    client = app.test_client()
    _login(client, ids["teacher"])
    response = client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['class_a']}",
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "可用学习资料" in html
    assert f"#learning-resource-{resource_id}" in html
    assert "数组边界提示" in html


def test_student_evidence_api_exposes_current_resource_version_only(
    learning_graph_context,
):
    app, ids = learning_graph_context
    assignment_id = ids["assignment_one"]
    resource_id = _create_resource(app, ids)
    with app.app_context():
        version = db.session.get(AssignmentLearningResource, resource_id).source_version

    student_client = app.test_client()
    _login(student_client, ids["student_one"])
    endpoint = f"/api/assignments/{assignment_id}/knowledge-evidence?q=空数组下标范围"
    response = student_client.get(endpoint)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    evidence = response.json["data"]["knowledge_evidence"]["evidence"]
    assert any(
        item["source_label"] == "教师学习资料"
        and item["source_version"] == version
        for item in evidence
    )
    assert "diagnostics" not in response.json["data"]["knowledge_evidence"]

    outsider_client = app.test_client()
    _login(outsider_client, ids["outside_student"])
    denied = outsider_client.get(endpoint)
    assert denied.status_code == 403
    assert "数组边界提示" not in denied.get_data(as_text=True)
