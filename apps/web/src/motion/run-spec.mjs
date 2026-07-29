/**
 * Runner for motion.spec.ts.
 *
 * apps/web has no test framework and the brief forbids adding a dependency
 * without an argument for it. There is a better option: esbuild is already
 * installed as a vite dependency, and motion.spec.ts is deliberately pure —
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
 *   G1  Any glass component that drives framer-motion must consult the
 *       reduced-motion preference. This is the rule that rots first: the
 *       global `prefers-reduced-motion` CSS in styles.css has no effect on a
 *       JS animation, so a component that forgets the hook silently ignores
 *       the user's setting and nothing anywhere reports it.
 *   G2  No component may write a duration, easing or spring literal. A magic
 *       number in a component is how a design system dies.
 */
async function sourceGuards() {
  const results = [];
  const dir = path.resolve(here, '..', 'components', 'glass');
  const files = (await readdir(dir)).filter((f) => f.endsWith('.tsx'));

  const MAGIC = [
    [/\bduration\s*:/, 'duration: literal'],
    [/cubic-bezier\s*\(/, 'cubic-bezier() literal'],
    [/\bstiffness\s*:/, 'stiffness: literal'],
    [/\bdamping\s*:/, 'damping: literal'],
    [/\bease\s*:\s*\[/, 'inline easing array'],
    [/\bstaggerChildren\s*:/, 'staggerChildren: literal']
  ];

  for (const file of files.sort()) {
    const source = await readFile(path.join(dir, file), 'utf8');
    const drivesMotion = /from 'framer-motion'/.test(source);

    if (drivesMotion) {
      results.push({
        name: `G1 ${file}: consults the reduced-motion preference`,
        ok: source.includes('useReducedMotionPref'),
        detail: source.includes('useReducedMotionPref') ? '' : 'imports framer-motion but never asks'
      });
    }

    const found = MAGIC.filter(([re]) => re.test(source)).map(([, label]) => label);
    results.push({
      name: `G2 ${file}: no motion literal outside src/motion`,
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
    entryPoints: [path.join(here, 'motion.spec.ts')],
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
