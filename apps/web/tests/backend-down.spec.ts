// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * "What does the cockpit say when the backend is NOT running?"
 *
 * HOW THIS IS MODELLED, AND WHY. `daedalus web` is a single origin: it serves
 * both the bundle and the API. If that process is truly dead, the browser never
 * gets a document at all and there is no app to say anything -- the honest
 * answer there is the browser's own connection error, and the SECOND test below
 * pins exactly that. The interesting case, and the one an operator actually
 * hits, is the app already open (or served from cache / a dev proxy) while
 * every API call is refused. That is what the FIRST test injects, with a real
 * `connectionrefused` abort rather than a 500, because those are different
 * code paths in the client and only one of them is "the server is not there".
 */
import { expect, test } from '@playwright/test';
import { GIBBERISH, PROVEN_STATE, TROUBLE, collect, healthStates, openApp, settle, visibleText } from './_app';

test('with every API call refused, the cockpit still renders and explains itself', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (r) => r.abort('connectionrefused'));
  await openApp(page); // the document is still served; every fetch beneath it is not

  await settle(page);
  const text = await visibleText(page);

  // 1. Not a white screen. The shell must survive a dead backend.
  expect(await page.locator('#root > *').count(), 'the cockpit rendered nothing at all with the backend refused').toBeGreaterThan(0);
  expect(text.trim().length, `the cockpit is effectively blank with the backend refused: ${JSON.stringify(text.slice(0, 200))}`).toBeGreaterThan(40);

  // 2. It SAYS so. A cockpit that looks calm while nothing is reachable is
  //    worse than one that crashes -- the operator believes the numbers.
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  const trouble = lines.filter((l) => TROUBLE.test(l));
  expect(
    trouble.length,
    'every API call was refused and the cockpit says nothing about it. ' +
      `A silent shell reads as "the system is idle". Screen was:\n${text.slice(0, 800)}`,
  ).toBeGreaterThan(0);

  // 3. What it says is usable. "undefined" is not a message.
  for (const line of trouble) {
    expect(line, `the backend-down message is raw placeholder text: ${JSON.stringify(line)}`).not.toMatch(GIBBERISH);
  }

  // 4. It distinguishes "nothing answered" from "there is nothing". This is the
  //    same property the picker's exit code carries, at the surface a person
  //    actually reads.
  expect(
    text,
    'with the backend refused, the cockpit does not say that NOTHING WAS READ. ' +
      'An empty screen that does not say why reads as "the system is idle". ' +
      `Screen:\n${text.slice(0, 800)}`,
  ).toMatch(/not answering|not responding|nothing .{0,30}read|not the same as/i);

  // 5. It says what to do. A diagnosis with no remedy sends the operator to the
  //    source.
  expect(
    text,
    `the backend-down notice offers no way to fix it. Screen:\n${text.slice(0, 800)}`,
  ).toMatch(/start it|python -m|daedalus web|refresh/i);

  // 6. NOTHING is painted as proven while nothing answered.
  const proven = await healthStates(page);
  expect(
    proven.filter(([s]) => s === PROVEN_STATE),
    'a subsystem is rendered as PROVEN WORKING while every request was refused -- ' +
      'the cockpit is asserting something this run could not possibly have established',
  ).toEqual([]);

  // 7. It did not take the app down with it.
  expect(seen.pageErrors, `uncaught exception(s) with the backend refused: ${seen.pageErrors.join(' || ')}`).toEqual([]);
});

test('the suite itself notices a server that is not there', async ({ page }) => {
  // THE HARNESS'S OWN CONTROL. Every other spec in this suite asserts against a
  // page it navigated to. If navigation could quietly succeed against a dead
  // port -- from cache, from a service worker, from a stale tab -- the whole
  // suite could go green with nothing running. `gui_check.py` hands us a port
  // it allocated and immediately released; reaching it must fail.
  const dead = process.env.DAEDALUS_GUI_DEAD_URL;
  expect(
    dead,
    'DAEDALUS_GUI_DEAD_URL was not provided, so this suite cannot prove it would ' +
      'notice a dead server. Run it via tools/gui_check.py.',
  ).toBeTruthy();

  let failed = false;
  let detail = '';
  try {
    const res = await page.goto(dead!, { waitUntil: 'domcontentloaded', timeout: 15_000 });
    detail = `navigation SUCCEEDED with status ${res?.status()} and title ${JSON.stringify(await page.title())}`;
  } catch (e) {
    failed = true;
    detail = String((e as Error)?.message || e).split('\n')[0];
  }
  expect(failed, `${dead} answered when nothing should be listening there -- ${detail}`).toBe(true);
  expect(detail, `the failure was not a connection error: ${detail}`).toMatch(/ERR_CONNECTION|ECONNREFUSED|refused|net::/i);
});
