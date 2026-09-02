# W7 — Kill-switch reach audit (`daedalus/spine/killswitch.py`)

Base: local `main` @b3cc415b (session tree shows `wip/g1-freeze-2026-08-31` /
`b3cc415b`, dirty: 1 file under `runs/`, unrelated to this audit). Static read
only; no files modified except this one.

## Enumeration

Exact commands run (all read-only):

- `Read daedalus/spine/killswitch.py` (1259 lines, full file).
- `Read daedalus/spine/effect_boundary.py` (full file, 3729 lines, in three
  `Read` calls: 1-1276, 1277-1886, 1886-2686, plus 2686-2986 for `begin_effect`
  and the conformance scaffolding after it).
- `Grep 'killswitch|KillSwitch|should_stop|LoopHalted|\.checkpoint\(\)'` over
  `daedalus/` → **17 files** (listed below), and over `tools/` → 3 files
  (`continuous_daedalus.ps1`, `operability_drill.py`, `agent_findings.py`).
  `runs/` matches were data/log artifacts (tsv/jsonl/txt), out of scope.
- `Grep 'killswitch|KillSwitch|kill switch|kill_switch'` scoped to
  `daedalus/spine/effect_boundary.py` alone → 6 matches, all either prose in
  an `EntrypointSpec.notes` string or the `cli.killswitch` row itself; **zero**
  matches inside the body of `begin_effect`.
- `grep -c '        id="'` and a small `.venv/Scripts/python.exe` text-parse of
  `effect_boundary.py` (no test execution, pure regex over the source text) to
  enumerate every `EntrypointSpec` row and its declared `effects`/`wiring`.
- `Grep 'acquire_attempt_lease|acquire_wave_offload_lease|acquire_chip_eda_lease'`
  over `daedalus/` to find every issuer call site.
- Targeted `Read`/`Grep` of: `daedalus/loop.py`, `daedalus/build_exec.py`,
  `daedalus/kernel/offload_lease.py`, `daedalus/kernel/attempt_execution.py`,
  `daedalus/spine/attempt.py`, `daedalus/spine/picker.py`,
  `daedalus/spine/bootstrap.py`, `daedalus/ignition/gate1.py`,
  `daedalus/chip_design/cli.py`, `daedalus/core.py`, `daedalus/offload.py`,
  `daedalus/web_api.py`, `daedalus/interfaces/http/effects.py`.

**Public API surface of `KillSwitch`** (the "am I killed?" doors a caller can
invoke): `should_stop()` (never raises, latches True forever once tripped),
`__call__`/`is_set()` (aliases of `should_stop`), `checkpoint()` (raises
`LoopHalted` iff `should_stop()`), `read_state()` (one disk read, never
raises, defaults to `SwitchState(running=False, ...)` on every error path).
A second, independent mechanism exists one layer up:
`daedalus.kernel.offload_lease.kill_switch_generation(switch)` — raises
`WaveLeaseKillSwitchEngaged` (a `LoopHalted` subclass) if the switch is
stopped, else returns the permit-bytes-derived generation.

**Fail-open or fail-closed:** `read_state()` is fail-closed by construction —
every early return in the function is a `halt(...)`, and the *only*
`running=True` exit is reached after the token was positively read as
`"RUN"` and no stop marker was found (`killswitch.py:834-897`). Missing file,
unreadable file, oversized file, bad UTF-8, unknown token, unreadable marker,
even an internal exception in `control_check` — all become STOP. `should_stop()`
wraps `read_state()` in a bare `except BaseException` that also resolves to
STOP (`killswitch.py:912-927`). This is a **fail-closed** design, confirmed by
reading every branch, not inferred from the docstring's own claim.

**Registry enumeration:** `ENTRYPOINTS` in `effect_boundary.py` (built by
concatenating the base tuple with `_REMAINDER_PROVIDER_ROWS`,
`_IKARUS_CHAT_ROWS`, `_PHASE4_DOOR_ROWS`, `_LATE_DOOR_ROWS`,
`_PORTABLE_TOOL_ROWS`) contains **108 `EntrypointSpec` rows** total
(wiring: 92 CENTRAL, 8 INVENTORY_ONLY, 7 LOCAL_GUARDS, 1 ABSENT). Of those,
**104 rows** declare at least one of the six effects this task treats as a
"door" (`PROCESS_SPAWN`, `NETWORK_EGRESS`, `FILESYSTEM_WRITE`,
`REPOSITORY_MUTATION`, `SPEND`, `LISTEN_SOCKET`); the other 4 rows
(`adapter.subprocess.send`, `adapter.subprocess.interrupt`,
`adapter.subprocess.terminate` — `PROCESS_CONTROL` only — and
`cli.approvals` — `SECRETS` only) are outside that definition and excluded
from the table below by the task's own criterion.

## THE central question: does `begin_effect` check the kill switch?

**No.** Read in full (`effect_boundary.py:2688-2796`). It: looks up the row
in `REGISTRY_BY_ID`; refuses if the row is not `Wiring.CENTRAL`; refuses if
any `guard_contracts` name is unknown or its contract is not in
`GUARD_CONTRACT_IMPLEMENTED`; refuses if a requested effect is not declared;
matches supplied `GuardDecision`s 1:1 against `spec.guard_contracts` (refusing
missing, duplicate, undeclared, unevidenced, or `allowed=False` decisions);
and on success returns a content-addressed `EffectStartReceipt`. There is no
call to anything in `daedalus.spine.killswitch`, no read of a permit file, no
`kill_switch_generation` call, anywhere in that function or in anything it
calls. `GUARD_CONTRACT_IMPLEMENTED` (`effect_boundary.py:143-156`) lists
exactly ten contracts — `budget.process_guard`, `containment.attempt`,
`containment.worktree`, `file_bridge.crash_journal`, `provider.egress_policy`,
`provider.write_policy`, `promotion.owner_approval`, `runtime.adapter_profile`,
`spine.intent_ledger`, `web.authenticated_bind` — **none of them is a
kill-switch contract.** A row cannot even *request* a kill-switch check
through `begin_effect`; the vocabulary to ask for one does not exist there.

**Consequence, stated plainly: every row in the table below whose only anchor
is `begin_effect` gets zero kill-switch coverage from that anchor, full stop.**
"VIA begin_effect" is not a real category for this specific mechanism — I
checked, and it inherits nothing. Real coverage exists only where application
code, independently of `begin_effect`, either (a) constructs a `KillSwitch`
and calls `should_stop()`/`checkpoint()` directly, or (b) acquires a lease
through the shared internal issuer in `daedalus/kernel/offload_lease.py`
(reached only via `acquire_wave_offload_lease`, `acquire_attempt_lease`, or
`acquire_chip_eda_lease`), which calls `kill_switch_generation()` itself
before granting anything.

## The second mechanism, and how far it actually reaches

`daedalus/kernel/offload_lease.py` has one shared internal issuer function
(around line 2472-2940, taking `entrypoint_id` as a parameter) that all three
narrow public issuers delegate to. It performs the kill-switch check **first**,
before computing anything else for the request — the code comment says so
literally: `"-- 1. the kill switch, before anything is computed for this
wave --"` (`offload_lease.py:2530-2532`, `generation =
kill_switch_generation(live_switch)`). This is checked-before-the-effect
(no ordering bug at acquisition).

More importantly for the "checked once, never re-checked" question: the
granted lease is *not* handed a captured generation. Line 2937:
`kill_switch_generation_reader=lambda: kill_switch_generation(live_switch)`,
with the comment *"LIVE, not captured: the facade re-reads this at every
boundary, so an operator's stop during a running wave invalidates the lease
at the next start/finish instead of being noticed only after the spend."*
I confirmed this is genuinely live (a closure that re-calls the function),
not a frozen int — contrast with `rebuild_effect_lease_authorization`
(`offload_lease.py:945-1002`), a **replay/reconstruction** path that
deliberately captures the generation once (`generation = int(...)` at line
987, closed over at line 1000) because it rebuilds evidence for an *already
finished* execution — correctly not live, and not a live-execution gap.

So for the three doors that reach this issuer, the switch is re-checked at
every lease boundary (wave/attempt/EDA-run start and finish), not just once
at the top of a long run. The one honest residual gap is the one
`killswitch.py`'s own docstring already names: an HTTP request already in
flight when the latch fires is not aborted (bound 3, "NO NEW SPEND", not "no
in-flight spend"). I did not find a *new* ordering bug beyond that documented
one.

Callers of the three narrow issuers (`Grep
'acquire_attempt_lease|acquire_wave_offload_lease|acquire_chip_eda_lease'`
over `daedalus/`, then read each call site):

- `daedalus/ignition/gate1.py:906` → `acquire_attempt_lease` (the `cli.ignition` lane).
- `daedalus/chip_design/cli.py:2315` → `acquire_chip_eda_lease` (the `cli.daedalus_chip` lane).
- `daedalus/build_exec.py:612` (`WaveExecutor._acquire_wave_lease`, docstring:
  *"Once per wave, here, because this is the last scope that knows the whole
  wave"*) → `acquire_wave_offload_lease` (the `python.offload` / `cli.build_exec`
  lane, also reused by `daedalus/loop.py`'s `LoopDriver` and by
  `daedalus/core.py:_try_ikarus`, both of which construct `WaveExecutor`).
- `daedalus/offload.py:offload()` (lines 843-916) **hard-refuses** any
  `live=True` call that does not carry an already-issued
  `effect_authorization`/`effect_execution` (`action: "effect_lease_required"`)
  — so a caller cannot reach a live provider effect through `offload()`
  without having gone through one of the three checked issuers first. This
  makes `python.offload` coverage a structural property of `offload()`, not
  merely "whoever remembers to call the issuer."

I traced two *callers* of `offload_runner(...)` (the `TaskAttempt` runner that
wraps `offload()`) that do **not** supply `effect_authorization`:
`daedalus/spine/picker.py:2910-2922` (`cli.picker`, `daedalus improve --live`)
and `daedalus/spine/bootstrap.py:730` (`cli.bootstrap`, the SHADOW iteration).
Both pass only `runner=offload_runner(live=bool(args.live))` /
`runner=offload_runner(**kwargs)` with no lease. Given `offload()`'s hard
refusal, this means neither door can currently complete a *live* spend via
this path at all — every `--live` attempt from these two doors returns
`effect_lease_required` and writes nothing. That is a fail-closed dead branch,
not a kill-switch gap, but it does mean the registry's own SPEND/NETWORK_EGRESS
declarations for `cli.picker`/`cli.bootstrap` describe a capability that, as
currently wired, cannot fire — worth flagging to whoever owns those rows, out
of this audit's scope to fix.

`daedalus/spine/attempt.py:TaskAttempt` (the `python.attempt` implementation,
actually in `daedalus/kernel/attempt_execution.py`) accepts `cancel: Any =
None` and `attempt_lease: Any = None`, both optional
(`attempt_execution.py:1244,1256`). `_as_predicate(None)` returns `lambda:
False` (`attempt_execution.py:354-355`) — i.e. **never cancelled** when no
token is supplied. So `python.attempt`'s kill-switch reach is entirely
caller-dependent: the `cli.ignition` lane threads a checked lease; `LoopDriver`
threads `self.switch` as the cancel token; `cli.picker`/`cli.bootstrap`'s
direct `run_attempt(...)` calls (picker.py:2910, bootstrap.py:655) pass
neither `cancel=` nor `attempt_lease=` — so an attempt launched straight from
those two doors (independent of the offload-lease gap above — a `run_tests`
gate loop with no live provider call still runs) has no reachable kill-switch
check inside `TaskAttempt` itself.

`daedalus/file_bridge.py`'s local dispatch (`file_bridge.process` /
`file_bridge.watch`) routes through `daedalus/core.py:process_bridge_payload`
→ `_try_ikarus` for `lane in ("auto","local","local_only")`, which constructs
a `WaveExecutor` (`core.py:1262-1271`) and runs `run_mission(...)` through it
— same checked-issuer path as `cli.build_exec`. The `codex` lane is
hard-disabled (`core.py:1470-1491`, "provider.codex has not adopted the
canonical... seam"). The `claude` lane and any `local`/`auto` request that
`_try_ikarus` could not accept fall through to `_ask_claude_report`
(`core.py:1339-1359`), which is a **stub that performs no effect** ("Claude
dispatch is disabled on the canonical queue path"). So every effectful branch
reachable from `file_bridge.process`/`file_bridge.watch` either goes through
the checked `WaveExecutor` lease or is hard-refused before any effect.

`web.mutations` (`daedalus/web_api.py:DaedalusHandler.do_POST`, line 1021):
its only anchor is `begin_effect("web.mutations", ...)` at line 1028, which
(per the finding above) checks nothing kill-switch-related. `_handle_post`
delegates to `daedalus/interfaces/http/effects.py:handle_post`, which takes
an injected `EffectPorts` bundle of callables; I grepped that module for
`process_bridge_payload|_try_ikarus|offload_runner|WaveExecutor|run_attempt|offload\(`
and found **zero** direct references — the actual effect implementations are
behind ports assembled elsewhere in `web_api.py` that I did not have budget
to trace exhaustively to their leaf callables. I record this as **UNCLEAR**
rather than asserting coverage either way: I can prove `begin_effect` gives
`web.mutations` no coverage, and I could not, within budget, prove or
disprove that some specific mutation kind's port implementation happens to
call one of the three checked issuers downstream. Given every other CENTRAL
row I *did* trace to a leaf has either the checked-issuer path or no reachable
live effect at all, I'd flag this specific door for a follow-up trace rather
than assume the best case.

## Coverage table

Legend: **DIRECT** = the door's own call path constructs/consults a
`KillSwitch` or reaches the live, re-read `kill_switch_generation()` gate,
confirmed by reading the code. **NONE** = only `begin_effect` (or nothing)
stands between the door and its effect; confirmed no kill-switch call exists
on the path I could trace. **UNCLEAR** = anchor gives no coverage but a
downstream port could not be fully traced in budget. **PARTIAL** = coverage
depends on which caller reaches the shared implementation.

| door id | effects (of the 6 tracked) | wiring | kill-switch check |
|---|---|---|---|
| `cli.loop` | FS_WRITE, SPAWN, EGRESS, REPO_MUT, SPEND | CENTRAL | **DIRECT** — `LoopDriver.switch.should_stop()` every iteration (`loop.py:936`) + mid-wave (`loop.py:1250`) + `with self.switch.watch()` background sweep (`loop.py:1406`) |
| `cli.build_exec` | FS_WRITE, SPAWN, EGRESS, REPO_MUT, SECRETS, SPEND | CENTRAL | **DIRECT** — `WaveExecutor._acquire_wave_lease` → `acquire_wave_offload_lease` → live `kill_switch_generation`, once per wave, before any wave work |
| `python.offload` | FS_WRITE, SPAWN, EGRESS, SPEND | CENTRAL | **DIRECT** — `offload()` hard-refuses `live=True` without an already-checked lease (`offload.py:874-883`) |
| `cli.ignition` | FS_WRITE, SPAWN | CENTRAL | **DIRECT** — `gate1.py:906` `acquire_attempt_lease` → live `kill_switch_generation` |
| `cli.daedalus_chip` | FS_WRITE, SPAWN | CENTRAL | **DIRECT** — `chip_design/cli.py:2315` `acquire_chip_eda_lease` → live `kill_switch_generation` |
| `file_bridge.process` | FS_WRITE, SPAWN, EGRESS, SPEND | CENTRAL | **DIRECT** — local/auto lane → `_try_ikarus` → `WaveExecutor` (same issuer as `cli.build_exec`); `codex`/unaccepted-`claude` fall to a no-op refusal stub |
| `file_bridge.watch` | FS_WRITE, SPAWN, EGRESS, SPEND | CENTRAL | **DIRECT** (inherits `file_bridge.process`'s per-request coverage; the watch loop itself was not separately checked for its own idle-poll cancellation) |
| `python.attempt` | FS_WRITE, SPAWN, REPO_MUT | CENTRAL | **PARTIAL** — real when the caller threads `cancel=`/`attempt_lease=` (the `cli.ignition` lane, `LoopDriver`); **NONE** when it does not (`cli.picker`, `cli.bootstrap` call `run_attempt` with neither) |
| `web.mutations` | FS_WRITE, SPAWN, EGRESS, SPEND | CENTRAL | **UNCLEAR** — anchor is `begin_effect` only (no coverage there); downstream `EffectPorts` implementations not fully traced in budget |
| `cli.picker` | FS_WRITE, SPAWN, PROC_CTRL, EGRESS, REPO_MUT, SECRETS, SPEND | CENTRAL | **NONE** reachable — `begin_effect` only, and the live-spend branch (`offload_runner` with no lease) currently dead-ends at `effect_lease_required` before any kill-switch question would even matter |
| `cli.bootstrap` | FS_WRITE, SPAWN, PROC_CTRL, EGRESS, REPO_MUT, SECRETS, SPEND | CENTRAL | **NONE** reachable — same shape as `cli.picker` |
| `web.server` | LISTEN_SOCKET | LOCAL_GUARDS | **NONE** — bind-only local guard, no killswitch anywhere on path |
| `web.mutations_put` | FS_WRITE | CENTRAL | **NONE** — `begin_effect` only |
| `file_bridge.enqueue` | FS_WRITE | CENTRAL | **NONE** — `begin_effect` only (queue write, no dispatch) |
| `kernel.attempt.begin` | FS_WRITE | LOCAL_GUARDS | **NONE** |
| `kernel.attempt.complete` | FS_WRITE | LOCAL_GUARDS | **NONE** |
| `kernel.attempt.prepare` | FS_WRITE | LOCAL_GUARDS | **NONE** |
| `python.promote_candidates` | FS_WRITE, SPAWN, REPO_MUT | LOCAL_GUARDS | **NONE** — owner-approval gated, but not kill-switch gated |
| `adapter.subprocess` | SPAWN, EGRESS, FS_WRITE | CENTRAL | **NONE** — `begin_effect` only |
| `cli.enforce`, `cli.gui_lint`, `cli.runbook`, `cli.selftest`, `cli.shift`, `cli.structcore`, `cli.structcore_slice`, `cli.token_monitor`, `cli.arch_memory`, `cli.bookkeeper`, `cli.dctx`, `cli.doctor`, `cli.eval_ceiling`, `cli.eval_correctness`, `cli.eval_graph_delta`, `cli.memory`, `cli.web_api`, `cli.file_bridge`, `cli.mapping_drift`, `cli.mapping_inventory`, `cli.mapping_render`, `cli.status`, `cli.health`, `cli.progress`, `cli.project_memory`, `cli.eval`, `cli.benchmark`, `cli.wiki_plan`, `cli.wiki_verify`, `cli.killswitch` (its own operator door) | various | CENTRAL | **NONE** — `begin_effect` is the sole anchor on every one of these; no killswitch reference found anywhere in their modules |
| `python.command_gate` | FS_WRITE | CENTRAL | **NONE** |
| `worktree.reap`, `worktree.create`, `worktree.commit`, `worktree.cleanup` | FS_WRITE, SPAWN, REPO_MUT | CENTRAL | **NONE** — containment-gated, not kill-switch gated |
| `provider.claude`, `provider.codex`, `provider.deepseek`, `provider.deepseek.rollback`, `provider.ollama.rollback`, `provider.ollama_native`, `runtimes.fault_attestation_issuer`, `runs.gate0_matrix.verify_whole_matrix` | various | INVENTORY_ONLY | **NONE** — not even central-wired yet; irrelevant to `begin_effect` question but confirmed no killswitch reference in these modules either |
| `provider.ollama` | EGRESS, FS_WRITE, SPAWN | LOCAL_GUARDS | **NONE** |
| `memory.embeddings` | EGRESS | CENTRAL | **NONE** — `_authorize_egress` only |
| `mcp.runtime` | SPAWN, EGRESS, FS_WRITE | ABSENT | N/A — no implementation exists |
| `tools.guarded_call`, `tools.audit_swarm`, `tools.funnel`, `tools.gate_discrimination`, `tools.bootstrap_receipt`, `tools.operability_drill`, `tools.gate_host_preflight`, `tools.gui_check`, `tools.mutation_score`, `tools.audit_triage`, `tools.agent_findings`, `tools.lane_invariants`, `tools.funnel_report`, `tools.run_gate_checks`, `tools.system_check`, `tools.docs_reference_check`, `tools.desktop_sidecar_build`, `tools.desktop_sidecar_smoke`, `tools.codex_state_import`, `tools.desktop_release_assets` | various | CENTRAL | **NONE** — `begin_effect` only on every one; `tools/operability_drill.py` and `tools/agent_findings.py` merely *mention* `killswitch.py` (a drill test name / a high-stakes-files list), they do not call it |
| `runtimes.container_fault_driver`, `runtimes.fixture_fault_collector`, `runtimes.live_fault_collector` | various | CENTRAL | **NONE** |
| `runs.council.room`, `runs.council.summarize`, `runs.council.room_server`, `runs.council.room_server.post`, `runs.council.stream_hook`, `runs.council.dead_letter_replay`, `runs.ab.run_arm`, `runs.ab.score`, `runs.ab.oracle_check`, `runs.ab.blind` | various | CENTRAL | **NONE** |
| `daedalus.hooks`, `tools.watchdog` | various | CENTRAL | **NONE** |
| `ikarus_os.ask`, `ikarus_os.ask_stream`, `ikarus_os.provider_call` | EGRESS, SPAWN, SPEND, SECRETS | CENTRAL | **NONE** — the interactive chat door; distinct from `file_bridge.process`'s task-delegation door, and does not route through `_try_ikarus`/`WaveExecutor` |

Total: **104 doors** (6-effect definition). **8 DIRECT/PARTIAL-real**
(`cli.loop`, `cli.build_exec`, `python.offload`, `cli.ignition`,
`cli.daedalus_chip`, `file_bridge.process`, `file_bridge.watch`,
`python.attempt`-when-caller-cooperates), **1 UNCLEAR** (`web.mutations`),
**95 NONE** (including the 8's own inventory/local-guard siblings and every
tool/runs/provider/chat door). By count, roughly **8%** of registered
effect doors have a traced, real kill-switch check on their path; the
remaining ~92% reach their effect through `begin_effect` alone, which the
kill switch never touches.

## Findings

### F-W7-01 `begin_effect`, the canonical effect boundary, never checks the kill switch
- **file:line**: `daedalus/spine/effect_boundary.py:2688-2796` (whole function body); `GUARD_CONTRACT_IMPLEMENTED` at `effect_boundary.py:143-156`.
- **class**: killswitch-gap
- **severity**: HIGH (scope, not exploitability — this is an architecture gap, not a bypass of an existing check)
- **status**: CONFIRMED with quoted code. The function's full refusal ladder is: unregistered entrypoint → id mismatch → not-CENTRAL wiring → unknown guard contract → unimplemented guard contract → unknown requested effect → no effects requested → undeclared effect → duplicate/undeclared/missing/unevidenced/denied guard decision. No step reads `daedalus.spine.killswitch` or calls `kill_switch_generation`. `GUARD_CONTRACT_IMPLEMENTED` — the exhaustive set of contracts a row can even name — has ten entries, none related to the kill switch.
- **evidence**: see the full function quoted in the "central question" section above; `POLICY_CONTRACTS = frozenset(GUARD_CONTRACT_IMPLEMENTED)` (`effect_boundary.py:157`) is the only vocabulary `begin_effect` will accept.
- **reachability**: every one of the 92 CENTRAL-wired rows calls `begin_effect` at its declared anchor. For 84 of those 92 (all except the 8 in the DIRECT/PARTIAL bucket above), `begin_effect` is the *entire* protection story for that row — there is no other kill-switch-aware code anywhere on the path from the door to its effect.

### F-W7-02 Master-plan invariant 8's "always enforced at effect boundaries" is not implemented for the kill switch
- **file:line**: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §4, invariant 8: *"Egress, write roots, secrets, authorization, containment, evidence boundaries and a kill switch are always enforced at effect boundaries, not entrusted to prompts."*
- **class**: overclaim
- **severity**: HIGH (this is exactly the class of finding AGENTS.md's own review rules call release-blocking: *"a hook or instruction advertised as a complete security guarantee"*, and F-W7-01 shows the mechanism this sentence names as "always enforced at effect boundaries" is absent from the one function that implements "effect boundaries" in this repository)
- **status**: CONFIRMED with quoted code (F-W7-01) against quoted plan text. Six other items in that same sentence — egress, write roots, secrets, authorization, containment, evidence boundaries — each correspond to a real `GUARD_CONTRACT_IMPLEMENTED` entry `begin_effect` actually checks (`provider.egress_policy`, `provider.write_policy`, `budget.process_guard`/`spine.intent_ledger`, `containment.attempt`/`containment.worktree`, etc.). "A kill switch" is the one item in that list with **no** corresponding contract, and I verified `begin_effect` calls none of them for it.
- **evidence**: quoted plan sentence above; `GUARD_CONTRACT_IMPLEMENTED` dict (F-W7-01) as the negative evidence.
- **reachability**: this is a documentation/architecture claim, not itself an exploitable code path — but it is exactly the sentence an operator or a future implementer would read to believe every `begin_effect` start is kill-switch-covered, and 87 of 104 doors are not.
- **note**: `daedalus/spine/killswitch.py`'s own module docstring makes **no** such universal claim — it explicitly frames itself as the mechanism for "the unattended loop" and is careful, scoped, and (per my read) accurate about its own reach, including naming its own residual gaps (the in-flight-HTTP-not-aborted bound, the sub-poll-interval race, the uncontained-forgery caveat). The overclaim lives in the master plan's summary language, not in the module that would have to carry it out.

### F-W7-03 `cli.picker --live` and `cli.bootstrap` declare SPEND/NETWORK_EGRESS in the registry but cannot currently reach it — so the kill-switch question is currently moot for them, not answered
- **file:line**: `daedalus/spine/picker.py:2910-2922`; `daedalus/spine/bootstrap.py:730`; `daedalus/offload.py:868-883`
- **class**: killswitch-gap (conditional) / scope note
- **severity**: MEDIUM — not exploitable today (the branch dead-ends closed), but if a future change threads a lease into these two callers without also confirming which issuer supplies it, the existing `TaskAttempt(cancel=None)` default means no kill-switch check would exist unless that same change also threads `cancel=`
- **status**: CONFIRMED with quoted code. `run_attempt(...)` at both call sites passes `runner=offload_runner(live=...)` and no `attempt_lease`/`effect_authorization`; `offload()` returns `{"action": "effect_lease_required", ...}` for any `live=True` call lacking `effect_authorization` (`offload.py:874-883`), before any effect executes.
- **reachability**: both are registered CENTRAL doors (`cli.picker`, `cli.bootstrap`) reachable as `daedalus improve --live` and `python -m daedalus.spine.bootstrap`. Today: reachable, but self-refusing before any spend. This is why the coverage table marks them **NONE** rather than **DIRECT** — there is no live path to test the claim against yet, and the *code that would need the kill-switch check if this were ever wired up* (`TaskAttempt.__init__(cancel=None)`) has no default protection.

## What I did not cover

- **`web.mutations`'s full port graph.** I proved its own `begin_effect` anchor
  gives no coverage, but did not trace every `EffectPorts` callable assembled
  in `daedalus/web_api.py` to its leaf implementation within budget. Flagged
  UNCLEAR above rather than guessed.
- **`ikarus_os.ask`/`ask_stream`/`provider_call`'s eight sink functions**
  (`_ollama`, `_ollama_cli`, `_deepseek`, `_claude`, `_codex`,
  `_ollama_stream`, `_deepseek_stream`, `_claude_stream` in `core.py`) — I
  read the registry's own description of them (egress admission via
  `_provider_start`) and confirmed none of it mentions `killswitch`, but I did
  not individually open all eight sink function bodies.
- **`daedalus/interfaces/desktop/http.py`'s `_handle_post`** (a second,
  desktop-specific HTTP mutation handler distinct from `web_api.py`'s) — out
  of the file list this task pointed at (`daedalus/spine/killswitch.py` +
  `effect_boundary.py` + callers), not traced.
- **The four excluded PROCESS_CONTROL/SECRETS-only rows**
  (`adapter.subprocess.send/interrupt/terminate`, `cli.approvals`) — outside
  the task's own six-effect door definition, not analyzed for kill-switch
  reach.
- **Runtime/live behavior.** Everything above is static reading; no tests
  were run, no process was started, per the read-only mandate.
- **`daedalus/kairos/_gated_writes_legacy.py.src` and
  `daedalus/spine/receipts.py`** were grepped (both matched the initial
  killswitch pattern) but only for identifier/constant references
  (`ATTEMPT_KILL_SWITCH_REF`, docstring cross-references); neither contains a
  live kill-switch call of its own, confirmed by reading the matched context,
  not assumed from the grep alone.
