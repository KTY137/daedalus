# G1-ARIADNE-03 — Frozen evaluator interpreter on Windows

Packet ID: G1-ARIADNE-03

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1 — owner-directed, controlled evolution

Owner: repository owner

Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`

Integration context: uncommitted `G1-ARIADNE-01/02` tree on branch
`codex/ikarus-computer-assistant-20260905`

Dependencies: `G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL`,
`G1-ARIADNE-02_CAMPAIGN_WORKBENCH`

Stage: 1 of the owner-directed 2026-09-05 loop (deliver in stages; the loop
does not end with this packet).

## Reproduced negative baseline (measured 2026-09-05)

Independent review of `G1-ARIADNE-02` (Odysseus, executed evidence, then
reproduced by hand) found that no live Ariadne campaign could nominate on the
owner's Windows 11 host:

- the frozen evaluator arm is spawned inside containment with a deliberately
  NULL stdin (`daedalus/spine/containment.py`, `hStdInput = None`) and one
  merged stdout/stderr log handle;
- `sys.executable` in a uv/venv on Windows is the venv launcher stub
  (`.venv/Scripts/python.exe`, 45 KB); given a NULL stdin it prints
  `warning: Making stdin inheritable failed` before the real interpreter runs;
- `_verify_frozen_evaluator_output` requires exactly one canonical JSON line,
  so every arm ended `failed` with blocker
  `baseline:AriadneCampaignError: frozen evaluator output is invalid`;
- the suite stayed green because the only end-to-end nomination test fakes
  `command_gate` and `verify_repository_head_revision`.

Raw evidence line (four fresh campaign ids, identical):

```
output repr: 'warning: Making stdin inheritable failed\n{"expected_sha256":"9d57…","observed_sha256":"1627…","passed":false}\n'
RAISED: AriadneCampaignError frozen evaluator output is invalid
```

The same warning line appears in the retained `G1-GENESIS-03` gate outputs;
Genesis parsers tolerate it, Ariadne's exact-output contract does not.

## Primary acceptance claim

A live Ariadne campaign on Windows reaches `nominated` through the real Git
HEAD check, real containment and the real frozen evaluator, with no test
double on the gate. The attempt identity is unchanged: `TaskSpec.gate_argv`
keeps the vendor-neutral literal `python`; only the spawn-time interpreter
resolution changed.

## Scope

This packet changes only stdlib-only evaluator interpreter selection, its
path-free provenance observation, the council launcher resolution found during
review, and focused tests. Evaluator source identity, gate budgets,
containment, receipts and promotion remain outside scope.

## Contracts and behavior

- `daedalus/ariadne/campaign.py`: new `_evaluator_interpreter()`; on `win32`
  it returns `sys._base_executable` when that file exists, otherwise
  `sys.executable`. Non-Windows behaviour is byte-identical to before. The
  frozen evaluator `command_gate` call uses it instead of `sys.executable`.
- `tests/test_ariadne_campaign_v0.py`: new
  `test_real_frozen_evaluator_reaches_nomination_without_gate_fakes`, a real
  `git init` repository, armed kill switch, no monkeypatch on the gate or the
  HEAD verifier; asserts blockers `[["exact-match-failed"],
  ["exact-match-failed"], []]`, statuses `failed, failed, passed`, outcome
  `nominated`, and that the primary checkout is untouched.

Forbidden and untouched: evaluator source and its CAS digest, the exact-output
binding check, TaskSpec/attempt digests, budgets, HTTP route, promotion path.

## Acceptance matrix

| Check | Result |
| --- | --- |
| new test before the fix | failed with the exact warning-prefixed output above |
| new test after the fix | 1 passed (6.36 s) |
| `tests/test_ariadne_campaign_v0.py` + `tests/interfaces/test_http_ariadne.py` (first fix) | 54 passed (40.8 s) |
| focused resolver/provenance/integration tests after the council refinements | 6 passed (8.2 s) |
| Windows named-stdio cleanup fault after an observed timeout | deterministic regression passed; 280 Council tests under XDist; 256 direct-child and 64 grandchild timeout stress cases with zero misclassification |
| campaign + HTTP + producer census after the refinements | 69 passed, 1 failed (77.3 s) |
| that failure, `test_real_outer_leases_allow_exact_campaign_replay`: `EffectLeaseExpired: effect lease is not valid yet` (lease `issued_at` later than the validating instant; no lease code in this diff) | passed alone (32.7 s) and in a full-file rerun: 34 passed (30.4 s); retained as a pre-existing timing flake |
| Ariadne + producer census + registry doors (pre-fix baseline) | 73 passed |
| Genesis backend cohort (pre-fix baseline, unaffected files) | 221 passed |

Cross-vendor council (Codex + Claude, degraded quorum: Google not signed in,
bench Ollama unreachable): see the section below once the transcript closes;
the council is advisory and gates nothing.

## Side packet landed in the same stage

The first council attempt returned `transport_error` for both seats within
100 ms. The Codex seat's cause: `CreateProcess` searches PATH but not `PATHEXT`, so the npm
`codex.CMD` shim that `shutil.which` finds was `not_on_path` for the runner.
`daedalus/council/vendors.py` now resolves a bare `argv[0]` against the
council environment's PATH before spawning (`_resolve_command`); a command
with a directory component is passed through untouched; an unresolvable name
still fails as `not_on_path`. Tests: new
`test_run_managed_resolves_a_bare_command_through_path_and_pathext`;
`test_live_true_actually_unlocks_dispatch` now compares the resolved binary
stem. Council suites: 149 passed.

## Cross-vendor council (advisory, 2026-09-05)

Bus: `runs/council/council-20260905T102457Z-75a7e4d1.jsonl` (hash-chained,
verify offline before quoting). **Degraded quorum: 2 of 4 vendors.** Google
(agy) is not signed in on the bench and the bench Ollama is unreachable, so
their independence was not obtained. Seats: OpenAI via codex-cli 0.153.0,
Anthropic via claude CLI; two rounds, round 1 blind. The Anthropic seat is a
self-review of Anthropic-authored code and is flagged as such in the bus.
The council promotes nothing; the tests below decide.

Dissents, by author:

- **Anthropic (falsifier, r1):** the fix is at the wrong layer; give the
  contained child a valid NUL stdin handle in containment and every gate,
  including Genesis, is cured without an interpreter swap.
  **OpenAI (maintainer, r2):** that CHECK is confounded, it changes stdin and
  the process-creation path at once; the controlled experiment is the same
  containment with `hStdInput` NULL vs an inheritable NUL handle.
  **Anthropic (security, r2):** a stdin-only fix keeps the trampoline hop
  between containment and the interpreter; the swap removes it.
  Status: **open, stage-2 question** (spine change, Minos/Cerberus review).
- **Anthropic (falsifier, r1):** `-I` does not imply `-S`; the base
  interpreter imports the base site-packages and `.pth` files.
  **Anthropic (security, r2):** the hazard predates the patch and is closed
  for both interpreters by `-S`, safe only because the evaluator is
  stdlib-only. Status: **applied** (measured: evaluator imports are exactly
  `hashlib, json, pathlib, sys`; `-I -S` runs under both interpreters).
- **Both seats (r1):** provenance is lossy, the resolved interpreter is not
  recorded. **Anthropic (r2):** recording the path would leak the user
  profile directory into receipts; record version, implementation and binary
  SHA-256 instead. Status: **applied** as observation schema `/2`.
- **OpenAI (security, r1):** the test runs PATH-resolved Git with ambient
  hooks and config. **Anthropic (r2):** skip is the wrong remedy, scrub the
  environment. Status: **applied** (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_NOSYSTEM`,
  `GIT_TEMPLATE_DIR`).
- **Both seats (r1):** no unit witness for the resolver. Status: **applied**.
- **Anthropic (falsifier, r1):** resolution inside the per-trial loop.
  **OpenAI (r2):** flagged as an implementation instruction inside evidence,
  not evidence. Hoisted anyway; one resolution per campaign is now asserted.
- **Both seats (r1):** the integration test discriminates only on hosts whose
  `sys.executable` is a launcher stub. Accepted; on other hosts it is a live
  witness of nomination, not of this fix. Recorded here rather than faked.
- **OpenAI (r1):** the Windows fallthrough to `sys.executable` could retain
  the defect. **Anthropic (r2):** a venv always exposes `_base_executable`
  and a non-venv interpreter has no stub, so that branch is only reached by
  interpreters that never printed the warning. Unit test pins the branches.
- **OpenAI (r1/r2):** Podman compatibility unproven. Not applicable on this
  host; the non-Windows branch returns the pre-patch value byte-for-byte.

Convergence (an observation, not a vote): both seats agree the Genesis gates
remain affected because `service.py:1291` still maps `python` to the launcher
stub, and that interpreter resolution belongs in shared, backend-aware
command selection. Two vendors with overlapping training data agreeing is
weak evidence; the Genesis half is not measured here and is stage-2 work.

Refinements landed after the council (all in `daedalus/ariadne/campaign.py`
and `tests/test_ariadne_campaign_v0.py`): resolver hoisted above the arms
loop; `-S` beside `-I` at spawn; `_interpreter_provenance()` (implementation,
version, platform, binary SHA-256, never a path) recorded in the evaluator
observation, schema bumped to `daedalus-ariadne-evaluator-observation/2` with
`/1` still verifiable for retained records; Git environment scrubbed in the
integration test; one-resolution-per-campaign and no-home-path assertions;
parametrized unit tests for the resolver and the provenance helper.

## Council transport findings (measured 2026-09-05, corrected 13:20)

- **Cause of the `transport_error` seats, corrected.** The first reading
  ("no `cli.council` door, so the CLI guard refuses") was wrong about the
  cause. `runs/budget/ledger.json` shows `spent_usd 5.0` for the day since
  10:54, and reproducing the council's exact Claude argv with the process
  guard installed returns the guard's own text:
  `BUDGET REFUSED: spend ceiling would be crossed ... period_ceiling=$5.0000,
  spent=$5.0000, remaining=$0.0000`. The CLI council was refused correctly by
  the daily ceiling. The missing `cli.council` registry row remains a real,
  separate gap (see G1-KERNEL-01, stage 2b).
- **Honest disclosure.** The review council recorded above and its probes
  were run in-process through `session.convene(..., live=True)`, which did not
  install the process guard, so those vendor calls (two rounds, two seats,
  plus four single-prompt probes, and two `room.py ask codex` calls from the
  owner's room skill outside the repository) were **not priced against the
  ledger** and ran past the exhausted ceiling. That is a bounded-effect
  bypass (plan invariant 8) committed by this session, not by the code
  author. It is now closed in code: `convene(live=True)` installs the net
  before the roster is chained (`daedalus/council/session.py`), and a
  `BudgetRefused` from a seat is recorded as the bus reason
  `budget_exhausted` instead of `transport_error` (`daedalus/council/vendors.py`).
  Tests: `test_live_true_installs_the_budget_net_before_any_vendor_spawn`,
  `test_live_false_does_not_touch_the_budget_net`,
  `test_budget_refusal_is_recorded_as_budget_exhausted_not_transport_error`;
  council suites 154 passed. The room engine is the owner's tool and is not
  changed here.
- The npm `codex` on PATH is 0.146.0; `~/.codex/config.toml` pins
  `gpt-6-astra` with reasoning effort `ultra`, which that CLI cannot serve
  (HTTP 400 "requires a newer version of Codex"). The VS Code extension
  bundles codex-cli 0.153.0 at
  `~/.vscode/extensions/openai.chatgpt-26.901.22334-win32-x64/bin/windows-x86_64/codex.exe`;
  a forwarding `codex.cmd` ahead on PATH lets the council and the room reach it.
  CLAUDE.md's "codex-cli 0.152.0 installed" refers to neither binary on PATH.

## Migration and rollback

The observation reader remains compatible with retained schema `/1` records.
Rollback is the scoped interpreter/council adapter change; retained negative
evidence and the unchanged evaluator artifact identity remain authoritative.

## Evidence, expected failures, and review

- The Genesis half is closed by `G1-KERNEL-01` and `G1-GENESIS-03`: both
  callers use the shared call-site helper, keep literal `python` in frozen
  identity, and record path-free provenance. The final fresh Chromium run
  passed all five gates without the launcher warning.
- Odysseus' remaining Ariadne-02 findings: first failed call returns no
  receipt (open); `ariadne_campaign_live` is a literal (**closed** in stage 2:
  `daedalus/interfaces/http/effects.py::mutation_route_wired` is the single
  route table for preflight, dispatch and the desktop projection;
  `test_ariadne_campaign_live_is_derived_from_the_wired_mutation_route`
  turns the flag off with the route); 40-hex guard
  untested (**closed** in stage 2: `test_source_revision_is_checked_against_the_real_git_head`,
  real Git, four shapes, no control state created, 4 passed); dirty working
  tree bound to a commit id (open); 400/409 conflict split (**closed** in
  stage 2: `CampaignIdentityConflict` in the kernel, mapped to
  `AriadneConflictError`, HTTP 409; corrupt retained state stays 400).
- `test_run_managed_kills_a_hang_and_reports_timeout` exposed a Windows cleanup
  race under host load (**closed** in release hardening): after the Job Object
  killed the process tree, an inherited named `stderr` handle could briefly
  make `TemporaryDirectory` cleanup raise WinError 32 and replace the already
  observed timeout with `spawn_error`. The runner retains file-backed stdin,
  stdout and stderr but uses OS-managed `TemporaryFile` handles, whose deletion
  waits for the final inherited handle. A deterministic cleanup-fault test and
  parallel direct-child/grandchild stress keep the timeout classification.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
