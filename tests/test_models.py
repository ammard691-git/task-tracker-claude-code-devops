import unittest

from task_tracker.errors import ValidationError
from task_tracker.models import (
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    SchemaError,
    Status,
    Task,
    validate_description,
    validate_title,
)

VALID = {
    "id": 1,
    "title": "Write tests",
    "description": None,
    "status": "todo",
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}


class StatusParseTests(unittest.TestCase):
    def test_accepts_canonical_and_lenient_forms(self):
        for raw in ("todo", "TODO", " in_progress ", "in-progress", "In Progress", "done"):
            with self.subTest(raw=raw):
                self.assertIsInstance(Status.parse(raw), Status)
        self.assertIs(Status.parse("in-progress"), Status.IN_PROGRESS)

    def test_rejects_unknown(self):
        with self.assertRaisesRegex(ValidationError, "Invalid status 'finished'"):
            Status.parse("finished")


class TitleValidationTests(unittest.TestCase):
    def test_rejects_empty_and_whitespace(self):
        for raw in ("", " ", "\t\n  "):
            with self.subTest(raw=repr(raw)):
                with self.assertRaises(ValidationError):
                    validate_title(raw)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(validate_title("  Buy milk  "), "Buy milk")

    def test_length_boundary(self):
        self.assertEqual(len(validate_title("x" * TITLE_MAX_LENGTH)), TITLE_MAX_LENGTH)
        with self.assertRaisesRegex(ValidationError, "too long"):
            validate_title("x" * (TITLE_MAX_LENGTH + 1))

    def test_single_character_title_ok(self):
        self.assertEqual(validate_title("a"), "a")


class DescriptionValidationTests(unittest.TestCase):
    def test_blank_becomes_none(self):
        self.assertIsNone(validate_description(None))
        self.assertIsNone(validate_description("   "))

    def test_length_boundary(self):
        validate_description("y" * DESCRIPTION_MAX_LENGTH)
        with self.assertRaises(ValidationError):
            validate_description("y" * (DESCRIPTION_MAX_LENGTH + 1))


class TaskSchemaTests(unittest.TestCase):
    def test_round_trip(self):
        task = Task.from_dict(VALID)
        self.assertEqual(task.to_dict(), VALID)

    def test_rejects_invalid_records(self):
        cases = {
            "not a dict": [],
            "missing id": {k: v for k, v in VALID.items() if k != "id"},
            "string id": {**VALID, "id": "1"},
            "bool id": {**VALID, "id": True},
            "zero id": {**VALID, "id": 0},
            "blank title": {**VALID, "title": "  "},
            "numeric description": {**VALID, "description": 5},
            "bad status": {**VALID, "status": "archived"},
            "bad timestamp": {**VALID, "created_at": "yesterday"},
            "naive timestamp": {**VALID, "updated_at": "2026-01-01T00:00:00"},
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(SchemaError):
                    Task.from_dict(record)


if __name__ == "__main__":
    unittest.main()
