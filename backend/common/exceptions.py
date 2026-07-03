"""Domain-specific exceptions for BOQ_AI services.

Services must raise meaningful errors and never fail silently
(docs/AGENTS.md - Error Handling).
"""


class BOQAIError(Exception):
    """Base class for all BOQ_AI domain errors."""


class ValidationError(BOQAIError):
    """Raised when uploaded data fails structural validation."""


class ImportError_(BOQAIError):
    """Raised when a database import fails."""


class ProcessingError(BOQAIError):
    """Raised when BOQ processing fails."""


class AIServiceError(BOQAIError):
    """Raised when an AI provider call fails."""


class ExportError(BOQAIError):
    """Raised when export generation fails."""
