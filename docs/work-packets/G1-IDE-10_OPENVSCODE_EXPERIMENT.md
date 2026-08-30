# G1-IDE-10 — OpenVSCode project workspace experiment

Status: implemented; Windows package acceptance in progress
Classification: `EXPERIMENT`
Active gate: Gate 1 — Renovation ignition slice
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 8
Master-plan SHA-256: `7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704`
Base revision: `98833bf71e53eec184a7db2a065aec1469a9b8c7`
Expiry: remove or promote through an owner-reviewed follow-up packet if the
IDE cannot remain loopback-only, project-bound, and lifecycle-managed.

## Primary claim

Daedalus can expose a complete, MIT-licensed OpenVSCode Server workspace for a
human-selected registered project without creating another orchestration store,
candidate identity, evaluator, or promotion path.

This is an isolated product experiment because a full human IDE is outside the
active Gate-1 Renovation slice. Direct human edits in the IDE are not Daedalus
candidate execution and carry no automatic nomination, evidence, merge, or
promotion authority.

## Baseline reproduced

- The cockpit lists registered projects but has no project-registration action.
- The cockpit has map and conversation views only; no complete editor/terminal.
- The desktop runtime manages the existing bridge and Ollama processes but no
  IDE process.
- Focused Python baseline: 37 passed, 1 unrelated failure caused by the stale
  hard-coded `C:/Users/nukei/Desktop/agent_env` fixture expectation.
- Web production build: passed before this packet.

## Acceptance matrix

1. `POST /api/projects` accepts an existing directory plus an optional name,
   canonicalizes it, rejects traversal/invalid input with HTTP 400, and writes
   one minimal project registry file atomically.
2. Re-registering the same canonical directory is idempotent and does not
   widen repository policy.
3. The cockpit project picker exposes an accessible “Projekt hinzufügen” flow
   even when no projects exist, uses the native desktop folder picker when
   available, retains a typed-path browser fallback, refreshes the list, and
   selects the result.
4. A third `IDE` view opens the selected registered repository inside the same
   Daedalus GUI and never silently substitutes another project's path. Windows
   host paths are represented by the verified Docker mount `/home/workspace`.
5. OpenVSCode binds only to a numeric loopback endpoint, is started and stopped
   by the existing desktop runtime lifecycle, and is not downloaded at runtime.
   Windows defaults to the pinned Docker adapter; native mode stays explicit.
6. Missing/unreachable OpenVSCode is rendered as an explicit state with a
   recovery action; it is never presented as a working IDE.
7. Native folder selection exposes only `dialog:allow-open` to the `main`
   window at `http://127.0.0.1:8765/*`. The capability is limited to Windows
   and macOS; Linux uses the typed-path fallback so an IDE iframe cannot inherit
   dialog IPC through Linux's documented iframe-origin limitation.
8. The existing TypeScript build plus focused project, desktop-runtime, API,
   and cockpit tests pass; unrelated baseline failures remain named separately.
9. Tauri requests nonce-authenticated canonical runtime cleanup before killing
   its Python child. Docker cleanup is time-bounded, failure-propagating and
   targets the fully inspected immutable container ID rather than a mutable name.

## Frozen inputs and budget

- Upstream: `gitpod-io/openvscode-server`, MIT, pinned release `1.109.5`.
- Release archive SHA-256:
  `b433bf4f0227321a7014d8460d10a8f958adc0f45aa79bd889e84e65e8f88363`.
- Local Windows image: `daedalus/openvscode-server:1.109.5`, built by
  `packaging/openvscode/Dockerfile`; Docker Desktop remains an external host
  prerequisite and the running application performs no pull/build/download.
- Native folder picker: official Tauri dialog plugin 2.7.2, MIT or Apache-2.0.
- Network: loopback only at runtime; no automatic GitHub download.
- Storage: existing `projects/*.json` registry and existing desktop settings;
  no new event store or orchestration database.
- Evaluation budget: focused deterministic tests and one production web build;
  no model calls and no paid services.

## Forbidden scope

- no automatic merge, promotion, candidate execution, or evaluator access;
- no non-loopback IDE bind and no unauthenticated remote IDE exposure;
- no copied Microsoft branding or proprietary Marketplace distribution;
- no new top-level product mythology, state store, or parallel control plane;
- no plan, amendment-chain, policy, or evaluator edits;
- no runtime download or execution of an unpinned GitHub artifact.

## Rollback

Remove the IDE view/component, OpenVSCode desktop-service fields/routes, and
project-registration POST while retaining the existing read-only project list.
Registered project JSON files are user data and are not deleted automatically.

## Retained negative evidence

- The first installed-package lifecycle check exposed that force-killing the
  Python sidecar left its Docker IDE container alive. That release candidate
  was rejected. The repair routes Tauri shutdown through a nonce-authenticated
  `manager.close(strict=True)` call before the bounded child termination.
- An abrupt operating-system/process crash still cannot guarantee cleanup of
  an external Docker container. Status reads do not adopt it; the next explicit
  IDE start verifies a matching orphan completely before adopting/reusing it.
  No crash-cleanup guarantee is claimed.

## Builder verification

- `58` focused Python checks ran: `57` passed; the one failure is the retained
  pre-existing `project_tct` fixture rooted at `C:/Users/nukei/...` rather than
  this machine.
- Project registration, desktop runtime, desktop packaging and startup nonce:
  `60 passed` after immutable-ID/strict-shutdown coverage was added.
- Web production build: passed.
- Motion contract: `136/136 passed`.
- Real Chromium acceptance against a live loopback Daedalus server:
  `3/3 passed` for empty-registry add, shortcut/project binding, and honest
  offline-to-start behavior.
- Rust/Tauri unit checks: `4/4 passed`, including the authenticated shutdown
  request and an absolute hung-response budget. Rust release compilation and
  NSIS generation passed before the shutdown defect was found; the corrected
  package is being rebuilt and must repeat installed-app acceptance.
- Live upstream smoke: the pinned Linux x64 v1.109.5 release matched GitHub's
  published SHA-256
  `b433bf4f0227321a7014d8460d10a8f958adc0f45aa79bd889e84e65e8f88363`,
  returned HTTP 200 without `X-Frame-Options` or a `frame-ancestors` directive,
  and rendered an embedded `.monaco-workbench` with eight workbench parts in
  headless Chromium.
- Real Docker adapter acceptance on this host: image `1.109.5`, HTTP 200,
  canonical source checkout mounted read/write at `/home/workspace`, and strict
  cleanup by the inspected 64-hex container ID. The temporary container was
  removed after measurement.
