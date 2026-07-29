import type { ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  HelpCircle
} from 'lucide-react';
import { cx } from '../components/glass';
import {
  NOT_PROVEN,
  STATES,
  STATE_META,
  VERDICT_TEXT,
  tally,
  verdict,
  type Assessment,
  type HealthState
} from './health';

/**
 * FIVE STATES, FIVE RENDERINGS.
 *
 * Each state differs on four independent axes — hue, icon glyph, border
 * treatment and the word itself — so the difference survives a colourblind
 * viewer, a greyscale screenshot and a two-second glance. `working` is the ONLY
 * state that is green and the only one with a filled badge; `present` is a
 * dashed amber outline and `unknown` is a hatched violet block, because both of
 * them mean "this run established nothing" and a dashboard that paints them
 * green is the defect this repo spent a night removing.
 */
const ICONS: Record<HealthState, ReactNode> = {
  working: <CheckCircle2 size={13} strokeWidth={2.4} />,
  present: <CircleDashed size={13} strokeWidth={2.4} />,
  degraded: <AlertTriangle size={13} strokeWidth={2.4} />,
  absent: <CircleSlash size={13} strokeWidth={2.4} />,
  unknown: <HelpCircle size={13} strokeWidth={2.6} />
};

export function StateBadge({ state, compact, title }: { state: HealthState; compact?: boolean; title?: string }) {
  const meta = STATE_META[state];
  return (
    <span
      className={cx('hstate', `hstate-${state}`, compact && 'compact')}
      title={title || `${meta.mark} — ${meta.meaning}`}
      data-state={state}
    >
      {ICONS[state]}
      <b>{meta.mark}</b>
    </span>
  );
}

/** The vocabulary itself, spelled out once per surface. Small, permanent, and
 * NOT a legend nobody reads — it is the key to every badge on the page and it
 * says out loud that four of the five are not passes. */
export function StateLegend({ counts }: { counts?: Record<HealthState, number> }) {
  return (
    <div className="hlegend">
      {STATES.map((state) => (
        <span className="hlegend-item" key={state}>
          <StateBadge state={state} compact />
          <span className="hlegend-meaning">{STATE_META[state].meaning}</span>
          {counts ? <em className="hlegend-count">{counts[state]}</em> : null}
        </span>
      ))}
    </div>
  );
}

/** One assessed thing, with its evidence open. */
export function AssessmentRow({ item, defaultOpen }: { item: Assessment; defaultOpen?: boolean }) {
  const rows = item.evidence || [];
  return (
    <details className={cx('hrow', `hrow-${item.state}`)} open={defaultOpen ?? item.state === 'degraded'}>
      <summary>
        <StateBadge state={item.state} />
        <span className="hrow-name">{item.name}</span>
        <span className="hrow-head">{item.headline}</span>
      </summary>
      <div className="hrow-body">
        {item.asks && <p className="hrow-asks">asks: {item.asks}</p>}
        {item.remedy && <p className="hrow-remedy">→ {item.remedy}</p>}
        {rows.length > 0 && (
          <dl className="hev">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="hrow-prov">derived from {item.derivedFrom}</p>
      </div>
    </details>
  );
}

/**
 * The summary line, ported from `health.render()`. It prints the counts AND
 * names everything that is not proven, because the count on its own is the
 * thing an operator skims past.
 */
export function VerdictLine({ items, subject }: { items: Assessment[]; subject: string }) {
  const counts = tally(items);
  const v = verdict(items);
  const unproven = items.filter((i) => NOT_PROVEN.includes(i.state));
  return (
    <div className={cx('hverdict', `hverdict-${v}`)} role="status">
      <div className="hverdict-counts">
        {counts.working} working · {counts.degraded} degraded · {counts.present} present-but-unexercised ·{' '}
        {counts.absent} absent · {counts.unknown} unknown <span>({items.length} {subject})</span>
      </div>
      {unproven.length > 0 && (
        <div className="hverdict-unproven">
          NOT PROVEN by this run: {unproven.map((i) => i.name).join(', ')}
        </div>
      )}
      <div className="hverdict-word">VERDICT: {VERDICT_TEXT[v]}</div>
    </div>
  );
}

/**
 * THE BANNER THIS WHOLE VIEW EXISTS FOR.
 *
 * `degraded_sources` is what separates "there is no work" from "a source
 * failed", and those two produce the identical empty list. It is rendered
 * ABOVE the results it invalidates, in the failure colour, never as a
 * dismissible toast, and never collapsed into a count.
 */
export function DegradedSourcesBanner({
  sources,
  warnings,
  what
}: {
  sources: string[];
  warnings?: string[];
  what: string;
}) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="degraded-banner" role="alert">
      <div className="db-mark">
        <AlertTriangle size={16} />
        <b>INCOMPLETE</b>
      </div>
      <div className="db-body">
        <p className="db-lead">
          {sources.length} source{sources.length === 1 ? '' : 's'} could not be consulted, so {what} is{' '}
          <b>not the whole picture</b>. A short or empty result here is <b>NOT</b> evidence that there is nothing to do.
        </p>
        <div className="db-chips">
          {sources.map((name) => (
            <span className="db-chip" key={name}>
              <StateBadge state="degraded" compact /> {name}
            </span>
          ))}
        </div>
        {(warnings || []).map((w) => (
          <p className="db-warn" key={w}>{w}</p>
        ))}
      </div>
    </div>
  );
}

/**
 * The counterpart, and just as load-bearing: when every source DID answer, say
 * so explicitly. "Nothing was withheld" is a real finding and it is the only
 * context in which an empty queue means what it looks like it means.
 */
export function AllSourcesReadNote({ what }: { what: string }) {
  return (
    <div className="sources-clean" role="status">
      <StateBadge state="working" compact />
      <span>Every source answered — {what} is complete as far as the sources go.</span>
    </div>
  );
}

/** Loading / error / empty, as three DIFFERENT things. A backend that is not
 * running says so; it never spins. */
export function SurfaceState({
  kind,
  title,
  detail,
  icon,
  action
}: {
  kind: 'loading' | 'error' | 'offline' | 'empty';
  title: string;
  detail?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={cx('surface-state', `surface-${kind}`)} role="status" aria-live="polite">
      {icon}
      <strong>{title}</strong>
      {detail ? <span>{detail}</span> : null}
      {action}
    </div>
  );
}
