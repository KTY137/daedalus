import { Suspense, lazy, useMemo } from 'react';
import { AlertTriangle, Boxes, Fingerprint, RefreshCw, Waypoints } from 'lucide-react';
import { GlassButton, cx } from '../components/glass';
import { StateBadge, SurfaceState } from './StateBadge';
import type { HealthState } from './health';
import type { MapFindings } from '../components/CodeMap';
import type { StructurePayload } from '../types';
import type { Theme } from '../hooks/useTheme';
import type { LoopData } from './useLoop';

const CodeMap = lazy(() => import('../components/CodeMap').then((m) => ({ default: m.CodeMap })));

/** Counts worth putting on the ribbon, in the order a reader wants them. */
const RIBBON: Array<{ key: string; label: string; hint: string }> = [
  { key: 'modules', label: 'modules', hint: 'every module the reachability pass parsed' },
  { key: 'islands', label: 'islands', hint: 'built, and nothing in the repo reaches them' },
  { key: 'shims', label: 'shims', hint: 're-exports nothing reaches — remove, do not wire in' },
  { key: 'unreached', label: 'unreached', hint: 'islands + shims + anything else nothing reaches' },
  { key: 'test_only', label: 'test-only', hint: 'imported only by tests — tests are not callers' },
  { key: 'unknown', label: 'unclassified', hint: 'the engine could not classify these — a finding about the MAP' },
  { key: 'dark_switches', label: 'dark switches', hint: 'env vars the code reads that no doc mentions' },
  { key: 'doc_drift', label: 'doc drift', hint: 'switches documented and code disagree' }
];

/**
 * GRAPH — the distilled codebase graph.
 *
 * Two layers, and they come from different places with different strength:
 *
 *   the SKELETON  `/api/structure`'s module graph: every module, every import
 *                 edge, coloured by churn × complexity.
 *   the FINDINGS  the generated architecture snapshot's reachability verdict:
 *                 islands and shims. Digest-covered and freshness-gated, so it
 *                 can be REFUSED — and when it is refused this view says so
 *                 instead of drawing a clean map.
 */
export function GraphSpace({
  project,
  structure,
  loading,
  error,
  onRefresh,
  theme,
  loop
}: {
  project: string;
  structure?: StructurePayload;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  theme: Theme;
  loop: LoopData;
}) {
  const arch = loop.architecture.data?.architecture;
  const queue = loop.queue.data?.queue;

  /**
   * Island/shim NAMES.
   *
   * `/api/loop/architecture` serves counts and refuses to serve the module
   * lists. The names are only obtainable as a side effect of the picker
   * ranking them as work — which means they arrive only when the snapshot is
   * TRUSTED, and only up to the queue's limit. Every one of those conditions
   * is a reason the list can be short or empty while the count is not, so each
   * one produces a stated `namesWithheld` rather than a quiet zero.
   */
  const findings: MapFindings = useMemo(() => {
    const islands: string[] = [];
    const shims: string[] = [];
    (queue?.candidates || []).forEach((c) => {
      const module = typeof c.evidence?.module === 'string' ? (c.evidence.module as string) : '';
      if (!module) return;
      if (c.source === 'map_island') islands.push(module);
      else if (c.source === 'map_shim') shims.push(module);
    });

    // PRECEDENCE MATTERS. Names that DID arrive are never reported as
    // withheld, whatever any other surface says about the snapshot — a panel
    // that lists six modules while claiming the list is withheld is worse than
    // either message on its own. Only two things can be true here: no names at
    // all (say why), or fewer names than the snapshot counts (say how many).
    const claimed = (arch?.counts?.islands || 0) + (arch?.counts?.shims || 0);
    const named = islands.length + shims.length;
    let namesWithheld = '';
    if (named === 0) {
      if (loop.queue.error) {
        namesWithheld = `the work queue could not be read (${loop.queue.error.message}), and the names are only obtainable from it`;
      } else if (!loop.queue.data) {
        namesWithheld = 'the work queue has not been read yet';
      } else if ((queue?.degraded_sources || []).includes('map')) {
        const detail = queue?.sources?.map as { trust?: { reason?: string } } | undefined;
        namesWithheld = detail?.trust?.reason
          || 'the generated snapshot was suppressed, so no island or shim was ranked';
      } else if (arch && !arch.trusted) {
        namesWithheld = arch.trust_reason || 'the architecture snapshot is not trusted';
      } else if (claimed > 0) {
        namesWithheld = `the snapshot counts ${claimed} island/shim module(s) and none reached this page — the counts endpoint serves no module lists, so names arrive only as ranked queue candidates`;
      }
    } else if (claimed > named) {
      namesWithheld = `${named} of the snapshot's ${claimed} island/shim module(s) are named here. The counts endpoint serves no module lists, so names arrive only as ranked queue candidates (limit ${queue?.limit ?? '?'}) — the rest are counted but unnamed`;
    }

    return {
      islands,
      shims,
      namesWithheld,
      counts: arch?.counts,
      trusted: arch?.trusted
    };
  }, [queue, arch, loop.queue.error, loop.queue.data]);

  // The snapshot's state, in the five-word vocabulary.
  const snapshotState: HealthState = loop.architecture.error
    ? (loop.architecture.error.kind === 'network' || loop.architecture.error.kind === 'timeout' ? 'unknown' : 'degraded')
    : !arch
      ? 'unknown'
      : !arch.read
        ? 'absent'
        : arch.trusted
          ? 'working'
          : 'degraded';

  const counts = arch?.counts || {};

  return (
    <section className="space graph-space">
      <header className="space-head">
        <div className="space-title">
          <Waypoints size={18} />
          <div>
            <h2>Graph</h2>
            <p>The skeleton — every module, every import edge, and what the reachability pass found in it.</p>
          </div>
        </div>
        <div className="space-actions">
          <GlassButton onClick={onRefresh} disabled={loading} title="Re-index the repository">
            <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Re-index
          </GlassButton>
        </div>
      </header>

      {/* ---- findings ribbon: the counts, with the snapshot's own verdict
             attached to them. When the snapshot is not trusted the numbers are
             struck through, because they describe a tree that is not this one. */}
      <div className={cx('findings-ribbon', snapshotState !== 'working' && 'untrusted')}>
        <div className="fr-trust">
          <StateBadge state={snapshotState} />
          <div>
            <b>architecture snapshot</b>
            <p>
              {loop.architecture.error
                ? loop.architecture.error.message
                : arch
                  ? (arch.trust_reason || 'no reason given')
                  : 'not read yet'}
            </p>
          </div>
        </div>
        <div className="fr-counts">
          {RIBBON.filter((r) => counts[r.key] != null).map((r) => (
            <span className="fr-count" key={r.key} title={r.hint}>
              <b>{counts[r.key].toLocaleString()}</b>
              <em>{r.label}</em>
            </span>
          ))}
          {Object.keys(counts).length === 0 && (
            <span className="fr-count fr-empty">
              <b>—</b><em>no counts read</em>
            </span>
          )}
        </div>
      </div>

      {findings.namesWithheld && (
        <div className="fr-withheld" role="alert">
          <AlertTriangle size={14} />
          <span>
            {findings.islands.length + findings.shims.length === 0 ? (
              <>
                <b>Island and shim names are withheld, not absent.</b> {findings.namesWithheld}. The
                graph below is still the real structure; the reachability verdict on top of it is not
                available.
              </>
            ) : (
              <>
                <b>The named findings below are a partial list.</b> {findings.namesWithheld}.
              </>
            )}
          </span>
        </div>
      )}

      <div className="space-body graph-body">
        <Suspense
          fallback={
            <SurfaceState
              kind="loading"
              icon={<RefreshCw size={22} className="spin" />}
              title="Opening the map"
              detail="The WebGL graph stack loads on demand so the chat surface starts fast."
            />
          }
        >
          {!project ? (
            <SurfaceState
              kind="empty"
              icon={<Boxes size={22} />}
              title="No project selected"
              detail="Pick a project in the top bar to index and draw its dependency graph."
            />
          ) : (
            <CodeMap
              project={project}
              data={structure}
              loading={loading}
              error={error}
              onRefresh={onRefresh}
              theme={theme}
              findings={findings}
            />
          )}
        </Suspense>
      </div>

      <p className="graph-foot">
        <Fingerprint size={12} /> The skeleton comes from <code>/api/structure</code> (indexed live).
        The island/shim verdict comes from <code>docs/architecture-state.json</code> via{' '}
        <code>/api/loop/*</code> — generated, digest-covered, and refused when it does not describe
        this HEAD.
      </p>
    </section>
  );
}
