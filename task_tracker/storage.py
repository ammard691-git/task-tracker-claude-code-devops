"""JSON file persistence with atomic writes and corruption recovery.

On-disk format (schema version 1)::

    {
      "version": 1,
      "next_id": 4,
      "tasks": [ {"id": 1, "title": "...", ...}, ... ]
    }

``next_id`` is a monotonically increasing counter, so IDs of deleted tasks are
never reused.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_tracker.errors import CorruptStorageError, StorageError
from task_tracker.models import SchemaError, Task

SCHEMA_VERSION = 1
DEFAULT_FILENAME = "tasks.json"


@dataclass
class TaskStore:
    """In-memory snapshot of the storage file."""

    tasks: list[Task] = field(default_factory=list)
    next_id: int = 1

    def to_document(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "next_id": self.next_id,
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class RecoveryResult:
    backup_path: Path | None
    salvaged: int
    discarded: int


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` so readers see either the old or new file.

    The data goes to a temporary file in the same directory (same filesystem),
    is flushed and fsync'd, and then ``os.replace`` swaps it in atomically. If
    anything fails, the original file is left untouched and the temp file is
    removed.
    """
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates files as 0600; keep the existing file's permissions.
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp_name, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    _fsync_directory(directory)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def _fsync_directory(directory: Path) -> None:
    """Persist the rename itself (POSIX only; best effort)."""
    if os.name != "posix":
        return
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def parse_document(data: Any) -> TaskStore:
    """Validate a decoded JSON document. Raises ``SchemaError`` if invalid."""
    if not isinstance(data, dict):
        raise SchemaError("top-level value must be a JSON object")

    version = data.get("version", SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise SchemaError("'version' must be an integer")
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"schema version {version} is newer than supported version "
            f"{SCHEMA_VERSION}; upgrade task-tracker"
        )

    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list):
        raise SchemaError("'tasks' must be a list")

    tasks: list[Task] = []
    seen: set[int] = set()
    for index, raw in enumerate(raw_tasks):
        try:
            task = Task.from_dict(raw)
        except SchemaError as exc:
            raise SchemaError(f"tasks[{index}]: {exc}") from None
        if task.id in seen:
            raise SchemaError(f"tasks[{index}]: duplicate task id {task.id}")
        seen.add(task.id)
        tasks.append(task)

    max_id = max(seen, default=0)
    next_id = data.get("next_id", max_id + 1)
    if not isinstance(next_id, int) or isinstance(next_id, bool) or next_id < 1:
        raise SchemaError("'next_id' must be a positive integer")
    # Self-heal a stale counter rather than risk handing out a duplicate ID.
    return TaskStore(tasks=tasks, next_id=max(next_id, max_id + 1))


class JsonStorage:
    """Loads and saves a ``TaskStore`` to a JSON file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    # -- reading -----------------------------------------------------------

    def load(self) -> TaskStore:
        """Load tasks, creating an empty storage file if none exists.

        An empty (zero-byte or whitespace-only) file is treated as an empty
        store. Malformed content raises ``CorruptStorageError``; the file is
        never modified in that case, so no data is lost.
        """
        if not self.path.exists():
            store = TaskStore()
            self.save(store)
            return store

        text = self._read_text()
        if not text.strip():
            return TaskStore()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptStorageError(
                self.path,
                f"invalid JSON at line {exc.lineno}, column {exc.colno} ({exc.msg})",
            ) from None
        try:
            return parse_document(data)
        except SchemaError as exc:
            raise CorruptStorageError(self.path, f"invalid schema: {exc}") from None

    def _read_text(self) -> str:
        if self.path.is_dir():
            raise StorageError(f"Storage path '{self.path}' is a directory, not a file.")
        try:
            return self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise CorruptStorageError(self.path, "file is not valid UTF-8 text") from None
        except OSError as exc:
            raise StorageError(
                f"Could not read storage file '{self.path}': {exc.strerror or exc}"
            ) from None

    # -- writing -----------------------------------------------------------

    def save(self, store: TaskStore) -> None:
        if not self.path.parent.is_dir():
            raise StorageError(
                f"Directory '{self.path.parent}' does not exist; "
                "cannot create the storage file."
            )
        content = json.dumps(store.to_document(), indent=2, ensure_ascii=False) + "\n"
        try:
            atomic_write_text(self.path, content)
        except OSError as exc:
            raise StorageError(
                f"Could not write storage file '{self.path}': {exc.strerror or exc}"
            ) from None

    # -- recovery ----------------------------------------------------------

    def recover(self) -> RecoveryResult:
        """Back up a corrupt file and replace it with a valid one.

        Any task entries that still validate are salvaged into the new file.
        The original bytes are preserved in a timestamped ``.corrupt`` backup.
        """
        if not self.path.exists():
            self.save(TaskStore())
            return RecoveryResult(backup_path=None, salvaged=0, discarded=0)

        try:
            raw_bytes = self.path.read_bytes()
        except OSError as exc:
            raise StorageError(
                f"Could not read storage file '{self.path}': {exc.strerror or exc}"
            ) from None

        store, discarded = _salvage(raw_bytes)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            # Write the backup before touching the original.
            atomic_write_bytes(backup, raw_bytes)
        except OSError as exc:
            raise StorageError(
                f"Could not create backup '{backup}': {exc.strerror or exc}"
            ) from None

        self.save(store)
        return RecoveryResult(
            backup_path=backup, salvaged=len(store.tasks), discarded=discarded
        )


def _salvage(raw_bytes: bytes) -> tuple[TaskStore, int]:
    """Extract every valid, uniquely-identified task from possibly bad data."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return TaskStore(), 0

    raw_tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(raw_tasks, list):
        return TaskStore(), 0

    tasks: list[Task] = []
    seen: set[int] = set()
    discarded = 0
    for raw in raw_tasks:
        try:
            task = Task.from_dict(raw)
        except SchemaError:
            discarded += 1
            continue
        if task.id in seen:
            discarded += 1
            continue
        seen.add(task.id)
        tasks.append(task)

    next_id = data.get("next_id")
    max_id = max(seen, default=0)
    if not isinstance(next_id, int) or isinstance(next_id, bool):
        next_id = 1
    return TaskStore(tasks=tasks, next_id=max(next_id, max_id + 1)), discarded


def resolve_storage_path(cli_value: str | None) -> Path:
    """Precedence: ``--file`` flag, then ``TASK_TRACKER_FILE``, then ./tasks.json."""
    if cli_value:
        return Path(cli_value).expanduser()
    env_value = os.environ.get("TASK_TRACKER_FILE")
    if env_value:
        return Path(env_value).expanduser()
    return Path.cwd() / DEFAULT_FILENAME
