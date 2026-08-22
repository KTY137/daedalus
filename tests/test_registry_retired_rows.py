"""A registry row may not outlive the file it inventories.

Two separate claims live here, both about rows in
``daedalus/spine/effect_boundary.py`` that describe a door nobody can walk
through:

1. RETIRED TARGETS. Commit 79825b57 deleted ``tools/iron_plan_guard.py`` and
   ``tools/iron_plan_hook_runner.py`` by owner decision. Their rows survived
   the deletion and became two permanent ``registry.target_missing`` blockers
   -- a false door: prose that reads as coverage of a mechanism that is gone,
   parked in front of a check that no correct wiring could ever clear. The
   rows are removed; this file keeps them from creeping back and, more
   generally, asserts that NO row anywhere names a Python target whose file is
   absent from the tree.

2. THE OLLAMA ROLLBACK ROW'S EFFECT SET. The conformance run reports
   ``entrypoint.effect_drift`` against
   ``daedalus.providers.ollama:OllamaProvider.rollback`` -- "new undeclared
   effects: network_egress, process_spawn". That finding is FALSE about the
   code, and ``tests/test_provider_rollback_single_source.py`` already pins it
   as a known scanner artefact. What that pin does NOT do is prove the row is
   the correct half of the disagreement. This file does: it derives the effect
   set from the AST of every body ``rollback`` can actually reach and shows it
   equals the row's declaration exactly. Without that, "the scanner is wrong"
   is an assertion; with it, it is a measurement -- and it is the evidence an
   amendment would need before touching either side.

Both parts are two-way guards. Read the failure messages before making either
one green again.
"""

from __future__ import annotations

import ast
from pathlib import Path

from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    Effect,
    check_conformance,
)


ROOT = Path(__file__).resolve().parents[1]

# Retired by owner decision in 79825b57, "unify(2026-08-22): main is the g0
# trunk, the iron guard is retired by owner decision". Both the row ids and the
# targets are listed: registry-side findings report under the row id and
# discovery-side findings under the target, so watching one key alone misses
# half the ways this could come back.
RETIRED_ROW_IDS = frozenset({
    "tools.iron_plan_guard",
    "tools.iron_plan_hook_runner",
})
RETIRED_TARGETS = frozenset({
    "tools.iron_plan_guard:main",
    "tools.iron_plan_hook_runner:main",
})
RETIRED_FILES = (
    Path("tools") / "iron_plan_guard.py",
    Path("tools") / "iron_plan_hook_runner.py",
)


def _module_path(target: str) -> Path:
    """``pkg.mod:qualname`` -> the file that would define it."""
    module = target.split(":", 1)[0]
    return ROOT.joinpath(*module.split("."))


# --------------------------------------------------------------------------- #
# 1. the retired rows                                                          #
# --------------------------------------------------------------------------- #
def test_the_retired_plan_guard_files_are_really_gone() -> None:
    """The premise, checked first.

    Every other assertion in this file is only meaningful while these files are
    absent. If an owner-approved amendment restores a plan guard, this test is
    the first thing that fails, and it fails LOUDLY rather than letting the
    rest of the file quietly assert the wrong thing about a live mechanism.
    """
    for rel in RETIRED_FILES:
        assert not (ROOT / rel).exists(), (
            f"{rel.as_posix()} is back on disk. The rows for it were removed "
            "from the effect registry on the measured premise that it was "
            "deleted by owner decision (79825b57). A restored guard needs a "
            "NEW registry row argued from scratch -- read the RETIRED comments "
            "in daedalus/spine/effect_boundary.py before writing one, and "
            "delete this test's entry for the file that came back.")


def test_no_registry_row_names_a_retired_plan_guard() -> None:
    """The rows themselves are gone, by id and by target."""
    ids = {row.id for row in ENTRYPOINTS}
    targets = {row.target for row in ENTRYPOINTS}

    assert not (ids & RETIRED_ROW_IDS), (
        "a retired plan-guard row is back in ENTRYPOINTS: "
        f"{sorted(ids & RETIRED_ROW_IDS)}")
    assert not (targets & RETIRED_TARGETS), (
        "a retired plan-guard target is back in ENTRYPOINTS: "
        f"{sorted(targets & RETIRED_TARGETS)}")


def test_no_row_anywhere_points_at_a_file_that_does_not_exist() -> None:
    """The general form, so the next retirement does not need a new test.

    ``check_conformance`` already emits ``registry.target_missing`` for this,
    but it emits it as one blocker among many in a report that currently has
    others; a suite that only watches "structurally conformant" cannot tell a
    false door from an unrelated gap. This walks the registry directly and
    names the offending row.

    ``discoverable=False`` rows are skipped: ``mcp.runtime`` deliberately
    carries the target ``<absent>`` to inventory a boundary Daedalus does not
    implement, which is an honest absence rather than a stale row.
    """
    stale = []
    for row in ENTRYPOINTS:
        if not row.discoverable or ":" not in row.target:
            continue
        base = _module_path(row.target)
        if not (base.with_suffix(".py").exists() or (base / "__init__.py").exists()):
            stale.append(f"{row.id} -> {row.target}")

    assert not stale, (
        "registry rows name Python modules that are not in the tree:\n  "
        + "\n  ".join(sorted(stale))
        + "\nA row whose target is gone is a false door: it reads as coverage "
          "of a mechanism nobody can run. Delete the row and record WHY in a "
          "neighbourhood comment (see the RETIRED notes for the plan guard), "
          "or restore the target.")


def test_conformance_reports_no_target_missing_blocker_for_a_retired_file() -> None:
    """The same claim, through the tool the gate actually runs.

    MEASURED 2026-08-22, before the removal: exactly two
    ``registry.target_missing`` blockers, subjects ``tools.iron_plan_guard``
    and ``tools.iron_plan_hook_runner``. After: none.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-08-22]: re-adding either
    EntrypointSpec to ``ENTRYPOINTS`` (target unchanged, file still deleted)
    puts its ``registry.target_missing`` blocker straight back and turns this
    red -- verified by constructing the registry with the row restored and
    re-running ``check_conformance``.
    """
    report = check_conformance(ROOT)
    missing = sorted(
        f"{row.subject} -- {row.detail}"
        for row in report.findings
        if row.code == "registry.target_missing" and row.severity == "blocker"
    )
    assert not missing, (
        "the effect registry claims targets that do not exist:\n  "
        + "\n  ".join(missing))


# --------------------------------------------------------------------------- #
# 2. the ollama rollback row's effect set                                      #
# --------------------------------------------------------------------------- #
#
# Sink -> effect, for the effects a rollback could plausibly carry. Deliberately
# generous on the two the scanner claims and the row denies: if ANY spawn or
# socket call is reachable from the undo path, this table finds it and the test
# says the row is wrong, not the scanner.
_SPAWN_NAMES = {
    "run", "Popen", "call", "check_call", "check_output", "system",
    "popen", "spawnv", "spawnl", "execv", "execvp", "fork",
}
_EGRESS_NAMES = {
    "urlopen", "Request", "request", "urlretrieve", "connect",
    "create_connection", "socket", "get", "post", "put", "delete", "send",
    "sendall", "getaddrinfo",
}
_WRITE_NAMES = {
    "write_bytes", "write_text", "unlink", "rmdir", "mkdir", "makedirs",
    "remove", "rename", "replace", "rmtree", "touch", "chmod",
}
_EGRESS_MODULES = {"urllib", "socket", "http", "requests", "httpx"}
_SPAWN_MODULES = {"subprocess", "multiprocessing"}


def _reachable_bodies() -> dict[str, ast.FunctionDef]:
    """``OllamaProvider.rollback`` plus everything it can reach in one hop.

    One hop is enough and is checked, not assumed: the test below asserts the
    body is a single delegating ``return self._rollback_writes()``, so the
    closure is exactly {rollback, _rollback_writes}. If someone re-inlines the
    loop or adds a second call, that assertion fails first and this walk is
    never trusted over a wider graph than it actually covers.
    """
    found: dict[str, ast.FunctionDef] = {}
    for rel, cls, name in (
        (Path("daedalus/providers/ollama.py"), "OllamaProvider", "rollback"),
        (Path("daedalus/providers/base.py"), "Provider", "_rollback_writes"),
    ):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == name:
                        found[f"{cls}.{name}"] = item
    return found


def _effects_of(node: ast.AST) -> set[Effect]:
    effects: set[Effect] = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        attr = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        root = ""
        target = func.value if isinstance(func, ast.Attribute) else None
        while isinstance(target, ast.Attribute):
            target = target.value
        if isinstance(target, ast.Name):
            root = target.id
        if attr in _WRITE_NAMES:
            effects.add(Effect.FILESYSTEM_WRITE)
        if root in _SPAWN_MODULES or (attr in _SPAWN_NAMES and root in _SPAWN_MODULES):
            effects.add(Effect.PROCESS_SPAWN)
        if root in _EGRESS_MODULES or (attr in _EGRESS_NAMES and root in _EGRESS_MODULES):
            effects.add(Effect.NETWORK_EGRESS)
    return effects


def test_the_ollama_rollback_body_only_delegates() -> None:
    """The premise of the effect derivation below, checked rather than assumed."""
    bodies = _reachable_bodies()
    assert set(bodies) == {"OllamaProvider.rollback", "Provider._rollback_writes"}

    calls = [
        node for node in ast.walk(bodies["OllamaProvider.rollback"])
        if isinstance(node, ast.Call)
    ]
    assert len(calls) == 1, (
        "OllamaProvider.rollback is no longer a single delegating call, so the "
        "one-hop effect closure below no longer covers it. Widen "
        "_reachable_bodies before trusting this file again.")
    func = calls[0].func
    assert isinstance(func, ast.Attribute) and func.attr == "_rollback_writes"


def test_the_ollama_rollback_row_equals_the_ast_derived_effect_set() -> None:
    """The row is the truthful half of the drift disagreement.

    ``check_conformance`` reports ``entrypoint.effect_drift`` here claiming
    undeclared ``network_egress`` and ``process_spawn``. Its evidence field is
    literally ``effectful-interface-contract``, i.e. NO sink was observed at
    all: same-module resolution found nothing (the restore loop lives one
    module away in ``daedalus/providers/base.py``), so the fallback for an
    OLLAMA-surface lifecycle method asserted the vendor-transport triple by
    interface rather than by evidence. That fallback is right about
    ``OllamaProvider.run``, which really does reach a vendor. It is wrong about
    the undo path.

    MEASURED here, over the real closure: ``{filesystem_write}`` -- Path
    ``write_bytes`` / ``unlink`` / ``rmdir`` and nothing else. No subprocess
    module, no urllib, no socket.

    So the correction belongs on the discovery fallback, never on this row.
    Widening the row to swallow the finding would declare an undo path capable
    of egress and spawn: an over-broad door on the one code path that runs
    exactly when a write already went wrong -- and precisely the "row declaring
    effects the code cannot perform" defect the registry deleted once before
    (see ``cli.claude_bridge`` in tests/test_effect_boundary.py).

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-08-22]: adding
    ``Effect.NETWORK_EGRESS`` to the ``provider.ollama.rollback`` row -- the
    tempting way to silence the drift blocker -- turns this red with the
    declared set no longer equal to the derived one.
    """
    derived: set[Effect] = set()
    for node in _reachable_bodies().values():
        derived |= _effects_of(node)

    assert derived == {Effect.FILESYSTEM_WRITE}, (
        "the rollback closure's AST-derived effects changed: "
        f"{sorted(e.value for e in derived)}. If it really gained a spawn or a "
        "socket, the ROW is now wrong and must be widened -- and the undo path "
        "of a write lane just grew a capability that needs its own argument.")

    row = {r.id: r for r in ENTRYPOINTS}["provider.ollama.rollback"]
    assert set(row.effects) == derived, (
        f"provider.ollama.rollback declares {sorted(e.value for e in row.effects)} "
        f"but its code can perform {sorted(e.value for e in derived)}. These "
        "must agree. If they disagree because the conformance scanner's "
        "interface fallback was appeased, revert that: the fallback is the "
        "thing to correct, not this row.")
