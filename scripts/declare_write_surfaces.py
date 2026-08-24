"""Derive the repository-write classification declaration from measurement.

WHAT THIS PRODUCES, AND WHAT IT REFUSES TO CLAIM
------------------------------------------------
``daedalus/gates/report_v3.py`` takes ``repository_write_classification_input``
-- a locator, never a verdict.  Without one, every blocking write surface the
scanner emits is ``unclassified`` and stays a failure.  This script writes the
first such declaration, and it derives every row rather than asserting it:

* the surface comes from the same scanner the reporter runs
  (:func:`scan_repository_write_surfaces_v2`), so the declaration binds to the
  exact ``source_revision`` and ``inventory_digest`` of that scan;
* the door comes from the canonical effect registry
  (``daedalus.spine.effect_boundary.ENTRYPOINTS``), restricted to rows whose
  ``wiring`` is CENTRAL and whose anchors name a ``begin_effect`` call;
* **dominance** is decided by AST ancestry, not by file membership: a surface
  is declared only when its exact ``(line, column)`` node is a descendant of a
  statement that provably executes after the anchor's ``begin_effect`` call.

Three claims this script deliberately does NOT make, because nothing in the
tree can back them at this revision:

1. ``TargetDisposition`` is always ``UNKNOWN``.  The scanner records callee and
   operation, not the resolved write root, and no tool in this repository emits
   a ``primary_checkout_disjointness_receipt``.  ``UNKNOWN`` is the fail-closed
   value and it keeps the surface a blocker.
2. ``GuardDisposition`` is always ``INVENTORY_ONLY``.  ``GuardDisposition.CENTRAL``
   in the classification contract means more than "the door is centrally wired":
   it requires a disjoint target plus guard-contract, effect-lease,
   runtime-conformance and disjointness evidence.  ``LOCAL_GUARDS`` would require
   a guard contract that certifies the write, and the only contract these doors
   name -- ``budget.process_guard`` -- interposes ``subprocess.run``,
   ``subprocess.Popen`` and ``urllib.request.urlopen`` against the spend
   ceiling.  It is a spend net.  It does not certify a filesystem write, which
   ``daedalus/spine/effect_boundary.py`` already states in its own notes.
3. The only evidence minted is ``EvidenceKind.SOURCE_ANCHOR``, whose payload is
   entirely measurable: the repository-relative path, the AST line and column,
   and the sha256 of the exact file bytes.  Every other evidence kind would
   require a receipt this tree has no producer for.

The declaration therefore moves surfaces from ``unclassified`` (nobody looked)
to ``blocked:write-target-unknown+production-write-inventory_only`` (someone
looked, and here is the named reason it is still a blocker).  It clears
nothing, and it is not supposed to.

SOUNDNESS OF THE DOMINANCE RULE
-------------------------------
Level 1 -- the surface's node is a descendant of a statement in the anchor
function's body that follows the statement containing ``begin_effect`` (or, when
that statement is a ``with`` whose items hold the call, of a statement in its
body).

Level 2 -- the surface's node is inside a module-private helper ``_f`` defined at
module top level, where (a) ``_f`` is named nowhere else in the repository's
Python sources, (b) ``_f`` is absent from the module's ``__all__``, and (c) every
reference to ``_f`` inside the module is itself inside an already-dominated
region.  Reaching ``_f`` therefore implies the anchor ran.  Iterated to a
fixpoint.

Unsound only under dynamic dispatch (``getattr``, ``globals()[...]``, a name
resolved from data), which is why the cross-module name check demands *zero*
mentions anywhere, including in strings: a collision excludes the helper, it
never admits one.

KNOWN FRAGILITY OF LEVEL 2 -- READ THIS BEFORE RELYING ON A ``central`` ROW
--------------------------------------------------------------------------
Level 2's admission test is UNIQUENESS OF A NAME doing the work REACHABILITY
should be doing, and that is not a design choice, it is a consequence of what
this analysis can see.  ``_referenced_names`` collects ``ast.Name`` nodes only,
so the rule cannot follow an attribute call and cannot see into a method body
(61f1ece3 measured the second half of that).  Having no way to ask "who can
reach ``_f``", it asks the strictly-stronger question it CAN answer -- "does the
token ``_f`` occur anywhere else at all" -- and treats any occurrence as a
possible caller.

That direction is fail-closed, which is why it ships.  It is also a tripwire
rather than a guarantee, and the difference matters:

* the property is breakable by a DOCUMENTATION commit.  A comment, a docstring,
  a test that mentions the helper, a grep-and-annotate pass -- any of these
  silently drops the door back to zero dominated surfaces.  Nothing about the
  program changed; a word was typed in a second file.
* it therefore forces production code into an unusual shape: the executor
  behind ``python.offload``'s lease is a helper whose name may not be written
  down anywhere else in the tree, and
  ``scripts/run_offload_lease_dominance_mutations.py`` has to assemble that
  name from two fragments so that the mutation runner does not disarm the very
  surface its mutants protect.
* the guard against that regression is a red test
  (``tests/gates/test_write_surface_lease_dominance.py::
  test_the_offload_door_lease_dominates_its_bench_write``), not a convention --
  because a convention that everyone must remember not to break by typing a
  word is not a control.

THE FIX IS UPSTREAM, in the analysis, not in everyone's memory: resolve
references (attribute calls and method bodies included) and admit a helper on
demonstrated reachability rather than on lexical absence.  Until then, every
``central`` row that rests on Level 2 rests on this, and it should be read that
way.

Usage::

    python scripts/declare_write_surfaces.py            # write the declaration
    python scripts/declare_write_surfaces.py --dry-run  # derive and report only
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.gates.repository_write_classification import (  # noqa: E402
    CLASSIFICATION_INPUT_SCHEMA,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    NonRuntimeConformityAdmission,
    SurfaceClassification,
    TargetDisposition,
    issue_non_runtime_conformity_binding,
    project_repository_write_classifications,
    surface_binding_sha256,
    surface_classification_verdict,
)
from daedalus.gates.repository_write_evidence_materialization import (  # noqa: E402
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_inventory_v2 import (  # noqa: E402
    RepositoryWriteSurface,
    scan_repository_write_surfaces_v2,
)
from daedalus.spine.envelope import canonical_json  # noqa: E402

#: Read from the chain, never spelled here: if the verifier's own literal ever
#: moves, this generator's document is refused instead of silently drifting.
INPUT_SCHEMA = CLASSIFICATION_INPUT_SCHEMA
EVIDENCE_SCHEMA = "daedalus-gate0-repository-write-evidence-object/1"
DERIVATION_SCHEMA = "daedalus-gate0-write-surface-declaration-derivation/1"

#: Where the declaration lands.  ``report_v3`` takes a path from its caller and
#: the sibling evidence locators (fault matrix, runtime conformance) are all
#: run-artifact directories, so this follows that convention.
DEFAULT_OUT_ROOT = "runs/gates/write-surface-classification"

#: The collector this script signs as when it authenticates a replay.  One id,
#: so a binding signed by a previous key fails verification loudly.
COLLECTOR_ID = "daedalus.write-evidence-collector"
COLLECTOR_KEY_ID = "daedalus.local.write-evidence-collector"

#: Files another lane holds open at this head.  A declaration binds a
#: ``source_sha256`` to exact file bytes, so a file being edited concurrently
#: would produce a declaration that is stale the moment it is written.
#: ``daedalus/spine/attempt.py`` left this set when its lane released it.  Both
#: doors it holds are now derived: ``python.attempt`` declares 0 surfaces (the
#: ``begin_effect`` sits inside a ``try`` whose ``else`` branch carries the
#: whole attempt, and the dominance rule counts only the statements AFTER the
#: holder) and ``python.command_gate`` declares 2.  Neither is lease-dominated.
LIVE_LANE_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "daedalus/spine/receipts.py",
    }
)

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class DeclarationError(RuntimeError):
    """The declaration could not be derived from measurement."""


# ---------------------------------------------------------------------------
# door resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoorAnchor:
    """One CENTRAL registry row whose anchor names a ``begin_effect`` start."""

    door_id: str
    module: str
    rel_path: str
    symbol: tuple[str, ...]
    contracts: tuple[str, ...]


def _module_rel_path(root: Path, module: str) -> str | None:
    parts = module.split(".")
    direct = Path(*parts).with_suffix(".py")
    if (root / direct).is_file():
        return direct.as_posix()
    package = Path(*parts, "__init__.py")
    if (root / package).is_file():
        return package.as_posix()
    return None


def resolve_central_doors(root: Path) -> tuple[tuple[DoorAnchor, ...], tuple[str, ...]]:
    """Every CENTRAL row with a ``begin_effect`` anchor inside ``daedalus/``.

    The second element records why a row was skipped, so the derivation can be
    read as an accounting rather than as a selection someone made by hand.
    """

    from daedalus.spine.effect_boundary import ENTRYPOINTS, Wiring

    doors: list[DoorAnchor] = []
    skipped: list[str] = []
    for row in ENTRYPOINTS:
        if row.wiring is not Wiring.CENTRAL:
            continue
        starts = [anchor for anchor in row.anchors if anchor.call == "begin_effect"]
        if not starts:
            skipped.append(f"{row.id}:no-begin_effect-anchor")
            continue
        for anchor in starts:
            module, _, symbol = anchor.target.partition(":")
            if not module.startswith("daedalus.") and module != "daedalus":
                skipped.append(f"{row.id}:anchor-outside-daedalus-package")
                continue
            rel_path = _module_rel_path(root, module)
            if rel_path is None:
                skipped.append(f"{row.id}:anchor-module-not-a-file")
                continue
            if rel_path in LIVE_LANE_EXCLUSIONS:
                skipped.append(f"{row.id}:live-lane-exclusion:{rel_path}")
                continue
            doors.append(
                DoorAnchor(
                    door_id=row.id,
                    module=module,
                    rel_path=rel_path,
                    symbol=tuple(symbol.split(".")) if symbol else (),
                    contracts=tuple(row.guard_contracts),
                )
            )
    return tuple(doors), tuple(sorted(set(skipped)))


# ---------------------------------------------------------------------------
# AST dominance
# ---------------------------------------------------------------------------


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _find_symbol(tree: ast.Module, symbol: Sequence[str]) -> ast.AST | None:
    node: ast.AST = tree
    for name in symbol:
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            return None
        found = None
        for child in body:
            if (
                isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and child.name == name
            ):
                found = child
                break
        if found is None:
            return None
        node = found
    return node


def _is_begin_effect(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "begin_effect"
    if isinstance(func, ast.Attribute):
        return func.attr == "begin_effect"
    return False


def _is_leased_begin_effect(node: ast.AST) -> bool:
    """The METHOD ``<authorization>.begin_effect(execution)``.

    ``NonRuntimeEffectAuthorization.begin_effect`` is the one call that turns a
    persisted lease into permission to act: it verifies the lease at a
    facade-owned instant, commits a durable start receipt through the ledger,
    and re-reads the kill-switch generation before returning ``execute=True``.
    It is reachable only through an authorization object, so it is always an
    attribute call -- which is exactly what separates it, mechanically, from
    the free receipt function above.  ``daedalus/offload.py:777`` is the shape
    this predicate is written against.

    WHAT IT DOES NOT CHECK, said rather than claimed away: the RECEIVER.  A
    method named ``begin_effect`` on any other object satisfies this predicate,
    because an AST has no types.  That is a deliberate forgery in source, not
    an accident -- and it still buys nothing on its own, because the row also
    needs a retained, replayed, terminal execution under the real kernel
    ledger.  This guard closes the accident (an optional authorization, a write
    between the receipt and the lease); it is not a defence against a source
    edit, and nothing here is a security boundary.
    """

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "begin_effect"
    )


def _anchor_regions(
    func: ast.AST, predicate=_is_begin_effect
) -> tuple[list[ast.stmt], str]:
    """Statements provably executed after the anchor's ``begin_effect`` call."""

    body = getattr(func, "body", None)
    if not isinstance(body, list) or not body:
        raise DeclarationError("anchor function has no body")
    index = None
    holder: ast.stmt | None = None
    call: ast.Call | None = None
    for position, statement in enumerate(body):
        found = [n for n in ast.walk(statement) if predicate(n)]
        if found:
            index = position
            holder = statement
            call = min(found, key=lambda n: (n.lineno, n.col_offset))
            break
    if index is None or holder is None or call is None:
        raise DeclarationError(
            "anchor function contains no "
            + (
                "<authorization>.begin_effect(...) call, so nothing it does "
                "happens inside a leased execution"
                if predicate is _is_leased_begin_effect
                else "begin_effect call"
            )
        )

    dominated: list[ast.stmt] = list(body[index + 1 :])
    shape = "statement"
    if isinstance(holder, (ast.With, ast.AsyncWith)) and any(
        node is call
        for item in holder.items
        for node in ast.walk(item.context_expr)
    ):
        # ``with begin_effect(...) as lease:`` -- the call is in the context
        # expression, so the whole body runs under the lease and is dominated
        # too.  A ``begin_effect`` buried in the with-BODY is not this case and
        # falls through to the plain statement rule above.
        dominated.extend(holder.body)
        shape = "with-context"
    return dominated, shape


def _module_all(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                value = getattr(statement, "value", None)
                if isinstance(value, (ast.List, ast.Tuple)):
                    for element in value.elts:
                        if isinstance(element, ast.Constant) and isinstance(
                            element.value, str
                        ):
                            names.add(element.value)
    return frozenset(names)


def _referenced_names(nodes: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                names.add(inner.id)
    return names


def _expand_private_callees(
    tree: ast.Module,
    seed: list[ast.stmt],
    *,
    module_functions: Mapping[str, ast.stmt],
    exported: frozenset[str],
    external_names: frozenset[str],
) -> tuple[list[ast.stmt], tuple[str, ...]]:
    """Fixpoint over module-private helpers reachable only from dominated code."""

    dominated: list[ast.stmt] = list(seed)
    admitted: list[str] = []
    changed = True
    while changed:
        changed = False
        dominated_ids = {id(node) for node in dominated}
        # Every reference the currently-dominated region makes.
        inside = _referenced_names(dominated)
        for name, definition in sorted(module_functions.items()):
            if name in admitted or not name.startswith("_"):
                continue
            if name in exported or name in external_names:
                continue
            if name not in inside:
                continue
            # Every reference inside this module must sit in dominated code.
            if not _references_are_dominated(tree, name, dominated_ids):
                continue
            body = getattr(definition, "body", None)
            if not isinstance(body, list) or not body:
                continue
            dominated.extend(body)
            admitted.append(name)
            changed = True
    return dominated, tuple(sorted(admitted))


def _references_are_dominated(
    tree: ast.Module, name: str, dominated_ids: set[int]
) -> bool:
    parents = _parent_map(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id != name:
            continue
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            return False
        current: ast.AST | None = node
        seen = False
        while current is not None:
            if id(current) in dominated_ids:
                seen = True
                break
            current = parents.get(id(current))
        if not seen:
            return False
    return True


@dataclass(frozen=True)
class ModuleDominance:
    rel_path: str
    positions: frozenset[tuple[int, int]]
    shape: str
    private_callees: tuple[str, ...]
    dominated_statements: int
    #: THE SECOND REGION, and the one a ``central`` row rests on.  Same
    #: dominance machinery, seeded from ``<authorization>.begin_effect(...)``
    #: instead of from the free receipt function: these are the positions whose
    #: execution PROVABLY happened inside a leased execution, because reaching
    #: them required an authorization object whose method had already committed
    #: a durable start receipt.  Empty when the anchor function consumes no
    #: lease, which is the fail-closed default for every door in this tree but
    #: ``python.offload``.
    leased_positions: frozenset[tuple[int, int]] = frozenset()
    #: Why ``leased_positions`` is empty, when it is.  Named rather than
    #: silent: "this door consumes no lease" and "this door's leased region
    #: holds no write surface" are different facts about Gate 0.
    leased_refusal: str = ""


class NameIndex:
    """Identifier-shaped tokens per Python source file in the repository.

    Deliberately a superset: it is built from raw text, so a name mentioned in
    a docstring, a comment or a string literal still counts as a mention.  A
    module-private helper is admitted only when :meth:`outside` does NOT hold
    its name, so over-counting can only ever exclude a helper, never admit one.
    """

    def __init__(self, per_file: Mapping[str, frozenset[str]]) -> None:
        self._per_file = dict(per_file)
        self._cache: dict[str, frozenset[str]] = {}

    @classmethod
    def build(cls, root: Path) -> "NameIndex":
        per_file: dict[str, frozenset[str]] = {}
        for path in sorted(root.rglob("*.py")):
            parts = set(path.parts)
            if ".git" in parts or "__pycache__" in parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            per_file[path.relative_to(root).as_posix()] = frozenset(
                _IDENTIFIER.findall(text)
            )
        return cls(per_file)

    def outside(self, rel_path: str) -> frozenset[str]:
        cached = self._cache.get(rel_path)
        if cached is not None:
            return cached
        union: set[str] = set()
        for path, names in self._per_file.items():
            if path == rel_path:
                continue
            union |= names
        result = frozenset(union)
        self._cache[rel_path] = result
        return result


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


def source_anchor_evidence(
    source_revision: str,
    surface: RepositoryWriteSurface,
    source_sha256: str,
) -> tuple[EvidenceBinding, bytes]:
    """Mint one SOURCE_ANCHOR evidence object and its exact CAS bytes.

    The locator names the digest of the bytes, and the bytes are written next
    to the declaration, so the materialization verifier can replay this
    evidence without trusting the declaration that references it.  The binding
    is built twice: once with a placeholder digest to reach
    ``evidence_subject_sha256``, then finally with the digest of the envelope
    those exact fields produce.
    """

    surface_sha256 = surface_binding_sha256(source_revision, surface)
    payload = {
        "path": surface.path,
        "line": surface.line,
        "column": surface.column,
        "source_sha256": source_sha256,
    }
    payload_bytes = canonical_json(payload).encode("ascii")
    # The subject digest covers kind/revision/surface/contract only, so a
    # placeholder blob digest does not enter it.  That is what makes it
    # non-circular and why it can be computed before the envelope exists.
    subject = evidence_subject_sha256(
        EvidenceBinding(
            kind=EvidenceKind.SOURCE_ANCHOR,
            source_revision=source_revision,
            surface_sha256=surface_sha256,
            sha256="0" * 64,
            locator=f"cas:sha256:{'0' * 64}",
        )
    )
    envelope = {
        "schema": EVIDENCE_SCHEMA,
        "kind": EvidenceKind.SOURCE_ANCHOR.value,
        "source_revision": source_revision,
        "surface_sha256": surface_sha256,
        "guard_contract": "",
        "subject_sha256": subject,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": payload,
    }
    raw = canonical_json(envelope).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    binding = EvidenceBinding(
        kind=EvidenceKind.SOURCE_ANCHOR,
        source_revision=source_revision,
        surface_sha256=surface_sha256,
        sha256=digest,
        locator=f"cas:sha256:{digest}",
    )
    return binding, raw


# ---------------------------------------------------------------------------
# the retained write-evidence store
# ---------------------------------------------------------------------------
#
# WHY THE PRODUCER IS HERE AND NOT IN A NEW MODULE.  This script is already the
# one thing in the repository that produces ``SurfaceClassification`` rows and
# the evidence objects they bind.  A second producer of the same artifact class
# would be a second answer to "what is this surface", which is exactly the
# invariant that says one contract has one producer.  What is new below is the
# material it reads, not a second kind of row.
#
# WHY IT CANNOT BE A DOCUMENT.  A ``central`` row with no runtime-conformance
# receipt is only legal while it carries a ``NonRuntimeConformityAdmission``,
# and that admission has no wire shape at all (6be14dff): ``to_dict`` does not
# emit it and ``from_dict`` has no key for it.  Constructing one runs a real
# replay against the effect ledger.  So the rows below exist IN PROCESS only,
# and :func:`declaration_document` refuses to serialise one -- a declaration
# file that carried such a row would be a row whose own verifier refuses it.


def collector_secret(path: Path) -> bytes:
    """Load, or create on first use, this collector's local signing key.

    The same construction as the Effect-Lease issuer key and for the same
    reason: not from the environment, because an env-carried secret is
    inherited by every child this process spawns, which includes a candidate's
    worker.  A file outside the checkout is not a security boundary either; it
    is simply not handed to children.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        material = path.read_bytes()
    except FileNotFoundError:
        material = b""
    if len(material) < 32:
        fresh = os.urandom(32)
        try:
            # O_BINARY for the reason measured in ``issuer_keyring``: without
            # it Windows translates 0x0A to 0x0D 0x0A and the key on disk is
            # not the key this process signed with.
            handle = os.open(
                str(path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            material = path.read_bytes()
        else:
            try:
                os.write(handle, fresh)
            finally:
                os.close(handle)
            material = fresh
    if len(material) < 32:
        raise DeclarationError(f"the collector key at {path} is too short to sign with")
    return material


@dataclass(frozen=True)
class RetainedWriteEvidence:
    """Everything the kernel retained about one revision's granted leases."""

    subjects: Mapping[str, Mapping[str, object]]
    terminals: tuple[Mapping[str, object], ...]
    disjointness: tuple[Mapping[str, object], ...]
    refusals: tuple[str, ...]


def _record_sha256(body: Mapping[str, object]) -> str:
    subject = {key: value for key, value in body.items() if key != "record_sha256"}
    return hashlib.sha256(canonical_json(subject).encode("ascii")).hexdigest()


def load_retained_write_evidence(
    evidence_root: Path,
    *,
    source_revision: str,
    control_root_sha256: str,
) -> RetainedWriteEvidence:
    """Read the store, and refuse every record that does not bind to this run.

    Three refusals, all of them fail-closed and all of them NAMED rather than
    skipped:

    * a record whose ``record_sha256`` does not recompute -- a tampered or
      truncated receipt is not evidence, and the digest covers the whole body;
    * a record that names a different ``control_root_sha256`` than the store
      being read (Momus F8) -- evidence produced under one control root and
      verified under another is two machines' facts in one report;
    * a record bound to a different ``source_revision``.
    """

    from daedalus.kernel.offload_lease import (
        DISJOINTNESS_RECORD_SCHEMA,
        LEASE_SUBJECT_RECORD_SCHEMA,
        LEASE_TERMINAL_RECORD_SCHEMA,
    )

    expected = {
        "lease-subject": LEASE_SUBJECT_RECORD_SCHEMA,
        "lease-terminal": LEASE_TERMINAL_RECORD_SCHEMA,
        "disjointness": DISJOINTNESS_RECORD_SCHEMA,
    }
    kept: dict[str, list[Mapping[str, object]]] = {kind: [] for kind in expected}
    refusals: list[str] = []
    for kind, schema in expected.items():
        for path in sorted((Path(evidence_root) / kind).glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                refusals.append(f"{kind}/{path.name}: unreadable: {exc}")
                continue
            if not isinstance(record, dict) or record.get("schema") != schema:
                refusals.append(f"{kind}/{path.name}: not a {schema} record")
                continue
            if _record_sha256(record) != record.get("record_sha256"):
                refusals.append(
                    f"{kind}/{path.name}: record_sha256 does not bind the body"
                )
                continue
            if record.get("control_root_sha256") != control_root_sha256:
                refusals.append(
                    f"{kind}/{path.name}: retained under control root "
                    f"{record.get('control_root_sha256')}, read under "
                    f"{control_root_sha256}"
                )
                continue
            if record.get("source_revision") != source_revision:
                refusals.append(
                    f"{kind}/{path.name}: bound to revision "
                    f"{record.get('source_revision')}"
                )
                continue
            kept[kind].append(record)
    return RetainedWriteEvidence(
        subjects={
            str(row["record_sha256"]): row for row in kept["lease-subject"]
        },
        terminals=tuple(kept["lease-terminal"]),
        disjointness=tuple(kept["disjointness"]),
        refusals=tuple(refusals),
    )


@dataclass(frozen=True)
class AuthenticatedDoor:
    """One door whose retained execution replayed as a terminal non-runtime one."""

    door_id: str
    execution_id: str
    terminal: Mapping[str, object]
    subject_record: Mapping[str, object]
    replay_subject: object
    guard_contracts: tuple[str, ...]
    implementation_target: str
    implementation_sha256: str


def authenticated_doors(
    root: Path,
    evidence: RetainedWriteEvidence,
    *,
    keyring: Mapping[str, bytes],
) -> tuple[dict[str, AuthenticatedDoor], tuple[str, ...]]:
    """Replay every retained terminal record; keep the ones that come back non-runtime.

    The replay is the Effect-Lease module's own typed check, not a field read:
    ``replay_non_runtime_effect_subject`` pulls the execution back out of the
    ledger, refuses a runtime-bound authorization, refuses one that never
    terminalised, and refuses one naming another execution.  A door reaches the
    map below only because that check passed for it.
    """

    from daedalus.gates.repository_write_effect_lease import (
        EffectLeaseReplaySubject,
        RepositoryWriteEffectLeaseError,
        replay_non_runtime_effect_subject,
    )
    from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseError
    from daedalus.kernel.offload_lease import rebuild_effect_lease_authorization

    doors: dict[str, AuthenticatedDoor] = {}
    refusals: list[str] = []
    for terminal in evidence.terminals:
        name = str(terminal["record_sha256"])[:12]
        subject_record = evidence.subjects.get(str(terminal["subject_record_sha256"]))
        if subject_record is None:
            refusals.append(f"terminal {name}: no retained subject record")
            continue
        try:
            authorization = rebuild_effect_lease_authorization(
                subject_record, keyring=keyring
            )
            execution = EffectExecutionRequest(**dict(terminal["execution"]))
            replay_subject = EffectLeaseReplaySubject(authorization, execution)
            replay_non_runtime_effect_subject(
                replay_subject, expected_execution_id=str(terminal["execution_id"])
            )
        except (
            EffectLeaseError,
            RepositoryWriteEffectLeaseError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            refusals.append(f"terminal {name}: {type(exc).__name__}: {exc}")
            continue
        contracts = tuple(
            sorted(
                str(item["contract"])
                for item in subject_record["guard_decisions"]
                if item.get("allowed") is True
            )
        )
        module_path = str(subject_record["issuer_module_path"])
        try:
            implementation_sha256 = hashlib.sha256(
                (root / module_path).read_bytes()
            ).hexdigest()
        except OSError as exc:
            refusals.append(f"terminal {name}: issuer module unreadable: {exc}")
            continue
        door_id = str(terminal["entrypoint_id"])
        if door_id in doors:
            # Two terminal executions for one door is the normal case; the row
            # may only carry ONE Effect-Lease receipt, so the first replayed
            # execution owns the door and the rest are named, not merged.
            refusals.append(
                f"terminal {name}: door {door_id} already authenticated by "
                f"{doors[door_id].execution_id}"
            )
            continue
        doors[door_id] = AuthenticatedDoor(
            door_id=door_id,
            execution_id=str(terminal["execution_id"]),
            terminal=terminal,
            subject_record=subject_record,
            replay_subject=replay_subject,
            guard_contracts=contracts,
            implementation_target=str(subject_record["issuer_target"]),
            implementation_sha256=implementation_sha256,
        )
    return doors, tuple(refusals)


def _evidence_object(
    kind: EvidenceKind,
    source_revision: str,
    surface_sha256: str,
    payload: Mapping[str, object],
    *,
    guard_contract: str = "",
) -> tuple[EvidenceBinding, bytes]:
    """One canonical evidence envelope and the exact CAS bytes behind it."""

    payload_bytes = canonical_json(dict(payload)).encode("ascii")
    subject = evidence_subject_sha256(
        EvidenceBinding(
            kind=kind,
            source_revision=source_revision,
            surface_sha256=surface_sha256,
            sha256="0" * 64,
            locator=f"cas:sha256:{'0' * 64}",
            guard_contract=guard_contract,
        )
    )
    envelope = {
        "schema": EVIDENCE_SCHEMA,
        "kind": kind.value,
        "source_revision": source_revision,
        "surface_sha256": surface_sha256,
        "guard_contract": guard_contract,
        "subject_sha256": subject,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": dict(payload),
    }
    raw = canonical_json(envelope).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=kind,
            source_revision=source_revision,
            surface_sha256=surface_sha256,
            sha256=digest,
            locator=f"cas:sha256:{digest}",
            guard_contract=guard_contract,
        ),
        raw,
    )


def central_row(
    door: AuthenticatedDoor,
    surface: RepositoryWriteSurface,
    source_anchor: tuple[EvidenceBinding, bytes],
    disjointness: Mapping[str, object],
    *,
    source_revision: str,
    collector_secret_bytes: bytes,
    issued_at: str,
) -> tuple[SurfaceClassification, dict[str, bytes]]:
    """Build the one row shape a document cannot express, for one surface.

    ``CHECKOUT_EXTERNAL`` rests on exactly one recorded fact: the
    ``containment.worktree`` decision this lease was issued under, which
    measured the attempt isolation root against the primary checkout with
    ``primary_tree.planned_overlap_reason``.  That decision covers the ground
    candidate checkouts land on -- NOT each individual write's resolved root --
    and the row's notes say so, because a target disposition that claims more
    than its receipt measured is the failure this whole chain exists to catch.
    """

    surface_sha256 = surface_binding_sha256(source_revision, surface)
    bindings = [source_anchor[0]]
    blobs = {source_anchor[0].locator: source_anchor[1]}
    for contract in door.guard_contracts:
        binding, raw = _evidence_object(
            EvidenceKind.GUARD_CONTRACT,
            source_revision,
            surface_sha256,
            {
                "contract": contract,
                "implementation_target": door.implementation_target,
                "implementation_sha256": door.implementation_sha256,
            },
            guard_contract=contract,
        )
        bindings.append(binding)
        blobs[binding.locator] = raw
    lease_binding, lease_raw = _evidence_object(
        EvidenceKind.EFFECT_LEASE_RECEIPT,
        source_revision,
        surface_sha256,
        {
            "receipt_schema": str(door.terminal["receipt_schema"]),
            "receipt_sha256": str(door.terminal["receipt_sha256"]),
            "entrypoint_id": str(door.terminal["entrypoint_id"]),
            "terminal_state": str(door.terminal["terminal_state"]),
        },
    )
    bindings.append(lease_binding)
    blobs[lease_binding.locator] = lease_raw
    disjoint_binding, disjoint_raw = _evidence_object(
        EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
        source_revision,
        surface_sha256,
        {
            "receipt_schema": str(disjointness["receipt_schema"]),
            "receipt_sha256": str(disjointness["record_sha256"]),
            "primary_checkout_sha256": str(disjointness["primary_checkout_sha256"]),
            "target_root_sha256": str(disjointness["target_root_sha256"]),
            "disjoint": True,
        },
    )
    bindings.append(disjoint_binding)
    blobs[disjoint_binding.locator] = disjoint_raw

    admission = NonRuntimeConformityAdmission(
        binding=issue_non_runtime_conformity_binding(
            source_revision=source_revision,
            surface_sha256=surface_sha256,
            execution_id=door.execution_id,
            collector_id=COLLECTOR_ID,
            collector_key_id=COLLECTOR_KEY_ID,
            issued_at=issued_at,
            secret=collector_secret_bytes,
        ),
        subject=door.replay_subject,
        collector_secrets={COLLECTOR_KEY_ID: collector_secret_bytes},
    )
    row = SurfaceClassification(
        source_revision=source_revision,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=door.guard_contracts,
        evidence=tuple(sorted(bindings, key=EvidenceBinding.sort_key)),
        notes=(
            f"anchor-dominated by door {door.door_id}; execution "
            f"{door.execution_id} replayed terminal and non-runtime; the "
            "disjoint target rests on the containment.worktree decision this "
            "lease was issued under, which measured the attempt isolation "
            "root, not this write's resolved root"
        ),
        non_runtime_conformity=admission,
    )
    return row, blobs


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Derivation:
    source_revision: str
    inventory_digest: str
    inventory_surface_count: int
    rows: tuple[SurfaceClassification, ...]
    blobs: Mapping[str, bytes]
    per_door: tuple[Mapping[str, object], ...]
    skipped_doors: tuple[str, ...]
    undominated_in_door_modules: int
    #: Rows that carry a ``NonRuntimeConformityAdmission``.  They are part of
    #: ``rows`` and they are the reason ``declaration_document`` refuses to
    #: serialise this derivation: the admission has no wire shape.
    admitted_surfaces: tuple[str, ...] = ()
    #: Every named reason a door or a retained record did not authenticate.
    evidence_refusals: tuple[str, ...] = ()
    authenticated_doors: tuple[str, ...] = ()


def derive(
    root: Path,
    source_revision: str,
    *,
    evidence_root: Path | None = None,
    control_root_path: Path | None = None,
    collector_key: Path | None = None,
    issuer_keyring: Mapping[str, bytes] | None = None,
    issued_at: str | None = None,
) -> Derivation:
    inventory = scan_repository_write_surfaces_v2(
        root, source_revision=source_revision
    )
    doors, skipped = resolve_central_doors(root)

    by_path: dict[str, list[RepositoryWriteSurface]] = {}
    for surface in inventory.surfaces:
        by_path.setdefault(surface.path, []).append(surface)

    index = NameIndex.build(root)
    claimed: dict[RepositoryWriteSurface, str] = {}
    per_door: list[Mapping[str, object]] = []
    door_module_paths: set[str] = set()
    #: door id -> the positions inside that door's LEASED region, and the named
    #: reason the region is empty when it is.
    leased_by_door: dict[str, frozenset[tuple[int, int]]] = {}
    leased_refusal_by_door: dict[str, str] = {}

    for door in doors:
        door_module_paths.add(door.rel_path)
        try:
            dominance = _dominance(root, door, index)
        except DeclarationError as exc:
            per_door.append(
                {
                    "door": door.door_id,
                    "path": door.rel_path,
                    "declared": 0,
                    "refused": str(exc),
                }
            )
            continue
        leased_by_door[door.door_id] = dominance.leased_positions
        if dominance.leased_refusal:
            leased_refusal_by_door[door.door_id] = dominance.leased_refusal
        declared = 0
        leased = 0
        for surface in by_path.get(door.rel_path, ()):
            if not surface.blocking:
                continue
            if (surface.line, surface.column) not in dominance.positions:
                continue
            if surface in claimed:
                continue
            claimed[surface] = door.door_id
            declared += 1
            if (surface.line, surface.column) in dominance.leased_positions:
                leased += 1
        per_door.append(
            {
                "door": door.door_id,
                "path": door.rel_path,
                "anchor": f"{door.module}:{'.'.join(door.symbol)}",
                "anchor_shape": dominance.shape,
                "dominated_statements": dominance.dominated_statements,
                "private_callees": list(dominance.private_callees),
                "surfaces_in_module": sum(
                    1 for s in by_path.get(door.rel_path, ()) if s.blocking
                ),
                "declared": declared,
                # How many of those declared surfaces are inside the door's
                # LEASED region.  Only these may become ``central`` rows.
                "lease_dominated": leased,
                "lease_refusal": dominance.leased_refusal,
            }
        )

    # What the kernel retained for this revision, if anything did.  Absent a
    # store this is empty and every row below stays exactly what it was before
    # commit 3b: anchor-dominated, target unknown, inventory-only.
    doors_by_id: dict[str, AuthenticatedDoor] = {}
    disjointness: Mapping[str, object] | None = None
    evidence_refusals: list[str] = []
    secret: bytes | None = None
    if evidence_root is not None and control_root_path is not None:
        from daedalus.kernel.offload_lease import write_root_identity_sha256

        evidence = load_retained_write_evidence(
            evidence_root,
            source_revision=source_revision,
            control_root_sha256=write_root_identity_sha256(control_root_path),
        )
        evidence_refusals.extend(evidence.refusals)
        if issuer_keyring is None:
            from daedalus.kernel.offload_lease import issuer_keyring as _issuer_keyring

            issuer_keyring = _issuer_keyring(root)
        doors_by_id, door_refusals = authenticated_doors(
            root, evidence, keyring=issuer_keyring
        )
        evidence_refusals.extend(door_refusals)
        if evidence.disjointness:
            disjointness = evidence.disjointness[0]
        elif doors_by_id:
            evidence_refusals.append(
                "no primary_checkout_disjointness record for this revision, so "
                "no door can claim a disjoint target"
            )
        if doors_by_id and disjointness is not None:
            key_path = (
                collector_key
                if collector_key is not None
                else Path(control_root_path) / "write-evidence-collector.key"
            )
            secret = collector_secret(Path(key_path))

    source_digests: dict[str, str] = {}
    rows: list[SurfaceClassification] = []
    blobs: dict[str, bytes] = {}
    admitted: list[str] = []
    stamp = issued_at or _utc_stamp()
    for surface, door_id in sorted(claimed.items(), key=lambda item: item[0]):
        if surface.path not in source_digests:
            source_digests[surface.path] = hashlib.sha256(
                (root / surface.path).read_bytes()
            ).hexdigest()
        anchor = source_anchor_evidence(
            source_revision, surface, source_digests[surface.path]
        )
        door = doors_by_id.get(door_id)
        # THE LEASE-DOMINANCE GUARD, and it is the one that keeps this counter
        # honest.  A retained terminal execution proves the DOOR held a lease;
        # it says nothing about whether THIS write happened inside one.  Those
        # two claims come apart exactly when the write is reachable from both a
        # leased and an un-leased caller -- which is what `python.offload` was
        # at 21f21f2a (its `worker.run` sat in `_offload_impl`, which the
        # un-leased `live=False` path also called, so the door declared zero
        # surfaces) and which any door with an OPTIONAL authorization
        # reproduces.  That case was caught by accident, because the
        # private-callee fixpoint refuses a helper the un-leased path also
        # names; a surface sitting directly in a `if auth is not None:` region
        # would not be.  So the region is computed from the lease consumption
        # itself, and a surface outside it stays a blocker with the reason
        # named in `lease_refusal`.
        #
        # `daedalus/offload.py` since answered the refusal rather than routing
        # around it: the planner returns a description of the dispatch and the
        # provider run moved behind a caller the un-leased path cannot reach,
        # so that one surface is now attributed.  The snapshot helper's
        # `subprocess.run` in the same file still is not -- `_repo_snapshot` is
        # imported and called by other modules -- which is the discrimination
        # this guard is for.
        lease_dominated = (surface.line, surface.column) in leased_by_door.get(
            door_id, frozenset()
        )
        if (
            door is not None
            and disjointness is not None
            and secret is not None
            and lease_dominated
        ):
            row, row_blobs = central_row(
                door,
                surface,
                anchor,
                disjointness,
                source_revision=source_revision,
                collector_secret_bytes=secret,
                issued_at=stamp,
            )
            rows.append(row)
            blobs.update(row_blobs)
            admitted.append(f"{surface.path}:{surface.line}:{surface.column}")
            continue
        binding, raw = anchor
        blobs[binding.locator] = raw
        rows.append(
            SurfaceClassification(
                source_revision=source_revision,
                surface=surface,
                target=TargetDisposition.UNKNOWN,
                guard=GuardDisposition.INVENTORY_ONLY,
                production_reachable=True,
                guard_contracts=(),
                evidence=(binding,),
                notes=(
                    f"anchor-dominated by door {door_id}; write target unresolved "
                    "and no implemented guard contract certifies a filesystem write"
                ),
            )
        )

    # NAME EVERY DOOR THE LEASE-DOMINANCE GUARD COST SOMETHING.  A door that
    # replayed a terminal execution and still classified nothing is the
    # measurement this guard exists to produce, and a silent zero would read as
    # "there was nothing to classify".
    for door_id in sorted(doors_by_id):
        leased = leased_by_door.get(door_id, frozenset())
        held = [s for s, owner in claimed.items() if owner == door_id]
        if not held:
            # A door that authenticated and classified nothing is a Gate-0
            # fact; a silent absence reads as "there was nothing to classify".
            # MEASURED 21f21f2a: this was `python.offload`'s own state --
            # authenticated with zero refusals, dominating no blocking surface,
            # because its writes sat in `_offload_impl`, which the un-leased
            # `live=False` path also called. It no longer is, and this branch
            # stayed because the next door to consume a lease will land here
            # before it lands anywhere else.
            evidence_refusals.append(
                f"door {door_id}: authenticated, and its anchor dominates no "
                f"blocking write surface"
                + (
                    f" -- {leased_refusal_by_door[door_id]}"
                    if door_id in leased_refusal_by_door
                    else "; its leased region holds none either"
                )
            )
            continue
        refused = [s for s in held if (s.line, s.column) not in leased]
        if not refused:
            continue
        reason = leased_refusal_by_door.get(door_id) or (
            "its leased region holds none of them"
        )
        evidence_refusals.append(
            f"door {door_id}: {len(refused)} of {len(held)} anchor-dominated "
            f"surface(s) are not lease-dominated, so they stay blockers -- "
            f"{reason}"
        )

    undominated = sum(
        1
        for surface in inventory.surfaces
        if surface.blocking
        and surface.path in door_module_paths
        and surface not in claimed
    )
    return Derivation(
        source_revision=source_revision,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=tuple(sorted(rows, key=SurfaceClassification.sort_key)),
        blobs=blobs,
        per_door=tuple(per_door),
        skipped_doors=skipped,
        undominated_in_door_modules=undominated,
        admitted_surfaces=tuple(admitted),
        evidence_refusals=tuple(evidence_refusals),
        authenticated_doors=tuple(sorted(doors_by_id)),
    )


def _utc_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _dominance(root: Path, door: DoorAnchor, index: NameIndex) -> ModuleDominance:
    external = index.outside(door.rel_path)
    source = (root / door.rel_path).read_bytes()
    tree = ast.parse(source, filename=door.rel_path)
    func = _find_symbol(tree, door.symbol)
    if func is None or not isinstance(
        func, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        raise DeclarationError(
            f"anchor symbol {'.'.join(door.symbol)} is not a module function"
        )
    module_functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    exported = _module_all(tree)

    def _region(predicate) -> tuple[frozenset[tuple[int, int]], str, tuple[str, ...], int]:
        seed, shape = _anchor_regions(func, predicate)
        dominated, callees = _expand_private_callees(
            tree,
            seed,
            module_functions=module_functions,
            exported=exported,
            external_names=external,
        )
        found: set[tuple[int, int]] = set()
        for statement in dominated:
            for node in ast.walk(statement):
                lineno = getattr(node, "lineno", None)
                col = getattr(node, "col_offset", None)
                if isinstance(lineno, int) and isinstance(col, int):
                    found.add((lineno, col))
        return frozenset(found), shape, callees, len(dominated)

    # THE ANCHOR REGION IS UNCHANGED.  ``_is_begin_effect`` accepts both the
    # free receipt function and the authorization method, because the registry
    # anchor (``GuardAnchor(target, "begin_effect")``) does not distinguish
    # them -- and ``daedalus.offload:offload``'s only ``begin_effect`` IS the
    # attribute call, so narrowing this predicate would have refused that door
    # outright.  The distinction below is an ADDITIONAL, stricter fact.
    positions, shape, callees, statements = _region(_is_begin_effect)

    # THE LEASED REGION, computed separately and allowed to be empty.  A
    # ``DeclarationError`` here is the normal answer, not a failure: it means
    # the anchor function never calls ``<authorization>.begin_effect``, so no
    # write inside it happened under a lease and no surface it dominates may be
    # classified ``central``.  See ``derive`` for what that costs a door.
    if not any(_is_leased_begin_effect(node) for node in ast.walk(func)):
        # The cheap half of the same answer, and the common one: no attribute
        # call named ``begin_effect`` occurs anywhere in the anchor function, so
        # the fixpoint below could only return the empty region.  Skipping it
        # is what keeps this generator's cost the same as before the guard.
        leased_positions = frozenset()
        leased_refusal = (
            "anchor function contains no <authorization>.begin_effect(...) call, "
            "so nothing it does happens inside a leased execution"
        )
    else:
        try:
            leased_positions, _shape, _callees, _statements = _region(
                _is_leased_begin_effect
            )
            leased_refusal = ""
        except DeclarationError as exc:
            leased_positions = frozenset()
            leased_refusal = str(exc)

    return ModuleDominance(
        rel_path=door.rel_path,
        positions=positions,
        shape=shape,
        private_callees=callees,
        dominated_statements=statements,
        leased_positions=leased_positions,
        leased_refusal=leased_refusal,
    )


def declaration_out_dir(
    root: Path, revision: str, explicit: str | None
) -> tuple[Path, str | None]:
    """Where this revision's declaration lands, or why it must not.

    Twelve hex, not forty: the directory is an ADDRESS, the identity is the
    full ``source_revision`` inside ``classification-input.json``. The 40-hex
    spelling made this repository's longest tracked path 154 characters and
    killed the first armed loop run of 2026-08-23 inside ``git worktree add``
    (Windows MAX_PATH). Codex (room 56): the spelling is not identity, shrink
    it -- but never let two revisions share a prefix silently. So a directory
    that already holds a declaration is re-entered only for the SAME full
    revision; a prefix twin or an unreadable occupant is a refusal, and an
    explicit ``--out-dir`` is checked by the same rule.
    """
    out_dir = (
        Path(explicit)
        if explicit is not None
        else root / DEFAULT_OUT_ROOT / revision[:12]
    )
    existing = out_dir / "classification-input.json"
    if existing.exists():
        try:
            bound = json.loads(
                existing.read_text(encoding="utf-8")).get("source_revision")
        except (OSError, ValueError) as exc:
            return out_dir, (
                f"REFUSED: {existing} exists but cannot be read "
                f"({type(exc).__name__}: {exc}); refusing to overwrite a "
                f"declaration whose bound revision is unknown")
        if bound != revision:
            return out_dir, (
                f"REFUSED: {out_dir} already holds the declaration for "
                f"{bound}, which is not {revision}; a 12-hex address is only "
                f"an address, and two revisions must never share one -- pass "
                f"--out-dir to place this one explicitly")
    return out_dir, None


def declaration_document(derivation: Derivation) -> dict[str, object]:
    """Serialise the derivation, or refuse when it cannot be serialised.

    THE WIRE CANNOT CARRY AN ADMISSION and that is deliberate (6be14dff): a
    ``central`` row with no runtime-conformance receipt is legal only while it
    holds a ``NonRuntimeConformityAdmission``, whose construction runs a replay
    against the effect ledger, and which ``to_dict`` does not emit.  Writing
    such a row to a declaration file would drop exactly the thing that makes it
    legal, and the file would then be refused by ``from_dict`` -- as a
    ``central classification lacks required evidence kinds``, a message about
    the shape rather than about the missing replay.  Refusing here says the
    true thing: this row exists in process only.
    """

    admitted = tuple(
        f"{row.surface.path}:{row.surface.line}:{row.surface.column}"
        for row in derivation.rows
        if row.non_runtime_conformity is not None
    )
    if admitted:
        raise DeclarationError(
            "these rows hold a NonRuntimeConformityAdmission, which has no "
            "wire shape, so they cannot be written to a declaration file: "
            + ", ".join(admitted)
        )
    rows: list[dict[str, object]] = []
    for row in derivation.rows:
        item = row.to_dict()
        # ``candidate_blockers`` is derived by the chain, never declared.
        item.pop("candidate_blockers", None)
        rows.append(item)
    return {
        "schema": INPUT_SCHEMA,
        "source_revision": derivation.source_revision,
        "inventory_digest": derivation.inventory_digest,
        "classifications": rows,
    }


def in_process_census(
    inventory, projection
) -> dict[str, int]:
    """The reporter's own verdict census, over rows the wire cannot carry.

    ``daedalus.gates.report_v3`` reads a declaration FILE, and the rows this
    producer builds cannot travel through one, so the census is composed here
    from the same two public functions the reporter uses --
    ``surface_classification_verdict`` for classified surfaces and
    ``NON_BLOCKING_SURFACE_VERDICT``/``UNCLASSIFIED_SURFACE_VERDICT`` for the
    rest.  Same vocabulary, same one-verdict-per-surface rule, so the two
    censuses are comparable; it is not a second classifier.
    """

    from daedalus.gates.repository_write_classification import (
        NON_BLOCKING_SURFACE_VERDICT,
        UNCLASSIFIED_SURFACE_VERDICT,
    )

    classified = {row.surface: row for row in projection.classifications}
    census: dict[str, int] = {}
    for surface in inventory.surfaces:
        if not surface.blocking:
            verdict = NON_BLOCKING_SURFACE_VERDICT
        else:
            row = classified.get(surface)
            verdict = (
                UNCLASSIFIED_SURFACE_VERDICT
                if row is None
                else surface_classification_verdict(row)
            )
        census[verdict] = census.get(verdict, 0) + 1
    return dict(sorted(census.items()))


def authenticate_in_process(
    root: Path,
    projection,
    blobs: Mapping[str, bytes],
    *,
    source_revision: str,
    collector_secret_bytes: bytes,
    effect_subjects: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run the six verifiers over the material this producer can supply.

    It supplies what it has: the CAS bytes it just minted, an origin
    attestation it signs over the materialization of exactly those bytes, and
    the replay subjects it authenticated, keyed by the terminal receipt digest
    the chain looks them up under.  It does NOT supply a signed
    guard-implementation manifest, runtime subjects, or a runtime trust ledger,
    because nothing in this repository produces them at this revision.
    Whichever verifier refuses first is reported verbatim -- that refusal is
    the owed stage, and inventing an input to get past it would be the
    fabrication the chain exists to prevent.
    """

    from datetime import datetime, timedelta, timezone

    from daedalus.gates.repository_write_classification import (
        RepositoryWriteAuthenticationInputs,
        authenticate_repository_write_surfaces,
    )
    from daedalus.gates.repository_write_evidence_materialization import (
        materialize_repository_write_evidence,
    )
    from daedalus.gates.repository_write_evidence_origin import (
        issue_repository_write_evidence_origin_attestation,
    )

    now = datetime.now(timezone.utc)
    materialization = materialize_repository_write_evidence(projection, dict(blobs))
    attestation = issue_repository_write_evidence_origin_attestation(
        materialization,
        attestation_id="daedalus.write-evidence-origin",
        collector_id=COLLECTOR_ID,
        collector_key_id=COLLECTOR_KEY_ID,
        collector_secret=collector_secret_bytes,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    inputs = RepositoryWriteAuthenticationInputs(
        blobs=dict(blobs),
        origin_attestation=attestation,
        guard_manifest=None,
        runtime_subjects={},
        runtime_trust_ledgers={},
        effect_subjects=dict(effect_subjects or {}),
        collector_keyring={(COLLECTOR_ID, COLLECTOR_KEY_ID): collector_secret_bytes},
        expected_collector_id=COLLECTOR_ID,
        guard_keyring={},
        expected_guard_authority_id="daedalus.guard-authority",
        current_revision=source_revision,
        now=now,
        repository_root=root,
    )
    try:
        authentications = authenticate_repository_write_surfaces(
            projection, inputs=inputs
        )
    except Exception as exc:  # noqa: BLE001 - the refusal IS the measurement
        return {
            "composed": False,
            "refused_by": type(exc).__name__,
            "refusal": str(exc),
            "surfaces": {},
        }
    return {
        "composed": True,
        "refused_by": None,
        "refusal": "",
        "surfaces": {
            f"{surface.path}:{surface.line}:{surface.column}": {
                "authenticated": record.authenticated,
                "stages": {name: verdict for name, verdict in record.verdicts},
            }
            for surface, record in authentications.items()
        },
    }


def _head_revision(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DeclarationError("cannot resolve HEAD revision") from exc
    revision = out.stdout.strip()
    if not _REVISION.fullmatch(revision):
        raise DeclarationError("HEAD revision is not a lowercase 40-hex commit")
    return revision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive the repository-write classification declaration for the "
            "surfaces an anchored CENTRAL door provably dominates."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-revision", default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="derive and print the accounting; write nothing",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=None,
        help=(
            "the retained write-evidence store to authenticate against; "
            "defaults to the control root's own store for --root"
        ),
    )
    parser.add_argument("--control-root", type=Path, default=None)
    parser.add_argument("--collector-key", type=Path, default=None)
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help=(
            "read the retained store, replay it, build the in-process central "
            "rows and run the six verifiers over them; writes no declaration"
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    revision = args.source_revision or _head_revision(root)
    evidence_root = args.evidence_root
    control_root_path = args.control_root
    if args.authenticate:
        from daedalus.kernel.offload_lease import control_root, write_evidence_root

        if control_root_path is None:
            control_root_path = control_root(root)
        if evidence_root is None:
            evidence_root = write_evidence_root(root, revision)
    derivation = derive(
        root,
        revision,
        evidence_root=evidence_root,
        control_root_path=control_root_path,
        collector_key=args.collector_key,
    )

    # Self-check: the chain must accept every row against the same scan.  A
    # generator that emits a document its own verifier refuses is worse than
    # no generator, so the refusal happens here, before anything is written.
    inventory = scan_repository_write_surfaces_v2(root, source_revision=revision)
    projection = project_repository_write_classifications(
        inventory,
        derivation.rows,
    )
    # Second self-check: every minted evidence object must survive the
    # content-addressed materialization verifier, so the locators in the
    # declaration name bytes that really hash to what they claim.
    materialization = materialize_repository_write_evidence(
        projection, derivation.blobs
    )
    if materialization.missing_locators:
        raise DeclarationError("minted evidence is missing its own CAS bytes")

    summary = {
        "schema": DERIVATION_SCHEMA,
        "source_revision": revision,
        "inventory_digest": derivation.inventory_digest,
        "inventory_surface_count": derivation.inventory_surface_count,
        "declared": len(derivation.rows),
        "missing_after_declaration": len(projection.missing_surfaces),
        "undominated_in_door_modules": derivation.undominated_in_door_modules,
        "evidence_objects": len(derivation.blobs),
        "materialized_evidence_records": len(materialization.records),
        "per_door": list(derivation.per_door),
        "skipped_doors": list(derivation.skipped_doors),
        "verdict_census": in_process_census(inventory, projection),
        "authenticated_doors": list(derivation.authenticated_doors),
        "admitted_surfaces": list(derivation.admitted_surfaces),
        "evidence_refusals": list(derivation.evidence_refusals),
    }
    if args.authenticate:
        # In-process rows only, and nothing is written in this mode even when
        # the store authenticated no door: the wire cannot carry an admitted
        # row, so a run that MIGHT have produced one must not fall through to
        # writing a declaration that silently says something weaker.
        if derivation.admitted_surfaces:
            key_path = (
                args.collector_key
                if args.collector_key is not None
                else Path(control_root_path) / "write-evidence-collector.key"
            )
            summary["authentication"] = authenticate_in_process(
                root,
                projection,
                derivation.blobs,
                source_revision=revision,
                collector_secret_bytes=collector_secret(Path(key_path)),
            )
            # RETAINED, not merely printed (Momus cut D item 3, 2026-08-24):
            # today every honest authentication run REFUSES -- two of six
            # stage inputs have no producer at this head -- and a refusal
            # that only scrolls by is a negative result destroyed. It lands
            # beside the declaration it judged, named as what is owed, and
            # counted by nobody: the chain still refuses to call anything
            # authenticated off the back of this file (it is a record of
            # absence, and it has no wire form into the verifiers).
            out_dir, refusal = declaration_out_dir(root, revision, args.out_dir)
            if refusal is None:
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / "authentication-owed.json").write_bytes(
                        canonical_json({
                            "schema": "daedalus-write-authentication-owed/1",
                            "source_revision": revision,
                            "authentication": summary["authentication"],
                        }).encode("ascii"))
                    summary["authentication_owed_path"] = (
                        (out_dir / "authentication-owed.json")
                        .relative_to(root).as_posix())
                except OSError as exc:
                    summary["authentication_owed_error"] = (
                        f"{type(exc).__name__}: {exc}")
            else:
                summary["authentication_owed_error"] = refusal
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    document = declaration_document(derivation)
    if not args.dry_run:
        out_dir, refusal = declaration_out_dir(root, revision, args.out_dir)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 2
        cas_dir = out_dir / "cas"
        cas_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "classification-input.json").write_bytes(
            canonical_json(document).encode("ascii")
        )
        for locator, raw in sorted(derivation.blobs.items()):
            digest = locator.split(":")[-1]
            (cas_dir / f"{digest}.json").write_bytes(raw)
        (out_dir / "derivation.json").write_bytes(
            canonical_json(summary).encode("ascii")
        )
        summary["out_dir"] = out_dir.relative_to(root).as_posix()

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(
            f"revision {revision}\n"
            f"inventory  surfaces={summary['inventory_surface_count']} "
            f"digest={derivation.inventory_digest}\n"
            f"declared   {summary['declared']} "
            f"(unclassified after: {summary['missing_after_declaration']})\n"
            f"door modules hold {derivation.undominated_in_door_modules} "
            "blocking surfaces no anchor dominates"
        )
        for entry in derivation.per_door:
            if entry.get("declared") or entry.get("refused"):
                print(f"  {entry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
