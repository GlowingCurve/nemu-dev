class ExplogError(Exception):
    """Base class for expected explog failures."""


class ConfigError(ExplogError):
    """Raised when the configuration cannot be loaded or validated."""


class LogError(ExplogError):
    """Raised when the JSONL log is invalid or cannot be used."""


class GitError(ExplogError):
    """Raised when the Git snapshot cannot be captured."""


class DirectoryError(ExplogError):
    """Raised when the run directories are invalid or cannot be created."""


class ScriptError(ExplogError):
    """Raised when an experiment or processing script fails."""
