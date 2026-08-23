"""tools/watchdog.py -- the two background watchdogs: docs and work.

Owner order 2026-08-22/23: a docs agent is always active, and a general work
watchdog runs in the background, independent of any open Claude session.

    python tools/watchdog.py docs          one docs pass (mechanical first, model only on drift)
    python tools/watchdog.py work          one health pass (mechanical; model report when HEAD moved)
    python tools/watchdog.py install       register both as Windows scheduled tasks (user, no admin)
    python tools/watchdog.py uninstall     remove the tasks
    python tools/watchdog.py status        tasks, last runs, last anomalies
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
the last one. Every spawn is reserved on the shared budget ledger before the
call (flat worst-case $3, refused above the ceiling) and settled with the
MEASURED cost from the CLI's JSON afterwards; the cost lands in the log.

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
LOCK_REL = "runs/watchdog/.pass.lock"

DOCS_INTERVAL_MIN = 30
WORK_INTERVAL_MIN = 15
REPORT_MIN_GAP_S = 2 * 3600
MODEL = "claude-haiku-4-5"
MODEL_TIMEOUT_S = 15 * 60
DAILY_MODEL_CAP = 12
#: The watchdog's own daily ceiling on the SHARED budget ledger. The ledger
#: prices every `claude -p` at a flat worst-case $3 before the call and settles
#: the measured cost after it (haiku reports: ~$0.12), so the ceiling must hold
#: today's settled spend plus one $3 reservation. Set DAEDALUS_BUDGET_USD in
#: the environment to override; an unconfigured process would get $5.
WATCHDOG_CEILING_USD = "15"
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
    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_REL
        self.fd: int | None = None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if time.time() - self.path.stat().st_mtime > MODEL_TIMEOUT_S + 60:
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
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    runs = state.get("model_runs") or {}
    return int(runs.get(day, 0))


def _count_model_run(state: dict, now: float | None = None) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    runs = state.setdefault("model_runs", {})
    runs[day] = int(runs.get(day, 0)) + 1
    for key in list(runs):
        if key != day:
            del runs[key]


def run_claude(root: Path, prompt: str, *, label: str, allowed_tools: str, max_turns: int,
               model: str = MODEL, dry: bool = False) -> ModelRun:
    """One priced, bounded `claude -p` call. The prompt goes on stdin."""
    exe = shutil.which("claude")
    if exe is None:
        return ModelRun(False, reason="claude CLI not on PATH")
    argv = [exe, "-p", "--model", model, "--output-format", "json", "--max-turns", str(max_turns)]
    if allowed_tools:
        argv += ["--allowedTools", allowed_tools]
    if dry:
        return ModelRun(True, text="(dry run: not spawned)", reason="dry")
    os.environ.setdefault("DAEDALUS_BUDGET_USD", WATCHDOG_CEILING_USD)
    from daedalus import budget

    started = time.perf_counter()
    # reserve -> run -> settle with the MEASURED cost from the CLI's JSON.
    # `budget.guard` would settle the ESTIMATE (a whole-session price, ~$3),
    # which charged a $0.12 report as $3.00 on the first live run and would
    # have exhausted the $5/day ceiling after two passes. An unknown actual
    # still settles the estimate -- a timeout is not a free call.
    try:
        res = budget.reserve("anthropic_cli", model, label=label)
    except budget.BudgetError as exc:
        return ModelRun(False, reason=f"budget refused: {exc}")
    proc = None
    try:
        proc = subprocess.run(
            argv, input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=MODEL_TIMEOUT_S, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        res.settle()
        return ModelRun(False, seconds=time.perf_counter() - started, reason="timeout")
    except OSError as exc:
        res.release(f"spawn failed before any vendor bytes moved: {exc}")
        return ModelRun(False, reason=f"spawn failed: {exc}")
    seconds = time.perf_counter() - started
    text, cost, turns = proc.stdout, None, None
    try:
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            text = str(data.get("result") or "")
            cost = data.get("total_cost_usd")
            turns = data.get("num_turns")
    except ValueError:
        pass
    res.settle(float(cost) if isinstance(cost, (int, float)) else None)
    if proc.returncode != 0:
        return ModelRun(False, text=proc.stdout[-2000:], cost_usd=cost, seconds=seconds,
                        reason=f"exit {proc.returncode}: {proc.stderr[-500:]}")
    return ModelRun(True, text=text, cost_usd=cost, turns=turns, seconds=seconds)


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
    elif model_runs_today(state) >= DAILY_MODEL_CAP:
        result["outcome"] = f"drift found but daily model cap ({DAILY_MODEL_CAP}) reached"
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


def toast(title: str, text: str) -> None:
    if os.name != "nt":
        return
    safe = lambda s: s.replace("'", "''")[:200]  # noqa: E731
    ps = f"(New-Object -ComObject Wscript.Shell).Popup('{safe(text)}', 8, '{safe(title)}', 48)"
    try:
        subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                       timeout=10, capture_output=True)
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
    if due and model_runs_today(state) < DAILY_MODEL_CAP:
        run = run_claude(root, report_prompt(root, facts, found), label="watchdog.report", allowed_tools="",
                         max_turns=1, dry=dry)
        result["model"] = asdict(run)
        if run.ok and not dry:
            _count_model_run(state, now)
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
            proc = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode == 0:
                # schtasks localises its labels (German box: "Aufgabenname",
                # "Nächste Laufzeit"); match on the English or German stems.
                stems = ("TaskName", "Aufgabenname", "Status", "Next Run", "Nächste", "Last Run", "Letzte", "Last Result", "Letztes Ergebnis")
                lines += [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith(stems)]
            else:
                lines.append(f"{name}: not installed")
    state = load_json(root / STATE_REL)
    lines.append(f"model runs today: {model_runs_today(state)} / {DAILY_MODEL_CAP}")
    lines.append(f"last docs: {json.dumps(state.get('last_docs', {}).get('outcome') or state.get('last_docs', {}).get('skipped'))}")
    lines.append(f"last work anomalies: {[a['id'] for a in (state.get('last_work') or {}).get('anomalies', [])]}")
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
    if mode == "status":
        print(status(root))
        return 0
    if mode in ("install", "uninstall"):
        return schedule(root, mode, dry=dry)
    if mode not in ("docs", "work"):
        print(__doc__)
        return 2
    with PassLock(root) as acquired:
        if not acquired:
            log(root, f"{mode} skipped: another pass holds {LOCK_REL}")
            print("skipped: another pass is running")
            return 0
        result = docs_pass(root, dry=dry) if mode == "docs" else work_pass(root, dry=dry)
    print(json.dumps({k: v for k, v in result.items() if k != "facts"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
