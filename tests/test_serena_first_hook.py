"""Coverage for .claude/hooks/serena-first.py.

The hook's central promise is asymmetric and both halves are tested here:

  * it denies a symbol lookup ONLY while Serena is reachable;
  * it denies nothing at all when Serena is down.

The second half matters more. A hook that blocks Grep and Read while no
symbol tool exists would leave no way to inspect code -- the unrecoverable
guard state that amendment proposal 002 point B names a defect. Reachability
is exercised against a real listening socket rather than a patched function,
so the probe itself is under test.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "serena-first.py"


class _Listener:
    """Stands in for a live Serena dashboard.

    Connections must actually be accepted. A listening socket that never
    accepts fills its backlog after the first probe, and every later connect
    is refused -- which the hook correctly reads as "Serena is down" and
    silently stops asserting anything.
    """

    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(64)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            conn.close()

    def close(self) -> None:
        self._running = False
        self._sock.close()
        self._thread.join(timeout=2)


def run_hook(payload: dict, *, port: int, env_extra: dict | None = None) -> dict | None:
    """Invoke the hook exactly as the harness does; None means 'allowed'."""
    env = {
        **os.environ,
        "SERENA_DASHBOARD_PORT": str(port),
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("DAEDALUS_SERENA_HOOK", None)
    env.update(env_extra or {})

    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=30,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    return json.loads(out) if out else None


def decision(result: dict | None) -> str | None:
    if result is None:
        return None
    return result["hookSpecificOutput"]["permissionDecision"]


class SerenaFirstHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.listener = _Listener()
        cls.live_port = cls.listener.port

        # A port nobody listens on. Bind, read the port, close it again.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        cls.dead_port = probe.getsockname()[1]
        probe.close()

        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)

        cls.big_py = tmp / "ledger.py"
        cls.big_py.write_text("x = 1\n" * 400, encoding="utf-8")

        cls.small_py = tmp / "tiny.py"
        cls.small_py.write_text("x = 1\n" * 10, encoding="utf-8")

        cls.doc = tmp / "notes.md"
        cls.doc.write_text("# heading\n" * 400, encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.listener.close()
        cls.tmp.cleanup()

    # ---- Grep -----------------------------------------------------------

    def test_definition_grep_is_denied_while_serena_runs(self) -> None:
        for pattern in ("def build_receipt", "class Ledger", "function render",
                        "interface Props", "^struct Node", "fn main", "enum Kind"):
            with self.subTest(pattern=pattern):
                result = run_hook(
                    {"tool_name": "Grep", "tool_input": {"pattern": pattern}},
                    port=self.live_port,
                )
                self.assertEqual(decision(result), "deny")
                self.assertIn("find_symbol", result["hookSpecificOutput"]
                              ["permissionDecisionReason"])

    def test_plain_text_grep_is_allowed(self) -> None:
        for pattern in ("TODO", "bias_voltage", "raise ValueError",
                        "import json", "classification"):
            with self.subTest(pattern=pattern):
                result = run_hook(
                    {"tool_name": "Grep", "tool_input": {"pattern": pattern}},
                    port=self.live_port,
                )
                self.assertIsNone(decision(result))

    def test_classification_substring_does_not_trigger(self) -> None:
        """'class' inside 'classification' is not a declaration keyword."""
        result = run_hook(
            {"tool_name": "Grep", "tool_input": {"pattern": "classifier|subclassing"}},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))

    # ---- Read -----------------------------------------------------------

    def test_whole_read_of_large_source_is_denied(self) -> None:
        result = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": str(self.big_py)}},
            port=self.live_port,
        )
        self.assertEqual(decision(result), "deny")
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("get_symbols_overview", reason)
        self.assertIn("400", reason)

    def test_targeted_read_is_allowed(self) -> None:
        result = run_hook(
            {"tool_name": "Read",
             "tool_input": {"file_path": str(self.big_py), "offset": 10, "limit": 40}},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))

    def test_small_source_file_is_allowed(self) -> None:
        result = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": str(self.small_py)}},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))

    def test_non_source_file_is_allowed(self) -> None:
        result = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": str(self.doc)}},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))

    def test_read_allowed_once_serena_touched_the_file(self) -> None:
        transcript = Path(self.tmp.name) / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"tool_name": "mcp__serena__get_symbols_overview",
                        "tool_input": {"relative_path": "ledger.py"}}) + "\n",
            encoding="utf-8",
        )
        result = run_hook(
            {"tool_name": "Read",
             "tool_input": {"file_path": str(self.big_py)},
             "transcript_path": str(transcript)},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))

    def test_read_still_denied_when_transcript_names_another_file(self) -> None:
        transcript = Path(self.tmp.name) / "other.jsonl"
        transcript.write_text(
            json.dumps({"tool_name": "mcp__serena__find_symbol",
                        "tool_input": {"relative_path": "router.py"}}) + "\n",
            encoding="utf-8",
        )
        result = run_hook(
            {"tool_name": "Read",
             "tool_input": {"file_path": str(self.big_py)},
             "transcript_path": str(transcript)},
            port=self.live_port,
        )
        self.assertEqual(decision(result), "deny")

    # ---- fail-open ------------------------------------------------------

    def test_nothing_is_denied_when_serena_is_unreachable(self) -> None:
        """The load-bearing guarantee: no Serena, no blocking."""
        for payload in (
            {"tool_name": "Grep", "tool_input": {"pattern": "def build_receipt"}},
            {"tool_name": "Read", "tool_input": {"file_path": str(self.big_py)}},
        ):
            with self.subTest(tool=payload["tool_name"]):
                result = run_hook(payload, port=self.dead_port)
                self.assertIsNone(decision(result))

    def test_env_switch_disables_the_hook(self) -> None:
        result = run_hook(
            {"tool_name": "Grep", "tool_input": {"pattern": "def build_receipt"}},
            port=self.live_port,
            env_extra={"DAEDALUS_SERENA_HOOK": "off"},
        )
        self.assertIsNone(decision(result))

    # ---- robustness -----------------------------------------------------

    def test_unrelated_tools_pass_through(self) -> None:
        for tool in ("Bash", "Edit", "Write", "Glob", "WebFetch"):
            with self.subTest(tool=tool):
                result = run_hook(
                    {"tool_name": tool, "tool_input": {"pattern": "def x",
                                                       "file_path": str(self.big_py)}},
                    port=self.live_port,
                )
                self.assertIsNone(decision(result))

    def test_malformed_payloads_never_block(self) -> None:
        for payload in ({}, {"tool_name": "Grep"},
                        {"tool_name": "Grep", "tool_input": {}},
                        {"tool_name": "Grep", "tool_input": {"pattern": ""}},
                        {"tool_name": "Read", "tool_input": {"file_path": None}}):
            with self.subTest(payload=payload):
                self.assertIsNone(decision(run_hook(payload, port=self.live_port)))

    def test_missing_file_does_not_block(self) -> None:
        result = run_hook(
            {"tool_name": "Read",
             "tool_input": {"file_path": str(Path(self.tmp.name) / "gone.py")}},
            port=self.live_port,
        )
        self.assertIsNone(decision(result))


if __name__ == "__main__":
    unittest.main()
