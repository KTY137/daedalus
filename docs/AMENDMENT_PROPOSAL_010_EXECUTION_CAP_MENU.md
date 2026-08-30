# Amendment proposal 010 — owner-controlled execution cap menu

## Classification

- Iron Plan: `AMENDMENT`
- Active gate: Gate 1
- Owner: repository owner
- Approval reference:
  `conversation-2026-08-30-owner-requests-full-cap-toggle-menu-and-says-implement`

## Exact change

Replace Revision 9's single period-USD exception with one canonical execution
limit policy. The desktop exposes three explicit modes:

- `bounded`: every Daedalus execution cap is enforced;
- `custom`: the owner enables or disables individual cap axes;
- `unbounded_execution`: every Daedalus execution cap axis is disabled.

The individually controllable axes are:

1. global period USD;
2. billable call count;
3. Mission, EffectLease and SpendEnvelope monetary limits;
4. input/context and output-token limits;
5. execution, provider, gate and evaluation wall-time limits;
6. retry, attempt, iteration and agent-step limits;
7. read-only worker, fan-out and candidate-evaluation concurrency limits; and
8. work-scope limits such as queue batch, decomposition count, rewrite scope
   and candidate population.

The policy does not disable authorization or integrity boundaries: the kill
switch, egress admission, bounded write roots, secret/tool policy,
authentication, evaluator isolation, provenance, evidence gates, explicit
owner approval, and the prohibition on automatic merge or promotion remain
enforced. Unsafe parallel writes remain refused until isolated worktrees make
them safe. Sandbox CPU, RAM, PID and filesystem quotas remain host containment,
not user execution caps.

Provider context windows, API quotas and rate limits, hardware capacity, disk
capacity and operating-system limits cannot be removed by Daedalus and are
reported as external limits rather than represented as disabled.

No disabled cap is represented by `Infinity`, `MAX_INT`, zero, or a missing
field. Configured positive fallback values remain stored while effective caps
and remaining values are explicitly nullable. Ledger, usage and evidence
recording continue in every mode.

Every widening transition (`bounded` to `custom`, any individual cap from on
to off, or entry into `unbounded_execution`) requires a transient,
backend-verified risk confirmation. It is never persisted. A policy change
applies only to newly admitted reservations, missions, attempts, leases,
provider calls and campaigns; an already issued contract is not rewritten.

## Reason

Revision 9 implemented only a no-global-period-USD mode and deliberately kept
the call ceiling and Mission/SpendEnvelope ceilings. The owner rejected that
remaining restriction and then explicitly requested a complete toggle menu and
said to implement it. A named policy is more honest and testable than scattered
large-number workarounds or environment-only bypasses.

## Affected invariants and priors

- Invariant 1 remains: the policy is a canonical kernel snapshot, not a second
  budget or orchestration store.
- Invariant 3 remains: candidates cannot change their policy, evaluator,
  evidence, ledger or promotion path.
- Invariant 7 is strengthened: the effective policy and disabled axes travel
  with receipts and evidence.
- Invariant 8 is amended: execution resource caps are bounded by default but
  may be disabled by the owner policy. Authorization, containment and the kill
  switch are never disabled by that policy.
- Invariant 9 remains: comparative claims still require equal declared
  budgets. `unbounded_execution` is an operating mode, not permission to claim
  scientific superiority from unequal runs.
- The four-plane Project Twin and latent-routing priors are unchanged.

## Alternatives rejected

- A single hidden emergency dollar ceiling: explicitly rejected by the owner.
- `Infinity`, zero, `MAX_INT`, or omitted keys as unlimited sentinels: ambiguous
  and unsafe across JSON, Python, Rust and TypeScript.
- Disabling security and authorization boundaries with the same switch: would
  conflate resource authority with trust authority.
- Rewriting active contracts when the setting changes: breaks provenance and
  makes prior evidence unverifiable.
- Advertising Ariadne as switched live today: no evolution campaign currently
  runs on the live path.

## Migration

- Missing policy defaults to `bounded` with all axes enabled.
- A valid Revision 9 configuration with
  `period_ceiling_enabled=false` migrates to `custom` with only the period-USD
  axis disabled. It never silently becomes fully unbounded.
- Existing numeric cap values remain positive finite fallback values.
- Existing ledger periods, spend, reservations, calls, envelopes, contracts
  and receipts remain authoritative and are not reset or rewritten.
- Invalid policy input is fail-closed while the settings UI remains available
  for explicit repair.

## Acceptance evidence required

- Backend and GUI tests for all three modes, every individual axis, transient
  widening confirmation, reload and draft isolation.
- Boundary tests proving disabled axes no longer refuse while ledger and usage
  stay recorded.
- Tests proving kill switch, egress, write roots, secrets, authentication,
  evaluator isolation and no-auto-promotion remain enforced in
  `unbounded_execution`.
- Tests proving a policy snapshot is frozen for newly issued work and existing
  contracts are not rewritten.
- Tests proving nullable effective values never render as zero or crash a
  consumer.
- Explicit UI disclosure for external provider/hardware limits and for the
  currently disconnected Ariadne campaign path.
- Desktop package and installed-application end-to-end verification before a
  prerelease is published.

## Rollback

Select `bounded`, which re-enables every stored cap for newly admitted work.
Code or schema removal is a later amendment; ledger and evidence history are
never rewritten.
