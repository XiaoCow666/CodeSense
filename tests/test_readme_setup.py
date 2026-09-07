"""Keep the documented local setup commands executable and in sync."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readmes_document_windows_activation_and_test_dependencies():
    for name in ("README.md", "README.en.md"):
        content = (ROOT / name).read_text(encoding="utf-8")
        assert ".venv\\Scripts\\Activate.ps1" in content
        assert "python -m pip install -r requirements-test.txt" in content
        assert "Python 3.14" in content


def test_test_requirements_include_runtime_requirements():
    content = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    active_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "-r requirements.txt" in active_lines
