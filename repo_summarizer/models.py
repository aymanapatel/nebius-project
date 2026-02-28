from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field


class SummarizeRequest(BaseModel):
    github_url: AnyHttpUrl


class SummaryResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str


class LanguageInfo(BaseModel):
    name: str
    extensions: list[str] = Field(default_factory=list)


class SupportedLanguagesResponse(BaseModel):
    languages: list[LanguageInfo] = Field(default_factory=list)


class LLMProviderConfig(BaseModel):
    """LLM Provider configuration with default models."""
    provider: str
    default_model: str
    default_base_url: str | None = None
    site_url_env: str | None = None
    app_name_env: str | None = None
    app_name_default: str | None = None


# Default LLM provider configurations with default models
DEFAULT_LLM_PROVIDERS = {
    "nebius": LLMProviderConfig(
        provider="nebius",
        default_model="Qwen/Qwen3-Coder-480B-A35B-Instruct",
        default_base_url="https://api.tokenfactory.nebius.com/v1/",
        site_url_env="NEBIUS_SITE_URL",
        app_name_env="NEBIUS_APP_NAME",
    ),
    "openrouter": LLMProviderConfig(
        provider="openrouter",
        default_model="openai/gpt-4o-mini",
        default_base_url="https://openrouter.ai/api/v1",
        site_url_env="OPENROUTER_SITE_URL",
        app_name_env="OPENROUTER_APP_NAME",
        app_name_default="repo-summarizer",
    ),
    "openai": LLMProviderConfig(
        provider="openai",
        default_model="gpt-4.1-mini",
        default_base_url="https://api.openai.com/v1",
    ),
}

