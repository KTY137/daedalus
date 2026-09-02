"""The spine must not reach the legacy facade, at module OR function scope.

G1-HIER-10 closed the direct leak for the kernel; G1-HIER-11 closed the
transitive one behind ``daedalus.twin``. Both left the same defect one layer
down, and G1-HIER-11's packet document named both instances explicitly:

* ``daedalus/spine/receipts.py:49`` imported ``daedalus.schemas`` at module
  scope. A cold import loaded 13 modules under ``daedalus.orchestration`` and
  ``daedalus.runtimes`` -- prefixes ``spine-no-outer-layers`` already forbids --
  and the rule passed anyway, because ``daedalus.schemas`` was not in its
  forbidden set.
* ``daedalus/spine/picker.py:2880`` imported the same facade INSIDE
  ``_default_attempt``. Its cold import measured 0 outer modules and no facade
  while the dependency was fully present at first call.

WHICH INSTRUMENT WAS ACTUALLY BLIND
-----------------------------------
Not the static checker. ``tools/architecture_boundaries.py`` uses ``ast.walk``,
so it observes an import at any scope; it missed both edges only because
``daedalus.schemas`` was absent from the rule. MEASURED in G1-HIER-12 by
replaying the amended rule against the ``4c370f2a`` source: exactly two
violations, ``receipts.py:49:0`` and ``picker.py:2880:4`` -- the second one
function-scope, and seen.

The blind instrument is the RUNTIME one: import a module, inspect
``sys.modules``. A deferred import is absent from ``sys.modules`` until first
call, so a cold-import test cannot see it. MEASURED across the tracked tree at
``4c370f2a``: 495 function-scope ``daedalus.*`` imports, none of which that
instrument can observe. Exactly one of them was a forbidden target
(``picker.py:2880``); the rest are invisible but currently legal.

That is why this file pairs the two checks instead of trusting either alone,
and why ``test_the_layer_still_defers_imports_the_cold_import_test_cannot_see``
pins the residual number rather than implying the layer is statically clean
because one entrypoint imports clean.

WHAT THIS FILE DELIBERATELY DOES NOT DO
---------------------------------------
It does not copy ``tests/kernel/test_fourfold_evidence_outer_ports.py``'s
blanket ban on function-scope imports. That guard is correct for
``daedalus/twin``, which has none. ``daedalus/spine`` has 34, and they are
load-bearing: ``bootstrap`` -> ``picker``, ``picker`` -> ``attempt``,
``containment`` -> ``cancel`` and the ``main`` entrypoints' budget/effect
imports are cycle-avoidance inside one layer, not layering debt. A blanket ban
would go red on legitimate edges, so it is not adopted and not baselined; the
owning shape is the static rule, which already sees every scope.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import daedalus.kernel.contracts.canonical as _nucleus
import daedalus.schemas as _facade
from tools.architecture_boundaries import (
    load_contract,
    scan_repository,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs" / "architecture" / "import-boundaries.json"

#: The layers a cold spine import must not pull in. This is the
#: ``spine-no-outer-layers`` forbidden set minus ``daedalus.schemas``, which is
#: asserted separately because it is a facade rather than a layer.
FORBIDDEN_PREFIXES = (
    "daedalus.build",
    "daedalus.build_exec",
    "daedalus.chip_design",
    "daedalus.core",
    "daedalus.desktop_runtime",
    "daedalus.eval",
    "daedalus.file_bridge",
    "daedalus.gates",
    "daedalus.ikarus_os",
    "daedalus.integrations",
    "daedalus.kairos",
    "daedalus.loop",
    "daedalus.offload",
    "daedalus.orchestration",
    "daedalus.providers",
    "daedalus.runtimes",
    "daedalus.twin",
    "daedalus.web_api",
)

#: Every symbol the two spine modules took from the facade, and the module that
#: now supplies it. 12 bindings over 11 distinct names -- ``ResourceBudget`` is
#: taken by both files. This is the FULL moved set, not a sample.
MOVED_BINDINGS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.attempts",
        ("AttemptContract", "AttemptReceipt"),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.base",
        ("ContractProvenance",),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.evidence",
        ("EvidencePacket",),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.missions",
        ("MissionContract",),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.policy",
        ("PolicyDecision",),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.resources",
        ("EffectScope", "ResourceBudget", "ResourceUsage", "RuntimeCapabilities"),
    ),
    (
        "daedalus.spine.receipts",
        "daedalus.kernel.contracts.runtime",
        ("RuntimeManifest",),
    ),
    (
        "daedalus.spine.picker",
        "daedalus.kernel.contracts.resources",
        ("ResourceBudget",),
    ),
)

#: Moving census, re-measured in the packet that moves it. Not an architecture
#: invariant -- a later packet may legitimately add or remove a deferred import
#: inside the layer. What must not change silently is that this number is
#: non-zero while a cold-import test is offered as evidence about the layer.
SPINE_DEFERRED_DAEDALUS_IMPORTS = 34


def _tracked_spine_files() -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "daedalus/spine"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    )
    paths = tuple(
        ROOT / raw.decode("utf-8")
        for raw in completed.stdout.split(b"\0")
        if raw.endswith(b".py")
    )
    # Fail closed: an empty selection is a broken locator, not a clean layer.
    assert len(paths) >= 10, paths
    return paths


def _import_targets(tree: ast.Module, package: str) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "." * node.level + (node.module or "")
                targets.append(importlib.util.resolve_name(base, package))
            elif node.module:
                targets.append(node.module)
    return targets


def _deferred_daedalus_imports(tree: ast.Module, package: str) -> list[tuple[int, str]]:
    """Every ``daedalus.*`` import whose nearest enclosing scope is a function.

    Nearest enclosing scope, not "anywhere under a function node": a class body
    nested in a function still executes when the function runs, and a function
    nested in a function is still deferred, so the recursive descent below
    attributes each import to the scope that actually decides when it runs.
    """
    found: list[tuple[int, str]] = []

    def walk(node: ast.AST, deferred: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                if not deferred:
                    continue
                for target in _import_targets(ast.Module(body=[child], type_ignores=[]), package):
                    if target == "daedalus" or target.startswith("daedalus."):
                        found.append((child.lineno, target))
                        break
            elif isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                walk(child, True)
            else:
                walk(child, deferred)

    walk(tree, False)
    return found


def _spine_rule():
    contract = load_contract(CONTRACT_PATH)
    matches = [
        rule for rule in contract.rules if rule.rule_id == "spine-no-outer-layers"
    ]
    assert len(matches) == 1, "spine-no-outer-layers must be registered exactly once"
    return contract, matches[0]


def test_no_spine_module_reaches_the_legacy_facade_or_an_outer_layer() -> None:
    """Whole layer, every scope -- not just the two entrypoints measured below."""
    offenders: list[tuple[str, int, str]] = []
    for path in _tracked_spine_files():
        relative = path.relative_to(ROOT).as_posix()
        module = relative[:-3].replace("/", ".").removesuffix(".__init__")
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for target in _import_targets(
                ast.Module(body=[node], type_ignores=[]), package
            ):
                if target == "daedalus.schemas" or any(
                    target == prefix or target.startswith(prefix + ".")
                    for prefix in FORBIDDEN_PREFIXES
                ):
                    offenders.append((relative, node.lineno, target))
    assert offenders == []


def test_spine_boundary_rule_forbids_the_facade_and_keeps_an_empty_baseline() -> None:
    """The durable guard. Without this prefix the rule was green on both leaks."""
    contract, rule = _spine_rule()
    assert "daedalus.schemas" in rule.forbidden_target_prefixes
    # The facade's declared targets are prefixes this rule already forbids, so
    # the facade is a one-hop bypass of the rule's own set rather than a new
    # restriction. Assert that relationship instead of just the membership.
    for laundered in ("daedalus.orchestration", "daedalus.runtimes"):
        assert laundered in rule.forbidden_target_prefixes
    # What this line is actually for: no SPINE violation may hide in the
    # baseline. It used to say `contract.baseline == ()`, which held only
    # while the whole contract had zero recorded debt. b3cc415b recorded one
    # entry -- the kernel's `attempt_execution.py:1209 -> daedalus.offload`
    # inversion -- deliberately, because the alternative on offer was leaving
    # it in an ALLOWLIST, a field that grants permission and that no
    # instrument counts. Asserting global emptiness made this test a tripwire
    # for any recorded debt anywhere, including debt that has nothing to do
    # with the spine; scoping it to this rule keeps the guard and drops the
    # false coupling. The whole-contract shape stays pinned, entry by entry,
    # in tests/test_architecture_boundaries.py.
    assert [
        entry for entry in contract.baseline if entry.rule_id == rule.rule_id
    ] == []
    # Same narrowing, one line down and for the same reason: scan_repository
    # returns RAW violations for every rule in the contract, not just this
    # one, so `violations == ()` was a whole-tree claim asserted from a spine
    # test -- and the kernel's recorded offload inversion is a raw violation
    # by construction (that is what a baseline entry IS). The spine claim is
    # that the spine rule has no violations at all, recorded or otherwise,
    # which is strictly stronger than what the baseline check above says and
    # is the property this test exists to defend.
    violations, tracked = scan_repository(ROOT, contract)
    spine_violations = [v for v in violations if v.rule_id == rule.rule_id]
    assert spine_violations == [], spine_violations
    assert tracked >= 400


def test_spine_rule_is_at_least_as_strict_as_the_kernel_rule() -> None:
    """The equality argument twin-no-outer-layers made, one layer further down.

    ``daedalus.kernel`` imports ``daedalus.spine`` by DIRECT MODULE-LEVEL edge
    -- ``kernel/approvals.py:30``, ``kernel/artifacts.py:19``,
    ``kernel/attempt_contracts.py:24``, ``kernel/attempt_ledger.py:13`` among
    others -- so everything the spine can reach, the kernel reaches. A spine
    forbidden set narrower than the kernel's therefore lets
    ``kernel-no-outer-layers`` pass in syntax while the layer it names loads in
    every kernel process anyway.

    That was not hypothetical at ``4c370f2a``: the spine set named eighteen
    prefixes and omitted ``daedalus.gates``, which the kernel set forbids. An
    adversarial probe confirmed the consequence -- an ordinary module-scope
    ``from daedalus.gates.report import ...`` inside ``daedalus/spine``
    transitively loaded 19 ``daedalus.runtimes`` modules, 2
    ``daedalus.orchestration`` modules and the facade, with both the checker
    and this file reporting green.

    This assertion is what stops the two sets drifting apart again. It is a
    subset relation, not equality: the spine legitimately forbids more than the
    kernel does (``daedalus.core``, ``daedalus.loop``, ``daedalus.web_api`` and
    the other interface layers), and that asymmetry is fine in this direction.
    """
    contract, spine = _spine_rule()
    kernel = [
        rule for rule in contract.rules if rule.rule_id == "kernel-no-outer-layers"
    ]
    assert len(kernel) == 1
    missing = set(kernel[0].forbidden_target_prefixes) - set(
        spine.forbidden_target_prefixes
    )
    assert missing == set(), sorted(missing)
    # And the specific prefix this packet added, named so a later edit that
    # drops it fails on something more legible than a set difference.
    assert "daedalus.gates" in spine.forbidden_target_prefixes


def test_the_static_checker_sees_a_function_scope_forbidden_import() -> None:
    """The property that makes one prefix enough to own picker.py:2880.

    Synthetic source, parsed in memory: no file is staged and no module is
    imported. If ``_import_references`` ever stopped walking into function
    bodies, this goes red and the packet's whole argument -- that no separate
    anti-lazy rule is needed for forbidden targets -- would be false.
    """
    from tools.architecture_boundaries import _import_references

    _, rule = _spine_rule()
    source = "def f():\n    from daedalus.schemas import ResourceBudget\n    return ResourceBudget\n"
    tree = ast.parse(source, filename="daedalus/spine/_synthetic.py")
    hits = [
        reference
        for reference in _import_references(
            tree, source_module="daedalus.spine._synthetic", is_package=False
        )
        if rule.forbidden_target(reference.candidates) == "daedalus.schemas"
    ]
    assert len(hits) == 1, hits
    # Column 4: proof it came from inside the function body, not module scope.
    assert (hits[0].line, hits[0].column) == (2, 4)


def test_the_layer_still_defers_imports_the_cold_import_test_cannot_see() -> None:
    """The finding this packet was dispatched for, kept mechanically true.

    A cold-import test proves what one entrypoint loads. It cannot prove a
    layer is clean while the layer defers imports, because a deferred import is
    not in ``sys.modules`` at the moment the test looks. This asserts the
    residual is real and pinned, so the next reader cannot mistake the two
    green cold-import tests below for a statement about ``daedalus/spine``.
    """
    deferred: list[tuple[str, int, str]] = []
    for path in _tracked_spine_files():
        relative = path.relative_to(ROOT).as_posix()
        module = relative[:-3].replace("/", ".").removesuffix(".__init__")
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        deferred.extend(
            (relative, line, target)
            for line, target in _deferred_daedalus_imports(tree, package)
        )
    assert len(deferred) == SPINE_DEFERRED_DAEDALUS_IMPORTS, sorted(deferred)
    # Non-zero is the load-bearing half: it is what makes the cold-import tests
    # insufficient on their own. Zero would be fine architecturally but would
    # mean this assertion is stale, so it is asserted rather than assumed.
    assert deferred, "a zero here means the census above was never re-measured"
    # And none of them is a forbidden target -- the static rule's job, restated
    # here over exactly the set the runtime instrument cannot observe.
    _, rule = _spine_rule()
    assert [row for row in deferred if rule.forbidden_target((row[2],))] == []


def _cold_import(target: str) -> dict[str, object]:
    script = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
import {target}
prefixes = {FORBIDDEN_PREFIXES!r}
print(json.dumps({{
    "leaked": sorted(
        name for name in sys.modules
        if any(name == p or name.startswith(p + '.') for p in prefixes)
    ),
    "facade": "daedalus.schemas" in sys.modules,
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(completed.stdout)


def test_cold_spine_receipts_import_loads_no_outer_implementation() -> None:
    """Was 13 outer modules and the facade at 4c370f2a."""
    assert _cold_import("daedalus.spine.receipts") == {"leaked": [], "facade": False}


def test_cold_spine_picker_import_loads_no_outer_implementation() -> None:
    """Was ALREADY {"leaked": [], "facade": False} at 4c370f2a, and false.

    This is the one cold-import assertion in the repository that was green on a
    live violation. It is kept -- with this docstring -- because the honest
    reading of a green cold import is "this entrypoint loads nothing outer",
    never "this module depends on nothing outer". The tests above are what
    carry the second claim.
    """
    assert _cold_import("daedalus.spine.picker") == {"leaked": [], "facade": False}


def test_moved_symbols_are_the_same_objects_the_facade_exposes() -> None:
    """Object identity over the FULL moved set: 12 bindings, 11 names.

    Be exact about what this proves. ``daedalus/schemas.py`` and every module
    under ``daedalus/kernel/contracts/`` re-export from
    ``daedalus.kernel.contracts.canonical``, so these ``is`` assertions hold
    whether or not the spine modules were repointed. This test therefore does
    NOT detect the repoint -- the AST sweep and the boundary rule do that.

    What it protects is the precondition that makes the repoint safe: facade,
    owner and nucleus must keep resolving to one object per name. The final
    assertion is the load-bearing one. If a later packet gives a domain locator
    its own definition of any of these names instead of re-exporting, the spine
    and every remaining facade consumer would silently validate against two
    contract authorities -- a release-blocking defect by this repository's own
    review rules -- and this goes red on it.
    """
    checked = 0
    names: set[str] = set()
    for consumer, owner_name, symbols in MOVED_BINDINGS:
        consumer_module = importlib.import_module(consumer)
        owner = importlib.import_module(owner_name)
        for symbol in symbols:
            checked += 1
            names.add(symbol)
            bound = getattr(owner, symbol)
            assert bound is getattr(_facade, symbol), (owner_name, symbol)
            assert bound is getattr(_nucleus, symbol), (owner_name, symbol)
            # The consumer holds the same object only where it binds the name
            # at module scope. picker takes ResourceBudget at module scope too
            # after this packet, so all 12 are checkable.
            assert getattr(consumer_module, symbol) is bound, (consumer, symbol)
    assert checked == 12
    assert len(names) == 11

    # Read from source, so a runtime rebinding cannot satisfy it: the domain
    # locators re-export these names and define none of them.
    for _, owner_name, symbols in MOVED_BINDINGS:
        relative = owner_name.replace(".", "/") + ".py"
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        defined.update(
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        )
        assert defined.isdisjoint(symbols), (owner_name, sorted(defined & set(symbols)))
