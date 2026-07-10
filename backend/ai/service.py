"""AI service.

Single entry point for OpenAI-backed text understanding. Prompts live in
ai/prompts/ and are formatted with caller-supplied context; business rules are
never hardcoded here (docs/AGENTS.md - OpenAI Rules). AI is used only for
understanding/extraction/validation, never pricing or supplier selection
(docs/AGENTS.md - AI Rules).

The service degrades gracefully: when no real API key is configured it reports
``is_enabled() == False`` so callers can skip AI work instead of failing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from common.exceptions import AIServiceError

from .openai_client import get_client, is_configured, load_prompt

logger = logging.getLogger("boq_ai")
instruction_logger = logging.getLogger("boq_ai.ai_instructions")


def render_prompt(template: str, **context) -> str:
    """Render a prompt without interpreting braces inside JSON context values."""
    prompt = template
    for key, value in context.items():
        prompt = prompt.replace(f"{{{key}}}", str(value))
    return prompt


class AIService:
    """Thin wrapper over the OpenAI Chat Completions API."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_MODEL

    @staticmethod
    def is_enabled() -> bool:
        return is_configured()

    @staticmethod
    def _supports_custom_temperature(model: str) -> bool:
        model_name = model.lower()
        default_temperature_only_prefixes = ("gpt-5", "o1", "o3", "o4")
        return not model_name.startswith(default_temperature_only_prefixes)

    def complete(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        template_name: str = "",
    ) -> str:
        """Send a single-prompt chat completion and return the raw content."""
        if not self.is_enabled():
            raise AIServiceError("AI is disabled: configure OPENAI_API_KEY.")

        client = get_client()
        self._log_instruction(prompt, json_mode=json_mode, template_name=template_name)
        kwargs: dict[str, Any] = {
            "model": str(self.model),
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._supports_custom_temperature(str(self.model)):
            kwargs["temperature"] = 0
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""  # type: ignore[attr-defined]
            self._log_usage(response, template_name=template_name)
            logger.info(
                "AI completion ok (model=%s, chars=%s)", self.model, len(content)
            )
            return content
        except AIServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            logger.exception("AI completion failed")
            raise AIServiceError(f"AI request failed: {exc}") from exc

    def run_prompt(self, template_name: str, **context) -> str:
        """Load a prompt template, format it with context, and run it."""
        template = load_prompt(template_name)
        prompt = render_prompt(template, **context)
        return self.complete(prompt, template_name=template_name)

    def run_json_prompt(self, template_name: str, **context) -> dict:
        """Run a prompt expecting a JSON object response and parse it."""
        template = load_prompt(template_name)
        prompt = render_prompt(template, **context)

        raw = self.complete(prompt, json_mode=True, template_name=template_name)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIServiceError(f"AI returned invalid JSON: {exc}") from exc

    def _log_instruction(
        self, prompt: str, *, json_mode: bool, template_name: str
    ) -> None:
        """Log the full runtime instruction sent to the AI provider."""
        database_context = ""
        if "Database context:\n" in prompt:
            _, _, database_context = prompt.partition("Database context:\n")
            database_context = database_context.split("\n\n", 1)[0]
        payload = {
            "event": "ai_runtime_instruction",
            "model": str(self.model),
            "template_name": template_name,
            "json_mode": json_mode,
            "database_context": database_context.strip() or None,
            "instruction_text": prompt,
        }
        instruction_logger.info(json.dumps(payload, ensure_ascii=False, default=str))

    def _log_usage(self, response, *, template_name: str) -> None:
        """Log provider token usage, including cached prompt tokens when present."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_details = self._usage_value(usage, "prompt_tokens_details") or {}
        payload = {
            "event": "ai_token_usage",
            "model": str(self.model),
            "template_name": template_name,
            "prompt_tokens": self._usage_value(usage, "prompt_tokens"),
            "completion_tokens": self._usage_value(usage, "completion_tokens"),
            "total_tokens": self._usage_value(usage, "total_tokens"),
            "cached_tokens": self._usage_value(prompt_details, "cached_tokens"),
        }
        instruction_logger.info(json.dumps(payload, ensure_ascii=False, default=str))

    @staticmethod
    def _usage_value(usage, key: str):
        if isinstance(usage, dict):
            return usage.get(key)
        return getattr(usage, key, None)
