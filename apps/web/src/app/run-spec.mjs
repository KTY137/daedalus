/**
 * Executable G1-UI-01 contract without a new test dependency.
 *
 * esbuild is already a Vite dependency. The runner bundles the pure resolver
 * specs into a temporary directory, then audits only Git-tracked frontend
 * sources for the single-root and single-implementation ownership rules.
 */
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..', '..');

function trackedFrontendSources() {
  const output = execFileSync(
    'git',
    ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'apps/web/src'],
    {
      cwd: repoRoot,
      encoding: 'utf8'
    }
  );
  return output
    .split('\0')
    .filter((entry) => /\.(?:ts|tsx)$/.test(entry))
    .filter((entry) => existsSync(path.join(repoRoot, entry)))
    .sort();
}

async function architectureSpec() {
  const results = [];
  const check = (name, ok, detail = '') => results.push({ name, ok, detail });
  const files = trackedFrontendSources();
  const sources = new Map(
    await Promise.all(
      files.map(async (file) => [file, await readFile(path.join(repoRoot, file), 'utf8')])
    )
  );

  const expectedImportShims = new Map([
    ['apps/web/src/api.ts', "export * from './shared/api';"],
    ['apps/web/src/types.ts', "export * from './shared/contracts';"],
    ['apps/web/src/cockpit/Cockpit.tsx', "export { Cockpit } from '../app/Cockpit';"],
    ['apps/web/src/cockpit/Conversation.tsx', "export * from '../features/conversation/Conversation';"],
    ['apps/web/src/cockpit/Decision.tsx', "export * from '../features/mission/Decision';"],
    ['apps/web/src/cockpit/IdeWorkspace.tsx', "export * from '../features/ide/IdeWorkspace';"],
    ['apps/web/src/cockpit/ProjectDialog.tsx', "export * from '../features/projects/ProjectDialog';"],
    ['apps/web/src/components/GlassSurface.tsx', "export { default } from '../shared/ui/glass/GlassSurface';\nexport type { GlassSurfaceProps } from '../shared/ui/glass/GlassSurface';"],
    ['apps/web/src/motion/index.ts', "export * from '../shared/ui/motion';"],
    ['apps/web/src/motion/tokens.ts', "export * from '../shared/ui/motion/tokens';"],
    ['apps/web/src/motion/useMotion.ts', "export * from '../shared/ui/motion/useMotion';"],
    ['apps/web/src/theme/ThemeProvider.tsx', "export * from '../shared/ui/theme/ThemeProvider';"],
    ['apps/web/src/theme/presets.ts', "export * from '../shared/ui/theme/presets';"]
  ]);

  const outsideHierarchy = files.filter((file) => {
    if (file === 'apps/web/src/main.tsx') return false;
    if (/^apps\/web\/src\/(?:app|features|shared)\//.test(file)) return false;
    return !expectedImportShims.has(file);
  });
  check(
    'tracked TypeScript implementation lives under app, features or shared',
    outsideHierarchy.length === 0,
    outsideHierarchy.join(', ')
  );

  // Line endings are a checkout property, not a shim's content: a Windows
  // worktree with autocrlf carries CRLF and the two-line GlassSurface shim
  // would otherwise fail on its own carriage return.
  const changedShims = [...expectedImportShims].filter(
    ([file, expected]) => (sources.get(file) || '').replace(/\r\n/g, '\n').trim() !== expected
  );
  check(
    'reviewed legacy TypeScript paths are import-only compatibility shims',
    changedShims.length === 0,
    changedShims.map(([file]) => file).join(', ')
  );

  const hierarchyRegistry = JSON.parse(
    await readFile(path.join(repoRoot, 'apps/web/src/app/hierarchy-shims.json'), 'utf8')
  );
  const registeredPaths = hierarchyRegistry.entries.flatMap((entry) => entry.paths).sort();
  const expectedRegisteredPaths = [
    ...expectedImportShims.keys(),
    'apps/web/src/components/GlassSurface.css',
    'apps/web/src/motion/run-spec.mjs'
  ].sort();
  check(
    'every retained hierarchy shim is registered exactly once',
    JSON.stringify(registeredPaths) === JSON.stringify(expectedRegisteredPaths),
    `registered=${registeredPaths.length} expected=${expectedRegisteredPaths.length}`
  );
  const glassCssShim = await readFile(
    path.join(repoRoot, 'apps/web/src/components/GlassSurface.css'),
    'utf8'
  );
  check(
    'the retained GlassSurface stylesheet path is import-only',
    glassCssShim.trim() === "@import '../shared/ui/glass/GlassSurface.css';"
  );
  const motionCommandAdapter = await readFile(
    path.join(repoRoot, 'apps/web/src/motion/run-spec.mjs'),
    'utf8'
  );
  check(
    'the unchanged motion command delegates to the shared/UI spec owner',
    motionCommandAdapter.includes("'shared', 'ui', 'motion', 'motion.spec.ts'")
  );
  check(
    'every registered hierarchy shim has evidence and removal criteria',
    hierarchyRegistry.entries.every(
      (entry) => entry.reason.length > 40 && entry.removal_criteria.length > 60
    )
  );

  const productionBundle = await build({
    absWorkingDir: repoRoot,
    entryPoints: ['apps/web/src/main.tsx'],
    alias: { '@': path.join(repoRoot, 'apps/web/src') },
    bundle: true,
    format: 'esm',
    platform: 'browser',
    outdir: path.join(tmpdir(), 'daedalus-hierarchy-spec'),
    write: false,
    metafile: true,
    logLevel: 'warning'
  });
  const productionInputs = Object.keys(productionBundle.metafile.inputs)
    .map((input) => path.relative(repoRoot, path.isAbsolute(input) ? input : path.resolve(repoRoot, input)).split(path.sep).join('/'))
    .filter((input) => input.startsWith('apps/web/src/'))
    .sort();
  const nonHierarchicalInputs = productionInputs.filter(
    (input) => input !== 'apps/web/src/main.tsx' && !/^apps\/web\/src\/(?:app|features|shared)\//.test(input)
  );
  check(
    'the shipping esbuild graph reaches only app, feature and shared owners',
    nonHierarchicalInputs.length === 0,
    `inputs=${productionInputs.length}${nonHierarchicalInputs.length ? ` offenders=${nonHierarchicalInputs.join(',')}` : ''}`
  );

  const rootCalls = [];
  for (const [file, source] of sources) {
    for (const match of source.matchAll(/\b(?:createRoot|hydrateRoot|ReactDOM\.render)\s*\(/g)) {
      rootCalls.push(`${file}:${source.slice(0, match.index).split('\n').length}`);
    }
  }
  check(
    'exactly one React root is created by the app bootstrap owner',
    rootCalls.length === 1 && rootCalls[0].startsWith('apps/web/src/app/bootstrap.tsx:'),
    rootCalls.join(', ')
  );

  const main = sources.get('apps/web/src/main.tsx') || '';
  check(
    'main is a thin facade over bootstrapApp',
    /^import \{ bootstrapApp \} from '\.\/app\/bootstrap';\s+bootstrapApp\(document\.getElementById\('root'\)!?, location\.search\);\s*$/s.test(main),
    main.replace(/\s+/g, ' ').trim()
  );

  const owner = sources.get('apps/web/src/app/SurfaceRoot.tsx') || '';
  check('SurfaceRoot owns the canonical Cockpit import', owner.includes("from './Cockpit'"));
  check('SurfaceRoot owns the shared theme-provider composition', owner.includes("from '@/shared/ui/theme/ThemeProvider'"));
  check('SurfaceRoot has no lazy or conditional application implementation', !/\blazy\b|\bSuspense\b|import\(['"]\.\.\/App['"]\)/.test(owner));

  const appImporters = [...sources.entries()]
    .filter(([, source]) => /(?:import\s*\(|from\s*)['"]\.\.\/App['"]/.test(source))
    .map(([file]) => file);
  check(
    'no production source can reach a second App implementation',
    appImporters.length === 0,
    appImporters.join(', ')
  );
  check('the separate App implementation is retired', !sources.has('apps/web/src/App.tsx'));

  const appShellOwners = [...sources.entries()]
    .filter(([, source]) => source.includes('app-shell'))
    .map(([file]) => file);
  check('the retired app-shell runtime string is absent from tracked production sources', appShellOwners.length === 0, appShellOwners.join(', '));

  const featureApi = sources.get('apps/web/src/features/system/api.ts') || '';
  for (const contract of ['getDashboard', 'getControlPlane', 'getClaudeBootstrap', 'getProviderStatus']) {
    check(`the Cockpit system feature owns the ${contract} port`, featureApi.includes(contract));
  }

  return results;
}

// Inside the web root's node_modules cache rather than the OS temp dir: with
// packages external, Node resolves react and react-dom/server relative to the
// bundle, and the temp dir has no node_modules above it. Ignored by Git.
const cacheRoot = path.join(repoRoot, 'apps', 'web', 'node_modules', '.cache');
await mkdir(cacheRoot, { recursive: true });
const workdir = await mkdtemp(path.join(cacheRoot, 'daedalus-app-spec-'));
const surfaceOutfile = path.join(workdir, 'surface.js');
const systemOutfile = path.join(workdir, 'system.js');
const conversationOutfile = path.join(workdir, 'conversation.js');
const missionOutfile = path.join(workdir, 'mission.js');
const acceleratorOutfile = path.join(workdir, 'accelerators.js');

try {
  await build({
    entryPoints: {
      surface: path.join(here, 'surface.spec.ts'),
      system: path.join(here, '..', 'features', 'system', 'system.spec.ts'),
      conversation: path.join(here, '..', 'features', 'conversation', 'conversation.spec.ts'),
      mission: path.join(here, '..', 'features', 'mission', 'mission.spec.ts'),
      accelerators: path.join(here, '..', 'features', 'system', 'accelerators.spec.ts')
    },
    bundle: true,
    absWorkingDir: repoRoot,
    alias: { '@': path.join(repoRoot, 'apps/web/src') },
    format: 'esm',
    platform: 'node',
    target: 'node18',
    // Node resolves packages itself: the conversation spec renders through
    // react-dom/server, whose CommonJS build requires node builtins that an
    // ESM bundle cannot carry. First-party sources are still bundled.
    packages: 'external',
    outdir: workdir,
    logLevel: 'warning'
  });

  const { runSurfaceSpec } = await import(pathToFileURL(surfaceOutfile).href);
  const { runSystemCapabilitiesSpec } = await import(pathToFileURL(systemOutfile).href);
  const { runConversationSpec } = await import(pathToFileURL(conversationOutfile).href);
  const { runMissionSpec } = await import(pathToFileURL(missionOutfile).href);
  const { runAcceleratorSpec } = await import(pathToFileURL(acceleratorOutfile).href);
  const results = [
    ...runSurfaceSpec(),
    ...(await runSystemCapabilitiesSpec()),
    ...runConversationSpec(),
    ...runMissionSpec(),
    ...runAcceleratorSpec(),
    ...(await architectureSpec())
  ];
  let failed = 0;
  for (const result of results) {
    if (result.ok) {
      console.log(`  ok    ${result.name}${result.detail ? `  (${result.detail})` : ''}`);
    } else {
      failed += 1;
      console.log(`  FAIL  ${result.name}${result.detail ? `  (${result.detail})` : ''}`);
    }
  }
  console.log(`\napp bootstrap spec: ${results.length - failed}/${results.length} passed`);
  process.exitCode = failed > 0 ? 1 : 0;
} finally {
  await rm(workdir, { recursive: true, force: true });
}
