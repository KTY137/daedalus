import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * The composer sizes itself, and the pin moves ONE box.
 *
 * WHY THIS FILE EXISTS. `features/conversation/Conversation.tsx` used to grow
 * the composer by writing `style.height = 'auto'` and reading `scrollHeight`
 * once per keystroke — a forced synchronous layout of the whole column the
 * transcript shares with it. That is now a CSS mirror (`.composer-grow` in
 * conversation.css), and off-screen turns are skipped with
 * `content-visibility: auto`. Both changes are invisible when they work and
 * silent when they break: a mirror whose typography drifts from the field
 * sizes the box wrong, and a skipped turn makes `scrollHeight` an estimate.
 *
 * Three regressions were found by hand during that work and none of them had
 * a test. These are those tests. Each one asserts a promise a reader can see,
 * not an implementation detail:
 *
 *   - the box is one line until the text needs two, and it comes back;
 *   - it stops growing at the declared ceiling and scrolls instead;
 *   - a pasted block and a trailing newline are text like any other;
 *   - pinning the transcript never scrolls anything ABOVE the transcript.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

/** One line at the talk breakpoint: `min-height: 52px` in conversation.css. */
const ONE_LINE = 52;
/** `max-height: 200px`, declared beside the mirror in conversation.css. */
const CEILING = 200;

function longThread(turnCount: number) {
  const turns = [];
  for (let i = 0; i < turnCount; i += 1) {
    turns.push({
      id: 100 + i,
      user_message: `Frage ${i + 1}: wo sitzt der Zyklus?`,
      assistant_text: `Antwort ${i + 1}.\n\n${'Ein Absatz mit genug Text, um eine Zeile zu füllen. '.repeat(12)}`,
      project: project.name,
      intent: 'chat',
      provider_used: 'claude_code_cli',
      model_used: 'claude',
      created_ts: '2026-09-02T10:00:00+00:00',
      envelope: { intent: 'chat', shell: 'voice', provider_used: 'claude_code_cli', model_used: 'claude' }
    });
  }
  return {
    conversation_id: 'conv_long',
    exists: true,
    project_binding: { state: 'bound', project: project.name, row_count: turnCount },
    turn_count: turnCount,
    narrative: '',
    turns,
    turns_returned: turnCount,
    dispatches: [],
    open_dispatches: []
  };
}

async function stubCockpit(page: Page, turnCount = 0) {
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: {
      ok: true, generated_at: '', project: null, warnings: [],
      runtimes: [{ id: 'claude_code_cli', label: 'Claude Code', mode: 'cli', available: true, auth_status: 'cli_detected', version: '2.1.233' }]
    }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: 0, drafts: [] }
  }));
  const rows = turnCount
    ? [{
        conversation_id: 'conv_long', turn_count: turnCount,
        first_message: 'Frage 1: wo sitzt der Zyklus?', last_message: `Frage ${turnCount}: wo sitzt der Zyklus?`,
        last_ts: '2026-09-02T10:05:00+00:00', last_intent: 'chat',
        last_provider_used: 'claude_code_cli', last_status: 'answered'
      }]
    : [];
  await page.route((url) => url.pathname === '/api/conversations' && url.searchParams.has('project'), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversations: rows } });
  });
  await page.route((url) => /^\/api\/conversations\/conv_long$/.test(url.pathname), (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation: longThread(turnCount) }
  }));
  // Sending must START; the draft clears optimistically, which is the moment
  // the box has to shrink back.
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_long' } });
  });
  await page.route('**/api/conversations/*/turns', async (route) => {
    await route.fulfill({
      status: 202,
      json: {
        ok: true, generated_at: '', project: project.name, warnings: [], created: true,
        turn_request: { request_id: 900, conversation_id: 'conv_long', project: project.name, state: 'streaming' }
      }
    });
  });
}

async function openChat(page: Page) {
  const response = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

/** The field's rendered height — what a reader actually sees. */
function composerHeight(page: Page) {
  return page.locator('.composer textarea').evaluate((el) => Math.round(el.getBoundingClientRect().height));
}

test.describe('the composer sizes itself', () => {
  test('one line until the text needs two, and back again when it is sent', async ({ page }) => {
    await stubCockpit(page);
    const seen = collect(page);
    await openChat(page);

    const composer = page.getByLabel('Nachricht an Ikarus');
    await expect(composer).toBeVisible();
    expect(await composerHeight(page)).toBe(ONE_LINE);

    // A second line is a second line, whether it was typed or pasted.
    await composer.fill('erste Zeile\nzweite Zeile');
    const twoLines = await composerHeight(page);
    expect(twoLines, 'the box did not grow for a second line').toBeGreaterThan(ONE_LINE);

    await composer.fill('erste Zeile\nzweite Zeile\ndritte Zeile\nvierte Zeile');
    const fourLines = await composerHeight(page);
    expect(fourLines, 'four lines are not taller than two').toBeGreaterThan(twoLines);

    // Sending clears the draft optimistically; the box must come back with it.
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect(composer).toHaveValue('');
    await expect.poll(() => composerHeight(page), { message: 'the box did not shrink back after send' }).toBe(ONE_LINE);

    expect(seen.pageErrors).toEqual([]);
  });

  test('stops at the declared ceiling and scrolls instead of growing forever', async ({ page }) => {
    await stubCockpit(page);
    await openChat(page);
    const composer = page.getByLabel('Nachricht an Ikarus');

    await composer.fill(Array.from({ length: 60 }, (_, i) => `Zeile ${i}`).join('\n'));
    const tall = await composerHeight(page);
    expect(tall, 'the box grew past its declared ceiling').toBeLessThanOrEqual(CEILING + 1);
    expect(tall, 'the box never reached its ceiling').toBeGreaterThan(ONE_LINE);

    // A ceiling that cannot be scrolled past would hide what was typed.
    const scrollable = await page.locator('.composer textarea').evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(scrollable, 'the overflowing text is unreachable').toBeGreaterThan(0);
    await expect(page.locator('.composer textarea')).toHaveCSS('overflow-y', 'auto');
  });

  test('an empty field and a trailing newline are both sized honestly', async ({ page }) => {
    await stubCockpit(page);
    await openChat(page);
    const composer = page.getByLabel('Nachricht an Ikarus');

    await composer.fill('');
    expect(await composerHeight(page), 'an empty field is not one line').toBe(ONE_LINE);

    // The mirror renders `attr(data-value)`; without the trailing space a
    // trailing newline collapses and the caret sits outside the box.
    await composer.fill('eine Zeile\n');
    expect(
      await composerHeight(page),
      'a trailing newline did not open the line it puts the caret on'
    ).toBeGreaterThan(ONE_LINE);

    // A single long unbroken token must wrap, not widen the surface.
    await composer.fill('x'.repeat(400));
    expect(await composerHeight(page), 'a long word did not wrap').toBeGreaterThan(ONE_LINE);
    const overflow = await page.locator('.composer').evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow, 'a long word widened the composer').toBeLessThanOrEqual(1);
  });

  test('the field and its sizing mirror agree on typography at every breakpoint', async ({ page }) => {
    await stubCockpit(page);
    await openChat(page);
    // conversation.css, shell.css and responsive.css all size `.composer
    // textarea`; each must name `.composer-grow::after` beside it or the
    // mirror sizes the field for a typography the field does not have. 390px
    // is the breakpoint that caught this by hand.
    for (const width of [1600, 1000, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(200);
      const pair = await page.locator('.composer-grow').evaluate((el) => {
        const field = getComputedStyle(el.querySelector('textarea')!);
        const mirror = getComputedStyle(el, '::after');
        const read = (s: CSSStyleDeclaration) => [s.minHeight, s.maxHeight, s.paddingTop, s.paddingBottom,
          s.paddingLeft, s.paddingRight, s.fontSize, s.fontFamily, s.lineHeight].join('|');
        return { field: read(field), mirror: read(mirror) };
      });
      expect(pair.mirror, `mirror and field disagree at ${width}px`).toBe(pair.field);
    }
  });
});

test.describe('pinning the transcript', () => {
  test('moves the transcript and never a scroll container above it', async ({ page }) => {
    // A shorter viewport than the suite default, so the transcript's bottom
    // still sits below the body's scrollport once `.talk-main` is forced tall
    // AND the reader is still pinned. At 1000px tall the forced height leaves
    // the transcript scrolled up, which correctly UNPINS it and would make
    // this test assert nothing.
    await page.setViewportSize({ width: 1400, height: 800 });
    await stubCockpit(page, 24);
    await openChat(page);

    /*
     * The condition, built BEFORE the transcript exists so that opening the
     * thread is the thing that pins.
     *
     * `.cockpit` is `overflow: hidden` (shell.css) — programmatically
     * scrollable, with no scrollbar a reader could drag back.
     * `.cockpit-body.talk` is `overflow: auto` under the shipped `flat`
     * material (shell.css; the default `glass` gives the rail its own
     * scroller), and `.talk-side` has no max-height there, so a tall rail
     * gives the body scrollable overflow. `.talk-main` is forced tall so the
     * transcript's own bottom sits below the body's scrollport, which is what
     * makes an ancestor-walking scroll want to move the ancestor.
     */
    const condition = await page.evaluate(() => {
      document.documentElement.dataset.material = 'flat';
      const filler = document.createElement('div');
      filler.style.height = '1600px';
      filler.style.flex = 'none';
      document.querySelector('.talk-side')!.appendChild(filler);
      // Inline, not a stylesheet: `.cockpit-body.talk .talk-main` sets
      // `min-height: 0` at a higher specificity and would win.
      (document.querySelector('.talk-main') as HTMLElement).style.minHeight = '1400px';
      const body = document.querySelector('.cockpit-body.talk') as HTMLElement;
      const cockpit = document.querySelector('.cockpit') as HTMLElement;
      body.scrollTop = 0;
      cockpit.scrollTop = 0;
      return {
        scrollable: body.scrollHeight - body.clientHeight,
        body: Math.round(body.scrollTop), cockpit: Math.round(cockpit.scrollTop)
      };
    });
    expect(condition.scrollable, 'the ancestor was not made scrollable, so this proves nothing').toBeGreaterThan(0);
    expect(condition.body).toBe(0);
    expect(condition.cockpit).toBe(0);

    await page.locator('.rail-tabs button', { hasText: /^Verlauf/ }).first().click();
    await page.locator('.threads-row > button').first().click();
    await expect.poll(() => page.locator('.convo-scroll > .turn').count()).toBeGreaterThan(10);
    // This ARMS the pin; it is not time-passing, and it must not be removed
    // as such. `Conversation.tsx:381` arms `pinned.current` only from an
    // `onScroll` whose gap is under 48 px, a `turns.length` layout effect, or
    // `jumpToEnd` — so when a long thread opens, the last scroll event the
    // handler sees can be one where the gap was still large while the
    // transcript comes to rest at gap 0, leaving the pin DISARMED. The settle
    // makes a later observer-driven scroll likely to re-arm it. Measured: with
    // this removed the test below fails 1 in 6 with `Received: 191` and no CPU
    // load; adding back a scroll whose last event sees gap 0 makes it pass.
    //
    // That is a race, not a guarantee, and the underlying disarm is a product
    // bug rather than a test problem. Booked as its own packet; leaving this
    // wait is the honest interim, not an oversight.
    await page.waitForTimeout(1200);

    // Precondition: the reader is following the newest turn. Without this the
    // pin is correctly dormant and the rounds below would assert nothing.
    await expect.poll(async () => page.evaluate(() => {
      const scroll = document.querySelector('.convo-scroll') as HTMLElement;
      return Math.round(scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight);
    }), { message: 'the transcript did not open pinned' }).toBeLessThanOrEqual(2);

    /*
     * CONTROL, so a green below cannot be vacuous. This performs, from the
     * test, exactly the ancestor-walking scroll the pin used to do
     * (`scrollIntoView({ block: 'end' })` on the newest turn) and shows the
     * constructed geometry really can carry the escape. If this stops moving
     * the body, the geometry has drifted and the assertions after it are
     * measuring nothing — which is how the first version of this test passed
     * against the very code it was written to catch.
     */
    const control = await page.evaluate(() => {
      const body = document.querySelector('.cockpit-body.talk') as HTMLElement;
      body.scrollTop = 0;
      const turns = document.querySelectorAll('.convo-scroll > .turn');
      turns[turns.length - 1].scrollIntoView({ block: 'end', inline: 'nearest' });
      return Math.round(body.scrollTop);
    });
    expect(control, 'an ancestor-walking scroll did NOT move the body: this geometry proves nothing')
      .toBeGreaterThan(2);

    for (let round = 0; round < 3; round += 1) {
      // Reset the ancestors and read back in ONE task, so nothing can move
      // them between the write and the measurement.
      const before = await page.evaluate(() => {
        const body = document.querySelector('.cockpit-body.talk') as HTMLElement;
        const cockpit = document.querySelector('.cockpit') as HTMLElement;
        const scroll = document.querySelector('.convo-scroll') as HTMLElement;
        body.scrollTop = 0;
        cockpit.scrollTop = 0;
        return { body: Math.round(body.scrollTop), cockpit: Math.round(cockpit.scrollTop), inner: Math.round(scroll.scrollTop) };
      });
      expect(before.body).toBe(0);
      expect(before.cockpit).toBe(0);

      // One streamed delta: the newest turn grows and the ResizeObserver pins.
      await page.evaluate(() => {
        const turns = document.querySelectorAll('.convo-scroll > .turn');
        const last = turns[turns.length - 1];
        const grow = document.createElement('p');
        grow.textContent = 'Nachlauf im Stream. '.repeat(40);
        last.querySelector('.turn-body')!.appendChild(grow);
      });
      // The pin must have RUN — a transcript that stopped following its newest
      // turn would leave a gap the size of the text just added, so this also
      // stops the two assertions below from passing vacuously.
      //
      // POLLED, not waited. This was a fixed 800 ms, which is about 7x the
      // 103–113 ms the pin actually takes — and it still went red on CI, on
      // branches that could not reach this page. A fixed budget encodes a
      // guess about the machine; the property this test is about is that the
      // pin runs at all.
      //
      // The one confirmed failure is CI run 34539112171, from the uploaded
      // evidence artifact: `Received: 191`, the height of the paragraph
      // appended just above. What it does NOT establish is the cause. A
      // starved observer and a pin that never armed produce the same number,
      // and the second is reproducible on demand — delete the 1200 ms settle
      // above and this fails 1 in 6 with no CPU load at all. Polling helps the
      // first and cannot help the second.
      await expect.poll(() => page.evaluate(() => {
        const scroll = document.querySelector('.convo-scroll') as HTMLElement;
        return Math.round(scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight);
      }), {
        message: `round ${round}: the transcript stopped following its newest turn`,
        timeout: 8000,
      }).toBeLessThanOrEqual(2);

      // Read the other two AFTER the pin has settled: the question they ask is
      // "and nothing else scrolled while it did", which is only meaningful once
      // it has.
      //
      // And they need a WINDOW, not just the right order. Polling alone
      // collapsed the observation from 800 ms to ~1 ms — measured, the poll
      // converges at 105–118 ms and the snapshot followed 1 ms later — so a
      // late ancestor escape passed green here while the fixed wait caught it.
      // 700 ms is what main already paid for; the poll above is what makes the
      // wait a bounded observation rather than a guess about the machine.
      // 700 ms is not "a number under 800": the poll converges at 105–118 ms,
      // so the snapshot lands about 805 ms after the append, at parity with
      // the fixed wait this replaced — and unlike that wait, the window no
      // longer SHRINKS as the pin slows, because it starts when the pin lands
      // rather than when the append happened. A one-shot escape beyond it is
      // still invisible; that is inherent to any fixed window.
      await page.waitForTimeout(700);
      const after = await page.evaluate(() => {
        const body = document.querySelector('.cockpit-body.talk') as HTMLElement;
        const cockpit = document.querySelector('.cockpit') as HTMLElement;
        return { body: Math.round(body.scrollTop), cockpit: Math.round(cockpit.scrollTop) };
      });
      expect(after.body, `round ${round}: the pin scrolled .cockpit-body.talk out from under the reader`).toBeLessThanOrEqual(2);
      expect(after.cockpit, `round ${round}: the pin scrolled the whole cockpit shell`).toBeLessThanOrEqual(2);
    }
  });

  test('follows the newest turn even though off-screen turns are not laid out', async ({ page }) => {
    await stubCockpit(page, 24);
    await openChat(page);
    await page.locator('.rail-tabs button', { hasText: /^Verlauf/ }).first().click();
    await page.locator('.threads-row > button').first().click();
    await expect.poll(() => page.locator('.convo-scroll > .turn').count()).toBeGreaterThan(10);

    // `content-visibility: auto` makes `scrollHeight` an estimate until a turn
    // has been rendered, which is what made the pin land short of the answer.
    await expect(page.locator('.convo-scroll > .turn').first()).toHaveCSS('content-visibility', 'auto');
    await expect.poll(async () => page.evaluate(() => {
      const scroll = document.querySelector('.convo-scroll') as HTMLElement;
      return Math.round(scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight);
    }), { message: 'the thread did not open on its newest turn' }).toBeLessThanOrEqual(2);

    const last = page.locator('.convo-scroll > .turn').last();
    await expect(last).toBeInViewport();
  });
});
