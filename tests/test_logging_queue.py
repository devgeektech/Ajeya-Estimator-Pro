"""Tests for log file bounded queue line retention (5,000 lines)."""
from pathlib import Path
import tempfile
import unittest

from common.logging_handlers import SafeRotatingFileHandler, trim_log_file


class LoggingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "test.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_trim_log_file_keeps_recent_lines(self):
        # Write 20 lines
        with open(self.log_file, "w", encoding="utf-8") as f:
            for i in range(20):
                f.write(f"Line {i}\n")

        # Trim to 10 lines
        trimmed = trim_log_file(self.log_file, max_lines=10)
        self.assertTrue(trimmed)

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f]

        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[0], "Line 10")
        self.assertEqual(lines[-1], "Line 19")

    def test_trim_log_file_noop_when_within_limit(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"Line {i}\n")

        trimmed = trim_log_file(self.log_file, max_lines=10)
        self.assertFalse(trimmed)

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f]

        self.assertEqual(len(lines), 5)

    def test_safe_rotating_file_handler_trims_on_init(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            for i in range(30):
                f.write(f"Pre-existing {i}\n")

        handler = SafeRotatingFileHandler(str(self.log_file), max_lines=15)
        handler.close()

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f]

        self.assertEqual(len(lines), 15)
        self.assertEqual(lines[0], "Pre-existing 15")
        self.assertEqual(lines[-1], "Pre-existing 29")
