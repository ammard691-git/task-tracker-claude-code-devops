"""Application logic. Each operation is a load -> mutate -> atomic save cycle,
so every change is committed to disk before the command returns."""

from __future__ import annotations

from collections.abc import Callable

from task_tracker.errors import TaskNotFoundError
from task_tracker.models import (
    Status,
    Task,
    utc_now_iso,
    validate_description,
    validate_title,
)
from task_tracker.storage import JsonStorage, TaskStore


class TaskService:
    def __init__(
        self, storage: JsonStorage, clock: Callable[[], str] = utc_now_iso
    ) -> None:
        self._storage = storage
        self._clock = clock

    def add(self, title: str, description: str | None = None) -> Task:
        clean_title = validate_title(title)
        clean_description = validate_description(description)

        store = self._storage.load()
        now = self._clock()
        task = Task(
            id=store.next_id,
            title=clean_title,
            description=clean_description,
            status=Status.TODO,
            created_at=now,
            updated_at=now,
        )
        store.tasks.append(task)
        store.next_id += 1
        self._storage.save(store)
        return task

    def list(self, status: Status | None = None) -> list[Task]:
        tasks = self._storage.load().tasks
        if status is not None:
            tasks = [t for t in tasks if t.status is status]
        return sorted(tasks, key=lambda t: t.id)

    def set_status(self, task_id: int, status: Status) -> tuple[Task, bool]:
        """Set a task's status. Returns ``(task, changed)``; no write if unchanged."""
        store = self._storage.load()
        task = _find(store, task_id)
        if task.status is status:
            return task, False
        task.status = status
        task.updated_at = self._clock()
        self._storage.save(store)
        return task, True

    def delete(self, task_id: int) -> Task:
        store = self._storage.load()
        task = _find(store, task_id)
        store.tasks.remove(task)
        self._storage.save(store)
        return task


def _find(store: TaskStore, task_id: int) -> Task:
    for task in store.tasks:
        if task.id == task_id:
            return task
    raise TaskNotFoundError(task_id)
