from app.knowledge import KnowledgeBaseStore, SessionMemoryStore


def test_dense_channel_recalls_semantically_related_chinese_question():
    """措辞没有明显重叠时，多语言向量仍应召回相关运行手册。"""
    store = KnowledgeBaseStore(max_documents=2)
    store.add(
        "payment-runbook.md",
        "支付网关发生异常时，优先检查数据库连接池是否耗尽，并核对最近发布记录。".encode("utf-8"),
    )

    results = store.search("付款接口不可用时应该先排查哪类资源瓶颈？", top_k=2)

    assert results
    assert results[0].document_name == "payment-runbook.md"
    assert "多语言语义向量" in results[0].retrieval_signals


def test_status_reports_truthful_hybrid_retrieval_components():
    store = KnowledgeBaseStore(max_documents=2)
    store.add("guide.txt", "服务故障处理指南".encode("utf-8"))

    store.search("如何处理服务故障？")
    status = store.status()

    assert status.retrieval_mode == "混合检索 RAG"
    assert status.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert "RRF" in status.retriever


def test_uploaded_document_is_restored_from_sqlite(tmp_path):
    first = KnowledgeBaseStore(max_documents=2, data_dir=tmp_path)
    first.add("restart-guide.md", "节点重启前必须先排空流量并记录审批单。".encode("utf-8"))

    restored = KnowledgeBaseStore(max_documents=2, data_dir=tmp_path)

    assert restored.list()[0].name == "restart-guide.md"
    assert restored.search("重启节点前需要做什么？")[0].document_name == "restart-guide.md"
    assert "SQLite" in restored.status().storage


def test_session_memory_uses_summary_recent_window_and_character_budget():
    memory = SessionMemoryStore(
        max_sessions=2,
        recent_messages=4,
        summary_max_chars=500,
        context_max_chars=1500,
    )
    for index in range(5):
        memory.append_exchange("session-a", f"问题 {index}：如何排查？", f"回答 {index}：先核对证据。")

    context = memory.context("session-a")

    assert context.total_turns == 5
    assert context.summarized_message_count == 6
    assert len(context.recent_messages) == 4
    assert "用户：问题 0" in context.summary
    assert len(context.summary) + sum(len(item.content) for item in context.recent_messages) <= 1500
