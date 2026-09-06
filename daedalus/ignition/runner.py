"""The three Gate-1 readings :mod:`daedalus.ignition.gate1` reuses.

WHAT THIS MODULE WAS, AND WHY IT IS NOT THAT ANY MORE
-----------------------------------------------------
Until 2026-09-06 this file also held ``run_voltage_ignition`` and
``materialize_voltage_rename``: a complete second implementation of the Gate-1
Renovation slice. It was the 2026-08 rehearsal -- one process, ``shutil.copytree``
instead of an attempt worktree, six literal ``str.replace`` writes instead of an
operator, a hand-written ``WORK_ITEMS`` constant instead of the four-plane
manifest, and synthetic ``"1"*40`` / ``"2"*40`` revisions instead of a resolved
git sha. ``python -m daedalus.ignition`` has never called it: the shipped door
is :func:`daedalus.ignition.gate1.run_gate1_ignition`.

Two implementations of one gate clause is the "second implementation truth"
plan §13 forbids, and it was not harmless: the entire fail-closed fault matrix
in ``tests/ignition/`` was asserted about the rehearsal, so the coverage the
activation checklist listed as settled did not hold for the path that ships
[MEASURED 2026-09-06, ``G1-RENOVATION-01`` §3 finding 1]. ``G1-RENOVATION-02A``
ported every row to the door and deleted the rehearsal. The deleted code is in
git history at ``585b7ea4``; nothing imported it outside this package
[MEASURED 2026-09-06, ``grep -rn "run_voltage_ignition\\|materialize_voltage_rename"``
over the tree: only ``daedalus/ignition/`` and ``tests/ignition/``].

WHAT REMAINS
------------
Three measurements ``gate1`` calls and one exception type it raises. They live
here rather than in ``gate1.py`` because they are the readings, not the order:
a second tree digest or a second graph delta would be exactly the drift the
Fourfold delta exists to detect. ``candidate_behavior`` imports candidate code
INTO THE VERIFIER PROCESS; that is a known open row
(``docs/work-packets/G1_ACTIVATION_CHECKLIST.md`` §2.3 F4) and deliberately not
addressed by the packet that emptied this module.
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from daedalus.spine.envelope import canonical_sha
from daedalus.twin.contracts import FourfoldSnapshot


class IgnitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class IgnitionGraphDelta:
    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    added_bindings: tuple[str, ...]
    removed_bindings: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added_nodes": list(self.added_nodes),
            "removed_nodes": list(self.removed_nodes),
            "added_bindings": list(self.added_bindings),
            "removed_bindings": list(self.removed_bindings),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _tree_digest(root: Path) -> str:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        rows.append({"path": rel, "sha256": canonical_sha({"bytes": path.read_bytes().hex()})})
    return canonical_sha({"schema": "daedalus-tree-digest/1", "files": rows})


def _behavior(candidate: Path) -> Mapping[str, object]:
    source = str(candidate / "src")
    previous = list(sys.path)
    stale = [name for name in sys.modules if name == "ignition_app" or name.startswith("ignition_app.")]
    for name in stale:
        sys.modules.pop(name, None)
    try:
        sys.path.insert(0, source)
        module = importlib.import_module("ignition_app")
        event = module.parse_event({"id": "1", "bias_voltage": "125.0"})
        return {
            "type": type(event).__name__,
            "id": event.id,
            "bias_voltage": event.bias_voltage,
            "has_old_voltage_attribute": hasattr(event, "voltage"),
        }
    finally:
        sys.path[:] = previous
        for name in [name for name in sys.modules if name == "ignition_app" or name.startswith("ignition_app.")]:
            sys.modules.pop(name, None)


def _graph_delta(base: FourfoldSnapshot, candidate: FourfoldSnapshot) -> IgnitionGraphDelta:
    base_nodes = {node for plane in base.planes for node in plane.node_ids}
    candidate_nodes = {node for plane in candidate.planes for node in plane.node_ids}
    base_bindings = {canonical_sha(list(binding.semantic_key)) for binding in base.bindings}
    candidate_bindings = {canonical_sha(list(binding.semantic_key)) for binding in candidate.bindings}
    return IgnitionGraphDelta(
        added_nodes=tuple(sorted(candidate_nodes - base_nodes)),
        removed_nodes=tuple(sorted(base_nodes - candidate_nodes)),
        added_bindings=tuple(sorted(candidate_bindings - base_bindings)),
        removed_bindings=tuple(sorted(base_bindings - candidate_bindings)),
    )


# --------------------------------------------------------------------------- #
# public names for the Gate-1 slice                                            #
# --------------------------------------------------------------------------- #
#: :mod:`daedalus.ignition.gate1` reuses these three measurements verbatim
#: rather than re-deriving them. They were written private because this module
#: was once their only caller; the public aliases are kept because
#: ``daedalus/ignition/bundle.py`` names this file as an evaluator module by
#: path, and because renaming them would move the evaluator bundle digest for
#: no measured gain.
tree_digest = _tree_digest
candidate_behavior = _behavior
fourfold_graph_delta = _graph_delta

__all__ = [
    "IgnitionError",
    "IgnitionGraphDelta",
    "candidate_behavior",
    "fourfold_graph_delta",
    "tree_digest",
]
