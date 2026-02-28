from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from repo_summarizer.models import DEFAULT_LLM_PROVIDERS

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
        context = self._sanitize_context(context)
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
            response = self._call_with_retry(
                model=self._model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=messages,
                max_tokens=1024,
            )
        except LLMError:
            raise
        except Exception:
            # Some OpenAI-compatible providers do not support response_format.
            try:
                response = self._call_with_retry(
                    model=self._model,
                    temperature=0.1,
                    messages=messages,
                    max_tokens=1024,
                )
            except LLMError:
                raise
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

    _MAX_RETRIES: int = 3
    _INITIAL_BACKOFF: float = 1.0

    def _call_with_retry(self, **kwargs: Any) -> Any:
        """Call the completions API with exponential backoff on 429 rate-limit errors."""
        backoff = self._INITIAL_BACKOFF
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                is_rate_limit = status == 429 or "rate" in str(exc).lower()
                if is_rate_limit and attempt < self._MAX_RETRIES:
                    sleep_time = backoff + random.uniform(0, 0.5)
                    logger.warning(
                        "Rate limited by LLM provider, retrying attempt=%d/%d sleep=%.1fs",
                        attempt,
                        self._MAX_RETRIES,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                    backoff *= 2
                else:
                    raise
        raise LLMError("Exceeded maximum retries due to rate limiting")  # pragma: no cover

    # Patterns that could attempt to override the system prompt.
    _INJECTION_RE = re.compile(
        r"ignore (previous|all|above) instructions"
        r"|you are now"
        r"|forget everything"
        r"|disregard"
        r"|new personality",
        re.IGNORECASE,
    )

    def _sanitize_context(self, context: str) -> str:
        """Redact lines containing prompt-injection patterns."""
        lines = context.splitlines()
        sanitized: list[str] = []
        redacted = 0
        for line in lines:
            if self._INJECTION_RE.search(line):
                sanitized.append("[redacted]")
                redacted += 1
            else:
                sanitized.append(line)
        if redacted:
            logger.warning(
                "Sanitized %d potential prompt-injection line(s) from context", redacted
            )
        return "\n".join(sanitized)

    @staticmethod
    def _resolve_provider_settings(model: str | None, provider: str | None) -> ProviderSettings:
        selected_provider = "nebius"
        config = DEFAULT_LLM_PROVIDERS[selected_provider]

        # Resolve API key
        api_key = (
            os.getenv("NEBIUS_API_KEY", "").strip()
            or os.getenv("LLM_API_KEY", "").strip()
        )
        if not api_key:
            raise LLMError("NEBIUS_API_KEY is not set")

        # Resolve base URL
        raw_base_url = (
            os.getenv("NEBIUS_API_BASE_URL", "").strip()
            or os.getenv("NEBIUS_API_URL", "").strip()
            or config.default_base_url
        )

        # Resolve model from env or use default from config
        selected_model = (model or os.getenv("NEBIUS_MODEL", "").strip() or config.default_model).strip()

        # Resolve optional fields
        site_url = os.getenv(config.site_url_env or "", "").strip() if config.site_url_env else ""
        app_name = os.getenv(config.app_name_env or "", "").strip() if config.app_name_env else ""
        if not app_name and config.app_name_default:
            app_name = config.app_name_default

        return ProviderSettings(
            provider=selected_provider,
            api_key=api_key,
            base_url=ProjectSummaryLLM._normalize_base_url(raw_base_url),
            model=selected_model,
            site_url=site_url,
            app_name=app_name,
        )

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
