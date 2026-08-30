# G1-DESKTOP-PRERELEASE-011 - Publish the validated v0.1.2 desktop bundles

## Classification

- Iron Plan: `ALIGNED`
- Target gate: `1`
- Promotion: forbidden; this packet publishes a product prerelease, not a
  candidate-tree promotion or a Gate decision.

## Problem

The trusted-main Tauri run at revision
`98833bf71e53eec184a7db2a065aec1469a9b8c7` built and retained the Windows
NSIS, Linux AppImage/deb, and macOS DMG/app workflow artifacts successfully.
The final publisher failed and no `desktop-v0.1.1` tag or release exists. The
next package identity is `0.1.2`; the failed `0.1.1` build is not reused.

`actions/download-artifact` extracts the macOS app artifact as an application
directory. The publisher's unfiltered `find ... -type f` then hands every file
inside that application directory to `gh release create`. The public v0.1.0
release instead has five desktop asset kinds: `.exe`, `.AppImage`, `.deb`,
`.dmg`, and `.app.tar.gz`. v0.1.2 must restore exactly that matrix without
publishing app internals.

## Change

- archive exactly one top-level `.app` on the macOS runner before workflow
  artifact upload, preserving executable modes and symlinks;
- select only top-level `.exe`, `.AppImage`, `.deb`, `.dmg`, and `.app.tar.gz`
  files for publication;
- require exactly one of each of those five kinds and unique release-asset
  basenames;
- keep that selection in one tested helper used by the workflow;
- trigger desktop CI for `packaging/**` changes;
- run packaging, desktop runtime, startup-nonce, and project-registration tests
  in both desktop build lanes;
- align npm, Tauri, and Cargo package metadata on `0.1.2`;
- keep the existing unsigned/notarization warning and prerelease status.

## Acceptance

1. Exactly one top-level `.app` produces one `.app.tar.gz` whose only top-level
   member is that application bundle; zero or multiple bundles are refused.
2. A synthetic artifact tree containing an expanded `.app` selects exactly the
   five v0.1.0 asset kinds and no app-internal file.
3. Missing asset kinds and duplicate basenames are refused before release
   creation.
4. Packaging, desktop runtime, startup-nonce, and project-registration tests
   pass in both desktop build lanes.
5. `packaging/**` changes trigger this workflow and every desktop package
   manifest reports `0.1.2`.
6. Hosted Windows, Linux, and macOS builds pass on one exact trusted-main
   revision.
7. `desktop-v0.1.2` exists as a prerelease and names that exact revision with
   exactly the five required desktop assets.

## Evidence

- Previous hosted run: platform builds passed; publish step failed.
- v0.1.0 public release asset inventory: one each of `.exe`, `.AppImage`,
  `.deb`, `.dmg`, and `.app.tar.gz`.
- Local selector, workflow-contract, project, and desktop matrix:
  `96 passed in 2.70s`.
- Workflow YAML plus changed Python, JSON, and TOML parsing: passed.
- Exact-head hosted run and published v0.1.2 release: pending and deliberately
  outside this packet edit.

## Rollback

Revert the workflow, selector, tests, packet, and aligned package-version bump.
Existing workflow artifacts and any already published release remain
authoritative historical evidence.
