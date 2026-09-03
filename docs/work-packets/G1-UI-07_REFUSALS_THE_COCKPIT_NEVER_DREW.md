# G1-UI-07 - The refusals the cockpit never drew: the promotion verdict and the compute lanes

## Frozen packet metadata

- Packet ID: G1-UI-07
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 5b58f8c3a3125d5199a6c0c9cd10f5cc7512140b
- Dependencies: G1-UI-06 (work rail, live stream, status line chips) in the same
  branch; no backend dependency — both routes already exist and are unchanged
- Promotion authority: repository owner; no automatic merge, promotion, release,
  or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752`

> The effect-registry digest above was MEASURED on this checkout with
> `registry_sha256()` from `daedalus/spine/effect_boundary.py`. It differs from
> the `ac020278…` that G1-ENV-01 and G1-GATE-01 carry: the registry has moved
> since those packets were frozen. Copying their value forward would have made
> this line a rumour, which is the whole failure class this packet is about.

## Primary acceptance claim

The cockpit draws two refusals the backend has always spelled out and the
interface reduced to a number or dropped entirely: **why promotion is blocked**,
and **what compute this machine can actually use**. Both are read-only
projections of existing routes. Neither adds a control that could promote,
write, or widen authority, and both refuse the specific collapse their payload
is shaped to prevent.

## Baseline reproduced

Measured on this checkout, 2026-09-03, against the live server at
`127.0.0.1:8765`:

- `GET /api/governance` returns a `verdict` sentence, a `blockers` list with a
  `why` per blocker, and per gate the `question` it asks, its state in the
  five-word vocabulary, its `provenance` and its evidence, plus the `head`
  revision the verdict was computed against. The status line rendered
  `Promotion gesperrt · 2 Blocker` and dropped every other field. Both live
  blockers say the same thing in different words — the gate held at some commit
  and HEAD is not that commit — so a verdict drawn without the two revisions it
  compares was unfalsifiable on screen.
- `GET /api/accelerators/status` had **no caller in the cockpit at all**. On
  this machine it reports one visible RTX 5080, six frameworks with
  `probed: false` and the detail `deep probe not requested`, six lanes of which
  zero are `ready`, and a `claims` block asserting that visible hardware does
  not imply a ready backend and a ready backend does not imply semantic
  validity.

## Scope

In scope:

New:

- `apps/web/src/features/system/PromotionPanel.tsx`
- `apps/web/src/features/system/promotion.ts` (pure chip reading)
- `apps/web/src/features/system/ComputeSection.tsx`
- `apps/web/src/features/system/accelerators.ts` (pure), `accelerators.spec.ts`
- `apps/web/src/features/system/compute.css`
- `apps/web/src/shared/ui/useDialogFocus.ts` (the shared modal focus contract)
- `apps/web/tests/{promotion,compute,dialogfocus}.spec.ts`
- `tests/contracts/test_ui_event_kinds_have_words.py`

Changed:

- `apps/web/src/features/system/HealthPanel.tsx` (dialog contract, tone, rank)
- `apps/web/src/features/mission/Timeline.tsx` (event kinds, per-step verdict)
- `apps/web/src/app/StatusLine.tsx`, `apps/web/src/app/Cockpit.tsx`
- `apps/web/src/app/styles/{overlays,instruments}.css`
- `apps/web/src/shared/api/index.ts` (accelerator contract + getter)
- `apps/web/src/shared/contracts/index.ts` (the gate fields the panel reads)
- `apps/web/src/features/settings/Settings.tsx` (renders the compute section)
- `apps/web/src/app/run-spec.mjs` (registers the new pure spec)
- `apps/web/tests/{work,health,cockpit}.spec.ts`

Forbidden and untouched:

- every Python module under `daedalus/`. No route added, changed, or removed;
  the one Python file added is a test.
- the promotion path, policy, ledger, evidence, and approval mechanism.
- `daedalus/foundation/accelerators.py` and `daedalus/core.py` — read, not
  modified.

## Contracts and behavior

### The four collapses this packet refuses

Each has a test, and each test was mutation-checked by making the collapse and
watching it go red.

1. **`probed: false` is not `installed: false`.** The shallow accelerator answer
   reports every framework as not installed, because nothing ran. Consulting
   `installed` before `probed` — the obvious order — makes this machine claim
   six absent backends it never looked for. `frameworkReading()` consults
   `probed` first and the spec pins the ordering itself, not just its output.
2. **`cuda_ready: null` is not `false`.** A framework may be installed with the
   CUDA question still open. The reading keeps three outcomes where the payload
   has three.
3. **A terminal step's colour comes from the verdict, not the word.**
   `daedalus/progress.py` has no `failed` kind: a failure is `done` with
   `succeeded: false`. Painting `done` green told a reader a failed run finished
   well. Each step prefers its OWN `detail.succeeded` over the unit's, because
   that is where the unit verdict is derived from and a run can record two.
4. **`promotion_allowed` is not the gate aggregate.** It is derived from the
   discrimination gate alone — deliberately; `core.py` says the other gates
   "inform the operator; they do not get a vote". `state` is the worst-of-five
   across all of them. Colouring the chip from the boolean rendered a green
   "Promotion offen" while the write lane was UNCONFINED.

Alongside these, `unsupported` is drawn as a deliberate non-goal rather than a
failure — DLSS is "inspiration for DSS, not an executable Daedalus backend", and
red would read as something broken that someone should go fix.

### The deep probe is a button

`?deep=1` imports torch, cupy, warp and friends to ask each whether CUDA really
works. That is real work, so it happens when a person asks. The shallow answer
is labelled shallow on screen — `nicht geprüft — flache Antwort` — next to the
control that would change it, rather than presented as a result.

### What neither surface does

Neither panel offers a control that promotes, approves, writes, or widens
authority. The promotion panel closes with the sentence that promotion remains
bound to the owner's explicit approval, and a green gate row is drawn as a green
gate row, never as permission.

## Acceptance matrix

| # | Claim | Check | Result |
|---|---|---|---|
| 1 | The promotion verdict, blockers and gates are drawn from `/api/governance` | `tests/promotion.spec.ts` (5) | green |
| 2 | A governance read that failed is not drawn as "nothing in the way" | `promotion.spec.ts` | green |
| 3 | A green gate is not drawn as permission to promote | `promotion.spec.ts` | green |
| 4 | An unprobed framework reads as unchecked, never absent | `accelerators.spec.ts`, `compute.spec.ts` | green; mutation-checked |
| 5 | `cuda_ready: null` is neither ready nor unverified | `accelerators.spec.ts` | green |
| 6 | A visible GPU is never reported as a working backend | `compute.spec.ts` | green |
| 7 | The deep probe does not run unasked | `compute.spec.ts` | green; mutation-checked |
| 8 | A deliberate non-goal lane is not painted as broken | `compute.spec.ts` | green; mutation-checked |
| 9 | A compute read that failed is not an empty inventory | `compute.spec.ts` | green |
| 10 | The live backend still answers the contract this section reads | `compute.spec.ts` (unstubbed) | green |
| 11 | A failed run does not paint its last step green | `work.spec.ts` | green |
| 12 | Every recorded event kind has a German word | `work.spec.ts` | green |
| 13 | Both dialogs move focus in and return it to the opener | `health.spec.ts`, `promotion.spec.ts` | green |
| 14 | No autonomy level applies a draft without a click | `cockpit.spec.ts` | green; mutation-checked |
| 15 | Accessibility floor holds at 1440/1024 in both themes | `tools/audit.mjs` | 0 below floor |
| 16 | A green promotion flag never greens the chip while a gate is absent | `promotion.spec.ts` | green |
| 17 | The backend's own warnings reach the screen | `promotion.spec.ts` | green |
| 18 | Tab and Shift+Tab never leave either dialog | `dialogfocus.spec.ts` (8) | green; mutation-checked |
| 19 | `KIND_WORD` covers `EVENT_KINDS` in both directions | `tests/contracts/test_ui_event_kinds_have_words.py` (12) | green; mutation-checked |

## Migration and rollback

Additive and read-only. Rollback is deleting the four new source files, the two
new spec files, and reverting the touched files; no data, route, or stored shape
changes, so nothing needs migrating in either direction.

## Evidence, expected failures and review

### Builder evidence, 2026-09-03

Run from `apps/web` against the live server at `127.0.0.1:8765`:

- `npx tsc --noEmit` — clean.
- `npx vite build` — clean.
- `npm run test:app` — 160/160 passed (was 137 before this packet).
- `npm run test:motion` — 138/138 passed.
- `npx playwright test` — **93 passed, 1 skipped, 0 failed**.
- `uv run --frozen python -m pytest tests/contracts/ -q` — 99 passed,
  28 subtests passed.
- `node tools/audit.mjs --widths 1440,1024 --themes referenz,leitstand` —
  0 combinations below the floor.

Before this packet the browser suite ran 73 passed / 1 skipped / **1 failed**.
That failure was not a bug: `cockpit.spec.ts` demanded four autonomy levels and
had been red since `151b8d18` (2026-08-31) removed the two that applied a draft
with no click. A stale red assertion is worse than none — it was demanding the
interface offer back the exact control the removal took away. It now pins the
removal instead, verified by restoring `alles` and watching it go red.

### Mutations executed

| Mutation | Expected | Observed |
|---|---|---|
| check `installed` before `probed` | unprobed reads absent | 2 unit + 1 browser check red |
| `unsupported` → `bad` tone | non-goal painted red | 1 browser check red |
| `wasDeepProbed` → `true` | shallow answer claimed measured | 2 browser checks red |
| restore the `alles` autonomy level | auto-apply offered again | 1 browser check red |

Every mutated file was restored and verified byte-identical afterwards.

### Expected failures and residual risk

- The compute section's live check runs against **this** machine. On a host with
  no NVIDIA hardware the shallow payload differs; the unstubbed test asserts
  only contract shape and the lane-state vocabulary, not this box's values.
- The deep probe is untested against a machine where it succeeds — no CUDA
  framework is installed here, so the `ready` path is covered by a stub and by
  the pure spec, not by a live probe. **UNVERIFIED** on real hardware.
- Cross-vendor review remains unavailable: `council` is degraded (0/2) and the
  Codex quota is exhausted until 2026-09-07. The independent review for this
  packet is single-vendor, and that is a weaker signal than the repo's normal
  chain.

### Independent review, 2026-09-03

A reviewer in fresh context, given the delta and the plan but not the reasoning
behind the patch, returned 1 BLOCKING, 7 SHOULD FIX and 6 NIT findings. All but
one are fixed; the exception is stated below rather than quietly dropped.

Two process notes, because both affect how the evidence reads:

- The reviewer observed the tree changing under them and 5 test failures. The
  concurrent writer was **this builder**, adding the compute section in the same
  worktree, and three of those failures (`compute.spec.ts:85`, `:103`, `:147`)
  are exactly the three mutations being run at that moment. Re-run on a quiet
  tree: 0 failed. Reviewing a tree that is still being written to is a mistake
  in how the review was scheduled, not a defect in either party's work.
- The reviewer independently **confirmed** the claim about the stale autonomy
  assertion by reading `151b8d18` themselves rather than taking it on trust.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| B1 | BLOCKING | The chip and verdict coloured from `promotion_allowed` (the discrimination gate alone) and discarded `state`, the worst-of-five aggregate. A payload with a holding discrimination gate and an `absent` write-confinement gate rendered a GREEN "Promotion offen" with the blocker count suppressed — a screen reader said "Promotion offen" while the write lane was unconfined. | Fixed. `features/system/promotion.ts` is a pure `promotionChip()`: the word still answers the promotion question, the colour comes from the aggregate, the blocker count appears on both branches, and the panel prints both answers side by side. New regression test with the contested payload. |
| S1 | SHOULD FIX | The new autonomy guard could not fail: its regex matched neither removed level's real wording, so restoring both verbatim left it green. An assertion whose message is a safety claim and whose body cannot go red. | Fixed. It now asserts the removed **labels** are absent — mutation-verified by restoring `alles`. |
| S2 | SHOULD FIX | The promotion fixture claimed in its docstring to be "the shape this machine really returns" and was invented: wrong gate questions, `runs/gates/*.json` receipt paths the server cannot emit, gates marked INHERITED when all three are MEASURED, and a blocker `why` differing from its headline. One assertion checked for a path no server would send. | Fixed. Replaced with a verbatim capture of `get_governance(None)`; the constructed B1 payload is separate and labelled constructed. |
| S3 | SHOULD FIX | `governance.warnings` was dropped, including the one this machine emits today: "the current revision could not be read, so every revision-tied claim below is reported as unknown" — the sentence that makes the verdict checkable. | Fixed. Rendered in a `role="alert"` block, asserted in the suite. |
| S4 | SHOULD FIX | Focus was MOVED, not TRAPPED, while the comment claimed the trap and `aria-modal="true"` promised modality to AT. Two Tabs reached the theme controls behind the scrim. | Fixed. `shared/ui/useDialogFocus.ts` implements a real trap; `tests/dialogfocus.spec.ts` walks the ring with 20 real Tab presses in both panels. Disabling the trap reproduces the reviewer's exact leak (`studio-close`, `settings-refresh`, 20 controls reached) and turns 6 of 8 red. |
| S5 | SHOULD FIX | Moving `fraction_hint` to a `title` made the backend's explanation mouse-only; the browser test asserted the attribute existed, not that anyone could read it. | Fixed. The sentence is visible text again; the assertion checks visible text. |
| S6 | SHOULD FIX | `receipt_path`, `kill_rate_floor` and `high_risk_paths` were consumed through a local cast, so the shared contract described a smaller payload than the one being read and `tsc` could not catch a rename. | Fixed. Added to `GovernanceGate` against a measured field inventory; cast removed. |
| S7 | SHOULD FIX | The ten event kinds were copied into the browser test, so an eleventh kind would leave both the map and the test stale — the exact drift that caused the bug. | Fixed. `tests/contracts/test_ui_event_kinds_have_words.py` reads `KIND_WORD` out of the shipped source and binds it to `EVENT_KINDS` in both directions. Mutation-verified. |
| N1 | NIT | Comment said a verdict-less `done` stays "neutral"; the code and test say amber. | Fixed (wording). |
| N2 | NIT | Every step took the UNIT verdict, so a run with two `done` events painted both the same. `progress.py` derives the unit verdict from the event's own `detail.succeeded`. | Fixed. `stepVerdict()` prefers the event's own verdict and falls back to the unit's. |
| N3 | NIT | The panel printed the current `head` but never the gate's own measured revision, so "held at X but HEAD is Y" rested on prose. | Fixed. `measured_head`/`measured_at` are rendered when present. |
| N4 | NIT | `AnimatePresence` never sees a child removal, because the panels return `null` when closed, so the `exit` variants are dead code. | **Not fixed, deliberately.** It is the pre-existing pattern for every overlay in this cockpit; changing it here alone would leave two conventions, and changing all of them is a different packet's scope. Recorded as a known dead path. |
| N5 | NIT | A comment claimed `fraction_hint` is "the same sentence for every unit"; `progress.py` emits a different one for an unknown unit. | Fixed (wording). |
| N6 | NIT | A `write_allow` list under an `absent` confinement gate read as though those paths were guarded. | Fixed. The heading becomes "Deklariert, nicht durchgesetzt" when the gate is absent. |

The reviewer also tried and **failed** to break three claims, which is worth
recording as much as the findings: sealed promotion (the panel imports no API,
has no mutating control, and states the owner rule), focus return on both mouse
and keyboard paths for both panels, and the unknown-state colour/sort rule.
