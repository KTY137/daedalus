import type { RuntimeRow } from '@/shared/contracts';
import { abilityNotes, placeNote, sourceNote, trustNotes } from './runtimetrust';

/**
 * Where your source goes, pinned.
 *
 * Every row below is the live shape of `/api/runtimes/status` on 2026-09-03.
 * The `codex_cli` case is the one that matters: it read `trusted_with_ip:
 * true` that morning because the registry the endpoint publishes disagreed
 * with the provider that enforces the egress gate, and published the more
 * generous of the two.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

function row(over: Partial<RuntimeRow> = {}): RuntimeRow {
  return {
    id: 'r', label: 'R', mode: 'cli', available: true, auth_status: 'cli_detected',
    command_path: '', version: '', models: [], selected_model: '', model_present: false,
    last_error: '', notes: '', ...over
  } as RuntimeRow;
}

export function runRuntimeTrustSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. an untrusted runtime is the loud case --------------------------
  const untrusted = sourceNote(row({ trusted_with_ip: false }));
  check('a runtime the gate distrusts is drawn as a finding', untrusted.tone === 'bad', untrusted.tone);
  check('and says what it may not receive',
    untrusted.text.includes('kein sensibler Quellcode'), untrusted.text);
  check('and explains that the gate, not the UI, decides',
    untrusted.why.includes('Egress-Gate'), untrusted.why);

  const trusted = sourceNote(row({ trusted_with_ip: true }));
  check('an approved runtime is not alarmed about', trusted.tone === '', trusted.tone);

  // THE DIRECTION THAT MATTERS. A row that did not report the flag has not
  // been approved, and silence must never render as approval.
  const silent = sourceNote(row({}));
  check('an unreported approval is not treated as approval', silent.tone !== '', silent.tone);
  check('and says so in words', silent.text.includes('unbekannt'), silent.text);
  check('and refuses to be read as a clearance',
    silent.why.includes('keine Freigabe'), silent.why);
  check('an unreported approval is not drawn as a measured refusal either',
    silent.tone === 'warn' && untrusted.tone === 'bad');

  // ---- 2. where it runs --------------------------------------------------
  check('a local runtime says nothing leaves the machine',
    placeNote(row({ local: true })).why.includes('verlässt die Maschine'));
  check('a local runtime is not alarmed about', placeNote(row({ local: true })).tone === '');
  check('an external runtime says so', placeNote(row({ local: false })).text === 'extern');
  check('an external runtime is flagged', placeNote(row({ local: false })).tone === 'warn');
  check('an unreported location is not assumed local',
    placeNote(row({})).text.includes('unbekannt') && placeNote(row({})).tone === 'warn');

  // ---- 3. what it may do -------------------------------------------------
  const writer = abilityNotes(row({ can_write: true, agentic: true }));
  check('a writing runtime says it may change files',
    writer.some((n) => n.text === 'darf schreiben' && n.tone === 'warn'));
  check('an agentic runtime says it drives itself',
    writer.some((n) => n.text === 'agentisch'));
  check('an API row claims neither', abilityNotes(row({ can_write: false, agentic: false })).length === 0);
  check('an unreported ability is not claimed', abilityNotes(row({})).length === 0);

  // ---- 4. the live six ---------------------------------------------------
  // Verbatim from /api/runtimes/status, 2026-09-03, after the registry fix.
  const live: Array<[string, Partial<RuntimeRow>]> = [
    ['claude_code_cli', { local: false, trusted_with_ip: true, can_write: true, agentic: true }],
    ['codex_cli', { local: false, trusted_with_ip: false, can_write: true, agentic: true }],
    ['ollama_http', { local: true, trusted_with_ip: true, can_write: true, agentic: true }],
    ['ollama_cli', { local: true, trusted_with_ip: true, can_write: true, agentic: true }],
    ['anthropic_api', { local: false, trusted_with_ip: true, can_write: false, agentic: false }],
    ['openai_api', { local: false, trusted_with_ip: false, can_write: false, agentic: false }]
  ];
  const distrusted = live
    .filter(([, r]) => sourceNote(row(r)).tone === 'bad')
    .map(([id]) => id);
  check(
    'exactly the two gate-distrusted runtimes are drawn red',
    distrusted.join(',') === 'codex_cli,openai_api',
    distrusted.join(',')
  );
  const localOnes = live.filter(([, r]) => placeNote(row(r)).tone === '').map(([id]) => id);
  check('exactly the two Ollama rows run on this machine',
    localOnes.join(',') === 'ollama_http,ollama_cli', localOnes.join(','));

  // Every runtime gets a place and a source verdict, always.
  for (const [id, r] of live) {
    const notes = trustNotes(row({ id, ...r }));
    check(`${id} states where it runs and what it may receive`, notes.length >= 2,
      notes.map((n) => n.text).join(' / '));
  }
  check('a row that reported nothing still states both unknowns',
    trustNotes(row({})).length === 2);

  return results;
}
