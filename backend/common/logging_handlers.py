"""File logging helpers that maintain bounded FIFO line queues across processes."""
from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
import time

MAX_LOG_LINES = 5000


def trim_log_file(filepath: str | Path, max_lines: int = MAX_LOG_LINES) -> bool:
    """Trim a log file in-place to retain only the most recent `max_lines` lines.

    Uses `r+` truncate mode to avoid Windows file sharing / rename locks when
    concurrent processes (web server and Celery worker) have the log file open.
    """
    path = Path(filepath)
    if not path.is_file():
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=max_lines + 1)
        if len(lines) <= max_lines:
            return False
        keep_lines = list(lines)[-max_lines:]
        with open(path, "r+", encoding="utf-8", errors="replace") as f:
            f.seek(0)
            f.writelines(keep_lines)
            f.truncate()
        return True
    except Exception:
        return False


class SkipBrokenPipeFilter(logging.Filter):
    """Drop Django runserver 'Broken pipe' INFO noise from cancelled browser requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        return "Broken pipe" not in message


class SafeRotatingFileHandler(logging.FileHandler):
    """
    Queue-based rotating file handler that retains only the recent `max_lines` lines.

    Maintains a FIFO queue of log lines (default 5,000) directly in each log file,
    eliminating accumulating backup files (.log.1, etc.) and preventing Windows
    multi-process file locking issues during rollover.
    """

    def __init__(
        self,
        filename: str,
        mode: str = "a",
        encoding: str | None = "utf-8",
        delay: bool = False,
        errors: str | None = None,
        max_lines: int = MAX_LOG_LINES,
        check_interval: int = 50,
        maxBytes: int = 0,
        backupCount: int = 0,
    ):
        super().__init__(filename, mode=mode, encoding=encoding, delay=delay, errors=errors)
        self.max_lines = max_lines if max_lines else MAX_LOG_LINES
        self.check_interval = check_interval if check_interval else 50
        self._emit_count = 0
        self._last_trim_time = 0.0
        try:
            trim_log_file(self.baseFilename, max_lines=self.max_lines)
        except Exception:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self._emit_count += 1
        if self._emit_count >= self.check_interval:
            self._emit_count = 0
            now = time.monotonic()
            if now - self._last_trim_time >= 5.0:
                self._last_trim_time = now
                try:
                    self.flush()
                    trim_log_file(self.baseFilename, max_lines=self.max_lines)
                except Exception:
                    pass

    def doRollover(self) -> None:
        """Trim file in-place if rollover is explicitly requested."""
        try:
            self.flush()
            trim_log_file(self.baseFilename, max_lines=self.max_lines)
        except Exception:
            pass

    def shouldRollover(self, record: logging.LogRecord) -> int:
        return 0
