/**
 * "Does the cockpit load?" -- against the real server, in a real browser.
 *
 * The existing `web.serves_and_terminates` check proves the SERVER answers.
 * That is a different claim: a server can answer 200 on every route while the
 * bundle throws on module evaluation and the user gets a white screen. These
 * assertions are the ones that separate the two.
 */
import { expect, test } from '@playwright/test';
import { collect, dockSpaces, openApp, settle, visibleText } from './_app';

test('the app loads against the real server and talks to it', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);

  await expect(page).toHaveTitle(/Daedalus/i);

  // A 200 with an empty #root IS the white screen. `openApp` already proved a
  // <nav> mounted; this states the property in the form the failure takes.
  const mounted = await page.locator('#root > *').count();
  expect(mounted, '#root is empty -- the document loaded but React rendered nothing').toBeGreaterThan(0);

  // A screenful of nothing passes every structural check ever written.
  const text = await visibleText(page);
  expect(text.trim().length, `the cockpit rendered almost no text at all: ${JSON.stringify(text.slice(0, 200))}`).toBeGreaterThan(80);

  const spaces = await dockSpaces(page);
  expect(
    spaces.length,
    `the dock rendered fewer than three navigable spaces: ${JSON.stringify(spaces)}`,
  ).toBeGreaterThanOrEqual(3);

  // IT IS NOT A STATIC PAGE. The cockpit must reach the API of the server that
  // served it. Without this, a hand-written index.html would pass everything
  // above.
  await settle(page, seen);
  const ok = seen.api.filter((r) => r.status === 200);
  expect(
    ok.length,
    `the app completed no successful /api/ request -- it rendered a shell, not a cockpit. saw: ${JSON.stringify(seen.api.slice(0, 12))}`,
  ).toBeGreaterThan(0);

  expect(
    seen.pageErrors,
    `uncaught exception(s) while loading the cockpit: ${seen.pageErrors.join(' || ')}`,
  ).toEqual([]);
});

test('the cockpit names the project it is showing', async ({ page }) => {
  // A cockpit that cannot say WHICH repo it is describing is a cockpit whose
  // every other number is unattributable. The project picker carries an
  // accessible name, so this survives a restyle.
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const picker = page.getByLabel('Project', { exact: true });
  await expect(picker, 'no project selector rendered -- nothing identifies the repo under inspection').toBeVisible();
  const chosen = await picker.inputValue();
  expect(chosen.trim(), 'the project selector rendered with nothing selected').not.toEqual('');
});
