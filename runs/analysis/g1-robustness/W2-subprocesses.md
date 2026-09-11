# W2 — Subprocess resource-lifetime sweep (read-only, static)

Scope: `daedalus/` and `tools/` (Python only). `tests/`, `apps/`, `vault/`,
`.quarantine/`, `daedalus/lanes/` out of scope. No file was modified, no git
mutation was run, no repo code was executed.

Repo: `C:/Users/Administrator/daedalus`.
Measured commit at scan time: `36a266ea005732c71b55ed4322f1b7670334b429`
(`git rev-parse HEAD` == `git rev-parse main`, branch `main`). Note: the task
header named `54f09753`; that sha was not what `git rev-parse HEAD` returned
in this worktree at scan time — recorded as a discrepancy, not silently
resolved.

Canonical defect writeup read first: `daedalus/kernel/effects.py:576-587`
(the `_initialize` docstring on the SQLite connection leak this campaign
generalizes from — transaction scope vs. closing scope, GC-timed finalization
of the WAL companion, TOCTOU on the scanner).

## Method

Grep alone was not trusted for the "no timeout" claim (a `timeout=` kwarg can
be far from the call, or applied via `**kwargs` unpacking) — a static AST scan
(`ast.parse`, no execution, no repo import) was written to a **scratch file
outside the repo** (`C:/Users/Administrator/daedalus_scratch_w2scan.py`, not
tracked, not under the repo root) and run with the repo's own interpreter
(`.venv/Scripts/python.exe`) to enumerate every `subprocess.run` /
`.check_output` / `.check_call` / `.Popen` call site, its exact line, whether
a literal `timeout=` keyword is present in the call, `shell=True`,
`creationflags`, `start_new_session`, and the enclosing function name. Every
flagged site was then read in full context with `Read` before classifying —
the AST scan finds candidates, it does not itself render a verdict.

Grep patterns used first, for raw counts, then superseded by the AST scan for
the authoritative per-site table:

| grep pattern | daedalus/ raw hits | tools/ raw hits |
| --- | --- | --- |
| `subprocess\.(run\|check_output\|check_call)\(` | 71 occurrences / 44 files | 38 occurrences / 15 files |
| `subprocess\.Popen` | 9 files | 5 files |

AST scan totals (authoritative, supersedes the grep raw counts above — the
grep count differs slightly from the AST count because grep counts pattern
occurrences including ones inside strings/comments that generate code, e.g.
`tools/gate_discrimination.py` seeds mutation-test source text containing the
literal substring `subprocess.run(`; the AST scan parses only real call
nodes):

| category | count |
| --- | --- |
| `subprocess.run` / `check_output` / `check_call` call sites | **101** |
| ...missing a literal `timeout=` keyword | **18** |
| `subprocess.Popen` call sites | **10** |
| `.communicate()` call sites | 2 |
| `.terminate()` call sites | 6 |
| `.kill()` call sites | 18 |
| `shell=True` sites | **0** |
| sites with `creationflags` set | 4 (all in `daedalus/desktop_runtime.py`) |
| sites with `start_new_session` set | 0 among the literal-kwarg scan (one real site — hermes adapter — sets it via a conditionally-built kwargs dict; see below) |

Triage: all 18 missing-timeout `run`/`check_output`/`check_call` sites were
read in full function context. All 10 `Popen` sites were read in full
function context, including their cleanup path (`finally`, owning-class
stop/cancel method, or absence thereof). All 6 `terminate()` and a
representative cross-section of the 18 `kill()` sites were read to check for
wait-then-escalate and process-group scope. 2/2 `communicate()` sites read.

## Gate1.py claim verification

Claim under test: "the git call at `daedalus/ignition/gate1.py` roughly lines
322-338 is the ONLY sibling git call in that file without a timeout."

Full enumeration of every subprocess call in `daedalus/ignition/gate1.py`
(there are exactly two — confirmed by both grep and the AST scan; no `Popen`,
no `shell=True`, no `creationflags`/`start_new_session`, no
`terminate`/`kill` in this file):

| line | call | enclosing function | has `timeout=` |
| --- | --- | --- | --- |
| 327 | `subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True)` (inside the `_git` helper) | `_git` | **no** |
| 527 | `subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=str(repo), stdout=handle, stderr=subprocess.PIPE)` (inside `compose_candidate`, bypasses the `_git` helper) | `compose_candidate` | **no** |

**Verdict: REFUTED.** `gate1.py` does not contain one git call without a
timeout and siblings with one — it contains exactly **2** subprocess call
sites in the whole file, both git invocations, and **both (2/2)** lack a
`timeout=`. There is no sibling call in this file that has a timeout for the
claim to be "the only one without" one against. The `_git` helper (used by
`prepare_ignition_repo` for `init`/`config`/`add`/`commit`/`rev-parse`) and
the direct `git archive` call in `compose_candidate` share the identical
defect shape and neither is more protected than the other.

Same defect shape recurs one level down the dependency graph, not "in that
file" but in the module `TaskAttempt` (and therefore this ignition slice)
actually spawns worktrees through: `daedalus/kairos/worktree.py:716`,
`GitWorktreeManager._run_git`, also `subprocess.run(cmd, cwd=cwd_path,
capture_output=True, text=True, check=True)` with **no** `timeout=`. This is
on the live attempt spine (every `TaskAttempt` worktree add/remove goes
through it), not just the Gate-1 rehearsal — see Findings below.

## Full inventory: `subprocess.run` / `check_output` / `check_call` (101 sites)

83/101 sites declare a literal `timeout=`. The 18 that do not:

| file:line | enclosing function | notes |
| --- | --- | --- |
| `daedalus/ignition/gate1.py:327` | `_git` | kernel-adjacent (Gate-1 rehearsal); see verdict above |
| `daedalus/ignition/gate1.py:527` | `compose_candidate` | kernel-adjacent (Gate-1 rehearsal); see verdict above |
| `daedalus/kairos/worktree.py:716` | `_run_git` (`GitWorktreeManager`) | **live attempt spine**, not a rehearsal-only path |
| `tools/audit_swarm.py:197` | `tracked_modules` | dev audit tool, `git ls-files` |
| `tools/bootstrap_receipt.py:529` | `run_single` | on the leased-attempt bootstrap path; `git rev-parse HEAD` against caller-supplied `target` |
| `tools/build_tauri_sidecar.py:204` | `build` | PyInstaller build invocation, `check=True`, genuinely long-running by design |
| `tools/docs_reference_check.py:201` | `_tracked_markdown` | dev doc-link checker, `git ls-files` |
| `tools/docs_reference_check.py:218` | `_resolve_candidates` | dev doc-link checker, `git ls-files` |
| `tools/funnel.py:137` | `_tracked` | dev tool, `git ls-files` |
| `tools/funnel.py:622` | `main` | dev tool, `git rev-parse --short HEAD` |
| `tools/funnel_report.py:292` | `repo_files` | dev tool, `git ls-files` |
| `tools/mutation_score.py:771` | `pytest_runner` | **caveat**: `timeout` is passed via `**run_options` only `if timeout is not None`; a caller that passes `timeout=None` gets a genuinely unbounded `pytest` run per mutant — confirmed by reading the source, not just the AST literal-kwarg scan |
| `tools/operability_drill.py:202` | `control_spend` | drill/test harness invoking `claude` CLI (behind a sentinel patch in this control, so it never truly spawns in the drill, but the call as written has no bound) |
| `tools/operability_drill.py:353` | `_alive` | `tasklist` liveness probe, OS utility, low risk |
| `tools/operability_drill.py:380` | `control_gate_escape` | drill harness spawning real `git` against a scratch repo |
| `tools/run_gate_checks.py:87` | `_run` | invokes the **whole gate/pytest profile** with no bound at all |
| `tools/watchdog.py:1211` | `schedule` | `schtasks /Create`/`/Delete`, OS utility |
| `tools/watchdog.py:1227` | `status` | `schtasks /Query`, OS utility |

## Full inventory: `subprocess.Popen` (10 sites)

| file:line | enclosing function | waited on all paths? | process-group isolated? | notes |
| --- | --- | --- | --- | --- |
| `daedalus/desktop_runtime.py:703` | `ensure_ide` | yes — `stop_ide` does `terminate()`→`wait(2)`→`kill()` | yes, `creationflags=self._creationflags()` | tracked in `self._ide`; relies on an explicit `stop_ide()` call somewhere in app shutdown |
| `daedalus/desktop_runtime.py:1152` | `ensure_remote_ollama` | yes — `stop_ollama_transport` same escalation | yes | tracked in `self._tunnel`; same caveat |
| `daedalus/ikarus_os.py:2017` | `_claude_stream` | yes — `finally: kill()`→`wait(5)` | no explicit flag | see Finding F1 (stdin-write pipe risk) |
| `daedalus/integrations/hermes/runtime_adapter.py:372` | `execute` | yes — `finally:` at line 514 always calls `_terminate` (`terminate()`→`wait(2)`→`kill()`) | yes, `CREATE_NEW_PROCESS_GROUP` (nt) / `start_new_session=True` (posix), built into `popen_options` before spawn | exemplary |
| `daedalus/spine/cancel.py:452` | `ManagedProcess.__init__` | yes — context-manager contract; `after_spawn` failure kills+waits before re-raising | yes, backend-selected Job Object (win) / process-group (posix) | exemplary; registered in a `WeakSet` swept by `KillSwitch.stop_children` |
| `tools/bootstrap_receipt.py:680` | `run_concurrent` | yes, but **`p.wait()` has no timeout** | no | see Finding F2 |
| `tools/gui_check.py:214` | `_start_server` | yes — caller's `finally: kill()`→`wait(20)` | no | see Finding F3 (stdout PIPE never drained while polling) |
| `tools/smoke_tauri_sidecar.py:38` | `smoke` | yes — `finally: terminate()`→`wait(5)`→on timeout `kill()`→`wait(5)` | no | good escalation pattern; low risk (frozen onedir exe, unlikely to spawn grandchildren) |
| `tools/system_check.py:663` | `_web` | yes — `finally: kill()`→`wait(20)` | no | see Finding F3 (same PIPE-not-drained shape) |
| `tools/system_check.py:788` | `_file_bridge` | yes — `finally: kill()`→`wait(20)` | no | see Finding F3 (same PIPE-not-drained shape) |

## Findings

### F1 — `daedalus/ikarus_os.py:2017-2060`, `_claude_stream`: stdin write before any stdout read

```python
proc = subprocess.Popen(
    args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    errors="replace", bufsize=1, cwd=_neutral_cwd(),
    env=runtime_subprocess_env("claude_code_cli"),
)
proc.stdin.write(prompt)
proc.stdin.close()
...
for line in proc.stdout:
```

**Failure enabled**: `proc.stdin.write(prompt)` is one synchronous write of
the whole prompt, issued before anything reads `proc.stdout`. If `prompt`
(the message plus injected context) exceeds the OS pipe buffer (~64 KB) and
the child does not fully drain stdin before it needs to write anything to
stdout (a startup banner, an early error), the child's stdout write blocks
because nobody is reading it yet, this process's `stdin.write()` blocks
because the child stopped reading — classic two-sided pipe deadlock,
`subprocess.communicate()` exists specifically to avoid this pattern.
**On mid-operation kill**: bounded — the `finally: kill(); wait(timeout=5)`
means a genuine deadlock here is capped at 5s past whatever the caller's own
timeout is, so this degrades to "the assistant silently falls back to the
blocking path" rather than a true hang or a zombie. **Severity**: low-medium.
Product-adjacent (chat streaming path, not the kernel/effect-boundary), and
the failure is silently absorbed by a broad `except (OSError,
SubprocessError, ValueError): return` plus the `finally` kill, so it never
surfaces as an operator-visible hang — but a large enough prompt could still
cost 5+ seconds of dead time on every large turn. **Confidence**: medium — CLI
child behavior (does `claude -p ... --output-format stream-json` fully drain
stdin before emitting anything?) was not independently verified; this is a
structural risk from the code shape, not an observed hang.

### F2 — `tools/bootstrap_receipt.py:672-685`, `run_concurrent`: `Popen.wait()` with no timeout, no process-group isolation

```python
procs.append((i, out, log,
              subprocess.Popen(cmd, cwd=str(CODE_ROOT), stdout=log,
                               stderr=subprocess.STDOUT)))
codes = []
for i, out, log, p in procs:
    codes.append({"index": i, "returncode": p.wait(), "out": str(out)})
    log.close()
```

**Failure enabled**: all `n` children are spawned first (this is the whole
point — a concurrency-reproduction harness), then reaped sequentially with a
bare `p.wait()` — no timeout. If any one child in the batch hangs (e.g. a
lease-acquisition deadlock, the exact class of bug this harness exists to
reproduce), the harness itself hangs forever on that `wait()`, even though
every later sibling in the batch may have already finished. No
`creationflags`/`start_new_session` either, so a Ctrl-C on the harness leaves
already-spawned children as orphans rather than a contained tree. **On
mid-operation kill**: the parent dying (Ctrl-C, crash) leaves every not-yet-
reaped child running unsupervised against the *same shared checkout* this
harness targets — each child is itself a live `TaskAttempt` doing git
worktree/lease work, so an orphaned one can leave a worktree or a lease
outstanding that the harness's own post-hoc "leak check" (`_leak_check`) was
supposed to catch but no longer can, because the process that would have
reaped and reconciled it is gone. **Severity**: medium. Confined to a dev/
reproduction tool (`tools/bootstrap_receipt.py --concurrent`), but it is
exactly the tool used to validate the kernel's own concurrency-safety
invariant, so a hang here silently drops the coverage it exists to provide.
**Confidence**: high — read in full, unambiguous.

### F3 — `tools/gui_check.py:212-229`, `tools/system_check.py:663-698` and `:788-811`: `stdout=PIPE`/`stderr=STDOUT` never drained while polling

```python
proc = subprocess.Popen(
    [PY, *argv, "--port", str(port)], cwd=str(repo_root),
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, ...)
...
while time.time() < deadline:
    if proc.poll() is not None: ...
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
            ...
```

(Three near-identical sites: `gui_check.py::_start_server`,
`system_check.py::_web`, `system_check.py::_file_bridge`.) **Failure
enabled**: `stdout`/`stderr` are captured into a pipe, but nothing reads that
pipe during the readiness-polling loop — only `proc.poll()` (exit-code check)
and an unrelated HTTP probe run. If the child (the `daedalus web` server, or
the file-bridge watcher) logs more than one pipe-buffer's worth of combined
stdout+stderr before answering, its own `write()` call blocks because the
pipe is full and nobody is consuming it — the process looks alive to
`poll()` (it is; it's blocked on I/O, not exited) while never becoming
network-ready, for a reason the readiness check cannot see. **On
mid-operation kill**: bounded — each site has a `finally: kill(); wait(...)`,
so this degrades to "wastes the whole readiness deadline (45s/90s/1800s
depending on caller) then reports FAIL/kills," not an infinite hang. But it
converts a real hazard (verbose child logging) into a **false negative**: the
tool reports "server did not answer" when the actual cause is "server was
blocked writing to a pipe nobody reads," which sends whoever is debugging the
gate failure toward the wrong cause. `gui_check.py::_drain` does read
`proc.stdout` — but only *after* the process is already killed, i.e. after
the false-FAIL already happened. **Severity**: low-medium — all three sites
are gate/CI tooling (`tools/system_check.py`, `tools/gui_check.py`), not the
runtime kernel; the practical exposure is flaky/misleading gate failures
under verbose child logging, not a live-system leak. **Confidence**: high
that the pattern is real (no reader thread or `communicate()` present in
either file's readiness loop, confirmed by reading both in full); medium on
how often the child actually logs enough to trigger it in practice.

### F4 — `daedalus/kairos/worktree.py:700-725`, `GitWorktreeManager._run_git`: no timeout on the git call the live attempt spine uses for every worktree operation

```python
result = subprocess.run(
    cmd, cwd=cwd_path, capture_output=True, text=True, check=True
)
```

**Failure enabled**: same shape as the two `gate1.py` sites, but this is the
helper `TaskAttempt` actually calls (via `GitWorktreeManager`) to create and
remove worktrees for every attempt, not just the Gate-1 rehearsal — `git
worktree add`/`remove` under `-c core.longpaths=true` (per the function's own
docstring, deep paths on this box). A stuck `.git/index.lock`, an
antivirus-held handle, or a wedged `git gc` on the shared checkout hangs this
call, and therefore the attempt, indefinitely; nothing above it imposes a
bound. **On mid-operation kill**: killing the caller (the attempt driver)
leaves an orphaned `git` process still holding `.git`'s index lock — the
*next* attempt against the same repo then fails to acquire the lock too,
which is a wider blast radius than a single hung attempt. **Severity**:
medium-high — this is closer to the kernel/attempt path than a dev tool;
`check=True` also means a `CalledProcessError`'s `.stderr` could itself carry
an unbounded amount of git output if `git` misbehaves, though that is a
secondary concern next to the missing timeout. **Confidence**: high — read in
full; `subprocess.run` here has no `timeout=` and no caller-supplied bound
was found nearby.

### F5 — `tools/run_gate_checks.py:86-93`, `_run`: entire gate/pytest profile run with no bound

```python
def _run(argv: list[str]) -> None:
    completed = subprocess.run(argv, cwd=ROOT, check=False)
```

**Failure enabled**: this is the outermost invocation of a full pytest
profile (`main` builds `argv` from `PROFILES[args.profile]`); no timeout
anywhere in the call chain shown. A single hanging test in a profile hangs
this process forever, with none of the profile's other tests ever reported.
**On mid-operation kill**: killing this process leaves the child `python -m
pytest ...` running unsupervised (no `creationflags`/`start_new_session`, so
on POSIX it would at least be in the same process group and typically die
with a terminal SIGHUP/Ctrl-C sweep; on Windows there is no such guarantee).
**Severity**: low — this is deliberately the outer profile runner, and
imposing an arbitrary global timeout on "run the whole gate suite" is a
product decision, not an obvious bug; still, "no bound at all" is a gap
against the plan's §4 invariant-8 wall-time axis if this path is ever reached
un-attended (e.g. from CI). **Confidence**: high the code is as shown; medium
on whether this is an accepted gap or an oversight — no comment discusses it,
unlike the deliberate `if timeout is not None` opt-out pattern seen elsewhere
(`tools/mutation_score.py`, `daedalus/kairos/evolution.py`).

## NOT findings (negative evidence retained)

- **`shell=True`**: zero sites in `daedalus/` or `tools/` (confirmed by the
  AST scan across all 101 `run`/`check_output`/`check_call` and 10 `Popen`
  call sites — `shell_true` is `False` everywhere).
- **83/101** `subprocess.run`/`check_output`/`check_call` sites *do* declare
  an explicit `timeout=` (`daedalus/accelerators.py`, `arch_memory.py`,
  `bookkeeper.py`, `build_exec.py`, `claude_bridge.py`, `core.py`, `dctx.py`,
  `desktop_runtime.py` ×4, `doctor.py` ×2, `dotenv.py`, `editor_context.py`
  ×3, `health.py` ×2, `ikarus_os.py` ×3, `loop.py`, `offload.py`,
  `runtime_registry.py`, `status.py`, `verifier.py` ×4, `council/publish.py`,
  `eval/ceiling.py` ×2, `eval/correctness.py` ×4, `eval/graph_delta.py`,
  `eval/mint.py`, `eval/provenance.py`, `hooks/_common.py`,
  `ignition/bundle.py` ×2, `ignition/checks.py`,
  `integrations/hermes/configuration.py`, `kernel/attempt_execution.py`,
  `kernel/promotion.py`, `kernel/promotion_trust_root.py`,
  `kernel/sandbox.py`, `mapping/render.py` ×2, `providers/codex_cli.py`,
  `providers/ollama.py` ×2, `runtimes/fixture_fault_collector.py`,
  `spine/bootstrap.py`, `spine/containment.py`, `spine/killswitch.py`,
  `structcore/churn.py` ×2, plus the `tools/` majority). This is genuinely
  good coverage, not a rubber stamp — the 18 exceptions above are the real
  minority.
- **5/6 `terminate()` call sites and the sampled `kill()` sites show
  correct wait-then-escalate discipline** with process-group/Job-Object
  containment where it matters
  (`daedalus/desktop_runtime.py::stop_ide`/`stop_ollama_transport`,
  `daedalus/integrations/hermes/runtime_adapter.py::_terminate`,
  `daedalus/spine/cancel.py::ManagedProcess`/`kill_tree`,
  `daedalus/adapters/subprocess_adapter.py::_stop_process`,
  `daedalus/spine/containment.py::wait`/`cancel`,
  `tools/smoke_tauri_sidecar.py::smoke`, `tools/gui_check.py::gui_run`,
  `tools/system_check.py::_web`/`_file_bridge`). None of these show a bare
  `terminate()` without a follow-up bounded `wait()` then `kill()`
  escalation.
- **`daedalus/kairos/evolution.py::evaluate_single`**'s unbounded
  `await process.communicate()` in the `else` branch (no timeout) is an
  **intentional, policy-gated** unbounded wait — it only executes when
  `self.limit_policy` does not enforce `wall_time`, i.e. under the master
  plan §4.1 owner-controlled `unbounded_execution` mode — not a silent gap.
  Not counted as a finding.
- **`tools/mutation_score.py::pytest_runner`**'s missing literal
  `timeout=` kwarg is the same pattern: `timeout` is threaded through
  `**run_options` only `if timeout is not None`. Noted above (F-adjacent,
  listed in the missing-timeout table with its caveat) because a caller that
  passes `None` gets a real unbounded `pytest` subprocess per mutant, but
  this is a parameterized default, not a hardcoded omission.
- **Windows-specific POSIX-only misuse**: none found. Every `os.killpg` /
  `SIGKILL`/`SIGTERM` site inspected (`hermes/runtime_adapter.py::_terminate`,
  `spine/containment.py::PosixSessionBackend`) is behind an explicit
  `os.name == "nt"` branch with a real Windows equivalent (`terminate()`/
  `kill()`, `GenerateConsoleCtrlEvent`+Job Objects) on the other side — this
  box is Windows 11 and the win32 branches were the ones actually read.
- No file under `daedalus/` or `tools/` calls `preexec_fn`.

## Ranked findings and packet recommendation

1. **F4** (`daedalus/kairos/worktree.py:716`) — highest severity: no
   timeout on the git call the *live* attempt spine uses for every worktree
   op, wider blast radius (index-lock contention blocks subsequent attempts
   too). Recommend its own fix packet, paired with F-gate1 below since both
   are "add `timeout=` to a git subprocess.run" fixes with the same shape.
2. **Gate1.py `_git`/`compose_candidate`** (lines 327, 527) — same shape as
   F4, confined to the Gate-1 rehearsal; worth fixing in the same packet as
   F4 rather than separately, since they're the identical defect.
3. **F2** (`tools/bootstrap_receipt.py:680`) — medium: unbounded
   `Popen.wait()` in the harness that specifically exists to prove
   concurrency safety; a hang silently drops its own coverage.
4. **F3** (`gui_check.py`/`system_check.py` PIPE-not-drained, 3 sites) —
   low-medium: converts a real hazard into a misleading gate failure, not a
   live leak; worth a small packet (background drain thread or
   `communicate()`-based polling) if gate flakiness under verbose server
   logging is ever observed.
5. **F1** (`ikarus_os.py::_claude_stream`) — low-medium, already bounded by
   a 5s kill-wait; fix is cheap (write via a thread, or bound the prompt) but
   not urgent given the existing containment.
6. **F5** (`tools/run_gate_checks.py::_run`) — low: likely an accepted
   product decision (don't truncate a full gate run), flag for an explicit
   owner call rather than a unilateral fix.
7. Remaining 12 missing-timeout dev-tool sites (`audit_swarm.py`,
   `build_tauri_sidecar.py`, `docs_reference_check.py` ×2, `funnel.py` ×2,
   `funnel_report.py`, `operability_drill.py` ×3, `watchdog.py` ×2) — low
   severity, short-lived `git ls-files`/`schtasks` calls; not worth a
   dedicated packet, but cheap to fold into any packet that already touches
   these files.
