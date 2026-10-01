"""Static contracts for the shared knowledge evidence assignment panel."""

from pathlib import Path
from bs4 import BeautifulSoup


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
    assert "retry_url" in macro
    assert "knowledge-evidence-retry" in macro
    assert "重新检索证据" in macro


def test_evidence_styles_define_tokens_focus_mobile_and_reduced_motion():
    css = (ROOT / "static" / "css" / "knowledge-evidence.css").read_text(
        encoding="utf-8"
    )

    for token in (
        "var(--cs-ink)",
        "var(--cs-accent)",
        "var(--cs-accent-soft)",
        "var(--cs-line)",
    ):
        assert token in css
    assert ":focus-visible" in css
    assert ":focus-within" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_compact_evidence_is_a_keyboard_operable_disclosure():
    macro = (ROOT / "templates" / "components" / "knowledge_evidence.html").read_text(
        encoding="utf-8"
    )
    submit = (ROOT / "templates" / "submit_code.html").read_text(encoding="utf-8")

    assert 'class="knowledge-evidence-panel__compact-disclosure"' in macro
    assert 'class="knowledge-evidence-panel__compact-summary"' in macro
    assert "<summary" in macro
    assert "knowledge-evidence-retry" in macro
    assert "knowledge-evidence-citation" in macro
    assert "knowledge-evidence-detail__source" in macro
    for element_id in ("ai-chat-messages", "ai-chat-input", "ai-send-button", "clear-chat"):
        assert f'id="{element_id}"' in submit
    assert 'class="ai-assistant-panel code-studio-assistant"' in submit


def test_analysis_evidence_stays_inside_scrollable_chat_messages():
    submit = (ROOT / "templates" / "submit_code.html").read_text(encoding="utf-8")
    document = BeautifulSoup(submit, "html.parser")
    mount = document.select_one("#code-studio-analysis-evidence")
    assert mount is not None
    assert mount.find_parent(id="ai-chat-messages") is not None
    chat_section = submit.split('id="ai-chat-messages"', 1)[1].split(
        'class="ai-chat-input-area"', 1
    )[0]
    assert "panel_id='code-studio-knowledge-evidence'" in chat_section


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
    assert "assignments.submit_code" in submit
    assert "assignments.submit_code" in submission


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
    assert "timeout" in renderer
    assert "rate_limited" in renderer
    assert "retryUrl" in renderer
    assert "cache: 'no-store'" in renderer or 'cache: "no-store"' in renderer
    assert "aria-label" in renderer
    assert "disabled" in renderer
    assert "js/knowledge-evidence.js" in submit
    assert "CodeSenseKnowledgeEvidence.render" in submit
    assert "retryUrl" in submit
    assert submit.count("appendKnowledgeEvidenceMount(wrapper);") == 2
    done_index = submit.index("if (data.done)")
    delta_index = submit.index("if (data.content)")
    assert done_index < delta_index
