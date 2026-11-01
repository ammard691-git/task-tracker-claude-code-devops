import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.helpers import TempDirTestCase

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ParserTests(TempDirTestCase):
    def test_add_and_list(self):
        code, out, _ = self.run_cli("add", "Buy milk", "-d", "2 litres")
        self.assertEqual(code, 0)
        self.assertIn("Added task 1: Buy milk", out)
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("Buy milk", out)
        self.assertIn("2 litres", out)
        self.assertIn("STATUS", out)

    def test_list_empty(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("No tasks yet", out)
        code, out, _ = self.run_cli("ls", "--status", "done")
        self.assertIn("No tasks with status 'done'", out)

    def test_status_commands_and_filter(self):
        self.run_cli("add", "one")
        self.run_cli("add", "two")
        self.run_cli("add", "three")
        self.assertEqual(self.run_cli("start", "1")[0], 0)
        self.assertEqual(self.run_cli("done", "2")[0], 0)
        code, out, _ = self.run_cli("mark", "3", "in-progress")
        self.assertEqual(code, 0)
        self.assertIn("marked as in_progress", out)

        _, out, _ = self.run_cli("list", "--status", "in_progress", "--json")
        self.assertEqual(sorted(t["id"] for t in json.loads(out)), [1, 3])
        _, out, _ = self.run_cli("list", "-s", "done", "--json")
        self.assertEqual([t["title"] for t in json.loads(out)], ["two"])

    def test_already_in_status_message(self):
        self.run_cli("add", "x")
        self.run_cli("done", "1")
        code, out, _ = self.run_cli("done", "1")
        self.assertEqual(code, 0)
        self.assertIn("already done", out)

    def test_delete(self):
        self.run_cli("add", "temp")
        code, out, _ = self.run_cli("rm", "1")
        self.assertEqual(code, 0)
        self.assertIn("Deleted task 1", out)
        self.assertEqual(json.loads(self.run_cli("list", "--json")[1]), [])

    def test_truncation_and_wide(self):
        long_title = "word " * 30
        self.run_cli("add", long_title)
        _, out, _ = self.run_cli("list")
        self.assertIn("...", out)
        _, out, _ = self.run_cli("list", "--wide")
        self.assertIn(long_title.strip(), out)

    def test_title_starting_with_dash_via_double_dash(self):
        code, out, _ = self.run_cli("add", "--", "-negative title")
        self.assertEqual(code, 0)
        self.assertIn("-negative title", out)

    # --- invalid input -------------------------------------------------

    def test_invalid_arguments_exit_2_with_readable_errors(self):
        cases = {
            ("add", "   "): "must not be empty",
            ("add", ""): "must not be empty",
            ("add", "x" * 201): "too long",
            ("start", "abc"): "invalid task ID 'abc'",
            ("done", "0"): "invalid task ID '0'",
            ("delete", "-5"): "",  # parsed as an unknown option by argparse
            ("mark", "1", "finished"): "Invalid status 'finished'",
            ("list", "--status", "bogus"): "Invalid status 'bogus'",
            ("frobnicate",): "invalid choice",
            (): "required",
            ("start",): "required",
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn(expected, err)
                self.assertNotIn("Traceback", err)

    def test_unknown_task_exit_1(self):
        for argv in (("start", "42"), ("done", "42"), ("rm", "42"), ("mark", "42", "todo")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("Task 42 not found", err)

    def test_boundary_max_length_title_accepted(self):
        self.assertEqual(self.run_cli("add", "x" * 200)[0], 0)

    def test_help_exits_zero(self):
        with mock.patch("sys.stdout"):
            code, _, _ = self.run_cli("--help")
        self.assertEqual(code, 0)

    # --- corrupt storage -----------------------------------------------

    def test_corrupt_file_reports_cleanly_and_suggests_recover(self):
        self.store_path.write_text('{"tasks": [')
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 3)
        self.assertIn("is corrupt", err)
        self.assertIn("recover", err)
        self.assertNotIn("Traceback", err)
        # Writes are refused too, so the damaged data is never overwritten.
        self.assertEqual(self.run_cli("add", "x")[0], 3)
        self.assertEqual(self.store_path.read_text(), '{"tasks": [')

    def test_recover_command(self):
        self.store_path.write_text("garbage")
        code, out, _ = self.run_cli("recover")
        self.assertEqual(code, 0)
        self.assertIn("Backed up corrupt file", out)
        self.assertEqual(self.run_cli("add", "after recovery")[0], 0)

    def test_recover_on_healthy_file(self):
        self.run_cli("add", "fine")
        code, out, _ = self.run_cli("recover")
        self.assertEqual(code, 0)
        self.assertIn("healthy", out)

    def test_unexpected_error_has_no_traceback(self):
        with mock.patch("task_tracker.cli.run", side_effect=RuntimeError("boom")):
            code, _, err = self.run_cli("list")
        self.assertEqual(code, 4)
        self.assertIn("unexpected failure", err)
        self.assertNotIn("Traceback", err)

    # --- path resolution -----------------------------------------------

    def test_env_var_selects_storage_file(self):
        target = self.tmp_path / "custom.json"
        with mock.patch.dict(os.environ, {"TASK_TRACKER_FILE": str(target)}):
            self.run_cli("add", "via env", use_file_flag=False)
        self.assertEqual(json.loads(target.read_text())["tasks"][0]["title"], "via env")


class PersistenceAcrossProcessesTests(TempDirTestCase):
    """Each call is a separate interpreter, proving data survives process exit."""

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "TASK_TRACKER_FILE"}
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "task_tracker", *args],
            cwd=self.tmp_path,  # default ./tasks.json lands in the temp dir
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_state_persists_between_invocations(self):
        self.assertEqual(self.cli("add", "first").returncode, 0)
        self.assertEqual(self.cli("add", "second", "-d", "desc").returncode, 0)
        self.assertEqual(self.cli("done", "1").returncode, 0)
        self.assertEqual(self.cli("delete", "2").returncode, 0)
        self.assertEqual(self.cli("add", "third").returncode, 0)

        result = self.cli("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        tasks = json.loads(result.stdout)
        self.assertEqual([(t["id"], t["status"]) for t in tasks], [(1, "done"), (3, "todo")])
        self.assertTrue((self.tmp_path / "tasks.json").exists())

    def test_corrupt_file_subprocess_has_no_traceback(self):
        (self.tmp_path / "tasks.json").write_text("{oops")
        result = self.cli("list")
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("Traceback", result.stderr)


class VersionFlagTests(TempDirTestCase):
    def test_version_prints_name_and_version(self):
        from task_tracker import __version__

        out = io.StringIO()
        # argparse's version action writes to sys.stdout directly.
        with redirect_stdout(out):
            code, _, err = self.run_cli("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), f"task-tracker {__version__}")
        self.assertEqual(err, "")
        self.assertFalse(self.store_path.exists(), "--version must not create storage")

    def test_version_from_subprocess(self):
        from task_tracker import __version__

        env = {k: v for k, v in os.environ.items() if k != "TASK_TRACKER_FILE"}
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        result = subprocess.run(
            [sys.executable, "-m", "task_tracker", "--version"],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"task-tracker {__version__}")

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
    def test_pyproject_reads_version_from_package(self):
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
            config = tomllib.load(fh)
        self.assertNotIn("version", config["project"], "version must live only in __init__.py")
        self.assertIn("version", config["project"]["dynamic"])
        self.assertEqual(
            config["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "task_tracker.__version__"},
        )
