"""Conversation Agent: bounded RAG + ReAct question answering."""

from __future__ import annotations

import re

from ..deepseek import DeepSeekClient, DeepSeekError
from ..evidence import SharedEvidenceLayer
from ..knowledge import SessionMemoryStore
from ..models import KnowledgeChatRequest, KnowledgeChatResponse
from .knowledge import KnowledgeAgent, KnowledgeAgentResult


class ConversationAgent:
    """Run a visible, bounded Reason-Action-Observation loop.

    The trace contains decision summaries, not hidden chain-of-thought. The Agent
    can call only the registered knowledge tool and has at most two retrieval
    attempts, so a hostile document cannot make it execute arbitrary commands.
    """

    name = "对话 Agent"

    def __init__(
        self,
        *,
        knowledge_agent: KnowledgeAgent,
        memory_store: SessionMemoryStore,
        evidence_layer: SharedEvidenceLayer,
        deepseek_client: DeepSeekClient | None,
        model_name: str,
        allow_fallback: bool,
    ) -> None:
        self.knowledge_agent = knowledge_agent
        self.memory_store = memory_store
        self.evidence_layer = evidence_layer
        self.deepseek_client = deepseek_client
        self.model_name = model_name
        self.allow_fallback = allow_fallback

    @staticmethod
    def _broader_query(question: str) -> str:
        terms = re.findall(r"[\w.-]+", question.lower())
        return " ".join(dict.fromkeys(terms[:12]))

    @staticmethod
    def _fallback(result: KnowledgeAgentResult) -> str:
        if not result.citations:
            return "当前知识库没有召回足以回答该问题的内容。你可以换一种问法，或上传相关 PDF、Markdown、TXT 文档。"
        excerpts = "\n\n".join(
            f"[{item.citation_id}] {item.document_name}: {item.excerpt[:320]}"
            for item in result.citations[:3]
        )
        return f"模型当前不可用。以下是检索到的原文片段，请据此核对：\n\n{excerpts}"

    async def answer(self, payload: KnowledgeChatRequest) -> KnowledgeChatResponse:
        memory = self.memory_store.context(payload.session_id)
        trace = [
            "对话 Agent：开始受限 ReAct 循环",
            "Reason：该问题需要先查询项目知识库",
            "Action：调用 knowledge.retrieve",
        ]
        result = self.knowledge_agent.retrieve(payload.question, top_k=payload.top_k)
        trace.extend(result.trace)
        trace.append(f"Observation：获得 {len(result.evidence)} 条知识证据")

        # One bounded retry is the ReAct adjustment path. It does not let the
        # model invent a tool name or an arbitrary network target.
        broader_query = self._broader_query(payload.question)
        if not result.citations and broader_query and broader_query != payload.question.lower():
            trace.extend(
                [
                    "Reason：第一次检索没有命中，调整为关键词查询",
                    "Action：再次调用 knowledge.retrieve",
                ]
            )
            result = self.knowledge_agent.retrieve(broader_query, top_k=payload.top_k)
            trace.extend(result.trace)
            trace.append(f"Observation：第二次检索获得 {len(result.evidence)} 条知识证据")

        usage = None
        if self.deepseek_client is not None:
            try:
                answer, usage = await self.deepseek_client.answer_question(
                    question=payload.question,
                    citations=result.citations,
                    history=memory.recent_messages,
                    history_summary=memory.summary,
                )
                analysis_mode = "deepseek-react-rag" if result.citations else "deepseek-react"
                trace.append("Final：DeepSeek 已根据检索证据生成回答")
            except DeepSeekError:
                if not self.allow_fallback:
                    raise
                answer = self._fallback(result)
                analysis_mode = "retrieval-fallback"
                trace.append("Final：模型不可用，返回可核对的检索原文")
        else:
            answer = self._fallback(result)
            analysis_mode = "retrieval-unconfigured"
            trace.append("Final：模型未配置，返回可核对的检索原文")

        valid, invalid = self.evidence_layer.answer_reference_status(answer, result.evidence)
        for citation_id in invalid:
            answer = answer.replace(f"[{citation_id}]", "[无效引用已移除]")
        if invalid:
            trace.append(f"证据校验：移除了 {len(invalid)} 个未知引用")
        else:
            trace.append(f"证据校验：回答引用了 {len(valid)} 个有效证据 ID")

        updated = self.memory_store.append_exchange(payload.session_id, payload.question, answer)
        trace.append(
            "会话记忆：保留近期原文并压缩更早内容；记忆不能替代证据"
        )
        return KnowledgeChatResponse(
            answer=answer,
            session_id=payload.session_id,
            citations=result.citations,
            trace=trace,
            analysis_mode=analysis_mode,
            model=self.model_name if self.deepseek_client is not None else None,
            usage=usage,
            memory_turns=updated.total_turns,
            memory_summary_active=bool(updated.summary),
            memory_recent_messages=len(updated.recent_messages),
            memory_clipped=updated.clipped,
        )

