"""The FOUR-plane task set: the frozen builder, with one plane-rule refinement.

`G2-TYPEPLANE-01`. Every result this programme has produced fuses THREE planes,
because `PLANE_BY_SUFFIX` assigns by suffix and sends all 90 tracked
`*.schema.json` files -- JSON Schema, i.e. declared contracts, precisely plan
§5's Type plane -- to the DATA plane alongside every config and fixture. So
criterion 14.4 (`plane_has_no_marginal_contribution`) has been NOT_EVALUABLE in
every run, and every negative result is a result about a three-plane
approximation.

**This module does not modify anything frozen.** It imports the frozen builder,
its `SELECTION`, its selection rules and its census machinery unchanged, and
rebinds exactly one name -- `plane_of` -- for the duration of one build. The
frozen `taskset_xplane.py` and `taskset.py::PLANE_BY_SUFFIX` are untouched, so
`taskset_xplane.json` remains reproducible byte for byte, which
``assert_frozen_taskset_unmoved`` proves rather than asserts.

The two task sets therefore coexist with different digests, and any published
number can be attributed to one of them. Editing the frozen rule in place would
silently re-cut four published measurements; `G3-BASE-01` refused the equivalent
move and so does this.

The refinement is deliberately narrow: a path ending ``.schema.json`` is
``type``, and nothing else changes. That is an explicit, self-describing
convention already used consistently in the subject tree (41 files under
``configs/schemas``, 41 under ``daedalus/resources/schemas``), so it needs no
content sniffing and cannot silently capture an ordinary config file.
"""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
from typing import Dict, Iterator

from experiments.forest_v2.s09_eval import taskset_xplane as frozen
from experiments.forest_v2.s09_eval.taskset import plane_of as frozen_plane_of

#: Stamped into every record this module writes, so a four-plane artifact can
#: never be mistaken for the frozen three-plane one by a reader or a script.
PLANE_RULE_ID = "v4-schema-json-is-type"

DEFAULT_PATH = Path(__file__).resolve().parent / "taskset_xplane4.json"


def plane_of_v4(path: str) -> str:
    """The frozen rule plus exactly one refinement."""
    if path.lower().endswith(".schema.json"):
        return "type"
    return frozen_plane_of(path)


@contextlib.contextmanager
def _refined_plane_rule() -> Iterator[None]:
    """Rebind the frozen builder's ``plane_of`` for one build, then restore.

    Rebinding rather than editing is the whole point: the frozen module's own
    source never changes, so its output stays reproducible. The restore runs in
    a ``finally`` so a failed build cannot leave the frozen builder refined.
    """
    original = frozen.plane_of
    frozen.plane_of = plane_of_v4  # type: ignore[assignment]
    try:
        yield
    finally:
        frozen.plane_of = original  # type: ignore[assignment]


def build(repo: Path, anchor: str = frozen.ANCHOR) -> Dict[str, object]:
    """Build the four-plane task set with the frozen selection rules."""
    with _refined_plane_rule():
        record = frozen.build(repo, anchor=anchor)
    # Self-identifying, and placed where a careless reader cannot miss it.
    record["plane_rule"] = PLANE_RULE_ID
    record["plane_rule_note"] = (
        "A path ending .schema.json is the TYPE plane. Every other assignment "
        "is the frozen PLANE_BY_SUFFIX. This record is NOT comparable "
        "case-for-case with taskset_xplane.json, which used the frozen rule."
    )
    return record


def assert_frozen_taskset_unmoved(repo: Path) -> str:
    """Re-derive the FROZEN task set and return its digest.

    Acceptance step 2 of `G2-TYPEPLANE-01`. Run in the same process, after the
    refined build, so a leaked rebinding would show up here as a changed digest
    rather than as a silent corruption of a published measurement.
    """
    record = frozen.build(repo, anchor=frozen.ANCHOR)
    return str(record["digest"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--anchor", default=frozen.ANCHOR)
    parser.add_argument("--out", default=str(DEFAULT_PATH))
    parser.add_argument(
        "--verify-frozen", action="store_true",
        help="also re-derive the frozen task set and print its digest",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    record = build(repo, anchor=args.anchor)
    Path(args.out).write_text(
        json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    census = record["census"]  # type: ignore[index]
    composition = record["plane_composition"]  # type: ignore[index]
    print(f"plane rule       {record['plane_rule']}")
    print(f"digest           {record['digest']}")
    print(f"cases            {len(record['cases'])}")  # type: ignore[arg-type]
    print(f"considered       {census['commits_considered']}")
    print(f"cross-plane      {census['supply']['cross_plane_admissible']}")
    print("combinations    ",
          json.dumps(composition.get("cases_by_plane_combination"), sort_keys=True))

    if args.verify_frozen:
        digest = assert_frozen_taskset_unmoved(repo)
        print(f"frozen digest    {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
