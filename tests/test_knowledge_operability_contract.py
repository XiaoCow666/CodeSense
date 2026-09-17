from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_knowledge_logs_keep_fallback_and_privacy_fields_bounded():
    routes = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")

    assert "retrieval_timeout_fallback" in routes
    assert "rate_limit_fallback" in routes
    assert "index_revision" in routes
    assert "privacy_filtered_count" in routes
    assert "query=%s" not in routes
    assert "answer=%s" not in routes


def test_help_explains_evidence_status_and_safe_recovery():
    help_page = (ROOT / "templates" / "help.html").read_text(encoding="utf-8")

    assert "知识证据" in help_page
    assert "超时" in help_page
    assert "限流" in help_page
    assert "重新检索" in help_page
    assert "不是评分依据" in help_page
