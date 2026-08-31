# G1-HIER-03A - Canonical event owner

## Frozen packet metadata

- Packet ID: `G1-HIER-03A`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: `repository owner`
- Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Dependencies: `G1-HIER-02A at 575873fcbadeac7a82a2637e1cc232e3662bbd4a (2cf1bb793f22137b67491dc958f3b6ebd928e6cc on the packet branch)`
- Promotion authority: no automatic merge, promotion, or Gate transition
- Required reviewed prerequisite: `G1-HIER-02A`, commit `575873fc`
  (`2cf1bb79` after the exact cherry-pick on this packet branch)
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
## Primary acceptance claim

Envelope, intent-ledger, and durability behavior has exactly one implementation
owner under `daedalus.kernel.events`; the three legacy `daedalus.spine`
locators resolve to those exact modules.

The packet consolidates the canonical Event Store; it does not add an event
store, schema, identity, policy, effect entrypoint, or promotion path.

## Contracts and behavior

At the frozen base, the implementation owners were:

- `daedalus/spine/envelope.py` (800 lines),
- `daedalus/spine/ledger.py` (878 lines), and
- `daedalus/spine/durability.py` (231 lines).

The focused pre-move suite passed: **68 passed** across envelope join/coverage,
ledger replay, and durability behavior/review. The Effect Registry digest was
`ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The exact frozen base also contains the retained WIP failure that
`daedalus.kernel.__init__` eagerly referenced an absent
`daedalus.kernel.campaigns`. Any ordinary import of a new
`daedalus.kernel.events` package would therefore have failed before reaching
this packet. The reviewed `G1-HIER-02A` prerequisite makes only that facade
lazy; it does not implement or mask Campaigns. This packet changes no line of
`daedalus/kernel/__init__.py` beyond that exact prerequisite commit.

## Scope

In scope:

- move the exact envelope implementation to
  `daedalus/kernel/events/envelope.py`;
- move the exact SQLite ledger implementation to
  `daedalus/kernel/events/ledger.py`;
- move the exact durability implementation to
  `daedalus/kernel/events/durability.py`;
- retain old modules as module aliases, including public and practically used
  private names, monkeypatch seams, and legacy pickle-global resolution;
- make both package facades lazy, so importing the pure envelope helper does
  not eagerly load SQLite or durability machinery;
- adjust the moved ledger's repository-root traversal from `parents[2]` to
  `parents[3]`, preserving the exact `runs/spine/spine.sqlite3` default;
- add bounded identity, replay, durability, AST, and digest acceptance tests.

Forbidden and unchanged:

- no kill-switch, cancellation, Attempt-lifecycle, effect-boundary, provider,
  gate, runtime, evaluator, or chip behavior;
- no SQLite schema, pragma, transaction, lock, JSON, digest, trace, locator, or
  event-state change;
- no new singleton, database, registry row, effect entrypoint, live provider,
  network call, promotion, or historical `runs/` move;
- no Master Plan or amendment-chain edit.

The implementation classes and functions now truthfully report their new
`__module__` owner. Historical import and pickle locators remain accepted via
exact module aliases. No tracked caller was found to require the old
`__module__` string as data.

## Acceptance matrix

| Claim or refusal | Deterministic evidence | Required result |
|---|---|---|
| One implementation owner | AST definition scan over old and new paths | definitions occur only under `kernel/events` |
| Import compatibility | old/new module and object identity tests | exact identity, including private seams |
| Old pickle compatibility | protocol-0 legacy global loads | old globals resolve to new owner objects |
| Envelope bytes and digest | literal golden JSON and SHA-256 | unchanged bytes and digest |
| Ledger replay | new-owner write, legacy-locator read-only replay, raw SQLite read | one row/history, unchanged canonical payload |
| Durability | legacy/new readback on the same FULL/WAL writer | identical satisfied receipt |
| Dependency direction | AST import scan of `kernel/events` | no import of spine, gates, runtimes, providers, kairos, eval, or chip design |
| Lazy prerequisite remains bounded | isolated import inventory | envelope only; no eager ledger/durability/capability owner |
| Effect Registry | exact digest assertion | `ac020278...6211ec` unchanged |
| Live effects | packet scope and test inventory | zero network/provider/EDA starts |

## Evidence expected failures and review

- CPython 3.13: the focused hierarchy/envelope/ledger/durability/lazy-facade
  matrix passed, **207 passed in 3.46s**.
- CPython 3.10: the same matrix passed, **207 passed in 3.79s**.
- CPython 3.13 extended consumers (conversation, writer inventory, Attempt,
  effect recovery/replay, approvals, promotion execution and provider-target
  receipt replay): **391 passed, 1 skipped, 1 deselected in 24.38s**. The skip
  retains the existing "symlinks unavailable" platform result.
- The deselected review assertion expects a Python class dictionary to contain
  only three keys. CPython 3.13 adds `__firstlineno__` and
  `__static_attributes__`; the identical failure was reproduced against the
  unmoved legacy owner. It is retained as parent/interpreter negative evidence,
  not rewritten in this structure packet.
- `git diff --check` passed (apart from Git's informational CRLF conversion
  warning), and `compileall` passed for the changed Python packages/tests.
- Post-move Effect Registry SHA-256:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`,
  identical to the baseline.

The full-suite `-x` probe reached **43 passed, 2 skipped** and then stopped at
the retained Forest-v2 corpus-pin drift detector (`5285` frozen functions
versus the current WIP tree). Running that experiment module directly produced
**6 passed, 2 failed**: the same frozen count drift and the already absent
fourth optional external corpus. Both failures reproduce outside this packet;
the experiment README explicitly prohibits rewriting the historical measured
row to match a later tree. No Campaign implementation was fabricated to erase
the frozen parent's separate missing-Campaign evidence.

## Migration and rollback

There is no persistent-data migration. Existing SQLite files, envelope bytes,
trace fields, digests, WAL files, and replay semantics remain in place.
Rollback delegates the three old module locators back to their prior source
files and restores the old eager `spine.__init__`; no database conversion is
required.

Independent review should focus on module-alias behavior, private monkeypatch
compatibility, default-path preservation after the deeper source location, and
whether any runtime import path escapes the static AST evidence. Dynamic
imports, monkeypatching, and runtime dispatch remain only partially visible to
the deterministic ontology preflight and are therefore covered separately by
the executable import/replay tests.
