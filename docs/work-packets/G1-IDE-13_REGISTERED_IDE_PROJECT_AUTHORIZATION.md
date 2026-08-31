# G1-IDE-13 - Registered IDE project authorization

Status: builder-verified for the primary claim; independent review/system acceptance pending
Classification: `ALIGNED`
Active gate: **Gate 1 - Renovation and owner-directed Genesis**
Owner: repository owner; no automatic merge, promotion, or Gate transition
Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
Dependencies: G1-IDE-11 canonical registration and G1-IDE-12 row transaction
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 11
Master-plan SHA-256:
`711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary claim

The desktop IDE start HTTP route accepts one exact registered project name,
resolves that row's native canonical root at the server boundary, and only
then calls the existing desktop runtime manager. Browser-supplied filesystem
paths, traversal, unknown names, stale roots, foreign-platform roots, and
unverifiable rows are refused before any OpenVSCode process start, Docker
inspection, or read/write bind mount.

The project registry remains the existing `projects/*.json` authority. This
packet adds no registry, policy store, event store, candidate identity, or
promotion path.

## Reproduced baseline

- `apps/web/src/cockpit/IdeWorkspace.tsx` passed the selected row's
  `repo_root` to `startDesktopIde`; the browser request therefore contained
  `{"project":"C:\\work\\atlas"}` rather than the registered name.
- `install_web_integration` forwarded `body.project` directly to
  `DesktopRuntimeManager.ensure_ide`. The focused baseline test passed while
  asserting that the arbitrary path `C:\\work\\demo` reached the manager.
- The manager's Docker path validation checked only that the supplied path was
  an existing local directory before constructing a read/write bind mount. It
  did not establish that the path belonged to a registered row.

Baseline command:

`py -3.13 -m pytest -q tests/test_desktop_runtime.py -k web_integration_exposes_ide_start_and_stop_routes`

Result: `1 passed, 86 deselected`; this is retained RED security evidence, not
acceptance evidence.

## Exact scope

In-scope paths are exactly:

- `daedalus/projects.py`;
- only the IDE-start branch/error mapping in `daedalus/desktop_runtime.py`;
- `apps/web/src/api.ts` and `apps/web/src/cockpit/IdeWorkspace.tsx`;
- `tests/test_ide_project_authorization.py` and the focused route test in
  `tests/test_desktop_runtime.py`;
- `apps/web/tests/ide.spec.ts`;
- this work packet.

Chat, SSE, other desktop services, manager lifecycle behavior, IDE endpoint
policy, Docker image policy, project registration/rewrite semantics, the
master plan, and the amendment chain are forbidden scope.

## Frozen authorization contract

1. The browser sends `{project: <ProjectRow.name>}` and never derives IDE
   authority from `ProjectRow.repo_root`.
2. The server validates the identifier as one exact direct registry stem;
   separators, traversal, NUL, empty/non-string input, aliases, and unknown
   names fail closed.
3. Resolution uses the existing fixed registry lock and exact-row verifier.
   The row must be a direct non-symlink JSON object with one valid root.
4. The stored root must be absolute under the current host's path semantics,
   resolve to an existing directory, and retain the same canonical identity.
   A foreign-platform or stale row stays listable but cannot start an IDE.
5. Only the server-resolved canonical path is passed to `ensure_ide`. The
   manager keeps its internal path interface for trusted local callers, but
   the HTTP route never forwards request path text to it.
6. Invalid/unknown/unavailable project input returns HTTP `400`; registry lock
   or row-integrity unavailability returns `503`. Neither path calls the
   manager.
7. The existing CENTRAL `web.mutations` effect boundary remains outside this
   route. No effectful entrypoint or registry target is added.

## Acceptance matrix

1. A registered name resolves to its canonical current-host root and starts
   native/Docker manager handling with that root.
2. The selected browser row posts its `name`, including when its displayed
   `repo_root` is a Windows path.
3. Absolute POSIX/Windows paths, relative path strings, traversal, missing
   names, non-strings, and unknown names invoke neither manager nor subprocess
   nor Docker boundary.
4. Row JSON `name` cannot act as an alias for its filename stem.
5. Missing directories, files, foreign-platform absolute roots, symlink rows,
   malformed JSON, and lock failure fail closed before manager invocation.
6. Existing manager-level canonicalization, loopback endpoint, immutable
   Docker ownership/ID, strict cleanup, and native no-runtime-download tests
   remain green.
7. Focused project and desktop Python tests, the IDE Playwright spec, the web
   production build, and `git diff --check` pass.

## Budget, rollback, and residuals

Evaluation is deterministic and local: no model, provider, network, runtime
download, Docker start, or paid service is required. Rollback removes the
resolver, route wiring, browser name payload, and focused tests; project rows
and desktop configuration require no migration or rollback.

The HTTP authorization is point-in-time. A non-cooperating local process with
permission to rewrite the project registry or filesystem can still race the
OS; this packet does not advertise the registry lock as a complete host
security boundary. The runtime revalidates directory existence immediately
before use, and all cooperating registry writers preserve root identity.

## Evidence handoff

Builder verification on Windows 11 / CPython 3.13.5 / Node 22:

- `py -3.13 -m pytest -q tests/test_ide_project_authorization.py
  tests/test_desktop_runtime.py`: `91 passed`.
- `npm.cmd ci --ignore-scripts --prefer-offline`: 106 locked packages
  installed, zero audit vulnerabilities; no lockfile change.
- `npm.cmd run build`: TypeScript and Vite production build passed;
  `2186` modules transformed. Generated `dist` output was deliberately not
  retained in this source packet.
- Focused real-Chromium Playwright selection for the registered-name request:
  `1 passed`.
- Full `ide.spec.ts` under the Vite development harness: `17 passed, 2
  failed`. The retained failures are pre-existing WIP-checkpoint behavior in
  the initial project-list race (`getCount` was already 2) and tablet CSS
  visibility (`hidden` element computed visible); neither exercises the
  registered-name request or its modified assertion.
- The dependent project-registration/row-rewrite selection is blocked during
  collection by the frozen parent importing missing
  `daedalus.kernel.campaigns`. The new authorization suite intentionally has
  no `web_api` import and remains independently executable; the missing parent
  module is not repaired in this packet.
- `py_compile` passed for all changed Python implementation/test modules and
  `git diff --check` passed.

No OpenVSCode process, Docker command/mount, live provider, network service,
merge, promotion, push, or owner decision was performed. The first failed
build attempt without worktree-local `node_modules` and the two unrelated
browser failures remain named rather than being reported as green.
