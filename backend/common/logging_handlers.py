"""File logging helpers that tolerate multi-process Windows locks."""
from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    RotatingFileHandler that skips rename when another process holds the file.

    Django runserver + Celery both write ``logs/application.log``. On Windows,
    rollover ``os.rename`` fails with WinError 32 and floods the console with
    ``--- Logging error ---`` while status polls continue. Swallow that and retry
    later instead of raising from every emit.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rollover_blocked_until = 0.0
        self._rollover_backoff_seconds = 60.0

    def doRollover(self) -> None:
        now = time.monotonic()
        if now < self._rollover_blocked_until:
            return
        try:
            super().doRollover()
        except PermissionError:
            self._rollover_blocked_until = now + self._rollover_backoff_seconds
            return
        except OSError as exc:
            # WinError 32 = sharing violation; 5 = access denied.
            if getattr(exc, "winerror", None) in {32, 5} or getattr(exc, "errno", None) in {
                13,
                16,
            }:
                self._rollover_blocked_until = now + self._rollover_backoff_seconds
                return
            raise
        else:
            self._rollover_blocked_until = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if time.monotonic() < self._rollover_blocked_until:
            return 0
        return super().shouldRollover(record)
