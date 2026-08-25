/**
 * Build the review page for a shot folder.
 *
 * Reads `manifest.json` — what was actually on screen for each shot — and
 * writes `index.html` beside it. Nothing here invents a caption: every line
 * under an image comes from the manifest, so a review page cannot describe a
 * screenshot that was never taken.
 *
 *   node tools/gallery.mjs ../../docs/design/prototypes/cockpit-<date>
 */
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const DIR = path.resolve(process.argv[2] || '.');
const TITLE = process.argv[3] || 'Daedalus — Cockpit';

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const manifest = JSON.parse(await readFile(path.join(DIR, 'manifest.json'), 'utf8'));

const byTheme = new Map();
for (const shot of manifest.shots) {
  const rows = byTheme.get(shot.themeId) || [];
  rows.push(shot);
  byTheme.set(shot.themeId, rows);
}

const PAGE_NAME = { karte: 'Karte', gespraech: 'Gespräch' };

const sections = [...byTheme.entries()]
  .map(([theme, shots]) => {
    const figures = shots
      .map((shot) => {
        const facts = [];
        if (shot.page === 'karte') {
          facts.push(`${shot.nodes} Knoten gezeichnet`);
          if (shot.focus) facts.push(`Mitte <code>${esc(shot.focus)}</code>`);
        } else {
          facts.push(`${esc(shot.pending || '0')} Entscheidung(en) offen`);
        }
        facts.push(`Kopf ${esc(shot.chrome)}`, `Gesprächsseite ${esc(shot.chat)}`);
        return `  <figure>
    <img src="${esc(shot.file)}" alt="${esc(theme)} — ${esc(PAGE_NAME[shot.page] || shot.page)}" loading="lazy">
    <figcaption>
      <b>${esc(PAGE_NAME[shot.page] || shot.page)}</b>
      <span>${facts.join(' · ')}</span>
      ${shot.counts ? `<span class="counts">${esc(shot.counts)}</span>` : ''}
    </figcaption>
  </figure>`;
      })
      .join('\n');
    return `<section>
  <h2>${esc(theme)}</h2>
${figures}
</section>`;
  })
  .join('\n');

const page = `<!doctype html>
<meta charset="utf-8">
<title>${esc(TITLE)}</title>
<style>
  :root {
    --bg:#141210; --panel:#1c1917; --ink:#f2ece3; --ink2:#b3a99b; --ink3:#8a8073;
    --line:#2e2925; --accent:#ffb85c;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    --mono:ui-monospace,"Cascadia Mono",Consolas,monospace;
  }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--ink); font-family:var(--sans); line-height:1.5; padding:48px 32px 96px; }
  header { max-width:72ch; margin:0 auto 56px; }
  h1 { font-size:30px; font-weight:600; letter-spacing:-0.01em; }
  .lede { color:var(--ink2); margin-top:12px; }
  .lede b { color:var(--accent); font-weight:600; }
  section { max-width:1500px; margin:0 auto 64px; }
  h2 { font-size:20px; font-weight:600; text-transform:capitalize; margin-bottom:16px; color:var(--ink); }
  figure { background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; margin-bottom:20px; }
  img { display:block; width:100%; height:auto; }
  figcaption { display:grid; gap:4px; padding:14px 18px 18px; border-top:1px solid var(--line); font-size:13px; color:var(--ink2); }
  figcaption b { color:var(--ink); font-size:15px; }
  figcaption .counts { color:var(--ink3); }
  code { font-family:var(--mono); font-size:0.92em; color:var(--ink); }
  footer { max-width:72ch; margin:56px auto 0; color:var(--ink3); font-size:13px; }
</style>
<header>
  <h1>${esc(TITLE)}</h1>
  <p class="lede">
    Keine Entwürfe. Jedes Bild ist ein <b>Screenshot der laufenden Anwendung</b>,
    aus dem gebauten Bundle gegen die lokale API. Karte und Gespräch sind zwei
    Seiten; die sechs Entwürfe der Gallery-Runde sind sechs <b>Themes</b> derselben
    Oberfläche und alle im Theme-Studio bearbeitbar.
  </p>
</header>
${sections}
<footer>
  ${manifest.shots.length} Aufnahmen, ${byTheme.size} Themes, Fenster ${manifest.viewport.width}×${manifest.viewport.height}.
  Aufgenommen mit <code>apps/web/tools/shoot.mjs</code> gegen <code>${esc(manifest.base)}</code>;
  was auf jedem Bild zu sehen war, steht in <code>manifest.json</code>.
  Konsolenfehler: ${manifest.consoleErrors?.length ? esc(manifest.consoleErrors.length) : 'keine'}.
  Hintergrund und offene Punkte: <code>README.md</code>.
</footer>
`;

await writeFile(path.join(DIR, 'index.html'), page, 'utf8');
process.stdout.write(`index.html written: ${manifest.shots.length} shots, ${byTheme.size} themes\n`);
