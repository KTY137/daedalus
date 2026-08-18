"""EXPERIMENT s06: the real slice-s01 upstream, wired.

This module replaces ``s01_adapter.py``, which guessed that s01 would emit a
JSONL stream of node dicts and offered an alias table to absorb the key names.
That guess was wrong in *shape*, not merely in naming: s01 emits no stream at
all.  Its contract is a Python one —

    ``s01_index.build_index(root) -> ProjectIndex``
        ``.modules: dict[str, ModuleInfo]``  (name, path, rel, tree,
            ``defs: name -> (kind, lineno)``, ``imports``, ``star_imports``,
            ``classes: name -> ClassInfo(bases, methods, attributes)``)
    ``s01_resolver.resolve_module(index, module) -> [(ast.Call, Resolution)]``
        ``Resolution(kind, status, target, site_rel, site_line,
            target_module, target_rel, target_line, origin)``

An alias table over JSON keys could never have absorbed that.  Keeping it
would have meant carrying a plausible-looking join that could not work.

What the wiring produces
------------------------
* **code plane** — from s01: one record per module, per module-level
  function/class/assignment, and per method.  Line ranges come from s01's own
  parsed ``ModuleInfo.tree``, so a locator is never guessed.
* **edges** — from s01's ``Resolution`` objects: a call site is attributed to
  the definition whose line range contains it, giving ``calls`` edges with
  real targets.  Class bases become ``derives_from`` edges resolved through
  ``index.class_of`` when the base is a repo class.  Unresolved calls are
  **counted, not invented** (``calls_unresolved`` in ``describe()``).
* **knowledge plane** — still from ``standin_source``.  s01 is a code-plane
  resolver; it has no knowledge plane to offer.  That split is reported per
  plane in the provenance book rather than asserted in prose.

The cross-lane coupling, named
------------------------------
s01 lives in a sibling worktree.  This module locates it by, in order: an
explicit ``--s01-path``, the ``F2_S01_PATH`` environment variable, then a
search of sibling worktrees.  When none of those finds it, the run does **not**
silently degrade: it falls back to the stand-in and reports a structured gap
(``UPSTREAM_GAP``) once per build.  The previous slice carried that same fact
as a 55-byte prose footnote inlined into all 8,466 cards; a named gap in one
place is the same information, honest, at 1/8466th of the cost.

Read-only: stdlib plus s01's own read-only modules.  No writes, no network,
no subprocess, no import of production repository code.
"""
from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from node_cards import ProvenanceBook
from standin_source import (
    KNOWLEDGE_DIRS,
    _segment,
    _signature,
    file_digest,
    knowledge_records,
    resolve_revision,
)

#: Where s01's package sits inside a worktree.
S01_RELATIVE = Path("experiments/forest_v2/s01_resolution")
S01_ENV_VAR = "F2_S01_PATH"

#: The named gap.  Emitted ONCE per build when the upstream cannot be reached,
#: never inlined into a card.
UPSTREAM_GAP_ID = "s06-upstream-s01-unreachable"


def find_s01(root: Path, explicit: Path | None = None) -> tuple[Path | None, list[str]]:
    """Locate s01's package.  Returns (path or None, the places searched)."""
    searched: list[str] = []

    def _try(candidate: Path, why: str) -> Path | None:
        searched.append(f"{why}: {candidate.as_posix()}")
        return candidate if (candidate / "s01_index.py").is_file() else None

    if explicit is not None:
        found = _try(Path(explicit), "explicit --s01-path")
        if found:
            return found, searched
        # An explicit path that does not hold s01 is an error worth raising:
        # silently searching elsewhere would defeat the point of naming it.
        raise FileNotFoundError(
            f"--s01-path does not contain s01_index.py: {Path(explicit).as_posix()}"
        )

    env = os.environ.get(S01_ENV_VAR)
    if env:
        found = _try(Path(env), f"${S01_ENV_VAR}")
        if found:
            return found, searched

    found = _try(root / S01_RELATIVE, "this worktree")
    if found:
        return found, searched

    parent = root.parent
    if parent.is_dir():
        for sibling in sorted(parent.iterdir()):
            if not sibling.is_dir() or sibling == root:
                continue
            candidate = sibling / S01_RELATIVE
            if (candidate / "s01_index.py").is_file():
                searched.append(f"sibling worktree: {candidate.as_posix()}")
                return candidate, searched
        searched.append(f"sibling worktrees under {parent.as_posix()}")
    return None, searched


def _import_s01(path: Path):
    """Import s01's modules from ``path``.  Read-only; nothing is executed but imports."""
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    import s01_index  # noqa: E402
    import s01_resolver  # noqa: E402

    return s01_index, s01_resolver


@dataclass(frozen=True)
class _Def:
    """One definition's real line range, taken from s01's parsed tree."""

    kind: str
    qualname: str
    name: str
    start: int
    end: int
    signature: str
    doc: str
    parent: str = ""
    parent_kind: str = ""


def _walk_defs(module_name: str, tree: ast.Module) -> list[_Def]:
    """Module-level defs and their methods, with exact ``start``/``end`` lines."""
    out: list[_Def] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(
                _Def(
                    kind="function",
                    qualname=f"{module_name}.{node.name}",
                    name=node.name,
                    start=node.lineno,
                    end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    signature=_signature(node),
                    doc=ast.get_docstring(node) or "",
                    parent=module_name,
                    parent_kind="module",
                )
            )
        elif isinstance(node, ast.ClassDef):
            cls_qual = f"{module_name}.{node.name}"
            out.append(
                _Def(
                    kind="class",
                    qualname=cls_qual,
                    name=node.name,
                    start=node.lineno,
                    end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    signature=_signature(node),
                    doc=ast.get_docstring(node) or "",
                    parent=module_name,
                    parent_kind="module",
                )
            )
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(
                        _Def(
                            kind="method",
                            qualname=f"{cls_qual}.{sub.name}",
                            name=sub.name,
                            start=sub.lineno,
                            end=getattr(sub, "end_lineno", sub.lineno) or sub.lineno,
                            signature=_signature(sub),
                            doc=ast.get_docstring(sub) or "",
                            parent=cls_qual,
                            parent_kind="class",
                        )
                    )
    return out


def _enclosing(defs: list[_Def], line: int) -> _Def | None:
    """The innermost definition whose range contains ``line``."""
    best: _Def | None = None
    for candidate in defs:
        if candidate.start <= line <= candidate.end:
            if best is None or candidate.start > best.start:
                best = candidate
    return best


def _posix(rel: object) -> str:
    """Separator normalisation, done on both sides of the join or on neither."""
    return str(rel).replace("\\", "/")


def _node_id(rel: str, kind: str, qualname: str) -> str:
    """Mint a code-plane id the way ``node_cards.node_id`` mints it.

    ``kind`` must be a **node** kind (``node_cards.CODE_NODE_KINDS``), never
    an s01 resolution bucket, and the separator is normalised here exactly as
    ``node_cards.node_id`` normalises it — an edge minted on a Windows ``rel``
    would otherwise miss every card on the other side of the join.
    """
    return f"code://{_posix(rel)}#{kind}:{qualname}"


@dataclass
class Upstream:
    """One build's record sources, their provenance, and any named gap."""

    mode: str
    revision: str
    book: ProvenanceBook
    _emit: Callable[[], Iterator[tuple[str, dict]]]
    gap: dict | None = None
    stats: dict = field(default_factory=dict)

    def iter_records(self) -> Iterator[tuple[str, dict]]:
        """Yield ``(provenance_ref, record)``.  Planes may differ in origin."""
        return self._emit()

    def describe(self) -> dict:
        out = {
            "mode": self.mode,
            "planes": self.stats.get("planes", {}),
            "s01_path": self.stats.get("s01_path", ""),
            "searched": self.stats.get("searched", []),
        }
        out.update({k: v for k, v in self.stats.items() if k not in out})
        # The gap is a first-class, named field -- present and null when the
        # upstream was reached, so a reader can tell "no gap" from "not asked".
        out["gap"] = self.gap
        return out


def _s01_code_records(
    root: Path, s01_path: Path | None = None, *, s01: tuple | None = None
) -> tuple[list[dict], dict]:
    """Build code-plane records from s01's index and resolver.  Read-only.

    ``s01`` injects an already-imported ``(index_module, resolver_module)``
    pair.  It exists so the record/edge join can be checked against a known
    edge set **without** the sibling worktree — a check that depends on
    another lane's HEAD is not a check this slice can run.
    """
    s01_index, s01_resolver = s01 if s01 is not None else _import_s01(s01_path)
    index = s01_index.build_index(root)

    counts = {
        "modules": 0,
        "unparseable": len(index.unparseable),
        "calls_total": 0,
        "calls_verified": 0,
        "calls_verified_joined": 0,
        "calls_verified_no_card": 0,
        "calls_external": 0,
        "calls_unresolved": 0,
        "bases_total": 0,
        "bases_repo": 0,
        "calls_by_resolution": {"verified": {}, "external": {}},
    }

    # ---- pass 1: read and parse ----------------------------------------
    # A module that cannot be read produces no records, so it must also not
    # appear in the join key below.  Deriving both from one list is what keeps
    # the two sides of the join describing the same set of modules.
    parsed: list[tuple] = []
    for info in index.modules.values():
        try:
            source = info.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        counts["modules"] += 1
        parsed.append(
            (
                info,
                source,
                source.splitlines(keepends=True),
                file_digest(source),
                _walk_defs(info.name, info.tree),
            )
        )

    # ---- the join key ---------------------------------------------------
    # ``(rel, qualname) -> the node kind this build cards that node under``.
    # It is derived from the records that will actually be emitted, so a
    # target this slice does not card is *absent* from the map rather than
    # guessed at.  That absence is what makes ``calls_verified_no_card`` a
    # measurement instead of an estimate.
    kind_of: dict[tuple[str, str], str] = {}
    for info, _source, _lines, _digest, defs in parsed:
        rel = _posix(info.rel)
        kind_of[(rel, info.name)] = "module"
        for item in defs:
            kind_of[(rel, item.qualname)] = item.kind

    records: list[dict] = []
    for info, source, lines, digest, defs in parsed:
        rel = _posix(info.rel)
        edges: dict[str, list[dict]] = {}

        # ---- call edges, attributed to the enclosing definition ----------
        for _call, res in s01_resolver.resolve_module(index, info):
            counts["calls_total"] += 1
            bucket = str(res.kind)
            if res.status == "verified":
                counts["calls_verified"] += 1
                counts["calls_by_resolution"]["verified"][bucket] = (
                    counts["calls_by_resolution"]["verified"].get(bucket, 0) + 1
                )
                # THE JOIN.  ``res.kind`` is s01's resolution bucket -- how the
                # call site was resolved -- and minting the target id from it
                # made 13,124 verified edges address cards that cannot exist.
                # The target's own node kind is the canonical side, because
                # that is what ``node_cards.node_id`` mints from a record.
                target_kind = kind_of.get((_posix(res.target_rel), res.target))
                if target_kind is None:
                    # s01 verified the definition and s06 has no card for it
                    # (a def nested inside a function, say).  Declining is the
                    # honest move: shipping the edge would leave a pointer into
                    # nothing, the exact failure this join guards against.
                    counts["calls_verified_no_card"] += 1
                    continue
                counts["calls_verified_joined"] += 1
                target_id = _node_id(res.target_rel, target_kind, res.target)
                edge_kind = target_kind
            elif res.status == "external":
                counts["calls_external"] += 1
                counts["calls_by_resolution"]["external"][bucket] = (
                    counts["calls_by_resolution"]["external"].get(bucket, 0) + 1
                )
                # An external symbol has no card, and no node kind this slice
                # can know, so the kind slot says ``symbol`` rather than
                # smuggling the route in.  Measured: 386 distinct external
                # targets under 386 ids either way, so this collapses nothing.
                target_id = f"code://external#symbol:{res.target}"
                edge_kind = "symbol"
            else:
                # Declined, not guessed.  Counted so the drop is visible.
                counts["calls_unresolved"] += 1
                continue
            holder = _enclosing(defs, res.site_line)
            owner_id = (
                _node_id(rel, holder.kind, holder.qualname)
                if holder
                else _node_id(rel, "module", info.name)
            )
            edges.setdefault(owner_id, []).append(
                {
                    "relation": "calls",
                    "direction": "out",
                    "node_id": target_id,
                    "kind": edge_kind,
                    "name": res.target.rsplit(".", 1)[-1],
                }
            )

        # ---- base-class edges, resolved through s01 where possible -------
        for cls_name, cls in info.classes.items():
            owner_id = _node_id(rel, "class", f"{info.name}.{cls_name}")
            for base in cls.bases:
                counts["bases_total"] += 1
                resolved = index.class_of(info.name, base)
                if resolved is not None:
                    counts["bases_repo"] += 1
                    target_mod = index.modules.get(resolved.module)
                    target_rel = target_mod.rel if target_mod else ""
                    target_id = _node_id(target_rel, "class", resolved.qualname)
                    base_kind = "class"
                else:
                    target_id = f"code://external#symbol:{base}"
                    base_kind = "symbol"
                edges.setdefault(owner_id, []).append(
                    {
                        "relation": "derives_from",
                        "direction": "out",
                        "node_id": target_id,
                        "kind": base_kind,
                        "name": base.rsplit(".", 1)[-1],
                    }
                )

        module_id = _node_id(rel, "module", info.name)
        module_edges = list(edges.get(module_id, ()))
        for item in defs:
            if item.parent_kind == "module":
                module_edges.append(
                    {
                        "relation": "defines",
                        "direction": "out",
                        "node_id": _node_id(rel, item.kind, item.qualname),
                        "kind": item.kind,
                        "name": item.name,
                    }
                )
        records.append(
            {
                "plane": "code",
                "kind": "module",
                "path": info.rel,
                "qualname": info.name,
                "start_line": 1,
                "end_line": max(1, len(lines)),
                "signature": "",
                "doc": ast.get_docstring(info.tree) or "",
                "text": source,
                "source_sha256": digest,
                "neighbors": module_edges,
            }
        )

        for item in defs:
            own_id = _node_id(rel, item.kind, item.qualname)
            neighbors = list(edges.get(own_id, ()))
            neighbors.append(
                {
                    "relation": "defined_in",
                    "direction": "in",
                    "node_id": _node_id(
                        rel,
                        item.parent_kind or "module",
                        item.parent or info.name,
                    ),
                    "kind": item.parent_kind or "module",
                    "name": (item.parent or info.name).rsplit(".", 1)[-1],
                }
            )
            if item.kind == "class":
                for sub in defs:
                    if sub.parent == item.qualname:
                        neighbors.append(
                            {
                                "relation": "defines",
                                "direction": "out",
                                "node_id": _node_id(rel, sub.kind, sub.qualname),
                                "kind": sub.kind,
                                "name": sub.name,
                            }
                        )
            records.append(
                {
                    "plane": "code",
                    "kind": item.kind,
                    "path": info.rel,
                    "qualname": item.qualname,
                    "start_line": item.start,
                    "end_line": item.end,
                    "signature": item.signature,
                    "doc": item.doc,
                    "text": _segment(lines, item.start, item.end),
                    "source_sha256": digest,
                    "neighbors": neighbors,
                }
            )

    return records, counts


def _standin_code_records(root: Path) -> list[dict]:
    from standin_source import CODE_PACKAGES, code_records

    out: list[dict] = []
    for package in CODE_PACKAGES:
        directory = root / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            out.extend(code_records(root, path))
    return out


def _knowledge_records(root: Path) -> list[dict]:
    out: list[dict] = []
    for directory_name in KNOWLEDGE_DIRS:
        directory = root / directory_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            out.extend(knowledge_records(root, path))
    return out


def load_upstream(
    root: Path, *, s01_path: Path | None = None, use_s01: bool = True
) -> Upstream:
    """Assemble this build's record sources and their provenance blocks.

    ``use_s01=False`` forces the stand-in path.  It exists so the fallback and
    its named gap are *exercised* rather than merely described, and so the
    provenance change can be measured against the previous corpus without the
    s01 wiring moving the numbers at the same time.
    """
    revision = resolve_revision(root)
    book = ProvenanceBook()
    if use_s01:
        found, searched = find_s01(root, s01_path)
    else:
        found, searched = None, ["disabled by --no-s01"]

    knowledge_ref = book.add(
        {
            "source": "standin_markdown_extractor",
            "extractor": "experiments.forest_v2.s06_cards.standin_source",
            "extractor_version": "1",
            "input_contract": "forest-v2-node-record/1",
            "plane": "knowledge",
            "read_only": True,
            "promotes": "nothing",
        }
    )

    gap: dict | None = None
    stats: dict = {"searched": searched}

    if found is not None:
        code_records_list, counts = _s01_code_records(root, found)
        code_ref = book.add(
            {
                "source": "s01_resolution",
                "extractor": "experiments.forest_v2.s01_resolution.s01_index",
                "resolver": "experiments.forest_v2.s01_resolution.s01_resolver",
                "extractor_version": "1",
                "input_contract": "forest-v2-node-record/1",
                "plane": "code",
                "read_only": True,
                "promotes": "nothing",
            }
        )
        mode = "s01"
        stats["s01_path"] = found.as_posix()
        stats.update(counts)
    else:
        code_records_list = _standin_code_records(root)
        code_ref = book.add(
            {
                "source": "standin_ast_extractor",
                "extractor": "experiments.forest_v2.s06_cards.standin_source",
                "extractor_version": "1",
                "input_contract": "forest-v2-node-record/1",
                "plane": "code",
                "read_only": True,
                "promotes": "nothing",
            }
        )
        mode = "standin"
        gap = {
            "id": UPSTREAM_GAP_ID,
            "wants": S01_RELATIVE.as_posix(),
            "effect": "code-plane records come from the stand-in, not from s01",
            "resolution": f"pass --s01-path, or set {S01_ENV_VAR}",
            "searched": searched,
        }

    knowledge = _knowledge_records(root)
    stats["planes"] = {
        "code": {"records": len(code_records_list), "source": mode},
        "knowledge": {"records": len(knowledge), "source": "standin"},
    }

    def _emit() -> Iterator[tuple[str, dict]]:
        for record in code_records_list:
            yield code_ref, record
        for record in knowledge:
            yield knowledge_ref, record

    return Upstream(
        mode=mode,
        revision=revision,
        book=book,
        _emit=_emit,
        gap=gap,
        stats=stats,
    )
