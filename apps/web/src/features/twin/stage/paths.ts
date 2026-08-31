import type { Line, Placed } from '../layout';

/**
 * The geometry of a relation.
 *
 * Four routings, one per stage composition, and all four now do the same two
 * jobs the old ones did not: they say WHICH WAY the dependency runs, and they
 * stop short of the glyph they point at so the arrowhead is on the outside.
 *
 * Direction is the fact this drawing was missing. `source imports target` is
 * the whole content of an import graph, and fifteen identical hairlines threw
 * it away.
 */

/** How far short of the target glyph a line stops, so its head is visible. */
const HEAD_ROOM = 10;

export type Routing = 'elbow' | 'flow' | 'arc' | 'line';

function halfWidth(p: Placed): number {
  return (p.boxW ?? p.r * 2) / 2;
}

function halfHeight(p: Placed): number {
  return (p.boxH ?? p.r * 2) / 2;
}

/**
 * An elbow, the way a wiring diagram draws one.
 *
 * Straight centre-to-centre lines through a field of boxes cross every card on
 * the way and none of them says which way the dependency runs. An orthogonal
 * route leaves the source's SIDE, turns once, and arrives at the target's side.
 */
function elbow(from: Placed, to: Placed, lanes: EdgeLanes): string {
  const rightward = to.x >= from.x;
  const sx = from.x + (rightward ? halfWidth(from) : -halfWidth(from));
  const ex = to.x + (rightward ? -(halfWidth(to) + HEAD_ROOM) : halfWidth(to) + HEAD_ROOM);
  /**
   * Leave and arrive at a lane of the card's own edge, not always at its
   * middle. Twelve wires leaving one block from one point are coincident until
   * their corridors diverge, so the first 40px of every trace is the same 40px;
   * spread over the block's edge, each one is separable where the reader's eye
   * starts following it, and the arrowheads arriving at a block can be counted.
   */
  const sy = from.y + lanes.from * Math.max(0, halfHeight(from) - 7);
  const ey = to.y + lanes.to * Math.max(0, halfHeight(to) - 7);
  if (Math.abs(ey - sy) < 1.5) return `M ${sx} ${sy} L ${ex} ${ey}`;
  /**
   * Every elbow between the same two columns turned at the same midpoint, so
   * a dozen of them stacked into one black vertical bar and the picture read
   * as a wiring loom. Measured at 1440×900 on Leitstand: 35 vertical runs, and
   * the closest pair of runs that overlapped vertically was 0.3px apart — two
   * different imports sharing one pixel column. `lanes.corridor` is a rank
   * among the edges crossing THIS gutter, so the corridors divide the gutter
   * evenly instead of landing wherever a hash put them. Clamped here as well
   * as when it was chosen: parallax moves the two ends by different amounts,
   * and a corridor outside its own span would draw an elbow that doubles back.
   */
  const lo = Math.min(sx, ex) + 10;
  const hi = Math.max(sx, ex) - 10;
  const mx = hi <= lo ? (sx + ex) / 2 : Math.max(lo, Math.min(hi, (sx + ex) / 2 + lanes.corridor));
  const r = Math.min(10, Math.abs(ex - sx) / 3, Math.abs(ey - sy) / 2);
  const dirX = ex >= sx ? 1 : -1;
  const dirY = ey >= sy ? 1 : -1;
  return [
    `M ${sx} ${sy}`,
    `L ${mx - r * dirX} ${sy}`,
    `Q ${mx} ${sy} ${mx} ${sy + r * dirY}`,
    `L ${mx} ${ey - r * dirY}`,
    `Q ${mx} ${ey} ${mx + r * dirX} ${ey}`,
    `L ${ex} ${ey}`
  ].join(' ');
}

/**
 * A flow link between two columns: leaves one card's side, arrives at the
 * next one's, and bends only in the gutter. The ordered view is a reading
 * order, so its relations read left-to-right like the text around them.
 */
function flow(from: Placed, to: Placed, lanes: EdgeLanes): string {
  const rightward = to.x >= from.x;
  const sx = from.x + (rightward ? halfWidth(from) : -halfWidth(from));
  const ex = to.x + (rightward ? -(halfWidth(to) + HEAD_ROOM) : halfWidth(to) + HEAD_ROOM);
  /**
   * Fan the departures across the source card's edge.
   *
   * Twelve links leaving one card from one point stacked into a single dark
   * bundle, and a bundle says "many" without saying "how many". Spread over
   * the card's own height they read as a fan the reader can count.
   */
  const sy = from.y + lanes.from * Math.max(0, halfHeight(from) - 8);
  const ey = to.y + lanes.to * Math.max(0, halfHeight(to) - 8);
  const bend = Math.max(18, Math.abs(ex - sx) * 0.45);
  const s = rightward ? 1 : -1;
  return `M ${sx} ${sy} C ${sx + s * bend} ${sy} ${ex - s * bend} ${ey} ${ex} ${ey}`;
}

/**
 * A half-ellipse above the axis; height follows distance so long relations
 * arch higher and short ones stay readable. The tangent at both ends is
 * vertical, so the head comes down onto the target — which is exactly how a
 * printed arc figure reads.
 */
function arc(from: Placed, to: Placed): string {
  const dx = to.x - from.x;
  const rx = Math.abs(dx) / 2;
  const ry = Math.min(220, Math.max(24, Math.abs(dx) * 0.42));
  const sweep = dx > 0 ? 1 : 0;
  const endY = to.y - (halfHeight(to) + HEAD_ROOM * 0.6);
  return `M ${from.x} ${from.y} A ${rx} ${ry} 0 0 ${sweep} ${to.x} ${endY}`;
}

/**
 * A straight or bowed line between two glyphs, trimmed at BOTH ends so it
 * touches neither: a line that starts inside a disc and ends inside another
 * one is the reason the forest read as a spider.
 */
function line(from: Placed, to: Placed, curve: number): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const startPad = Math.min(from.r + 2, len * 0.4);
  const endPad = Math.min(to.r + HEAD_ROOM, len * 0.45);
  const sx = from.x + ux * startPad;
  const sy = from.y + uy * startPad;
  const ex = to.x - ux * endPad;
  const ey = to.y - uy * endPad;
  if (!curve) return `M ${sx} ${sy} L ${ex} ${ey}`;
  const mx = (sx + ex) / 2;
  const my = (sy + ey) / 2;
  const bow = Math.min(120, len * 0.18) * curve;
  return `M ${sx} ${sy} Q ${mx - uy * bow} ${my + ux * bow} ${ex} ${ey}`;
}

/**
 * Which lane each relation takes, decided over the WHOLE set at once.
 *
 * A per-edge hash cannot know that two edges are about to land in the same
 * pixel column; a rank among the edges that share a gutter can. Three ranks
 * per edge, each in −1…1:
 *
 *   corridor  how far the orthogonal turn is displaced from the natural
 *             midpoint, in stage units, so that no two vertical runs that
 *             overlap vertically end up in the same pixel column
 *   from      where it leaves the source card's edge, among that card's
 *             departures, −1…1
 *   to        where it arrives at the target card's edge, −1…1
 *
 * `corridor` is a DISPLACEMENT and not an absolute x on purpose: parallax
 * shifts a plane under the camera, and a corridor pinned to an absolute
 * coordinate would slide out from between the two cards it belongs to. Ranks
 * are taken from the unshifted layout coordinates for the same reason —
 * re-ranking mid-pan would make the wiring reshuffle under the reader's hand.
 */
export interface EdgeLanes {
  corridor: number;
  from: number;
  to: number;
}

const NO_LANES: EdgeLanes = { corridor: 0, from: 0, to: 0 };

/** How far apart two vertical runs must be before a reader can follow one. */
const CORRIDOR_SEP = 15;

export function edgeKey(l: Line): string {
  return `${l.from.id}>${l.to.id}`;
}

/** Even spread of n items across −1…1; a lone item sits on the centre line. */
function rank(i: number, n: number): number {
  return n < 2 ? 0 : (i / (n - 1)) * 2 - 1;
}

function assign(lines: Line[], keyOf: (l: Line) => string, sortBy: (l: Line) => number, write: (k: string, v: number) => void): void {
  const buckets = new Map<string, Line[]>();
  lines.forEach((l) => {
    const k = keyOf(l);
    const b = buckets.get(k);
    if (b) b.push(l);
    else buckets.set(k, [l]);
  });
  buckets.forEach((group) => {
    const sorted = [...group].sort((a, b) => sortBy(a) - sortBy(b) || edgeKey(a).localeCompare(edgeKey(b)));
    sorted.forEach((l, i) => write(edgeKey(l), rank(i, sorted.length)));
  });
}

export function edgeLanes(lines: Line[], routing: Routing): Map<string, EdgeLanes> {
  const out = new Map<string, EdgeLanes>();
  if (routing !== 'elbow' && routing !== 'flow') return out;
  const lane = (k: string): EdgeLanes => {
    const found = out.get(k);
    if (found) return found;
    const made = { corridor: 0, from: 0, to: 0 };
    out.set(k, made);
    return made;
  };
  if (routing === 'elbow') {
    /**
     * A channel router, because bucketing by column pair is not enough.
     *
     * Ranking within a gutter separates edges that share BOTH endpoints'
     * columns, and leaves untouched the case that actually produced the bus:
     * a long left-to-right run and a short neighbouring one whose midpoints
     * happen to coincide. So the corridors are laid out over the whole set at
     * once — each edge takes the free position nearest its natural midpoint,
     * where "free" means no already-placed corridor within CORRIDOR_SEP that
     * also overlaps it vertically. A corridor may never leave the gutter it
     * belongs to (an elbow that turns outside its own span doubles back), so
     * an edge with no room keeps its midpoint and the collision stays
     * visible rather than being hidden by a route that lies about the graph.
     */
    const taken: Array<{ x: number; y1: number; y2: number }> = [];
    const spans = lines
      .map((l) => {
        const rightward = l.to.x >= l.from.x;
        const sx = l.from.x + (rightward ? halfWidth(l.from) : -halfWidth(l.from));
        const ex = l.to.x + (rightward ? -(halfWidth(l.to) + HEAD_ROOM) : halfWidth(l.to) + HEAD_ROOM);
        return {
          key: edgeKey(l),
          mid: (sx + ex) / 2,
          lo: Math.min(sx, ex) + 12,
          hi: Math.max(sx, ex) - 12,
          y1: Math.min(l.from.y, l.to.y),
          y2: Math.max(l.from.y, l.to.y)
        };
      })
      .sort((a, b) => a.mid - b.mid || a.key.localeCompare(b.key));

    spans.forEach((s) => {
      if (s.hi <= s.lo) {
        lane(s.key).corridor = 0;
        return;
      }
      /**
       * How much room this position has, in px, to the nearest corridor that
       * shares vertical space with it. `Infinity` when nothing is in its way.
       */
      const room = (x: number) => {
        let d = Infinity;
        taken.forEach((t) => {
          if (Math.min(t.y2, s.y2) - Math.max(t.y1, s.y1) <= 10) return;
          d = Math.min(d, Math.abs(t.x - x));
        });
        return d;
      };
      /**
       * A narrow gutter cannot hold every corridor at full separation, and
       * that case is the common one below about 1100px. Falling back to the
       * natural midpoint made it WORSE than no router at all — every edge with
       * no free slot piled onto the same pixel column, measured at 0.2px
       * separation on a 1280px window. Taking the roomiest position instead
       * degrades: the corridors thin out evenly rather than collapsing into
       * one bar.
       */
      let put = Math.max(s.lo, Math.min(s.hi, s.mid));
      let best = room(put);
      if (best < CORRIDOR_SEP) {
        const steps = Math.max(8, Math.min(48, Math.round((s.hi - s.lo) / 4)));
        for (let k = 0; k <= steps; k += 1) {
          const x = s.lo + ((s.hi - s.lo) * k) / steps;
          const r = room(x);
          // Nearest to the natural midpoint wins a tie, so a corridor never
          // wanders further from its own gutter than it has to.
          if (r > best + 0.001 || (r >= best - 0.001 && Math.abs(x - s.mid) < Math.abs(put - s.mid))) {
            best = r;
            put = x;
          }
          if (best >= CORRIDOR_SEP && Math.abs(put - s.mid) <= CORRIDOR_SEP) break;
        }
      }
      taken.push({ x: put, y1: s.y1, y2: s.y2 });
      lane(s.key).corridor = put - s.mid;
    });
  }
  // A flow link needs no corridor: its curve diverges from its neighbours from
  // the first pixel, which is the whole reason the ordered view uses one.
  assign(
    lines,
    (l) => l.from.id,
    (l) => l.to.y,
    (k, v) => {
      lane(k).from = v;
    }
  );
  assign(
    lines,
    (l) => l.to.id,
    (l) => l.from.y,
    (k, v) => {
      lane(k).to = v;
    }
  );
  return out;
}

export function routeEdge(l: Line, routing: Routing, curve: number, at: (p: Placed) => Placed, lanes?: EdgeLanes): string {
  const from = at(l.from);
  const to = at(l.to);
  if (routing === 'elbow') return elbow(from, to, lanes ?? NO_LANES);
  if (routing === 'flow') return flow(from, to, lanes ?? NO_LANES);
  if (routing === 'arc') return arc(from, to);
  return line(from, to, curve);
}
