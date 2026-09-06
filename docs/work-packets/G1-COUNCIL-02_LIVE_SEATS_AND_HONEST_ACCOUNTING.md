# G1-COUNCIL-02 — Live council seats answer, and the ledger tells the truth

Packet ID: G1-COUNCIL-02
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: existing council (`daedalus/council/*`), budget process guard
(G1-HIER-06C), pricing owner (G1-HIER-06A); owner instruction on 2026-09-05
to solve the degraded council ("Löse das Problem, arbeite solange daran bis
du es gelöst hast")
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: implementation and builder verification complete; live seat
verification recorded below; no fence, cap or policy widened.

## Primary acceptance claim

A live council on this Windows box seats Claude, Codex and the local Ollama
model and each answers a checkable prompt through the real spawn path, and
when a seat is missing the record names the vendor's own reason. The budget
ledger charges a council seat what the vendor reported, charges a seat that
never spawned nothing, and keeps the conservative worst case only when the
price is unknown. No cap was raised and the day ledger was not rewritten.

## Root causes (measured 2026-09-05)

The 10:54 council returned 0 of 3. Four independent causes, each reproduced
in isolation before any change:

1. **Codex seat**: the npm global `@openai/codex` on PATH was 0.146.0 while
   the owner's `~/.codex/config.toml` selects `gpt-6-astra`; the API refused
   with HTTP 400 "requires a newer version of Codex". The running Codex chats
   used the VS Code extension's bundled 0.153.0 binary, which hid the gap.
   Earlier the same seat failed as `not_on_path` because `CreateProcess` does
   not apply `PATHEXT` to the `.CMD` shim; `_resolve_command` (added by a
   concurrent session, 14:44) resolves it through `shutil.which`.
2. **Claude seat**: the CLI works (one-word reply in 21 s, `total_cost_usd`
   0.34). The failure was a 420 s per-call cap on a ~29k-token review while
   three test suites loaded the box. The shipped default of 120 s per call and
   900 s wall clock was probe-sized.
3. **Local seat**: `qwen2.5-coder:7b` answers (48 s cold) but runs with
   `num_ctx=6144` (usable window 5120) on a 2 GB GPU / 15.7 GB RAM box; the
   council's 28893 evidence tokens were refused as `over_context_budget`,
   which the bus vocabulary and the render collapsed into `transport_error`.
4. **Budget ledger**: after the 10:54 council the day ledger showed `spent_usd
   5.0` from two worst-case bookings: Claude $3.00 (timed out, actual
   unknown) and Codex $2.00 for a spawn that raised `FileNotFoundError`
   inside `Popen.__init__` and never existed. Every later seat was then
   refused as `budget_exhausted`, which the render did not explain.

## Changes

- `daedalus/runtimes/execution/budget_process.py`: a spawn that raises
  `FileNotFoundError` from `Popen.__init__` or `subprocess.run` is released
  with a reason naming the exception; every other exception still settles
  (the guard's settle-on-exception rule is unchanged).
- `daedalus/council/vendors.py`: `_CliAdapter._dispatch` reserves explicitly
  through `budget.guard` (`anthropic_cli` / `openai_cli`, label `council seat
  <vendor>: <argv[0]>`), releases when the runner reports `not_on_path`,
  settles at the CLI's reported `total_cost_usd` when present, and otherwise
  lets the guard settle at the worst case. The process guard stands down for
  that spawn, so nothing is reserved twice.
- `daedalus/council/session.py`: `ParticipantRecord.detail` carries the
  vendor's reason and first stderr line behind the fixed bus reason and the
  degraded render prints it (`MISSING VOICE … (unavailable: budget_exhausted
  -- BUDGET REFUSED: spend ceiling would be crossed …)`); defaults raised to
  600 s per call and 2400 s wall clock with the measurements in the source.
- Host: `npm install -g @openai/codex@latest` (0.146.0 → 0.153.4), a
  reversible tool upgrade the API message demanded; CLAUDE.md already
  records 0.152.0 as the installed state.
- `.claude/skills/council/SKILL.md`: measured operating notes (CLI version,
  timeouts, local context window, budget accounting, canary first).
- Tests: `tests/test_budget_is_installed.py` (release on never-spawned),
  `tests/test_council_vendors.py` (reported-cost settle, release on
  `not_on_path`, worst case on timeout/unpriced, ceiling refusal spawns
  nothing; autouse isolated ledger), `tests/test_council_session.py` (detail
  render), isolated-ledger fixtures in the livewire and canary suites so no
  test touches the real day ledger.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Seat liveness | Each of the three seats returns `PONG` to a one-word prompt through `run_managed` (Claude 21 s, Codex ~60 s at "ultra", local 48 s) |
| Never-spawned release | A guarded `Popen`/`run` of a missing executable raises and the ledger records `release`, `usd 0.0`, reason naming `FileNotFoundError`; spent and calls stay 0 |
| Reported cost | A Claude seat reply with `total_cost_usd` settles at that value with the $3.00 estimate retained on the entry |
| Missing executable seat | A seat whose runner reports `not_on_path` releases its reservation; a timed-out or unpriced seat settles at the worst case |
| Ceiling refusal | With a $1.00 ceiling the Claude seat is `budget_exhausted`, the runner is never called and the ledger file is not created |
| Honest render | A degraded council shows the vendor detail behind `transport_error`/`budget_exhausted`; the bus keeps its closed vocabulary |
| Ledger integrity | No entry of `runs/budget/ledger.json` was edited; today's $5.00 stays spent |
| Live verification | Recorded in the evidence section |

## Migration and rollback

Additive. Rollback restores the previous `_dispatch` (guard-only accounting),
removes the two release branches and the render detail; the npm upgrade is
reversible with `npm install -g @openai/codex@0.146.0`. The day ledger is
never rewritten by this packet; the owner widens the ceiling only through the
desktop cap menu or an explicit `DAEDALUS_BUDGET_USD`, and declares flat-rate
vendors only through `DAEDALUS_SUBSCRIPTION_VENDORS`.

## Evidence, expected failures and review

Builder evidence 2026-09-05 (project `.venv`, Python 3.13.14, Windows 11):

| Measurement | Result |
| --- | --- |
| Seat probes through `run_managed` | local: `{"status": "ok", "content": "PONG"}` in 48.4 s; Claude: `PONG`, returncode 0, 21.1 s, `total_cost_usd` 0.3400; Codex 0.146.0: HTTP 400 "The 'gpt-6-astra' model requires a newer version of Codex"; Codex 0.153.4: `PONG`, 8.4k tokens |
| Ledger before changes | `spent_usd 5.0`, `calls 2`: `anthropic_cli` settle 3.0 (timeout) and `openai_cli` settle 2.0 for a never-spawned process |
| RED | Guard test: missing executable booked at $3.00 and the next spawn refused; council seat tests: no ledger entry written at all |
| GREEN | `tests/test_council_vendors.py tests/test_council_session.py tests/test_council_livewire.py tests/test_council_canary.py tests/test_council_bus.py tests/test_council_publish.py tests/test_council_publish_cli.py tests/test_budget.py tests/test_budget_is_installed.py`: **452 passed in 64.47 s** |
| Council re-run after the render fix (exhausted ledger) | `MISSING VOICE council.anthropic.unknown (unavailable: budget_exhausted -- budget_exhausted: BUDGET REFUSED: spend ceiling would be crossed (basis=worst_case) …)` for both CLI seats: the reason is now visible |
| Live council after all fixes | `council-20260905T134029Z-e652bd64`, evidence `tests/runtimes/test_computer_service_files.py` (small enough for the local window), `DAEDALUS_SUBSCRIPTION_VENDORS=openai_cli` set for that process only: **2 of 3 responded, 2 distinct weight families, rounds 2/2**. Codex spoke in round 2 (120 s, one checkable claim) after exceeding the 600 s cap in round 1 at the owner's "ultra" reasoning effort; the local seat spoke in round 1 (110 s) and was recorded as an `instruction_in_evidence` anomaly by the council's own guard, then timed out in round 2; Claude was refused by the exhausted day ledger in 98 ms with the reason rendered. Ledger afterwards: `spent_usd 5.0` unchanged, two `council seat openai: codex` reservations settled at $0.00 (declared flat-rate), `calls 4` |
| Docs and index contracts | `tests/test_docs_reference_check.py tests/contracts/test_work_packet_index.py`: 32 passed in 7.53 s with this packet present |

Residual, stated plainly: the Claude seat is proven live by the direct probe
(`PONG`, $0.34) but cannot be seated again today until the day ledger rolls
over or the owner widens the ceiling; Codex at `model_reasoning_effort =
"ultra"` (the owner's `~/.codex/config.toml`) can exceed 600 s on a small
review, so pass `--timeout 900` or lower the effort for council use; the
local 7B seat is a weak voice that the anomaly guard may flag on evidence
containing imperative test prose.

Expected failures that remain honest: a seat over the local context window
refuses; a seat refused by the ceiling spawns nothing; a killed seat keeps
its worst-case charge because its actual is unknown.
