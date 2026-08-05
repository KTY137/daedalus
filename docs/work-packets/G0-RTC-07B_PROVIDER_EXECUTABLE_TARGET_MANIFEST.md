# G0-RTC-07B — Signed Provider Executable Target Manifest

## Exact parent and blocked dependency

This read-only packet stacks on exact head
`62be3829e44eebe2d07fe7fc578c8ed59bb0a710` of draft PR #206. That parent has
received an independent static counter-review, but its builder, mutation,
platform, full-suite and packaging jobs remain unexecuted because GitHub Actions
issue #67 terminates every hosted job before Step 1.

The dependent broker migration is therefore frozen. This packet performs only
independent preparatory contract work permitted by the adopted plan: it adds no
loader, callback, provider client, effect transition, persistence or execution
path.

## Manifest and signed target authority

`ProviderExecutableTargetManifest` gives each provider exactly one inert target
descriptor for an exact source revision and signed provider-invocation registry
digest. Each descriptor binds:

- provider, adapter and implementation identities;
- runtime entrypoint and runtime identity;
- the authenticated identity-descriptor digest;
- adapter artifact and configuration digests;
- canonical local `daedalus...:Qualified.target` names for invocation and output
  evidence;
- source digests for both named targets.

Only targets inside the `daedalus` package grammar are accepted. The manifest is
canonically ordered, refuses duplicate provider and identity-descriptor rows,
and requires every descriptor to share its exact source revision.

The first draft authenticated the invocation identity but accepted the target
manifest independently. That would have allowed a caller to substitute another
local target manifest with matching provider metadata. The draft was corrected
before review by adding `ProviderExecutableTargetAuthority`.

The signed target authority binds the exact invocation authority and invocation
contract digests, authenticated invocation identity, invocation registry and
identity descriptor, target manifest and selected target descriptor, provider,
adapter, implementation, entrypoint, runtime, execution, idempotency key, lease
and source revision. It uses the same authenticated authority-key identity as
the nested provider-observation authority.

## Verification order

`project_provider_executable_targets(...)` does not accept a caller-constructed
identity projection. It:

1. authenticates the signed composite invocation authority and derives the
   invocation identity internally;
2. authenticates the target-authority signature;
3. compares target contract, invocation authority/contract, identity, registry,
   manifest and complete runtime-effect subject before any target lookup;
4. resolves the selected descriptor from the signed manifest;
5. compares its digest and provider/adapter/implementation/artifact/config
   bindings with the authenticated identity.

An invalid invocation signature, invalid target signature, unsigned manifest
substitution or foreign signed target contract therefore refuses before a target
can be selected.

## Inert output

`ProviderExecutableTargetProjection` content-addresses the authenticated
identity, invocation registry, target manifest, target descriptor, adapter
artifact/configuration and both target source digests. Its exact wire format
permanently reports:

- `targets_structurally_verified=false`;
- `provider_execution_allowed=false`.

It exposes no callable, import, dynamic loader, filesystem read/write, process,
network, SQLite, effect, recovery or promotion operation.

## Adversarial verification prepared

Builder tests cover exact authority/manifest/projection round-trip, invalid
composite and target signatures, unsigned manifest and signed contract
substitution, stale revisions, provider, adapter, implementation, entrypoint,
runtime, descriptor, artifact and config substitution, target grammar,
duplicate rows, malformed contracts, exact wire shapes, authority escalation and
exact-type refusal.

A separate AST/source review proves the module has no import-loader, execution,
process, network or write primitive; no public callback/loader/identity-assertion
parameter; invocation and target signatures before target lookup; complete
signed subject and descriptor comparisons; and permanent false structural and
execution claims. Ten bounded mutants target those properties.

The requested CI matrix includes Ubuntu and Windows, Python 3.10 and 3.12, two
hash seeds, predecessor invocation/broker regressions, full suite, package build
and isolated-wheel import. Until issue #67 is resolved, none is represented as
executed evidence.

## Remaining issue #188 path

This packet intentionally does not close issue #188. It authenticates exact
target metadata but does not yet prove the named targets against exact
source-tree bytes or load them. The broker still accepts independent `invoke`
and `output_digests` callbacks. After the blocked parent is green, the next
dependent packets must:

1. structurally resolve both signed targets against an exact source revision,
   tree and source digest without importing arbitrary caller-selected code;
2. produce a retained verification receipt bound to this signed target
   authority and projection;
3. construct a guarded executable registry from that verified receipt;
4. require the broker to consume the exact registry binding before
   `begin_effect`, with no loose callback production path.

No change to `main` or `experimental`; no merge, promotion, OwnerApproval,
PromotionReceipt, issue closure or Gate transition.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Evidence: prepared deterministic tests, independent source review and mutation
campaign; exact-head execution blocked by issue #67.
