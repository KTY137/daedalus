import type { SceneEnvironmentId } from '../theme/types';
import manifest from './environments/manifest.json';

/**
 * The rooms behind the glass.
 *
 * Data only. The images are a separate module (`environmentImages.ts`) so the
 * theme store, the node spec runner and react-dom/server can validate an
 * environment id without ever touching a binary asset. Names and notes are
 * what the owner reads in the Theme Studio; `base` says which ink the picture
 * wants so a light look over a dark room can be flagged rather than guessed.
 *
 * Ids, order and titles follow docs/design/blender-scenes/scripts/build.py
 * (G1-UI-11). Adding a scene there means rendering it, re-running
 * tools/build_scene_environments.py and adding one row here — the spec fails
 * on a registry/manifest mismatch in either direction.
 */
export interface SceneEnvironment {
  id: SceneEnvironmentId;
  name: string;
  note: string;
  base: 'light' | 'dark';
}

export const SCENE_ENVIRONMENTS: readonly SceneEnvironment[] = [
  { id: 'porcelain', name: 'Porcelain', note: 'Helles Studio, ein Band aus Glas.', base: 'light' },
  { id: 'graphite', name: 'Graphite Atelier', note: 'Rauchglas und Titan im Dunkeln.', base: 'dark' },
  { id: 'daylight', name: 'Spatial Daylight', note: 'Steinbogen, Meer und Morgenlicht.', base: 'light' },
  { id: 'dusk', name: 'Spatial Dusk', note: 'Abendhimmel hinter dem Bogen.', base: 'dark' },
  { id: 'studio', name: 'Spatial Studio', note: 'Gestaffelte Galerie, weißes Licht.', base: 'light' },
  { id: 'techno-forest', name: 'Techno Forest', note: 'Lichtfasern zwischen Bäumen.', base: 'dark' }
];

const IDS = new Set<string>(SCENE_ENVIRONMENTS.map((e) => e.id));

export function isSceneEnvironmentId(value: unknown): value is SceneEnvironmentId {
  return typeof value === 'string' && IDS.has(value);
}

export function sceneEnvironment(id: SceneEnvironmentId): SceneEnvironment {
  return SCENE_ENVIRONMENTS.find((e) => e.id === id)!;
}

/** One rendered file and its digest, as written by tools/build_scene_environments.py. */
export interface SceneEnvironmentFile {
  file: string;
  width: number;
  height: number;
  bytes: number;
  sha256: string;
}

/** Where a room's picture came from: the Blender render, its bytes, its settings. */
export interface SceneEnvironmentProvenance {
  id: string;
  title: string;
  /** `draft` means a low-sample preview stood in for a missing final render. */
  quality: 'final' | 'draft';
  source: string;
  sourceSha256: string;
  sourceResolution: number[];
  blender: string | null;
  samples: number | null;
  seed: number | null;
  blend: string | null;
  image: SceneEnvironmentFile;
  thumb: SceneEnvironmentFile;
}

const PROVENANCE: Record<string, SceneEnvironmentProvenance> = Object.fromEntries(
  (manifest.environments as unknown as SceneEnvironmentProvenance[]).map((entry) => [entry.id, entry])
);

export function sceneEnvironmentProvenance(): Record<string, SceneEnvironmentProvenance>;
export function sceneEnvironmentProvenance(id: string): SceneEnvironmentProvenance | undefined;
export function sceneEnvironmentProvenance(
  id?: string
): Record<string, SceneEnvironmentProvenance> | SceneEnvironmentProvenance | undefined {
  return id === undefined ? PROVENANCE : PROVENANCE[id];
}
