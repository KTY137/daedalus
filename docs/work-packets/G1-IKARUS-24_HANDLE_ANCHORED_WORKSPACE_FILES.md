# G1-IKARUS-24 — Handle-anchored workspace file adapter

Packet ID: G1-IKARUS-24
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: reviewed G1-IKARUS-17; G1-IKARUS-COMPUTER-01 v0.1.6 path-I/O
release fence and its retained ancestor-swap finding; existing `ComputerPolicy`
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Owner direction: continue building Ikarus into an autonomous computer
assistant (2026-09-05 conversation). Unrelated working-tree changes, including
the concurrent Codex work on packets 21–23, are retained; this packet adds
files only and edits no shared module.
Status: **HOLD for a file-tool fence lift**. Independent dormant-adapter review
revisions and a fresh focused Windows verification are complete. The current
two-rename replacement no longer overwrites a hostile target substitution,
but a process crash or power loss between its handle-bound renames can leave a
reserved backup/temporary without a service-owned reconciliation receipt or
recovery operation. Earlier Windows and isolated WSL/Linux measurements are
retained below as historical evidence, not relabelled as evidence for the
current revision. Service wiring and the v0.1.6 release fence stay unchanged.

## Primary acceptance claim

Workspace file operations can be performed without ever re-opening a checked
pathname: every component below the owner-configured workspace is opened
relative to the handle of its verified parent, links and reparse points are
refused at each step, and create, replace, mkdir and move execute relative to
that parent handle. On the Windows v0.1.6 target, opened effect parents and
effect targets also deny delete sharing, pinning them against a move outside
the workspace between admission and effect. The link-swap race retained in
G1-IKARUS-COMPUTER-01 therefore cannot redirect a Windows release effect
outside the workspace. This module grants no capability by itself; every call
re-admits through `ComputerPolicy`, any fence lift remains a separate packet,
and the public adapter has an independent Windows-only gate for write, mkdir
and move. POSIX observations remain measurable, but POSIX effects cannot pass
the public entrypoint.

## Scope

Allowed files: `daedalus/runtimes/computer_files.py`,
`tests/runtimes/test_computer_files.py` and this packet. Forbidden: the kernel
computer policy and its fence, the computer service, mission loop, schedule,
shell, conversation commands, plan, instructions, `apps/web`, and every file
another agent edits concurrently. No effect registry row, lease, ledger, CLI or
HTTP route changes.

## Contracts and behavior

`WorkspaceFiles(policy, checkpoint).execute(tool, arguments)` mirrors the
desktop and browser adapters and returns a JSON-safe observation for
`file.list`, `file.read`, `file.write`, `file.mkdir` and `file.move`. The
`checkpoint` is the trusted service's cooperative cancellation and
re-admission probe; it runs after the parent directory is open and before every
observation or effect. The public entrypoint calls `ComputerPolicy.admit`
itself, then re-validates argument shape, `expected_sha256` form, bounded size,
portable component syntax and the policy's lexical path rules. A direct caller
therefore cannot skip the owner grant or release fence. Read and write text
also pass the requested path and content through the secret floor inside the
adapter before disclosure or effect.

Traversal opens the workspace root, then each directory relative to its parent
handle, then the final object relative to the last directory handle. A
symbolic link, junction or other reparse point at any position refuses; a file
where a directory is expected, or the reverse, refuses; hard-linked files
(`st_nlink != 1`) refuse. After the checkpoint the open parent must still sit
at its expected name (Windows: `GetFinalPathNameByHandleW`; POSIX: `fstat`
against `lstat` device/inode), otherwise the operation refuses with "changed
during the operation" and no effect. After an effect the same identity is
checked again together with a read-back through the parent handle; drift
yields `postcondition_verified: false` plus a `detail`, never a silent success
at a name that no longer exists.

Windows backend: `NtCreateFile` with `OBJECT_ATTRIBUTES.RootDirectory` and
`FILE_OPEN_REPARSE_POINT` (a reparse point opens as itself and is then refused
by attribute), `FILE_DIRECTORY_FILE` / `FILE_NON_DIRECTORY_FILE` type
enforcement, `FILE_CREATE` for exclusive creation, `NtSetInformationFile`
`FileRenameInformation` with a `RootDirectory` handle and `ReplaceIfExists`
false for `file.move` and both replacement renames,
`FileDispositionInformation` to discard a failed temporary or retired backup
through its own handle, `NtQueryDirectoryFile` for listing, and `CreateFileW` with
`FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT` plus a final-path
equality check for the root. Every opened directory and observation file
denies delete sharing until verification. A newly created file or replacement
temporary denies both write and delete sharing. A move source does the same,
binding `expected_sha256` to the bytes and name moved by that open handle. A
replacement target also denies both write and delete sharing; the adapter can
still move it through the DELETE-capable handle it already owns. Reserved
`.daedalus-internal-…` recovery components are hidden from listings and
refused as public request paths. Components are validated before any NT call:
no separator, drive/stream colon, wildcard or quoting character, control
character, `.`/`..`, NUL, non-NFC spelling, trailing dot or space, reserved
device name, or more than 255 UTF-16 code units.

POSIX measurement backend: the configured workspace is opened one component at a time from
the filesystem-root handle, then traversal uses `dir_fd`-relative `os.open`
with `O_NOFOLLOW | O_DIRECTORY` for directories and
`O_NOFOLLOW | O_NONBLOCK` (`O_CREAT | O_EXCL` when creating) for files,
`os.mkdir(dir_fd=...)`, and `os.link` + `os.unlink` for no-replace move and the
two legs of the replacement protocol (POSIX `rename(2)` would overwrite), plus
`os.listdir(fd)` with `follow_symlinks=False` stat for kinds. The backend retains
an unused `replace=True` `os.rename` branch; the public adapter does not call it.
Hosts without these `dir_fd` capabilities refuse at construction. The public
entrypoint nevertheless refuses write, mkdir and move on non-Windows hosts
because POSIX cannot pin a moved-open parent; tests may lift that private gate
only to retain bounded backend evidence.

Replacement holds and hashes the target, writes and fsyncs a reserved random
temporary next to it, then renames the held original to a different reserved
backup with no replacement. It installs the held temporary at the public name
with a second no-replace rename and deletes the backup through the original's
still-open handle. If another actor occupies the public name between the two
renames, installation and rollback both refuse to overwrite it: the actor's
bytes survive, the verified original stays in the hidden backup, the temporary
is discarded, and `ComputerFileEffectUncertain` reports recovery paths. A
`KeyboardInterrupt` reports `ComputerFileInterrupted.effect_state == "none"`
only after create cleanup or replacement rollback is verified; an installed or
unverifiable state reports `"uncertain"`. Move uses the open source handle's
current Windows location to distinguish interruption before the atomic rename
from interruption after it. These types are adapter evidence only: the dormant
service does not yet consume them. Because replacement never writes through
the existing inode, a hard link created after the check keeps the old content
instead of receiving the new one.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Round trip | Write, read, mkdir, list and move report exact digests, byte counts and `postcondition_verified` through parent handles; Unicode names and content |
| Release host gate | The public adapter refuses write, mkdir and move before any checkpoint or handle when Windows ancestry pinning is unavailable; read and list remain observations |
| Ancestor swap at checkpoint | The private POSIX backend experiment permits the rename then refuses after the checkpoint identity check; Windows pins the open parent so the rename attempt fails and the effect proceeds at the verified path; neither writes outside |
| Configured-root ancestor swap | Replacing an ancestor of the configured workspace with a directory link after policy construction refuses in the handle backend; nothing is created at the redirected target |
| Ancestor swap after the last check | An injected swap between identity check and create still lands inside the workspace and reports `postcondition_verified: false` with a `detail` |
| Ancestry move outside after the last check | On Windows injected moves of the opened effect parent, the workspace root containing it, and a writable ancestor above that root are denied; bytes remain at the verified workspace path |
| Pre-existing links | Directory junction/symlink components, a linked workspace root and a file symlink refuse for every tool, with and without the policy's lexical pre-check |
| Exclusive effects | A file or destination created at the checkpoint is never overwritten; a target changed at the checkpoint is never replaced; Windows create, temporary, replacement-target and move-source handles exclude competing writers and renames; both replacement renames are no-replace, so a late target substitute survives and the verified original remains recoverable |
| Hard links | Read, replace and move refuse `st_nlink != 1` at the open handle; listings omit hard-linked entries through policy admission |
| Type confusion | Directory-as-file, file-as-directory and file-as-ancestor refuse without effect |
| Lexical refusals | `..`, absolute, drive and stream colons, protected names, reserved devices, wildcard/quoting/control characters, non-NFC spelling, trailing dot/space, NUL, empty, root-as-file and malformed argument types refuse before the checkpoint and before any handle |
| Windows Unicode and rename ABI | An astral-character filename round-trips without truncation; one-character files can be atomically replaced and moved |
| Cancellation and observations | All five tools run the checkpoint; read/list data is withheld when its opened parent drifts before return, and a refusing checkpoint returns no data and performs no effect; injected create/replace/move interrupts report typed `none` versus `uncertain` evidence |
| Bounds | `max_file_bytes` applies to read, write and move; listing is bounded to 200 sorted entries with an explicit `truncated` flag |
| Fault injection | An injected write failure leaves the original bytes and no temporary file; failed create cleanup and interruption after replacement/move commit report typed uncertainty instead of claiming rollback |
| Missing state | Absent parents are never created; a missing workspace refuses |
| Mutation | The retained mutation pass covers reparse refusal, reparse-open flag, identity checks, hard-link check, exclusive creation, pre-rename re-verification, no-replace move, delete-share pinning, admission, secret floor, listing filter, observation admission, object-type check and `BaseException` propagation; current two-rename race/interrupt cases are direct adversarial tests, not relabelled mutation evidence |

## Baseline and retained negative evidence

Baseline: G1-IKARUS-COMPUTER-01 records that the pre-fence adapter created
`outside/escaped.txt` (`outside_file_created=True`) when a checked ancestor was
swapped for a directory link, and `tests/runtimes/test_computer_service.py`
proves the fence refuses the same race before any lease. No handle-relative
implementation existed; `_read_bytes` and `_file` in the service remain fenced
and unchanged by this packet.

Throwaway probe (scratch, not retained in the tree): `NtCreateFile` relative
opens, junction detection (`0x410`, tag `0xA0000003`), relative create, read
back, `NtQueryDirectoryFile`, hard-link `st_nlink`, and the swap itself, where
the file landed in the renamed real directory and not outside. The Win32
`SetFileInformationByHandle(FileRenameInfo)` wrapper rejected a
`RootDirectory` handle with `ERROR_INVALID_PARAMETER (87)`; the native
`NtSetInformationFile(FileRenameInformation)` accepts it, refuses an existing
destination with `STATUS_OBJECT_NAME_COLLISION`, and replaces when asked.

Retained mutation finding: the first suite (42 cases) caught four of seven
guard mutations. Disabling the hard-link check, exclusive creation and the
no-replace move each stayed green, because the policy's lexical layer or the
adapter's own pre-check masked the guard. Three checkpoint-race tests and a
handles-only parametrization of the hard-link case were added; all eight
mutations, including a new "skip pre-rename re-verification", now fail the
suite.

## Migration and rollback

This packet is additive and dormant. Rollback deletes its module, focused test
and packet. The
dependent wiring packet replaces the fenced `_file`/`_read_bytes` seams in
`daedalus/runtimes/computer.py` with this adapter, removes the `file.*` rows
from `RELEASE_DISABLED_TOOLS` (path-based vision forms stay disabled unless
they are anchored the same way), keeps secret-floor filtering, canonical lease,
receipt and evidence handling in the service, and requires its own independent
review, service-level ancestor-swap acceptance and a fresh capability
projection check. Legacy stored grants remain inert until that packet is green.

## Evidence, expected failures and review

Builder evidence 2026-09-05, project `.venv` Python 3.13.14 on Windows 11:

| Measurement | Result |
| --- | --- |
| RED | `pytest -q tests/runtimes/test_computer_files.py` before the module: 1 collection error (`ImportError: cannot import name 'computer_files'`) |
| GREEN, first suite | 42 passed in 3.87 s |
| Mutation round 1 | 4 of 7 caught; not caught: hard-link check, move overwrite, exclusive create |
| GREEN, final suite | 46 passed in 5.52 s; 0 skipped (host allowed junctions, file symlinks and hard links) |
| Mutation round 2 | 8 of 8 caught (no-reparse-refusal, follow-reparse-points, no-in-place-check, no-post-effect-in-place, no-hardlink-check, move-overwrites, no-exclusive-create, no-replace-reverify) |
| Repository census suites | `tests/test_sensitivity_write_intent.py tests/test_envelope_coverage.py tests/test_host_predicate.py tests/test_deepseek_substitution_guard.py tests/test_promotion_trust_root_single_caller.py tests/test_byte_pin_eol_durability.py tests/test_kernel_contracts_have_producers.py tests/test_mutation_score.py tests/test_imports_graph.py`: 310 passed, 4 skipped, 10 subtests passed in 289.04 s with the new module present |
| Docs reference check | `tests/test_docs_reference_check.py` with this packet present: 10 passed in 7.81 s |

Independent review found and repaired multiple dormant-adapter defects before
the release handoff. On Windows, `UNICODE_STRING.Length` used Python code-point
count rather than UTF-16 byte count: requesting `🙂.txt` created a truncated
`🙂.tx` entry before refusing. The same review found that a one-code-unit
rename payload was shorter than `sizeof(FILE_RENAME_INFORMATION)` and failed
with `NTSTATUS 0xC0000004`. On POSIX, opening the workspace root as one absolute
pathname left its intermediate components outside `O_NOFOLLOW`, and policy
inspection could leak `NotADirectoryError`. Finally, moving an opened Windows
effect parent to a sibling directory after the last identity check succeeded,
and a direct probe wrote `MODEL BYTES` outside the configured root before
returning an unverified postcondition. The repair measures UTF-16 bytes, pads
the rename structure to its ABI minimum, maps host inspection errors to a typed
refusal, walks the configured POSIX root from `/` by handles, and denies delete
sharing while Windows effect-parent and effect-target handles are live. A
second review pass found that the public adapter did not itself invoke policy
admission, observations did not checkpoint, secret/list filtering lived only
at the future service seam, post-effect verification exceptions could conceal
an effect, and a `file.move` source still allowed a competing writer after its
digest check. Those paths now admit and filter in the adapter, observations
withhold on drift, verification failures return a false postcondition, move
sources deny write/delete sharing, and non-Windows effects have an independent
public-entrypoint gate. The failed probes and their exact outcomes are retained
here rather than hidden.

Independent evidence 2026-09-05:

| Measurement | Result |
| --- | --- |
| Windows pre-fix focused suite | 47 passed in 4.16 s; the packet's earlier 46-case builder count preceded one later test |
| Windows adversarial probes | Astral destination truncated and left behind after refusal; one-character replace and move each refused with `NTSTATUS 0xC0000004` |
| Windows out-of-root move probe | Moving the opened parent after the final check succeeded and `outside/sub/escaped.txt` contained `MODEL BYTES`; after delete-share pinning the same move is denied and no outside entry appears |
| POSIX pre-fix focused suite | Alpine 3.23 / Python 3.12.14: 44 passed, 2 skipped, 3 failed; two link refusals had a different safe errno and one file-as-ancestor request leaked `NotADirectoryError` |
| Windows review checkpoint (superseded revision) | 54 passed in 13.40 s, 0 skipped; this predates direct admission, observation withholding, writer holds and the explicit host gate |
| POSIX backend checkpoint (superseded revision) | Alpine 3.23 / Python 3.12.14 in an isolated WSL2 chroot: 49 passed, 5 Windows-only cases skipped, in 7.27 s; current tests may lift the private host gate only to continue backend measurement |
| Pre-two-rename review revision | Focused Windows suite: 75 passed, 1 strict xfailed in 9.10 s; the retained xfail proved the old supersede strategy overwrote a hostile late target substitute |
| Current review revision | `python -m py_compile daedalus/runtimes/computer_files.py tests/runtimes/test_computer_files.py` passed; focused Windows suite: **81 passed in 13.67 s**, 0 skipped/xfail. Adversarial cases cover target substitution, create cleanup failure and interrupts before/after replace and move commit. The crash-recovery/service contract remains HOLD despite the green adapter suite |
| Canonical packet parser | `tools.index_work_packets._artifact(..., set())` accepted the current packet as `G1-IKARUS-24`, primary, Gate 1, with six required sections |
| Registry and docs contracts (earlier content) | `tests/contracts/test_work_packet_index.py tests/test_docs_reference_check.py`: 32 passed in 14.45 s; rerun pending after these edits |

### Second independent review: Cerberus and Odysseus (2026-09-05)

The repository's security reviewer (Cerberus, blocking veto) and adversarial
verifier (Odysseus, executed probes) reviewed the dormant adapter after the
first repairs. Cerberus returned **BLOCK** on the primary claim as then
written: handle anchoring closed the link-plant race but not the
move-the-object-out variant, `file.read`/`file.list` verified nothing and
hard-coded `postcondition_verified: true`, the `detail` strings asserted a
containment the code never checked, the adapter executed without
`ComputerPolicy.admit` (an empty grant still wrote a file), the secret floor
did not survive the described wiring, and `file.list` disclosed protected
names. Odysseus confirmed the escape with an executed probe (`outside\sub\
escaped.txt` = `OUTSIDE-WS` for write, replace, mkdir and move at the
pre-pinning revision), measured a 13/202 one-shot race hit rate, found the
lost-update window (`SOMEONE-ELSES-EDIT` destroyed with `postcondition_verified:
true`), a post-effect refusal that hid a completed effect, swallowed
`KeyboardInterrupt`, a temp left behind when the disposition fails, and one
surviving mutant (the object-type check masked by NT create options); its
handle-hygiene census over about 16 000 calls found no leak.

Repairs in this packet, each with a test and a mutation that now fails:

- Directory handles and effect targets deny delete sharing, so Windows refuses
  to rename, move or delete the parent, the root or an ancestor above the root
  while the operation runs (measured: leaf, middle, root and the ancestor above
  the root all refuse; other processes still create, read and delete files
  inside). The claim is narrowed to Windows; the private POSIX backend refuses
  every effect through the public entrypoint in this release.
- `execute` admits through `ComputerPolicy.admit`; the secret floor keyed by
  the requested path applies to write text and read text inside the adapter.
- Reads and listings run the checkpoint and the identity check before and
  after the data is taken; drift withholds the data as a refusal.
- `file.list` omits entries the policy would refuse.
- Post-effect verification reports through `detail` instead of raising;
  `detail` no longer asserts containment; `KeyboardInterrupt`/`SystemExit`
  propagate after the partial file is discarded.
- The replacement target is held with share READ only. Its own DELETE-capable
  handle moves it to a reserved backup; the held temporary then uses a second
  `FileRenameInformation` no-replace rename. An adversarial create immediately
  before installation survives the collision, while the verified old bytes
  remain in the hidden backup for reconciliation. Earlier supersede probes
  (including the corrected class-10 result) remain negative historical evidence,
  not evidence for the current protocol.
- Own character class (wildcards, quoting, control characters), NFC-only
  names, `EMLINK` no longer reported as a link, and a direct object-type test.

Before the final protocol change,
`tests/runtimes/test_computer_files.py` measured **75 passed, 1 strict xfailed
in 9.10 s** on Windows 11 / Python 3.13.14; that xfail was the hostile target
substitution blocker, not a waived failure. The then-current in-process
mutations caught **16 of 16** listed guard changes. The current two-no-replace
revision measures **81 passed in 13.67 s**, including the former blocker and
typed create/replace/move interrupt states; the 16-mutant result is retained as
evidence for the preceding guard set and was not rerun or presented as coverage
of the new state machine. The fence stays.

Confirmation pass (Cerberus, 13:12, bound to module sha256 `432bee9c66601bde…`):
both CRITICALs, HIGH-1, HIGH-3, MEDIUM-2, MEDIUM-3 and every Odysseus item
**CLOSED** with executed evidence; the pinned chain held against ancestor
renames at every depth and share mode, 8.3 aliases, a junction or `subst`
above the root and `MOVEFILE_DELAY_UNTIL_REBOOT`, and a supersede rename does
not follow a symlink, junction or hard link planted at the name. The verdict
stayed **BLOCK** on two grounds. NEW-1 (CRITICAL): the secret floor had two
doors instead of three, so `file.move` laundered its path channel (`.env`,
`id_rsa`, `server.key` and `app.pem` moved to `ok.txt` and then read).
NEW-2/NEW-3 (process): the file changed four times during the review while
the concurrent session replaced the hold-and-supersede design with its
two-rename protocol, and intermediate revisions were red. NEW-4 (MEDIUM):
`file.list` withheld entries silently. NEW-5 (MEDIUM): a green POSIX CI run
proves nothing about the release property because the fixture lifts the host
gate there. NEW-6 (LOW): the docstring credited ancestor pinning to
delete-share denial, whereas ancestors are protected by the open-descendant
rule under any share mode and delete-share denial protects the held object.

Repairs after that pass: `file.move` applies the secret floor's path channel
to both endpoints and its content channel to the source bytes (`.env`,
secret-bearing text and a protected destination name refuse with nothing
moved); `file.list` reports `withheld`, the number of entries the policy or
secret floor kept out; the module docstring names both Windows mechanisms.
NEW-5 is accepted as stated above. Re-measured at module sha256
`762aaa7fdd7498fc…`: **81 passed in 3.02 s**; the `no-secret-floor` mutation
still fails the suite through the new move case. A confirmation on this exact
revision is still owed; until then the BLOCK is answered, not lifted.

Cross-vendor council (`daedalus council --live`, seats anthropic, openai
with `--trust openai`, local qwen2.5-coder:7b; google not seated because the
bench sign-in is absent): **degraded quorum, 0 of 3 responded**. Anthropic
`timeout` after the 420 s per-call cap on a heavily loaded box, local
`transport_error` although Ollama answered `/api/tags`, OpenAI `not_on_path`
although `codex` resolves on the interactive PATH (the npm shim is not resolved
inside the council's sanitized spawn). The chained record is
`runs/council/council-20260905T085443Z-828a3874.jsonl`; it contains no claim
and is not evidence for or against this packet. The council tooling failures
are reported, not repaired, by this packet.

Limitations stated honestly: the Windows root must resolve to the same final
path it was configured with (a `subst` or mapped drive whose final name
differs refuses). The handle-bound two-rename protocol prevents an unobserved
target occupant from being overwritten, but it is not a crash-atomic
transaction: termination after the original moves and before installation or
cleanup can leave a missing public name plus reserved backup/temporary. The
adapter deliberately preserves ambiguous artifacts rather than guessing. A
fence lift therefore requires a service-owned, canonically leased recovery
operation that records STARTED/committed/reconciled evidence and binds recovery
to the reported target and internal handle identities, or it must keep
replacement disabled. The current service consumes neither
`ComputerFileEffectUncertain` nor `ComputerFileInterrupted.effect_state`, so
G1-IKARUS-25 remains NOT_WIRED/HOLD. On POSIX
another process can move
an already-open effect parent outside the configured root after the last
identity check; the public entrypoint therefore refuses the effect instead of
relying on a post-effect warning. The private POSIX no-replace move uses
handle-relative
`link` plus `unlink`; a hostile concurrent replacement of the source name can
therefore cause an in-workspace effect that is detected only by the subsequent
digest/postcondition check. Network-backed Windows rename with a non-null
`RootDirectory`, macOS, POSIX mount-point traversal and filesystems other than
the measured local volumes remain unmeasured; the wiring packet must either
retain the fence for them or add and verify a narrower volume gate. Listing
scans at most 4096 raw entries before reporting truncation; protected names,
links, reparse points and hard-linked files are omitted. The adapter is a
trusted host seam, not a sandbox. No commit, merge, promotion, fence change or
live model use was performed.
