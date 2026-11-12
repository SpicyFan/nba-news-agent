from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6-sol", alias="OPENAI_MODEL")
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = Field(
        default="medium",
        alias="OPENAI_REASONING_EFFORT",
    )
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    web_search: bool = Field(default=True, alias="NBA_AGENT_WEB_SEARCH")
    max_tool_rounds: int = Field(default=8, ge=1, le=20, alias="NBA_AGENT_MAX_TOOL_ROUNDS")
    request_timeout: float = Field(
        default=30.0,
        ge=3.0,
        le=120.0,
        alias="NBA_AGENT_REQUEST_TIMEOUT",
    )
    knowledge_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "knowledge"
    )

    def require_api_key(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "未配置 OPENAI_API_KEY。请复制 .env.example 为 .env 并填入 API Key。"
            )

