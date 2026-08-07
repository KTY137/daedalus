# G0-RTC-07C — Provider Executable Structure Receipt

## Exact parent

This packet starts from `824b1ec93b9c38c071613031be516facb0e6405b` on `g0/provider-executable-target-manifest-linear` and remains a short-lived stacked Gate-0 branch.

## Scope

The signed predecessor authenticates the provider, adapter, implementation, runtime, execution, lease, artifact/config digests and two local Python targets, but it intentionally projects inert metadata only. This packet adds a read-only structural boundary. It replays the complete signed target-authority verification before any repository read, resolves the invocation and output-evidence targets against exact source bytes, and retains their unique Python AST definition chains in a deterministic receipt.

The public verifier accepts the signed `ProviderExecutableTargetAuthority`, invocation authority, identity registry, effect execution request and target manifest. It does not accept a caller-supplied target projection. The authenticated projection is rebuilt internally through `project_provider_executable_targets(...)`, then the shared race-aware repository reader and conservative Python target resolver bind path, size, source digest, definition kind, source positions and chain kinds.

Receipt schema v2 retains the target-authority digest and contract, invocation-authority and invocation-contract digests, execution ID, idempotency key, lease digest, identity registry/descriptor, adapter artifact/config and target manifest/descriptor. Receipt verification re-authenticates and rebuilds the complete live result.

## Adversarial finding and correction

The first draft API accepted an exact `ProviderExecutableTargetProjection` supplied by the caller and treated class identity as proof that the signed target authority had been replayed. A frozen dataclass can be directly constructed, so this did not mechanically earn the authentication claim. The permanent non-execution flags prevented direct provider authority, but dependent work could not safely consume that receipt.

The issue was found in the independent review of this batch and corrected before dependency use: the loose projection parameter was removed, signature and manifest verification now run before repository resolution, and the complete authority chain is retained. Tests explicitly reject direct-projection substitution, invalid signatures, manifest substitution and non-exact projected results before source resolution.

## Authority boundary

Structural presence is not executable admission. The packet does not import the selected module, evaluate decorators, invoke a provider, compute output evidence, begin or finish an effect, mutate runtime state, authenticate the current Git HEAD, or authorize a loader.

The receipt permanently records:

- `target_authority_authenticated=true`
- `targets_structurally_verified=true`
- `repository_bytes_executed=false`
- `provider_execution_allowed=false`
- `source_revision_verified_against_git_head=false`

Issue #188 remains open. A later dependent packet must authenticate the repository revision, retain that binding, resolve exact callables through a guarded registry, and make the broker consume only that result before `begin_effect`.

## Adversarial batch

Prepared coverage includes strict receipt round-trip and authenticated live reconstruction; invalid target signature and manifest substitution before repository resolution; loose and non-exact projection refusal; changed source and missing target refusal; resolver target and source-digest detachment; retained authority-digest detachment; authority-escalation refusal; strict schema checks; an independent AST review for authentication order, loading, execution and effect authority; and ten bounded mutants.

CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, the full suite, package build and isolated-wheel import.

## Evidence state

No prepared test, source inspection or LLM statement is represented as hard evidence. GitHub Actions issue #67 still prevents hosted jobs from reaching checkout or Step 1 and provides no logs or artifacts. Dependent executable broker wiring remains frozen until exact-head CI can run.

No change targets `main` or `experimental`. No merge, automatic promotion, OwnerApproval, PromotionReceipt, issue closure or Gate transition is authorized.
