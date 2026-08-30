// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import type { StructureGraph, StructureGraphEdge, StructureGraphNode } from '../types';

/**
 * The neighbourhood model behind the stage.
 *
 * The stage never draws "the codebase". It draws ONE module and what actually
 * reaches it, because that is the only claim the data supports: the backend
 * caps the map at the highest-heat nodes and reports how many edges lead off
 * it (`n_edges_offmap`). A whole-repo hairball would silently present a sample
 * as a census.
 *
 * Direction matters and is kept: `source` imports `target`. "Wer ruft mich"
 * (incoming) and "was ich brauche" (outgoing) are different questions and the
 * cockpit lets you see them apart.
 */

export interface GraphIndex {
  nodes: Map<string, StructureGraphNode>;
  /** module -> modules that import it */
  incoming: Map<string, string[]>;
  /** module -> modules it imports */
  outgoing: Map<string, string[]>;
  edges: StructureGraphEdge[];
  /** the highest fan-in module, a sane default focus */
  busiest: string;
}

export function buildIndex(graph: StructureGraph | undefined): GraphIndex {
  const nodes = new Map<string, StructureGraphNode>();
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  const edges = graph?.edges ?? [];

  (graph?.nodes ?? []).forEach((n) => {
    nodes.set(n.module, n);
    incoming.set(n.module, []);
    outgoing.set(n.module, []);
  });

  edges.forEach((e) => {
    if (!nodes.has(e.source) || !nodes.has(e.target)) return;
    outgoing.get(e.source)!.push(e.target);
    incoming.get(e.target)!.push(e.source);
  });

  let busiest = '';
  let best = -1;
  nodes.forEach((n, id) => {
    const degree = (incoming.get(id)?.length ?? 0) + (outgoing.get(id)?.length ?? 0);
    // Ties break on heat, so the default focus is a module worth looking at.
    if (degree > best || (degree === best && n.score > (nodes.get(busiest)?.score ?? -1))) {
      best = degree;
      busiest = id;
    }
  });

  return { nodes, incoming, outgoing, edges, busiest };
}

export type Direction = 'both' | 'in' | 'out';

export interface Neighbour {
  id: string;
  level: 1 | 2;
  /** how this node relates to the focus: it imports the focus, or the focus imports it */
  via: 'in' | 'out' | 'mixed';
  node?: StructureGraphNode;
}

export interface Neighbourhood {
  focus: string;
  focusNode?: StructureGraphNode;
  level1: Neighbour[];
  level2: Neighbour[];
  /** edges among focus + level 1 — the backbone drawn at rest */
  backbone: StructureGraphEdge[];
  /** every edge inside the two-level neighbourhood */
  edges: StructureGraphEdge[];
  /** direct neighbour count — the "N direkt" number */
  direct: number;
  /** unique modules reachable within two levels, focus excluded */
  reach: number;
}

function step(index: GraphIndex, id: string, direction: Direction): Array<{ id: string; via: 'in' | 'out' }> {
  const out: Array<{ id: string; via: 'in' | 'out' }> = [];
  if (direction !== 'out') (index.incoming.get(id) ?? []).forEach((n) => out.push({ id: n, via: 'in' }));
  if (direction !== 'in') (index.outgoing.get(id) ?? []).forEach((n) => out.push({ id: n, via: 'out' }));
  return out;
}

export function neighbourhood(index: GraphIndex, focus: string, direction: Direction = 'both'): Neighbourhood {
  const seen = new Map<string, Neighbour>();

  step(index, focus, direction).forEach(({ id, via }) => {
    if (id === focus) return;
    const existing = seen.get(id);
    if (existing) {
      if (existing.via !== via) existing.via = 'mixed';
      return;
    }
    seen.set(id, { id, level: 1, via, node: index.nodes.get(id) });
  });

  const level1 = [...seen.values()];
  level1.forEach((n) => {
    step(index, n.id, direction).forEach(({ id }) => {
      if (id === focus || seen.has(id)) return;
      seen.set(id, { id, level: 2, via: n.via, node: index.nodes.get(id) });
    });
  });

  const level2 = [...seen.values()].filter((n) => n.level === 2);
  const inSet = new Set<string>([focus, ...seen.keys()]);
  const backboneSet = new Set<string>([focus, ...level1.map((n) => n.id)]);

  const edges = index.edges.filter((e) => inSet.has(e.source) && inSet.has(e.target));
  /**
   * The backbone is every edge that TOUCHES the focus or a direct neighbour —
   * not only the edges running between them. The stricter reading left the
   * second level as a field of dots with no lines whenever the focus had one
   * direct neighbour, which reads as a broken render rather than as a sparse
   * module. Only level-2-to-level-2 edges wait for hover.
   */
  const backbone = edges.filter((e) => backboneSet.has(e.source) || backboneSet.has(e.target));

  // Sort by weight so the caller can trim the ring without dropping the
  // important neighbours first.
  const byWeight = (a: Neighbour, b: Neighbour) => (b.node?.score ?? 0) - (a.node?.score ?? 0);
  level1.sort(byWeight);
  level2.sort(byWeight);

  return {
    focus,
    focusNode: index.nodes.get(focus),
    level1,
    level2,
    backbone,
    edges,
    direct: level1.length,
    reach: level1.length + level2.length
  };
}

/** The short label for a module path: the file name, with the parent when it disambiguates. */
export function shortLabel(module: string): string {
  const parts = module.split(/[\\/]/);
  const file = parts[parts.length - 1] || module;
  if (parts.length === 1) return file;
  // index.ts / __init__.py alone tell the reader nothing.
  if (/^(index|__init__|main|mod)\.[a-z]+$/i.test(file)) {
    return `${parts[parts.length - 2]}/${file}`;
  }
  return file;
}

/**
 * The module the cockpit opens on.
 *
 * Not the busiest: that is whatever everything imports, and its neighbourhood
 * is a wall of names whose only story is "it is imported". Not simply the
 * hottest either: the hottest module in this repository has ONE drawn edge,
 * and a stage with one line on it teaches nobody anything.
 *
 * So: the hottest module whose neighbourhood is big enough to show structure
 * and small enough to read. If none qualifies, heat wins — an honest sparse
 * picture beats an unreadable dense one.
 */
export function defaultFocus(index: GraphIndex, min = 3, max = 22): string {
  const ranked = rankModules(index, 200);
  const degree = (id: string) => (index.incoming.get(id)?.length ?? 0) + (index.outgoing.get(id)?.length ?? 0);
  const good = ranked.find((n) => {
    const d = degree(n.module);
    return d >= min && d <= max;
  });
  return good?.module || ranked[0]?.module || index.busiest;
}

/** Rank modules for the "was ist hier los" list: heat first, then reach. */
export function rankModules(index: GraphIndex, limit = 40): StructureGraphNode[] {
  return [...index.nodes.values()].sort((a, b) => b.score - a.score || b.fan_in - a.fan_in).slice(0, limit);
}

/** Case-insensitive substring search over module paths, best-prefix first. */
export function searchModules(index: GraphIndex, query: string, limit = 12): StructureGraphNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: Array<{ node: StructureGraphNode; rank: number }> = [];
  index.nodes.forEach((node, id) => {
    const low = id.toLowerCase();
    const at = low.indexOf(q);
    if (at === -1) return;
    const file = shortLabel(id).toLowerCase();
    // A hit in the file name beats a hit somewhere in the directory chain.
    const rank = (file.startsWith(q) ? 0 : file.includes(q) ? 1 : 2) * 1000 + at;
    hits.push({ node, rank });
  });
  hits.sort((a, b) => a.rank - b.rank || b.node.score - a.node.score);
  return hits.slice(0, limit).map((h) => h.node);
}
