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

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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


# ---------------------------------------------------------------- expansion

@dataclass(frozen=True)
class NeutralEdit:
    name: str
    apply: Callable[[Path], None] = field(repr=False)


def _comment_edit(fname: str, tag: str) -> NeutralEdit:
    stem = fname.split(".")[0]
    return NeutralEdit(
        f"comment_{stem}_{tag}",
        lambda tree, f=fname, t=tag: _append_line(
            tree / f, f"# neutral drift marker {t}"),
    )


def _blank_edit(fname: str, tag: str) -> NeutralEdit:
    stem = fname.split(".")[0]
    return NeutralEdit(
        f"blank_{stem}_{tag}",
        lambda tree, f=fname: _append_line(tree / f, ""),
    )


REORDER_CALIB = NeutralEdit(
    "reorder_calib_imports",
    lambda tree: _must_replace(
        tree / "calib.py", "import csv\nimport sys\n", "import sys\nimport csv\n"),
)

REORDER_CHECKS = NeutralEdit(
    "reorder_checks_imports",
    lambda tree: _must_replace(
        tree / "checks.py",
        "import csv\nfrom pathlib import Path\n",
        "from pathlib import Path\nimport csv\n"),
)


def walk_edits(L: int, variant: int) -> list:
    """Deterministically numbered neutral-edit walk.

    Families cycle (comment/whitespace on calib.py and checks.py, plus the
    two one-shot import reorders); `variant` offsets the cycle so walks of
    the same length differ. Tags embed variant and step, so appended
    markers are pairwise distinct. A reorder that already ran in this walk
    is replaced by a fresh comment edit — repeating it would raise (target
    gone) or silently no-op, and both would make L dishonest.
    """
    edits = []
    used = set()
    for i in range(L):
        idx = (variant + i) % 6
        tag = f"{variant}.{i}"
        if idx == 0:
            e = _comment_edit("calib.py", tag)
        elif idx == 1:
            e = _blank_edit("calib.py", tag)
        elif idx == 2:
            e = _comment_edit("checks.py", tag)
        elif idx == 3:
            e = _blank_edit("checks.py", tag)
        elif idx == 4:
            e = REORDER_CALIB if REORDER_CALIB.name not in used \
                else _comment_edit("calib.py", tag)
        else:
            e = REORDER_CHECKS if REORDER_CHECKS.name not in used \
                else _comment_edit("checks.py", tag)
        used.add(e.name)
        edits.append(e)
    return edits


def run_expansion(fixtures: dict, out_dir: Path,
                  ladder: tuple = (0, 2, 4, 8, 16), variants: int = 3) -> dict:
    """H-CRYPT expansion: walk ladder x numbered variants over N fixtures.

    `fixtures` maps fixture name -> (path, probes_factory). One receipt
    chain covers the whole campaign; the analysis is bound into the chain
    like run_matrix does, and cryptic.json carries the external anchor.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        raise FileExistsError(f"receipts already exist at {receipts_path}")
    chain = assay.ReceiptChain(receipts_path)
    work = out_dir / "work"

    result_fixtures = {}
    for fname, (fpath, probes_factory) in fixtures.items():
        fpath = Path(fpath)
        chain.append(assay.provenance_record(fpath))
        base = assay.run_word(fpath, [], work / fname / "base", chain)
        base_sigs = {
            name: _probe_signature(assay.run_word(
                fpath, [op], work / fname / f"base_probe_{name}", chain))
            for name, op in probes_factory().items()
        }
        walks = []
        l0_ok = None
        certified = 0
        total = 0
        for L in ladder:
            for v in range(1 if L == 0 else variants):
                total += 1
                edits = walk_edits(L, v)
                endpoint = work / fname / f"walk_L{L}_v{v}"
                if endpoint.exists():
                    shutil.rmtree(endpoint)
                shutil.copytree(
                    fpath, endpoint,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                for e in edits:
                    e.apply(endpoint)
                endpoint_y = evaluate.evaluate_tree(endpoint)
                neutral = endpoint_y == base["Y"]
                chain.append({
                    "experiment": assay.EXPERIMENT,
                    "spec_rev": assay.SPEC_REV,
                    "record": "neutral-walk",
                    "fixture": fname,
                    "L": L,
                    "variant": v,
                    "edits": [e.name for e in edits],
                    "neutral_certified": neutral,
                })
                walk = {
                    "L": L,
                    "variant": v,
                    "edits": [e.name for e in edits],
                    "neutral_certified": neutral,
                    "flips": [],
                    "flip_rate": None,
                }
                if neutral:
                    certified += 1
                    flips = []
                    for name, op in probes_factory().items():
                        res = assay.run_word(
                            endpoint, [op],
                            work / fname / f"walk_L{L}_v{v}_probe_{name}", chain)
                        if _probe_signature(res) != base_sigs[name]:
                            flips.append(name)
                    walk["flips"] = flips
                    walk["flip_rate"] = len(flips) / len(base_sigs)
                    if L == 0:
                        l0_ok = not flips
                walks.append(walk)
        result_fixtures[fname] = {
            "l0_ok": l0_ok,
            "acceptance_rate": certified / total,
            "walks": walks,
        }

    analysis = {
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "record": "cryptic-expansion",
        "ladder": list(ladder),
        "variants": variants,
        "fixtures": result_fixtures,
    }
    analysis_sha = hashlib.sha256(assay._canonical(analysis).encode()).hexdigest()
    chain.append({
        "experiment": assay.EXPERIMENT,
        "spec_rev": assay.SPEC_REV,
        "record": "analysis",
        "analysis_sha": analysis_sha,
    })
    analysis["receipt_head"] = chain.prev
    analysis["receipt_count"] = chain.seq
    with open(out_dir / "cryptic.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    return analysis


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
