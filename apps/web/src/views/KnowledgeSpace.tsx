import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Archive,
  Beaker,
  FileWarning,
  Fingerprint,
  Inbox,
  Library,
  ListOrdered,
  RefreshCw,
  ScrollText,
  ShieldQuestion,
  Telescope
} from 'lucide-react';
import { GlassButton, cx } from '../components/glass';
import {
  AllSourcesReadNote,
  AssessmentRow,
  DegradedSourcesBanner,
  StateBadge,
  StateLegend,
  SurfaceState,
  VerdictLine
} from './StateBadge';
import { assessFetch, assessPickerSources, evidenceRows, tally } from './health';
import type { Assessment } from './health';
import type {
  LoopArchitectureBlock,
  LoopAttemptsBlock,
  LoopCandidate,
  LoopQueueBlock
} from '../api';
import type { LoopData } from './useLoop';

type Tab = 'queue' | 'attempts' | 'architecture';

const TABS: Array<{ key: Tab; label: string; icon: ReactNode }> = [
  { key: 'queue', label: 'Work queue', icon: <ListOrdered size={14} /> },
  { key: 'attempts', label: 'Attempts', icon: <ScrollText size={14} /> },
  { key: 'architecture', label: 'Architecture', icon: <Fingerprint size={14} /> }
];

function num(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

/** The picker's bands, so a score can be shown as what it is: a stated
 * priority plus a measurement, never one opaque number. */
const BAND_MEANING: Record<string, string> = {
  map_island: 'generated map · unreachable module',
  map_shim: 'generated map · re-export nothing reaches',
  inventory_island: 'hand-written inventory · island',
  inventory_stale: 'hand-written inventory · stale',
  eval_miss: 'eval regression',
  hotspot: 'churn × complexity hotspot'
};

/** How many candidates the notes say were withheld. The count only ever
 * appears inside free-form note text, so it is parsed rather than read. */
function withheldFromNotes(notes: string[]): number {
  let total = 0;
  notes.forEach((note) => {
    const m = /\((\d+)\s+candidate\(s\)\s+withheld\)/i.exec(note);
    if (m) total += Number(m[1]) || 0;
  });
  return total;
}

/* ------------------------------------------------------------------ *
 * One candidate. The EVIDENCE is the content; the score is a footnote.
 * ------------------------------------------------------------------ */
function CandidateCard({ candidate, rank }: { candidate: LoopCandidate; rank: number }) {
  const evidence = useMemo(() => evidenceRows(candidate.evidence), [candidate.evidence]);
  const gates = Array.isArray(candidate.gate_paths) ? (candidate.gate_paths as unknown[]) : [];

  return (
    <article className="cand">
      <header className="cand-head">
        <span className="cand-rank">{rank}</span>
        <div className="cand-title">
          <h4 title={candidate.task_id}>{candidate.task_id}</h4>
          <p>{candidate.reason || 'no reason recorded'}</p>
        </div>
        <span className="cand-source" title={BAND_MEANING[candidate.source] || candidate.source}>
          {candidate.source}
        </span>
      </header>

      {/* The measurement it was scored FROM — the interesting content. */}
      <div className="cand-evidence">
        <div className="cand-evidence-head">
          <Telescope size={13} />
          <span>Evidence — what this was measured from</span>
        </div>
        {evidence.length === 0 ? (
          <p className="cand-noev">
            No evidence came back with this candidate. The picker refuses to construct one without
            evidence, so an empty block here means the field was lost in transit, not that the work
            is unjustified — treat the ranking below as unbacked.
          </p>
        ) : (
          <dl className="hev">
            {evidence.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      {/* Score, decomposed. A band is a PRIOR; only the offset is measured, and
          cross-band order is a stated priority rather than a claim about
          evidence. Rendering one fused number would hide exactly that. */}
      <div className="cand-score" title="score = band (a stated priority for the source) + measured offset">
        <span className="cs-part cs-band">
          band <b>{num(candidate.band)}</b>
          <em>stated priority</em>
        </span>
        <span className="cs-plus">+</span>
        <span className="cs-part cs-offset">
          offset <b>{num(candidate.measured_offset)}</b>
          <em>measured</em>
        </span>
        <span className="cs-plus">=</span>
        <span className="cs-part cs-total">
          score <b>{num(candidate.score)}</b>
        </span>
      </div>

      {gates.length > 0 && (
        <div className="cand-gates">
          gate paths: {gates.map((g) => <code key={String(g)}>{String(g)}</code>)}
        </div>
      )}

      {candidate.instruction && (
        <details className="cand-instruction">
          <summary>the instruction this would hand a fixer</summary>
          <p>{candidate.instruction}</p>
        </details>
      )}
    </article>
  );
}

/* ------------------------------------------------------------------ *
 * Work queue
 * ------------------------------------------------------------------ */
function QueueTab({ block, sourceAssessments }: { block: LoopQueueBlock; sourceAssessments: Assessment[] }) {
  const degraded = block.degraded_sources || [];
  const notes = block.notes || [];
  const withheld = withheldFromNotes(notes);
  const candidates = block.candidates || [];

  return (
    <>
      {degraded.length > 0
        ? <DegradedSourcesBanner sources={degraded} what="this queue" />
        : <AllSourcesReadNote what="the ranking below" />}

      {candidates.length === 0 && (
        degraded.length > 0 ? (
          <SurfaceState
            kind="error"
            icon={<FileWarning size={22} />}
            title={withheld > 0
              ? `${withheld} candidate(s) were withheld — this is not an empty queue`
              : 'The queue is empty AND a source failed'}
            detail={
              <>
                {degraded.join(', ')} could not be consulted. “There is no work” and “a source could
                not be read” produce the identical empty list, and this one is the second.
              </>
            }
          />
        ) : (
          <SurfaceState
            kind="empty"
            icon={<Inbox size={22} />}
            title="Every source was read, and none of them names any work"
            detail="This empty queue is a finding: nothing was withheld to produce it."
          />
        )
      )}

      {candidates.length > 0 && (
        <div className="cand-list">
          {candidates.map((c, i) => <CandidateCard key={c.task_id || i} candidate={c} rank={i + 1} />)}
        </div>
      )}

      {(block.dropped_for_size ?? 0) > 0 && (
        <p className="loop-note loop-note-warn">
          {block.dropped_for_size} candidate row(s) were dropped by the server's response-size bound.
          `degraded_sources` and the notes are never trimmed, so the reason for a short list is always
          intact — but the list itself is not complete.
        </p>
      )}

      {notes.length > 0 && (
        <section className="loop-section">
          <h3><Beaker size={14} /> Notes the picker wrote while building this queue</h3>
          <ul className="loop-notes">
            {notes.map((n) => (
              <li key={n} className={cx(/SUPPRESSED|unavailable|did not/i.test(n) && 'bad')}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="loop-section">
        <h3><ShieldQuestion size={14} /> Every source, and what this request established about it</h3>
        <VerdictLine items={sourceAssessments} subject="sources" />
        <div className="hrows">
          {sourceAssessments.map((item) => <AssessmentRow item={item} key={item.name} />)}
        </div>
      </section>

      {block.opt_in_sources_available === false && (
        <p className="loop-note">
          Two sources (<code>eval_gate</code>, <code>hotspots</code>) are not reachable from this page
          at all: each costs a whole-repo analysis pass, and a browser tab must not be able to start a
          multi-minute replay inside the server. They report <b>present</b>, never absent — the code is
          there, nothing ran it.
        </p>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * Attempts
 * ------------------------------------------------------------------ */
const OUTCOME_TONE: Record<string, string> = {
  clean: 'ok',
  no_change: 'warn',
  failed: 'bad',
  rejected: 'bad'
};

function AttemptsTab({ block }: { block: LoopAttemptsBlock }) {
  const rows = block.intents || [];
  const ledger = block.ledger;

  return (
    <>
      <DegradedSourcesBanner sources={block.degraded_sources || []} what="this history" />

      <div className="ledger-strip">
        <StateBadge
          state={ledger.error ? 'degraded' : !ledger.exists ? 'absent' : rows.length === 0 ? 'present' : 'working'}
        />
        <div>
          <b>spine ledger</b>
          <p>
            {ledger.error
              ? `the ledger exists and could not be read: ${ledger.error}`
              : !ledger.exists
                ? 'no ledger on this machine yet — nothing has recorded an intent here. That is a fresh checkout, not a failure, and it is NOT the same as an unreadable ledger.'
                : rows.length === 0
                  ? 'the ledger exists and this query matched nothing — the write path may never have run here'
                  : `read ${rows.length} intent(s), opened read-only`}
          </p>
          <code>{ledger.path}</code>
        </div>
      </div>

      {rows.length > 0 && (
        <div className="attempt-list">
          {rows.map((row) => (
            <article className={cx('attempt', row.error && 'attempt-bad')} key={row.intent_id}>
              <div className="at-top">
                <span className="at-id">#{row.intent_id}</span>
                <span className="at-task" title={row.task_id}>{row.task_id || '(no task id)'}</span>
                <span className={cx('at-outcome', OUTCOME_TONE[row.outcome || ''] || 'muted')}>
                  {row.outcome || row.state}
                </span>
              </div>
              <div className="at-meta">
                <span>{row.kind}</span>
                <span>{row.state}</span>
                {row.source && <span>via {row.source}</span>}
                {row.gates_passed != null && (
                  <span className={row.gates_passed ? 'ok' : 'bad'}>
                    gates {row.gates_passed ? 'passed' : 'failed'}
                  </span>
                )}
                {row.changed_paths != null && <span>{row.changed_paths} path(s) changed</span>}
                <span className="at-ts">{row.created_ts}</span>
              </div>
              {row.reason && <p className="at-reason">{row.reason}</p>}
              {row.error && <p className="at-error">{row.error}</p>}
              {row.resolved_ts == null && (
                <p className="at-open">
                  <StateBadge state="unknown" compact /> recorded and never resolved — an effect was begun
                  and its acknowledgement was lost. Reconcile it against the world before trusting it.
                </p>
              )}
            </article>
          ))}
        </div>
      )}

      {rows.length === 0 && !ledger.error && (
        <SurfaceState
          kind="empty"
          icon={<Archive size={22} />}
          title={ledger.exists ? 'No attempts matched' : 'Nothing has been attempted in this checkout'}
          detail={`kind filter: ${block.kind} · limit ${block.limit}`}
        />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * Architecture snapshot
 * ------------------------------------------------------------------ */
function ArchitectureTab({ block }: { block: LoopArchitectureBlock }) {
  const trust = block.trust || {};
  const freshness = trust.freshness || {};
  const counts = Object.entries(block.counts || {});
  const disagreements = Object.entries(block.count_disagreements || {});

  // Integrity and freshness are two independent questions and the endpoint
  // returns both. A snapshot whose digest verifies but describes a different
  // commit is intact AND useless, and one badge could not say that.
  const integrityState = trust.integrity === true ? 'working' : trust.integrity === false ? 'degraded' : 'unknown';
  const freshState = freshness.fresh === true ? 'working' : freshness.fresh === false ? 'degraded' : 'unknown';

  return (
    <>
      <DegradedSourcesBanner
        sources={block.degraded_sources || []}
        what="every count on this page"
      />

      {!block.read && (
        <SurfaceState
          kind="error"
          icon={<FileWarning size={22} />}
          title="No architecture snapshot was read"
          detail={<>Expected at <code>{block.path}</code>. Regenerate it with <code>daedalus map</code>.</>}
        />
      )}

      <div className="trust-grid">
        <div className="trust-cell">
          <StateBadge state={integrityState} />
          <b>integrity</b>
          <p>
            {trust.integrity === true
              ? "the snapshot's own digest covers its contents — it has not been hand-edited"
              : trust.integrity === false
                ? "the digest does NOT cover the contents — this file was hand-edited"
                : 'the endpoint did not report integrity'}
          </p>
        </div>
        <div className="trust-cell">
          <StateBadge state={freshState} />
          <b>freshness</b>
          <p>{freshness.reason || 'the endpoint did not report freshness'}</p>
          {freshness.recorded_head && (
            <dl className="hev">
              <div><dt>written against</dt><dd>{freshness.recorded_head}</dd></div>
              <div><dt>HEAD is</dt><dd>{freshness.actual_head || '(unknown)'}</dd></div>
              <div><dt>worktree dirty</dt><dd>{String(freshness.dirty ?? 'unknown')}</dd></div>
            </dl>
          )}
        </div>
        <div className="trust-cell">
          <StateBadge state={block.trusted ? 'working' : 'degraded'} />
          <b>verdict</b>
          <p>{block.trust_reason || trust.reason || 'no reason given'}</p>
        </div>
      </div>

      <section className="loop-section">
        <h3><Library size={14} /> Counts in the snapshot</h3>
        {!block.trusted && (
          <p className="loop-note loop-note-warn">
            These numbers are rendered struck through because the snapshot is not trusted. They are
            what the file says; they are not what the tree is.
          </p>
        )}
        <div className={cx('count-grid', !block.trusted && 'untrusted')}>
          {counts.map(([key, value]) => (
            <div className="count-cell" key={key}>
              <b>{num(value)}</b>
              <span>{key.replace(/_/g, ' ')}</span>
              {block.measured_lengths?.[key] != null && block.measured_lengths[key] !== value && (
                <em className="count-disagree">list holds {num(block.measured_lengths[key])}</em>
              )}
            </div>
          ))}
          {counts.length === 0 && <p className="loop-note">The snapshot carries no counts block.</p>}
        </div>
      </section>

      {disagreements.length > 0 && (
        <section className="loop-section">
          <h3><FileWarning size={14} /> The file tells two stories</h3>
          <p className="loop-note loop-note-warn">
            Its recorded counts and the lengths of its own lists disagree. That disagreement is worth
            more than either number.
          </p>
          <dl className="hev">
            {disagreements.map(([key, d]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>recorded {num(d.recorded)} · measured {num(d.measured)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section className="loop-section">
        <h3><Fingerprint size={14} /> Provenance</h3>
        <dl className="hev">
          <div><dt>path</dt><dd>{block.path}</dd></div>
          <div><dt>schema</dt><dd>{num(block.schema)}</dd></div>
          <div><dt>digest</dt><dd className="mono-wrap">{block.digest || '(none)'}</dd></div>
        </dl>
        {block.note && <p className="loop-note">{block.note}</p>}
      </section>
    </>
  );
}

/* ------------------------------------------------------------------ *
 * The space
 * ------------------------------------------------------------------ */
export function KnowledgeSpace({ loop, project }: { loop: LoopData; project: string }) {
  const [tab, setTab] = useState<Tab>('queue');

  const queueBlock = loop.queue.data?.queue;
  const sourceAssessments = useMemo(
    () => (queueBlock ? assessPickerSources(queueBlock.sources || {}, queueBlock.notes || []) : []),
    [queueBlock]
  );

  // The three endpoints themselves, assessed with the same vocabulary. A dead
  // backend is `unknown` — it is not an empty page.
  const endpoints: Assessment[] = useMemo(() => [
    assessFetch('/api/loop/queue', {
      loading: loop.queue.loading, error: loop.queue.error, loadedAt: loop.queue.loadedAt,
      asks: 'does the loop know what to do next, and why?'
    }),
    assessFetch('/api/loop/attempts', {
      loading: loop.attempts.loading, error: loop.attempts.error, loadedAt: loop.attempts.loadedAt,
      asks: 'what has the loop tried, and how did it end?'
    }),
    assessFetch('/api/loop/architecture', {
      loading: loop.architecture.loading, error: loop.architecture.error, loadedAt: loop.architecture.loadedAt,
      asks: 'does the generated map describe this tree?'
    })
  ], [loop.queue, loop.attempts, loop.architecture]);

  const active = tab === 'queue' ? loop.queue : tab === 'attempts' ? loop.attempts : loop.architecture;
  const offline = active.error?.kind === 'network';

  return (
    <section className="space knowledge-space">
      <header className="space-head">
        <div className="space-title">
          <Library size={18} />
          <div>
            <h2>Knowledge</h2>
            <p>What the system has established about itself — and, just as loudly, what it has not.</p>
          </div>
        </div>
        <div className="space-actions">
          <GlassButton onClick={loop.reload} disabled={loop.busy} title="Re-read all three loop surfaces">
            <RefreshCw size={14} className={loop.busy ? 'spin' : undefined} /> Re-read
          </GlassButton>
        </div>
      </header>

      <StateLegend counts={tally([...sourceAssessments, ...endpoints])} />

      <nav className="space-tabs" role="tablist">
        {TABS.map((t) => {
          const f = t.key === 'queue' ? loop.queue : t.key === 'attempts' ? loop.attempts : loop.architecture;
          const block = t.key === 'queue'
            ? f.data && (f.data as { queue?: LoopQueueBlock }).queue
            : t.key === 'attempts'
              ? f.data && (f.data as { attempts?: LoopAttemptsBlock }).attempts
              : f.data && (f.data as { architecture?: LoopArchitectureBlock }).architecture;
          const incomplete = !!(block as { incomplete?: boolean } | undefined)?.incomplete;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              className={cx('space-tab', tab === t.key && 'active')}
              onClick={() => setTab(t.key)}
            >
              {t.icon}
              {t.label}
              {(incomplete || f.error) && <i className="tab-flag" title="this surface is incomplete" />}
            </button>
          );
        })}
      </nav>

      <div className="space-body">
        {active.loading && !active.data && (
          <SurfaceState
            kind="loading"
            icon={<RefreshCw size={22} className="spin" />}
            title="Reading…"
            detail={`asking the API about ${project || 'this checkout'}`}
          />
        )}

        {offline && (
          <SurfaceState
            kind="offline"
            icon={<FileWarning size={22} />}
            title="The Daedalus API is not answering"
            detail={
              <>
                Nothing answered on the loopback port. This page therefore knows <b>nothing</b> about the
                loop — which is not the same as the loop having nothing to do. Start it with{' '}
                <code>python -m daedalus.web_api</code> (loopback; do not widen the bind).
              </>
            }
            action={<GlassButton primary onClick={loop.reload}><RefreshCw size={14} /> Try again</GlassButton>}
          />
        )}

        {!offline && active.error && (
          <SurfaceState
            kind="error"
            icon={<FileWarning size={22} />}
            title={active.error.kind === 'notfound'
              ? 'This backend does not serve that endpoint'
              : active.error.kind === 'timeout'
                ? 'No answer in time — nothing was established either way'
                : 'The endpoint answered and refused'}
            detail={active.error.message}
            action={<GlassButton onClick={loop.reload}><RefreshCw size={14} /> Retry</GlassButton>}
          />
        )}

        {tab === 'queue' && queueBlock && (
          <QueueTab block={queueBlock} sourceAssessments={sourceAssessments} />
        )}
        {tab === 'attempts' && loop.attempts.data?.attempts && (
          <AttemptsTab block={loop.attempts.data.attempts} />
        )}
        {tab === 'architecture' && loop.architecture.data?.architecture && (
          <ArchitectureTab block={loop.architecture.data.architecture} />
        )}

        <section className="loop-section">
          <h3><ShieldQuestion size={14} /> The three endpoints themselves</h3>
          <VerdictLine items={endpoints} subject="endpoints" />
          <div className="hrows">
            {endpoints.map((item) => <AssessmentRow item={item} key={item.name} />)}
          </div>
        </section>
      </div>
    </section>
  );
}
