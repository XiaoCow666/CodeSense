import re
from pathlib import Path

import pytest

from app import create_app
from config import TestingConfig
from models import db


@pytest.fixture
def status_app(tmp_path, monkeypatch):
    database_path = tmp_path / "status-recovery.db"
    monkeypatch.setattr(
        TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_responses_expose_server_request_id_not_client_value(status_app):
    client = status_app.test_client()

    response = client.get("/healthz", headers={"X-Request-ID": "client-controlled"})

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["X-Request-ID"])
    assert response.headers["X-Request-ID"] != "client-controlled"


def test_html_404_is_recoverable_and_keeps_request_id(status_app):
    response = status_app.test_client().get("/missing-page")

    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "页面没有找到" in body
    assert "反馈中心" in body
    assert "请求编号" in body
    assert re.search(r"X?Request-ID|请求编号", body)


@pytest.mark.parametrize("path", ["/api/missing", "/healthz"])
def test_json_error_boundary_preserves_status_and_shape(status_app, path):
    method = "get" if path.startswith("/api/") else "post"
    response = getattr(status_app.test_client(), method)(
        path,
        headers={"Accept": "application/json"},
    )

    assert response.status_code in {404, 405}
    assert response.is_json
    assert set(response.json) == {"error", "message", "request_id"}
    assert re.fullmatch(r"[0-9a-f-]{36}", response.json["request_id"])


def test_html_500_is_generic_and_keeps_request_id(status_app):
    @status_app.get("/__status-recovery-500")
    def status_recovery_500():
        raise RuntimeError("secret exception should not be rendered")

    response = status_app.test_client().get("/__status-recovery-500")

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "页面暂时出了问题" in body
    assert "secret exception" not in body
    assert "请求编号" in body


def test_static_shell_has_local_favicon_and_recovery_hooks(status_app):
    favicon = status_app.test_client().get("/static/img/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.mimetype == "image/svg+xml"

    layout = Path("templates/layout.html").read_text(encoding="utf-8")
    base = Path("templates/base.html").read_text(encoding="utf-8")
    modern_css = Path("static/modern.css").read_text(encoding="utf-8")
    assert 'filename=\'img/favicon.svg\'' in layout
    assert 'filename=\'img/favicon.svg\'' in base
    assert 'id="codesense-live-region"' in layout
    assert "prefers-reduced-motion" in modern_css


def test_mobile_navigation_restores_focus_on_escape():
    layout = Path("templates/layout.html").read_text(encoding="utf-8")

    assert "lastFocusedElement" in layout
    assert "event.key === 'Escape'" in layout
    assert "lastFocusedElement.focus()" in layout
    assert "aria-expanded', 'false'" in layout


def test_teacher_and_student_templates_expose_recovery_states():
    teacher = Path("templates/teacher_ai_suggestions.html").read_text(encoding="utf-8")
    evaluating = Path("templates/submission_evaluating.html").read_text(encoding="utf-8")

    assert 'role="status"' in teacher
    assert 'aria-busy="true"' in teacher
    assert "DOMPurify.sanitize" in teacher
    assert "function escapeHtml" in teacher
    assert 'role="progressbar"' in evaluating
    assert 'aria-live="polite"' in evaluating
    assert 'id="retry-status"' in evaluating
    assert "查看提交记录" in evaluating
