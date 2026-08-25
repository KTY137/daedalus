/**
 * Read the design of a real, shipped interface — from the page itself.
 *
 * Not "what does this look like to me" but what the CSS actually says: the
 * font stacks in use and at what sizes, the colours that carry text and
 * surfaces, the radii, the shadows, where a backdrop filter is really applied
 * and how strong, and the spacing values that repeat.
 *
 *   node tools/reference.mjs https://linear.app https://vercel.com …
 *
 * Output is one block per site on stdout. Nothing is downloaded or copied;
 * this reads computed styles in a headless browser and prints numbers.
 */
import { chromium } from '@playwright/test';

const log = (line) => process.stdout.write(String(line).concat('\n'));

function collect() {
  const seen = document.querySelectorAll('body *');
  const fonts = new Map();
  const sizes = new Map();
  const weights = new Map();
  const colors = new Map();
  const backgrounds = new Map();
  const radii = new Map();
  const shadows = new Map();
  const blurs = new Map();
  const gaps = new Map();
  const tracking = new Map();

  const bump = (m, k) => {
    if (!k) return;
    m.set(k, (m.get(k) ?? 0) + 1);
  };

  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2 && r.top < innerHeight * 3;
  };

  seen.forEach((el) => {
    if (!visible(el)) return;
    const cs = getComputedStyle(el);
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1);

    if (hasText) {
      bump(fonts, cs.fontFamily.split(',')[0].replace(/["']/g, '').trim());
      bump(sizes, Math.round(parseFloat(cs.fontSize) * 10) / 10);
      bump(weights, cs.fontWeight);
      bump(colors, cs.color);
      if (cs.letterSpacing && cs.letterSpacing !== 'normal') bump(tracking, cs.letterSpacing);
    }
    if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') bump(backgrounds, cs.backgroundColor);
    if (cs.borderTopLeftRadius && cs.borderTopLeftRadius !== '0px') bump(radii, cs.borderTopLeftRadius);
    if (cs.boxShadow && cs.boxShadow !== 'none') bump(shadows, cs.boxShadow.slice(0, 80));
    if (cs.backdropFilter && cs.backdropFilter !== 'none') bump(blurs, cs.backdropFilter);
    if (cs.gap && cs.gap !== 'normal' && cs.gap !== '0px') bump(gaps, cs.gap);
  });

  const top = (m, n = 8) =>
    [...m.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([k, v]) => `${k} (${v})`);

  const body = getComputedStyle(document.body);
  return {
    title: document.title,
    bodyBg: body.backgroundColor,
    bodyColor: body.color,
    bodyFont: body.fontFamily,
    fonts: top(fonts),
    sizes: top(sizes, 12),
    weights: top(weights),
    colors: top(colors, 10),
    backgrounds: top(backgrounds, 10),
    radii: top(radii),
    shadows: top(shadows, 4),
    blurs: top(blurs, 4),
    gaps: top(gaps),
    tracking: top(tracking, 6)
  };
}

const urls = process.argv.slice(2);
if (!urls.length) {
  process.stderr.write('usage: node tools/reference.mjs <url> [url…]\n');
  process.exit(2);
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  // A plain desktop UA: several of these sites serve a different shell to an
  // unknown client, and measuring that shell would measure nothing.
  userAgent:
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
});

for (const url of urls) {
  const page = await context.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForTimeout(2500);
    const r = await page.evaluate(collect);
    log(`\n================ ${url}`);
    log(`title      ${r.title}`);
    log(`body       bg ${r.bodyBg} · text ${r.bodyColor}`);
    log(`body font  ${r.bodyFont}`);
    log(`fonts      ${r.fonts.join('  ')}`);
    log(`sizes      ${r.sizes.join('  ')}`);
    log(`weights    ${r.weights.join('  ')}`);
    log(`tracking   ${r.tracking.join('  ')}`);
    log(`text       ${r.colors.join('  ')}`);
    log(`surfaces   ${r.backgrounds.join('  ')}`);
    log(`radii      ${r.radii.join('  ')}`);
    log(`shadows    ${r.shadows.join(' | ')}`);
    log(`backdrop   ${r.blurs.join('  ') || 'none used'}`);
    log(`gaps       ${r.gaps.join('  ')}`);
  } catch (e) {
    log(`\n================ ${url}`);
    log(`FAILED     ${String(e).split('\n')[0]}`);
  } finally {
    await page.close();
  }
}

await browser.close();
