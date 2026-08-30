# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""tools/watchdog.py -- background docs, work, and advisory-fleet watchdogs.

Owner order 2026-08-22/23: a docs agent is always active, and a general work
watchdog runs in the background, independent of any open Claude session.

    python tools/watchdog.py docs          one docs pass (mechanical first, model only on drift)
    python tools/watchdog.py work          one health pass (mechanical; model report when HEAD moved)
    python tools/watchdog.py install       register both as Windows scheduled tasks (user, no admin)
    python tools/watchdog.py uninstall     remove the tasks
    python tools/watchdog.py status        tasks, last runs, last anomalies
    python tools/watchdog.py fleet         idle-gated, one-shot advisory fleet pass
    python tools/watchdog.py fleet-install register the robust 20-minute fleet task
    python tools/watchdog.py fleet-status  task contract plus campaign state
    python tools/watchdog.py fleet-uninstall remove only the fleet task
    --config PATH                          explicit fleet campaign JSON
    --dry-run                              never spawn the model, never commit

MECHANICAL FIRST, MODEL ON EVIDENCE. A background loop that calls a model on a
timer burns money on quiet afternoons. Each pass first measures, in Python:

  docs: is the architecture memory stale? does docs/architecture-state.json
        name HEAD? do top-level docs mention files deleted in the last 30
        commits without a "(replaced by ...)" / "(archived: ...)" mark? do they
        carry relative links to paths that do not exist?
  work: HEAD and its age, dirty source files and the oldest one's age, a stale
        .git/index.lock, the age of the last docs sweep, hook-ledger activity
        (is any session alive?), the declared shift, the last recorded test run,
        disk free, the size of %TEMP%/claude.

Only a docs pass WITH findings spawns `claude -p` (haiku) with the findings
listed in the prompt, so the model fixes rather than searches. A work pass
spawns the model only for the periodic report, and only when HEAD moved since
the last one. Every spawn goes through ``budget.guard`` -- one reservation,
one settlement at the MEASURED cost, and no second billing from the process
guard.

NO SELF-IMPOSED SPENDING LIMIT (owner decision 2026-08-24), and it still never
touches the ceiling every other lane shares. The watchdog reserves against its
OWN ledger (``runs/watchdog/ledger.json``), not ``runs/budget/ledger.json``,
with a ceiling high enough to never bind. Two prior designs were both wrong in
opposite directions: raising ``DAEDALUS_BUDGET_USD`` for the watchdog process
raised the ceiling every lane shares and let it starve the others (MEASURED
2026-08-24: $9.74 spent overnight, other lanes refused); a self-imposed daily
cap on the SHARED ledger meant the watchdog could itself be starved by other
lanes' spend. A dedicated ledger has neither failure mode: nothing here can be
blocked by, or block, anyone else's spend.

SHARED TREE, SHARED INDEX. Other lanes commit in this tree. The docs sweep
commits ONLY with a pathspec (``git commit -F msg -- <paths>``), never the
index, and a pass is skipped outright when ``.git/index.lock`` exists, when
HEAD moved in the last three minutes, or when another watchdog pass holds
the lock. ``.claude/watchdog/PAUSE`` (a file) or ``DAEDALUS_WATCHDOG=off``
pauses everything.

NEVER A GUARD. The watchdog reports and repairs docs; it blocks nothing and
enforces nothing on anyone's work (owner decision 2026-08-23: the workflow
is not to be constrained).

Effect boundary: registered as ``tools.watchdog`` (PROCESS_SPAWN,
FILESYSTEM_WRITE, NETWORK_EGRESS, SPEND, REPOSITORY_MUTATION); ``main`` starts
through ``begin_effect``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WATCHDOG_DIR_REL = ".claude/watchdog"
STATE_REL = "runs/watchdog/state.json"
HEALTH_JSON_REL = "runs/watchdog/health.json"
HEALTH_MD_REL = "runs/watchdog/HEALTH.md"
REPORT_MD_REL = "runs/watchdog/REPORT.md"
REPORTS_DIR_REL = "runs/watchdog/reports"
LOG_REL = "runs/watchdog/watchdog.log"
SWEEPS_LOG_REL = ".claude/watchdog/docs/sweeps.log"
PAUSE_REL = ".claude/watchdog/PAUSE"
FLEET_CONFIG_REL = ".claude/watchdog/opus-fleet.json"
#: ONE LOCK PER MODE. A single shared lock meant the docs pass -- which holds
#: it for as long as a model call takes -- skipped every work pass that ticked
#: while it ran, and on aligned 15/30-minute schedules that is every other one.
#: MEASURED in runs/watchdog/watchdog.log: "work skipped: another pass holds
#: ..." at :08 and :38, every half hour, all night. The lock exists so that two
#: passes of the SAME kind cannot overlap; nothing about a docs sweep requires
#: the health measurement to wait.
LOCK_REL_TEMPLATE = "runs/watchdog/.{mode}.lock"

DOCS_INTERVAL_MIN = 30
WORK_INTERVAL_MIN = 15
REPORT_MIN_GAP_S = 2 * 3600
MODEL = "claude-haiku-4-5"
MODEL_TIMEOUT_S = 15 * 60
#: The pruner. Owner decision 2026-08-25: Sonnet cleans and updates the docs on
#: every docs tick with no per-pass cap, no rotation limit, and no spend
#: ceiling. What stays is not a limit on the cleaning but the difference
#: between a docs cleaner and a repo-wide mutator: no push, pathspec commits
#: (other lanes stage in this tree), no history rewrite, and the constitution
#: below stays unreadable to it because AGENTS.md forbids editing it silently.
MODEL_PRUNE = "claude-sonnet-5"
PRUNE_TIMEOUT_S = 25 * 60
PRUNE_MAX_TURNS = 300
PRUNE_STATE_REL = "runs/watchdog/prune-state.json"
PRUNES_LOG_REL = "runs/watchdog/prunes.log"
PRUNE_RECEIPT_REL = "runs/watchdog/prune-receipt.json"
PRUNE_GLOBS = ("README.md", "docs/**/*.md")
PRUNE_FORBIDDEN = ("AGENTS.md", "CLAUDE.md")
PRUNE_FORBIDDEN_PREFIX = "docs/IKARUS_ARIADNE_MASTER_PLAN"
#: The watchdog's OWN ledger file -- never ``runs/budget/ledger.json``, the one
#: every interactive lane shares. Isolating the file is what makes "no
#: spending limit" safe to grant: a ceiling high enough to never bind on a
#: SHARED ledger would let the watchdog starve every other lane (measured
#: 2026-08-24, see the module docstring); on its own ledger the same ceiling
#: starves nobody.
WATCHDOG_LEDGER_REL = "runs/watchdog/ledger.json"
#: Not a real limit -- ``budget.Ledger`` requires a finite, positive ceiling
#: and call count (daedalus/budget.py's ``_num``: "must be finite", "never
#: zero"), so "no limit" is expressed as a number no realistic run reaches
#: rather than as an omitted check. At the measured ~$0.30-0.45 per sweep this
#: is effectively forever; nothing here refuses on cost or call count.
WATCHDOG_CEILING_USD = 1_000_000.0
WATCHDOG_MAX_CALLS = 1_000_000
#: Findings handed to one model run; the rest wait for the next pass.
MAX_DRIFTS_PER_PASS = 15
HEAD_QUIET_S = 180
LOG_MAX_BYTES = 512 * 1024
SOURCE_SCOPES = ("daedalus", "tools", "tests", "scripts")
DOC_FILES = ("README.md", "docs/*.md")
NL = chr(10)

# anomaly thresholds (work watchdog)
COMMIT_GAP_S = 3 * 3600
INDEX_LOCK_STALE_S = 10 * 60
DIRTY_SOURCE_STALE_S = 6 * 3600
SWEEP_STALE_S = 3 * 3600
TEST_STALE_S = 4 * 3600
DISK_FREE_MIN_GB = 10.0
TEMP_ENTRIES_MAX = 400
RENOTIFY_S = 3 * 3600


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------


def log(root: Path, line: str) -> None:
    try:
        p = root / LOG_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.stat().st_size > LOG_MAX_BYTES:
                os.replace(p, p.with_suffix(".log.1"))
        except OSError:
            pass
        with p.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + line + NL)
    except OSError:
        pass


def git(root: Path, *args: str, timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    # rstrip only: `git status --porcelain` lines START with a significant
    # space (" M path"), and a full strip() ate it on the first line.
    return proc.stdout.rstrip(chr(13) + chr(10)) if proc.returncode == 0 else ""


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def paused(root: Path, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    if (env.get("DAEDALUS_WATCHDOG") or "").lower() == "off":
        return "DAEDALUS_WATCHDOG=off"
    if (root / PAUSE_REL).exists():
        return f"{PAUSE_REL} exists"
    return ""


def head_quiet(root: Path, now: float | None = None) -> tuple[bool, str]:
    """False when HEAD moved within HEAD_QUIET_S or an index.lock exists:
    another lane is mid-commit, and a docs commit now would collide."""
    now = time.time() if now is None else now
    lock = root / ".git" / "index.lock"
    if lock.exists():
        return False, ".git/index.lock exists"
    ts = git(root, "log", "-1", "--format=%ct")
    try:
        age = now - int(ts)
    except ValueError:
        return True, "no commits"
    if age < HEAD_QUIET_S:
        return False, f"HEAD moved {int(age)} s ago"
    return True, ""


class PassLock:
    def __init__(self, root: Path, mode: str = "pass") -> None:
        self.path = root / LOCK_REL_TEMPLATE.format(mode=mode)
        self.fd: int | None = None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # the window has to cover the LONGEST pass that can hold this lock,
            # or a running prune (PRUNE_TIMEOUT_S) gets declared dead mid-flight
            # and a second pass starts on top of it
            if time.time() - self.path.stat().st_mtime > max(MODEL_TIMEOUT_S, PRUNE_TIMEOUT_S) + 60:
                self.path.unlink()
        except OSError:
            pass
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode("ascii"))
            return True
        except (FileExistsError, PermissionError):
            return False

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
                self.path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# model spawn (priced)
# --------------------------------------------------------------------------


@dataclass
class ModelRun:
    ok: bool
    text: str = ""
    cost_usd: float | None = None
    turns: int | None = None
    seconds: float = 0.0
    reason: str = ""


def model_runs_today(state: dict, now: float | None = None) -> int:
    """How many model calls the watchdog made today -- reporting only, not a
    gate; see WATCHDOG_LEDGER_REL for why nothing here refuses on this."""
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    runs = state.get("model_runs") or {}
    return int(runs.get(day, 0))


def spend_today(state: dict, now: float | None = None) -> float:
    """The MEASURED dollars this watchdog spent today -- reporting only.

    Read from the watchdog's own state, not from its dedicated ledger: this
    function backs the ``status`` line, and asking it to gate anything again
    would reintroduce the two failure modes WATCHDOG_LEDGER_REL exists to
    avoid (see the module docstring).
    """

    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    spend = state.get("model_spend_usd") or {}
    try:
        return float(spend.get(day, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _record_spend(state: dict, usd: float | None, now: float | None = None) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    spend = state.setdefault("model_spend_usd", {})
    spend[day] = round(float(spend.get(day, 0.0)) + float(usd or 0.0), 6)
    for key in list(spend):
        if key != day:
            del spend[key]


def _count_model_run(state: dict, now: float | None = None) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    runs = state.setdefault("model_runs", {})
    runs[day] = int(runs.get(day, 0)) + 1
    for key in list(runs):
        if key != day:
            del runs[key]


def own_ledger(root: Path):
    """The watchdog's dedicated, effectively-unlimited budget ledger.

    A fresh :class:`daedalus.budget.Ledger` object, not the module-global
    default: passing it explicitly to ``budget.guard(led=...)`` is what keeps
    this off ``runs/budget/ledger.json`` without touching any environment
    variable (an env var would apply to every subprocess this process spawns,
    including a plain ``git`` call, for no reason).
    """
    from daedalus import budget

    return budget.Ledger(
        root / WATCHDOG_LEDGER_REL,
        ceiling_usd=WATCHDOG_CEILING_USD,
        max_calls=WATCHDOG_MAX_CALLS,
        period="day",
    )


def run_claude(root: Path, prompt: str, *, label: str, allowed_tools: str, max_turns: int,
               model: str = MODEL, dry: bool = False,
               timeout_s: int = MODEL_TIMEOUT_S) -> ModelRun:
    """One priced, bounded `claude -p` call. The prompt goes on stdin."""
    exe = shutil.which("claude")
    if exe is None:
        return ModelRun(False, reason="claude CLI not on PATH")
    argv = [exe, "-p", "--model", model, "--output-format", "json", "--max-turns", str(max_turns)]
    if allowed_tools:
        argv += ["--allowedTools", allowed_tools]
    if dry:
        return ModelRun(True, text="(dry run: not spawned)", reason="dry")
    from daedalus import budget

    started = time.perf_counter()
    # ONE BILLING, AT THE MEASURED PRICE. `budget.guard` reserves, enters the
    # EXPLICIT mode that stops the process guard from pricing the same spawn a
    # second time, and settles on the way out; settling inside the block with
    # the CLI's own total_cost_usd wins, because Reservation.settle is
    # idempotent and the context manager's closing settle() then no-ops.
    #
    # MEASURED 2026-08-24, and this is why the code looks like this: a bare
    # reserve/settle pair (no explicit mode) had the process guard bill each
    # `claude` spawn a SECOND time at the flat $3 worst case, so every sweep
    # cost $3.42 instead of $0.42 and five of them exhausted the shared daily
    # ceiling -- which would have refused any other lane's model call too. The
    # ledger for 2026-08-24 shows the pairs: reserve/settle "watchdog.docs"
    # $0.42 beside reserve/settle "subprocess.run: ...claude.EXE" $3.00.
    text, cost, turns, failure = proc_out = "", None, None, ""
    warning = ""
    try:
        with budget.guard("anthropic_cli", model, label=label, led=own_ledger(root)) as reservation:
            try:
                proc = subprocess.run(
                    argv, input=prompt, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout_s, cwd=str(root),
                )
            except subprocess.TimeoutExpired:
                # settles the estimate: a timeout after the tokens were
                # generated looks exactly like a connection refused
                return ModelRun(False, seconds=time.perf_counter() - started, reason="timeout")
            except OSError as exc:
                reservation.release(f"spawn failed before any vendor bytes moved: {exc}")
                return ModelRun(False, reason=f"spawn failed: {exc}")
            text = proc.stdout
            try:
                data = json.loads(proc.stdout)
                if isinstance(data, dict):
                    text = str(data.get("result") or "")
                    cost = data.get("total_cost_usd")
                    turns = data.get("num_turns")
            except ValueError:
                pass
            if isinstance(cost, (int, float)):
                reservation.settle(float(cost))
            if proc.returncode != 0:
                # MEASURED 2026-08-25: `claude -p` exited 1 because a plugin
                # SessionEnd hook failed AFTER the work was done and the
                # result JSON was already on stdout. Losing a finished pass
                # (and its turn count) to a cleanup hook costs a real sweep.
                if text and cost is not None:
                    warning = f"exit {proc.returncode} after a complete result: {proc.stderr[-300:]}"
                else:
                    failure = f"exit {proc.returncode}: {proc.stderr[-500:]}"
                    proc_out = proc.stdout[-2000:]
    except budget.BudgetError as exc:
        return ModelRun(False, reason=f"budget refused: {exc}")
    seconds = time.perf_counter() - started
    if failure:
        return ModelRun(False, text=proc_out, cost_usd=cost, seconds=seconds, reason=failure)
    return ModelRun(True, text=text, cost_usd=cost, turns=turns, seconds=seconds,
                    reason=warning)


# --------------------------------------------------------------------------
# docs watchdog
# --------------------------------------------------------------------------


@dataclass
class Drift:
    kind: str
    subject: str
    detail: str


def _doc_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in DOC_FILES:
        out += sorted(p for p in root.glob(pattern) if p.is_file())
    return out


#: A markdown link whose target looks like a path (has a slash or a dot);
#: `spec["fn"](sb)` in prose is not a link.
_LINK = re.compile(r"\]\(([^)\s#]*[./][^)\s#]*)(?:#[^)]*)?\)")
_MARKED = re.compile(r"\((?:replaced by|archived:)[^)]*\)")


def docs_drift(root: Path) -> list[Drift]:
    """Mechanical drift detection; no model involved."""
    drifts: list[Drift] = []
    head = git(root, "rev-parse", "--short=8", "HEAD")

    # 1. architecture memory / map freshness
    try:
        from daedalus import arch_memory

        mem = arch_memory.load(root)
        if mem.lines and mem.head and head and not head.startswith(mem.head[:8]) and not mem.head.startswith(head):
            drifts.append(Drift("arch_memory_stale", "runs/arch_memory.json",
                                f"built at {mem.head[:8]}, HEAD is {head}"))
    except Exception as exc:  # noqa: BLE001
        drifts.append(Drift("arch_memory_unknown", "runs/arch_memory.json", f"{type(exc).__name__}: {exc}"))
    state_json = load_json(root / "docs/architecture-state.json")
    repo_state = state_json.get("repo_state") if isinstance(state_json.get("repo_state"), dict) else {}
    state_head = str(repo_state.get("head") or repo_state.get("commit") or state_json.get("head") or "")
    # "unknown" is what the map writes when it could not read git; not comparable,
    # and a perpetual drift would spend the daily model cap on nothing.
    if head and state_head and state_head != "unknown" and not (state_head.startswith(head) or head.startswith(state_head[:8])):
        drifts.append(Drift("architecture_state_stale", "docs/architecture-state.json",
                            f"names {state_head[:8]}, HEAD is {head}"))

    # 2. mentions of recently deleted files without a replacement mark
    # `git log` rather than `HEAD~30..HEAD`: the range form errors out (and
    # goes silent) on a history shorter than 30 commits.
    deleted = git(root, "log", "-30", "--diff-filter=D", "--name-only", "--format=").splitlines()
    deleted = sorted({d for d in deleted if d and not d.startswith(("docs/archive/", "runs/"))})
    docs = _doc_files(root)
    texts = {}
    for doc in docs:
        try:
            texts[doc] = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    live_names = {Path(p).name for p in git(root, "ls-files").splitlines()}
    for gone in deleted:
        name = Path(gone).name
        # the bare name counts only when no live file carries it (daedalus/cli.py
        # must not make every "cli.py" a mention of the deleted agent_env/cli.py)
        needles = (gone,) if name in live_names else (gone, name)
        for doc, text in texts.items():
            for i, line in enumerate(text.splitlines(), 1):
                if any(n in line for n in needles) and not _MARKED.search(line) and "replaced by" not in line and "removed 20" not in line:
                    drifts.append(Drift("deleted_file_mentioned", f"{doc.relative_to(root).as_posix()}:{i}",
                                        f"names {gone}, deleted within HEAD~30"))
                    break

    # 3. dead relative links
    for doc, text in texts.items():
        for i, line in enumerate(text.splitlines(), 1):
            for target in _LINK.findall(line):
                if "://" in target or target.startswith(("mailto:", "<")):
                    continue
                candidate = (doc.parent / target).resolve()
                if not candidate.exists():
                    drifts.append(Drift("dead_link", f"{doc.relative_to(root).as_posix()}:{i}", target))
    return drifts


def sweep_prompt(root: Path, drifts: list[Drift], head: str) -> str:
    findings = NL.join(f"- [{d.kind}] {d.subject}: {d.detail}" for d in drifts)
    return f"""You are Mnemosyne, the chronicler of the Daedalus crew, running as the background docs watchdog in {root} (branch main, HEAD {head}). MECHANICAL truth-keeping only. Work in the foreground; use no Serena/MCP tools.

The watchdog measured these drifts; fix exactly these, nothing else:
{findings}

Rules:
- For `deleted_file_mentioned`: append ` (replaced by daedalus/hooks/, 2026-08-23)` when the file was one of daedalus/shift_hook.py, arch_hook.py, crew_hook.py, .claude/hooks/serena-first.py, .claude/hooks/docs-drift-reminder.py; otherwise append ` (removed <YYYY-MM-DD>)` using `git log --diff-filter=D -1 --format=%cs -- <path>`. Never rewrite prose.
- For `dead_link`: point the link at the file's new location if `git log --all --diff-filter=R` or a `find` shows one; otherwise mark it `(archived: <path>)`.
- For `arch_memory_stale`: run `python -m daedalus.arch_memory` (writes an untracked file; do not commit it).
- For `architecture_state_stale`: run `python -m daedalus.cli map`, then include docs/architecture-state.json, docs/architecture-map.html, docs/FEATURE_INVENTORY.json in the commit.
- Any number you touch gets a provenance stamp: MEASURED / INHERITED / ASSUMED.
- Never touch: docs/IKARUS_ARIADNE_MASTER_PLAN*.md, AGENTS.md, CLAUDE.md, .claude/, tools/, .agentenv/, .github/, daedalus/, tests/, runs/watchdog/, docs/missions/, vault/.
- COMMIT WITH A PATHSPEC ONLY, never the index (other lanes stage in this tree): write the message to runs/watchdog/docs-commitmsg.txt, then `git commit -F runs/watchdog/docs-commitmsg.txt -- <the files you changed>`. Message ends with exactly `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never `git add -A`, never `--no-verify`, never `git push`.
- If a commit fails because of a lock, stop and report it; do not retry in a loop.

End with: the commands you ran, the HEAD after your commit (or "no commit"), and the files changed."""


def _prune_docs(root: Path) -> list[Path]:
    """Every doc the pruner may touch: README plus all of docs/, recursively.

    The drift sweep's DOC_FILES is deliberately non-recursive; the pruner is
    not, because docs/wiki/ and the other subtrees are exactly where the bloat
    accumulated (450 files, ~21k lines, MEASURED 2026-08-25).
    """
    seen: set[Path] = set()
    for pattern in PRUNE_GLOBS:
        seen.update(p for p in root.glob(pattern) if p.is_file())
    out = []
    for p in sorted(seen):
        rel = p.relative_to(root).as_posix()
        if rel in PRUNE_FORBIDDEN or rel.startswith(PRUNE_FORBIDDEN_PREFIX):
            continue
        out.append(p)
    return out


def _digest(path: Path) -> tuple[str, int]:
    """(content digest, line count) - the pair a pass compares before/after."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "", 0
    return hashlib.sha256(raw).hexdigest()[:16], raw.count(b"\n")


def prune_candidates(root: Path, cleaned: dict) -> list[Path]:
    """Docs whose CURRENT content has not been cleaned yet.

    This is not a cap on the pruner. One pass cannot reach 450 files, so
    without a memory of where it got to it would re-read the head of the list
    every 30 minutes and never touch the tail. A file re-enters the queue the
    moment its content changes again.
    """
    out = []
    for p in _prune_docs(root):
        rel = p.relative_to(root).as_posix()
        if cleaned.get(rel) != _digest(p)[0]:
            out.append(p)
    return out


def prune_prompt(root: Path, candidates: list[Path], head: str) -> str:
    listing = NL.join(f"- {p.relative_to(root).as_posix()}" for p in candidates)
    receipt_shape = ('{"reviewed": ["<repo-relative posix path>", ...], '
                     '"changed": [...], "notes": "<one line>"}')
    return f"""You are Mnemosyne, chronicler of the Daedalus crew, running as the background docs pruner in {root} (branch main, HEAD {head}). Work in the foreground; use no Serena/MCP tools.

Your job is two things, and the owner cares most about the first:

1. CLEAN. The documentation is bloated and the owner is fed up with it. Cut it down. Concretely: duplicated sections that say the same thing in several files, superseded status blocks, "current state" claims that describe a state long past, handoff notes for work that finished, restatements of the master plan that add nothing, dead scaffolding, ceremonial preambles. Prefer removing to rewriting. A shorter true document beats a longer one.

2. UPDATE. Where a document contradicts the code, make it match the code. The code is the truth; the document is the claim.

Files queued this pass ({len(candidates)}). Get through as many as you can; whatever you do not reach comes back next pass, so never rush a file in order to cover more of them:
{listing}

Rules:
- CHECK BEFORE YOU CUT. Read or Grep the code before rewriting a claim about it. Delete because you verified it is obsolete, never because it looks old. An unverified deletion is the one failure mode that matters here.
- RECORDS MAY BE CONDENSED, NEVER ERASED. In docs/decisions-taken/, docs/adrs/, docs/archive/, docs/work-packets/: tighten the prose, but the decision, its date, and its outcome must survive. Do not delete a record file.
- NEVER TOUCH: AGENTS.md, CLAUDE.md, docs/IKARUS_ARIADNE_MASTER_PLAN.md, docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl, or anything outside README.md and docs/. Never commit anything under runs/, .claude/, daedalus/, tests/, tools/, vault/.
- SKIP WHAT SOMEONE ELSE IS HOLDING. Other lanes work in this checkout. Before you edit a file, run `git status --porcelain -- <file>`; if it already shows as modified, leave it alone this pass and say so at the end. Committing it by pathspec would commit their unfinished work. It returns to the queue once they land it.
- Any number you keep gets a provenance stamp: MEASURED / INHERITED / ASSUMED.
- COMMIT WITH A PATHSPEC ONLY, never the index (other lanes stage in this tree): write the message to runs/watchdog/prune-commitmsg.txt, then `git commit -F runs/watchdog/prune-commitmsg.txt -- <the doc files you changed>`. The message body ends with these two lines exactly:
Watchdog-Prune: {head}
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
- Never `git add -A`, never `--no-verify`, never `git push`, never rewrite history.
- If a commit fails because of a lock, stop and report it; do not retry in a loop.
- BEFORE YOU FINISH, write runs/watchdog/prune-receipt.json:
  {receipt_shape}
  `reviewed` is every file you actually opened this pass; `changed` is every file you edited. This is how the watchdog knows where to resume, so an empty or missing receipt costs the next pass real work.

End with: the files you changed, the lines you removed, the HEAD after your commit (or "no commit"), and anything you chose NOT to cut and why."""


def prune_commit_effect(root: Path, head: str) -> tuple[list[str], int]:
    """What the pruner itself committed since `head`: (files, net lines removed).

    Attribution has to come from git, not from the working tree. Several lanes
    commit into this checkout, so "the file changed" says nothing about who
    changed it. The pruner stamps every commit of its own with
    `Watchdog-Prune: <head>`; that trailer is the only claim we accept.
    """
    trailer = f"Watchdog-Prune: {head}"
    mine = [c for c in git(root, "log", "--format=%H", f"{head}..HEAD").splitlines()
            if c and trailer in git(root, "log", "-1", "--format=%B", c)]
    files: set[str] = set()
    added = deleted = 0
    for commit in mine:
        for line in git(root, "show", "--numstat", "--format=", commit).splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            plus, minus, path = parts
            files.add(path)
            if plus.isdigit():
                added += int(plus)
            if minus.isdigit():
                deleted += int(minus)
    return sorted(files), max(0, deleted - added)


def prune_pass(root: Path, *, dry: bool = False, env: dict | None = None) -> dict:
    """One Sonnet cleaning pass over the docs.

    Owner decision 2026-08-25: no per-pass cap, no rotation limit, no spend
    ceiling. The gates that remain are the ones shared with every other pass
    (PAUSE, quiet HEAD, the pass lock) plus pathspec-only commits.
    """
    pstate = load_json(root / PRUNE_STATE_REL)
    cleaned = pstate.get("cleaned") or {}
    result: dict = {"kind": "prune", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    why = paused(root, env)
    if why:
        result["skipped"] = why
        return result
    quiet, reason = head_quiet(root)
    if not quiet:
        result["skipped"] = reason
        return result
    candidates = prune_candidates(root, cleaned)
    result["candidates"] = len(candidates)
    if not candidates:
        result["outcome"] = "corpus clean"
        return result

    head = git(root, "rev-parse", "--short=8", "HEAD")
    queued = {p.relative_to(root).as_posix() for p in candidates}
    prompt = prune_prompt(root, candidates, head)
    (root / WATCHDOG_DIR_REL / "docs").mkdir(parents=True, exist_ok=True)
    with (root / WATCHDOG_DIR_REL / "docs" / "last-prune-prompt.md").open(
            "w", encoding="utf-8", newline="") as fh:
        fh.write(prompt)
    receipt = root / PRUNE_RECEIPT_REL
    if not dry:
        try:
            receipt.unlink()
        except OSError:
            pass

    run = run_claude(root, prompt, label="watchdog.prune",
                     allowed_tools="Read,Grep,Glob,Edit,Write,Bash",
                     max_turns=PRUNE_MAX_TURNS, model=MODEL_PRUNE,
                     dry=dry, timeout_s=PRUNE_TIMEOUT_S)
    result["model"] = asdict(run)
    if dry:
        result["outcome"] = "dry run: prune would run"
        return result

    mstate = load_json(root / STATE_REL)
    _count_model_run(mstate)
    _record_spend(mstate, run.cost_usd)

    reviewed: list[str] = []
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
        reviewed = [str(x) for x in (data.get("reviewed") or [])]
        result["receipt"] = data.get("notes") or "read"
    except (OSError, ValueError):
        # The receipt is the model's own claim, so it can be absent or wrong.
        # Observation below is what actually advances the queue.
        result["receipt"] = "missing: resume relies on observed changes only"

    changed, removed = prune_commit_effect(root, head)
    result["changed"] = changed
    result["lines_removed"] = removed
    result["reviewed_claimed"] = len(reviewed)

    # A file is marked cleaned only on evidence the PRUNER handled it: it
    # named the file in its receipt, or the file rode one of its own commits.
    # A bare content change is not evidence -- other lanes edit this checkout,
    # and crediting their edits silently drops files out of the queue unpruned.
    for rel in set(reviewed) | set(changed):
        path = root / rel
        if rel in queued and path.is_file():
            cleaned[rel] = _digest(path)[0]
    pstate["cleaned"] = cleaned
    pstate["last_pass"] = result["ts"]
    save_json(root / PRUNE_STATE_REL, pstate)

    new_head = git(root, "rev-parse", "--short=8", "HEAD")
    result["committed"] = bool(changed)
    result["outcome"] = "prune ran" if run.ok else f"prune failed: {run.reason}"
    mstate["last_prune"] = result
    save_json(root / STATE_REL, mstate)
    try:
        with (root / PRUNES_LOG_REL).open("a", encoding="utf-8", newline="") as fh:
            fh.write(f"{result['ts']} HEAD={new_head} queued={len(candidates)} "
                     f"reviewed={len(reviewed)} changed={len(changed)} "
                     f"lines_removed={removed} "
                     f"commit={'yes' if result['committed'] else 'none'} "
                     f"cost={run.cost_usd} turns={run.turns}{NL}")
    except OSError:
        pass
    log(root, f"prune {result['outcome']} queued={len(candidates)} "
              f"changed={len(changed)} -{removed} lines")
    return result


def docs_pass(root: Path, *, dry: bool = False, env: dict | None = None) -> dict:
    state = load_json(root / STATE_REL)
    result: dict = {"kind": "docs", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    why = paused(root, env)
    if why:
        result["skipped"] = why
        return result
    quiet, reason = head_quiet(root)
    if not quiet:
        result["skipped"] = reason
        return result
    drifts = docs_drift(root)
    result["drifts"] = [asdict(d) for d in drifts]
    if not drifts:
        result["outcome"] = "no drift"
    else:
        head = git(root, "rev-parse", "--short=8", "HEAD")
        batch = drifts[:MAX_DRIFTS_PER_PASS]
        result["batched"] = len(batch)
        prompt = sweep_prompt(root, batch, head)
        (root / WATCHDOG_DIR_REL / "docs").mkdir(parents=True, exist_ok=True)
        (root / WATCHDOG_DIR_REL / "docs" / "last-prompt.md").write_text(prompt, encoding="utf-8")
        run = run_claude(root, prompt, label="watchdog.docs", allowed_tools="Read,Grep,Glob,Edit,Write,Bash",
                         max_turns=80, dry=dry)
        if not dry:
            _count_model_run(state)
            _record_spend(state, run.cost_usd)
        result["model"] = asdict(run)
        result["outcome"] = ("dry run: sweep would run" if dry else
                             "sweep ran" if run.ok else f"sweep failed: {run.reason}")
        new_head = git(root, "rev-parse", "--short=8", "HEAD")
        if dry:
            return result
        try:
            with (root / SWEEPS_LOG_REL).open("a", encoding="utf-8") as fh:
                fh.write(f"{result['ts']} HEAD={new_head} changed={len(drifts)} commit={'?' if new_head != head else 'none'} "
                         f"note=watchdog {'ran' if run.ok else 'failed'} cost={run.cost_usd} turns={run.turns}{NL}")
        except OSError:
            pass
    state["last_docs"] = result
    save_json(root / STATE_REL, state)
    log(root, f"docs {result.get('outcome') or result.get('skipped')} drifts={len(result.get('drifts', []))}")
    return result


# --------------------------------------------------------------------------
# work watchdog
# --------------------------------------------------------------------------


@dataclass
class Anomaly:
    id: str
    message: str


def _age(ts: float | None, now: float) -> float | None:
    return None if ts is None else max(0.0, now - ts)


def _hm(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def health(root: Path, *, now: float | None = None, temp_root: Path | None = None) -> dict:
    """Mechanical health facts; every value says where it came from."""
    now = time.time() if now is None else now
    facts: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}

    facts["branch"] = git(root, "branch", "--show-current")
    facts["head"] = git(root, "rev-parse", "--short=8", "HEAD")
    ts = git(root, "log", "-1", "--format=%ct")
    facts["last_commit_age_s"] = _age(int(ts), now) if ts.isdigit() else None
    facts["last_commit_subject"] = git(root, "log", "-1", "--format=%s")[:100]

    status = git(root, "status", "--porcelain", "--untracked-files=normal", "--", ".", ":(exclude)runs/hooks")
    dirty = [l[3:].strip().strip('"') for l in status.splitlines() if len(l) > 3]
    facts["dirty_files"] = len(dirty)
    source_dirty = [p for p in dirty if p.startswith(tuple(s + "/" for s in SOURCE_SCOPES))]
    facts["dirty_source_files"] = len(source_dirty)
    oldest = None
    for rel in source_dirty:
        try:
            m = (root / rel).stat().st_mtime
            oldest = m if oldest is None else min(oldest, m)
        except OSError:
            continue
    facts["oldest_dirty_source_age_s"] = _age(oldest, now)

    lock = root / ".git" / "index.lock"
    facts["index_lock_age_s"] = _age(lock.stat().st_mtime, now) if lock.exists() else None

    sweep_age = None
    try:
        lines = (root / SWEEPS_LOG_REL).read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            stamp = line.split(" ", 1)[0]
            try:
                sweep_age = now - time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")) + time.timezone
                break
            except ValueError:
                continue
    except OSError:
        pass
    facts["last_docs_sweep_age_s"] = sweep_age

    ledger = root / "runs/hooks/ledger.jsonl"
    facts["hook_ledger_age_s"] = _age(ledger.stat().st_mtime, now) if ledger.exists() else None
    sessions = 0
    try:
        for p in (root / "runs/hooks").glob("state-*.json"):
            if now - p.stat().st_mtime < 30 * 60:
                sessions += 1
    except OSError:
        pass
    facts["sessions_active_30m"] = sessions

    test_age = None
    try:
        for p in (root / "runs/hooks").glob("state-*.json"):
            data = load_json(p)
            t = data.get("last_test")
            if isinstance(t, dict):
                age = now - p.stat().st_mtime
                test_age = age if test_age is None else min(test_age, age)
    except OSError:
        pass
    facts["last_recorded_test_age_s"] = test_age

    try:
        from daedalus import shift as shift_mod

        s = shift_mod.load(root)
        facts["shift"] = {"goal": s.goal, "until": s.until, "expired": bool(s.goal and s.expired)}
    except Exception:  # noqa: BLE001
        facts["shift"] = {"goal": "", "until": "", "expired": False}

    try:
        usage = shutil.disk_usage(str(root))
        facts["disk_free_gb"] = round(usage.free / 1e9, 1)
    except OSError:
        facts["disk_free_gb"] = None

    temp_root = temp_root or Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / "claude"
    entries = None
    try:
        entries = sum(1 for _ in os.scandir(temp_root))
        entries += sum(
            1 for d in os.scandir(temp_root) if d.is_dir() for _ in os.scandir(d.path)
        )
    except OSError:
        pass
    facts["temp_claude_entries"] = entries
    return facts


def anomalies(facts: dict) -> list[Anomaly]:
    out: list[Anomaly] = []
    shift = facts.get("shift") or {}
    age = facts.get("last_commit_age_s")
    if shift.get("goal") and not shift.get("expired") and age is not None and age > COMMIT_GAP_S:
        out.append(Anomaly("commit_gap", f"no commit for {_hm(age)} during the declared shift"))
    if shift.get("expired"):
        out.append(Anomaly("shift_expired", f"the declared shift window ended ({shift.get('until')})"))
    lock_age = facts.get("index_lock_age_s")
    if lock_age is not None and lock_age > INDEX_LOCK_STALE_S:
        out.append(Anomaly("stale_index_lock", f".git/index.lock is {_hm(lock_age)} old"))
    oldest = facts.get("oldest_dirty_source_age_s")
    if oldest is not None and oldest > DIRTY_SOURCE_STALE_S:
        out.append(Anomaly("dirty_source_stale",
                           f"{facts.get('dirty_source_files')} uncommitted source files, oldest {_hm(oldest)}"))
    sweep = facts.get("last_docs_sweep_age_s")
    if sweep is None or sweep > SWEEP_STALE_S:
        out.append(Anomaly("docs_sweep_stale", f"last docs sweep {_hm(sweep) if sweep else 'never'} ago"))
    test_age = facts.get("last_recorded_test_age_s")
    if facts.get("dirty_source_files") and test_age is not None and test_age > TEST_STALE_S:
        out.append(Anomaly("tests_stale", f"source dirty and last recorded test run {_hm(test_age)} ago"))
    free = facts.get("disk_free_gb")
    if free is not None and free < DISK_FREE_MIN_GB:
        out.append(Anomaly("disk_low", f"{free} GB free"))
    entries = facts.get("temp_claude_entries")
    if entries is not None and entries > TEMP_ENTRIES_MAX:
        out.append(Anomaly("temp_bloat", f"%TEMP%/claude holds {entries} top-level entries"))
    return out


def render_health(facts: dict, found: list[Anomaly]) -> str:
    a = lambda key: _hm(facts.get(key))  # noqa: E731
    lines = [
        "# Daedalus work watchdog -- HEALTH",
        "",
        f"measured {facts.get('ts')} (MEASURED by tools/watchdog.py work; numbers are ages at that moment)",
        "",
        "| fact | value |",
        "| --- | --- |",
        f"| tree | {facts.get('branch')} @{facts.get('head')} |",
        f"| last commit | {a('last_commit_age_s')} ago -- {facts.get('last_commit_subject')} |",
        f"| dirty files | {facts.get('dirty_files')} (source: {facts.get('dirty_source_files')}, oldest {a('oldest_dirty_source_age_s')}) |",
        f"| index.lock | {a('index_lock_age_s') if facts.get('index_lock_age_s') is not None else 'none'} |",
        f"| last docs sweep | {a('last_docs_sweep_age_s')} ago |",
        f"| hook ledger | last activity {a('hook_ledger_age_s')} ago; sessions active (30 m): {facts.get('sessions_active_30m')} |",
        f"| last recorded test run | {a('last_recorded_test_age_s')} ago |",
        f"| shift | {facts.get('shift', {}).get('goal') or 'none declared'} {'(EXPIRED)' if facts.get('shift', {}).get('expired') else ''} |",
        f"| disk free | {facts.get('disk_free_gb')} GB |",
        f"| %TEMP%/claude | {facts.get('temp_claude_entries')} entries |",
        "",
        "## anomalies",
        "",
    ]
    lines += [f"- **{x.id}**: {x.message}" for x in found] or ["- none"]
    return NL.join(lines) + NL


#: The message reaches PowerShell through the ENVIRONMENT, never through argv.
#:
#: MEASURED 2026-08-24: an anomaly toast whose text named ``%TEMP%/claude``
#: was classified by ``budget.classify_argv`` as an Anthropic CLI call and
#: reserved $3 of the shared ceiling -- for a popup. The classifier is right to
#: be broad (it has to catch ``cmd /c claude -p`` and ``ssh bench 'claude -p'``,
#: and for a spend guard a false positive costs a refusal while a false
#: negative costs unbilled money); what was wrong is a background job putting
#: MEASURED TEXT into an argv at all. Through the environment there is nothing
#: to classify, nothing to quote and nothing to inject.
_TOAST_TITLE_ENV = "DAEDALUS_TOAST_TITLE"
_TOAST_TEXT_ENV = "DAEDALUS_TOAST_TEXT"
_TOAST_SCRIPT = (
    "(New-Object -ComObject Wscript.Shell).Popup("
    f"$env:{_TOAST_TEXT_ENV}, 8, $env:{_TOAST_TITLE_ENV}, 48)"
)


def toast(title: str, text: str) -> None:
    if os.name != "nt":
        return
    env = dict(os.environ)
    env[_TOAST_TITLE_ENV] = str(title)[:120]
    env[_TOAST_TEXT_ENV] = str(text)[:400]
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _TOAST_SCRIPT],
            timeout=10, capture_output=True, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def vault_append(root: Path, line: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    note = root / "vault" / "Sessions" / f"{day}.md"
    try:
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists():
            note.write_text(f"---{NL}tags: [session]{NL}date: {day}{NL}---{NL}{NL}# Session {day}{NL}", encoding="utf-8")
        text = note.read_text(encoding="utf-8")
        header = "## watchdog"
        with note.open("a", encoding="utf-8") as fh:
            if header not in text:
                fh.write(f"{NL}{header}{NL}{NL}")
            fh.write(f"- {time.strftime('%H:%M', time.localtime(now))} {line}{NL}")
    except OSError:
        pass


def report_prompt(root: Path, facts: dict, found: list[Anomaly]) -> str:
    day = time.strftime("%Y%m%d", time.gmtime())
    progress = ""
    for cand in sorted((root / "runs/watchdog").glob("mission-*/PROGRESS.md"), reverse=True):
        try:
            progress = NL.join(cand.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
            progress = f"{cand.relative_to(root).as_posix()} (last 15 lines):{NL}{progress}"
        except OSError:
            continue
        break
    gitlog = git(root, "log", "-12", "--format=%h %cr %s")
    return f"""You are the Daedalus work watchdog's reporter. Everything you need is below; use NO tools. Write at most 12 lines of plain text for the repository owner (German is fine): (1) what landed since the last report, (2) what is red or stale and since when, (3) what the open lane(s) appear to be doing next, (4) one line "watch:" naming the single most important thing to look at. Numbers only from the data below; stamp each as MEASURED. No headings, no praise, no advice beyond the watch line.

HEALTH (MEASURED {facts.get('ts')}):
{render_health(facts, found)}

git log -12:
{gitlog}

{progress}
"""


def work_pass(root: Path, *, dry: bool = False, env: dict | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    state = load_json(root / STATE_REL)
    result: dict = {"kind": "work", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
    why = paused(root, env)
    if why:
        result["skipped"] = why
        return result
    facts = health(root, now=now)
    found = anomalies(facts)
    result["facts"] = facts
    result["anomalies"] = [asdict(x) for x in found]
    save_json(root / HEALTH_JSON_REL, {"facts": facts, "anomalies": result["anomalies"]})
    (root / HEALTH_MD_REL).write_text(render_health(facts, found), encoding="utf-8")

    # notify once per anomaly onset, again after RENOTIFY_S
    notified = state.setdefault("notified", {})
    fresh = []
    for x in found:
        last = float(notified.get(x.id, 0))
        if now - last > RENOTIFY_S:
            fresh.append(x)
            notified[x.id] = now
    for key in list(notified):
        if key not in {x.id for x in found}:
            del notified[key]
    if fresh and not dry:
        toast("Daedalus work watchdog", "; ".join(f"{x.id}: {x.message}" for x in fresh))
        vault_append(root, "[watchdog] " + "; ".join(f"{x.id}: {x.message}" for x in fresh), now)
    result["notified"] = [x.id for x in fresh]

    # periodic model report, only when HEAD moved since the last one
    last_report = state.get("last_report") or {}
    due = (now - float(last_report.get("at", 0)) > REPORT_MIN_GAP_S) and last_report.get("head") != facts.get("head")
    if due:
        run = run_claude(root, report_prompt(root, facts, found), label="watchdog.report", allowed_tools="",
                         max_turns=1, dry=dry)
        result["model"] = asdict(run)
        if run.ok and not dry:
            _count_model_run(state, now)
            _record_spend(state, run.cost_usd, now)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
            (root / REPORTS_DIR_REL).mkdir(parents=True, exist_ok=True)
            body = f"# Work watchdog report {result['ts']} (HEAD {facts.get('head')}, {MODEL}, cost {run.cost_usd}){NL}{NL}{run.text}{NL}"
            (root / REPORTS_DIR_REL / f"{stamp}.md").write_text(body, encoding="utf-8")
            (root / REPORT_MD_REL).write_text(body, encoding="utf-8")
            state["last_report"] = {"at": now, "head": facts.get("head"), "cost_usd": run.cost_usd}
    state["last_work"] = {"ts": result["ts"], "anomalies": result["anomalies"]}
    save_json(root / STATE_REL, state)
    log(root, f"work anomalies={[x.id for x in found]} notified={result['notified']} report={'yes' if result.get('model') else 'no'}")
    return result


# --------------------------------------------------------------------------
# scheduling (Windows Task Scheduler, per-user, no admin)
# --------------------------------------------------------------------------

TASKS = {
    "Daedalus\\DocsWatchdog": ("docs", DOCS_INTERVAL_MIN),
    "Daedalus\\WorkWatchdog": ("work", WORK_INTERVAL_MIN),
}


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def _option_value(argv: list[str], option: str) -> str | None:
    """Return one explicit CLI option value; duplicates/missing values fail."""
    positions = [i for i, value in enumerate(argv) if value == option]
    if len(positions) > 1:
        raise ValueError(f"{option} may be supplied only once")
    if not positions:
        return None
    index = positions[0]
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise ValueError(f"{option} requires a value")
    return argv[index + 1]


def fleet_config_path(root: Path, argv: list[str]) -> Path:
    """Resolve a fleet config relative to the canonical watchdog checkout."""
    raw = _option_value(argv, "--config")
    path = Path(raw) if raw else root / FLEET_CONFIG_REL
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _fleet_scheduler_paths(root: Path, config: Path):
    from experiments.opus_fleet_watchdog.scheduler import SchedulerPaths

    return SchedulerPaths.validated(
        pythonw=_pythonw(),
        watchdog=root / "tools" / "watchdog.py",
        config=config,
        working_directory=root,
    )


def _fleet_status_dict(value) -> dict:
    data = asdict(value)
    data["degraded"] = bool(value.degraded)
    return data


def fleet_command(root: Path, mode: str, *, config: Path, dry: bool = False) -> int:
    """Thin canonical door for the isolated advisory-fleet experiment."""
    from experiments.opus_fleet_watchdog import campaign_status, dry_plan, run_campaign
    from experiments.opus_fleet_watchdog import scheduler as fleet_scheduler

    if mode == "fleet":
        if dry:
            result = dry_plan(config)
        else:
            from experiments.opus_fleet_watchdog.session_probe import fleet_session_probe

            result = run_campaign(config, session_probe=fleet_session_probe)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        status_name = str(result.get("status") or "")
        reason = str(result.get("reason") or "")
        if status_name == "degraded":
            return 1
        if status_name == "waiting" and reason.startswith("session_probe_error:"):
            return 3
        return 0

    if mode == "fleet-uninstall":
        if dry:
            result = {
                "action": "would_uninstall",
                "task": fleet_scheduler.TASK_FULL_NAME,
            }
        else:
            fleet_scheduler.uninstall()
            result = {
                "action": "uninstalled",
                "task": fleet_scheduler.TASK_FULL_NAME,
            }
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    paths = _fleet_scheduler_paths(root, config)
    if mode == "fleet-install":
        # Refuse to register a timer around a malformed or unavailable plan.
        plan = dry_plan(config)
        if dry:
            result = {
                "action": "would_install",
                "task": fleet_scheduler.TASK_FULL_NAME,
                "arguments": paths.action_arguments,
                "working_directory": str(paths.working_directory),
                "plan_digest": plan["plan_digest"],
            }
        else:
            fleet_scheduler.install(
                pythonw=paths.pythonw,
                watchdog=paths.watchdog,
                config=paths.config,
                working_directory=paths.working_directory,
            )
            current = fleet_scheduler.status(expected_paths=paths)
            result = {
                "action": "installed",
                "task": fleet_scheduler.TASK_FULL_NAME,
                "scheduler": _fleet_status_dict(current),
                "plan_digest": plan["plan_digest"],
            }
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0

    if mode == "fleet-status":
        current = fleet_scheduler.status(expected_paths=paths)
        result = {
            "task": fleet_scheduler.TASK_FULL_NAME,
            "scheduler": _fleet_status_dict(current),
            "campaign": campaign_status(config),
        }
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 1 if current.degraded else 0

    raise ValueError(f"unknown fleet mode {mode!r}")


def task_commands(root: Path, action: str) -> list[list[str]]:
    """The schtasks argv lists for install/uninstall (pure; tests check them)."""
    script = root / "tools" / "watchdog.py"
    cmds: list[list[str]] = []
    for name, (mode, minutes) in TASKS.items():
        if action == "install":
            tr = f'"{_pythonw()}" "{script}" {mode}'
            cmds.append(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(minutes),
                         "/TN", name, "/TR", tr, "/RL", "LIMITED"])
        else:
            cmds.append(["schtasks", "/Delete", "/F", "/TN", name])
    return cmds


def schedule(root: Path, action: str, *, dry: bool = False) -> int:
    rc = 0
    for argv in task_commands(root, action):
        print(" ".join(argv))
        if dry or os.name != "nt":
            continue
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((proc.stdout or proc.stderr).strip())
        rc = rc or proc.returncode
    if action == "install" and not dry:
        log(root, "installed scheduled tasks " + ", ".join(TASKS))
    return rc


def status(root: Path) -> str:
    lines = []
    if os.name == "nt":
        for name in TASKS:
            # schtasks writes OEM-codepage bytes, not UTF-8. Decoding them as
            # UTF-8 turned every umlaut into U+FFFD, which a cp1252 stdout then
            # refused to encode -- `status` crashed on this box (MEASURED
            # 2026-08-25, reproduced on the unmodified file).
            proc = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
                                  capture_output=True, text=True, encoding="oem", errors="replace")
            if proc.returncode == 0:
                # schtasks localises its labels (German box: "Aufgabenname",
                # "Nächste Laufzeit"); match on the English or German stems.
                stems = ("TaskName", "Aufgabenname", "Status", "Next Run", "Nächste", "Last Run", "Letzte", "Last Result", "Letztes Ergebnis")
                lines += [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith(stems)]
            else:
                lines.append(f"{name}: not installed")
    state = load_json(root / STATE_REL)
    lines.append(f"model runs today: {model_runs_today(state)} (no cap)")
    lines.append(f"spend today: ${spend_today(state):.2f} (measured, own ledger, no cap)")
    lines.append(f"last docs: {json.dumps(state.get('last_docs', {}).get('outcome') or state.get('last_docs', {}).get('skipped'))}")
    lines.append(f"last work anomalies: {[a['id'] for a in (state.get('last_work') or {}).get('anomalies', [])]}")
    # the pruner's own picture, so one command answers "is it working" without
    # anyone having to remember three more
    cleaned = (load_json(root / PRUNE_STATE_REL).get("cleaned") or {})
    total = len(_prune_docs(root))
    open_docs = len(prune_candidates(root, cleaned))
    lines.append(f"prune queue: {total - open_docs}/{total} docs cleaned, {open_docs} open")
    lp = state.get("last_prune") or {}
    lines.append(f"last prune: {json.dumps(lp.get('outcome') or lp.get('skipped'))}"
                 f" changed={len(lp.get('changed') or [])} lines_removed={lp.get('lines_removed', 0)}")
    stamped = [c for c in git(root, "log", "--grep=Watchdog-Prune", "--format=%h").splitlines() if c]
    lines.append(f"prune commits: {len(stamped)}{' (' + ', '.join(stamped[:5]) + ')' if stamped else ''}")
    lines.append(f"pass running now: {'yes' if (root / LOCK_REL_TEMPLATE.format(mode='docs')).exists() else 'no'}")
    lines.append(f"paused: {paused(root) or 'no'}")
    return NL.join(lines)


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    mode = args[0] if args else "status"
    root = ROOT
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, EffectBoundaryError, begin_effect

    try:
        begin_effect(
            "tools.watchdog",
            REGISTRY_BY_ID["tools.watchdog"].effects,
            (process_guard_boundary_decision(),),
        )
    except EffectBoundaryError as exc:
        print(f"[watchdog] effect boundary refused: {exc}", file=sys.stderr)
        return 2
    if mode in ("fleet", "fleet-install", "fleet-uninstall", "fleet-status"):
        try:
            config = fleet_config_path(root, argv)
            return fleet_command(root, mode, config=config, dry=dry)
        except Exception as exc:  # scheduled tasks need a loud, non-zero result
            print(
                f"[watchdog] {mode} refused: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
    if mode == "status":
        text = status(root)
        try:
            print(text)
        except UnicodeEncodeError:
            # a console narrower than the text is not a reason to report nothing
            enc = sys.stdout.encoding or "ascii"
            print(text.encode(enc, "replace").decode(enc, "replace"))
        return 0
    if mode in ("install", "uninstall"):
        return schedule(root, mode, dry=dry)
    if mode not in ("docs", "work", "prune"):
        print(__doc__)
        return 2
    with PassLock(root, "docs" if mode == "prune" else mode) as acquired:
        if not acquired:
            log(root, f"{mode} skipped: another {mode} pass is already running")
            print(f"skipped: another {mode} pass is running")
            return 0
        if mode == "docs":
            result = docs_pass(root, dry=dry)
            # The pruner rides the same 30-minute tick and the same lock;
            # a second scheduled task would only fight this one for it.
            result["prune"] = prune_pass(root, dry=dry)
        elif mode == "prune":
            result = prune_pass(root, dry=dry)
        else:
            result = work_pass(root, dry=dry)
    print(json.dumps({k: v for k, v in result.items() if k != "facts"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
