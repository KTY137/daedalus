# G1-ARIADNE-09 — The Ariadne CLI answers each outcome with its own exit code

Packet ID: G1-ARIADNE-09

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: isolated worktree `.claude/worktrees/lane4-cli-exit-codes`, branch `loop/lane4-cli-exit-codes`, stacked on `loop/stage3-failed-receipt`

Dependencies: `G1-ARIADNE-04_FAILED_RECEIPT_ON_FIRST_CALL`, `G1-ARIADNE-06_NAMED_REFUSALS`, `G1-ARIADNE-07_COUNCIL_HARDENING`

Stage: the open question stage 3 put to Codex and never got an answer to. G1-ARIADNE-04 named it out of scope on purpose: "CLI exit-code semantics (`daedalus ariadne` already prints `rejected` receipts with exit 0; `failed` follows the same rule, an outcome-based exit code is a separate decision)". This is that decision.

## Primary acceptance claim

`daedalus ariadne` and `python -m daedalus.ariadne` give each typed campaign
outcome its own exit code and put exactly one JSON document on stdout for every
one of them, so a script and the desktop branch on the code instead of parsing
prose. The two doors share one implementation and emit identical bytes.
`daedalus/ariadne/campaign.py` is not touched: no campaign semantics, no
refusal timing, no receipt field changes.

## Reproduced negative baseline (measured 2026-09-05, worktree venv, Windows)

Measured against a real tmp git repository (the `_git_repo` fixture pattern) with
the **real** frozen evaluator, both doors as real child processes:

| scenario | `python -m daedalus.ariadne` | `daedalus ariadne` |
| --- | --- | --- |
| nominated | exit 0, receipt JSON on stdout, stderr empty | exit 0, `{"ok": true, "ariadne": <receipt>}` on stdout |
| request refusal (`../escape.txt`) | exit **1**, uncaught traceback on stderr, stdout empty | exit **2**, prose `Ariadne refused: ...` on stderr |
| request refusal (missing `--repo-root`) | exit **1**, uncaught `FileNotFoundError` traceback | exit **2**, prose |
| revision conflict (stale SHA) | exit **1**, uncaught traceback | exit **2**, prose |
| kill switch stopped | exit **1**, uncaught traceback | exit **2**, prose |
| usage error (missing required flag) | exit **2**, argparse usage | exit **2**, argparse usage |

Three defects follow from that table:

1. `python -m daedalus.ariadne` had **no failure handling at all**. Every
   refusal, conflict and cancellation escaped as a traceback with exit 1,
   indistinguishable from a crash, and its stdout was empty.
2. `daedalus ariadne` collapsed `AriadneRequestError`, `AriadneConflictError`,
   `LoopHalted`, `OSError`, `TypeError` and `ValueError` into one exit 2 with
   prose — **the same code argparse uses for a mistyped flag**. A caller could
   not tell "you spelled a flag wrong" from "the repository HEAD moved" from
   "there is a bug in Daedalus", and an `OSError` was reported as operator error.
3. A settled `failed` receipt — the retained domain verdict G1-ARIADNE-04 made
   the first call return — exited **0**, exactly as for a nomination. A script
   branching on the exit code read a rejected candidate as a success.

New tests before the change: **26 failed, 2 passed** (230.19 s). The two that
passed are the module door's nomination path and `--help`, which the contract
keeps unchanged.

## Scope

In scope: `daedalus/ariadne/__main__.py` (the contract and the shared body),
the `ariadne` subcommand of `daedalus/interfaces/cli/entry.py` (`_ariadne` and
its usage block only), `tests/test_ariadne_cli_exit_codes.py`, this packet and
its evidence.

Out of scope and deliberately untouched: `daedalus/ariadne/campaign.py` (every
outcome, refusal class, refusal timing and receipt field is exactly as
G1-ARIADNE-04/05/06/07 left it), the HTTP facade `/api/ariadne` (its status
mapping is its own contract and no CLI change reaches it), the effect-boundary
registry (`cli.ariadne_campaign` keeps its row, its `daedalus.ariadne.__main__:main`
target, its effect tuple and its `begin_effect` `GuardAnchor` — mapping exit
codes is not a change of what the door may do, so **the registry digest is not
re-pinned**; the pin family above proves it did not move), the `council`
subcommand, promotion.

## Contracts and behavior

Both doors call one function, `daedalus.ariadne.__main__.run_cli(argv, prog=...)`,
so they cannot drift apart. The caller owns its effect boundary: `main` still
calls `begin_effect("cli.ariadne_campaign", ...)` as its first statement, before
argument handling, exactly as the registered `GuardAnchor` requires.

| code | condition | stdout | stderr |
| --- | --- | --- | --- |
| 0 | settled receipt, `outcome == "nominated"` | the receipt | empty |
| 1 | settled receipt, any other outcome (`rejected`, `failed`, `cancelled`, or one this contract predates) | the receipt | empty |
| 2 | `AriadneRequestError` | error document | empty |
| 3 | `AriadneConflictError` | error document | empty |
| 4 | `LoopHalted` | error document | empty |
| 5 | any other `AriadneCampaignError` | error document | empty |
| 64 | argparse usage error (`EX_USAGE`) | error document | argparse's usage text |
| 70 | any other exception (`EX_SOFTWARE`) | error document | the traceback |

- Error document: `{"error":{"kind":...,"message":...}}`, always exactly one
  compact line whether or not `--json` was passed, because a script must be able
  to read one without buffering to find its end. `json.dumps` escapes any
  newline inside the message, so the line really is a line. Kinds are `request`,
  `conflict`, `halted`, `campaign`, `usage`, `internal`.
- Receipts are the **bare** canonical document. The subcommand's
  `{"ok": true, "ariadne": ...}` wrapper is dropped: it had no consumer in the
  tree (measured — the only other hits are the HTTP facade's own separate
  envelope and its tests), and its `ok` was `true` for a settled `failed`
  receipt, which is the third baseline defect above.
- `--json` renders the receipt as one compact line; without it the receipt stays
  indented for a human. Errors ignore the flag by design (previous point).
- `classify_failure` order is load-bearing and pinned by a test:
  `AriadneRequestError` and `AriadneConflictError` are **subclasses** of
  `AriadneCampaignError`, so classifying the base first would make both named
  classes unobservable and collapse 2, 3 and 5 into one code.
- Code 5 exists because the base class is genuinely raised for causes that are
  neither a request shape nor a conflict (`campaign_id must be ...` on one side,
  `inner attempt effect needs reconciliation: ...` on the other). Folding it into
  2 would call an integrity failure an operator error; folding it into 70 would
  print a traceback for a typo. A later packet that re-raises one of those as
  `AriadneRequestError` moves that case from 5 to 2 — a deliberate, visible
  contract change, recorded here so it cannot happen silently.
- 64 and 70 are not invented here. They are taken from BSD `sysexits.h`
  (`/usr/include/sysexits.h`): `EX_USAGE` 64, "command was used incorrectly";
  `EX_SOFTWARE` 70, "internal software error". They sit deliberately far from
  the outcome block so a mistyped flag can never be read as a refusal (baseline
  defect 2). argparse's own message still goes to stderr for the human, and is
  repeated in the document so the caller need not read stderr.
- `--help` keeps argparse's behaviour: usage text on stdout, exit 0. It is the
  one stdout output that is not a JSON document, and the only one.

## Acceptance matrix

| Check | Result (2026-09-05, worktree, `.venv` python 3.13) |
| --- | --- |
| baseline measured end to end against a real git repo and the real evaluator, both doors as child processes | the table under "Reproduced negative baseline" |
| new tests before the change | **26 failed, 2 passed** (230.19 s) |
| new tests after the change | **28 passed** (398.32 s) |
| exit 0 / 1 / 5 / 70 through the argv `main` function, both doors | pinned, receipt or document asserted, stderr asserted empty (70 excepted) |
| exit 2 / 3 / 4 / 64 through a real child process, both doors | pinned, exit code is a process code |
| kill switch armed in a tmp control root via `DAEDALUS_KILLSWITCH`, then stopped | exit 4, `kind == "halted"`, no state left behind |
| both doors answer a conflict with byte-identical stdout and exit code | pinned |
| stage suites (`test_ariadne_campaign_v0.py`, `interfaces/test_http_ariadne.py`, `test_cli_effect_boundary.py`, `test_registry_new_doors.py`, `test_kernel_contracts_have_producers.py`) | **156 passed, 0 failed** (309.05 s) |
| registry pin family (`test_effect_boundary.py`, `test_registry_facade_order.py`, `test_registry_retired_rows.py`, `test_registry_shadowing.py`, `test_runtime_registry_portable.py`, `test_loop_entrypoint_guard.py`) | **111 passed, 14 subtests passed, 0 failed** (474.94 s) — the `cli.ariadne_campaign` row and the registry digest are untouched and were **not** re-pinned |

## Migration and rollback

Rollback is `git revert` of one commit: the previous `__main__.py` (no failure
handling, exit 0/1) and the previous `_ariadne` (prose on stderr, exit 0/2)
return, and the test file is deleted. Nothing persisted changes: no receipt, no
CAS blob, no ledger row, no spine record and no evidence artifact is written,
read or shaped differently by this packet — only what a process prints and the
integer it exits with.

The one behavioural break for an existing caller is intended and is the point of
the packet: a script that treated exit 0 as "a candidate was nominated" was
already wrong for a `failed` receipt and now gets 1; a script that treated exit 2
as "refused" must now distinguish 2, 3, 4, 5 and 64. No in-tree caller exists
(measured), so the migration is documentation: the contract table is in the
module docstring and in `daedalus --help`.

## Evidence, expected failures, and review

- Evidence: `runs/g1-ariadne-09/stage-suites.log.txt` (affected suites),
  the baseline table above (measured by driving both doors as child processes
  against a real repository before any edit).
- Expected failures retained: the module door's nomination path and `--help`
  passed before the change and still pass — recorded rather than deleted,
  because a new test file that is entirely red proves less than one that names
  which behaviour was already right.
- Known limitation, stated rather than hidden: exit 5 is only as narrow as the
  exception hierarchy in `campaign.py`. Every bare `AriadneCampaignError` shares
  it, including request-shaped ones (`campaign_id must be ...`). Narrowing them
  is a `campaign.py` change and campaign.py is out of scope here.
- Not done: no HTTP facade change (its status mapping is a separate contract and
  no CLI code reaches it); no effect-boundary row added or moved; no `daedalus
  ariadne` effect boundary introduced — the subcommand still relies on the inner
  `python.ariadne_campaign` lease exactly as before, which is a pre-existing
  asymmetry with the module door and belongs to whoever owns that row.
- Review requested from Codex as a room turn. Not merged, not promoted.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
