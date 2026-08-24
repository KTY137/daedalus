"""The Phase-4 door rows say what their code does, and can be made to lie.

WHAT IS BEING GUARDED
---------------------
Giga plan Phase 4 asks for the surviving unregistered doors to be registered or
removed. Ten module tails were registered. A row count would satisfy that
sentence without protecting anything -- the registry lane's own rule is that an
effect set must be DERIVED from the code, never painted on -- so this file does
not count rows. For every new row it re-derives the effect set from source and
asserts the label agrees IN BOTH DIRECTIONS:

* a reachable sink with no declared effect is an UNDER-DECLARATION;
* a declared effect with no reachable justification is a PAINTED LABEL.

The second direction is what makes the first worth having. Without it the
cheapest way to pass is to declare every effect on every door, and the registry
would then carry no information at all.

WHAT THE DERIVATION ACTUALLY MEASURED, AND WHERE IT CORRECTED THE AUTHOR
-----------------------------------------------------------------------
Three of the ten rows were wrong when they were first written by hand, and the
derivation is what found it. Recorded here because a rule that never
contradicted its author is a rule nobody has tested:

* ``cli.health`` denied FILESYSTEM_WRITE. The probes go out of their way not to
  create what they observe, which makes "a status read writes nothing" read as
  obviously true -- and ``_p_picker`` calls ``build_queue``, which reaches
  ``structcore.cache:FileCache.__init__``, which mkdirs a cache root and opens
  a sqlite index read-write.
* ``cli.picker`` and ``cli.bootstrap`` omitted PROCESS_CONTROL (the gate child
  runs under ``spine.cancel:ManagedProcess``, which Popens and kills it) and
  SECRETS (``offload`` reaches ``doctor:check``, which pulls DEEPSEEK_API_KEY
  into THIS process). ``cli.benchmark`` and ``cli.build_exec`` gained SECRETS
  for the same reason; ``cli.eval`` reaches neither and does not declare it,
  which is the discrimination that keeps the rule from being a rubber stamp.
* ``daedalus.progress:main`` was in the no-row column. ``--ledger`` opens
  SpineLedger read-only, and a read-only WAL open still creates the -wal/-shm
  sidecars, which cli.token_monitor already declares as FILESYSTEM_WRITE. It
  got row ``cli.progress`` instead of a verdict.

HOW EACH EFFECT CLASS IS DERIVED
--------------------------------
* filesystem_write / process_spawn / process_control / network_egress /
  listen_socket: from ``effect_boundary._direct_effects`` -- the scanner's OWN
  sink table -- applied over the repository-local call closure below.
* spend: no call shape means "money", so it comes from
  ``daedalus.budget.BILLABLE_SITES``, the repository's own list of paid sites.
* repository_mutation: no sink either (`git worktree add` is a subprocess), so
  it comes from reaching a target that ANOTHER registry row already labels
  REPOSITORY_MUTATION. A row may never justify itself.
* secrets: a credential-shaped environment read inside the closure -- the same
  regex tests/test_provider_secrets_rows.py uses, widened to accept a
  credential-named VARIABLE, because ``daedalus.kernel.approvals`` takes the
  variable name from ``--secret-env`` and the literal-only rule cannot see it.

THE CLOSURE IS A LOWER BOUND, and the two places it cannot see are declared as
BRIDGES rather than waved through: each names the hop, the reason, and a fact
this file re-checks, so the exception cannot rot silently.

NO PYTEST, NO UNITTEST: plain asserts, callable as ``python
tests/test_registry_new_doors.py`` and collectable by a suite either way.

MUTATION NOTE (how to see these go red):
  * delete any ``begin_effect`` call in a registered door -> the anchor probe
    and the conformance probe both fail;
  * move one below ``parse_args`` -> the ordering probe fails;
  * drop ``Effect.SECRETS`` from ``cli.picker`` -> the under-declaration
    direction fails;
  * add ``Effect.LISTEN_SOCKET`` to any new row -> the painted-label direction
    fails;
  * add a write to ``daedalus.metrics:main`` -> the no-row verdict fails and
    demands a row.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.budget import BILLABLE_SITES  # noqa: E402
from daedalus.spine.effect_boundary import (  # noqa: E402
    ENTRYPOINTS,
    REGISTRY_BY_ID,
    Effect,
    Surface,
    Wiring,
    _called_names,
    _direct_effects,
    _models,
    _target_node,
    check_conformance,
)

# --------------------------------------------------------------------------- #
# what this file is about                                                      #
# --------------------------------------------------------------------------- #

#: The ten rows Phase 4 added, and the entry function each one guards.
NEW_ROWS: dict[str, str] = {
    "cli.killswitch": "daedalus.spine.killswitch:_main",
    "cli.health": "daedalus.health:main",
    "cli.progress": "daedalus.progress:main",
    "cli.project_memory": "daedalus.memory.projection_worker:main",
    "cli.eval": "daedalus.eval.__main__:main",
    "cli.approvals": "daedalus.kernel.approvals:main",
    "cli.picker": "daedalus.spine.picker:main",
    "cli.benchmark": "daedalus.benchmark:main",
    "cli.build_exec": "daedalus.build_exec:main",
    "cli.bootstrap": "daedalus.spine.bootstrap:main",
}

#: The four candidates that were examined and deliberately got NO row, with the
#: claim each refusal rests on.  Tested, so a refusal cannot quietly rot into a
#: gap: if one of these starts performing an effect, its probe fails and asks
#: for a row.
NO_ROW: dict[str, str] = {
    "daedalus.metrics:main": (
        "read-only reporter: summary() -> _load() -> read_text; record() is "
        "the module's writer and main never calls it"
    ),
    "daedalus.claude_bridge:main": (
        "fail-closed stub: parse_args then parser.error, no reachable effect; "
        "its row was deliberately deleted 2026-08-17 for this reason"
    ),
    "daedalus.structcore.index:build_index": (
        "library runner with no module tail; reached only through doors that "
        "already carry a row"
    ),
    "daedalus.memory.__init__:main": (
        "already registered as cli.memory; a second row would be a duplicate "
        "target"
    ),
}

#: Hops the name-based closure provably cannot follow.  Each entry is (row id,
#: effect, reason, checker name) and every one is re-verified by
#: ``test_the_bridges_are_checked_not_believed`` below.  This list is the
#: honest alternative to widening the closure until it says what the author
#: wanted: two named exceptions beat one unfalsifiable heuristic.
BRIDGES: dict[tuple[str, str], str] = {
    ("cli.project_memory", "network_egress"): (
        "EventVectorStore._backend() RETURNS the embedding backend "
        "(`self._backend_override or OllamaEmbeddingBackend(host)`), and the "
        "closure resolves methods on constructor-bound names, not on "
        "method-returned ones. The POST is at "
        "memory/embeddings.py OllamaEmbeddingBackend.embed."
    ),
    ("cli.build_exec", "repository_mutation"): (
        "WaveExecutor.run_wave hands the write path to "
        "kairos.gated_writes:run_write_wave, which lives in the retained "
        "legacy source daedalus/kairos/_gated_writes_legacy.py.src -- loaded "
        "through importlib.resources behind a sha1 check, and outside "
        "SCAN_PACKAGES because its suffix is not `.py`. That blob imports "
        "GitWorktreeManager and calls run_attempt."
    ),
}

#: ``daedalus.health`` dispatches its probes through a table
#: (``assess`` calls ``spec.fn(ctx)``), so no call-graph walk reaches them from
#: ``main``.  The table has exactly one populator -- the ``@probe(...)``
#: decorator -- so the probe set is statically enumerable, and enumerating it
#: is a rule, not a special case.
DISPATCH_ROOTS: dict[str, str] = {"daedalus.health": "probe"}

CREDENTIAL = re.compile(r"(API_KEY|_KEY$|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
BILLABLE = {
    (row["file"].replace("/", ".")[: -len(".py")], row["func"])
    for row in BILLABLE_SITES
}
#: Effects with no AST sink at all; they are derived from another authority.
NO_SINK = {Effect.SPEND, Effect.REPOSITORY_MUTATION, Effect.SECRETS}

MODELS = {model.module: model for model in _models(ROOT)[0]}


# --------------------------------------------------------------------------- #
# the closure                                                                  #
# --------------------------------------------------------------------------- #
def _package(module: str) -> str:
    if module.endswith(".__init__"):
        return module[: -len(".__init__")]
    return module.rsplit(".", 1)[0] if "." in module else ""


def _aliases(module: str, node: ast.AST) -> dict[str, str]:
    """Absolute names for the imports under ``node``, relative imports resolved.

    ``_ModuleModel.aliases`` keeps ``from .harness import x`` as
    ``harness.x``, which is enough for its own sink matching and not enough to
    find the module that owns ``x``.
    """
    package = _package(module)
    out: dict[str, str] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(child, ast.ImportFrom):
            base = child.module or ""
            if child.level:
                parts = package.split(".") if package else []
                if child.level > 1:
                    parts = parts[: -(child.level - 1)] or []
                base = ".".join([*parts, base]) if base else ".".join(parts)
            for alias in child.names:
                out[alias.asname or alias.name] = (
                    f"{base}.{alias.name}" if base else alias.name
                )
    return out


def _owner(absolute: str) -> tuple[str, str] | None:
    """Split a dotted absolute name into (scanned module, remainder)."""
    parts = absolute.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module, rest = ".".join(parts[:cut]), ".".join(parts[cut:])
        for candidate in (module, module + ".__init__"):
            if candidate in MODELS:
                return candidate, rest
    return None


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


_BINDINGS: dict[str, dict[str, tuple[str, str]]] = {}
_LOCAL: dict[str, dict[str, tuple[set[Effect], set[str], set[str]]]] = {}


def _bindings(module: str) -> dict[str, tuple[str, str]]:
    """``name`` / ``self.attr`` -> the class it was constructed from.

    Enough to follow ``switch = KillSwitch(path); switch.stop()`` and
    ``store = EventVectorStore(...); store.record_journal_watermark(...)``,
    which is how three of these doors reach their sinks.
    """
    if module in _BINDINGS:
        return _BINDINGS[module]
    model = MODELS[module]
    aliases = _aliases(module, model.tree)
    out: dict[str, tuple[str, str]] = {}

    def note(target: ast.AST, value: ast.AST) -> None:
        if not isinstance(value, ast.Call):
            return
        called = _dotted(value.func)
        if not called:
            return
        head = called.split(".")[0]
        hit = _owner(aliases.get(head, head) + called[len(head) :])
        owner: tuple[str, str] | None = None
        if hit is not None:
            klass = hit[1].split(".")[0]
            if any(k.startswith(klass + ".") for k in MODELS[hit[0]].functions):
                owner = (hit[0], klass)
        if owner is None:
            klass = called.rsplit(".", 1)[-1]
            if any(k.startswith(klass + ".") for k in model.functions):
                owner = (module, klass)
        if owner is None:
            return
        if isinstance(target, ast.Name):
            out[target.id] = owner
        elif (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            out["self." + target.attr] = owner

    for node in ast.walk(model.tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                note(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            note(node.target, node.value)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            note(node.optional_vars, node.context_expr)
    _BINDINGS[module] = out
    return out


def _local(module: str):
    if module not in _LOCAL:
        model = MODELS[module]
        _LOCAL[module] = {
            name: _direct_effects(node, model.aliases)
            for name, node in model.functions.items()
        }
    return _LOCAL[module]


def _probe_roots(module: str) -> tuple[tuple[str, str], ...]:
    decorator = DISPATCH_ROOTS.get(module)
    if decorator is None:
        return ()
    return tuple(
        (module, node.name)
        for node in MODELS[module].tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == decorator
            for item in node.decorator_list
        )
    )


_CLOSURE: dict[str, set[tuple[str, str]]] = {}
_DERIVED: dict[str, tuple[dict[str, list[str]], set[tuple[str, str]]]] = {}


def closure(target: str) -> set[tuple[str, str]]:
    """Every repository-local function the door can reach.

    Follows same-module calls, imported functions, methods on names bound to a
    constructor, ``self.method()``, ``self.property`` reads (a property read
    IS a call), ``Cls(...)`` into ``Cls.__init__``, and bare references to a
    function (passing a callable is how it gets called). It does NOT claim
    whole-program reachability: dynamic dispatch, methods returned from
    methods and non-``.py`` sources are exactly what BRIDGES and
    DISPATCH_ROOTS exist to name.
    """
    if target in _CLOSURE:
        return _CLOSURE[target]
    module, _, qualname = target.partition(":")
    seen: set[tuple[str, str]] = set()
    stack: list[tuple[str, str]] = [(module, qualname), *_probe_roots(module)]
    while stack:
        mod, qual = stack.pop()
        if (mod, qual) in seen or mod not in MODELS:
            continue
        model = MODELS[mod]
        if qual not in model.functions:
            continue
        seen.add((mod, qual))
        node = model.functions[qual]
        aliases = dict(model.aliases)
        aliases.update(_aliases(mod, model.tree))
        aliases.update(_aliases(mod, node))
        binds = _bindings(mod)
        klass = qual.split(".", 1)[0] if "." in qual else None
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id in model.functions:
                    stack.append((mod, child.id))
                referenced = aliases.get(child.id)
                if referenced:
                    hit = _owner(referenced)
                    if hit is not None and hit[1] in MODELS[hit[0]].functions:
                        stack.append(hit)
            if (
                isinstance(child, ast.Attribute)
                and isinstance(child.ctx, ast.Load)
                and isinstance(child.value, ast.Name)
                and child.value.id == "self"
                and klass
                and f"{klass}.{child.attr}" in model.functions
            ):
                stack.append((mod, f"{klass}.{child.attr}"))
            if not isinstance(child, ast.Call):
                continue
            called = _dotted(child.func)
            if not called:
                continue
            if "." in called:
                receiver, _, method = called.rpartition(".")
                if receiver == "self" and klass and f"{klass}.{method}" in model.functions:
                    stack.append((mod, f"{klass}.{method}"))
                bound = binds.get(receiver) or binds.get(
                    "self." + receiver.split(".")[-1]
                )
                if bound is not None and f"{bound[1]}.{method}" in MODELS[bound[0]].functions:
                    stack.append((bound[0], f"{bound[1]}.{method}"))
            if called in model.functions:
                stack.append((mod, called))
            if f"{called}.__init__" in model.functions:
                stack.append((mod, f"{called}.__init__"))
            head = called.split(".")[0]
            hit = _owner(aliases.get(head, head) + called[len(head) :])
            if hit is None:
                continue
            hmod, rest = hit
            if rest in MODELS[hmod].functions:
                stack.append((hmod, rest))
            else:
                candidate = f"{rest.split('.')[0]}.{rest.split('.')[-1]}"
                if candidate in MODELS[hmod].functions:
                    stack.append((hmod, candidate))
            if f"{rest}.__init__" in MODELS[hmod].functions:
                stack.append((hmod, f"{rest}.__init__"))
    _CLOSURE[target] = seen
    return seen


# --------------------------------------------------------------------------- #
# the derivation                                                               #
# --------------------------------------------------------------------------- #
def _credential_reads(reached) -> list[str]:
    found: list[str] = []
    for mod, qual in reached:
        for child in ast.walk(MODELS[mod].functions[qual]):
            if isinstance(child, ast.Call) and child.args:
                name = ast.unparse(child.func)
                if name.endswith("environ.get") or name.endswith("getenv"):
                    arg = child.args[0]
                    if isinstance(arg, ast.Constant) and CREDENTIAL.search(str(arg.value)):
                        found.append(f"{mod}:{qual}@{child.lineno} {arg.value}")
                    elif isinstance(arg, ast.Name) and CREDENTIAL.search(arg.id):
                        found.append(f"{mod}:{qual}@{child.lineno} <{arg.id}>")
            if isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
                if ast.unparse(child.value).endswith("environ") and CREDENTIAL.search(
                    str(child.slice.value)
                ):
                    found.append(f"{mod}:{qual}@{child.lineno} {child.slice.value}")
    return sorted(set(found))


def derive(target: str) -> tuple[dict[str, list[str]], set[tuple[str, str]]]:
    """Effect -> the witnesses that justify it, for one entry target."""
    if target in _DERIVED:
        return _DERIVED[target]
    reached = closure(target)
    own = tuple(target.partition(":")[::2])
    witnesses: dict[str, list[str]] = {}

    for mod, qual in sorted(reached):
        effects, evidence, _calls = _local(mod)[qual]
        for effect in effects:
            witnesses.setdefault(effect.value, []).append(
                f"{mod}:{qual} [{', '.join(sorted(evidence))}]"
            )

    for mod, qual in sorted(reached):
        if (mod.replace(".__init__", ""), qual) in BILLABLE:
            witnesses.setdefault(Effect.SPEND.value, []).append(
                f"BILLABLE_SITES {mod}:{qual}"
            )

    for spec in ENTRYPOINTS:
        other = tuple(spec.target.partition(":")[::2])
        if other == own or other not in reached:
            continue
        for effect in spec.effects:
            if effect in NO_SINK:
                witnesses.setdefault(effect.value, []).append(
                    f"row {spec.id} declares it on {spec.target}"
                )

    for item in _credential_reads(reached):
        witnesses.setdefault(Effect.SECRETS.value, []).append(f"credential {item}")

    _DERIVED[target] = (witnesses, reached)
    return witnesses, reached


def _boundary_lines(target: str) -> dict[str, int]:
    module, _, qualname = target.partition(":")
    node = MODELS[module].functions[qualname]
    lines: dict[str, int] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _dotted(child.func).rsplit(".", 1)[-1]
            if name and name not in lines:
                lines[name] = child.lineno
    return lines


# --------------------------------------------------------------------------- #
# the probes                                                                   #
# --------------------------------------------------------------------------- #
def test_every_new_row_is_central_with_a_resolving_anchor():
    """A row that names a call the source no longer makes is decoration."""
    problems: list[str] = []
    for row_id, target in NEW_ROWS.items():
        spec = REGISTRY_BY_ID.get(row_id)
        if spec is None:
            problems.append(f"{row_id}: no such row")
            continue
        if spec.target != target:
            problems.append(f"{row_id}: target is {spec.target}, expected {target}")
        if spec.surface is not Surface.CLI:
            problems.append(f"{row_id}: surface is {spec.surface.value}, expected cli")
        if spec.wiring is not Wiring.CENTRAL:
            problems.append(f"{row_id}: wiring is {spec.wiring.value}, expected central")
        if not spec.guard_contracts:
            problems.append(f"{row_id}: central row with no guard contract")
        if not spec.anchors:
            problems.append(f"{row_id}: no guard anchor")
        for anchor in spec.anchors:
            located = _target_node(MODELS, anchor.target)
            if located is None:
                problems.append(f"{row_id}: anchor target {anchor.target} is gone")
                continue
            model, node = located
            calls = _called_names(node, model.aliases)
            if not any(
                call == anchor.call or call.endswith("." + anchor.call) for call in calls
            ):
                problems.append(
                    f"{row_id}: {anchor.target} no longer calls {anchor.call}"
                )
    assert not problems, "registry rows do not match the tree:\n" + "\n".join(problems)


def test_every_registered_door_starts_at_the_boundary_before_anything_else():
    """Ordering no runtime trace can prove for every future code path.

    ``begin_effect`` above argument handling is what makes the start
    unconditional: no ``--help``, no parse error and no branch added later can
    reach an effect around it. The rule asserted here is stronger than "above
    parse_args", because ``killswitch._main`` parses argv by hand and has no
    ``parse_args`` to be above: the boundary call must precede EVERY other
    call in the function.
    """
    problems: list[str] = []
    for row_id, target in NEW_ROWS.items():
        lines = _boundary_lines(target)
        if "begin_effect" not in lines:
            problems.append(f"{row_id}: {target} does not call begin_effect")
            continue
        if "process_guard_boundary_decision" not in lines:
            problems.append(f"{row_id}: {target} takes no process_guard decision")
            continue
        first = lines["begin_effect"]
        # The decision call is an ARGUMENT of begin_effect, so it is allowed to
        # sit below it; nothing else is.
        later = {
            name: line
            for name, line in lines.items()
            if name not in {"begin_effect", "process_guard_boundary_decision"}
            and line <= first
        }
        if later:
            problems.append(
                f"{row_id}: {sorted(later)} run at or before the boundary "
                f"(begin_effect at line {first})"
            )
        if "parse_args" in lines and lines["parse_args"] <= first:
            problems.append(f"{row_id}: parse_args precedes the boundary")
    assert not problems, "the boundary is not first:\n" + "\n".join(problems)


def test_no_declared_effect_is_painted_on():
    """Every declared effect names code that really performs it."""
    problems: list[str] = []
    for row_id, target in NEW_ROWS.items():
        spec = REGISTRY_BY_ID[row_id]
        witnesses, _reached = derive(target)
        for effect in spec.effects:
            if witnesses.get(effect.value):
                continue
            if (row_id, effect.value) in BRIDGES:
                continue
            problems.append(
                f"{row_id} declares {effect.value} with no reachable "
                f"justification and no declared bridge"
            )
    assert not problems, "painted labels:\n" + "\n".join(problems)


def test_no_reachable_effect_is_left_undeclared():
    """Every effect the derivation finds is on the row."""
    problems: list[str] = []
    for row_id, target in NEW_ROWS.items():
        declared = {effect.value for effect in REGISTRY_BY_ID[row_id].effects}
        witnesses, _reached = derive(target)
        for value, evidence in sorted(witnesses.items()):
            if value not in declared:
                problems.append(f"{row_id} performs {value} ({evidence[0]}) undeclared")
    assert not problems, "under-declared doors:\n" + "\n".join(problems)


def test_the_bridges_are_checked_not_believed():
    """The two hops the closure cannot follow are still really there.

    A declared exception that nobody re-checks is how a derivation quietly
    stops deriving. Each bridge names a fact; this asserts the fact.
    """
    # 1. project_memory -> the embedding POST, through a method-returned object.
    embeddings = (ROOT / "daedalus" / "memory" / "embeddings.py").read_text(
        encoding="utf-8"
    )
    assert "OllamaEmbeddingBackend(host)" in embeddings, (
        "EventVectorStore no longer constructs the embedding backend; the "
        "cli.project_memory network_egress bridge is stale"
    )
    backend_effects, _e, _c = _local("daedalus.memory.embeddings")[
        "OllamaEmbeddingBackend.embed"
    ]
    assert Effect.NETWORK_EGRESS in backend_effects, (
        "OllamaEmbeddingBackend.embed no longer opens a socket; "
        "cli.project_memory should not declare network_egress"
    )
    store_reached = closure("daedalus.memory.projection_worker:main")
    assert ("daedalus.memory.embeddings", "EventVectorStore._backend") in store_reached, (
        "the worker no longer reaches the backend selector; re-derive the row"
    )

    # 2. build_exec -> the worktree, through a retained non-.py legacy source.
    legacy = ROOT / "daedalus" / "kairos" / "_gated_writes_legacy.py.src"
    assert legacy.exists(), f"the retained legacy source is gone: {legacy}"
    tree = ast.parse(legacy.read_text(encoding="utf-8"), filename=str(legacy))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "run_write_wave" in names, (
        "the retained source no longer defines run_write_wave; the "
        "cli.build_exec repository_mutation bridge is stale"
    )
    calls = {_dotted(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert "run_attempt" in calls, (
        "the retained write wave no longer calls run_attempt, so the worktree "
        "is no longer reachable from cli.build_exec"
    )
    assert "GitWorktreeManager" in calls, (
        "the retained write wave no longer constructs a worktree manager"
    )
    assert "run_write_wave" in (
        (ROOT / "daedalus" / "build_exec.py").read_text(encoding="utf-8")
    ), "build_exec no longer hands down to the gated write path"


def test_the_no_row_verdicts_are_still_true():
    """A refusal to register is a claim, and claims rot.

    Four candidates were examined and deliberately left without a row. If any
    of them starts performing an effect this fails and asks for one, which is
    the difference between a decision and an omission.
    """
    problems: list[str] = []
    for target, reason in NO_ROW.items():
        module, _, qualname = target.partition(":")
        if module not in MODELS or qualname not in MODELS[module].functions:
            problems.append(f"{target}: gone from the tree ({reason})")
            continue
        if target == "daedalus.memory.__init__:main":
            owners = [spec.id for spec in ENTRYPOINTS if spec.target == target]
            if owners != ["cli.memory"]:
                problems.append(f"{target}: expected exactly cli.memory, got {owners}")
            continue
        witnesses, _reached = derive(target)
        if target == "daedalus.structcore.index:build_index":
            # A library runner IS effectful; the claim is that it has no door
            # of its own, not that it is inert.
            source = (ROOT / "daedalus" / "structcore" / "index.py").read_text(
                encoding="utf-8"
            )
            if "__main__" in source:
                problems.append(f"{target}: the library grew a module tail")
            if "main" in MODELS[module].functions:
                problems.append(f"{target}: the library grew a main()")
            continue
        if witnesses:
            problems.append(
                f"{target} now performs {sorted(witnesses)}; the no-row "
                f"verdict ({reason}) no longer holds"
            )
    assert not problems, "a no-row verdict went stale:\n" + "\n".join(problems)


def test_the_derivation_is_not_vacuous():
    """A rule that finds nothing makes every probe above pass by saying nothing.

    So pin the ground truth this head measured, in both directions, including
    the discrimination that a blanket rule would lose: the four offload doors
    read a credential in-process and cli.eval does not.
    """
    picker, _ = derive("daedalus.spine.picker:main")
    assert "secrets" in picker and any(
        "DEEPSEEK_API_KEY" in item for item in picker["secrets"]
    ), picker.get("secrets")
    assert "process_control" in picker and any(
        "cancel" in item for item in picker["process_control"]
    ), picker.get("process_control")
    assert "repository_mutation" in picker and any(
        "run_attempt" in item for item in picker["repository_mutation"]
    ), picker.get("repository_mutation")

    evaluation, _ = derive("daedalus.eval.__main__:main")
    assert "secrets" not in evaluation, (
        "cli.eval now reads a credential; the rule was supposed to "
        "discriminate, so declare it rather than deleting this line"
    )
    assert "spend" in evaluation and any(
        "BILLABLE_SITES" in item for item in evaluation["spend"]
    ), evaluation.get("spend")

    approvals, _ = derive("daedalus.kernel.approvals:main")
    assert approvals.get("secrets") and any(
        "<secret_env>" in item for item in approvals["secrets"]
    ), (
        "the parameterised credential read is the whole reason this file "
        "widened the literal-name rule"
    )

    health_effects = set(derive("daedalus.health:main")[0])
    assert "filesystem_write" in health_effects, (
        "the FileCache write the derivation caught is gone; this is the "
        "correction that proved the rule catches its own author"
    )

    metrics, _ = derive("daedalus.metrics:main")
    assert metrics == {}, f"the read-only reporter is no longer read-only: {metrics}"


def test_a_planted_effect_and_a_deleted_one_are_both_caught():
    """The mutation test, run rather than described.

    Both directions are asserted above against the real registry; here they
    are exercised against deliberately wrong copies of a row, so a future
    refactor that makes the checks vacuous fails HERE instead of passing
    everywhere.
    """
    from dataclasses import replace

    real = REGISTRY_BY_ID["cli.picker"]
    witnesses, _ = derive(real.target)
    declared = {effect.value for effect in real.effects}

    painted = replace(real, effects=real.effects + (Effect.LISTEN_SOCKET,))
    unjustified = [
        effect.value
        for effect in painted.effects
        if not witnesses.get(effect.value)
        and (painted.id, effect.value) not in BRIDGES
    ]
    assert unjustified == ["listen_socket"], (
        "the painted-label direction did not catch a planted effect: "
        f"{unjustified}"
    )

    stripped = tuple(e for e in real.effects if e is not Effect.SECRETS)
    missing = [value for value in witnesses if value not in {e.value for e in stripped}]
    assert missing == ["secrets"], (
        f"the under-declaration direction did not catch a deleted effect: {missing}"
    )
    assert "secrets" in declared, "cli.picker lost SECRETS; the probe above is moot"


def test_the_new_rows_add_no_conformance_blocker():
    """Registering ten doors must not make the matrix worse.

    Ten ``entrypoint.not_rediscovered`` REVIEW findings are the expected and
    documented price -- the registry's own label for a registered target the
    conservative scanner cannot classify, which is precisely why these doors
    survived unregistered. Blockers and Gate-0 gaps must not move.
    """
    report = check_conformance(ROOT)
    blockers = sorted(
        (finding.code, finding.subject)
        for finding in report.findings
        if finding.severity == "blocker"
    )
    #: MEASURED 2026-08-24 after b90d236a: the rollback drift was the
    #: scanner's ignorance-default and is a review finding now, so the
    #: measured blocker set is EMPTY -- and Phase 4 must keep it that way.
    assert blockers == [], f"new conformance blockers: {blockers}"

    gaps = [f for f in report.findings if f.severity == "gap"]
    assert len(gaps) == 19, f"Gate-0 gap count moved to {len(gaps)}"

    not_rediscovered = {
        finding.subject
        for finding in report.findings
        if finding.code == "entrypoint.not_rediscovered"
    }
    for target in NEW_ROWS.values():
        assert target in not_rediscovered, (
            f"{target} is now rediscovered by the scanner -- good news, but "
            f"this probe's accounting is stale"
        )


if __name__ == "__main__":
    failures = 0
    for name, probe in sorted(globals().items()):
        if not name.startswith("test_") or not callable(probe):
            continue
        try:
            probe()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}\n  {exc}")
        else:
            print(f"ok   {name}")
    raise SystemExit(1 if failures else 0)
