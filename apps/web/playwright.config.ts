/**
 * Browser-level acceptance for the Daedalus cockpit.
 *
 * WHY THIS EXISTS. `tools/system_check.py` already proves the web server
 * STARTS, ANSWERS and DIES. It does not prove a human could operate the thing:
 * a server that answers 200 on every route is indistinguishable, from the
 * outside, from one whose app renders a white screen. Three fully green suites
 * sat over three live escapes in one day in this repo. This config drives the
 * BUILT bundle in a real browser against the REAL server, so "it works" means
 * something a person could have observed.
 *
 * THERE IS DELIBERATELY NO `webServer` BLOCK. Playwright's webServer helper
 * would start the API for us and usually stop it -- "usually" is not the
 * contract this repo needs. This machine has leaked orphaned servers before, so
 * the process lifetime is owned by `tools/gui_check.py`, which starts it on a
 * free LOOPBACK port and kills it in a `finally` on every path including
 * failure. The specs are handed a URL and never spawn anything.
 *
 * Run it through the harness, never by hand:
 *
 *     python tools/gui_check.py          # this suite, with a real server
 *     python tools/system_check.py       # the whole acceptance run, incl. this
 */
import os from 'node:os';
import path from 'node:path';
import { defineConfig } from '@playwright/test';

const baseURL = process.env.DAEDALUS_GUI_BASE_URL;
if (!baseURL) {
  throw new Error(
    'DAEDALUS_GUI_BASE_URL is not set.\n\n' +
      'These specs drive the REAL Daedalus server and deliberately do not start ' +
      'one -- the guaranteed kill lives in tools/gui_check.py, not here.\n\n' +
      '    python tools/gui_check.py\n',
  );
}

// Loopback, and only loopback. daedalus/web_api.py refuses a non-loopback bind
// without an explicit opt-in plus a token; an acceptance harness that pointed a
// browser at anything else would be testing a configuration nobody should run.
if (!/^http:\/\/(127\.0\.0\.1|\[::1\]):\d+$/.test(baseURL)) {
  throw new Error(
    `DAEDALUS_GUI_BASE_URL must be a numeric loopback address, got ${JSON.stringify(baseURL)}. ` +
      "'localhost' is a NAME and is refused on purpose -- a name that resolves to " +
      'loopback when it is checked can resolve elsewhere when it is connected.',
  );
}

// Never into the repo. A default that writes reports and failure screenshots
// into the working tree turns every run into an untracked-file diff, and this
// harness runs inside a disposable clone whose cleanliness is itself a checked
// property (see Sandbox.worktree_fingerprint).
const tmp = os.tmpdir();

export default defineConfig({
  testDir: './tests',
  outputDir: process.env.DAEDALUS_GUI_OUTDIR || path.join(tmp, 'daedalus-gui-artifacts'),

  // DETERMINISM IS A PROPERTY, NOT A PREFERENCE.
  //   workers: 1  -- one server, one browser, no interleaved route interception
  //   retries: 0  -- a test that passes on the second try has not passed; a
  //                  green built out of retries is the failure mode this whole
  //                  harness exists to prevent.
  workers: 1,
  retries: 0,
  fullyParallel: false,
  forbidOnly: true,

  // The cockpit suite deliberately exercises a cold structure scan with a
  // 240s wait and a project-switch scan with a 300s wait. A 60s GLOBAL test
  // timeout made those assertions unreachable: Playwright killed the test
  // before the product-specific wait could produce a verdict. Keep this finite
  // and above the largest declared per-test wait; tools/gui_check.py still owns
  // the outer suite budget through DAEDALUS_GUI_SUITE_TIMEOUT_S.
  timeout: 360_000,
  expect: { timeout: 15_000 },

  reporter: [
    ['list'],
    ['json', { outputFile: process.env.DAEDALUS_GUI_REPORT || path.join(tmp, 'daedalus-gui-report.json') }],
  ],

  use: {
    baseURL,
    // Plain chromium, NOT devices['Desktop Chrome'] -- that device pins
    // `channel: 'chrome'`, which requires a full Google Chrome install and
    // would turn "the browser is missing" into a confusing launch error
    // instead of the INCOMPLETE that gui_check.py reports.
    browserName: 'chromium',
    headless: true,
    // > 1180: apps/web/src/styles.css hides the live rail under 900px and
    // reflows under 1180px. A viewport that hides the health surface would
    // make the health spec pass by not looking at it.
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'off',
    video: 'off',
    screenshot: 'only-on-failure',
  },
});