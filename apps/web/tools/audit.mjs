/**
 * Measure the cockpit against the floor, in every theme, at every width.
 *
 * Four rounds of design review died on the same four things, so they are
 * measured here rather than asserted in a commit message:
 *
 *   contrast   every rendered text run against what is actually behind it,
 *              composited through translucent panels — a glass surface over a
 *              lit stage is where a "checked" palette stops being readable.
 *   targets    every interactive element, INCLUDING the SVG ones. The previous
 *              round reported "0 targets under 44px" while excluding the graph,
 *              which is where all the small targets were.
 *   type       the smallest rendered font size, and where it is.
 *   overflow   the page must never scroll sideways.
 *
 *   node tools/audit.mjs --base http://127.0.0.1:8765 [--widths 1440,1280,900]
 *
 * Exit code 1 when anything is below the floor. The report names each offender
 * so the fix is a line, not a hunt.
 */
import { chromium } from '@playwright/test';

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const BASE = arg('base', 'http://127.0.0.1:8765');
const THEMES = arg('themes', 'kammer,werkstatt,sternkarte,depesche,nachtfenster,leitstand').split(',');
const WIDTHS = arg('widths', '1440,1280,900').split(',').map(Number);
const MIN_TARGET = Number(arg('target', 44));
const MIN_FONT = Number(arg('font', 11));

const log = (line) => process.stdout.write(String(line).concat('\n'));

/** Runs in the page. Everything here must be self-contained. */
function measure({ minTarget, minFont }) {
  const luminance = (r, g, b) => {
    const f = (c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  /**
   * Parse a CSS colour. HEX IS NOT OPTIONAL: the theme tokens are written as
   * `#0d0805`, and the first version of this parser only understood `rgb()`.
   * It therefore failed to read the room tone, fell back to white, and
   * reported near-white text on a near-black stage as 1.17:1 — a measuring
   * instrument failing toward "everything is broken" is no better than one
   * failing toward "everything is fine".
   */
  const parse = (css) => {
    const v = (css || '').trim();
    if (!v || v === 'none' || v === 'transparent') return null;
    const m = /rgba?\(([^)]+)\)/.exec(v);
    if (m) {
      const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    const hex = /^#([0-9a-f]{3,8})$/i.exec(v);
    if (hex) {
      let h = hex[1];
      if (h.length === 3 || h.length === 4) h = h.split('').map((c) => c + c).join('');
      const n = parseInt(h.slice(0, 6), 16);
      const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a };
    }
    return null;
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1
  });

  /**
   * The colour actually behind an element: walk up compositing every
   * translucent ancestor onto the one below. Reading only the nearest opaque
   * ancestor is what lets a 0.11-alpha panel over a lit stage pass a contrast
   * check it visibly fails.
   */
  const backdrop = (el) => {
    const stack = [];
    let node = el;
    while (node && node !== document.documentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c && c.a > 0) stack.push(c);
      node = node.parentElement;
    }
    const root = parse(getComputedStyle(document.documentElement).backgroundColor);
    const body = parse(getComputedStyle(document.body).backgroundColor);
    // The cockpit paints a gradient on .cockpit; sample its mid tone via the
    // room token, which is what that gradient is made of.
    const roomVar = getComputedStyle(document.documentElement).getPropertyValue('--room2').trim();
    let base = parse(roomVar) || (body && body.a === 1 ? body : null) || (root && root.a === 1 ? root : null) || { r: 255, g: 255, b: 255, a: 1 };
    for (let i = stack.length - 1; i >= 0; i -= 1) base = over(stack[i], base);
    return base;
  };

  const ratio = (a, b) => {
    const la = luminance(a.r, a.g, a.b);
    const lb = luminance(b.r, b.g, b.b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };

  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
    if (el.closest('[aria-hidden="true"]')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };

  const textOffenders = [];
  const smallest = { size: 999, where: '' };

  document.querySelectorAll('body *').forEach((el) => {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1);
    if (!own || !visible(el)) return;
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize) || 0;
    const label = `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''}`;
    if (size && size < smallest.size) {
      smallest.size = size;
      smallest.where = label;
    }
    // SVG text carries its colour in `fill`, HTML in `color`.
    const fgRaw = el instanceof SVGElement ? cs.fill : cs.color;
    const fg = parse(fgRaw);
    if (!fg) return;
    const bg = el instanceof SVGElement ? backdrop(el.ownerSVGElement || el) : backdrop(el);
    const composited = fg.a < 1 ? over(fg, bg) : fg;
    const r = ratio(composited, bg);
    const bold = Number(cs.fontWeight) >= 700;
    const floor = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (r < floor) {
      textOffenders.push({
        where: label,
        text: (el.textContent || '').trim().slice(0, 40),
        size: Math.round(size * 10) / 10,
        ratio: Math.round(r * 100) / 100,
        floor
      });
    }
  });

  const targetOffenders = [];
  const excused = [];
  const SELECTOR = 'a[href], button, input, select, textarea, [role="button"], [role="tab"], [role="radio"], [tabindex]:not([tabindex="-1"])';
  document.querySelectorAll(SELECTOR).forEach((el) => {
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width >= minTarget && r.height >= minTarget) return;
    const row = {
      where: `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : ''}`,
      label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30),
      w: Math.round(r.width),
      h: Math.round(r.height),
      svg: el instanceof SVGElement
    };
    /**
     * ONE documented exception, and it is printed every run.
     *
     * A graph node cannot have a 44px target: the ring relaxes to about 32px
     * of spacing, so 44px circles would swallow their neighbours and the
     * wrong module would open. Its hit circle is 36px, and the equivalent
     * larger path is real — ctrl+K lists every module as a 44px row, and the
     * arrow keys walk the same ring. That is an exception with a reason, not
     * the previous round's "0 targets under 44px" measured by leaving SVG out
     * of the query.
     */
    if (el.closest('.stage-node')) excused.push(row);
    else targetOffenders.push(row);
  });

  return {
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    smallestFont: smallest,
    tooSmallFont: smallest.size < minFont,
    contrast: textOffenders.slice(0, 25),
    contrastCount: textOffenders.length,
    targets: targetOffenders.slice(0, 25),
    targetCount: targetOffenders.length,
    excusedCount: excused.length,
    excusedSmallest: excused.reduce((m, e) => Math.min(m, e.w, e.h), 999)
  };
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: WIDTHS[0], height: 900 } });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.stage-node', { timeout: 180_000 });

  let failures = 0;
  for (const id of THEMES) {
    await page.evaluate((t) => localStorage.setItem('daedalus-theme-id', t), id);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.stage-node', { timeout: 180_000 });
      await page.waitForTimeout(500);

      const r = await page.evaluate(measure, { minTarget: MIN_TARGET, minFont: MIN_FONT });
      const bad = r.overflowX > 1 || r.contrastCount > 0 || r.targetCount > 0 || r.tooSmallFont;
      if (bad) failures += 1;
      log(`\n${id} @ ${width}px  ${bad ? 'FAIL' : 'ok'}`);
      log(`  overflow-x ${r.overflowX}px · smallest text ${r.smallestFont.size}px (${r.smallestFont.where})`);
      if (r.contrastCount) {
        log(`  contrast: ${r.contrastCount} below floor`);
        r.contrast.forEach((c) => log(`    ${c.ratio}:1 (needs ${c.floor}) ${c.size}px  ${c.where}  "${c.text}"`));
      }
      if (r.targetCount) {
        log(`  targets under ${MIN_TARGET}px: ${r.targetCount}`);
        r.targets.forEach((t) => log(`    ${t.w}x${t.h}  ${t.where}${t.svg ? ' [svg]' : ''}  "${t.label}"`));
      }
      if (r.excusedCount) {
        log(
          `  excused: ${r.excusedCount} graph nodes below ${MIN_TARGET}px (smallest side ${r.excusedSmallest}px) — ` +
            'a 44px target would swallow its neighbour; ctrl+K and the arrow keys are the larger equivalent path'
        );
      }
    }
  }

  await browser.close();
  log(`\n${failures} theme/width combinations below the floor`);
  process.exit(failures ? 1 : 0);
}

main().catch((e) => {
  process.stderr.write(`${e.stack || e}\n`);
  process.exit(2);
});
