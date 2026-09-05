import type { FourfoldGraphNode, FourfoldPlane } from '@/shared/contracts';

export type FourfoldLayout = 'layers' | 'sphere';

export const FOURFOLD_ORDER: FourfoldPlane[] = ['code', 'type', 'data', 'knowledge'];

export const PLANE_LABEL: Record<FourfoldPlane, string> = {
  code: 'Code',
  type: 'Typen',
  data: 'Daten',
  knowledge: 'Wissen'
};

export const PLANE_MARK: Record<FourfoldPlane, string> = {
  code: 'C',
  type: 'T',
  data: 'D',
  knowledge: 'W'
};

export const PLANE_COLOR: Record<FourfoldPlane, string> = {
  code: '#5b8ff9',
  type: '#a66cff',
  data: '#2fbf71',
  knowledge: '#f59e0b'
};

export interface FourfoldPosition {
  id: string;
  x: number;
  y: number;
  size: number;
}

function visualSize(node: FourfoldGraphNode): number {
  const evidence = Math.max(0, node.fan_in * 2 + node.loc / 60 + node.score / 3);
  return Math.min(10, 3.2 + Math.log2(1 + evidence));
}

function grouped(nodes: FourfoldGraphNode[]): Map<FourfoldPlane, FourfoldGraphNode[]> {
  const groups = new Map(FOURFOLD_ORDER.map((plane) => [plane, [] as FourfoldGraphNode[]]));
  nodes.forEach((node) => groups.get(node.plane)?.push(node));
  groups.forEach((planeNodes) => planeNodes.sort((a, b) => a.id.localeCompare(b.id)));
  return groups;
}

/** Deterministic positions: switching filters or reloading never scrambles identity. */
export function layoutFourfold(
  nodes: FourfoldGraphNode[],
  mode: FourfoldLayout
): FourfoldPosition[] {
  const groups = grouped(nodes);
  const result: FourfoldPosition[] = [];
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  FOURFOLD_ORDER.forEach((plane, planeIndex) => {
    const planeNodes = groups.get(plane) ?? [];
    const count = planeNodes.length;
    planeNodes.forEach((node, index) => {
      if (mode === 'layers') {
        // Long planes wrap into shallow rows instead of becoming one
        // unreadable line. The four plane bands themselves never overlap.
        const columns = Math.max(1, Math.ceil(Math.sqrt(count * 2.8)));
        const row = Math.floor(index / columns);
        const column = index % columns;
        const rows = Math.max(1, Math.ceil(count / columns));
        result.push({
          id: node.id,
          x: column - (Math.min(columns, count) - 1) / 2 + (row % 2) * 0.24,
          y: (1.5 - planeIndex) * 3.2 + (row - (rows - 1) / 2) * 0.46,
          size: visualSize(node)
        });
        return;
      }

      // A 2-D orthographic projection of four nested shells. Knowledge is
      // the core, code the outer skin; the order is semantic, not a force-fit.
      const shell = 4 - planeIndex;
      const radius = shell * 1.65;
      const angle = index * goldenAngle + planeIndex * 0.57;
      const depth = Math.sin(angle * 0.5);
      result.push({
        id: node.id,
        x: Math.cos(angle) * radius * (0.76 + depth * 0.12),
        y: Math.sin(angle) * radius * 0.72,
        size: visualSize(node)
      });
    });
  });
  return result;
}

export function searchFourfold(
  nodes: FourfoldGraphNode[],
  query: string,
  limit = 10
): FourfoldGraphNode[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  return nodes
    .filter((node) => `${node.id} ${node.kind} ${node.language}`.toLocaleLowerCase().includes(needle))
    .sort((a, b) => {
      const aStarts = a.id.toLocaleLowerCase().startsWith(needle) ? 0 : 1;
      const bStarts = b.id.toLocaleLowerCase().startsWith(needle) ? 0 : 1;
      return aStarts - bStarts || b.score - a.score || a.id.localeCompare(b.id);
    })
    .slice(0, limit);
}
