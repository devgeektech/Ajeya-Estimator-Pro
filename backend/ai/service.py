"""AI service.

Single entry point for OpenAI-backed text understanding. Prompts live in
ai/prompts/ and are formatted with caller-supplied context; business rules are
never hardcoded here (docs/AGENTS.md - OpenAI Rules). AI is used only for
understanding/extraction/validation, never pricing or vendor selection
(docs/AGENTS.md - AI Rules).

The service degrades gracefully: when no real API key is configured it reports
``is_enabled() == False`` so callers (e.g. the processing pipeline) can skip AI
work instead of failing.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from common.exceptions import AIServiceError

from .openai_client import get_client, is_configured, load_prompt

logger = logging.getLogger("boq_ai")


class AIService:
    """Thin wrapper over the OpenAI Chat Completions API."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_MODEL

    @staticmethod
    def is_enabled() -> bool:
        return is_configured()

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        """Send a single-prompt chat completion and return the raw content."""
        if not self.is_enabled():
            raise AIServiceError("AI is disabled: configure OPENAI_API_KEY.")

        client = get_client()
        kwargs: dict[str, Any] = {
            "model": str(self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""  # type: ignore[attr-defined]
            logger.info("AI completion ok (model=%s, chars=%s)", self.model, len(content))
            return content
        except AIServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            logger.exception("AI completion failed")
            raise AIServiceError(f"AI request failed: {exc}") from exc

    def run_prompt(self, template_name: str, **context) -> str:
        """Load a prompt template, format it with context, and run it."""
        template = load_prompt(template_name)
        try:
            prompt = template.format(**context)
        except KeyError as exc:
            raise AIServiceError(f"Missing prompt variable: {exc}") from exc
        return self.complete(prompt)

    def run_json_prompt(self, template_name: str, **context) -> dict:
        """Run a prompt expecting a JSON object response and parse it."""
        template = load_prompt(template_name)
        try:
            prompt = template.format(**context)
        except KeyError as exc:
            raise AIServiceError(f"Missing prompt variable: {exc}") from exc

        raw = self.complete(prompt, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIServiceError(f"AI returned invalid JSON: {exc}") from exc
