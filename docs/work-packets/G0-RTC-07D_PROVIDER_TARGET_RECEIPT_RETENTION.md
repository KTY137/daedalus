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
3. derive and validate the canonical receipt bytes and artifact address;
4. install and re-read the exact partial uniqueness invariant;
5. persist one canonical Event-Store intent keyed by the receipt digest;
6. publish the exact canonical receipt bytes to the existing CAS;
7. append one terminal Event-Store event binding the artifact digest;
8. strictly re-read the Event-Store rows and CAS bytes before returning.

Authentication and all pure local validation precede even the idempotent schema
write. The partial unique index is checked through `sqlite_master`; a foreign
same-name index is refused rather than trusted. No receipt-specific table or
second database is created.

## Restart, unknown outcomes and replay

A crash after the intent but before CAS publication leaves a visible pending
intent. A crash after CAS publication but before terminal append leaves the same
pending intent plus an identifiable immutable object. Re-submitting the exact
signed subject may finish that same transition. A completed replay re-verifies
the signed receipt and retained bytes, returns the original intent/artifact
identity and performs no CAS write or terminal transition.

An Event-Store exception is not treated as proof that a transaction failed. The
writer re-reads the exact effect key after both intent and terminal write errors.
A post-commit disconnect therefore recovers the persisted winner; a pre-commit
terminal failure remains `INTENDED` and explicitly requires replay. Likewise, a
failed CAS call is not converted into a terminal failure because publication may
have occurred before the caller observed the exception. This preserves unknown-
outcome semantics instead of guessing what an external write did.

## Protected topology

The primary checkout must be a real, symlink-free directory. The receipt CAS,
canonical Event Store and primary checkout are pairwise disjoint. The retention
path never creates, opens for write, or otherwise mutates a path beneath the
primary checkout.

## Adversarial matrix prepared

The focused tests cover:

- exact retention followed by inert replay;
- crash after CAS publication and restart completion;
- intent post-commit disconnect recovery;
- terminal pre-commit failure followed by replay;
- terminal post-commit disconnect reconciliation;
- invalid receipt signature before schema, Event-Store or CAS writes;
- substituted retained CAS bytes;
- noncanonical, duplicate-terminal and trace-substituted Event-Store state;
- foreign same-name uniqueness index;
- primary-checkout overlap;
- subclass and duck-typed authority substitution;
- concurrent same-subject retention with one canonical identity;
- independent source-order review proving validation → intent → CAS → terminal;
- absence of provider loader, process, network, approval and promotion authority.

A bounded mutation runner attacks pre-authentication writes, primary-checkout
containment, publication-before-intent, CAS-readback removal and unique-index
removal. The workflow requests Ubuntu and Windows on Python 3.10 and 3.12 with
two hash seeds, predecessor regressions, the declared test dependency set, full
suite and isolated-wheel import.

## Deliberate remaining boundary

This packet is a migration step, not Gate-0 closure. The retention method is a
new local filesystem-writing entrypoint. It is not production-admissible until a
separate short packet makes it visible to the canonical effect inventory and a
dependent packet consumes a persisted Effect Lease before this method can
become `CENTRAL`.

The retained receipt remains explicitly inert. A later green line must build a
guarded executable registry only from authenticated retained material and exact
installed/repository bytes, then make the runtime broker consume that binding
before `begin_effect`. Production `invoke` and `output_digests` callback seams
remain open in the parent broker and issue #188 remains unresolved.

GitHub Actions issue #67 continues to terminate hosted jobs before Step 1. The
workflow and tests in this packet are prepared evidence only until an exact-head
run records real steps, logs and artifacts. No LLM or static-review assertion is
treated as executable evidence.
