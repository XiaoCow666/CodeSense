from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "static" / "modern.css"

EXPECTED_COLORS = {
    "--cs-bg": "#F5F7F8",
    "--cs-surface": "#FFFFFF",
    "--cs-ink": "#23343D",
    "--cs-muted": "#64757D",
    "--cs-line": "#DDE5E6",
    "--cs-accent": "#237B75",
    "--cs-accent-soft": "#EAF4F2",
    "--cs-input": "#F0F3F3",
}


def test_shared_theme_exposes_flat_semantic_colors():
    css = CSS.read_text(encoding="utf-8")
    for name, value in EXPECTED_COLORS.items():
        assert f"{name}: {value};" in css
    assert "background-color: var(--cs-bg);" in css
    assert "background-color: var(--cs-surface);" in css
    assert "background-color: var(--cs-accent);" in css
    assert "outline: 3px solid var(--cs-accent);" in css
