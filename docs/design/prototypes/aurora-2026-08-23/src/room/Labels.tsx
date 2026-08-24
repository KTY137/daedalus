/* The names in the room.
 *
 * The hard rule of this round: no text ever lies across a body. So placement
 * is a search, not an offset. Each name is tried at a ring of candidate
 * positions around its anchor, and a candidate is accepted only if its box
 * misses every projected sphere silhouette, every glass panel, and every name
 * already placed. A name that cannot find a clear position is dropped rather
 * than laid over the object.
 *
 * At rest that is four plane names standing in the gaps of the constellation.
 * The node under the pointer gets exactly one callout, parked at the edge of
 * the object with a hairline leading back to it — the leader line is what lets
 * the name sit clear of the body and still belong to it. Everything else stays
 * unnamed until it is asked for. */

import { useEffect, useRef } from 'react';
import { bus } from './bus';
import { ACCENT, SELECT, TINT } from './materials';
import { PLANE_LABEL, type Fixture, type Plane, type ViewMode } from '../data';
import { PLANE_ORDER } from './layout';

const isIdentifier = (s: string) => /[/._§]/.test(s) || /\(\)$/.test(s);

const SANS = '450 12px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif';
const MONO = '400 11.5px Consolas,"Cascadia Mono",ui-monospace,monospace';
const PLANE_FONT = '500 10.5px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif';

let ctx: CanvasRenderingContext2D | null = null;
const widthCache = new Map<string, number>();
function measure(text: string, font: string) {
  const key = font[0] + font[2] + text;
  const hit = widthCache.get(key);
  if (hit !== undefined) return hit;
  if (!ctx) ctx = document.createElement('canvas').getContext('2d');
  ctx!.font = font;
  // the tracking the stylesheet adds is not in measureText
  const w = ctx!.measureText(text).width + (font === PLANE_FONT ? text.length * 1.5 : 0);
  widthCache.set(key, w);
  return w;
}

export interface LabelsProps {
  fx: Fixture;
  view: ViewMode;
  lit: string[];
  selected: string | null;
  hovered: string | null;
  deg: Record<string, number>;
}

interface Box { x: number; y: number; w: number; h: number }

const hitsBox = (a: Box, b: Box) =>
  !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);

/** a box against a circle: the closest point of the box to the centre */
const hitsCircle = (b: Box, c: { x: number; y: number; r: number }) => {
  const cx = Math.max(b.x, Math.min(c.x, b.x + b.w));
  const cy = Math.max(b.y, Math.min(c.y, b.y + b.h));
  return Math.hypot(c.x - cx, c.y - cy) < c.r;
};

type Want = {
  text: string; font: string; tone: string; cls: string;
  ax: number; ay: number; ring: number; angle?: number;
  leaderTo?: { x: number; y: number };
};

export default function Labels(props: LabelsProps) {
  const { fx } = props;
  const host = useRef<HTMLDivElement>(null);
  const leader = useRef<SVGLineElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const p = useRef(props);
  p.current = props;

  useEffect(() => {
    const root = host.current!;
    const slots = Array.from(root.querySelectorAll('span')) as HTMLSpanElement[];

    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      if (!bus.frame) return;
      const s = p.current;
      const W = window.innerWidth, H = window.innerHeight;

      /* every obstacle, before a single name is placed */
      const circles = [...bus.spheres.values()];
      const blocked: Box[] = [];
      for (const sel of ['.panel', '.orn', '.topbar', '.statusbar']) {
        for (const el of Array.from(document.querySelectorAll(sel))) {
          const b = el.getBoundingClientRect();
          if (b.width > 2 && b.height > 2) blocked.push({ x: b.left - 6, y: b.top - 6, w: b.width + 12, h: b.height + 12 });
        }
      }
      const placed: Box[] = [];
      const wanted: Want[] = [];

      if (s.view === 'ordered') {
        const ranked = [...fx.graph.nodes].sort((a, b) =>
          (bus.pts.get(a.id)?.y ?? 0) - (bus.pts.get(b.id)?.y ?? 0));
        let group: string | null = null;
        for (const n of ranked) {
          const pt = bus.pts.get(n.id);
          if (!pt) continue;
          if (n.plane !== group) {
            group = n.plane;
            wanted.push({
              text: PLANE_LABEL[n.plane].toUpperCase(),
              font: PLANE_FONT, tone: TINT[n.plane], cls: 'lb lb-plane',
              ax: pt.x - 14, ay: pt.y - 20, ring: 0,
            });
          }
          wanted.push({
            text: n.label,
            font: isIdentifier(n.label) ? MONO : SANS,
            tone: s.lit.includes(n.id) ? ACCENT : s.selected === n.id ? SELECT : '#CFC6B8',
            cls: isIdentifier(n.label) ? 'lb lb-mono' : 'lb',
            ax: pt.x + pt.r + 12, ay: pt.y, ring: 0,
          });
        }
      } else {
        const cx = circles.reduce((a, c) => a + c.x, 0) / Math.max(1, circles.length);
        const cy = circles.reduce((a, c) => a + c.y, 0) / Math.max(1, circles.length);
        for (const pl of PLANE_ORDER) {
          const c = bus.spheres.get(pl);
          if (!c) continue;
          wanted.push({
            text: PLANE_LABEL[pl as Plane].toUpperCase(),
            font: PLANE_FONT, tone: TINT[pl as Plane], cls: 'lb lb-plane',
            ax: c.x, ay: c.y, ring: c.r,
            angle: Math.atan2(c.y - cy, c.x - cx),
          });
        }
        const one = s.hovered ?? s.selected;
        if (one) {
          const pt = bus.pts.get(one);
          const n = fx.graph.nodes.find(x => x.id === one);
          if (pt && n) {
            wanted.unshift({
              text: n.label,
              font: isIdentifier(n.label) ? MONO : SANS,
              tone: s.selected === one ? SELECT : '#F2EADC',
              cls: 'lb lb-call' + (isIdentifier(n.label) ? ' lb-mono' : ''),
              ax: pt.x, ay: pt.y, ring: Math.max(pt.r, 10),
              leaderTo: { x: pt.x, y: pt.y },
            });
          }
        }
      }

      let used = 0;
      let leaderDrawn = false;
      for (const w of wanted) {
        if (used >= slots.length) break;
        const tw = measure(w.text, w.font);
        const th = s.view === 'ordered' ? 14 : 16;
        let box: Box | null = null;
        const free = (b: Box) =>
          !placed.some(q => hitsBox(b, q)) && !circles.some(c => hitsCircle(b, c))
          && !blocked.some(q => hitsBox(b, q))
          && b.x >= 8 && b.x + b.w <= W - 8 && b.y >= 8 && b.y + b.h <= H - 8;

        if (w.ring === 0) {
          const b: Box = { x: w.ax - 4, y: w.ay - th / 2 - 2, w: tw + 8, h: th + 4 };
          if (free(b)) box = b;
        } else {
          const base = w.angle;
          const angles: number[] = [];
          const seed = base !== undefined ? base : -Math.PI / 2;
          for (let k = 0; k < 16; k++) angles.push(seed + (k % 2 ? -1 : 1) * Math.ceil(k / 2) * 0.40);
          outer:
          for (const rad of [w.ring + 24, w.ring + 44, w.ring + 68, w.ring + 98, w.ring + 132]) {
            for (const a of angles) {
              const px = w.ax + Math.cos(a) * rad;
              const py = w.ay + Math.sin(a) * rad;
              const b: Box = {
                x: Math.cos(a) < 0 ? px - tw - 6 : px - 2,
                y: py - th / 2 - 2, w: tw + 8, h: th + 4,
              };
              if (free(b)) { box = b; break outer; }
            }
          }
        }
        if (!box) continue;

        placed.push(box);
        const el = slots[used++];
        el.textContent = w.text;
        el.className = w.cls;
        el.style.display = 'block';
        el.style.transform = `translate3d(${Math.round(box.x + 4)}px,${Math.round(box.y + 2)}px,0)`;
        el.style.color = w.tone;

        if (w.leaderTo && leader.current && !leaderDrawn) {
          const nearX = Math.max(box.x, Math.min(w.leaderTo.x, box.x + box.w));
          const nearY = Math.max(box.y, Math.min(w.leaderTo.y, box.y + box.h));
          leader.current.setAttribute('x1', String(Math.round(w.leaderTo.x)));
          leader.current.setAttribute('y1', String(Math.round(w.leaderTo.y)));
          leader.current.setAttribute('x2', String(Math.round(nearX)));
          leader.current.setAttribute('y2', String(Math.round(nearY)));
          if (svg.current) svg.current.style.display = 'block';
          leaderDrawn = true;
        }
      }
      if (!leaderDrawn && svg.current) svg.current.style.display = 'none';
      for (let i = used; i < slots.length; i++) slots[i].style.display = 'none';
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [fx]);

  return (
    <div className="labels" ref={host} aria-hidden="true">
      <svg className="leader" ref={svg} style={{ display: 'none' }}>
        <line ref={leader} x1="0" y1="0" x2="0" y2="0" />
      </svg>
      {Array.from({ length: 36 }, (_, i) => (
        <span className="lb" key={i} style={{ display: 'none' }} />
      ))}
    </div>
  );
}
