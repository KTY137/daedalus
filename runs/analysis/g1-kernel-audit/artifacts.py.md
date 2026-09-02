# daedalus/kernel/artifacts.py  (119 lines)

Base 54f09753. Static read-only. Auditor: parent (W4 slice, subagent cap hit).

## What the file is for

The mechanical content-addressed identity layer: `ArtifactRef` (a digest/locator
pair that validates its own consistency), `store_canonical_json` (persist a
canonical-JSON payload under its digest), and `digest_file_tree` (a
symlink-refusing deterministic tree digest).

## Axis 1 — docstring truth

### Checked and TRUE

- `:3-5` "This module contains no domain policy. It provides the **single**
  mechanical implementation for `sha256` artifact locators, canonical JSON
  persistence, and deterministic read-only file-tree digests." Verified for the
  "no domain policy" half: there is no branching on mission, lane, or approval
  state anywhere in the file. The "single implementation" half is a universal I
  did **not** fully enumerate repo-wide — `source_trees.py` has its own CAS
  writers (`put_bytes`, `materialize_tree`), though they store *blobs and trees*
  rather than canonical JSON, so they do not contradict this claim on its own
  terms. Flagging the incompleteness rather than asserting the universal.
- `:31` `ArtifactRef` — "An exact digest/locator pair with **mechanical equality
  validation**." Verified: `__post_init__` (`:36-44`) validates the digest
  (`_sha256`), validates the locator (`_artifact_locator`), and then requires
  `_locator_sha256(locator) == digest` (`:39-42`), raising
  `ArtifactIdentityError` otherwise. The pair genuinely cannot be constructed
  inconsistent.
- `:83-87` `digest_file_tree` — "Digest a regular-file tree **without following
  symlinks**… Rejecting symlinks keeps the digest independent of external
  filesystem state." Verified: `:95-98` raises on `path.is_symlink()` before any
  read, and `:99-100` skips non-files. The claim is implemented by *refusal*,
  not by silently following or silently skipping — the correct choice, and it
  matches the strong containment pattern found elsewhere in the tree.
- `:67` `store_canonical_json` — "Persist canonical JSON under its digest and
  **refuse content collisions**." Verified at `:74-76`: if the path exists and
  its bytes differ from what we are about to write, raise. Real check, not a
  comment.

No overclaims found.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:72` `directory.mkdir(parents=True, exist_ok=True)` | FILESYSTEM_WRITE | none | no |
| `:78` `path.write_bytes(raw)` | FILESYSTEM_WRITE | none | no |
| `:75` `path.read_bytes()`, `:101` `path.read_bytes()` | read | n/a | n/a |

No subprocess, no network, no `os.environ`. Two unregistered filesystem writes —
consistent with the audit-wide finding that only 4 of 108 `EntrypointSpec` rows
target `daedalus.kernel.*` and none covers the CAS writers.

## Axis 3 — unreleased resources

Clean. `write_bytes` / `read_bytes` are `Path` convenience methods that open and
close internally. No connections, locks, or temp objects held.

## Axis 4 — validator gaps (W4 class)

### Checked — `store_canonical_json` CANNOT traverse, and this is the good pattern

`:73` builds the path as:

```python
path = directory / f"{ref.sha256}.json"
```

`ref.sha256` is not caller-shaped: it is computed locally from the payload
(`canonical_sha(body)` at `:70`) and then passed through `ArtifactRef.from_sha256`
→ `_sha256`, which enforces `^[0-9a-f]{64}$` (`canonical.py:26`). A 64-character
lowercase-hex string contains no `/`, no `\`, no `.`, and no `:`, so the
interpolation is traversal-proof **by the shape of the validator**, not by luck.

This is exactly the contrast the W4 theme needs: the same f-string-into-path
construction that is a weak spot in `attempt_contracts.py:68` (where the
interpolated value is `_identifier`-validated and admits `.`, `/`, `:`) is
completely safe here because the value is digest-validated. The defect class is
not "f-strings in paths" — it is "which validator guards the interpolated
value." W4's report and this dossier agree on that framing.

`digest_file_tree` uses `path.relative_to(directory)` (`:97`, `:104`) after
`Path(root).resolve()` (`:89`), so the recorded paths are contained by
construction.

## Axis 5 — dead / duplicate

Not separately assessed; every symbol in `__all__` (`:112-119`) is a documented
public API and `ArtifactRef` is used pervasively across the kernel
(`attempt_contracts.py`, `attempt_ledger.py`, `source_trees.py`, `offload_lease.py`).

## Additional finding

### CONFIRMED — the canonical-JSON CAS write is NOT atomic, while its sibling CAS writer is

`:74-78`:

```python
if path.exists():
    if path.read_bytes() != raw:
        raise ArtifactIdentityError("content-addressed artifact collision")
else:
    path.write_bytes(raw)
```

`path.write_bytes` is a plain create-and-write. A crash, disk-full, or kill
between create and complete write leaves a **truncated file at a
content-addressed path** — a filename asserting a SHA-256 that its contents do
not have. Content-addressed storage's whole invariant is that the name proves
the bytes.

The failure is also **sticky rather than self-healing**: on the next attempt the
`path.exists()` branch is taken, the truncated bytes are compared against `raw`,
they differ, and the function raises `ArtifactIdentityError("content-addressed
artifact collision")` — permanently, for that digest, until someone deletes the
file by hand. The error message would send a reader hunting a hash collision
rather than a torn write.

Secondarily, `exists()` → `write_bytes` is a TOCTOU: two processes storing the
same payload can both take the `else` branch and write concurrently. Same
content, so the end state is benign, but the interleaved writes are what produce
the torn file above.

The repository already has the correct pattern in the sibling CAS writer:
`source_trees.py::materialize_tree` (`:650-680`) stages into a
`tempfile.mkdtemp` directory, writes with `open("xb")` + `flush` + `os.fsync`,
then `os.replace` — atomic — and `policy/ledger.py:977-981` likewise does
`tmp.write_text(...)` + `os.replace(tmp, self.path)`. So two of the three
durable writers in this kernel are atomic and this one is not.

Severity: MEDIUM. Not a security boundary and not reachable by an attacker, but
it can permanently poison one CAS entry and report it under a misleading name.
The fix is the pattern already used twice next door.
