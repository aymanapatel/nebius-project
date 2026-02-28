from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    api_key: str
    base_url: str
    model: str
    site_url: str = ""
    app_name: str = ""


class ProjectSummaryLLM:
    def __init__(self, model: str | None = None, provider: str | None = None) -> None:
        settings = self._resolve_provider_settings(model=model, provider=provider)
        self._provider = settings.provider
        self._model = settings.model
        self._base_url = settings.base_url

        headers: dict[str, str] = {}
        if settings.site_url:
            headers["HTTP-Referer"] = settings.site_url
        if settings.app_name:
            headers["X-Title"] = settings.app_name

        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            default_headers=headers or None,
        )

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def summarize(self, context: str) -> dict[str, Any]:
        system_prompt = (
            "You are an expert software architect. Analyze the following code signatures "
            "from a mixed-language repository. Identify the project's purpose, main components, "
            'and how they interact. Return strict JSON with keys: summary, technologies, structure. '
            "The technologies field must be an array of strings."
        )
        user_prompt = f"Repository skeletons:\n\n{context}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            "Calling LLM API provider=%s model=%s base_url=%s context_chars=%d",
            self._provider,
            self._model,
            self._base_url,
            len(context),
        )
        logger.debug("Prepared LLM payload messages=%d", len(messages))

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception:
            # Some OpenAI-compatible providers do not support response_format.
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    temperature=0.1,
                    messages=messages,
                )
            except Exception as exc:
                raise LLMError(f"Failed to call LLM provider: {exc}") from exc

        if not response.choices:
            raise LLMError("LLM returned no choices")

        content = self._extract_content(response.choices[0].message.content)
        if not content:
            raise LLMError("LLM returned an empty response")

        try:
            payload = json.loads(self._strip_code_fences(content))
        except json.JSONDecodeError as exc:
            raise LLMError("LLM returned non-JSON output") from exc

        logger.debug("Decoded LLM JSON payload keys=%s", sorted(payload.keys()))
        return {
            "summary": str(payload.get("summary", "")).strip(),
            "technologies": self._normalize_technologies(payload.get("technologies")),
            "structure": str(payload.get("structure", "")).strip(),
        }

    @staticmethod
    def _resolve_provider_settings(model: str | None, provider: str | None) -> ProviderSettings:
        selected_provider = (provider or os.getenv("API_PROVIDER", "nebius")).strip().lower()

        if selected_provider == "nebius":
            api_key = (
                os.getenv("NEBIUS_API_KEY", "").strip()
                or os.getenv("LLM_API_KEY", "").strip()
            )
            if not api_key:
                raise LLMError("NEBIUS_API_KEY is not set")
            raw_base_url = (
                os.getenv("NEBIUS_API_BASE_URL", "").strip()
                or "https://api.tokenfactory.eu-west1.nebius.com/v1/"
            )
            return ProviderSettings(
                provider="nebius",
                api_key=api_key,
                base_url=ProjectSummaryLLM._normalize_base_url(raw_base_url),
                model=(
                    model
                    or os.getenv("NEBIUS_MODEL", "").strip()
                    or os.getenv("HELIUM_MODEL", "openai/gpt-4o-mini")
                ).strip(),
                site_url=os.getenv("NEBIUS_SITE_URL", "").strip(),
                app_name=os.getenv("NEBIUS_APP_NAME", "").strip()
            )

        if selected_provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
            if not api_key:
                raise LLMError("OPENROUTER_API_KEY is not set")
            raw_base_url = (
                os.getenv("OPENROUTER_API_BASE_URL", "").strip()
                or os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1").strip()
            )
            return ProviderSettings(
                provider="openrouter",
                api_key=api_key,
                base_url=ProjectSummaryLLM._normalize_base_url(raw_base_url),
                model=(model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")).strip(),
                site_url=os.getenv("OPENROUTER_SITE_URL", "").strip(),
                app_name=os.getenv("OPENROUTER_APP_NAME", "repo-summarizer").strip(),
            )

        if selected_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            raw_base_url = (
                os.getenv("OPENAI_API_BASE_URL", "").strip()
                or os.getenv("OPENAI_API_URL", "https://api.openai.com/v1").strip()
            )
            return ProviderSettings(
                provider="openai",
                api_key=api_key,
                base_url=ProjectSummaryLLM._normalize_base_url(raw_base_url),
                model=(model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")).strip(),
            )

        raise LLMError("Unsupported API_PROVIDER. Supported values: openrouter, openai, nebius")

    @staticmethod
    def _normalize_base_url(raw_url: str) -> str:
        url = raw_url.strip().rstrip("/")
        suffix = "/chat/completions"
        if url.endswith(suffix):
            url = url[: -len(suffix)]
        return url

    @staticmethod
    def _normalize_technologies(raw_value: Any) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if raw_value is None:
            return []
        value = str(raw_value).strip()
        if not value:
            return []
        return [part.strip() for part in value.split(",") if part.strip()]

    @staticmethod
    def _extract_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif hasattr(item, "type") and getattr(item, "type") == "text":
                    parts.append(str(getattr(item, "text", "")))
            return "".join(parts)
        return ""

    @staticmethod
    def _strip_code_fences(value: str) -> str:
        text = value.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return text
