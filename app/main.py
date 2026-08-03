"""FastAPI entry point for the public OnCall Agent demo."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .deepseek import DeepSeekClient, DeepSeekError
from .engine import analyze_incident
from .fixtures import SCENARIOS
from .models import IncidentAnalysis, IncidentRequest, Scenario


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

app = FastAPI(
    title="OnCall Agent API",
    version="0.1.0",
    description="Evidence-grounded incident triage with auditable reasoning and safety gates.",
)

# Same-origin deployment does not need CORS. Localhost origins are allowed only for
# separate frontend development servers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

request_windows: dict[str, deque[float]] = defaultdict(deque)
daily_usage: dict[str, tuple[str, int]] = {}


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    now = time.monotonic()
    if request.url.path == "/api/analyze":
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
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "deepseek_configured": deepseek_client is not None,
        "model": DEEPSEEK_MODEL,
        "fallback_enabled": ALLOW_RULE_FALLBACK,
    }


@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios() -> list[Scenario]:
    return list(SCENARIOS.values())


@app.get("/api/scenarios/{key}", response_model=Scenario)
def get_scenario(key: str) -> Scenario:
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown scenario")
    return scenario


@app.post("/api/analyze", response_model=IncidentAnalysis)
async def analyze(payload: IncidentRequest) -> IncidentAnalysis:
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


if not FRONTEND_DIR.is_dir():
    raise RuntimeError(f"Frontend directory not found: {FRONTEND_DIR}")

# Mount last so explicit API routes take precedence.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
