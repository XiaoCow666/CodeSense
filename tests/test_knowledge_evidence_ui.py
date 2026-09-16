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


def test_submission_and_code_studio_reuse_the_evidence_workspace():
    submission = (ROOT / "templates" / "submission_detail.html").read_text(
        encoding="utf-8"
    )
    submit = (ROOT / "templates" / "submit_code.html").read_text(
        encoding="utf-8"
    )

    assert 'components/knowledge_evidence.html' in submission
    assert "这道作业使用的知识焦点" in submission
    assert "boundary_note=true" in submission
    assert 'components/knowledge_evidence.html' in submit
    assert "knowledge_evidence" in submit
    assert "请用问题引导我检查" in submit


def test_dynamic_evidence_renderer_is_safe_and_done_only():
    renderer = (ROOT / "static" / "js" / "knowledge-evidence.js").read_text(
        encoding="utf-8"
    )
    submit = (ROOT / "templates" / "submit_code.html").read_text(
        encoding="utf-8",
    )

    assert "window.CodeSenseKnowledgeEvidence" in renderer
    assert "replaceChildren" in renderer
    assert "textContent" in renderer
    assert 'role", "status"' in renderer or "role', 'status'" in renderer
    assert "aria-live" in renderer
    assert "innerHTML" not in renderer
    assert "js/knowledge-evidence.js" in submit
    assert "CodeSenseKnowledgeEvidence.render" in submit
    assert submit.count("appendKnowledgeEvidenceMount(wrapper);") == 2
    done_index = submit.index("if (data.done)")
    delta_index = submit.index("if (data.content)")
    assert done_index < delta_index
