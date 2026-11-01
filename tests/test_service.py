import json
from datetime import datetime, timezone

from task_tracker.errors import TaskNotFoundError, ValidationError
from task_tracker.models import Status
from task_tracker.service import TaskService
from task_tracker.storage import JsonStorage
from tests.helpers import TempDirTestCase


class FakeClock:
    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"2026-01-01T00:00:{self.ticks:02d}+00:00"


class TaskCreationTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.service = TaskService(JsonStorage(self.store_path))

    def test_new_task_defaults(self):
        task = self.service.add("  Write docs  ", "  details  ")
        self.assertEqual(task.id, 1)
        self.assertEqual(task.title, "Write docs")
        self.assertEqual(task.description, "details")
        self.assertIs(task.status, Status.TODO)
        self.assertEqual(task.created_at, task.updated_at)

    def test_timestamps_are_accurate_iso8601_utc(self):
        before = datetime.now(timezone.utc)
        task = self.service.add("Timestamped")
        after = datetime.now(timezone.utc)
        created = datetime.fromisoformat(task.created_at)
        self.assertIsNotNone(created.tzinfo)
        self.assertEqual(created.utcoffset().total_seconds(), 0)
        self.assertTrue(before <= created <= after)

    def test_ids_are_unique_and_incremental(self):
        ids = [self.service.add(f"Task {i}").id for i in range(25)]
        self.assertEqual(ids, list(range(1, 26)))
        self.assertEqual(len(set(ids)), len(ids))

    def test_ids_are_never_reused_after_delete(self):
        self.service.add("a")
        second = self.service.add("b")
        self.service.delete(second.id)
        self.assertEqual(self.service.add("c").id, 3)

    def test_stale_next_id_counter_cannot_cause_duplicates(self):
        self.service.add("a")
        self.service.add("b")
        doc = json.loads(self.store_path.read_text())
        doc["next_id"] = 1  # simulate a hand-edited / stale counter
        self.store_path.write_text(json.dumps(doc))
        self.assertEqual(self.service.add("c").id, 3)

    def test_empty_title_rejected_and_nothing_written(self):
        self.service.add("keep")
        before = self.store_path.read_bytes()
        with self.assertRaises(ValidationError):
            self.service.add("   ")
        self.assertEqual(self.store_path.read_bytes(), before)


class TaskMutationTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.service = TaskService(JsonStorage(self.store_path), clock=self.clock)
        self.task = self.service.add("Work item")

    def test_set_status_updates_timestamp(self):
        task, changed = self.service.set_status(self.task.id, Status.IN_PROGRESS)
        self.assertTrue(changed)
        self.assertIs(task.status, Status.IN_PROGRESS)
        self.assertEqual(task.created_at, "2026-01-01T00:00:01+00:00")
        self.assertEqual(task.updated_at, "2026-01-01T00:00:02+00:00")

    def test_set_same_status_is_noop(self):
        before = self.store_path.read_bytes()
        task, changed = self.service.set_status(self.task.id, Status.TODO)
        self.assertFalse(changed)
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_unknown_id_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.service.set_status(999, Status.DONE)
        with self.assertRaises(TaskNotFoundError):
            self.service.delete(999)

    def test_delete_removes_task(self):
        self.service.delete(self.task.id)
        self.assertEqual(self.service.list(), [])

    def test_list_filters_by_status(self):
        b = self.service.add("b")
        self.service.set_status(b.id, Status.DONE)
        self.assertEqual([t.id for t in self.service.list(Status.DONE)], [b.id])
        self.assertEqual([t.id for t in self.service.list(Status.TODO)], [self.task.id])
        self.assertEqual(self.service.list(Status.IN_PROGRESS), [])
        self.assertEqual(len(self.service.list()), 2)
