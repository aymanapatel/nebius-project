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

