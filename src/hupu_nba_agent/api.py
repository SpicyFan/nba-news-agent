from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from .agent import HupuNbaAgent
from .config import Settings
from .models import AgentResponse, GenerateRequest, HealthResponse
from .tools import ContentAuditor, SourceParser

app = FastAPI(
    title="虎扑 NBA 新闻 AI Agent",
    version="0.1.0",
    description="英文 NBA 新闻源到虎扑风格中文新闻稿的单 Agent MVP。",
)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_agent() -> HupuNbaAgent:
    return HupuNbaAgent(get_settings())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(model=settings.openai_model, web_search=settings.web_search)


@app.post("/v1/news/generate", response_model=AgentResponse)
def generate_news(request: GenerateRequest) -> AgentResponse:
    try:
        return get_agent().run(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - translate provider errors at API boundary
        raise HTTPException(
            status_code=502,
            detail=f"生成失败：{type(exc).__name__}: {exc}",
        ) from exc


@app.post("/v1/tools/parse-source")
def parse_source(payload: dict) -> dict:
    raw_input = str(payload.get("source", "")).strip()
    if not raw_input:
        raise HTTPException(status_code=422, detail="source 不能为空。")
    return SourceParser(timeout=get_settings().request_timeout).parse(raw_input)


@app.post("/v1/tools/audit")
def audit_draft(payload: dict) -> dict:
    return ContentAuditor().audit(
        payload.get("draft", {}),
        payload.get("evidence", []),
        str(payload.get("mode", "news")),
    )
