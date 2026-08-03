# G0-ATT-13A — Shared-authority Source Tree CAS Port

## Purpose

This packet ports the bounded source-tree behavior from the earlier exploratory
branch without replacing the selected Gate-0 artifact authority. It is the
immutable candidate substrate required before an isolated Attempt lifecycle can
be wired.

It performs no Attempt execution, provider call, owner approval, promotion or
primary-checkout mutation.

## Topology decision

The earlier `g0/source-tree-cas` branch replaced `kernel.artifacts` with a second
combined CAS implementation. The selected linear stack already owns canonical
`ArtifactRef`, artifact locators and shared tree identities in
`daedalus.kernel.artifacts`.

This packet therefore adds only `daedalus.kernel.source_trees` and imports the
existing `ArtifactRef` and locator function. It deliberately exports no second
locator parser or digest authority. Existing import paths remain unchanged;
new source-tree types are additive kernel exports.

## Contract and identity

`SourceTreeManifest` binds:

- one exact 40- or 64-character source revision;
- deterministic sorted regular-file entries;
- exact raw blob SHA-256, byte size and executable bit;
- mandatory `.git` and `.daedalus` exclusions;
- case-insensitive path uniqueness and file/child conflict refusal;
- provenance containing the unique retained blob identities.

Duplicate file contents are valid and share one CAS object while retaining both
manifest paths.

## Persistence boundary

`SourceTreeStore` provides:

- SHA-256 sharded objects addressed through the shared `ArtifactRef`;
- temporary-file write, fsync and atomic hard-link publication;
- no-follow descriptor reads where supported;
- path/descriptor identity and stable metadata checks;
- bounded reads with a one-byte overflow sentinel;
- digest recomputation on every object read;
- exact canonical manifest bytes and duplicate-key refusal;
- staged all-or-nothing materialization into a destination that does not exist.

The CAS root is refused when it is equal to or contained by the captured source
root. Capturing a candidate therefore cannot write into the source or primary
checkout.

## Adversarial review

Separate source-review tests pin:

- reuse of `kernel.artifacts` rather than a second locator authority;
- the external-store fence before traversal and publication;
- mandatory metadata exclusions and unique provenance inputs;
- staged materialization with no destination replacement;
- absence of Git, subprocess, provider, lease, owner or promotion authority;
- address recomputation after descriptor-stability checks.

Behavioral tests cover deterministic capture, duplicate contents, exact
materialization, revision drift, store-inside-source refusal, symlinks, file and
total bounds, object corruption, noncanonical and duplicate-key manifests,
existing destinations and path collisions.

The bounded mutation campaign attacks the external-store fence, mandatory
metadata exclusions, symlink refusal, canonical manifest wire and CAS digest
recomputation.

## Deliberate remaining boundary

This packet does not create an Attempt workspace owner, lifecycle ledger,
restart/replay decision, Effect Lease, runtime manifest, sandbox execution or
Candidate FourfoldSnapshot. The next packet must own an external workspace
parent, materialize one exact manifest, bind one canonical Attempt and persist
start/terminal state before any runtime executes.

GitHub Actions issue #67 remains an external exact-head execution blocker while
hosted jobs terminate before Step 1 without logs or artifacts. Such runs are not
represented as test, mutation, platform, packaging or Gate evidence.

Iron Plan: **ALIGNED BY SCOPE; EXECUTION PENDING**  
Iron Gate: **0**  
Promotion: **not requested**
