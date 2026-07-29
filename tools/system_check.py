"""Does the SYSTEM work? -- an end-to-end acceptance run over the real paths.

WHY THIS EXISTS. The unit suite is at 1732 green and that is not evidence the
product works. Three times in one day a fully green suite sat over a live
escape; the A/B produced two implementations that passed their gate and
contained no tests at all. A green suite says "the parts behave as their tests
describe". This says "the spine runs, on this machine, right now" -- or it says
which stage does not, with the evidence attached.

THREE OUTCOMES, AND ONLY ONE IS SUCCESS.

    PASS         the property was checked and held
    FAIL         the property was checked and did NOT hold
    UNAVAILABLE  the property could NOT be checked here

UNAVAILABLE IS NOT SUCCESS, AND ON A CORE CHECK IT IS NOT EVEN NEUTRAL. The
first version of this file counted it separately and still exited 0, which made
the contract above a sentence rather than a control -- exactly the defect this
repo keeps finding. The exit code now says which of three things happened:

    0   every CORE check ran and passed          (the only "it works")
    1   at least one check FAILED
    2   INCOMPLETE: a CORE check could not run, so the run proves nothing

EVERYTHING RUNS IN A DISPOSABLE CLONE. Checks that must observe mutation cannot
be trusted to observe it in the tree they are also being read from, and a
harness that can damage the working repo is not one anybody will run twice. The
clone carries the working tree (committed state plus uncommitted diff plus
untracked files), a temp spine DB, and a temp HOME.

    python tools/system_check.py              # the acceptance run
    python tools/system_check.py --json       # machine-readable receipt
    python tools/system_check.py --self-test  # prove every check can go RED
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

PASS, FAIL, UNAVAILABLE = "PASS", "FAIL", "UNAVAILABLE"
EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE = 0, 1, 2


@dataclass
class Result:
    name: str
    outcome: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    stage: str = ""
    proves: str = ""
    core: bool = True
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "stage": self.stage, "core": self.core,
                "proves": self.proves, "outcome": self.outcome,
                "detail": self.detail, "evidence": self.evidence,
                "seconds": round(self.seconds, 2)}


CHECKS: list = []


def check(name: str, *, stage: str, proves: str, core: bool = True):
    """Register a check. ``core=False`` marks one whose absence does not
    invalidate the run -- used only where the capability is genuinely optional
    on a given machine, never to soften a check that keeps going UNAVAILABLE."""
    def deco(fn):
        CHECKS.append({"name": name, "stage": stage, "proves": proves,
                       "core": core, "fn": fn})
        return fn
    return deco


def run(args, *, cwd=None, timeout=900, env=None, stdin=None):
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}
    try:
        proc = subprocess.run([str(a) for a in args], cwd=str(cwd or ROOT),
                              capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              env=full_env, input=stdin)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except OSError as e:
        return 127, f"could not execute: {e}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- #
# the disposable clone                                                         #
# --------------------------------------------------------------------------- #
class Sandbox:
    """A throwaway copy of the WORKING TREE, plus a temp HOME and spine DB.

    Committed state alone would test HEAD, not what is actually on disk, so the
    uncommitted diff and the untracked-but-not-ignored files are carried over
    too: an acceptance run that cannot see your current work is measuring the
    wrong tree.
    """

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="daedalus-acceptance-"))
        self.repo = self.tmp / "repo"
        self.home = self.tmp / "home"
        self.db = self.tmp / "spine.sqlite3"
        self.home.mkdir(parents=True, exist_ok=True)
        self.ready = False
        self.error = ""

    def build(self) -> bool:
        rc, out = run(["git", "clone", "--local", "--no-hardlinks",
                       str(ROOT), str(self.repo)], timeout=1800)
        if rc != 0:
            self.error = f"git clone failed: {out[-300:]}"
            return False
        rc, diff = run(["git", "diff", "HEAD"], timeout=600)
        if rc == 0 and diff.strip():
            patch = self.tmp / "working.patch"
            patch.write_text(diff, encoding="utf-8", newline="")
            rc2, out2 = run(["git", "apply", "--whitespace=nowarn", str(patch)],
                            cwd=self.repo, timeout=600)
            if rc2 != 0:
                self.error = f"could not carry the working diff: {out2[-300:]}"
                return False
        rc, listing = run(["git", "ls-files", "--others", "--exclude-standard"],
                          timeout=600)
        for rel in [l.strip() for l in listing.splitlines() if l.strip()]:
            src, dst = ROOT / rel, self.repo / rel
            try:
                if src.is_file() and src.stat().st_size < 8_000_000:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except OSError:
                pass
        self.ready = True
        return True

    @property
    def env(self) -> dict:
        return {"HOME": str(self.home), "USERPROFILE": str(self.home),
                "DAEDALUS_SPINE_DB": str(self.db)}

    def cli(self, *args, **kw):
        kw.setdefault("cwd", self.repo)
        kw["env"] = {**self.env, **(kw.get("env") or {})}
        return run([PY, "-m", "daedalus.cli", *args], **kw)

    def py(self, *args, **kw):
        kw.setdefault("cwd", self.repo)
        kw["env"] = {**self.env, **(kw.get("env") or {})}
        return run([PY, *args], **kw)

    def git(self, *args) -> str:
        rc, out = run(["git", *args], cwd=self.repo, timeout=300)
        return out if rc == 0 else ""

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def worktree_fingerprint(self) -> tuple:
        """(HEAD, porcelain status SET, hash of every tracked file).

        A COUNT of status lines is not a fingerprint: one file deleted plus one
        created leaves the count unchanged, and an edit to an already-dirty file
        never shows at all. The first version of this harness compared counts
        and would have called both of those "no mutation".
        """
        status = frozenset(l.strip() for l in
                           self.git("status", "--porcelain").splitlines() if l.strip())
        h = hashlib.sha256()
        for rel in sorted(l.strip() for l in
                          self.git("ls-files").splitlines() if l.strip()):
            p = self.repo / rel
            h.update(rel.encode("utf-8", "replace"))
            try:
                h.update(p.read_bytes() if p.is_file() else b"<missing>")
            except OSError:
                h.update(b"<unreadable>")
        return self.head(), status, h.hexdigest()

    def attempt_branches(self) -> list:
        return sorted(l.strip().lstrip("* ") for l in
                      self.git("branch", "--list", "daedalus-attempt-*").splitlines()
                      if l.strip())

    def intents(self) -> list:
        return read_intents(self.db)

    def destroy(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def read_intents(db: Path) -> list:
    if not Path(db).exists():
        return []
    import sqlite3
    try:
        uri = "file:" + str(db).replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        rows = con.execute(
            "SELECT i.id, i.payload, COALESCE((SELECT e.state FROM intent_events e"
            " WHERE e.intent_id = i.id AND e.state IN ('COMPLETED','FAILED')"
            " LIMIT 1), 'INTENDED') FROM intents i ORDER BY i.id").fetchall()
        con.close()
        return rows
    except Exception:
        return []


def _json_tail(out: str):
    """The LAST JSON object in the output, not the first.

    A probe's own report is the last thing it prints; anything the imported
    product code emitted first (a warning, a progress line, its own JSON) comes
    before it. Taking the first `{` made one check "catch" a seeded defect for
    the wrong reason -- it failed to PARSE rather than failing the property,
    which is a pass that would have evaporated the moment the noise changed.
    """
    for start in range(len(out)):
        if out[start] != "{":
            continue
        break
    candidates = [i for i, ch in enumerate(out) if ch == "{"]
    for i in reversed(candidates):
        try:
            return json.loads(out[i:].strip())
        except (ValueError, json.JSONDecodeError):
            continue
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- #
# 0 -- preflight                                                               #
# --------------------------------------------------------------------------- #
@check("cli.entrypoint", stage="0 preflight",
       proves="the single documented entry point runs and lists its verbs")
def _cli_entrypoint(sb: Sandbox) -> Result:
    rc, out = sb.cli(timeout=300)
    ok = rc == 0 and "daedalus improve" in out and "daedalus map" in out
    return Result("cli.entrypoint", PASS if ok else FAIL,
                  "" if ok else f"rc={rc}; head={out[:200]!r}",
                  {"returncode": rc})


@check("doctor.reports_readiness", stage="0 preflight",
       proves="doctor states whether the bench can execute instead of guessing")
def _doctor(sb: Sandbox) -> Result:
    rc, out = sb.cli("doctor", timeout=600)
    verdict = ("READY" in out) or ("[OK]" in out) or ("[!!]" in out)
    if not verdict:
        return Result("doctor.reports_readiness", FAIL,
                      f"rc={rc}; no verdict in output", {"returncode": rc})
    return Result("doctor.reports_readiness", PASS, "",
                  {"returncode": rc,
                   "ollama": "[OK] Ollama server reachable" in out,
                   "claude_cli": "[OK] claude CLI" in out})


# --------------------------------------------------------------------------- #
# 1 -- intent and plan                                                         #
# --------------------------------------------------------------------------- #
@check("context.produces_a_budgeted_plan", stage="1 intent+plan",
       proves="an objective becomes a budgeted, receipted context plan")
def _context(sb: Sandbox) -> Result:
    rc, out = sb.cli("context", "wire the compaction module into a real caller",
                     "--repo-root", str(sb.repo), "--json", timeout=1800)
    payload = _json_tail(out)
    if rc != 0 or payload is None:
        return Result("context.produces_a_budgeted_plan", FAIL,
                      f"rc={rc}; no JSON plan: {out[-300:]!r}", {"returncode": rc})
    plan = (payload.get("dss") or {}).get("context_plan") or {}
    receipt = (payload.get("dss") or {}).get("receipt") or {}
    selected, budget, used = plan.get("selected") or [], plan.get("token_budget"), plan.get("tokens_used")
    problems = []
    if not selected:
        problems.append("the planner selected NO files -- the context layer sees nothing")
    if not receipt.get("receipt_sha256"):
        problems.append("no provenance receipt on the plan")
    if isinstance(used, int) and isinstance(budget, int) and used > budget:
        problems.append(f"plan is OVER budget: {used} > {budget}")
    return Result("context.produces_a_budgeted_plan",
                  PASS if not problems else FAIL, "; ".join(problems),
                  {"selected": len(selected), "token_budget": budget,
                   "tokens_used": used, "has_receipt": bool(receipt.get("receipt_sha256"))})


@check("offload.plans_without_mutating", stage="1 intent+plan",
       proves="a plan-only offload decides and changes NOTHING on disk")
def _offload_plan(sb: Sandbox) -> Result:
    before = sb.worktree_fingerprint()
    rc, out = sb.cli("offload", "add a docstring to daedalus/compaction.py",
                     "--repo-root", str(sb.repo), timeout=1800)
    after = sb.worktree_fingerprint()
    decision = _json_tail(out)
    if rc != 0 or decision is None:
        return Result("offload.plans_without_mutating", FAIL,
                      f"rc={rc}; no decision: {out[-300:]!r}", {"returncode": rc})
    problems = []
    if after[0] != before[0]:
        problems.append(f"HEAD MOVED: {before[0][:12]} -> {after[0][:12]}")
    if after[1] != before[1]:
        problems.append(f"status changed: {sorted(after[1] ^ before[1])[:6]}")
    if after[2] != before[2]:
        problems.append("TRACKED FILE CONTENT CHANGED during a plan-only run")
    if not decision.get("provider") or not decision.get("action"):
        problems.append("the plan carries no routing decision")
    return Result("offload.plans_without_mutating",
                  PASS if not problems else FAIL, "; ".join(problems),
                  {"provider": decision.get("provider"),
                   "action": decision.get("action"),
                   "worktree_identical": after == before})


# --------------------------------------------------------------------------- #
# 2 -- the generated map                                                       #
# --------------------------------------------------------------------------- #
@check("map.drift_gate_is_green", stage="2 map",
       proves="the generated architecture map still describes this tree")
def _map_check(sb: Sandbox) -> Result:
    rc, out = sb.cli("map", "--check", timeout=1800)
    # THE GATE'S OWN VERDICT IS ITS EXIT CODE. The first version of this check
    # grepped for the string "no drift" and reported FAIL on a run that exited 0
    # and printed "Nothing blocking" -- a harness inventing a failure the tool
    # did not report.
    ok = rc == 0
    return Result("map.drift_gate_is_green", PASS if ok else FAIL,
                  "" if ok else f"drift gate exited {rc}: {out[-400:]!r}",
                  {"returncode": rc, "counts": _grep(out, "now:")})


# --------------------------------------------------------------------------- #
# 3 -- the picker                                                              #
# --------------------------------------------------------------------------- #
@check("picker.ranks_with_evidence", stage="3 pick",
       proves="every queued candidate carries measured evidence, never opinion")
def _picker_evidence(sb: Sandbox) -> Result:
    # STEP ZERO, HERE TOO. The picker's sources are derived artefacts stamped
    # with the revision they describe, so EVERY commit makes them stale -- and
    # this harness clones at HEAD. The consequence, measured across three runs
    # tonight: the live picker had 10 candidates while this check reported "the
    # queue is EMPTY -- the loop has nothing to work on" and dragged two core
    # checks to INCOMPLETE behind it. The only way it could have passed was if
    # the map happened to be regenerated in the very last commit.
    #
    # That is not a property of the product, it is an artefact of when the
    # snapshot was taken, so the harness regenerates first for the same reason
    # `spine/bootstrap.py::refresh_sources` does: a loop that must be
    # hand-reseeded after every success is not a loop, and a harness that only
    # passes on a freshly-seeded tree is measuring the seeding.
    #
    # Regeneration FAILING is reported rather than swallowed -- if `map` cannot
    # run, an empty queue afterwards says nothing about the picker.
    gen_rc, gen_out = sb.py("-m", "daedalus.cli", "map", timeout=1800)
    if gen_rc != 0:
        return Result("picker.ranks_with_evidence", UNAVAILABLE,
                      f"the sources could not be regenerated (rc={gen_rc}), so "
                      f"an empty queue would say nothing about the picker: "
                      f"{gen_out[-300:]!r}", {"returncode": gen_rc})

    rc, out = sb.py("-m", "daedalus.spine.picker", "--dry-run", "--json",
                    "--limit", "10", timeout=1800)
    queue = _json_tail(out)
    if queue is None:
        return Result("picker.ranks_with_evidence", FAIL,
                      f"rc={rc}; no JSON queue", {"returncode": rc})
    cands = queue.get("candidates") or []
    if not cands:
        return Result("picker.ranks_with_evidence", FAIL,
                      "the queue is EMPTY AFTER a successful regeneration -- "
                      "the loop has nothing to work on",
                      {"degraded_sources": queue.get("degraded_sources")})
    naked = [c["task_id"] for c in cands
             if not c.get("evidence") or not str(c.get("reason") or "").strip()]
    return Result("picker.ranks_with_evidence", PASS if not naked else FAIL,
                  "" if not naked else f"candidates without evidence: {naked}",
                  {"candidates": len(cands),
                   "sources": sorted({c["source"] for c in cands}),
                   "degraded_sources": queue.get("degraded_sources"),
                   "top": cands[0]["task_id"]})


@check("picker.exit_code_distinguishes_degraded", stage="3 pick",
       proves="'a source failed' never reads as 'there is no work'")
def _picker_exit(sb: Sandbox) -> Result:
    rc, out = sb.py("-m", "daedalus.spine.picker", "--dry-run", "--json",
                    "--limit", "5", timeout=1800)
    queue = _json_tail(out)
    if queue is None:
        return Result("picker.exit_code_distinguishes_degraded", FAIL,
                      "could not read the queue", {"returncode": rc})
    degraded = queue.get("degraded_sources") or []
    expected = 3 if degraded else 0
    return Result("picker.exit_code_distinguishes_degraded",
                  PASS if rc == expected else FAIL,
                  "" if rc == expected else
                  f"degraded={degraded} but exit was {rc}, expected {expected}",
                  {"returncode": rc, "degraded_sources": degraded})


# --------------------------------------------------------------------------- #
# 4 -- the attempt                                                             #
# --------------------------------------------------------------------------- #
@check("spine.intent_is_recorded_BEFORE_the_effect", stage="4 attempt",
       proves="the ledger row exists while the runner is still executing")
def _intent_before_effect(sb: Sandbox) -> Result:
    """Reads the DB from INSIDE the runner, at the real effect boundary.

    Checking afterwards proves only that a row exists, not that it existed
    first -- which is the entire claim of an intent-before-effect ledger. The
    runner below is called by TaskAttempt at exactly the moment the worktree
    exists and the work is about to happen, so what it can see is what a crash
    at that instant would have left behind.
    """
    probe = sb.tmp / "intent_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "sys.path.insert(0, os.environ['ACC_TOOLS'])\n"
        "from system_check import read_intents\n"
        "from daedalus.spine.attempt import TaskSpec, TaskAttempt\n"
        "from pathlib import Path\n"
        "seen = {}\n"
        "def runner(ctx):\n"
        "    seen['during'] = read_intents(Path(os.environ['DAEDALUS_SPINE_DB']))\n"
        "    seen['worktree_exists'] = Path(ctx.worktree).is_dir()\n"
        "    (Path(ctx.worktree) / 'acceptance.txt').write_text('x', encoding='utf-8')\n"
        "def gate(ctx):\n"
        "    return True\n"
        "spec = TaskSpec(task_id='acceptance-intent-probe',\n"
        "                instruction='write one file so a patch exists')\n"
        "res = TaskAttempt(spec, runner=runner, gate=gate,\n"
        "                  repo_root=os.environ['ACC_REPO']).run()\n"
        "print(json.dumps({'state': res.state,\n"
        "                  'during': [[r[0], r[2]] for r in seen.get('during', [])],\n"
        "                  'worktree_existed': seen.get('worktree_exists'),\n"
        "                  'after': [[r[0], r[2]] for r in read_intents(Path(os.environ['DAEDALUS_SPINE_DB']))],\n"
        "                  'reaped': [r.get('action') for r in (res.reaped or ())]}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(probe), timeout=1800,
                    env={"ACC_REPO": str(sb.repo),
                         "ACC_TOOLS": str(Path(__file__).resolve().parent)})
    got = _json_tail(out)
    if got is None:
        return Result("spine.intent_is_recorded_BEFORE_the_effect", FAIL,
                      f"probe did not report: {out[-400:]!r}", {"returncode": rc})
    during = got.get("during") or []
    problems = []
    if not during:
        problems.append("NO intent existed while the runner was executing -- "
                        "a crash there would have left an effect nobody intended")
    elif not any(state == "INTENDED" for _, state in during):
        problems.append(f"the intent was not OPEN during the effect: {during}")
    if not got.get("worktree_existed"):
        problems.append("the runner did not receive a real worktree")
    return Result("spine.intent_is_recorded_BEFORE_the_effect",
                  PASS if not problems else FAIL, "; ".join(problems), got)


@check("spine.attempt_leaves_the_primary_untouched", stage="4 attempt",
       proves="a real attempt mutates nothing outside its own worktree, "
              "and leaves no branch behind")
def _attempt_isolation(sb: Sandbox) -> Result:
    before_fp = sb.worktree_fingerprint()
    before_branches = sb.attempt_branches()
    rc, out = sb.py("-m", "daedalus.spine.picker", "--once", "--limit", "3",
                    timeout=2400)
    after_fp = sb.worktree_fingerprint()
    leaked = sorted(set(sb.attempt_branches()) - set(before_branches))

    if rc == 3:
        return Result("spine.attempt_leaves_the_primary_untouched", UNAVAILABLE,
                      "no candidate to attempt (sources degraded)",
                      {"returncode": rc})
    if rc in (124, 127) or rc not in (0, 2):
        return Result("spine.attempt_leaves_the_primary_untouched", FAIL,
                      f"the attempt run exited {rc}: {out[-300:]!r}",
                      {"returncode": rc})
    problems = []
    if after_fp[0] != before_fp[0]:
        problems.append(f"HEAD MOVED: {before_fp[0][:12]} -> {after_fp[0][:12]}")
    if after_fp[2] != before_fp[2]:
        problems.append("TRACKED FILE CONTENT CHANGED in the primary checkout")
    if leaked:
        problems.append(f"leaked candidate branches: {leaked}")
    return Result("spine.attempt_leaves_the_primary_untouched",
                  PASS if not problems else FAIL, "; ".join(problems),
                  {"returncode": rc, "leaked_branches": leaked,
                   "head_unchanged": after_fp[0] == before_fp[0],
                   "content_unchanged": after_fp[2] == before_fp[2],
                   "intents": [[r[0], r[2]] for r in sb.intents()]})


@check("spine.circle_closes", stage="5 digestion",
       proves="THE SPRUNG: an attempt changes what the picker chooses next")
def _circle(sb: Sandbox) -> Result:
    def queue(limit):
        rc, out = sb.py("-m", "daedalus.spine.picker", "--dry-run", "--json",
                        "--limit", str(limit), timeout=1800)
        return rc, _json_tail(out)

    rc0, before = queue(0)          # 0 == no limit in this CLI? use a big one
    rc0, before = queue(500)
    if before is None:
        return Result("spine.circle_closes", FAIL, "could not read the cold queue",
                      {"returncode": rc0})
    cands = before.get("candidates") or []
    if not cands:
        return Result("spine.circle_closes", UNAVAILABLE,
                      "no candidates, so there is no next pick to change",
                      {"degraded_sources": before.get("degraded_sources")})
    top_before = cands[0]["task_id"]
    cold_len = len(cands)

    rc1, out1 = sb.py("-m", "daedalus.spine.picker", "--once", "--limit", "3",
                      timeout=2400)
    if rc1 == 3:
        return Result("spine.circle_closes", UNAVAILABLE,
                      "the attempt did not run", {"returncode": rc1})
    if rc1 not in (0, 2):
        # A crash or timeout is NOT an acceptable way to reach the second half.
        return Result("spine.circle_closes", FAIL,
                      f"the attempt exited {rc1}: {out1[-300:]!r}",
                      {"returncode": rc1})

    rc2, after = queue(500)
    if after is None:
        return Result("spine.circle_closes", FAIL, "could not read the warm queue",
                      {"returncode": rc2})
    after_ids = [c["task_id"] for c in after.get("candidates") or []]
    remembered = next((c for c in (after.get("candidates") or [])
                       if c["task_id"] == top_before), None)

    problems = []
    if after_ids and after_ids[0] == top_before:
        problems.append(f"the picker chose {top_before!r} AGAIN after attempting "
                        f"it -- the loop is spinning in place")
    # "still present" is only meaningful over the WHOLE queue; a limited view
    # cannot tell rank 11 from removed.
    if top_before not in after_ids:
        problems.append("the attempted candidate VANISHED from the full queue "
                        "(memory must be a penalty, never a filter)")
    if not (remembered or {}).get("evidence", {}).get("prior_attempts"):
        problems.append("no prior_attempts evidence on the attempted candidate")
    return Result("spine.circle_closes", PASS if not problems else FAIL,
                  "; ".join(problems),
                  {"top_before": top_before,
                   "top_after": after_ids[0] if after_ids else None,
                   "rank_after": (after_ids.index(top_before) + 1)
                                 if top_before in after_ids else None,
                   "cold_len": cold_len, "warm_len": len(after_ids),
                   "prior_attempts": (remembered or {}).get("evidence", {}).get("prior_attempts")})


# --------------------------------------------------------------------------- #
# 6 -- eval and web                                                            #
# --------------------------------------------------------------------------- #
@check("eval.replays_a_task_and_scores_it", stage="6 eval",
       proves="the measurement harness actually measures, on one real task")
def _eval(sb: Sandbox) -> Result:
    probe = sb.tmp / "eval_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "from daedalus.eval import harness\n"
        "tasks = [t for t in harness.all_tasks() if t.get('repo') == 'agent_env'][:1]\n"
        "if not tasks:\n"
        "    print(json.dumps({'skip': 'no agent_env task in the corpus'}))\n"
        "else:\n"
        "    row = harness.eval_task_tier1(tasks[0])\n"
        "    print(json.dumps({'task': tasks[0].get('id') or tasks[0].get('target'),\n"
        "                      'recall': row.get('recall'), 'error': row.get('error'),\n"
        "                      'withheld': row.get('focus_withheld')\n"
        "                                  or row.get('withheld_reason'),\n"
        "                      'keys': sorted(row)[:8]}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(probe), timeout=1800, env={"ACC_REPO": str(sb.repo)})
    got = _json_tail(out)
    if got is None:
        return Result("eval.replays_a_task_and_scores_it", FAIL,
                      f"probe did not report: {out[-400:]!r}", {"returncode": rc})
    if got.get("skip"):
        return Result("eval.replays_a_task_and_scores_it", UNAVAILABLE,
                      got["skip"], got)
    if got.get("error"):
        return Result("eval.replays_a_task_and_scores_it", FAIL,
                      f"the task errored: {got['error']}", got)
    recall = got.get("recall")
    if isinstance(recall, (int, float)):
        return Result("eval.replays_a_task_and_scores_it", PASS, "", got)
    # "THE SECRET FLOOR WITHHELD THE FOCUS FILE" AND "THE HARNESS IS BROKEN"
    # ARE DIFFERENT FACTS, and this check used to report both as FAIL.
    #
    # Measured: `daedalus/web_api.py` trips the floor on the single line
    # `AUTH_TOKEN_ENV = "DAEDALUS_WEB_TOKEN"` -- a credential-assignment shape
    # whose value is the NAME of an environment variable. A false positive, in
    # the safe direction, and the floor stays: weakening a security pattern to
    # make a measurement convenient is the trade this project refuses.
    #
    # But the consequence is that the task cannot be scored, and calling that a
    # broken harness sends the next person to debug the eval instead of reading
    # the withholding notice the eval already prints. UNAVAILABLE is the honest
    # state -- the property was not checked, and it is NOT counted as working.
    if got.get("withheld"):
        return Result("eval.replays_a_task_and_scores_it", UNAVAILABLE,
                      f"the focus file was withheld by the secret floor "
                      f"({got['withheld']}), so this task cannot be scored -- "
                      f"the harness was not exercised, which is not the same "
                      f"as broken", got)
    return Result("eval.replays_a_task_and_scores_it", FAIL,
                  "the replay produced no recall number and gave no reason", got)


@check("web.serves_and_terminates", stage="6 web",
       proves="the local Agent OS API starts on a free port, answers, and dies")
def _web(sb: Sandbox) -> Result:
    port = _free_port()
    env = {**sb.env, "PYTHONIOENCODING": "utf-8"}
    proc = None
    try:
        proc = subprocess.Popen(
            [PY, "-m", "daedalus.cli", "web", "--port", str(port)],
            cwd=str(sb.repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", env={**os.environ, **env})
        import urllib.error
        import urllib.request
        deadline, last = time.time() + 45, ""
        answered = False
        while time.time() < deadline:
            if proc.poll() is not None:
                last = "the server exited before answering"
                break
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=3) as r:
                    r.read(256)
                    answered = True
                    break
            except (urllib.error.URLError, OSError) as e:
                last = str(e)
                time.sleep(0.5)
        if not answered:
            return Result("web.serves_and_terminates", FAIL,
                          f"no answer within the readiness deadline: {last}",
                          {"port": port})
        return Result("web.serves_and_terminates", PASS, "", {"port": port})
    except Exception as e:
        return Result("web.serves_and_terminates", FAIL,
                      f"could not start the server: {type(e).__name__}: {e}", {})
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=20)
            except Exception:
                pass


@check("gui.a_human_can_operate_the_cockpit", stage="6 web",
       proves="the BUILT webapp loads in a REAL BROWSER against the real server, "
              "its three spaces are reachable, the health states are "
              "distinguishable, and a degraded source is VISIBLE rather than "
              "rendering as 'no work'")
def _gui(sb: Sandbox) -> Result:
    """Drives the cockpit with Playwright. See ``tools/gui_check.py``.

    WHY THIS IS NOT COVERED BY ``web.serves_and_terminates``. That check proves
    the SERVER answers. A server that answers 200 on every route is
    indistinguishable, from outside, from one whose bundle throws on module
    evaluation and hands the user a white screen -- and the whole reason this
    file exists is that a suite which cannot see that difference goes green over
    it.

    THE INSTRUMENT COMES FROM THE WORKING TREE, THE SPECIMEN IS THE CLONE.
    ``node_modules`` is gitignored, so the disposable clone carries no
    Playwright and no browser. The specs and the browser therefore live in
    ``apps/web`` HERE, while the server being driven is started from the clone.

    UNAVAILABLE, NOT PASS, when the browser or the built bundle is missing --
    ``gui_check.py`` owns that distinction and reports it as its own exit code.
    """
    gui = Path(__file__).resolve().parent / "gui_check.py"
    if not gui.exists():
        return Result("gui.a_human_can_operate_the_cockpit", UNAVAILABLE,
                      "tools/gui_check.py is not present", {})
    rc, out = sb.py(str(gui), "--repo-root", str(sb.repo),
                    "--web-root", str(ROOT / "apps" / "web"), "--json",
                    timeout=1800)
    payload = _json_tail(out)
    if payload is None:
        return Result("gui.a_human_can_operate_the_cockpit", FAIL,
                      f"the GUI check produced no receipt (rc={rc}): {out[-400:]!r}",
                      {"returncode": rc})
    ev = payload.get("evidence") or {}
    evidence = {k: ev.get(k) for k in
                ("server_entry", "specs", "passed", "failed", "skipped",
                 "documented_entry_error", "browser") if k in ev}
    outcome = {"PASS": PASS, "INCOMPLETE": UNAVAILABLE}.get(payload.get("outcome"), FAIL)
    return Result("gui.a_human_can_operate_the_cockpit", outcome,
                  payload.get("detail") or "", evidence)


@check("bridge.enqueue_watch_report_archive", stage="6 bridge",
       proves="a queued task is picked up by the REAL watcher, answered into "
              "the inbox, and the request archived -- exactly once")
def _file_bridge(sb: Sandbox) -> Result:
    """The one loop in the product that is a loop: enqueue → watch → report →
    archive.

    Hermetic on purpose: the request uses ``strategy="configure"``, which
    ``process_bridge_payload`` answers itself without routing to any model. That
    keeps this a test of the BRIDGE -- the queue, the watcher, the report file,
    the archive move -- instead of a test of whichever provider happened to be
    reachable.

    Also checks the property a queue must have and a smoke test would miss:
    processing is EXACTLY ONCE. Two identical requests must produce two reports
    and leave nothing in the outbox, and a second watcher pass must not
    re-process what it already archived.
    """
    enq = sb.tmp / "bridge_enqueue.py"
    enq.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "from daedalus import file_bridge as fb\n"
        "paths = []\n"
        "for i in range(2):\n"
        "    p = fb.enqueue('acceptance configure probe', os.environ['ACC_REPO'],\n"
        "                   [], strategy='configure', source='acceptance')\n"
        "    paths.append(p.name)\n"
        "print(json.dumps({'queued': paths, 'outbox': str(fb.OUTBOX),\n"
        "                  'inbox': str(fb.INBOX), 'archive': str(fb.ARCHIVE)}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(enq), timeout=600, env={"ACC_REPO": str(sb.repo)})
    info = _json_tail(out)
    if info is None:
        return Result("bridge.enqueue_watch_report_archive", FAIL,
                      f"could not enqueue: {out[-300:]!r}", {"returncode": rc})

    outbox, inbox, archive = (Path(info["outbox"]), Path(info["inbox"]),
                              Path(info["archive"]))
    queued = info["queued"]

    proc = None
    try:
        proc = subprocess.Popen(
            [PY, "-m", "daedalus.file_bridge", "watch", "--interval-s", "0.3",
             "--repo-root", str(sb.repo)],
            cwd=str(sb.repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
            env={**os.environ, **sb.env, "PYTHONIOENCODING": "utf-8"})
        deadline = time.time() + 90
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            done = [n for n in queued if (archive / n).exists()]
            if len(done) == len(queued):
                break
            time.sleep(0.4)
    except Exception as e:
        return Result("bridge.enqueue_watch_report_archive", FAIL,
                      f"the watcher could not start: {type(e).__name__}: {e}", {})
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=20)
            except Exception:
                pass

    archived = sorted(p.name for p in archive.glob("*.json")) if archive.is_dir() else []
    reports = sorted(p.name for p in inbox.glob("*.report.json")) if inbox.is_dir() else []
    left = sorted(p.name for p in outbox.glob("*.json")) if outbox.is_dir() else []

    problems = []
    missing = [n for n in queued if n not in archived]
    if missing:
        problems.append(f"request(s) never archived: {missing}")
    if left:
        problems.append(f"outbox not drained: {left}")
    expected_reports = {Path(n).stem + ".report.json" for n in queued}
    absent = sorted(expected_reports - set(reports))
    if absent:
        problems.append(f"no report written for: {absent}")
    # EXACTLY ONCE: two requests, two reports -- never one, never three.
    if len(reports) != len(queued):
        problems.append(f"{len(queued)} requests produced {len(reports)} reports")

    return Result("bridge.enqueue_watch_report_archive",
                  PASS if not problems else FAIL, "; ".join(problems),
                  {"queued": len(queued), "archived": len(archived),
                   "reports": len(reports), "outbox_left": left})


# --------------------------------------------------------------------------- #
# 7 -- safety                                                                  #
# --------------------------------------------------------------------------- #
@check("safety.remote_ollama_is_refused", stage="7 safety",
       proves="repository content is never sent to an OLLAMA_HOST that is not this machine")
def _egress(sb: Sandbox) -> Result:
    probe = sb.tmp / "egress_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "from daedalus.providers.ollama import OllamaProvider\n"
        "p = OllamaProvider()\n"
        "r = p.run(objective='x', repo_root=os.environ['ACC_REPO'],\n"
        "          paths=['README.md'], agent={'name': 'generalist-dev'}, writable=True)\n"
        "print(json.dumps({'lane': p.egress_lane, 'ok': r.get('ok'),\n"
        "                  'refused': r.get('refused')}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(probe), timeout=600,
                    env={"ACC_REPO": str(sb.repo),
                         "OLLAMA_HOST": "http://100.119.126.9:11434"})
    got = _json_tail(out)
    if got is None:
        return Result("safety.remote_ollama_is_refused", FAIL,
                      f"probe did not report: {out[-300:]!r}", {})
    ok = (got.get("lane") == "untrusted" and got.get("ok") is False
          and got.get("refused") == "remote_ollama_endpoint")
    return Result("safety.remote_ollama_is_refused", PASS if ok else FAIL,
                  "" if ok else "a REMOTE ollama endpoint was NOT refused", got)


@check("safety.picker_cannot_apply", stage="7 safety",
       proves="the module that ranks work offers no promotion flag and spawns nothing")
def _no_apply(sb: Sandbox) -> Result:
    probe = sb.tmp / "apply_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "from daedalus.spine.picker import _build_parser\n"
        "print(json.dumps({'flags': sorted(_build_parser()._option_string_actions)}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(probe), timeout=600, env={"ACC_REPO": str(sb.repo)})
    got = _json_tail(out)
    if got is None:
        return Result("safety.picker_cannot_apply", FAIL,
                      f"probe failed: {out[-300:]!r}", {})
    # THE PARSER, not the help TEXT. The first version grepped --help output and
    # matched the epilog sentence "There is no --apply flag", i.e. it read the
    # denial of the flag as evidence the flag existed.
    offered = [f for f in ("--apply", "--promote", "--merge", "--commit", "--push")
               if f in got["flags"]]
    src = (sb.repo / "daedalus" / "spine" / "picker.py").read_text(encoding="utf-8")
    spawns = [t for t in ("subprocess", "os.system") if t in src]
    problems = []
    if offered:
        problems.append(f"promotion flags offered: {offered}")
    if spawns:
        problems.append(f"process-spawning surface present: {spawns}")
    return Result("safety.picker_cannot_apply", PASS if not problems else FAIL,
                  "; ".join(problems), {"flags": got["flags"], "spawns": spawns})


@check("safety.room_prompt_gates_by_speaker", stage="7 safety",
       proves="an EXTERNAL speaker's assembled prompt carries no un-gated source")
def _room_lane(sb: Sandbox) -> Result:
    """Drives build_prompt, not the predicate.

    The first version called ``_speaker_lane`` and asserted the answer, which is
    the same mistake the unit tests made: both halves can be perfect while the
    wiring between them passes a hardcoded lane. What matters is the prompt a
    vendor actually receives.
    """
    room = sb.repo / "runs" / "council" / "room.py"
    if not room.exists():
        return Result("safety.room_prompt_gates_by_speaker", UNAVAILABLE,
                      "runs/council/room.py not present", {})
    probe = sb.tmp / "room_probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['ACC_REPO'])\n"
        "sys.path.insert(0, os.path.join(os.environ['ACC_REPO'], 'runs', 'council'))\n"
        "import room\n"
        "target = 'daedalus/sensitivity.py'\n"
        "ext, _, _ = room.build_prompt('codex', extra='review', attach=[target])\n"
        "tru, _, _ = room.build_prompt('claude', extra='review', attach=[target])\n"
        "needle = 'def lane_for_host'\n"
        "print(json.dumps({'external_has_source': needle in ext,\n"
        "                  'trusted_has_source': needle in tru,\n"
        "                  'external_says_withheld': 'WITHHELD' in ext}))\n",
        encoding="utf-8")
    rc, out = sb.py(str(probe), timeout=900, env={"ACC_REPO": str(sb.repo)})
    got = _json_tail(out)
    if got is None:
        return Result("safety.room_prompt_gates_by_speaker", FAIL,
                      f"probe failed: {out[-400:]!r}", {"returncode": rc})
    problems = []
    if got.get("external_has_source"):
        problems.append("SOURCE REACHED AN EXTERNAL SPEAKER'S PROMPT")
    if not got.get("external_says_withheld"):
        problems.append("the external prompt does not name what was withheld")
    if not got.get("trusted_has_source"):
        problems.append("the trusted speaker lost its distilled view "
                        "(gate is over-withholding, the room is now useless)")
    return Result("safety.room_prompt_gates_by_speaker",
                  PASS if not problems else FAIL, "; ".join(problems), got)


@check("safety.bus_chain_detects_a_break", stage="7 safety",
       proves="the hash-chained transcript VERIFIES when intact and NAMES a break "
              "when tampered with")
def _bus(sb: Sandbox) -> Result:
    """Both halves, because only the pair is a control.

    A verifier that always says OK passes an intact-chain test. A verifier that
    always fails passes a tamper test. Only checking both proves it discriminates.
    """
    room = sb.repo / "runs" / "council" / "room.py"
    chain = sb.repo / "runs" / "council" / "room.jsonl"
    if not room.exists():
        return Result("safety.bus_chain_detects_a_break", UNAVAILABLE,
                      "runs/council/room.py not present", {})

    # BUILD OUR OWN CHAIN rather than requiring one to be lying around.
    # `runs/council/*.jsonl` is gitignored, so a clone never has one and this
    # core check reported UNAVAILABLE forever -- a property that can never be
    # checked is indistinguishable from one that does not hold. Two real turns
    # through the real `say` path give the verifier something to verify.
    if not chain.exists() or not chain.read_text(encoding="utf-8").strip():
        seed = sb.tmp / "seed_turn.txt"
        seed.write_text("acceptance seed turn\n", encoding="utf-8")
        for who in ("kaya", "claude"):
            rc_say, out_say = sb.py(str(room), "say", who, str(seed), timeout=600)
            if rc_say != 0:
                return Result("safety.bus_chain_detects_a_break", FAIL,
                              f"could not append a turn through `say`: "
                              f"rc={rc_say} {out_say[-200:]!r}", {})
    if not chain.exists() or not chain.read_text(encoding="utf-8").strip():
        return Result("safety.bus_chain_detects_a_break", FAIL,
                      "two turns were appended but NOTHING was mirrored into "
                      "the chain -- the tamper-evidence is not being written",
                      {})

    rc_intact, out_intact = sb.py(str(room), "verify", timeout=600)

    original = chain.read_bytes()
    try:
        lines = original.decode("utf-8", "replace").splitlines()
        if lines:
            try:
                rec = json.loads(lines[-1])
                rec["body"] = (rec.get("body") or "") + "  TAMPERED"
                lines[-1] = json.dumps(rec)
            except (ValueError, json.JSONDecodeError):
                lines[-1] = lines[-1] + " "
            chain.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc_broken, out_broken = sb.py(str(room), "verify", timeout=600)
    finally:
        chain.write_bytes(original)

    problems = []
    if rc_intact != 0:
        problems.append(f"an untouched chain did not verify (rc={rc_intact}): "
                        f"{_grep(out_intact, 'VERIFY')}")
    if rc_broken == 0:
        problems.append("a TAMPERED chain still verified -- the mirror is not "
                        "tamper-evident")
    return Result("safety.bus_chain_detects_a_break",
                  PASS if not problems else FAIL, "; ".join(problems),
                  {"intact_rc": rc_intact, "tampered_rc": rc_broken,
                   "intact_verdict": _grep(out_intact, "chain"),
                   "tampered_verdict": _grep(out_broken, "-")})


def _grep(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return ""


# --------------------------------------------------------------------------- #
# the run                                                                      #
# --------------------------------------------------------------------------- #
def acceptance_run(only=None, sandbox: Sandbox | None = None) -> list:
    own = sandbox is None
    sb = sandbox or Sandbox()
    results = []
    try:
        if own:
            print("  building a disposable clone of the working tree ...")
            if not sb.build():
                return [Result("sandbox.build", FAIL, sb.error)]
            print(f"  clone: {sb.repo}\n")
        for spec in CHECKS:
            if only and only not in spec["name"]:
                continue
            t0 = time.time()
            try:
                res = spec["fn"](sb)
            except Exception as e:
                res = Result(spec["name"], FAIL,
                             f"the check itself raised: {type(e).__name__}: {e}")
            res.stage, res.proves, res.core = spec["stage"], spec["proves"], spec["core"]
            res.seconds = time.time() - t0
            results.append(res)
            mark = {PASS: "ok  ", FAIL: "FAIL", UNAVAILABLE: "n/a "}[res.outcome]
            tag = "" if res.core else "  (optional)"
            print(f"  [{mark}] {res.name:48s} {res.seconds:6.1f}s{tag}")
            if res.detail:
                print(f"         {res.detail}")
    finally:
        if own:
            sb.destroy()
    return results


def verdict(results: list) -> int:
    failed = [r for r in results if r.outcome == FAIL]
    blocked = [r for r in results if r.outcome == UNAVAILABLE and r.core]
    if failed:
        return EXIT_FAILED
    if blocked:
        return EXIT_INCOMPLETE
    return EXIT_OK


def report(results: list) -> int:
    npass = sum(1 for r in results if r.outcome == PASS)
    failed = [r for r in results if r.outcome == FAIL]
    blocked = [r for r in results if r.outcome == UNAVAILABLE and r.core]
    optional_na = [r for r in results if r.outcome == UNAVAILABLE and not r.core]
    code = verdict(results)

    print(f"\n{'=' * 70}")
    print(f"{npass} pass / {len(failed)} FAIL / "
          f"{len(blocked) + len(optional_na)} unavailable  of {len(results)} checks")
    if failed:
        print("\nFAILED -- the system does not do what it says here:")
        for r in failed:
            print(f"  * {r.name}: {r.detail}")
            print(f"      (proves: {r.proves})")
    if blocked:
        print("\nINCOMPLETE -- a CORE property could NOT be checked, so this run")
        print("proves nothing about it. Not counted as working:")
        for r in blocked:
            print(f"  * {r.name}: {r.detail}")
    if optional_na:
        print("\nunavailable (optional):")
        for r in optional_na:
            print(f"  * {r.name}: {r.detail}")
    print(f"\nVERDICT: " + {
        EXIT_OK: "PASS -- every core property held on this machine",
        EXIT_FAILED: "FAIL -- at least one property does not hold",
        EXIT_INCOMPLETE: "INCOMPLETE -- a core property could not be checked",
    }[code] + f"  (exit {code})")
    print("=" * 70)
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="substring filter on check name")
    ap.add_argument("--self-test", action="store_true",
                    help="break things in the clone and prove the checks go RED")
    args = ap.parse_args(argv)

    if args.self_test:
        from self_test import run_self_test  # noqa: E402  (tools/ is on sys.path)
        return run_self_test(only=args.only)

    print(f"daedalus acceptance -- {len(CHECKS)} checks over the real paths")
    print(f"repo: {ROOT}\n")
    results = acceptance_run(args.only)
    if args.json:
        print(json.dumps({"results": [r.to_dict() for r in results],
                          "verdict": verdict(results)}, indent=2))
        return verdict(results)
    return report(results)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
