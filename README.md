# kilix-tmux

A small standard-library CLI and Python backend for controlling tmux sessions
through an explicit socket. Derived from tmux-browse's MIT-licensed tmux-cli
core; see [source provenance](PROVENANCE.md). Requires Python 3.10+ and tmux.

**Status:** this repository is not installed on its own. Kilix ships a
vendored derivative of this backend (taken from commit `172bdc5`) as
`config/kilix_tmux`; it answers `kilix tmux --socket PATH VERB ...` and
Kilix Needle's tmux jobs. That copy predates this repository's `type --wait`,
`read --since` and `--max-bytes` options. `KILIX_TMUX_CLI` or
`KILIX_TMUX_MODULE_ROOT` points Kilix at a checkout of this repository instead.

## What it does

- Lists sessions with stable session and pane IDs.
- Creates, renames and closes sessions; sends literal text, typed lines and
  named keys to exact targets.
- Reads bounded pane text and returns a cursor for reading only new output.
- Answers every call with one versioned JSON envelope (`kilix.tmux/v1`), with
  dry runs that validate and resolve without changing a session.

## Quick start

Run directly from a checkout:

```sh
bin/kilix-tmux --socket /absolute/path/to/socket --json list
bin/kilix-tmux --socket /absolute/path/to/socket --json new example
bin/kilix-tmux --socket /absolute/path/to/socket --json read example --lines 40
bin/kilix-tmux --socket /absolute/path/to/socket --json type example 'make test' --wait 120
bin/kilix-tmux --socket /absolute/path/to/socket --json read example --since CURSOR --max-bytes 10000
bin/kilix-tmux --socket /absolute/path/to/socket --json --dry-run close example
```

`python3 -m kilix_tmux` runs the same CLI, and `pip install .` installs it as
the `kilix-tmux` command.

## Usage

| Verb | Arguments | Effect |
|---|---|---|
| `list` | none | Sessions, windows and stable pane IDs |
| `new` | `NAME [--cwd DIR]` | Detached session running tmux's default shell |
| `read` | `TARGET [--lines N \| --since CURSOR] [--max-bytes N]` | Bounded pane text plus a cursor |
| `send` | `TARGET TEXT` | Literal text, no Enter |
| `type` | `TARGET TEXT [--wait SECONDS] [--max-bytes N]` | Text, then a separate Enter |
| `key` | `TARGET KEY...` | Named keys from a fixed allowlist |
| `rename` | `TARGET NEW_NAME` | Rename a session |
| `close` | `TARGET` | Kill a session |

Every verb takes `--socket PATH` (required), `--json` and `--dry-run`.

## How it works

The socket is always required. Listing returns stable session and pane IDs.
Names match exactly; I/O on a session with several panes requires an explicit
pane ID or numeric window/pane target. `send` sends literal text without Enter;
`type` sends text followed by a separate Enter and reports submission, with
completion unknown unless `--wait SECONDS` is given: then it waits for the shell
command to finish and returns `exit_code` and its `output`. Every read returns a
`cursor`; `read --since CURSOR` returns only the new rows, or the visible screen
while a full-screen program runs. `--max-bytes` keeps the first and last
halves. `key` accepts a limited set of named keys. Dry runs validate
and resolve without changing a session.

```python
from kilix_tmux import dispatch

response = dispatch({
    "operation": "read", "socket": "/absolute/path/to/socket",
    "target": "%0", "lines": 40,
})
```

See [CONTRACT.md](CONTRACT.md) for all fields, target rules and error codes.
Kilix and Needle share this backend; they add structured verbs and deterministic
request grammar respectively. Backend tests use fresh private tmux servers:

```sh
python3 -B -m unittest discover -s tests -v
```

The benchmark category compares native tmux, this CLI, Kilix verbs, discovery,
guide/skill, Needle CLI and Needle MCP on the same private fixtures. Held-out
requests and model runs belong to the benchmark owner, outside this repository.

## Documentation

- [CONTRACT.md](CONTRACT.md) — request and response fields, target rules, error codes
- [PROVENANCE.md](PROVENANCE.md) — what was adapted from tmux-cli and what changed

## Related repositories

- [tmux-cli](https://github.com/itsmygithubacct/tmux-cli#readme) — the MIT tmux CLI core this backend derives from
- [tmux-browse](https://github.com/itsmygithubacct/tmux-browse#readme) — the dashboard that vendors tmux-cli
- [kilix](https://github.com/itsmygithubacct/kilix#readme) — carries a vendored copy as `config/kilix_tmux` behind `kilix tmux --socket`
- [kilix-needle](https://github.com/itsmygithubacct/kilix-needle#readme) — drives tmux through Kilix's copy of this backend

## Part of Plebian-OS

kilix-tmux is one of the repositories behind
[Plebian-OS](https://github.com/itsmygithubacct/plebian-os#readme), a Debian
install whose desktop is [Kilix](https://github.com/itsmygithubacct/kilix#readme)
running the [Kilix 95](https://github.com/itsmygithubacct/kilix-95#readme)
desktop through [Pleb](https://github.com/itsmygithubacct/pleb#readme).
It reaches users as the copy vendored inside Kilix, not as an install of its
own. The map of every repository and how it ships is on the
[components page](https://github.com/itsmygithubacct/plebian-os/blob/main/docs/components.md).

## Licence

MIT. See [LICENSE](LICENSE).
