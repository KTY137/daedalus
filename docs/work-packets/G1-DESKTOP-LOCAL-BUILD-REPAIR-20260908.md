# G1-DESKTOP-LOCAL-BUILD-REPAIR-20260908

Iron Plan: ALIGNED. Iron Gate: 1.
Owner: repository owner, explicit instruction to repair `.local/build_desktop.ps1`
until it runs successfully, including a configurable version/installer name.
Base: `24e229c0f34e5404bc219637b646386529f82035` plus existing local changes.
Plan SHA-256: `04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`.

## Scope and acceptance frozen before implementation

- Repair the owner-selected local PowerShell build driver; reuse the canonical
  backend build and smoke entrypoints and retain their policy admission.
- Let the owner set the build version in the script or with `-Version`;
  synchronize all package and lock version mirrors without dependency changes.
  Keep installed application identity `Daedalus` / `dev.daedalus.desktop`.
- Correct the reproduced Windows path comparison failure in the desktop test;
  retain settings HTTP, canonical authority-root and lifecycle assertions.
- Remove a hardcoded current-version expectation from the mirror consistency
  test so deliberate version changes can build, preserving mirror equality.
- Preflight validates without source edits or running build stages. Invalid
  versions and incompatible expected versions refuse before mutation.
- A complete default run must pass web checks, desktop contracts, frozen backend
  smoke, Rust format/tests and NSIS packaging. Check the fresh installer, hash
  and result record. Record skipped platform tests and any remaining failures.
- Independently review the script and verify version edits in an isolated
  metadata fixture. Local build evidence is not hosted CI or release admission.

No policy, plan, amendment, runtime authority, install, publication, Git merge or
promotion changes. Preserve unrelated dirty source files and earlier logs.
This is a direct repair of the owner's named local script; build outputs stay
under local build directories. Rollback is restoration of this task's script
backup and exact scoped edits only. Do not reset the shared checkout.

## Baseline

Owner log: MSVC selected successfully; web stages passed. Desktop contracts:
1 failed, 221 passed, 14 skipped. Failure is only Windows directory spelling
`pytest-of-Administrator` versus `pytest-of-administrator` in a string assertion.
Independent focused reproduction: 1 failed in 2.04 seconds.
The existing script checks five version mirrors but cannot set a version;
native stderr is formatted as PowerShell errors even for successful stages.

## Verification and handoff

Completed 2026-09-08. The script now selects MSVC by default, exposes `Version`
(editable default `0.1.6`) and optional `ReleaseName`, synchronizes all eight
version fields, and preserves original changed metadata in per-run backups.
It uses an isolated Python build environment, an exclusive local build lock,
UTF-8 plain-text native logs, checked native exit codes, immediate smoke-port
selection and unique output directories. It verifies the copied installer's
SHA-256 against the built file and rechecks all version fields before success.
Neither installed application identity nor runtime implementation changed.

The desktop runtime test now derives its expected path from the resolved root,
preserving exact string and authority-root assertions. The packaging version
test retains equality across all eight fields and validates `x.y.z`, replacing
the fixed `0.1.6` literal. Preexisting Cargo.toml, web output, .gitignore and
session changes remain in the checkout; no Git commit or release was created.

### Actual final build

Command from repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .local/build_desktop.ps1
```

- Final script SHA-256:
  `3b328b80a63307764f9779cc1e817ce9dff9fb8b342918991484fdfcce7a2074`.
- Exit code 0; all 13 stages passed in 211.4 seconds. No skip switches used.
- Web: 549 app checks, 145 motion checks, TypeScript and production build pass.
- Desktop contracts: 222 passed, 14 skipped (host/platform capabilities).
- Frozen backend starts with the expected startup nonce, serves the cockpit
  and returns all six scene assets byte-identically.
- Rust: format check and 26 library tests pass; MSVC release and NSIS pass.
- Final run: `.local/builds/0.1.6/20260908T112646Z-msvc-d2f0191b/`.
- Installer: `Daedalus_0.1.6_x64-setup.exe`, 102,776,164 bytes; Windows file
  metadata confirms product `Daedalus`, version `0.1.6`.
- Installer SHA-256:
  `b3d6b1f69906fe6fda9bab76c1e38f3a0d9921c4ce95832aa58cd9cdf12f88ee`.
- `result.json` records the installer, actual eight versions, backend identity,
  source HEAD, dirty-tree status and logs. Full console log also retained at
  `.local/build-desktop-final-verification.log`.
- Earlier successful full run retained at
  `.local/builds/0.1.6/20260908T112024Z-msvc-e0edb08a/` (307.1 seconds).

### Independent and adversarial review

A separate agent performed read-only review and exercised the script in isolated
metadata fixtures: 84 checks cover nondefault `0.2.37` / `Demo-test`, eight-field
synchronization, unchanged unrelated bytes, original backups, nonmutating
preflight, invalid inputs, exclusive-lock refusal/release and environment
restoration. Additional faults verify native exit 7, missing executable, failed
log writes and blank stderr. Trailing-newline parameter admission was reproduced
and corrected with absolute regex anchors; all three parameters now refuse it.
`uv lock --check --offline` accepts the nondefault-version fixture (126 packages).
Review evidence is retained under
`.local/review-desktop-eb4180d7433d4dd48ab44a31e2988489/` in `review-result.json`,
`fault-review-result.json`, and `final-input-review.json`.

Scoped `git diff --check` passes. Master-plan SHA-256 remains unchanged.
Remaining limits: unsigned local installer built from the explicitly selected
dirty checkout; no installation/UI acceptance or hosted cross-platform CI run.
Existing Vite chunk-size and Rust unused-function warnings remain nonfatal.
This closes the local-script repair only, not release admission or Gate 1.
Original script backup: `.local/build-desktop-backup-20260908T131744/`.
