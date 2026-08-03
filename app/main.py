"""FastAPI entry point for the public OnCall Agent demo."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .alerts import AlertInboxStore
from .connectors import EnterpriseToolGateway
from .deepseek import DeepSeekClient, DeepSeekError
from .engine import analyze_incident
from .models import (
    AgentRun,
    AgentRunRequest,
    AlertEventRequest,
    AlertReceipt,
    ApprovalRequest,
    ChatMessage,
    DashboardSummary,
    ExecutionRequest,
    IncidentAnalysis,
    IncidentRequest,
    KnowledgeChatRequest,
    KnowledgeChatResponse,
    KnowledgeDocument,
    KnowledgeReviewRequest,
    KnowledgeStatus,
    Scenario,
    Signal,
    SignalKind,
)
from .runtime import AgentRunStore
from .knowledge import KnowledgeBaseStore, MAX_FILE_BYTES, SessionMemoryStore
from .statuspage import MultiStatusClient


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
WEBHOOK_TOKEN = os.getenv("ONCALL_WEBHOOK_TOKEN", "").strip()
TOOL_GATEWAY_URL = os.getenv("ONCALL_TOOL_GATEWAY_URL", "").strip()
TOOL_GATEWAY_TOKEN = os.getenv("ONCALL_TOOL_GATEWAY_TOKEN", "").strip()
STATUS_CACHE_SECONDS = int(os.getenv("ONCALL_STATUS_CACHE_SECONDS", "300"))
STATUS_SCENARIO_LIMIT = int(os.getenv("ONCALL_STATUS_SCENARIO_LIMIT", "36"))
STATUS_PER_SOURCE_LIMIT = int(os.getenv("ONCALL_STATUS_PER_SOURCE_LIMIT", "12"))
DATA_DIR_VALUE = (
    os.getenv("ONCALL_DATA_DIR", "").strip()
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    or str(BASE_DIR / "data")
)
DATA_DIR = Path(DATA_DIR_VALUE)
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR

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
status_client = MultiStatusClient(
    cache_seconds=STATUS_CACHE_SECONDS,
    scenario_limit=STATUS_SCENARIO_LIMIT,
    per_source_limit=STATUS_PER_SOURCE_LIMIT,
)
run_store = AgentRunStore(
    max_runs=int(os.getenv("ONCALL_MAX_RUNS", "100")),
    data_dir=DATA_DIR,
)
alert_store = AlertInboxStore(data_dir=DATA_DIR)
tool_gateway = EnterpriseToolGateway(
    base_url=TOOL_GATEWAY_URL,
    token=TOOL_GATEWAY_TOKEN,
    timeout_seconds=float(os.getenv("ONCALL_TOOL_GATEWAY_TIMEOUT_SECONDS", "5")),
)
knowledge_store = KnowledgeBaseStore(
    max_documents=int(os.getenv("ONCALL_MAX_DOCUMENTS", "50")),
    data_dir=DATA_DIR,
)
memory_store = SessionMemoryStore(
    max_sessions=int(os.getenv("ONCALL_MAX_SESSIONS", "100")),
    recent_messages=int(os.getenv("ONCALL_MEMORY_RECENT_MESSAGES", "8")),
    summary_max_chars=int(os.getenv("ONCALL_MEMORY_SUMMARY_CHARS", "2400")),
    context_max_chars=int(os.getenv("ONCALL_CONTEXT_MAX_CHARS", "12000")),
)

app = FastAPI(
    title="OnCall Agent API",
    version="0.5.0",
    description="具备告警接入、诊断、Runbook 审批、处置演练、验证回滚与知识沉淀的 OnCall Agent。",
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
    if request.url.path in {
        "/api/analyze",
        "/api/runs",
        "/api/chat",
        "/api/knowledge/documents",
        "/api/integrations/alerts",
    }:
        client = request.client.host if request.client else "unknown"
        window = request_windows[client]
        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "请求过于频繁，请一分钟后重试。"},
            )
        current_day = datetime.now(timezone.utc).date().isoformat()
        stored_day, count = daily_usage.get(client, (current_day, 0))
        if stored_day != current_day:
            count = 0
        if count >= DAILY_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "今日公开演示额度已用完，请明天再试。"},
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
        "incident_source": "、".join(status_client.source_names),
        "incident_data_mode": status_client.last_mode,
        "run_store": "SQLite 持久化",
        "run_count": run_store.count(),
        "alert_count": len(alert_store.list()),
        "execution_mode": "dry-run",
        "webhook_configured": bool(WEBHOOK_TOKEN),
        "tool_gateway_configured": tool_gateway.configured,
        "knowledge_document_count": knowledge_store.status().document_count,
        "memory_session_count": memory_store.count(),
    }


@app.get("/api/scenarios", response_model=list[Scenario])
async def list_scenarios() -> list[Scenario]:
    return await _scenarios_with_knowledge()


async def _scenarios_with_knowledge() -> list[Scenario]:
    """获取真实事故并幂等同步到知识库的第二类数据源。"""
    scenarios = await status_client.get_scenarios()
    knowledge_store.sync_scenarios(scenarios)
    return scenarios


@app.get("/api/scenarios/{key}", response_model=Scenario)
async def get_scenario(key: str) -> Scenario:
    scenarios = await _scenarios_with_knowledge()
    scenario = next((item for item in scenarios if item.key == key), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail="未找到该事故")
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
    scenarios = await _scenarios_with_knowledge()
    return DashboardSummary(
        incident_count=len(scenarios),
        unresolved_count=sum(item.incident_status not in {"resolved", "postmortem"} for item in scenarios),
        run_count=run_store.count(),
        awaiting_approval_count=run_store.awaiting_count(),
        source_name="、".join(status_client.source_names),
        data_mode=status_client.last_mode,
        deepseek_configured=deepseek_client is not None,
        model=DEEPSEEK_MODEL,
        recovered_count=run_store.recovered_count(),
        rollback_count=run_store.rollback_count(),
        knowledge_candidate_count=run_store.knowledge_candidate_count(),
    )


@app.post("/api/runs", response_model=AgentRun, status_code=status.HTTP_201_CREATED)
async def create_run(payload: AgentRunRequest) -> AgentRun:
    scenario: Scenario | None = None
    incident = payload.incident
    if payload.scenario_key is not None:
        scenarios = await _scenarios_with_knowledge()
        scenario = next((item for item in scenarios if item.key == payload.scenario_key), None)
        if scenario is None:
            raise HTTPException(status_code=404, detail="未找到该事故")
        incident = scenario.request
    if incident is None:  # Defensive; Pydantic already enforces this invariant.
        raise HTTPException(status_code=422, detail="必须提供事故输入")
    investigation_tools = []
    if scenario is None:
        incident, investigation_tools = await tool_gateway.collect(incident)
    analysis = await _analyze_payload(incident)
    return run_store.create(
        request=incident,
        analysis=analysis,
        session_id=payload.session_id,
        scenario=scenario,
        investigation_tools=investigation_tools,
    )


@app.get("/api/runs", response_model=list[AgentRun])
def list_runs(session_id: str | None = None) -> list[AgentRun]:
    return run_store.list(session_id=session_id)


@app.get("/api/runs/{run_id}", response_model=AgentRun)
def get_run(run_id: str) -> AgentRun:
    run = run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该运行记录")
    return run


@app.post("/api/runs/{run_id}/decision", response_model=AgentRun)
def decide_run(run_id: str, payload: ApprovalRequest) -> AgentRun:
    try:
        run = run_store.decide(run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该运行记录")
    return run


@app.post("/api/runs/{run_id}/execute", response_model=AgentRun)
def execute_run(run_id: str, payload: ExecutionRequest) -> AgentRun:
    """Execute an approved run through the built-in non-production drill adapter."""
    try:
        run = run_store.execute(run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该运行记录")
    return run


@app.post("/api/runs/{run_id}/knowledge-review", response_model=AgentRun)
def review_run_knowledge(run_id: str, payload: KnowledgeReviewRequest) -> AgentRun:
    """Review a generated post-incident candidate before knowledge publication."""
    try:
        run = run_store.review_knowledge(run_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="未找到该运行记录")
    return run


@app.get("/api/alerts", response_model=list[AlertReceipt])
def list_alerts() -> list[AlertReceipt]:
    return alert_store.list()


@app.post("/api/integrations/alerts", response_model=AlertReceipt, status_code=status.HTTP_202_ACCEPTED)
async def ingest_enterprise_alert(
    payload: AlertEventRequest,
    x_oncall_token: str | None = Header(default=None, alias="X-OnCall-Token"),
) -> AlertReceipt:
    """Receive a trusted alert, deduplicate it, and start one investigation run.

    Production deployment must configure ``ONCALL_WEBHOOK_TOKEN``. Repeated
    notifications with the same fingerprint update the occurrence counter rather
    than starting duplicate investigations.
    """
    if not WEBHOOK_TOKEN:
        raise HTTPException(status_code=503, detail="企业告警 Webhook 尚未配置")
    if x_oncall_token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="告警 Webhook 凭据无效")

    receipt = alert_store.ingest(payload)
    if receipt.run_id or payload.status == "resolved":
        return receipt

    signals = list(payload.signals)
    signals.append(
        Signal(
            kind=SignalKind.ALERT,
            name="alert.title",
            value=payload.title,
            source=payload.source,
            display_name="监控系统告警",
            display_value=payload.title,
        )
    )
    incident = IncidentRequest(
        description=payload.description,
        service=payload.service,
        severity=payload.severity,
        environment=payload.environment,
        change_event=payload.change_event,
        signals=signals,
        source_name=payload.source,
        source_incident_id=receipt.event_id,
    )
    incident, investigation_tools = await tool_gateway.collect(incident)
    analysis = await _analyze_payload(incident)
    run = run_store.create(
        request=incident,
        analysis=analysis,
        session_id=f"alert:{receipt.fingerprint}",
        investigation_tools=investigation_tools,
    )
    alert_store.link_run(receipt.fingerprint, run.run_id)
    receipt.run_id = run.run_id
    return receipt


@app.get("/api/knowledge/status", response_model=KnowledgeStatus)
async def knowledge_status() -> KnowledgeStatus:
    await _scenarios_with_knowledge()
    return knowledge_store.status()


@app.get("/api/knowledge/documents", response_model=list[KnowledgeDocument])
async def list_knowledge_documents() -> list[KnowledgeDocument]:
    await _scenarios_with_knowledge()
    return knowledge_store.list()


@app.post("/api/knowledge/documents", response_model=KnowledgeDocument, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(file: UploadFile = File(...)) -> KnowledgeDocument:
    """提取文档文本，写入 SQLite，并在进程内建立混合检索索引。"""
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
    await _scenarios_with_knowledge()
    citations = knowledge_store.search(payload.question, top_k=payload.top_k)
    memory_context = memory_store.context(payload.session_id)
    status_snapshot = knowledge_store.status()
    trace = [
        "问题识别：知识库问答",
        f"数据源路由：{len(status_snapshot.source_types)} 类数据源",
        f"混合检索：召回 {len(citations)} 个相关分块",
        "RRF 融合：合并 BM25 与 BGE 中文向量排名",
        (
            "会话记忆：滚动摘要"
            f"（{memory_context.summarized_message_count} 条已压缩）+ "
            f"{len(memory_context.recent_messages)} 条近期原文"
        ),
        f"上下文预算：最多 {memory_store.context_max_chars:,} 个字符",
    ]
    usage = None
    if deepseek_client is not None:
        try:
            answer, usage = await deepseek_client.answer_question(
                question=payload.question,
                citations=citations,
                history=memory_context.recent_messages,
                history_summary=memory_context.summary,
            )
            analysis_mode = "deepseek-rag" if citations else "deepseek-general"
            trace.append("答案生成：DeepSeek 已返回响应")
        except DeepSeekError:
            if not ALLOW_RULE_FALLBACK:
                raise HTTPException(status_code=502, detail="DeepSeek answer is temporarily unavailable")
            answer = _knowledge_fallback(citations)
            analysis_mode = "retrieval-fallback"
            trace.append("答案生成：已使用确定性降级结果")
    else:
        answer = _knowledge_fallback(citations)
        analysis_mode = "retrieval-unconfigured"
        trace.append("答案生成：模型未配置，返回检索原文")
    updated_memory = memory_store.append_exchange(payload.session_id, payload.question, answer)
    trace.append("安全校验：答案仅保留可追踪知识片段")
    trace.append("会话写入：近期原文保存在进程内存，较早消息进入有界滚动摘要")
    return KnowledgeChatResponse(
        answer=answer,
        session_id=payload.session_id,
        citations=citations,
        trace=trace,
        analysis_mode=analysis_mode,
        model=DEEPSEEK_MODEL if deepseek_client is not None else None,
        usage=usage,
        memory_turns=updated_memory.total_turns,
        memory_summary_active=bool(updated_memory.summary),
        memory_recent_messages=len(updated_memory.recent_messages),
        memory_clipped=updated_memory.clipped,
    )


def _knowledge_fallback(citations):
    if not citations:
        return "当前知识库没有召回足以回答该问题的内容。你可以换一种问法，或上传相关 PDF、Markdown、TXT 文档。"
    excerpts = "\n\n".join(
        f"[{item.citation_id}] {item.document_name}: {item.excerpt[:320]}"
        for item in citations[:3]
    )
    return f"模型当前不可用。以下是检索到的原文片段，请据此核对：\n\n{excerpts}"


if not FRONTEND_DIR.is_dir():
    raise RuntimeError(f"Frontend directory not found: {FRONTEND_DIR}")

# Mount last so explicit API routes take precedence.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
