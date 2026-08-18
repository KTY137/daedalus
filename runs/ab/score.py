"""Score both arms against the hidden conformance suite, per-test.

Reports what Codex's design review demanded and no less:

* PER-TEST results grouped by module, not a bare `/23`. Twenty-three tests are
  not twenty-three equal requirements -- ten recipe mappings share a single
  test -- so a single ratio would overstate its own precision.
* The two tests Codex flagged as unfairly derived from the brief are scored
  SEPARATELY, and the headline is reported both with and without them:
    - `viewRecipe: unknown type or missing recipe returns null` asserts
      `place + tisch -> null`, which the brief's "Required mappings" list does
      not imply, because that list is required rather than exhaustive.
    - `deepLink: parses the four documented example URLs` requires the
      document's `recipe=tactical` URL to parse, while `tactical` is not a
      `RecipeId` and the brief never defines alias semantics.
* An EXPLORATORY compliance check (marked exploratory, decides nothing, per the
  pre-registration's rule about axes noticed mid-run): did the arm edit files
  the brief forbade?
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
AB_ROOT = Path(r"C:\Users\nukei\Desktop\ab_run")
SUITE = HERE / "conformance" / "conformance.test.ts"

CONTESTED = {
    "viewRecipe: unknown type or missing recipe returns null":
        "asserts place+tisch -> null; the brief's mapping list is 'required', not exhaustive",
    "deepLink: parses the four documented example URLs":
        "requires the document's recipe=tactical URL to parse; 'tactical' is not a RecipeId",
}

FORBIDDEN = ("package.json", "tsconfig.json", "vite.config.ts",
             "src/App.tsx", "src/main.tsx")


_REL_IMPORT = re.compile(r'(from\s+["\'])(\.\.?/[^"\']+?)(["\'])')


def materialise(core: Path) -> Path:
    """Copy an arm's modules somewhere Node's ESM loader can actually load them.

    NOT a correctness fix-up, and it changes no semantics. Both arms wrote
    `from "./scope"` -- extensionless relative imports, which is the idiomatic
    TypeScript a bundler resolves and which BOTH arms' `tsc --noEmit && vite
    build` gate accepted. Node's native type-stripping ESM loader demands an
    explicit extension, so running the modules directly scored the whole
    deepLink group 0/5 for BOTH arms.

    That was a defect in the MEASURING INSTRUMENT, not in either arm: it graded
    them in a configuration the product never runs. The transformation below is
    mechanical, identical for both arms, and touches only the import specifier.
    """
    import shutil
    import tempfile

    out = Path(tempfile.mkdtemp(prefix="abscore-"))
    if not core.is_dir():
        return out
    for src in core.glob("*.ts"):
        text = src.read_text(encoding="utf-8", errors="replace")
        text = _REL_IMPORT.sub(
            lambda m: m.group(1) + m.group(2) + ("" if Path(m.group(2)).suffix
                                                 else ".ts") + m.group(3), text)
        (out / src.name).write_text(text, encoding="utf-8")
    return out


def run_suite(core: Path) -> list[dict]:
    runnable = materialise(core)
    proc = subprocess.run(
        ["node", "--test", "--test-reporter=tap", str(SUITE)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=900,
        env={**__import__("os").environ, "ARM_CORE": str(runnable)}, shell=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    results = []
    for line in out.splitlines():
        m = re.match(r"^(not ok|ok)\s+\d+\s+-\s+(.*?)(?:\s+#.*)?$", line.strip())
        if not m:
            continue
        name = m.group(2).strip()
        if name.startswith("Subtest"):
            continue
        results.append({"test": name, "passed": m.group(1) == "ok"})
    return results


def module_of(test_name: str) -> str:
    return test_name.split(":", 1)[0].strip() if ":" in test_name else "other"


def compliance(arm: str) -> dict:
    """Exploratory only: what did the arm touch that the brief forbade?"""
    arm_dir = AB_ROOT / f"arm{arm}"
    proc = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=arm_dir,
                          capture_output=True, encoding="utf-8",
                          errors="replace", timeout=120)
    changed = [p.strip().replace("\\", "/") for p in (proc.stdout or "").splitlines()
               if p.strip()]
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=arm_dir,
        capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    added = [p.strip().replace("\\", "/") for p in (untracked.stdout or "").splitlines()
             if p.strip() and "node_modules" not in p]
    violations = [p for p in changed if any(p.endswith(f) for f in FORBIDDEN)]
    return {"modified": changed, "added": added, "forbidden_edits": violations}


def score_arm(arm: str) -> dict:
    core = AB_ROOT / f"arm{arm}" / "design" / "visual-lab" / "src" / "core"
    results = run_suite(core)
    by_module: dict[str, dict] = {}
    for r in results:
        mod = module_of(r["test"])
        b = by_module.setdefault(mod, {"passed": 0, "failed": 0, "tests": []})
        b["passed" if r["passed"] else "failed"] += 1
        b["tests"].append(r)

    contested = [r for r in results if r["test"] in CONTESTED]
    uncontested = [r for r in results if r["test"] not in CONTESTED]
    return {
        "arm": arm,
        "core_exists": core.is_dir(),
        "files": sorted(p.name for p in core.glob("*.ts")) if core.is_dir() else [],
        "headline": {
            "passed": sum(1 for r in results if r["passed"]), "total": len(results),
        },
        "excluding_contested": {
            "passed": sum(1 for r in uncontested if r["passed"]),
            "total": len(uncontested),
        },
        "contested": [{**r, "why_flagged": CONTESTED[r["test"]]} for r in contested],
        "by_module": {k: {"passed": v["passed"], "failed": v["failed"]}
                      for k, v in sorted(by_module.items())},
        "failures": [r["test"] for r in results if not r["passed"]],
        "compliance_EXPLORATORY": compliance(arm),
    }


def main() -> int:
    import sys as _sys
    _repo_root = str(HERE.parents[1])
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "runs.ab.score",
        REGISTRY_BY_ID["runs.ab.score"].effects,
        (process_guard_boundary_decision(),),
    )
    out = {"note": ("per-test, module-grouped. Contested tests are excluded from "
                    "'excluding_contested' and listed with the reason. The "
                    "compliance block is EXPLORATORY and decides nothing."),
           "arms": {}}
    for arm in ("A", "B"):
        out["arms"][arm] = score_arm(arm)
    (HERE / "receipts" / "conformance.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    for arm, s in out["arms"].items():
        h, e = s["headline"], s["excluding_contested"]
        print(f"arm{arm}: {h['passed']}/{h['total']}  "
              f"(excl. contested {e['passed']}/{e['total']})  files={len(s['files'])}")
        for mod, m in s["by_module"].items():
            print(f"    {mod:14s} {m['passed']} pass / {m['failed']} fail")
        if s["compliance_EXPLORATORY"]["forbidden_edits"]:
            print(f"    ! forbidden edits: {s['compliance_EXPLORATORY']['forbidden_edits']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
