import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Every `var(--x)` a stylesheet reads must be a token something writes.
 *
 * The Genesis panels touched (owner report 2026-09-06, G1-UI-20) because
 * `genesis.css` spaced them with `--u5`, and `theme/apply.ts` never set a
 * `--u5`: an undefined custom property makes the whole declaration invalid
 * at computed-value time, so `gap` and `padding` silently became 0. Nothing
 * in tsc, the bundler or the browser console says a word. This spec does.
 *
 * Definitions come from two places: `--x:` declarations in any stylesheet
 * under src, and `'--x'` string literals in TS/TSX — the token array and
 * `setProperty` calls in `theme/apply.ts`, and inline `style={{ '--x': … }}`
 * on components (stage planes, studio previews). A `var(--x, fallback)` is
 * exempt: the author already answered the "what if it is missing" question.
 *
 * Plain JS on purpose: the web tsconfig has no node types, and this spec
 * needs the filesystem, like `architectureSpec` in run-spec.mjs.
 */

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function walk(dir, exts, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, exts, out);
    else if (exts.some((ext) => full.endsWith(ext))) out.push(full);
  }
  return out;
}

export function auditTokens(root = src) {
  const used = new Map();
  const defined = new Set();
  const css = walk(root, ['.css']);
  for (const file of css) {
    const text = readFileSync(file, 'utf8');
    const rel = path.relative(root, file).replaceAll('\\', '/');
    // var(--x) with no fallback; a comma after the name means a fallback exists
    for (const m of text.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)) {
      if (!used.has(m[1])) used.set(m[1], new Set());
      used.get(m[1]).add(rel);
    }
    for (const m of text.matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
  }
  const code = walk(root, ['.ts', '.tsx']);
  for (const file of code) {
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(/['"](--[\w-]+)['"]/g)) defined.add(m[1]);
  }
  return { used, defined, stylesheets: css.length, sources: code.length };
}

export function runTokenSpec() {
  const results = [];
  const { used, defined, stylesheets } = auditTokens();
  const missing = [...used.entries()].filter(([token]) => !defined.has(token));
  results.push({
    name: 'every var(--x) read by a stylesheet is defined somewhere',
    ok: missing.length === 0,
    detail: missing.length
      ? missing.map(([token, where]) => `${token} in ${[...where].join(', ')}`).join('; ')
      : `${used.size} tokens across ${stylesheets} stylesheets, all defined`
  });
  // The spacing scale is contiguous on purpose: a stylesheet may reach for
  // any half step between u1 and u8 without wondering whether it exists.
  for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
    results.push({ name: `spacing step --u${n} is a theme token`, ok: defined.has(`--u${n}`), detail: '' });
  }
  return results;
}
