import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ThemeSpec } from '@/shared/ui/theme/types';
import { shortLabel, type Neighbourhood } from './graph';
import { DEFAULT_BUDGET, LABEL_PX, MORE_ID, labelSizeFor, layoutFor, type Line, type Placed } from './layout';
import { HOME, planeShift, useCamera } from './stage/camera';
import { Glyph, tierWeight } from './stage/Glyph';
import { Legend } from './stage/Legend';
import { edgeKey, edgeLanes, routeEdge, type Routing } from './stage/paths';
import { Reading } from './stage/Reading';
import { Tools, type StageMode } from './stage/Tools';

/**
 * The stage: one module and what actually reaches it.
 *
 * The page is a COMPOSITION, not a drawing dropped under a caption. A reading
 * rail on the left carries the name, the counts, what was left out, the legend
 * for the encodings, and the controls; the field to its right is the drawing
 * and nothing else. The previous version put a 40ch header block in the
 * top-left corner of the canvas and let the force layout dodge it, which is
 * how a 1440×900 page ended up with an empty upper-left third.
 *
 * Design rules this component is built to keep, all of them earned from
 * previous review rounds:
 *
 *  - it is operable. Wheel zooms at the cursor, drag pans, the arrow keys walk
 *    the neighbourhood IN THE DIRECTION PRESSED, and clicking a node re-centres
 *    on it. Nothing here is a picture of an interaction.
 *  - the drawing carries the data. Size is fan-in, the arrowhead is the
 *    direction of the import, the neutral rule is the heat rank, and the plane
 *    is the distance. What an encoding means is in the legend beside it.
 *  - the backbone is the resting state. The second level's own edges appear on
 *    hover or selection, so at rest the reader sees structure, not a hairball.
 *  - depth is real: three planes, each occluding the one behind it, each moving
 *    at its own rate under the camera. Off entirely under prefers-reduced-motion.
 *  - labels are never below 11px and never sit on top of a glyph.
 *  - what is not drawn is said out loud, by the caller, from the counts this
 *    component returns via `onBudget`.
 */

export interface StageProps {
  neighbourhood: Neighbourhood;
  theme: ThemeSpec;
  onFocus: (module: string) => void;
  /** rendered at the top of the reading rail — the caller owns the copy */
  header?: React.ReactNode;
  /** rendered over the stage, top-right (the decision card in 'float' themes) */
  overlay?: React.ReactNode;
  /** rendered over the stage, bottom-left (the chat card in 'card' themes) */
  panel?: React.ReactNode;
  onBudget?: (hidden1: number, hidden2: number, hiddenIds: string[]) => void;
  /** the reader pressed the aggregate glyph: show them what it stands for */
  onShowHidden?: (ids: string[]) => void;
}

/** Separator for the hidden-neighbour dependency key. Module paths never
 *  contain a unit separator, so two different sets cannot share a key. */
const SEP = String.fromCharCode(31);

/**
 * A theme knob, read defensively.
 *
 * `parallax`, `depthFog` and `depthBlur` arrive from the theme layer, and a
 * stored theme written before they existed simply does not carry them. A
 * missing knob must fall back to a sane default, not to `NaN` — a `NaN` in a
 * transform silently blanks the whole drawing.
 */
function knob(v: number | undefined, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

type EdgeWeight = 'focus' | 'backbone' | 'context';

function edgeWeight(l: Line): EdgeWeight {
  if (l.from.level === 0 || l.to.level === 0) return 'focus';
  if (l.backbone) return 'backbone';
  return 'context';
}

/**
 * Spatial keyboard navigation: the arrow key means the DIRECTION on screen.
 *
 * The old ring walked an array, so ArrowRight moved to whatever happened to be
 * next in the list — usually across the stage and back. Scoring candidates by
 * distance along the pressed axis plus a penalty on the perpendicular offset
 * is what makes "right" mean right in both representations, the four-column
 * one included.
 */
function stepTo(from: { x: number; y: number }, all: Placed[], dir: 'left' | 'right' | 'up' | 'down'): Placed | undefined {
  const ax = dir === 'left' ? -1 : dir === 'right' ? 1 : 0;
  const ay = dir === 'up' ? -1 : dir === 'down' ? 1 : 0;
  let best: Placed | undefined;
  let bestScore = Infinity;
  let wrap: Placed | undefined;
  let wrapScore = -Infinity;
  all.forEach((p) => {
    const dx = p.x - from.x;
    const dy = p.y - from.y;
    const along = dx * ax + dy * ay;
    const across = Math.abs(dx * ay + dy * ax);
    if (along > 4) {
      const score = along + across * 2.2;
      if (score < bestScore) {
        bestScore = score;
        best = p;
      }
      return;
    }
    // the furthest thing behind us, so the walk cycles instead of dead-ending
    const back = -along + across * 2.2;
    if (back > wrapScore) {
      wrapScore = back;
      wrap = p;
    }
  });
  return best ?? wrap;
}

export function Stage({ neighbourhood, theme, onFocus, header, overlay, panel, onBudget, onShowHidden }: StageProps) {
  const field = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 720 });
  const [mode, setMode] = useState<StageMode>('spatial');
  const [hover, setHover] = useState<string>('');
  const [cursor, setCursor] = useState<string>('');
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const { view, reduced, set, glide, zoomAt } = useCamera(neighbourhood.focus);

  useEffect(() => {
    const el = field.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const ordered = mode === 'ordered';
  const kind = ordered ? 'ordered' : theme.stage.layout;
  const glyph = ordered ? 'card' : theme.stage.glyph;
  const routing: Routing = ordered ? 'flow' : theme.stage.layout === 'cards' ? 'elbow' : theme.stage.layout === 'arcs' ? 'arc' : 'line';
  const isArcs = !ordered && theme.stage.layout === 'arcs';
  const asCard = glyph === 'card';
  const parallax = knob(theme.stage.parallax, 1);
  const fog = knob(theme.stage.depthFog, 0.35);
  const dof = knob(theme.stage.depthBlur, 0);

  /**
   * The field is the drawing's whole room.
   *
   * The rail is a sibling element rather than a keep-out box over the canvas,
   * so the layout centres in the space it actually has instead of laying out
   * across the full width and then shoving nodes out from under a header.
   * Nothing is drawn over the field any more, so there is nothing to avoid.
   */
  const layout = useMemo(
    () =>
      layoutFor(kind, neighbourhood, {
        width: size.w,
        height: size.h,
        sizeByFanIn: theme.stage.sizeByFanIn,
        avoid: [],
        ...DEFAULT_BUDGET
      }),
    [kind, neighbourhood, size.w, size.h, theme.stage.sizeByFanIn]
  );

  // `hiddenIds` is a new array on every layout; keying the effect on its
  // CONTENT is what stops "report the budget" from re-rendering its own input.
  const hiddenKey = layout.hiddenIds.join(SEP);
  useEffect(() => {
    onBudget?.(layout.hidden1, layout.hidden2, hiddenKey ? hiddenKey.split(SEP) : []);
  }, [layout.hidden1, layout.hidden2, hiddenKey, onBudget]);

  useEffect(() => {
    setCursor('');
  }, [neighbourhood.focus]);

  const active = hover || cursor;

  const litIds = useMemo(() => {
    if (!active) return null;
    const set2 = new Set<string>([active]);
    layout.lines.forEach((l) => {
      if (l.from.id === active) set2.add(l.to.id);
      if (l.to.id === active) set2.add(l.from.id);
    });
    return set2;
  }, [active, layout.lines]);

  /**
   * Parallax, applied to POSITIONS rather than to layers.
   *
   * Transforming three `<g>` elements by different amounts would move the
   * glyphs and leave every edge behind, because an edge's two endpoints live
   * on two different planes. Shifting the coordinates instead means a line
   * still touches both of its nodes at every point of the pan — the depth is
   * in the scene, not in a stack of sliding pictures.
   */
  const at = useCallback(
    (p: Placed): Placed => {
      const { dx, dy } = planeShift(view, p.level, reduced || ordered, parallax);
      return dx || dy ? { ...p, x: p.x + dx, y: p.y + dy } : p;
    },
    [view, reduced, ordered, parallax]
  );

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const rect = field.current?.getBoundingClientRect();
      if (!rect) return;
      zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - rect.left, e.clientY - rect.top);
    },
    [zoomAt]
  );

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    set((v) => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) }));
  };
  const endDrag = () => {
    drag.current = null;
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const ring = layout.placed.filter((p) => p.level !== 0);
    if (!ring.length) return;
    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomAt(1.25, size.w / 2, size.h / 2, true);
      return;
    }
    if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      zoomAt(1 / 1.25, size.w / 2, size.h / 2, true);
      return;
    }
    if (e.key === '0') {
      e.preventDefault();
      glide(HOME);
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      if (cursor) {
        e.preventDefault();
        if (cursor === MORE_ID) onShowHidden?.(layout.hiddenIds);
        else onFocus(cursor);
      }
      return;
    }
    const dir =
      e.key === 'ArrowRight' ? 'right' : e.key === 'ArrowLeft' ? 'left' : e.key === 'ArrowUp' ? 'up' : e.key === 'ArrowDown' ? 'down' : null;
    if (!dir) return;
    e.preventDefault();
    const here = layout.byId.get(cursor) ?? layout.placed.find((p) => p.level === 0) ?? ring[0];
    const next = stepTo(here, ring.filter((p) => p.id !== cursor), dir);
    if (next) setCursor(next.id);
  };

  const showEdge = (l: Line) => {
    const w = edgeWeight(l);
    if (ordered && Math.abs(l.from.x - l.to.x) < 1) return false;
    if (w !== 'context') return true;
    if (litIds && (litIds.has(l.from.id) || litIds.has(l.to.id))) return true;
    return !ordered && !theme.stage.backboneOnly;
  };

  const focusNode = layout.placed.find((p) => p.level === 0);
  const hasFar = layout.placed.some((p) => p.level === 2);

  /**
   * Lanes are decided once for the whole edge set, not per edge, because the
   * question "is this trace on its own" cannot be answered one trace at a time.
   */
  const lanes = useMemo(() => edgeLanes(layout.lines, routing), [layout.lines, routing]);

  /**
   * What the rail reads out, and how the reader got there.
   *
   * `hover` wins over `cursor` for the same reason it wins in `active`: the
   * pointer is the more recent intent. With neither, the focus — which always
   * exists — keeps the block from being an empty panel.
   */
  const readingSource = hover ? 'pointer' : cursor ? 'keyboard' : 'focus';
  const reading = layout.byId.get(hover || cursor || neighbourhood.focus) ?? focusNode;
  const focusLabel = focusNode?.label ?? shortLabel(neighbourhood.focus);

  /**
   * What the drawing put on the stage, counted from the layout rather than
   * from the neighbourhood: the budget drops nodes, and a caption taken from
   * the payload would name relations that are not on screen.
   *
   * `sided` is the honest gate on "Importeure links, Importe rechts". Where a
   * module's neighbours all point the same way the layout deliberately fills
   * both halves with them, and the sentence would then be false.
   */
  const counts = useMemo(() => {
    let ins = 0;
    let outs = 0;
    let far = 0;
    const tiers: [number, number, number] = [0, 0, 0];
    layout.placed.forEach((p) => {
      if (p.kind !== 'node') return;
      tiers[p.tier] += 1;
      if (p.level === 2) far += 1;
      else if (p.level === 1) {
        if (p.via === 'out') outs += 1;
        else ins += 1;
      }
    });
    return { ins, outs, far, tiers, sided: !ordered && ins > 0 && outs > 0, ordered };
  }, [layout.placed, ordered]);

  /**
   * Elevation as depth, from the theme's own four-step scale.
   *
   * `--shadow-pane` and its siblings are CSS box-shadows — several layers,
   * some of them `inset` — and none of that can be applied to an SVG mark. The
   * NUMBER behind them can: `form.elevationPane` is the same 0…4 step the
   * shadow string is generated from, so a theme that declares itself flat
   * (Depesche, 0) draws no filter at all and pays for none.
   */
  const lift = knob(theme.form.elevationPane, theme.form.elevation);

  /** Edges live on the plane of their DEEPER end, so a near node occludes them. */
  const renderEdges = (plane: 1 | 2) =>
    layout.lines.map((l, i) => {
      const deep = l.from.level === 2 && l.to.level === 2 ? 2 : 1;
      if (deep !== plane || !showEdge(l)) return null;
      const w = edgeWeight(l);
      /**
       * Lit means INCIDENT to the selection, not "both ends happen to be lit".
       * The old test lit every edge between two neighbours of the selected
       * node as well — selecting `containment.py` drew a hot line from the
       * focus to `cancel.py`, which is a relation the reader did not ask about
       * and the drawing had no business claiming.
       */
      const lit = Boolean(active) && (l.from.id === active || l.to.id === active);
      const muted = Boolean(litIds && !lit);
      /**
       * The focus's own relations are the subject of the picture and everything
       * else is context. At the old spread (1.5 / 1.2 / 0.8 at near-equal
       * opacity) a schematic theme's elbows read as one wiring loom with the
       * subject lost inside it, so the range is widened until the star around
       * the focus survives a squint.
       */
      const width = lit ? 2.2 : w === 'focus' ? 1.7 : w === 'backbone' ? 0.9 : 0.6;
      return (
        <path
          key={`${l.from.id}->${l.to.id}-${i}`}
          d={routeEdge(l, routing, theme.stage.curve, at, lanes.get(edgeKey(l)))}
          fill="none"
          stroke={lit ? 'var(--edge-hot)' : 'var(--edge)'}
          strokeWidth={width}
          strokeLinecap="round"
          opacity={lit ? 1 : muted ? 0.14 : w === 'focus' ? 1 : w === 'backbone' ? 0.38 : 0.14}
          markerEnd={w === 'context' && !lit ? undefined : lit ? 'url(#stage-arrow-hot)' : 'url(#stage-arrow)'}
        />
      );
    });

  const renderNodes = (plane: 0 | 1 | 2) =>
    layout.placed.map((p) => {
      const node = at(p);
      const isMore = p.kind === 'more';
      if ((isMore ? 1 : p.level) !== plane) return null;
      const dimmed = Boolean(litIds && !litIds.has(p.id));
      const selected = p.id === active;
      const centred = (asCard && !isMore) || isMore || p.anchor === 'middle';
      const sub = asCard && !isMore && p.node && (ordered || p.level !== 2)
        ? ordered
          ? `${p.node.fan_in} Importeure · Hitze ${Math.round(p.node.score)}`
          : `${p.node.fan_in} Importeure`
        : null;
      /**
       * A centred label belongs INSIDE a card and BELOW anything else. The
       * card layout centres every label because that is where a card wants
       * it; pairing that layout with the pearl glyph — which the Studio lets
       * you do — then printed the name across the sphere. The glyph decides.
       */
      const labelY = isMore
        ? node.y + 4
        : isArcs && p.level === 0
          ? node.y - (p.r + 32)
          : asCard
            ? node.y + (sub ? -2 : 5)
            : p.anchor === 'middle'
              ? node.y + p.r + 16
              : node.y + p.labelDy;
      const activate = () => {
        if (isMore) onShowHidden?.(layout.hiddenIds);
        else if (p.level !== 0) onFocus(p.id);
      };
      return (
        <g
          key={p.id}
          className="stage-node"
          data-tier={p.tier}
          data-plane={isMore ? undefined : p.level}
          role={p.level === 0 ? undefined : 'button'}
          tabIndex={-1}
          aria-label={isMore ? p.full : undefined}
          onPointerEnter={() => setHover(p.id)}
          onPointerLeave={() => setHover('')}
          onClick={activate}
          style={{ cursor: p.level === 0 ? 'default' : 'pointer' }}
        >
          <title>
            {isMore
              ? p.full
              : `${p.id}${p.node ? ` — ${p.node.fan_in} Importeure, ${p.node.loc} Zeilen, Hitze ${p.node.score.toFixed(1)}` : ''}`}
          </title>
          {/* A pointer target, not a dot. A level-2 glyph is 10px across and
              nobody hits a 10px circle; this invisible circle makes the hit
              area at least 36px while the drawing stays the size the data
              says it is. It cannot reach 44 without swallowing its neighbours
              — the ring relaxes to roughly 32px spacing — so the palette, the
              arrow keys and the ordered view stay the larger equivalent path,
              and tools/audit.mjs reports that exception out loud rather than
              excluding SVG from the count. */}
          {!isMore && !asCard && <circle cx={node.x} cy={node.y} r={Math.max(18, p.r + 10)} fill="transparent" />}
          <Glyph
            p={node}
            kind={glyph}
            radius={theme.form.radius}
            glow={theme.stage.glow}
            fog={ordered ? 0 : fog}
            selected={selected}
            dimmed={dimmed}
          />
          {/* On the axis, names hang BELOW it at 45 degrees, reading
              down-and-right, so they never cross the arcs above. The focus
              keeps a horizontal name: it is the caption of the figure, not one
              more entry on the axis. */}
          {isArcs && !isMore && p.level !== 0 ? (
            <text
              className="stage-label"
              x={node.x}
              y={node.y + 16}
              textAnchor="start"
              fontSize={labelSizeFor(p.level)}
              fontWeight={tierWeight(p.tier)}
              opacity={dimmed ? 0.4 : 1}
              transform={`rotate(45 ${node.x} ${node.y + 16})`}
            >
              {p.label}
            </text>
          ) : (
            <text
              className={p.level === 0 ? 'stage-label focus' : isMore ? 'stage-label more' : 'stage-label'}
              x={node.x + (centred ? 0 : p.anchor === 'end' ? -(p.r + 10) : p.r + 10)}
              y={labelY}
              textAnchor={centred || (isArcs && p.level === 0) ? 'middle' : p.anchor}
              fontSize={isMore ? 12 : labelSizeFor(p.level)}
              fontWeight={p.level === 0 ? undefined : tierWeight(p.tier)}
              opacity={dimmed ? 0.4 : 1}
            >
              {p.label}
            </text>
          )}
          {sub && (
            <text
              className="stage-sub"
              x={node.x}
              y={node.y + (p.level === 0 ? 15 : 12)}
              textAnchor="middle"
              fontSize={LABEL_PX.figure}
              opacity={dimmed ? 0.4 : 1}
            >
              {sub}
            </text>
          )}
        </g>
      );
    });

  return (
    /* `data-dof` gates the depth-of-field filter: `blur(0px)` still promotes
       every glyph to its own filter layer, so a theme that asked for no depth
       of field must not pay for one. */
    <div
      className="stage"
      data-mode={mode}
      data-dof={!ordered && dof > 0 ? 'on' : undefined}
      data-lift={lift > 0 ? 'on' : undefined}
    >
      <aside className="stage-rail">
        {header && <div className="stage-header">{header}</div>}
        <Legend stage={theme.stage} radius={theme.form.radius} hasFar={hasFar} ordered={ordered} />
        <Reading p={reading} focusLabel={focusLabel} source={readingSource} counts={counts} />
        <Tools
          mode={mode}
          onMode={(m) => {
            setMode(m);
            glide(HOME);
          }}
          zoom={view.k}
          onZoom={(f) => zoomAt(f, size.w / 2, size.h / 2, true)}
          onHome={() => glide(HOME)}
        />
      </aside>

      <div className="stage-field" ref={field}>
        <svg
          className="stage-svg"
          width={size.w}
          height={size.h}
          role="application"
          aria-label={`Nachbarschaft von ${neighbourhood.focus}, ${ordered ? 'geordnet in vier Spalten' : 'räumlich'}. Pfeiltasten wählen einen Nachbarn, Eingabetaste rückt ihn in die Mitte.`}
          tabIndex={0}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={onKeyDown}
        >
          <defs>
            <radialGradient id="stage-pearl" cx="35%" cy="30%">
              <stop offset="0%" stopColor="var(--node)" />
              <stop offset="70%" stopColor="var(--node)" stopOpacity="0.82" />
              <stop offset="100%" stopColor="var(--node2)" />
            </radialGradient>
            <radialGradient id="stage-halo">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.34 * theme.stage.glow} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
            </radialGradient>
            {/* The floor the scene stands on. Keyed to the theme's own glow, so
                the three themes that set it to zero get no wash at all and
                their depth comes from occlusion and weight instead. */}
            <radialGradient id="stage-floor">
              <stop offset="0%" stopColor="var(--surface)" stopOpacity={0.42 * theme.stage.glow} />
              <stop offset="60%" stopColor="var(--surface)" stopOpacity={0.16 * theme.stage.glow} />
              <stop offset="100%" stopColor="var(--surface)" stopOpacity="0" />
            </radialGradient>
            {/* The near planes cast onto the field; the far plane does not.
                A still cannot show parallax, so the depth a screenshot can
                carry is scale (the layout's) and elevation (this). */}
            {lift > 0 && (
              <filter id="stage-lift" x="-40%" y="-40%" width="180%" height="180%">
                <feDropShadow
                  dx="0"
                  dy={1 + lift * 1.4}
                  stdDeviation={1.2 + lift * 1.8}
                  floodColor="#000"
                  floodOpacity={0.07 + lift * 0.055}
                />
              </filter>
            )}
            <marker id="stage-arrow" markerUnits="userSpaceOnUse" markerWidth={9} markerHeight={7} refX={8.4} refY={3.5} orient="auto">
              <path d="M 0 0 L 9 3.5 L 0 7 z" fill="var(--edge)" />
            </marker>
            <marker id="stage-arrow-hot" markerUnits="userSpaceOnUse" markerWidth={9} markerHeight={7} refX={8.4} refY={3.5} orient="auto">
              <path d="M 0 0 L 9 3.5 L 0 7 z" fill="var(--edge-hot)" />
            </marker>
          </defs>

          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {theme.stage.glow > 0 && focusNode && !ordered && (
              <ellipse
                cx={focusNode.x}
                cy={focusNode.y}
                rx={Math.max(240, size.w * 0.44)}
                ry={Math.max(180, size.h * 0.42)}
                fill="url(#stage-floor)"
              />
            )}

            {isArcs && (
              <line
                x1={40}
                y1={layout.placed[0]?.y ?? size.h * 0.68}
                x2={size.w - 40}
                y2={layout.placed[0]?.y ?? size.h * 0.68}
                stroke="var(--line2)"
                strokeWidth={1}
              />
            )}

            {/* The column headers are drawn from the layout's own counts, so a
                header can never claim a number the column does not hold. */}
            {layout.columns?.map((c) => (
              <g key={c.label}>
                <text className="stage-column" x={c.x} y={c.y} textAnchor="middle" fontSize={LABEL_PX.figure}>
                  {c.label.toUpperCase()}
                </text>
                {/* The focus column holds exactly one card and always will;
                    printing "1" under it is a figure with no reader. */}
                {c.count > 1 && (
                  <text className="stage-column-count" x={c.x} y={c.y + 16} textAnchor="middle" fontSize={LABEL_PX.figure}>
                    {c.hidden > 0 ? `${c.count - c.hidden} von ${c.count}` : String(c.count)}
                  </text>
                )}
              </g>
            ))}

            <g className="stage-plane far">
              {renderEdges(2)}
              {renderNodes(2)}
            </g>
            <g className="stage-plane mid">
              {renderEdges(1)}
              {renderNodes(1)}
            </g>
            <g className="stage-plane near">{renderNodes(0)}</g>
          </g>
        </svg>

        {overlay && <div className="stage-overlay">{overlay}</div>}
        {panel && <div className="stage-panel">{panel}</div>}
      </div>
    </div>
  );
}
