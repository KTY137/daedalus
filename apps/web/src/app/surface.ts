import surfaceShims from './surface-shims.json';

export type AppSurface = 'cockpit';

const classicQueryValues = surfaceShims.entries.flatMap((entry) => entry.query_values);

/**
 * Resolve the compatibility query at the one application-composition door.
 *
 * Every value opens the one Cockpit implementation. The known `classic` and
 * `legacy` values remain recorded below so caller audits can retire the query
 * shim without recreating a second application branch.
 */
export function resolveSurface(search: string): AppSurface {
  const requested = new URLSearchParams(search).get('surface');
  if (requested !== null && classicQueryValues.includes(requested)) return 'cockpit';
  return 'cockpit';
}

export { surfaceShims };
