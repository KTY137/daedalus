# G1-DESKTOP-PRERELEASE-012 - Publish the final v0.1.3 Gate-1 desktop prerelease

## Classification

- Master Plan: `ALIGNED`
- Target gate: `1`
- Promotion: forbidden; this is a product prerelease, not candidate promotion
  or a Gate transition.

## Reason for the patch release

The first v0.1.2 trusted-main run proved the Windows, Linux, and macOS bundle
lanes but exposed one publisher-environment defect: the tested selector imports
the canonical effect boundary, while the publish job had neither installed the
package nor placed the checkout root on `PYTHONPATH`. After adding that explicit
path, run `33321096897` published the five-asset `desktop-v0.1.2` prerelease at
`ac6f33c0f04984c6946e76a4532734b650c62182`. That release is retained as the
pipeline proof and is not overwritten. The repository then retained the final
dynamic child-nonce race tests, the sealed 07D4 broker cutover, the hosted
Windows/Ubuntu runtime-admission matrix, and the bounded ignition-receipt
closure. The next honest package identity for final delivery is therefore
`0.1.3`.

## Change

- align Python, npm, Tauri, Cargo, and Cargo-lock package identity on `0.1.3`;
- reuse the tested five-asset publisher from G1-DESKTOP-PRERELEASE-011;
- expose the checked-out `daedalus` package to the selector through the
  publisher job's explicit `PYTHONPATH`, without rerunning build hooks under a
  write-capable token;
- retain the unsigned Windows and ad-hoc-signed/not-notarized macOS warning;
- publish only after the exact trusted-main Windows, Linux, and macOS matrix
  passes.

## Acceptance

1. Package manifests and the desktop packaging contract all report `0.1.3`.
2. Frozen-backend nonce smoke and desktop contract tests pass on Windows,
   Linux, and macOS at one exact trusted-main revision.
3. `desktop-v0.1.3` is a prerelease targeting that revision.
4. The release contains exactly one `.exe`, `.AppImage`, `.deb`, `.dmg`, and
   `.app.tar.gz` asset, with no expanded application internals.
5. The installed Windows application reports version `0.1.3`, starts its
   nonce-authenticated child backend, and exposes a working Managed Bridge
   status.

## Rollback

Do not overwrite or retarget an existing release. Revert the version bump and
retain hosted failures and already published prereleases as historical
evidence.
