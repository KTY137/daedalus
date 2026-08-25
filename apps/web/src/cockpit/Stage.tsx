import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ThemeSpec } from '../theme/types';
import type { Neighbourhood } from './graph';
import { DEFAULT_BUDGET, MORE_ID, labelSizeFor, layoutFor, type Box, type Line, type Placed } from './layout';

/**
 * The stage: one module and what actually reaches it, drawn as SVG.
 *
 * Design rules this component is built to keep, all of them earned from
 * previous review rounds:
 *
 *  - it is operable. Wheel zooms at the cursor, drag pans, the keyboard moves
 *    the selection between real neighbours, and clicking a node re-centres on
 *    it. Nothing here is a picture of an interaction.
 *  - the backbone is the resting state. With `backboneOnly` the second level's
 *    edges appear on hover/selection, so at rest the reader sees structure
 *    rather than a hairball.
 *  - labels are never below 11px and never sit on top of a glyph.
 *  - what is not drawn is said out loud, by the caller, from the counts this
 *    component returns via `onBudget`.
 */

export interface StageProps {
  neighbourhood: Neighbourhood;
  theme: ThemeSpec;
  onFocus: (module: string) => void;
  /** rendered inside the stage frame, top-left — the caller owns the copy */
  header?: React.ReactNode;
  /** rendered over the stage, top-right (the decision card in 'float' themes) */
  overlay?: React.ReactNode;
  /** rendered over the stage, bottom-left (the chat card in 'card' themes) */
  panel?: React.ReactNode;
  onBudget?: (hidden1: number, hidden2: number, hiddenIds: string[]) => void;
  /** the reader pressed the aggregate glyph: show them what it stands for */
  onShowHidden?: (ids: string[]) => void;
}

const MIN_ZOOM = 0.45;
const MAX_ZOOM = 3.2;

/** Separator for the hidden-neighbour dependency key. Module paths never
 *  contain a unit separator, so two different sets cannot share a key. */
const SEP = String.fromCharCode(31);

interface View {
  x: number;
  y: number;
  k: number;
}

function edgePath(line: Line, curve: number, arcs: boolean): string {
  const { from, to } = line;
  if (arcs) {
    // A half-ellipse above the axis; height follows distance so long
    // relations arch higher and short ones stay readable.
    const dx = to.x - from.x;
    const rx = Math.abs(dx) / 2;
    const ry = Math.min(220, Math.max(24, Math.abs(dx) * 0.42));
    const sweep = dx > 0 ? 1 : 0;
    return `M ${from.x} ${from.y} A ${rx} ${ry} 0 0 ${sweep} ${to.x} ${to.y}`;
  }
  if (!curve) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2;
  const nx = -(to.y - from.y);
  const ny = to.x - from.x;
  const len = Math.hypot(nx, ny) || 1;
  const bow = Math.min(120, len * 0.18) * curve;
  return `M ${from.x} ${from.y} Q ${mx + (nx / len) * bow} ${my + (ny / len) * bow} ${to.x} ${to.y}`;
}

/** Width of a card glyph, kept in step with layout.ts's cardWidth(). */
function cardWidth(p: Placed): number {
  return Math.max(96, p.label.length * 7.4 + 30);
}

function Glyph({ p, kind, selected, dimmed }: { p: Placed; kind: ThemeSpec['stage']['glyph']; selected: boolean; dimmed: boolean }) {
  const fill = p.level === 2 ? 'var(--node2)' : 'var(--node)';
  const opacity = dimmed ? 0.32 : 1;

  // The aggregate glyph is deliberately not a node: it is a pill that says how
  // many neighbours it stands for, in every theme, so it can never be mistaken
  // for one module with a strange name.
  if (p.kind === 'more') {
    const w = p.label.length * 7.6 + 26;
    return (
      <g opacity={opacity}>
        <rect
          x={p.x - w / 2}
          y={p.y - 15}
          width={w}
          height={30}
          rx={15}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={1.2}
          strokeDasharray="4 3"
        />
      </g>
    );
  }

  if (kind === 'card') {
    const w = cardWidth(p);
    const h = p.level === 0 ? 46 : 34;
    return (
      <g opacity={opacity}>
        <rect
          x={p.x - w / 2}
          y={p.y - h / 2}
          width={w}
          height={h}
          rx={4}
          fill={p.level === 0 ? 'var(--surface)' : 'var(--node)'}
          stroke={selected || p.level === 0 ? 'var(--accent)' : 'var(--line)'}
          strokeWidth={selected || p.level === 0 ? 2 : 1}
        />
      </g>
    );
  }

  if (kind === 'star') {
    // A star chart whose stars are two pixels across is a dark rectangle. The
    // floor is what keeps a level-2 node visible at 100%.
    const r = Math.max(p.level === 2 ? 5 : 8, p.r);
    const spikes = `M ${p.x - r * 1.5} ${p.y} L ${p.x + r * 1.5} ${p.y} M ${p.x} ${p.y - r * 1.5} L ${p.x} ${p.y + r * 1.5}`;
    return (
      <g opacity={opacity}>
        {p.level === 0 && <path d={spikes} stroke="var(--accent)" strokeWidth={1} opacity={0.7} />}
        <circle cx={p.x} cy={p.y} r={r * 0.42} fill={p.level === 0 ? 'var(--accent)' : fill} />
        {p.level !== 2 && <circle cx={p.x} cy={p.y} r={r * 0.9} fill="none" stroke={fill} strokeWidth={0.6} opacity={0.4} />}
      </g>
    );
  }

  if (kind === 'pearl') {
    return (
      <g opacity={opacity}>
        {p.level === 0 && <circle cx={p.x} cy={p.y} r={p.r * 2.6} fill="url(#stage-halo)" />}
        <circle cx={p.x} cy={p.y} r={p.r} fill={p.level === 2 ? 'var(--node2)' : 'url(#stage-pearl)'} />
        {(selected || p.level === 0) && (
          <circle cx={p.x} cy={p.y} r={p.r + 7} fill="none" stroke="var(--accent)" strokeWidth={1.4} opacity={0.85} />
        )}
      </g>
    );
  }

  return (
    <g opacity={opacity}>
      <circle cx={p.x} cy={p.y} r={p.r} fill={p.level === 0 ? 'var(--accent)' : fill} />
      {selected && p.level !== 0 && <circle cx={p.x} cy={p.y} r={p.r + 5} fill="none" stroke="var(--accent)" strokeWidth={1.5} />}
    </g>
  );
}

export function Stage({ neighbourhood, theme, onFocus, header, overlay, panel, onBudget, onShowHidden }: StageProps) {
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 1200, h: 720 });
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const [hover, setHover] = useState<string>('');
  const [cursor, setCursor] = useState<string>('');
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const isArcs = theme.stage.layout === 'arcs';

  /**
   * The regions the interface covers, as constants rather than measurements.
   *
   * Measuring the real boxes would be more exact and would also form a loop:
   * the header's height depends on how many neighbours the layout hid, which
   * depends on the header's height. These match the CSS (`.stage-header`,
   * `.stage-overlay`, `.stage-panel`) with room to spare, and erring generous
   * costs a little space while erring exact costs readability.
   */
  // Presence, not identity: `header`/`overlay`/`panel` are fresh React elements
  // on every render of the caller, so depending on them would rebuild the
  // layout every frame and feed the budget effect back into itself.
  const hasHeader = Boolean(header);
  const hasOverlay = Boolean(overlay);
  const hasPanel = Boolean(panel);

  const avoid = useMemo<Box[]>(() => {
    if (size.w < 900) return [];
    const boxes: Box[] = [];
    if (hasHeader) boxes.push({ x1: 0, y1: 0, x2: 430, y2: 240 });
    if (hasOverlay) boxes.push({ x1: size.w - 400, y1: 0, x2: size.w, y2: 250 });
    if (hasPanel) boxes.push({ x1: 0, y1: size.h - 340, x2: 480, y2: size.h });
    // the zoom controls, bottom right
    boxes.push({ x1: size.w - 210, y1: size.h - 70, x2: size.w, y2: size.h });
    return boxes;
  }, [hasHeader, hasOverlay, hasPanel, size.w, size.h]);

  const layout = useMemo(
    () =>
      layoutFor(theme.stage.layout, neighbourhood, {
        width: size.w,
        height: size.h,
        sizeByFanIn: theme.stage.sizeByFanIn,
        avoid,
        ...DEFAULT_BUDGET
      }),
    [avoid, neighbourhood, size.w, size.h, theme.stage.layout, theme.stage.sizeByFanIn]
  );

  // `hiddenIds` is a new array on every layout; keying the effect on its
  // CONTENT is what stops "report the budget" from re-rendering its own input.
  const hiddenKey = layout.hiddenIds.join(SEP);
  useEffect(() => {
    onBudget?.(layout.hidden1, layout.hidden2, hiddenKey ? hiddenKey.split(SEP) : []);
  }, [layout.hidden1, layout.hidden2, hiddenKey, onBudget]);

  // A new focus is a new picture: reset the camera so the reader is never left
  // looking at empty space where the old neighbourhood used to be.
  useEffect(() => {
    setView({ x: 0, y: 0, k: 1 });
    setCursor('');
  }, [neighbourhood.focus]);

  const active = hover || cursor;

  const litIds = useMemo(() => {
    if (!active) return null;
    const set = new Set<string>([active]);
    layout.lines.forEach((l) => {
      if (l.from.id === active) set.add(l.to.id);
      if (l.to.id === active) set.add(l.from.id);
    });
    return set;
  }, [active, layout.lines]);

  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    setView((v) => {
      const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * factor));
      if (k === v.k) return v;
      // keep the point under the cursor fixed
      const scale = k / v.k;
      return { k, x: px - (px - v.x) * scale, y: py - (py - v.y) * scale };
    });
  }, []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const rect = frame.current?.getBoundingClientRect();
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
    setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) }));
  };
  const endDrag = () => {
    drag.current = null;
  };

  /** Arrow keys walk the real neighbour ring; Enter re-centres on the cursor. */
  const onKeyDown = (e: React.KeyboardEvent) => {
    const ring = layout.placed.filter((p) => p.level !== 0);
    if (!ring.length) return;
    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomAt(1.15, size.w / 2, size.h / 2);
      return;
    }
    if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      zoomAt(1 / 1.15, size.w / 2, size.h / 2);
      return;
    }
    if (e.key === '0') {
      e.preventDefault();
      setView({ x: 0, y: 0, k: 1 });
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
    const dir = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const at = ring.findIndex((p) => p.id === cursor);
    const next = ring[(at + dir + ring.length) % ring.length];
    setCursor(next.id);
  };

  const showEdge = (l: Line) => {
    if (!theme.stage.backboneOnly) return true;
    if (l.backbone) return true;
    return Boolean(litIds && (litIds.has(l.from.id) || litIds.has(l.to.id)));
  };

  const labelSize = (p: Placed) => labelSizeFor(p.level);

  return (
    <div className="stage" ref={frame}>
      <svg
        className="stage-svg"
        width={size.w}
        height={size.h}
        role="application"
        aria-label={`Nachbarschaft von ${neighbourhood.focus}. Pfeiltasten wählen einen Nachbarn, Eingabetaste rückt ihn in die Mitte.`}
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
        </defs>

        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
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

          <g className="stage-edges">
            {layout.lines.map((l, i) => {
              if (!showEdge(l)) return null;
              const lit = Boolean(litIds && litIds.has(l.from.id) && litIds.has(l.to.id));
              const touchesFocus = l.from.level === 0 || l.to.level === 0;
              return (
                <path
                  key={`${l.from.id}->${l.to.id}-${i}`}
                  d={edgePath(l, theme.stage.curve, isArcs)}
                  fill="none"
                  stroke={lit ? 'var(--edge-hot)' : 'var(--edge)'}
                  strokeWidth={lit ? 1.8 : touchesFocus ? 1.2 : 0.8}
                  opacity={lit ? 1 : touchesFocus ? 0.85 : 0.4}
                />
              );
            })}
          </g>

          <g className="stage-nodes">
            {layout.placed.map((p) => {
              const dimmed = Boolean(litIds && !litIds.has(p.id));
              const selected = p.id === active;
              const isMore = p.kind === 'more';
              const asCard = theme.stage.glyph === 'card' && !isMore;
              const centred = asCard || isMore || p.anchor === 'middle';
              /**
               * A centred label belongs INSIDE a card and BELOW anything else.
               * The card layout centres every label because that is where a
               * card wants it; pairing that layout with the pearl glyph — which
               * the Studio lets you do — then printed the name across the
               * sphere. The glyph decides, not the layout.
               */
              const labelY = isMore
                ? p.y + 4
                : isArcs && p.level === 0
                  ? p.y - (p.r + 32)
                  : asCard
                    ? p.y + p.labelDy
                    : p.anchor === 'middle'
                      ? p.y + p.r + 16
                      : p.y + p.labelDy;
              const activate = () => {
                if (isMore) onShowHidden?.(layout.hiddenIds);
                else if (p.level !== 0) onFocus(p.id);
              };
              return (
                <g
                  key={p.id}
                  className="stage-node"
                  role={p.level === 0 ? undefined : 'button'}
                  tabIndex={-1}
                  aria-label={isMore ? p.full : undefined}
                  onPointerEnter={() => setHover(p.id)}
                  onPointerLeave={() => setHover('')}
                  onClick={activate}
                  style={{ cursor: p.level === 0 ? 'default' : 'pointer' }}
                >
                  <title>
                    {isMore ? p.full : `${p.id}${p.node ? ` — ${p.node.fan_in} Importeure, ${p.node.loc} Zeilen` : ''}`}
                  </title>
                  {/* A pointer target, not a dot. A level-2 glyph is 10px
                      across and nobody hits a 10px circle; this invisible
                      circle makes the hit area at least 36px while the
                      drawing stays the size the data says it is. It cannot
                      reach 44 without swallowing its neighbours — the ring
                      relaxes to roughly 32px spacing — so the palette and the
                      arrow keys stay the larger equivalent path, and
                      tools/audit.mjs reports that exception out loud rather
                      than excluding SVG from the count. */}
                  {!isMore && (
                    <circle cx={p.x} cy={p.y} r={Math.max(18, p.r + 10)} fill="transparent" />
                  )}
                  <Glyph p={p} kind={theme.stage.glyph} selected={selected} dimmed={dimmed} />
                  {/* On the axis, names hang BELOW it at 45 degrees, reading
                      down-and-right, so they never cross the arcs above. The
                      focus keeps a horizontal name: it is the caption of the
                      figure, not one more entry on the axis. */}
                  {isArcs && !isMore && p.level !== 0 ? (
                    <text
                      className="stage-label"
                      x={p.x}
                      y={p.y + 16}
                      textAnchor="start"
                      fontSize={labelSize(p)}
                      opacity={dimmed ? 0.4 : 1}
                      transform={`rotate(45 ${p.x} ${p.y + 16})`}
                    >
                      {p.label}
                    </text>
                  ) : (
                    <text
                      className={p.level === 0 ? 'stage-label focus' : isMore ? 'stage-label more' : 'stage-label'}
                      x={p.x + (centred ? 0 : p.anchor === 'end' ? -(p.r + 10) : p.r + 10)}
                      y={labelY}
                      textAnchor={centred || (isArcs && p.level === 0) ? 'middle' : p.anchor}
                      fontSize={isMore ? 12 : labelSize(p)}
                      opacity={dimmed ? 0.4 : 1}
                    >
                      {p.label}
                    </text>
                  )}
                  {asCard && p.node && (
                    <text className="stage-sub" x={p.x} y={p.y + 14} textAnchor="middle" fontSize={11} opacity={dimmed ? 0.4 : 0.9}>
                      {p.node.fan_in} Importeure
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </g>
      </svg>

      {header && <div className="stage-header">{header}</div>}
      {overlay && <div className="stage-overlay">{overlay}</div>}
      {panel && <div className="stage-panel">{panel}</div>}

      <div className="stage-tools" role="group" aria-label="Ansicht">
        <button type="button" onClick={() => zoomAt(1.2, size.w / 2, size.h / 2)} aria-label="Näher">+</button>
        <button type="button" onClick={() => zoomAt(1 / 1.2, size.w / 2, size.h / 2)} aria-label="Weiter weg">−</button>
        <button type="button" onClick={() => setView({ x: 0, y: 0, k: 1 })} aria-label="Ansicht zurücksetzen">⟳</button>
        <span className="stage-zoom">{Math.round(view.k * 100)}%</span>
      </div>
    </div>
  );
}
