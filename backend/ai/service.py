"""OpenAI chat completion wrapper for BOQ analysis."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.conf import settings

from ai.openai_client import get_client, is_configured
from common.exceptions import AIServiceError

logger = logging.getLogger("boq_ai")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class AIService:
    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_MODEL

    @staticmethod
    def is_enabled() -> bool:
        return is_configured()

    @staticmethod
    def _supports_custom_temperature(model: str) -> bool:
        model_name = model.lower()
        return not model_name.startswith(("gpt-5", "o1", "o3", "o4"))

    def complete_json(
        self,
        prompt: str,
        *,
        template_name: str = "",
    ) -> dict[str, Any]:
        content = self.complete(prompt, json_mode=True, template_name=template_name)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIServiceError(f"AI returned invalid JSON: {exc}") from exc

    def complete(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        template_name: str = "",
    ) -> str:
        if not self.is_enabled():
            raise AIServiceError("OPENAI_API_KEY is not configured.")

        client = get_client()
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
            content = response.choices[0].message.content or ""
            logger.info(
                "AI completion ok (model=%s, template=%s, chars=%s)",
                self.model,
                template_name or "-",
                len(content),
            )
            return content
        except AIServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI completion failed")
            raise AIServiceError(f"AI request failed: {exc}") from exc

    @staticmethod
    def load_prompt(name: str) -> str:
        path = _PROMPTS_DIR / name
        if not path.is_file():
            raise AIServiceError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")
