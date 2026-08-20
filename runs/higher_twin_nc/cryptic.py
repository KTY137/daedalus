"""Cryptic-variance pilot (H-CRYPT): does certified-neutral drift change
what future patches do?

Deterministic neutral edits (no RNG — reproducibility over realism at pilot
stage) are composed into walks of length L. A walk endpoint is CERTIFIED
neutral only if its full evaluator outcome equals the baseline's. Then every
probe operator is applied both to the baseline and to the walk endpoint; a
FLIP is any difference in the probe's outcome (composability, fail reason, or
evaluator result — tree hashes are excluded: the endpoint tree trivially
differs by the neutral edits themselves).

L=0 is the harness self test: any flip there proves nondeterminism and
invalidates the run.
"""
from __future__ import annotations

import json
from pathlib import Path

import assay
import evaluate
import operators


# ---------------------------------------------------------------- neutral edits

def _append_line(path: Path, line: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(text + line + "\n", encoding="utf-8", newline="\n")


def _must_replace(path: Path, old: str, new: str) -> None:
    """A neutral edit that silently does nothing would inflate the walk
    length L; refusing loudly keeps L honest."""
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"neutral edit target not found in {path.name}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def n1_comment_calib(tree: Path) -> None:
    _append_line(tree / "calib.py", "# neutral drift marker one")


def n2_blankline_after_offset(tree: Path) -> None:
    _must_replace(tree / "calib.py", "OFFSET = 0.1\n", "OFFSET = 0.1\n\n")


def n3_import_reorder(tree: Path) -> None:
    _must_replace(tree / "calib.py", "import csv\nimport sys\n", "import sys\nimport csv\n")


def n4_comment_checks(tree: Path) -> None:
    _append_line(tree / "checks.py", "# neutral drift marker two")


WALKS = [
    (0, []),
    (2, [n1_comment_calib, n2_blankline_after_offset]),
    (4, [n1_comment_calib, n2_blankline_after_offset, n3_import_reorder, n4_comment_checks]),
]


def _probe_signature(result: dict) -> dict:
    return {
        "composable": result["composable"],
        "fail_reason": result["fail_reason"],
        "Y": result["Y"],
    }


def run_pilot(fixture: Path, out_dir: Path) -> dict:
    fixture = Path(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        raise FileExistsError(f"receipts already exist at {receipts_path}")
    chain = assay.ReceiptChain(receipts_path)
    chain.append(assay.provenance_record(fixture))
    work = out_dir / "work"

    base = assay.run_word(fixture, [], work / "base", chain)
    probes = operators.standard_ops()
    base_signatures = {
        name: _probe_signature(assay.run_word(fixture, [op], work / f"base_probe_{name}", chain))
        for name, op in probes.items()
    }

    walks = []
    l0_ok = None
    for L, edits in WALKS:
        endpoint = work / f"walk_L{L}"
        if endpoint.exists():
            import shutil
            shutil.rmtree(endpoint)
        import shutil
        shutil.copytree(
            fixture, endpoint,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for edit in edits:
            edit(endpoint)
        endpoint_y = evaluate.evaluate_tree(endpoint)
        neutral = endpoint_y == base["Y"]
        chain.append({
            "experiment": assay.EXPERIMENT,
            "spec_rev": assay.SPEC_REV,
            "record": "neutral-walk",
            "L": L,
            "edits": [e.__name__ for e in edits],
            "neutral_certified": neutral,
        })
        walk = {
            "L": L,
            "edits": [e.__name__ for e in edits],
            "neutral_certified": neutral,
            "flips": [],
            "flip_rate": None,
        }
        if neutral:
            flips = []
            for name, factory in operators.standard_ops().items():
                res = assay.run_word(
                    endpoint, [factory], work / f"walk_L{L}_probe_{name}", chain
                )
                if _probe_signature(res) != base_signatures[name]:
                    flips.append(name)
            walk["flips"] = flips
            walk["flip_rate"] = len(flips) / len(base_signatures)
            if L == 0:
                l0_ok = not flips
        walks.append(walk)

    analysis = {
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "fixture": fixture.name,
        "record": "cryptic-pilot",
        "receipt_head": chain.prev,
        "receipt_count": chain.seq,
        "l0_ok": l0_ok,
        "walks": walks,
    }
    with open(out_dir / "cryptic.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    return analysis


if __name__ == "__main__":
    here = Path(__file__).parent
    result = run_pilot(here / "fixtures" / "sensorlab", here / "runs" / "cryptic-pilot")
    print(json.dumps({k: result[k] for k in ("l0_ok",)} | {"walks": result["walks"]}, indent=2))
