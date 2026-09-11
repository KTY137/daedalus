# G1-CAPS-13 — Owner execution cap menu

## Classification

- Iron Plan: `AMENDMENT` while Revision 10 is adopted, then `ALIGNED`
- Target gate: Gate 1
- Active amendment: `AMENDMENT_PROPOSAL_010_EXECUTION_CAP_MENU.md`
- Promotion: forbidden

## Problem

The desktop currently controls only the global period USD ceiling. The owner
requires a full toggle menu and a master mode that removes every Daedalus-owned
execution resource cap without pretending that security boundaries or external
provider/hardware limits disappeared.

## Frozen acceptance matrix

1. One canonical policy exposes `bounded`, `custom` and
   `unbounded_execution` and the eight cap axes named in Amendment 010.
2. Missing/old configuration migrates without widening authority; Revision 9
   USD-only uncapped becomes `custom`, not fully unbounded.
3. Every widening requires transient backend confirmation before any service,
   file, environment, ledger or work-admission effect.
4. Configured fallback values remain finite and positive. Effective disabled
   caps and remaining values are `null`, never numeric sentinels.
5. The policy is captured for newly admitted work; active contracts and ledger
   history are never rewritten or reset.
6. Ledger and usage continue recording on all disabled axes.
7. Kill switch, egress, write roots, secrets/tools, authentication, evaluator
   isolation, evidence gates and no-auto-promotion remain enforced.
8. Unsafe parallel writes and sandbox containment remain outside the menu.
9. The GUI provides a master switch, individual grouped toggles, values,
   explicit risk acknowledgement, effective-state display, external-limit
   disclosure and truthful Ariadne not-live status.
10. Python, TypeScript build, motion, Playwright, packaged-backend and installed
    desktop tests pass before release.

## Forbidden scope

- no second ledger, event store, HTTP server, configuration file or promotion
  path;
- no hidden high cap and no `Infinity`, zero or `MAX_INT` sentinel;
- no disabling authorization, containment, evidence or promotion policy;
- no claim that an Ariadne campaign is live until a live producer exists;
- no automatic cancellation, rewrite or widening of already issued contracts.

## Baseline

- Revision 9 plan SHA-256:
  `41b414f62b0856683e8c3e98b1846b18d9cb70c9d7430d607e9a7590e86f3a48`.
- Revision 9 budget/backend focused suite: `236 passed`.
- Revision 9 adjacent consumer suite: `117 passed`.
- Revision 9 frontend: production build passed, motion `136/136`, targeted
  spend-settings Playwright `5/5`.
- Read-only cap inventory retained in the owner session; Ariadne campaign is
  producerless on the live path.

## Evidence

Pending implementation and end-to-end verification.
