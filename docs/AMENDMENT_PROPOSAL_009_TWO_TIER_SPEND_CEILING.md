# Amendment proposal 009 — explicit uncapped monetary mode

Status: **APPROVED by repository owner**
Approval reference: `conversation-2026-08-30-owner-approves-two-tier-spend-ceiling`
Proposed and approved: 2026-08-30
Base plan SHA-256: `7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704`
Base revision: 8
Target revision: 9
Target version: 2.0.0

## Decision

Keep the canonical period monetary ceiling enabled at `$5.00` by default, while
allowing the repository owner to explicitly select an uncapped monetary mode.
In that mode there is no global period USD ceiling: reservations are not
refused because of cumulative period spend.

The existing call ceiling, egress policy, and any explicitly bounded
Mission/SpendEnvelope remain independent controls. Unknown prices are still
estimated and recorded. Configuration changes never rewrite the ledger,
release a reservation, reset spend, or change evidence for completed calls.

GUI/API changes that raise the period ceiling or switch to uncapped monetary
mode widen spend authority and require an explicit transient confirmation. The
GUI requires a second confirmation that names the absence of a global USD cap;
the backend independently refuses the transition without the confirmation.

## Reason

The `$5.00` default correctly protects unattended runs but is too small for an
owner-supervised local desktop session. The owner explicitly rejected a hidden
or fixed emergency USD ceiling and approved a genuine no-global-USD-cap mode.
Making that exceptional mode visible, authenticated, confirmed, and reversible
is safer and more honest than an undocumented environment workaround.

## Affected invariants

- Invariant 1, one kernel: configuration still feeds the existing canonical
  budget ledger; no second authority or state store is created.
- Invariant 7, provenance: configured and effective ceilings are reported
  separately and prior ledger evidence is retained.
- Invariant 8, bounded effects: amended from an unconditional monetary bound to
  bounded-by-default spend with an explicit owner-controlled uncapped exception;
  egress, writes, concurrency, secrets, kill switch, and configured Mission or
  SpendEnvelope limits remain enforced.
- Invariant 10, no silent constitution change: this approved record changes the
  plan and amendment chain explicitly.

## Alternatives considered

- **Fixed absolute emergency ceiling:** rejected by the owner because it would
  make the advertised off state still capped.
- **Simply raise the default:** rejected because it silently widens every
  unconfigured process.
- **Only add a paid-spend kill switch:** useful but does not satisfy the owner's
  request to run supervised work beyond the small default period ceiling.
- **Environment-only bypass:** rejected because it is harder to inspect and
  easier for the GUI to misreport.

## Migration

- Missing settings preserve today's behavior: period ceiling enabled at
  `$5.00`.
- Existing positive `DAEDALUS_BUDGET_USD` values remain period ceilings.
- Non-finite values, zero, and negative values refuse before spend until
  corrected; uncapped mode uses a separate explicit boolean and never a magic
  numeric sentinel.
- Existing ledger periods, spend, reservations, calls, and envelopes remain
  byte-for-byte authoritative.

## Rollback

Re-enable the period ceiling at `$5.00` in persisted settings and remove the
desktop projection. Retain all ledger data. Reverting the plan text requires a
new owner-approved amendment; history is not rewritten.

## Acceptance evidence

- boundary tests for capped and uncapped monetary modes;
- refusal before provider spawn/request when the enabled period ceiling is crossed;
- persistence/reload tests proving uncapped mode reports `null` remaining USD
  rather than inventing a numeric ceiling;
- tests proving ledger state is unchanged by configuration updates;
- frontend tests for widening confirmation, honest effective-limit copy, and
  backend validation errors;
- focused legacy budget, desktop runtime, and runtime-probe suites.
