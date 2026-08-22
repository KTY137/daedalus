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

Usage::

    python scripts/declare_write_surfaces.py            # write the declaration
    python scripts/declare_write_surfaces.py --dry-run  # derive and report only
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
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
    SurfaceClassification,
    TargetDisposition,
    project_repository_write_classifications,
    surface_binding_sha256,
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

#: Files another lane holds open at this head.  A declaration binds a
#: ``source_sha256`` to exact file bytes, so a file being edited concurrently
#: would produce a declaration that is stale the moment it is written.
LIVE_LANE_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "daedalus/spine/attempt.py",
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


def _anchor_regions(func: ast.AST) -> tuple[list[ast.stmt], str]:
    """Statements provably executed after the anchor's ``begin_effect`` call."""

    body = getattr(func, "body", None)
    if not isinstance(body, list) or not body:
        raise DeclarationError("anchor function has no body")
    index = None
    holder: ast.stmt | None = None
    call: ast.Call | None = None
    for position, statement in enumerate(body):
        found = [n for n in ast.walk(statement) if _is_begin_effect(n)]
        if found:
            index = position
            holder = statement
            call = min(found, key=lambda n: (n.lineno, n.col_offset))
            break
    if index is None or holder is None or call is None:
        raise DeclarationError("anchor function contains no begin_effect call")

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


def derive(root: Path, source_revision: str) -> Derivation:
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
        declared = 0
        for surface in by_path.get(door.rel_path, ()):
            if not surface.blocking:
                continue
            if (surface.line, surface.column) not in dominance.positions:
                continue
            if surface in claimed:
                continue
            claimed[surface] = door.door_id
            declared += 1
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
            }
        )

    source_digests: dict[str, str] = {}
    rows: list[SurfaceClassification] = []
    blobs: dict[str, bytes] = {}
    for surface, door_id in sorted(claimed.items(), key=lambda item: item[0]):
        if surface.path not in source_digests:
            source_digests[surface.path] = hashlib.sha256(
                (root / surface.path).read_bytes()
            ).hexdigest()
        binding, raw = source_anchor_evidence(
            source_revision, surface, source_digests[surface.path]
        )
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
    )


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
    seed, shape = _anchor_regions(func)
    module_functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    dominated, callees = _expand_private_callees(
        tree,
        seed,
        module_functions=module_functions,
        exported=_module_all(tree),
        external_names=external,
    )
    positions: set[tuple[int, int]] = set()
    for statement in dominated:
        for node in ast.walk(statement):
            lineno = getattr(node, "lineno", None)
            col = getattr(node, "col_offset", None)
            if isinstance(lineno, int) and isinstance(col, int):
                positions.add((lineno, col))
    return ModuleDominance(
        rel_path=door.rel_path,
        positions=frozenset(positions),
        shape=shape,
        private_callees=callees,
        dominated_statements=len(dominated),
    )


def declaration_document(derivation: Derivation) -> dict[str, object]:
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
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    revision = args.source_revision or _head_revision(root)
    derivation = derive(root, revision)

    # Self-check: the chain must accept every row against the same scan.  A
    # generator that emits a document its own verifier refuses is worse than
    # no generator, so the refusal happens here, before anything is written.
    projection = project_repository_write_classifications(
        scan_repository_write_surfaces_v2(root, source_revision=revision),
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
    document = declaration_document(derivation)

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
    }

    if not args.dry_run:
        out_dir = (
            Path(args.out_dir)
            if args.out_dir is not None
            else root / DEFAULT_OUT_ROOT / revision
        )
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
