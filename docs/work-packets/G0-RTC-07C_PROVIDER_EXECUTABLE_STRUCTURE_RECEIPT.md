# G0-RTC-07C — Provider Executable Structure Receipt

## Exact parent

This packet starts from `824b1ec93b9c38c071613031be516facb0e6405b` on `g0/provider-executable-target-manifest-linear` and remains a short-lived stacked Gate-0 branch.

## Scope

The signed predecessor authenticates the provider, adapter, implementation, runtime, artifact/config digests and two local Python targets, but retains inert metadata only. This packet adds a read-only structural boundary. It resolves the invocation and output-evidence targets against exact repository bytes and retains their unique Python AST definition chains in a deterministic receipt.

The verifier consumes the exact `ProviderExecutableTargetProjection`, uses the shared race-aware repository reader and conservative Python target resolver, verifies each source digest, and binds path, size, definition kind, source positions and chain kinds. Receipt verification rebuilds the complete live result and accepts no caller-supplied source bytes.

## Authority boundary

Structural presence is not executable admission. The packet does not import the selected module, evaluate decorators, invoke a provider, compute output evidence, begin or finish an effect, mutate runtime state, authenticate the current Git HEAD, or authorize a loader.

The receipt permanently records:

- `targets_structurally_verified=true`
- `repository_bytes_executed=false`
- `provider_execution_allowed=false`
- `source_revision_verified_against_git_head=false`

Issue #188 remains open. A later dependent packet must authenticate the repository revision, retain that binding, resolve exact callables through a guarded registry, and make the broker consume only that result before `begin_effect`.

## Adversarial batch

Prepared coverage includes strict receipt round-trip and live reconstruction; changed source and missing target refusal; projection and retained-receipt substitution; resolver target and source-digest detachment; exact subject types; authority-escalation refusal; strict schema checks; an independent AST review for loading, execution and effect authority; and ten bounded mutants.

CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, the full suite, package build and isolated-wheel import.

## Evidence state

No prepared test, source inspection or LLM statement is represented as hard evidence. GitHub Actions issue #67 still prevents hosted jobs from reaching checkout or Step 1 and provides no logs or artifacts. Dependent executable broker wiring remains frozen until exact-head CI can run.

No change targets `main` or `experimental`. No merge, automatic promotion, OwnerApproval, PromotionReceipt, issue closure or Gate transition is authorized.
