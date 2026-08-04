# G0-RTC-06Y — Signed Provider Invocation Resolution

## Exact parent and purpose

This packet stacks on exact revision `f2c7de5c65ba49f3a6de11dd1d5a26f89fa49f7b` from `g0/provider-invocation-registry-manifest-linear`. It composes the signed invocation-observation authority with the immutable registry manifest and emits one non-executing resolution receipt.

The packet remains preparatory. It does not load an adapter, call a provider, persist the receipt, start an effect, modify the broker, recover an execution, merge, promote or change a Gate state.

## Resolution sequence

`resolve_provider_invocation_authority(...)` requires exact composite-authority, registry-manifest and execution-request types. It canonicalizes an aware verification time, requires the manifest source revision to match the expected revision and requires the signed registry digest to equal the exact manifest digest.

It then authenticates the nested provider-observation authority and composite invocation signature through the existing verifier. Only after authentication does it resolve the signed `ProviderInvocationSubject` through the registry. The resulting receipt binds the complete registry digest, composite and nested authority digests, invocation contract, invocation subject, resolved descriptor, selected implementation identity, adapter artifact/config digests, runtime routing identity and effect execution/lease subject.

The receipt recomputes its own digest during construction and requires an exact serialized shape. Reverification accepts neither a caller-selected descriptor nor a claim that the authority was already authenticated. It reruns the complete authority, registry, execution, lease, revision and verification-time resolution and compares the newly derived receipt with the retained receipt.

## Adversarial corrections

The initial receipt-verification draft accepted a `descriptor` argument. That would have allowed a caller to choose a matching descriptor outside the retained manifest while presenting the manifest digest separately. The descriptor argument was removed and resolution became manifest-derived.

The next draft described its authority and manifest inputs as already authenticated and only reconstructed the receipt. That created a dangerous public API assumption. The verifier now requires the complete authority keyrings, execution, lease, revision, contract and verification time and calls `resolve_provider_invocation_authority(...)` again before comparison.

## Prepared verification

Builder tests cover exact resolution and receipt round-trip, changed manifest identity, a valid signed subject that does not resolve, composite and nested signature tampering, stale revision, wrong execution, malformed verification time, receipt digest and shape tampering, full authority reauthentication and verification-time binding.

A separate AST/source review verifies absence of execution, loading, persistence and promotion authority; exact verification-before-resolution ordering; complete receipt subject coverage; digest recomputation; exact parsing; full reverification through the authenticated resolver; and timezone-aware canonical verification time. Eight bounded mutants target signed-registry mismatch, skipped authority verification, resolution bypass, implementation detachment, receipt-digest bypass, naive time, skipped receipt reauthentication and receipt-subject mismatch.

Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, full suite, package build and isolated-wheel import are requested. These commands are prepared, not represented as executed evidence. GitHub Actions issue #67 currently terminates jobs before checkout/Step 1 and yields no logs or artifacts.

## Remaining work

A dependent packet must durably retain this receipt before provider execution, define a guarded executable registry that mechanically binds a loaded implementation to the descriptor artifact identity, bind that registry into Runtime Manifest and RuntimeConformanceReceipt authority, replace the broker's loose callbacks, and make recovery derive the retained resolution without caller authority. Issue #188 and Gate 0 remain open.
