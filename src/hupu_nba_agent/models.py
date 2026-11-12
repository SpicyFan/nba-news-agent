from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WorkflowMode(StrEnum):
    NEWS = "news"
    LONGFORM = "longform"


class EventType(StrEnum):
    BREAKING = "breaking"
    TRADE = "trade"
    SIGNING = "signing"
    INJURY = "injury"
    INTERVIEW = "interview"
    GAME_PREVIEW = "game_preview"
    GAME_RECAP = "game_recap"
    PERFORMANCE = "performance"
    LEAGUE_POLICY = "league_policy"
    OTHER = "other"


class GenerateRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120_000)
    mode: WorkflowMode = WorkflowMode.NEWS
    editor_note: str = Field(default="", max_length=3_000)
    use_web_search: bool | None = None


class SourceAnalysis(BaseModel):
    source_type: Literal["url", "x_post", "text", "unknown"] = "unknown"
    source_url: str = ""
    source_name: str = ""
    reporter: str = ""
    published_at: str = ""
    players: list[str] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)
    event_type: EventType = EventType.OTHER
    core_facts: list[str] = Field(default_factory=list)
    raw_title: str = ""
    extraction_notes: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    claim: str
    value: str
    as_of: str = ""
    source_name: str
    source_url: str


class AuditIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    suggestion: str = ""


class AuditReport(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    issues: list[AuditIssue] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class NewsDraft(BaseModel):
    title: str
    lead: str
    body_paragraphs: list[str] = Field(min_length=1)
    background_paragraphs: list[str] = Field(default_factory=list)
    source_name: str
    source_url: str
    tags: list[str] = Field(default_factory=list)
    image_keywords: list[str] = Field(default_factory=list)
    alternate_titles: list[str] = Field(default_factory=list)

    @property
    def paragraphs(self) -> list[str]:
        return [self.lead, *self.body_paragraphs, *self.background_paragraphs]

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.strip() for p in self.paragraphs if p.strip())

    @model_validator(mode="after")
    def longform_title_limit(self) -> NewsDraft:
        if len(self.alternate_titles) > 10:
            self.alternate_titles = self.alternate_titles[:10]
        return self


class NewsPackage(BaseModel):
    source_analysis: SourceAnalysis
    evidence: list[EvidenceItem] = Field(default_factory=list)
    draft: NewsDraft
    audit: AuditReport
    editorial_notes: list[str] = Field(default_factory=list)


class ToolTrace(BaseModel):
    round: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str = ""


class AgentResponse(BaseModel):
    result: NewsPackage
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    model: str
    response_id: str
    consulted_urls: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    model: str
    web_search: bool
