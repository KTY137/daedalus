#!/usr/bin/env node
/**
 * probe.js — deterministic capture of a rendered surface.
 *
 * Writes a JSON description of every visible element (geometry + the computed
 * styles the linter cares about) plus page-level facts. It computes NO verdicts:
 * the rules live in `lint.py`, in Python, where they are testable with stdlib.
 * This file's only job is to make the capture honest and repeatable.
 *
 * Determinism is load-bearing. A screenshot diff or a metric delta is only
 * meaningful if two runs of the same page agree, so before capture we:
 *   - force prefers-reduced-motion and pause every animation/transition
 *   - freeze Date.now / performance.now and stub Math.random
 *   - wait for fonts to settle
 * Without this, a canvas that rotates and a clock that ticks make every run
 * differ and the whole lane reports noise as signal.
 *
 * Usage:
 *   node daedalus/gui/probe.js <url> <label> [outDir] [width] [height]
 *
 * Uses the Playwright already present in apps/web — no new dependency.
 */
const path = require('path');
const fs = require('fs');

const APPS_WEB = path.resolve(__dirname, '..', '..', 'apps', 'web');
let chromium;
try {
  ({ chromium } = require(path.join(APPS_WEB, 'node_modules', 'playwright-core')));
} catch (e) {
  try {
    ({ chromium } = require(path.join(APPS_WEB, 'node_modules', '@playwright', 'test')));
  } catch (e2) {
    console.error('Playwright not resolvable from apps/web/node_modules. ' +
                  'Install it there (npm i) rather than adding a global dependency.');
    process.exit(2);
  }
}

const FREEZE = () => {
  // Motion off. Two mechanisms, because a CSS animation and a JS rAF loop stop
  // for different reasons and the canvas projections use the second.
  const style = document.createElement('style');
  style.textContent = `*,*::before,*::after{
    animation-play-state:paused!important;
    animation-delay:0s!important;
    transition:none!important;
  }`;
  document.documentElement.appendChild(style);

  // Frozen clock + stubbed randomness, so seeded canvases land on one frame.
  const T0 = 1767052800000; // fixed instant, arbitrary but constant
  const _now = () => T0;
  try { Date.now = _now; } catch (e) {}
  try { performance.now = () => 0; } catch (e) {}
  try { Math.random = () => 0.42; } catch (e) {}
};

const EXTRACT = () => {
  const MAX = 2000;
  const NEUTRAL_SAT = 0.12;   // below this a colour counts as neutral, not accent

  const rgb = (s) => {
    const m = /rgba?\(([^)]+)\)/.exec(s || '');
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };

  // The effective background behind a text node: walk ancestors until something
  // is not transparent. Resolving this here rather than in the linter is the
  // whole reason contrast can be computed at all.
  const effectiveBg = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = rgb(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.92) return c;
      n = n.parentElement;
    }
    const c = rgb(getComputedStyle(document.documentElement).backgroundColor);
    return c && c.a > 0 ? c : { r: 255, g: 255, b: 255, a: 1 };
  };

  const sat = (c) => {
    if (!c) return 0;
    const mx = Math.max(c.r, c.g, c.b), mn = Math.min(c.r, c.g, c.b);
    return mx === 0 ? 0 : (mx - mn) / mx;
  };
  const hue = (c) => {
    const r = c.r / 255, g = c.g / 255, b = c.b / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    if (d === 0) return -1;
    let h;
    if (mx === r) h = ((g - b) / d) % 6;
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    return Math.round(((h * 60) + 360) % 360);
  };

  const INTERACTIVE = 'a,button,input,select,textarea,summary,[role="button"],[role="tab"],[tabindex]:not([tabindex="-1"])';
  const out = [];
  const all = document.querySelectorAll('body *');

  for (let i = 0; i < all.length && out.length < MAX; i++) {
    const el = all[i];
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom < 0 || r.top > innerHeight * 1.05) continue;   // above/below the fold
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.06) continue;

    const bw = ['borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth']
      .map((k) => parseFloat(cs[k]) || 0);
    const borderColors = ['borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor']
      .map((k) => rgb(cs[k]));
    const visibleBorderSides = bw.filter((w, idx) => w > 0.4 && borderColors[idx] && borderColors[idx].a > 0.06).length;

    // own text only — a wrapper must not be credited with its children's words
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.nodeValue;
    own = own.replace(/\s+/g, ' ').trim();

    const fg = rgb(cs.color);
    const rec = {
      tag: el.tagName.toLowerCase(),
      cls: (el.className && typeof el.className === 'string' ? el.className : '').slice(0, 60),
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      radius: cs.borderRadius,
      radiusPx: parseFloat(cs.borderTopLeftRadius) || 0,
      borderSides: visibleBorderSides,
      bg: cs.backgroundColor,
      bgAlpha: (rgb(cs.backgroundColor) || { a: 0 }).a,
      font: (cs.fontFamily || '').slice(0, 90),
      fontSize: parseFloat(cs.fontSize) || 0,
      fontWeight: cs.fontWeight,
      transform: cs.textTransform,
      letterSpacing: cs.letterSpacing,
      interactive: el.matches(INTERACTIVE),
      text: own.slice(0, 140),
      textLen: own.length,
      fgHue: fg ? hue(fg) : -1,
      fgSat: fg ? +sat(fg).toFixed(3) : 0,
      depth: (() => { let d = 0, n = el; while ((n = n.parentElement)) d++; return d; })()
    };

    if (own.length) {
      const bg = effectiveBg(el);
      rec.fg = [fg ? fg.r : 0, fg ? fg.g : 0, fg ? fg.b : 0];
      rec.bgEff = [bg.r, bg.g, bg.b];
    }
    // accent hue only from saturated non-text surfaces and saturated text
    const bgc = rgb(cs.backgroundColor);
    if (bgc && bgc.a > 0.3 && sat(bgc) > NEUTRAL_SAT) { rec.bgHue = hue(bgc); rec.bgSat = +sat(bgc).toFixed(3); }
    out.push(rec);
  }

  return {
    url: location.href,
    viewport: { w: innerWidth, h: innerHeight },
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    elementsSeen: all.length,
    elementsKept: out.length,
    truncated: out.length >= 2000,
    els: out
  };
};

(async () => {
  const [url, label, outDir = 'runs/gui', wArg = '1440', hArg = '900'] = process.argv.slice(2);
  if (!url || !label) {
    console.error('usage: node daedalus/gui/probe.js <url> <label> [outDir] [width] [height]');
    process.exit(2);
  }
  const width = parseInt(wArg, 10), height = parseInt(hArg, 10);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
    colorScheme: 'dark'
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + String(e.message).slice(0, 200)));

  await page.addInitScript(FREEZE);
  await page.goto(url, { waitUntil: 'load', timeout: 30000 });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.waitForTimeout(450);          // let one settled frame land
  await page.evaluate(FREEZE);             // re-apply after any late stylesheet

  const data = await page.evaluate(EXTRACT);
  data.label = label;
  data.consoleErrors = errors;
  data.probeVersion = 1;

  fs.mkdirSync(outDir, { recursive: true });
  const slug = `${label}-${width}x${height}`;
  fs.writeFileSync(path.join(outDir, slug + '.json'), JSON.stringify(data, null, 1));
  await page.screenshot({ path: path.join(outDir, slug + '.png') });
  await browser.close();

  console.log(`${slug}: kept ${data.elementsKept}/${data.elementsSeen} elements, ` +
              `${errors.length} console error(s)${data.truncated ? ', TRUNCATED' : ''}`);
})().catch((e) => { console.error(e); process.exit(1); });
