"""Custom password validators."""
from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class ComplexityPasswordValidator:
    """Validate password has minimum length and contains letters, numbers, and special symbols."""

    def __init__(self, min_length: int = 6) -> None:
        self.min_length = int(min_length)

    def validate(self, password: str, user: Any = None) -> None:
        errors: list[ValidationError] = []

        if len(password) < self.min_length:
            errors.append(
                ValidationError(
                    _(f"Password must be at least {self.min_length} characters long."),
                    code="password_too_short",
                )
            )
        if not re.search(r"[a-zA-Z]", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one letter (a-z, A-Z)."),
                    code="password_no_letter",
                )
            )
        if not re.search(r"\d", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one number (0-9)."),
                    code="password_no_number",
                )
            )
        if not re.search(r"[^a-zA-Z0-9\s]", password):
            errors.append(
                ValidationError(
                    _("Password must contain at least one special symbol (e.g. @, #, $, %, !)."),
                    code="password_no_symbol",
                )
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self) -> str:
        return _(
            f"Your password must be at least {self.min_length} characters long and "
            "contain letters, numbers, and special symbols (e.g. @, #, $)."
        )
