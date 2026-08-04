# G0-RTC-06X — Provider Invocation Registry Manifest

## Exact parent and purpose

This packet stacks on exact revision `2eee927a49ee3c75efc2e1392691b81095ed72db` from `g0/provider-invocation-observation-authority-linear`. It provides the non-executing registry subject required by issue #188 before any broker or adapter execution change.

`ProviderAdapterDescriptor` maps one provider ID to an adapter ID, implementation ID, adapter artifact digest, adapter configuration digest, runtime entrypoint, runtime ID and exact source revision. `ProviderInvocationRegistryManifest` requires a canonical provider-ID order, exactly one descriptor per provider ID and one revision shared by the manifest and every descriptor.

## Exact resolution

The manifest digest covers the schema tag, registry ID, source revision and every complete descriptor. Changing implementation identity, artifact bytes digest, configuration digest or any routing identity changes the registry digest.

`resolve(...)` accepts only an exact `ProviderInvocationSubject`. It first resolves the provider ID to exactly one descriptor and then compares adapter ID, artifact digest, configuration digest, entrypoint, runtime and source revision. Execution-specific fields remain signed in the invocation subject and composite authority; the registry deliberately owns only the stable adapter-definition plane.

The packet includes an integration test in which `ProviderInvocationObservationAuthority` signs the exact manifest digest, verifies it, and resolves the corresponding subject. A manifest with a changed implementation identity produces a different digest and cannot satisfy the retained signed authority.

## Deliberate non-executing boundary

The manifest imports no callback type, provider client, process/network API, dynamic loader, broker, SQLite store or recovery implementation. It does not import or execute the artifact named by the descriptor. That work requires a separate guarded executable-registry packet with Runtime Manifest and RuntimeConformanceReceipt authority.

The current production broker still accepts independently supplied `invoke` and `output_digests` callbacks. This packet therefore does not close issue #188 or Gate 0.

## Prepared adversarial verification

Builder tests cover canonical build and round-trip, exact resolution, adapter/artifact/config/entrypoint/runtime/revision substitution, unknown providers, duplicate provider IDs, noncanonical ordering, stale descriptor revisions, implementation-identity digest sensitivity, malformed shapes, hostile descriptor container types and signed-composite integration.

A separate AST/source review proves absence of execution/loading authority, exact descriptor fields, canonical uniqueness and revision invariants, complete digest coverage, exact resolution comparisons, strict parser shape and separation of permissive canonical building from exact parsing. Eight bounded mutants target implementation-digest detachment, ordering, duplicate IDs, stale revisions, artifact/config bypass, subject subclass acceptance and extra manifest fields.

Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, full suite, package build and isolated-wheel import are requested. These commands are prepared, not represented as executed evidence. GitHub Actions issue #67 currently terminates jobs before checkout/Step 1 and yields no logs or artifacts.

## Remaining work

A dependent packet must define the executable registry boundary, mechanically bind an executable adapter to the descriptor artifact identity under Runtime Manifest and RuntimeConformanceReceipt authority, replace loose broker callbacks, persist the composite invocation authority before execution, and make recovery derive the exact retained registry contract. No merge, promotion, OwnerApproval, PromotionReceipt or Gate transition is authorized here.
