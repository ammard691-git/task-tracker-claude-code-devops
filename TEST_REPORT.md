# task-tracker: Test Report

- **Date:** 2026-11-01
- **Version tested:** 1.0.0
- **Environment:** Linux, Python 3.12.15 (running as root)
- **Scope:** the automated test suite, a manual run of every CLI command, and
  failure-injection scenarios. No source code was changed.

## Summary

| Area | Result |
|---|---|
| Automated suite (`python -m unittest discover tests`) | **51 of 51 pass** (about 2.7 s) |
| Manual functional checks (add, list, filter, update, delete) | All pass |
| Missing, empty and corrupt storage handling | All pass |
| Edge-case and stress probes | **9 issues found**: 2 high, 2 medium, 5 low (see [Bugs found](#bugs-found)) |

All the core requirements in the spec work. The bugs show up in situations the
spec doesn't cover directly: concurrent commands, symlinked storage files,
pipes, newer schema versions, and unusual characters in titles.

Each command was run as its own `python -m task_tracker` process in a
throwaway temp directory, so every step also checks that data persists between
invocations.

---

## Results table

| Feature | Test performed | Result | Notes |
|---|---|---|---|
| Test suite | `python -m unittest discover tests` | PASS | 51 tests, 0 failures |
| Help / version | `--help`, `--version`, `<cmd> --help` for all 7 commands | PASS | Exit 0 for each |
| Add | Title + `-d` / `--description` | PASS | `Added task 1: Write report` |
| Add | Leading/trailing whitespace in title | PASS | Stored as `padded title` |
| Add | Unicode title (`Café ☕ 日本語`) | PASS | Saved and read back correctly (see BUG-8 for table alignment) |
| Add | Title of exactly 200 characters | PASS | Accepted |
| Add | Title of 201 characters | PASS | `Task title is too long (201 characters; maximum is 200).`, exit 2 |
| Add | Description of 2001 characters | PASS | Rejected, exit 2 |
| Add | Whitespace-only description `-d "   "` | PASS | Stored as `null` |
| Add | Title with an embedded newline | PASS | Stored as entered; the table shows it on one line |
| Add | Title starting with a dash, using `--` | PASS | `add -- "-dash title"` works |
| Add | Title starting with a dash, without `--` | PASS* | Rejected, but the error is misleading (BUG-9) |
| Add | Empty `""`, spaces only, `\t\n` | PASS | `Task title must not be empty or whitespace-only.`, exit 2 |
| Add | No title argument | PASS | argparse "required: title", exit 2 |
| Add | Zero-width-space title (`U+200B`) | FAIL | Accepted; the title looks blank (BUG-7) |
| Add | Title containing ANSI escape / control characters | FAIL | Written raw to the terminal (BUG-7) |
| IDs | IDs count up from 1 | PASS | 1, 2, 3, … |
| IDs | No reuse after delete | PASS | Delete 2, then add, gives ID 3 |
| IDs | Uniqueness when commands run in parallel | **FAIL** | 20 parallel adds announced duplicate IDs (BUG-1) |
| Timestamps | `created_at` / `updated_at` are ISO 8601 with UTC offset | PASS | e.g. `2026-11-01T12:44:57.785596+00:00` |
| Timestamps | `updated_at` changes on a status change, `created_at` doesn't | PASS | Checked with a 1 s gap |
| List | `list`, `ls` | PASS | Aligned table with header and separator row |
| List | Empty store | PASS | `No tasks yet. Add one with: …` |
| List | Long title truncated, then `--wide` | PASS | Ends in `...`; `--wide` shows the full text |
| List | `--json` | PASS | Valid JSON array |
| List | Output piped to `head` | FAIL | `unexpected failure: BrokenPipeError`, exit 4 (BUG-5) |
| Filter | `-s todo`, `-s in_progress`, `-s done` | PASS | Correct subsets |
| Filter | `-s in-progress` (hyphen form) | PASS | Accepted |
| Filter | Filter matches nothing | PASS | `No tasks with status 'done'.` |
| Filter | `-s bogus`, `-s ""` | PASS | Lists the valid choices, exit 2 |
| Update | `start <id>`, `done <id>` | PASS | `Task 1 marked as in_progress.` |
| Update | `mark <id> in-progress / IN_PROGRESS / "In Progress" / todo` | PASS | Case-insensitive; going back to `todo` is allowed |
| Update | Setting the status a task already has | PASS | `Task 1 is already in_progress.`; file not rewritten |
| Update | ID `abc`, `0`, `-5`, `1.5` | PASS | `invalid task ID '…' (must be a positive integer)`, exit 2 |
| Update | ID `" 4"`, `01` | PASS | Accepted as 4 and 1 |
| Update | Unknown ID `999`, or a 20-digit ID | PASS | `Task 999 not found.`, exit 1 |
| Update | Missing ID or missing status | PASS | argparse "required", exit 2 |
| Update | `mark 3 finished` | PASS | Lists the valid choices, exit 2 |
| Delete | `delete <id>`, `rm <id>` | PASS | `Deleted task 4: …` |
| Delete | Deleting an already-deleted ID, or `999` | PASS | `Task N not found.`, exit 1 |
| Delete | `delete abc` | PASS | Exit 2 |
| CLI | Unknown command, no command, unknown option | PASS | Clear argparse messages, exit 2 |
| CLI | `--file ""` | FAIL (minor) | Silently uses `./tasks.json` instead (BUG-6) |
| CLI | `TASK_TRACKER_FILE` environment variable | PASS | Covered by the automated suite |
| Persistence | State survives between separate processes | PASS | Every manual step was its own process |
| Missing file | `list` with no `tasks.json` | PASS | Creates `{"version":1,"next_id":1,"tasks":[]}` |
| Missing file | `--file nodir/tasks.json` | PASS | `Directory 'nodir' does not exist…`, exit 3 |
| Missing file | `--file` points at a directory | PASS | `…is a directory, not a file.`, exit 3 |
| Missing file | Unwritable location (`/proc/tasks.json`) | PASS | Exit 3, no traceback. The OS message ("No such file or directory") is slightly confusing |
| Empty file | 0-byte file, then `list` and `add` | PASS | Treated as empty; `add` writes a valid document |
| Empty file | Whitespace-only file, then `list` | PASS | Treated as empty; the file is left as it was |
| Corrupt file | Truncated JSON, `garbage`, `null`, `[]` | PASS | Names the problem (with line and column for JSON errors), exit 3, suggests `recover` |
| Corrupt file | `tasks` is not a list, `tasks` is missing, invalid task, `next_id` is a float | PASS | `invalid schema: …` with a specific reason |
| Corrupt file | Invalid UTF-8 bytes | PASS | `file is not valid UTF-8 text`, exit 3 |
| Corrupt file | `add` against a corrupt file | PASS | Refused; the file stays byte-for-byte the same for all 9 corrupt variants |
| Corrupt file | Recovery hint when the path contains a space | PASS | Shell-quoted: `--file 'my dir/t.json' recover` |
| Recover | One valid entry and one invalid entry | PASS | Backup created; 1 salvaged, 1 discarded; `next_id` kept |
| Recover | Healthy file | PASS | `…is healthy; nothing to recover.` |
| Recover | File from a newer schema version | FAIL | Called "corrupt", and `recover` downgrades it (BUG-3) |
| Recover | Unparseable file | PASS* | Works, but `next_id` goes back to 1 (BUG-6) |
| Atomic write | Temp files left after normal runs and failures | PASS | None left behind (the suite also covers failures injected mid-write) |
| Atomic write | Storage file is a symlink | **FAIL** | The symlink is replaced by a regular file; the real target stops getting updates (BUG-2) |
| Atomic write | Read-only (`chmod 444`) storage file | Note | Overwritten anyway, because rename ignores the file's own mode. Expected POSIX behaviour, but worth documenting |
| Schema | Unknown fields in the file | FAIL | Silently dropped on the next write (BUG-4) |
| Display | Wide (CJK/emoji) characters in the table | FAIL (cosmetic) | Columns shift by the extra display width (BUG-8) |

---

## Bugs found

### BUG-1: Running commands at the same time loses tasks and gives out duplicate IDs (HIGH)

Every command reads the whole file, changes it, then writes it back, with no
lock. When two commands overlap, the later write overwrites the earlier one.
Both commands still report success.

**Reproduce:**
```bash
task-tracker list >/dev/null
for i in $(seq 1 20); do (task-tracker add "p$i" > out.$i) & done; wait
grep -c Added out.*            # 20 success messages
awk '{print $3}' out.* | sort | uniq -d   # IDs announced more than once
python3 -c 'import json;print(len(json.load(open("tasks.json"))["tasks"]))'
```
**Observed:** 20 "Added" messages, but only 7–9 tasks saved. IDs 1, 2, 3 and 5
were each reported to more than one caller. The file stays valid JSON, so this
isn't corruption, but it is silent data loss. Scripts that use the printed ID
may then act on the wrong task. The README lists this as a known limitation,
but only in terms of lost updates; it doesn't mention the false success
messages or the duplicate IDs.

### BUG-2: A symlinked storage file is replaced with a regular file (HIGH)

`os.replace(tmp, path)` swaps out the symlink itself rather than its target.

**Reproduce:**
```bash
mkdir real && task-tracker --file real/tasks.json add seed
ln -s real/tasks.json link.json
task-tracker --file link.json add via-link
ls -l link.json     # now a regular file, mode 600, no longer a symlink
python3 -c 'import json;print(len(json.load(open("real/tasks.json"))["tasks"]))'   # 1
```
**Impact:** after the first write, data is split between two files without any
warning. This commonly hits users who keep `tasks.json` in a dotfiles or
synced folder and symlink to it, including through `TASK_TRACKER_FILE`.

### BUG-3: A newer schema version is called "corrupt", and `recover` downgrades it (MEDIUM)

**Reproduce:**
```bash
echo '{"version": 2, "next_id": 5, "tasks": [{"id":4,"title":"from v2","description":null,"status":"done","created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00","priority":"high"}]}' > tasks.json
task-tracker list       # "is corrupt: invalid schema: schema version 2 is newer…" + "run: task-tracker recover"
task-tracker recover    # succeeds; rewrites the file as version 1; "priority" is gone
```
**Impact:** the error message tells the user to run a command that loses data.
A backup is made, so the data can be restored by hand. The right advice here
is "upgrade task-tracker", not "recover".

### BUG-4: Unknown fields are silently dropped on any write (MEDIUM)

`Task.from_dict` and `parse_document` ignore keys they don't recognise, and
`to_document` writes back only the known keys.

**Reproduce:** add `"priority":"high"` to a task, or `"meta":{…}` at the top
level of `tasks.json`, then run `task-tracker add x`. Both fields are gone.

**Impact:** fields added by hand, or by a newer version of the app, are erased
by an older one. This is the everyday form of BUG-3.

### BUG-5: Piping output into `head` (or anything that closes early) causes "unexpected failure" (LOW)

**Reproduce:** fill the store with about 3000 tasks, then run
`task-tracker list | head -1`.

**Observed:** `error: unexpected failure: BrokenPipeError: [Errno 32] Broken pipe`
and exit code 4. Standard CLI behaviour is to exit quietly when the pipe closes.

### BUG-6: Smaller input and recovery edge cases (LOW)

- `--file ""` falls back to `./tasks.json` without telling the user, because
  `resolve_storage_path` treats an empty string as "not given".
- `recover` on unparseable JSON resets `next_id` to 1. New tasks then reuse IDs
  that exist in the `.corrupt-*` backup, which makes any later manual merge
  harder.

### BUG-7: Titles that look blank, and terminal escape sequences, get through (LOW)

- `task-tracker add $'​'` is accepted, and the task shows a blank title.
  `str.strip()` doesn't remove zero-width or format characters.
- Control characters and ANSI escape sequences in titles and descriptions are
  printed to the terminal as-is: `add $'esc\x1b[31mRED'` turns the rest of the
  line red. If someone else edits a shared `tasks.json`, they could use this to
  inject terminal escape sequences.

### BUG-8: The table is misaligned when it contains wide characters (LOW, cosmetic)

Column widths come from `len()`, which counts code points, not terminal
columns. A title such as `Café ☕ 日本語` pushes the following columns right by
3 characters.

### BUG-9: A title starting with a dash, without `--`, gives a misleading error (LOW, UX)

`task-tracker add -dash` prints `the following arguments are required: title`.
argparse reads `-dash` as an option, so the title the user actually typed seems
to disappear. The README documents `--` for this case, but the error message
doesn't mention it.

---

## Recommended fixes (most severe first)

1. **BUG-1 (High): lock around each command.** Hold an exclusive advisory lock
   on a sidecar file such as `tasks.json.lock` for the whole load → change →
   save cycle. Use `fcntl.flock` on POSIX and `msvcrt.locking` on Windows,
   wrapped in a `JsonStorage.transaction()` context manager that `TaskService`
   uses. Add a regression test that runs N parallel adds and checks that N
   unique IDs are saved.
2. **BUG-2 (High): resolve symlinks before writing.** In `atomic_write_bytes`
   (or `JsonStorage.__init__`), use `path = path.resolve()` (or `os.path.realpath`)
   so the temp file is created next to the real target and replaces it. The
   symlink then stays in place.
3. **BUG-3 (Medium): treat a newer schema version as its own error.** Raise a
   dedicated `UnsupportedVersionError(StorageError)` instead of
   `CorruptStorageError`, with the message "upgrade task-tracker". Don't show
   the `recover` hint for it, and have `recover` refuse to downgrade unless
   given `--force`.
4. **BUG-4 (Medium): keep unknown fields.** Store unrecognised keys on `Task`
   and `TaskStore` (for example in an `extra: dict` field) and write them back
   unchanged.
5. **BUG-5 (Low): handle `BrokenPipeError` in `main()`.** Catch it before the
   generic handler, point stdout at `os.devnull` so the interpreter doesn't
   complain while shutting down, and return 0 (or 141).
6. **BUG-7 (Low): clean up text.** Reject titles that contain no printable
   characters (use `unicodedata.category`, rejecting `C*` and `Zs`-only titles).
   Strip or escape control characters when displaying text, or when saving it.
7. **BUG-6 (Low): fix the small cases.** Make `--file ""` a usage error. In
   recovery, when the JSON is unparseable, set `next_id` past the largest
   number that looks like an ID in the backup, or simply keep the counter from
   the most recent good write.
8. **BUG-9 (Low): improve the dash-title message.** When `add` is missing its
   title and the command line contains an unknown option, suggest
   `task-tracker add -- "<title>"`.
9. **BUG-8 (Low, cosmetic): pad by display width.** Measure width with
   `unicodedata.east_asian_width` (W/F count as 2 columns) when padding
   columns.

## Not covered by this run

- **Python 3.10:** only 3.12 was available, so 3.10 compatibility wasn't
  tested. The code avoids 3.11+ APIs.
- **Windows:** not tested. That includes `os.replace` behaviour when another
  process has the file open, and console encoding.
- **Permission-denied reads and writes:** not testable here because the tests
  ran as root, which bypasses file permissions. Only the `/proc` case was
  checked.
- **Real power loss:** not simulated. Only the automated suite's injected
  `os.replace` / `fsync` failures cover interrupted writes.
