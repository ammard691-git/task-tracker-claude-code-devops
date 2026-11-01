# task-tracker

A Python 3.10+ command-line task manager that uses only the standard library.
Tasks are stored in a JSON file. Layers: `cli.py` → `service.py` → `storage.py`
→ `models.py` / `errors.py`.

## Run

```bash
python -m task_tracker --help              # from the repo root, no install needed
pip install -e . && task-tracker --help    # installs the console script
```

The storage file is chosen in this order: `--file PATH`, then the
`TASK_TRACKER_FILE` environment variable, then `./tasks.json`. Set
`TASK_TRACKER_DEBUG=1` to show tracebacks.

Exit codes: 0 ok, 1 task not found, 2 bad input, 3 storage error, 4 unexpected error.

## Test

```bash
python -m unittest discover tests
```

Tests run in temp directories and must never touch a real `tasks.json`. Use
`tests/helpers.py::TempDirTestCase` for new tests.

## Known bugs and limitations (details in TEST_REPORT.md)

- **No file locking.** Commands running at the same time silently lose tasks
  and print duplicate IDs, while all reporting success.
- **Symlinked storage file.** The first write replaces the symlink with a
  regular file, so the real target stops being updated.
- **Newer schema version.** It is reported as "corrupt", and `recover`
  downgrades it.
- **Unknown JSON fields** are dropped on the next write.
- **`BrokenPipeError`** (e.g. `list | head`) exits 4 with "unexpected failure".
- **Smaller issues:**
  - `--file ""` silently uses the default path.
  - Titles made only of zero-width characters are accepted.
  - Control and ANSI characters are printed raw.
  - Wide (CJK) characters misalign the table.
  - `recover` of unparseable JSON resets `next_id` to 1.
- **Only tested on Python 3.12, as root.** Python 3.10 and Windows are untested.
