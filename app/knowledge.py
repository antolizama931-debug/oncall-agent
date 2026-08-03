"""Process-local knowledge base and bounded conversation memory.

The public demo intentionally keeps uploaded text in memory: documents disappear
when the service restarts and are never written to disk. Retrieval uses a small
BM25-style lexical index that works for both Chinese character n-grams and Latin
words without claiming to provide embedding search.
"""

from __future__ import annotations

import math
import re
import secrets
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock

from pypdf import PdfReader

from .models import ChatMessage, KnowledgeCitation, KnowledgeDocument, KnowledgeStatus


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARACTERS = 250_000
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}


@dataclass(frozen=True)
class _Chunk:
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    tokens: Counter[str]


def _tokenize(text: str) -> Counter[str]:
    normalized = text.lower()
    tokens: list[str] = re.findall(r"[a-z0-9_./:-]{2,}", normalized)
    for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.extend(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return Counter(tokens)


def _split_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"[ \t]+", " ", text.replace("\x00", ""))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(cleaned):
        end = min(cursor + size, len(cleaned))
        if end < len(cleaned):
            boundary = max(cleaned.rfind("\n", cursor + size // 2, end), cleaned.rfind("。", cursor + size // 2, end))
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
    raise ValueError("Text document must use UTF-8 or GB18030 encoding")


def extract_document_text(filename: str, data: bytes) -> tuple[str, str, str]:
    """Extract supported document text without executing embedded content."""
    safe_name = Path(filename or "document").name[:180]
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only PDF, Markdown, and plain-text documents are supported")
    if not data:
        raise ValueError("Uploaded document is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Document must not exceed 5 MB")
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF documents are not supported")
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Unable to extract text from this PDF") from exc
        media_type = "application/pdf"
    else:
        text = _decode_text(data)
        media_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
    text = text.strip()
    if not text:
        raise ValueError("Document contains no extractable text")
    if len(text) > MAX_TEXT_CHARACTERS:
        raise ValueError("Extracted document text must not exceed 250,000 characters")
    return safe_name, text, media_type


class KnowledgeBaseStore:
    def __init__(self, max_documents: int = 20) -> None:
        self.max_documents = max(1, max_documents)
        self._documents: OrderedDict[str, KnowledgeDocument] = OrderedDict()
        self._chunks: dict[str, list[_Chunk]] = {}
        self._lock = Lock()

    def add(self, filename: str, data: bytes) -> KnowledgeDocument:
        safe_name, text, media_type = extract_document_text(filename, data)
        raw_chunks = _split_text(text)
        document_id = f"DOC-{secrets.token_hex(4).upper()}"
        chunks = [
            _Chunk(
                chunk_id=f"K-{document_id[4:]}-{index:03d}",
                document_id=document_id,
                document_name=safe_name,
                text=value,
                tokens=_tokenize(value),
            )
            for index, value in enumerate(raw_chunks, start=1)
        ]
        document = KnowledgeDocument(
            document_id=document_id,
            name=safe_name,
            media_type=media_type,
            character_count=len(text),
            chunk_count=len(chunks),
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._documents[document_id] = document
            self._chunks[document_id] = chunks
            while len(self._documents) > self.max_documents:
                removed_id, _ = self._documents.popitem(last=False)
                self._chunks.pop(removed_id, None)
        return document.model_copy(deep=True)

    def list(self) -> list[KnowledgeDocument]:
        with self._lock:
            return [item.model_copy(deep=True) for item in reversed(self._documents.values())]

    def status(self) -> KnowledgeStatus:
        with self._lock:
            return KnowledgeStatus(
                document_count=len(self._documents),
                chunk_count=sum(len(items) for items in self._chunks.values()),
                supported_types=["PDF", "Markdown", "TXT"],
                retriever="BM25 lexical",
                storage="process-local",
            )

    def search(self, query: str, top_k: int = 4) -> list[KnowledgeCitation]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        with self._lock:
            chunks = [chunk for items in self._chunks.values() for chunk in items]
        if not chunks:
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
                inverse_frequency = math.log(1 + (len(chunks) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
                denominator = frequency + 1.5 * (0.25 + 0.75 * length / max(1.0, average_length))
                score += query_weight * inverse_frequency * (frequency * 2.5 / denominator)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        maximum = scored[0][0] if scored else 1.0
        return [
            KnowledgeCitation(
                citation_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                excerpt=chunk.text[:700],
                relevance=min(1.0, score / maximum),
            )
            for score, chunk in scored[:top_k]
        ]


class SessionMemoryStore:
    def __init__(self, max_sessions: int = 100, max_messages: int = 16) -> None:
        self.max_sessions = max(1, max_sessions)
        self.max_messages = max(2, max_messages)
        self._sessions: OrderedDict[str, list[ChatMessage]] = OrderedDict()
        self._lock = Lock()

    def history(self, session_id: str) -> list[ChatMessage]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._sessions.get(session_id, [])]

    def append_exchange(self, session_id: str, question: str, answer: str) -> list[ChatMessage]:
        with self._lock:
            messages = self._sessions.setdefault(session_id, [])
            messages.extend([ChatMessage(role="user", content=question), ChatMessage(role="assistant", content=answer)])
            del messages[:-self.max_messages]
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return [item.model_copy(deep=True) for item in messages]

    def clear(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
