# The codex ikarus lane: why it is not integrated, and exactly what a rebase must resolve

`[MEASURED 2026-09-09]`
Subject: `origin/g1/ikarus-runtime-invocation-binding-07d3` @ `eab3fe24`
Against: `origin/main` @ `db38a762`, merge-base `1c3c60288d3324a5b0d32db759206c5685192a96`
Status: **not integrated.** This document is the handoff, not a decision.

## Why it is not integrated

The repository owner asked twice, in the same words, for this lane to be
integrated alongside the tensor lane. The tensor lane merged clean, three times
in one day. This one did not, and the reason is worth stating precisely because
it is **not** the reason it first appeared to be.

The Claude Code safety classifier refused `git merge` of this branch twice. Its
apparent discriminator: the branch removes ~234 lines from
`daedalus/kernel/runtime_authorization_issuer.py` and adds
`daedalus/runtimes/admission/authorization.py` — trust-root machinery.

**That is a diff artifact.** Measured directly:

```
$ git merge-base origin/main origin/g1/ikarus-runtime-invocation-binding-07d3
1c3c60288d3324a5b0d32db759206c5685192a96

$ git rev-parse 1c3c6028:daedalus/kernel/runtime_authorization_issuer.py
15a358f7bad73e3f45f63b004846e5aa89cdf3de

$ git rev-parse origin/g1/...:daedalus/runtimes/admission/authorization.py
15a358f7bad73e3f45f63b004846e5aa89cdf3de      <-- identical blob
```

It is a `git mv`. The "-234 lines from the trust root" is the deletion half of a
rename whose addition half sits in the same commit, byte for byte. `main`
performed the same move independently (G1-RUNTIME-02) and keeps its own
`authorization.py` (blob `68b124e3`) plus a facade at the old kernel path
(`9eeee0b7`).

An independent security review (read-only, `cerberus`) reached
**PASS-WITH-FINDINGS, no CRITICAL**, and found no new effect path, no second
control plane, no widened authority, and no direct subprocess or socket. Four
paths in the lane actually *narrow*.

**None of that is authority to land it.** An agent's review is not the owner's
approval, the refusal is the harness's and not mine to overrule, and the review
itself lists the remaining questions as the owner's. So the lane stays out and
this document exists instead.

## The real obstacle, which is not the trust root

The lane is on a stale base. `git merge-tree` against `origin/main` reports
**20 conflicts**, and one class of them is dangerous in a way a default
resolution would hide.

### Class A — main DELETED these; the branch modifies them (resolve: keep the deletion)

| path | conflict |
| --- | --- |
| `apps/web/src/cockpit/WorkPulse.tsx` | modify/delete |
| `apps/web/src/cockpit/liveWork.ts` | modify/delete |
| `apps/web/dist/assets/CodeMap-*.js` | rename/delete + modify/delete |
| `apps/web/dist/assets/NetworkSheet-*.js` | rename/delete + modify/delete |
| `apps/web/dist/assets/StructureSheet-*.js` | rename/delete + modify/delete |
| `apps/web/dist/index.html` | content |

`git merge-tree` leaves the *branch's* version in the tree for every one of
these. A merge taken at face value therefore **resurrects two source files main
deliberately removed**, plus three stale build artifacts. This — not the trust
root — is the concrete reason not to merge as-is.

### Class B — the rename both sides performed (resolve: prefer main's side)

| path | conflict |
| --- | --- |
| `daedalus/kernel/runtime_authorization_issuer.py` | content |
| `daedalus/runtimes/admission/authorization.py` | add/add |

Main's version differs from the branch's by a docstring rewording and by
importing `PolicyDecision` from `daedalus.kernel.contracts.policy` rather than
`daedalus.schemas`. Main's guard tests
(`tests/kernel/test_runtime_trust_port_boundary.py`) assert the import set and
the call ordering, which are identical either way — but main's spelling is the
current one, so take it.

Resolving this class in main's favour is what makes the phantom −234 vanish from
the diff entirely.

### Class C — real content merges, and the lane's actual value

| path | note |
| --- | --- |
| `daedalus/core.py` | branch closes a legacy provider probe path |
| `daedalus/file_bridge.py` | adds identifiers/digests to `_report_brief` |
| `daedalus/providers/__init__.py` | new `_claude_dispatch_readiness()` |
| `daedalus/providers/claude_cli.py` | adds receipt fields to the result |
| `daedalus/orchestration/ikarus/effect_bridge.py` | **main moved this module**; the branch edits the old `daedalus/ikarus_effect_bridge.py` path |
| `tests/providers/test_claude_sealed_output_evidence.py` | |
| `tests/test_dynamic.py` | |
| `tests/test_runtime_registry_claude_shim.py` | |

The module move is the bulk of the work: main restructured Ikarus under
`daedalus/orchestration/ikarus/` while the lane kept editing the flat paths.

### Class D — dead after integration (resolve: drop)

`.github/workflows/g1-ikarus-unified-runtime-admission.yml` triggers on three
`g1/...` branch names that will not exist post-merge.

## Recommendation

**Rebase, do not merge**, and let the lane's own author do it. Two reasons:

1. A rebase onto `db38a762` resolves Class B in main's favour as a side effect,
   after which there is no trust-root deletion in the diff for anything to react
   to.
2. The lane is a **moving target** — it gained 83 commits between two
   measurements on a single morning. Rebasing it from outside is work that the
   next codex push invalidates.

## What the owner must decide

Taken from the review, unchanged, because these are authority questions:

1. Rebase or merge.
2. Whether the classifier's refusal stands as a governance signal now that its
   trigger is shown to be a rename.
3. Whether `provider.claude` moves from `INVENTORY_ONLY` to `CENTRAL`. **This
   branch deliberately does not flip it**, and its new readiness probe makes the
   `INVENTORY_ONLY` state visible to routing and the UI. Activating Claude
   dispatch is a separate owner-signed decision under plan §4.1/§10 and must not
   ride in on this packet.
4. Whether the two deleted web files are dropped from the lane or restored.

## What has NOT been verified

The review **read** the lane's tests and did not execute them; it was scoped
read-only and never checked the branch out. Its report that they are adversarial
(monkeypatching the downstream effectful call with a sentinel and asserting both
the refusal *and* non-reachability) is a reading, not a measurement. Plan §10
step 4 requires an executed run post-rebase before any of this counts as
evidence.
