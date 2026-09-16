"""Role-aware assignment knowledge evidence view contracts."""

import json

import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from models import Assignment, AssignmentKnowledgePoint, KnowledgePointScore, User, db
from routes import assignments as assignment_routes


@pytest.fixture
def assignment_view_context(tmp_path, monkeypatch):
    database_path = tmp_path / "assignment-knowledge-views.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        student = User(
            student_id="assignment-view-student",
            username="assignment-view-student",
            usertype="学生",
            full_name="页面学生私密名",
        )
        outsider = User(
            student_id="assignment-view-outsider",
            username="assignment-view-outsider",
            usertype="学生",
        )
        teacher = User(
            student_id="assignment-view-teacher",
            username="assignment-view-teacher",
            usertype="教师",
        )
        admin = User(
            student_id="assignment-view-admin",
            username="assignment-view-admin",
            usertype="管理员",
        )
        for user in (student, outsider, teacher, admin):
            user.password = "password"

        student_assignment = Assignment(
            title="学生证据作业",
            description="请处理数组边界。",
            creator_id=student.student_id,
        )
        staff_assignment = Assignment(
            title="教师证据作业",
            description="教师查看安全诊断。",
            creator_id=teacher.student_id,
        )
        db.session.add_all(
            [student, outsider, teacher, admin, student_assignment, staff_assignment]
        )
        db.session.commit()

        AssignmentKnowledgePoint.add_to_assignment(
            student_assignment.id,
            "array",
            weight=1.5,
            auto_detected=True,
        )
        AssignmentKnowledgePoint.add_to_assignment(
            staff_assignment.id,
            "pointer",
            weight=1.0,
        )
        db.session.add(
            KnowledgePointScore(
                student_id=student.student_id,
                knowledge_point="array",
                score=99.0,
            )
        )
        db.session.commit()
        ids = {
            "student_assignment": student_assignment.id,
            "staff_assignment": staff_assignment.id,
        }

    client = app.test_client()
    yield app, client, ids

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _login(client, username):
    response = client.post(
        "/login",
        data={"username": username, "password": "password"},
    )
    assert response.status_code in {302, 303}


def _retrieval(status="grounded"):
    evidence = []
    if status == "grounded":
        evidence = [
            {
                "evidence_id": "assignment-kp:1",
                "citation": "[K1]",
                "source_type": "assignment_knowledge_point",
                "title": "数组边界",
                "content": "当前作业显式绑定知识点：数组边界。",
                "created_at": "2026-09-16T08:00:00",
            }
        ]
    return {
        "status": status,
        "evidence": evidence,
        "metrics": {
            "candidate_count": 1,
            "hit_count": 1 if evidence else 0,
            "indexed_chunk_count": 1,
            "retrieval_latency_ms": 2.5,
            "retrieval_mode": "vector" if evidence else status,
        },
        "fallback": (
            {
                "code": "NO_KNOWLEDGE_EVIDENCE",
                "message": "知识证据暂不可引用。",
            }
            if status == "no_result"
            else {
                "code": "KNOWLEDGE_RETRIEVAL_UNAVAILABLE",
                "message": "知识证据暂时不可用。",
            }
            if status == "unavailable"
            else None
        ),
    }


def test_view_assignment_rejects_before_retrieval(assignment_view_context, monkeypatch):
    _, client, ids = assignment_view_context
    _login(client, "assignment-view-outsider")

    def retrieval_must_not_run(*args, **kwargs):
        pytest.fail("assignment access must be checked before retrieval")

    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        retrieval_must_not_run,
    )

    response = client.get(f"/view_assignment/{ids['student_assignment']}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


@pytest.mark.parametrize(
    ("username", "assignment_key", "audience"),
    [
        ("assignment-view-student", "student_assignment", "student"),
        ("assignment-view-teacher", "staff_assignment", "teacher"),
        ("assignment-view-admin", "staff_assignment", "admin"),
    ],
)
def test_view_assignment_passes_role_aware_knowledge_evidence(
    assignment_view_context,
    monkeypatch,
    username,
    assignment_key,
    audience,
):
    _, client, ids = assignment_view_context
    _login(client, username)
    captured = {}

    def fake_render(template, **context):
        captured.update(template=template, context=context)
        return "rendered"

    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: _retrieval(),
    )
    monkeypatch.setattr(assignment_routes, "render_template", fake_render)

    response = client.get(f"/view_assignment/{ids[assignment_key]}")

    assert response.status_code == 200
    assert captured["template"] == "assignment_detail.html"
    view = captured["context"]["knowledge_evidence"]
    assert view["status"] == "grounded"
    assert view["evidence"][0]["title"] == "数组边界"
    if audience == "student":
        assert "diagnostics" not in view
    else:
        assert view["diagnostics"]["candidate_count"] == 1


def test_student_html_has_learning_evidence_but_no_diagnostics_or_private_scores(
    assignment_view_context, monkeypatch
):
    _, client, ids = assignment_view_context
    _login(client, "assignment-view-student")
    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: _retrieval(),
    )

    response = client.get(f"/view_assignment/{ids['student_assignment']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "已找到作业知识证据" in html
    assert "数组边界" in html
    assert "当前作业显式绑定知识点：数组边界。" in html
    assert "展开证据详情，把问题与对应概念联系起来。" in html
    assert "diagnostics" not in html
    assert "KnowledgePointScore" not in html
    assert "99.0" not in html
    panel = html.split('id="assignment-knowledge-evidence"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "页面学生私密名" not in panel


def test_teacher_html_contains_bounded_diagnostics_only(
    assignment_view_context, monkeypatch
):
    _, client, ids = assignment_view_context
    _login(client, "assignment-view-teacher")
    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: _retrieval(),
    )

    response = client.get(f"/view_assignment/{ids['staff_assignment']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "作业知识诊断" in html
    assert "候选证据 1" in html
    assert "命中证据 1" in html
    assert "KnowledgePointScore" not in html
    assert "private_score" not in html


@pytest.mark.parametrize(
    ("status", "expected_label", "expected_next_step"),
    [
        ("grounded", "已找到作业知识证据", "展开证据详情"),
        ("no_result", "暂无匹配证据", "缩小问题"),
        ("unavailable", "证据暂时不可用", "稍后重试"),
    ],
)
def test_assignment_html_explains_all_retrieval_states(
    assignment_view_context,
    monkeypatch,
    status,
    expected_label,
    expected_next_step,
):
    _, client, ids = assignment_view_context
    _login(client, "assignment-view-student")
    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: _retrieval(status),
    )

    response = client.get(f"/view_assignment/{ids['student_assignment']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert expected_label in html
    assert expected_next_step in html
    if status != "grounded":
        assert "基础指导仍可继续" in html or "暂无可引用" in html


def test_assignment_html_escapes_evidence_text(assignment_view_context, monkeypatch):
    _, client, ids = assignment_view_context
    _login(client, "assignment-view-student")
    unsafe = _retrieval()
    unsafe["evidence"][0]["title"] = "<script>alert('title')</script>"
    unsafe["evidence"][0]["content"] = "<img src=x onerror=alert('content')>"
    monkeypatch.setattr(
        assignment_routes,
        "retrieve_assignment_knowledge",
        lambda *args, **kwargs: unsafe,
    )

    response = client.get(f"/view_assignment/{ids['student_assignment']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "&lt;script&gt;alert(&#39;title&#39;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(&#39;content&#39;)&gt;" in html
    assert "<script>alert('title')</script>" not in html
    assert "<img src=x onerror=alert('content')>" not in html


def test_role_aware_context_does_not_serialize_private_fields(assignment_view_context):
    _, _, ids = assignment_view_context
    view = _retrieval()
    payload = json.dumps(view, ensure_ascii=False)
    assert "KnowledgePointScore" not in payload
    assert str(ids["student_assignment"]) in payload or ids["student_assignment"]
