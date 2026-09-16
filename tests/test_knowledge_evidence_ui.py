"""Static contracts for the shared knowledge evidence assignment panel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_assignment_detail_uses_the_shared_evidence_macro_and_stylesheet():
    template = (ROOT / "templates" / "assignment_detail.html").read_text(
        encoding="utf-8"
    )

    assert 'components/knowledge_evidence.html' in template
    assert "knowledge_evidence_panel" in template
    assert 'css/knowledge-evidence.css' in template
    assert "knowledge_evidence" in template


def test_evidence_macro_has_accessible_status_and_disclosure_contract():
    macro = (ROOT / "templates" / "components" / "knowledge_evidence.html").read_text(
        encoding="utf-8"
    )

    assert "aria-labelledby" in macro
    assert 'role="status"' in macro
    assert 'aria-live="polite"' in macro
    assert "<details" in macro
    assert "<summary" in macro
    assert "knowledge-evidence-detail" in macro
    assert "knowledge-evidence-panel" in macro


def test_evidence_styles_define_tokens_focus_mobile_and_reduced_motion():
    css = (ROOT / "static" / "css" / "knowledge-evidence.css").read_text(
        encoding="utf-8"
    )

    for token in (
        "#14213D",
        "#2F80ED",
        "#F7FAFC",
        "#0F766E",
        "#B45309",
    ):
        assert token in css
    assert ":focus-visible" in css
    assert ":focus-within" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
