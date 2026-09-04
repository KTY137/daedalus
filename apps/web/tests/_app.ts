/**
 * Shared moves for the cockpit acceptance specs.
 *
 * SELECTOR POLICY. Everything here addresses the app the way a screen reader
 * (and therefore a user) does -- roles and accessible names -- never CSS
 * classes. `apps/web/src/**` is under active redesign by other hands; a suite
 * pinned to `.railcard .h .t` would go red on a restyle that broke nothing, and
 * a suite that goes red for cosmetic reasons is one nobody reads. Where a
 * future surface has no accessible name yet, the helper prefers a
 * `data-testid` if one appears and falls back to text, so wiring one in is an
 * upgrade rather than a breaking change.
 */
import { expect, type Page } from '@playwright/test';

/**
 * What `daedalus/web_api.py::_send_static` serves INSTEAD of the app when
 * `apps/web/dist` has not been built. It comes back 200 with a <h1>, so every
 * "the server answered" check passes on it. Reading it as "the app loaded" is
 * exactly the green lie this suite exists to prevent.
 */
export const NOT_BUILT = /Run npm install/i;

/**
 * THE APP'S OWN CLOSED VOCABULARY, from `apps/web/src/views/health.ts`.
 *
 * Exactly one of the five states may be read as a pass. Anchoring the specs to
 * these words rather than to prose means a restyle cannot break them and a
 * rewording cannot quietly weaken them -- if someone adds a sixth state that
 * renders as green, `PROVEN_STATE` stops being the only pass and the specs say
 * so.
 */
export const PROVEN_STATE = 'working';
export const UNPROVEN_STATES = ['present', 'degraded', 'absent', 'unknown'] as const;
export const ALL_STATES = [PROVEN_STATE, ...UNPROVEN_STATES];

/** Vocabulary a human would recognise as "something here is not established".
 *  Includes the four un-proven state marks, because those ARE this app's way
 *  of saying it. */
export const TROUBLE =
  /did not respond|not answering|not responding|not running|not reachable|nothing .{0,30}read|failed|failure|error|unavailable|offline|could not|cannot|unable|timed out|refused|no response|incomplete|degraded|withheld|suppressed|problem|snag|PRESENT\?|DEGRADED|ABSENT|UNKNOWN!/i;

/** Placeholder text that must never be the whole of a user-facing message. */
export const GIBBERISH = /^\s*(undefined|null|\[object Object\]|NaN)\s*$/i;

export interface Signals {
  pageErrors: string[];
  consoleErrors: string[];
  api: { path: string; status: number }[];
}

/** Attach listeners BEFORE navigating; a page error during load is the one
 *  that turns the cockpit into a white screen. */
export function collect(page: Page): Signals {
  const s: Signals = { pageErrors: [], consoleErrors: [], api: [] };
  page.on('pageerror', (e) => s.pageErrors.push(String(e?.message || e)));
  page.on('console', (m) => {
    if (m.type() === 'error') s.consoleErrors.push(m.text());
  });
  page.on('response', (r) => {
    try {
      const u = new URL(r.url());
      if (u.pathname.startsWith('/api/')) s.api.push({ path: u.pathname, status: r.status() });
    } catch {
      /* opaque url */
    }
  });
  return s;
}

/**
 * Load the CLASSIC surface and prove it actually mounted.
 *
 * `/` now opens the themed cockpit (`src/cockpit/`), which has its own suite in
 * `cockpit.spec.ts`. Everything in this helper — the dock, the three spaces,
 * the health badges — belongs to the surface that is still served at
 * `?surface=classic`, and that surface still owns the contracts these specs
 * pin. Pointing them at the new shell instead would have turned a real suite
 * into a red one for a reason that is not a defect.
 */
export const CLASSIC = '/?surface=classic';

export async function openApp(page: Page): Promise<void> {
  const res = await page.goto(CLASSIC, { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);

  const html = await res!.text();
  expect(
    html,
    'the server served its "not built" placeholder instead of the app -- ' +
      'apps/web/dist is missing or empty, so nothing below would be testing the cockpit',
  ).not.toMatch(NOT_BUILT);

  // The dock is the only <nav> in the shell (apps/web/src/components/glass/Dock.tsx).
  // If React never mounted, this is where we find out.
  await expect(
    page.getByRole('navigation'),
    'the app never mounted: no navigation landmark rendered inside #root',
  ).toBeVisible({ timeout: 20_000 });
}

/** Accessible names of every navigable space in the dock, in dock order. */
export async function dockSpaces(page: Page): Promise<string[]> {
  const buttons = page.getByRole('navigation').getByRole('button');
  const n = await buttons.count();
  const names: string[] = [];
  for (let i = 0; i < n; i++) {
    const b = buttons.nth(i);
    const label = (await b.getAttribute('aria-label')) || (await b.innerText());
    const name = (label || '').trim();
    if (name) names.push(name);
  }
  return names;
}

/** Open a space by its accessible name and return the headings it revealed.
 *
 *  The spaces render INLINE in the main column (a sheet overlay is used only
 *  for the secondary tool panels), so "what opened" is answered by the visible
 *  headings, not by a dialog role. */
export async function openSpace(page: Page, name: string): Promise<string> {
  await page.getByRole('navigation').getByRole('button', { name, exact: true }).click();
  await page.waitForTimeout(700); // the space swap is animated
  const heads = await page.getByRole('heading', { level: 2 }).allInnerTexts();
  return heads.map((h) => h.trim()).filter(Boolean).join(' | ');
}

/**
 * Everything a human can CURRENTLY read on screen.
 *
 * NOT `body.innerText`. The closed tool sheet stays mounted with
 * `aria-hidden="true"` and is hidden with opacity/transform rather than
 * `display:none`, so `innerText` happily returns a screenful of text nobody
 * can see. A spec that searched that would "find" content on a surface the
 * user never opened -- an assertion passing on invisible markup is the same
 * class of lie as a skipped test reported as green.
 */
export async function visibleText(page: Page): Promise<string> {
  return page.evaluate(() => {
    const out: string[] = [];
    const walk = (node: Node): void => {
      if (node.nodeType === Node.TEXT_NODE) {
        const t = (node.textContent || '').trim();
        if (t) out.push(t);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const el = node as HTMLElement;
      if (el.getAttribute('aria-hidden') === 'true') return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) return;
      node.childNodes.forEach(walk);
    };
    document.body.childNodes.forEach(walk);
    return out.join('\n');
  });
}

/** Every health badge on screen as [state, mark]. `data-state` carries the
 *  closed vocabulary verbatim, which is a far more stable hook than a colour
 *  or a class name. */
export async function healthStates(page: Page): Promise<Array<[string, string]>> {
  return page.locator('[data-state]').evaluateAll((els) =>
    els.map((e) => [e.getAttribute('data-state') || '', (e as HTMLElement).innerText.trim()] as [string, string]),
  );
}

/** A same-origin fetch issued BY THE LOADED PAGE.
 *
 *  Not a curl from Python: this goes out under the app's own origin, through
 *  the browser's fetch stack, and therefore proves the thing the cockpit
 *  depends on rather than the thing a shell script can reach. */
export async function apiJson<T = any>(
  page: Page,
  path: string,
): Promise<{ status: number; body: T }> {
  return page.evaluate(async (p) => {
    const r = await fetch(p, { headers: { 'Content-Type': 'application/json' } });
    let body: any;
    try {
      body = await r.json();
    } catch (e) {
      body = { ok: false, error: `response was not JSON: ${String(e)}` };
    }
    return { status: r.status, body };
  }, path);
}

/**
 * Let the initial API fan-out become observably quiet.
 *
 * `networkidle` is deliberately NOT used here: the cockpit owns a long-lived
 * `/api/events` stream, so a healthy app may never reach Playwright's global
 * network-idle state. Waiting for it turned every `settle()` call into a fixed
 * 30-second tax and eventually made the acceptance suite hit its 600-second
 * outer timeout without identifying a product failure. Instead, when response
 * signals are available, require at least one API response and then a short
 * quiet window in the response count. This measures the thing this helper
 * actually cares about — the initial request burst — without treating a live
 * event stream as a hang.
 */
export async function settle(page: Page, signals?: Signals): Promise<void> {
  if (signals) {
    await expect
      .poll(() => signals.api.length, {
        message: 'the app issued no /api/ requests at all',
        timeout: 30_000,
      })
      .toBeGreaterThan(0);

    let lastCount = signals.api.length;
    let stablePolls = 0;
    await expect
      .poll(
        () => {
          const count = signals.api.length;
          if (count === lastCount) {
            stablePolls += 1;
          } else {
            lastCount = count;
            stablePolls = 0;
          }
          return stablePolls;
        },
        {
          message: 'the initial /api/ response burst never became quiet',
          timeout: 6_000,
          intervals: [250],
        },
      )
      .toBeGreaterThanOrEqual(3);
  }
  await page.waitForTimeout(500);
}

/** One 500 from a named endpoint, shaped exactly like the server's own error
 *  envelope so the app takes the normal failure path rather than a parse
 *  crash. */
export function failJson(reason: string) {
  return {
    status: 500,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({ ok: false, error: `acceptance fault injection: ${reason}` }),
  };
}

/** Lines present in `after` that were not present in `before`. */
export function newLines(before: string, after: string): string[] {
  const had = new Set(
    before
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean),
  );
  return after
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !had.has(l));
}
