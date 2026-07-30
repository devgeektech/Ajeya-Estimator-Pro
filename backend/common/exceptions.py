"""Domain-specific exceptions for BOQ_AI services."""


class BOQAIError(Exception):
    """Base class for all BOQ_AI domain errors."""


class ValidationError(BOQAIError):
    """Raised when uploaded data fails structural validation."""


class ImportError_(BOQAIError):
    """Raised when a database import fails."""


class AIServiceError(BOQAIError):
    """Raised when an AI provider call fails."""
