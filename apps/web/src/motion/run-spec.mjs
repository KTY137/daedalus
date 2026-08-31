/**
 * Compatibility runner for the canonical shared/UI motion spec.
 *
 * apps/web has no test framework and the brief forbids adding a dependency
 * without an argument for it. There is a better option: esbuild is already
 * installed as a vite dependency, and the canonical motion spec is deliberately pure —
 * no React, no DOM, no framer-motion runtime (its framer-motion import is
 * type-only and erases). So the spec bundles to a few kB of plain ESM and
 * runs in node directly.
 *
 *   node src/motion/run-spec.mjs        (or: npm run test:motion)
 *
 * Exit code 1 on any failure.
 */
import { build } from 'esbuild';
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Source-level guards. The pure spec proves the vocabulary is correct; these
 * prove the components actually use it. Both failure modes they catch are the
 * realistic ones — not "the token is wrong" but "someone added a primitive
 * next to the system instead of inside it".
 *
 *   G1  Any component that drives framer-motion must consult the
 *       reduced-motion preference. This is the rule that rots first: the
 *       global `prefers-reduced-motion` CSS in styles.css has no effect on a
 *       JS animation, so a component that forgets the hook silently ignores
 *       the user's setting and nothing anywhere reports it.
 *   G2  No component may write a duration, easing or spring literal. A magic
 *       number in a component is how a design system dies.
 *
 * Scope: every shipping app/feature surface plus the shared glass and theme
 * owners. Walked recursively so a new feature directory is covered without
 * editing this file again. The implementation vocabulary itself lives only in
 * `src/shared/ui/motion`; this old command path remains because package.json
 * and existing CI invoke it directly.
 */
const SCAN_ROOTS = [
  path.resolve(here, '..', 'app'),
  path.resolve(here, '..', 'features'),
  path.resolve(here, '..', 'shared', 'ui', 'glass'),
  path.resolve(here, '..', 'shared', 'ui', 'theme')
];

async function walkTsx(dir) {
  const out = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out; // a root that does not exist yet is not a failure
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walkTsx(full)));
    else if (entry.isFile() && entry.name.endsWith('.tsx')) out.push(full);
  }
  return out;
}

async function sourceGuards() {
  const results = [];

  const MAGIC = [
    [/\bduration\s*:/, 'duration: literal'],
    [/cubic-bezier\s*\(/, 'cubic-bezier() literal'],
    [/\bstiffness\s*:/, 'stiffness: literal'],
    [/\bdamping\s*:/, 'damping: literal'],
    [/\bease\s*:\s*\[/, 'inline easing array'],
    [/\bstaggerChildren\s*:/, 'staggerChildren: literal']
  ];

  const files = (await Promise.all(SCAN_ROOTS.map(walkTsx))).flat().sort();

  for (const full of files) {
    const label = path.relative(path.resolve(here, '..'), full).split(path.sep).join('/');
    const source = await readFile(full, 'utf8');
    const drivesMotion = /from 'framer-motion'/.test(source);

    if (drivesMotion) {
      results.push({
        name: `G1 ${label}: consults the reduced-motion preference`,
        ok: source.includes('useReducedMotionPref'),
        detail: source.includes('useReducedMotionPref') ? '' : 'imports framer-motion but never asks'
      });
    }

    const found = MAGIC.filter(([re]) => re.test(source)).map(([, magicLabel]) => magicLabel);
    results.push({
      name: `G2 ${label}: no motion literal outside src/shared/ui/motion`,
      ok: found.length === 0,
      detail: found.join(', ')
    });
  }

  return results;
}
const workdir = await mkdtemp(path.join(tmpdir(), 'ikarus-motion-spec-'));
const outfile = path.join(workdir, 'spec.mjs');

try {
  await build({
    entryPoints: [path.resolve(here, '..', 'shared', 'ui', 'motion', 'motion.spec.ts')],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node18',
    outfile,
    logLevel: 'warning'
  });

  const { runMotionSpec } = await import(pathToFileURL(outfile).href);
  const results = [...runMotionSpec(), ...(await sourceGuards())];

  let failed = 0;
  for (const result of results) {
    if (result.ok) {
      console.log(`  ok    ${result.name}${result.detail ? `  (${result.detail})` : ''}`);
    } else {
      failed += 1;
      console.log(`  FAIL  ${result.name}${result.detail ? `  (${result.detail})` : ''}`);
    }
  }

  console.log(`\nmotion spec: ${results.length - failed}/${results.length} passed`);
  process.exitCode = failed > 0 ? 1 : 0;
} finally {
  await rm(workdir, { recursive: true, force: true });
}
