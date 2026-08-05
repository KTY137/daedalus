# G0-RTC-07C — Signed Provider Target Source-Tree Verification

## Exact parent and frozen dependency

This packet stacks on exact head
`824b1ec93b9c38c071613031be516facb0e6405b` of draft PR #207. The parent has
received a separate static counter-review, including correction of its original
unsigned target-manifest gap. Exact-head execution remains externally blocked:
GitHub Actions issue #67 terminates every job before checkout and Step 1.

Executable loading and broker migration therefore remain frozen. This packet is
an independent read-only verifier. It does not import or execute a target,
construct a provider client, persist a receipt, transition an Effect Lease,
spawn a process, access a network, or write a source tree or checkout.

## Strangler responsibility split

The new responsibility is separated into:

- `provider_target_verification_contracts.py` — inert verified-target records,
  signed receipt wire contract and verification error domain;
- `provider_target_verification.py` — exact source-tree reads, Python AST
  structure checks, receipt issuance and receipt re-verification.

It reuses the canonical `SourceTreeStore`, `SourceTreeManifest` and
`ArtifactRef` authorities from `daedalus.kernel`. It does not define another CAS
or locator format. It reuses the signed target authority from PR #207 rather
than introducing another provider identity source.

## Verification chain

`issue_provider_target_verification_receipt(...)` requires exact
`SourceTreeStore` and `ArtifactRef` objects. Before any source-tree read it
authenticates the complete signed invocation and target authority through
`project_provider_executable_targets(...)`.

The verifier then:

1. loads the exact content-addressed source-tree manifest and requires its
   revision to equal the signed provider target revision;
2. maps each signed module name to exactly one repository path:
   `module.py` or `module/__init__.py`, never both;
3. requires the selected manifest entry digest to equal the signed target
   source digest;
4. reads the bounded CAS object and independently recomputes SHA-256;
5. decodes strict UTF-8 and parses with `ast.parse` without import or compile;
6. resolves every qualified owner as an exact class and the final symbol as one
   unique sync or async function definition;
7. refuses duplicate definitions, aliases, class targets, non-class owners,
   malformed source and ambiguous module layouts.

The receipt binds the verifier identity, exact source revision/tree
digest/locator/tree ID, signed target authority, target projection, target
manifest and selected descriptor, provider/adapter/implementation, runtime
effect subject, lease, and exact structural records for invocation and output
evidence.

## Inert authenticated receipt

`ProviderExecutableTargetVerificationReceipt` signs its entire canonical wire.
It reports:

- `targets_structurally_verified=true`;
- `provider_execution_allowed=false`.

Verification authenticates the receipt before any source-tree read, then
re-authenticates the signed target authority, re-reads and reparses the exact
source bytes, rebuilds the expected receipt, and requires byte-semantic equality.
A valid receipt from another tree, even at the same source revision and with the
same provider target file, is refused because the complete source-tree manifest
digest differs.

The receipt is returned to the caller but is not persisted in this packet.
Therefore it is structural evidence, not yet a runtime admission capability.

## Adversarial verification prepared

Builder tests cover:

- exact receipt round-trip and complete re-verification;
- invalid target authority, invalid receipt signature and unknown verifier key
  before source-tree read;
- independent digest recomputation even when the exact store method is
  monkeypatched to return substituted bytes;
- stale source revision and signed source-digest substitution;
- `module.py` / package shadow ambiguity;
- duplicate method definitions, aliases, class targets and non-class owners;
- sync and async methods;
- malformed UTF-8, Python syntax and source-size limits;
- exact store, reference, receipt and nested target types;
- wire-shape and claim escalation;
- a valid signed receipt replayed against a different exact source tree.

A separate AST/source review forbids dynamic loading, execution, process,
network, SQLite, filesystem writes, CAS writes and materialization. It verifies
authentication/read ordering, independent byte hashing, exact module and symbol
cardinality, complete receipt signing and fixed structural/execution claims.
Ten bounded mutants target those properties.

The requested CI matrix contains Ubuntu and Windows, Python 3.10 and 3.12, two
hash seeds, predecessor source-tree/target-authority regressions, full suite,
package build and isolated-wheel imports. While issue #67 persists, prepared
checks are not represented as executed hard evidence.

## Remaining issue #188 path

This packet advances but does not close issue #188. The exact remaining
dependent sequence is:

1. durably retain the signed structural verification receipt under one
   canonical runtime authority;
2. construct a guarded executable registry only from an authenticated retained
   receipt and exact installed/repository bytes;
3. resolve the two callables through that exact registry, with no caller-selected
   callback or import target;
4. require `run_runtime_provider(...)` to consume the registry binding before
   `begin_effect`;
5. prove normal execution, exact replay and recovery cannot accept callbacks.

No change to `main` or `experimental`; no merge, promotion, OwnerApproval,
PromotionReceipt, issue closure or Gate transition.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Evidence: prepared deterministic tests, separate source review and bounded
mutation campaign; exact-head execution blocked by issue #67.
