import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app import create_app
from config import TestingConfig as _TestingConfig
from models import (
    AbilityTrend,
    Assignment,
    AssignmentKnowledgePoint,
    Class,
    KnowledgePointScore,
    Submission,
    StudentVectorIndexState,
    TeacherAISuggestion,
    ThinkingSession,
    User,
    db,
)
from services.action_center import build_action_center, count_action_center_items
from services.feedback import create_feedback_record, save_feedback
from services.notifications import create_notification, list_notifications
from services.submission_reviews import create_review_request
from services.student_vector_store import (
    rebuild_student_vector_index,
    search_student_learning_vectors,
)
from services.teacher_learning_actions import send_learning_memory_refresh_reminders


@pytest.fixture
def action_center_context(tmp_path, monkeypatch):
    database_path = tmp_path / "action-center.db"
    monkeypatch.setattr(_TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path}")
    app = create_app("testing")
    now = datetime.utcnow()

    with app.app_context():
        db.create_all()
        student = User(
            student_id="action-student",
            username="action-student",
            usertype="学生",
            full_name="行动中心学生",
            email="student-private@example.test",
        )
        teacher = User(
            student_id="action-teacher",
            username="action-teacher",
            usertype="教师",
            full_name="行动中心教师",
        )
        outsider_teacher = User(
            student_id="other-teacher",
            username="other-teacher",
            usertype="教师",
            full_name="其他教师",
        )
        admin = User(
            student_id="action-admin",
            username="action-admin",
            usertype="管理员",
            full_name="行动中心管理员",
        )
        empty_student = User(
            student_id="action-empty-student",
            username="action-empty-student",
            usertype="学生",
            full_name="空行动学生",
        )
        for user in (student, teacher, outsider_teacher, admin, empty_student):
            user.password = "password"

        managed_class = Class(name="行动中心班", teacher_id=teacher.student_id)
        managed_class_two = Class(name="行动中心班二", teacher_id=teacher.student_id)
        outsider_class = Class(name="其他教师班", teacher_id=outsider_teacher.student_id)
        db.session.add_all([
            student,
            teacher,
            outsider_teacher,
            admin,
            empty_student,
            managed_class,
            managed_class_two,
            outsider_class,
            StudentVectorIndexState(
                student_id=empty_student.student_id,
                status="empty",
            ),
        ])
        db.session.flush()
        student.class_id = managed_class.id
        second_student = User(
            student_id="action-student-2",
            username="action-student-2",
            usertype="学生",
            full_name="行动中心学生二",
            class_id=managed_class.id,
        )
        third_student = User(
            student_id="action-student-3",
            username="action-student-3",
            usertype="学生",
            full_name="行动中心学生三",
            class_id=managed_class_two.id,
        )
        fourth_student = User(
            student_id="action-student-4",
            username="action-student-4",
            usertype="学生",
            full_name="行动中心学生四",
            class_id=managed_class_two.id,
        )
        fifth_student = User(
            student_id="action-student-5",
            username="action-student-5",
            usertype="学生",
            full_name="行动中心学生五",
            class_id=managed_class.id,
        )
        for additional_student in (
            second_student,
            third_student,
            fourth_student,
            fifth_student,
        ):
            additional_student.password = "password"
        db.session.add_all([
            second_student,
            third_student,
            fourth_student,
            fifth_student,
        ])

        assignment = Assignment(
            title="行动中心作业",
            description="只用于聚合测试",
            creator_id=teacher.student_id,
            target_classes=managed_class.name,
            created_time=now - timedelta(days=1),
        )
        latest_assignment = Assignment(
            title="最新数组练习",
            description="当前学生可继续完成的数组练习",
            creator_id=teacher.student_id,
            target_classes=managed_class.name,
            created_time=now,
        )
        second_class_assignment = Assignment(
            title="第二班数组练习",
            description="第二个管理班级的练习",
            creator_id=teacher.student_id,
            target_classes=managed_class_two.name,
            created_time=now,
        )
        outsider_assignment = Assignment(
            title="其他教师作业",
            description="不应进入当前教师队列",
            creator_id=outsider_teacher.student_id,
            target_classes=outsider_class.name,
        )
        db.session.add_all([assignment, latest_assignment, second_class_assignment, outsider_assignment])
        db.session.flush()
        db.session.add_all([
            AssignmentKnowledgePoint(
                assignment_id=assignment.id,
                knowledge_point="array",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=assignment.id,
                knowledge_point="recursion",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=latest_assignment.id,
                knowledge_point="array",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=second_class_assignment.id,
                knowledge_point="array",
                weight=1.0,
            ),
            AssignmentKnowledgePoint(
                assignment_id=outsider_assignment.id,
                knowledge_point="pointer",
                weight=1.0,
            ),
            KnowledgePointScore(
                student_id=student.student_id,
                knowledge_point="array",
                score=40,
                total_attempts=2,
                correct_attempts=1,
            ),
            KnowledgePointScore(
                student_id=second_student.student_id,
                knowledge_point="array",
                score=50,
                total_attempts=2,
                correct_attempts=1,
            ),
            KnowledgePointScore(
                student_id=third_student.student_id,
                knowledge_point="array",
                score=30,
                total_attempts=2,
                correct_attempts=0,
            ),
            KnowledgePointScore(
                student_id=fourth_student.student_id,
                knowledge_point="array",
                score=20,
                total_attempts=2,
                correct_attempts=0,
            ),
        ])

        pending_submission = Submission(
            student_id=student.student_id,
            assignment_id=assignment.id,
            code="SECRET_STUDENT_CODE",
            status="pending",
            submitted_at=now - timedelta(minutes=3),
        )
        review_submission = Submission(
            student_id=student.student_id,
            assignment_id=assignment.id,
            code="PRIVATE_REVIEW_CODE",
            status="evaluated",
            submitted_at=now - timedelta(minutes=8),
        )
        outsider_submission = Submission(
            student_id=student.student_id,
            assignment_id=outsider_assignment.id,
            code="OUTSIDER_CODE",
            status="pending",
            submitted_at=now - timedelta(minutes=1),
        )
        db.session.add_all([pending_submission, review_submission, outsider_submission])
        db.session.flush()
        session = ThinkingSession(
            student_id=student.student_id,
            assignment_id=assignment.id,
            current_stage=2,
            stage1_description="private learning content",
            started_at=now - timedelta(minutes=2),
            status="in_progress",
        )
        db.session.add(session)
        db.session.add_all([
            TeacherAISuggestion(
                teacher_id=teacher.student_id,
                class_id=managed_class.id,
                status="failed",
                suggestion_markdown="PRIVATE_TEACHER_AI_OUTPUT",
            ),
            TeacherAISuggestion(
                teacher_id=outsider_teacher.student_id,
                class_id=outsider_class.id,
                status="failed",
                suggestion_markdown="OUTSIDER_TEACHER_AI_OUTPUT",
            ),
            AbilityTrend(student_id=student.student_id, status="failed"),
        ])
        db.session.commit()

        create_review_request(
            review_submission,
            student.student_id,
            "PRIVATE_REVIEW_BODY",
        )
        create_notification(
            student.student_id,
            kind="submission",
            title="提交状态已更新",
            message="你的提交需要查看。",
            url="/submissions",
            idempotency_key="action-center-student-notification",
        )
        feedback = create_feedback_record(
            {
                "category": "bug",
                "subject": "后台反馈主题",
                "message": "后台反馈的私密正文不应出现在行动中心。",
                "reproduction_steps": "只用于测试",
                "page_context": "/feedback",
                "contact_email": "feedback-private@example.test",
            },
            request_context={"request_id": "action-center-test", "endpoint": "/feedback", "method": "POST"},
        )
        save_feedback(feedback, user_id=student.student_id)

        yield app, {
            "student": student.student_id,
            "teacher": teacher.student_id,
            "admin": admin.student_id,
            "empty_student": empty_student.student_id,
            "outsider_teacher": outsider_teacher.student_id,
            "managed_class": managed_class.id,
            "managed_class_two": managed_class_two.id,
            "outsider_class": outsider_class.id,
            "assignment": assignment.id,
            "latest_assignment": latest_assignment.id,
            "second_class_assignment": second_class_assignment.id,
        }

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _login(client, username):
    response = client.post("/login", data={"username": username, "password": "password"})
    assert response.status_code in {302, 303}


def test_student_contract_is_bounded_owned_and_content_free(action_center_context):
    app, ids = action_center_context
    with app.app_context():
        payload = build_action_center(db.session.get(User, ids["student"]), limit=200)

    kinds = {item["kind"] for item in payload["items"]}
    assert payload["schema_version"] == 1
    assert payload["role"] == "student"
    assert payload["data_scope"] == "actor-owned"
    assert {"submission", "review", "session", "notification"}.issubset(kinds)
    assert len(payload["items"]) <= 50
    assert payload["counts"]["total"] >= len(payload["items"])
    assert all(item["href"].startswith("/") for item in payload["items"])
    assert all(not item["id"].rsplit(":", 1)[-1].isdigit() for item in payload["items"])
    serialized = json.dumps(payload, ensure_ascii=False)
    for private_value in (
        "SECRET_STUDENT_CODE",
        "PRIVATE_REVIEW_CODE",
        "PRIVATE_REVIEW_BODY",
        "student-private@example.test",
        "feedback-private@example.test",
    ):
        assert private_value not in serialized


def test_student_learning_graph_recommendation_is_one_scoped_practice_action(
    action_center_context,
):
    app, ids = action_center_context
    with app.app_context():
        payload = build_action_center(db.session.get(User, ids["student"]), emit_log=False)

    graph_items = [item for item in payload["items"] if item["kind"] == "learning_graph"]
    assert len(graph_items) == 2
    array_action = next(item for item in graph_items if item["title"] == "继续练习：数组")
    recursion_action = next(item for item in graph_items if item["title"] == "继续练习：递归")
    assert array_action["source"] == "learning_graph"
    assert array_action["source_label"] == "知识图谱"
    assert array_action["href"] == f"/submit/{ids['latest_assignment']}"
    assert recursion_action["href"] == f"/submit/{ids['assignment']}"
    serialized = json.dumps(graph_items, ensure_ascii=False)
    assert "最新数组练习" in serialized
    assert "第二班数组练习" not in serialized
    assert "行动中心学生二" not in serialized
    assert "其他教师作业" not in serialized


def test_student_graph_actions_load_recommended_assignments_in_one_query(
    action_center_context,
):
    app, ids = action_center_context
    statements = []

    def capture_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement.lower(), parameters))

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", capture_statement)
        try:
            payload = build_action_center(
                db.session.get(User, ids["student"]),
                emit_log=False,
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", capture_statement)

    graph_items = [item for item in payload["items"] if item["kind"] == "learning_graph"]
    assignment_queries = [
        parameters
        for statement, parameters in statements
        if "from assignments" in " ".join(statement.split())
        and "assignments.id in" in " ".join(statement.split())
    ]

    assert len(graph_items) == 2
    assert len(assignment_queries) == 1
    assert str(ids["assignment"]) in repr(assignment_queries[0])
    assert str(ids["latest_assignment"]) in repr(assignment_queries[0])


def test_navigation_count_does_not_build_learning_graph(action_center_context):
    app, ids = action_center_context
    statements = []

    def capture_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", capture_statement)
        try:
            count_action_center_items(db.session.get(User, ids["student"]))
        finally:
            event.remove(db.engine, "before_cursor_execute", capture_statement)

    graph_tables = ("assignment_knowledge_points", "knowledge_point_scores")
    assert not any(table in statement for statement in statements for table in graph_tables)


def test_teacher_graph_action_uses_one_aggregate_query_and_private_scope(
    action_center_context,
):
    app, ids = action_center_context
    statements = []

    def capture_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", capture_statement)
        try:
            payload = build_action_center(
                db.session.get(User, ids["teacher"]),
                emit_log=False,
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", capture_statement)

    graph_items = [item for item in payload["items"] if item["kind"] == "learning_graph"]
    assert len(graph_items) == 1
    assert graph_items[0]["href"] == "/teacher/knowledge-focus/array"
    assert "已有掌握记录的 4 名学生" in graph_items[0]["summary"]
    assert "5 名学生" not in graph_items[0]["summary"]
    assert "根据你管理的 2 个班级汇总" in graph_items[0]["summary"]
    serialized = json.dumps(payload, ensure_ascii=False)
    for private_value in (
        "行动中心学生",
        "action-student-2",
        "第二班数组练习",
        "其他教师作业",
    ):
        assert private_value not in serialized

    assignment_queries = [
        statement
        for statement in statements
        if "from assignment_knowledge_points" in " ".join(statement.split())
    ]
    score_queries = [
        statement
        for statement in statements
        if "from knowledge_point_scores" in " ".join(statement.split())
    ]
    assert len(assignment_queries) == 1
    assert len(score_queries) == 1


def test_teacher_and_admin_sources_are_role_scoped(action_center_context):
    app, ids = action_center_context
    with app.app_context():
        teacher_payload = build_action_center(db.session.get(User, ids["teacher"]), limit=50)
        trend = db.session.get(AbilityTrend, 1)
        trend.status = "processing"
        db.session.commit()
        admin_payload = build_action_center(db.session.get(User, ids["admin"]), limit=50)

    teacher_kinds = {item["kind"] for item in teacher_payload["items"]}
    admin_kinds = {item["kind"] for item in admin_payload["items"]}
    assert teacher_payload["role"] == "teacher"
    assert {"review", "teacher_ai"}.issubset(teacher_kinds)
    assert "admin_feedback" not in teacher_kinds
    teacher_json = json.dumps(teacher_payload, ensure_ascii=False)
    assert "其他教师作业" not in teacher_json
    assert "OUTSIDER_TEACHER_AI_OUTPUT" not in teacher_json
    assert {"feedback", "ability"}.issubset(admin_kinds)
    assert admin_payload["data_scope"] == "system-queue"
    assert any(item["status"] == "processing" for item in admin_payload["items"] if item["kind"] == "ability")
    assert "行动中心学生" not in json.dumps(admin_payload, ensure_ascii=False)


def test_priority_filter_limit_and_degraded_source_contract(action_center_context, monkeypatch):
    app, ids = action_center_context
    import services.action_center as action_center

    with app.app_context():
        urgent = build_action_center(db.session.get(User, ids["student"]), priority="urgent", limit=999)
        info = build_action_center(db.session.get(User, ids["student"]), priority="info", limit=999)
        fallback = build_action_center(db.session.get(User, ids["student"]), priority="not-valid")

        def broken_source(_actor, **_kwargs):
            raise RuntimeError("SECRET_INTERNAL_ERROR")

        monkeypatch.setattr(action_center, "_read_student_submissions", broken_source)
        degraded = build_action_center(db.session.get(User, ids["student"]))

    assert urgent["items"]
    assert all(item["priority"] == "urgent" for item in urgent["items"])
    assert all(item["priority"] == "info" for item in info["items"])
    assert fallback["counts"]["total"] >= len(fallback["items"])
    assert "submissions" in degraded["degraded_sources"]
    assert "SECRET_INTERNAL_ERROR" not in json.dumps(degraded, ensure_ascii=False)


def test_action_center_routes_require_login_and_return_no_store_json(action_center_context):
    app, ids = action_center_context
    client = app.test_client()
    assert client.get("/action-center").status_code in {302, 303}
    assert client.get("/api/action-center").status_code in {302, 303}

    _login(client, ids["student"])
    page = client.get("/action-center")
    response = client.get("/api/action-center?priority=urgent&limit=999")

    assert page.status_code == 200
    assert "行动中心" in page.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["schema_version"] == 1
    assert all(item["priority"] == "urgent" for item in response.get_json()["items"])


def test_action_center_page_has_accessible_queue_contract(action_center_context):
    app, ids = action_center_context
    client = app.test_client()
    _login(client, ids["student"])
    html = client.get("/action-center").get_data(as_text=True)

    assert 'aria-live="polite"' in html
    assert 'aria-labelledby="action-center-title"' in html
    assert "action-center.css" in html
    assert "学习队列" in html
    assert "SECRET_STUDENT_CODE" not in html


def test_action_center_empty_state_mentions_learning_suggestions(action_center_context):
    app, ids = action_center_context
    client = app.test_client()
    _login(client, ids["empty_student"])
    html = client.get("/action-center").get_data(as_text=True)

    assert "现在没有需要处理的行动。" in html
    assert "新的练习建议、提交状态、复核或通知" in html


def test_role_pages_render_their_scoped_queue_sources(action_center_context):
    app, ids = action_center_context

    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    teacher_html = teacher_client.get("/action-center").get_data(as_text=True)
    assert "班级建议：行动中心班" in teacher_html
    assert "班级知识提醒：数组" in teacher_html
    assert "知识图谱" in teacher_html
    assert "learning_graph" not in teacher_html
    assert f"/teacher/knowledge-focus/array" in teacher_html
    assert "其他教师作业" not in teacher_html
    assert 'class="action-center-count notification-count"' in teacher_html

    teacher_client.post("/logout")
    _login(teacher_client, ids["admin"])
    admin_html = teacher_client.get("/action-center").get_data(as_text=True)
    assert "反馈：后台反馈主题" in admin_html
    assert "能力分析：系统队列" in admin_html
    assert "行动中心学生" not in admin_html
    assert "PRIVATE_REVIEW_BODY" not in admin_html
    assert "班级知识提醒：数组" not in admin_html


def test_students_can_follow_graph_action_into_the_scoped_assignment(
    action_center_context,
):
    app, ids = action_center_context
    client = app.test_client()
    _login(client, ids["student"])

    action_page = client.get("/action-center")
    action_api = client.get("/api/action-center")
    practice_page = client.get(f"/submit/{ids['latest_assignment']}")

    assert action_page.status_code == 200
    assert f'href="/submit/{ids["latest_assignment"]}"' in action_page.get_data(as_text=True)
    assert action_api.status_code == 200
    api_items = action_api.get_json()["items"]
    assert any(
        item["kind"] == "learning_graph"
        and item["href"] == f"/submit/{ids['latest_assignment']}"
        for item in api_items
    )
    assert practice_page.status_code == 200


def test_submission_detail_explains_structured_ai_feedback(action_center_context):
    app, ids = action_center_context
    with app.app_context():
        submission = Submission.query.filter_by(student_id=ids["student"]).first()
        assert submission is not None
        submission.ai_feedback = json.dumps({
            "overall_score": 40,
            "overall_feedback": "检查循环条件。",
            "algorithm_score": 30,
            "dimension_feedback": "循环边界需要验证。",
        }, ensure_ascii=False)
        submission.score = 40
        submission.status = "evaluated"
        db.session.commit()
        submission_id = submission.id

    client = app.test_client()
    _login(client, ids["student"])
    response = client.get(f"/view_submission/{submission_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "AI 分项参考" in html
    assert "算法 30/100" in html
    assert "循环边界需要验证。" in html
    assert '&quot;overall_score&quot;' not in html


def test_pending_submission_detail_keeps_a_readable_score_state(action_center_context):
    app, ids = action_center_context
    with app.app_context():
        submission = Submission.query.filter_by(student_id=ids["student"]).first()
        assert submission is not None
        submission.score = None
        submission.status = "pending"
        db.session.commit()
        submission_id = submission.id

    client = app.test_client()
    _login(client, ids["student"])
    response = client.get(f"/view_submission/{submission_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "评测中" in html


def test_teacher_can_follow_graph_action_into_managed_class_focus(
    action_center_context,
):
    app, ids = action_center_context
    client = app.test_client()
    _login(client, ids["teacher"])

    action_page = client.get("/action-center")
    focus_page = client.get("/teacher/knowledge-focus/array")
    selected_class_page = client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['managed_class']}"
    )
    outside_class_page = client.get(
        f"/teacher/knowledge-focus/array?class_id={ids['outsider_class']}"
    )

    assert action_page.status_code == 200
    assert "班级知识提醒：数组" in action_page.get_data(as_text=True)
    assert focus_page.status_code == 200
    assert "行动中心作业" in focus_page.get_data(as_text=True)
    assert selected_class_page.status_code == 200
    assert "行动中心作业" in selected_class_page.get_data(as_text=True)
    assert outside_class_page.status_code == 403


def test_student_vector_refresh_action_is_private_and_reaches_memory_panel(
    action_center_context,
):
    app, ids = action_center_context
    with app.app_context():
        db.session.add(StudentVectorIndexState(
            student_id=ids["student"],
            revision=3,
            status="stale",
            source_count=4,
        ))
        db.session.commit()

    client = app.test_client()
    _login(client, ids["student"])
    student_page = client.get("/action-center")
    student_home = client.get("/home")
    student_items = client.get("/api/action-center").get_json()["items"]
    assert "需要更新" in student_home.get_data(as_text=True)
    assert any(item["kind"] == "learning_memory" for item in student_items)

    rebuilt_home = client.post(
        "/student/rebuild-learning-memory",
        follow_redirects=True,
    )
    rebuilt_items = client.get("/api/action-center").get_json()["items"]
    with app.app_context():
        vector_result = search_student_learning_vectors(
            ids["student"],
            "数组",
            assignment_id=ids["latest_assignment"],
        )

    client.post("/logout")
    _login(client, ids["teacher"])
    teacher_items = client.get("/api/action-center").get_json()["items"]

    client.post("/logout")
    _login(client, ids["admin"])
    admin_items = client.get("/api/action-center").get_json()["items"]

    assert student_page.status_code == 200
    assert 'href="/#student-learning-memory-title"' in student_page.get_data(as_text=True)
    assert student_home.status_code == 200
    assert 'id="student-learning-memory-title"' in student_home.get_data(as_text=True)
    assert any(item["kind"] == "learning_memory" for item in student_items)
    assert rebuilt_home.status_code == 200
    assert "学习记忆已更新" in rebuilt_home.get_data(as_text=True)
    assert all(item["kind"] != "learning_memory" for item in rebuilt_items)
    assert vector_result["status"] == "grounded"
    assert vector_result["metrics"]["scope_filter"] == "assignment"
    assert all(item["scope"] == "student_private" for item in vector_result["evidence"])
    assert all(item["kind"] != "learning_memory" for item in teacher_items)
    assert all(item["kind"] != "learning_memory" for item in admin_items)


def test_student_can_start_unbuilt_memory_from_action_center(action_center_context):
    app, ids = action_center_context
    client = app.test_client()
    _login(client, ids["student"])

    action_page = client.get("/action-center")
    action_items = client.get("/api/action-center").get_json()["items"]
    home_page = client.get("/home")

    action = next(item for item in action_items if item["kind"] == "learning_memory")
    assert action["status"] == "not_built"
    assert action["title"] == "建立我的学习记忆"
    assert action["href"] == "/#student-learning-memory-title"
    assert "建立我的学习记忆" in action_page.get_data(as_text=True)
    assert "尚未建立" in home_page.get_data(as_text=True)


def test_ready_memory_past_freshness_window_offers_refresh(action_center_context):
    app, ids = action_center_context
    with app.app_context():
        rebuilt = rebuild_student_vector_index(ids["student"])
        state = StudentVectorIndexState.query.filter_by(student_id=ids["student"]).one()
        state.last_built_at = datetime.utcnow() - timedelta(days=31)
        db.session.commit()
        action_items = build_action_center(
            db.session.get(User, ids["student"]),
            emit_log=False,
        )["items"]

    action = next(item for item in action_items if item["kind"] == "learning_memory")
    assert rebuilt["active_count"] > 0
    assert action["status"] == "stale"
    assert action["status_label"] == "需要更新"


def test_teacher_memory_reminder_resolves_after_student_rebuild(action_center_context):
    app, ids = action_center_context
    teacher_client = app.test_client()
    _login(teacher_client, ids["teacher"])
    reminder_response = teacher_client.post(
        f"/teacher/classes/{ids['managed_class']}/learning-memory-reminder"
    )
    assert reminder_response.status_code == 302
    teacher_client.post("/logout")
    with app.app_context():
        send_learning_memory_refresh_reminders(
            db.session.get(User, ids["teacher"]),
            ids["managed_class"],
            now=datetime.utcnow() + timedelta(days=1),
        )

    student_client = app.test_client()
    _login(student_client, ids["student"])
    before_payload = student_client.get("/api/action-center").get_json()
    assert before_payload["role"] == "student"
    before_items = before_payload["items"]
    memory_items = [
        item for item in before_items
        if item["kind"] in {"learning_memory", "learning_memory_refresh"}
    ]
    assert len(memory_items) == 1
    assert memory_items[0]["kind"] == "learning_memory_refresh"

    rebuild_response = student_client.post(
        "/student/rebuild-learning-memory",
        follow_redirects=True,
    )
    after_items = student_client.get("/api/action-center").get_json()["items"]
    with app.app_context():
        unread = list_notifications(ids["student"], unread_only=True)

    assert rebuild_response.status_code == 200
    assert all(
        item["kind"] not in {"learning_memory", "learning_memory_refresh"}
        for item in after_items
    )
    assert all(notification["kind"] != "learning_memory_refresh" for notification in unread)


@pytest.mark.parametrize(
    ("revision", "source_count", "has_previous_records"),
    [(0, 0, False), (4, 2, False), (4, 2, True)],
)
def test_failed_vector_build_message_tracks_available_index_sources(
    action_center_context,
    revision,
    source_count,
    has_previous_records,
):
    app, ids = action_center_context
    with app.app_context():
        if has_previous_records:
            rebuilt = rebuild_student_vector_index(ids["student"])
            assert rebuilt["active_count"] > 0
            state = StudentVectorIndexState.query.filter_by(student_id=ids["student"]).one()
        else:
            state = StudentVectorIndexState(student_id=ids["student"])
            db.session.add(state)
        state.revision = revision
        state.status = "failed"
        state.source_count = source_count
        db.session.commit()
        payload = build_action_center(
            db.session.get(User, ids["student"]),
            emit_log=False,
        )

    client = app.test_client()
    _login(client, ids["student"])
    home_html = client.get("/home").get_data(as_text=True)
    action = next(item for item in payload["items"] if item["kind"] == "learning_memory")
    assert action["status"] == "failed"
    if has_previous_records:
        assert "先前可用记录仍保留" in action["summary"]
        assert "原有学习记录仍然保留" in home_html
    else:
        assert "尚无可用记录" in action["summary"]
        assert "仍保留" not in action["summary"]
        assert "当前尚无可用记录" in home_html
        assert "原有学习记录仍然保留" not in home_html
