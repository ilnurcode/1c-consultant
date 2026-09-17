class ConsultantError(Exception):
    """Base application error with a stable CLI exit code."""

    exit_code = 2


class InvalidConfigurationError(ConsultantError):
    exit_code = 2


class WorkflowBlockedError(ConsultantError):
    exit_code = 3


class NotFoundError(ConsultantError):
    exit_code = 4


class AgentError(ConsultantError):
    exit_code = 5


class GenerationValidationError(ConsultantError):
    exit_code = 6


class RepositoryValidationError(ConsultantError):
    exit_code = 7


class ODataError(ConsultantError):
    """A safe, user-facing failure while reading the configured 1C OData service."""

    exit_code = 8
