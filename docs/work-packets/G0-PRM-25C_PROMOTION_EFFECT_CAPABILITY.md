# G0-PRM-25C — Typed Promotion Effect Capability

## Scope and parent

This Work Packet is stacked directly on the canonical promotion-registry
installation packet:

- parent branch: `g0/promotion-registry-install-linear`;
- parent revision: `764455920df83998cc47a87cdc55507aafde2a1c`;
- parent draft PR: `#144`.

It adds one typed composition object under `daedalus.kernel`. The object binds an
already-produced `PromotionAuthorization`, an already-issued
`NonRuntimeEffectAuthorization`, and one narrowed `EffectExecutionRequest`.
It does not issue any of those authorities and does not call the live Kairos
promotion seam.

## Exact subject binding

`PromotionEffectCapability` refuses unless all of the following name the same
promotion:

- the declared `PromotionAuthorization` digest recomputes from candidate,
  evidence, source revision, target ref, live target revision and persisted
  approval-consumption identity;
- the Effect-Lease request and signed lease both name
  `python.promote_candidates` and its complete three-effect set;
- the request `attempt_id` and effect execution ID equal the promotion ID;
- the execution idempotency key equals the complete promotion-authorization
  digest;
- request and lease provenance use the promotion source revision;
- request provenance contains the authorization, candidate, EvidencePacket and
  approval-consumption digests;
- the supplied prospective registry contains exactly one non-runtime `central`
  row with the reviewed target, effects and guard contracts;
- the guard set is exact, allowed and evidenced, and
  `promotion.owner_approval` evidence names the consumed approval capability;
- neither scope nor narrowed execution carries egress, secret or spend
  authority, and both explicitly bind the `git` tool.

The adapter delegates only `grant`, `begin_effect` and `finish_effect` to the
existing persisted Effect-Lease authority. It contains no issuer, policy
engine, owner key, Git call, worktree manager, sandbox launcher or repository
mutation.

## Honest migration state

The canonical `python.promote_candidates` row intentionally remains
`local_guards`. Therefore the canonical registry cannot issue a production
Effect Lease for this capability yet. Tests use a prospective exact central row
to verify composition semantics without changing live wiring.

A dependent packet must install the capability at the live promotion seam before
manager construction, lock-file creation, Event-Store mutation, Git invocation
or worktree creation. That packet must also reconcile the top-level Effect-Lease
replay semantics with the existing persisted `PromotionExecutionLedger` replay
and terminalize the top-level effect on success, refusal, fault and cancellation.
Only after that composition is mechanically proven may the relevant registry
rows be upgraded to `central`.

## Adversarial batch

The focused suite covers:

- valid grant/start/terminal/replay through the canonical effect ledger;
- repacked promotion authorization;
- cross-promotion attempt, execution and idempotency substitution;
- detached candidate/evidence/approval provenance;
- local, wrong-target, wrong-effect, wrong-guard and runtime-bearing registry
  rows;
- detached owner-consumption guard evidence;
- denied, empty, duplicate and extra guards;
- hidden egress and missing Git authority;
- source review proving the module cannot issue authority or perform promotion.

The bounded mutation runner attacks the non-central refusal, promotion
provenance binding, idempotency binding, owner evidence, egress refusal and Git
requirement. Exact-head execution, full suite, packaging, the supported
Python/platform matrix and independent human review remain required.

## External execution blocker

Repository issue `#67` still records GitHub Actions jobs terminating before
Step 1 with no logs or artifacts. Such runs are infrastructure observations,
not passing or failing product evidence. This Work Packet therefore makes no
exact-head green or Gate-closure claim.

No merge, promotion, OwnerApproval issuance or automatic action is requested.
