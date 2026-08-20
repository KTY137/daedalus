"""A/B/AB/BA/Sham intervention assay for higher-twin-nc-v1.

Runs ordered operator words on fresh copies of a fixture tree, evaluates
each outcome with the sealed deterministic ladder, and emits hash-chained
receipts. The pair analysis separates:

  K_tree     do both orders even produce the same tree?
  K_behave   do both orders produce the same evaluator outcome?

and cross-references the static footprint prediction:

  certificate   footprint-disjoint pairs are predicted to commute (sound,
                deliberately incomplete)
  anomaly       footprint-disjoint but behaviorally non-commuting: the
                signature of a hidden coupling

Nothing here promotes anything; the output is measurement plus receipts.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from itertools import combinations, permutations
from pathlib import Path

import evaluate
import operators

EXPERIMENT = "higher-twin-nc-v1"
SPEC_REV = 2

#: Harness modules whose bytes define the measurement instrument; hashed into
#: every campaign's provenance receipt so a silent code change under the same
#: experiment/spec identifiers is detectable.
_CODE_FILES = ("operators.py", "evaluate.py", "assay.py", "loops.py", "cryptic.py")


def provenance_record(fixture: Path) -> dict:
    import sys as _sys
    h = hashlib.sha256()
    here = Path(__file__).parent
    for name in _CODE_FILES:
        path = here / name
        if path.exists():
            h.update(name.encode("utf-8"))
            h.update(b"\0")
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return {
        "experiment": EXPERIMENT,
        "spec_rev": SPEC_REV,
        "record": "provenance",
        "code_sha": h.hexdigest(),
        "python_version": _sys.version.split()[0],
        "fixture": Path(fixture).name,
        "fixture_tree_sha": hash_tree(fixture),
    }


# ---------------------------------------------------------------- hashing

def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_tree(tree: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(Path(tree).rglob("*")):
        rel = path.relative_to(tree).as_posix()
        if "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        if path.is_dir():
            # empty directories are observable by fixture code; K_tree must
            # not silently equate trees that differ only in one
            h.update(rel.encode("utf-8"))
            h.update(b"\0DIR\0")
            continue
        data = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


# ---------------------------------------------------------------- receipts

class ReceiptChain:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.prev = None
        self.seq = 0

    def append(self, record: dict) -> dict:
        record = dict(record)
        record["seq"] = self.seq
        record["prev"] = self.prev
        record["ts"] = datetime.now(timezone.utc).isoformat()
        record["entry_sha"] = hashlib.sha256(_canonical(record).encode()).hexdigest()
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(_canonical(record) + "\n")
        self.prev = record["entry_sha"]
        self.seq += 1
        return record


def verify_chain(path: Path, expected_head: str = None, expected_count: int = None) -> bool:
    """Verify the receipt chain. Bool contract: malformed input returns False.

    LIMIT (documented, not a security guarantee): without `expected_head` and
    `expected_count` anchored OUTSIDE this file (kmatrix.json stores them),
    any valid prefix verifies, and an attacker who rewrites a line and
    rehashes all successors also verifies — there is no secret. The chain is
    a tamper INDICATOR against accident, not a cryptographic seal.
    """
    prev = None
    seq = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                record = json.loads(line)
                claimed = record.pop("entry_sha")
                if record.get("prev") != prev or record.get("seq") != seq:
                    return False
                if hashlib.sha256(_canonical(record).encode()).hexdigest() != claimed:
                    return False
                prev = claimed
                seq += 1
    except (OSError, ValueError, KeyError):
        return False
    if expected_head is not None and prev != expected_head:
        return False
    if expected_count is not None and seq != expected_count:
        return False
    return seq > 0


def value_distance(a: list, b: list):
    """Continuous K component: mean symmetric relative distance of the
    calibrated-value vectors. None when shapes make comparison meaningless."""
    if a is None or b is None or len(a) != len(b) or not a:
        return None
    total = 0.0
    for x, y in zip(a, b):
        if not (isinstance(x, float) and isinstance(y, float)):
            # non-finite tokens are carried as strings; distance is undefined
            return None
        total += abs(x - y) / (abs(x) + abs(y) + 1e-12)
    return total / len(a)


# ---------------------------------------------------------------- word runs

def _file_shas(tree: Path) -> dict:
    shas = {}
    for path in sorted(Path(tree).rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(tree).as_posix()
        if "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        shas[rel] = hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
    return shas


def run_word(fixture: Path, ops: list, workdir: Path, chain: ReceiptChain = None) -> dict:
    tree = Path(workdir)
    if tree.exists():
        shutil.rmtree(tree)
    shutil.copytree(
        fixture, tree,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    result = {
        "word": [op.name for op in ops],
        "composable": True,
        "fail_reason": None,
        "tree_sha": None,
        "Y": None,
        "ops_applied": [],
        "precondition_mutations": [],
    }

    def _diff(before, after):
        return sorted(
            set(before) ^ set(after)
            | {rel for rel in set(before) & set(after) if before[rel] != after[rel]}
        )

    for op in ops:
        # snapshot BEFORE the precondition: a mutating precondition must not
        # be invisible to the measured footprint
        before = _file_shas(tree)
        reason = op.precondition(tree)
        after_pre = _file_shas(tree)
        pre_mut = _diff(before, after_pre)
        if pre_mut:
            result["precondition_mutations"].extend(pre_mut)
        if reason is not None:
            result["composable"] = False
            result["fail_reason"] = f"{op.name}: {reason}"
            break
        try:
            op.apply(tree)
        except Exception as exc:  # a broken operator is a recorded failure, not a crash
            after = _file_shas(tree)
            result["ops_applied"].append({
                "name": op.name,
                "files_changed": _diff(after_pre, after),
                "failed": True,
            })
            result["composable"] = False
            result["fail_reason"] = f"{op.name}: exception {type(exc).__name__}: {exc}"
            break
        after = _file_shas(tree)
        # measured footprint (file level): the audit channel that adjudicates
        # H-CERT kill vs. H-ANOM hit — declarations are self-reports, this is not
        result["ops_applied"].append({
            "name": op.name,
            "files_changed": _diff(after_pre, after),
            "failed": False,
        })
    if result["composable"]:
        result["tree_sha"] = hash_tree(tree)
        # evaluate at a CANONICAL path: the digest must never observe the
        # order-specific workdir label (AB vs BA ran under different names)
        exec_dir = tree.parent / "_exec"
        if exec_dir.exists():
            shutil.rmtree(exec_dir)
        shutil.copytree(
            tree, exec_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        try:
            result["Y"] = evaluate.evaluate_tree(exec_dir)
        finally:
            shutil.rmtree(exec_dir, ignore_errors=True)
    if chain is not None:
        chain.append({
            "experiment": EXPERIMENT,
            "spec_rev": SPEC_REV,
            "fixture": Path(fixture).name,
            "record": "word",
            **result,
        })
    return result


# ---------------------------------------------------------------- matrix

def _classify(ab: dict, ba: dict) -> str:
    if not ab["composable"] and not ba["composable"]:
        return "noncomposable-both"
    if ab["composable"] != ba["composable"]:
        return "noncomposable-asym"
    if ab["tree_sha"] == ba["tree_sha"]:
        return "commute-tree"
    if ab["Y"] == ba["Y"]:
        return "commute-behavior"
    return "noncommute-behavior"


def run_matrix(fixture: Path, ops: dict, out_dir: Path, depth: int = 2) -> dict:
    fixture = Path(fixture)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        # fail-closed: appending a second run would restart seq/prev mid-file
        # and leave an unverifiable chain next to fresh-looking artifacts
        raise FileExistsError(
            f"receipts already exist at {receipts_path}; use a fresh out_dir"
        )
    chain = ReceiptChain(receipts_path)
    chain.append(provenance_record(fixture))

    def run(ops_list, label):
        return run_word(fixture, ops_list, work / label, chain)

    results = {}
    results[()] = run([], "000_baseline")
    results[("sham",)] = run([operators.sham()], "001_sham")
    names = list(ops)
    for i, name in enumerate(names):
        results[(name,)] = run([ops[name]], f"1{i:02d}_{name}")
    if depth >= 2:
        for i, (a, b) in enumerate(permutations(names, 2)):
            results[(a, b)] = run([ops[a], ops[b]], f"2{i:02d}_{a}--{b}")

    pairs = []
    for a, b in combinations(names, 2):
        ab, ba = results[(a, b)], results[(b, a)]
        both = ab["composable"] and ba["composable"]
        fp_conflict = operators.conflict(ops[a], ops[b])
        classification = _classify(ab, ba)
        k_value = value_distance(
            ab["Y"]["values"] if both else None,
            ba["Y"]["values"] if both else None,
        )
        pair = {
            "pair": [a, b],
            "ab_composable": ab["composable"],
            "ba_composable": ba["composable"],
            "fail_reasons": [ab["fail_reason"], ba["fail_reason"]],
            "footprint_conflict": fp_conflict,
            "tree_equal": bool(both and ab["tree_sha"] == ba["tree_sha"]),
            "behavior_equal": bool(both and ab["Y"] == ba["Y"]),
            "digest_equal": bool(both and ab["Y"]["digest"] == ba["Y"]["digest"]),
            "k_value": k_value,
            "classification": classification,
            "certificate_predicted": not fp_conflict,
            # anomaly = declared-disjoint pair whose order still matters:
            # behaviorally (Y differs on DIFFERENT trees) or structurally
            # (asymmetric composability). Identical trees with differing Y is
            # not a coupling — it is evaluator nondeterminism: harness_alert.
            "anomaly": bool(
                not fp_conflict
                and (
                    classification == "noncomposable-asym"
                    or (
                        both
                        and ab["tree_sha"] != ba["tree_sha"]
                        and ab["Y"] != ba["Y"]
                    )
                )
            ),
            "harness_alert": bool(
                both and ab["tree_sha"] == ba["tree_sha"] and ab["Y"] != ba["Y"]
            ),
        }
        pairs.append(pair)

    analysis = {
        "experiment": EXPERIMENT,
        "spec_rev": SPEC_REV,
        "fixture": fixture.name,
        "runs": len(results),
        "baseline": results[()],
        "sham": results[("sham",)],
        "singles": {name: results[(name,)] for name in names},
        "pairs": pairs,
    }
    # bind the ANALYSIS (pair classifications, anomaly flags) into the chain:
    # a receipt chain that only covers word runs would let kmatrix.json and
    # report.md be edited while the chain still verifies
    analysis_sha = hashlib.sha256(_canonical(analysis).encode()).hexdigest()
    chain.append({
        "experiment": EXPERIMENT,
        "spec_rev": SPEC_REV,
        "record": "analysis",
        "analysis_sha": analysis_sha,
    })
    analysis["receipt_head"] = chain.prev
    analysis["receipt_count"] = chain.seq
    with open(out_dir / "kmatrix.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(analysis, fh, indent=2)
        fh.write("\n")
    _write_report(out_dir / "report.md", analysis)
    return analysis


def verify_analysis(out_dir: Path) -> bool:
    """Anchored verification of a matrix campaign directory.

    Checks that (a) the chain verifies against the head/count stored in
    kmatrix.json, and (b) the analysis content of kmatrix.json matches the
    analysis_sha bound into the chain's final receipt. The remaining trust
    root is the commit that stores both files — git is the external anchor.
    """
    out_dir = Path(out_dir)
    try:
        with open(out_dir / "kmatrix.json", encoding="utf-8") as fh:
            stored = json.load(fh)
        head = stored.pop("receipt_head")
        count = stored.pop("receipt_count")
        if not verify_chain(out_dir / "receipts.jsonl",
                            expected_head=head, expected_count=count):
            return False
        expected_sha = hashlib.sha256(_canonical(stored).encode()).hexdigest()
        last = None
        with open(out_dir / "receipts.jsonl", encoding="utf-8") as fh:
            for line in fh:
                last = json.loads(line)
        return bool(last and last.get("record") == "analysis"
                    and last.get("analysis_sha") == expected_sha)
    except (OSError, ValueError, KeyError):
        return False


def _write_report(path: Path, analysis: dict) -> None:
    lines = [
        f"# K-matrix report: {analysis['fixture']} ({EXPERIMENT}, spec rev {SPEC_REV})",
        "",
        f"Runs: {analysis['runs']}  |  sham is behavioral null: "
        f"{analysis['sham']['Y'] == analysis['baseline']['Y']}",
        "",
        "| pair | composable AB/BA | footprint | class | k_value | anomaly |",
        "|---|---|---|---|---|---|",
    ]
    for p in analysis["pairs"]:
        comp = f"{'y' if p['ab_composable'] else 'n'}/{'y' if p['ba_composable'] else 'n'}"
        fp = "conflict" if p["footprint_conflict"] else "disjoint"
        kv = "-" if p["k_value"] is None else f"{p['k_value']:.6f}"
        lines.append(
            f"| {p['pair'][0]}+{p['pair'][1]} | {comp} | {fp} "
            f"| {p['classification']} | {kv} | {'YES' if p['anomaly'] else '-'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="fixtures/sensorlab")
    parser.add_argument("--out", default="runs/pilot")
    args = parser.parse_args()
    here = Path(__file__).parent
    analysis = run_matrix(here / args.fixture, operators.standard_ops(), here / args.out)
    print(json.dumps({k: analysis[k] for k in ("experiment", "fixture", "runs")}, indent=2))
    print((here / args.out / "report.md").read_text(encoding="utf-8"))
