"""Domain model: ``Task``, ``Status`` and input validation rules."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from task_tracker.errors import ValidationError

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000


class Status(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"

    @classmethod
    def parse(cls, value: str) -> Status:
        """Parse user input leniently: case-insensitive, accepts ``in-progress``."""
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return cls(normalized)
        except ValueError:
            choices = ", ".join(s.value for s in cls)
            raise ValidationError(
                f"Invalid status '{value}'. Choose one of: {choices}."
            ) from None


def utc_now_iso() -> str:
    """Current time as a timezone-aware ISO 8601 string in UTC."""
    return datetime.now(timezone.utc).isoformat()


def validate_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("Task title must not be empty or whitespace-only.")
    if len(cleaned) > TITLE_MAX_LENGTH:
        raise ValidationError(
            f"Task title is too long ({len(cleaned)} characters; "
            f"maximum is {TITLE_MAX_LENGTH})."
        )
    return cleaned


def validate_description(description: str | None) -> str | None:
    if description is None:
        return None
    cleaned = description.strip()
    if not cleaned:
        return None
    if len(cleaned) > DESCRIPTION_MAX_LENGTH:
        raise ValidationError(
            f"Task description is too long ({len(cleaned)} characters; "
            f"maximum is {DESCRIPTION_MAX_LENGTH})."
        )
    return cleaned


class SchemaError(ValueError):
    """A stored record does not match the expected schema (internal)."""


def _parse_timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"'{field_name}' must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SchemaError(f"'{field_name}' is not a valid ISO 8601 timestamp") from None
    if parsed.tzinfo is None:
        raise SchemaError(f"'{field_name}' must include a timezone offset")
    return value


@dataclass
class Task:
    id: int
    title: str
    description: str | None
    status: Status
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Task:
        """Build a Task from stored JSON, raising ``SchemaError`` if invalid."""
        if not isinstance(data, dict):
            raise SchemaError("task entry must be an object")

        task_id = data.get("id")
        # bool is a subclass of int; reject it explicitly.
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise SchemaError("'id' must be a positive integer")

        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SchemaError(f"task {task_id}: 'title' must be a non-empty string")

        description = data.get("description")
        if description is not None and not isinstance(description, str):
            raise SchemaError(f"task {task_id}: 'description' must be a string or null")

        raw_status = data.get("status")
        try:
            status = Status(raw_status)
        except ValueError:
            raise SchemaError(f"task {task_id}: invalid status {raw_status!r}") from None

        try:
            created_at = _parse_timestamp(data.get("created_at"), "created_at")
            updated_at = _parse_timestamp(data.get("updated_at"), "updated_at")
        except SchemaError as exc:
            raise SchemaError(f"task {task_id}: {exc}") from None

        return cls(
            id=task_id,
            title=title,
            description=description,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )
