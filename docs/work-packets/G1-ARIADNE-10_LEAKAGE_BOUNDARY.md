# G1-ARIADNE-10 — The self-Renovation leakage boundary as code

Packet ID: `G1-ARIADNE-10`
Artifact role: `primary`
Status: `built; tests green; mutation-checked; independent review pending`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `db38a762991b04cbc96c3cbed5209d6a517fa611`
Dependencies: `none (prerequisite named by the forward plan for G1-SELF-02)`
Master-plan authority: `Revision 13`
Promotion: not requested; no gate transition. Nothing here starts a campaign,
finds a candidate or reaches the chat; it only adds refusals.

## Primary acceptance claim

**One** claim: *an Ariadne campaign request whose `target_path` lies inside the
master plan's section 8.1 leakage boundary is refused by the existing pure
target admission before the repository, its HEAD or any effect lease is
observed, and every other target is admitted exactly as before.*

Master plan section 8.1 (revision 13): *"a candidate produced from `daedalus/`
sources may not edit `daedalus/spine`, `daedalus/kernel` policy enforcement,
the master plan, amendment chain, `AGENTS.md`, or tests of its own
evaluator."* Until this packet that sentence had no code behind it:
`[MEASURED 2026-09-08]` `_admit_target_path` (`daedalus/ariadne/campaign.py`)
refused only malformed shapes and the mandatory ignored roots (`.git`,
`.daedalus`); `grep -i leakage daedalus/` found nothing related. The owner's
"verbessere Daedalus" goal makes Daedalus itself the campaign subject, so the
boundary has to exist before any chat-to-campaign edge does.

## Scope

In scope: `daedalus/ariadne/campaign.py` (`SELF_RENOVATION_PROTECTED_PREFIXES`,
`protected_prefix_for`, one refusal inside `_admit_target_path`),
`tests/test_ariadne_leakage_boundary.py` (new), this document, the registry
index and its pins, the forest_v2 s02 corpus pin re-measurement that any edit
under `daedalus/` costs.

Out of scope, deliberately: a candidate finder, a clone-subject runner, a chat
intent, an HTTP route, any widening of what a message may reach. Those are
the authorization-bearing halves the owner has not named yet (see the session
record of 2026-09-08); this packet is the refusal that must precede them.

## Contracts and behavior

`SELF_RENOVATION_PROTECTED_PREFIXES` (unconditional, case-insensitive,
repository-relative):

| Prefix | Plan class |
| --- | --- |
| `daedalus/spine/` | the spine |
| `daedalus/kernel/policy/`, `daedalus/kernel/promotion`, `daedalus/kernel/approvals.py`, `daedalus/kernel/contracts/` | kernel policy enforcement, promotion, approvals, contracts |
| `daedalus/ariadne/campaign.py` | the candidate's own evaluator |
| `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` | the plan and its chain |
| `AGENTS.md`, `CLAUDE.md`, `.agentenv/` | the agent constitution and the mechanical veto policy |
| `tests/test_ariadne` | the tests of its own evaluator |

A prefix ending in `/` names a directory; any other prefix matches the path
itself and every path that continues it. `_admit_target_path` checks shape,
then the mandatory ignored roots (unchanged wording and precedence), then the
boundary, and raises `AriadneRequestError("target_path is inside the
self-Renovation leakage boundary (master plan section 8.1): <prefix>")`. The
refusal happens before `read_repository_source`, before
`acquire_effect_lease`, and leaves no file behind. The tuple applies to every
repository, not only Daedalus: refusing a foreign `AGENTS.md` is the safe
direction and costs nothing that exists today.

## Acceptance matrix

| # | Test | Passes when |
| --- | --- | --- |
| A1 | `test_protected_target_is_refused_before_read_or_effect` (19 paths incl. upper-case variants) | `run_campaign` raises with `leakage boundary`; the repository read and the lease admission are never reached; the scratch tree is untouched |
| A2 | `test_protected_prefix_is_named_in_the_refusal` | the refusal names the exact tuple entry |
| A3 | `test_ordinary_source_is_still_admitted` (8 paths) | `_admit_target_path` returns the path unchanged and `protected_prefix_for` is `None` |
| A4 | `test_ignored_roots_keep_their_own_refusal_and_precedence` | `.git/HEAD` still says `mandatory ignored root` |
| A5 | `test_the_tuple_covers_every_class_the_plan_names` | each plan class has an entry |
| A6 | existing `tests/test_ariadne_campaign_v0.py`, `tests/test_ariadne_cli_exit_codes.py`, `tests/interfaces/test_http_ariadne.py` | unchanged and green |

`[MEASURED 2026-09-08]` see the commit message and `docs/evidence/G1-ARIADNE-10/`.

## Migration and rollback

Additive: one tuple, one helper, one refusal. No stored state, no schema, no
row. Rollback = revert the commit; the s02 pin is then re-measured again.

## Evidence, expected failures and review

- Kernel-corpus remeasurement per convention (two probe runs, retained under
  `docs/evidence/G1-ARIADNE-10/`, README paragraph appended).
- Expected failure recorded before the build: a refusal placed *after* the
  ignored-root check keeps the ignored-root wording for `.git/...`, which A4
  pins on purpose; an earlier draft that checked the boundary first would have
  changed a message G1-ARIADNE-06 named.
- Review questions: (1) Is `tests/test_ariadne` too narrow for "tests of its own
  evaluator"? The exact-match evaluator lives in `campaign.py`; its tests are
  the `tests/test_ariadne*.py` files. (2) Should `daedalus/kernel/` be protected
  wholesale? Not by the plan's text, which names policy enforcement; the
  artifacts/CAS modules stay renovatable.
