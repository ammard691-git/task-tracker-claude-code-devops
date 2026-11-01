"""Command-line interface: argument parsing, output and error reporting."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import traceback
from collections.abc import Sequence
from typing import TextIO

from task_tracker import __version__
from task_tracker.errors import CorruptStorageError, TaskTrackerError, ValidationError
from task_tracker.formatting import render_table
from task_tracker.models import Status
from task_tracker.service import TaskService
from task_tracker.storage import JsonStorage, resolve_storage_path

PROG = "task-tracker"

EXIT_OK = 0
EXIT_UNEXPECTED = 4
EXIT_INTERRUPTED = 130


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid task ID '{value}' (must be a positive integer)"
        ) from None
    if number < 1:
        raise argparse.ArgumentTypeError(
            f"invalid task ID '{value}' (must be a positive integer)"
        )
    return number


def status_value(value: str) -> Status:
    try:
        return Status.parse(value)
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Track tasks from the command line. Data is stored in a JSON file.",
        epilog="Run '%(prog)s <command> --help' for details on a command.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-f",
        "--file",
        metavar="PATH",
        help="storage file (default: $TASK_TRACKER_FILE or ./tasks.json)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    add = sub.add_parser("add", help="add a new task")
    add.add_argument("title", help="task title (quote it if it contains spaces)")
    add.add_argument("-d", "--description", help="optional longer description")

    lst = sub.add_parser("list", aliases=["ls"], help="list tasks")
    lst.add_argument(
        "-s",
        "--status",
        type=status_value,
        help="only show tasks with this status (todo, in_progress, done)",
    )
    lst.add_argument("-w", "--wide", action="store_true", help="do not truncate long text")
    lst.add_argument("--json", action="store_true", help="output machine-readable JSON")

    start = sub.add_parser("start", help="mark a task as in_progress")
    start.add_argument("id", type=positive_int, help="task ID")

    done = sub.add_parser("done", help="mark a task as done")
    done.add_argument("id", type=positive_int, help="task ID")

    mark = sub.add_parser("mark", help="set a task to any status")
    mark.add_argument("id", type=positive_int, help="task ID")
    mark.add_argument(
        "status", type=status_value, help="new status (todo, in_progress, done)"
    )

    delete = sub.add_parser("delete", aliases=["rm"], help="delete a task")
    delete.add_argument("id", type=positive_int, help="task ID")

    sub.add_parser(
        "recover",
        help="back up a corrupt storage file and rebuild it, salvaging valid tasks",
    )
    return parser


def _cmd_add(service: TaskService, args: argparse.Namespace, out: TextIO) -> int:
    task = service.add(args.title, args.description)
    print(f"Added task {task.id}: {task.title}", file=out)
    return EXIT_OK


def _cmd_list(service: TaskService, args: argparse.Namespace, out: TextIO) -> int:
    tasks = service.list(args.status)
    if args.json:
        json.dump([t.to_dict() for t in tasks], out, indent=2, ensure_ascii=False)
        print(file=out)
    elif not tasks:
        if args.status is not None:
            print(f"No tasks with status '{args.status.value}'.", file=out)
        else:
            print("No tasks yet. Add one with: task-tracker add \"My task\"", file=out)
    else:
        print(render_table(tasks, wide=args.wide), file=out)
    return EXIT_OK


def _set_status(service: TaskService, task_id: int, status: Status, out: TextIO) -> int:
    task, changed = service.set_status(task_id, status)
    if changed:
        print(f"Task {task.id} marked as {status.value}.", file=out)
    else:
        print(f"Task {task.id} is already {status.value}.", file=out)
    return EXIT_OK


def _cmd_delete(service: TaskService, args: argparse.Namespace, out: TextIO) -> int:
    task = service.delete(args.id)
    print(f"Deleted task {task.id}: {task.title}", file=out)
    return EXIT_OK


def _cmd_recover(storage: JsonStorage, out: TextIO) -> int:
    try:
        storage.load()
    except CorruptStorageError:
        pass
    else:
        print(f"Storage file '{storage.path}' is healthy; nothing to recover.", file=out)
        return EXIT_OK

    result = storage.recover()
    print(f"Backed up corrupt file to '{result.backup_path}'.", file=out)
    print(
        f"Rebuilt '{storage.path}': {result.salvaged} task(s) salvaged, "
        f"{result.discarded} invalid entr{'y' if result.discarded == 1 else 'ies'} discarded.",
        file=out,
    )
    return EXIT_OK


def run(args: argparse.Namespace, out: TextIO) -> int:
    storage = JsonStorage(resolve_storage_path(args.file))
    if args.command == "recover":
        return _cmd_recover(storage, out)

    service = TaskService(storage)
    if args.command == "add":
        return _cmd_add(service, args, out)
    if args.command in ("list", "ls"):
        return _cmd_list(service, args, out)
    if args.command == "start":
        return _set_status(service, args.id, Status.IN_PROGRESS, out)
    if args.command == "done":
        return _set_status(service, args.id, Status.DONE, out)
    if args.command == "mark":
        return _set_status(service, args.id, args.status, out)
    if args.command in ("delete", "rm"):
        return _cmd_delete(service, args, out)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def main(
    argv: Sequence[str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Entry point. Returns a process exit code instead of raising."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse reports usage errors (exit 2) and --help (0)
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        return run(args, out)
    except CorruptStorageError as exc:
        print(f"error: {exc}", file=err)
        print(
            "Your data has not been modified. To back up the damaged file and "
            "start fresh (keeping any valid tasks), run:\n"
            f"  {PROG}{_file_flag(args)} recover",
            file=err,
        )
        return exc.exit_code
    except TaskTrackerError as exc:
        print(f"error: {exc}", file=err)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Interrupted.", file=err)
        return EXIT_INTERRUPTED
    except Exception as exc:  # last-resort guard: never show a raw traceback
        if os.environ.get("TASK_TRACKER_DEBUG"):
            traceback.print_exc(file=err)
        print(
            f"error: unexpected failure: {exc.__class__.__name__}: {exc}\n"
            "Set TASK_TRACKER_DEBUG=1 to see the full traceback.",
            file=err,
        )
        return EXIT_UNEXPECTED


def _file_flag(args: argparse.Namespace) -> str:
    return f" --file {shlex.quote(args.file)}" if args.file else ""
