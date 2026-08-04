"""Knowledge Agent: document preparation and evidence-producing retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from ..evidence import SharedEvidenceLayer
from ..knowledge import KnowledgeBaseStore
from ..models import Evidence, KnowledgeCitation, KnowledgeDocument, KnowledgeStatus, Scenario
from ..public_sources import PublicKnowledgeRecord


@dataclass(slots=True)
class KnowledgeAgentResult:
    citations: list[KnowledgeCitation]
    evidence: list[Evidence]
    trace: list[str]


class KnowledgeAgent:
    """Own the knowledge lifecycle instead of exposing the store as an Agent."""

    name = "知识库 Agent"

    def __init__(self, store: KnowledgeBaseStore, evidence_layer: SharedEvidenceLayer) -> None:
        self.store = store
        self.evidence_layer = evidence_layer

    def add_document(self, filename: str, data: bytes) -> KnowledgeDocument:
        return self.store.add(filename, data)

    def sync_scenarios(self, scenarios: list[Scenario]) -> None:
        self.store.sync_scenarios(scenarios)

    def sync_public_documents(self, records: list[PublicKnowledgeRecord]) -> None:
        self.store.sync_public_documents(records)

    def retrieve(self, query: str, *, top_k: int = 4) -> KnowledgeAgentResult:
        citations = self.store.search(query, top_k=top_k)
        evidence = self.evidence_layer.from_citations(citations)
        channels = sorted({signal for item in citations for signal in item.retrieval_signals})
        trace = [
            f"知识库 Agent：收到检索问题，最多返回 {top_k} 个片段",
            f"检索执行：召回 {len(citations)} 个片段",
            f"检索通道：{'、'.join(channels) if channels else '没有命中'}",
            f"证据转换：生成 {len(evidence)} 条可引用知识证据",
        ]
        return KnowledgeAgentResult(citations=citations, evidence=evidence, trace=trace)

    def status(self) -> KnowledgeStatus:
        return self.store.status()

    def documents(self) -> list[KnowledgeDocument]:
        return self.store.list()

