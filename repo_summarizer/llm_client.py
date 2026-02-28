from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class ProjectSummaryLLM:
    def __init__(self, model: str = "openai/gpt-4o-mini") -> None:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise LLMError("OPENROUTER_API_KEY is not set")

        self._model = model
        self._api_key = api_key
        self._endpoint = os.getenv(
            "OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions"
        )
        self._site_url = os.getenv("OPENROUTER_SITE_URL", "").strip()
        self._app_name = os.getenv("OPENROUTER_APP_NAME", "repo-summarizer").strip()

    def summarize(self, context: str) -> dict[str, Any]:
        system_prompt = (
            "You are an expert software architect. Analyze the following code signatures "
            "from a mixed-language repository. Identify the project's purpose, main components, "
            'and how they interact. Return strict JSON with keys: summary, technologies, structure. '
            "The technologies field must be an array of strings."
        )

        logger.info("Context sent to LLM", )
        user_prompt = f"Repository skeletons:\n\n{context}"

        request_payload = {
            "model": self._model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        logger.info(
            "Calling OpenRouter API model=%s endpoint=%s context_chars=%d and context=%s",
            self._model,
            self._endpoint,
            len(context),
            context
        )
        logger.debug("Prepared LLM payload messages=%d", len(request_payload["messages"]))

        command = [
            "curl",
            "-sS",
            "-X",
            "POST",
            self._endpoint,
            "-H",
            f"Authorization: Bearer {self._api_key}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(request_payload),
        ]
        if self._site_url:
            command.extend(["-H", f"HTTP-Referer: {self._site_url}"])
        if self._app_name:
            command.extend(["-H", f"X-Title: {self._app_name}"])
        logger.debug(
            "Executing OpenRouter request headers site_url_set=%s app_name=%s",
            bool(self._site_url),
            self._app_name,
        )

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise LLMError(f"Failed to call LLM: {exc}") from exc

        if result.returncode != 0:
            raise LLMError(f"OpenRouter request failed: {result.stderr.strip() or 'unknown error'}")
        logger.debug("OpenRouter HTTP call completed output_chars=%d", len(result.stdout))

        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError("OpenRouter returned non-JSON output") from exc

        if "error" in response:
            message = response["error"].get("message", "unknown OpenRouter error")
            raise LLMError(f"OpenRouter error: {message}")

        content = self._extract_content(response)
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
    def _extract_content(response: dict[str, Any]) -> str:
        choices = response.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            return "".join(text_parts)
        return ""

    @staticmethod
    def _strip_code_fences(value: str) -> str:
        text = value.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return text
