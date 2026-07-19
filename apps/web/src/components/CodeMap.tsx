import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Crosshair,
  Flame,
  Map as MapIcon,
  RefreshCw,
  Scissors,
  Waypoints,
  X
} from 'lucide-react';
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';
import { GlassButton, GlassCard } from './glass';
import { DistillResult } from './StructureSheet';
import { distill } from '../api';
import type {
  DistillPayload,
  StructureGraph,
  StructureGraphNode,
  StructurePayload
} from '../types';
import type { Theme } from '../hooks/useTheme';

interface CodeMapProps {
  project: string;
  data?: StructurePayload;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  theme: Theme;
}

function num(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : '0';
}

/**
 * Heat scores span wildly different ranges — a five-file repo tops out around
 * 3.5, a large one runs into the hundreds. Rounding unconditionally printed
 * "hot 4" as the ceiling of a graph whose real maximum was 3.5, i.e. a number
 * no module in the repo actually had. Keep a decimal while the range is small.
 */
function fmtScore(value: number, max: number): string {
  if (!Number.isFinite(value)) return '0';
  return max < 10 ? value.toFixed(1) : Math.round(value).toLocaleString();
}

/* ------------------------------------------------------------------ *
 * Heat ramp — the product insight made visible.
 *
 * `score` is churn x complexity: rot lives where code is complex AND
 * changing. Cold code must RECEDE (low-contrast slate that sinks into the
 * scene) and hot code must POP (amber -> red). Stops are hand-picked per
 * theme so the cold end sits close to the backdrop in both.
 * ------------------------------------------------------------------ */
type Stop = [number, [number, number, number]];

const RAMP_DARK: Stop[] = [
  [0.0, [56, 68, 90]],
  [0.3, [74, 118, 168]],
  [0.55, [106, 168, 255]],
  [0.78, [240, 195, 74]],
  [1.0, [255, 92, 96]]
];

const RAMP_LIGHT: Stop[] = [
  [0.0, [188, 198, 214]],
  [0.3, [124, 158, 202]],
  [0.55, [56, 122, 220]],
  [0.78, [226, 158, 30]],
  [1.0, [214, 45, 60]]
];

function rampColor(t: number, theme: Theme): string {
  const stops = theme === 'light' ? RAMP_LIGHT : RAMP_DARK;
  const x = Math.max(0, Math.min(1, t));
  let lo = stops[0];
  let hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    if (x >= stops[i][0] && x <= stops[i + 1][0]) {
      lo = stops[i];
      hi = stops[i + 1];
      break;
    }
  }
  const span = hi[0] - lo[0] || 1;
  const k = (x - lo[0]) / span;
  const ch = (i: number) => Math.round(lo[1][i] + (hi[1][i] - lo[1][i]) * k);
  return `rgb(${ch(0)}, ${ch(1)}, ${ch(2)})`;
}

/**
 * Heat scores are long-tailed (a couple of monsters, a long cold tail), so a
 * linear normalisation would flatten everything below the top file into one
 * indistinguishable cold blob. log1p spreads the mass where the modules
 * actually are while keeping the ordering exact and the ends anchored to the
 * real min/max, which the legend prints.
 */
function heatT(score: number, maxScore: number): number {
  if (!(maxScore > 0) || !Number.isFinite(score) || score <= 0) return 0;
  return Math.log1p(score) / Math.log1p(maxScore);
}

/**
 * The floor is a *hit-target* constraint, not an aesthetic one: a leaf module
 * with fan-in 0 still has to be clickable to be distillable, and anything
 * under ~4px is a coin-flip with a real mouse (measured — a 2.4px node ate
 * repeated genuine clicks while only synthetic pixel-exact events landed).
 * Cold code is made to recede with colour instead, which costs no hit area.
 */
const MIN_SIZE = 4.5;
const MAX_SIZE = 15;

/**
 * Size encodes `fan_in` (how many modules import this one), NOT `loc`.
 * `score` already folds complexity in, and complexity tracks loc closely — so
 * sizing by loc would just re-draw the colour axis. fan_in is orthogonal: it
 * is blast radius. Big AND hot therefore reads as "lots depends on this and it
 * is rotting", which is exactly the triage target. sqrt because perceived
 * magnitude follows disc area, not radius.
 */
function nodeSize(fanIn: number, maxFanIn: number): number {
  if (!(maxFanIn > 0)) return 5;
  const k = Math.sqrt(Math.max(0, fanIn) / maxFanIn);
  return MIN_SIZE + (MAX_SIZE - MIN_SIZE) * k;
}

interface Palette {
  edge: string;
  edgeHi: string;
  dim: string;
  label: string;
  ring: string;
}

function palette(theme: Theme): Palette {
  return theme === 'light'
    ? {
        // Light theme needs a notably darker edge than the dark theme needs a
        // lighter one: near-white scene + low-alpha strokes washed the import
        // lines out almost completely at 14%.
        edge: 'rgba(52, 72, 104, .30)',
        edgeHi: 'rgba(40, 90, 180, .70)',
        dim: 'rgba(150, 162, 180, .13)',
        label: 'rgba(23, 30, 44, .92)',
        ring: '#1b2436'
      }
    : {
        edge: 'rgba(150, 180, 230, .11)',
        edgeHi: 'rgba(140, 190, 255, .5)',
        dim: 'rgba(120, 140, 175, .09)',
        label: 'rgba(236, 240, 247, .92)',
        ring: '#0b1220'
      };
}

/**
 * Movement II — the living code map.
 *
 * A WebGL (Sigma.js) module dependency graph over `structure.graph`, with the
 * churn x complexity heat painted straight onto the nodes and "Distill this"
 * wired to the same `/api/distill` path the Structure sheet uses.
 */
export function CodeMap({ project, data, loading, error, onRefresh, theme }: CodeMapProps) {
  const graph = data?.structure?.graph;

  return (
    <section className="panel feature-panel codemap-panel">
      <div className="panel-head">
        <Waypoints size={18} />
        <div>
          <h2>Code Map</h2>
          <p>Every module, every import edge — coloured by churn x complexity. Hot means rotting.</p>
        </div>
        <button
          type="button"
          className="iconbtn struct-refresh"
          onClick={onRefresh}
          disabled={loading}
          title="Re-index repository"
          aria-label="Re-index repository"
        >
          <RefreshCw size={15} className={loading ? 'spin' : undefined} />
        </button>
      </div>

      {loading && (
        <div className="struct-state">
          <RefreshCw size={22} className="spin" />
          <strong>Indexing {project || 'repository'}…</strong>
          <span>The first scan of a big repo can take minutes. The map draws as soon as it lands.</span>
        </div>
      )}

      {!loading && error && (
        <div className="struct-state struct-state-error">
          <AlertTriangle size={22} />
          <strong>Couldn't load the map</strong>
          <span>{error}</span>
          <GlassButton onClick={onRefresh}><RefreshCw size={14} /> Retry</GlassButton>
        </div>
      )}

      {!loading && !error && data && !graph && (
        <div className="struct-state">
          <MapIcon size={22} />
          <strong>No dependency graph</strong>
          <span>This backend didn't return <code>structure.graph</code> for the project.</span>
        </div>
      )}

      {!loading && !error && !data && (
        <div className="struct-state">
          <MapIcon size={22} />
          <strong>No map yet</strong>
          <span>Open this sheet to index the project and draw its dependency graph.</span>
        </div>
      )}

      {!loading && !error && graph && (
        graph.nodes.length === 0 ? (
          <div className="struct-state">
            <MapIcon size={22} />
            <strong>Nothing to draw</strong>
            <span>The index found no modules with dependency data in this repository.</span>
          </div>
        ) : (
          <CodeMapCanvas key={`${project}:${theme}`} project={project} graph={graph} theme={theme} />
        )
      )}
    </section>
  );
}

function CodeMapCanvas({
  project,
  graph,
  theme
}: {
  project: string;
  graph: StructureGraph;
  theme: Theme;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const layoutRef = useRef<FA2Layout | null>(null);
  const stopTimer = useRef<number | undefined>(undefined);

  // Hover/selection live in refs so the Sigma reducers always read fresh
  // values without tearing the renderer down and rebuilding it.
  const hoverRef = useRef<string | null>(null);
  const neighborRef = useRef<Set<string> | null>(null);
  const selectedRef = useRef<string | null>(null);
  /** Re-derives the focus/neighbour highlight; owned by the renderer effect. */
  const refocusRef = useRef<(() => void) | null>(null);

  const [selected, setSelected] = useState<StructureGraphNode | null>(null);
  const [laying, setLaying] = useState(false);

  const [distilling, setDistilling] = useState('');
  const [distillResult, setDistillResult] = useState<DistillPayload | undefined>();
  const [distillError, setDistillError] = useState('');
  const [distillTarget, setDistillTarget] = useState('');
  const [showSlice, setShowSlice] = useState(false);

  const byId = useMemo(() => {
    const m = new Map<string, StructureGraphNode>();
    graph.nodes.forEach((n) => m.set(n.module, n));
    return m;
  }, [graph]);

  const stats = useMemo(() => {
    let maxScore = 0;
    let maxFanIn = 0;
    let minScore = Number.POSITIVE_INFINITY;
    graph.nodes.forEach((n) => {
      if (n.score > maxScore) maxScore = n.score;
      if (n.score < minScore) minScore = n.score;
      if (n.fan_in > maxFanIn) maxFanIn = n.fan_in;
    });
    if (!Number.isFinite(minScore)) minScore = 0;
    return { maxScore, minScore, maxFanIn };
  }, [graph]);

  /** Stop the layout worker but keep the renderer alive. */
  const stopLayout = useCallback(() => {
    if (stopTimer.current !== undefined) {
      window.clearTimeout(stopTimer.current);
      stopTimer.current = undefined;
    }
    if (layoutRef.current?.isRunning()) layoutRef.current.stop();
    setLaying(false);
  }, []);

  /**
   * Kick ForceAtlas2 for a bounded burst. It runs in a **web worker**, so the
   * main thread stays free to pan/zoom/scroll while the graph settles — the
   * cockpit is supposed to feel snappy, and a 2k-node layout on the UI thread
   * would freeze it solid. We auto-stop so we never pin a core forever.
   */
  const runLayout = useCallback((ms: number) => {
    if (!layoutRef.current) return;
    if (stopTimer.current !== undefined) window.clearTimeout(stopTimer.current);
    if (!layoutRef.current.isRunning()) layoutRef.current.start();
    setLaying(true);
    stopTimer.current = window.setTimeout(() => {
      if (layoutRef.current?.isRunning()) layoutRef.current.stop();
      setLaying(false);
      stopTimer.current = undefined;
    }, ms);
  }, []);

  useEffect(() => {
    const container = holder.current;
    if (!container) return undefined;

    const pal = palette(theme);
    const { maxScore, maxFanIn } = stats;
    const g = new Graph({ type: 'directed', multi: false, allowSelfLoops: false });

    // Seed positions on a jittered circle — FA2 cannot escape a degenerate
    // all-zero start, and a ring unfolds far more evenly than pure random.
    const n = graph.nodes.length;
    graph.nodes.forEach((node, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, n);
      const r = 100 + Math.random() * 40;
      const t = heatT(node.score, maxScore);
      g.addNode(node.module, {
        x: Math.cos(a) * r + (Math.random() - 0.5) * 12,
        y: Math.sin(a) * r + (Math.random() - 0.5) * 12,
        size: nodeSize(node.fan_in, maxFanIn),
        color: rampColor(t, theme),
        label: node.module.split(/[\\/]/).pop() || node.module,
        heat: t,
        zIndex: Math.round(t * 100)
      });
    });

    // The backend guarantees no dangling endpoints, but a self-loop or a
    // repeated pair would still throw — guard rather than trust.
    graph.edges.forEach((e) => {
      if (e.source === e.target) return;
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) return;
      if (g.hasEdge(e.source, e.target)) return;
      g.addEdge(e.source, e.target, { color: pal.edge, size: 0.6 });
    });

    const big = n > 400;
    const renderer = new Sigma(g, container, {
      allowInvalidContainer: true,
      defaultEdgeColor: pal.edge,
      labelColor: { color: pal.label },
      labelSize: 11,
      labelWeight: '600',
      labelDensity: 0.6,
      labelGridCellSize: 90,
      // Only the structurally-important nodes earn a label; otherwise a big
      // repo turns into unreadable text soup and costs a fortune to draw. The
      // threshold is on rendered size, so it tightens automatically as you
      // zoom out and relaxes as you zoom into a neighbourhood.
      labelRenderedSizeThreshold: n > 1200 ? 9 : big ? 7.5 : 3,
      renderEdgeLabels: false,
      enableEdgeEvents: false,
      // Dropping edges/labels during a drag is what keeps a 2k-node graph at
      // 60fps while panning.
      hideEdgesOnMove: big,
      hideLabelsOnMove: big,
      zIndex: true,
      minCameraRatio: 0.05,
      maxCameraRatio: 14,
      nodeReducer: (key, attrs) => {
        const hovered = hoverRef.current;
        const sel = selectedRef.current;
        const focus = hovered || sel;
        const res: Record<string, unknown> = { ...attrs };
        if (focus) {
          const near = key === focus || neighborRef.current?.has(key);
          if (!near) {
            // Push the unrelated repo into the background rather than hiding
            // it — you keep the sense of scale, you lose the noise.
            res.color = pal.dim;
            res.label = '';
            res.zIndex = 0;
          } else {
            res.forceLabel = true;
            res.zIndex = 200;
          }
        }
        if (key === sel) {
          res.highlighted = true;
          res.forceLabel = true;
          res.zIndex = 300;
        }
        return res;
      },
      edgeReducer: (key, attrs) => {
        const focus = hoverRef.current || selectedRef.current;
        const res: Record<string, unknown> = { ...attrs };
        if (focus) {
          const [s, t] = g.extremities(key);
          if (s === focus || t === focus) {
            res.color = pal.edgeHi;
            res.size = 1.2;
            res.zIndex = 250;
          } else {
            res.hidden = true;
          }
        }
        return res;
      }
    });

    sigmaRef.current = renderer;

    /**
     * Hover and selection are two independent sources of focus, so the
     * neighbour set is always DERIVED from whichever is active rather than
     * written by each handler. Doing it the other way round meant that simply
     * moving the pointer off the canvas (say, to reach "Distill this") fired
     * `leaveNode`, cleared the neighbours out from under the still-active
     * selection, and greyed out the very dependencies you selected the node
     * to look at.
     */
    const applyFocus = () => {
      const focus = hoverRef.current || selectedRef.current;
      neighborRef.current = focus && g.hasNode(focus)
        ? new Set<string>(g.neighbors(focus))
        : null;
      renderer.refresh({ skipIndexation: true });
    };
    refocusRef.current = applyFocus;

    renderer.on('enterNode', ({ node }) => {
      hoverRef.current = node;
      applyFocus();
      container.style.cursor = 'pointer';
    });
    renderer.on('leaveNode', () => {
      hoverRef.current = null;
      applyFocus();
      container.style.cursor = 'default';
    });
    renderer.on('clickNode', ({ node }) => {
      selectedRef.current = node;
      setSelected(byId.get(node) || null);
      applyFocus();
    });
    renderer.on('clickStage', () => {
      selectedRef.current = null;
      setSelected(null);
      applyFocus();
    });

    const supervisor = new FA2Layout(g, {
      settings: {
        // inferSettings picks barnesHutOptimize etc. from the graph order.
        ...forceAtlas2.inferSettings(g),
        slowDown: 8,
        // Spread has to scale with the graph or a big repo collapses into one
        // unreadable disc where the heat signal is invisible: weaken gravity
        // and push repulsion up so packages separate. Small graphs need the
        // opposite — without gravity a handful of nodes just drift apart.
        gravity: big ? 0.35 : 1.2,
        scalingRatio: big ? 18 : 6,
        // Anti-collision makes nodes readable but is O(expensive); only worth
        // it while the graph is small enough to converge quickly.
        adjustSizes: n <= 800
      }
    });
    layoutRef.current = supervisor;
    supervisor.start();
    setLaying(true);
    // Scale the burst with the graph: small repos settle almost instantly,
    // big ones need longer, but nothing runs unbounded.
    const budget = Math.min(9000, 2200 + n * 3);
    stopTimer.current = window.setTimeout(() => {
      if (supervisor.isRunning()) supervisor.stop();
      setLaying(false);
      stopTimer.current = undefined;
    }, budget);

    return () => {
      if (stopTimer.current !== undefined) window.clearTimeout(stopTimer.current);
      stopTimer.current = undefined;
      supervisor.kill();
      layoutRef.current = null;
      renderer.kill();
      sigmaRef.current = null;
      refocusRef.current = null;
      hoverRef.current = null;
      neighborRef.current = null;
      selectedRef.current = null;
    };
  }, [graph, theme, stats, byId]);

  async function runDistill(target: string) {
    if (!target || distilling) return;
    setDistilling(target);
    setDistillTarget(target);
    setDistillError('');
    setShowSlice(false);
    try {
      const res = await distill(project, target);
      setDistillResult(res);
    } catch (err) {
      setDistillResult(undefined);
      setDistillError(err instanceof Error ? err.message : String(err));
    } finally {
      setDistilling('');
    }
  }

  function clearSelection() {
    selectedRef.current = null;
    setSelected(null);
    refocusRef.current?.();
  }

  const shownNodes = graph.nodes.length;
  const shownEdges = graph.edges.length;

  return (
    <>
      {/* ---- no silent caps: say exactly what is on screen ---- */}
      {graph.truncated ? (
        <div className="map-truncated" role="status">
          <AlertTriangle size={15} />
          <span>
            Bounded view — showing the <b>{num(shownNodes)} hottest</b> of{' '}
            <b>{num(graph.n_nodes_total)}</b> modules and {num(shownEdges)} of{' '}
            {num(graph.n_edges_total)} edges. This is not the whole repository.
          </span>
        </div>
      ) : (
        <div className="map-complete" role="status">
          Complete graph — {num(shownNodes)} modules, {num(shownEdges)} edges.
        </div>
      )}

      <div className="map-stage">
        <div className="map-canvas" ref={holder} />

        {/* ---- legend: anchors the colour ramp to real numbers ---- */}
        <div className="map-legend">
          <div className="ml-title"><Flame size={12} /> churn × complexity</div>
          <div
            className="ml-ramp"
            style={{
              background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1]
                .map((t) => rampColor(t, theme))
                .join(', ')})`
            }}
          />
          <div className="ml-scale">
            <span>cold {fmtScore(stats.minScore, stats.maxScore)}</span>
            <span>hot {fmtScore(stats.maxScore, stats.maxScore)}</span>
          </div>
          <div className="ml-note">size = fan-in (blast radius), max {num(stats.maxFanIn)}</div>
        </div>

        <div className="map-tools">
          {laying && <span className="map-chip laying"><RefreshCw size={11} className="spin" /> settling</span>}
          <button type="button" className="map-chip btn" onClick={() => runLayout(4000)} disabled={laying}>
            <Waypoints size={11} /> Re-run layout
          </button>
          <button
            type="button"
            className="map-chip btn"
            onClick={() => {
              stopLayout();
              sigmaRef.current?.getCamera().animatedReset({ duration: 260 });
            }}
          >
            <Crosshair size={11} /> Fit
          </button>
        </div>

        {selected && (
          <div className="map-inspector">
            <div className="mi-head">
              <strong title={selected.module}>{selected.module}</strong>
              <button type="button" className="iconbtn" onClick={clearSelection} aria-label="Close inspector">
                <X size={14} />
              </button>
            </div>

            <div className="mi-metrics">
              <span className="struct-chip"><b>{selected.language || 'unknown'}</b></span>
              <span className="struct-chip">{num(selected.loc)} loc</span>
              <span className="struct-chip">churn {num(selected.churn)}</span>
              <span className="struct-chip">fan-in {num(selected.fan_in)}</span>
            </div>

            <div className="mi-heat">
              <div className="mi-heat-label">
                <span>heat</span>
                <b style={{ color: rampColor(heatT(selected.score, stats.maxScore), theme) }}>
                  {fmtScore(selected.score, stats.maxScore)}
                </b>
              </div>
              <div className="mi-heat-track">
                <div
                  className="mi-heat-fill"
                  style={{
                    width: `${Math.round(heatT(selected.score, stats.maxScore) * 100)}%`,
                    background: rampColor(heatT(selected.score, stats.maxScore), theme)
                  }}
                />
              </div>
            </div>

            <GlassButton
              className="distill-btn mi-distill"
              onClick={() => runDistill(selected.module)}
              disabled={distilling === selected.module}
            >
              <Scissors size={13} />{' '}
              {distilling === selected.module ? 'Distilling…' : 'Distill this'}
            </GlassButton>

            {(distilling || distillResult || distillError) && (
              <DistillResult
                distilling={distilling}
                result={distillResult}
                error={distillError}
                target={distillTarget}
                showSlice={showSlice}
                onToggleSlice={() => setShowSlice((v) => !v)}
              />
            )}
          </div>
        )}

        {/* Follows the `.railcard` precedent: keep the glass edge treatment,
            drop the per-element blur (see the rule in styles.css). */}
        {!selected && (
          <GlassCard className="map-hint">
            Click a node to inspect it and distill it.
          </GlassCard>
        )}
      </div>
    </>
  );
}
