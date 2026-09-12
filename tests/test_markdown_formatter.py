"""Characterization tests for ``utils/markdown_formatter.py``.

``MarkdownFormatter`` normalizes LLM-produced Markdown: CRLF handling, fenced
code-block language tags, closure of unterminated fences, wrapping of bare
code-like paragraphs, list-marker spacing, and a small subset of HTML
rendering. It is a standard-library-only module (``re``/``typing``), so these
tests import it directly: no Flask app, database, Redis, or network access.

The assertions pin behavior verified against the current implementation that
is also implied by the docstrings. The heading-spacing pass in ``enhance``
has known quirks on isolated heading lines; that path is deliberately not
pinned here so a future fix to it stays green.
"""

import pytest

from utils.markdown_formatter import (
    MarkdownFormatter,
    enhance_code_blocks,
    enhance_markdown,
)


# ---------------------------------------------------------------------------
# falsy passthrough and newline normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["", None])
def test_enhance_passes_falsy_input_through_unchanged(value):
    assert MarkdownFormatter.enhance(value) is value


@pytest.mark.parametrize("value", ["", None])
def test_enhance_code_blocks_passes_falsy_input_through_unchanged(value):
    assert MarkdownFormatter.enhance_code_blocks(value) is value


@pytest.mark.parametrize(
    "fn",
    [MarkdownFormatter.enhance, MarkdownFormatter.enhance_code_blocks],
)
def test_public_entry_points_normalize_crlf_to_lf(fn):
    assert fn("a\r\nb\r\nc") == "a\nb\nc"


# ---------------------------------------------------------------------------
# fenced code-block closure
# ---------------------------------------------------------------------------

def test_fix_code_blocks_appends_closing_fence_when_unbalanced():
    text = "explanation\n```cpp\nint a = 1;"
    assert MarkdownFormatter._fix_code_blocks(text, "cpp") == text + "\n```"


def test_fix_code_blocks_leaves_balanced_fences_untouched():
    text = "```cpp\nint a = 1;\n```"
    assert MarkdownFormatter._fix_code_blocks(text, "cpp") == text


def test_ensure_code_block_closed_appends_fence_for_odd_count():
    text = "```cpp\nint a = 1;"
    assert MarkdownFormatter._ensure_code_block_closed(text) == text + "\n```"


def test_enhance_code_blocks_closes_unterminated_fence():
    assert MarkdownFormatter.enhance_code_blocks("```cpp\nint a = 1;") == (
        "```cpp\nint a = 1;\n```"
    )


def test_enhance_closes_unterminated_fence():
    text = "note\n```cpp\nint a = 1;"
    assert MarkdownFormatter.enhance(text) == text + "\n```"


# ---------------------------------------------------------------------------
# language-tag normalization
# ---------------------------------------------------------------------------

def test_missing_language_tag_gets_default():
    assert MarkdownFormatter._fix_code_block_langs(
        "```\nx = 1\n```", "cpp"
    ) == "```cpp\nx = 1\n```"


@pytest.mark.parametrize(
    "raw_lang,expected",
    [
        ("c", "cpp"),
        ("C", "cpp"),
        ("py", "python"),
        ("javascript", "js"),
        ("j", "java"),
        ("J", "java"),
        ("sh", "bash"),
        ("shell", "bash"),
    ],
)
def test_language_aliases_are_mapped_case_insensitively(raw_lang, expected):
    out = MarkdownFormatter._fix_code_block_langs(
        f"```{raw_lang}\ncode\n```", "cpp"
    )
    assert out == f"```{expected}\ncode\n```"


def test_unknown_language_tag_is_preserved():
    assert MarkdownFormatter._fix_code_block_langs(
        "```rust\ncode\n```", "cpp"
    ) == "```rust\ncode\n```"


def test_missing_language_tag_respects_custom_default():
    assert MarkdownFormatter._fix_code_block_langs(
        "```\ncode\n```", "python"
    ) == "```python\ncode\n```"


# ---------------------------------------------------------------------------
# bare code detection and wrapping
# ---------------------------------------------------------------------------

def test_looks_like_code_requires_marker_and_multiple_lines():
    assert MarkdownFormatter._looks_like_code("int a = 1;\nreturn a;") is True


@pytest.mark.parametrize(
    "text",
    [
        "int a = 1;",  # single line is not enough
        "# heading\nint a = 1;\nreturn a;",  # headings stay prose
        "- item\n- other",  # list markup stays prose
        "> quote line",  # blockquote stays prose
        "```cpp\nint a;\n```",  # already fenced
    ],
)
def test_looks_like_code_rejects_non_code_paragraphs(text):
    assert MarkdownFormatter._looks_like_code(text) is False


def test_fix_plain_code_wraps_code_like_paragraph_only():
    text = "some prose paragraph\n\nint a = 1;\nreturn a;"
    assert MarkdownFormatter._fix_plain_code(text, "cpp") == (
        "some prose paragraph\n\n```cpp\nint a = 1;\nreturn a;\n```"
    )


def test_fix_plain_code_leaves_prose_paragraphs_untouched():
    text = "just an explanation\n\nwith another plain paragraph"
    assert MarkdownFormatter._fix_plain_code(text, "cpp") == text


def test_enhance_code_blocks_wraps_bare_multiline_code():
    assert MarkdownFormatter.enhance_code_blocks(
        "int a = 1;\nreturn a;", "cpp"
    ) == "```cpp\nint a = 1;\nreturn a;\n```"


# ---------------------------------------------------------------------------
# list-marker spacing
# ---------------------------------------------------------------------------

def test_fix_lists_inserts_space_after_bullet_markers():
    assert MarkdownFormatter._fix_lists("*a\n-b\n+c") == "* a\n- b\n+ c"


def test_fix_lists_leaves_well_formed_bullets_and_numbers_untouched():
    text = "* a\n- b\n1. first\n2. second"
    assert MarkdownFormatter._fix_lists(text) == text


def test_fix_lists_inserts_space_after_numbered_dot():
    # A malformed "1.a" must become "1. a"; any correct implementation of
    # the marker fix produces this, so the assertion survives a future
    # reimplementation of the spacing logic.
    assert MarkdownFormatter._fix_lists("1.a") == "1. a"


def test_fix_lists_does_not_touch_content_inside_code_fences():
    assert MarkdownFormatter._fix_lists("```\n*a\n-b\n```") == "```\n*a\n-b\n```"


# ---------------------------------------------------------------------------
# enhance() integration on heading-free documents
# ---------------------------------------------------------------------------

def test_enhance_normalizes_document_with_lists_and_fences():
    raw = "*a\r\n-b\r\n\r\n```cpp\r\nint a = 1;"
    assert MarkdownFormatter.enhance(raw) == (
        "* a\n- b\n\n```cpp\nint a = 1;\n```"
    )


def test_enhance_leaves_plain_prose_paragraphs_unchanged():
    text = "hello world\n\nsecond para"
    assert MarkdownFormatter.enhance(text) == text


# ---------------------------------------------------------------------------
# module-level convenience wrappers
# ---------------------------------------------------------------------------

def test_convenience_functions_delegate_to_formatter():
    text = "a\r\n*b"
    assert enhance_markdown(text) == MarkdownFormatter.enhance(text)
    assert enhance_code_blocks(text) == MarkdownFormatter.enhance_code_blocks(text)


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

def test_render_html_wraps_paragraphs():
    assert MarkdownFormatter.render_html("first line\nsecond line") == (
        "<p>first line</p>\n<p>second line</p>"
    )


def test_render_html_emits_list_items():
    assert MarkdownFormatter.render_html("- one\n* two") == (
        "<li>one</li>\n<li>two</li>"
    )


def test_render_html_escapes_angle_brackets_inside_code_blocks():
    html = MarkdownFormatter.render_html("```cpp\nif (a < b && c > d) {}\n```")
    # Only angle brackets are escaped; "&" is passed through by the current
    # simplified renderer.
    assert html == (
        '<pre><code class="language-cpp">\n'
        "if (a &lt; b && c &gt; d) {}\n"
        "</code></pre>"
    )
