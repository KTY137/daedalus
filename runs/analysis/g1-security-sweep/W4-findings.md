# W4 — Write-boundary path handling: traversal and symlink escape

Scope: `C:/Users/Administrator/daedalus` @ `b3cc415b` (local `main`), read-only.
Excluded per brief: `vault/`, `.quarantine/`, `daedalus/lanes/`,
`.claude/worktrees/`, `.daedalus_worktrees/`, `build/`,
`apps/web/src-tauri/backend/`, `apps/web/src-tauri/target/`.

## Enumeration

Greps run (all from repo root, `daedalus/**/*.py` unless noted):

- `write_root|write_roots|allowed_paths|is_within|PathPolicy|bounded write|workspace isolation`
- `def .*(is_within|within_root|contains_path|_bounded|_contain|ensure_within|check_.*path|validate_.*path)`
- `\.relative_to\(|commonpath|os\.path\.abspath|startswith\(str\(|startswith\(root`
- `def _key|def canonical_path_identity`
- `shutil\.rmtree|shutil\.copytree|os\.remove\(|\.unlink\(|os\.replace\(|os\.rename\(`
- `zipfile|tarfile|extractall|ZipFile`
- `HIER-13` / `HIER_13` / `HIER13` (case-insensitive, whole repo)
- `attempt_id=` / `_identifier(` / `_repo_path(` across `daedalus/**/*.py`
- targeted reads of every hit below

**G1-HIER-13 anchor**: could not be found. `grep -ri "HIER.?13"` over the whole
repo (tracked files, `docs/`, `runs/analysis/`, the two sibling W2/W6/W8
findings files already on disk) returns zero matches, and no
`docs/work-packets/G1-HIER-13*` file exists (the `G1-HIER-*` series present
runs `01, 02A/B, 02, 03A-D, 04, 04B, 05, 06A-E, 07A-B, 08, 09, 10, 11, 12` and
jumps straight to `G1-UI-03`). I could not verify the "already-flagged"
symlink vector's exact shape and therefore could not exclude it by content —
only by the ID string, which does not exist in this tree. Everything reported
below was independently derived; if it duplicates the G1-HIER-13 vector, that
is not detectable from here (see "What I did not cover").

**Containment implementations found (distinct lexical/resolution strategies), 7:**

1. `daedalus/kairos/worktree.py::_is_within` (line 192) — **lexical only**
   (`os.path.normcase(os.path.normpath(...))`, `str.startswith`), deliberately
   documented as such (`"""True if child is parent or lies under it,
   lexically."""`). Used as one layer inside a much larger no-follow
   containment system in the same file (`_is_reparse_point`, `_path_identity`
   via `os.lstat`, resolved-form re-checks in `_require_allocated_worktree`
   step 4, `create_worktree`'s belt-and-braces resolved-root check). This is
   the most heavily adversarially-hardened file in the tree for this scope —
   see "What I did not report" below.
2. `daedalus/chip_design/manifest.py::_is_within` (line 136) — resolved
   (`canonical_path_identity` = `abspath` → `realpath` → strip `\\?\` prefix →
   `normcase`/`normpath`) + `os.path.commonpath`. Strong form.
3. `daedalus/gates/repository_write_artifact_cas.py::_is_within` (line 98) +
   `_real_directory` (line 78) — resolved with `strict=True`, explicit
   symlink rejection on both the leaf and the parent, lexical-vs-resolved
   equality check, descriptor-bound re-validation after read
   (`_revalidate_exact_path`). Read-only resolver, not a write boundary, but
   the strongest containment implementation found in this sweep.
4. `daedalus/desktop_runtime.py::_path_is_within` (line 72) — **weak form**:
   `os.path.abspath` (does NOT resolve symlinks/junctions), no `realpath`.
   Investigated and NOT reported as a finding: it filters `PATH` environment
   entries before spawning an Ollama child (line 86-99), not a write
   boundary, and its input is the parent process's own `PATH`, not
   candidate-controlled data. Out of scope by the brief's own class list, but
   named here since it matches the weak-form pattern verbatim.
5. `daedalus/kernel/attempt_contracts.py::_is_same_or_within` (line 75) —
   `candidate == parent or parent in candidate.parents`, always called after
   the caller has already run `.resolve(strict=True)` on both sides
   (`attempt_workspace.py`). Sound given that precondition.
6. `daedalus/gates/provider_target_receipt_retention_inventory.py::_contains_symlink`
   (line 251) — walks `path.parts` checking `.is_symlink()` per-component,
   no-follow. Sound for its stated purpose (retention *source* inspection).
7. `daedalus/kernel/contracts/canonical.py::_repo_path` (line 124) — not a
   filesystem check but the up-front string validator used for
   `writable_paths` and other declared-path fields: rejects absolute paths,
   any `..` path segment, and drive-qualified (`C:foo`) paths. **This is the
   one correct general-purpose path-safety validator in the contracts layer.**
   It sits in the same file as, and is bypassed by, F-W4-01 below.

**Write/delete sites traced:** `shutil.rmtree`/`copytree`, `os.remove`,
`.unlink(`, `os.replace(`, `os.rename(` matched in 28 files under
`daedalus/**/*.py`. Of these, the destructive-delete-with-derived-path class
was checked in `daedalus/kairos/worktree.py` (the recursive worktree
deleter — extensively hardened, see below), `daedalus/kernel/source_trees.py`
(`materialize_tree`, `os.replace(staging, target)` — the destination is
attacker-reachable via F-W4-01, though the *manifest entries within* the
staging tree are correctly bounded), and `daedalus/kernel/attempt_workspace.py`
(the caller that constructs the vulnerable destination). CAS-identity writers
(`daedalus/kernel/artifacts.py::store_canonical_json`,
`daedalus/kernel/offload_lease.py`'s evidence writers) use a validated
SHA-256 digest as the sole filename component and cannot traverse.

**Zip/tar extraction:** zero occurrences of `zipfile`/`tarfile`/`extractall`/
`ZipFile` as actual extraction calls anywhere under `daedalus/`. The one hit
(`daedalus/gates/repository_write_stdlib_delta.py`) is a static classifier
table that *names* those stdlib APIs as write-capable for an AST scanner; it
does not call them. **No zip-slip surface exists in this tree.**

---

## F-W4-01: Attempt workspace materialization trusts an attacker-shaped `attempt_id` for path construction, bypassing the repo's own path-safety validator

- **file:line**:
  - `daedalus/kernel/contracts/canonical.py:27` (`daedalus/kernel/contracts/attempts.py` re-exports `AttemptContract` from here) — weak validator definition (file has its own local copy of the regex; see grep below for the canonical one)
  - `daedalus/kernel/attempt_contracts.py:67-68` (`_workspace_relative_path`)
  - `daedalus/kernel/attempt_workspace.py:236, 247, 249-252` (`IsolatedAttemptCoordinator.prepare`)
  - `daedalus/kernel/source_trees.py:621-679` (`SourceTreeStore.materialize_tree`)
- **class**: traversal / weak-containment
- **severity**: HIGH (code-level defect CONFIRMED by reading; end-to-end attacker reachability PLAUSIBLE, not proven — see below)
- **status**: CONFIRMED for the defect chain itself, PLAUSIBLE for external exploitability

**Evidence.**

`AttemptContract.attempt_id` (and `mission_id`, `task_id`, `campaign_id`) is
validated only by `_identifier`, whose regex is:

```
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
```

(`daedalus/kernel/contracts/canonical.py:27`, confirmed by direct read). This
pattern accepts `.`, `/`, and `-` anywhere after the first character with **no
check that a `.` `.` pair forms a `..` path segment** — e.g.
`"x/../../../../../../tmp/evil"` fullmatches it (starts with alnum `x`,
every remaining character is in the allowed class).

`_workspace_relative_path` builds a path string directly from this field:

```python
def _workspace_relative_path(attempt: AttemptContract) -> str:
    return f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"
```

(`daedalus/kernel/attempt_contracts.py:67-68`)

`IsolatedAttemptCoordinator.prepare` then turns that string into a `Path` with
no `..`-segment check and no containment re-verification of the *result*:

```python
relative = _workspace_relative_path(attempt)
...
workspace = self.workspace_parent.joinpath(*relative.split("/"))
try:
    materialized = self.source_store.materialize_tree(
        input_tree.ref,
        workspace,
    )
```

(`daedalus/kernel/attempt_workspace.py:236-252`). The only containment checks
in this class (`_resolve_workspace_parent`, `_require_stable_workspace_parent`,
`_assert_disjoint`) are all applied to `self.workspace_parent` — the *fixed*
root — and are called **before** `workspace` (root + attacker-shaped
`relative`) is computed. Nothing re-checks `workspace` itself against
`primary_checkout` or `cas_root` after the join.

`materialize_tree` (`daedalus/kernel/source_trees.py:621-679`) receives this
`destination` and trusts it completely as the write target:

```python
target = Path(destination)
if target.exists() or target.is_symlink():
    raise SourceTreeCaptureError(...)
target.parent.mkdir(parents=True, exist_ok=True)
...
staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
...
os.replace(staging, target)
```

Its only containment check (`staging_root not in parent.parents`, line 661) is
scoped to *manifest entries inside the CAS tree being materialized* — it
bounds where blob content lands **inside `staging`**, never where `target`
itself sits relative to `workspace_parent`. `target.parent.mkdir(parents=True,
exist_ok=True)` will create every intermediate directory named by a `..`-laden
`destination`, and the final `os.replace(staging, target)` lands the
materialized candidate source tree there — potentially outside
`workspace_parent`, and (depending on how many `..` segments and what follows
them) potentially back inside `primary_checkout`, defeating the very
disjointness `_resolve_workspace_parent` establishes for the *root*.

**Contrast with the correct pattern already in this codebase.** The same file
(`daedalus/kernel/contracts/canonical.py:124-136`) defines `_repo_path`, used
for `writable_paths` and other declared-path fields, which correctly rejects
absolute paths and any `".."` segment:

```python
def _repo_path(value: Any, name: str) -> str:
    raw = _non_empty(value, name, max_length=500).replace("\\", "/")
    ...
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{name} must stay inside the declared workspace")
    ...
```

`attempt_id` is never run through this validator; only the weaker
`_identifier`. `daedalus/kairos/worktree.py::create_worktree` (line
998-1092) shows the correct treatment of an analogous attacker-shaped
`branch_name` — it lexically escape-checks *and* re-checks the *resolved*
form of the join result before ever creating a directory. `attempt_workspace.py`
does neither for the attempt-id-derived `workspace`.

**Reachability — what I could not establish.** I traced every call site of
`_workspace_relative_path` (exactly one: `attempt_workspace.py:236`, confirmed
by repo-wide grep) and every call site of `IsolatedAttemptCoordinator`
(production wiring in `daedalus/kernel/attempts.py`, which is a re-export
facade). I did **not** find, in the time available, the exact live code path
by which an `AttemptContract.attempt_id` value is populated from
lower-trust input (a model's free-text output, an Ikarus `WorkItem`
decomposition of user intent, or a CLI/API argument such as
`chip_design/cli.py:2033`'s `args.attempt_id`, which is validated by the same
weak `_identifier`). Per the master plan, attempt/work-item identifiers are
expected to be orchestrator-minted rather than raw user text, which would
narrow this to a defense-in-depth gap rather than a directly attacker-reachable
bug — but I did not verify that minting is always deterministic/safe, so I am
not claiming direct external reachability. What is CONFIRMED beyond doubt by
reading the code: (a) the validator accepts traversal-shaped identifiers, (b)
the one live consumer builds an unvalidated filesystem path from it, (c)
nothing downstream re-checks the result before creating directories and
calling `os.replace`.

**Reachability**: whoever can cause an `AttemptContract` to be constructed
with a crafted `attempt_id` (scope of that authority not fully traced in the
time available — see above).

---

## F-W4-02: Same weak identifier regex reused broadly; not confirmed to reach a second write site, flagged for follow-up

- **file:line**: `daedalus/kernel/contracts/canonical.py:27` (`_ID_RE`); same
  pattern duplicated verbatim or near-verbatim in `daedalus/chip_design/cli.py:568-575`,
  `daedalus/gates/repository_write_effect_lease.py:97-102`,
  `daedalus/runtimes/live_fault_collector.py:88-91`,
  `daedalus/runtimes/live_fault_attestation_issuer.py:80-83`,
  `daedalus/runtimes/host_fault_runner.py:64-67`,
  `daedalus/runtimes/fixture_fault_collector.py:92-95`,
  `daedalus/runtimes/fixture_fault_attestation_issuer.py:74-77`,
  `daedalus/runtimes/fault_matrix.py:71-74`,
  `daedalus/runtimes/fault_attestation_issuer.py:85-88`,
  `daedalus/runtimes/fault_attestations.py:62-65`,
  `daedalus/gates/baseline.py:449-452`, `daedalus/twin/extractors/contracts.py:20-23`,
  `daedalus/ikarus_oneshot.py:44-47`, `daedalus/ikarus_runtime_role.py:43-48`
- **class**: weak-containment (systemic pattern, not a single confirmed write-site bug)
- **severity**: LOW/INFO as reported (no second concrete write-site instance found)
- **status**: PLAUSIBLE — I confirmed the pattern is duplicated at least 14
  times across the tree, all sharing the same "`.`/`/`/`-` allowed, `..` not
  rejected" shape, but in the time available I only found ONE place
  (F-W4-01) where a value validated this way is later used to build a
  filesystem path with no downstream containment check. `chip_design/cli.py:2033-2034`
  passes CLI-argument `attempt_id`/`mission_id` through the same weak
  `_identifier` and constructs derived phase identifiers with
  `_phase_identifier`, but I did not find those derived identifiers used in a
  `Path`/`joinpath`/`mkdir` call within the file in the time available — flagging
  as a place worth a second pass rather than asserting a finding.
- **evidence**: regex bodies quoted above; not re-quoted per file for brevity.
- **reachability**: not established beyond F-W4-01.

---

## What I did not report (investigated, found sound)

- `daedalus/kairos/worktree.py` — the recursive worktree deleter
  (`_remove_tree_no_follow`) and `GitWorktreeManager` containment
  (`_require_allocated_worktree`, `_refuse_if_the_primary_checkout_moved`,
  `create_worktree`'s three-layer escape check). This is a symlink/junction
  no-follow implementation with per-syscall fresh `lstat` re-verification,
  explicit mutation-testing notes, and an honestly documented residual gap
  (the "move-in" attack, which involves no reparse point at all and is
  explicitly out of path-hygiene's reach — see its own docstring, lines
  50-71). I read the full 1562-line file. No new symlink-escape instance
  found here; this file is the strongest evidence in the tree of the pattern
  the brief calls "the G1-HIER-13 class" being done correctly.
- `daedalus/spine/containment.py` — Windows MIC (Mandatory Integrity Control)
  write-containment for the candidate-executing child process. Not a
  path-traversal/symlink-escape checker (out of this class), but its own
  docstring explicitly names the residual TOCTOU gap in `primary_tree.py`
  ("a junction swapped in between those two steps is NOT closed by Python")
  as an already-acknowledged, honestly-disclosed limitation — not a new
  overclaim.
- `daedalus/primary_tree.py` — the primary-checkout write fence. Resolves
  before comparing, checks both lexical and `st_dev`/`st_ino` identity,
  probes the nearest existing ancestor for a not-yet-created target. The
  TOCTOU gap between its `resolve()` and the actual write is explicitly
  named in `containment.py`'s docstring (see above) rather than concealed —
  does not qualify as an overclaim under the brief's definition.
- `daedalus/kernel/artifacts.py` (`store_canonical_json`, `digest_file_tree`) —
  filenames are exclusively validated SHA-256 hex digests; `digest_file_tree`
  explicitly rejects symlinks during the walk. Sound.
- `daedalus/gates/repository_write_artifact_cas.py` — read-only CAS resolver
  (explicit in its own docstring: "cannot publish, repair, fetch, delete,
  promote, or mutate"). Strongest containment implementation found in this
  sweep (resolved-vs-lexical equality, symlink rejection at leaf and parent,
  file-identity re-validation after open, `O_NOFOLLOW` on the read). Read all
  577 lines; no finding.
- `daedalus/desktop_runtime.py::_path_is_within` — weak form
  (`os.path.abspath`, no symlink resolution) confirmed by reading, but its
  one call site filters PATH-env entries before spawning Ollama, not a write
  boundary and not candidate-controlled data. Named in the enumeration above
  for completeness, not filed as a finding.
- No zip/tar extraction exists anywhere under `daedalus/` (checked above) — a
  clean negative for the zip-slip class.
- Windows-specific forms (8.3 short names, ADS `file:stream`, reserved
  device names, UNC/`\\?\`, trailing dot/space, drive-relative `C:foo`):
  `daedalus/chip_design/manifest.py::canonical_path_identity` explicitly
  handles the 8.3/long-name and `\\?\`-prefix cases (its own docstring names
  the 8.3 case; `_strip_extended_windows_prefix` handles the prefix).
  `_repo_path` (canonical.py:131-132) explicitly rejects drive-qualified
  (`C:foo`) relative-looking paths. I did not find or construct a test for
  ADS (`path:stream`) or reserved-device-name (`CON`, `NUL`) handling
  anywhere in the write-boundary code in the time available — absence of
  evidence, not evidence of absence; flagged under "what I did not cover".

## What I did not cover

- Did not build or run any code; all findings are static-read conclusions.
  F-W4-01's exploitability claim is bounded accordingly (CONFIRMED at the
  code level, PLAUSIBLE for external reachability).
- Did not trace the full production call graph from an Ikarus-compiled
  `WorkItem`/mission through to `AttemptContract` construction to determine
  the actual origin and trust level of `attempt_id` in the live (non-test)
  orchestration path — this is the single largest open question behind
  F-W4-01's severity.
- Did not exhaustively check every one of the 14 duplicate `_identifier`/`_ID_RE`
  copies (F-W4-02) for a second live write-site consumer; only
  `chip_design/cli.py` was spot-checked.
- Did not check Windows ADS, reserved-device-name, or trailing-dot/space
  handling anywhere outside `chip_design/manifest.py` and `_repo_path`.
- Excluded directories per the brief were not read at all (`vault/`,
  `.quarantine/`, `daedalus/lanes/`, worktree/build trees).
- Did not re-derive or verify the G1-HIER-13 vector's exact shape — the
  referenced note could not be located anywhere in this tree (see
  Enumeration). If another worker's shard has since written it, this
  worker's findings should be diffed against it for overlap before either is
  treated as final.
- Did not review `daedalus/kernel/attempt_execution.py` (2724 lines) or
  `daedalus/gates/repository_write_inventory.py` /
  `repository_write_source_anchor_semantics.py` /
  `repository_write_stdlib_delta.py` (558-920 lines each) line-by-line; only
  grepped for the write/delete/containment vocabulary in scope. A deeper pass
  on these four large files is the most likely place a second instance of
  F-W4-01's class would surface.
