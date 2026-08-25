import type { StructureGraphNode } from '../types';
import { shortLabel, type Neighbour, type Neighbourhood } from './graph';

/**
 * Where things go on the stage.
 *
 * Three position algorithms, chosen by the active theme: a radial forest (also
 * used by the star chart), columns of labelled cards, and a one-axis arc
 * figure. They all produce the same `Placed`/`Line` shape, so the renderer
 * draws glyphs and never re-derives geometry.
 *
 * Two rules the first version got wrong and this one is built around:
 *
 *  - A module with 161 importers has no readable ring. Past the budget the
 *    remainder becomes ONE glyph that says how many it stands for and opens
 *    the full list — not 64 overlapping labels, and not a silent truncation.
 *  - Positions are resolved against LABEL boxes, not glyph circles. The label
 *    is the part a reader actually reads, and `repository_write_artifact_
 *    admission.py` is twenty times wider than the dot it belongs to.
 */

export interface Placed {
  id: string;
  x: number;
  y: number;
  /** glyph radius in stage units */
  r: number;
  level: 0 | 1 | 2;
  /** 'more' is the aggregate glyph standing for everything past the budget */
  kind: 'node' | 'more';
  /** how many neighbours the aggregate stands for */
  moreCount?: number;
  label: string;
  /** the untruncated name, for the tooltip */
  full: string;
  anchor: 'start' | 'middle' | 'end';
  labelDy: number;
  /**
   * Set by the card layout: the glyph IS a box of this size, so collision
   * resolution has to use it. Without this, two 34px-tall cards whose 16px
   * label boxes miss each other are reported as not overlapping — which is
   * exactly how the card themes ended up with a pile in the corner.
   */
  boxW?: number;
  boxH?: number;
  node?: StructureGraphNode;
  via?: 'in' | 'out' | 'mixed';
}

export interface Line {
  from: Placed;
  to: Placed;
  backbone: boolean;
  /** the direction as data: the source imports the target */
  via: 'in' | 'out';
}

export interface StageLayout {
  placed: Placed[];
  byId: Map<string, Placed>;
  lines: Line[];
  width: number;
  height: number;
  /** direct neighbours the aggregate glyph stands for */
  hidden1: number;
  /** second-level neighbours not drawn */
  hidden2: number;
  /** every neighbour the budget dropped, so the caller can list them */
  hiddenIds: string[];
}

/** A rectangle the layout must keep clear, in stage coordinates. */
export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface LayoutOptions {
  width: number;
  height: number;
  sizeByFanIn: number;
  maxLevel1: number;
  maxLevel2: number;
  /**
   * Regions the stage draws UI over — the header, the decision card, the chat
   * card. Without these the layout happily puts `storage.py` underneath the
   * sentence explaining what is not drawn, which is the specific way the first
   * version of this stage was unreadable.
   */
  avoid?: Box[];
}

export const DEFAULT_BUDGET = { maxLevel1: 18, maxLevel2: 20 };

/** id of the aggregate glyph; not a module, and never focusable as one */
export const MORE_ID = '::more::';

const MAX_LABEL = 26;
/** average glyph advance for the mono stack, as a fraction of font size */
const CHAR_W = 0.58;

/**
 * Shorten from the MIDDLE, never from the end.
 *
 * `provider_target_receipt_retention_admission.py` and
 * `provider_target_receipt_retention_completed_evidence.py` both end up as
 * `provider_target_receipt_r…` when the tail is cut — two different modules
 * wearing one label, which is worse than a long name. Keeping the head and the
 * tail keeps them distinguishable.
 */
function trimTo(label: string, max: number): string {
  if (label.length <= max) return label;
  const head = Math.ceil((max - 1) * 0.55);
  const tail = max - 1 - head;
  return `${label.slice(0, head)}…${label.slice(label.length - tail)}`;
}

function trim(label: string): string {
  return trimTo(label, MAX_LABEL);
}

/**
 * Label sizes, and they live here because the LAYOUT resolves collisions
 * against label boxes. If these and the renderer's sizes drift apart, the
 * layout separates boxes that are not the boxes being drawn — so both read
 * this one table.
 */
export const LABEL_PX = { focus: 19, near: 14.5, far: 12.5 } as const;

export function labelSizeFor(level: 0 | 1 | 2): number {
  return level === 0 ? LABEL_PX.focus : level === 1 ? LABEL_PX.near : LABEL_PX.far;
}

function radiusFor(n: Neighbour | undefined, level: 0 | 1 | 2, sizeByFanIn: number): number {
  const basis = level === 0 ? 22 : level === 1 ? 12 : 7;
  const fan = n?.node?.fan_in ?? 0;
  const growth = Math.log2(1 + Math.max(0, fan)) * (level === 0 ? 2.4 : level === 1 ? 2 : 1);
  return basis + growth * sizeByFanIn;
}

/**
 * Names that are unique ON THIS STAGE.
 *
 * Two different modules can share a file name — this repository has several
 * `provider_target_receipt_retention*.py` — and drawing both as the same
 * truncated label is worse than a collision: it is two nodes claiming to be
 * the same file. Where a short name repeats, its parent directory joins it.
 */
function labeller(ids: string[]): (id: string) => string {
  const unique = [...new Set(ids)];

  // 1. the file name, with its parent directory where the file name repeats
  const shortCounts = new Map<string, number>();
  unique.forEach((id) => {
    const short = shortLabel(id);
    shortCounts.set(short, (shortCounts.get(short) ?? 0) + 1);
  });
  const base = new Map<string, string>();
  unique.forEach((id) => {
    const short = shortLabel(id);
    if ((shortCounts.get(short) ?? 0) < 2) {
      base.set(id, short);
      return;
    }
    const parts = id.split(/[\/]/);
    base.set(id, parts.length > 1 ? `${parts[parts.length - 2]}/${short}` : short);
  });

  /**
   * 2. shorten, and CHECK THE RESULT.
   *
   * Truncation can manufacture the collision it was meant to avoid:
   * `provider_target_receipt_retention_completed_evidence.py` and
   * `provider_target_receipt_retention_effect_terminal_evidence.py` shorten to
   * the same string at any sane width, and two nodes then claim to be the same
   * file. Where that happens the budget is widened for exactly those names
   * until they differ, or until they are drawn whole.
   */
  const out = new Map<string, string>();
  const byLabel = new Map<string, string[]>();
  unique.forEach((id) => {
    const label = trim(base.get(id)!);
    out.set(id, label);
    byLabel.set(label, [...(byLabel.get(label) ?? []), id]);
  });

  byLabel.forEach((owners) => {
    if (owners.length < 2) return;
    for (let width = MAX_LABEL + 6; width <= 64; width += 6) {
      const widened = new Map(owners.map((id) => [id, trimTo(base.get(id)!, width)] as const));
      if (new Set(widened.values()).size === owners.length) {
        widened.forEach((label, id) => out.set(id, label));
        return;
      }
    }
    owners.forEach((id) => out.set(id, base.get(id)!));
  });

  return (id: string) => out.get(id) ?? shortLabel(id);
}

function place(
  id: string,
  x: number,
  y: number,
  level: 0 | 1 | 2,
  n: Neighbour | undefined,
  sizeByFanIn: number,
  centreX: number,
  name: (id: string) => string = shortLabel
): Placed {
  const r = radiusFor(n, level, sizeByFanIn);
  const full = name(id);
  const anchor: Placed['anchor'] = level === 0 ? 'middle' : x < centreX - 12 ? 'end' : 'start';
  return {
    id,
    x,
    y,
    r,
    level,
    kind: 'node',
    label: full,
    full,
    anchor,
    labelDy: level === 0 ? r + 24 : 4,
    node: n?.node,
    via: n?.via
  };
}

/** The pixel box a placed node's label occupies, at the size the stage draws it. */
function labelBox(p: Placed): { x1: number; x2: number; y1: number; y2: number } {
  if (p.boxW && p.boxH) {
    return { x1: p.x - p.boxW / 2, x2: p.x + p.boxW / 2, y1: p.y - p.boxH / 2, y2: p.y + p.boxH / 2 };
  }
  const size = labelSizeFor(p.level);
  const w = p.label.length * size * CHAR_W;
  const gap = p.r + 10;
  const cy = p.y + p.labelDy;
  if (p.anchor === 'middle') return { x1: p.x - w / 2, x2: p.x + w / 2, y1: cy - size, y2: cy + 4 };
  if (p.anchor === 'end') return { x1: p.x - gap - w, x2: p.x - gap, y1: cy - size, y2: cy + 4 };
  return { x1: p.x + gap, x2: p.x + gap + w, y1: cy - size, y2: cy + 4 };
}

function intersects(a: Box, b: Box): boolean {
  return a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
}

/** The glyph circle and its label, as one rectangle. */
function occupied(p: Placed): Box {
  const l = labelBox(p);
  return {
    x1: Math.min(l.x1, p.x - p.r),
    x2: Math.max(l.x2, p.x + p.r),
    y1: Math.min(l.y1, p.y - p.r),
    y2: Math.max(l.y2, p.y + p.r)
  };
}

/**
 * Move nodes out of the regions the interface covers.
 *
 * Vertical first, because the side of the focus a node sits on carries meaning
 * (importers left, imports right) and must survive. A node that cannot escape
 * vertically inside the frame is moved sideways as a last resort.
 */
function avoidBoxes(placed: Placed[], boxes: Box[], width: number, height: number): void {
  if (!boxes.length) return;
  placed.forEach((p) => {
    if (p.level === 0) return;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const hit = boxes.find((b) => intersects(occupied(p), b));
      if (!hit) return;
      const box = occupied(p);
      const down = hit.y2 - box.y1 + 8;
      const up = box.y2 - hit.y1 + 8;
      const canDown = box.y2 + down < height - 8;
      const canUp = box.y1 - up > 8;
      if (canDown && (!canUp || down <= up)) p.y += down;
      else if (canUp) p.y -= up;
      else {
        const right = hit.x2 - box.x1 + 10;
        const left = box.x2 - hit.x1 + 10;
        if (box.x2 + right < width - 8 && right <= left) p.x += right;
        else p.x -= left;
      }
    }
  });
}

/**
 * Separate labels, not dots.
 *
 * Vertical-only: moving a node sideways changes which side of the focus it
 * appears on, and that side carries meaning (importers left, imports right).
 * The focus never moves — it is the thing you asked about.
 */
function relaxLabels(placed: Placed[], width: number, height: number, passes = 140): void {
  const pad = 9;
  const movable = placed.filter((p) => p.level !== 0);
  for (let pass = 0; pass < passes; pass += 1) {
    let moved = false;
    for (let i = 0; i < movable.length; i += 1) {
      for (let j = i + 1; j < movable.length; j += 1) {
        const a = movable[i];
        const b = movable[j];
        const ba = labelBox(a);
        const bb = labelBox(b);
        if (ba.x2 + pad < bb.x1 || bb.x2 + pad < ba.x1) continue;
        const overlap = Math.min(ba.y2, bb.y2) - Math.max(ba.y1, bb.y1) + pad;
        if (overlap <= 0) continue;
        const push = overlap / 2;
        if (ba.y1 < bb.y1) {
          a.y -= push;
          b.y += push;
        } else {
          a.y += push;
          b.y -= push;
        }
        moved = true;
      }
    }
    if (!moved) break;
  }
  // Keep glyph AND label inside the frame; flip the anchor when a label would
  // run off the edge rather than clipping it.
  placed.forEach((p) => {
    if (p.level === 0) return;
    p.y = Math.min(height - 30, Math.max(30, p.y));
    const box = labelBox(p);
    if (box.x1 < 8 && p.anchor === 'end') p.anchor = 'start';
    else if (box.x2 > width - 8 && p.anchor === 'start') p.anchor = 'end';
    const after = labelBox(p);
    if (after.x1 < 8) p.x += 8 - after.x1;
    if (after.x2 > width - 8) p.x -= after.x2 - (width - 8);
  });
}

function linesFor(nh: Neighbourhood, byId: Map<string, Placed>): Line[] {
  const backbone = new Set(nh.backbone.map((e) => `${e.source} ${e.target}`));
  const out: Line[] = [];
  nh.edges.forEach((e) => {
    const from = byId.get(e.source);
    const to = byId.get(e.target);
    if (!from || !to) return;
    out.push({
      from,
      to,
      backbone: backbone.has(`${e.source} ${e.target}`),
      via: e.target === nh.focus ? 'in' : 'out'
    });
  });
  return out;
}

/**
 * The vertical band a side of the stage can actually use.
 *
 * A keep-out box that touches the top edge raises the floor; one that touches
 * the bottom lowers the ceiling. Laying out INSIDE the band beats laying out
 * across the whole height and then shoving nodes out of the way: the second
 * produces a pile exactly where the pushing stops.
 */
function freeBand(boxes: Box[], side: -1 | 1, width: number, height: number): { top: number; bottom: number } {
  const x1 = side === -1 ? 0 : width / 2;
  const x2 = side === -1 ? width / 2 : width;
  let top = 24;
  let bottom = height - 24;
  boxes.forEach((b) => {
    if (b.x2 <= x1 || b.x1 >= x2) return;
    if (b.y1 <= 2) top = Math.max(top, b.y2 + 16);
    else if (b.y2 >= height - 2) bottom = Math.min(bottom, b.y1 - 16);
  });
  if (bottom - top < 120) return { top: 24, bottom: height - 24 };
  return { top, bottom };
}

/** Split the level-1 budget between the two sides in proportion to their size. */
function share(ins: number, outs: number, budget: number): [number, number] {
  const total = ins + outs;
  if (total <= budget) return [ins, outs];
  const a = Math.max(ins ? 1 : 0, Math.round((ins / total) * budget));
  return [Math.min(ins, a), Math.min(outs, budget - Math.min(ins, a))];
}

interface Selection {
  ins: Neighbour[];
  outs: Neighbour[];
  level2: Neighbour[];
  hidden1: number;
  hidden2: number;
  hiddenIds: string[];
}

/**
 * Choose what is drawn.
 *
 * Level 2 is restricted to neighbours of the level-1 nodes that survived: a
 * second-level node floating with no visible parent is a dot with no story.
 */
function choose(
  nh: Neighbourhood,
  opts: LayoutOptions,
  /** hard per-side ceilings from the free band, when the caller has them */
  caps?: { left: number; right: number }
): Selection {
  const allIns = nh.level1.filter((n) => n.via !== 'out');
  const allOuts = nh.level1.filter((n) => n.via === 'out');
  let [takeIn, takeOut] = share(allIns.length, allOuts.length, opts.maxLevel1);
  if (caps) {
    // Fitting the band beats overflowing it: a neighbour that cannot be drawn
    // legibly joins the aggregate glyph, where it is still counted and still
    // reachable, instead of landing on top of its neighbour's name.
    //
    // When every neighbour points the same way — and for a module 161 files
    // import, they do — the side of the stage carries no meaning, so the empty
    // half is given to the side that has something to show. Half a picture and
    // an empty half is not a composition, it is a wasted half.
    const both = caps.left + caps.right;
    takeIn = Math.min(takeIn, allOuts.length === 0 ? both : caps.left);
    takeOut = Math.min(takeOut, allIns.length === 0 ? both : caps.right);
  }
  const ins = allIns.slice(0, takeIn);
  const outs = allOuts.slice(0, takeOut);

  const shown = new Set([...ins, ...outs].map((n) => n.id));
  const reachable = new Set<string>();
  nh.edges.forEach((e) => {
    if (shown.has(e.source)) reachable.add(e.target);
    if (shown.has(e.target)) reachable.add(e.source);
  });
  const candidates = nh.level2.filter((n) => reachable.has(n.id));
  const level2 = candidates.slice(0, opts.maxLevel2);

  const hiddenIds = [
    ...allIns.slice(takeIn).map((n) => n.id),
    ...allOuts.slice(takeOut).map((n) => n.id)
  ];

  return {
    ins,
    outs,
    level2,
    hidden1: hiddenIds.length,
    hidden2: nh.level2.length - level2.length,
    hiddenIds
  };
}

function moreGlyph(count: number, x: number, y: number): Placed {
  const label = `+${count} weitere`;
  return {
    id: MORE_ID,
    x,
    y,
    r: 13,
    level: 1,
    kind: 'more',
    moreCount: count,
    label,
    full: `${count} weitere direkte Nachbarn — anklicken zum Auflisten`,
    anchor: 'middle',
    labelDy: 27
  };
}

/**
 * Radial forest. Importers take the left half, imports the right, so the side
 * of a node is a fact about the data rather than a arrangement. Level 1 sits
 * on two staggered radii — alternating in and out — which is what keeps long
 * file names from stacking into a wall.
 */
export function radialLayout(nh: Neighbourhood, opts: LayoutOptions): StageLayout {
  const { width, height, sizeByFanIn } = opts;
  const boxes = opts.avoid ?? [];
  const cx = width / 2;
  const cy = height / 2;

  // How many names each side can carry legibly, from the space it actually has.
  const bandL = freeBand(boxes, -1, width, height);
  const bandR = freeBand(boxes, 1, width, height);
  const ROW = 34;
  const sel = choose(nh, opts, {
    left: Math.max(2, Math.floor((bandL.bottom - bandL.top) / ROW)),
    right: Math.max(2, Math.floor((bandR.bottom - bandR.top) / ROW))
  });

  const name = labeller([nh.focus, ...sel.ins.map((n) => n.id), ...sel.outs.map((n) => n.id), ...sel.level2.map((n) => n.id)]);

  const placed: Placed[] = [];
  const byId = new Map<string, Placed>();

  const focus = place(nh.focus, cx, cy, 0, { id: nh.focus, level: 1, via: 'in', node: nh.focusNode }, sizeByFanIn, cx, name);
  placed.push(focus);
  byId.set(focus.id, focus);

  const side = (list: Neighbour[], dir: -1 | 1, band: { top: number; bottom: number }) => {
    const n = list.length;
    if (!n) return;
    // Two radii, alternating, so neighbouring labels are never at the same x.
    const rInner = Math.min(width * 0.17, 210);
    const rOuter = Math.min(width * 0.27, 330);
    const top = band.top + 10;
    const span = Math.max(60, band.bottom - band.top - 20);
    list.forEach((entry, i) => {
      const t = n === 1 ? 0.5 : i / (n - 1);
      const y = top + t * span;
      const rx = i % 2 === 0 ? rInner : rOuter;
      // ease the x in towards the focus at the vertical extremes
      const bulge = Math.cos((t - 0.5) * Math.PI) * 0.3 + 0.7;
      const p = place(entry.id, cx + dir * rx * bulge, y, 1, entry, sizeByFanIn, cx, name);
      placed.push(p);
      byId.set(p.id, p);
    });
  };

  if (sel.outs.length === 0 && sel.ins.length > 0) {
    // one-sided: alternate down the two halves so the heaviest stay near the top
    side(sel.ins.filter((_, i) => i % 2 === 0), -1, bandL);
    side(sel.ins.filter((_, i) => i % 2 === 1), 1, bandR);
  } else if (sel.ins.length === 0 && sel.outs.length > 0) {
    side(sel.outs.filter((_, i) => i % 2 === 0), 1, bandR);
    side(sel.outs.filter((_, i) => i % 2 === 1), -1, bandL);
  } else {
    side(sel.ins, -1, bandL);
    side(sel.outs, 1, bandR);
  }

  /**
   * Level 2 rides an outer ellipse, but a slot that would land under the
   * interface is SKIPPED rather than shoved: walking to the next free angle
   * keeps the ring a ring, where pushing turns it into a queue against the
   * edge of the keep-out box.
   */
  // Everything already on the stage, level 1 included. Checking only against
  // other level-2 nodes let a distant node land on top of a direct neighbour.
  const taken: Placed[] = placed.filter((p) => p.level !== 0);
  const total = Math.max(1, sel.level2.length);
  const step = Math.PI / 22;
  let dropped = 0;
  sel.level2.forEach((entry, i) => {
    const rx = Math.min(width * 0.44, 600);
    const ry = Math.min(height * 0.44, 360);
    // Each node gets its own share of the circle and then looks for room
    // NEAR it, alternating outwards. Walking a single cursor instead made
    // every blocked slot push the whole remainder into one crowded quadrant.
    const ideal = (i / total) * Math.PI * 2 - Math.PI / 2;
    let put: Placed | undefined;
    for (let k = 0; k < 44 && !put; k += 1) {
      const offset = (k === 0 ? 0 : Math.ceil(k / 2) * step) * (k % 2 === 0 ? 1 : -1);
      const a = ideal + offset;
      const candidate = place(entry.id, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, 2, entry, sizeByFanIn, cx, name);
      const box = occupied(candidate);
      const offFrame = box.x1 < 8 || box.x2 > width - 8 || box.y1 < 8 || box.y2 > height - 8;
      const blocked = boxes.some((b) => intersects(box, b)) || taken.some((t) => intersects(occupied(t), box));
      if (!offFrame && !blocked) put = candidate;
    }
    if (!put) {
      dropped += 1;
      return;
    }
    taken.push(put);
    placed.push(put);
    byId.set(put.id, put);
  });
  sel.hidden2 += dropped;

  if (sel.hidden1 > 0) {
    // Under the focus, on the centre line: the one place both bands leave free.
    const g = moreGlyph(sel.hidden1, cx, Math.min(height - 40, cy + Math.min(height * 0.34, 280)));
    placed.push(g);
    byId.set(g.id, g);
  }

  relaxLabels(placed, width, height);
  avoidBoxes(placed, boxes, width, height);

  return {
    placed,
    byId,
    lines: linesFor(nh, byId),
    width,
    height,
    hidden1: sel.hidden1,
    hidden2: sel.hidden2,
    hiddenIds: sel.hiddenIds
  };
}

/**
 * Columns of labelled cards. Readability over beauty: every neighbour is a box
 * with its name and its importer count. Column positions are derived from the
 * widest card actually in the column, so cards cannot land on top of each
 * other the way a fixed offset let them.
 */
export function cardLayout(nh: Neighbourhood, opts: LayoutOptions): StageLayout {
  const { width, height, sizeByFanIn } = opts;
  const boxes = opts.avoid ?? [];
  const cx = width / 2;
  const cy = height / 2;

  const bandL = freeBand(boxes, -1, width, height);
  const bandR = freeBand(boxes, 1, width, height);
  // A card is 34 tall and needs air; two rings share the band, so each side's
  // ceiling is what fits at that pitch.
  const PITCH = 56;
  const capL = Math.max(2, Math.floor((bandL.bottom - bandL.top) / PITCH));
  const capR = Math.max(2, Math.floor((bandR.bottom - bandR.top) / PITCH));

  // Cards are wide; a smaller budget is the honest trade, and the aggregate
  // glyph carries the rest.
  const sel = choose(
    nh,
    { ...opts, maxLevel1: Math.min(opts.maxLevel1, 10), maxLevel2: Math.min(opts.maxLevel2, 8) },
    { left: capL, right: capR }
  );

  const name = labeller([nh.focus, ...sel.ins.map((n) => n.id), ...sel.outs.map((n) => n.id), ...sel.level2.map((n) => n.id)]);

  const placed: Placed[] = [];
  const byId = new Map<string, Placed>();
  const focus = place(nh.focus, cx, cy, 0, { id: nh.focus, level: 1, via: 'in', node: nh.focusNode }, sizeByFanIn, cx, name);
  focus.anchor = 'middle';
  focus.labelDy = 0;
  focus.boxW = Math.max(96, focus.label.length * 7.4 + 30);
  focus.boxH = 46;
  placed.push(focus);
  byId.set(focus.id, focus);

  const asCard = (p: Placed) => {
    p.anchor = 'middle';
    p.labelDy = 0;
    p.boxW = Math.max(96, p.label.length * 7.4 + 30);
    p.boxH = p.level === 0 ? 46 : 34;
    return p;
  };

  const column = (
    list: Neighbour[],
    dir: -1 | 1,
    ring: 1 | 2,
    innerEdge: number,
    band: { top: number; bottom: number }
  ): number => {
    if (!list.length) return innerEdge;
    const built = list.map((n) => asCard(place(n.id, 0, 0, ring, n, sizeByFanIn, cx, name)));
    const widest = Math.max(...built.map((p) => p.boxW || 96));
    const centreLine = innerEdge + dir * (widest / 2 + 46);
    const span = band.bottom - band.top;
    const gap = Math.min(PITCH + 12, Math.max(46, span / Math.max(1, built.length)));
    const stack = (built.length - 1) * gap;
    // Centre the column in the band, then clamp so it cannot run out of it.
    const top = Math.max(band.top + 24, Math.min(cy - stack / 2, band.bottom - stack - 24));
    built.forEach((p, i) => {
      p.x = centreLine;
      p.y = top + i * gap;
      placed.push(p);
      byId.set(p.id, p);
    });
    return centreLine + dir * (widest / 2);
  };

  const focusHalf = (focus.boxW || 96) / 2;
  const oneSided = sel.outs.length === 0 && sel.ins.length > 0;
  const leftFirst = oneSided ? sel.ins.filter((_, i) => i % 2 === 0) : sel.ins;
  const rightFirst = oneSided ? sel.ins.filter((_, i) => i % 2 === 1) : sel.outs;
  const leftEdge = column(leftFirst, -1, 1, cx - focusHalf, bandL);
  const rightEdge = column(rightFirst, 1, 1, cx + focusHalf, bandR);

  const half = Math.ceil(sel.level2.length / 2);
  column(sel.level2.slice(0, half), -1, 2, leftEdge, bandL);
  column(sel.level2.slice(half), 1, 2, rightEdge, bandR);

  if (sel.hidden1 > 0) {
    const g = moreGlyph(sel.hidden1, cx, Math.min(height - 40, cy + Math.min(height * 0.34, 260)));
    g.labelDy = 0;
    placed.push(g);
    byId.set(g.id, g);
  }

  relaxLabels(placed, width, height);
  avoidBoxes(placed, boxes, width, height);

  return {
    placed,
    byId,
    lines: linesFor(nh, byId),
    width,
    height,
    hidden1: sel.hidden1,
    hidden2: sel.hidden2,
    hiddenIds: sel.hiddenIds
  };
}

/**
 * One axis, relations as arcs above it. Ordered so the focus sits in the
 * middle with its importers to the left and its imports to the right, which
 * makes the direction of every arc readable without a legend.
 */
export function arcLayout(nh: Neighbourhood, opts: LayoutOptions): StageLayout {
  const { width, height, sizeByFanIn } = opts;
  /**
   * A printed figure has one axis and finite width. 96px per position is what
   * a 45-degree file name needs before its neighbour's name starts under it,
   * so the axis takes what fits and the aggregate glyph carries the rest —
   * the same bargain the other layouts make, priced for this one.
   */
  const seats = Math.max(5, Math.floor((width - 140) / 96));
  const sel = choose(nh, {
    ...opts,
    maxLevel1: Math.min(opts.maxLevel1, Math.max(2, seats - 4)),
    maxLevel2: Math.min(opts.maxLevel2, Math.max(2, Math.floor(seats / 3)))
  });

  const l2a = sel.level2.slice(0, Math.ceil(sel.level2.length / 2));
  const l2b = sel.level2.slice(Math.ceil(sel.level2.length / 2));

  const order: Array<{ n: Neighbour | undefined; id: string; level: 0 | 1 | 2 }> = [
    ...l2a.map((n) => ({ n, id: n.id, level: 2 as const })),
    ...sel.ins.map((n) => ({ n, id: n.id, level: 1 as const })),
    { n: { id: nh.focus, level: 1, via: 'in' as const, node: nh.focusNode }, id: nh.focus, level: 0 as const },
    ...sel.outs.map((n) => ({ n, id: n.id, level: 1 as const })),
    ...l2b.map((n) => ({ n, id: n.id, level: 2 as const }))
  ];

  // The axis sits low: the arcs need the room above it, and the names need the
  // room below it. Splitting the frame in half gave both half of what they use.
  const baseline = Math.round(height * 0.7);
  const name = labeller(order.map((entry) => entry.id));

  /**
   * The right margin is the length of the longest NAME, not a constant.
   *
   * These labels hang below the axis at 45 degrees, so the last one on the
   * right runs out of the frame by roughly its own length times cos(45). A
   * fixed margin clipped `embeddings.py` off the edge; measuring the labels
   * that are actually seated does not.
   */
  const longest = Math.max(...order.map((entry) => trim(name(entry.id)).length), 1);
  const runOut = longest * LABEL_PX.far * CHAR_W * 0.71;
  const marginLeft = 70;
  const marginRight = Math.min(width * 0.22, Math.max(70, runOut + 24));
  const margin = marginLeft;
  const span = Math.max(1, width - marginLeft - marginRight);
  const gap = span / Math.max(1, order.length - 1);
  const placed: Placed[] = [];
  const byId = new Map<string, Placed>();
  order.forEach((entry, i) => {
    const p = place(entry.id, margin + i * gap, baseline, entry.level, entry.n, sizeByFanIn, width / 2, name);
    p.anchor = 'end';
    p.labelDy = 0;
    placed.push(p);
    byId.set(p.id, p);
  });

  if (sel.hidden1 > 0) {
    // Below the axis at the left margin, where the figure's caption would go —
    // not on top of the zoom controls in the opposite corner.
    const g = moreGlyph(sel.hidden1, margin + 40, Math.min(height - 24, baseline + 150));
    g.anchor = 'middle';
    g.labelDy = 0;
    placed.push(g);
    byId.set(g.id, g);
  }

  return {
    placed,
    byId,
    lines: linesFor(nh, byId),
    width,
    height,
    hidden1: sel.hidden1,
    hidden2: sel.hidden2,
    hiddenIds: sel.hiddenIds
  };
}

export function layoutFor(
  kind: 'forest' | 'stars' | 'cards' | 'arcs',
  nh: Neighbourhood,
  opts: LayoutOptions
): StageLayout {
  if (kind === 'cards') return cardLayout(nh, opts);
  if (kind === 'arcs') return arcLayout(nh, opts);
  return radialLayout(nh, opts);
}
