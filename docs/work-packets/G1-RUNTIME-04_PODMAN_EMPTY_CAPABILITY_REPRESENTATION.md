# G1-RUNTIME-04 - Podman empty capability representation

Packet ID: `G1-RUNTIME-04`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `eb7834d52949ad10b2bb8c51fccd2a81c48aab20`
Dependencies: `Master Plan Revision 13; G1-INTEGRATION-01; existing Linux OCI containment boundary`
Freeze: `2026-09-08`, before production or test edits.

## Primary acceptance claim

If retained raw output from the unchanged canonical Podman inspection confirms
explicit null EffectiveCaps and BoundingCaps, accept that documented empty Go
slice representation at the existing capability admission check. Both resolved
sets must still be empty. Missing fields, nonempty sets, and malformed values
refuse before candidate start. A real contained probe must independently observe
zero effective and bounding capability masks and NoNewPrivs=1 in its own procfs
status. This is runtime compatibility evidence, not scientific Gate closure or
release acceptance.

Implementation is conditional on the exact raw CI observation, independent
review, and root's go-ahead. No source/test edits are authorized by this draft.
The proposed ID was absent from docs/work-packets/index.json at the base above.
Root owns any later primary metadata, index, corpus pins, and commit integration.

## Existing failure and source evidence

On the preceding 7d23 integration head, Linux Python 3.10 and 3.12 live OCI
preflight reached _verify_container and refused its EffectiveCaps/BoundingCaps
comparison to []. Existing artifacts do not expose the full candidate inspection
or those raw fields; their values remain unknown at this freeze. The earlier
seccomp package metadata refusal was separately reproduced and corrected by
exact-version authenticated package restoration (mode 777 to 644, same bytes).
That provisioning result does not establish capability state.

Upstream Podman v4.9.3 supports the conditional hypothesis:

- pkg/specgen/generate/security_linux.go79-108 starts caplist as a nil []string,
  appending only surviving capabilities;147 assigns it to Bounding. For a
  nonroot user with no additions,166-173 assigns a nil userCaps to Effective.
- libpod/container_inspect.go175-178 copies those OCI capability slices directly.
- libpod/define/container_inspect.go662-663 declares []string JSON fields without
  omitempty. Go encoding/json encodes nil slices as JSON null.

Primary source links:
https://github.com/containers/podman/blob/v4.9.3/pkg/specgen/generate/security_linux.go#L78-L178
https://github.com/containers/podman/blob/v4.9.3/libpod/container_inspect.go#L175-L178
https://github.com/containers/podman/blob/v4.9.3/libpod/define/container_inspect.go#L662-L663
https://pkg.go.dev/encoding/json#Marshal
https://man7.org/linux/man-pages/man5/proc_pid_status.5.html

Source inference is distinct from the pending observed candidate metadata.

## Scope

Production: daedalus/spine/linux_containment.py::_verify_container, limited to
reading the two existing capability fields. Use local missing-field distinction;
do not broaden _ci_get or _empty globally. Normalize only the explicit null or
empty JSON array representation into the existing empty capability facts.

Tests: tests/test_linux_oci_containment.py, extending existing admission and
create/inspect/start/cleanup coverage and the existing single real OCI probe.
No new module, helper subsystem, schema, event store, evidence authority, or
runtime path. Root-owned CI capture may retain exact inspect/procfs observations
without changing the test outcome or weakening admission.

Unchanged: --cap-drop=all, no-new-privileges request and verification, trusted
runtime paths, rootless mapping, package/seccomp checks, image digest admission,
mount/network/resource checks, immutable OCI identity, create-inspect-start
ordering, strict cleanup, containment attestation schema, and policy/evaluator.
No candidate fallback on the host, no retry, no provider launch, no release or
promotion, and no Master Plan amendment.

## Acceptance matrix

A1. Retain raw JSON from the unchanged canonical create/inspect seam and the
original failure in each available Linux matrix lane. Record exact source head,
Podman version, image digest, field presence, field values, and JSON types.
If either capability set is actually nonempty, missing, or malformed, stop this
codec correction and report the real boundary failure; do not normalize it away.

A2. On the unchanged source, add meaningful positive cases []/[], null/[],
[]/null, and null/null for EffectiveCaps/BoundingCaps. Preserve the [] baseline;
retain the null-case failures before the production change. Each accepted case
must produce the same existing empty capability facts; no raw null leaks into a
new contract or weakens another field.

A3. For each field separately, refuse missing, empty object, empty string,
boolean false/true, numeric zero, nonempty capability list, and malformed array
members such as null. Exercise mixed pairs so an empty field cannot hide an
unsafe other field. Retain existing case-insensitive lookup behavior; do not
invent alternate schemas or accept strings naming empty values.

A4. Through spawn_oci_contained, not only direct verifier calls, malformed,
missing, and nonempty capability inspection must never reach subprocess.Popen.
Verify the canonical removal of the exact created container and hooks cleanup.
Do not replace production cleanup with a fake successful result under review;
controlled subprocess doubles test ordering only and are explicitly scoped.

A5. Extend the existing live test
 test_live_linux_container_writes_workspace_but_not_root_and_has_no_network
in place. Within that actual contained Python process read /proc/self/status,
retain the exact CapEff, CapBnd and NoNewPrivs strings, and expose them through
the existing captured output. Parent-side assertions must require all fields,
parse hexadecimal capability masks, and require exactly zero for both; require
NoNewPrivs exactly 1. Missing/unparseable/nonzero observations fail. Retain actual
workspace write, refused root write, refused network and exit-success assertions.
Keep this as one unskipped live test, preserving its existing opt-in requirement.
The fixed probe is measurement code, not candidate-supplied evidence authority.
Retain the captured procfs observation in the CI evidence/JUnit without making
successful stdout alone an attestation; the host assertions decide the result.

A6. Run the full focused tests/test_linux_oci_containment.py and relevant existing
containment/admission contract checks once source is frozen. Real Windows runs
will skip the Linux live test and cannot close A5. Require the actual existing
Linux Python3.10/3.12 CI matrix to produce one unskipped live pass each, including
the independent procfs assertions, then run the unchanged real HTTP Genesis
suite against that admitted runtime. The host Python matrix does not imply two
different interpreters inside the single pinned OCI image.

A7. Retain all preceding negative CI evidence and red tests with source identity;
append measured green results and independent review without rewriting prior
claims. Actual Linux OCI acceptance remains pending until observed. The known
Linux full-GUI release-only gap remains separate and no tagged-release claim is
made. Root decides proportional full integration reruns and corpus repins.

## Migration and rollback

No migration. Reverting the bounded decoder change restores explicit-null
refusal. This packet proves the specified running probe on the measured runtime
and image; it is not a universal Linux security guarantee or a new capability
policy. Kernel checks remain the canonical production admission boundary.


## Contracts and behavior

Frozen activation and explicit scope addendum, 2026-09-08, before any production
or test edit: root authorized implementation after both capability keys were
observed present with JSON null in the exact eb7834 Linux312 raw inspect. The
original conditional draft remains byte-for-byte retained at
runs/integration-20260908/G1-RUNTIME-04_PODMAN_EMPTY_CAPABILITY_REPRESENTATION.draft.md,
SHA256 3d051729ef61e2d9ace98f3f10e95fb656cb9b2e84469fdd3f796ce8674c91cc.
Its pre-observation unknown statements are historical freeze evidence, superseded
by the observations and authorization here, not silently rewritten.

The complete observed inspect exposes another subsequent refusal in the same
canonical verifier: NetworkSettings.Networks is a singleton mapping named none,
although HostConfig.NetworkMode is none. Podman v4.9.3 deliberately generates
this zero-valued marker before a container starts. Source
libpod/networking_common.go225-230 sets NetworkID to NetworkMode;249-263 returns
that marker when no network is joined:
https://github.com/containers/podman/blob/v4.9.3/libpod/networking_common.go#L225-L263

Allowed scope expands only to that existing network inspection check, in the
same function/file. Require present Networks metadata. Admit an empty mapping,
or exactly the singleton key none containing exactly these fields and types:

- EndpointID, Gateway, IPAddress, IPv6Gateway, GlobalIPv6Address, MacAddress:
  each the empty string.
- IPPrefixLen and GlobalIPv6PrefixLen: each integer zero, excluding booleans and
  floating-point zero.
- NetworkID: exactly the string none.
- DriverOpts, IPAMConfig and Links: each explicit JSON null.

No missing field is equivalent to null. Reject extra keys, additional networks,
alternate network IDs, populated addresses/endpoints, options, aliases, or
links; reject missing/null/nonmapping Networks metadata. This explicitly narrows
the old generic-empty acceptance for unknown metadata. Keep the independent
HostConfig.NetworkMode=none prerequisite and the existing empty-map case.
The new representation match is typed and exact; _empty and _ci_get retain their
global semantics. Successful OciContainmentFacts fields/schema stay unchanged.

Additional frozen network matrix: singleton none passes alongside capability
null/empty combinations; missing/extra inner fields, nonempty values, wrong
scalar/container types (especially bool/float zero prefixes), a wrong marker
name or ID, another network, and missing/null/nonmapping outer metadata fail
before Popen with exact-container removal and hooks cleanup. Keep the existing
network=bridge refusal. Do not bypass later verifier checks to make the fixture
pass; report any additional compatibility blocker before broadening this scope.

The existing single live probe is extended in place to print measured procfs
CapEff, CapBnd and NoNewPrivs. Host assertions require zero hexadecimal masks and
NoNewPrivs=1, and JUnit retains these three exact observed values via the existing
pytest evidence channel. No provider credentials or host environment are logged.
Its root-write and network refusal checks remain; raw inspect alone is not proof
of the eventual running process state.

## Evidence expected failures and review

The Linux312 raw artifact is
runs/integration-20260908/diagnostic-ci-eb7834-linux312-artifacts/candidate-container-inspect.json,
10728 bytes, SHA256 17befd5c197f5723e927a4ca4728c15ac37ca67c832d03583b607b8bada9c759,
from CI run 34200772093 and source eb7834d52949ad10b2bb8c51fccd2a81c48aab20.
Both capability fields are present/null; State is created, Running=false, Pid=0,
StartedAt is the zero timestamp. The original one-test receipt failed with no
skip at the unchanged capability check. Root retains the independent Linux310
raw artifact and its original receipt separately; their exact hashes will be
appended when archived. Neither failure is converted into a runtime pass.

Required red/green local evidence, source hashes, independent review, and actual
Linux procfs/OCI/HTTP outcomes will be appended after measurement. The Linux
live case is unavailable on this Windows host and remains a separate CI result.


## Measured local correction and independent review

2026-09-08: source and tests are frozen after the independent negative-case
review. Production SHA256 is
7f52a56da9d01731e4de141a2f51fcdfc9ba80e524cd41c1f972a2e3b1371871;
final test SHA256 is
a14cb86327a5223deeefec6c9fccc227dd8ed978978f29c4f86ce67b09dd9eac.
Both edited Python files use uniform LF. Exact byte sizes, normalized Git blobs
and line-ending census are retained in
runs/integration-20260908/podman-inspect-codec-source.json.

All local commands used the existing repository .venv/Scripts/python.exe,
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, pytest -q -p no:cacheprovider and a named JUnit
output. The actual source starts from the frozen eb7834 revision plus this
bounded correction; source hashes above identify the tested uncommitted delta.

- Red, before production edits: the two new test groups selected with
  -k 'empty_capability_representations or invalid_inspection_representation'
  returned 10 failed, 58 passed, 45 deselected in 0.97s. Seven failures reproduce
  rejected empty capability/network representations. Three independently expose
  prior missing/null/list Networks admission reaching a controlled Popen
  tripwire; no candidate was started by that diagnostic. Retained
  podman-inspect-codec-red.xml and .log preserve the complete negative result.
- First corrected complete containment file: 112 passed, 1 skipped in 15.44s,
  retained podman-inspect-codec-green.xml and .log.
- Independent review found the extra-network negative also used an invalid
  empty none marker. The test datum was corrected to preserve the complete valid
  none marker plus bridge:{}, isolating the promised extra-network rejection.
  No production change was needed. Final complete containment file: 112 passed,
  1 skipped in 0.88s, retained podman-inspect-codec-reviewed.xml and .log.
- Independent read-only review and selected regression run: 68 passed,
  45 deselected in 0.64s; no blocking findings remain. Retained
  podman-inspect-independent-review.json, .xml and .log record exact source
  identities, scope, the resolved test gap and the pending live-runtime limit.
- Broader focused run: 244 passed in 110.38s. Selected files were
  tests/test_containment_scope.py, tests/test_containment.py,
  tests/test_gate_containment_job_caps.py, tests/test_gate_containment.py,
  tests/test_spine_attempt_containment.py, tests/test_effect_boundary.py,
  tests/test_cli_effect_boundary.py and tests/interfaces/test_http_genesis.py.
  Retained podman-inspect-integration-focused.xml and .log. This Windows result
  includes real local HTTP Genesis, but is not Linux OCI evidence.

The basenames above are under runs/integration-20260908/. Root owns their
lossless tracked evidence archival and the index/acceptance update; this packet
does not claim a not-yet-executed CI result. The Linux live test is the sole
skip in the containment-file run on this Windows host.

Both original raw inspect artifacts have 10728 bytes. Linux310 SHA256 is
cc1a991dcfe82ec6d253a26ff3a7d385d4869b5c8d099efeb8464a3ce00266ae;
Linux312 SHA256 is
17befd5c197f5723e927a4ca4728c15ac37ca67c832d03583b607b8bada9c759.
Existing tracked-archive destinations, written by root, are
 docs/evidence/G1-INTEGRATION-01/diagnostic-ci-eb7834-linux310-artifacts-candidate-container-inspect.json.gz
and
 docs/evidence/G1-INTEGRATION-01/diagnostic-ci-eb7834-linux312-artifacts-candidate-container-inspect.json.gz.
The original failed linux-oci.xml receipts and runtime/image/package/stat
observations are archived with the same lane prefixes. Their contained-process
start was refused; these artifacts are not positive runtime receipts.

A no-start replay of each complete actual raw inspection now passes every
remaining _verify_container check. For Windows portability only two payload
paths were rebound to a real owned temporary workspace:
/0/Mounts/0/Source and /0/HostConfig/Binds/0. The hook verifier checked a real
empty directory against its actual local owner, rather than the captured Linux
UID; the raw user and preflight UID remained 1001. Container ID, name, command,
user, image ID/digest, security and all remaining inspect fields stayed intact.
Both original artifact byte sequences stayed unchanged. Record
runs/integration-20260908/podman-inspect-actual-replay.json explicitly labels
this as parser evidence without any candidate start or Linux-runtime proof.

The extended single live OCI probe and its exact JUnit CapEff/CapBnd/
NoNewPrivs observations are still PENDING on the corrected source. The two Linux
CI lanes must independently produce one unskipped pass and then pass the real
HTTP Genesis suite. No Gate transition, tagged release, promotion, or complete
Linux release-acceptance claim follows from these local checks.
