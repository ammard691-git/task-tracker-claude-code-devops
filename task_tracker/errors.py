"""Exception hierarchy.

Every error the application raises on purpose derives from ``TaskTrackerError``
and carries a human-readable message plus a process exit code, so the CLI layer
can report it without a stack trace.
"""

from __future__ import annotations

from pathlib import Path


class TaskTrackerError(Exception):
    """Base class for all expected, user-facing errors."""

    exit_code: int = 1


class ValidationError(TaskTrackerError):
    """User input failed validation (empty title, bad status, ...)."""

    exit_code = 2


class TaskNotFoundError(TaskTrackerError):
    """No task exists with the requested ID."""

    exit_code = 1

    def __init__(self, task_id: int) -> None:
        super().__init__(f"Task {task_id} not found.")
        self.task_id = task_id


class StorageError(TaskTrackerError):
    """The storage file could not be read or written."""

    exit_code = 3


class CorruptStorageError(StorageError):
    """The storage file exists but holds malformed JSON or an invalid schema."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"Storage file '{path}' is corrupt: {reason}")
        self.path = path
        self.reason = reason
