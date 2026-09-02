"""The kernel's Fourfold evidence path must not load the outer layers.

G1-HIER-10 closed the direct leak: eighteen kernel modules stopped importing
the ``daedalus.schemas`` facade. It did not close the transitive one. A cold
``import daedalus.kernel.fourfold_evidence`` still loaded eleven
``daedalus.runtimes`` modules and two ``daedalus.orchestration`` modules,
because ``daedalus/kernel/fourfold_evidence.py`` imports
``daedalus.twin.contracts`` -- a deliberate, permitted edge -- and four
``daedalus.twin`` modules reached the facade behind it.

``kernel-no-outer-layers`` could not see that: the checker reads direct import
syntax, and the leak crossed a permitted edge. Adding ``daedalus.twin`` to that
rule is not the fix and this packet measured why -- it produces exactly one
violation, ``daedalus.kernel.fourfold_evidence`` line 41, the edge the module
exists for. The guard is ``twin-no-outer-layers``, which constrains the
intermediate layer's own imports.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import daedalus.kernel.contracts.canonical as _nucleus
import daedalus.schemas as _facade
from daedalus.kernel.contracts import base as _owner
from tools.architecture_boundaries import evaluate_repository, load_contract


ROOT = Path(__file__).resolve().parents[2]
TWIN_DIR = ROOT / "daedalus" / "twin"
CONTRACT_PATH = ROOT / "docs" / "architecture" / "import-boundaries.json"

#: The layers a cold kernel import must not pull in. Same list the
#: ``kernel-no-outer-layers`` rule forbids, minus ``daedalus.schemas``, which is
#: asserted separately because it is a facade rather than a layer.
FORBIDDEN_PREFIXES = (
    "daedalus.chip_design",
    "daedalus.eval",
    "daedalus.gates",
    "daedalus.kairos",
    "daedalus.orchestration",
    "daedalus.providers",
    "daedalus.runtimes",
)

#: Every symbol the four twin modules took from the facade before G1-HIER-11,
#: and the module that now supplies it. Nine distinct names, fifteen bindings.
MOVED_BINDINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "daedalus.twin.contracts",
        (
            "CanonicalContract",
            "ContractProvenance",
            "_identifier",
            "_non_empty",
            "_record_payload",
            "_require_provenance_inputs",
            "_revision",
            "_sha256",
            "_sorted_strings",
        ),
    ),
    ("daedalus.twin.legacy_forest", ("ContractProvenance",)),
    (
        "daedalus.twin.reference_compiler",
        ("ContractProvenance", "_identifier", "_revision", "_sha256"),
    ),
    ("daedalus.twin._reference_claims", ("_identifier",)),
)


def _tracked_twin_files() -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "daedalus/twin"],
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
    assert len(paths) >= 8
    return paths


def _import_targets(tree: ast.Module, package: str) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "." * node.level + (node.module or "")
                import importlib.util

                targets.append(importlib.util.resolve_name(base, package))
            elif node.module:
                targets.append(node.module)
    return targets


def test_no_twin_module_reaches_the_legacy_facade_or_an_outer_layer() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _tracked_twin_files():
        relative = path.relative_to(ROOT).as_posix()
        module = relative[:-3].replace("/", ".").removesuffix(".__init__")
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for target in _import_targets(tree, package):
            if target == "daedalus.schemas" or any(
                target == prefix or target.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                offenders.append((relative, target))
    assert offenders == []


def test_twin_layer_has_no_lazy_or_sys_modules_escape() -> None:
    """A lazy import turns the cold-import test green and leaves the leak.

    Module ``__getattr__``, ``importlib``, ``__import__``, a ``sys.modules``
    swap or a function-scope import would each hide the dependency behind first
    use rather than remove it.

    Exactly one check is relaxed, for exactly two files. The two extractor
    adapters import ``importlib`` at module level to probe for an optional
    third-party parser (``uproot``, ``tree_sitter``) -- a capability question,
    not a layering one, and the module names they resolve are third-party
    literals, never ``daedalus.*``. So they are exempt from the ``importlib``
    check and from nothing else: the ``__getattr__``, ``__import__``,
    ``sys.modules`` and function-scope-import checks still apply to them.
    MEASURED: with those four checks applied to the two adapters, offenders is
    still empty, so the narrower exemption costs nothing today and stops the
    two files from becoming a blind spot tomorrow.
    """
    importlib_exempt = {
        "extractors/root_file_adapter.py",
        "extractors/tree_sitter_adapter.py",
    }
    offenders: list[tuple[str, str]] = []
    for path in _tracked_twin_files():
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "__getattr__":
                    offenders.append((relative, "module __getattr__"))
                for inner in ast.walk(node):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        offenders.append((relative, f"deferred import in {node.name}"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "__import__":
                    offenders.append((relative, "__import__"))
        if relative.removeprefix("daedalus/twin/") not in importlib_exempt:
            for target in _import_targets(tree, "daedalus.twin"):
                if target.split(".")[0] == "importlib":
                    offenders.append((relative, "importlib"))
        if "sys.modules" in source:
            offenders.append((relative, "sys.modules"))
    assert offenders == []


def test_cold_fourfold_evidence_import_loads_no_outer_implementation() -> None:
    script = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
import daedalus.kernel.fourfold_evidence
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
        timeout=60,
    )
    assert json.loads(completed.stdout) == {"leaked": [], "facade": False}


def test_moved_symbols_are_the_same_objects_the_facade_exposes() -> None:
    """Object identity over the full moved set, not a sample.

    Be exact about what this proves, because an independent reviewer of this
    packet correctly pointed out that the obvious reading is too generous.
    ``daedalus/schemas.py`` and ``daedalus/kernel/contracts/base.py`` both
    re-export from ``daedalus.kernel.contracts.canonical``, so the identity
    assertions below hold whether or not the twin modules were repointed. This
    test therefore does **not** detect the repoint -- the AST sweep and the
    cold-import test above do that, and both were measured to go red on a
    plain revert.

    What it does protect is the precondition that makes the repoint safe and
    that a later packet could quietly break: facade, owner and nucleus must
    keep resolving to one object per name. The last assertion is the load-
    bearing one. If someone gives ``base.py`` its own definition of any of
    these nine names instead of re-exporting, the twin layer and every legacy
    facade consumer would silently be validating against two different
    contract authorities -- a release-blocking defect by this repository's own
    review rules -- and this test goes red on it.
    """
    import importlib

    checked = 0
    names: set[str] = set()
    for module_name, symbols in MOVED_BINDINGS:
        module = importlib.import_module(module_name)
        for symbol in symbols:
            checked += 1
            names.add(symbol)
            bound = getattr(module, symbol)
            assert bound is getattr(_facade, symbol), (module_name, symbol)
            assert bound is getattr(_owner, symbol), (module_name, symbol)
            assert bound is getattr(_nucleus, symbol), (module_name, symbol)
    assert checked == 15
    assert len(names) == 9

    # One nucleus, not two: the owner re-exports these names and defines none
    # of them. Read from source, so a runtime rebinding cannot satisfy it.
    owner_source = (
        ROOT / "daedalus" / "kernel" / "contracts" / "base.py"
    ).read_text(encoding="utf-8")
    owner_tree = ast.parse(owner_source, filename="daedalus/kernel/contracts/base.py")
    defined = {
        node.name
        for node in ast.walk(owner_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    } | {
        target.id
        for node in ast.walk(owner_tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert defined & names == set()


def test_twin_boundary_rule_is_registered_and_at_least_as_strict_as_the_kernel() -> None:
    """The rule that keeps this closed, and the argument for its exact shape.

    ``daedalus.kernel`` imports ``daedalus.twin``, so anything twin may reach,
    the kernel reaches. A ``twin-no-outer-layers`` forbidden set narrower than
    ``kernel-no-outer-layers``' would let the kernel rule pass in syntax while
    the layer it names is loaded in every kernel process regardless.
    """
    contract = load_contract(CONTRACT_PATH)
    rules = {rule.rule_id: rule for rule in contract.rules}

    assert "twin-no-outer-layers" in rules
    twin_rule = rules["twin-no-outer-layers"]
    kernel_rule = rules["kernel-no-outer-layers"]
    assert twin_rule.source_prefixes == ("daedalus.twin",)
    assert set(kernel_rule.forbidden_target_prefixes) <= set(
        twin_rule.forbidden_target_prefixes
    )

    # ``daedalus.twin`` must stay out of the kernel rule: the one kernel->twin
    # edge is deliberate, and forbidding it there red-flags the module this
    # packet protects rather than the leak behind it.
    assert "daedalus.twin" not in kernel_rule.forbidden_target_prefixes

    report = evaluate_repository(ROOT, contract)
    assert contract.baseline == ()
    assert report.new == ()
    assert report.passed is True
