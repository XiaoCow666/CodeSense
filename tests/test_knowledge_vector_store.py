from services.knowledge_pipeline import KnowledgeDocument, ParagraphChunker
from services.knowledge_vector_store import HybridKnowledgeIndex


def _chunks(*documents):
    chunker = ParagraphChunker()
    return tuple(
        chunk
        for document in documents
        for chunk in chunker.split(document)
    )


def test_vector_index_writes_and_returns_deterministic_top_k():
    index = HybridKnowledgeIndex(
        _chunks(
            KnowledgeDocument(
                "pointer",
                "指针生命周期",
                "释放后不要解引用指针。",
                "offline-eval",
                priority=2,
            ),
            KnowledgeDocument(
                "array",
                "数组边界",
                "检查下标范围后再访问元素。",
                "offline-eval",
                priority=1,
            ),
        )
    )

    first = index.search("下标范围", top_k=1)
    second = index.search("下标范围", top_k=1)

    assert first == second
    assert first.mode == "vector"
    assert first.indexed_chunk_count == 2
    assert [item.chunk.document_id for item in first.candidates] == ["array"]


def test_keyword_fallback_can_search_a_title_not_present_in_body_vector():
    index = HybridKnowledgeIndex(
        _chunks(
            KnowledgeDocument(
                "array",
                "数组边界",
                "检查下标范围。",
                "offline-eval",
            )
        )
    )

    result = index.search("边界", top_k=1)

    assert result.mode == "keyword_fallback"
    assert [item.chunk.document_id for item in result.candidates] == ["array"]


def test_hybrid_index_keeps_unmatched_query_legacy_priority_fallback():
    index = HybridKnowledgeIndex(
        _chunks(
            KnowledgeDocument("low", "低优先级", "数组。", "offline-eval", priority=1),
            KnowledgeDocument("high", "高优先级", "指针。", "offline-eval", priority=2),
        )
    )

    result = index.search("数据库迁移", top_k=2)

    assert result.mode == "priority_fallback"
    assert [item.chunk.document_id for item in result.candidates] == ["high", "low"]


def test_hybrid_indexes_do_not_share_request_state():
    first = HybridKnowledgeIndex(
        _chunks(KnowledgeDocument("first", "第一份", "alpha", "offline-eval"))
    )
    second = HybridKnowledgeIndex(
        _chunks(KnowledgeDocument("second", "第二份", "beta", "offline-eval"))
    )

    assert [item.chunk.document_id for item in first.search("beta").candidates] == [
        "first"
    ]
    assert [item.chunk.document_id for item in second.search("beta").candidates] == [
        "second"
    ]
