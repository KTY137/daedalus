import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import type {
  FourfoldGraphNode,
  FourfoldPayload,
  FourfoldPlane
} from '@/shared/contracts';
import { imperativeTiming, useReducedMotionPref } from '@/shared/ui/motion';
import {
  FOURFOLD_ORDER,
  PLANE_COLOR,
  PLANE_LABEL,
  PLANE_MARK,
  layoutFourfold,
  searchFourfold,
  type FourfoldLayout
} from './fourfold';

export type FourfoldScope = 'overview' | 'all';

export interface FourfoldStageProps {
  payload: FourfoldPayload;
  layout: FourfoldLayout;
  scope: FourfoldScope;
  onLayout: (layout: FourfoldLayout) => void;
  onScope: (scope: FourfoldScope) => void;
}

function nodeLabel(node: FourfoldGraphNode): string {
  const pieces = node.id.split(/[\\/]/);
  const tail = pieces[pieces.length - 1] || node.id;
  return tail.length > 48 ? `${tail.slice(0, 45)}…` : tail;
}

/**
 * The complete Fourfold read is rendered by Sigma/WebGL instead of the small
 * SVG neighbourhood renderer: the explicit whole-graph option must remain a
 * usable graph when it contains thousands of modules.
 */
export function FourfoldStage({ payload, layout, scope, onLayout, onScope }: FourfoldStageProps) {
  const container = useRef<HTMLDivElement>(null);
  const renderer = useRef<Sigma | null>(null);
  const graph = payload.fourfold.graph;
  const [enabled, setEnabled] = useState<Set<FourfoldPlane>>(() => new Set(FOURFOLD_ORDER));
  const [selected, setSelected] = useState('');
  const [hovered, setHovered] = useState('');
  const [query, setQuery] = useState('');
  const [renderError, setRenderError] = useState('');
  const deferredQuery = useDeferredValue(query);
  const reducedMotion = useReducedMotionPref();

  const planeRows = useMemo(
    () => new Map(payload.fourfold.planes.map((plane) => [plane.plane, plane])),
    [payload]
  );
  const nodesById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes]
  );
  const visibleNodes = useMemo(
    () => graph.nodes.filter((node) => enabled.has(node.plane)),
    [enabled, graph.nodes]
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)),
    [graph.edges, visibleIds]
  );
  const positions = useMemo(() => layoutFourfold(visibleNodes, layout), [layout, visibleNodes]);
  const hits = useMemo(() => searchFourfold(visibleNodes, deferredQuery), [deferredQuery, visibleNodes]);
  const selectedNode = nodesById.get(selected);

  useEffect(() => {
    if (selected && !visibleIds.has(selected)) setSelected('');
  }, [selected, visibleIds]);

  useEffect(() => {
    const host = container.current;
    if (!host || visibleNodes.length === 0) return;
    const computed = getComputedStyle(host);
    const labelColor = computed.getPropertyValue('--ink').trim() || '#d9e1ea';
    const edgeColor = computed.getPropertyValue('--edge').trim() || '#64748b';
    const crossEdgeColor = computed.getPropertyValue('--edge-hot').trim() || '#8793a5';
    const positionById = new Map(positions.map((position) => [position.id, position]));
    const nextGraph = new Graph({ type: 'mixed', multi: true, allowSelfLoops: true });

    visibleNodes.forEach((node) => {
      const position = positionById.get(node.id)!;
      nextGraph.addNode(node.id, {
        x: position.x,
        y: position.y,
        size: position.size,
        label: nodeLabel(node),
        color: PLANE_COLOR[node.plane],
        forceLabel: visibleNodes.length <= 90,
        zIndex: FOURFOLD_ORDER.length - FOURFOLD_ORDER.indexOf(node.plane)
      });
    });
    // Sigma frames the occupied bounding box. Sparse/asymmetric data would
    // otherwise move the semantic centre away from the concentric guides (or
    // vertically squash the four bands). Hidden bounds stabilize that camera
    // geometry and are renderer-only: they never enter payload counts/search.
    const bounds = layout === 'sphere'
      ? [[-7.2, 0], [7.2, 0], [0, -5.2], [0, 5.2]]
      : [[0, -6], [0, 6]];
    bounds.forEach(([x, y], index) => {
      nextGraph.addNode(`__fourfold-layout-bound:${index}`, {
        x,
        y,
        size: 0,
        label: '',
        color: labelColor,
        hidden: true,
        zIndex: -1
      });
    });
    visibleEdges.forEach((edge, index) => {
      const attributes = {
        color: edge.cross_plane ? crossEdgeColor : edgeColor,
        size: edge.cross_plane ? 1.15 : 0.65,
        type: edge.directed ? 'arrow' : 'line',
        zIndex: edge.cross_plane ? 1 : 0
      };
      const key = `fourfold-edge:${index}`;
      if (edge.directed) {
        nextGraph.addDirectedEdgeWithKey(key, edge.source, edge.target, attributes);
      } else {
        nextGraph.addUndirectedEdgeWithKey(key, edge.source, edge.target, attributes);
      }
    });

    try {
      setRenderError('');
      const nextRenderer = new Sigma(nextGraph, host, {
        allowInvalidContainer: true,
        defaultNodeColor: PLANE_COLOR.code,
        defaultEdgeColor: edgeColor,
        labelColor: { color: labelColor },
        labelFont: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        labelSize: 11,
        labelDensity: visibleNodes.length > 800 ? 0.25 : 0.7,
        labelGridCellSize: visibleNodes.length > 800 ? 140 : 90,
        labelRenderedSizeThreshold: visibleNodes.length > 240 ? 8 : 5,
        renderEdgeLabels: false,
        enableEdgeEvents: false,
        zIndex: true
      });
      renderer.current = nextRenderer;
      nextRenderer.on('clickNode', ({ node }) => setSelected(node));
      nextRenderer.on('enterNode', ({ node }) => setHovered(node));
      nextRenderer.on('leaveNode', () => setHovered(''));
      nextRenderer.on('clickStage', () => setSelected(''));
      return () => {
        renderer.current = null;
        nextRenderer.kill();
      };
    } catch (reason) {
      setRenderError(reason instanceof Error ? reason.message : 'WebGL-Graph konnte nicht gezeichnet werden.');
      return undefined;
    }
  }, [layout, positions, visibleEdges, visibleNodes]);

  useEffect(() => {
    const current = renderer.current;
    if (!current) return;
    const active = selected || hovered;
    current.setSetting('nodeReducer', (node, data) => ({
      ...data,
      highlighted: active === node,
      forceLabel: active === node || data.forceLabel
    }));
    current.refresh();
  }, [hovered, positions, selected]);

  const togglePlane = useCallback((plane: FourfoldPlane) => {
    setEnabled((current) => {
      const next = new Set(current);
      if (next.has(plane)) {
        if (next.size > 1) next.delete(plane);
      } else {
        next.add(plane);
      }
      return next;
    });
  }, []);

  const focusNode = useCallback((id: string) => {
    setSelected(id);
    setQuery('');
    const current = renderer.current;
    const display = current?.getNodeDisplayData(id);
    if (!current || !display) return;
    const point = current.graphToViewport(display);
    const state = current.getViewportZoomedState(point, Math.min(current.getCamera().ratio, 0.35));
    void current.getCamera().animate(state, imperativeTiming('move', reducedMotion));
  }, [reducedMotion]);

  const zoom = useCallback((direction: 'in' | 'out' | 'home') => {
    const camera = renderer.current?.getCamera();
    if (!camera) return;
    if (direction === 'home') void camera.animatedReset(imperativeTiming('exit', reducedMotion));
    else if (direction === 'in') void camera.animatedZoom(imperativeTiming('ack', reducedMotion));
    else void camera.animatedUnzoom(imperativeTiming('ack', reducedMotion));
  }, [reducedMotion]);

  return (
    <div className="stage fourfold-stage" data-layout={layout} data-scope={scope}>
      <aside className="stage-rail fourfold-rail">
        <header className="fourfold-title">
          <div className="stage-eyebrow">Project Twin · Fourfold</div>
          <h1 className="stage-focus">Vier Ebenen</h1>
          <p>
            {graph.n_nodes_shown.toLocaleString('de-DE')} von {graph.n_nodes_total.toLocaleString('de-DE')} Knoten geladen ·{' '}
            {visibleNodes.length.toLocaleString('de-DE')} sichtbar · {visibleEdges.length.toLocaleString('de-DE')} Relationen
          </p>
          {scope === 'all' && enabled.has('code') ? (
            <strong className="fourfold-census">
              Ganzer Graph: alle {graph.n_modules_shown.toLocaleString('de-DE')} Module angezeigt.
            </strong>
          ) : scope === 'all' ? (
            <strong className="fourfold-bounded">
              Ganzer Graph geladen; die Code-Ebene ist gerade ausgeblendet.
            </strong>
          ) : graph.truncated ? (
            <span className="fourfold-bounded">
              Übersicht begrenzt; {graph.n_nodes_total - graph.n_nodes_shown} Knoten liegen außerhalb.
            </span>
          ) : (
            <span className="fourfold-census">Die Übersicht enthält bereits den ganzen Graphen.</span>
          )}
        </header>

        <section className="fourfold-planes" aria-label="Fourfold-Ebenen">
          {FOURFOLD_ORDER.map((plane) => {
            const row = planeRows.get(plane);
            const absent = !row || row.status === 'absent';
            return (
              <button
                key={plane}
                type="button"
                aria-pressed={enabled.has(plane)}
                disabled={absent}
                onClick={() => togglePlane(plane)}
                title={absent ? row?.reason || `${PLANE_LABEL[plane]} nicht beobachtet` : `${PLANE_LABEL[plane]} ein-/ausblenden`}
                style={{ '--plane-color': PLANE_COLOR[plane] } as CSSProperties}
              >
                <i>{PLANE_MARK[plane]}</i>
                <span>{PLANE_LABEL[plane]}</span>
                <b>{row?.shown_count ?? 0}</b>
                <small>{absent ? 'fehlt' : row?.status === 'partial' ? 'partiell' : 'vollständig'}</small>
              </button>
            );
          })}
        </section>

        <div className="fourfold-search">
          <label htmlFor="fourfold-node-search">Knoten finden</label>
          <input
            id="fourfold-node-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Modul, Typ oder Dokument"
          />
          {hits.length > 0 && (
            <div className="fourfold-hits">
              {hits.map((node) => (
                <button key={node.id} type="button" onClick={() => focusNode(node.id)}>
                  <span>{nodeLabel(node)}</span>
                  <small>{PLANE_MARK[node.plane]} · {node.kind}</small>
                </button>
              ))}
            </div>
          )}
        </div>

        <section className="stage-reading fourfold-reading" aria-live="polite">
          <div className="stage-eyebrow">Auswahl</div>
          {selectedNode ? (
            <>
              <div className="stage-reading-name">{nodeLabel(selectedNode)}</div>
              <div className="stage-reading-path">{selectedNode.id}</div>
              <p className="stage-reading-rel">
                {PLANE_LABEL[selectedNode.plane]} · {selectedNode.kind}
                {selectedNode.language ? ` · ${selectedNode.language}` : ''}
                {selectedNode.loc ? ` · ${selectedNode.loc} Zeilen` : ''}
              </p>
            </>
          ) : (
            <p className="stage-reading-unmeasured">Klick einen Knoten an, um seine belegten Eigenschaften zu lesen.</p>
          )}
        </section>

        <div className="stage-tools fourfold-tools">
          <div className="stage-tools-group" role="group" aria-label="Fourfold-Darstellung">
            <button type="button" aria-pressed={layout === 'layers'} onClick={() => onLayout('layers')}>Schichten</button>
            <button type="button" aria-pressed={layout === 'sphere'} onClick={() => onLayout('sphere')}>Kugel</button>
          </div>
          <p className="stage-tools-note">
            {layout === 'layers'
              ? 'Vier getrennte Bänder; Querverbindungen laufen zwischen den Ebenen.'
              : 'Geschichtete Kugel als 2-D-Projektion: Wissen im Kern, Code auf der Außenhaut.'}
          </p>
          <div className="stage-tools-group" role="group" aria-label="Graphumfang">
            <button type="button" aria-pressed={scope === 'overview'} onClick={() => onScope('overview')}>Übersicht</button>
            <button type="button" aria-pressed={scope === 'all'} onClick={() => onScope('all')}>Ganzer Graph</button>
          </div>
          <div className="stage-tools-group" role="group" aria-label="Kamera">
            <button type="button" onClick={() => zoom('out')} aria-label="Weiter weg">−</button>
            <button type="button" onClick={() => zoom('home')}>Einpassen</button>
            <button type="button" onClick={() => zoom('in')} aria-label="Näher">+</button>
          </div>
        </div>
      </aside>

      <div className="stage-field fourfold-field">
        <div className={`fourfold-guides ${layout}`} aria-hidden="true">
          {layout === 'layers'
            ? FOURFOLD_ORDER.map((plane) => <span key={plane}>{PLANE_MARK[plane]} · {PLANE_LABEL[plane]}</span>)
            : [...FOURFOLD_ORDER].reverse().map((plane) => <i key={plane} style={{ '--shell-color': PLANE_COLOR[plane] } as CSSProperties}><span>{PLANE_MARK[plane]}</span></i>)}
        </div>
        {visibleNodes.length > 0 && (
          <div
            ref={container}
            className="fourfold-canvas"
            role="application"
            tabIndex={0}
            aria-label={`Fourfold-Graph, ${layout === 'layers' ? 'in vier Schichten' : 'als geschichtete Kugel'}, ${visibleNodes.length} sichtbare Knoten. Ziehen verschiebt, das Mausrad zoomt.`}
          />
        )}
        {(visibleNodes.length === 0 || renderError) && (
          <div className="fourfold-render-empty">
            <strong>Graph nicht darstellbar.</strong>
            <span>{renderError || 'Die ausgewählten Ebenen enthalten keine beobachteten Knoten.'}</span>
          </div>
        )}
        <div className="fourfold-edge-key" aria-label="Kantenlegende">
          <span><i className="within" /> innerhalb einer Ebene</span>
          <span><i className="cross" /> zwischen Ebenen</span>
          {graph.n_hyperedges_total > 0 && <span>{graph.n_hyperedges_total} Hyperkanten gezählt, nicht zu Paaren erfunden</span>}
        </div>
      </div>
    </div>
  );
}
