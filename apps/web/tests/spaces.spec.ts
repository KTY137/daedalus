// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * "Can a human get to the three spaces?"
 *
 * The IA is a trio: the conversation, a structural/graph view, and the work
 * feed. The dock labels for those will change -- a redesign is in flight -- so
 * each space is matched by a FAMILY of names rather than a literal, and the
 * failure message prints the dock it actually found. That is the difference
 * between a spec that catches a broken nav and one that catches a rename.
 */
import { expect, test } from '@playwright/test';
import { collect, dockSpaces, openApp, openSpace, settle } from './_app';

// Matched by FAMILY, and resolved in dock order -- the three primary spaces
// lead the dock, ahead of the secondary tool panels, so `.find()` lands on the
// space rather than on a tool that happens to share a word.
const SPACES: Array<{ space: string; match: RegExp }> = [
  { space: 'conversation', match: /ikarus|chat|conversation|ask/i },
  { space: 'structure / graph', match: /graph|code map|structure|network|architecture|topology/i },
  { space: 'work / knowledge', match: /knowledge|wiki|memory|mission|queue|feed|inbox|draft/i },
];

test('all three spaces are present in the dock', async ({ page }) => {
  await openApp(page);
  const found = await dockSpaces(page);

  const missing = SPACES.filter((s) => !found.some((n) => s.match.test(n))).map((s) => s.space);
  expect(
    missing,
    `the cockpit offers no way to reach: ${missing.join(', ')}. The dock exposes: ${JSON.stringify(found)}`,
  ).toEqual([]);
});

test('opening a space actually changes the surface', async ({ page }) => {
  // A nav whose buttons all reveal the same thing passes every "the button
  // exists" test ever written. Only comparing two spaces catches it.
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const found = await dockSpaces(page);
  const graph = found.find((n) => SPACES[1].match.test(n));
  const work = found.find((n) => SPACES[2].match.test(n));
  expect(graph, `no structural space in the dock: ${JSON.stringify(found)}`).toBeTruthy();
  expect(work, `no work space in the dock: ${JSON.stringify(found)}`).toBeTruthy();

  const graphHeading = await openSpace(page, graph!);
  expect(graphHeading, `opening ${JSON.stringify(graph)} revealed no titled surface at all`).not.toEqual('');

  const workHeading = await openSpace(page, work!);
  expect(workHeading, `opening ${JSON.stringify(work)} revealed no titled surface at all`).not.toEqual('');

  expect(
    workHeading,
    `two different dock entries (${graph} / ${work}) revealed the SAME surface ` +
      `titled ${JSON.stringify(graphHeading)} -- the navigation is decorative`,
  ).not.toEqual(graphHeading);
});

test('the conversation space is reachable and can take input', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const found = await dockSpaces(page);
  const chat = found.find((n) => SPACES[0].match.test(n));
  expect(chat, `no conversation space in the dock: ${JSON.stringify(found)}`).toBeTruthy();

  // Go somewhere else first, so returning is a real transition and not the
  // initial state answering for us.
  const other = found.find((n) => SPACES[1].match.test(n));
  if (other) await openSpace(page, other);

  await page.getByRole('navigation').getByRole('button', { name: chat!, exact: true }).click();
  await expect(page.getByRole('dialog'), 'the overlay did not close when returning to the conversation').toHaveCount(0);

  const composer = page.getByLabel('Ask Ikarus');
  await expect(composer, 'the conversation space renders no composer -- there is no way to talk to the OS').toBeVisible();
  await expect(composer, 'the composer is present but disabled on a healthy load').toBeEnabled();

  // Typing is the cheapest proof the surface is live rather than a screenshot.
  await composer.fill('acceptance probe -- not sent');
  await expect(composer).toHaveValue('acceptance probe -- not sent');
});
