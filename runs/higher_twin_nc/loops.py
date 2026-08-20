"""Loop assays (H-HOL pilot): interventional holonomy with built-in controls.

A loop applies an operator and its declared inverse and asks whether the
tree returns to the base point. Classification per loop:

  trivial    tree identical to baseline (holonomy zero)
  tree       tree differs, evaluator outcome identical (representation-only
             holonomy)
  behavior   evaluator outcome differs (behavioral holonomy)

The pilot ships one designed negative control (rename roundtrip: word-level
replacement is bijective here, expected trivial) and one designed positive
control (scale roundtrip: numeric formatting loses the original text form,
expected behavioral holonomy on the digest while the calibrated VALUES stay
equivalent — label/format holonomy, k_value 0).

Non-invertible operators (clip, add, tighten) have no loop: information loss
is a cone, not a cycle; they are recorded as excluded, not skipped silently.
"""
from __future__ import annotations

import json
from pathlib import Path

import assay
import operators

EXCLUDED_NON_INVERTIBLE = ["clip", "add", "tighten"]


def standard_loops() -> list:
    return [
        (
            "rename_roundtrip",
            [
                operators.rename_field("voltage", "bias_voltage"),
                operators.rename_field("bias_voltage", "voltage"),
            ],
        ),
        (
            "scale_roundtrip",
            [
                operators.scale_values("voltage", 1000.0, "mV"),
                operators.scale_values("voltage", 0.001, "V"),
            ],
        ),
    ]


def run_loops(fixture: Path, out_dir: Path) -> dict:
    fixture = Path(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        raise FileExistsError(f"receipts already exist at {receipts_path}")
    chain = assay.ReceiptChain(receipts_path)
    chain.append(assay.provenance_record(fixture))
    work = out_dir / "work"

    baseline = assay.run_word(fixture, [], work / "baseline", chain)
    loop_results = []
    for name, word in standard_loops():
        res = assay.run_word(fixture, word, work / name, chain)
        if not res["composable"]:
            classification = "noncomposable"
            k_value = None
        elif res["tree_sha"] == baseline["tree_sha"]:
            classification = "trivial"
            k_value = 0.0
        elif res["Y"] == baseline["Y"]:
            classification = "tree"
            k_value = 0.0
        else:
            classification = "behavior"
            k_value = assay.value_distance(
                res["Y"]["values"], baseline["Y"]["values"]
            )
        loop_results.append({
            "name": name,
            "word": res["word"],
            "composable": res["composable"],
            "classification": classification,
            "k_value": k_value,
            "digest_equal": bool(
                res["composable"]
                and res["Y"]["digest"] == baseline["Y"]["digest"]
            ),
        })

    analysis = {
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "fixture": fixture.name,
        "record": "loops",
        "receipt_head": chain.prev,
        "receipt_count": chain.seq,
        "excluded_non_invertible": EXCLUDED_NON_INVERTIBLE,
        "baseline_tree_sha": baseline["tree_sha"],
        "loops": loop_results,
    }
    with open(out_dir / "loops.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    return analysis


# ------------------------------------------------- commuting squares (2nd order)

SQUARE_PAIRS = {
    # fixture -> (A-factory args, B-factory args): certified-disjoint,
    # invertible pair per fixture; scale roundtrip chosen so the numeric
    # format loss lands in a different channel per fixture (pre-registered).
    "sensorlab": (("voltage", "bias_voltage"), ("pressure", 10.0, "hPa", 0.1, "kPa")),
    "pumplab": (("flow_rate", "mass_flow"), ("pressure", 10.0, "hPa", 0.1, "kPa")),
    "chemlab": (("reagent_a", "acid_a"), ("reagent_b", 1000.0, "uL", 0.001, "mL")),
    "textlab": (("weight", "mass"), ("score", 10.0, "dpt", 0.1, "pt")),
}


def commuting_squares(profile: str) -> list:
    """Square word [A, B, A^-1, B^-1] plus sequential control
    [A, A^-1, B, B^-1] for one certified-disjoint invertible pair."""
    (old, new), (fldb, k, unit_fwd, k_inv, unit_back) = SQUARE_PAIRS[profile]
    a = operators.rename_field(old, new)
    a_inv = operators.rename_field(new, old)
    b = operators.scale_values(fldb, k, unit_fwd)
    b_inv = operators.scale_values(fldb, k_inv, unit_back)
    return [(
        f"square_{old}__{fldb}",
        [a, b, a_inv, b_inv],
        [a, a_inv, b, b_inv],
    )]


def run_squares(fixture: Path, out_dir: Path, profile: str) -> dict:
    fixture = Path(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        raise FileExistsError(f"receipts already exist at {receipts_path}")
    chain = assay.ReceiptChain(receipts_path)
    chain.append(assay.provenance_record(fixture))
    work = out_dir / "work"

    baseline = assay.run_word(fixture, [], work / "baseline", chain)
    square_results = []
    for name, square_word, control_word in commuting_squares(profile):
        sq = assay.run_word(fixture, square_word, work / name, chain)
        ctrl = assay.run_word(fixture, control_word, work / f"{name}_ctrl", chain)
        if not sq["composable"]:
            classification = "noncomposable"
            k_value = None
        elif sq["tree_sha"] == baseline["tree_sha"]:
            classification = "trivial"
            k_value = 0.0
        elif sq["Y"] == baseline["Y"]:
            classification = "tree"
            k_value = 0.0
        else:
            classification = "behavior"
            k_value = assay.value_distance(
                sq["Y"]["values"], baseline["Y"]["values"])
        # second order: does interleaving add holonomy beyond the
        # component roundtrips? zero iff square and control end identical.
        if sq["composable"] and ctrl["composable"]:
            second_order = "zero" if sq["tree_sha"] == ctrl["tree_sha"] \
                else "nonzero"
        else:
            second_order = "noncomposable"
        square_results.append({
            "name": name,
            "word": sq["word"],
            "control_word": ctrl["word"],
            "composable": sq["composable"],
            "control_composable": ctrl["composable"],
            "classification": classification,
            "k_value": k_value,
            "digest_equal": bool(
                sq["composable"]
                and sq["Y"]["digest"] == baseline["Y"]["digest"]),
            "second_order": second_order,
        })

    analysis = {
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "fixture": fixture.name,
        "record": "commuting-squares",
        "receipt_head": chain.prev,
        "receipt_count": chain.seq,
        "baseline_tree_sha": baseline["tree_sha"],
        "squares": square_results,
    }
    with open(out_dir / "squares.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    return analysis


if __name__ == "__main__":
    here = Path(__file__).parent
    result = run_loops(here / "fixtures" / "sensorlab", here / "runs" / "loops-pilot")
    print(json.dumps(result["loops"], indent=2))
