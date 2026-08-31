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
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..', '..');

function trackedFrontendSources() {
  const output = execFileSync('git', ['ls-files', '-z', '--', 'apps/web/src'], {
    cwd: repoRoot,
    encoding: 'utf8'
  });
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
  check('SurfaceRoot owns the Cockpit import', owner.includes("from '../cockpit/Cockpit'"));
  check('SurfaceRoot owns the provider composition', owner.includes("from '../theme/ThemeProvider'"));
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

const workdir = await mkdtemp(path.join(tmpdir(), 'daedalus-app-spec-'));
const surfaceOutfile = path.join(workdir, 'surface.js');
const systemOutfile = path.join(workdir, 'system.js');

try {
  await build({
    entryPoints: {
      surface: path.join(here, 'surface.spec.ts'),
      system: path.join(here, '..', 'features', 'system', 'system.spec.ts')
    },
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node18',
    outdir: workdir,
    logLevel: 'warning'
  });

  const { runSurfaceSpec } = await import(pathToFileURL(surfaceOutfile).href);
  const { runSystemCapabilitiesSpec } = await import(pathToFileURL(systemOutfile).href);
  const results = [
    ...runSurfaceSpec(),
    ...(await runSystemCapabilitiesSpec()),
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
