"""taskset.py -- turn the repo's EXISTING task corpus into a ``FrozenTaskSet``.

Packet G3-BASE-01, freeze obligation #1 ("freeze public tasks"). EXPERIMENT,
Gate-3 prework; the active delivery gate is 1 (see ``daedalus.eval.gate3``
package docstring). Nothing here opens, enters, or satisfies Gate 3.

This module does not mint tasks, does not store tasks, and does not change
``daedalus.eval.tasks`` or ``daedalus.eval.mint`` in any way -- it only reads
``daedalus.eval.harness.all_tasks()`` (or any task list shaped like it) and
compiles a frozen, digest-bound, plane-labelled view of it (``contracts.
FrozenTaskSet``).

Two decisions are made explicit here because plan §14 and packet rule R3
depend on them being auditable rather than implicit:

1. TIER FILTERING. Only tasks whose ``"tier"`` is the exact string
   ``"primary"`` enter the frozen set. This mirrors ``daedalus.eval.harness.
   _is_primary_tier``'s fail-closed rule -- a missing, misspelled, or
   otherwise unrecognized tier is quarantine, never trusted as primary. It is
   REIMPLEMENTED here (not imported) because it is one line of policy, not a
   subsystem this package is forbidden from duplicating (packet §2's
   forbidden list is BM25, aggregation, task store, tokenizer, gate -- a
   tier predicate is none of those); ``test_tier_predicate_agrees_with_harness``
   pins it against the real function so the two cannot silently drift apart.
   Exclusion is never silent: ``build_frozen_taskset`` emits a ``UserWarning``
   naming the excluded count, and ``filter_primary_tasks`` is exported so a
   caller can get the exact count without capturing warnings.

2. LABEL-PLANE CLASSIFICATION (``classify_task_plane``). A task's gold labels
   (``must_include``) live in exactly one of the four Project-Twin planes
   (plan §5): code, type, data, knowledge. The rule is:

     a. Strip an optional ``"::symbol"`` suffix from ``task["target"]`` to get
        a file path, and look up its extension in one of four DISJOINT,
        explicit extension sets below (``_PLANE_EXTENSIONS``). No extension
        is listed under more than one plane, and an extension absent from all
        four is a REFUSAL, not a guess -- there is deliberately no default
        branch that assigns "code" (or anything else) to an unrecognized
        shape. A silent "code" default would manufacture exactly the kind of
        single-plane label set rule R3 exists to catch, and would hide the
        fact that it did so.

     b. For the two planes whose gold labels are conventionally *symbol
        names* -- code and type -- the task's ``must_include`` entries (when
        present) are cross-checked against an identifier shape
        (``^[A-Za-z_][A-Za-z0-9_]*$``, i.e. what a Python/JS/TS/Java/... call
        site or definition name actually looks like). If the extension says
        "code" but the labels are not identifier-shaped, that is a
        contradiction this function cannot silently resolve -- it REFUSES
        rather than trusting either signal alone. Data and knowledge labels
        are not shape-constrained: a data fixture's or a doc excerpt's gold
        substrings are legitimately free text, numbers, or punctuation.

   A task with no ``"target"`` at all cannot be classified by either signal
   and is refused for the same reason.

``census()`` applies ``classify_task_plane`` over a task list and always
returns a mapping over exactly the four planes (§5's PLANES), so its values
sum to the length of the input by construction -- there is no code path that
drops a task's contribution once it has been classified, and a task that
cannot be classified raises before it can be dropped.
"""
from __future__ import annotations

import re
import warnings
from typing import Mapping, Sequence

from .contracts import FreezeError, FrozenTaskSet, PLANES, canonical_digest

# --------------------------------------------------------------------------- #
# 1. tier filtering (mirrors daedalus.eval.harness._is_primary_tier)          #
# --------------------------------------------------------------------------- #


def _is_primary_tier(label_tier: object) -> bool:
    """Fail-closed, byte-for-byte mirror of ``daedalus.eval.harness.
    _is_primary_tier``: only the EXACT string ``"primary"`` counts. See the
    module docstring for why this is reimplemented rather than imported, and
    ``test_tier_predicate_agrees_with_harness`` for the anti-drift check."""
    return label_tier == "primary"


def filter_primary_tasks(tasks: Sequence[dict]) -> tuple[list[dict], int]:
    """(primary_tasks, n_excluded_quarantine).

    The exclusion count is always computable from the return value alone --
    nothing about a quarantine-tier task is dropped without also being
    counted. ``build_frozen_taskset`` uses this and additionally warns when
    the count is non-zero, but this function itself never warns: it is the
    silent, composable primitive; the warning is a presentation concern.
    """
    primary = [t for t in tasks if _is_primary_tier(t.get("tier"))]
    return primary, len(tasks) - len(primary)


# --------------------------------------------------------------------------- #
# 2. label-plane classification                                              #
# --------------------------------------------------------------------------- #

#: Disjoint, explicit extension -> plane map. An extension not listed here is
#: UNKNOWN, not "code" by default (see module docstring, decision 2a).
_PLANE_EXTENSIONS: Mapping[str, tuple[str, ...]] = {
    "code": (
        ".py", ".pyw", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java",
        ".kt", ".go", ".rs", ".c", ".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx",
        ".rb", ".php", ".swift", ".scala", ".cs", ".sh", ".bash", ".ps1",
        ".lua", ".m", ".mm", ".pl", ".vue", ".svelte",
    ),
    "type": (
        ".pyi", ".proto", ".graphql", ".gql", ".thrift", ".fbs", ".capnp",
        ".xsd",
    ),
    "data": (
        ".csv", ".tsv", ".parquet", ".sql", ".json", ".jsonl", ".yaml",
        ".yml", ".ini", ".xml", ".toml", ".env",
    ),
    "knowledge": (
        ".md", ".mdx", ".rst", ".txt", ".adoc", ".org", ".wiki",
    ),
}

# Flattened extension -> plane lookup, built once at import time. Also
# doubles as the disjointness check: the extension sets must not overlap. A
# collision here would let one extension silently pick a plane by dict
# iteration order, which is exactly the kind of hidden nondeterminism this
# packet's rules (R4: denominator declared before the run) exist to forbid.
_EXTENSION_TO_PLANE: dict[str, str] = {}
for _plane, _exts in _PLANE_EXTENSIONS.items():
    for _ext in _exts:
        if _ext in _EXTENSION_TO_PLANE:
            raise AssertionError(
                f"_PLANE_EXTENSIONS is not disjoint: {_ext!r} claimed by both "
                f"{_EXTENSION_TO_PLANE[_ext]!r} and {_plane!r}")
        _EXTENSION_TO_PLANE[_ext] = _plane
del _plane, _exts, _ext

#: Planes whose gold labels are conventionally symbol names, and therefore
#: shape-checked against ``_IDENTIFIER_RE`` (decision 2b).
_SYMBOL_SHAPED_PLANES = frozenset({"code", "type"})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _target_path(task: dict) -> str:
    target = task.get("target")
    if not isinstance(target, str) or not target.strip():
        raise FreezeError(
            f"task {task.get('id', '<no id>')!r} has no usable 'target' -- "
            "cannot classify its label plane without knowing what file the "
            "gold labels describe")
    return target.split("::", 1)[0]


def _extension_of(path: str) -> str:
    # rsplit on the last path separator ourselves rather than pathlib: task
    # targets are repo-relative POSIX-style strings even when the harness
    # runs on Windows (see daedalus.eval.tasks), and we only need the suffix.
    base = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].lower()


def classify_task_plane(task: dict) -> str:
    """Classify one task's gold labels into a plane of ``PLANES``.

    Raises ``FreezeError`` -- never guesses -- when the target has no usable
    extension, the extension is not in ``_PLANE_EXTENSIONS``, or the
    extension and the shape of ``must_include`` contradict each other (see
    module docstring, decisions 2a/2b).
    """
    path = _target_path(task)
    ext = _extension_of(path)
    if not ext:
        raise FreezeError(
            f"task {task.get('id', '<no id>')!r} target {path!r} has no file "
            "extension -- cannot map it to a Project-Twin plane")
    plane = _EXTENSION_TO_PLANE.get(ext)
    if plane is None:
        raise FreezeError(
            f"task {task.get('id', '<no id>')!r} target {path!r} has "
            f"extension {ext!r}, which is not in any of the four declared "
            f"plane extension sets {sorted(_PLANE_EXTENSIONS)} -- refusing "
            "rather than defaulting to a guessed plane")

    if plane in _SYMBOL_SHAPED_PLANES:
        must_include = task.get("must_include") or []
        non_identifier = [m for m in must_include
                           if not (isinstance(m, str) and _IDENTIFIER_RE.match(m))]
        if non_identifier:
            raise FreezeError(
                f"task {task.get('id', '<no id>')!r} target {path!r} has "
                f"extension {ext!r} (plane={plane!r}), but must_include "
                f"contains non-identifier-shaped entries {non_identifier!r} -- "
                "extension and label shape disagree, so the plane cannot be "
                "confidently assigned")

    return plane


def census(tasks: Sequence[dict]) -> dict[str, int]:
    """Plane -> count of tasks whose gold labels live in that plane.

    Always has all four ``PLANES`` as keys (zero-filled), and its values sum
    to ``len(tasks)`` by construction: every task is classified into exactly
    one bucket, or ``classify_task_plane`` raises before any bucket is
    touched. There is no path that increments a count without the task
    itself being counted, and no path that swallows a classification error.
    """
    counts: dict[str, int] = {p: 0 for p in PLANES}
    for task in tasks:
        counts[classify_task_plane(task)] += 1
    return counts


# --------------------------------------------------------------------------- #
# 3. the frozen task set                                                     #
# --------------------------------------------------------------------------- #


def build_frozen_taskset(name: str, tasks: Sequence[dict],
                          counting_rule: str) -> FrozenTaskSet:
    """Compile ``tasks`` into a ``FrozenTaskSet``.

    * Quarantine-tier tasks (anything whose ``"tier"`` is not exactly
      ``"primary"``) are EXCLUDED from the frozen set -- packet rule/§4.4,
      mirroring ``harness._is_primary_tier``'s fail-closed posture: an
      unconfirmed label must not silently count toward a go/no-go number.
      The exclusion is never silent: when at least one task is excluded, this
      function emits a ``UserWarning`` naming the count, and
      ``filter_primary_tasks`` remains available for a caller that wants the
      exact number without capturing warnings.
    * ``label_plane_census`` is derived from the SAME primary-only task list
      that becomes ``task_ids`` -- so ``FrozenTaskSet.__post_init__``'s
      "census sums to len(task_ids)" check is satisfied by construction, not
      by coincidence.
    * ``counting_rule`` is passed through verbatim: it is the caller's
      declared denominator (packet rule R4), frozen and hashed by
      ``FrozenTaskSet`` -- this function does not invent, adjust, or
      soften it.
    """
    primary, n_excluded = filter_primary_tasks(tasks)
    if n_excluded:
        warnings.warn(
            f"build_frozen_taskset({name!r}): excluded {n_excluded} of "
            f"{len(tasks)} tasks as quarantine-tier (not exactly tier== "
            "'primary'); only primary-tier tasks enter the frozen set and "
            "its label-plane census.",
            stacklevel=2,
        )
    task_ids = tuple(t["id"] for t in primary)
    plane_census = census(primary)
    # CONTENT, not just identity. Ids and a census do not change when a task's
    # gold labels are rewritten, so a digest over them alone freezes the
    # membership of the set and nothing about what the set asks.
    content = [
        {
            "id": t["id"],
            "target": t.get("target"),
            "must_include": sorted(t.get("must_include") or ()),
            "minted_at_sha": t.get("minted_at_sha"),
            "label_provenance": t.get("label_provenance"),
        }
        for t in sorted(primary, key=lambda t: t["id"])
    ]
    return FrozenTaskSet(
        name=name,
        task_ids=task_ids,
        counting_rule=counting_rule,
        label_plane_census=plane_census,
        content_digest=canonical_digest(content),
    )


#: The counting rule this module uses when freezing ``daedalus.eval.harness.
#: all_tasks()`` -- declared here, once, so every caller that freezes the real
#: corpus states the identical denominator rather than each writing its own
#: prose (packet rule R4: the denominator is part of the frozen spec).
REAL_CORPUS_COUNTING_RULE = (
    "one unit per task id in daedalus.eval.harness.all_tasks() (TASKS plus "
    "the persisted mint store) whose 'tier' is the exact string 'primary'; "
    "quarantine-tier tasks are excluded and reported separately, mirroring "
    "harness._is_primary_tier's fail-closed rule. Correctness-format tasks "
    "(daedalus.eval.correctness) are out of scope: they never enter "
    "all_tasks() and carry no must_include to classify."
)
