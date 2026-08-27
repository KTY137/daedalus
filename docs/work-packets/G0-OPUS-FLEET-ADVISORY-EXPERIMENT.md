# G0-OPUS-FLEET — bounded advisory watchdog experiment

Iron Plan: `EXPERIMENT`

Iron Gate: `0`

Owner request: 2026-08-25 — retry Claude/Opus work every 20 minutes, use a
global fleet of 20 agents, and fall back to Codex when Claude is unavailable.
Owner clarification: 2026-08-26 — keep the supervisor active continuously,
observe whether Claude, Codex, or Daedalus sessions are already active, and
start one fleet session only when the machine is idle.

## Why this is an experiment

The requested writable fleet cannot be wired honestly today. The canonical
`provider.claude` and `provider.codex` registry rows are deliberately
`INVENTORY_ONLY`; no production caller owns the complete runtime authority,
workspace authority, observation authority, exact-head conformance evidence,
and terminal receipt chain. Bypassing those blockers from a timer would create
a second promotion-capable control path.

This packet therefore freezes the smallest useful alternative:

- vendor processes are completion-style reviewers with every tool disabled;
- they receive only explicitly selected, secret-scanned evidence;
- their output is advisory evidence in the existing Council transcript format;
- nothing edits a checkout, applies a patch, commits, merges, pushes, or
  promotes;
- one campaign has at most 20 global slots across all configured projects and
  is complete after those slots reach terminal records;
- LangGraph computes the pure slot plan only. The watchdog owns effects and
  durable operational state.

Deletion/replacement path: delete `experiments/opus_fleet_watchdog`, remove the
`fleet*` modes from `tools/watchdog.py`, and delete the optional pure planner
from `daedalus/langgraph_adapter.py`. The canonical Loop/Attempt/provider path
is unchanged.

## Frozen scope

- `docs/work-packets/G0-OPUS-FLEET-ADVISORY-EXPERIMENT.md`
- `daedalus/langgraph_adapter.py`
- `experiments/opus_fleet_watchdog/**`
- `tests/test_langgraph_adapter.py`
- `tests/test_opus_fleet_watchdog.py`
- `tests/test_opus_fleet_session_probe.py`
- `tests/test_opus_fleet_cli.py`
- `tests/test_opus_fleet_scheduler.py`
- `tools/watchdog.py` (thin dispatch/install/status wiring only)
- `.claude/watchdog/opus-fleet.json` (ignored local campaign configuration)

No plan or amendment file is in scope.

## Invariants

1. At most 20 planned work slots machine-wide, never 20 per project or
   provider.
2. Exactly one Claude/Opus probe reaches a vendor before any other slot.
3. Codex eligibility follows only a structured Claude wrapper with HTTP/API
   status 429, 503, or 529. Generic `blocked`, free text, authentication,
   timeout, malformed output, policy, budget, or kill-switch failures do not
   enable fallback.
4. A fallback is a fresh single-seat Council record; it never continues a
   possibly ambiguous Claude call.
5. Every slot is durably claimed before dispatch. A process restart changes an
   abandoned `in_flight` claim to `unknown`; unknown work is retained and is
   never automatically replayed.
6. Calls have finite call, spend, prompt-token, per-call time, parallelism, and
   campaign bounds. The campaign ID is the re-arm token: a completed campaign
   never starts again until the operator supplies a new ID.
7. Evidence paths are explicit and per-file secret-floor checked. Other
   registered projects remain disabled until their own configuration opts in.
8. Model output has no write path and no decision field. Independent gates and
   a human remain responsible for any later implementation or promotion.
9. The Windows task is least-privilege, logged-in-user only, shell-free at run
   time, hidden, `IgnoreNew`, available on battery, not idle-gated, and has an
   explicit two-hour execution limit.
10. The task fires every `PT20M`; a non-zero last task result is degraded, not
    healthy. No automatic restart is configured until unknown-outcome
    reconciliation is proven.
11. Every dispatch tick is admitted by a fresh, fail-closed session census.
    Real Claude/Codex process evidence and recent hook activity across the
    registered project set block a new fleet. Unknown or partial observation
    also blocks. A second census before fan-out narrows the race with a human
    session starting after the sole provider probe.
12. “24/7” describes the supervisor's availability, not an unbounded spend or
    an invented work stream. One campaign ID remains finite and one-shot; a
    new reviewed work packet/campaign ID is still the explicit re-arm token.

## Falsifiers / kill criteria

Stop and do not advertise the fleet if any test or live observation shows:

- more than 20 slot claims or any duplicate slot ID;
- any vendor tool request, checkout modification, commit, merge, or push;
- Codex started after an untyped/unknown Claude failure;
- more than one pre-probe vendor start;
- automatic replay of an `unknown` slot;
- evidence bytes sent after a secret-floor refusal;
- overlapping scheduled instances;
- a vendor call while the session census is busy or unknown;
- raw process command lines, PIDs, or absolute user paths persisted as session
  evidence;
- task settings that stop on battery/idle or omit the 20-minute interval;
- a campaign reported complete without one terminal record per planned slot.

If a write-capable fleet is still wanted later, it is a separate Gate-0 work
packet: activate one brokered Opus attempt at exact HEAD first, then one
brokered Codex fallback, then prove a single global claim coordinator. This
experiment supplies none of those activation claims.

## Acceptance evidence

- focused pure planner tests;
- failure-classification and no-fallback adversarial tests;
- durable claim/restart/one-shot tests;
- concurrency barrier with observed maximum starts;
- Council live-wire test with injected transports (no network in CI);
- scheduler contract tests plus exported live task inspection after install;
- dry-run plan for the local tensor campaign;
- primary checkout fingerprint before and after the dry run.
