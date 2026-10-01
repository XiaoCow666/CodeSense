from pathlib import Path
import re


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


def test_first_party_pages_do_not_use_gradients():
    gradient = re.compile(r"(?:linear|radial)-gradient\(", re.I)
    offenders = []
    for directory, suffix in (("static", ".css"), ("templates", ".html")):
        for path in (ROOT / directory).rglob(f"*{suffix}"):
            if "vendor" in path.parts:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if gradient.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "Gradient declarations remain in: " + ", ".join(offenders)


def test_bootstrap_primary_utilities_follow_the_shared_accent():
    css = CSS.read_text(encoding="utf-8")
    for selector in (".bg-primary", ".text-primary", ".btn-outline-primary"):
        assert selector in css
    assert "--bs-primary: var(--cs-accent);" in css


def test_login_explains_the_product_before_scripts_run():
    template = (ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    banner = template.split('class="left-banner"', 1)[1].split(
        'class="right-panel"', 1
    )[0]
    assert re.search(r"<h1>[^<]*编程[^<]*</h1>", banner)
