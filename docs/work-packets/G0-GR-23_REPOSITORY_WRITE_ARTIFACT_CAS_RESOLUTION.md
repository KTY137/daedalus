# G0-GR-23 — Repository-Write Artifact CAS Resolution

## Exact parent

This packet stacks on `78a6271e8df6f15ce314f8aee5fe3b7bdb06d598` from `g0/repository-write-artifact-verifier-linear`. It advances issue #194 without modifying the existing byte verifier or forming a collection PR.

## Narrow authority

The packet adds a read-only resolver for one exact `artifact-locator:sha256` object in a fixed local CAS layout:

```text
sha256/<first two digest characters>/<remaining 62 characters>
```

The CAS root is bound to one source revision and must be an existing real directory disjoint from the Primary Checkout. Resolution accepts no caller path. It derives the sole object path from the retained locator digest, rejects redirected root/shard/object paths and hard-link aliases, opens the object read-only, bounds the read to 16 MiB, binds the opened descriptor identity, hashes the immutable bytes, and rechecks both descriptor and lexical path identity after reading.

The result contains exact immutable bytes and a canonical `RepositoryWriteArtifactResolutionReceipt` binding the artifact evidence, locator, content digest, CAS-root digest, derived relative path, file identity, size, modification time, source/tree revisions, checks and provenance. An exact JSON Schema is included.

## Adversarial corrections

The initial post-read inspection used `Path.stat()`. A path replaced by a symlink to the same retained inode could therefore preserve the compared inode tuple while changing the lexical authority path. The current resolver explicitly refuses a post-read symlink, parent redirection or object-path redirection before accepting the final identity.

The initial receipt separately validated locator and content digest but did not derive `relative_path` from that locator or enforce the resolver byte ceiling. Both are now receipt invariants. The immutable byte wrapper also requires byte-length equality with the receipt's file size.

## Prepared verification

The batch contains behavior coverage for exact resolution and round trip, missing objects without directory creation, byte substitution, stale revision, Primary-Checkout overlap, root/shard/object symlinks, hard-link aliases, oversized objects, descriptor substitution, path replacement, exact types, receipt substitutions and schema parity.

A separate AST/source review checks that the module imports no process, network, effect-execution or promotion authority; contains no publication or deletion calls; uses one read-only `os.open`; derives the path only from the locator digest; checks isolation and file identity before, during and after reading; and makes no release, trusted, OwnerApproval or PromotionReceipt claim. Eleven bounded mutants target the principal binding and bypass fences.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor regression, mutation, full suite, package build and isolated-wheel import.

Prepared tests and source review are not executable evidence. GitHub Actions issue #67 currently terminates hosted jobs before checkout/Step 1, so exact-head verification remains pending external CI.

## Deliberate boundary

This resolver does not publish, fetch, repair or delete CAS objects. It does not authenticate an artifact signer or trust bundle, compare the retained source tree with current Git HEAD, compose the resolution receipt with the G0-GR-22 byte-verification receipt, change the evidence index, issue a release receipt, merge, promote or change a Gate state.

No change to `main` or `experimental`; no automatic merge, OwnerApproval, PromotionReceipt or Gate transition.
