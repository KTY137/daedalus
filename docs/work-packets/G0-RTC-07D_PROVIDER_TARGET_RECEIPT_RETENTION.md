# G0-RTC-07D — Provider Target Receipt Retention

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Exact parent: `4d67a562343d920da589d75cfecc8109657061fa`  
Promotion: **not requested**

## Primary acceptance claim

A signed, inert `ProviderExecutableTargetVerificationReceipt` that has been
re-authenticated against its exact invocation authority, target authority,
source-tree manifest and source bytes can be retained durably without creating
a second workflow database or granting provider execution authority.

The retention path uses the existing canonical `SpineLedger` as intent and
terminal authority and the existing `SourceTreeStore` as content-addressed
artifact authority. It does not import, load, resolve or invoke the provider
targets named by the receipt.

## Exact transition

The writer performs this ordered transition:

1. require exact receipt, Event-Store and CAS authority types;
2. verify the signed receipt against the exact target/invocation authorities,
   registry, execution request, target manifest, source-tree reference and
   independently re-read source bytes;
3. derive the receipt artifact address from canonical receipt JSON;
4. persist one canonical Event-Store intent keyed by that digest;
5. publish the exact canonical receipt bytes to the existing CAS;
6. re-read and rehash the published object;
7. append one terminal Event-Store event binding the artifact digest;
8. strictly re-read the Event-Store rows and CAS bytes before returning.

A unique partial index on the canonical `intents` table serializes the exact
receipt identity. It creates no receipt-specific table and no second database.

## Restart and replay

A crash after the intent but before CAS publication leaves a visible pending
intent. A crash after CAS publication but before terminal append leaves the same
pending intent plus an identifiable immutable object. Re-submitting the exact
signed subject may finish that same transition. A completed replay re-verifies
the signed receipt and retained bytes, returns the original intent/artifact
identity and performs no CAS write or terminal transition.

A failed CAS call is not converted into a terminal failure because publication
may have occurred before the caller observed the exception. The intent remains
pending reconciliation. This preserves the unknown-outcome semantics rather
than guessing that an external filesystem effect did not happen.

## Protected topology

The primary checkout must be a real, symlink-free directory. The receipt CAS,
canonical Event Store and primary checkout are pairwise disjoint. The retention
path never creates, opens for write, or otherwise mutates a path beneath the
primary checkout.

## Adversarial matrix prepared

The focused tests cover:

- exact retention followed by inert replay;
- crash after CAS publication and restart completion;
- invalid receipt signature before Event-Store or CAS writes;
- substituted retained CAS bytes;
- noncanonical/tampered Event-Store rows;
- primary-checkout overlap;
- subclass and duck-typed authority substitution;
- source-order review proving authentication → intent → CAS → terminal order;
- absence of provider loader, process, network, approval and promotion authority.

A bounded mutation runner attacks pre-authentication writes, primary-checkout
containment, publication-before-intent, CAS-readback removal and unique-index
removal. The workflow requests Ubuntu and Windows on Python 3.10 and 3.12 with
two hash seeds, predecessor regressions, full suite and isolated-wheel import.

## Deliberate remaining boundary

This packet is a migration step, not Gate-0 closure. The retention method is a
new local filesystem-writing entrypoint. It is not production-admissible until a
separate short packet classifies it in the canonical effect registry and then a
dependent packet consumes a persisted Effect Lease before this method can
become `CENTRAL`.

The retained receipt remains explicitly inert. A later green line must build a
guarded executable registry only from authenticated retained material and exact
installed/repository bytes, then make the runtime broker consume that binding
before `begin_effect`. Production `invoke` and `output_digests` callback seams
remain open in the parent broker and issue #188 remains unresolved.

GitHub Actions issue #67 continues to terminate hosted jobs before Step 1. The
workflow and tests in this packet are prepared evidence only until an exact-head
run records real steps, logs and artifacts. No LLM/source assertion is treated
as executable evidence.
