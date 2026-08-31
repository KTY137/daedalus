/**
 * Executable G1-UI-01 contract without a new test dependency.
 *
 * esbuild is already a Vite dependency. The runner bundles the pure resolver
 * spec into a temporary directory, then audits only Git-tracked frontend
 * sources for the single-root and lazy-compatibility ownership rules.
 */
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
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
  check('the classic implementation stays lazy', owner.includes("lazy(() => import('../App'))"));
  check('the classic stylesheet cannot enter through a static App import', !/from ['"]\.\.\/App['"]/.test(owner));

  const appImporters = [...sources.entries()]
    .filter(([, source]) => /(?:import\s*\(|from\s*)['"]\.\.\/App['"]/.test(source))
    .map(([file]) => file);
  check(
    'only the shared SurfaceRoot can reach the classic implementation',
    appImporters.length === 1 && appImporters[0] === 'apps/web/src/app/SurfaceRoot.tsx',
    appImporters.join(', ')
  );

  return results;
}

const workdir = await mkdtemp(path.join(tmpdir(), 'daedalus-app-spec-'));
const outfile = path.join(workdir, 'surface-spec.mjs');

try {
  await build({
    entryPoints: [path.join(here, 'surface.spec.ts')],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node18',
    outfile,
    logLevel: 'warning'
  });

  const { runSurfaceSpec } = await import(pathToFileURL(outfile).href);
  const results = [...runSurfaceSpec(), ...(await architectureSpec())];
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
