// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * "A DEGRADED SOURCE IS VISIBLE, not silently rendered as 'no work'."
 *
 * This is the property the whole harness exists for. In this repo a task queue
 * silently dropped tasks while 1756 unit tests were green; the picker grew
 * `degraded_sources` and a distinct exit code so that "a source failed" could
 * never again read as "there is nothing to do". The same failure is available
 * one layer up: a panel that renders an empty list when its endpoint 500s tells
 * the operator the fleet is idle.
 *
 * BOTH HALVES AGAIN. The healthy run establishes what the screen says when
 * nothing is wrong; the faulted run must say something MORE. Asserting only
 * that a faulted page contains the word "error" would pass on a page that
 * always contains it.
 */
import { expect, test } from '@playwright/test';
import { GIBBERISH, TROUBLE, collect, dockSpaces, failJson, newLines, openApp, openSpace, settle, visibleText } from './_app';

/** Phrasings that mean "there is nothing here" -- fine on their own, a lie
 *  when the reason is actually "we could not look". */
const READS_AS_EMPTY = /no runtimes|none detected|nothing (yet|here|to)|no results|empty|0 of 0/i;

test('a source that FAILED is visible, and does not read as "nothing here"', async ({ page }) => {
  // --- control: what a healthy cockpit says -------------------------------
  const healthySignals = collect(page);
  await openApp(page);
  await settle(page, healthySignals);
  const healthy = await visibleText(page);
  expect(
    healthy,
    'the HEALTHY cockpit already reads as broken, so this spec could not tell a fault from the baseline:\n' + healthy.slice(0, 400),
  ).not.toMatch(/did not respond/i);

  // --- fault: one endpoint 500s -------------------------------------------
  await page.route('**/api/runtimes/status*', (r) => r.fulfill(failJson('runtimes status is down')));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('navigation')).toBeVisible({ timeout: 20_000 });
  await settle(page);
  const faulted = await visibleText(page);

  // 1. The screen CHANGED. A cockpit that looks identical with a dead source
  //    is one whose display is not a function of its inputs.
  expect(
    faulted,
    'a data source returned 500 and the cockpit rendered EXACTLY the same screen -- the failure is invisible',
  ).not.toEqual(healthy);

  // 2. What changed says something went wrong, in words.
  const added = newLines(healthy, faulted);
  expect(
    added.join(' | '),
    `a data source returned 500 but nothing on screen names a failure. new text was: ${JSON.stringify(added)}`,
  ).toMatch(TROUBLE);

  // 3. THE CORE CLAIM. If any panel now reads as empty, the page must ALSO
  //    carry the reason -- otherwise "could not look" is being displayed as
  //    "nothing to see".
  if (READS_AS_EMPTY.test(faulted)) {
    expect(
      faulted,
      'a panel reads as EMPTY while its source was failing, and the page carries no failure notice: ' +
        '"we could not look" is being rendered as "there is nothing there"',
    ).toMatch(TROUBLE);
  }

  // 4. The cockpit is still operable. Degradation must not be an outage.
  const spaces = await dockSpaces(page);
  expect(spaces.length, 'the dock disappeared when one source failed').toBeGreaterThanOrEqual(3);
  const somewhere = spaces.find((n) => /code map|structure|network|mission|queue|feed/i.test(n));
  if (somewhere) {
    const heading = await openSpace(page, somewhere);
    expect(heading, `the cockpit became unnavigable after one source failed (${somewhere} opened nothing)`).not.toEqual('');
  }
});

test('the failure notice is written for a human, not printed from a variable', async ({ page }) => {
  await page.route('**/api/runtimes/status*', (r) => r.fulfill(failJson('runtimes status is down')));
  const seen = collect(page);
  await openApp(page);
  await settle(page);

  const text = await visibleText(page);
  const trouble = text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => TROUBLE.test(l));

  expect(trouble.length, `no line on screen reports the failed source at all:\n${text.slice(0, 600)}`).toBeGreaterThan(0);
  for (const line of trouble) {
    expect(line, `a failure was reported as raw placeholder text: ${JSON.stringify(line)}`).not.toMatch(GIBBERISH);
  }
  expect(
    trouble.join(' '),
    `the failure notice is too short to act on: ${JSON.stringify(trouble)}`,
  ).toMatch(/.{20,}/);
  expect(seen.pageErrors, `the cockpit threw while handling a failed source: ${seen.pageErrors.join(' || ')}`).toEqual([]);
});
