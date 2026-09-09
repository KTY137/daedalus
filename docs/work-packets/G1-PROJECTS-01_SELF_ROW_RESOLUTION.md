# G1-PROJECTS-01 — The self row: `repo_root: "."` resolves to the checkout that owns the registry

Packet ID: `G1-PROJECTS-01`
Artifact role: `primary`
Status: `built; tests green; mutation-checked; independent review pending`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `db38a762991b04cbc96c3cbed5209d6a517fa611`
Dependencies: `none (prerequisite of the renovation offer in G1-IKARUS-37)`
Master-plan authority: `Revision 13`
Promotion: not requested; no gate transition.

## Primary acceptance claim

**One** claim: *the effectful project-root seam
`daedalus.foundation.projects.resolve_registered_project_root` resolves a
registry row whose `repo_root` is exactly `"."` to the checkout that owns the
registry (`PROJECT_DIR.parent`), independent of the process working
directory, while every other relative value keeps failing closed.*

Why it matters for the owner's goal ("verbessere Daedalus" → a bounded
self-Renovation campaign): `projects/agent_env.json` deliberately carries
`"repo_root": "."` so the row stays valid in every clone and CI job. The seam
that authorizes exposing a checkout to an effectful local service
(`POST /api/ariadne` → `effects.py:479`) refused that row —
`[MEASURED 2026-09-08]` `resolve_registered_project_root("agent_env")` raised
`ProjectRegistryUnavailable: project registry row 'agent_env.json' has no
valid repo_root` on `db38a762` — so the product could never run an Ariadne
campaign against itself through the registered door.

## Scope

In scope (this packet writes only here):

- `daedalus/foundation/projects.py`: `SELF_CHECKOUT_ROOT = "."`,
  `self_checkout_root()`, the self branch in `_registered_root_key` and in
  `resolve_registered_project_root`.
- `tests/test_ide_project_authorization.py`: two new tests.
- `experiments/forest_v2/s02_types/test_external_corpora.py`,
  `experiments/forest_v2/README.md`, `docs/evidence/G1-PROJECTS-01/**`: the
  kernel-corpus pin moves with any edit under `daedalus/` and is re-measured
  per the repository convention.
- This document, `docs/work-packets/index.json`, the registry pins in
  `tests/contracts/test_work_packet_index.py`.

Forbidden: the lenient `resolve_repo_root` (still returns the raw row value,
`"."` included — callers that use it are cwd-relative by design and are not
changed here), the registry lock protocol, the HTTP handlers, the plan and
its chain.

## Contracts and behavior

| Value of `repo_root` | Before | After |
| --- | --- | --- |
| exactly `"."` (whitespace-stripped) | `_registered_root_key` → `None`; row loader refuses `has no valid repo_root` | key = `_path_key(PROJECT_DIR.parent)`; seam resolves to `PROJECT_DIR.parent` (canonicalized, must exist and be a directory) |
| any other relative value (`"./"`, `"sub/dir"`, `".."`, `"./projects/.."`) | refused | unchanged: `_registered_root_key` → `None`, loader refuses `has no valid repo_root` |
| absolute native path | resolved | unchanged |
| foreign-platform absolute path | stale inventory, refused `not absolute on this host` | unchanged |

`self_checkout_root()` is derived from `PROJECT_DIR` at call time: a test that
points the registry elsewhere moves the self root with it, and a relocated
registry can never keep pointing at the source tree by accident. The identity
check `_registered_root_key(data) == _path_key(root)` holds by construction
for the self row.

The branch `registered repo_root is not absolute on this host` inside the seam
is measured to be unreachable for relative rows (the locked loader refuses
them first); it stays as defense in depth and is not the contract.

## Acceptance matrix

| # | Test | Passes when |
| --- | --- | --- |
| A1 | `test_self_row_dot_resolves_to_the_registry_checkout_not_the_cwd` | with the registry under `tmp/projects` and cwd moved elsewhere, the seam returns `tmp` (resolved); `self_checkout_root()` is `PROJECT_DIR.parent`; `_registered_root_key` keys `"."` and `" . "` to `tmp` |
| A2 | `test_other_relative_roots_still_fail_closed` | `"./"`, `"sub/dir"`, `".."`, `"./projects/.."` have no registry key and the seam refuses with `ProjectRegistryUnavailable` `no valid repo_root` |
| A3 | existing `tests/test_ide_project_authorization.py`, `tests/test_project_registration.py`, `tests/interfaces/test_http_ariadne.py` | unchanged and green |
| A4 | live: `resolve_registered_project_root("agent_env")` in a checkout | returns that checkout's root |

`[MEASURED 2026-09-08]` A1–A3: `61 passed` (`python -m pytest -q -p
no:cacheprovider tests/test_ide_project_authorization.py
tests/test_project_registration.py tests/interfaces/test_http_ariadne.py`);
A4: returned `C:\Users\Administrator\Desktop\projects\daedalus-ignite-projectroot`
(the worktree the packet was built in).

Mutation `[MEASURED 2026-09-08]`: with `SELF_CHECKOUT_ROOT` set to
`"__never__"` the suite reports `2 failed, 4 passed` (A1 and the relative-root
test both bite); restored, `6 passed`.

## Migration and rollback

Additive: one constant, one helper, two guarded branches. No registry row
changes; `projects/agent_env.json` keeps its literal `"."`. Rollback = revert
the commit; the s02 pin is then re-measured again per convention.

## Evidence, expected failures and review

- Kernel-corpus remeasurement `[MEASURED 2026-09-08]`: two complete probe
  runs agree except wall time; retained as
  `docs/evidence/G1-PROJECTS-01/s02-g1-projects-01-corpora-{a,b}.json.gz` with
  SHA-256 values in `acceptance.json`. Kernel row: 485 parsed files, 6,779
  functions; annotation-only 94.35 %; full resolver 94.23 %; marginal 8
  functions / 0.1180 pp; 45,191 type-name sites, resolution 99.93 %; verified
  internal 4,053 / 4,478 (90.51 %); 425 named-only internal sites; pin
  `3e5b493b41eceba7a91611d778ba9405f55b77f4afc432f188b38bd9a3a4ba02`.
  Against the row pinned at `db38a762` (6,778 functions, 45,190 type-name
  sites, pin `d6b652d9…`) this packet moves exactly one function
  (`self_checkout_root`) and one type-name site; every rate and every other
  count is unchanged. No resolver improvement is claimed.
- Import census: unchanged (no new module; `tests/contracts/test_import_scc_hierarchy.py` green).
- Expected failure recorded before the build: the first draft of A2 expected
  `ProjectRegistrationError` `this host`; measuring showed the locked loader
  refuses relative rows earlier with `ProjectRegistryUnavailable`. The test
  now pins the measured refusal.
- Review questions: (1) Is `"."` the only self value the registry should
  accept, or should `""` be admitted too? (No: an empty root has no meaning
  and stays refused.) (2) Does resolving the self row widen what an effectful
  service can reach? (No: it can reach exactly the checkout the registry
  lives in, which every absolute row already could name.)
