# G1-IKARUS-07A — Provider executable pre-admission

## Goal

Advance Ikarus toward the broker-bound real-runtime parity item without creating
an Ikarus-local provider loader or bypassing Gate-0 provider identity controls.
This packet composes the existing canonical provider invocation, target
verification/structure, retained-receipt, persisted retention-effect, and Git
HEAD evidence into one immutable pre-admission receipt.

Hermes parity motivation: Ikarus already has the sessionless one-shot request,
resource bounds, policy-projected tool scope, and a bridge to canonical Effect
requests. A real LLM runtime must now be selected by authenticated provider and
adapter identity rather than by an arbitrary callback. The canonical Daedalus
provider stack already supplies most of that evidence; this packet makes its
cross-bindings explicit before any guarded loader is allowed to exist.

## Exact inputs

`build_provider_executable_pre_admission` accepts exact instances of:

- `ProviderInvocationResolutionReceipt`;
- `ProviderExecutableTargetVerificationReceipt`;
- `ProviderExecutableStructureReceipt`;
- `ProviderTargetReceiptRetentionCompletedEvidenceReceipt`;
- `ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt`;
- `RepositoryHeadRevisionReceipt`.

The builder canonical-round-trips every component, then requires one exact
source revision, provider/adapter/implementation identity, runtime effect
subject, retained provider-target receipt, invocation authority/contract,
registry descriptor, target manifest/projection, adapter artifact/config digest,
and both signed Python target source identities. It independently reconstructs
the canonical `ProviderInvocationIdentityProjection` digest from the invocation
resolution before accepting the structure receipt.

## Deliberate authority boundary

The output explicitly records that the prerequisites are composed and that the
source revision is still repository HEAD, but keeps all of the following false:

- repository bytes executed;
- provider execution allowed;
- automatic re-execution allowed;
- callback seam removed;
- broker invocation performed;
- effect start authorized;
- OwnerApproval/promotion/Gate transition authorized.

The module imports no process, network or dynamic-loader API and accepts no
callable. Static review tests enforce that boundary.

## Why this is a separate packet

`ProviderExecutableStructureReceipt` intentionally says
`source_revision_verified_against_git_head=False` and
`provider_execution_allowed=False`. The retained target receipt and its
completed retention Effect also remain evidence rather than executable
authority. Jumping directly from those inert receipts to `run_runtime_provider`
would preserve the exact loose-callback substitution problem tracked by issue
#188. This packet instead creates one content-addressed, inspectable prerequisite
that a later guarded executable loader can require.

## Tests

Focused tests cover:

- successful composition and canonical round-trip;
- adapter-config substitution;
- invocation-identity projection substitution;
- stale repository HEAD;
- retained provider-target receipt substitution;
- signed target source substitution;
- authority-claim escalation in serialized receipts;
- exact-type rejection for subclassed evidence;
- AST review proving no loader/process/network imports and no provider/effect
  execution calls in the builder.

CI also runs the existing invocation-resolution, executable-structure,
retention-completed-evidence, retention-effect-terminal-evidence, and repository
HEAD regression suites on Python 3.10 and 3.12.

## Deferred next slice

G1-IKARUS-07B should implement the canonical guarded executable registry/loader
that consumes this receipt and proves the exact loaded executable bytes/objects
before the broker's durable `begin_effect`. Only after that proof should
`run_runtime_provider` lose its production `invoke`/`output_digests` callback
parameters. Recovery must remain callback-free and replay must remain inert.
