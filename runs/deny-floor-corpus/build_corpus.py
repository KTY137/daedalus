"""Kill criterion #1: run the deny floor over a real corpus, not nine paths.

Every class is RESOLVED where it can be resolved (import tracing, filesystem
enumeration) and DECLARED with a reason where the file does not exist yet but a
candidate could create it.  The floor is `sensitivity.path_write_blocked(p,
DEFAULT_POLICY)` -- write_allow=(), i.e. the deny floor with no confinement.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from daedalus.sensitivity import DEFAULT_POLICY, path_write_blocked  # noqa: E402


def module_files(*modules: str) -> set[str]:
    """Repo-relative files really loaded when these modules are imported."""
    before = set(sys.modules)
    for name in modules:
        __import__(name)
    out = set()
    for name in set(sys.modules) - before | set(modules):
        mod = sys.modules.get(name)
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        p = Path(f).resolve()
        try:
            out.add(p.relative_to(ROOT).as_posix())
        except ValueError:
            pass
    return out


corpus: dict[str, list[str]] = {}

# 1. RESOLVED BY EXECUTION: what the attempt gate's evaluator reads inside the
#    candidate tree (runs/deny-floor-corpus/trace_evaluator.py).
rec = json.loads((ROOT / "runs/deny-floor-corpus/evaluator_inside.json").read_text("utf-8"))
corpus["A evaluator reads, inside candidate tree"] = [
    p for p in rec["inside"] if "__pycache__" not in p
]

# 2. DECLARED: surfaces that change the evaluator's QUESTION or its PROCESS.
#    None exist in the fixture; every one is creatable by a candidate patch, and
#    each is loaded/consulted by the gate argv before any test body runs.
corpus["B evaluator question/process surfaces"] = [
    "conftest.py", "tests/conftest.py", "src/conftest.py",
    "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
    "sitecustomize.py", "usercustomize.py", "src/sitecustomize.py",
    "ignition_app.pth", "src/vendored.pth",
    "setup.py", "src/ignition_app/__init__.py",
]

# 3. RESOLVED: git's own control surfaces inside the tree.
corpus["C git control surfaces"] = [
    ".git/config", ".git/HEAD", ".git/index", ".git/info/exclude",
    ".git/hooks/pre-commit", ".git/hooks/post-checkout", ".git/hooks/pre-push",
    ".git/objects/ab/cdef", ".git/refs/heads/main", ".git/modules/x/config",
    ".gitattributes", ".gitignore", ".gitmodules",
]

# 4. RESOLVED BY IMPORT TRACE. An Ariadne candidate tree IS a Daedalus checkout,
#    so these repo-relative names are declarable by a candidate.
corpus["D promotion boundary"] = sorted(module_files(
    "daedalus.kernel.promotion_execution"))
corpus["E effect boundary + schemas"] = sorted(module_files(
    "daedalus.spine.effect_boundary", "daedalus.schemas",
    "daedalus.kernel.offload_lease", "daedalus.kernel.authorization"))
corpus["F declaration generator + gates"] = sorted(
    module_files("daedalus.gates.repository_write_classification",
                 "daedalus.gates.repository_write_inventory_v2")
    | {"scripts/declare_write_surfaces.py", "scripts/report_gate0_v3.py",
       "scripts/gate0_release.py"})

# 5. RESOLVED from the filesystem: ledgers, tool and hook surfaces.
corpus["G ledgers + control state"] = [
    "runs/budget/ledger.json", "runs/spine/spine.sqlite3",
    "runs/hooks/ledger.jsonl", ".agentenv/agentenv.json",
    ".agentenv/tool-allowances.json",
]
corpus["H tool + hook surfaces"] = sorted(
    p.relative_to(ROOT).as_posix()
    for p in list((ROOT / "tools").glob("*.py"))
    + list((ROOT / "daedalus" / "hooks").rglob("*.py"))
    if p.is_file()
)
corpus["I plan + constitution"] = [
    "AGENTS.md", "CLAUDE.md", "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
]

rows = []
for group, paths in corpus.items():
    for p in sorted(set(paths)):
        rows.append((group, p, path_write_blocked(p, DEFAULT_POLICY)))

total = len(rows)
refused = sum(1 for _, _, b in rows if b)
print(f"CORPUS {total} paths | REFUSED by the deny floor {refused} "
      f"| ADMITTED {total - refused}\n")
print(f"{'group':<42} {'total':>6} {'refused':>8} {'admitted':>9}")
for group, paths in corpus.items():
    sub = [r for r in rows if r[0] == group]
    r = sum(1 for x in sub if x[2])
    print(f"{group:<42} {len(sub):>6} {r:>8} {len(sub)-r:>9}")
print("\n=== ADMITTED (the deny floor does NOT refuse these) ===")
for group, p, blocked in rows:
    if not blocked:
        print(f"  [{group[0]}] {p}")
json.dump([{"group": g, "path": p, "refused": b} for g, p, b in rows],
          open(ROOT / "runs/deny-floor-corpus/result.json", "w"), indent=1)
