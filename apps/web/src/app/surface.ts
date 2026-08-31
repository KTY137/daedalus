import surfaceShims from './surface-shims.json';

export type AppSurface = 'cockpit' | 'classic';

const classicQueryValues = surfaceShims.entries.flatMap((entry) => entry.query_values);

/**
 * Resolve the compatibility query at the one application-composition door.
 *
 * Unknown and absent values keep opening Cockpit. `classic` and its historical
 * `legacy` alias remain exact, case-sensitive compatibility values until the
 * registry's removal criterion is met.
 */
export function resolveSurface(search: string): AppSurface {
  const requested = new URLSearchParams(search).get('surface');
  return requested !== null && classicQueryValues.includes(requested) ? 'classic' : 'cockpit';
}

export { surfaceShims };
