"""Owner-run kit: amendment 004 - de-scope harness config from the iron guard.

Owner decision 2026-08-21 (AskUserQuestion: "De-Scope"): day-to-day harness
tuning must stop requiring the amendment ceremony, while the constitution
stays sealed.

Exact diff (tools/iron_plan_guard.py only):
  - PROTECTED_PATHS        loses ".claude/settings.json" and ".codex/hooks.json"
  - LOCAL_PROTECTED_PATHS  loses ".claude/settings.local.json"
Everything else keeps protection: plan, ledger, AGENTS.md, CLAUDE.md, the
guard itself, its tests, hook runner, githooks, CI workflow, CODEOWNERS,
agentenv policy, config.py/gated_writes.py/sensitivity.py.

What is deliberately NOT weakened: verify() still content-checks on every
commit that .claude/settings.json carries the Iron Plan guard hooks for all
REQUIRED_HOOK_EVENTS, that disableAllHooks is not set (settings.json AND
settings.local.json), and that hook-control mutations (core.hooksPath,
--no-verify) are blocked. The ceremony goes; the invariant stays.

Alternatives considered: full guard removal (rejected by recommendation -
kills the ledger credibility Gate 0 is built on); leaving as-is (rejected by
owner - real delay cost, measured 2026-08-21).
Rollback: revert the amendment commit via a new amendment (never rewrite).

The literal ".claude/settings.json" appears in MULTIPLE places in the guard
(the constants AND verify()'s content checks). This kit therefore removes
entries ONLY inside the two constant assignment spans, located via ast -
the verify() content checks are untouched. It then re-imports the edited
module in a subprocess and asserts the exact expected membership, runs the
guard's own test file (tolerating only the known pre-existing red
test_ci_history_check_accepts_adoption_and_rejects_rewrite), bumps the plan
revision, appends the chained ledger record, verifies, and commits atomically.

Run from anywhere:  python <path-to>/amendment_004_descope_harness_kit.py
"""
import ast
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\nukei\Desktop\agent_env")
sys.path.insert(0, str(ROOT / "tools"))
import iron_plan_guard as guard  # noqa: E402

PLAN = ROOT / "docs/IKARUS_ARIADNE_MASTER_PLAN.md"
LEDGER = ROOT / "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl"
GUARD = ROOT / "tools/iron_plan_guard.py"

DROP = {
    "PROTECTED_PATHS": {'".claude/settings.json",', '".codex/hooks.json",'},
    "LOCAL_PROTECTED_PATHS": {'".claude/settings.local.json",'},
}
KNOWN_RED = "test_ci_history_check_accepts_adoption_and_rejects_rewrite"

# --- 0. preflight (dynamic: works at any revision) --------------------------
records = guard.read_ledger(ROOT)
prev = records[-1]
base_digest = guard.file_sha256(PLAN)
plan_text = PLAN.read_text(encoding="utf-8")
revision, version, _ = guard.parse_plan_header(plan_text)
if base_digest != prev["result_plan_sha256"] or revision != prev["result_revision"]:
    print("plan/ledger are not in a sealed state; run verify and fix first")
    sys.exit(1)
if ".claude/settings.json" not in guard.PROTECTED_PATHS:
    print("already de-scoped; nothing to do")
    sys.exit(0)

# --- 1. guard edit, scoped to the two constant assignments via ast ----------
src_bytes = GUARD.read_bytes()
lines = src_bytes.splitlines(keepends=True)
tree = ast.parse(src_bytes.decode("utf-8"))
spans: dict[str, tuple[int, int]] = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in DROP:
            spans[target.id] = (node.lineno - 1, node.end_lineno)  # 0-based, excl
missing = set(DROP) - set(spans)
if missing:
    print(f"could not locate assignment span(s) for {sorted(missing)}; refusing")
    sys.exit(1)

removed = 0
keep: list[bytes] = []
for i, line in enumerate(lines):
    drop_this = False
    for name, (lo, hi) in spans.items():
        if lo <= i < hi and line.strip().decode("utf-8", "replace") in DROP[name]:
            drop_this = True
            removed += 1
            break
    if not drop_this:
        keep.append(line)
expected_removals = sum(len(v) for v in DROP.values())
if removed != expected_removals:
    print(f"expected to remove {expected_removals} entry lines, found {removed}; refusing")
    sys.exit(1)
GUARD.write_bytes(b"".join(keep))
print(f"guard: removed {removed} entries inside the constant spans")

# --- 2. re-import in a clean subprocess and assert exact membership ---------
probe = (
    "import sys; sys.path.insert(0, r'%s')\n"
    "import iron_plan_guard as g\n"
    "assert '.claude/settings.json' not in g.PROTECTED_PATHS\n"
    "assert '.codex/hooks.json' not in g.PROTECTED_PATHS\n"
    "assert '.claude/settings.local.json' not in g.LOCAL_PROTECTED_PATHS\n"
    "for keep in ('docs/IKARUS_ARIADNE_MASTER_PLAN.md',\n"
    "             'docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl',\n"
    "             'AGENTS.md', 'CLAUDE.md', 'tools/iron_plan_guard.py',\n"
    "             'tests/test_iron_plan_guard.py', '.githooks/pre-commit'):\n"
    "    assert keep in g.PROTECTED_PATHS, keep\n"
    "print('membership OK:', len(g.PROTECTED_PATHS), 'protected')\n"
) % str(ROOT / "tools")
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
if r.returncode != 0:
    print("membership probe FAILED; rollback: git checkout -- tools/iron_plan_guard.py")
    sys.exit(1)

# --- 3. guard test file must stay green (known pre-existing red tolerated) --
t = subprocess.run(
    [sys.executable, "-m", "pytest", str(ROOT / "tests/test_iron_plan_guard.py"),
     "-q", "--no-header"],
    capture_output=True, text=True, cwd=str(ROOT))
tail = "\n".join((t.stdout or "").strip().splitlines()[-15:])
print(tail)
if t.returncode != 0:
    failed = [ln for ln in (t.stdout or "").splitlines() if "FAILED" in ln]
    if any(KNOWN_RED not in ln for ln in failed) or not failed:
        print("NEW test failures; rollback: git checkout -- tools/iron_plan_guard.py")
        sys.exit(1)
    print(f"only the known pre-existing red ({KNOWN_RED}); proceeding")

# --- 4. plan revision bump (byte surgery) -----------------------------------
plan_bytes = PLAN.read_bytes()
needle = f"\nRevision: {revision}".encode()
if plan_bytes.count(needle) != 1:
    print("could not uniquely locate the Revision header; refusing")
    sys.exit(1)
PLAN.write_bytes(plan_bytes.replace(needle, f"\nRevision: {revision + 1}".encode(), 1))
result_digest = guard.file_sha256(PLAN)
print(f"plan: Revision {revision} -> {revision + 1}, digest {base_digest[:12]}... -> {result_digest[:12]}...")

# --- 5. chained ledger record ----------------------------------------------
record = {
    "schema": guard.SCHEMA,
    "plan_id": guard.PLAN_ID,
    "sequence": len(records) + 1,
    "status": "accepted",
    "accepted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "approval_ref": "owner-decision-2026-08-21-descope-harness-config (AskUserQuestion)",
    "owner": "repository-owner",
    "base_plan_sha256": base_digest,
    "result_plan_sha256": result_digest,
    "base_revision": revision,
    "result_revision": revision + 1,
    "version": version,
    "previous_record_sha256": prev["record_sha256"],
    "scope": ["guard-scope", "derived-controls", "harness-config"],
    "summary": (
        "De-scope harness config from path protection: .claude/settings.json "
        "and .codex/hooks.json leave PROTECTED_PATHS, .claude/settings.local.json "
        "leaves LOCAL_PROTECTED_PATHS. verify() content checks (guard hooks "
        "present, hooks not disabled) remain in force."
    ),
}
record["record_sha256"] = guard.canonical_record_sha256(record)
ledger_bytes = LEDGER.read_bytes()
eol = b"\r\n" if b"\r\n" in ledger_bytes else b"\n"
with LEDGER.open("ab") as fh:
    if ledger_bytes and not ledger_bytes.endswith(b"\n"):
        fh.write(eol)
    fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + eol)
print(f"ledger: record {record['sequence']} appended ({record['record_sha256'][:12]}...)")

# --- 6. verify with the EDITED guard (subprocess, not the stale import) -----
v = subprocess.run([sys.executable, str(GUARD), "--repo-root", str(ROOT), "verify"],
                   capture_output=True, text=True)
print((v.stdout or v.stderr).strip())
if v.returncode != 0:
    print("verify FAILED; rollback: git checkout -- tools/iron_plan_guard.py "
          "docs/IKARUS_ARIADNE_MASTER_PLAN.md docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
    sys.exit(1)

# --- 7. atomic stage + commit ----------------------------------------------
msg = Path(__file__).with_name("amendment_004_commitmsg.txt")
env = dict(os.environ, DAEDALUS_IRON_PLAN_AMENDMENT=base_digest)
subprocess.run(["git", "-C", str(ROOT), "add",
                "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
                "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
                "tools/iron_plan_guard.py"], env=env, check=False)
commit = subprocess.run(["git", "-C", str(ROOT), "commit", "-F", str(msg)],
                        env=env, capture_output=True, text=True)
print("commit rc:", commit.returncode)
print((commit.stdout or commit.stderr).strip()[-500:])
sys.exit(commit.returncode)
