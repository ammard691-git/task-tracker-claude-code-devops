# task-tracker

A small command-line task manager that stores tasks in a local JSON file. It
uses only the Python standard library.

- Adds, lists, filters, updates and deletes tasks from the terminal
- Saves every change to disk immediately, using atomic writes
- Detects corrupted storage files and offers a recovery command
- Prints clear error messages and uses consistent exit codes, with no raw stack traces

---

## Architecture

```
task_tracker/
├── __main__.py    # `python -m task_tracker` entry point
├── cli.py         # argparse parser, command dispatch, output, error → exit-code mapping
├── service.py     # application logic: add / list / set_status / delete
├── models.py      # Task dataclass, Status enum, input validation, record schema checks
├── storage.py     # JSON persistence, schema validation, atomic writes, recovery
├── formatting.py  # plain-text table rendering
└── errors.py      # exception hierarchy (each error carries its exit code)
tests/             # unittest suite; every test runs in an isolated temp directory
```

The code is split into layers, and each layer depends only on the ones below it:

```
cli  ──▶  service  ──▶  storage  ──▶  models / errors
 └──▶ formatting
```

- **CLI layer** (`cli.py`) is the only code that knows about `argv`, stdout or
  stderr, and exit codes. It turns every expected `TaskTrackerError` into a
  one-line `error: ...` message. A last-resort handler makes sure unexpected
  failures don't print a traceback either (set `TASK_TRACKER_DEBUG=1` to show it).
- **Service layer** (`service.py`) runs each command as one cycle:
  *load → validate/mutate → atomic save*. Changes are on disk before the
  command returns. The clock can be injected, which keeps tests deterministic.
- **Storage layer** (`storage.py`) owns the file format, schema validation,
  atomic writes and recovery.

### Storage format

```json
{
  "version": 1,
  "next_id": 4,
  "tasks": [
    {
      "id": 1,
      "title": "Write report",
      "description": "Q4 numbers",
      "status": "in_progress",
      "created_at": "2026-11-01T12:30:30.123456+00:00",
      "updated_at": "2026-11-01T12:45:02.654321+00:00"
    }
  ]
}
```

- **IDs** are incrementing integers. `next_id` is a counter that only goes up,
  so a deleted task's ID is **never reused**. If someone edits the file by hand
  and leaves the counter stale, it is corrected on load to `max(id) + 1`.
- **Timestamps** are ISO 8601 strings in UTC that include the timezone offset.

### Robustness guarantees

| Situation | Behaviour |
|---|---|
| `tasks.json` missing | An empty, valid file is created automatically. |
| `tasks.json` is empty (0 bytes or whitespace only) | Treated as an empty task list. |
| Malformed JSON, invalid UTF-8, wrong schema, duplicate IDs, bad status or timestamp | Exits with code 3, names the problem and its location, and **does not modify the file**. Writes are refused too, so damaged data is never overwritten silently. Suggests running `task-tracker recover`. |
| `recover` | Copies the damaged file to `tasks.json.corrupt-<UTC timestamp>`, keeps every task entry that still validates, and writes a clean file. |
| Crash, power loss or Ctrl-C during a write | The data is written to a temp file in the same directory, `fsync`'d, then swapped in with `os.replace` (atomic on POSIX and Windows). The directory is `fsync`'d afterwards on POSIX. Readers see either the old file or the new one, never a partial write. Temp files are cleaned up if the write fails, and the existing file's permissions are kept. |

**Known limitation:** commands do not lock the file. If two commands write at
the exact same moment, one change can overwrite the other. Neither write can
corrupt the file, though.

---

## Installation

Requires **Python 3.10+**. There are no third-party dependencies.

```bash
git clone <repo-url> task-tracker && cd task-tracker   # or copy the project folder

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install .                      # installs the `task-tracker` command
# or, for development:
pip install -e .
```

You can also run it without installing:

```bash
python -m task_tracker --help
```

---

## Command reference

```
task-tracker [--file PATH] <command> [options]
```

### Global options

| Option | Description |
|---|---|
| `-f PATH`, `--file PATH` | Storage file to use. |
| `--version` | Print the version (e.g. `task-tracker 1.0.0`) and exit 0. |
| `-h`, `--help` | Show help (works on every subcommand too). |

The storage file is chosen in this order: `--file`, then the
`TASK_TRACKER_FILE` environment variable, then `./tasks.json` in the current
directory.

```bash
task-tracker --file ~/work-tasks.json list
export TASK_TRACKER_FILE=~/tasks.json && task-tracker list
task-tracker --version
task-tracker add --help
```

The version is defined once, as `__version__` in `task_tracker/__init__.py`;
`pyproject.toml` reads it from there, so bump it only in that file.

### `add`: create a task

```bash
task-tracker add "Write quarterly report"
task-tracker add "Fix login bug" --description "Users with + in email can't sign in"
task-tracker add "Call dentist" -d "Before Friday"
task-tracker add -- "-titles starting with a dash need --"
```

Output: `Added task 1: Write quarterly report`

Rules:
- The title is required. Leading and trailing whitespace is removed, and the
  title can't be empty or whitespace-only. Maximum 200 characters.
- The description is optional. Maximum 2000 characters. A blank description is
  stored as `null`.
- New tasks start with status `todo`.

### `list` (alias `ls`): show tasks

```bash
task-tracker list
task-tracker ls
task-tracker list --status todo
task-tracker list -s in_progress
task-tracker list -s in-progress      # hyphen form accepted, case-insensitive
task-tracker list --status done
task-tracker list --wide              # don't truncate long titles/descriptions
task-tracker list -w -s todo
task-tracker list --json              # machine-readable output
task-tracker list --json -s done | python -m json.tool
```

Sample output:

```
ID  STATUS       TITLE                   DESCRIPTION                     CREATED (UTC)     UPDATED (UTC)
--  -----------  ----------------------  ------------------------------  ----------------  ----------------
 1  in_progress  Write quarterly report  -                               2026-11-01 12:30  2026-11-01 12:45
 2  todo         Fix login bug           Users with + in email can't...  2026-11-01 12:31  2026-11-01 12:31
```

| Option | Description |
|---|---|
| `-s STATUS`, `--status STATUS` | Show only tasks with this status: `todo`, `in_progress`, `done`. |
| `-w`, `--wide` | Don't truncate titles (normally 40 characters) or descriptions (normally 30). |
| `--json` | Print a JSON array of task objects instead of a table. |

### `start`: mark a task as `in_progress`

```bash
task-tracker start 1
```

### `done`: mark a task as `done`

```bash
task-tracker done 1
```

### `mark`: set any status (including back to `todo`)

```bash
task-tracker mark 2 in_progress
task-tracker mark 2 done
task-tracker mark 2 todo
```

When a status changes, the task's `updated_at` changes too. Setting a task to
the status it already has does nothing: the command prints
`Task 1 is already done.` and doesn't write to the file.

### `delete` (alias `rm`): remove a task

```bash
task-tracker delete 3
task-tracker rm 3
```

### `recover`: repair a corrupt storage file

```bash
task-tracker recover
task-tracker --file ~/work-tasks.json recover
```

If the file is valid, `recover` reports that and does nothing.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Task not found |
| `2` | Invalid command, argument or input (e.g. empty title, bad ID, unknown status) |
| `3` | Storage error (corrupt file, unreadable or unwritable path) |
| `4` | Unexpected internal error |
| `130` | Interrupted (Ctrl-C) |

### Example session

```bash
$ task-tracker add "Write report" -d "Q4 numbers"
Added task 1: Write report
$ task-tracker add "   "
error: Task title must not be empty or whitespace-only.
$ task-tracker start 1
Task 1 marked as in_progress.
$ task-tracker done 9
error: Task 9 not found.
$ task-tracker start abc
usage: task-tracker start [-h] id
task-tracker start: error: argument id: invalid task ID 'abc' (must be a positive integer)
$ echo '{"tasks": [' > tasks.json
$ task-tracker list
error: Storage file '/home/me/tasks.json' is corrupt: invalid JSON at line 2, column 1 (Expecting value)
Your data has not been modified. To back up the damaged file and start fresh (keeping any valid tasks), run:
  task-tracker recover
$ task-tracker recover
Backed up corrupt file to '/home/me/tasks.json.corrupt-20261101T123030960116Z'.
Rebuilt '/home/me/tasks.json': 0 task(s) salvaged, 0 invalid entries discarded.
```

---

## Running the tests

From the project root:

```bash
python -m unittest discover tests
```

Verbose:

```bash
python -m unittest discover tests -v
```

Every test creates its own `tempfile.TemporaryDirectory` and clears
`TASK_TRACKER_FILE` using `unittest.mock`, so your real `tasks.json` is never
read or changed. The suite covers:

- **Task creation**: default values, unique and incrementing IDs, no ID reuse
  after deletion, a stale-counter self-heal, and timestamps that are accurate
  UTC ISO 8601.
- **Persistence**: real subprocess runs of `python -m task_tracker`, showing
  that state survives between separate processes.
- **CLI parser**: valid commands and aliases, length boundaries (200 and 201
  characters), invalid IDs and statuses, unknown commands, missing arguments,
  exit codes, and no tracebacks.
- **Storage resilience**: missing, empty, whitespace-only, truncated,
  non-UTF-8 and schema-invalid files. Recovery and salvage. Atomic writes under
  simulated `os.replace` failure and a `KeyboardInterrupt` mid-write.
