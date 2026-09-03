"""What `python -m daedalus.interfaces.cli.token_monitor` starts with, and what it writes.

Two claims, one instrument.

1. THE TAIL STARTS AT THE BOUNDARY. The module has a second door: the
   ``if __name__ == "__main__"`` tail is reachable without passing
   ``daedalus.interfaces.cli.entry:main``'s dispatch, so adding the ``daedalus tokens``
   subcommand did not close it -- it added a door beside it. The boundary
   therefore lives at the top of ``main()``, where both doors pass it, and this
   proves it from the tail's side. Same argument and same shape as
   ``tests/test_loop_entrypoint_guard.py`` (72b5af82).

2. IT WRITES ONLY ITS OWN REPORT. The registry row declares
   ``FILESYSTEM_WRITE`` and names three roots: ``memory/`` for the report it
   produces, plus the budget lock file and the spine WAL sidecars, which exist
   only because it READS those two stores. A monitor that quietly wrote
   anywhere else -- into the ledger it reads, into the repository it watches --
   would be enforcement wearing an observability label, and the registry row
   would be a lie a reviewer reads instead of the code.

The instrument is ``sys.addaudithook``, not a mock. A mock proves a particular
call happened; the audit hook reports every write the interpreter performs, in
order, whichever module performs it -- including a write nobody thought to
mock. It runs in a child process because an audit hook cannot be removed once
added, and the child imports everything and builds its fixtures BEFORE arming
the hook, so the trace covers the verb and not the cost of importing Python.

HONEST LIMIT, stated because a probe advertised as total and quietly partial is
worse than a narrow one: the ``open`` audit event covers writes that go through
the interpreter. SQLite reaches its file through C, so the spine's WAL sidecars
do not appear in this trace at all; they are declared on the registry row and
bounded by ``read_only=True`` (mode=ro fails any write at the engine), not by
this test. What this test does cover is every Python-level write, which is the
report itself and the budget lock.

MUTATION NOTE: delete the ``begin_effect`` call in ``token_monitor.main`` and
the boundary probe goes red. Point ``STATUS_PATH`` anywhere outside the
declared roots -- or make ``_budget_view`` call ``reserve`` instead of
``state`` -- and the write-root probe goes red with the offending path named.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "AUDIT-TRACE:"

# Runs in a child interpreter, with -B so bytecode writes never enter the
# trace. argv[1] is the sandbox root; every store the verb touches is
# redirected under it, so "wrote outside a declared root" and "wrote outside
# the sandbox" are the same assertion.
CHILD = r'''
import json, os, sys
from pathlib import Path

TMP = Path(sys.argv[1])
MEM = TMP / "memory"
MEM.mkdir(parents=True, exist_ok=True)
(TMP / "budget").mkdir(parents=True, exist_ok=True)
(TMP / "spine").mkdir(parents=True, exist_ok=True)
(TMP / "repo").mkdir(parents=True, exist_ok=True)
os.environ["DAEDALUS_BUDGET_LEDGER"] = str(TMP / "budget" / "ledger.json")
os.environ["DAEDALUS_SPINE_DB"] = str(TMP / "spine" / "spine.sqlite3")

import daedalus.budget as budget
import daedalus.memory as memory
import daedalus.interfaces.cli.token_monitor as tm
import daedalus.spine.effect_boundary as boundary
from daedalus.spine.ledger import SpineLedger

# A real spine database to read, created HERE -- before the hook is armed and
# by a writable handle that is not the verb's. The verb must never be the
# thing that brings a spine database into existence, which is why _spine_view
# checks existence first; this fixture is what lets the read path run at all.
SpineLedger(os.environ["DAEDALUS_SPINE_DB"]).close()
budget.reset_default_ledger()

memory.MEMORY_DIR = MEM
memory.EVENTS_PATH = MEM / "events.local.jsonl"
memory.TODO_PATH = MEM / "todos.local.md"
tm.MEMORY_DIR = MEM
tm.STATUS_PATH = MEM / "token_status.local.json"
# The real reader walks ~/.claude and greps every transcript. Covered by
# tests/test_hardening.py; here it would only make the trace slow and
# machine-dependent. A rate-limit sample is injected so the CHECKPOINT branch
# runs -- the branch that appends to the journal and rewrites the TODO
# snapshot, i.e. the one that writes the most.
tm.read_usage_samples = lambda repo_root=None, max_files=20: [
    tm.UsageSample(
        path="synthetic",
        timestamp="2026-08-22T00:00:00Z",
        session_id="s",
        model="m",
        api_error_status=429,
        text="rate limited",
    )
]

events = []
_real_begin = boundary.begin_effect
_real_guard = budget.install_process_guard


def _traced_begin(*args, **kwargs):
    receipt = _real_begin(*args, **kwargs)
    sys.audit("daedalus.trace.effect_started", str(args[0]))
    return receipt


def _traced_guard():
    sys.audit("daedalus.trace.guard_installed")
    return _real_guard()


boundary.begin_effect = _traced_begin
budget.install_process_guard = _traced_guard


def hook(event, args):
    if event == "daedalus.trace.guard_installed":
        events.append(["guard", ""])
    elif event == "daedalus.trace.effect_started":
        events.append(["boundary", str(args[0])])
    elif event in ("subprocess.Popen", "os.exec", "os.posix_spawn"):
        events.append(["spawn", str(args[0])])
    elif event in ("socket.connect", "socket.getaddrinfo", "urllib.Request"):
        events.append(["network", event])
    elif event == "open":
        path, mode, flags = args
        writing = False
        if isinstance(mode, str):
            writing = any(flag in mode for flag in "wax+")
        elif mode is None:
            writing = bool(
                int(flags)
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
            )
        if writing:
            events.append(["write", str(path)])


sys.addaudithook(hook)
code = tm.main(["--repo-root", str(TMP / "repo"), "--json"])
snapshot = list(events)
sys.stderr.write(
    "\nMARKER_TOKEN" + json.dumps({"code": code, "events": snapshot}) + "\n"
)
'''.replace("MARKER_TOKEN", MARKER)

EFFECT_KINDS = {"write", "spawn", "network"}


@pytest.fixture(scope="module")
def traced_run(tmp_path_factory):
    sandbox = tmp_path_factory.mktemp("tokenmon")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(sandbox)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = next(
        (
            row[len(MARKER):]
            for row in completed.stderr.splitlines()
            if row.startswith(MARKER)
        ),
        None,
    )
    assert line is not None, (
        "the traced child produced no audit trace. "
        f"exit={completed.returncode} stdout={completed.stdout} "
        f"stderr={completed.stderr}"
    )
    payload = json.loads(line)
    payload["sandbox"] = sandbox
    return payload


def test_the_module_tail_starts_at_the_canonical_boundary(traced_run):
    kinds = [kind for kind, _ in traced_run["events"]]
    assert "boundary" in kinds, (
        "`python -m daedalus.interfaces.cli.token_monitor` reached its work without a "
        "canonical effect start; the module tail is a second console door and "
        "the registry row claims it is guarded"
    )
    started = [subject for kind, subject in traced_run["events"] if kind == "boundary"]
    assert "cli.token_monitor" in started

    assert "guard" in kinds, "no guard-install event preceded the effect start"
    guard_at = kinds.index("guard")
    boundary_at = kinds.index("boundary")
    assert guard_at < boundary_at, (
        "the boundary receipt must be able to name a guard that already ran"
    )

    effects_before = [
        traced_run["events"][index]
        for index, kind in enumerate(kinds)
        if kind in EFFECT_KINDS and index < boundary_at
    ]
    assert effects_before == [], (
        f"effects preceded the effect start: {effects_before}"
    )


def test_the_verb_writes_only_inside_its_declared_roots(traced_run):
    """Every Python-level write, classified against the registry's own list."""
    sandbox = Path(traced_run["sandbox"]).resolve()
    declared = {
        "memory/": (sandbox / "memory").resolve(),
        "runs/budget/": (sandbox / "budget").resolve(),
        "runs/spine/": (sandbox / "spine").resolve(),
    }

    writes = [path for kind, path in traced_run["events"] if kind == "write"]
    assert writes, (
        "no writes were traced at all -- the verb is supposed to write its "
        "report, so an empty trace means the probe stopped measuring"
    )

    stray = []
    for raw in writes:
        path = Path(raw).resolve()
        if not any(
            path == root or root in path.parents for root in declared.values()
        ):
            stray.append(raw)

    assert stray == [], (
        "the monitor wrote outside every root its registry row declares "
        f"({sorted(declared)}): {stray}. Observability writes its own report "
        "and nothing else; a write into the ledger it reads or the repository "
        "it watches is enforcement wearing an observability label."
    )


def test_the_report_and_the_budget_lock_are_both_present_in_the_trace(traced_run):
    """Pin what the run actually did, so a silently no-op probe is visible.

    Without this, deleting the status write and deleting the whole body would
    both leave the write-root assertion green.
    """
    writes = [Path(path).name for kind, path in traced_run["events"] if kind == "write"]
    assert "token_status.local.json" in writes, (
        "the report the verb exists to produce was never written"
    )
    assert any(name.endswith(".lock") for name in writes), (
        "the budget lock was never taken, so the ledger was not actually read "
        "-- the spend block in the report would be an unavailable stub"
    )


def test_the_run_reached_the_checkpoint_branch(traced_run):
    assert traced_run["code"] == 0, "the traced run did not exit clean"
    journal = [
        Path(path).name for kind, path in traced_run["events"] if kind == "write"
    ]
    assert "events.local.jsonl" in journal, (
        "the injected rate-limit sample was supposed to trip the checkpoint "
        "branch; a different path means the trace covered less than it claims"
    )


def test_no_spend_or_egress_happened(traced_run):
    """A monitor that spends is not a monitor.

    The registry row declares neither SPEND nor NETWORK_EGRESS, and this is
    the runtime half of that claim: the trace records no spawn and no socket.
    """
    offending = [
        event for event in traced_run["events"] if event[0] in ("spawn", "network")
    ]
    assert offending == [], f"the monitor spawned or connected: {offending}"


def test_the_spend_numbers_cannot_reach_the_checkpoint_decision():
    """The distinction, pinned in the source instead of in a comment.

    ``should_checkpoint`` is the only function in the module that returns a
    verdict.  It takes the token summary and two thresholds -- and nothing
    else.  Making a spend number change a checkpoint verdict therefore cannot
    be done without changing this signature, which is a line in the diff a
    reviewer will see, rather than one more argument threaded quietly through.
    """
    module = ast.parse(
        (ROOT / "daedalus" / "interfaces" / "cli" / "token_monitor.py").read_text(encoding="utf-8")
    )
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
    }

    decision = functions["should_checkpoint"]
    assert [arg.arg for arg in decision.args.args] == [
        "summary",
        "fresh_threshold",
        "cached_threshold",
    ]

    called_in_decision = {
        node.func.id
        for node in ast.walk(decision)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_budget_view" not in called_in_decision
    assert "_spine_view" not in called_in_decision

    # ...and the same for the function that persists the record: the views are
    # assembled in main(), after the verdict, and merged into the REPORT only.
    persisted = functions["checkpoint_if_needed"]
    called_in_persist = {
        node.func.id
        for node in ast.walk(persisted)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_budget_view" not in called_in_persist
    assert "_spine_view" not in called_in_persist
