from services.knowledge_pipeline import (
    KnowledgeDocument,
    LexicalCandidateRetriever,
    OfflineKnowledgePipeline,
    ParagraphChunker,
    StableCitationBuilder,
    StablePriorityReranker,
    TokenCountEmbedder,
)


def test_offline_pipeline_prefers_query_match_before_source_priority():
    documents = [
        KnowledgeDocument(
            document_id="pointer-guide",
            title="指针基础",
            content="Pointer lifetime must be checked before dereferencing.",
            source_type="offline-sample",
            priority=10,
        ),
        KnowledgeDocument(
            document_id="array-guide",
            title="数组边界",
            content="Check the array boundary before reading the next element.",
            source_type="offline-sample",
            priority=1,
        ),
    ]

    citations = OfflineKnowledgePipeline().search(
        "array boundary",
        documents,
        limit=2,
    )

    assert [citation.evidence_id for citation in citations] == [
        "array-guide#chunk-0",
        "pointer-guide#chunk-0",
    ]
    assert [citation.citation for citation in citations] == ["[K1]", "[K2]"]


def test_offline_pipeline_chunks_and_citations_are_deterministic():
    pipeline = OfflineKnowledgePipeline(chunker=ParagraphChunker(max_chars=18))
    document = KnowledgeDocument(
        document_id="sample",
        title="离线样本",
        content="First boundary. Second boundary. Third boundary.",
        source_type="offline-sample",
    )

    first = pipeline.search("boundary", [document], limit=2)
    second = pipeline.search("boundary", [document], limit=2)

    assert first == second
    assert [citation.evidence_id for citation in first] == [
        "sample#chunk-0",
        "sample#chunk-1",
    ]
    assert all(citation.citation.startswith("[K") for citation in first)


def test_candidate_retriever_keeps_late_match_before_small_limit():
    documents = [
        KnowledgeDocument("early", "无关", "unrelated material", "offline-sample"),
        KnowledgeDocument("late", "目标", "the target evidence", "offline-sample"),
    ]
    chunker = ParagraphChunker()
    embedder = TokenCountEmbedder()
    chunks = tuple(chunk for document in documents for chunk in chunker.split(document))
    embeddings = {chunk.chunk_id: embedder.embed(chunk.text) for chunk in chunks}

    candidates = LexicalCandidateRetriever().retrieve(
        embedder.embed("target"),
        chunks,
        embeddings,
        limit=1,
    )

    assert len(candidates) == 1
    assert candidates[0].chunk.document_id == "late"


class ReverseReranker:
    def rerank(self, query_embedding, candidates):
        return tuple(reversed(candidates))


def test_pipeline_stages_can_be_replaced_without_changing_contract():
    pipeline = OfflineKnowledgePipeline(
        embedder=TokenCountEmbedder(),
        reranker=ReverseReranker(),
        citation_builder=StableCitationBuilder(),
    )
    documents = [
        KnowledgeDocument("a", "A", "alpha", "offline-sample"),
        KnowledgeDocument("b", "B", "beta", "offline-sample"),
    ]

    citations = pipeline.search("alpha", documents, limit=2)

    assert [citation.evidence_id for citation in citations] == [
        "b#chunk-0",
        "a#chunk-0",
    ]
