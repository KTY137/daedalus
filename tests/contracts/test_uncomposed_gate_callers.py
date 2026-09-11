"""No shipped caller may invoke the registered gate doors uncomposed.

WHY THIS FILE EXISTS, stated as the failure it is meant to replace.

``spine.attempt.command_gate``/``pytest_gate`` are the registered Effect
Registry doors. Since G1-HIER-03B/03D they own no scratch-cleanup capability:
they raise ``AttemptPortMissing`` unless a caller injects a ``ScratchCleanupPort``,
so that no future caller silently inherits an ambient Kairos walker. The single
composition root ``daedalus.orchestration.execution.attempts`` binds the
production port (``remove_tree_no_follow``).

G1-HIER-03D migrated the in-tree callers and missed three. Two were test modules
that failed *loudly* -- eleven reds -- and still went unnoticed for ten commits,
because the full suite costs 39 minutes and every packet ran only its own
subset. The third, ``tools/bootstrap_receipt.py``, failed **silently**: nothing
executed it, so its refusal was never observed at all.

Loudness was not the missing ingredient; a cheap scored instrument was. This
file is that instrument. It is in the ``g1`` profile, it is pure AST over
tracked source, it needs no subprocess, and it answers the question the
39-minute suite answered too late: *does any shipped module call a gate door
without the port it requires?*

SCOPE, deliberately narrow.

* Shipped code only -- ``daedalus/`` and ``tools/``. ``tests/`` is excluded on
  purpose: a refusal test MUST be able to call the bare door uncomposed, and
  that is exactly what ``tests/orchestration/test_attempt_composition_hierarchy``
  and ``tests/test_cli_effect_boundary`` do.
* The gate doors only. The sibling ``workspace_port`` obligation on
  ``TaskAttempt``/``run_attempt`` is a different axis with its own open
  callers; see the G1-HIER-09 packet's evidence section. Widening this scan to
  cover it without fixing them would make this file red on arrival, which is
  how instruments get disabled.
* A ``**kwargs`` forward counts as injection. ``spine.attempt.pytest_gate`` and
  the composition root both forward rather than name the port, and a scan that
  called those violations would be measuring syntax, not authority.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

#: The module whose gate names are the registered, deliberately uncomposed doors.
DOOR_MODULE = "daedalus.spine.attempt"
#: The registered gate doors that require a ``ScratchCleanupPort``.
GATE_NAMES = frozenset({"command_gate", "pytest_gate"})
#: The port whose absence is the refusal.
REQUIRED_PORT = "scratch_cleanup"
#: Shipped trees. Anything here is reachable in production or by an operator.
SHIPPED_PREFIXES = ("daedalus", "tools")


def _tracked_python_files() -> tuple[Path, ...]:
    """Tracked ``.py`` files under the shipped trees, per Git, not the disk.

    Git is the authority for "shipped": an untracked scratch file is not part
    of the product, and a build artefact left in the tree must not be able to
    turn this instrument red or hide a violation behind a ``.gitignore``.
    """
    out = subprocess.run(
        ["git", "ls-files", "--", *SHIPPED_PREFIXES],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return tuple(
        ROOT / line for line in out if line.endswith(".py")
    )


def _dotted(node: ast.AST) -> str | None:
    """Reconstruct ``a.b.c`` from an attribute/name chain, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


class _GateCallScan(ast.NodeVisitor):
    """Collect gate-door calls that do not inject the cleanup port.

    Bindings are collected module-wide regardless of scope. Imports in this
    repository are routinely function-local (``tools/bootstrap_receipt.py``
    imports inside ``run_single``), and a scope-accurate resolver would buy
    precision this check does not need: over-approximating can only produce a
    false positive, and the whole-tree assertion below proves there are none.
    """

    def __init__(self) -> None:
        #: local name -> door gate name, for ``from ... import command_gate``
        self.direct: dict[str, str] = {}
        #: local name -> DOOR_MODULE, for ``import ... as attempt_mod``
        self.module_alias: dict[str, str] = {}
        self.violations: list[tuple[int, str]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == DOOR_MODULE:
                self.module_alias[alias.asname or alias.name] = DOOR_MODULE
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == DOOR_MODULE:
            for alias in node.names:
                if alias.name in GATE_NAMES:
                    self.direct[alias.asname or alias.name] = alias.name
        # ``from daedalus.spine import attempt as _door``
        elif node.module == DOOR_MODULE.rpartition(".")[0]:
            leaf = DOOR_MODULE.rpartition(".")[2]
            for alias in node.names:
                if alias.name == leaf:
                    self.module_alias[alias.asname or alias.name] = DOOR_MODULE
        self.generic_visit(node)

    def _resolve(self, func: ast.AST) -> str | None:
        dotted = _dotted(func)
        if dotted is None:
            return None
        if dotted in self.direct:
            return self.direct[dotted]
        head, _, tail = dotted.rpartition(".")
        if tail in GATE_NAMES and (head in self.module_alias or head == DOOR_MODULE):
            return tail
        return None

    def visit_Call(self, node: ast.Call) -> None:
        gate = self._resolve(node.func)
        if gate is not None:
            injected = any(
                # ``arg is None`` is ``**kwargs``: the caller forwards whatever
                # it was given, which is how the door and the composition root
                # both pass the port on.
                kw.arg is None or kw.arg == REQUIRED_PORT
                for kw in node.keywords
            )
            if not injected:
                self.violations.append((node.lineno, gate))
        self.generic_visit(node)


def _scan_source(source: str) -> list[tuple[int, str]]:
    scan = _GateCallScan()
    scan.visit(ast.parse(source))
    return scan.violations


# --------------------------------------------------------------------------- #
# The instrument must be able to go red. Proven first, on planted source.      #
# --------------------------------------------------------------------------- #
#: Byte-for-byte the shape ``tools/bootstrap_receipt.py`` shipped with before
#: G1-HIER-09, reduced to the two lines that mattered.
_THE_ACTUAL_DEFECT = """
from daedalus.spine.attempt import TaskAttempt, TaskSpec, command_gate
gate = command_gate(gate_command)
"""

_COMPOSED_CONTROL = """
from daedalus.orchestration.execution.attempts import command_gate
gate = command_gate(gate_command)
"""

_EXPLICIT_PORT_CONTROL = """
from daedalus.spine.attempt import command_gate
gate = command_gate(argv, scratch_cleanup=remove_tree_no_follow)
"""

_FORWARDED_PORT_CONTROL = """
from daedalus.spine import attempt as _door
gate = _door.pytest_gate(paths, **kwargs)
"""

_MODULE_ALIAS_DEFECT = """
import daedalus.spine.attempt as attempt_mod
verdict = attempt_mod.pytest_gate(timeout_s=300)(ctx)
"""


def test_the_scan_catches_the_defect_that_actually_shipped() -> None:
    """If this passes vacuously the whole file is decoration."""
    assert _scan_source(_THE_ACTUAL_DEFECT) == [(3, "command_gate")]


def test_the_scan_catches_the_module_alias_spelling() -> None:
    """The eleven reds used this spelling, not the ``from ... import`` one."""
    assert _scan_source(_MODULE_ALIAS_DEFECT) == [(3, "pytest_gate")]


@pytest.mark.parametrize(
    "label, source",
    [
        ("composed", _COMPOSED_CONTROL),
        ("explicit_port", _EXPLICIT_PORT_CONTROL),
        ("forwarded_port", _FORWARDED_PORT_CONTROL),
    ],
)
def test_the_scan_does_not_flag_a_composed_caller(label: str, source: str) -> None:
    """Otherwise "always red" would be indistinguishable from "detects it"."""
    assert _scan_source(source) == [], label


# --------------------------------------------------------------------------- #
# THE MEASUREMENT, on the real tree.                                           #
# --------------------------------------------------------------------------- #
def test_no_shipped_module_calls_a_gate_door_without_the_cleanup_port() -> None:
    files = _tracked_python_files()
    # Guard against the scan silently measuring nothing -- an empty selection
    # would make every assertion below trivially true.
    assert len(files) > 100, f"tracked-file scan collected only {len(files)}"

    findings: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            pytest.fail(f"{path.relative_to(ROOT)} could not be parsed: {exc}")
        scan = _GateCallScan()
        scan.visit(tree)
        rel = path.relative_to(ROOT).as_posix()
        findings.extend(
            f"{rel}:{lineno} calls {gate}() without an injected "
            f"{REQUIRED_PORT} port"
            for lineno, gate in scan.violations
        )

    assert findings == [], (
        "uncomposed gate-door caller(s); route them through "
        "daedalus.orchestration.execution.attempts:\n  " + "\n  ".join(findings)
    )


def test_the_composition_root_is_the_one_that_binds_the_port() -> None:
    """One composition root, named. A second one is the defect this prevents.

    The claim is not "somebody passes scratch_cleanup" but "exactly one shipped
    module does". A second binder would be a second authority over candidate
    scratch cleanup, which is the parallel-path defect the master plan forbids.
    """
    binders = set()
    for path in _tracked_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scan = _GateCallScan()
        scan.visit(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if scan._resolve(node.func) is None:
                continue
            if any(kw.arg == REQUIRED_PORT for kw in node.keywords):
                binders.add(path.relative_to(ROOT).as_posix())

    assert binders == {"daedalus/orchestration/execution/attempts.py"}, binders
