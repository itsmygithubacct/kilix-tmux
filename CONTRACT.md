# Tmux control contract

API: `from kilix_tmux import dispatch`; call `dispatch(request)`.
CLI: `bin/kilix-tmux --socket /absolute/path --json VERB ...`.
Python CLI: `python3 -m kilix_tmux --socket /absolute/path --json VERB ...`.
Discovery: `KILIX_TMUX_CLI` may select the executable; `KILIX_TMUX_MODULE_ROOT`
may select this import root. Neither selects a socket. There is no socket
environment or default-server fallback. The socket is mandatory on every call.

Requests are objects with `operation`, `socket`, and optional boolean
`dry_run` (default false). Optional `schema` must be `kilix.tmux.request/v1`.
Unknown fields and wrong types are usage errors. Operations:

| Operation | Fields | Result |
| --- | --- | --- |
| list | none | `sessions`, each with stable `id`, `name`, `windows`, `attached`, and `panes` |
| new | `name`, optional absolute existing `cwd` | `session` with stable ID, name and panes |
| read | `target`; optional integer `lines` (1–2000, default 80) or `since` cursor; optional `max_bytes` | `target` stable pane ID, `text`, `kind`, `cursor`, `truncated`, `omitted_bytes`; `lines` and `alternate_screen` for a lines read; `reason` for a screen read |
| send | `target`, `text` | `target`, `sent`, `submitted: false` |
| type | `target`, `text`; optional `wait` seconds (above 0, at most 600) with optional `max_bytes` | `target`, `sent`, `submitted: true`, `completion: "unknown"`; with `wait`: `completion` `"done"` (plus `exit_code`) or `"timeout"`, `output`, `kind`, `cursor`, `truncated`, `omitted_bytes`, `seconds` |
| key | `target`, nonempty `keys` string list | `target`, `keys`, `submitted` (true if Enter), `completion: "unknown"` |
| rename | `target`, `new_name` | `session` with stable ID and new name |
| close | `target` | `closed` stable session ID |

Targets are exact session names, stable session IDs (`$N`), stable pane IDs
(`%N`, I/O only), or `NAME:WINDOW.PANE` with numeric indices (I/O only).
Session-only I/O requires exactly one pane in the session; otherwise
`EAMBIGUOUS`. Never use tmux prefix/fnmatch lookup. Names use
`[A-Za-z0-9_][A-Za-z0-9_-]*`, maximum 128 characters. The listing reports
unsupported external names but they can still be addressed by stable ID.
Lifecycle operations accept only session names or stable session IDs.

Text must be a nonempty string without control characters except tab.
It is literal data, never interpreted by the controller. `send` does not
append Enter; `type` sends literal text and then a separate Enter invocation.
Literal text uses a unique named stdin-loaded tmux buffer, preserving trailing
semicolons. If the Enter call fails after text delivery, the error envelope
includes `details` with `sent`, `submitted: false`, and `completion: "unknown"`.
The controller never selects a shell command for a new session: tmux starts
its configured default shell. Text length is limited to 65536 characters.
Keys: Enter, Tab, Escape, BSpace, Space, Up, Down, Left, Right, Home, End,
PageUp, PageDown, Delete, C-c, C-d, C-u, C-a, C-e, C-l. At most 16 per call.

Reading new output. Every non-dry-run read, and every `type` with `wait`,
returns an opaque `cursor` naming the pane's cursor row. A later
`read` with `since: CURSOR` returns only the rows from that row to the current
cursor row (`kind: "since"`); the cursor row itself is repeated because it may
still be growing. `since` and `lines` are mutually exclusive. A cursor holds
the row's absolute position, the history size then, and a hash of the row above
it. When those no longer agree (after `clear`, a history trim at
`history-limit`, or a resize reflow), or when a program holds the alternate
screen (vim, less, top), the read returns the rendered visible screen instead,
with `kind: "screen"` and `reason` `"cursor_lost"` or `"alternate_screen"`. It
never silently skips or repeats rows. A cursor is meaningful only for the pane
that issued it. A lines read keeps its old capture and reports
`alternate_screen`. Rows are returned without trailing padding.

`max_bytes` (256–1048576) caps returned text by keeping the first and last
halves around a `[... N bytes omitted by kilix-tmux ...]` note; `truncated`
and `omitted_bytes` report it. Reads have no cap unless `max_bytes` is given;
`type` with `wait` defaults to 10000.

Completion. `type` with `wait` appends `; printf '\n__KT_%s_%s__\n' TOKEN "$?"`
to the typed line (a single space instead of `; ` after a trailing `&` or `;`),
with a fresh random 16-hex TOKEN per call, and polls the pane until
`__KT_TOKEN_N__` appears or `wait` seconds pass. The shell's echo of the line
cannot match, because it shows the `%s` format. `done` reports `exit_code` N
and `output`: the rows between the echoed command line and the marker. `timeout`
reports what has printed so far; the command is never killed or retyped (send
`key` C-c to stop it), and its marker is removed from later reads. It assumes
a POSIX shell (`$?`) at a prompt and one complete command line; a trailing
comment or an unfinished line (`a &&`) leaves the sentinel unreached, so the
call times out. The appended sentinel enters the shell's history. Reads strip
the sentinel from echoed command lines and drop marker rows.

`dry_run: true` validates the entire request and resolves targets against the
specified socket. New/rename duplicate checks apply. No mutation occurs;
`data` contains `operation`, `dry_run: true`, normalized `request`, and
resolved `target` where relevant. List still reads its snapshot. Read plans
resolve without capturing. No dry-run implies execution or submission.

All responses have `schema: "kilix.tmux/v1"` and `ok`. Success: `data`
contains `operation`, `dry_run`, and operation fields above. Errors:
`error` (message), `code`, `exit`. CLI exit code matches `exit`.

| Code | Exit | Meaning |
| --- | --- | --- |
| EUSAGE | 2 | malformed request, target, socket, text or key |
| ENOENT | 3 | exact session/pane absent |
| EEXIST | 4 | new/rename name already exists |
| ETIMEDOUT | 5 | tmux subprocess deadline exceeded |
| ENOSERVER | 6 | missing/dead socket for operations requiring a target |
| ETMUX | 7 | tmux unavailable or command/snapshot failed |
| EAMBIGUOUS | 8 | session has multiple possible I/O panes |

An absent server yields an empty list; new may start a server at that exact
socket. Unresponsive or malformed snapshots are errors, never empty lists.
All subprocesses use argument arrays and the explicit `-S` socket. No
dashboard, HTTP server, session logger, setup rewrite or live-server discovery.

Needle integration: `kilix-needle tmux --socket PATH REQUEST`; MCP
`kilix_tmux_plan` / `kilix_tmux_act` with required `socket`. The grammar is
owned by Needle and must refuse unsupported or compound requests. Kilix
integration: `kilix tmux --socket PATH [--json] VERB ...`, same derivative.
