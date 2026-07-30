import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Activity,
  ArrowRight,
  Clock3,
  Gauge,
  KeyRound,
  Radio,
  RefreshCw,
  ShieldCheck,
  Workflow
} from 'lucide-react';
import type {
  GovernancePayload,
  GovernanceState
} from '../types';
import type {
  HealthPayload,
  LoopAttempt,
  ProviderStatusRow
} from '../api';
import type { LoopData } from '../views/useLoop';
import { StateBadge } from '../views/StateBadge';
import { coerceState, type HealthState } from '../views/health';
import { cx } from './glass';

type StreamState = 'live' | 'connecting' | 'down';

export interface MissionControlProps {
  project: string;
  stream: StreamState;
  inFlight: number;
  queueDepth: number;
  health?: HealthPayload;
  healthError: string;
  healthLoadedAt: number | null;
  providers: ProviderStatusRow[];
  providersError: string;
  providersLoadedAt: number | null;
  governance?: GovernancePayload;
  governanceLoadedAt: number | null;
  loop: LoopData;
  onRefresh: () => void;
  onOpenKnowledge: () => void;
  onOpenProviders: () => void;
  refreshing: boolean;
}

function useClock(): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function ageLabel(loadedAt: number | null, now: number): string {
  if (!loadedAt) return 'never sampled';
  const seconds = Math.max(0, Math.floor((now - loadedAt) / 1000));
  if (seconds < 4) return 'sampled now';
  if (seconds < 60) return `sampled ${seconds}s ago`;
  return `sampled ${Math.floor(seconds / 60)}m ago`;
}

function isStale(loadedAt: number | null, now: number, maxAgeMs = 45_000): boolean {
  return loadedAt == null || now - loadedAt > maxAgeMs;
}

function overallState(health: HealthPayload | undefined, error: string): HealthState {
  if (error || !health?.health) return 'unknown';
  if (health.health.verdict === 0) return 'working';
  if (health.health.verdict === 1) return 'degraded';
  // Exit 2 is the backend's explicit "not proven" verdict. PRESENT? is the
  // honest aggregate: checks exist and ran, but not all were exercised.
  return 'present';
}

function providerState(
  row: ProviderStatusRow,
  unavailableSample: boolean
): HealthState {
  if (unavailableSample) return 'unknown';
  if (!row.implemented) return 'absent';
  if (!row.configured) return 'absent';
  if (!row.available) return 'degraded';
  // Availability is only a reachability probe. No paid/model call ran.
  return 'present';
}

function attemptTone(row: LoopAttempt | undefined): HealthState {
  if (!row) return 'unknown';
  if (!row.resolved_ts) return 'working';
  if (row.error || row.gates_passed === false || ['failed', 'rejected'].includes(row.outcome || '')) {
    return 'degraded';
  }
  return row.outcome === 'clean' ? 'working' : 'present';
}

function gateTone(row: LoopAttempt | undefined): HealthState {
  if (!row || row.gates_passed == null) return 'unknown';
  return row.gates_passed ? 'working' : 'degraded';
}

function Stage({
  index,
  label,
  state,
  detail,
  terminal
}: {
  index: string;
  label: string;
  state: HealthState;
  detail: string;
  terminal?: boolean;
}) {
  return (
    <>
      <div className={cx('mc-stage', `mc-stage-${state}`)}>
        <span className="mc-stage-index">{index}</span>
        <span className="mc-stage-lamp" aria-hidden="true" />
        <div>
          <b>{label}</b>
          <span>{detail}</span>
        </div>
      </div>
      {!terminal && <ArrowRight className="mc-stage-arrow" size={14} aria-hidden="true" />}
    </>
  );
}

function SectionTitle({ icon, children, tail }: { icon: ReactNode; children: ReactNode; tail?: ReactNode }) {
  return (
    <div className="mc-section-title">
      <span>{icon}{children}</span>
      {tail}
    </div>
  );
}

function metric(value: number | undefined | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

export function MissionControl({
  project,
  stream,
  inFlight,
  queueDepth,
  health,
  healthError,
  healthLoadedAt,
  providers,
  providersError,
  providersLoadedAt,
  governance,
  governanceLoadedAt,
  loop,
  onRefresh,
  onOpenKnowledge,
  onOpenProviders,
  refreshing
}: MissionControlProps) {
  const now = useClock();
  const healthState = overallState(health, healthError);
  const healthCounts = health?.health.counts;
  const queue = loop.queue.data?.queue;
  const attempts = loop.attempts.data?.attempts;
  const latest = attempts?.intents?.[0];
  const providerSampleUnknown = Boolean(providersError) || !providersLoadedAt;
  const providerSampleStale = isStale(providersLoadedAt, now);
  const reachable = providers.filter((p) => p.available).length;
  const configured = providers.filter((p) => p.configured).length;
  const governanceState = governance ? coerceState(governance.state) : 'unknown';

  const queueStage: HealthState = loop.queue.error
    ? 'unknown'
    : !queue
      ? 'unknown'
      : queue.incomplete
        ? 'degraded'
        : 'working';
  const attemptState = attemptTone(latest);
  const gateState = gateTone(latest);
  const promoteState: HealthState = !governance
    ? 'unknown'
    : governance.promotion_allowed
      ? 'present'
      : governanceState === 'unknown'
        ? 'unknown'
        : 'degraded';

  const issues = useMemo(
    () => (health?.health.subsystems || [])
      .filter((item) => item.state !== 'working')
      .sort((a, b) => {
        const order: Record<GovernanceState, number> = {
          degraded: 0, unknown: 1, absent: 2, present: 3, working: 4
        };
        return order[a.state] - order[b.state];
      })
      .slice(0, 4),
    [health]
  );

  const queueAge = ageLabel(loop.queue.loadedAt, now);
  const attemptAge = ageLabel(loop.attempts.loadedAt, now);
  const govAge = ageLabel(governanceLoadedAt, now);

  return (
    <section className="mission-control glass" aria-labelledby="mission-control-title">
      <header className="mc-head">
        <div className="mc-identity">
          <span className="mc-kicker">DAEDALUS / MISSION CONTROL</span>
          <div className="mc-title-row">
            <h1 id="mission-control-title">Evolution control</h1>
            <span className="mc-project">{project || 'unresolved checkout'}</span>
          </div>
        </div>
        <div className="mc-head-status">
          <StateBadge state={healthState} />
          <span className={cx('mc-sample', isStale(healthLoadedAt, now) && 'stale')}>
            {healthError ? 'system sample failed' : ageLabel(healthLoadedAt, now)}
          </span>
        </div>
        <div className="mc-actions">
          <button type="button" className="mc-action" onClick={onOpenKnowledge}>
            <Workflow size={14} /> Inspect loop
          </button>
          <button type="button" className="mc-action" onClick={onOpenProviders}>
            <KeyRound size={14} /> Providers
          </button>
          <button
            type="button"
            className="mc-action mc-action-icon"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh Mission Control"
          >
            <RefreshCw size={14} className={refreshing ? 'spin' : undefined} />
          </button>
        </div>
      </header>

      <div className="mc-readouts">
        <div className="mc-readout">
          <span>telemetry</span>
          <b><i className={cx('mc-led', stream === 'live' && 'on')} />{stream === 'live' ? 'streaming' : stream}</b>
          <small>{inFlight} running · {queueDepth} queued</small>
        </div>
        <div className="mc-readout">
          <span>system proof</span>
          <b>{metric(healthCounts?.working)} / {health?.health.subsystems.length ?? '—'}</b>
          <small>{metric(healthCounts?.degraded)} degraded · {metric(healthCounts?.unknown)} unknown</small>
        </div>
        <div className="mc-readout">
          <span>provider sample</span>
          <b>{providerSampleUnknown ? 'unknown' : `${reachable} / ${providers.length}`}</b>
          <small>{providerSampleUnknown ? 'endpoint unread' : `${configured} configured · ${ageLabel(providersLoadedAt, now)}`}</small>
        </div>
        <div className="mc-readout">
          <span>promotion</span>
          <b>{!governance ? 'unknown' : governance.promotion_allowed ? 'eligible' : 'refused'}</b>
          <small>{govAge} · {governance?.head ? governance.head.slice(0, 8) : 'HEAD unknown'}</small>
        </div>
      </div>

      <div className="mc-workbench">
        <section className="mc-flow">
          <SectionTitle
            icon={<Workflow size={14} />}
            tail={<span className="mc-sample">{queueAge}</span>}
          >
            live evolution path
          </SectionTitle>
          <div className="mc-stages" aria-label="Loop lifecycle">
            <Stage
              index="01"
              label="discover"
              state={queueStage}
              detail={!queue ? 'queue unread' : queue.incomplete ? 'source failure' : `${queue.n_candidates} ranked`}
            />
            <Stage
              index="02"
              label="attempt"
              state={attemptState}
              detail={!latest ? 'no reported attempt' : latest.resolved_ts ? latest.outcome || latest.state : 'in progress'}
            />
            <Stage
              index="03"
              label="gate"
              state={gateState}
              detail={!latest || latest.gates_passed == null ? 'verdict unreported' : latest.gates_passed ? 'passed' : 'failed'}
            />
            <Stage
              index="04"
              label="promote"
              state={promoteState}
              detail={!governance ? 'unknown' : governance.promotion_allowed ? 'human decision' : 'blocked'}
              terminal
            />
          </div>

          <div className="mc-attempt">
            <div className="mc-attempt-main">
              <span>{latest ? `intent #${latest.intent_id}` : 'no current run surface'}</span>
              <b>{latest?.task_id || 'The API exposes history, not a live loop run.'}</b>
              <p>
                {latest?.error || latest?.reason ||
                  'Run lifecycle, stop reason, execution budget, trace and worker are not served by the current loop endpoints.'}
              </p>
            </div>
            <dl className="mc-attempt-meta">
              <div><dt>lane</dt><dd>{latest?.lane || 'not reported'}</dd></div>
              <div><dt>worker</dt><dd>{latest?.worker || 'not reported'}</dd></div>
              <div><dt>run / trace</dt><dd>{latest?.run_id || latest?.trace_id || 'not reported'}</dd></div>
              <div><dt>history</dt><dd>{attemptAge}</dd></div>
            </dl>
          </div>
        </section>

        <section className="mc-governance">
          <SectionTitle
            icon={<ShieldCheck size={14} />}
            tail={<StateBadge state={governanceState} compact />}
          >
            governance
          </SectionTitle>
          <p className="mc-verdict">
            {governance?.verdict || 'No governance verdict was returned. Promotion remains unproven.'}
          </p>
          <div className="mc-gates">
            {(governance?.gates || []).map((gate) => (
              <div className="mc-gate" key={gate.id}>
                <span className={cx('mc-gate-mark', `mc-gate-${coerceState(gate.state)}`)} />
                <div>
                  <b>{gate.id.replace(/_/g, ' ')}</b>
                  <span>{gate.headline}</span>
                </div>
                <em>{gate.provenance}</em>
              </div>
            ))}
            {!governance?.gates?.length && (
              <div className="mc-unknown-copy">No gates were served; this is UNKNOWN, not permission.</div>
            )}
          </div>
        </section>
      </div>

      <details className="mc-evidence">
        <summary>
          <span><Gauge size={14} /> Evidence console</span>
          <span className="mc-evidence-summary">
            providers · bounds · unresolved system checks
          </span>
        </summary>
        <div className="mc-evidence-grid">
          <section>
            <SectionTitle
              icon={<KeyRound size={14} />}
              tail={<span className={cx('mc-sample', providerSampleStale && 'stale')}>{ageLabel(providersLoadedAt, now)}</span>}
            >
              declared vs measured providers
            </SectionTitle>
            {providersError && <p className="mc-inline-error">{providersError}</p>}
            <div className="mc-provider-table">
              <div className="mc-provider-head">
                <span>provider</span><span>declared</span><span>reachability</span><span>state</span>
              </div>
              {providers.map((row) => (
                <div className="mc-provider-row" key={row.name}>
                  <span><b>{row.display_name}</b><small>{row.name}</small></span>
                  <span>{row.configured ? 'configured' : row.requires_key ? 'no key' : 'not configured'}</span>
                  <span>{providerSampleUnknown ? 'unknown' : row.available ? 'answered' : row.last_error || 'did not answer'}</span>
                  <StateBadge state={providerState(row, providerSampleUnknown)} compact />
                </div>
              ))}
              {providers.length === 0 && (
                <div className="mc-unknown-copy">No provider rows were returned. Availability is UNKNOWN.</div>
              )}
            </div>
          </section>

          <section>
            <SectionTitle icon={<Gauge size={14} />}>visible bounds</SectionTitle>
            <dl className="mc-bounds">
              <div><dt>queue request cap</dt><dd>{metric(queue?.limit)} rows</dd></div>
              <div><dt>queue returned</dt><dd>{metric(queue?.returned ?? queue?.candidates.length)}</dd></div>
              <div><dt>queue response</dt><dd>{metric(queue?.response_bytes)} bytes</dd></div>
              <div><dt>rows dropped for size</dt><dd>{metric(queue?.dropped_for_size)}</dd></div>
              <div><dt>attempt history cap</dt><dd>{metric(attempts?.limit)} rows</dd></div>
              <div><dt>run iterations / budget</dt><dd>not served</dd></div>
            </dl>
            <p className="mc-bound-note">
              HTTP list bounds are visible. The current backend does not expose the active loop report,
              so execution bounds and stop reason cannot be shown honestly.
            </p>
          </section>

          <section>
            <SectionTitle
              icon={<Activity size={14} />}
              tail={<span className="mc-sample">{ageLabel(healthLoadedAt, now)}</span>}
            >
              unresolved checks
            </SectionTitle>
            {healthError && <p className="mc-inline-error">{healthError}</p>}
            <div className="mc-issues">
              {issues.map((item) => (
                <div key={item.name}>
                  <StateBadge state={coerceState(item.state)} compact />
                  <span><b>{item.name}</b><small>{item.headline}</small></span>
                </div>
              ))}
              {!healthError && issues.length === 0 && health && (
                <div className="mc-unknown-copy">Every cheap system check was exercised and held.</div>
              )}
              {!health && !healthError && (
                <div className="mc-unknown-copy">The system glance has not returned yet.</div>
              )}
            </div>
          </section>
        </div>
      </details>

      <footer className="mc-foot">
        <span><Radio size={12} /> SSE carries watcher and mission-queue events; loop history refreshes after reports.</span>
        <span><Clock3 size={12} /> Stale samples remain labelled; they never become a live claim.</span>
      </footer>
    </section>
  );
}
