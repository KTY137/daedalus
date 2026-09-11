import type { RuntimeRow } from '@/shared/contracts';

/**
 * WHERE YOUR SOURCE GOES WHEN YOU PICK A RUNTIME.
 *
 * `/api/runtimes/status` has always sent six capability and trust flags that
 * the TypeScript contract never declared -- `local`, `trusted_with_ip`,
 * `can_write`, `agentic`, `command`, `env_key` -- so they were unreachable
 * through the typed path and the reachability list showed none of them. The
 * same failure shape as `asked` on the health payload: the field was not
 * forgotten, it was undeclared and therefore invisible.
 *
 * `trusted_with_ip` is the one that matters most. Its contract
 * (`daedalus/runtimes/providers/contracts.py`) defines it as "approved to
 * receive proprietary/sensitive source", and it is ENFORCED at the egress
 * gate: `providers/codex_cli.py` declares `trusted_with_ip=False,   # NEVER
 * receives denylisted/sensitive content`, and `orchestration/ikarus_os.py`
 * builds that lane's brain context with `lane="untrusted"`.
 *
 * A picker that offers runtimes without saying which of them the gate treats
 * as untrusted asks the operator to choose where their code goes while
 * withholding the only fact that makes the choice meaningful.
 *
 * MEASURED against the live endpoint, 2026-09-03 -- six runtimes, two on this
 * machine, one not trusted with source:
 *
 *   claude_code_cli  local=false  trusted=true   can_write=true   agentic=true
 *   codex_cli        local=false  trusted=false  can_write=true   agentic=true
 *   ollama_http      local=true   trusted=true   can_write=true   agentic=true
 *   ollama_cli       local=true   trusted=true   can_write=true   agentic=true
 *   anthropic_api    local=false  trusted=true   can_write=false  agentic=false
 *   openai_api       local=false  trusted=false  can_write=false  agentic=false
 *
 * (`codex_cli` read `trusted=true` until the same day: the registry the
 * endpoint publishes disagreed with the provider that enforces the gate, and
 * published the more generous of the two. See
 * `tests/runtimes/test_trust_flags_agree.py`.)
 */

export interface TrustNote {
  /** short chip text */
  text: string;
  /** '' | 'warn' | 'bad' — an unknown flag is never drawn as reassuring */
  tone: string;
  /** the longer sentence, for a title or detail line */
  why: string;
}

/**
 * Where the work runs. `local` is a static class property of the runtime, not
 * a measurement of the current host, so it is reported as what it is.
 */
export function placeNote(row: Pick<RuntimeRow, 'local'>): TrustNote {
  if (row.local === true) {
    return { text: 'auf diesem Rechner', tone: '', why: 'Läuft lokal; nichts verlässt die Maschine.' };
  }
  if (row.local === false) {
    return { text: 'extern', tone: 'warn', why: 'Läuft außerhalb dieser Maschine.' };
  }
  return { text: 'Ort unbekannt', tone: 'warn', why: 'Die Laufzeit hat nicht gemeldet, wo sie läuft.' };
}

/**
 * Whether the egress gate lets proprietary source reach this runtime.
 *
 * `false` is the finding, so it is the loud one. `undefined` is NOT drawn as
 * trusted: a runtime that did not report the flag has not been approved, and
 * silence must not read as approval.
 */
export function sourceNote(row: Pick<RuntimeRow, 'trusted_with_ip'>): TrustNote {
  if (row.trusted_with_ip === true) {
    return {
      text: 'Quellcode erlaubt',
      tone: '',
      why: 'Freigegeben für proprietären Quellcode.'
    };
  }
  if (row.trusted_with_ip === false) {
    return {
      text: 'kein sensibler Quellcode',
      tone: 'bad',
      why: 'Das Egress-Gate behandelt diese Laufzeit als nicht vertrauenswürdig für '
        + 'proprietären Quellcode; gesperrte Inhalte erreichen sie nie.'
    };
  }
  return {
    text: 'Freigabe unbekannt',
    tone: 'warn',
    why: 'Diese Laufzeit hat nicht gemeldet, ob sie proprietären Quellcode erhalten darf. '
      + 'Das ist keine Freigabe.'
  };
}

/**
 * What it may do. `can_write` and `agentic` are different questions: an
 * agentic runtime drives itself, a writing one may change files. The API rows
 * are neither.
 */
export function abilityNotes(row: Pick<RuntimeRow, 'can_write' | 'agentic'>): TrustNote[] {
  const out: TrustNote[] = [];
  if (row.can_write === true) {
    out.push({ text: 'darf schreiben', tone: 'warn', why: 'Kann Dateien im Arbeitsbereich ändern.' });
  }
  if (row.agentic === true) {
    out.push({ text: 'agentisch', tone: '', why: 'Führt mehrschrittige Arbeit selbst aus.' });
  }
  return out;
}

/** Every note for a row, in the order a reader should meet them. */
export function trustNotes(row: RuntimeRow): TrustNote[] {
  return [placeNote(row), sourceNote(row), ...abilityNotes(row)];
}
