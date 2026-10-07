# kilix-tmux

A small standard-library CLI and Python backend for controlling tmux sessions
through an explicit socket. Derived from tmux-browse's MIT-licensed tmux-cli
core; see [source provenance](PROVENANCE.md). Requires Python 3.10+ and tmux.

Run directly from a checkout:

```sh
bin/kilix-tmux --socket /absolute/path/to/socket --json list
bin/kilix-tmux --socket /absolute/path/to/socket --json new example
bin/kilix-tmux --socket /absolute/path/to/socket --json read example --lines 40
bin/kilix-tmux --socket /absolute/path/to/socket --json type example 'make test' --wait 120
bin/kilix-tmux --socket /absolute/path/to/socket --json read example --since CURSOR --max-bytes 10000
bin/kilix-tmux --socket /absolute/path/to/socket --json --dry-run close example
```

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
