"""Shared test fixtures. Every test works inside its own temporary directory
and clears TASK_TRACKER_FILE, so real runtime storage is never touched."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from task_tracker.cli import main


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="task-tracker-test-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.store_path = self.tmp_path / "tasks.json"

        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TASK_TRACKER_FILE", None)
        os.environ.pop("TASK_TRACKER_DEBUG", None)

    def run_cli(self, *args: str, use_file_flag: bool = True) -> tuple[int, str, str]:
        """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        argv = (["--file", str(self.store_path)] if use_file_flag else []) + list(args)
        # argparse writes usage errors to sys.stderr directly.
        with redirect_stderr(err):
            code = main(argv, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()
