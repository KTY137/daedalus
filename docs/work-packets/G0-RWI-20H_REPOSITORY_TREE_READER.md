# G0-RWI-20H — Exact Read-Only Repository Tree Snapshot

## Parent and purpose

This packet is stacked on exact parent
`df69e4ef1c50a634e34bd1fa5df5273df7ac51a8` from
`g0/repository-write-guard-manifest-linear`.

It introduces a narrow repository-tree responsibility boundary for later
semantic replay. The new primitive reads one normalized repository-relative
regular UTF-8 file and returns an immutable snapshot containing exact bytes,
SHA-256, and size. It is additive only: the existing source-anchor verifier is
not migrated in this packet, so no predecessor behavior or import path changes.

## Read boundary

The reader:

- requires a real non-symlink `pathlib.Path` repository root;
- accepts normalized repository-relative POSIX paths only;
- rejects absolute, drive-qualified, dot-component, duplicate-separator,
  backslash, newline, missing, directory, and symlink paths;
- resolves containment beneath the selected root;
- opens read-only and uses `O_NOFOLLOW` where supported;
- bounds source size to 16 MiB;
- compares lstat/open/read/final path identities and the root identity;
- detects replacement before open, mutation during read, and incomplete reads;
- rejects NUL-containing and non-UTF-8 source bytes;
- binds the returned bytes, size, and SHA-256 in a frozen typed snapshot.

The module contains no write, process, network, repository-mutation, effect,
OwnerApproval, promotion, or Gate authority.

## Adversarial batch

Prepared behavior coverage includes exact deterministic snapshots, malformed
path grammar, invalid roots, missing/non-regular targets, root/file/parent
symlink refusal, NUL and encoding faults, bounded size, replacement before open,
descriptor identity mutation, incomplete reads, and detached snapshot
digest/size refusal.

A separate AST/source review checks read-only authority, normalized path fences,
no-follow descriptor use, unconditional close, root/file identity checks,
bounded reads, exact snapshot binding, and absence of Gate/effect claims. Eight
bounded mutants attack drive paths, symlinks, pre-open and post-read identity,
incomplete reads, UTF-8 validation, NUL validation, and snapshot digest binding.

An isolated module harness reports `25 passed`; all eight bounded mutants were
killed. This is preparatory author-side evidence only, not exact-head repository,
supported-platform, packaging, independent-human, or Gate evidence.

Exact-head CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash
seeds, predecessor regressions, mutation, Iron Plan verification, full suite,
package build, and isolated-wheel import. GitHub Actions issue #67 continues to
produce zero-step jobs without logs or artifacts.

No merge, promotion, OwnerApproval, or Gate transition is requested.
