"""Plain-text table rendering (no third-party dependencies)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from task_tracker.models import Task

TITLE_WIDTH = 40
DESCRIPTION_WIDTH = 30
ELLIPSIS = "..."

HEADERS = ("ID", "STATUS", "TITLE", "DESCRIPTION", "CREATED (UTC)", "UPDATED (UTC)")


def _single_line(text: str) -> str:
    return " ".join(text.split())


def truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(width - len(ELLIPSIS), 0)] + ELLIPSIS


def format_timestamp(value: str) -> str:
    """Render an ISO timestamp as ``YYYY-MM-DD HH:MM`` in UTC."""
    try:
        moment = datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return value
    return moment.strftime("%Y-%m-%d %H:%M")


def render_table(tasks: Sequence[Task], wide: bool = False) -> str:
    rows: list[tuple[str, ...]] = []
    for task in tasks:
        title = _single_line(task.title)
        description = _single_line(task.description or "")
        if not wide:
            title = truncate(title, TITLE_WIDTH)
            description = truncate(description, DESCRIPTION_WIDTH)
        rows.append(
            (
                str(task.id),
                task.status.value,
                title,
                description or "-",
                format_timestamp(task.created_at),
                format_timestamp(task.updated_at),
            )
        )

    widths = [len(h) for h in HEADERS]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row)]

    def fmt(cells: Sequence[str]) -> str:
        parts = []
        for index, (cell, width) in enumerate(zip(cells, widths)):
            # Right-align the numeric ID column, left-align the rest.
            parts.append(cell.rjust(width) if index == 0 else cell.ljust(width))
        return "  ".join(parts).rstrip()

    lines = [fmt(HEADERS), fmt(["-" * w for w in widths])]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)
