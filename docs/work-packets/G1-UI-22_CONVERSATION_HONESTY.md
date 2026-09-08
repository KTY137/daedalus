# G1-UI-22 - Conversation honesty: cost, cause and confirmation

Packet ID: `G1-UI-22`
Artifact role: `primary`
Status: `built; focused suites green; shipped bundle not rebuilt`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `db38a762991b04cbc96c3cbed5209d6a517fa611`
Dependencies: `G1-UI-05, G1-UI-06, G1-UI-08 integrated. The additive envelope
llm fields are OPTIONAL: every acceptance case below passes with and without
them, so this packet lands and stays honest whether or not the parallel voice
lane emits them.`

## Primary acceptance claim

After one Ikarus turn, the cockpit states **what the run cost, how long it
took, why it ended, and exactly what a confirmed offer will run** — each word
derived from a field that actually arrived — without inventing a placeholder
for anything that did not arrive, and without regressing the four cadence
defects G1-UI-08 already closed.

The measured motivating failure: on 2026-09-08 `ikarus_os.ask('agent_env',
'verbessere Daedalus')` took **150.3 s** and returned `intent='error'`
[MEASURED 2026-09-08, lane brief]. Everything the reader saw for that was the
answer row `FEHLGESCHLAGEN · 150 s` — no provider, no duration, no cost, no
reason. `stampFor` returns early for `intent === 'error'`
(`apps/web/src/features/conversation/model.ts`) and dropped the provider with
it. This packet adds two rows to the Protokoll and one panel to an offer.

### The audit this packet was asked to do first (lane goal 2)

Three of the four cadence items named in the brief were **already fixed** by
G1-UI-08 and are deliberately NOT re-fixed here:

| claim | status at `db38a762` | evidence |
| --- | --- | --- |
| thread mint before paint | FIXED | `Conversation.tsx` appends the user turn and the empty Ikarus turn, then `await ensureThread(scope)` |
| `Ikarus denkt` lifecycle | FIXED | `model.ts::activityForTurn` derives five observed phases with German labels |
| stop affordance before EventSource | FIXED | `canCloseObservation = busy && Boolean(stream.current)` |
| per-delta Markdown re-parse | FIXED for settled turns | `MarkdownMessage` is `memo`; `elapsed` is passed only while `streaming && !text` |

What was **still true**: the receipt derivation *around* those memoised
components was not incremental. `Conversation.tsx` recomputed `stampForTurn`,
`ledgerFor`, `activityForTurn` for every turn and `citationsFrom` (a global
regex scan of the whole answer) for every settled turn, once per animation
frame, because `patchReply` returns a new array from `.map`. That is what this
packet fixes, and it is fixed with a **counting** test, not an assertion about
milliseconds.

## Scope

In scope (this lane owns these paths):

- `apps/web/src/features/conversation/model.ts` — additive `llm` narrowing, the
  frozen German copy maps, `costLabel`/`durationLabel`, the `execution` and
  `failure` ledger rows, `offerSubject`, `createReceiptCache`.
- `apps/web/src/features/conversation/Conversation.tsx` — incremental receipts,
  reading the `model_used`/`timeout_s` the start frame already carries, the
  confirm affordance, `runAction` consuming the one derived subject.
- `apps/web/src/features/conversation/OfferConfirm.tsx` — new, presentational.
- `apps/web/src/features/conversation/Ledger.tsx` — `memo` boundary only.
- `apps/web/src/features/conversation/MarkdownMessage.tsx` — optional
  `budgetSeconds` denominator in the empty-stream bubble.
- `apps/web/src/features/conversation/conversation.css` — `.offer-confirm`.
- `apps/web/src/shared/api/index.ts` — **types only**, additive widening of the
  two `onStart` handler parameters. No runtime change.
- `apps/web/src/features/conversation/conversation.spec.ts`,
  `apps/web/tests/conversation-honesty.spec.ts` — tests.
- `tests/contracts/test_work_packet_index.py` — three mechanically forced
  registry pins (see Migration and rollback; this is a declared deviation).

Explicitly out of scope:

- every other Python file, in particular
  `daedalus/orchestration/ikarus/shell.py`. The English refusal sentence, the
  English failure sentence, `_reply_in_german`, and the missing
  `verbessere`/`verbessern` act verbs belong to the voice/intent lanes.
- emitting the new `llm` fields, measuring provider cost, settling the ledger
  with an actual instead of the `$3.00` worst case — voice lane.
- `apps/web/dist/**` and `daedalus/resources/web_dist/**`. The shipped bundle
  is NOT rebuilt by this packet.
- `apps/web/src/shared/contracts/index.ts` — not owned by this lane, and not
  needed: `envelopeFrom(value: unknown)` narrows the `llm` block itself.
- re-fixing the four G1-UI-08 cadence items listed above.
- any live provider call. The measured budget state on this host already
  carried a `$3.00` reserve + `$3.00` settle against the `$5.00` daily ceiling
  on 2026-09-08 [MEASURED 2026-09-08, lane brief], so a second `anthropic_cli`
  call is refused by the process guard anyway. Every new field is exercised
  through fixtures.

## Contracts and behavior

### 1. The additive `llm` block (voice lane → cockpit)

All optional, all narrowed in `envelopeFrom`, all dropped when malformed:

| field | accepted | otherwise |
| --- | --- | --- |
| `attempts`, `num_turns` | safe integer `>= 0` | dropped |
| `cost_usd_measured` | finite `number >= 0`, **or literal `null`** | dropped |
| `cost_basis` | exactly `provider_reported` or `estimate` | dropped → renders `Basis nicht angegeben` |
| `duration_ms` | finite `number >= 0` | dropped |
| `stop_reason`, `subtype`, `model_used`, `stderr_tail`, `ledger_basis` | non-empty string, kept verbatim | dropped |
| `ledger_charged_usd` | finite `number >= 0` | dropped |

`null` for `cost_usd_measured` survives narrowing on purpose. "The provider ran
and reported no cost" (`null`, rendered `Kosten nicht gemessen`) and "no cost
information exists" (key absent, no cost fragment at all) are different facts;
collapsing them would destroy the distinction. `RouteStart` gains
`model_used` and `timeout_s`, both already emitted or requested on the `start`
frame.

### 2. Two new ledger rows

`LedgerKey` gains `execution` and `failure`. The order becomes
`route, context, refusal, editor, execution, answer, failure, mismatch, offer,
dispatch, cancel`.

**`execution`** exists only when at least one of `duration_ms`, a
`cost_usd_measured` key, `stop_reason`/`subtype`, or `num_turns` arrived. Its
datum joins the present fragments: `18,9 s (Anbieter) · 0,41 USD (gemessen) ·
Ende: Turn-Limit des Anbieters erreicht`. Tone is `bad` when the end value
starts with `error_`, `warn` when the cost is explicitly `null`, else `info`.
Its detail carries the browser-measured round trip (a *different* measurement,
named as such), the provider turn count, the attempts, the raw `stop_reason`
when a `subtype` overrode it, the model the run itself named when it differs
from the envelope's, the caveat **"Anbieter-Selbstauskunft; der Budget-Ledger
verbucht nach eigener Preisliste."** whenever a cost number is shown, the amount
the ledger actually charged when the backend relays it, and the clipped
provider stderr.

**`failure`** is the visible explanation a reader gets *without* opening the
disclosure. It fires on `envelope.intent === 'error'`, `origin.intent ===
'error'`, or `stream_interrupted === true`, and is **suppressed entirely when a
refusal receipt is present** — `refusalRow` already owns that fact, which is
what keeps the pinned key sequence `route,refusal,answer` intact. Its datum is
the first available of: the provider's end state, "Stream ohne vollständige
Antwort beendet", the attempt count, or `Kein Grund übermittelt`.

### 3. Only measured values are glossed

`PROVIDER_END_DE` translates exactly four values — `success`, `tool_use`,
`error_max_turns`, `error_max_budget_usd` — because those are the ones a run on
this host actually produced [MEASURED 2026-09-08, lane brief: `claude -p
--output-format json` ended `stop_reason='tool_use'`, and with caps
`subtype='error_max_turns'` / `subtype='error_max_budget_usd'`]. Any other value
is printed **verbatim**. Inventing German for a state nobody observed would be
the surface authoring a claim the provider did not make.

### 4. Cost is a self-report, never a settlement

`daedalus/kernel/policy/pricing.py` prices vendor `anthropic_cli` at a flat
`per_call_worst_usd` of `$3.00` with `basis=worst_case`, and the process guard
settles at the estimate when no actual is known; the CLI itself reported
`$0.4056` and `$0.4084` for the same calls [MEASURED 2026-09-08, lane brief].
The cockpit therefore never labels a provider-reported figure as the charged
amount. When `ledger_charged_usd` arrives, both numbers are drawn side by side.

### 5. The confirm affordance

`offerSubject(action, fallbackProject)` is the ONE derivation used by both the
panel and the queue request, with the fallbacks copied from the request path
(`project || currentProject`, `lane || 'local_only'`). The panel names Aktion,
Projekt, Lane, Ziel and Revision before any click, always states
**"Nominierung, keine Übernahme. Nichts wird automatisch gemerged oder
promotet; die Freigabe bleibt beim Owner."**, and:

- a `requires_confirmation: false` from the server does **not** auto-run
  anything; it earns the sentence "Der Server meldet
  „requires_confirmation: false“. Diese Oberfläche fragt trotzdem." A response
  flag is descriptive data, never UI-side authority.
- an action `kind` other than `queue_task` is drawn, `Loslegen` is disabled,
  and the panel says no execution path is known and nothing was sent. The
  cockpit does not guess an endpoint for a kind it has never been told about;
  `answerOffer` refuses it a second time behind the disabled control.
- a revision is a 40-character lowercase hex string or it is reported
  `unlesbar übermittelt`. `HEAD`, a short SHA, 39 or 41 characters, uppercase
  hex, a number and an object all fail closed and are never normalised into
  something that looks canonical.

### 6. Incremental receipts

`createReceiptCache(labelOf, resolveModule)` derives per turn and caches by
**turn object identity** in a closure-held `WeakMap`. `patchReply` replaces
exactly one turn object per animation frame, so an unchanged turn keeps its
receipt — including a reference-identical `rows` array, which is what makes
the new `memo(Ledger)` boundary actually skip work. Correctness rests on that
identity discipline; the counting case in the Node spec is the guard against a
future `setTurns` that rebuilds every turn.

### 7. German (lane goal 3)

Every deterministic cockpit string in `features/conversation/**` was already
German at `db38a762`; the requirement was already met and this packet keeps it
met by putting all new copy in three frozen exported maps that the Node spec
pins character-for-character. The remaining English a German user can see is
**backend assistant text**, which the cockpit renders byte-identically and
refuses to translate — rewriting it would make the surface author a claim the
server did not make. The new German reason sits beside it and says it is
derived.

## Acceptance matrix

Runner note: this repository has no Vitest. The unit runner is
`npm run test:app` → `node src/app/run-spec.mjs`, which esbuild-bundles
`features/conversation/conversation.spec.ts` and renders React through
`react-dom/server`. Browser cases are Playwright, driven against a built bundle
on loopback (see Evidence).

| id | case | expected | result |
| --- | --- | --- | --- |
| A0 | baselines before any edit: `npm run test:app`, `npx tsc --noEmit`, `tools/index_work_packets.py --check` | recorded, diffed line-by-line afterwards | PASS — 549/549, rc=0 no diagnostics, `473 tracked files, 407 packet IDs, 2 unassigned legacy artifacts` [MEASURED 2026-09-08] |
| A1 | the measured run shape narrows and renders | all nine fields survive; datum is exactly `18,9 s (Anbieter) · 0,41 USD (gemessen) · Ende: Turn-Limit des Anbieters erreicht`, tone `bad`, detail carries `Stop-Grund: tool_use`, `Turns des Anbieters: 2`, `Versuche: 1`, the self-report caveat and `Modell laut Lauf: claude-opus-5[1m]` | PASS |
| A2 | cost basis table: `estimate`, absent, `gemessen`, `provider-reported`, `true`, `1`, `null` | `(geschätzt)`; `(Basis nicht angegeben)`; every unrecognised literal drops to `(Basis nicht angegeben)` and NEVER renders `gemessen` | PASS |
| A3 | `cost_usd_measured: null` vs absent key | `Kosten nicht gemessen` vs no cost fragment at all; an otherwise clean run with a null cost is `warn`-toned; a run that ended in a provider error stays `bad` | PASS |
| A4 | a negative or NaN cost | dropped at narrowing; `llm` block empty | PASS |
| A5 | failure row: bare error, `attempts: 1`, `subtype: error_max_budget_usd`, `stream_interrupted`, error only on the origin | `Kein Grund übermittelt` / `Kein nutzbares Ergebnis nach 1 Versuch(en)` / `Anbieter beendet: Budget-Limit des Anbieters erreicht` / `Stream ohne vollständige Antwort beendet` (warn) / `Kein Grund übermittelt`; all carry the derived-line detail | PASS |
| A6 | unknown gloss key `wat_is_this`; `PROVIDER_END_DE` key set | `Ende: wat_is_this` verbatim; exactly the four measured keys | PASS |
| A7 | regression pins `keys(startedRows) === 'route,answer'` and `keys(refusedRows) === 'route,refusal,answer'` | unchanged, proving the failure row yields to a refusal | PASS |
| A8 | `ledger_charged_usd: 3` + `ledger_basis: worst_case`, browser `seconds: 150.3` | `Vom Budget-Ledger verbucht: 3,00 USD (worst_case)` beside the self-report caveat, and `Hier gemessen: 150 s (kompletter Rundweg inkl. Verlauf anlegen)` | PASS |
| A9 | `offerSubject` revision states: 40-hex, `HEAD`, short SHA, 39, 41, uppercase, number, object, absent | `valid` / `unreadable` ×6 / `absent`; `sourceRevision` undefined for every non-matching value | PASS |
| A10 | `OfferConfirm` static markup | names kind, project, lane, objective and the nomination sentence; `requires_confirmation:false` adds the flag-ignored sentence; an unknown kind disables `Loslegen` and says nothing was sent; `Loslegen` / `Nicht jetzt` / `Vorgeschlagene Aktion beantworten` all preserved | PASS |
| A11 | cadence counting: 40 settled + 1 live turn, instrumented `labelOf` / `resolveModule`, 200 single-turn delta patches | `resolveModule` calls IDENTICAL after 200 patches to after the first pass; `labelOf` growth `< 5 × 200`, not `40 × 200`; `receipts[0]` and its `ledger` array reference-identical across all 201 passes | PASS |
| A12 | browser: mint held 3000 ms, click `Senden` | the held mint is still unanswered when the user's text and `Anfrage wird angelegt` are visible, the frame beats half the hold, and zero turn-creation POSTs were made at that moment | PASS — see the correction below |
| A13 | browser: full `llm` block on a `final`, disclosure NOT opened | `18,9 s (Anbieter) · 0,41 USD (gemessen) · Ende: Turn-Limit des Anbieters erreicht` and `Anbieter beendet: …` visible; `.ledger-detail` count 0; the server's English sentence rendered byte-identically | PASS |
| A14 | browser: `stderr_tail` carrying `ANTHROPIC_API_KEY=sk-live-XXXX` and 900 filler chars | absent from `.turn-text`; absent while collapsed; after `Protokoll aufklappen` exactly one detail line, prefixed `Provider-stderr (gekürzt, ungeprüft):`, under 560 characters; no `a`/`code` element in `.turn-text` | PASS |
| A15 | browser: `queue_task` offer | panel shows kind/project/lane/objective/nomination before any click; zero queue POSTs before it; after `Loslegen` exactly one POST whose `project`/`objective`/`lane`/`conversation_id`/`turn_id` match what was displayed | PASS |
| A16 | browser: `source_revision` 40-hex vs 39 chars | `db38a762991b` with the full 40 in `title`; vs `unlesbar übermittelt` with the malformed value never displayed | PASS |
| A17 | browser: `requires_confirmation: false` | zero queue POSTs after a 1000 ms poll; the flag-ignored sentence visible; one POST only after a human click | PASS |
| A18 | browser: `kind: run_campaign` | `Loslegen` disabled, the "kein Ausführungsweg" sentence visible, zero queue POSTs after a 1000 ms poll | PASS |
| A19 | after: `npm run test:app`, `npx tsc --noEmit`, `tools/index_work_packets.py --check`, `pytest tests/contracts/test_work_packet_index.py` | FAIL-line diff against the baseline empty; tsc rc=0; registry clean | PASS — 612/612, rc=0 |
| A20 | regression: `tests/cockpit-stream.spec.ts` (12) and `tests/ide.spec.ts` (29) against the built bundle | green, including the `Loslegen` queue case and the `role=group` absence case | PASS — 12 passed, 29 passed [MEASURED 2026-09-08] |

Refusals (each one a test, not a promise):

| id | refusal |
| --- | --- |
| R1 | a server flag never becomes UI authority: `requires_confirmation: false` still requires a human click, and the panel says so |
| R2 | a malformed `cost_basis` never upgrades a self-report to `gemessen` |
| R3 | a non-40-hex revision is never normalised, truncated or shown as a revision |
| R4 | a turn with no execution evidence draws neither row — no `—`, no `unbekannt`, no grey placeholder |
| R5 | provider stderr never reaches `.turn-text`, never goes through react-markdown, never appears while the Protokoll is collapsed, and is never in the copied answer (`Antwort kopieren` writes `t.text` only) |
| R6 | backend assistant text is never translated, rewritten or suppressed |
| R7 | no new endpoint, store, event kind, retry or effect; zero legacy `**/api/ikarus/**` requests; one turn-creation POST per send |
| R8 | nothing in this packet reads a natural-language classification to grant or widen authority |
| R9 | no live `claude -p` probe; no write to `runs/budget/ledger.json` |

## Migration and rollback

No data migration. No schema change. No stored artifact changes shape: the new
`llm` fields are read out of an envelope the server already stores through
`_loop_shape`, and a resumed turn that lacks them simply draws no execution or
failure row.

Rollback is `git revert` of the single commit. The one non-local consequence is
the Work Packet registry: adding this document forces
`docs/work-packets/index.json` to be regenerated and forces three pins in
`tests/contracts/test_work_packet_index.py` (the `"N tracked files"` string,
the `counts` dict, and `expected_primary_ids`) to move.

**Declared deviation.** This lane's file ownership says "do NOT touch any Python
file", and the registry mechanically requires exactly those three pins to move
or `--check` and the contract test go red. The two instructions cannot both be
honoured. Chosen resolution: **update exactly those three pins and nothing
else, as the last edit before the commit, re-measured immediately beforehand**
— and say so here rather than doing it quietly. If the integrating agent
prefers zero Python edits from this lane, revert the packet document and the
index together; the source and test changes stand on their own.

`tests/contracts/test_import_scc_hierarchy.py` and the
`experiments/forest_v2` external-corpora re-measurement are **not triggered**:
no new module appears under `daedalus/`.

## Evidence, expected failures and review

Commands, exactly as run, from
`C:/Users/Administrator/Desktop/projects/daedalus-ignite-cockpit`:

```
(cd apps/web && npm ci)                                   # rc=0, node_modules was absent
(cd apps/web && npm run test:app)                          # BEFORE: 549/549 passed
(cd apps/web && npx tsc --noEmit)                          # BEFORE: rc=0, no diagnostics
.venv/Scripts/python.exe tools/index_work_packets.py --check
                                                           # BEFORE: clean, 473 tracked files
(cd apps/web && npm run test:app)                          # AFTER: 612/612 passed, 0 FAIL lines
(cd apps/web && npx tsc --noEmit)                          # AFTER: rc=0, no diagnostics
(cd apps/web && npx vite build --outDir <runs>/dist-test --emptyOutDir)
(node <runs>/serve-dist-test.mjs <runs>/dist-test 5200)
(cd apps/web && DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5200 \
   npx playwright test tests/conversation-honesty.spec.ts --reporter=list)   # 8 passed
(cd apps/web && DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5200 \
   npx playwright test tests/cockpit-stream.spec.ts --reporter=list)         # 12 passed
(cd apps/web && DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5200 \
   npx playwright test tests/ide.spec.ts --reporter=list)                    # 29 passed
```

All results above are [MEASURED 2026-09-08] on this host.

### Expected failures, recorded before the build

1. **The Vite source dev server cannot host these specs.** `stubLiveProject`
   routes `**/api/**`, and in dev mode Vite serves the real module
   `/src/shared/api/index.ts` — which that glob matches. The stub 404s the
   application's own code and the page renders blank. This was OBSERVED: the
   pre-existing `cockpit-stream.spec.ts` fails identically against a dev server
   [MEASURED 2026-09-08], so it is an environment property, not a regression.
   The browser cases therefore run against a **built** bundle emitted into a
   scratch directory and served on loopback.
2. **The shipped bundle is not proven by this lane.** `apps/web/dist/**` is
   tracked, was dirty from another agent at session start, and is mirrored by
   `tests/interfaces/test_web_distribution.py`. This packet does not rebuild or
   commit it, so `tools/gui_check.py` — which serves `dist` — would still drive
   the OLD bundle. Rebuilding the shipped bundle and its
   `daedalus/resources/web_dist` mirror belongs to an integration lane.
   **UNVERIFIED here.**
3. **The visible benefit depends on a parallel lane.** None of the new `llm`
   fields is emitted by the backend today. Every acceptance case passes with
   the fields absent, so this packet is landable and correct on its own, but
   the chat does not yet explain a real failure's cost until the voice lane
   emits them. Saying otherwise would be a claim without evidence.

### Requested from other lanes

- **voice → cockpit:** the eight optional `llm` keys above, with the exact
  literal spellings for `cost_basis`; `cost_usd_measured` as `null` (not
  omitted, not `0`) when the provider ran and reported nothing; `attempts`
  retained; optionally `ledger_charged_usd` + `ledger_basis`; optionally
  `timeout_s` on the `start` frame (the cockpit already reads the `model_used`
  and `auto_selected` that frame carries). `stderr_tail` must be
  credential-free **at the source** — the cockpit escapes, clips and hides it,
  but containment is not redaction. If redaction cannot be guaranteed, the
  honest fallback is a length-only report.
- **intent → cockpit:** an offered action keeps `kind`, `args.project`,
  `args.lane`, `args.objective`, `requires_confirmation`; a revision is
  `args.source_revision` as 40-character lowercase hex. A new `kind` must come
  with the endpoint that executes it; the cockpit will not guess and will not
  add a route.

### Review questions

1. Does any new string state something no observed field proves?
2. Can a malformed or hostile provider field reach the answer bubble, the
   clipboard, the Markdown renderer, or a request body?
3. Does the receipt cache stay correct if a future `setTurns` rebuilds every
   turn? (It does not; A11 is the guard and must not be deleted.)
4. Does anything here grant authority from text rather than from an explicit
   human action?

## Correction: A12 measured a runner, not a property (2026-09-08)

The first revision of A12 asserted the first frame under a fixed **500 ms**.
That constant was measured on the owner's workstation against a warm scratch
server (**282 ms**). On a cold GitHub Windows runner the same frame took
**619 ms** and the check went red: `[MEASURED 2026-09-08, run 34252316106]`
264 of 265 browser specs passed, this one alone failed, and the failure was
the stopwatch, not the cockpit — the retained evidence artifact records
`"first frame took 619 ms while the mint was held for 3000 ms"`.

Widening the constant would have surrendered the property quietly, which is
the failure mode this packet exists to prevent. The assertion now states the
causal fact instead:

1. the held mint is **still unanswered** when the frame is observed
   (`observed.mintAnsweredAtMs === null`, stamped inside the route handler),
2. the frame beats **half the hold** (`< mintDelayMs / 2`), a bound derived
   from the delay it must beat rather than from any host's speed,
3. zero turn-creation POSTs have been made at that moment (unchanged).

A paint that waits for the mint lands at 3000 ms and fails all three on any
host. `[MEASURED 2026-09-08]` mutation: inserting a 3200 ms await before the
optimistic paint in `Conversation.tsx` turns the spec red; restored, the eight
cases pass in 9.8 s against a freshly built bundle. The measured distribution
is retained here rather than hidden: 282 ms warm workstation, 619 ms cold CI
runner, both far below the 3000 ms hold.
