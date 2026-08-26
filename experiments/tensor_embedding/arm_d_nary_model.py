"""EXPERIMENT ``tensor-embedding-v3``, Arm D: what does binarisation cost?

v2 ended on a measured fact: all ten cross-plane claims in the repository's own
ground truth are binary, so an n-ary tensor has no object to act on. The obvious
follow-up is not "use a bigger tensor" but "is the data model binary because the
world is, or because the schema is?"

This arm answers that against the real fixture, not a synthetic corpus. It
builds two models of the SAME facts --

* ``binary``  -- the claim vocabulary as ``fourfold.json`` defines it today;
* ``nary``    -- one claim per concept, with one slot per plane manifestation,

-- and then measures three things the binary model is suspected to lose:

* **coverage**   -- manifestations no binary claim can name at all;
* **hub bias**   -- pairs that exist in the world but are only reachable
  through a privileged plane;
* **detection** -- whether a half-completed rename is visible in the claim set
  itself, without an external join.

Nothing here writes to the fixture. The rename is applied to an in-memory copy.

Run:  python experiments/tensor_embedding/arm_d_nary_model.py
"""

from __future__ import annotations

import itertools
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "ignition" / "voltage"
OUT = ROOT / "runs" / "tensor_embedding_v3"

REVISION = "rev-fixture"


# --------------------------------------------------------------------------
# The facts, read off the fixture text. Seven files; a parser would add a
# failure mode without adding a fact.
# --------------------------------------------------------------------------

def manifestations(python_field: str = "voltage") -> list[dict]:
    """Every place a field-level concept actually appears in the fixture."""
    return [
        {"concept": "Event.id", "plane": "type", "role": "type_field",
         "node": "type:models.py#Event.id", "name": "id"},
        {"concept": "Event.id", "plane": "data", "role": "data_column",
         "node": "data:events.csv#id", "name": "id"},
        {"concept": "Event.id", "plane": "data", "role": "schema_property",
         "node": "data:event.schema.json#id", "name": "id"},

        {"concept": "Event.voltage", "plane": "type", "role": "type_field",
         "node": "type:models.py#Event.voltage", "name": python_field},
        {"concept": "Event.voltage", "plane": "data", "role": "data_column",
         "node": "data:events.csv#voltage", "name": "voltage"},
        {"concept": "Event.voltage", "plane": "data", "role": "schema_property",
         "node": "data:event.schema.json#voltage", "name": "voltage"},
        # wiki/Event.md line 1 is "# Event voltage" and line 4 carries the
        # code span `voltage`. The concept demonstrably appears in the
        # knowledge plane at FIELD level.
        {"concept": "Event.voltage", "plane": "knowledge", "role": "doc_mention",
         "node": "knowledge:wiki/Event.md#voltage", "name": "voltage"},
        # repository.py reads row["voltage"] and passes voltage=... -- the code
        # plane touches the field itself, not just the file.
        {"concept": "Event.voltage", "plane": "code", "role": "code_use",
         "node": "code:repository.py#parse_event.voltage", "name": "voltage"},
        {"concept": "Event.id", "plane": "code", "role": "code_use",
         "node": "code:repository.py#parse_event.id", "name": "id"},
    ]


def binary_claims() -> list[dict]:
    """The claims ``fourfold.json`` actually carries, verbatim in structure."""
    raw = json.loads((FIXTURE / "fourfold.json").read_text(encoding="utf-8"))
    return raw["claims"]


def nary_claims(python_field: str = "voltage") -> list[dict]:
    """One claim per concept. Arity is whatever the world supplies."""
    by_concept: dict[str, list[dict]] = {}
    for m in manifestations(python_field):
        by_concept.setdefault(m["concept"], []).append(m)
    claims = []
    for concept, slots in by_concept.items():
        claims.append(
            {
                "claim_id": f"realization:{concept}@{REVISION}",
                "kind": "concept_realization",
                "concept": concept,
                "revision": REVISION,
                "arity": len(slots),
                "slots": [
                    {"role": s["role"], "plane": s["plane"], "node": s["node"], "name": s["name"]}
                    for s in slots
                ],
            }
        )
    return claims


# --------------------------------------------------------------------------
# The three measurements
# --------------------------------------------------------------------------

def measure_coverage() -> dict:
    """Which real manifestations can no binary claim name?"""
    named_in_binary: set[str] = set()
    for claim in binary_claims():
        for key, value in claim.items():
            if key.endswith("_field") or key.endswith("_name"):
                named_in_binary.add(f"{claim['kind']}:{value}")
    field_level_keys = {"type_field", "csv_field", "schema_field"}
    covered_planes = set()
    for claim in binary_claims():
        for key in claim:
            if key in field_level_keys:
                covered_planes.add({"type_field": "type", "csv_field": "data",
                                    "schema_field": "data"}[key])

    real = manifestations()
    uncovered = [m for m in real if m["plane"] not in covered_planes]
    return {
        "manifestations_total": len(real),
        "planes_reachable_at_field_level_in_binary_model": sorted(covered_planes),
        "manifestations_unnameable_in_binary_model": [m["node"] for m in uncovered],
        "unnameable_count": len(uncovered),
    }


def measure_hub_bias() -> dict:
    """Which true pairs exist only via a privileged plane?"""
    pairs_asserted = set()
    for claim in binary_claims():
        if claim["kind"] == "type_matches_csv_field":
            pairs_asserted.add(("type", "data:csv", claim["type_field"]))
        if claim["kind"] == "type_matches_schema_field":
            pairs_asserted.add(("type", "data:schema", claim["type_field"]))

    all_true_pairs = set()
    by_concept: dict[str, list[dict]] = {}
    for m in manifestations():
        by_concept.setdefault(m["concept"], []).append(m)
    for concept, slots in by_concept.items():
        for a, b in itertools.combinations(sorted(slots, key=lambda s: s["role"]), 2):
            all_true_pairs.add((concept, a["role"], b["role"]))

    asserted_roles = set()
    for claim in binary_claims():
        if claim["kind"] == "type_matches_csv_field":
            asserted_roles.add((f"Event.{claim['type_field']}", "data_column", "type_field"))
        if claim["kind"] == "type_matches_schema_field":
            asserted_roles.add((f"Event.{claim['type_field']}", "schema_property", "type_field"))

    missing = sorted(p for p in all_true_pairs if p not in asserted_roles)
    hub_free = [p for p in missing if "type_field" not in (p[1], p[2])]
    return {
        "true_pairs_total": len(all_true_pairs),
        "pairs_asserted_in_binary_model": len(asserted_roles),
        "pairs_missing": len(missing),
        "pairs_missing_that_do_not_touch_the_type_hub": len(hub_free),
        "examples_without_hub": hub_free[:6],
    }


def measure_rename_detection() -> dict:
    """Is a half-completed rename visible in the claim set itself?

    The Gate-1 defect: Python says ``bias_voltage``, CSV and schema still say
    ``voltage``. Ask each model whether it can see the inconsistency using only
    what the claim carries.
    """
    result = {}

    # n-ary: one claim holds every manifestation, so disagreement is local.
    for label, field in (("aligned", "voltage"), ("renamed", "bias_voltage")):
        detected = []
        for claim in nary_claims(field):
            names = {s["name"] for s in claim["slots"]}
            if len(names) > 1:
                detected.append({"claim_id": claim["claim_id"], "names": sorted(names)})
        result[f"nary/{label}"] = {
            "inconsistent_claims_found": len(detected),
            "detail": detected,
            "join_required": False,
        }

    # binary: each claim names a type_field and a partner field. A claim can be
    # checked in isolation -- but only for the pair it carries.
    for label, field in (("aligned", "voltage"), ("renamed", "bias_voltage")):
        detected = []
        for claim in binary_claims():
            if claim["kind"] == "type_matches_csv_field":
                type_name = field if claim["type_field"] == "voltage" else claim["type_field"]
                if type_name != claim["csv_field"]:
                    detected.append({"kind": claim["kind"], "pair": [type_name, claim["csv_field"]]})
            if claim["kind"] == "type_matches_schema_field":
                type_name = field if claim["type_field"] == "voltage" else claim["type_field"]
                if type_name != claim["schema_field"]:
                    detected.append({"kind": claim["kind"], "pair": [type_name, claim["schema_field"]]})
        result[f"binary/{label}"] = {
            "inconsistent_claims_found": len(detected),
            "detail": detected,
            "join_required": True,
            "note": (
                "each hit is a separate pair; deciding whether ONE concept is "
                "consistently renamed requires joining them on type_field "
                "outside the claim"
            ),
        }
    return result


def main() -> int:
    started = time.time()
    payload = {
        "experiment": "tensor-embedding-v3",
        "arm": "D",
        "question": "is the data model binary because the world is, or because the schema is?",
        "fixture": str(FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "binary_claim_count": len(binary_claims()),
        "nary_claim_count": len(nary_claims()),
        "nary_arities": sorted(c["arity"] for c in nary_claims()),
        "coverage": measure_coverage(),
        "hub_bias": measure_hub_bias(),
        "rename_detection": measure_rename_detection(),
    }
    payload["elapsed_seconds"] = round(time.time() - started, 3)

    cov = payload["coverage"]
    hub = payload["hub_bias"]
    print(f"binary claims: {payload['binary_claim_count']}   "
          f"n-ary claims: {payload['nary_claim_count']}   arities: {payload['nary_arities']}")
    print(f"\ncoverage: {cov['unnameable_count']} of {cov['manifestations_total']} real "
          f"manifestations cannot be named at field level in the binary model")
    for node in cov["manifestations_unnameable_in_binary_model"]:
        print(f"   unnameable: {node}")
    print(f"\nhub bias: {hub['pairs_missing']} of {hub['true_pairs_total']} true pairs unasserted; "
          f"{hub['pairs_missing_that_do_not_touch_the_type_hub']} of them never touch the type hub")
    print("\nrename detection:")
    for key, val in payload["rename_detection"].items():
        print(f"   {key:16s} inconsistencies={val['inconsistent_claims_found']}  "
              f"join_required={val['join_required']}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_d.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nwrote {OUT / 'arm_d.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
