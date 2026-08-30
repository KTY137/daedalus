// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * THE FIVE STATES, on the client side.
 *
 * `daedalus/health.py` defines a CLOSED vocabulary of five words, only one of
 * which is good news, and it has no way to collapse them:
 *
 *   working    exercised JUST NOW by this run, and here is the measurement
 *   present    the code is here; NOTHING in this run exercised it
 *   degraded   it ran, and what came back is wrong — with the reason
 *   absent     it is not here at all
 *   unknown    the check COULD NOT RUN. Never green, never silent, never a skip
 *
 * A UI that paints `present` or `unknown` the same green as `working` rebuilds
 * the exact defect that module exists to prevent — so this file carries the
 * vocabulary across the wire boundary and `StateBadge` gives each of the five
 * its own colour AND its own icon AND its own border treatment AND its own
 * word. Five axes, so the distinction survives a colourblind viewer, a
 * screenshot, and a glance.
 *
 * There is deliberately NO sixth state and no `ok`. `coerceState()` below is
 * the port of `health._coerce`: anything it does not recognise becomes
 * `unknown`, never a pass.
 *
 * WHERE THE STATES COME FROM. The Python health surface is a CLI; it is not
 * served over HTTP (see the report accompanying this change). Everything
 * rendered with this vocabulary is therefore derived from payloads the API
 * *does* expose, and every derivation says what established it:
 *
 *   • `/api/loop/queue` → `queue.sources[*]`, whose shape already distinguishes
 *     "ran and read" from "suppressed" from "opt-in, never ran".
 *   • the fetch itself → reachable / timed out / 404 / refused.
 *   • `/api/runtimes/status` + `/api/providers/status` → configured vs available.
 */

export const WORKING = 'working';
export const PRESENT = 'present';
export const DEGRADED = 'degraded';
export const ABSENT = 'absent';
export const UNKNOWN = 'unknown';

export type HealthState =
  | typeof WORKING
  | typeof PRESENT
  | typeof DEGRADED
  | typeof ABSENT
  | typeof UNKNOWN;

/** The only five words this UI may render. */
export const STATES: readonly HealthState[] = [WORKING, PRESENT, DEGRADED, ABSENT, UNKNOWN];

/** States that mean "this run did not establish that the thing works".
 * `present` sits here with `unknown` and `absent` on purpose. */
export const NOT_PROVEN: readonly HealthState[] = [PRESENT, UNKNOWN, ABSENT];

/**
 * How each state reads. The words are the CLI's own `MARKS`, kept
 * deliberately un-symmetric: `works` is the only quiet one, so a screen of
 * `PRESENT?` cannot be skimmed as a screen of green.
 */
export interface StateMeta {
  /** The loud short word on the badge. */
  mark: string;
  /** What the state MEANS, in one clause. Never a synonym for "fine". */
  meaning: string;
  /** CSS custom-property colour, resolved from the shipped theme. */
  color: string;
  /** Border treatment — the second, non-colour axis. */
  border: 'solid' | 'dashed' | 'dotted' | 'double';
  /** Whether this state may ever be read as a pass. Exactly one may. */
  proven: boolean;
}

export const STATE_META: Record<HealthState, StateMeta> = {
  working: {
    mark: 'works',
    meaning: 'exercised just now, with a measurement behind it',
    color: 'var(--good)',
    border: 'solid',
    proven: true
  },
  present: {
    mark: 'PRESENT?',
    meaning: 'the code is here and NOTHING exercised it — this is not a pass',
    color: 'var(--warn)',
    border: 'dashed',
    proven: false
  },
  degraded: {
    mark: 'DEGRADED',
    meaning: 'it ran and what came back is wrong',
    color: 'var(--bad)',
    border: 'solid',
    proven: false
  },
  absent: {
    mark: 'ABSENT',
    meaning: 'it is not here at all',
    color: 'var(--dim)',
    border: 'dotted',
    proven: false
  },
  unknown: {
    mark: 'UNKNOWN!',
    meaning: 'the check could not run — never green, never silent',
    color: 'var(--violet)',
    border: 'double',
    proven: false
  }
};

/**
 * One assessed thing: a state, a headline, and the evidence for both.
 *
 * `evidence` is not decoration. A verdict whose reasoning is not on screen is
 * an opinion, and this whole surface exists to stop opinions from rendering as
 * measurements.
 */
export interface Assessment {
  name: string;
  state: HealthState;
  headline: string;
  /** What this probe was even asking. Mirrors `ProbeSpec.asks`. */
  asks?: string;
  /** Ordered key/value evidence, rendered verbatim. */
  evidence?: Array<[string, string]>;
  /** What to do about it, when the payload said. */
  remedy?: string;
  /** Where this verdict came from — always shown, so nothing looks measured
   * that was in fact inferred by this client. */
  derivedFrom: string;
}

/**
 * The port of `health._coerce`. Any word outside the closed vocabulary becomes
 * `unknown` and SAYS SO, so a future backend field cannot invent a sixth state
 * that renders as a pass.
 */
export function coerceState(value: unknown): HealthState {
  const word = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return (STATES as readonly string[]).includes(word) ? (word as HealthState) : UNKNOWN;
}

export function isProven(state: HealthState): boolean {
  return STATE_META[state].proven;
}

/** Count of each state across a set of assessments — the CLI's summary line. */
export function tally(items: Assessment[]): Record<HealthState, number> {
  const out = { working: 0, present: 0, degraded: 0, absent: 0, unknown: 0 };
  items.forEach((item) => { out[item.state] += 1; });
  return out;
}

/**
 * The verdict, matching `health.verdict()`'s three-way exit:
 *   bad       something DEGRADED, or a required thing is missing
 *   unproven  nothing that ran is broken — but not everything ran
 *   ok        every subsystem was exercised and held
 */
export type Verdict = 'ok' | 'unproven' | 'bad';

export function verdict(items: Assessment[]): Verdict {
  if (items.length === 0) return 'unproven';
  if (items.some((i) => i.state === DEGRADED || i.state === ABSENT)) return 'bad';
  if (items.some((i) => NOT_PROVEN.includes(i.state))) return 'unproven';
  return 'ok';
}

export const VERDICT_TEXT: Record<Verdict, string> = {
  ok: 'every source was exercised and held',
  unproven: 'nothing that ran is broken — but not everything ran',
  bad: 'at least one source is DEGRADED or missing'
};

/* ------------------------------------------------------------------ *
 * Deriving the five states from what the API actually returns.
 * ------------------------------------------------------------------ */

function str(value: unknown, fallback = ''): string {
  if (value == null) return fallback;
  if (typeof value === 'string') return value || fallback;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function rec(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Flatten a bounded evidence/detail object into printable rows, one level deep. */
export function evidenceRows(value: unknown, prefix = ''): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const obj = rec(value);
  if (!obj) return out;
  Object.entries(obj).forEach(([key, raw]) => {
    const label = prefix ? `${prefix}.${key}` : key;
    const nested = rec(raw);
    if (nested && !prefix) {
      out.push(...evidenceRows(nested, label));
      return;
    }
    if (Array.isArray(raw)) {
      out.push([label, raw.length === 0 ? '(none)' : raw.map((v) => str(v, JSON.stringify(v))).join(', ')]);
      return;
    }
    if (nested) {
      out.push([label, JSON.stringify(raw)]);
      return;
    }
    out.push([label, raw == null ? '(null)' : String(raw)]);
  });
  return out;
}

/** Normalise a source name so a free-form note can be matched to it
 * (`attempt_memory` ↔ "attempt memory unavailable: …"). */
function noteKey(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

const FAILURE_WORDS = ['unavailable', 'did not run', 'did not build', 'suppressed', 'could not'];

/**
 * A note that reports a failure for `name`, if there is one.
 *
 * WHY THIS EXISTS: `sources.eval_baseline` is `{candidates, cheap}` with NO
 * error field even when the baseline failed to load — the failure is only ever
 * written into `notes`. Without this join, a source that could not be read
 * would render as `working` with zero candidates, which is precisely the
 * "empty list means no work" collapse the whole surface is built against.
 * The gap is reported upstream; until it closes, the note is the evidence.
 */
export function failingNote(name: string, notes: string[]): string {
  const key = noteKey(name);
  return notes.find((note) => {
    const n = noteKey(note);
    return n.startsWith(key) && FAILURE_WORDS.some((w) => n.includes(noteKey(w)));
  }) || '';
}

/**
 * Assess ONE picker source from `/api/loop/queue`'s `queue.sources`.
 *
 * The shapes differ per source on purpose, and the difference is the whole
 * signal:
 *
 *   {error: "..."}                        → DEGRADED (it ran and failed)
 *   {suppressed: true, trust|freshness}   → DEGRADED (read, and withheld — it
 *                                           describes a tree that is not this one)
 *   {ran|read: false, reason: "opt-in"}   → PRESENT  (here, nothing ran it)
 *   {ran|read: true, ...}                 → WORKING  (consulted this request)
 *   anything else                         → UNKNOWN  (refusing to render an
 *                                           unrecognised shape as a pass)
 */
export function assessPickerSource(
  name: string,
  detail: unknown,
  notes: string[] = []
): Assessment {
  const derivedFrom = `GET /api/loop/queue → queue.sources.${name}`;
  const obj = rec(detail);

  if (!obj) {
    return {
      name,
      state: UNKNOWN,
      headline: 'the queue returned no detail for this source, so nothing is known about it',
      derivedFrom
    };
  }

  const evidence = evidenceRows(obj);
  const note = failingNote(name, notes);

  const error = str(obj.error);
  if (error) {
    return {
      name, state: DEGRADED, evidence, derivedFrom,
      headline: `it ran and failed: ${error}`,
      remedy: 'this source contributed nothing — the queue below is short BECAUSE of this, not because there is no work'
    };
  }

  if (obj.suppressed === true) {
    const trust = rec(obj.trust);
    const freshness = rec(obj.freshness) || rec(trust?.freshness);
    const reason = str(trust?.reason) || str(freshness?.reason) || 'withheld';
    return {
      name, state: DEGRADED, evidence, derivedFrom,
      headline: `read, then WITHHELD: ${reason}`,
      remedy: note || 'a snapshot of a different tree is worse than a missing one — it looks authoritative. Regenerate it.'
    };
  }

  if (note) {
    return {
      name, state: DEGRADED, evidence, derivedFrom,
      headline: note,
      remedy: 'the source detail carries no error field for this failure; the note is the only evidence (see report: backend gap)'
    };
  }

  const ran = obj.ran;
  const read = obj.read;
  const reason = str(obj.reason);

  if (ran === false || read === false) {
    return {
      name, state: PRESENT, evidence, derivedFrom,
      headline: reason
        ? `the source exists and did NOT run: ${reason}`
        : 'the source exists and nothing in this request ran it',
      remedy: 'present is not a pass — this source contributed nothing to the ranking below'
    };
  }

  if (ran === true || read === true) {
    const n = typeof obj.candidates === 'number' ? obj.candidates : null;
    const remembered = typeof obj.tasks_remembered === 'number' ? obj.tasks_remembered : null;
    return {
      name, state: WORKING, evidence, derivedFrom,
      headline: n != null
        ? `consulted for this request; contributed ${n} candidate(s)`
        : remembered != null
          ? `consulted for this request; ${remembered} task(s) remembered`
          : 'consulted for this request'
    };
  }

  if (typeof obj.candidates === 'number') {
    return {
      name, state: WORKING, evidence, derivedFrom,
      headline: `consulted for this request${obj.cheap === true ? ' (cheap, always on)' : ''}; contributed ${obj.candidates} candidate(s)`
    };
  }

  // The `_coerce` rule: an unrecognised shape is never a pass.
  return {
    name, state: UNKNOWN, evidence, derivedFrom,
    headline: 'this source reported a shape this view does not recognise — refusing to render it as a pass',
    remedy: 'the client vocabulary is closed on purpose; a new source shape has to be read before it can be believed'
  };
}

/** Every source in a queue payload, ranked worst-first so a failure cannot be
 * scrolled past. */
export function assessPickerSources(
  sources: Record<string, unknown>,
  notes: string[] = []
): Assessment[] {
  const order: Record<HealthState, number> = { degraded: 0, unknown: 1, absent: 2, present: 3, working: 4 };
  return Object.entries(sources || {})
    .map(([name, detail]) => assessPickerSource(name, detail, notes))
    .sort((a, b) => order[a.state] - order[b.state] || a.name.localeCompare(b.name));
}

/**
 * Assess a fetch. This is where "the backend is not running" stops being a
 * spinner: nothing answering is `unknown` about the SUBJECT (we learned
 * nothing about the loop) and it is stated as such rather than as an empty
 * result.
 */
export function assessFetch(
  name: string,
  opts: { loading: boolean; error?: { kind: string; message: string } | null; loadedAt?: number | null; asks?: string }
): Assessment {
  const derivedFrom = `the ${name} request itself`;
  if (opts.error) {
    const { kind, message } = opts.error;
    if (kind === 'network') {
      return {
        name, state: UNKNOWN, derivedFrom, asks: opts.asks,
        headline: 'nothing answered on the loopback port — this view learned NOTHING, which is not the same as “there is nothing”',
        remedy: 'start the API on loopback:  python -m daedalus.web_api',
        evidence: [['transport', message]]
      };
    }
    if (kind === 'timeout') {
      return {
        name, state: UNKNOWN, derivedFrom, asks: opts.asks,
        headline: 'the request was abandoned before an answer arrived — nothing was established either way',
        evidence: [['transport', message]]
      };
    }
    if (kind === 'notfound') {
      return {
        name, state: ABSENT, derivedFrom, asks: opts.asks,
        headline: 'this backend does not serve that endpoint — the surface is missing, not empty',
        evidence: [['http', message]]
      };
    }
    return {
      name, state: DEGRADED, derivedFrom, asks: opts.asks,
      headline: `the endpoint answered and refused: ${message}`,
      evidence: [['http', message]]
    };
  }
  if (opts.loading) {
    return {
      name, state: UNKNOWN, derivedFrom, asks: opts.asks,
      headline: 'in flight — nothing is known yet'
    };
  }
  if (!opts.loadedAt) {
    return {
      name, state: PRESENT, derivedFrom, asks: opts.asks,
      headline: 'the endpoint exists and this session has not called it'
    };
  }
  return {
    name, state: WORKING, derivedFrom, asks: opts.asks,
    headline: 'answered this session',
    evidence: [['fetched', new Date(opts.loadedAt).toLocaleTimeString()]]
  };
}

/**
 * Assess a provider/runtime pair. `configured` (a key or a login exists) and
 * `available` (it answers right now) are separate facts and the existing rail
 * collapsed both into connected/offline.
 *
 * NOTE the ceiling: `available` here means the registry probed a CLI path or a
 * local endpoint. It never means a billable call succeeded, so this function
 * cannot return `working` — the honest top of this scale is `present`, exactly
 * as `health.vendors.cli` refuses to say more than "on PATH".
 */
export function assessProvider(row: {
  label: string;
  configured?: boolean;
  available: boolean;
  requiresKey?: boolean;
  detail?: string;
  lastError?: string;
}): Assessment {
  const derivedFrom = 'GET /api/runtimes/status + /api/providers/status';
  const evidence: Array<[string, string]> = [
    ['configured', row.configured == null ? 'not reported' : String(row.configured)],
    ['reachable', String(row.available)]
  ];
  if (row.detail) evidence.push(['detail', row.detail]);
  if (row.lastError) evidence.push(['last error', row.lastError]);

  if (row.configured === false) {
    return {
      name: row.label, state: ABSENT, evidence, derivedFrom,
      headline: row.requiresKey ? 'no key configured — this lane cannot run' : 'not configured on this machine'
    };
  }
  if (!row.available) {
    return {
      name: row.label, state: DEGRADED, evidence, derivedFrom,
      headline: row.lastError || 'configured, and it did not answer'
    };
  }
  return {
    name: row.label, state: PRESENT, evidence, derivedFrom,
    headline: 'installed and reachable — NOTHING was invoked, so this run cannot prove the lane works',
    remedy: 'a vendor call is billable; presence on PATH is not a working lane'
  };
}
