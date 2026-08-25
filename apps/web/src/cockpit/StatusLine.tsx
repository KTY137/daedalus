import type { HealthPayload } from '../api';
import type { GovernancePayload, StructurePayload, TopologyPayload } from '../types';

/**
 * One line of state, and every item in it is a fact somebody can check.
 *
 * The rule that makes this line worth having: an item that could not be read
 * says so. "Health unbekannt" and "alles grün" are different sentences and
 * this line will never print the second one for the first situation — the
 * five-state health vocabulary exists precisely so a run that was not proven
 * cannot collapse into a pass.
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
  if (!health?.health) return { text: 'Zustand wird gelesen …', tone: 'muted' };
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

  return (
    <div className="statusline" role="status" aria-label="Systemzustand">
      <span className="status-item">
        <b>{project || '—'}</b>
        {s?.repo_root ? <span className="muted"> · {s.repo_root}</span> : null}
      </span>

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

      <span className={`status-item ${governance?.promotion_allowed ? 'ok' : 'warn'}`}>
        {governance
          ? governance.promotion_allowed
            ? 'Promotion offen'
            : `Promotion gesperrt${governance.blockers?.length ? ` · ${governance.blockers.length} Blocker` : ''}`
          : 'Promotion unbekannt'}
      </span>

      {s ? (
        <span className="status-item">
          {s.n_files} Dateien im Kern
          {ignored ? ` · ${ignored.count} ausgeschlossen von ${ignored.n_files_scanned} gescannt` : ''}
        </span>
      ) : null}

      {/* Labelled "Karte", because the topology item beside it reports a
          DIFFERENT graph with a bigger node count. Two unlabelled numbers for
          "the graph" on one bar is how a reader ends up trusting whichever they
          read first. */}
      {graph ? (
        <span
          className="status-item"
          title="Die gezeichnete Karte ist die nach Hitze gerankte, gedeckelte Teilmenge des Index — nicht der ganze Importgraph."
        >
          Karte {graph.nodes.length} Knoten · {graph.edges.length} Kanten
          {graph.n_edges_offmap ? ` · ${graph.n_edges_offmap} führen heraus` : ''}
          {graph.truncated ? ' · beschnitten' : ''}
        </span>
      ) : null}

      {topology?.topology?.available ? (
        <span
          className={`status-item ${topology.topology.connected_components > 1 ? 'warn' : ''}`}
          title={`${topology.topology.graph_type}. Methode: ${topology.topology.method} — ${topology.topology.reason}`}
        >
          Importgraph {topology.topology.node_count} Knoten ·{' '}
          {topology.topology.connected_components === 1
            ? 'zusammenhängend'
            : `${topology.topology.connected_components} Komponenten`}
        </span>
      ) : null}

      {s?.backend ? (
        <span className="status-item muted">
          {s.backend.tree_sitter ? 'tree-sitter' : 'kein tree-sitter'}
          {s.backend.lizard ? ' · lizard' : ' · kein lizard'}
        </span>
      ) : null}

      <span className="status-item">
        <span className={`dot ${streamLive ? 'ok' : 'muted'}`} aria-hidden="true" />
        {streamLive ? 'live' : 'kein Ereignisstrom'}
        {typeof inFlight === 'number' ? ` · ${inFlight} laufen` : ''}
        {typeof queued === 'number' ? ` · ${queued} in der Schlange` : ''}
      </span>
    </div>
  );
}
