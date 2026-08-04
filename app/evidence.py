"""Shared evidence normalization and citation validation.

The evidence layer is deliberately small. It does not plan, retrieve, call an
LLM, or execute remediation. It only gives the knowledge, conversation, and
operations agents one provenance format and one validation policy.
"""

from __future__ import annotations

import hashlib
import re

from .models import Artifact, Evidence, Hypothesis, IncidentAnalysis, IncidentRequest, KnowledgeCitation


def _content_hash(source: str, statement: str) -> str:
    return hashlib.sha256(f"{source}\n{statement}".encode("utf-8")).hexdigest()[:16]


class SharedEvidenceLayer:
    """Normalize observations and reject references to unknown evidence."""

    def from_incident(self, request: IncidentRequest) -> list[Evidence]:
        source = "user_report"
        if request.source_name and request.source_incident_id:
            source = f"{request.source_name.lower().replace(' ', '_')}:{request.source_incident_id}"

        evidence: list[Evidence] = []

        def append(
            item_source: str,
            statement: str,
            relevance: float,
            *,
            observed_at=None,
            evidence_type: str,
            source_url: str | None = None,
            evidence_id: str | None = None,
            collected_by: str = "运维 Agent",
        ) -> None:
            resolved_id = evidence_id or f"E-{sum(item.evidence_id.startswith('E-') for item in evidence) + 1:03d}"
            evidence.append(
                Evidence(
                    evidence_id=resolved_id,
                    source=item_source,
                    statement=statement,
                    relevance=relevance,
                    observed_at=observed_at,
                    evidence_type=evidence_type,
                    source_url=source_url,
                    collected_by=collected_by,
                    content_hash=_content_hash(item_source, statement),
                )
            )

        append(
            source,
            request.description,
            0.72,
            evidence_type="incident-report",
            source_url=request.source_url,
        )
        if request.change_event:
            append("change_event", request.change_event, 0.84, evidence_type="change")
        for signal in request.signals:
            append(
                f"{signal.kind.value}:{signal.source}",
                f"{signal.name}: {signal.value}",
                0.78,
                observed_at=signal.timestamp,
                evidence_type=signal.kind.value,
            )
        for artifact in request.artifacts:
            if artifact.name.startswith("knowledge:"):
                citation_id = artifact.name.split(":", 1)[1]
                url_match = re.search(r"^来源：(https?://\S+)$", artifact.content, flags=re.MULTILINE)
                append(
                    artifact.name,
                    artifact.content,
                    0.74,
                    evidence_type="knowledge",
                    source_url=url_match.group(1) if url_match else None,
                    evidence_id=citation_id,
                    collected_by="知识库 Agent",
                )
            else:
                append(
                    f"artifact:{artifact.name}",
                    artifact.content,
                    0.74,
                    evidence_type="artifact",
                )
        return evidence

    def from_citations(self, citations: list[KnowledgeCitation]) -> list[Evidence]:
        return [
            Evidence(
                evidence_id=item.citation_id,
                source=f"knowledge:{item.document_name}",
                statement=item.excerpt,
                relevance=item.relevance,
                evidence_type="knowledge",
                source_url=item.source_url,
                collected_by="知识库 Agent",
                content_hash=_content_hash(item.document_name, item.excerpt),
            )
            for item in citations
        ]

    def attach_knowledge(
        self,
        request: IncidentRequest,
        citations: list[KnowledgeCitation],
        *,
        maximum: int = 3,
    ) -> IncidentRequest:
        """Attach bounded retrieved passages as untrusted incident artifacts."""

        available = max(0, 5 - len(request.artifacts))
        additions = [
            Artifact(
                name=f"knowledge:{item.citation_id}",
                content=(
                    f"资料：{item.document_name}\n"
                    f"来源：{item.source_url or '本地知识库'}\n"
                    f"内容：{item.excerpt}"
                )[:20_000],
                media_type="text/plain",
            )
            for item in citations[: min(maximum, available)]
        ]
        return request.model_copy(update={"artifacts": [*request.artifacts, *additions]})

    def validate_analysis(self, analysis: IncidentAnalysis) -> IncidentAnalysis:
        valid_ids = {item.evidence_id for item in analysis.evidence}
        fallback_id = analysis.evidence[0].evidence_id if analysis.evidence else None
        limitations = list(analysis.limitations)
        hypotheses: list[Hypothesis] = []
        for hypothesis in analysis.hypotheses:
            references = [item for item in hypothesis.supporting_evidence if item in valid_ids]
            if not references and fallback_id:
                references = [fallback_id]
                limitations.append(f"“{hypothesis.title}”缺少有效证据引用，已回退到事故报告。")
            hypotheses.append(hypothesis.model_copy(update={"supporting_evidence": references}))
        return analysis.model_copy(
            update={
                "hypotheses": hypotheses,
                "limitations": list(dict.fromkeys(limitations)),
            }
        )

    @staticmethod
    def answer_reference_status(answer: str, evidence: list[Evidence]) -> tuple[list[str], list[str]]:
        """Return valid and invalid citation IDs mentioned by an answer."""

        mentioned = set(re.findall(r"\[([A-Za-z0-9:_-]+)\]", answer))
        valid_ids = {item.evidence_id for item in evidence}
        return sorted(mentioned & valid_ids), sorted(mentioned - valid_ids)


shared_evidence_layer = SharedEvidenceLayer()
