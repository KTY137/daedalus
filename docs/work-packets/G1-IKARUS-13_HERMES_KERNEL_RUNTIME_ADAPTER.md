# G1-IKARUS-13 — Hermes kernel runtime adapter

## Frozen packet metadata

- Packet ID: `G1-IKARUS-13`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `52b4baa5f7b065c54779cafd6a35b2411eeb5e84`
- Master-plan authority: Revision 10
- Master-plan digest: `5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`
- Dependencies: G1-IKARUS-02 through 07D4, G1-IKARUS-09 through 12,
  canonical provider broker, Effect Lease, tool scope, runtime events, and
  one-shot request contracts
- Upstream candidate evidence: the additive Hermes adapter commits ending at
  `56c9854dc9ae01cc85ce900c51bf76aaba74b630`; no merge or branch switch
- Primary claim: an exactly pinned Hermes agent loop can run as a replaceable,
  stateless Ikarus userspace worker behind Daedalus-owned runtime, tool, Effect,
  receipt, memory and evidence boundaries in a fixture-backed vertical slice.

This packet is one migration axis. It does not claim full Hermes parity or
production admission. The goal remains a complete Hermes-plus Ikarus; later
packets must close exact upstream materialization, outer containment, live
model compatibility, unknown-outcome recovery, chat selection, and measured
parity before legacy code is removed.

## Baseline

- The current checkout has no `daedalus/integrations/hermes/` package and no
  executable `hermes_agent` runtime.
- ADR-022 and source provenance pin Hermes v0.20.5 / tag v2026.8.19 / commit
  `fcbd1076a93841fa88855acce810e342a5b78101`, but deliberately keep it
  `source-only`.
- The current tree already supplies the reusable Daedalus authorities:
  `RuntimeRoleRegistry`, `OneShotRequest`, policy-bound tool scope, runtime
  event projection, sealed provider operations, Effect Leases and receipts.
- The PDF's later statement that the adapter was already delivered is not
  current-tree evidence. No named delivery ZIP, patch or report exists in the
  supplied Downloads directory.

## Scope

In scope:

- a new optional `daedalus.integrations.hermes` package;
- exact source/configuration and environment confinement contracts;
- explicit context and read-only memory projections;
- strict bounded JSONL worker protocol and observation-only event adapter;
- Daedalus-owned tool schemas plus an authenticated, task/scope/budget-bound
  loopback gateway;
- isolated worker lifecycle, timeout, cancellation and process-group cleanup;
- a fixed, closure-free `ProviderRuntimeOperation` registered in the existing
  sealed broker registry;
- fixture-backed runtime, gateway, kernel-provider and conformance tests;
- ADR/provenance, focused CI workflow, and this packet.

Forbidden:

- no Hermes scheduler, SessionDB, canonical memory, learning, gateway,
  messaging, cron, checkpoint database, plugin/skill mutation or background
  authority;
- no direct process, filesystem, network or tool effect outside the canonical
  Daedalus runtime/effect boundary;
- no second mission, attempt, policy, Effect, receipt, artifact, event,
  evaluator or promotion authority;
- no production admission from fixture evidence;
- no live provider/model call in local verification;
- no deletion of existing Ikarus/Claude/Codex paths in this packet;
- no Master Plan, amendment-chain, evaluator or promotion edit.

## Exact source boundary

The adapter is bound to:

```text
repository        NousResearch/hermes-agent
release           v0.20.5
tag               v2026.8.19
commit            fcbd1076a93841fa88855acce810e342a5b78101
tree              cc9f987a403a1d02b8b17cc527a57b54402e864b
run_agent.py sha   b8e0244cfdbdce9328040d92adb9b89d78351000ee88bafae35d71b3e33fb8a1
LICENSE sha        821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6
archive sha        b7a86a237c11b4b5b439c6b803cc9837f1eab4861c3470a0b7f00651e18a5654
license            MIT, Copyright 2025 Nous Research
```

No upstream source is vendored by this packet. Importing the integration must
perform no I/O, registration, socket open, process start or model connection.

## Acceptance matrix

| Claim/refusal | Deterministic evidence | Expected |
| --- | --- | --- |
| Exact checkout binding | wrong commit/tree/source/license/dirty tests | refuse before worker/model work |
| No upstream state authority | env/config and memory tests | ephemeral roots; mutation refused |
| Environment and secrets | allowlist tests | undeclared host values absent |
| Strict worker protocol | malformed/oversized/sequence/identity tests | fail closed, never infer success |
| Tool authority | schema/scope/auth/expiry/budget tests | only declared calls reach injected Daedalus boundary |
| Canonical provider path | real 07D4 registry test | one fixed closure-free operation; callbacks refused |
| Timeout/cancellation | process tests | entire process group terminated |
| Observations are not truth | digest/event tests | canonical receipts remain authoritative |
| Import safety | subprocess/socket/import review | zero import-time effects |
| Regression safety | affected Ikarus/provider/broker suites | Claude, Codex, fixture and current chat paths green |
| Production honesty | conformance evidence tests | `production_admitted=false` until every live bit is proven |

Budgets: zero live model/provider calls, zero non-loopback network calls, one
fixture worker process per accepted process test, focused suite under 120
seconds. Negative tests must start zero provider/model work.

## Migration and rollback

The package is additive and explicitly registered. Rollback deletes only the
new integration/provider facade, its tests, workflow, ADR/provenance and this
packet. No schema or state migration is allowed. The deterministic Ikarus path
remains available until later measured parity and owner-approved removal.

## Next packets required by the full user goal

1. exact upstream checkout materialization as a content-addressed artifact;
2. verified container/user-namespace containment on supported hosts;
3. live no-secret model/tool compatibility plus egress and unknown-outcome
   fault matrices;
4. executable runtime-role admission and project-owned chat selection;
5. repeated parity evaluation against the incumbent path, followed by
   selective deletion only when rollback evidence exists.

Iron Plan: ALIGNED
Iron Gate: 1
