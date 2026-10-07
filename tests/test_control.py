import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from kilix_tmux import dispatch

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def test_invalid_requests_never_invoke_tmux(self):
        base = {"operation": "send", "socket": "/tmp/unused", "target": "fixture", "text": "hello"}
        requests = [None, [], {}, dict(base, operation=[]),
                    {k: v for k, v in base.items() if k != "socket"},
                    dict(base, socket="relative"), dict(base, target="fix*"),
                    dict(base, target="-x"), dict(base, target="fixture:window"),
                    dict(base, text=""), dict(base, text="line\nEnter"),
                    dict(base, text="\x1b[31m"), dict(base, text="x" * 65537),
                    dict(base, dry_run="false"), dict(base, schema="v2"),
                    dict(base, command="extra"),
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "lines": True},
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "lines": 2001},
                    {"operation": "key", "socket": "/tmp/unused", "target": "fixture", "keys": ["Enter", "-l"]},
                    {"operation": "key", "socket": "/tmp/unused", "target": "fixture", "keys": []},
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "since": "1:0:00000000", "lines": 5},
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "since": "12"},
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "since": 12},
                    {"operation": "read", "socket": "/tmp/unused", "target": "fixture", "max_bytes": 10},
                    dict(base, operation="type", wait=0), dict(base, operation="type", wait=601),
                    dict(base, operation="type", wait=True), dict(base, operation="type", wait="5"),
                    dict(base, operation="type", max_bytes=1000),
                    dict(base, operation="type", wait=1, text="x" * 65530),
                    dict(base, wait=1)]
        with patch("kilix_tmux.control.subprocess.run") as run:
            for request in requests:
                with self.subTest(request=str(request)[:100]):
                    self.assertEqual(dispatch(request)["code"], "EUSAGE")
            run.assert_not_called()

    def test_timeout_and_missing_executable_are_errors(self):
        req = {"operation": "list", "socket": "/tmp/unused"}
        for exc, code in [(FileNotFoundError(), "ETMUX"),
                          (subprocess.TimeoutExpired("tmux", 5), "ETIMEDOUT")]:
            with patch("kilix_tmux.control.subprocess.run", side_effect=exc):
                self.assertEqual(dispatch(req)["code"], code)

    def test_type_partial_failure_reports_sent_but_not_submitted(self):
        from kilix_tmux.control import ControlError
        sessions = [{"id": "$1", "name": "fixture", "panes": [{"id": "%2"}]}]
        with patch("kilix_tmux.control._snapshot", return_value=sessions), \
             patch("kilix_tmux.control._send_literal") as send, \
             patch("kilix_tmux.control._run", side_effect=ControlError("ETMUX", "lost pane")) as run:
            response = dispatch({"operation": "type", "socket": "/tmp/unused", "target": "fixture", "text": "hello"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["details"]["sent"], 5)
        self.assertFalse(response["details"]["submitted"])
        send.assert_called_once_with("/tmp/unused", "%2", "hello")
        self.assertEqual(run.call_args.args[-1], "Enter")

    def test_sentinel_keeps_the_command_line_valid(self):
        from kilix_tmux.control import _with_sentinel
        tail = " printf '\\n__KT_%s_%s__\\n' abc \"$?\""
        self.assertEqual(_with_sentinel("make test", "abc"), "make test;" + tail)
        self.assertEqual(_with_sentinel("server &  ", "abc"), "server &" + tail)
        self.assertEqual(_with_sentinel("a && b", "abc"), "a && b;" + tail)
        self.assertEqual(_with_sentinel("cd /tmp;", "abc"), "cd /tmp;" + tail)

    def test_limit_keeps_head_and_tail(self):
        from kilix_tmux.control import _limit
        text = "".join(f"{n}\n" for n in range(1, 1001))
        self.assertEqual(_limit(text, None), (text, 0))
        cut, omitted = _limit(text, 300)
        self.assertTrue(cut.startswith("1\n2\n"))
        self.assertTrue(cut.endswith("999\n1000\n"))
        self.assertIn(f"[... {omitted} bytes omitted by kilix-tmux ...]", cut)
        self.assertEqual(omitted, len(text.encode()) - 300)

    def test_buffer_failure_cleans_up_and_does_not_enter(self):
        from kilix_tmux.control import ControlError, _send_literal
        with patch("kilix_tmux.control._run", side_effect=["", ControlError("ETMUX", "lost pane"), ""]) as run:
            with self.assertRaises(ControlError):
                _send_literal("/tmp/unused", "%2", "literal;")
        self.assertEqual(run.call_args_list[0].kwargs["input_text"], "literal;")
        self.assertEqual(run.call_args_list[0].args[1], "load-buffer")
        self.assertEqual(run.call_args_list[-1].args[1], "delete-buffer")


@unittest.skipUnless(__import__("shutil").which("tmux"), "tmux unavailable")
class PrivateServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kt-test-")
        self.directory = Path(self.tmp.name)
        self.socket = str(self.directory / "socket")
        self.env = dict(os.environ, HOME=self.tmp.name, PS1="fixture> ", TERM="xterm-256color")
        self.env.pop("TMUX", None)
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "fixture", "-x", "200", "-y", "30",
                  "/bin/bash --noprofile --norc")
        self.tmux("set-option", "-g", "default-shell", "/bin/bash")
        self.tmux("set-option", "-g", "default-command", "/bin/bash --noprofile --norc")

    def tearDown(self):
        try:
            subprocess.run(["tmux", "-S", self.socket, "kill-server"], env=self.env,
                           capture_output=True, timeout=5)
        finally:
            self.tmp.cleanup()

    def tmux(self, *args):
        return subprocess.run(["tmux", "-S", self.socket, *args], env=self.env,
                              capture_output=True, text=True, timeout=5, check=True).stdout

    def call(self, operation, **fields):
        result = dispatch(dict(operation=operation, socket=self.socket, **fields))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema"], "kilix.tmux/v1")
        return result["data"]

    def await_receipt(self, path, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if path.exists() and path.read_bytes() == expected.encode():
                return
            time.sleep(.02)
        self.fail(f"no target execution receipt: {path}")

    def test_lifecycle_stable_ids_and_dry_run(self):
        initial = self.call("list")["sessions"]
        self.assertEqual(initial[0]["name"], "fixture")
        self.call("new", name="new_session", cwd=self.tmp.name, dry_run=True)
        self.assertEqual(self.call("list")["sessions"], initial)
        created = self.call("new", name="new_session", cwd=self.tmp.name)["session"]
        self.assertEqual(dispatch(dict(operation="new", socket=self.socket, name="new_session"))["code"], "EEXIST")
        self.call("rename", target=created["id"], new_name="renamed", dry_run=True)
        self.assertIn("new_session", [s["name"] for s in self.call("list")["sessions"]])
        renamed = self.call("rename", target=created["id"], new_name="renamed")["session"]
        self.assertEqual(renamed["id"], created["id"])
        self.call("close", target=created["id"], dry_run=True)
        self.call("close", target="renamed")
        self.assertEqual([s["name"] for s in self.call("list")["sessions"]], ["fixture"])

    def test_no_prefix_or_wildcard_targeting(self):
        self.call("new", name="fixture_longer")
        for op, fields in [("read", {}), ("send", {"text": "hello"}),
                           ("type", {"text": "hello"}), ("key", {"keys": ["Enter"]}),
                           ("rename", {"new_name": "bad"}), ("close", {})]:
            response = dispatch(dict(operation=op, socket=self.socket, target="fixt", **fields))
            self.assertEqual(response["code"], "ENOENT")
        self.assertEqual(len(self.call("list")["sessions"]), 2)

    def test_send_never_submits_and_key_enter_executes_in_target(self):
        receipt = self.directory / "receipt"
        text = f"printf '%s' 'literal $(echo unexpected); \"quotes\"' > {shlex.quote(str(receipt))}"
        pane = self.call("list")["sessions"][0]["panes"][0]["id"]
        result = self.call("send", target=pane, text=text)
        self.assertFalse(result["submitted"])
        time.sleep(.1)
        self.assertFalse(receipt.exists())
        submitted = self.call("key", target=pane, keys=["Enter"])
        self.assertTrue(submitted["submitted"])
        self.await_receipt(receipt, 'literal $(echo unexpected); "quotes"')

    def test_type_returns_submission_and_real_target_receipt(self):
        receipt = self.directory / "receipt"
        self.call("type", target="fixture", text=f"printf '%s' '✓ done' > {shlex.quote(str(receipt))}", dry_run=True)
        self.assertFalse(receipt.exists())
        result = self.call("type", target="fixture", text=f"printf '%s' '✓ done' > {shlex.quote(str(receipt))}")
        self.assertTrue(result["submitted"])
        self.assertEqual(result["completion"], "unknown")
        self.await_receipt(receipt, "✓ done")

    def test_trailing_semicolon_preserved_byte_for_byte_without_enter(self):
        # A raw reader records bytes received by the target, independent of
        # capture-pane rendering or shell echo. No benchmark prompts here.
        receipt = self.directory / "bytes"
        reader = self.directory / "reader.py"
        reader.write_text("import os, tty\nfrom pathlib import Path\ntty.setraw(0)\n"
                          f"p=Path({str(receipt)!r})\n"
                          "while True:\n b=os.read(0,1)\n with p.open('ab') as f: f.write(b)\n")
        pane = self.tmux("new-window", "-d", "-t", "=fixture:", "-P", "-F", "#{pane_id}",
                         f"{shlex.quote(sys.executable)} -u {shlex.quote(str(reader))}").strip()
        time.sleep(.1)
        payload = "literal $HOME `never_run` 'quotes' ✓;"
        result = self.call("send", target=pane, text=payload)
        self.assertFalse(result["submitted"])
        self.await_receipt(receipt, payload)
        self.assertEqual(receipt.read_bytes(), payload.encode())
        result = self.call("type", target=pane, text=payload)
        self.assertTrue(result["submitted"])
        self.await_receipt(receipt, payload + payload + "\r")

    def test_ambiguous_session_refused_explicit_panes_work(self):
        self.tmux("split-window", "-d", "-t", "=fixture:", "/bin/bash --noprofile --norc")
        for op, fields in [("read", {}), ("send", {"text": "hello"}),
                           ("type", {"text": "hello"}), ("key", {"keys": ["Enter"]})]:
            result = dispatch(dict(operation=op, socket=self.socket, target="fixture", **fields))
            self.assertEqual(result["code"], "EAMBIGUOUS")
        panes = self.call("list")["sessions"][0]["panes"]
        for pane in panes:
            self.call("read", target=pane["id"], lines=1)
            self.call("read", target=f"fixture:{pane['window']}.{pane['index']}", lines=1)

    def test_read_bound_and_literal_dash(self):
        self.call("send", target="fixture", text="-n does not become a tmux flag")
        time.sleep(.05)
        self.assertIn("-n does not become a tmux flag", self.call("read", target="fixture")["text"])
        self.call("key", target="fixture", keys=["C-u"])
        receipt = self.directory / "done"
        self.call("type", target="fixture", text=f"printf '1\\n2\\n3\\n'; touch {shlex.quote(str(receipt))}")
        self.await_receipt(receipt, "")
        text = self.call("read", target="fixture", lines=2)["text"]
        self.assertLessEqual(len(text.splitlines()), 2)
        self.assertIn("3", text)

    def await_read(self, cursor, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            data = self.call("read", target="fixture", since=cursor)
            if predicate(data) or time.monotonic() > deadline:
                return data
            time.sleep(.05)

    def test_type_wait_reports_exit_code_and_only_command_output(self):
        self.call("type", target="fixture", text="echo before", wait=5)
        result = self.call("type", target="fixture", text="printf 'a\\nb\\n'; (exit 3)", wait=5)
        self.assertEqual((result["completion"], result["exit_code"], result["kind"]), ("done", 3, "since"))
        self.assertEqual(result["output"], "a\nb\n")
        self.assertFalse(result["truncated"])
        result = self.call("type", target="fixture", text="true", wait=5)
        self.assertEqual((result["exit_code"], result["output"]), (0, ""))
        result = self.call("type", target="fixture", text="sleep 1 &", wait=5)
        self.assertEqual((result["completion"], result["exit_code"]), ("done", 0))
        self.assertEqual(self.call("type", target="fixture", text="echo x", wait=5, dry_run=True)["dry_run"], True)

    def test_type_wait_timeout_leaves_command_running_and_since_sees_it_finish(self):
        result = self.call("type", target="fixture", text="sleep 1; echo late", wait=.3)
        self.assertEqual(result["completion"], "timeout")
        self.assertNotIn("exit_code", result)
        self.assertNotIn("late", result["output"])
        later = self.await_read(result["cursor"], lambda d: "late" in d["text"])
        self.assertEqual(later["kind"], "since")
        self.assertIn("late", later["text"])
        self.assertNotIn("__KT_", later["text"])
        self.assertNotIn("printf '\\n", later["text"])

    def test_read_since_returns_only_new_rows_and_caps_bytes(self):
        self.call("type", target="fixture", text="echo old-output", wait=5)
        cursor = self.call("read", target="fixture")["cursor"]
        self.call("type", target="fixture", text="echo new-output", wait=5)
        data = self.call("read", target="fixture", since=cursor)
        self.assertEqual(data["kind"], "since")
        self.assertIn("new-output", data["text"])
        self.assertNotIn("old-output", data["text"])
        again = self.call("read", target="fixture", since=data["cursor"])
        self.assertNotIn("new-output", again["text"])
        result = self.call("type", target="fixture", text="seq 1 500", wait=5, max_bytes=256)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["output"].startswith("1\n2\n"))
        self.assertTrue(result["output"].endswith("499\n500\n"))
        capped = self.call("read", target="fixture", lines=2000, max_bytes=256)
        self.assertTrue(capped["truncated"])
        self.assertLessEqual(len(capped["text"].encode()), 256 + 64)  # plus the omission note

    def test_cleared_screen_makes_cursor_lost_not_wrong(self):
        self.call("type", target="fixture", text="seq 1 8", wait=5)
        cursor = self.call("read", target="fixture")["cursor"]
        self.call("type", target="fixture", text="clear", wait=5)
        self.call("type", target="fixture", text="seq 101 120", wait=5)
        data = self.call("read", target="fixture", since=cursor)
        self.assertEqual((data["kind"], data["reason"]), ("screen", "cursor_lost"))
        self.assertIn("120", data["text"])

    def test_full_screen_programs_read_as_visible_screen(self):
        # Terminus-2's fallback: a scrollback diff is meaningless while a
        # program owns the alternate screen, so read the rendered screen.
        page = self.directory / "page.txt"
        page.write_text("".join(f"page line {n}\n" for n in range(1, 61)))
        for program, quit_text, quit_keys in [(f"less {shlex.quote(str(page))}", "q", None),
                                              (f"vim -u NONE -N -n {shlex.quote(str(page))}", ":q!", ["Enter"])]:
            with self.subTest(program=program.split()[0]):
                before = self.call("read", target="fixture")["cursor"]
                self.call("type", target="fixture", text=program)
                data = self.await_read(before, lambda d: "page line 1" in d["text"] and d["kind"] == "screen")
                self.assertEqual((data["kind"], data["reason"]), ("screen", "alternate_screen"))
                self.assertIn("page line 1\n", data["text"])
                self.assertNotIn("page line 60", data["text"])  # only the 30-row screen
                self.assertTrue(self.call("read", target="fixture")["alternate_screen"])
                self.call("send", target="fixture", text=quit_text)
                if quit_keys:
                    self.call("key", target="fixture", keys=quit_keys)
                after = self.await_read(before, lambda d: d["kind"] == "since")
                self.assertEqual(after["kind"], "since")
                self.assertFalse(self.call("read", target="fixture")["alternate_screen"])
                self.assertNotIn("page line 30", after["text"])
                self.call("key", target="fixture", keys=["C-u"])

    def test_text_naming_a_key_is_typed_not_pressed(self):
        receipt = self.directory / "bytes"
        reader = self.directory / "reader.py"
        reader.write_text("import os, tty\nfrom pathlib import Path\ntty.setraw(0)\n"
                          f"p=Path({str(receipt)!r})\n"
                          "while True:\n b=os.read(0,1)\n with p.open('ab') as f: f.write(b)\n")
        pane = self.tmux("new-window", "-d", "-t", "=fixture:", "-P", "-F", "#{pane_id}",
                         f"{shlex.quote(sys.executable)} -u {shlex.quote(str(reader))}").strip()
        time.sleep(.1)
        for name in ("Enter", "C-c", "Escape"):
            self.call("send", target=pane, text=name)
        self.await_receipt(receipt, "EnterC-cEscape")
        self.assertEqual(dispatch(dict(operation="key", socket=self.socket, target=pane, keys=["q"]))["code"], "EUSAGE")

    def test_explicit_other_socket_cannot_reach_fixture(self):
        other = str(self.directory / "other")
        self.assertEqual(dispatch(dict(operation="list", socket=other))["data"]["sessions"], [])
        self.assertEqual(dispatch(dict(operation="close", socket=other, target="fixture"))["code"], "ENOSERVER")
        self.assertEqual(self.call("list")["sessions"][0]["name"], "fixture")

    def test_cli_flags_envelope_exit_codes_and_help(self):
        for argv in [("--socket", self.socket, "--json", "list"),
                     ("list", "--json", "--socket", self.socket)]:
            proc = subprocess.run([sys.executable, "-B", "-m", "kilix_tmux", *argv], cwd=ROOT,
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["ok"])
        proc = subprocess.run([sys.executable, "-B", "-m", "kilix_tmux", "--socket", self.socket, "--json",
                               "type", "fixture", "exit_status_probe() { return 4; }; exit_status_probe",
                               "--wait", "5"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual((data["completion"], data["exit_code"]), ("done", 4))
        proc = subprocess.run([sys.executable, "-B", "-m", "kilix_tmux", "--socket", self.socket, "--json",
                               "read", "fixture", "--since", data["cursor"], "--max-bytes", "300"],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(proc.stdout)["data"]["kind"], "since")
        proc = subprocess.run([str(ROOT / "bin/kilix-tmux"), "--json", "close", "fixture"],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["code"], "EUSAGE")


if __name__ == "__main__":
    unittest.main()
