"""FastAPI entry point for the public OnCall Agent demo."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .deepseek import DeepSeekClient, DeepSeekError
from .engine import analyze_incident
from .models import (
    AgentRun,
    AgentRunRequest,
    ApprovalRequest,
    ChatMessage,
    DashboardSummary,
    IncidentAnalysis,
    IncidentRequest,
    KnowledgeChatRequest,
    KnowledgeChatResponse,
    KnowledgeDocument,
    KnowledgeStatus,
    Scenario,
)
from .runtime import AgentRunStore
from .knowledge import KnowledgeBaseStore, MAX_FILE_BYTES, SessionMemoryStore
from .statuspage import GitHubStatusClient


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
load_dotenv(BASE_DIR / ".env")

RATE_LIMIT = int(os.getenv("ONCALL_RATE_LIMIT_PER_MINUTE", "5"))
DAILY_LIMIT = int(os.getenv("ONCALL_DAILY_LIMIT", "30"))
WINDOW_SECONDS = 60
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "2200"))
ALLOW_RULE_FALLBACK = os.getenv("ONCALL_ALLOW_RULE_FALLBACK", "true").lower() == "true"
STATUS_CACHE_SECONDS = int(os.getenv("ONCALL_STATUS_CACHE_SECONDS", "300"))
STATUS_SCENARIO_LIMIT = int(os.getenv("ONCALL_STATUS_SCENARIO_LIMIT", "6"))

deepseek_client = (
    DeepSeekClient(
        api_key=DEEPSEEK_API_KEY,
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        max_tokens=DEEPSEEK_MAX_TOKENS,
    )
    if DEEPSEEK_API_KEY
    else None
)
status_client = GitHubStatusClient(
    cache_seconds=STATUS_CACHE_SECONDS,
    scenario_limit=STATUS_SCENARIO_LIMIT,
)
run_store = AgentRunStore(max_runs=int(os.getenv("ONCALL_MAX_RUNS", "100")))
knowledge_store = KnowledgeBaseStore(max_documents=int(os.getenv("ONCALL_MAX_DOCUMENTS", "20")))
memory_store = SessionMemoryStore(
    max_sessions=int(os.getenv("ONCALL_MAX_SESSIONS", "100")),
    max_messages=int(os.getenv("ONCALL_MAX_SESSION_MESSAGES", "16")),
)

app = FastAPI(
    title="OnCall Agent API",
    version="0.2.0",
    description="Evidence-grounded OnCall Agent runtime with real incident replays and approval gates.",
)

# Same-origin deployment does not need CORS. Localhost origins are allowed only for
# separate frontend development servers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https://[a-zA-Z0-9-]+\.github\.io",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

request_windows: dict[str, deque[float]] = defaultdict(deque)
daily_usage: dict[str, tuple[str, int]] = {}


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    now = time.monotonic()
    if request.url.path in {"/api/analyze", "/api/runs", "/api/chat", "/api/knowledge/documents"}:
        client = request.client.host if request.client else "unknown"
        window = request_windows[client]
        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again in one minute."},
            )
        current_day = datetime.now(timezone.utc).date().isoformat()
        stored_day, count = daily_usage.get(client, (current_day, 0))
        if stored_day != current_day:
            count = 0
        if count >= DAILY_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Daily public-demo limit exceeded. Try again tomorrow."},
            )
        window.append(now)
        daily_usage[client] = (current_day, count + 1)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/api/health")
def health() -> dict[str, str | bool | int]:
    return {
        "status": "ok",
        "deepseek_configured": deepseek_client is not None,
        "model": DEEPSEEK_MODEL,
        "fallback_enabled": ALLOW_RULE_FALLBACK,
        "incident_source": "GitHub Status",
        "incident_data_mode": status_client.last_mode,
        "run_store": "process-local",
        "run_count": run_store.count(),
        "knowledge_document_count": knowledge_store.status().document_count,
        "memory_session_count": memory_store.count(),
    }


@app.get("/api/scenarios", response_model=list[Scenario])
async def list_scenarios() -> list[Scenario]:
    return await status_client.get_scenarios()


@app.get("/api/scenarios/{key}", response_model=Scenario)
async def get_scenario(key: str) -> Scenario:
    scenarios = await status_client.get_scenarios()
    scenario = next((item for item in scenarios if item.key == key), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return scenario


async def _analyze_payload(payload: IncidentRequest) -> IncidentAnalysis:
    """Use the configured model, with an explicit deterministic fallback."""
    if deepseek_client is not None:
        try:
            return await deepseek_client.analyze(payload)
        except DeepSeekError as exc:
            if not ALLOW_RULE_FALLBACK:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="DeepSeek analysis is temporarily unavailable.",
                ) from exc
            result = analyze_incident(payload)
            result.analysis_mode = "deterministic-fallback"
            result.model = DEEPSEEK_MODEL
            result.limitations.append(
                "DeepSeek was temporarily unavailable; deterministic fallback analysis was used."
            )
            return result

    result = analyze_incident(payload)
    result.analysis_mode = "deterministic-unconfigured"
    result.limitations.append(
        "DEEPSEEK_API_KEY is not configured; deterministic analysis was used."
    )
    return result


@app.post("/api/analyze", response_model=IncidentAnalysis)
async def analyze(payload: IncidentRequest) -> IncidentAnalysis:
    return await _analyze_payload(payload)


@app.get("/api/dashboard", response_model=DashboardSummary)
async def dashboard() -> DashboardSummary:
    scenarios = await status_client.get_scenarios()
    return DashboardSummary(
        incident_count=len(scenarios),
        unresolved_count=sum(item.incident_status not in {"resolved", "postmortem"} for item in scenarios),
        run_count=run_store.count(),
        awaiting_approval_count=run_store.awaiting_count(),
        source_name="GitHub Status",
        data_mode=status_client.last_mode,
        deepseek_configured=deepseek_client is not None,
        model=DEEPSEEK_MODEL,
    )


@app.post("/api/runs", response_model=AgentRun, status_code=status.HTTP_201_CREATED)
async def create_run(payload: AgentRunRequest) -> AgentRun:
    scenario: Scenario | None = None
    incident = payload.incident
    if payload.scenario_key is not None:
        scenarios = await status_client.get_scenarios()
        scenario = next((item for item in scenarios if item.key == payload.scenario_key), None)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Unknown scenario")
        incident = scenario.request
    if incident is None:  # Defensive; Pydantic already enforces this invariant.
        raise HTTPException(status_code=422, detail="Incident input is required")
    analysis = await _analyze_payload(incident)
    return run_store.create(
        request=incident,
        analysis=analysis,
        session_id=payload.session_id,
        scenario=scenario,
    )


@app.get("/api/runs", response_model=list[AgentRun])
def list_runs(session_id: str | None = None) -> list[AgentRun]:
    return run_store.list(session_id=session_id)


@app.get("/api/runs/{run_id}", response_model=AgentRun)
def get_run(run_id: str) -> AgentRun:
    run = run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    return run


@app.post("/api/runs/{run_id}/decision", response_model=AgentRun)
def decide_run(run_id: str, payload: ApprovalRequest) -> AgentRun:
    try:
        run = run_store.decide(run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    return run


@app.get("/api/knowledge/status", response_model=KnowledgeStatus)
def knowledge_status() -> KnowledgeStatus:
    return knowledge_store.status()


@app.get("/api/knowledge/documents", response_model=list[KnowledgeDocument])
def list_knowledge_documents() -> list[KnowledgeDocument]:
    return knowledge_store.list()


@app.post("/api/knowledge/documents", response_model=KnowledgeDocument, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(file: UploadFile = File(...)) -> KnowledgeDocument:
    """Extract a bounded PDF/Markdown/TXT upload into process-local chunks."""
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
    finally:
        await file.close()
    try:
        return knowledge_store.add(file.filename or "document", data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}", response_model=list[ChatMessage])
def session_history(session_id: str) -> list[ChatMessage]:
    return memory_store.history(session_id)


@app.delete("/api/sessions/{session_id}")
def clear_session(session_id: str) -> dict[str, bool]:
    return {"cleared": memory_store.clear(session_id)}


@app.post("/api/chat", response_model=KnowledgeChatResponse)
async def knowledge_chat(payload: KnowledgeChatRequest) -> KnowledgeChatResponse:
    citations = knowledge_store.search(payload.question, top_k=payload.top_k)
    history = memory_store.history(payload.session_id)
    trace = [
        "intent.classify: knowledge-question",
        f"retriever.search: {len(citations)} relevant chunks",
        f"memory.load: {len(history)} previous messages",
    ]
    usage = None
    if deepseek_client is not None:
        try:
            answer, usage = await deepseek_client.answer_question(
                question=payload.question,
                citations=citations,
                history=history,
            )
            analysis_mode = "deepseek-rag" if citations else "deepseek-general"
            trace.append("llm.answer: DeepSeek response validated")
        except DeepSeekError:
            if not ALLOW_RULE_FALLBACK:
                raise HTTPException(status_code=502, detail="DeepSeek answer is temporarily unavailable")
            answer = _knowledge_fallback(citations)
            analysis_mode = "retrieval-fallback"
            trace.append("llm.answer: deterministic fallback used")
    else:
        answer = _knowledge_fallback(citations)
        analysis_mode = "retrieval-unconfigured"
        trace.append("llm.answer: model is not configured")
    messages = memory_store.append_exchange(payload.session_id, payload.question, answer)
    trace.append("memory.save: exchange stored in bounded process memory")
    return KnowledgeChatResponse(
        answer=answer,
        session_id=payload.session_id,
        citations=citations,
        trace=trace,
        analysis_mode=analysis_mode,
        model=DEEPSEEK_MODEL if deepseek_client is not None else None,
        usage=usage,
        memory_turns=len(messages) // 2,
    )


def _knowledge_fallback(citations):
    if not citations:
        return "知识库中暂无可用于回答该问题的内容。请先上传 PDF、Markdown 或 TXT 文档。"
    excerpts = "\n\n".join(
        f"[{item.citation_id}] {item.document_name}: {item.excerpt[:320]}"
        for item in citations[:3]
    )
    return f"模型当前不可用。以下是检索到的原文片段，请据此核对：\n\n{excerpts}"


if not FRONTEND_DIR.is_dir():
    raise RuntimeError(f"Frontend directory not found: {FRONTEND_DIR}")

# Mount last so explicit API routes take precedence.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
