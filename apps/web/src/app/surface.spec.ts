import { resolveSurface, surfaceShims } from './surface';

export interface SurfaceSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

export function runSurfaceSpec(): SurfaceSpecResult[] {
  const results: SurfaceSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const cases: Array<[string, 'cockpit']> = [
    ['', 'cockpit'],
    ['?project=daedalus', 'cockpit'],
    ['?surface=cockpit', 'cockpit'],
    ['?surface=unknown', 'cockpit'],
    ['?surface=CLASSIC', 'cockpit'],
    ['?surface=classic', 'cockpit'],
    ['?surface=legacy', 'cockpit'],
    ['?project=daedalus&surface=classic&view=chat', 'cockpit']
  ];

  for (const [search, expected] of cases) {
    const actual = resolveSurface(search);
    check(`surface ${JSON.stringify(search)} resolves to ${expected}`, actual === expected, `actual=${actual}`);
  }

  check('the surface shim registry has one reviewed compatibility entry', surfaceShims.entries.length === 1);
  const shim = surfaceShims.entries[0];
  check('the classic and legacy values are registered exactly', shim.query_values.join(',') === 'classic,legacy');
  check('the compatibility query has an app-layer owner', shim.owner === 'apps/web/src/app/surface.ts');
  check('the compatibility query targets Cockpit itself', shim.target === 'apps/web/src/cockpit/Cockpit.tsx');
  check('the shim is a same-implementation alias', shim.kind === 'same_implementation_query_alias');
  check('the shim has an evidence-based removal criterion', shim.removal_criteria.length > 80);

  return results;
}
