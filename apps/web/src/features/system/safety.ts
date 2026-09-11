/**
 * DID THE SAFETY GATES VERIFY?
 *
 * `/api/dashboard` carries a `quality` block that `daedalus/core.py` builds by
 * actually RUNNING two probes, and it escalates their failure in its own words:
 *
 *     if not local_only_gate:
 *         warnings.append("SAFETY: local_only fail-closed guard did not "
 *                         "verify -- investigate before queueing.")
 *     if not schema_gate:
 *         warnings.append("SAFETY: empty-report schema gate did not verify.")
 *
 * `local_only_never_claude` is a containment guarantee: it checks that a task
 * requested on the `local_only` lane cannot fall back to Claude. That is the
 * same property the work rail now reports per-run as a lane divergence -- this
 * is the standing version of it, checked before any run exists.
 *
 * The whole block was undeclared in `DashboardPayload`, so it was unreachable
 * through the typed path. The card that had the data in hand rendered the
 * project name, the governance verdict, and a raw JSON dump. A failed safety
 * probe was therefore visible only to someone who expanded the blob and knew
 * which key to look for.
 *
 * MEASURED on this machine, 2026-09-03:
 *
 *   local_only_never_claude   true
 *   schema_non_empty_summary  true
 *   empty_reports_fail        true      (core.py sets it from the same probe)
 *   stale_watchers            0
 *   fallback_alarm            false
 *   fallback_rate             0.0
 *   recommendation            ""        (set only when a watcher is stale)
 *
 * THE FAILURE DIRECTION. `false` means the probe RAN AND DID NOT VERIFY, which
 * core.py labels SAFETY. `undefined` means the block never arrived. Those are
 * different, and neither may render as "verified" -- a gate nobody checked is
 * not a gate that held.
 */

export interface QualityBlock {
  local_only_never_claude?: boolean;
  schema_non_empty_summary?: boolean;
  empty_reports_fail?: boolean;
  stale_watchers?: number;
  fallback_alarm?: boolean;
  fallback_rate?: number;
  recommendation?: string;
}

export type GateReading = 'verified' | 'failed' | 'unreported';

export const GATE_WORD: Record<GateReading, string> = {
  verified: 'geprüft und gehalten',
  failed: 'NICHT verifiziert',
  unreported: 'nicht gemeldet'
};

/** Only a probe that ran and held is green; silence is never green. */
export function gateTone(reading: GateReading): string {
  if (reading === 'verified') return 'ok';
  if (reading === 'failed') return 'bad';
  return 'warn';
}

export function gateReading(value: boolean | undefined): GateReading {
  if (value === true) return 'verified';
  if (value === false) return 'failed';
  return 'unreported';
}

export interface SafetyGate {
  /** what the probe answers, phrased as the question it settles */
  question: string;
  reading: GateReading;
  /** what a failure would mean, in core.py's terms */
  consequence: string;
}

export function safetyGates(quality: QualityBlock | undefined): SafetyGate[] {
  const q = quality || {};
  return [
    {
      question: 'Kann eine local_only-Aufgabe auf Claude ausweichen?',
      reading: gateReading(q.local_only_never_claude),
      consequence: 'Der Fail-closed-Schutz für local_only wurde nicht verifiziert — '
        + 'vor dem Einreihen prüfen.'
    },
    {
      question: 'Werden leere Berichte abgewiesen?',
      reading: gateReading(q.schema_non_empty_summary),
      consequence: 'Das Schema-Gate gegen leere Berichte wurde nicht verifiziert.'
    }
  ];
}

/** The worst reading present, so a card can colour itself without averaging. */
export function worstGate(gates: SafetyGate[]): GateReading {
  if (gates.some((g) => g.reading === 'failed')) return 'failed';
  if (gates.some((g) => g.reading === 'unreported')) return 'unreported';
  return 'verified';
}

/**
 * The fallback rate, as a percentage, or null when it was not reported.
 *
 * Never defaulted to 0: "no fallbacks happened" and "nobody counted" are
 * different, and 0 is the reassuring one.
 */
export function fallbackText(quality: QualityBlock | undefined): string | null {
  const rate = quality?.fallback_rate;
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return null;
  const pct = (rate * 100).toFixed(1).replace('.', ',');
  return `${pct} %`;
}

/**
 * Stale watchers, in words.
 *
 * A stale watcher makes `core.py` recommend `local_only` outright, because a
 * dead watcher holding a claim is exactly the fallback ambiguity that lane
 * exists to avoid. Zero is stated as zero; an unreported count is not zero.
 */
export function staleText(quality: QualityBlock | undefined): { text: string; tone: string } {
  const n = quality?.stale_watchers;
  if (typeof n !== 'number' || !Number.isFinite(n)) {
    return { text: 'nicht gemeldet', tone: 'warn' };
  }
  if (n === 0) return { text: 'keiner', tone: '' };
  return { text: n === 1 ? '1 hängengeblieben' : `${n} hängengeblieben`, tone: 'bad' };
}
