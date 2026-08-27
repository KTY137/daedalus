import type { HealthPayload } from '../api';
import type { GovernancePayload, StructurePayload, TopologyPayload } from '../types';

/**
 * Two lines of state, and every item in it is a fact somebody can check.
 *
 * The rule that makes this line worth having: an item that could not be read
 * says so, and says it differently from an item that WAS read and came back
 * empty. "Health unbekannt" and "alles grün" are different sentences, and
 * "Kern wird gelesen" and "Karte nicht verfügbar" are different sentences too
 * — the five-state health vocabulary exists precisely so a run that was not
 * proven cannot collapse into a pass, and that same discipline now applies to
 * every other item on the line, not only health.
 *
 * Nine facts in one run read as one sentence, so this groups them: line one is
 * scope and trust (where you are, whether it is healthy, whether it can
 * promote) — the two things worth a glance every time. Line two is the index
 * (what got scanned, what the map and the import graph found, which backend
 * read it) and liveness — detail you check when the first line asks a
 * question. A hairline divider marks a group boundary; the loose " · " inside
 * a group stays as it was.
 *
 * A finding that is actually a problem (a red health count, a blocked
 * promotion, an unproven claim, a disconnected graph) gets a tinted, bordered
 * chip via `.status-item.bad`/`.status-item.warn` in instruments.css — the
 * one piece of hierarchy this line needed. A plain fact never does; four
 * counts in matching chips would just be the rejected metric-tile row wearing
 * a status line's clothes.
 */

export interface StatusLineProps {
  project: string;
  health?: HealthPayload;
  healthError?: string;
  governance?: GovernancePayload;
  structure?: StructurePayload;
  topology?: TopologyPayload;
  inFlight?: number;
  queued?: number;
  streamLive?: boolean;
  onOpenHealth?: () => void;
}

function healthWord(health: HealthPayload | undefined, error: string | undefined): { text: string; tone: string } {
  if (error) return { text: `Zustand ungelesen — ${error}`, tone: 'bad' };
  if (!health?.health) return { text: 'Zustand wird gelesen …', tone: 'pending' };
  const c = health.health.counts;
  const bits = [
    c.working ? `${c.working} laufen` : '',
    c.degraded ? `${c.degraded} beeinträchtigt` : '',
    c.absent ? `${c.absent} fehlen` : '',
    c.present ? `${c.present} ungeprüft` : '',
    c.unknown ? `${c.unknown} unbekannt` : ''
  ].filter(Boolean);
  const tone = c.degraded || c.absent ? 'bad' : c.present || c.unknown ? 'warn' : 'ok';
  return { text: bits.join(' · ') || 'keine Prüfungen gemeldet', tone };
}

export function StatusLine({
  project,
  health,
  healthError,
  governance,
  structure,
  topology,
  inFlight,
  queued,
  streamLive,
  onOpenHealth
}: StatusLineProps) {
  const h = healthWord(health, healthError);
  const s = structure?.structure;
  const graph = s?.graph;
  const ignored = s?.ignored;
  const topo = topology?.topology;
  const promotionTone = !governance ? 'pending' : governance.promotion_allowed ? 'ok' : 'warn';

  return (
    <div className="statusline" role="status" aria-label="Systemzustand">
      <div className="status-row">
        <span className="status-group">
          <span className="status-item">
            <b>{project || '—'}</b>
            {s?.repo_root ? <span className="muted"> · {s.repo_root}</span> : null}
          </span>
        </span>

        <span className="status-sep" aria-hidden="true" />

        <span className="status-group">
          <button type="button" className={`status-item link ${h.tone}`} onClick={onOpenHealth}>
            <span className={`dot ${h.tone}`} aria-hidden="true" />
            {h.text}
          </button>

          {health?.health?.not_proven?.length ? (
            <span className="status-item warn">
              {health.health.not_proven.length} nicht bewiesen: {health.health.not_proven.slice(0, 3).join(', ')}
              {health.health.not_proven.length > 3 ? ' …' : ''}
            </span>
          ) : null}

          <span className={`status-item ${promotionTone}`}>
            {governance
              ? governance.promotion_allowed
                ? 'Promotion offen'
                : `Promotion gesperrt${governance.blockers?.length ? ` · ${governance.blockers.length} Blocker` : ''}`
              : 'Promotion unbekannt'}
          </span>
        </span>
      </div>

      <div className="status-row secondary">
        <span className="status-group">
          {s ? (
            <>
              <span className="status-item">
                {s.n_files} Dateien im Kern
                {ignored ? ` · ${ignored.count} ausgeschlossen von ${ignored.n_files_scanned} gescannt` : ''}
              </span>

              {/* Labelled "Karte", because the topology item beside it reports a
                  DIFFERENT graph with a bigger node count. Two unlabelled numbers
                  for "the graph" on one bar is how a reader ends up trusting
                  whichever they read first. */}
              {graph ? (
                <span
                  className="status-item"
                  title="Die gezeichnete Karte ist die nach Hitze gerankte, gedeckelte Teilmenge des Index — nicht der ganze Importgraph."
                >
                  Karte {graph.nodes.length} Knoten · {graph.edges.length} Kanten
                  {graph.n_edges_offmap ? ` · ${graph.n_edges_offmap} führen heraus` : ''}
                  {graph.truncated ? ' · beschnitten' : ''}
                </span>
              ) : (
                <span className="status-item muted">Karte nicht verfügbar — alter Index ohne Graph</span>
              )}

              {topo ? (
                topo.available ? (
                  <span
                    className={`status-item ${topo.connected_components > 1 ? 'warn' : ''}`}
                    title={`${topo.graph_type}. Methode: ${topo.method} — ${topo.reason}`}
                  >
                    Importgraph {topo.node_count} Knoten ·{' '}
                    {topo.connected_components === 1 ? 'zusammenhängend' : `${topo.connected_components} Komponenten`}
                  </span>
                ) : (
                  <span className="status-item muted" title={topo.reason}>
                    Importgraph nicht verfügbar
                  </span>
                )
              ) : (
                <span className="status-item pending">Importgraph wird gelesen …</span>
              )}

              {s.backend ? (
                <span className="status-item muted">
                  {s.backend.tree_sitter ? 'tree-sitter' : 'kein tree-sitter'}
                  {s.backend.lizard ? ' · lizard' : ' · kein lizard'}
                </span>
              ) : null}
            </>
          ) : (
            <span className="status-item pending">Kern und Karte werden gelesen …</span>
          )}
        </span>

        <span className="status-sep" aria-hidden="true" />

        <span className="status-group">
          <span className="status-item">
            <span className={`dot ${streamLive ? 'ok' : 'muted'}`} aria-hidden="true" />
            {streamLive ? 'live' : 'kein Ereignisstrom'}
            {typeof inFlight === 'number' ? ` · ${inFlight} laufen` : ''}
            {typeof queued === 'number' ? ` · ${queued} in der Schlange` : ''}
          </span>
        </span>
      </div>
    </div>
  );
}
