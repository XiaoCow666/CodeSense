import pytest

from app import create_app
from config import TestingConfig as _TestingConfig
from routes import api as api_routes
from services.knowledge_pipeline import KnowledgeDocument, ParagraphChunker
from services.knowledge_rag import retrieve_assignment_knowledge
from services.knowledge_reliability import (
    KnowledgePrivacyFilter,
    KnowledgeQualityMonitor,
    SlidingWindowRateLimiter,
    VersionedKnowledgeIndex,
)
from services.knowledge_vector_store import (
    HybridKnowledgeIndex,
    InMemoryVectorStore,
    KnowledgeRetrievalTimeout,
    NgramCountEmbedder,
)
from models import Assignment, db, User


@pytest.fixture
def knowledge_context(tmp_path, monkeypatch):
    database_path = tmp_path / "knowledge_reliability.db"
    monkeypatch.setattr(
        _TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{database_path}",
    )
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        student = User(
            student_id="reliability-student",
            username="reliability-student",
            usertype="学生",
        )
        student.password = "password"
        assignment = Assignment(
            title="可靠性演练题",
            description="验证知识检索的安全回退。",
            creator_id="reliability-student",
        )
        db.session.add_all([student, assignment])
        db.session.commit()
        assignment_id = assignment.id
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": "reliability-student", "password": "password"},
    )
    assert login.status_code in {302, 303}
    yield app, client, assignment_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _chunks(*documents):
    chunker = ParagraphChunker()
    return tuple(
        chunk
        for document in documents
        for chunk in chunker.split(document)
    )


def test_versioned_index_applies_incremental_update_and_rolls_back():
    index = VersionedKnowledgeIndex(
        _chunks(
            KnowledgeDocument("array", "数组", "数组边界。", "offline-eval"),
            KnowledgeDocument("pointer", "指针", "指针生命周期。", "offline-eval"),
        )
    )

    published = index.upsert(
        _chunks(
            KnowledgeDocument("array", "数组下标", "数组下标从零开始。", "offline-eval")
        ),
        remove_document_ids=["pointer"],
    )

    assert published.number == 2
    assert [item.chunk.document_id for item in index.search("下标").candidates] == [
        "array"
    ]
    assert all(item.document_id != "pointer" for item in index.chunks)

    rolled_back = index.rollback()

    assert rolled_back.number == 3
    assert index.history_depth == 0
    assert {item.document_id for item in index.chunks} == {"array", "pointer"}


def test_versioned_index_does_not_publish_a_failed_update():
    class FailingEmbedder(NgramCountEmbedder):
        def embed(self, text):
            if "boom" in text:
                raise RuntimeError("embedding failed")
            return super().embed(text)

    index = VersionedKnowledgeIndex(
        _chunks(KnowledgeDocument("stable", "稳定", "旧内容。", "offline-eval")),
        embedder=FailingEmbedder(),
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        index.upsert(
            _chunks(KnowledgeDocument("stable", "稳定", "boom。", "offline-eval"))
        )

    assert index.revision.number == 1
    assert index.history_depth == 0
    assert index.chunks[0].text == "旧内容。"


def test_privacy_filter_redacts_content_and_drops_unsafe_metadata():
    document = KnowledgeDocument(
        "private",
        "联系alice@example.com",
        "请联系alice@example.com，手机号 13800138000，请token=top-secret",
        "offline-eval",
        metadata={
            "evidence_id": "safe-id",
            "record_id": 7,
            "secret_note": "do not copy",
        },
    )

    sanitized = KnowledgePrivacyFilter.sanitize_document(document)

    assert "alice@example.com" not in sanitized.title
    assert "alice@example.com" not in sanitized.content
    assert "13800138000" not in sanitized.content
    assert "top-secret" not in sanitized.content
    assert "[已过滤]" in sanitized.title
    assert "[已过滤]" in sanitized.content
    assert set(sanitized.metadata) == {"evidence_id", "record_id"}


def test_privacy_filter_validates_whitelisted_metadata_types_and_formats():
    document = KnowledgeDocument(
        "private-metadata",
        "安全标题",
        "安全内容",
        "offline-eval",
        metadata={
            "evidence_id": "alice@example.com",
            "record_id": "7",
            "created_at": "not-a-timestamp",
        },
    )

    sanitized = KnowledgePrivacyFilter.sanitize_document(document)

    assert sanitized.metadata == {}


def test_rate_limiter_releases_capacity_after_window():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(
        max_requests=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    assert limiter.allow("assignment:1") is True
    assert limiter.allow("assignment:1") is True
    assert limiter.allow("assignment:1") is False
    now[0] = 10.1
    assert limiter.allow("assignment:1") is True


def test_quality_monitor_bounds_caller_controlled_label_cardinality():
    monitor = KnowledgeQualityMonitor(max_samples=2, max_labels=3)

    for index in range(20):
        monitor.record(
            status=f"status-{index}",
            mode=f"mode-{index}",
            latency_ms=index,
            fallback_code=f"fallback-{index}",
        )

    snapshot = monitor.snapshot()

    assert len(snapshot["status_counts"]) <= 3
    assert len(snapshot["mode_counts"]) <= 3
    assert snapshot["status_counts"]["requests"] == 20
    assert snapshot["status_counts"]["__other__"] > 0
    assert snapshot["mode_counts"]["__other__"] > 0
    assert snapshot["latency_sample_count"] == 2


def test_vector_index_enforces_deadline_before_work():
    with pytest.raises(KnowledgeRetrievalTimeout):
        HybridKnowledgeIndex(
            _chunks(KnowledgeDocument("slow", "慢", "内容。", "offline-eval")),
            deadline=0.0,
            clock=lambda: 1.0,
        )


def test_vector_store_upsert_only_embeds_changed_chunks():
    class CountingEmbedder(NgramCountEmbedder):
        def __init__(self):
            self.calls = 0

        def embed(self, text):
            self.calls += 1
            return super().embed(text)

    embedder = CountingEmbedder()
    store = InMemoryVectorStore(embedder)
    initial = _chunks(
        KnowledgeDocument("array", "数组", "旧数组内容。", "offline-eval"),
        KnowledgeDocument("pointer", "指针", "指针内容。", "offline-eval"),
    )
    changed = _chunks(
        KnowledgeDocument("array", "数组", "新数组内容。", "offline-eval")
    )

    store.write(initial)
    store.upsert(changed)

    assert embedder.calls == 3
    assert store.chunks[0].text == "新数组内容。"
    assert store.chunks[1].text == "指针内容。"


def test_retriever_rate_limit_stays_on_answer_only_path(knowledge_context):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        from models import AssignmentKnowledgePoint

        AssignmentKnowledgePoint.add_to_assignment(assignment_id, "array")
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        monitor = KnowledgeQualityMonitor()
        first = retrieve_assignment_knowledge(
            assignment_id,
            query="数组",
            rate_limiter=limiter,
            request_key="test-rate-limit",
            quality_monitor=monitor,
        )
        second = retrieve_assignment_knowledge(
            assignment_id,
            query="数组",
            rate_limiter=limiter,
            request_key="test-rate-limit",
            quality_monitor=monitor,
        )

    assert first["status"] == "grounded"
    assert second["status"] == "rate_limited"
    assert second["metrics"]["rate_limit_fallback"] is True
    assert "仅基于题目和代码" in second["fallback"]["message"]
    assert monitor.snapshot()["status_counts"]["rate_limited"] == 1


def test_ask_question_rate_limit_returns_answer_only_response(
    knowledge_context, monkeypatch
):
    app, client, assignment_id = knowledge_context
    with app.app_context():
        from models import AssignmentKnowledgePoint

        AssignmentKnowledgePoint.add_to_assignment(assignment_id, "array")
        monkeypatch.setattr(
            "services.knowledge_rag.knowledge_rate_limiter",
            SlidingWindowRateLimiter(max_requests=1, window_seconds=60),
        )

    monkeypatch.setattr(
        api_routes,
        "generate_answer_to_question",
        lambda **_: "请先检查数组边界。",
    )
    payload = {
        "assignment_id": assignment_id,
        "code": "int main(){return 0;}",
        "question": "数组边界怎么检查？",
    }
    first = client.post("/api/ask_question", json=payload)
    assert first.status_code == 200

    # The API has a separate ten-second student cooldown. Clear only that
    # session value so this test reaches the RAG limiter on the second call.
    with client.session_transaction() as session:
        session.pop("last_ai_question_time", None)

    second = client.post("/api/ask_question", json=payload)

    assert second.status_code == 200
    retrieval = second.json["data"]["knowledge_retrieval"]
    assert retrieval["status"] == "rate_limited"
    assert retrieval["fallback"]["code"] == "KNOWLEDGE_RETRIEVAL_RATE_LIMITED"
    assert second.json["data"]["answer"].startswith("请先检查数组边界。")
    assert "知识证据请求过于频繁" in second.json["data"]["answer"]


def test_retriever_timeout_stays_on_answer_only_path(knowledge_context, monkeypatch):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        from models import AssignmentKnowledgePoint

        AssignmentKnowledgePoint.add_to_assignment(assignment_id, "array")

        class TimeoutIndex:
            def __init__(self, *_args, **_kwargs):
                raise KnowledgeRetrievalTimeout("test timeout")

        monkeypatch.setattr(
            "services.knowledge_rag.VersionedKnowledgeIndex",
            TimeoutIndex,
        )
        retrieval = retrieve_assignment_knowledge(
            assignment_id,
            query="数组",
            request_key="test-timeout",
        )

    assert retrieval["status"] == "timeout"
    assert retrieval["fallback"]["code"] == "KNOWLEDGE_RETRIEVAL_TIMEOUT"
    assert retrieval["metrics"]["retrieval_timeout_fallback"] is True
    assert "仅基于题目和代码" in retrieval["fallback"]["message"]


def test_ask_question_timeout_returns_answer_only_response(knowledge_context, monkeypatch):
    app, client, assignment_id = knowledge_context
    with app.app_context():
        from models import AssignmentKnowledgePoint

        AssignmentKnowledgePoint.add_to_assignment(assignment_id, "array")

    class TimeoutIndex:
        def __init__(self, *_args, **_kwargs):
            raise KnowledgeRetrievalTimeout("test timeout")

    monkeypatch.setattr(
        "services.knowledge_rag.VersionedKnowledgeIndex",
        TimeoutIndex,
    )
    monkeypatch.setattr(
        api_routes,
        "generate_answer_to_question",
        lambda **_: "先检查数组边界。",
    )
    response = client.post(
        "/api/ask_question",
        json={
            "assignment_id": assignment_id,
            "code": "int main(){return 0;}",
            "question": "数组边界怎么检查？",
        },
    )

    assert response.status_code == 200
    retrieval = response.json["data"]["knowledge_retrieval"]
    assert retrieval["status"] == "timeout"
    assert retrieval["fallback"]["code"] == "KNOWLEDGE_RETRIEVAL_TIMEOUT"
    assert response.json["data"]["answer"].startswith("先检查数组边界。")
    assert "知识证据检索超时" in response.json["data"]["answer"]


def test_retriever_privacy_filter_is_applied_before_citation(knowledge_context):
    app, _, assignment_id = knowledge_context
    with app.app_context():
        from models import AssignmentKnowledgePoint

        AssignmentKnowledgePoint.add_to_assignment(assignment_id, "联系alice@example.com")
        retrieval = retrieve_assignment_knowledge(
            assignment_id,
            query="联系",
            request_key="test-privacy",
        )

    assert retrieval["status"] == "grounded"
    assert retrieval["metrics"]["privacy_filtered_count"] == 1
    rendered = " ".join(
        f"{item['title']} {item['content']}" for item in retrieval["evidence"]
    )
    assert "alice@example.com" not in rendered
    assert "[已过滤]" in rendered
