import { builtIn, BUILT_INS, DEFAULT_THEME_ID } from './presets';
import { exportThemes, importThemes } from './store';
import { SCENE_ENVIRONMENTS, isSceneEnvironmentId, sceneEnvironmentProvenance } from '../scene/environments';

function canonical(value: unknown): string {
  if (typeof value !== 'object' || value === null) return JSON.stringify(value);
  return `{${Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}:${canonical(v)}`).join(',')}}`;
}

export function runThemeSpec() {
  const results: Array<{ name: string; ok: boolean; detail: string }> = [];
  const check = (name: string, ok: boolean) => results.push({ name, ok, detail: '' });
  for (const theme of BUILT_INS) {
    const imported = importThemes(exportThemes([theme])).themes[0];
    check(`${theme.name}: all presentation controls survive JSON export/import`, canonical(imported) === canonical(theme));
  }
  const sample = structuredClone(builtIn('liquid')!);
  sample.scene = { enabled: false, intensity: .23, speed: .17 };
  sample.stage.parallax = .91;
  sample.form.elevationDrawer = 4;
  sample.type.voice = 'Georgia, serif';
  const restored = importThemes(exportThemes([sample])).themes[0];
  check('edited scene remains disabled with exact intensity/speed after round trip', JSON.stringify(restored.scene) === JSON.stringify(sample.scene));
  check('depth, elevation and voice edits remain exact after round trip', restored.stage.parallax === .91 && restored.form.elevationDrawer === 4 && restored.type.voice === sample.type.voice);
  sample.scene = { enabled: true, intensity: 900, speed: -10 };
  const bounded = importThemes(exportThemes([sample])).themes[0];
  check('imported scene resource knobs are bounded', bounded.scene?.intensity === 1 && bounded.scene?.speed === 0);
  const legacy = structuredClone(builtIn('referenz')!);
  const old = importThemes(exportThemes([legacy])).themes[0];
  check('older reference themes do not acquire an ambient scene', old.scene === undefined);
  check('malformed theme JSON returns a visible problem', importThemes('{broken').problems.length > 0);

  // Rendered environments (G1-UI-12). The registry is data; the images are a
  // separate module so this node bundle never touches binary assets.
  const ids = SCENE_ENVIRONMENTS.map((e) => e.id);
  check('scene environments have unique ids, names and notes',
    new Set(ids).size === ids.length && SCENE_ENVIRONMENTS.every((e) => e.name.trim() && e.note.trim() && (e.base === 'light' || e.base === 'dark')));
  check('every registered environment carries render provenance from the Blender manifest',
    SCENE_ENVIRONMENTS.every((e) => {
      const p = sceneEnvironmentProvenance(e.id);
      return !!p && p.source.startsWith('docs/design/blender-scenes/') && /^[0-9a-f]{64}$/.test(p.sourceSha256) && /^[0-9a-f]{64}$/.test(p.image.sha256) && p.image.width > 0;
    }));
  check('the manifest names no environment the registry lacks',
    Object.keys(sceneEnvironmentProvenance()).every((id) => isSceneEnvironmentId(id)));
  // G1-UI-13: the room collection binds one look to each rendered room; every
  // older look, including the rejected Liquid Glass reference, stays roomless.
  const roomLooks = BUILT_INS.filter((t) => t.origin === 'rooms-2026-09-05');
  const otherLooks = BUILT_INS.filter((t) => t.origin !== 'rooms-2026-09-05');
  check('looks outside the room collection keep no environment',
    otherLooks.length >= 10 && otherLooks.every((t) => t.scene?.environment === undefined));
  check('each rendered room has exactly one look, with the sculpture off and a matching base',
    roomLooks.length === SCENE_ENVIRONMENTS.length &&
    new Set(roomLooks.map((t) => t.scene?.environment)).size === SCENE_ENVIRONMENTS.length &&
    roomLooks.every((t) => t.scene?.enabled === false && isSceneEnvironmentId(t.scene?.environment) &&
      SCENE_ENVIRONMENTS.find((e) => e.id === t.scene?.environment)?.base === t.base));
  check('new installations open in Graphite Atelier; Liquid Glass remains selectable',
    DEFAULT_THEME_ID === 'room-graphite' && builtIn(DEFAULT_THEME_ID)?.scene?.environment === 'graphite' && !!builtIn('liquid'));
  const roomed = structuredClone(builtIn('liquid')!);
  roomed.scene = { enabled: false, intensity: .4, speed: 0, environment: 'graphite' };
  const roomedBack = importThemes(exportThemes([roomed])).themes[0];
  check('a chosen environment survives JSON export/import with the sculpture off', JSON.stringify(roomedBack.scene) === JSON.stringify(roomed.scene));
  const bogus = JSON.parse(exportThemes([roomed])) as { themes: Array<{ scene: Record<string, unknown> }> };
  bogus.themes[0].scene.environment = 'lava-lamp';
  const bogusBack = importThemes(JSON.stringify(bogus));
  check('an unknown environment is dropped and reported, never rendered',
    bogusBack.themes[0].scene?.environment === undefined && bogusBack.problems.some((p) => p.id === roomed.id));
  check('isSceneEnvironmentId refuses non-strings and unknown ids',
    !isSceneEnvironmentId(undefined) && !isSceneEnvironmentId(3) && !isSceneEnvironmentId('none') && isSceneEnvironmentId('techno-forest'));
  return results;
}
