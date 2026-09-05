import type { SceneEnvironmentId } from '../theme/types';

/**
 * The pictures for `environments.ts`, resolved by Vite.
 *
 * `import.meta.glob` is expanded at build time into hashed asset URLs, so a
 * render that is not there yet is simply absent from the map instead of
 * breaking the build. Outside Vite — the esbuild-bundled spec runner,
 * react-dom/server — `import.meta.glob` does not exist, the call throws and
 * the catalogue is empty: the app then renders no room and the Studio marks
 * every tile as not rendered. Nothing here imports an image statically.
 */
let files: Record<string, string> = {};
try {
  files = import.meta.glob('./environments/*.webp', { eager: true, import: 'default' }) as Record<string, string>;
} catch {
  files = {};
}

export function environmentImage(id: SceneEnvironmentId, size: 'full' | 'thumb' = 'full'): string | undefined {
  return files[`./environments/${id}${size === 'thumb' ? '.thumb' : ''}.webp`];
}
