"""多数据源知识库、混合检索和有上限的会话记忆。

检索采用两个互补通道：

1. BM25 词法检索负责故障码、服务名、命令和精确术语；
2. BGE 中文稠密向量负责语义相近但措辞不同的问题；
3. 倒数排名融合（Reciprocal Rank Fusion, RRF）只融合名次，不直接相加
   两种量纲不同的原始分数。

上传文档与多个官方 Statuspage 事故都会进入同一套可追踪分块。用户上传文档
的提取文本写入 SQLite；公开事故按需重新拉取，不重复保存原始副本。
"""

from __future__ import annotations

import math
import os
import re
import secrets
import sqlite3
import hashlib
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock

from fastembed import TextEmbedding
from pypdf import PdfReader

from .models import (
    ChatMessage,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeStatus,
    Scenario,
)


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARACTERS = 250_000
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}
DENSE_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DENSE_MIN_SCORE = float(os.getenv("ONCALL_DENSE_MIN_SCORE", "0.36"))
RRF_RANK_CONSTANT = 60
RETRIEVAL_CANDIDATES = 20


@dataclass(frozen=True)
class _Chunk:
    chunk_id: str
    document_id: str
    document_name: str
    source_type: str
    source_url: str | None
    text: str
    tokens: Counter[str]
    embedding: tuple[float, ...] | None


@dataclass(frozen=True)
class MemoryContext:
    """送入模型的有界上下文；摘要用于连续性，不作为事实证据。"""

    summary: str
    recent_messages: list[ChatMessage]
    total_turns: int
    summarized_message_count: int
    clipped: bool


@dataclass
class _SessionState:
    summary: str
    messages: list[ChatMessage]
    total_turns: int = 0
    summarized_message_count: int = 0


def _tokenize(text: str) -> Counter[str]:
    """同时提取拉丁词、中文连续片段和中文二元组。"""
    normalized = text.lower()
    tokens: list[str] = re.findall(r"[a-z0-9_./:-]{2,}", normalized)
    for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.extend(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return Counter(tokens)


def _split_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """按自然边界分块，并保留少量重叠以减少跨块信息损失。"""
    cleaned = re.sub(r"[ \t]+", " ", text.replace("\x00", ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(cleaned):
        end = min(cursor + size, len(cleaned))
        if end < len(cleaned):
            boundary = max(
                cleaned.rfind("\n", cursor + size // 2, end),
                cleaned.rfind("。", cursor + size // 2, end),
            )
            if boundary > cursor:
                end = boundary + 1
        chunks.append(cleaned[cursor:end].strip())
        if end >= len(cleaned):
            break
        cursor = max(cursor + 1, end - overlap)
    return [item for item in chunks if item]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本文件必须使用 UTF-8 或 GB18030 编码")


def extract_document_text(filename: str, data: bytes) -> tuple[str, str, str]:
    """提取受支持文档的文本，不执行文档中的任何内容。"""
    safe_name = Path(filename or "document").name[:180]
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 PDF、Markdown 和 TXT 文档")
    if not data:
        raise ValueError("上传的文档为空")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("单个文档不能超过 5 MB")
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("暂不支持加密 PDF")
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("无法从该 PDF 中提取文本") from exc
        media_type = "application/pdf"
    else:
        text = _decode_text(data)
        media_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
    text = text.strip()
    if not text:
        raise ValueError("文档中没有可提取的文本")
    if len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("提取后的文本不能超过 250,000 个字符")
    return safe_name, text, media_type


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _scenario_text(scenario: Scenario) -> str:
    """把公开事故转换为保留来源和时间线的可检索文本。"""
    timeline = "\n".join(
        f"- {signal.timestamp.isoformat() if signal.timestamp else '时间未知'}｜{signal.name}｜{signal.value}"
        for signal in scenario.request.signals
    )
    components = "、".join(scenario.components) or scenario.request.service
    return (
        f"事故标题：{scenario.title}\n"
        f"事故中文标题：{scenario.display_title or scenario.title}\n"
        f"中文摘要：{scenario.display_summary or '暂无'}\n"
        f"事故状态：{scenario.incident_status}\n"
        f"影响级别：{scenario.impact}\n"
        f"涉及组件：{components}\n"
        f"事故摘要：{scenario.request.description}\n"
        f"数据来源：{scenario.source_name}\n"
        f"原始链接：{scenario.source_url}\n"
        f"公开时间线：\n{timeline}"
    )


class KnowledgeBaseStore:
    """线程安全知识库：上传文本写入 SQLite，索引在进程内重建。"""

    def __init__(self, max_documents: int = 20, data_dir: str | Path | None = None) -> None:
        self.max_documents = max(1, max_documents)
        self._documents: OrderedDict[str, KnowledgeDocument] = OrderedDict()
        self._chunks: dict[str, list[_Chunk]] = {}
        self._uploaded_ids: OrderedDict[str, None] = OrderedDict()
        self._public_ids: set[str] = set()
        self._public_signature: tuple[tuple[str, str], ...] = ()
        self._lock = Lock()
        self._model_lock = Lock()
        self._embedding_model: TextEmbedding | None = None
        self._embedding_attempted = False
        self._embedding_error: str | None = None
        self._database_path: Path | None = None
        self._persistence_error: str | None = None
        if data_dir is not None:
            self._initialize_persistence(Path(data_dir))

    def _connect(self) -> sqlite3.Connection:
        if self._database_path is None:
            raise RuntimeError("SQLite 持久化未启用")
        connection = sqlite3.connect(str(self._database_path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_persistence(self, data_dir: Path) -> None:
        """初始化数据库；磁盘不可写时降级到内存而不阻断服务。"""
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._database_path = data_dir / "knowledge.db"
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS uploaded_documents (
                        document_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        text_content TEXT NOT NULL,
                        character_count INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                rows = connection.execute(
                    "SELECT * FROM uploaded_documents ORDER BY created_at ASC"
                ).fetchall()
            for row in rows[-self.max_documents :]:
                self._restore_upload(row)
        except Exception as exc:
            self._persistence_error = str(exc)[:240]
            self._database_path = None

    def _restore_upload(self, row: sqlite3.Row) -> None:
        document_id = row["document_id"]
        text = row["text_content"]
        chunks = self._build_chunks(
            document_id=document_id,
            document_name=row["name"],
            text=text,
            source_type="用户上传",
            source_url=None,
            prefix=f"K-{document_id[4:]}",
        )
        document = KnowledgeDocument(
            document_id=document_id,
            name=row["name"],
            media_type=row["media_type"],
            source_type="用户上传",
            character_count=row["character_count"],
            chunk_count=len(chunks),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        self._documents[document_id] = document
        self._chunks[document_id] = chunks
        self._uploaded_ids[document_id] = None

    def _persist_upload(self, document: KnowledgeDocument, text: str) -> None:
        if self._database_path is None:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO uploaded_documents
                    (document_id, name, media_type, text_content, character_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.document_id,
                        document.name,
                        document.media_type,
                        text,
                        document.character_count,
                        document.created_at.isoformat(),
                    ),
                )
        except Exception as exc:
            self._persistence_error = str(exc)[:240]

    def _delete_persisted(self, document_id: str) -> None:
        if self._database_path is None:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM uploaded_documents WHERE document_id = ?", (document_id,)
                )
        except Exception as exc:
            self._persistence_error = str(exc)[:240]

    def _get_embedding_model(self) -> TextEmbedding | None:
        """延迟加载模型；失败时明确降级到 BM25，不影响应用启动。"""
        if self._embedding_attempted:
            return self._embedding_model
        with self._model_lock:
            if self._embedding_attempted:
                return self._embedding_model
            self._embedding_attempted = True
            try:
                cache_dir = os.getenv("FASTEMBED_CACHE_PATH", "").strip()
                options = {"cache_dir": cache_dir} if cache_dir else {}
                self._embedding_model = TextEmbedding(model_name=DENSE_MODEL_NAME, **options)
            except Exception as exc:  # 模型不可用时保留词法检索服务。
                self._embedding_error = str(exc)[:240]
                self._embedding_model = None
            return self._embedding_model

    def _passage_embeddings(self, texts: list[str]) -> list[tuple[float, ...] | None]:
        model = self._get_embedding_model()
        if model is None or not texts:
            return [None] * len(texts)
        try:
            return [tuple(float(value) for value in vector) for vector in model.passage_embed(texts)]
        except Exception as exc:
            self._embedding_error = str(exc)[:240]
            return [None] * len(texts)

    def _query_embedding(self, text: str) -> tuple[float, ...] | None:
        model = self._get_embedding_model()
        if model is None:
            return None
        try:
            vector = next(iter(model.query_embed([text])))
            return tuple(float(value) for value in vector)
        except Exception as exc:
            self._embedding_error = str(exc)[:240]
            return None

    def _build_chunks(
        self,
        *,
        document_id: str,
        document_name: str,
        text: str,
        source_type: str,
        source_url: str | None,
        prefix: str,
    ) -> list[_Chunk]:
        raw_chunks = _split_text(text)
        embeddings = self._passage_embeddings(raw_chunks)
        return [
            _Chunk(
                chunk_id=f"{prefix}-{index:03d}",
                document_id=document_id,
                document_name=document_name,
                source_type=source_type,
                source_url=source_url,
                text=value,
                tokens=_tokenize(value),
                embedding=embeddings[index - 1],
            )
            for index, value in enumerate(raw_chunks, start=1)
        ]

    def add(self, filename: str, data: bytes) -> KnowledgeDocument:
        safe_name, text, media_type = extract_document_text(filename, data)
        document_id = f"DOC-{secrets.token_hex(4).upper()}"
        chunks = self._build_chunks(
            document_id=document_id,
            document_name=safe_name,
            text=text,
            source_type="用户上传",
            source_url=None,
            prefix=f"K-{document_id[4:]}",
        )
        document = KnowledgeDocument(
            document_id=document_id,
            name=safe_name,
            media_type=media_type,
            source_type="用户上传",
            character_count=len(text),
            chunk_count=len(chunks),
            created_at=datetime.now(timezone.utc),
        )
        self._persist_upload(document, text)
        with self._lock:
            self._documents[document_id] = document
            self._chunks[document_id] = chunks
            self._uploaded_ids[document_id] = None
            while len(self._uploaded_ids) > self.max_documents:
                removed_id, _ = self._uploaded_ids.popitem(last=False)
                self._documents.pop(removed_id, None)
                self._chunks.pop(removed_id, None)
                self._delete_persisted(removed_id)
        return document.model_copy(deep=True)

    def sync_scenarios(self, scenarios: list[Scenario]) -> None:
        """以幂等方式同步多个官方状态页事故，不重复累积公开记录。"""
        signature = tuple(
            (item.source_incident_id, item.fetched_at.isoformat()) for item in scenarios
        )
        with self._lock:
            if signature == self._public_signature:
                return
        prepared: list[tuple[KnowledgeDocument, list[_Chunk]]] = []
        for scenario in scenarios:
            stable_id = hashlib.sha1(scenario.key.encode("utf-8")).hexdigest()[:16].upper()
            document_id = f"STATUS-{stable_id}"
            text = _scenario_text(scenario)
            name = f"{scenario.source_name}｜{scenario.title}"
            chunks = self._build_chunks(
                document_id=document_id,
                document_name=name,
                text=text,
                source_type=f"{scenario.source_name} 真实事故",
                source_url=scenario.source_url,
                prefix=f"S-{stable_id}",
            )
            prepared.append(
                (
                    KnowledgeDocument(
                        document_id=document_id,
                        name=name,
                        media_type="application/vnd.statuspage+json",
                        source_type=f"{scenario.source_name} 真实事故",
                        source_url=scenario.source_url,
                        character_count=len(text),
                        chunk_count=len(chunks),
                        created_at=scenario.fetched_at,
                    ),
                    chunks,
                )
            )
        with self._lock:
            for document_id in self._public_ids:
                self._documents.pop(document_id, None)
                self._chunks.pop(document_id, None)
            self._public_ids = set()
            for document, chunks in prepared:
                self._documents[document.document_id] = document
                self._chunks[document.document_id] = chunks
                self._public_ids.add(document.document_id)
            self._public_signature = signature

    def list(self) -> list[KnowledgeDocument]:
        with self._lock:
            return [item.model_copy(deep=True) for item in reversed(self._documents.values())]

    def status(self) -> KnowledgeStatus:
        with self._lock:
            documents = list(self._documents.values())
            chunk_count = sum(len(items) for items in self._chunks.values())
            upload_count = len(self._uploaded_ids)
            source_count = len(self._public_ids)
        dense_ready = self._embedding_model is not None
        if dense_ready:
            retriever = "BM25 + BGE 中文向量 + RRF"
            mode = "混合检索 RAG"
        elif self._embedding_attempted:
            retriever = "BM25（向量通道已降级）"
            mode = "词法检索降级"
        else:
            retriever = "BM25 + BGE 中文向量（准备中）"
            mode = "混合检索准备中"
        return KnowledgeStatus(
            document_count=len(documents),
            uploaded_document_count=upload_count,
            source_document_count=source_count,
            chunk_count=chunk_count,
            supported_types=["PDF", "Markdown", "TXT", "官方 Statuspage JSON"],
            retriever=retriever,
            storage=self.storage_label,
            embedding_model=DENSE_MODEL_NAME if dense_ready else None,
            retrieval_mode=mode,
            source_types=sorted({item.source_type for item in documents}),
        )

    @property
    def storage_label(self) -> str:
        if self._database_path is None:
            return "进程内存（SQLite 不可用）"
        if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
            return "Railway Volume + SQLite（跨部署持久化）"
        return "本地 SQLite（Railway 重部署后可能清空）"

    def _bm25_ranking(self, query_tokens: Counter[str], chunks: list[_Chunk]) -> list[_Chunk]:
        if not query_tokens or not chunks:
            return []
        document_frequency = Counter()
        for chunk in chunks:
            document_frequency.update(set(chunk.tokens))
        average_length = sum(sum(chunk.tokens.values()) for chunk in chunks) / len(chunks)
        scored: list[tuple[float, _Chunk]] = []
        for chunk in chunks:
            length = max(1, sum(chunk.tokens.values()))
            score = 0.0
            for token, query_weight in query_tokens.items():
                frequency = chunk.tokens.get(token, 0)
                if not frequency:
                    continue
                inverse_frequency = math.log(
                    1 + (len(chunks) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5)
                )
                denominator = frequency + 1.5 * (0.25 + 0.75 * length / max(1.0, average_length))
                score += query_weight * inverse_frequency * (frequency * 2.5 / denominator)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:RETRIEVAL_CANDIDATES]]

    def _dense_ranking(self, query: str, chunks: list[_Chunk]) -> list[_Chunk]:
        query_embedding = self._query_embedding(query)
        if query_embedding is None:
            return []
        scored = [
            (_cosine_similarity(query_embedding, chunk.embedding), chunk)
            for chunk in chunks
            if chunk.embedding is not None
        ]
        scored = [item for item in scored if item[0] >= DENSE_MIN_SCORE]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:RETRIEVAL_CANDIDATES]]

    def search(self, query: str, top_k: int = 4) -> list[KnowledgeCitation]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        with self._lock:
            chunks = [chunk for items in self._chunks.values() for chunk in items]
        if not chunks:
            return []

        # 两路召回的分数不在同一量纲，因此只用排名进行 RRF 融合。
        ranked_lists = [
            ("BM25 词法", self._bm25_ranking(query_tokens, chunks)),
            ("BGE 中文向量", self._dense_ranking(query, chunks)),
        ]
        fused_scores: dict[str, float] = {}
        candidates: dict[str, _Chunk] = {}
        signals: dict[str, list[str]] = {}
        for label, ranking in ranked_lists:
            for rank, chunk in enumerate(ranking, start=1):
                fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + 1 / (
                    RRF_RANK_CONSTANT + rank
                )
                candidates[chunk.chunk_id] = chunk
                signals.setdefault(chunk.chunk_id, []).append(label)
        ordered_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
        maximum = fused_scores[ordered_ids[0]] if ordered_ids else 1.0
        return [
            KnowledgeCitation(
                citation_id=candidates[chunk_id].chunk_id,
                document_id=candidates[chunk_id].document_id,
                document_name=candidates[chunk_id].document_name,
                source_type=candidates[chunk_id].source_type,
                source_url=candidates[chunk_id].source_url,
                retrieval_signals=signals[chunk_id],
                excerpt=candidates[chunk_id].text[:700],
                relevance=min(1.0, fused_scores[chunk_id] / maximum),
            )
            for chunk_id in ordered_ids[:top_k]
        ]


class SessionMemoryStore:
    """滚动摘要 + 近期原文 + 硬字符预算的分层会话记忆。"""

    def __init__(
        self,
        max_sessions: int = 100,
        recent_messages: int = 8,
        summary_max_chars: int = 2400,
        context_max_chars: int = 12_000,
    ) -> None:
        self.max_sessions = max(1, max_sessions)
        self.recent_messages = max(2, recent_messages)
        self.summary_max_chars = max(400, summary_max_chars)
        self.context_max_chars = max(self.summary_max_chars + 1000, context_max_chars)
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _compact_message(message: ChatMessage, limit: int = 360) -> str:
        text = re.sub(r"\s+", " ", message.content).strip()
        if len(text) > limit:
            text = f"{text[: limit - 1]}…"
        label = "用户" if message.role == "user" else "助手"
        return f"{label}：{text}"

    def _merge_summary(self, existing: str, messages: list[ChatMessage]) -> str:
        lines = [line for line in existing.splitlines() if line.strip()]
        lines.extend(self._compact_message(message) for message in messages)
        while lines and len("\n".join(lines)) > self.summary_max_chars:
            lines.pop(0)
        return "\n".join(lines)

    def context(self, session_id: str) -> MemoryContext:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return MemoryContext("", [], 0, 0, False)
            remaining = max(0, self.context_max_chars - len(state.summary))
            selected: list[ChatMessage] = []
            used = 0
            clipped = False
            for message in reversed(state.messages):
                if used + len(message.content) > remaining:
                    clipped = True
                    break
                selected.append(message.model_copy(deep=True))
                used += len(message.content)
            selected.reverse()
            return MemoryContext(
                summary=state.summary,
                recent_messages=selected,
                total_turns=state.total_turns,
                summarized_message_count=state.summarized_message_count,
                clipped=clipped,
            )

    def history(self, session_id: str) -> list[ChatMessage]:
        return self.context(session_id).recent_messages

    def append_exchange(self, session_id: str, question: str, answer: str) -> MemoryContext:
        with self._lock:
            state = self._sessions.setdefault(session_id, _SessionState(summary="", messages=[]))
            state.messages.extend(
                [ChatMessage(role="user", content=question), ChatMessage(role="assistant", content=answer)]
            )
            state.total_turns += 1
            overflow_count = max(0, len(state.messages) - self.recent_messages)
            if overflow_count:
                overflow = state.messages[:overflow_count]
                state.summary = self._merge_summary(state.summary, overflow)
                state.summarized_message_count += len(overflow)
                del state.messages[:overflow_count]
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        return self.context(session_id)

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
