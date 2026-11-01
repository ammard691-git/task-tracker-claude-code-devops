import json
import os
from unittest import mock

from task_tracker.errors import CorruptStorageError, StorageError
from task_tracker.models import Status, Task
from task_tracker.storage import JsonStorage, TaskStore, atomic_write_text
from tests.helpers import TempDirTestCase


def make_task(task_id: int) -> Task:
    ts = "2026-01-01T00:00:00+00:00"
    return Task(task_id, f"t{task_id}", None, Status.TODO, ts, ts)


class MissingAndEmptyFileTests(TempDirTestCase):
    def test_missing_file_is_initialized(self):
        storage = JsonStorage(self.store_path)
        store = storage.load()
        self.assertEqual(store.tasks, [])
        self.assertTrue(self.store_path.exists())
        doc = json.loads(self.store_path.read_text())
        self.assertEqual(doc, {"version": 1, "next_id": 1, "tasks": []})

    def test_zero_byte_and_whitespace_files_are_empty_stores(self):
        for content in ("", "   \n\t"):
            with self.subTest(content=repr(content)):
                self.store_path.write_text(content)
                self.assertEqual(JsonStorage(self.store_path).load().tasks, [])

    def test_missing_parent_directory_is_clear_error(self):
        storage = JsonStorage(self.tmp_path / "nope" / "tasks.json")
        with self.assertRaisesRegex(StorageError, "does not exist"):
            storage.load()

    def test_directory_path_is_clear_error(self):
        with self.assertRaisesRegex(StorageError, "is a directory"):
            JsonStorage(self.tmp_path).load()


class CorruptFileTests(TempDirTestCase):
    CORRUPT = {
        "truncated json": '{"tasks": [',
        "garbage": "not json at all",
        "top-level list": "[]",
        "tasks not list": '{"tasks": {}}',
        "missing tasks": '{"version": 1}',
        "invalid task": '{"tasks": [{"id": "x"}]}',
        "duplicate ids": json.dumps(
            {"tasks": [make_task(1).to_dict(), make_task(1).to_dict()]}
        ),
        "future version": '{"version": 99, "tasks": []}',
    }

    def test_corrupt_content_raises_without_modifying_file(self):
        for name, content in self.CORRUPT.items():
            with self.subTest(case=name):
                self.store_path.write_text(content)
                with self.assertRaises(CorruptStorageError):
                    JsonStorage(self.store_path).load()
                self.assertEqual(self.store_path.read_text(), content)

    def test_invalid_utf8_is_corrupt(self):
        self.store_path.write_bytes(b"\xff\xfe\x00garbage")
        with self.assertRaisesRegex(CorruptStorageError, "UTF-8"):
            JsonStorage(self.store_path).load()

    def test_recover_backs_up_and_salvages_valid_tasks(self):
        doc = {"next_id": 10, "tasks": [make_task(1).to_dict(), {"id": "bad"}, make_task(4).to_dict()]}
        original = json.dumps(doc)
        self.store_path.write_text(original)
        storage = JsonStorage(self.store_path)

        result = storage.recover()

        self.assertEqual((result.salvaged, result.discarded), (2, 1))
        self.assertEqual(result.backup_path.read_text(), original)
        store = storage.load()
        self.assertEqual([t.id for t in store.tasks], [1, 4])
        self.assertEqual(store.next_id, 10)

    def test_recover_unparseable_file_starts_fresh(self):
        self.store_path.write_text("{{{{")
        result = JsonStorage(self.store_path).recover()
        self.assertEqual(result.salvaged, 0)
        self.assertEqual(result.backup_path.read_text(), "{{{{")
        self.assertEqual(JsonStorage(self.store_path).load().tasks, [])


class AtomicWriteTests(TempDirTestCase):
    def test_failed_replace_leaves_original_intact_and_no_temp_files(self):
        storage = JsonStorage(self.store_path)
        storage.save(TaskStore([make_task(1)], next_id=2))
        original = self.store_path.read_bytes()

        with mock.patch("task_tracker.storage.os.replace", side_effect=OSError(28, "No space left")):
            with self.assertRaisesRegex(StorageError, "No space left"):
                storage.save(TaskStore([make_task(1), make_task(2)], next_id=3))

        self.assertEqual(self.store_path.read_bytes(), original)
        self.assertEqual(os.listdir(self.tmp_path), ["tasks.json"])

    def test_interrupt_during_write_leaves_original_intact(self):
        atomic_write_text(self.store_path, "original")
        with mock.patch("task_tracker.storage.os.fsync", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                atomic_write_text(self.store_path, "new content")
        self.assertEqual(self.store_path.read_text(), "original")
        self.assertEqual(os.listdir(self.tmp_path), ["tasks.json"])

    def test_preserves_existing_permissions(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions only")
        atomic_write_text(self.store_path, "x")
        os.chmod(self.store_path, 0o640)
        atomic_write_text(self.store_path, "y")
        self.assertEqual(self.store_path.stat().st_mode & 0o777, 0o640)

    def test_round_trip_unicode(self):
        storage = JsonStorage(self.store_path)
        ts = "2026-01-01T00:00:00+00:00"
        storage.save(TaskStore([Task(1, "Café ☕ 日本", "naïve", Status.DONE, ts, ts)], 2))
        self.assertEqual(storage.load().tasks[0].title, "Café ☕ 日本")
