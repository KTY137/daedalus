# G1-WP-IKARUS-COMPUTER-LOOP-01

Packet ID: G1-WP-IKARUS-COMPUTER-LOOP-01
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-17 and G1-IKARUS-COMPUTER-01 trusted service; existing canonical Mission, spine, CAS and guarded model transport

Owner approval: conversation request `ja implmenetierer`, 2026-09-05.
Existing unrelated working-tree changes are retained.

## Primary acceptance claim

Primary claim: explicit computer requests use a bounded model proposal loop,
canonical MissionContract, canonical spine intents and existing CAS identities;
only the trusted ComputerService may execute an admitted tool.

## Scope

Scope: `daedalus/orchestration/ikarus/computer_loop.py`, additive command routing
in `shell.py`, tool-only response handling in `orchestration/llm_client.py`, and
focused tests. Dependencies: amendment 012 adoption and the trusted computer
adapter interface. Live effect activation requires that adapter's acceptance.
Forbidden: new event stores, schedulers, candidate host control, implicit remote
image/file transmission, software release changes, automatic repeated effects.

## Contracts and behavior

Explicit `/computer` commands route before software classification. The model
proposes a strictly validated tool or finish response within frozen policy,
step and time limits; only the trusted service executes tools. Canonical
mission and step artifacts retain observed outcomes. Finish text remains
advisory, and replay uses retained terminal evidence or requires reconciliation.
Owner setup, configuration, scheduling and context commands are absent from
the model's tool inventory.

Baseline: shell's voice returns text and hand proposes software work; there is
no general computer tool loop. Canonical leases and Mission contracts already
exist. General tasks explicitly mark repository/Twin inputs inapplicable.

## Acceptance matrix

Acceptance: model-selected tools pass only through ComputerService; unsupported
or malformed calls cause zero adapter effects; unavailable dependency and policy
denial are visible; steps and timeout stop further calls; tool failure prevents
a model's success claim; interrupted mission replay requires reconciliation;
same mission replay returns its recorded terminal result; local-only context
refuses remote providers/endpoints; existing software/chat routes retain behavior.
Fixtures use temporary storage and fake proposal/adapter seams. Real adapter
verification belongs to its packet; fake tools prove orchestration only.

## Migration and rollback

Rollback: remove command routing and disable computer capabilities; retain
canonical events/artifacts. Interrupted effects remain unresolved until inspected.
Review questions: can chat select authority, can a model forge completion, can
replay execute again, can context egress without an owner-configured permission?

## Evidence, expected failures and review

Builder evidence, 2026-09-05:

- `python -m pytest -q tests/test_ikarus_computer_loop.py tests/test_llm_client.py tests/test_ikarus_shells.py tests/test_ikarus_stream.py tests/test_ikarus_os_boundary.py`
  — 122 passed, 34 subtests passed in 182.12 seconds.
- After the additional setup-without-policy and postcondition-refusal checks,
  `python -m pytest -q tests/test_ikarus_computer_loop.py` — 24 passed in
  3.59 seconds. These are orchestration fixture results, not live host evidence.
- Existing command-menu discoverability now includes `/computer`; setup invokes
  the fixed owner setup adapter, and status displays actual tool availability.
- `npm.cmd run build` in `apps/web` stopped at existing ThemeStudio.tsx errors:
  `ThemeSpec` / `DeepPartial<ThemeSpec>` do not define `scene` (lines 140, 260,
  261). No theme files were modified by this packet. Frontend build acceptance
  remains blocked by that retained diagnostic.

The loop persists goals and step receipts. The later durable-work packet adds
one-shot schedule admission to the existing KairosScheduler and ticks through
the existing File Bridge watcher (or an explicit manual run-due command).
Automatic execution requires that matching watcher to remain running; no new
background daemon is introduced. Interrupted external effects require explicit
reconciliation and are never automatically repeated.
Model finish text remains advisory; postcondition evidence for still-enabled
browser/desktop and observation-backed vision operations is owned by the
independently checked adapter result.

v0.1.6 release supersession: the planner capability inventory omits every
`file.*` tool and path-based vision operation. The file-write/read trials below
predate the release fence and remain retained integration and negative evidence
only; they do not establish a shipping v0.1.6 file capability.

Live local-planner evidence (no paid provider, disposable workspace):

- Installed loopback model: `qwen2.5-coder:7b`; initial 25-second cold planner
  probe returned no usable response.
- Unconstrained text proposal trial produced invalid proposal shape and zero
  tools. This negative result motivated strict JSON-schema projection through
  the existing guarded Ollama transport.
- First schema-constrained trial proposed `file.write` with an empty optional
  hash. The adapter refused and created no file; optional-hash schema and
  planner instructions were corrected, retaining the rejected proposal.
- The next trial executed real `file.write` and `file.read` under canonical
  leases. Independent file read verified exactly `IKARUS_LOCAL_LIVE_FIXTURE`.
  The final model response exhausted the shortened 180-second admission, so
  its overall report remained blocked. This is positive file-tool evidence and
  negative task-completion evidence, never reported as a completed mission.
- A final trial using the normal 300-second bound completed in **248.609
  seconds**: the actual local model proposed file creation, verified file read,
  then a finish response. Exact fixture bytes were independently read back.
  No further live trials were run.
- A compact sanitized copy of all five positive and negative trial outcomes is
  retained in [local integration evidence](../evidence/ikarus-computer-local-2026-09-05.json).
  Canonical Mission, lease and artifact digests remain linked. Input/output
  token counts are explicitly unknown because the existing text transport does
  not return them. These evolving development trials are not a comparative
  benchmark.

Latest integration checks:
`python -m pytest -q tests/interfaces/test_computer_watcher.py tests/test_ikarus_computer_loop.py`
— 29 passed in 5.63 seconds. Existing watcher structural checks passed except
their historical global registry hash assertion, which predates the explicitly
registered computer interfaces. That frozen diagnostic is retained separately.
