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

THE CLOSURE IS A LOWER BOUND, and the one place it cannot see is declared as a
BRIDGE rather than waved through: it names the hop, the reason, and a fact this
file re-checks, so the exception cannot rot silently. There were two until
2026-09-02; teaching the walk to resolve an annotated port made the
``cli.project_memory`` one unnecessary, and it was DELETED rather than left
lying around, because a bridge suppresses the painted-label check for its row.

WHAT THE WALK LEARNED IN 2026-09 (and why the closure grew)
------------------------------------------------------------
The hierarchy refactor moved implementations one layer down and left the
historical locators behind as facades. The name-based walk kept resolving to
the locator, found an empty module, and derived nothing -- 14 of 42 declared
effects lost their justification while the UNDER-declaration direction went on
passing, because a walk that reaches nothing reports no undeclared effect
either. tests/registry_facades.py teaches it the six constructs involved
(module aliases, re-exports, module-class facades, PEP 562 tables, inherited
doors, and receivers named by a type annotation) and refuses rather than
resolving to nothing when a hop lands on a module that cannot be parsed.
tests/test_registry_facade_order.py plants a real sink behind each construct
and checks every fixture against a blinded control.

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
from contextlib import contextmanager
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
    _target_node,
    check_conformance,
)

if str(Path(__file__).resolve().parent) not in sys.path:  # noqa: E402
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry_facades import (  # noqa: E402
    Resolver,
    models as _facade_models,
    resolver,
)

# --------------------------------------------------------------------------- #
# what this file is about                                                      #
# --------------------------------------------------------------------------- #

#: The ten rows Phase 4 added, and the entry function each one guards.
PHASE4_ROWS: dict[str, str] = {
    "cli.killswitch": "daedalus.spine.killswitch:_main",
    "cli.health": "daedalus.health:main",
    "cli.progress": "daedalus.progress:main",
    "cli.project_memory": "daedalus.memory.projection_worker:main",
    "cli.eval": "daedalus.eval.__main__:main",
    "cli.approvals": "daedalus.kernel.approvals:main",
    "cli.picker": "daedalus.spine.picker:main",
    "cli.benchmark": "daedalus.orchestration.benchmark:main",
    "cli.build_exec": "daedalus.build_exec:main",
    "cli.bootstrap": "daedalus.spine.bootstrap:main",
}

#: Doors registered AFTER the Phase-4 sweep, kept in a second dict for one
#: reason that is not cosmetic: the Phase-4 ten are all invisible to the static
#: scanner (that is why they survived unregistered, and why each costs an
#: ``entrypoint.not_rediscovered`` REVIEW finding), whereas these three were
#: FOUND by the scanner as ``entrypoint.unregistered`` blockers in the Gate-0
#: report at 0430c07f.  Merging them into one dict would have forced the
#: accounting probe below to accept either answer for either group, which is
#: how a probe stops discriminating.  Every derivation probe still runs over
#: both groups through ``NEW_ROWS``.
LATE_ROWS: dict[str, str] = {
    "cli.wiki_plan": "daedalus.wiki.plan:main",
    "cli.wiki_verify": "daedalus.wiki.verify:main",
    "tools.docs_reference_check": "tools.docs_reference_check:main",
}

#: Post-renovation doors whose effects are visible to the repository-local
#: closure above, but whose thin wrapper is not rediscovered by the deliberately
#: conservative Gate-0 entrypoint scanner. Keep this distinction explicit: the
#: exact effect derivation still runs over the row, while conformance records
#: the expected ``entrypoint.not_rediscovered`` REVIEW finding.
STATIC_ONLY_ROWS: dict[str, str] = {
    "cli.ignition": "daedalus.ignition.__main__:main",
}

#: Every row this file derives, both groups.
NEW_ROWS: dict[str, str] = {
    **PHASE4_ROWS,
    **LATE_ROWS,
    **STATIC_ONLY_ROWS,
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
#: wanted: a named exception beats an unfalsifiable heuristic.
#:
#: RETIRED 2026-09-02, ``("cli.project_memory", "network_egress")``.  Its reason
#: was that ``EventVectorStore._backend()`` RETURNS the backend
#: (``self._backend_override or OllamaEmbeddingBackend(host)``) and the closure
#: resolved methods only on constructor-bound names.  That is no longer true:
#: the consumers take ``backend: EmbeddingBackend`` as an annotated parameter,
#: and the walk now resolves an annotated port to the classes that implement it,
#: so it reaches ``memory/embeddings.py OllamaEmbeddingBackend.embed``
#: (``urllib.request.urlopen@517``) on its own -- MEASURED, and re-asserted in
#: ``test_the_bridges_are_checked_not_believed``.  The measured path is
#: ``projection_worker:main -> ProjectionWorker.run ->
#: EventVectorStore.ingest_events_report -> _verify_identity ->
#: OllamaEmbeddingBackend.embed``; with the port hop disabled the row drops back
#: to ``filesystem_write`` alone, so it really is the annotation carrying it.
#: The one caveat: that hop rests on ``EmbeddingBackend`` having exactly one
#: repository-local implementation.  A second one widens the closure rather than
#: breaking it, and the painted-label direction is what would notice.
#:
#: The entry is deleted rather than kept as a harmless leftover.  A bridge
#: suppresses the painted-label check for its row and effect, so a stale one is
#: a standing pre-authorisation: delete the POST tomorrow and the row would stay
#: green on the strength of an exception nobody needed.  Narrowing this table is
#: the opposite of the widening that would have "fixed" this packet cheaply.
BRIDGES: dict[tuple[str, str], str] = {
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

MODELS = _facade_models(ROOT)


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


#: Follows the four facade constructs the hierarchy refactor left on the
#: derivation path -- whole-module ``sys.modules`` aliases, re-exports, the
#: module-class fallback, and PEP 562 tables. See tests/registry_facades.py for
#: what each one means for a lookup, why module-scope statements are
#: interpreted in ORDER, and why an unreadable owner raises instead of
#: resolving to nothing.
RESOLVER = resolver(ROOT)


def _owner(absolute: str) -> tuple[str, str] | None:
    """Split a dotted absolute name into (owning scanned module, remainder).

    The split alone is no longer enough. ``daedalus.spine.ledger`` still
    resolves as a module, but it is twelve lines that replace themselves in
    ``sys.modules`` with ``daedalus.kernel.events.ledger``; stopping at the
    locator finds a module with no functions and reports no effects. The
    resolver carries the name the rest of the way to the module that defines
    it, and REFUSES rather than reporting nothing when a hop lands on a
    scanned module the model set could not parse.
    """
    return RESOLVER.resolve(absolute)


def _module_aliases(module: str) -> dict[str, str]:
    """Module-scope names with the dead ones removed; see ``Resolver.aliases``."""
    return RESOLVER.aliases(module)


@contextmanager
def walk_over(replacement: dict):
    """Run this file's walk over a DIFFERENT model set, then restore this one.

    The walk reads the repository through module-level state
    (``MODELS``/``RESOLVER`` and three memo tables), which is right for an
    instrument whose subject is one fixed tree. It also means the walk cannot
    be pointed at a planted example, and a derivation nobody can aim at a known
    answer is a derivation nobody has tested.

    ``tests/test_registry_facade_order.py`` uses this to plant a real sink
    behind each construct the walk claims to follow, and to plant the six
    statement-order shapes that must NOT open a facade, and checks both against
    a blinded control. Nothing in the production path calls it.
    """
    global MODELS, RESOLVER, _CLOSURE, _BINDINGS, _LOCAL, _DERIVED
    saved = (MODELS, RESOLVER, _CLOSURE, _BINDINGS, _LOCAL, _DERIVED)
    MODELS, RESOLVER = replacement, Resolver(replacement)
    # EVERY memo, including _DERIVED. A cache left behind here does not fail --
    # it answers the new tree's question with the old tree's answer, which is
    # the one result a fixture cannot detect.
    _CLOSURE, _BINDINGS, _LOCAL, _DERIVED = {}, {}, {}, {}
    try:
        yield RESOLVER
    finally:
        MODELS, RESOLVER, _CLOSURE, _BINDINGS, _LOCAL, _DERIVED = saved


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
    aliases = _module_aliases(module)
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


def _constructed_class(
    module: str, model, aliases: dict[str, str], call: ast.Call
) -> tuple[str, str] | None:
    """``(module, class)`` for a ``Cls(...)`` call, or None if it is not one."""
    called = _dotted(call.func)
    if not called:
        return None
    if called in model.class_bases:
        return module, called
    head = called.split(".")[0]
    hit = _owner(aliases.get(head, head) + called[len(head) :])
    if hit is not None and hit[1] in MODELS[hit[0]].class_bases:
        return hit
    return None


def _annotation_names(node: ast.AST | None) -> list[str]:
    """Every dotted type name in an annotation, with ``| None`` unwrapped."""
    if node is None:
        return []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_names(node.left) + _annotation_names(node.right)
    if isinstance(node, ast.Subscript):
        # ``Optional[X]`` and ``Annotated[X, ...]`` still describe the RECEIVER.
        # Every other generic -- ``Sequence[X]``, ``Mapping[str, X]``,
        # ``Callable[[X], Y]`` -- describes the CONTENTS, and treating a
        # container's element type as the receiver's type would attribute
        # ``mapping.get(...)`` to a method on the value class. Narrow on
        # purpose: an annotation this reader cannot use yields nothing, and a
        # missing witness fails loudly in the painted-label direction, while a
        # wrong one quietly justifies an effect.
        if _dotted(node.value).rsplit(".", 1)[-1] not in {"Optional", "Annotated"}:
            return []
        inner = node.slice
        if isinstance(inner, ast.Tuple) and inner.elts:
            inner = inner.elts[0]
        return _annotation_names(inner)
    if isinstance(node, ast.Tuple):
        return [name for element in node.elts for name in _annotation_names(element)]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _annotation_names(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return []
    dotted = _dotted(node)
    return [dotted] if dotted else []


def _ports(
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Parameter name -> the classes that satisfy its annotated Protocol.

    The refactor moved the workspace and evaluator capabilities behind neutral
    ports, so the kernel now says ``evaluator_port.command_gate(...)``. No
    constructor binds that receiver -- it is a parameter -- which is why the
    walk stopped there and three doors lost the gate child that justifies their
    PROCESS_CONTROL. The annotation is the evidence, and
    ``Resolver.implementations`` turns it into named classes rather than a
    guess; a parameter whose annotation is not a repository-local Protocol
    yields nothing.
    """
    out: dict[str, tuple[tuple[str, str], ...]] = {}
    arguments = node.args
    for arg in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ):
        implementations: list[tuple[str, str]] = []
        for name in _annotation_names(arg.annotation):
            if name in MODELS[module].class_bases:
                # Declared in this very module; ``_owner`` needs a dotted
                # prefix and would refuse a bare local name.
                hit: tuple[str, str] | None = (module, name)
            else:
                head = name.split(".")[0]
                hit = _owner(aliases.get(head, head) + name[len(head) :])
            if hit is None or "." in hit[1]:
                continue
            implementations.extend(RESOLVER.receivers(hit[0], hit[1]))
        if implementations:
            out[arg.arg] = tuple(dict.fromkeys(implementations))
    return out


def closure(target: str) -> set[tuple[str, str]]:
    """Every repository-local function the door can reach.

    Follows same-module calls, imported functions, methods on names bound to a
    constructor, ``self.method()``, ``self.property`` reads (a property read
    IS a call), ``Cls(...)`` into ``Cls.__init__``, ``Cls(...).method()``, and
    bare references to a function (passing a callable is how it gets called).

    Since the hierarchy refactor it also follows the six constructs the moved
    implementations hide behind -- module aliases, re-exports, module-class
    facades, PEP 562 tables, inherited doors including ``super()``, and a
    receiver whose type an annotation names. Those live in
    tests/registry_facades.py, which documents each one and refuses (rather
    than resolving to nothing) when a hop lands on a module that cannot be
    parsed. tests/test_registry_facade_order.py plants a real sink behind every
    one of them and checks each fixture against a blinded control, so a
    construct the walk stops following fails there.

    It still does NOT claim whole-program reachability: a callable with no
    readable type -- passed through ``**kwargs``, taken out of a dict, or
    returned by a method -- plus non-``.py`` sources are exactly what BRIDGES
    and DISPATCH_ROOTS exist to name.
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
        aliases = _module_aliases(mod)
        aliases.update(_aliases(mod, node))
        binds = _bindings(mod)
        ports = _ports(mod, node, aliases)
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
            ):
                inherited = RESOLVER.method(mod, klass, child.attr)
                if inherited is not None:
                    stack.append(inherited)
            if not isinstance(child, ast.Call):
                continue
            # ``super().m(...)``: the base's ``m``, not this class's. The dotted
            # name of that call is bare ``m`` -- indistinguishable from a call
            # to a module-level ``m`` -- so it is matched on the AST shape.
            if (
                isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Call)
                and _dotted(child.func.value.func) == "super"
                and klass
            ):
                for base in RESOLVER.bases(mod, klass):
                    found = _owner(base)
                    if found is None or "." in found[1]:
                        continue
                    inherited = RESOLVER.method(found[0], found[1], child.func.attr)
                    if inherited is not None:
                        stack.append(inherited)
                        break
            # ``Cls(...).method()``: the construct-and-call shape. No name is
            # ever bound, so ``_bindings`` cannot see it -- and it is how
            # ``run_attempt`` reaches the whole Attempt lifecycle
            # (``TaskAttempt(task, **kwargs).run()``).
            if isinstance(child.func, ast.Attribute) and isinstance(
                child.func.value, ast.Call
            ):
                constructed = _constructed_class(
                    mod, model, aliases, child.func.value
                )
                if constructed is not None:
                    inherited = RESOLVER.method(*constructed, child.func.attr)
                    if inherited is not None:
                        stack.append(inherited)
            called = _dotted(child.func)
            if not called:
                continue
            if "." in called:
                receiver, _, method = called.rpartition(".")
                if receiver == "self" and klass:
                    inherited = RESOLVER.method(mod, klass, method)
                    if inherited is not None:
                        stack.append(inherited)
                bound = binds.get(receiver) or binds.get(
                    "self." + receiver.split(".")[-1]
                )
                if bound is not None:
                    inherited = RESOLVER.method(bound[0], bound[1], method)
                    if inherited is not None:
                        stack.append(inherited)
                for port_module, port_class in ports.get(receiver, ()):
                    implemented = RESOLVER.method(port_module, port_class, method)
                    if implemented is not None:
                        stack.append(implemented)
            if called in model.functions:
                stack.append((mod, called))
            if called in model.class_bases:
                constructor = RESOLVER.method(mod, called, "__init__")
                if constructor is not None:
                    stack.append(constructor)
            head = called.split(".")[0]
            hit = _owner(aliases.get(head, head) + called[len(head) :])
            if hit is None:
                continue
            hmod, rest = hit
            if rest in MODELS[hmod].functions:
                stack.append((hmod, rest))
            elif "." in rest:
                inherited = RESOLVER.method(
                    hmod, rest.split(".")[0], rest.rsplit(".", 1)[-1]
                )
                if inherited is not None:
                    stack.append(inherited)
            if rest in MODELS[hmod].class_bases:
                constructor = RESOLVER.method(hmod, rest, "__init__")
                if constructor is not None:
                    stack.append(constructor)
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
    """The one remaining hop the closure cannot follow is still really there.

    A declared exception that nobody re-checks is how a derivation quietly
    stops deriving. The bridge names a fact; this asserts the fact.

    Part 1 is the RETIRED project_memory bridge, kept as a check rather than an
    exception: the same three facts are asserted, plus the one that made the
    exception unnecessary -- the egress is now DERIVED. If it stops being
    derived this fails and demands a real answer, instead of a bridge quietly
    absorbing the loss again.
    """
    # 1. project_memory -> the embedding POST, now derived rather than bridged.
    embeddings = (ROOT / "daedalus" / "memory" / "embeddings.py").read_text(
        encoding="utf-8"
    )
    assert "OllamaEmbeddingBackend(host)" in embeddings, (
        "EventVectorStore no longer constructs the embedding backend; "
        "re-derive the cli.project_memory row"
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
    assert ("daedalus.memory.embeddings", "OllamaEmbeddingBackend.embed") in (
        store_reached
    ), (
        "the walk stopped reaching the embedding POST, so cli.project_memory's "
        "network_egress has no justification again. It is reached through the "
        "`backend: EmbeddingBackend` parameter annotation, NOT through the "
        "method-returned object the retired bridge described -- restore that "
        "hop rather than re-adding the exception."
    )
    assert ("cli.project_memory", "network_egress") not in BRIDGES, (
        "the retired project_memory bridge is back. It was removed because the "
        "effect is derived; a bridge here would suppress the painted-label "
        "check for a row that no longer needs it."
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
    """Registering these doors must not make the matrix worse.

    Ten ``entrypoint.not_rediscovered`` REVIEW findings are the expected and
    documented price for ``PHASE4_ROWS`` -- the registry's own label for a
    registered target the conservative scanner cannot classify, which is
    precisely why those doors survived unregistered. ``LATE_ROWS`` is the
    opposite case and is asserted as such: the scanner DOES see all three, so
    each must be rediscovered, and rediscovery is what removed their
    ``entrypoint.unregistered`` blockers. Blockers stay empty and the Gate-0
    gap count must not move.
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
    #: RE-MEASURED 2026-08-26 at 0430c07f: 16, not the 19 pinned here since
    #: Phase 4.  The three that left are not this lane's doing -- the count was
    #: already 16 in a Gate-0 report run BEFORE any edit in this change, so the
    #: constant had gone stale under an earlier commit and this probe had been
    #: failing for whoever ran it.  It is corrected rather than relaxed: the
    #: number is still exact, because a range here would stop noticing the one
    #: thing it exists to notice.  The three rows added in this change are all
    #: CENTRAL and contribute no gap, which is why the count does not rise.
    assert len(gaps) == 16, f"Gate-0 gap count moved to {len(gaps)}"

    not_rediscovered = {
        finding.subject
        for finding in report.findings
        if finding.code == "entrypoint.not_rediscovered"
    }
    for target in PHASE4_ROWS.values():
        assert target in not_rediscovered, (
            f"{target} is now rediscovered by the scanner -- good news, but "
            f"this probe's accounting is stale"
        )
    for target in LATE_ROWS.values():
        assert target not in not_rediscovered, (
            f"{target} stopped being rediscovered by the scanner; its row can "
            f"no longer be checked against a discovery and this probe's "
            f"accounting is stale"
        )
    for target in STATIC_ONLY_ROWS.values():
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
