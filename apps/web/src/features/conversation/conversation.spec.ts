import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { subprocessCancellationFrom, type ConversationView } from '@/shared/api';
import type { IkarusAskPayload } from '@/shared/contracts';
import { COMMANDS, helpText, looksLikeCommand, matchCommands, parseCommand } from './commands';
import { MarkdownMessage } from './MarkdownMessage';
import { OfferConfirm } from './OfferConfirm';
import {
  activityForTurn,
  cancelledObservation,
  conversationConfirmsProject,
  costLabel,
  createReceiptCache,
  durationLabel,
  envelopeFrom,
  ledgerFor,
  offerSubject,
  openDispatchesFrom,
  relativeTime,
  resumedTurns,
  settleTurn,
  stampForTurn,
  COST_BASIS_DE,
  HONESTY_DE,
  PROVIDER_END_DE,
  type Turn
} from './model';
import { createTextBatcher } from './streaming';

export interface ConversationSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

const labelOf = (id: string): string | undefined =>
  id === 'claude_code_cli' ? 'Claude Code' : id === 'ollama_http' ? 'Ollama' : undefined;

function keys(rows: ReturnType<typeof ledgerFor>): string {
  return rows.map((r) => r.key).join(',');
}

/**
 * The Protokoll is fed recorded frames and asserted exactly. Every case here
 * is a shape the backend was observed to emit (docs/superpowers/specs/
 * 2026-09-02-ikarus-agent-surface-design.md §4.2); none is invented.
 */
export function runConversationSpec(): ConversationSpecResult[] {
  const results: ConversationSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  /* ---- ledger: nothing arrived, nothing drawn ---- */
  const bare: Turn = { role: 'ikarus', text: '' };
  check('a turn with no frames has no ledger rows', ledgerFor(bare, labelOf).length === 0, keys(ledgerFor(bare, labelOf)));
  check('a note turn has no ledger', ledgerFor({ role: 'note', text: 'x' }, labelOf).length === 0);
  check('an empty envelope narrows to no fields', Object.keys(envelopeFrom({}) || { x: 1 }).length === 0);
  check('a non-object envelope is dropped', envelopeFrom('nope') === undefined && envelopeFrom([1]) === undefined);

  /* ---- ledger: the start frame alone ---- */
  const started: Turn = { role: 'ikarus', text: '', streaming: true, started: { intent: 'chat', shell: 'voice', provider_used: 'claude_code_cli' } };
  const startedRows = ledgerFor(started, labelOf);
  check('a start frame yields a live route row and an activity answer row', keys(startedRows) === 'route,answer', keys(startedRows));
  check('the route names only the runtime selection the start frame proves', startedRows[0]?.datum === 'Claude Code · ausgewählt', startedRows[0]?.datum);
  check('the streaming route is live', startedRows[0]?.tone === 'live');
  check('the empty stream names the observed route without claiming reasoning', startedRows[1]?.datum === 'Claude Code ist ausgewählt' && startedRows[1]?.tone === 'live');

  /* ---- live cadence: only facts already present on the turn ---- */
  const creating = activityForTurn({ role: 'ikarus', text: '', streaming: true }, labelOf);
  const accepted = activityForTurn({ role: 'ikarus', text: '', streaming: true, requestId: 41 }, labelOf);
  const routed = activityForTurn(started, labelOf);
  const writing = activityForTurn({ ...started, text: 'Hallo' }, labelOf);
  const cancelling = activityForTurn({ ...started, cancellation: 'requested' }, labelOf);
  check('a live turn advances through observed request phases',
    [creating?.phase, accepted?.phase, routed?.phase, writing?.phase, cancelling?.phase].join(',') === 'creating,accepted,routed,writing,cancelling');
  check('live phase copy says only what its fields prove',
    [creating?.label, accepted?.label, routed?.label, writing?.label, cancelling?.label].join('|')
      === 'Anfrage wird angelegt|Anfrage angenommen|Claude Code ist ausgewählt|Claude Code antwortet|Abbruch angefordert');
  check('a settled turn has no live activity', activityForTurn({ role: 'ikarus', text: 'fertig' }, labelOf) === undefined);

  const cancelledUnknown = cancelledObservation(undefined);
  check('a cancelled turn without a cancellation receipt stays explicitly unknown',
    cancelledUnknown.cancellation === 'unknown'
      && cancelledUnknown.text === 'Der Turn wurde als abgebrochen gemeldet. Abbruchzustand unbekannt.',
    `${cancelledUnknown.cancellation}|${cancelledUnknown.text}`);
  const cancelledConfirmed = cancelledObservation('confirmed');
  check('only a confirmed cancellation receipt says the server confirmed the cancellation',
    cancelledConfirmed.cancellation === 'confirmed'
      && cancelledConfirmed.text === 'Der Server hat den Abbruch bestätigt.',
    `${cancelledConfirmed.cancellation}|${cancelledConfirmed.text}`);

  /* ---- stream cadence: transport chunks become paint-sized batches ---- */
  let frameId = 0;
  const frames = new Map<number, () => void>();
  const delivered: string[] = [];
  const batch = createTextBatcher(
    (text) => delivered.push(text),
    (callback) => {
      frameId += 1;
      frames.set(frameId, callback);
      return frameId;
    },
    (handle) => { frames.delete(handle); }
  );
  batch.push('Hal');
  batch.push('lo');
  check('many transport deltas schedule one paint', frames.size === 1 && delivered.length === 0, `frames=${frames.size} delivered=${delivered.join('')}`);
  const firstFrame = frames.entries().next().value as [number, () => void] | undefined;
  if (firstFrame) {
    frames.delete(firstFrame[0]);
    firstFrame[1]();
  }
  check('a painted batch preserves byte order', delivered.join('') === 'Hallo', delivered.join(''));
  batch.push(' Welt');
  batch.finish();
  batch.push(' verloren');
  check('finish drains pending bytes exactly once and refuses late chunks', delivered.join('') === 'Hallo Welt' && frames.size === 0, delivered.join(''));

  /* ---- ledger: deterministic status answer ---- */
  const statusFinal: IkarusAskPayload = {
    ok: true,
    project: 'p',
    intent: 'status',
    assistant: '**status** …',
    provider_used: 'deterministic',
    turn_id: 12,
    conversation_persisted: true,
    delivery_mode: 'stream',
    stream_interrupted: false
  };
  const settled = settleTurn({ ...started, started: { intent: 'status', shell: 'deterministic', provider_used: 'deterministic' } }, statusFinal, 0.31, true);
  const statusRows = ledgerFor(settled, labelOf);
  check('a measured answer yields route and answer rows only', keys(statusRows) === 'route,answer', keys(statusRows));
  check('the deterministic route is named as the local index', statusRows[0]?.datum === 'Lokaler Index' && statusRows[0]?.detail?.[0] === 'Shell: deterministisch');
  check('the answer row carries the stamp and the measured wait', statusRows[1]?.datum === 'GEMESSEN · lokaler Index · 0,3 s', statusRows[1]?.datum);
  check('the measured answer is ok-toned', statusRows[1]?.tone === 'ok');
  check('the stamp word matches the invitation', stampForTurn(settled, labelOf)?.word === 'GEMESSEN');

  /* ---- ledger: a model answer with selection, context and offer ---- */
  const modelFinal = {
    ok: true,
    project: 'p',
    intent: 'chat',
    shell: 'voice',
    assistant: 'Der Parser …',
    provider_used: 'claude_code_cli',
    model_used: 'claude',
    llm: { provider: 'claude_code_cli', requested: null, auto_selected: true, timeout_s: 150, max_attempts: 1, reason: 'first available in configured order' },
    context: { focus_file: 'daedalus/spine/attempt.py', included: 7, withheld_count: 2, trimmed: 0, ambiguous: false },
    act_offer: { objective: 'Mach den Parser robuster', reason: 'imperative act verb', signal: 'mach' },
    turn_id: 13,
    conversation_persisted: true,
    delivery_mode: 'stream',
    stream_interrupted: false
  } as unknown as IkarusAskPayload;
  const modelTurn = settleTurn({ role: 'ikarus', text: 'Der Parser …', streaming: true }, modelFinal, 12.84, true);
  const modelRows = ledgerFor(modelTurn, labelOf);
  check('a model answer yields route, context, answer, offer', keys(modelRows) === 'route,context,answer,offer', keys(modelRows));
  check('automatic selection is drawn as an arrow to the chosen runtime', modelRows[0]?.datum === 'Automatisch → Claude Code', modelRows[0]?.datum);
  check('the selection reason and window are in the detail', (modelRows[0]?.detail || []).join('|') === 'Shell: Voice|first available in configured order|Zeitfenster 150 s', (modelRows[0]?.detail || []).join('|'));
  check('the context row names the focus file and the withheld count', modelRows[1]?.datum === 'attempt.py · 7 Dateien gelesen · 2 zurückgehalten', modelRows[1]?.datum);
  check('the model answer names the runtime and the wait', modelRows[2]?.datum === 'MODELL · Claude Code · 13 s', modelRows[2]?.datum);
  check('a model answer is info-toned, not ok', modelRows[2]?.tone === 'info');
  check('an act offer waits for confirmation', modelRows[3]?.datum === 'wartet auf Bestätigung · Mach den Parser robuster' && modelRows[3]?.tone === 'info', modelRows[3]?.datum);

  /* ---- ledger: nothing measured, nothing drawn ---- */
  const emptyContext = ledgerFor({ role: 'ikarus', text: 'x', origin: { intent: 'chat', provider_used: 'deterministic' }, envelope: envelopeFrom({ context: { trimmed: 0, ambiguous: false } }) }, labelOf);
  check('a context receipt with nothing in it draws no row', emptyContext.every((r) => r.key !== 'context'), keys(emptyContext));
  const unnamed = ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({ llm: { auto_selected: true } }) }, labelOf);
  check('a selection without a provider draws no route row', unnamed.every((r) => r.key !== 'route'), keys(unnamed));
  const noProvider = settleTurn({ role: 'ikarus', text: '', streaming: true }, { ok: true, project: 'p', intent: 'chat', assistant: 'x', provider_used: '' } as IkarusAskPayload, 1, true);
  check('a final without a provider stores no provider and earns no stamp', noProvider.origin?.provider_used === undefined && stampForTurn(noProvider, labelOf) === undefined);

  /* ---- ledger: an unnamed runtime stays an identifier ---- */
  const idOnly = ledgerFor({ role: 'ikarus', text: 'x', origin: { intent: 'chat', provider_used: 'codex_cli' } }, labelOf);
  check('an unknown runtime id is printed as itself', idOnly[0]?.datum === 'codex_cli' && stampForTurn({ role: 'ikarus', text: 'x', origin: { intent: 'chat', provider_used: 'codex_cli' } }, labelOf)?.originIsId === true);

  /* ---- ledger: refusal, offer with confirmation, dispatch, cancel ---- */
  const refused: Turn = {
    role: 'ikarus',
    text: 'Abgelehnt.',
    origin: { intent: 'error', provider_used: 'deterministic' },
    envelope: envelopeFrom({
      intent: 'error',
      provider_used: 'deterministic',
      refusal: { entrypoint_id: 'ikarus.ask_stream', verdict: 'deny', contract: 'budget.process_guard', lane: 'n/a', provider: '', host: null, reason: 'ceiling reached' }
    })
  };
  const refusedRows = ledgerFor(refused, labelOf);
  check('a refusal draws a bad Prüfung row after the route', keys(refusedRows) === 'route,refusal,answer', keys(refusedRows));
  check('the refusal names the contract', refusedRows[1]?.datum === 'budget.process_guard · abgelehnt' && refusedRows[1]?.detail?.[0] === 'ceiling reached');
  check('a failed answer is stamped FEHLGESCHLAGEN', refusedRows[2]?.datum === 'FEHLGESCHLAGEN' && refusedRows[2]?.tone === 'bad');

  const offered: Turn = {
    role: 'ikarus',
    text: 'Soll ich?',
    origin: { intent: 'enqueue', provider_used: 'deterministic' },
    offer: { kind: 'queue_task', args: { project: 'p', objective: 'Parser härten', lane: 'local_only' }, requires_confirmation: true }
  };
  const offeredRows = ledgerFor(offered, labelOf);
  check('an open offer is a live Angebot row', offeredRows.find((r) => r.key === 'offer')?.tone === 'live');
  check('the open offer names the objective', offeredRows.find((r) => r.key === 'offer')?.datum === 'Aufgabe · Parser härten');
  const interrupted = settleTurn({ ...offered, streaming: true }, {
    ok: true, project: 'p', intent: 'enqueue', assistant: 'Teilantwort', provider_used: 'deterministic',
    stream_interrupted: true, action: offered.offer
  }, 1, true);
  check('an interrupted final preserves partial text and refuses an executable action', interrupted.text === 'Teilantwort' && interrupted.offer === undefined && interrupted.envelope?.stream_interrupted === true);

  const dispatched: Turn = {
    ...offered,
    offer: undefined,
    offerOutcome: 'eingereiht · Lane local_only',
    dispatch: {
      id: 'req_a91f', found: true, state: 'running', source: 'queue_stream', lane: 'local_only', requested_lane: 'local_only',
      actual_providers: ['ollama'], summary: null, error: null, applied: null, applied_reason: 'noch nicht abgeschlossen', stalled: false, timed_out: false
    },
    cancellation: 'requested'
  };
  const dispatchedRows = ledgerFor(dispatched, labelOf);
  check('offer outcome, dispatch and cancellation follow the answer', keys(dispatchedRows) === 'route,answer,offer,dispatch,cancel', keys(dispatchedRows));
  const dispatchRow = dispatchedRows.find((r) => r.key === 'dispatch');
  check('a running dispatch is live and names id and lane', dispatchRow?.tone === 'live' && dispatchRow?.datum === 'läuft · req_a91f · Lane local_only', dispatchRow?.datum);
  check('the handoff state is never inferred', dispatchRow?.detail?.includes('Übergabe: unklar') === true, (dispatchRow?.detail || []).join('|'));
  check('a requested cancellation is warn-toned', dispatchedRows.find((r) => r.key === 'cancel')?.tone === 'warn');

  const done: Turn = { ...dispatched, cancellation: undefined, dispatch: { ...dispatched.dispatch!, state: 'done', applied: false, applied_reason: 'patch produced, not applied' } };
  const doneRow = ledgerFor(done, labelOf).find((r) => r.key === 'dispatch');
  check('a finished task with an unapplied patch is ok-toned but says so', doneRow?.tone === 'ok' && doneRow?.detail?.includes('Übergabe: nicht bestätigt') === true && doneRow?.detail?.includes('patch produced, not applied') === true);

  /* ---- ledger: halted observation ---- */
  const halted = ledgerFor({ role: 'ikarus', text: 'teil', halted: true, origin: { intent: 'chat', provider_used: 'ollama_http' } }, labelOf);
  check('a closed observation is ANZEIGE BEENDET and warn-toned', halted.find((r) => r.key === 'answer')?.datum === 'ANZEIGE BEENDET' && halted.find((r) => r.key === 'answer')?.tone === 'warn');

  /* ---- ledger: intent mismatch ---- */
  const mismatch = ledgerFor({ role: 'ikarus', text: 'x', origin: { intent: 'chat', provider_used: 'deterministic' }, envelope: envelopeFrom({ intent_mismatch: { start: 'chat', final: 'enqueue', dropped_action: true } }) }, labelOf);
  check('a dropped action is an Abgleich row', mismatch.find((r) => r.key === 'mismatch')?.datum === 'Aktion verworfen · Start chat, Ende enqueue');
  const agreed = ledgerFor({ role: 'ikarus', text: 'x', origin: { intent: 'chat', provider_used: 'deterministic' }, envelope: envelopeFrom({ intent_mismatch: { start: 'chat', final: 'chat', dropped_action: false } }) }, labelOf);
  check('an agreeing reconciliation draws nothing', agreed.every((r) => r.key !== 'mismatch'));

  /* ---- resume: the stored envelope reaches the ledger ---- */
  const resumed = resumedTurns(
    {
      conversation_id: 'conv_1',
      exists: true,
      turn_count: 1,
      turns: [{
        id: 44, user_message: 'status', assistant_text: 'ok', intent: 'status', provider_used: 'deterministic', created_ts: '2026-09-02T10:00:00+00:00',
        envelope: { intent: 'status', provider_used: 'deterministic', context: { focus_file: null, included: 0, withheld_count: 0, trimmed: 0, ambiguous: false } }
      }],
      turns_returned: 1,
      dispatches: [{ link: { turn_id: 44, dispatch_ref: 'req_9' }, latest: { lifecycle: 'reported', summary: 'patch produced, not applied', outcome_state: 'PRESENT', detail: { lane: 'local_only', applied: false } } }]
    },
    'conv_1'
  );
  check('a stored exchange becomes two turns', resumed.length === 2 && resumed[0].role === 'you' && resumed[1].role === 'ikarus');
  check('the stored turn keeps its spine id and timestamp', resumed[1].backendTurnId === 44 && resumed[1].createdTs === '2026-09-02T10:00:00+00:00');
  const resumedRows = ledgerFor(resumed[1], labelOf);
  check('a resumed turn draws route, context, answer, dispatch from stored data', keys(resumedRows) === 'route,context,answer,dispatch', keys(resumedRows));
  check('a resumed answer has no measured wait', resumedRows.find((r) => r.key === 'answer')?.datum === 'GEMESSEN · lokaler Index');
  check('a resumed dispatch reads PRESENT as done, not applied', resumedRows.find((r) => r.key === 'dispatch')?.datum === 'fertig · req_9 · Lane local_only' && resumedRows.find((r) => r.key === 'dispatch')?.detail?.includes('Übergabe: nicht bestätigt') === true);

  const projectBoundView: ConversationView = {
    conversation_id: 'conv_atlas',
    exists: true,
    project_binding: { state: 'bound', project: 'atlas', row_count: 1 },
    quarantined: false,
    turn_count: 1,
    turns: [{ user_message: 'atlas', assistant_text: 'ok', project: 'atlas' }],
    turns_returned: 1
  };
  check('a canonical thread confirms its exact project', conversationConfirmsProject(projectBoundView, 'conv_atlas', 'atlas'));
  check('a thread id from another project is rejected', !conversationConfirmsProject(projectBoundView, 'conv_atlas', 'beta'));
  check('a mismatched canonical id is rejected', !conversationConfirmsProject(projectBoundView, 'conv_beta', 'atlas'));
  check('a legacy view without canonical binding proof fails closed',
    !conversationConfirmsProject({ ...projectBoundView, project_binding: undefined }, 'conv_atlas', 'atlas'));
  const sameProjectTail = Array.from({ length: 40 }, (_, index) => ({
    user_message: `atlas-${index}`,
    assistant_text: 'ok',
    project: 'atlas'
  }));
  check('more than forty same-project turns trust the unbounded server proof',
    conversationConfirmsProject({
      ...projectBoundView,
      project_binding: { state: 'bound', project: 'atlas', row_count: 61 },
      turn_count: 60,
      turns: sameProjectTail,
      turns_returned: 40
    }, 'conv_atlas', 'atlas'));
  check('a mixed old row cannot hide behind a forty-turn same-project tail',
    !conversationConfirmsProject({
      ...projectBoundView,
      project_binding: { state: 'mixed', project: null, row_count: 41 },
      quarantined: true,
      turn_count: 0,
      turns: sameProjectTail,
      turns_returned: 40
    }, 'conv_atlas', 'atlas'));

  /* ---- open dispatches: what has not reported back ---- */
  const openView = {
    conversation_id: 'conv_1',
    exists: true,
    turn_count: 1,
    turns: [],
    turns_returned: 0,
    open_dispatches: [
      { link: { turn_id: 44, dispatch_ref: 'req_open', created_ts: '2026-09-02T11:00:00+00:00' }, latest: { lifecycle: 'dispatched', summary: 'Parser härten' } },
      { link: { turn_id: 45 }, latest: { lifecycle: 'dispatched', summary: 'kein ref' } },
      { link: { dispatch_ref: 'req_bare' }, latest: null }
    ]
  };
  const open = openDispatchesFrom(openView).items;
  check('an open dispatch requires a dispatched lifecycle and leaves an unbound identity explicit', open.length === 1 && open[0].ref === 'req_open' && open[0].turnId === 44 && open[0].since === '2026-09-02T11:00:00+00:00' && open[0].descriptionSource === 'none' && open[0].summary === 'Parser härten', JSON.stringify(open));
  check('a dispatch with no ref is not a row', open.every((d) => d.ref !== ''));
  check('a dispatch without a dispatched lifecycle is not open work evidence', !open.some((row) => row.ref === 'req_bare'));
  check('no open dispatches is an empty list, never undefined', openDispatchesFrom(undefined).items.length === 0 && openDispatchesFrom({ ...openView, open_dispatches: [] }).items.length === 0);

  const childExit = { request_id: 12, cancellation_requested: true, was_running: true, terminate_sent: true, kill_sent: false, process_exited: true, returncode: -15 };
  check('local child evidence requires the exact durable request identity', subprocessCancellationFrom(childExit, 13) === undefined && subprocessCancellationFrom({ ...childExit, request_id: '12' }, 12) === undefined);
  check('malformed child-exit evidence is not coerced into confirmation', subprocessCancellationFrom({ ...childExit, process_exited: 'true' }, 12) === undefined && subprocessCancellationFrom({ ...childExit, returncode: Number.NaN }, 12) === undefined);
  check('child-exit evidence requires a coherent observed return code', subprocessCancellationFrom({ ...childExit, returncode: null }, 12) === undefined && subprocessCancellationFrom({ ...childExit, process_exited: false }, 12) === undefined);
  check('a process that was not cancelled is not cancellation evidence', subprocessCancellationFrom({ ...childExit, cancellation_requested: false }, 12) === undefined);
  check('signed Windows process return codes remain exact', subprocessCancellationFrom({ ...childExit, returncode: -1073741510 }, 12)?.returncode === -1073741510);
  const childTurn: Turn = { role: 'ikarus', text: '', requestId: 12, cancellation: 'confirmed', cancellationProcess: subprocessCancellationFrom(childExit, 12) };
  const childRow = ledgerFor(childTurn, labelOf).find((row) => row.key === 'cancel');
  check('observed local child exit never becomes remote-termination proof', childRow?.detail?.includes('Lokaler CLI-Prozess beendet · Remote-Termination nicht bewiesen') === true);


  /* ================================================================
     G1-UI-22 — what the run cost, why it ended, and what a yes runs.

     Every shape below is one this host actually produced or one the
     narrowing must refuse. The measured Claude Code 2.1.263 run of
     2026-09-08 is the reference: 18.9 s, $0.4056 self-reported,
     stop_reason `tool_use`, subtype `error_max_turns`, 2 turns.
     ================================================================ */

  const runLlm = {
    provider: 'claude_code_cli',
    cost_usd_measured: 0.4056,
    cost_basis: 'provider_reported',
    duration_ms: 18900,
    subtype: 'error_max_turns',
    stop_reason: 'tool_use',
    num_turns: 2,
    attempts: 1,
    model_used: 'claude-opus-5[1m]'
  };
  const runEnv = envelopeFrom({ llm: runLlm });
  check('every additive execution field survives narrowing',
    runEnv?.llm?.cost_usd_measured === 0.4056 && runEnv?.llm?.cost_basis === 'provider_reported'
      && runEnv?.llm?.duration_ms === 18900 && runEnv?.llm?.subtype === 'error_max_turns'
      && runEnv?.llm?.stop_reason === 'tool_use' && runEnv?.llm?.num_turns === 2
      && runEnv?.llm?.attempts === 1 && runEnv?.llm?.model_used === 'claude-opus-5[1m]',
    JSON.stringify(runEnv?.llm));
  const runRow = ledgerFor({ role: 'ikarus', text: 'x', envelope: runEnv }, labelOf).find((r) => r.key === 'execution');
  check('the execution row says duration, cost with its basis, and how it ended',
    runRow?.datum === '18,9 s (Anbieter) · 0,41 USD (gemessen) · Ende: Turn-Limit des Anbieters erreicht', runRow?.datum);
  check('a provider error end is bad-toned', runRow?.tone === 'bad', runRow?.tone);
  check('the execution detail keeps the raw stop reason, the turns, the attempts and the ledger caveat',
    (runRow?.detail || []).includes('Stop-Grund: tool_use')
      && (runRow?.detail || []).includes('Turns des Anbieters: 2')
      && (runRow?.detail || []).includes('Versuche: 1')
      && (runRow?.detail || []).includes(HONESTY_DE.selfReport),
    (runRow?.detail || []).join('|'));
  check('a model named only by the run is reported as such, never merged away',
    (runRow?.detail || []).includes('Modell laut Lauf: claude-opus-5[1m]'), (runRow?.detail || []).join('|'));

  const datumOf = (llm: Record<string, unknown>): string | undefined =>
    ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({ llm }) }, labelOf).find((r) => r.key === 'execution')?.datum;
  check('an estimate says it is an estimate',
    datumOf({ ...runLlm, cost_basis: 'estimate' })?.includes('0,41 USD (geschätzt)') === true, datumOf({ ...runLlm, cost_basis: 'estimate' }));
  const noBasis = { ...runLlm } as Record<string, unknown>;
  delete noBasis.cost_basis;
  check('a cost without a basis says the basis is missing',
    datumOf(noBasis)?.includes('0,41 USD (Basis nicht angegeben)') === true, datumOf(noBasis));
  for (const bogus of ['gemessen', 'provider-reported', true, 1, null]) {
    check(`an unrecognised cost basis ${JSON.stringify(bogus)} is dropped, never read as measured`,
      datumOf({ ...runLlm, cost_basis: bogus })?.includes('(Basis nicht angegeben)') === true
        && datumOf({ ...runLlm, cost_basis: bogus })?.includes('(gemessen)') === false,
      datumOf({ ...runLlm, cost_basis: bogus }));
  }
  const nullCost = envelopeFrom({ llm: { ...runLlm, cost_usd_measured: null } });
  check('a null cost survives narrowing as null, distinct from an absent key',
    nullCost?.llm !== undefined && 'cost_usd_measured' in nullCost.llm && nullCost.llm.cost_usd_measured === null);
  const nullRow = ledgerFor({ role: 'ikarus', text: 'x', envelope: nullCost }, labelOf).find((r) => r.key === 'execution');
  check('a provider that ran and reported no cost says so', nullRow?.datum.includes('Kosten nicht gemessen') === true, nullRow?.datum);
  check('a run that ended in a provider error stays bad-toned even when the cost is unmeasured',
    nullRow?.tone === 'bad', nullRow?.tone);
  const nullQuiet = ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({
    llm: { duration_ms: 8100, cost_usd_measured: null, subtype: 'success' }
  }) }, labelOf).find((r) => r.key === 'execution');
  check('an unmeasured cost on an otherwise clean run is warn-toned, not quietly info',
    nullQuiet?.tone === 'warn' && nullQuiet?.datum === '8,1 s (Anbieter) · Kosten nicht gemessen · Ende: regulär beendet',
    `${nullQuiet?.datum}|${nullQuiet?.tone}`);
  const noCostKey = { ...runLlm } as Record<string, unknown>;
  delete noCostKey.cost_usd_measured;
  check('an absent cost key draws no cost fragment at all',
    datumOf(noCostKey) === '18,9 s (Anbieter) · Ende: Turn-Limit des Anbieters erreicht', datumOf(noCostKey));
  check('a negative or non-finite cost is dropped',
    envelopeFrom({ llm: { cost_usd_measured: -1 } })?.llm === undefined
      && envelopeFrom({ llm: { cost_usd_measured: Number.NaN } })?.llm === undefined);
  check('an unmeasured provider end value is printed verbatim, never invented in German',
    datumOf({ subtype: 'wat_is_this' }) === 'Ende: wat_is_this', datumOf({ subtype: 'wat_is_this' }));
  check('the provider end gloss covers only values observed on this host',
    Object.keys(PROVIDER_END_DE).sort().join(',') === 'error_max_budget_usd,error_max_turns,success,tool_use',
    Object.keys(PROVIDER_END_DE).join(','));
  check('the cost basis wording is exactly three cases',
    `${COST_BASIS_DE.provider_reported}|${COST_BASIS_DE.estimate}|${COST_BASIS_DE.unknown}` === 'gemessen|geschätzt|Basis nicht angegeben');
  check('money and duration speak German at the precision they carry',
    costLabel(0.4056) === '0,41 USD' && costLabel(0) === '0,00 USD' && costLabel(0.001) === 'unter 0,01 USD'
      && durationLabel(18.9) === '18,9 s' && durationLabel(150.3) === '150 s',
    `${costLabel(0.4056)}|${costLabel(0)}|${costLabel(0.001)}|${durationLabel(18.9)}|${durationLabel(150.3)}`);
  const ledgerCharged = ledgerFor({ role: 'ikarus', text: 'x', seconds: 150.3, envelope: envelopeFrom({
    llm: { ...runLlm, ledger_charged_usd: 3, ledger_basis: 'worst_case' }
  }) }, labelOf).find((r) => r.key === 'execution');
  check('the amount the budget ledger charged is drawn beside the self-report, not instead of it',
    (ledgerCharged?.detail || []).includes('Vom Budget-Ledger verbucht: 3,00 USD (worst_case)')
      && (ledgerCharged?.detail || []).includes(HONESTY_DE.selfReport),
    (ledgerCharged?.detail || []).join('|'));
  check('the browser-measured round trip is named as a different measurement',
    (ledgerCharged?.detail || []).includes('Hier gemessen: 150 s (kompletter Rundweg inkl. Verlauf anlegen)'),
    (ledgerCharged?.detail || []).join('|'));

  /* ---- the failure row: why a dead turn is dead ---- */
  const failRow = (payload: Record<string, unknown>, origin?: Turn['origin']) =>
    ledgerFor({ role: 'ikarus', text: 'x', origin, envelope: envelopeFrom(payload) }, labelOf).find((r) => r.key === 'failure');
  check('an error with no evidence says no reason was sent',
    failRow({ intent: 'error' })?.datum === HONESTY_DE.noReason && failRow({ intent: 'error' })?.tone === 'bad',
    failRow({ intent: 'error' })?.datum);
  check('attempts alone become the reason',
    failRow({ intent: 'error', llm: { attempts: 1 } })?.datum === 'Kein nutzbares Ergebnis nach 1 Versuch(en)',
    failRow({ intent: 'error', llm: { attempts: 1 } })?.datum);
  check('a provider end wins over the attempt count',
    failRow({ intent: 'error', llm: { subtype: 'error_max_budget_usd', attempts: 1 } })?.datum
      === 'Anbieter beendet: Budget-Limit des Anbieters erreicht');
  check('an interrupted stream is a warn-toned failure of its own',
    failRow({ intent: 'chat', stream_interrupted: true })?.datum === 'Stream ohne vollständige Antwort beendet'
      && failRow({ intent: 'chat', stream_interrupted: true })?.tone === 'warn');
  check('an error intent stored only on the origin still explains itself',
    failRow({}, { intent: 'error', provider_used: 'claude_code_cli' })?.datum === HONESTY_DE.noReason);
  check('every failure row says it is derived, not the server sentence',
    (failRow({ intent: 'error' })?.detail || []).includes(HONESTY_DE.derived));
  check('a refusal owns its own explanation and draws no second failure row',
    keys(refusedRows) === 'route,refusal,answer', keys(refusedRows));
  check('a healthy turn draws neither an execution nor a failure row',
    keys(modelRows) === 'route,context,answer,offer', keys(modelRows));
  check('nothing measured about the run draws no execution row',
    ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({ llm: { provider: 'claude_code_cli' } }) }, labelOf)
      .every((r) => r.key !== 'execution' && r.key !== 'failure'));

  /* ---- untrusted provider stderr is contained, never in the answer ---- */
  const leak = 'ANTHROPIC_API_KEY=sk-live-XXXX at C:/Users/x `code` [l](javascript:alert(1))';
  const leakTurn: Turn = { role: 'ikarus', text: 'Fehlgeschlagen.', origin: { intent: 'error', provider_used: 'claude_code_cli' },
    envelope: envelopeFrom({ intent: 'error', llm: { ...runLlm, stderr_tail: leak + 'x'.repeat(900) } }) };
  const leakRows = ledgerFor(leakTurn, labelOf);
  const leakExec = leakRows.find((r) => r.key === 'execution');
  const leakFail = leakRows.find((r) => r.key === 'failure');
  check('provider stderr appears once, in a detail line, prefixed and clipped to 500 characters',
    (leakExec?.detail || []).filter((line) => line.includes('sk-live-XXXX')).length === 1
      && (leakExec?.detail || []).some((line) => line.startsWith(`${HONESTY_DE.stderr}: `) && line.length <= HONESTY_DE.stderr.length + 502)
      && (leakFail?.detail || []).every((line) => !line.includes('sk-live-XXXX')),
    (leakExec?.detail || []).map((l) => l.slice(0, 40)).join('|'));
  check('provider stderr is never part of the datum a collapsed protokoll shows',
    !leakExec?.datum.includes('sk-live') && !leakFail?.datum.includes('sk-live'));
  check('provider stderr never reaches the answer bubble',
    !renderToStaticMarkup(createElement(MarkdownMessage, { text: leakTurn.text })).includes('sk-live-XXXX'));
  const strayFail = ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({ intent: 'error', llm: { stderr_tail: leak } }) }, labelOf)
    .find((r) => r.key === 'failure');
  /* ---- the voice lane nests its evidence under llm.invocation ---- */
  const nestedEnv = envelopeFrom({ llm: { provider: 'claude_code_cli', attempts: 1, invocation: { ...runLlm } } });
  const nestedExec = ledgerFor({ role: 'ikarus', text: 'x', envelope: nestedEnv }, labelOf).find((r) => r.key === 'execution');
  const flatExec = ledgerFor({ role: 'ikarus', text: 'x', envelope: runEnv }, labelOf).find((r) => r.key === 'execution');
  check('execution evidence nested under llm.invocation renders exactly like the flat shape',
    nestedExec !== undefined && nestedExec.datum === flatExec?.datum
      && JSON.stringify(nestedExec.detail) === JSON.stringify(flatExec?.detail),
    `${nestedExec?.datum} vs ${flatExec?.datum}`);
  const nestedWins = envelopeFrom({ llm: { provider: 'claude_code_cli', stop_reason: 'flat', invocation: { stop_reason: 'nested' } } });
  check('when both shapes carry a key the measured (nested) value wins', nestedWins?.llm?.stop_reason === 'nested');
  const strayLong = ledgerFor({ role: 'ikarus', text: 'x', envelope: envelopeFrom({ intent: 'error', llm: { stderr_tail: leak + 'x'.repeat(900) } }) }, labelOf)
    .find((r) => r.key === 'failure');
  check('with no execution row the stderr is still clipped to 500 characters',
    (strayLong?.detail || []).some((line) => line.startsWith(`${HONESTY_DE.stderr}: `) && line.length <= HONESTY_DE.stderr.length + 502)
      && (strayLong?.detail || []).every((line) => line.length <= HONESTY_DE.stderr.length + 502),
    (strayLong?.detail || []).map((l) => String(l.length)).join('|'));
  check('with no execution row the stderr still has exactly one home',
    (strayFail?.detail || []).filter((line) => line.includes('sk-live-XXXX')).length === 1,
    (strayFail?.detail || []).join('|'));

  /* ---- the start frame's model and budget reach the surface ---- */
  const startedFull: Turn = { role: 'ikarus', text: '', streaming: true,
    started: { intent: 'chat', shell: 'voice', provider_used: 'claude_code_cli', model_used: 'claude-opus-5[1m]', timeout_s: 150 } };
  check('the model the start frame already carried is drawn in the route detail',
    (ledgerFor(startedFull, labelOf)[0]?.detail || []).includes('Modell claude-opus-5[1m]'),
    (ledgerFor(startedFull, labelOf)[0]?.detail || []).join('|'));
  const budgetHtml = renderToStaticMarkup(createElement(MarkdownMessage, {
    text: '', streaming: true, elapsed: 31, activity: 'Claude Code antwortet', budgetSeconds: 150
  }));
  check('a long wait is legible against the budget the server named', budgetHtml.includes('Claude Code antwortet · 31 s von 150 s'), budgetHtml);
  const noBudgetHtml = renderToStaticMarkup(createElement(MarkdownMessage, {
    text: '', streaming: true, elapsed: 31, activity: 'Claude Code antwortet'
  }));
  check('without a server budget no denominator is invented', noBudgetHtml.includes('Claude Code antwortet · 31 s') && !noBudgetHtml.includes(' von '));

  /* ---- the offered action, as the panel shows it and the request sends it ---- */
  const queueAction = { kind: 'queue_task', args: { project: 'atlas', objective: 'Parser härten', lane: 'local_only' }, requires_confirmation: true };
  const subject = offerSubject(queueAction, 'fallback');
  check('the offer subject is the exact shape the request will use',
    subject?.kind === 'queue_task' && subject.project === 'atlas' && subject.lane === 'local_only'
      && subject.objective === 'Parser härten' && subject.executable === true && subject.requiresConfirmation === true,
    JSON.stringify(subject));
  check('an omitted project and lane fall back exactly as the request falls back',
    offerSubject({ kind: 'queue_task', args: {} }, 'atlas')?.project === 'atlas'
      && offerSubject({ kind: 'queue_task', args: {} }, 'atlas')?.lane === 'local_only');
  check('a full 40-character revision is readable',
    offerSubject({ kind: 'queue_task', args: { source_revision: 'db38a762991b04cbc96c3cbed5209d6a517fa611' } }, 'p')?.revisionState === 'valid');
  for (const bad of ['HEAD', 'db38a76', 'd'.repeat(39), 'a'.repeat(41), 'DB38A762991B04CBC96C3CBED5209D6A517FA611', 5, {}]) {
    const derived = offerSubject({ kind: 'queue_task', args: { source_revision: bad } }, 'p');
    check(`a revision of ${JSON.stringify(bad)} is reported unreadable, never normalised`,
      derived?.revisionState === 'unreadable' && derived.sourceRevision === undefined, JSON.stringify(derived));
  }
  check('an absent revision is absent, not unreadable',
    offerSubject({ kind: 'queue_task', args: {} }, 'p')?.revisionState === 'absent');
  check('an action kind this cockpit has no endpoint for is not executable',
    offerSubject({ kind: 'run_campaign', args: {} }, 'p')?.executable === false
      && offerSubject({ kind: 'run_campaign', args: {} }, 'p')?.kind === 'run_campaign');
  check('a non-object action derives nothing', offerSubject('queue_task', 'p') === undefined && offerSubject(undefined, 'p') === undefined);

  const panel = renderToStaticMarkup(createElement(OfferConfirm, { subject: subject!, onAccept: () => {}, onDecline: () => {} }));
  check('the confirm panel names the action, project, lane and objective before any click',
    panel.includes('queue_task') && panel.includes('atlas') && panel.includes('local_only') && panel.includes('Parser härten'), panel.slice(0, 200));
  check('the confirm panel always states that a nomination is not a promotion', panel.includes(HONESTY_DE.nomination));
  check('a descriptive requires_confirmation:false does not silence the panel',
    renderToStaticMarkup(createElement(OfferConfirm, {
      subject: offerSubject({ ...queueAction, requires_confirmation: false }, 'p')!, onAccept: () => {}, onDecline: () => {}
    })).includes(HONESTY_DE.flagIgnored));
  check('a confirmed offer keeps saying nothing about the flag when the server asked for confirmation',
    !panel.includes(HONESTY_DE.flagIgnored));
  const inertPanel = renderToStaticMarkup(createElement(OfferConfirm, {
    subject: offerSubject({ kind: 'run_campaign', args: { project: 'p' } }, 'p')!, onAccept: () => {}, onDecline: () => {}
  }));
  check('an unknown action kind disables the primary control and says nothing was sent',
    inertPanel.includes('Diese Oberfläche kennt für „run_campaign“ keinen Ausführungsweg. Nichts wurde gesendet.')
      && /<button[^>]*disabled[^>]*>\s*Loslegen/.test(inertPanel), inertPanel.slice(0, 400));
  check('the confirm panel keeps the two accessible control names the suites pin',
    panel.includes('Loslegen') && panel.includes('Nicht jetzt') && panel.includes('Vorgeschlagene Aktion beantworten'));

  /* ---- cadence: derivation is incremental, not per-frame over the thread ---- */
  let labelCalls = 0;
  let resolveCalls = 0;
  const countedLabel = (id: string) => { labelCalls += 1; return labelOf(id); };
  const countedResolve = (needle: string) => { resolveCalls += 1; return needle.endsWith('.py') ? `mod:${needle}` : undefined; };
  const settledTurns: Turn[] = Array.from({ length: 40 }, (_, i) => ({
    role: 'ikarus' as const,
    text: `Antwort ${i} in daedalus/spine/attempt.py und apps/web/src/features/conversation/model.ts`,
    localId: `t${i}`,
    seconds: 1.2,
    origin: { intent: 'chat', provider_used: 'claude_code_cli', model_used: 'claude' }
  }));
  const live: Turn = { role: 'ikarus', text: '', localId: 'live', streaming: true, started: { provider_used: 'claude_code_cli' } };
  let thread: Turn[] = [...settledTurns, live];
  const derive = createReceiptCache(countedLabel, countedResolve);
  const first = derive(thread);
  const resolveAfterFirst = resolveCalls;
  const labelAfterFirst = labelCalls;
  check('the first pass derives every turn', first.length === 41 && resolveAfterFirst > 0);
  let stable = true;
  let current = first;
  for (let i = 0; i < 200; i += 1) {
    // Exactly what `patchReply` does: a new ARRAY, one new turn OBJECT.
    const previous = thread;
    const last = previous[previous.length - 1];
    const patched: Turn = { ...last, text: `${last.text}x` };
    thread = previous.map((t) => (t === last ? patched : t));
    const next = derive(thread);
    if (next[0] !== first[0] || next[0].ledger !== first[0].ledger || next[17] !== current[17]) stable = false;
    current = next;
  }
  check('two hundred stream deltas never re-scan a settled answer for citations',
    resolveCalls === resolveAfterFirst, `${resolveAfterFirst} -> ${resolveCalls}`);
  check('per-frame runtime lookups stay a small constant, not the whole thread',
    labelCalls - labelAfterFirst < 5 * 200, `${labelAfterFirst} -> ${labelCalls}`);
  check('an unchanged turn keeps its receipt and its rows array by reference', stable);

  /* ---- relative time ---- */
  const now = Date.parse('2026-09-02T12:00:00Z');
  check('relative time speaks German', relativeTime('2026-09-02T11:58:40Z', now) === 'vor 1 min' && relativeTime('2026-09-01T11:00:00Z', now) === 'gestern' && relativeTime('2026-09-02T09:00:00Z', now) === 'vor 3 h');
  check('an unparsable time is nothing, not NaN', relativeTime('nope', now) === '' && relativeTime(undefined, now) === '');

  /* ---- commands ---- */
  check('a sentence is not a command', parseCommand('status') === null && parseCommand('Was ist /api/health?') === null);
  check('/status sends the deterministic word', JSON.stringify(parseCommand('/status')) === JSON.stringify({ kind: 'send', message: 'status' }));
  check('/distill sends the deterministic word', JSON.stringify(parseCommand('/distill')) === JSON.stringify({ kind: 'send', message: 'distill' }));
  check('/plan takes the rest of the line', JSON.stringify(parseCommand('/plan wo wird der Kontextplan gebaut')) === JSON.stringify({ kind: 'plan', text: 'wo wird der Kontextplan gebaut' }));
  check('/karte takes a module', JSON.stringify(parseCommand('/karte attempt.py')) === JSON.stringify({ kind: 'map', module: 'attempt.py' }));
  check('/aufwand understands German levels', parseCommand('/aufwand hoch')?.kind === 'effort' && (parseCommand('/aufwand hoch') as { level: string }).level === 'high' && (parseCommand('/AUFWAND gering') as { level: string }).level === 'low');
  check('a command missing its argument is incomplete, not sent', parseCommand('/aufwand')?.kind === 'incomplete' && parseCommand('/karte')?.kind === 'incomplete' && parseCommand('/plan')?.kind === 'incomplete');
  check('/neu /modell /abbrechen /hilfe are in-page actions', ['new', 'model', 'cancel', 'help'].join() === ['/neu', '/modell', '/abbrechen', '/hilfe'].map((c) => parseCommand(c)?.kind).join());
  check('an unknown command is sent verbatim', JSON.stringify(parseCommand('/foo bar')) === JSON.stringify({ kind: 'unknown', message: '/foo bar' }));
  check('the menu matches by prefix', matchCommands('/a').map((c) => c.name).join() === 'aufwand,abbrechen' && matchCommands('/').length === COMMANDS.length && matchCommands('x').length === 0);
  check('a slash alone or a slash word looks like a command', looksLikeCommand('/') && looksLikeCommand('/sta') && looksLikeCommand('/plan wo') && !looksLikeCommand('a/b') && !looksLikeCommand('/api/health ist'));
  const help = helpText();
  check('the help note names every command', COMMANDS.every((c) => help.includes(`/${c.name}`)));

  /* ---- markdown: a model answer can never make this browser fetch ---- */
  const hostile = [
    '![leak](https://example.invalid/a.png)',
    '<img src="https://example.invalid/b.png" onerror="alert(1)">',
    '<script>alert(1)</script>',
    '[go](javascript:alert(1)) and [ok](https://example.invalid/) and [ftp](ftp://x/)',
    '| a | b |\n| --- | --- |\n| 1 | `x` |',
    '- [x] done\n- [ ] open'
  ].join('\n\n');
  const html = renderToStaticMarkup(createElement(MarkdownMessage, { text: hostile }));
  check('an image never becomes an img element', !/<img\b/i.test(html) && html.includes('Bild: leak'), html.slice(0, 200));
  check('raw HTML is skipped, never rendered', !/<script/i.test(html) && !/onerror/i.test(html));
  check('only http(s) links open; other schemes become plain text', !/javascript:/i.test(html) && !/href="ftp:/i.test(html) && /href="https:\/\/example\.invalid\/"/.test(html));
  check('external links never send a referrer', /rel="noreferrer"/.test(html));
  check('GFM tables render as tables', /<table>/.test(html) && /<th>a<\/th>/.test(html));
  check('task items are glyphs, not form controls', !/<input/i.test(html) && /md-task on/.test(html));
  const activityHtml = renderToStaticMarkup(createElement(MarkdownMessage, {
    text: '', streaming: true, elapsed: 3, activity: 'Anfrage angenommen'
  }));
  check('an empty stream renders its observed activity and elapsed time', activityHtml.includes('Anfrage angenommen · 3 s'));
  check('the visual empty-stream activity is not a nested live region', !activityHtml.includes('role="status"'));
  check('the live surface does not claim hidden thinking', !activityHtml.includes('denkt'));

  return results;
}
