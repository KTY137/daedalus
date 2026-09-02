# daedalus/editor_context.py

## 1. Size and shape

626 lines (`daedalus/editor_context.py:1-627`). 6 classes
(`EditorContextError`, `EditorContextRefused`, `UnknownEditorContext`,
`UnknownEditorSession`, `_Session` (a `@dataclass`), `EditorSessionRegistry`),
21 top-level functions. Module-level state/singletons:
- `SESSIONS = EditorSessionRegistry()` — `editor_context.py:617`, a
  process-local module-level singleton instance holding an in-memory
  `dict[str, _Session]` guarded by a `threading.Lock`. This is real
  module-level side effect at import: instantiating the registry object (its
  `__init__` just sets up an empty dict and a lock, no I/O).
- Compiled regexes `_SHA256_RE`, `_REVISION_RE` — `editor_context.py:41-42`,
  cheap, no I/O.
- Constants: `SCHEMA`, `CAPSULE_SCHEMA`, `CONTEXT_PREFIX`, `CAPSULE_PREFIX`,
  `MAX_SELECTION_CHARS`, `MAX_DIAGNOSTICS`, `DEFAULT_CONTEXT_TTL_S`,
  `DEFAULT_SESSION_TTL_S`, `ALLOWED_SOURCES`, `ALLOWED_COMMANDS`
  (`editor_context.py:31-40`).

No file reads, env reads, registry mutation, or network happen at import time.
`_artifact_root()` (`editor_context.py:69-74`) reads `os.environ.get(
"DAEDALUS_EDITOR_CONTEXT_DIR", "")` and resolves a `Path`, but only when
called — it is a function body, not module-level code, and it does not create
the directory (no `mkdir` in that function; directory creation happens
lazily inside `store_canonical_json`, called elsewhere).

## 2. What it does

`daedalus/editor_context.py` validates and persists immutable, TTL-bound
"editor context" artifacts — an explicit text selection from one file in one
registered project, checked byte-for-byte against the actual file and Git
revision, then content-addressed and written via the shared
`kernel.artifacts.store_canonical_json` implementation. It composes accepted
context references into a bounded "context capsule" after re-verifying each
one is still fresh (same base revision, same file hash, not expired) and
running the outbound text through `sensitivity`'s egress/secret-floor rules
for the target lane. It also runs a process-local, TTL-bound
`EditorSessionRegistry` that issues bearer tokens to editor adapters
(VS Code/OpenVSCode) and queues/serves a small fixed vocabulary of navigation
commands (`reveal_location`, `open_diff`) — explicitly, per its own docstring
(`editor_context.py:3-8`), it "owns no workflow authority" and "cannot write
files, run shells, enqueue work, change policy, or approve/promote
candidates."

## 3. Who imports it (MEASURED)

**TOTAL: 5** importers across the git-tracked tree, all forms searched:
`from .editor_context import`, `from daedalus.editor_context import`, `from
daedalus import editor_context`, `import daedalus.editor_context`, `from . import
editor_context`.

Per-layer breakdown: flat (daedalus/) 2, `daedalus.interfaces.http` 2, tests 1.
**All 5 are MODULE-LEVEL — zero deferred**, matching the independent AST
cross-check in the task brief exactly.

| File:line | Form | Layer | Scope |
| --- | --- | --- | --- |
| `daedalus/conversation_requests.py:20` | `from . import conversation, editor_context, ikarus_os` | flat | MODULE-LEVEL |
| `daedalus/web_api.py:29` | `editor_context,` inside `from . import (...)` (`web_api.py:21-32`) | flat | MODULE-LEVEL |
| `daedalus/interfaces/http/effects.py:17` | `editor_context,` inside `from ... import (...)` (`effects.py:9-18`) | interfaces/http | MODULE-LEVEL |
| `daedalus/interfaces/http/read.py:14` | `editor_context,` inside `from ... import (...)` (`read.py:8-15`) | interfaces/http | MODULE-LEVEL |
| `tests/test_editor_context.py:9` | `from daedalus import editor_context, projects` | tests | MODULE-LEVEL |

Correction against a plausible false positive: `daedalus/ikarus_os.py` matches
a naive grep for the string `editor_context` (`ikarus_os.py:294,1666`), but
those are **not imports** — they are dict-key assignments
(`envelope["editor_context"] = dict(context_receipt)`), so `ikarus_os.py` is
**not** counted as an importer. Verified by reading `ikarus_os.py`'s import
block directly — no `editor_context` import exists there.

No runtime-string registration of `daedalus.editor_context` was found in
`daedalus/spine/effect_boundary.py` (it is not a CLI entrypoint target).

## 4. What it imports (MEASURED)

All MODULE-LEVEL (no deferred imports in this file):

- `daedalus.kernel.artifacts` — `editor_context.py:25` (`from .kernel.artifacts
  import ArtifactIdentityError, store_canonical_json`), target layer **kernel**.
- `daedalus.projects` — `editor_context.py:26` (`from .projects import
  load_project, resolve_repo_root`), target layer **flat/unclassified**.
- `daedalus.sensitivity` — `editor_context.py:27` (`from .sensitivity import
  load_policy, secret_floor_rule, slice_egress_rule`), target layer
  **foundation** (declared FOUNDATION).
- `daedalus.spine.envelope` — `editor_context.py:28` (`from .spine.envelope
  import canonical_sha`), target layer **spine**.

Third-party: none. Stdlib only: `hashlib`, `json`, `os`, `re`, `secrets`,
`subprocess`, `threading`, `time`, `uuid`, `dataclasses`, `datetime`,
`pathlib`, `typing`.

## 5. Proposed destination

**orchestration**, confidence **medium**, with an explicit caveat below.

Argument from measured edges: `editor_context.py`'s *own* dependency graph
(kernel.artifacts, sensitivity, spine.envelope, plus the one flat
`projects` edge) is shaped like a shared kernel/spine-adjacent service, not
like an interface adapter — it does no HTTP request/response handling or
routing itself, it validates bytes against Git and a content-addressed store.
But its *importers* are split exactly 2 flat / 2 interfaces/http (section 3),
which argues against parking it inside `interfaces/http` specifically: two of
its four production callers (`conversation_requests.py`, `web_api.py`) are
flat modules that are not themselves interfaces code, and an interfaces-layer
service being imported by non-interfaces flat modules would be a layering
inversion (interfaces should be consumed by callers, not the reverse). Landing
it in `orchestration` — a layer none of the four boundary rules constrain as
a source, and which none of `kernel`/`spine`/`twin` currently import this
module through (section 6e) — is the destination that creates zero new
boundary violations today and matches "shared service both flat orchestration
code and the HTTP interface consume."

**Caveat / what would change my mind:** `editor_context.py`'s own imports
(kernel, spine, sensitivity) are otherwise exactly the shape of a `kernel` or
`spine` module. The only thing blocking a cleaner `kernel`/`spine` placement
is its module-level dependency on `daedalus.projects`, which is flat and not
on either allowlist (section 6c). If a future packet promotes
`daedalus.projects` to FOUNDATION (or `editor_context.py` is split so its
project-resolution call goes through a foundation-level seam instead of the
flat `projects` module directly), `kernel` or `spine` becomes the stronger,
more literal fit and I would revise this recommendation upward from
`orchestration`. Conversely, if `conversation_requests.py` and `web_api.py`
are themselves later reclassified into `interfaces` (plausible given their
names and their own role as request/API surfaces), then all 4 production
importers become interfaces-layer and `interfaces/http` becomes the better
fit instead.

**Split-boundary note:** nothing in this module is fused across two concerns
that need separating — `create_context`/`get_context`/`materialize_capsule`
(context capsule validation/storage) and `EditorSessionRegistry` (session/
token/command queueing) are two distinct responsibilities living in one file,
but both are consumed by the same importer set and both have the identical
kernel/spine/sensitivity/projects dependency shape, so there is no boundary
argument for splitting them into different target layers.

## 6. Boundary-rule check after the move

(a) Moved to `orchestration`: would any of its own imports be REFUSED? **No.**
No current rule names `daedalus.orchestration` as a constrained
`source_prefix` (only `kernel`, `spine`, `twin`, `runtimes` are sources), so
none of `editor_context.py`'s imports (`kernel.artifacts`, `projects`,
`sensitivity`, `spine.envelope`) would be mechanically refused for landing
under `daedalus.orchestration`.

(b) Does any CURRENT rule name this module by prefix? **No.** `daedalus.editor_context`
does not appear as a `forbidden_target_prefix` or `allowed_target_prefix` in
any of the four rules. Nothing breaks and nothing is silently un-forbidden —
but note `daedalus.orchestration` itself *is* named, as a forbidden target,
by all three of `kernel-no-outer-layers`, `spine-no-outer-layers`, and
`twin-no-outer-layers`. That is exactly why (e) below matters: moving this
module under the `daedalus.orchestration` prefix means any future
kernel/spine/twin import of it would be mechanically refused going forward —
which is the desired direction (kernel/spine/twin should not depend on this
module), not a regression.

(c) N/A for `kernel`/`spine`/`twin` as proposed destination — proposed
destination is `orchestration`, not one of the three allowlisted layers. (For
the record, if `kernel` or `spine` were chosen instead: `editor_context.py`'s
module-level `from .projects import load_project, resolve_repo_root`
(`editor_context.py:26`) would be REFUSED under both `kernel-no-outer-layers`'
and `spine-no-outer-layers`' allowlists — `daedalus.projects` is flat,
non-FOUNDATION, and absent from both `allowed_target_prefixes` lists.
Admitting it would need a reviewed diff of
`tests/test_architecture_boundaries.py::test_the_allowlists_cannot_grow_quietly`,
the same cost documented in `enforce.md` for the identical `daedalus.projects`
edge.)

(d) `daedalus.interfaces` as SOURCE is unconstrained by any current rule — true.
Since `orchestration`, not `interfaces/*`, is this dossier's proposed
destination, there is no laundering question to answer for *this* module's
placement. It is worth flagging generally (as `enforce.md` also notes) that
`daedalus.interfaces.http.effects` and `daedalus.interfaces.http.read` —
two of `editor_context.py`'s own current importers — themselves import
`daedalus.kairos.drafts` directly (`effects.py:10`, `read.py:8`,
`from ...kairos import drafts`), which is a `daedalus.kairos`-prefixed edge.
`daedalus.kairos` is forbidden for `kernel`, `spine`, and `twin` as a target,
but `daedalus.interfaces` is not a constrained source for anything and is not
a forbidden target for `kernel`/`spine`/`twin` either — so a future
kernel/spine/twin module importing `daedalus.interfaces.http.effects` would
not be refused by any of the four rules today, even though that import would
transitively reach `daedalus.kairos`. This is the same one-hop-launder shape
the `spine-no-outer-layers` rule's own rationale documents for the
`daedalus.schemas` facade case. It is a pre-existing risk in
`daedalus/interfaces/http/*`, not something this module's move creates or
worsens, since `editor_context.py` itself never imports `daedalus.kairos`.

(e) **Destination is orchestration — mandatory check.** `kernel`, `spine`, and
`twin` all forbid `daedalus.orchestration` as a target
(`kernel-no-outer-layers` and `twin-no-outer-layers` list it explicitly;
`spine-no-outer-layers` lists it explicitly too). Measured: **zero**
`kernel`/`spine`/`twin` modules currently import `daedalus.editor_context` —
all 5 measured importers (section 3) are flat, interfaces/http, or tests, none
under `daedalus.kernel`, `daedalus.spine`, or `daedalus.twin`. So moving this
module under `daedalus.orchestration` turns zero currently-green edges into
violations; there is no import to fix or grandfather in.

## 7. Dead-code signals

Not low/zero-importer — 5 measured importers, all module-level, spanning two
production layers (flat, interfaces/http) plus a dedicated test file
(`tests/test_editor_context.py`). The module's own docstring
(`editor_context.py:1-8`) is explicit about its bounded contract and reads as
a deliberately scoped, actively maintained service, not an abandoned one.
Searched: all import forms above via `git grep` restricted to `*.py`; no
`console_scripts` entry in `pyproject.toml` names it (only `daedalus` and
`daedalus-chip` are registered — neither is this module); no bare-string
`"daedalus.editor_context"` registration was found in
`daedalus/spine/effect_boundary.py`'s `EntrypointSpec` list; no entry for it
in `docs/architecture/shim-registry.json`; git log shows its origin at
`151b8d18` ("chore(wip): freeze Gate-1 dirty tree before hierarchy refactor"),
i.e. it entered the tree as part of the same Gate-1 hierarchy-refactor freeze
this dossier task is itself part of — no prior consumer was removed since,
because there is no prior version.

**Label: LIVE.**
