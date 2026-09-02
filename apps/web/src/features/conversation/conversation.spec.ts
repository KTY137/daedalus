import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { IkarusAskPayload } from '@/shared/contracts';
import { COMMANDS, helpText, looksLikeCommand, matchCommands, parseCommand } from './commands';
import { MarkdownMessage } from './MarkdownMessage';
import {
  envelopeFrom,
  ledgerFor,
  relativeTime,
  resumedTurns,
  settleTurn,
  stampForTurn,
  type Turn
} from './model';

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
  check('a start frame yields a live route row and a thinking answer row', keys(startedRows) === 'route,answer', keys(startedRows));
  check('the route names the runtime by label once it can', startedRows[0]?.datum === 'Claude Code · antwortet', startedRows[0]?.datum);
  check('the streaming route is live', startedRows[0]?.tone === 'live');
  check('the empty stream says Ikarus denkt', startedRows[1]?.datum === 'Ikarus denkt' && startedRows[1]?.tone === 'live');

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

  return results;
}
