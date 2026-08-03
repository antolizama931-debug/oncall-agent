from app.knowledge import KnowledgeBaseStore


def test_dense_channel_recalls_semantically_related_chinese_question():
    """措辞没有明显重叠时，BGE 中文向量仍应召回相关运行手册。"""
    store = KnowledgeBaseStore(max_documents=2)
    store.add(
        "payment-runbook.md",
        "支付网关发生异常时，优先检查数据库连接池是否耗尽，并核对最近发布记录。".encode("utf-8"),
    )

    results = store.search("付款接口不可用时应该先排查哪类资源瓶颈？", top_k=2)

    assert results
    assert results[0].document_name == "payment-runbook.md"
    assert "BGE 中文向量" in results[0].retrieval_signals


def test_status_reports_truthful_hybrid_retrieval_components():
    store = KnowledgeBaseStore(max_documents=2)
    store.add("guide.txt", "服务故障处理指南".encode("utf-8"))

    status = store.status()

    assert status.retrieval_mode == "混合检索 RAG"
    assert status.embedding_model == "BAAI/bge-small-zh-v1.5"
    assert "RRF" in status.retriever
