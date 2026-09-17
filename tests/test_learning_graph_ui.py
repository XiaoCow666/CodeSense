from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PANEL = (PROJECT_ROOT / "templates" / "components" / "learning_graph_panel.html").read_text(
    encoding="utf-8"
)
STUDENT_HOME = (PROJECT_ROOT / "templates" / "student_home.html").read_text(
    encoding="utf-8"
)
TEACHER_HOME = (PROJECT_ROOT / "templates" / "teacher_home.html").read_text(
    encoding="utf-8"
)
MODERN_CSS = (PROJECT_ROOT / "static" / "modern.css").read_text(encoding="utf-8")


def test_learning_graph_panel_has_accessible_and_safe_states():
    assert 'aria-labelledby="{{ graph_id }}-title"' in PANEL
    assert 'role="progressbar"' in PANEL
    assert 'role="status"' in PANEL
    assert "样本不足" in PANEL
    assert "不会在此处展示个人姓名或个人分数" in PANEL
    assert "不代表系统已经判定它们存在先后依赖" in PANEL
    assert "url_for('assignments.submit_code'" in PANEL
    assert "innerHTML" not in PANEL


def test_dashboards_mount_the_same_learning_graph_panel():
    assert "components/learning_graph_panel.html" in STUDENT_HOME
    assert "components/learning_graph_panel.html" in TEACHER_HOME
    assert "student-learning-graph" in STUDENT_HOME
    assert "teacher-knowledge-coverage" in TEACHER_HOME


def test_learning_graph_panel_has_responsive_styles():
    assert ".learning-graph-panel" in MODERN_CSS
    assert ".learning-graph-concepts" in MODERN_CSS
    assert ".learning-graph-coverage-grid" in MODERN_CSS
    assert "@media (max-width: 480px)" in MODERN_CSS
