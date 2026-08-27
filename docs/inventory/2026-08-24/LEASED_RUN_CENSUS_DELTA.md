# The leased run lands, the census does not move -- and the reason is one level below the door

Measurement session, g0 `main`, HEAD pinned at `df659738` for the entire
exercise (verified three independent ways below). Tests the falsifiable
prediction recorded in `eae9f72e`'s commit message and in
`runs/watchdog/mission-20260824/PROGRESS.md`: *this commit does NOT move the
census by itself; the number moves only with the next LEASED run at the
declared revision, because what the census counts is retained terminal
evidence.*

**Verdict, stated in two parts because they are two different systems:**

1. **Does the `python.attempt` Effect Lease door work?** Yes, measured.
   `tools/bootstrap_receipt.py --leased` acquired a lease, the attempt ran to
   a closed state (`COMPLETED`/`no_change`), the primary checkout stayed
   untouched, and the worktree was reaped cleanly.
2. **Does the write-surface census (`scripts/report_gate0_v3.py` /
   `build_gate0_report_v3`) surface that evidence?** No -- and it cannot,
   through this reporter, regardless of what any leased run leaves behind.
   `daedalus/gates/report_v3.py:623` calls
   `authenticate_repository_write_surfaces(projection)` with no `inputs=`
   keyword, so `_run_stage_verifiers` never executes and every one of the six
   authentication stages stays `absent` by construction. This is a separate,
   pre-existing gap from the door commit, pinned by its own test
   (`tests/gates/test_gate_report_v3_raw_input_composition.py`). The leased
   run did not fail to move the census; the census was never wired to look at
   what a leased run leaves.

The raw numbers: `repository_write_surfaces_total` before = **435**, after =
**435**. `report_sha256` before = after =
`5578bc3c7afb3beb80495f7f8ab1537d18b505076206702d8bb047188d05a8cb`. The two
report files are **byte-identical** (verified by direct `diff` and by
matching sha256 of the JSON bytes, not just the printed summary).

## 0. A note on the 435 vs. 410 in the B5 handoff

`docs/decisions-pending/B5_HANDOFF_COMMIT4.md` quotes `surfaces_total 410 ->
410` from the B5 branch's own test run. This document measures **435** at
`df659738`, not 410. That is not a discrepancy to explain away: the B5
handoff's 410 was measured on an earlier revision (the branch predates
`df659738`, which itself landed after five more B5 commits plus unrelated
work). `repository_write_files_scanned: 294` at `df659738` -- the scanner
counted more files and more syntactic write-effect callsites because the tree
grew. `unclassified:435` both before and after in this session is the
number that matters for the delta; 410 is a different revision's answer to
the same question, not a wrong answer to this one.

## 1. HEAD-continuity, verified three ways (a correction folded in)

I initially reported to the coordinator that HEAD "moved to `897405d0`
during the AFTER census." That was wrong, and the wrongness is itself
worth recording: it was caused by my own Bash tool's working directory
silently resetting to `/c/Users/nukei/Desktop/agent_env` (the archived
`checkpoint/2026-07-20-session` tree, a **different repository**) between
calls, not by anything happening in g0. A bare `git rev-parse HEAD` issued
from that wrong cwd returned the archived tree's HEAD, which had moved
(two unrelated "promotion: the owner's signing key..." commits landed
there), and I misread that as g0 drifting.

Corrected, and reproduced with paths anchored inside a single command so
there is no cwd ambiguity:

```
$ cd /c/Users/nukei/Desktop/agent_env_g0 && pwd && git rev-parse HEAD
/c/Users/nukei/Desktop/agent_env_g0
df659738cec52cf46aa135383e63909f0852571f
```

```
$ git -C /c/Users/nukei/Desktop/agent_env_g0 reflog -3
df659738 HEAD@{0}: commit: docs: patch deleted-file references and regenerate architecture state
eae9f72e HEAD@{1}: commit: spine: the attempt door consumes the lease it is handed, and the lease may precede the intent it authorises
74b9be69 HEAD@{2}: commit: room: a coordination near-miss on the attempt-lease door, caught before any file changed
```

```
$ git -C /c/Users/nukei/Desktop/agent_env_g0 merge-base --is-ancestor 897405d0a1691622ccba2790b5eee216973c8316 HEAD
(exit 1 -- NO)
$ git -C /c/Users/nukei/Desktop/agent_env_g0 branch --all --contains 897405d0a1691622ccba2790b5eee216973c8316
  checkpoint/2026-07-20-session
```

g0 `main` never moved. `897405d0` and its parent `2239dd08` exist only on
`checkpoint/2026-07-20-session`, the archived tree's branch, visible in g0's
object database (shared/fetched refs) but never an ancestor of g0 `main`.

The measurement chain itself (BEFORE census, leased run, AFTER census) is
independently proven to have run against g0 and not the archived tree,
because `/c/Users/nukei/Desktop/agent_env` has **neither** the census script
nor the lease flag:

```
$ ls -la /c/Users/nukei/Desktop/agent_env/scripts/report_gate0_v3.py
ls: cannot access '.../scripts/report_gate0_v3.py': No such file or directory
$ grep -c '"--leased"' /c/Users/nukei/Desktop/agent_env/tools/bootstrap_receipt.py
0
```

A run against the wrong tree would have failed outright with a traceback, not
coincidentally produced a matching, well-formed 435-surface report. All three
census runs (before, after, and a third re-derivation done in the same
command as the `cd`/`pwd`/`HEAD` check below) hash identically.

## 2. BEFORE census

Command (killswitch confirmed `armed` immediately before, at
`C:\Users\nukei\.daedalus\control\2ea46e496ce4\killswitch`):

```
$ git rev-parse HEAD
df659738cec52cf46aa135383e63909f0852571f
$ python scripts/report_gate0_v3.py . --source-revision df659738cec52cf46aa135383e63909f0852571f
```

(interpreter: `/c/Users/nukei/AppData/Local/Microsoft/WindowsApps/python.exe`)

Exit code: `1` (expected -- `main()` returns `0 if report.closed else 1`, and
Gate 0 is not closed; this is not an error).

Full raw JSON (122,605 bytes) saved at
`runs/gates/lease-wall-census-20260824/census_df659738.json`,
sha256 `d8638fa22b9243ba8cdb5077a2e538fb44ff540acdc84e86520b47fe73661659`.
Key fields, quoted verbatim from the parsed report:

```
schema: daedalus-gate-report/5
closed: False
source_revision: df659738cec52cf46aa135383e63909f0852571f
report_sha256: 5578bc3c7afb3beb80495f7f8ab1537d18b505076206702d8bb047188d05a8cb
registry_sha256: 0323d243e3954bad30022e04b6d573359c359611557d07dac3294bff00040303
repository_write_inventory_schema: daedalus-gate0-repository-write-inventory/2
repository_write_classification_schema: daedalus-gate0-repository-write-classification/2
repository_write_inventory_sha256: cec7203410900fc5a3c4c6eb07378234459c085a670c596f1e60ab82137e9e1c
repository_write_scan_input_sha256: 49094fee42bfde6bc43788169d90d4100082dfa5ffc7f2cdae64b8aa8c91a915
repository_write_files_scanned: 294
repository_write_scanner_error: 0
repository_write_surfaces_total: 435
repository_write_surface_verdicts: ['unclassified:435']
repository_write_failures: [list len 435]
runtime_conformance_failures: ['runtime-conformance-receipts:unbound:no-persisted-receipt-bundle']
fault_injection_failures: ['whole-matrix:unbound:no-verdict-at-cited-revision:candidates=gate0-matrix-2026-08-17,gate0-matrix-20260818-closure,gate0-matrix-20260818-head,gate0-matrix-20260818-morning']
blockers: [list len 446]
diagnostics: [list len 136]
```

Sample of `repository_write_failures` (first 6 of 435, verbatim):

```
daedalus/accelerators.py:174:17:process_effect_unknown:subprocess.run:dynamic-command:verdict=unclassified
daedalus/accelerators.py:343:17:process_effect_unknown:subprocess.run:dynamic-command:verdict=unclassified
daedalus/accelerators.py:94:17:process_effect_unknown:subprocess.run:dynamic-command:verdict=unclassified
daedalus/adapters/subprocess_adapter.py:247:24:process_effect_unknown:asyncio.create_subprocess_exec:create_subprocess_exec:verdict=unclassified
daedalus/adapters/subprocess_adapter.py:290:8:ambiguous_stdlib_binding:session.process.stdin.write:rebound-or-conflicting-binding:verdict=unclassified
daedalus/adapters/transport.py:38:12:ambiguous_binding:self.path.parent.mkdir:rebound-or-conflicting-binding:verdict=unclassified
```

Every one of the 435 rows ends `verdict=unclassified` -- **cleared = 0** (no
row anywhere carries `verdict=cleared` or an authentication tag), so
"authenticated" is trivially 0 as well: nothing cleared, so nothing was
eligible to authenticate. This is the honest zero the task brief warned to
distinguish from a silent-failure zero -- I confirmed it is a real "measured
and found nothing to clear," not an instrument that couldn't measure, by
reading why it is structurally zero (Section 4) rather than trusting the
absence of a `cleared:` verdict on faith.

## 3. The leased run

Command (single line, no `--live`, see rationale below):

```
python tools/bootstrap_receipt.py --single --leased --local-only \
  --repo-root . \
  --instruction "Gate-0 lease-wall census probe: measurement run, no functional change requested." \
  --paths docs/inventory/2026-08-24/LEASE_WALL_PROBE_TARGET.md \
  --gate-paths tests/gates/test_gate_report_v3_cli.py \
  --task-id lease-wall-census-probe-20260824 \
  --base-revision df659738cec52cf46aa135383e63909f0852571f \
  --out runs/spine/bootstrap/lease-wall-census-probe-20260824.json
```

**Why no `--live`:** read `daedalus/offload.py:833` before running anything.
`stamped_offload_runner` in `tools/bootstrap_receipt.py` calls `offload(...)`
without `effect_authorization=`/`effect_execution=`, so even with `--live`
passed, `offload()` would hit its own `if effect_authorization is None or
effect_execution is None: return {"action": "effect_lease_required", ...}`
refusal -- `--leased` on this CLI acquires the **`python.attempt`** lease
(via `acquire_attempt_lease`), a different lease from **`python.offload`**'s,
which `bootstrap_receipt.py` never wires in. So `--live` here would not have
produced a real candidate edit either way; it would only have added a real
local-model planning call for no measurement gain. Running without it is not
a shortcut around the mechanism under test -- `TaskAttempt.run()` creates the
isolated worktree (`git worktree add -b`, the exact mutation the lease
covers per the commit message) unconditionally, independent of the `live`
flag, so the lease/terminal-record path is exercised either way. `offload.py`
confirms: `if not live: return _offload_impl(...)` and `_offload_impl` with
`live=False` returns `{"action": "would_offload", ...}` -- a deterministic,
zero-cost, zero-risk routing decision, no model call.

Raw stdout, verbatim:

```
state              : no_change
base_revision      : df659738cec52cf46aa135383e63909f0852571f
artifact           : 0 bytes  []
gate               : None
worktree_removed   : True  cleanup_error=None
primary quiet      : True  (delta appeared=[])
candidate leaked   : []  clean=True
promotion_allowed  : False
  at base revision : False -- no discrimination measurement exists, so a green gate means only that the configured gate command ran
  at live head     : False -- no discrimination measurement exists, so a green gate means only that the configured gate command ran
receipt: C:\Users\nukei\Desktop\agent_env_g0\runs\spine\bootstrap\lease-wall-census-probe-20260824.json
```

Exit code `2` (`EXIT_NO_CANDIDATE` -- `main()` returns
`EXIT_OK if state == "clean" else EXIT_NO_CANDIDATE`; state was `no_change`,
which is a normal, expected outcome given no `--live`, not a failure).

Full receipt at `runs/spine/bootstrap/lease-wall-census-probe-20260824.json`
(gitignored by `runs/spine/*`, left in place as local evidence). Load-bearing
fields from `attempt`, verbatim:

```
"state": "no_change",
"base_revision": "df659738cec52cf46aa135383e63909f0852571f",
"artifact": {"changed_paths": [], "byte_length": 0, "diff_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
"worktree_removed": true,
"cleanup_error": null,
"lease_id": "bootstrap-lease-wall-census-probe-20260824-python.attempt-daedalus-attempt-lease-wall-census-probe-20260824-00e08fd2-0440cc-a4eeff60",
"lease_outcome": "COMPLETED",
"lease_error": null,
"reaped": [{"action": "deleted", "reason": "tip is unchanged since allocation and is still reachable from refs/heads/main; no work is lost"}]
```

`primary_unchanged: true`. `primary_leak.no_candidate_path_reached_the_primary_checkout: true`.
`primary_leak.head_unchanged: true`. HEAD confirmed `df659738` immediately
before and immediately after this run (both checked with `git rev-parse
HEAD` in the same working directory as the command itself).

**This is a genuine, retained terminal record**: a `python.attempt` Effect
Lease was granted, consumed, and closed through `_resolve_and_finish` with
outcome `COMPLETED`, stored in `runs/spine/spine.sqlite3` (the SpineLedger)
and in the receipt JSON above. The peer's mechanism works exactly as
`eae9f72e` describes.

## 4. AFTER census

Same command, same pinned revision, run after the leased attempt completed
and after re-confirming HEAD unchanged:

```
$ git rev-parse HEAD
df659738cec52cf46aa135383e63909f0852571f
$ python scripts/report_gate0_v3.py . --source-revision df659738cec52cf46aa135383e63909f0852571f
```

Result: **byte-identical** to the BEFORE report.

```
$ diff before_census.json after_census.json
(no output -- files are byte-identical)
$ sha256sum before_census.json after_census.json
d8638fa22b9243ba8cdb5077a2e538fb44ff540acdc84e86520b47fe73661659  before_census.json
d8638fa22b9243ba8cdb5077a2e538fb44ff540acdc84e86520b47fe73661659  after_census.json
```

`repository_write_surfaces_total: 435` (unchanged). `repository_write_surface_verdicts:
['unclassified:435']` (unchanged). `report_sha256` identical. `runtime_conformance_failures`
still `['runtime-conformance-receipts:unbound:no-persisted-receipt-bundle']`
(unchanged -- I passed no `--conformance-receipts` directory, and nothing in
this run's own production path persisted one; see Section 4a).

A third re-derivation, done in the same shell command as the `cd`/`pwd`/`HEAD`
check to remove any ambiguity about which repository it ran against, hashes
identically (`d8638fa2...`, matching both above). Three independent
invocations, same bytes, every time.

### 4a. Why the runtime-conformance side stays unbound too

Separately from the `inputs=` gap (Section 5), nothing in production calls
`daedalus.kernel.runtime_conformance.persist_conformance_receipt` or
`assemble_recorded_conformance` at all -- both functions exist only as
definitions plus test-only callers:

```
$ grep -rn "persist_conformance_receipt\|assemble_recorded_conformance" --include="*.py" daedalus/ tools/ scripts/
daedalus/kernel/runtime_conformance.py:59:def assemble_recorded_conformance(
daedalus/kernel/runtime_conformance.py:125:def persist_conformance_receipt(
daedalus/kernel/__init__.py: (re-exports only)
```

No caller in `daedalus/spine/attempt.py` or anywhere else in the production
path. Even a real `--conformance-receipts <dir>` pointed at an empty
directory would still bind `bound=False` with the same
`blocker:runtime_conformance_receipts:unbound` diagnostic
(`daedalus/gates/runtime_conformance_binding.py:117-128`), because nothing
ever writes a bundle into that directory in the first place. This is a third,
independent gap from the same family -- evidence exists in principle
(`RuntimeConformanceReceipt` is a real typed schema) but nothing wires a real
attempt run to produce and persist one.

## 5. The structural finding: why no leased run could ever move this reporter's `authenticated` count

`daedalus/gates/report_v3.py:619-682`, function `_classify_repository_write_surfaces`,
is the only place this reporter computes cleared/authenticated counts. Its own
docstring (`report_v3.py:589-598`) states the property plainly:

> "Authentication is composed here, in process. This reporter hands
> `authenticate_repository_write_surfaces` nothing but the projection it just
> built, and that function has no parameter a stage report could arrive
> through: stages exist only when it was given RAW inputs and ran all six
> verifiers over them itself. No raw stage input is wired into this reporter
> yet, so every stage is `absent`, every surface is unauthenticated..."

The call site, verbatim, `report_v3.py:623`:

```python
authentications = authenticate_repository_write_surfaces(projection)
```

No `inputs=` keyword. Compare the function signature it calls,
`daedalus/gates/repository_write_classification.py:1087-1112`:

```python
def authenticate_repository_write_surfaces(
    report: "RepositoryWriteClassificationReport",
    *,
    inputs: RepositoryWriteAuthenticationInputs | None = None,
    ...
) -> dict[...]:
    ...
    return _compose_authenticated_surfaces(
        report,
        _run_stage_verifiers(report, inputs) if inputs is not None else {},
        ...
    )
```

`inputs is None` at the one production call site, so `_run_stage_verifiers`
never executes, `stage_reports = {}`, and every
`SurfaceEvidenceAuthentication.authenticated` composed from it is `False` for
every stage-applicable surface -- unconditionally, independent of revision,
independent of any lease, independent of whether a real attempt ran a minute
ago or never.

This is not a bug I am reporting as new; it is a **deliberate, pinned
property** confirmed by its own test,
`tests/gates/test_gate_report_v3_raw_input_composition.py:1-11`:

> "Before this, the composition accepted stage reports somebody else had
> built and only checked their type and their binding... Here the only way a
> stage report exists on the report path is that `_run_stage_verifiers`
> invoked that stage's verifier, in this call, over raw material. Two AST
> pins hold the shape: the reporter calls the composition with the
> projection alone and no keyword at all, and no function on the report path
> declares a parameter that could carry a stage report."

There is a second, independent reason `cleared` itself cannot move through
this exact CLI even before authentication is considered:
`build_gate0_report_v3` accepts a `repository_write_classification_input:
Path | None` parameter (`report_v3.py:788`, docstring at `:792-797`: "Omitting
it leaves every blocking surface unclassified, which is the fail-closed
default"), but `scripts/report_gate0_v3.py`'s own `argparse` parser
(`scripts/report_gate0_v3.py:23-41`) has **no flag that reaches this
parameter at all** -- only `repository_root`, `--source-revision`, and
`--conformance-receipts` are defined. So `classification_input` is always
`None` at this entrypoint, `cleared` is always `0`, and the question of
whether `authenticated_cleared` could exceed `cleared` never even arises
through this CLI. Two independently-sufficient reasons, either one alone
enough to keep this measurement flat.

**Consequence for the peer's prediction:** the retained terminal evidence
this leased run left behind (Section 3) is real, and the `python.attempt`
Effect Lease door genuinely closed the gap `B5_HANDOFF_COMMIT4.md` described.
But "the number moves only with the next LEASED run... because what the
census counts is retained terminal evidence" turns out to be **half right**:
the commit that unblocked the door landed and didn't move the census (true,
confirmed), but a leased run completing afterward *also* didn't move it
(measured, this document) -- not because the run failed to produce evidence,
but because the census reporter this whole conversation has been calling
"the census" was never wired to consume any run's evidence, leased or not.
Moving `authenticated_cleared` off zero needs two more things, neither of
which exists yet: (a) a `repository_write_classification_input` declaration
reachable from this CLI (or a caller of `build_gate0_report_v3` that supplies
one) to get `cleared` above 0, and (b) `report_v3.py` supplying a real
`RepositoryWriteAuthenticationInputs` (built from things like this leased
run's lease receipt, the runtime-conformance receipt nothing persists yet
per Section 4a, and the other four stage inputs) to
`authenticate_repository_write_surfaces(projection, inputs=...)`. Both are
open work, not "already done and just not showing."

## 6. Files touched by this measurement session

- `runs/gates/lease-wall-census-20260824/census_df659738.json` -- the raw
  report (before = after = this file, sha256
  `d8638fa22b9243ba8cdb5077a2e538fb44ff540acdc84e86520b47fe73661659`).
- `runs/spine/bootstrap/lease-wall-census-probe-20260824.json` -- the leased
  run's full receipt (gitignored by `runs/spine/*`, left on disk).
- `runs/spine/spine.sqlite3` -- SpineLedger, carries the terminal lease
  record (gitignored, pre-existing tracked path pattern).
- `docs/inventory/2026-08-24/LEASED_RUN_CENSUS_DELTA.md` -- this document.
- One appended row, `runs/watchdog/mission-20260824/PROGRESS.md`.

No file under the peer's off-limits list (`daedalus/spine/attempt.py`,
`daedalus/kernel/offload_lease.py`, `tests/kernel/test_attempt_lease.py`,
`tools/bootstrap_receipt.py`, its tests) was edited -- all were read-only for
this session. `docs/inventory/2026-08-24/LEASE_WALL_PROBE_TARGET.md`, the
path declared as the leased attempt's write scope, was never created --
`--local-only` without `--live` means `offload()` never reached its write
branch (`_offload_impl` returned `would_offload` before any file I/O), which
is exactly the "genuinely real, zero-risk" property this run was chosen for.

**UPDATE 2026-08-26**: Gate 0 closed (657c8af5). This measurement documents a pre-closure state. The structural finding (Sections 4–5) about the reporter wiring remains valid and carries forward to any successor work.
