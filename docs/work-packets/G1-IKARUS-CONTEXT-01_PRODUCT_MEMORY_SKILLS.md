# G1-IKARUS-CONTEXT-01: product memory and selected skill context

Packet ID: G1-IKARUS-CONTEXT-01
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-17, G1-IKARUS-COMPUTER-01, existing SpineLedger record_fact and foundation skill reader

Unrelated user work is preserved.
Authority: master plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.

## Primary acceptance claim

Primary claim: explicit owner notes and one selected inert skill become bounded,
versioned, authority-scoped product context through the existing canonical spine
and CAS, with no independent memory database and no research-memory coupling.

## v0.1.6 release supersession

Current contract: owner notes remain enabled. New local skill-directory
selection/read is centrally refused before workspace I/O or state mutation.
Retained pre-fence skill metadata projects as unavailable and may only be
cleared with `/computer skill off`. The skill-specific contracts and scratch-
source measurements below are retained development evidence; they are not
v0.1.6 shipping-capability acceptance.

## Scope

Scope: `daedalus/orchestration/ikarus/computer_context.py`,
`tests/test_ikarus_computer_context.py`, and this packet. Parent packets own
registry admission and explicit conversation commands, mission snapshot binding,
and presentation. No model mutation tools, scheduler, database/schema changes,
script execution, policy/evaluator modification or new authority are allowed.

## Contracts and behavior

Only explicit owner commands publish note or selected-skill mutations through
registered canonical effect admission. Projection is read-only, scoped to the
authority root, and treated as untrusted data. A mission binds one immutable
snapshot; notes and skill content cannot modify policy or acquire tools.
Limits and retained state-publication behavior are specified below.

## Acceptance matrix

| Case | Required evidence |
| --- | --- |
| Empty context | read-only; no absent ledger is created |
| Remember/restart | real canonical fact and CAS; stable note identity/provenance |
| Forget/restart | tombstone action retained; prior note remains in history only |
| Different authority | no other authority's notes or skills are projected |
| Missing confirmation, secret, limits | refuse before mutation |
| Concurrent additions | no lost notes or duplicate revision |
| Skill selection | existing load_skill/render_untrusted, workspace path and byte digest bound |
| Skill scripts/tool claims | inert untrusted content; no execution or authority widening |
| Changed/missing/linked/secret skill | visible refusal or unavailable selected context |
| Mission context | parent freezes one snapshot; later notes cannot rewrite it |

Limits: at most 20 active notes and 8000 note characters; one selected skill,
maximum 16000 source bytes and 18000 rendered characters. Zero provider calls,
zero network or script execution. Bundle inventory is bounded to 256 entries and
depth 8 before the existing skill loader runs; linked entries are refused.
Tests use isolated canonical ledger paths and scratch skills only.

Baseline: existing conversation uses open_gate0_spine_writer; the canonical
ledger supports record_fact and indexed bounded tail reads by effect key.
foundation.skills already loads inert SKILL.md data and fences its rendering.
No computer product-context projection exists before this packet.

Each fact retains a complete bounded state plus its mutation/tombstone action
and previous-fact digest. Therefore bounded tail reads cannot resurrect forgotten
notes as history grows. Fact publication is the state mutation; a prepared CAS
artifact without a committed fact has no state effect. A per-authority OS lock
serializes snapshot updates using the existing ExclusiveFileLock primitive.

## Migration and rollback

Rollback disables these owner commands and context projection; history is
retained. Forgetting removes a note from active context, not historical evidence.
Independent review must challenge missing admission, authority confusion,
secret retention, corrupt provenance and skill capabilities disguised as data.

## Evidence, expected failures and review

Builder evidence 2026-09-05:
`python -m pytest -q tests/test_ikarus_computer_context.py` produced **18 passed
in 6.85 seconds**. This uses the actual canonical SpineLedger/CAS with four
concurrent owner updates and real scratch skill sources. Model calls and scripts
are absent; it does not claim provider or conversation-UI acceptance. Parent
packet owns independent review and combined context/prompt integration tests.

Retained design finding: foundation.skills inventories bundled paths before
returning its inert Skill. Context preflights that inventory to avoid an
unbounded or linked bundle expanding the selected workspace read scope.
