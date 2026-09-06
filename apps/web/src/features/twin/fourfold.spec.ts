import type { FourfoldGraphNode, FourfoldPlane } from '@/shared/contracts';
import { layoutFourfold, searchFourfold } from './fourfold';

function node(id: string, plane: FourfoldPlane, score = 0): FourfoldGraphNode {
  return { id, plane, kind: plane === 'code' ? 'module' : plane, language: '', loc: 10, score, fan_in: 1 };
}

export function runFourfoldSpec() {
  const results: Array<{ name: string; ok: boolean; detail?: string }> = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });
  const nodes = [
    node('src/a.ts', 'code', 8),
    node('src/b.ts', 'code', 2),
    node('type:src/a.ts#Message', 'type'),
    node('dataset:events', 'data'),
    node('README.md', 'knowledge')
  ];

  const layered = layoutFourfold(nodes, 'layers');
  const yByPlane = new Map(nodes.map((item) => [item.plane, layered.find((p) => p.id === item.id)!.y]));
  check(
    'layered Fourfold gives all four planes distinct bands',
    new Set(yByPlane.values()).size === 4
  );
  check(
    'layered Fourfold is deterministic',
    JSON.stringify(layered) === JSON.stringify(layoutFourfold([...nodes].reverse(), 'layers'))
  );

  const sphere = layoutFourfold(nodes, 'sphere');
  const radius = (id: string) => {
    const p = sphere.find((position) => position.id === id)!;
    return Math.hypot(p.x, p.y / 0.72);
  };
  check(
    'sphere places knowledge inside data, type and code shells',
    radius('README.md') < radius('dataset:events')
      && radius('dataset:events') < radius('type:src/a.ts#Message')
      && radius('type:src/a.ts#Message') < radius('src/a.ts')
  );

  const hits = searchFourfold(nodes, 'message');
  check(
    'Fourfold search reaches non-code planes',
    hits.length === 1 && hits[0].plane === 'type'
  );
  return results;
}
