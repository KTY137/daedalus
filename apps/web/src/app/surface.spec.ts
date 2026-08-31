import { resolveSurface, surfaceShims } from './surface';

export interface SurfaceSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

export function runSurfaceSpec(): SurfaceSpecResult[] {
  const results: SurfaceSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const cases: Array<[string, 'cockpit' | 'classic']> = [
    ['', 'cockpit'],
    ['?project=daedalus', 'cockpit'],
    ['?surface=cockpit', 'cockpit'],
    ['?surface=unknown', 'cockpit'],
    ['?surface=CLASSIC', 'cockpit'],
    ['?surface=classic', 'classic'],
    ['?surface=legacy', 'classic'],
    ['?project=daedalus&surface=classic&view=chat', 'classic']
  ];

  for (const [search, expected] of cases) {
    const actual = resolveSurface(search);
    check(`surface ${JSON.stringify(search)} resolves to ${expected}`, actual === expected, `actual=${actual}`);
  }

  check('the surface shim registry has one reviewed compatibility entry', surfaceShims.entries.length === 1);
  const shim = surfaceShims.entries[0];
  check('the classic and legacy values are registered exactly', shim.query_values.join(',') === 'classic,legacy');
  check('the compatibility surface has an app-layer owner', shim.owner === 'apps/web/src/app/SurfaceRoot.tsx');
  check('the compatibility target remains the existing classic implementation', shim.target === 'apps/web/src/App.tsx');
  check('the shim has an evidence-based removal criterion', shim.removal_criteria.length > 120);

  return results;
}
