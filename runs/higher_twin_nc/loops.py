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


if __name__ == "__main__":
    here = Path(__file__).parent
    result = run_loops(here / "fixtures" / "sensorlab", here / "runs" / "loops-pilot")
    print(json.dumps(result["loops"], indent=2))
