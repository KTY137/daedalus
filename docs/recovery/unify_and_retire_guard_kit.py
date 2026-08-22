"""Owner-run kit 2026-08-22: unify the two lines on the g0 trunk, retire the
iron guard there, harvest today's work. History-preserving throughout.

Owner decisions (2026-08-22 08:55, verbatim intent): "unify die repos, das
neuere ist unsere basis" (D1 = g0 trunk), "heb alle guards auf", big cleanup.

What this does, in order (every step prints; aborts before any irreversible
step if preconditions fail; nothing is ever deleted from history):

PART A - UNIFY
  A1 tag the checkpoint line as archive/checkpoint-2026-07-20-session (at its
     current HEAD, i.e. including today's commits)
  A2 tag the g0 trunk as base/unified-2026-08-22
  A3 move `main` to the g0 trunk head (fast-forward if main is an ancestor;
     otherwise tag the old main as archive/main-pre-unify-2026-08-22 first,
     then force-move - history kept under the tag). Refuses if main is checked
     out in a worktree; tells you where.
  A4 in the g0 worktree: switch the checkout from work/g0-trunk-20260817 to
     main (same commit) so `main` is the working branch from now on.

PART B - RETIRE THE IRON GUARD (on main, in the g0 worktree)
  B1 write one FINAL amendment record on the g0 chain (seq N+1, Revision +1)
     saying the mechanical guard is retired by owner decision, with the
     checkpoint tip + tag named as frozen history; computed with the guard's
     own canonical hash while it still exists. Plan header Revision bumped by
     one byte, and a short dated retirement note appended at the end of the plan.
  B2 git config --local --unset core.hooksPath  (no commit hook runs anymore)
  B3 git rm: tools/iron_plan_guard.py, tools/iron_plan_hook_runner.py,
     tests/test_iron_plan_guard.py, .githooks/, .agents/skills/enforce-iron-plan/,
     .github/workflows/iron-plan.yml (if present)
  B4 .claude/settings.json: drop every hook entry whose command mentions
     iron_plan_hook_runner (SessionStart/UserPromptSubmit/PreToolUse/
     SubagentStart/Stop); keep the docs-drift reminder; ADD the serena-first
     PreToolUse entry (harvest of amendment 003) and copy
     .claude/hooks/serena-first.py from the checkpoint line.
  B5 .codex/hooks.json: drop iron entries (delete file if empty).
  B6 AGENTS.md: replace "Mandatory workflow" and "Protected changes" with the
     light, owner-decides versions; keep boundaries, scientific freedom,
     review rules.
  B7 one commit: "unify(2026-08-22): main is the g0 trunk, the iron guard is
     retired by owner decision". No trailers needed anymore.

PART C - HARVEST (cherry-pick -x onto main, in order; conflict => abort that
  one, record "needs rework", continue)
  today's docs commits from the checkpoint line (swarm archive, inventory
  bundle, giga plan, plain-language plan), then the vet.py hardening commits
  (5295c36f fb48a306 6ec7d2cb c264f5dd). Amendment 003 itself is NOT
  cherry-picked (its ledger record belongs to the frozen chain); its payload
  is applied in B4.

NOT touched: the runtime safety fence (daedalus/sensitivity.py, enforce,
vet.py, gated_writes write_wave_policy=never, .agentenv policy) - that
protects the product, it does not block the owner. Say so if it should go too.

Run (any cwd):  python docs/recovery/unify_and_retire_guard_kit.py
Dry run:        python docs/recovery/unify_and_retire_guard_kit.py --dry-run
After it lands: work in C:\\Users\\nukei\\Desktop\\agent_env_g0 (branch main)
and start Claude there; this checkpoint worktree keeps its old hooks until
you leave it.
"""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

DRY = "--dry-run" in sys.argv
CP = Path(r"C:\Users\nukei\Desktop\agent_env")          # checkpoint worktree
G0 = Path(r"C:\Users\nukei\Desktop\agent_env_g0")       # g0 trunk worktree
CP_BRANCH = "checkpoint/2026-07-20-session"
G0_BRANCH = "work/g0-trunk-20260817"
TODAY = "2026-08-22"
HARVEST = [  # oldest first
    "5295c36f", "fb48a306", "6ec7d2cb", "c264f5dd",   # vet.py hardening + tests
    "afd2968d", "1bf3fcf5", "77e7498a",               # swarm archive, inventory, giga plan
]


def git(cwd, *args, check=True, capture=True):
    cmd = ["git", "-C", str(cwd), *args]
    if DRY and args[0] in {"tag", "branch", "switch", "rm", "commit", "cherry-pick", "config", "add"} and "--list" not in args and "-r" not in args:
        print("   [dry] git", " ".join(args))
        return ""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return (r.stdout or "").strip() if capture else r.returncode


def step(msg):
    print(f"\n== {msg}")


# ---------------------------------------------------------------- preflight
step("preflight")
cp_head = git(CP, "rev-parse", CP_BRANCH)
g0_head = git(CP, "rev-parse", G0_BRANCH)
print("checkpoint head:", cp_head[:12], "| g0 head:", g0_head[:12])
g0_status = git(G0, "status", "--porcelain")
if g0_status:
    raise SystemExit("g0 worktree is not clean; commit or stash there first:\n" + g0_status)
g0_branch = git(G0, "branch", "--show-current")
if g0_branch != G0_BRANCH:
    raise SystemExit(f"g0 worktree is on {g0_branch!r}, expected {G0_BRANCH!r}")
if (CP / "docs/recovery/amendment_003_serena_first_kit.py").exists() is False:
    print("note: amendment_003 kit not found on checkpoint (fine)")
worktrees = git(CP, "worktree", "list", "--porcelain")
main_checked_out = re.search(r"worktree (.+)\nHEAD [0-9a-f]+\nbranch refs/heads/main\b", worktrees)
if main_checked_out:
    raise SystemExit(f"`main` is checked out at {main_checked_out.group(1)}; detach or switch it first")
main_exists = git(CP, "branch", "--list", "main") != ""
main_head = git(CP, "rev-parse", "main") if main_exists else ""
print("main exists:", main_exists, "| main head:", main_head[:12] if main_head else "-")
# today's checkpoint-only commits after the giga plan (plain-language companion etc.)
extra = git(CP, "log", "--format=%h", "77e7498a.." + CP_BRANCH).split()
for sha in reversed(extra):
    if sha not in HARVEST:
        HARVEST.append(sha)
print("harvest list:", " ".join(HARVEST))

# ---------------------------------------------------------------- PART A
step("A1/A2 tags")
git(CP, "tag", "-a", f"archive/checkpoint-2026-07-20-session", cp_head,
    "-m", f"Frozen checkpoint line at unification {TODAY}; harvested onto main; history preserved")
git(CP, "tag", "-a", f"base/unified-{TODAY}", g0_head,
    "-m", f"Owner decision {TODAY}: the g0 trunk is the unified base (D1)")
print("tagged.")

step("A3 move main")
if main_exists:
    ff = subprocess.run(["git", "-C", str(CP), "merge-base", "--is-ancestor", "main", G0_BRANCH]).returncode == 0
    if not ff:
        git(CP, "tag", "-a", f"archive/main-pre-unify-{TODAY}", "main",
            "-m", "old main before unification; history preserved")
        print("old main diverged -> tagged archive/main-pre-unify; force-moving")
git(CP, "branch", "-f", "main", g0_head)
print("main ->", g0_head[:12])

step("A4 switch g0 worktree to main")
git(G0, "switch", "main")
print("g0 worktree on:", "main" if DRY else git(G0, "branch", "--show-current"))

# ---------------------------------------------------------------- PART B
step("B1 final amendment record + plan note (with the guard's own hash)")
sys.path.insert(0, str(G0 / "tools"))
try:
    import iron_plan_guard as guard  # g0's guard, still present
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"cannot import g0 guard for the final record: {exc}")
PLAN = G0 / "docs/IKARUS_ARIADNE_MASTER_PLAN.md"
LEDGER = G0 / "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl"
records = guard.read_ledger(G0)
prev = records[-1]
base_digest = guard.file_sha256(PLAN)
revision, version, _ = guard.parse_plan_header(PLAN.read_text(encoding="utf-8"))
if base_digest != prev["result_plan_sha256"] or revision != prev["result_revision"]:
    raise SystemExit("g0 plan/ledger not sealed; the final record would not chain")
plan_bytes = PLAN.read_bytes()
needle = f"\nRevision: {revision}".encode()
if plan_bytes.count(needle) != 1:
    raise SystemExit("cannot locate the Revision header uniquely")
eol = b"\r\n" if b"\r\n" in plan_bytes else b"\n"
note = (
    f"{eol.decode()}{eol.decode()}Retirement note ({TODAY}, revision {revision + 1}): the mechanical "
    f"guard (tools/iron_plan_guard.py, hooks, commit hooks, CI) is retired by owner "
    f"decision. This plan stays the design authority as a document; changes are "
    f"owner commits that append a record to the amendment chain by hand. The "
    f"checkpoint line is frozen at tag archive/checkpoint-2026-07-20-session "
    f"({cp_head[:12]}); its work is harvested onto main.{eol.decode()}"
).encode("utf-8")
new_plan = plan_bytes.replace(needle, f"\nRevision: {revision + 1}".encode(), 1)
if not new_plan.endswith(b"\n"):
    new_plan += eol
new_plan += note
if not DRY:
    PLAN.write_bytes(new_plan)
result_digest = guard.file_sha256(PLAN) if not DRY else "dry"
record = {
    "schema": guard.SCHEMA, "plan_id": guard.PLAN_ID,
    "sequence": len(records) + 1, "status": "accepted",
    "accepted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "approval_ref": f"owner-decision-{TODAY}-unify-on-g0-and-retire-guard",
    "owner": "repository-owner",
    "base_plan_sha256": base_digest, "result_plan_sha256": result_digest,
    "base_revision": revision, "result_revision": revision + 1, "version": version,
    "previous_record_sha256": prev["record_sha256"],
    "scope": ["governance", "guard-retirement", "unification"],
    "summary": (f"Unify on the g0 trunk (main = {g0_head[:12]}); freeze the checkpoint "
                f"line at {cp_head[:12]} (tag archive/checkpoint-2026-07-20-session); "
                f"retire the mechanical iron guard by owner decision. Final "
                f"machine-validated record; later records are owner-appended."),
}
record["record_sha256"] = guard.canonical_record_sha256(record)
if not DRY:
    lb = LEDGER.read_bytes()
    with LEDGER.open("ab") as fh:
        if lb and not lb.endswith(b"\n"):
            fh.write(eol)
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + eol)
    errs = guard.verify(G0)
    if errs:
        print("guard verify after final record reports:", *errs, sep="\n  ")
        print("(continuing: the guard is being retired; the record chain itself is what matters)")
print(f"record {record['sequence']} appended; Revision {revision} -> {revision + 1}")

step("B2 unset core.hooksPath (shared .git -> all worktrees)")
git(CP, "config", "--local", "--unset", "core.hooksPath", check=False)
print("hooksPath:", git(CP, "config", "--local", "--get", "core.hooksPath", check=False) or "(unset)")

step("B3 remove guard files")
for rel in ["tools/iron_plan_guard.py", "tools/iron_plan_hook_runner.py",
            "tests/test_iron_plan_guard.py", ".githooks", ".agents/skills/enforce-iron-plan",
            ".github/workflows/iron-plan.yml"]:
    if (G0 / rel).exists():
        git(G0, "rm", "-r", "-q", rel)
        print("  removed", rel)

step("B4 settings.json: drop iron hooks, add serena-first (harvest)")
SETTINGS = G0 / ".claude/settings.json"
cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
hooks = cfg.get("hooks", {})
for event in list(hooks):
    kept = [e for e in hooks[event]
            if not any("iron_plan_hook_runner" in h.get("command", "") for h in e.get("hooks", []))]
    if kept:
        hooks[event] = kept
    else:
        del hooks[event]
serena_src = CP / ".claude/hooks/serena-first.py"
if serena_src.exists():
    dst = G0 / ".claude/hooks/serena-first.py"
    if not DRY:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(serena_src.read_bytes())
    hooks.setdefault("PreToolUse", []).append({
        "matcher": "Read|Grep",
        "hooks": [{"type": "command",
                   "command": 'python "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/serena-first.py"',
                   "timeout": 10, "statusMessage": "Routing symbol work through Serena..."}],
    })
    print("  serena-first hook harvested")
cfg["hooks"] = hooks
if not DRY:
    SETTINGS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    to_add = [".claude/settings.json"]
    if (G0 / ".claude/hooks/serena-first.py").exists():
        to_add.append(".claude/hooks/serena-first.py")
    sweep_src = CP / ".claude/watchdog/docs-sweep-prompt.md"
    if sweep_src.exists():  # docs watchdog prompt (untracked on the checkpoint line)
        sweep_dst = G0 / ".claude/watchdog/docs-sweep-prompt.md"
        sweep_dst.parent.mkdir(parents=True, exist_ok=True)
        sweep_dst.write_bytes(sweep_src.read_bytes())
        to_add.append(".claude/watchdog/docs-sweep-prompt.md")
    git(G0, "add", *to_add)
print("  hook events now:", sorted(hooks))

step("B5 .codex/hooks.json")
CODEX = G0 / ".codex/hooks.json"
if CODEX.exists():
    try:
        cj = json.loads(CODEX.read_text(encoding="utf-8"))
        txt = json.dumps(cj)
        if "iron_plan" in txt:
            git(G0, "rm", "-q", ".codex/hooks.json")
            print("  removed (iron-only)")
    except ValueError:
        print("  unreadable; left alone")

step("B6 AGENTS.md light")
AG = G0 / "AGENTS.md"
ag = AG.read_text(encoding="utf-8")
light_workflow = """## Working agreement

1. Read `docs/IKARUS_ARIADNE_MASTER_PLAN.md` before architecture, product,
   orchestration, memory, graph, generation, evolution, evaluator, storage, or
   runtime work. It is the design authority as a document; nothing enforces it
   mechanically anymore (owner decision 2026-08-22).
2. Say in one line whether a change is aligned with the plan, an isolated
   experiment, or a change to the plan itself. Changes to the plan are owner
   commits that append a record to the amendment chain by hand.
3. Implement through the canonical kernel. Prefer wiring, consolidation, and
   deletion over a new subsystem.
4. Preserve unrelated user changes and retain negative experimental evidence.
5. Verify the effect in proportion to risk and say what you measured.
"""
ag = re.sub(r"## Mandatory workflow\n.*?(?=\n## Non-negotiable boundaries)", light_workflow, ag, flags=re.S)
ag = ag.replace("- Never silently edit the plan, its lock, these instructions, or guardrails.\n",
                "- Never silently edit the plan or these instructions; say what you changed.\n")
ag = re.sub(r"## Protected changes\n.*?(?=\n## Review rules)",
            "## Plan changes\n\nThe plan and this file change by owner decision, recorded as an\nappended record in `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`.\nNo tool enforces this; honesty does.\n", ag, flags=re.S)
ag = ag.replace("- a hook or instruction advertised as a complete security guarantee.\n",
                "- a hook or instruction advertised as a complete security guarantee;\n- a guard that blocks reading or measuring (the retired one did).\n")
if not DRY:
    AG.write_text(ag, encoding="utf-8")
    git(G0, "add", "AGENTS.md", "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl")
print("  rewritten")

step("B7 commit")
msg = G0 / ".git-unify-msg.tmp"
if not DRY:
    msg.write_text(
        f"unify({TODAY}): main is the g0 trunk, the iron guard is retired by owner decision\n\n"
        f"Checkpoint line frozen at tag archive/checkpoint-2026-07-20-session ({cp_head[:12]});\n"
        f"g0 trunk tagged base/unified-{TODAY} ({g0_head[:12]}) and main moved there.\n"
        f"Final amendment record {record['sequence']} chains the retirement; plan Revision\n"
        f"{revision} -> {revision + 1}. Guard, hook runner, guard tests, git hooks, CI guard\n"
        f"and the enforce skill are removed; the serena-first hook is harvested.\n"
        f"The runtime safety fence is untouched.\n\n"
        f"Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n", encoding="utf-8")
    git(G0, "commit", "-F", str(msg))
    msg.unlink(missing_ok=True)
print("committed:", git(G0, "log", "--oneline", "-1") if not DRY else "(dry)")

# ---------------------------------------------------------------- PART C
step("C harvest cherry-picks onto main")
report = []
for sha in HARVEST:
    r = subprocess.run(["git", "-C", str(G0), "cherry-pick", "-x", sha],
                       capture_output=True, text=True, encoding="utf-8", errors="replace") if not DRY else None
    if DRY:
        report.append((sha, "dry")); continue
    if r.returncode == 0:
        report.append((sha, "ported"))
    else:
        subprocess.run(["git", "-C", str(G0), "cherry-pick", "--abort"], capture_output=True)
        report.append((sha, "needs-rework: " + (r.stderr.strip().splitlines() or ["?"])[-1][:120]))
for sha, state in report:
    print(f"  {sha}  {state}")

print("\nDONE. Next: cd C:\\Users\\nukei\\Desktop\\agent_env_g0 ; git log --oneline -12 ; start Claude there.")
print("Then run the cleanup kit: python docs/recovery/house_cleanup_kit.py --dry-run")
