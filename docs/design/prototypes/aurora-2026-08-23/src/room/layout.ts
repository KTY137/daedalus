/* Where a node stands.
 *
 * The object is an orrery: four bodies of nodes hanging in one room. Each
 * plane is a sphere — its nodes sit on the shell on a golden-angle lattice
 * with a deterministic breath in and out of the surface, so the body has
 * volume instead of reading as a ring seen edge-on. Code is the largest and
 * nearest, knowledge the smallest and furthest, type and data offset between
 * them, and no two silhouettes touch: the gaps between the bodies are where
 * the type goes, and that is a constraint the layout has to satisfy, not a
 * hope the renderer might fulfil.
 *
 * Ordered keeps the same nodes and rearranges them into four columns of type.
 *
 * Nothing here is random. The same run produces the same picture. */

import * as THREE from 'three';
import type { Fixture, GEdge, GNode, Plane } from '../data';

export interface Body {
  c: THREE.Vector3;   // centre, in the object's own space
  R: number;          // shell radius
  spin: number;       // radians per second about its own axis
  axis: THREE.Vector3;
  nodeScale: number;  // a small body carries smaller nodes
}

const body = (x: number, y: number, z: number, R: number, spin: number, ax: number, ay: number, az: number): Body => ({
  c: new THREE.Vector3(x, y, z),
  R, spin,
  axis: new THREE.Vector3(ax, ay, az).normalize(),
  nodeScale: 0.52 + 0.48 * (R / 0.79),
});

export const BODIES: Record<Plane, Body> = {
  code: body(-0.98, 0.98, 1.20, 0.79, 0.050, 0.16, 1, 0.10),
  type: body(0.92, 1.98, 0.20, 0.56, 0.068, -0.30, 1, 0.18),
  data: body(0.88, -0.56, -0.50, 0.52, 0.061, 0.22, 1, -0.26),
  knowledge: body(-0.80, -1.46, -1.50, 0.46, 0.085, -0.14, 1, 0.34),
};

export const PLANE_ORDER: Plane[] = ['code', 'type', 'data', 'knowledge'];

/* The ordered view is one ranked column of all 32 nodes, grouped by plane and
   busiest first inside each group. Four columns would have to share the
   corridor the panels leave open, which would force every name to be truncated
   to nothing; one column can carry the full name of every node. */
/* The column has to fit between the toolbar and the ornament with room for a
   group head above each group: 32 rows at 20 px, three group breaks at 18.6 px,
   and a 20 px lift for each head. Every one of the 32 names is carried; a row
   that could not be placed would be a layout bug, not a graceful degradation. */
export const ORDERED_X = -1.46, ORDERED_Y0 = 2.945, ORDERED_DY = 0.156, ORDERED_GAP = 0.145;
export const ORDERED_SCALE = 0.35;

const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return ((h >>> 0) % 100000) / 100000; };

export interface Layouts {
  /** position on the body's own shell, before the body has turned */
  local: Record<string, THREE.Vector3>;
  ordered: Record<string, THREE.Vector3>;
  plane: Record<string, Plane>;
  deg: Record<string, number>;
  radius: Record<string, number>;
}

/** Radius from the number of relations the index records at a node. The
 *  fixture's raw in-degree spans 0..2 and carries no rhythm; total relations
 *  span 1..7, and the interface says "relations" rather than pretending. */
export function radiusFor(deg: number): number {
  return 0.046 * (1 + 0.92 * Math.pow(Math.max(0, deg - 1), 0.62));
}

/** the pointer disc: never smaller than 44 px at the composed camera */
export const hitRadius = (r: number) => Math.max(0.218, r * 1.8);

export function buildLayouts(fx: Fixture, edges: GEdge[]): Layouts {
  const deg: Record<string, number> = {};
  for (const e of edges) { deg[e.s] = (deg[e.s] ?? 0) + 1; deg[e.t] = (deg[e.t] ?? 0) + 1; }

  const local: Record<string, THREE.Vector3> = {};
  const ordered: Record<string, THREE.Vector3> = {};
  const plane: Record<string, Plane> = {};
  const radius: Record<string, number> = {};

  let row = 0;
  PLANE_ORDER.forEach((p, pi) => {
    const b = BODIES[p];
    const ns = fx.graph.nodes.filter(n => n.plane === p);
    // busiest first, walked out from the equator, so a hub lands where the
    // shell is widest and reads as a hub from across the room
    const ranked = [...ns].sort((a, z) => (deg[z.id] ?? 0) - (deg[a.id] ?? 0) || a.id.localeCompare(z.id));
    const n = ranked.length;
    ranked.forEach((nd: GNode, i) => {
      const k = i % 2 === 0 ? i / 2 : n - 1 - (i - 1) / 2;
      const y = 1 - (k + 0.5) * 2 / n;
      const rr = Math.sqrt(Math.max(0, 1 - y * y));
      const th = k * 2.399963 + pi * 0.7;
      const breath = 0.88 + 0.19 * hash(nd.id + 'b');
      local[nd.id] = new THREE.Vector3(
        Math.cos(th) * rr * b.R * breath,
        y * b.R * breath * 1.03,
        Math.sin(th) * rr * b.R * breath
      );
      plane[nd.id] = p;
      radius[nd.id] = radiusFor(deg[nd.id] ?? 1) * b.nodeScale;
    });

    const sorted = [...ns].sort((a, z) => (deg[z.id] ?? 0) - (deg[a.id] ?? 0) || a.label.localeCompare(z.label));
    sorted.forEach(nd => {
      ordered[nd.id] = new THREE.Vector3(ORDERED_X, ORDERED_Y0 - row * ORDERED_DY, 0);
      row++;
    });
    row += ORDERED_GAP / ORDERED_DY;
  });

  return { local, ordered, plane, deg, radius };
}
