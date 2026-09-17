from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_dashboard_has_a_refreshable_quality_card():
    template = (ROOT / "templates" / "admin_dashboard.html").read_text(
        encoding="utf-8"
    )

    assert "css/knowledge-quality.css" in template
    assert "js/knowledge-quality.js" in template
    assert 'id="knowledge-quality-card"' in template
    assert "api.get_knowledge_quality" in template
    assert "检索质量" in template
    assert "刷新状态" in template


def test_quality_dashboard_script_is_bounded_and_accessible():
    script = (ROOT / "static" / "js" / "knowledge-quality.js").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "static" / "css" / "knowledge-quality.css").read_text(
        encoding="utf-8"
    )

    assert "cache: 'no-store'" in script or 'cache: "no-store"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "aria-live" in script
    assert "status_counts" in script
    assert "mode_counts" in script
    assert ":focus-visible" in css
    assert "@media (max-width: 767px)" in css
