# G1-IKARUS-28 — Anchor the path-based vision forms on a bytes observation seam

Packet ID: G1-IKARUS-28
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-24 (handle-anchored adapter, still HOLD for replacement
crash reconciliation), G1-IKARUS-25 phase 2 (file fence lift, independent review
in progress), G1-IKARUS-CV-01 (`daedalus/runtimes/computer_vision.py`)
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb` (re-measured
2026-09-05 over the working-tree plan file). The base revision is the branch head
in the session git snapshot, inherited from G1-IKARUS-24/25.
Status: **DRAFT, baseline recorded, build not started.**

## Primary acceptance claim

Path-based vision (`vision.match`, `vision.changes`, and the `path` form of
`vision.inspect` / `vision.ocr`) can read workspace image bytes through the same
handle-anchored, reparse-refusing, checkpointed adapter that G1-IKARUS-24 built
for file tools — never through a re-opened pathname — and the seam refuses
anything that is not a PNG or JPEG, so text and secrets cannot reach a vision
observation through it. The release fence is **not** lifted here: phase 1 builds
and tests the seam behind the standing fence, phase 2 lifts it only after
independent review.

Current state this replaces: `ComputerService._read_bytes`
(`daedalus/runtimes/computer.py:327-336`) calls `refuse_workspace_path_io()`
(`daedalus/kernel/policy/computer.py:102-104`) unconditionally at `computer.py:328`,
so every path form is dead code behind the fence.

## Scope

In scope, phase 1: `daedalus/runtimes/computer_files.py` (add
`WorkspaceFiles.read_bytes` and the `ImageBytes` record; no change to any
existing method), `tests/runtimes/test_computer_files.py`,
`tests/runtimes/test_computer_vision_paths.py` (this packet's baseline), and
this packet.

In scope, phase 2 only (after independent review): `daedalus/runtimes/computer.py`
(`_read_bytes` routes to the seam; the projection at `:71-91`; the
`path_io_release_lock` text at `:185-186`), `daedalus/kernel/policy/computer.py`
(`RELEASE_DISABLED_TOOLS` at line 48; the observation-only exact-argument-set
check at `:91-99`; a new `max_image_bytes` field),
`tests/kernel/test_computer_policy.py`, `tests/runtimes/test_computer_service.py`,
the fence inventory assertion in `tests/test_ikarus_computer_autonomy.py`,
`docs/IKARUS_COMPUTER.md`.

Forbidden, both phases: `daedalus/runtimes/computer_vision.py` and
`computer_ocr.py` (owned by G1-IKARUS-CV-01; this packet supplies bytes, it does
not change decoding), the file-tool boundary logic in `computer_files.py`
(`_open_chain`, `_checked`, `_create`, `_replace`, `_move`), `computer_context.py`,
the mission loop, schedule, shell, plan, instructions, `apps/web`, effect
registry rows, ledger, promotion. No capture, camera, or new egress.

## Contracts and behavior

Proposed seam, on the existing adapter, observation-only:

    WorkspaceFiles.read_bytes(name: str, *, tool: str, args: Mapping) -> ImageBytes

`ImageBytes` is a frozen record `(data, path, sha256, image_format)`. Behaviour,
each item reusing an existing verified mechanism:

1. **Admission for the real tool.** `self.policy.admit(tool, args)` with the
   caller's actual vision tool and arguments — never a synthesized `file.read`.
   `admit` (`policy/computer.py:223-235`) re-checks the owner grant, the release
   fence (line 228) and the lexical rules for `path`, `template`, `before` and
   `after` (lines 229-231). `execute` restricts itself to `FILE_TOOLS`
   (`computer_files.py:658`), so `read_bytes` is a parallel entrypoint with its
   own tool set, not a widening of `execute`.
2. **Handle-anchored open.** `_components` / `_target` / `_open_chain`
   (`computer_files.py:684`, `:704`, `:728`) then `_file` (`:722`) — the same
   `_checked` open (`:450-466`) with `FILE_OPEN_REPARSE_POINT` and attribute
   refusal. Reparse points, 8.3 aliases (components come from the requested text,
   `:687-690`), escapes, protected and reserved names, and hard links
   (`_regular`, `:772-773`) refuse exactly as for `file.read`.
3. **Checkpoint before the read.** `_admit_observation` (`:760-764`) runs
   `self.checkpoint()` and the in-place proof before any byte is taken; `_read`
   re-proves in-place after (`:1086`, `:1091-1092`). `read_bytes` reuses both, so
   cancellation, deadline, kill switch and policy drift land at the same point as
   `file.read`.
4. **Explicit image bound, not the text bound.** `_regular` (`:774`) bounds at
   `policy.max_file_bytes`, default `1_048_576` (`policy/computer.py:118`). That
   is a *text* disclosure bound: a 1920×1080 screenshot routinely exceeds it, so
   reusing it makes the path forms useless in practice, while silently raising it
   widens an authority the owner configured. Proposal: an adapter constant
   `IMAGE_OBSERVATION_MAX_BYTES = 8 * 1024 * 1024`, pinned equal to
   `VisionLimits.max_image_bytes` (`computer_vision.py:95`, validated 64 B … 64 MiB
   at `:100`) so the seam never hands the decoder bytes it would refuse anyway,
   plus a new owner-visible `ComputerPolicy.max_image_bytes` field with that
   default which may **lower** but never raise it. Effective bound:
   `min(policy.max_image_bytes, IMAGE_OBSERVATION_MAX_BYTES)`.
5. **Content sniff — PNG and JPEG only.** Refuse unless the bytes begin with the
   PNG signature or a JPEG SOI. Deliberately narrower than "PNG/JPEG/BMP/WebP":
   `_header_dimensions` (`computer_vision.py:122-186`) accepts only PNG (`:124`)
   and JPEG, ending at `:186` with "Only encoded PNG and JPEG bytes are
   supported", so admitting BMP or WebP would pass more non-text byte shapes for
   zero capability gain. Anything else — UTF-8 text included — refuses as
   not-an-image, which is what keeps `.env`, keys and prose off this path. The
   secret floor (`secret_floor_rule`, applied to text at `computer_files.py:1097`)
   is a text rule and does **not** subsume this: the sniff, not the floor, fences
   the image seam.
6. **Observation-only.** No `_EFFECT_TOOLS` membership (`:68`), no
   create/rename/unlink, no `effect_state`. Nothing to reconcile after a crash.
7. **Windows-only, like the rest of the adapter.** `_effect_host_available`
   (`:71-73`) gates effects; observations currently do not. Because §7.2 makes a
   wrong image a wrong *coordinate*, and POSIX cannot pin the open chain,
   `read_bytes` refuses off Windows too, and the phase-2 projection reports the
   path forms unavailable there via `_release_unavailable_reason`
   (`computer.py:112-139`).

Phase 2 service side: `_read_bytes` routes to the seam and returns `.data`; the
vision result gains an `image_sources` list of `(path, sha256, bytes,
image_format)` records so §7.2 coordinate provenance names the exact input
bytes. `vision.match` calls the seam twice (image and template,
`computer.py:369`); `vision.changes` twice (`:354`).

What admits the `path` forms **today**: nothing executes them.
`_validate_arguments` (`computer.py:94-109`) accepts a lone `path` — the
exactly-one-source rule is at `:100-101` — but `enforce_release_tool_fence`
(`policy/computer.py:80-99`) then refuses: `vision.match` and `vision.changes`
by membership in `RELEASE_DISABLED_TOOLS` (line 48, checked at `:87-88`), and
`vision.inspect` / `vision.ocr` by the exact-argument-set check at `:96-99`,
which admits only `{"observation_id": <non-empty str>}`. The projection hides
them too (`_release_tool_spec`, `computer.py:73-74`, `:83-85`).

## Acceptance matrix

Refusals are phase 1 (seam-level, behind the standing fence); positives are
phase 1 at the seam and phase 2 end-to-end.

| Kind | Case | Expected |
| --- | --- | --- |
| refuse | Junction / symlink / reparse point at any component | refuse via `_checked`; no bytes |
| refuse | 8.3 alias for a long name | refuse; requested text drives traversal |
| refuse | `..`, absolute, drive/stream colon, protected or reserved name | refuse before any handle (`policy.path`) |
| refuse | Hard-linked image | refuse (`_regular`, `st_nlink != 1`) |
| refuse | Non-image bytes (UTF-8 text, `.env` renamed `.png`, zero bytes) | refuse as not-an-image; no bytes returned, nothing logged |
| refuse | Oversize image (> effective bound) | refuse; no full read into memory |
| refuse | Refusing checkpoint (cancel / deadline / kill switch / policy drift) | refuse; no bytes |
| refuse | Parent renamed between open and read | refuse "changed during the observation" |
| refuse | Non-Windows host | refuse at the public seam |
| refuse | Ungranted or fenced tool | refuse in `policy.admit`; no lease |
| refuse | §7.2 sensitive image | an image the owner has not authorized for model context must not be returned — shape decided by review question 4 |
| pass | `vision.match` with a workspace template | image and template bytes both arrive via the seam; a unique match returns coordinates with the frame provenance CV-01 already produces |
| pass | `vision.changes` between two workspace images | changed regions returned; both `image_sources` records retained in the result |
| pass | `vision.inspect` / `vision.ocr` `path` form | dimensions / words returned with `image_sources` provenance |
| pass | Digest stability | `ImageBytes.sha256` equals the digest `file.read` reports for the same file |

## Migration and rollback

Phase 1 is additive: rollback deletes `read_bytes`, `ImageBytes` and their tests;
nothing else changes and the fence never moved. Phase 2 rollback restores
`vision.match`/`vision.changes` to `RELEASE_DISABLED_TOOLS`, the observation-only
exact-argument-set check, the projection, and the `refuse_workspace_path_io()`
call at `computer.py:328`. No stored grant, lease, ledger row or evidence record
is rewritten in either direction; owners who already granted vision tools regain
nothing until phase 2 is green, because the fence was never a grant.

## Evidence, expected failures and review

Gate 1 required evidence (Plan §11), with applicability stated honestly:

| Evidence | Applies | Note |
| --- | --- | --- |
| Real adapter execution | yes | real files on a real NTFS volume, no mocked backend |
| Verified postconditions | partly | an observation has no postcondition; the in-place proof before and after the read is the equivalent obligation |
| Policy refusal | yes | ungranted tool, fenced tool, lexical refusals, non-Windows |
| Stale-target handling | yes | parent renamed between open and read |
| Cancellation | yes | refusing checkpoint returns no bytes |
| Timeout | yes | deadline via the same checkpoint |
| Crash recovery | **no** | observation-only: no effect, no reserved artifact, nothing to reconcile. This is the reason the packet is separable from the G1-IKARUS-24 HOLD |

Baseline, measured 2026-09-05 on Windows 11 with `.venv/Scripts/python.exe -m
pytest -p no:cacheprovider -q tests/runtimes/test_computer_vision_paths.py`:
**14 passed, 14 xfailed in 39.80 s** (parametrized cases counted individually;
0 xpassed, so no proposed behaviour exists by accident). The plain tests pin
today's refusals: fence inventory, `enforce_release_tool_fence` for all four
vision tools including `vision.match`'s observation form, `policy.admit` refusing
a granted-but-fenced tool, `_read_bytes` refusing with the exact fence message
before touching the workspace, the projection hiding the path forms,
`_validate_arguments` accepting the shape the fence then refuses, the absent
seam, and the 1 MiB-vs-8 MiB bound mismatch. The strict xfails are the
acceptance tests above; each names what is missing. Expected build outcome: the
xfails turn green and the two tests that pin absence
(`…_has_no_bytes_observation_seam`, `…_refuse_workspace_path_io_is_the_only_gate…`)
are deleted with a note, not weakened.

Expected failure during the build: the checkpoint test passes trivially until
`read_bytes` really calls `_admit_observation`, so the build must run the
mutation "remove the checkpoint call" and show the suite red.

Review questions for the independent reviewer:

1. Does `read_bytes` as a second public entrypoint create any path that reaches
   the traversal helpers without `policy.admit`, given `execute` guards only
   `FILE_TOOLS` (`computer_files.py:658`)?
2. Is the magic sniff a real fence, or can a crafted file be both valid PNG and
   a secret carrier (e.g. secrets in an ancillary PNG chunk or JPEG comment)
   that the decoder ignores but a vision-language model would read? If so, does
   the seam need a re-encode rather than a sniff?
3. Is raising the effective read bound from `max_file_bytes` (1 MiB) to 8 MiB an
   authority widening that requires an explicit owner confirmation under Plan
   §4.1, or is a new `max_image_bytes` field with a documented default enough?
4. §7.2 says sensitive images must not enter model context without policy
   authorization. A workspace PNG that happens to show credentials passes every
   check in this packet. Does the seam need an owner-scoped image-source
   allowlist, or is the workspace boundary the authorization?
5. Should `vision.match` keep its `observation_id` form fenced? Today the whole
   tool is disabled (`RELEASE_DISABLED_TOOLS`, line 48), so lifting the fence for
   the path form also lifts a desktop-observation form that has never executed.
   Related: does the phase-2 `image_sources` record disclose workspace layout
   beyond what the tool arguments already carry?
