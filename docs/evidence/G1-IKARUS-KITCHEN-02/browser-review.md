# Shopping-list browser review — 2026-09-12

Scope: read-only runtime review with generated test items in fresh Chromium profiles. Native CDP fallback was used because agent-browser and Playwright packages were unavailable; existing Chromium was reused without installation. No original app/evidence files or pre-existing server were modified.

## Advertised preview

http://127.0.0.1:8765 returned HTTP 200 with an empty Directory listing for /, no app inputs or buttons. Screenshot: 01-existing-preview-port8765.png. Pre-existing python server PID 34580 was still listening after verification.

## Existing base candidate

Source: C:/Users/Administrator/.daedalus/kitchen/candidates/bau-mir-nh-app-eine-einkaufslisten-app-l-42e4f4ed

Browser report: browser-report.json; screenshot: 02-candidate-after-reload.png; mobile screenshot: 03-candidate-mobile.png.

- Add by button and Enter: passed.
- Mark complete by clicking the item: passed.
- Reload preserves text and completion: passed.
- Delete: failed; no delete control is rendered. The README promises deletion, but addItem/loadItems create only plain li text. Calling deleteItem from console would not verify a user flow and was not performed.
- Quantity and clear-list controls: absent in this base version.
- No JavaScript exceptions observed. Viewport 390 px had no horizontal overflow.

## Retained improvement patch

The evidence packet order-85c455029188cda8.evidence.json says nominated after build and 6 structural tests. Its recorded workspace is missing, and the current ~/.daedalus/kitchen/worktrees directory contains no app checkout. The patch remains at ~/.daedalus/kitchen/orders/order-85c455029188cda8.patch. Current registered shopping project HEAD exactly equals recorded base 1df621c5ff45603e7a640d4a4671c8632de09974.

For verification only, git archive of that exact base was extracted under improved-reconstructed and the retained patch passed git apply --check, then applied there. This is a reconstruction of retained patch behavior, not a claim that the missing original content-addressed candidate tree was recovered: reconstruction has 8 files and tree digest 76e80073d7c5454f873c7273762d822dd8f2b614901d9377e61b4c69b21d55fa, while historical evidence counts 9 files and digest f08d8b5112cef20f0684350b16abf18cf6a4c19ab50e4e28bf660a8cf6cebc0b. The patch excludes kitchen bookkeeping.

Latest authoritative browser report for reconstructed improvement: improved-browser-v2/browser-report.json. Screenshots: improved-browser-v2/02-candidate-after-reload.png and improved-browser-v2/03-candidate-mobile.png.

- Add with quantity 3: passed, renders CDP Test Apples x 3.
- Next add without changing quantity: failed quantity behavior; first add clears quantity input, and the next item is accepted as CDP Test Bread x (empty quantity).
- Completion and persistence across reload: passed, including persistence of the invalid empty quantity.
- Delete: failed; still no delete controls.
- Clear List button and persistence of empty list after reload: passed.
- Every document load raises TypeError: Cannot read properties of null (reading 'addEventListener') at app.js:16:46. Script refers to #clear-list-btn; HTML clear button has no such id. Inline onclick happens to keep clear-list working.
- Viewport 390 px had no horizontal overflow; screenshot retains the actual controls and invalid quantity.

The initial improved-browser report incorrectly named a quantity-default observation taken after reload; improved-browser-v2 fixes the observation timing to immediately after add and preserves the earlier report as audit history.

## Reusable harness

browser-check.cjs accepts OUTPUT_DIRECTORY and CANDIDATE_DIRECTORY. OUTPUT_DIRECTORY must already exist and must not contain chromium-profile. It starts and closes only its own ephemeral static server and headless Chromium profile; it observes but never stops port 8765. UI interaction uses CDP Input events, not direct app-function calls. Output JSON records individual check results; process exit code reports harness execution, not application acceptance.

Example from PowerShell, after creating a fresh output directory:

& 'C:/Users/Administrator/AppData/Local/hermes/node/node.exe' './browser-check.cjs' '<fresh-output-directory>' '<candidate-directory>'
