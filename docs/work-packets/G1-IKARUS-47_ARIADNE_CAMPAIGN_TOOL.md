# G1-IKARUS-47 — The computer loop can run one Ariadne controlled-repair campaign on the registered project, nominating only

Packet ID: `G1-IKARUS-47`
Artifact role: `primary`
Status: `built; packet suites green; mutation table 19/19 caught; one live campaign nominated through the loop and one refused at the leakage boundary; independent review pending; not promoted`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `b29105affb32fdc1f20624e20de1bf4074488786`
Stacking: on `packet/g1-ikarus-46-daedalus-tools-20260910` at that commit (`b29105af`); rebased onto that packet's final commit before independent review
Dependencies: `G1-IKARUS-46 (act verbs, computer_task offer, daedalus.* observations, egress gate per lane), G1-ARIADNE-05/06/10 (working-tree base binding, unsupported worktree layout, leakage boundary as code), G1-SELF-00/01 (the campaign as evidence)`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion and Gate transition are
forbidden. The tool NOMINATES. Nothing in this packet applies a candidate to
any checkout, and the campaign never writes into the subject repository.

Owner instruction (2026-09-10, verbatim): *"doch auch Mutationen der soll sich
selbst verbessern und code generation starten können"*; *"Genesis und Ariadne
sollen Teil des Daedalus Kernels sein Ikarus ist sein interface, quasi ein
SuperAgent"*; 15:05: *"brute force die Hermes Jarvis fähigkeit und die
selbstverbesserung … der soll völlig autonom meinen PC benutzen können"*. This
packet is the second of the sequence G1-IKARUS-46 opened: it gives the loop
the door through which the kernel's self-Renovation campaign is reached. It
does not claim self-improvement (see "What this packet does not claim").

## Primary acceptance claim

**One** claim: *the Ikarus computer loop, under the owner's computer policy,
can hand a planner-proposed bounded repair (`target_path`, `before`, `after`)
of the registered project to the canonical `daedalus.ariadne.run_campaign`
through one new policy-scoped tool, `daedalus.ariadne_campaign`; the campaign
runs its three arms under equal budgets in a checkout-external workspace under
the control root, the subject checkout is untouched, the receipt is retained
as evidence, the planner sees a projection of the receipt that carries no
host path, and the nominated candidate is never applied.*

Measured before this packet `[MEASURED 2026-09-10 15:20, worktree jarvis-47 at b29105af]`:

| probe | result |
| --- | --- |
| `"daedalus.ariadne_campaign" in ALL_COMPUTER_TOOLS` | `False` |
| `ComputerPolicy(workspace=…, tools=("daedalus.ariadne_campaign",))` | refused: `tools must be unique known computer tools` |
| `"daedalus.ariadne_campaign" in TOOL_SPECS` | `False`; `_HOST_MUTATION_TOOLS` has 9 members |
| `/computer enable ariadne` | (by code, `computer_loop.py` enable branch) refused: `Use /computer enable daedalus [confirm-remote] or /computer disable daedalus` |
| how G1-SELF-00/01 reached the campaign | the `cli.ariadne_campaign` door and `POST /api/ariadne`; no chat or loop path exists (`grep -rn ariadne daedalus/orchestration/ikarus/` = 0 hits) |

## What this packet does not claim

- **Not "Daedalus improves itself".** The campaign's evaluator is the frozen
  exact-match evaluator of `daedalus/ariadne/campaign.py`
  (`EVALUATOR_SOURCE`, sha256 pinned): the repair arm passes iff the target
  file's bytes equal the `after`-applied bytes; baseline and negative control
  fail by construction. That proves isolation, provenance, budget equality,
  nomination and non-application — G1-SELF-01's exact claim — not that the
  change is better. An evaluator that runs the project's own tests in every
  arm is an evaluator change and therefore a separate packet (master plan
  §10: "evaluator change belongs in a separate packet"); it is named in the
  sequence below as G1-IKARUS-48. The grant text says this in the owner's
  language.
- **Not a new runner.** The tool calls `run_campaign` exactly as the CLI and
  HTTP doors do. No second campaign implementation, no clone, no scheduler.
- **Not a subject for linked worktrees.** `run_campaign` refuses a subject
  whose `.git` is a gitdir pointer (G1-ARIADNE-06: bytes a candidate could
  rewrite). The registered project must be a plain checkout; the refusal is
  surfaced verbatim. This packet's own worktree therefore cannot be its live
  subject; the live run uses a plain clone.

## Scope

In scope (files changed or added):

- `daedalus/kernel/policy/computer.py` — `ARIADNE_TOOLS = ("daedalus.ariadne_campaign",)`,
  in `ALL_COMPUTER_TOOLS`. A fresh `/computer setup` still grants nothing.
- `daedalus/runtimes/computer.py` — the `TOOL_SPECS` row (`target_path`,
  `before`, `after`, optional `campaign_id`, optional `timeout_s`); the tool
  in `_HOST_MUTATION_TOOLS` (it writes under the control root and runs the
  frozen evaluator); `ComputerService(..., campaign_runner=None)`; capability
  unavailable without a project, readers or runner; dispatch to the adapter;
  `filesystem_scope_kind: "control-root-ariadne-campaign"`; the adapter's
  `effect_state` honoured like the file adapter's (`none` before the campaign
  was entered, `uncertain` after).
- `daedalus/runtimes/computer_ariadne.py` (new) — `CampaignRunner`
  (injected: `run_campaign`, `head_revision`) and `AriadneCampaignTool`:
  bounds the arguments, refuses the leakage boundary and mandatory-ignored
  roots BEFORE the runner is called (pure path admission through the same
  `protected_prefix_for`), resolves the registered project's repository root
  through the registry, reads HEAD through the injected reader, calls the
  runner, and projects the receipt: outcome, campaign id, selected arm and
  seed, trial verdicts with wall time, budget equality, negative outcomes,
  candidate/nomination/receipt sha256 — never a locator or host path; the
  target path is echoed only if the lane's gate admits it.
- `daedalus/orchestration/ikarus/computer_loop.py` — `register_campaign_runner`
  / `campaign_runner()` (a REGISTRY: the loop itself must not import
  `daedalus.ariadne` — `[MEASURED 2026-09-10]` one such import merged the
  cross-domain import cycle from 19 to 22 modules, which the census pins
  forbid) and `head_revision()` (bounded read-only `git rev-parse`); the
  runner is handed to the service and to `computer_status`; a process without
  a registered factory reports the tool unavailable with the reason;
  `/computer enable ariadne confirm-campaigns` and
  `/computer disable ariadne` (compare-and-replace on the policy digest; the
  grant needs a one-use confirmation because model-authored edits are then
  EXECUTED by the frozen evaluator in an isolated workspace and nominated);
  the status text lists both.
- `daedalus/interfaces/http/web_api.py` — `_campaign_runner()` (the same lazy
  `run_campaign` import `POST /api/ariadne` uses, plus `protected_prefix_for`
  and the loop's `head_revision`) registered with the loop at import: the
  cockpit chat's process has the door; a process that never imports the web
  API (a bare CLI) reports it unavailable.
- `docs/IKARUS_COMPUTER.md` — the tool, the grant, the honesty notes.
- Tests: `tests/runtimes/test_computer_ariadne.py` (new),
  `tests/test_ikarus_computer_dispatch.py` (grant/revoke), pins.

Forbidden paths (not touched): `daedalus/ariadne/`, `daedalus/spine/`,
`daedalus/kernel/` except `policy/computer.py`, `daedalus/kernel/promotion*`,
the plan, the amendment chain, `AGENTS.md`, `CLAUDE.md`, `.agentenv/`.

## Contracts and behavior

- Tool `daedalus.ariadne_campaign` arguments: `target_path` (repository-relative,
  ≤ 1000 chars, no NUL), `before` (non-empty), `after` (may be empty),
  `campaign_id` (optional; default `ikarus-<sha256 of the operation>[:24]`;
  1–64 chars of `[A-Za-z0-9._-]`), `timeout_s` (optional integer 1–120,
  default 30; the campaign's own lease is 3× that).
- Result (projection, `daedalus-computer-ariadne-result/1`): `outcome`
  (`nominated` or the negative outcome the receipt names), `campaign_id`,
  `source_revision`, `target_path` (gated), `selected_variant_id`,
  `selected_seed`, `selection_mode`, `trials[]` = `{variant_id, status,
  wall_time_ms, negative_outcomes, blockers}`, `budget_equality`
  (`configured_equal`, `realized_usage_recorded`, `within_budget`),
  `negative_outcomes[]`, `candidate_tree_sha256`, `nomination_receipt_sha256`,
  `campaign_receipt_sha256`, `evaluator: "ariadne-frozen-evaluator (exact match)"`,
  `applied: False`, `postcondition_verified: True` iff the receipt was retained
  and its sha256 re-read matches. No locator, no absolute path, no `after`
  text echoed back.
- Refusals before any effect (`effect_state = "none"`): tool not granted; no
  project / readers / runner; argument shape; `target_path` inside the
  self-Renovation leakage boundary or a mandatory-ignored root; `before ==
  after`; `timeout_s` out of bounds.
- Refusals or failures after the runner was entered (`effect_state =
  "uncertain"`): surfaced with the campaign's own error class name and text
  (`AriadneRequestError`, `AriadneConflictError`, `AriadneCampaignError`); the
  computer lease stays STARTED for reconciliation, exactly as for a file
  adapter failure after the effect.

## Acceptance matrix

| # | check | how |
| --- | --- | --- |
| A1 | policy: the tool is a known family; a fresh policy grants nothing | unit |
| A2 | `TOOL_SPECS` row validates the five arguments; unknown keys refused | unit |
| A3 | capability unavailable without project / readers / runner, with the exact reason | unit through `ComputerService.capabilities()` |
| A4 | pre-run refusals: leakage boundary (each `SELF_RENOVATION_PROTECTED_PREFIXES` entry, case-folded), mandatory-ignored root, `before == after`, bounds — the runner is NEVER called (a runner that raises on call proves it) | unit |
| A5 | the projection carries no locator, no absolute path, no `after` text; the target path goes through the lane's gate | unit with a fake runner returning a real-shaped receipt containing host paths |
| A6 | the campaign id default is deterministic per operation; a supplied id is validated | unit |
| A7 | `effect_state` is `none` for pre-run refusals and `uncertain` for a runner failure; the service keeps the lease STARTED in the latter case | unit through `ComputerService.execute` with a fake runner that raises |
| A8 | **real campaign through the real lease**: a plain-git scratch subject registered as the project, the REAL `run_campaign` as runner, an armed kill switch and a scratch spine for the subject: outcome `nominated`; `git status --porcelain` of the subject empty before and after; the campaign's evidence exists under the subject's control root; the retained computer result carries `host_mutation: True`, `filesystem_scope_kind: "control-root-ariadne-campaign"`, `applied: False`; the result JSON contains no host path | integration (the pattern of `test_the_real_adapter_through_the_real_lease_…`) |
| A9 | a linked-worktree subject is refused verbatim by the campaign and reported `uncertain`… no: the refusal comes from `_verify_head` BEFORE any lease inside `run_campaign`; it is surfaced with its text and the computer lease is settled as a failed effect (the adapter cannot prove "no effect" once the runner was entered) | integration |
| A10 | `/computer enable ariadne` without `confirm-campaigns` answers `confirmation_required` and changes nothing; with it, the tool joins the policy through compare-and-replace; `/computer disable ariadne` removes it; the grant text names the frozen exact-match evaluator, the control-root workspace, the untouched subject and non-application | dispatch tests |
| A11 | the offer of G1-IKARUS-46 lists the tool once granted; a `/computer run` mission can reach the tool (fake planner proposing it) and the mission report shows the outcome | loop test with a fake service |
| A12 | census pin unchanged (no runtimes→ariadne import); work-packet registry, s02 corpus and imports graph re-pinned | contract suites |
| A13 | mutation table: every guard above disabled one at a time is caught | driver |
| A14 | live: one real campaign through the loop with the Claude planner on a plain clone of this repository (target: a docstring), retained under `docs/evidence/G1-IKARUS-47/` with the ledger rows; and one refused attempt on a protected path | measurement |

## Measured

`[MEASURED 2026-09-10 15:20–16:20, this host, worktree jarvis-47, authority
control root 0c70d5e4cc69, subject = a plain clone of this branch at
b29105af under %TEMP%\dd47-subject (control root 5b7ca2e5473f), scratch
ledger runs/jarvis-47/scratch-ledger-47.json, Claude planner]`

| check | result |
| --- | --- |
| A1–A7, A10, A11 | `tests/runtimes/test_computer_ariadne.py` (39), `tests/test_ikarus_computer_loop_ariadne.py` (2), `EnableAriadneTest` (5) green; the fifteen packet, neighbouring, Ariadne, census, registry and imports-graph suites: see `docs/evidence/G1-IKARUS-47/acceptance.json` |
| A8 real campaign through the real lease | nominated; the subject's tracked tree and HEAD unchanged; the only file the campaign adds inside the subject is its record in the subject's canonical spine (`runs/spine/spine.sqlite3`, invariant 1; ignored by this repository's `.gitignore`); evidence under the subject's control root; `host_mutation: True`, `filesystem_scope_kind: control-root-ariadne-campaign`, `applied: False`; no host path in the retained result |
| A9 linked worktree | refused by the campaign (`AriadneRequestError … linked git worktree`), surfaced verbatim; the subject unchanged |
| A12 pins | census 521 modules / 2104 edges, components and digest unchanged — after the loop's direct `daedalus.ariadne` import was replaced by the registry (that import had merged the cross-domain cycle 19 → 22); registry 529 tracked files / 463 packet ids; s02 re-pinned after the rebase |
| A13 mutation table | 19 guards: 18 caught in the first pass; M14 (execution admits the tool without a runner) survived as a guard masked by the dispatch refusal behind it, got a pre-lease pin and was re-run alone: caught (`mutation-table-1.txt`) |
| A14 live run 1 | **negative evidence, retained.** `daedalus.slice` ok; then the KERNEL refused the campaign step: `ComputerPolicy.admit` applied the workspace path rule to `before`/`after` by KEY NAME (image paths for `vision.changes`, text fragments for the campaign) — "path must remain relative to the computer workspace". Repaired: `_PATH_ARGUMENT_KEYS` names the campaign's path argument (`target_path`, held to the same lexical rule), pinned by `test_the_policy_path_rule_holds_the_target_path_and_leaves_the_text_fragments_alone`. 2 planner calls, $0.20 |
| A14 live run 2 | same objective ("nominiere per daedalus.ariadne_campaign eine Docstring-Verbesserung in daedalus/build.py …"): `daedalus.slice` → `daedalus.ariadne_campaign` → **`nominated`**, campaign `ikarus-9f205ae3e05ee82b5715ffe4`, `before` "This module is deterministic and additive." → `after` "This module's behaviour is deterministic and purely additive: identical inputs yield an identical plan, and no existing state is mutated.", arms failed/failed/passed, budget equality true; 3 planner calls, 53.9 s, ≈ $0.33; subject clone clean (`git status --porcelain` empty, HEAD unchanged); campaign evidence under the subject's control root; nothing applied |
| A14 live run 3 | a planner-proposed change to `daedalus/spine/killswitch.py`: refused at step 1 by `_PreRunRefusal` (leakage boundary, master plan §8.1) before the runner was entered; mission `blocked`, no repeat, no campaign evidence written; 1 planner call, 10.9 s |
| clone trap | a clone under the worktree path fails on Windows (`Filename too long`, MAX_PATH): the subject lives under a short `%TEMP%` path |

Total live spend on the scratch ledger: $0.60 (12 rows, worst-case reserve $3.00 per Claude call, settled $0.07–0.12).

## Review round 1 (2026-09-10, `70eeb25e`)

**Cerberus: `block`.** CRITICAL 1 — the adapter's refusal and failure texts
interpolated the exception message (`git rev-parse` stderr, the campaign's
`repo_root is unavailable or unsafe: [WinError 2] … 'C:\…'`, the registry
error) and that text reaches the planner's history through `outcome["error"]`;
MAJOR 2 — the grant text said "der Projektbaum wird nie beschrieben" while the
campaign records itself in the subject's canonical spine under `runs/spine/`;
minor — runner re-registration was last-wins. Cleared: trust surface, admission
before effect (18 spellings), the kernel path rule (no tool loses a key),
projection egress, grant compare-and-replace, registry fail-closed, invariants.

**Odysseus** (executed probes, real campaigns on scratch subjects):

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D1 (high) | a directory JUNCTION inside the subject (`shortcut` → `daedalus/spine`) is not `S_ISLNK`; `shortcut/killswitch.py` passed every string check and the campaign NOMINATED a change to a protected file (nothing applied — invariant 5 held; §8.1 bypassed) | `_admit_target_file`: the real path is resolved (junctions and symlinks included), must stay inside the resolved subject, must spell the very path requested, is held to the leakage boundary again, and must be a regular file — reads only, before the runner | `test_a_junction_inside_the_subject_cannot_reach_the_leakage_boundary` (Windows), `test_a_missing_or_non_regular_target_is_refused_before_the_runner`; M24 |
| D2 (medium-high) | `daedalus/spine./killswitch.py` (Windows strips the trailing dot) passed the adapter's and the campaign's string checks; the campaign read and materialized the protected file before failing for another reason; only the kernel path rule stopped it in production | every segment is held to the kernel's lexical rule here (no trailing dot/space, no `:`, no Windows-invalid character, no device name, no `.`/empty segment); plus the resolved-path check above | the parametrized pre-run refusals; M25 |
| D3 (medium) | `./daedalus/spine/x.py`, `daedalus/./spine/x.py` and a looser `campaign_id` rule reached the runner and were refused there — misclassified `uncertain`; a missing target likewise | refused lexically before the runner; the campaign's own `campaign_id` rule; a missing or non-regular target is a pre-run refusal | same; `test_every_pre_run_refusal_precedes_the_runner` |
| D4 (medium) | `postcondition_verified` was true for any receipt saying "nominated" | backed: two well-formed digests AND the campaign's evidence directory present under the subject's control root (`evidence_present` reported beside it) | `test_the_postcondition_is_backed_by_the_evidence_directory`; M26 |
| D5 (medium) | = Cerberus CRITICAL 1 | `_safe_failure_text`: class name always, the message only if it names no host path; the registry refusal class-only | `test_failure_texts_keep_the_class_and_drop_a_message_that_names_a_host_path`; M20, M21 |
| D6 (low) | the projection rendered three times and gated render two | the receipt is rendered ONCE; digest and projection come from that rendering | `test_the_projection_is_rendered_once_and_bounded`; M29 |
| D7 (low) | a no-op grant/revoke claimed "applied" | `ariadne_tools_change: unchanged`, nothing written | `test_a_no_op_grant_or_revoke_says_so_and_writes_nothing`; M27 |
| D8 (low) | `/computer enable Ariadne` fell through to the daedalus usage text | the subcommand token is case-folded | `test_the_subcommand_token_is_case_insensitive`; M28 |
| D9 (low) | unbounded projection lists; no runner type check; NaN escaped as a bare `ValueError` | trials/lists bounded with `*_elided`; `CampaignRunner` type checked at admission and construction; an unrenderable receipt is a `_CampaignFailure` | `test_the_projection_is_rendered_once_and_bounded`, `test_a_runner_of_the_wrong_type_is_refused` |
| MAJOR 2 | grant text | "der versionierte Projektbaum wird nie beschrieben (… kanonische Spine … `runs/spine/`, Invariante 1)" | `EnableAriadneTest`; M23 |
| minor | last-wins registration | first wins; a different factory is refused; `None` unregisters | `test_a_process_without_a_registered_runner_reports_the_tool_unavailable`; M22 |

**Narrowed claims, stated honestly.** "Refused before any effect" means before
any CAMPAIGN effect: every refusal raised inside the adapter happens under the
computer lease, whose evidence records are written and then settled as
cancelled (nine files); only a pre-lease refusal (no runner, unknown tool)
leaves nothing. A live service keeps the runner it was constructed with after
`register_campaign_runner(None)`; the registry is a composition-root binding,
not a per-call lookup.

**Finding for another owner (not this packet's to fix).** The campaign's own
doors (`daedalus ariadne`, `POST /api/ariadne`) share D1 and D2: `_admit_target_path`
in `daedalus/ariadne/campaign.py` tests the requested string, and
`read_repository_source` refuses `S_ISLNK` only, so a junction or a trailing
dot reaches a protected file there too. Recorded on the coordination board
as a proposed G1-ARIADNE-11; this packet closes the hole at its own door.

## Review round 2 (2026-09-10, `d7b5b072`)

**Cerberus: `block`, one CRITICAL.** NEW-1 — `_project_receipt` called
`self._repo_root()` a SECOND time, after `run_campaign` had returned. A
registry read that fails there raised `_PreRunRefusal`, whose contract is
`effect_state = "none"`, so the service settled the lease as "provably no
campaign effect" while the campaign had written its lease, its ledger rows and
its evidence. Odysseus reproduced it independently (its D10) by failing
`load_project` on the second call: the runner recorded one call and the service
returned `state="blocked", error_type="_PreRunRefusal"`. Repair: the projection
receives `repo_root` (and `started_at`) as arguments, and every check it makes
is wrapped so a failure reads as "not verified", never as a refusal. NEW-2
(medium) — the `_admit_path` docstring said the target echo is admitted by the
lane's gate, which overstates the TRUSTED lane, where `slice_egress_rule`
applies the secret floor only; the docstring now says so (pre-existing
behaviour, not changed here). NEW-3 (low, TOCTOU between the admission stat and
the campaign's own read) and NEW-4 (low, presence is not causation for the
evidence check) are stated below rather than closed. D1/D2/D6-D9 of round 1
were confirmed resolved.

**Odysseus** (frozen `git archive` copy, executed probes, 55/55 baseline):

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D10 (medium) = Cerberus NEW-1 | the postcondition check re-read the registry after the campaign ran; a failure there misclassified a real effect as effect-free | `repo_root` and `started_at` are arguments; nothing after the runner raises | `test_nothing_after_the_runner_can_raise_a_pre_run_refusal`; M34 |
| hard link (low-medium) | `mklink /H pkg/hard.py daedalus/spine/killswitch.py` — one inode, two names: `realpath` returns the requested spelling, so every lexical and resolved check passed and the campaign was admitted for a protected file. The kernel HAS an `st_nlink` check but resolves against the computer workspace, so it never sees the subject | `_admit_target_file` refuses `st_nlink > 1` | `test_a_hard_link_to_a_protected_file_is_refused_before_the_runner`; M30 |
| D4 residue (medium) | the default `campaign_id` is a digest of the OPERATION, so a second call with the same arguments inherited the first run's evidence directory: a forged receipt (a runner that writes nothing) reported `postcondition_verified=True` | the evidence must carry a timestamp from THIS run (`started_at` minus a 2 s filesystem tolerance) | `test_the_evidence_must_have_been_written_during_this_run`; M32 |
| D11 (low-medium) | `campaign_id` had no filesystem-spelling rule although the target segments do: `CAMP1`, `camp1.` and `con` name the same or no directory on Windows | lower case, no trailing dot or space, no reserved device name | `test_a_campaign_id_is_held_to_the_filesystem_spelling_of_its_directory`; M31 |
| D9 residue / D12 (low) | counts were bounded, VALUES were not: a 2 MB receipt field produced a 2.5 MB projection | every projected STRING is cut at 200 characters with the loss stated — integers were still unbounded until round 3 (D16) | `test_every_projected_value_is_bounded_not_only_every_list`; M33 |
| D1, D2, D3, D5, D6, D7, D8 | re-attacked: junctions (intermediate and terminal), 8.3 short names (`IKARUS~1.MD`), case and Unicode spellings (`daedaluſ`), `::$DATA`, trailing dot, 24 malformed shapes, a stateful `__str__`, the case-folded subcommand | confirmed resolved; a case-different but legitimate spelling (`Pkg/Mod.py`) is still admitted, so the rule does not over-refuse | the existing round-1 tests |

**Not closed, stated.** A file symbolic link could not be measured on this host
(`WinError 1314`, the token has no `SeCreateSymbolicLink`); the resolution
mechanism is proven by the junction case plus an `S_ISLNK` test. The evidence
check proves that evidence appeared under this campaign's directory during this
run — presence, not causation (Cerberus NEW-4); a receipt is not tied to the
files by a digest. Between the admission `stat` and the campaign's own read the subject could
change (NEW-3). Round 2 claimed the campaign's own `before` mismatch closes
that window. **That claim was false and is withdrawn:** `before` is chosen by
the planner, which can pick a fragment that occurs in the file it wants to
reach, and Odysseus won the race 12 times out of 12 (round 3, D13). The window
is closed at the read instead — see round 3.

## Review round 3 (2026-09-10, `a2a6198d`)

**Odysseus: one HIGH with an executed end-to-end exploit, one HIGH/MEDIUM, two
MEDIUM, six LOW.** The round-2 repairs held where they were measured: no
`_PreRunRefusal` is reachable after the runner (11 injections at the seam; the
three exceptions that do escape carry no `effect_state`, and the service
requires the literal `"none"` for this family, so they reconcile instead of
claiming no effect); every static link shape is refused; the campaign-id regex
is ASCII, so no Unicode folding route exists at all.

| # | finding | repair | pinned by |
| --- | --- | --- | --- |
| D13 (HIGH, executed) | the `st_nlink` refusal is admission-time, and the campaign's own reader never checked it. A concurrent writer that swapped the admitted file for a HARD LINK during the `git rev-parse` window won every attempt (0.39 ms writer against a 12.2 ms window) and the REAL campaign, through the REAL lease, nominated a candidate carrying `daedalus/spine/killswitch.py` bytes, with those bytes in six control-root files. Nothing was applied (invariant 5 held), but a §8.1 leakage boundary was crossed | the check moves to where the read is atomic: `os.fstat(descriptor).st_nlink > 1` in `read_repository_source`, beside the existing device/inode/size race check. This is a deliberate, minimal extension of this packet's scope into `daedalus/gates/repository/tree.py`, because the hole is reachable through the door this packet opens and closing it at the door only narrows the window | `test_a_hard_link_is_refused_on_the_open_descriptor` (the reader's own suite); M35 |
| D14 (HIGH/MEDIUM) | a planner-supplied `campaign_id` named the evidence directory with no binding to the operation, so campaign B borrowed campaign A's FRESH evidence and reported a verified postcondition — the round-2 fix closed re-using your own stale directory and left borrowing someone else's open | the id always carries the operation digest: a supplied label is TRUNCATED at 40 characters and COMPOSED as `<label[:40]>-<digest12>` (worst case 53, inside the campaign's own 64-character rule), the default stays `ikarus-<digest24>`. The id in the result is therefore composed, not echoed; two labels differing only after character 40 with the same operation share one directory, which is identical work under two names | `test_a_campaign_id_is_held_to_the_filesystem_spelling_of_its_directory`, `test_the_default_campaign_id_is_deterministic_per_operation_and_a_given_label_is_bound_to_it`; M36 |
| D15 (MEDIUM) | the freshness floor had no ceiling: one file dated a year ahead verified every later forgery | bounded on both sides (`floor <= mtime <= now + tolerance`) | `test_evidence_with_a_future_timestamp_does_not_verify_forever`; M37 |
| D16 (MEDIUM) | `_short` passed every integer through, so only CPython's 4300-digit conversion limit bounded the projection — 62 KB out of rules that promise 200 characters — and the packet's own row said otherwise | an integer wider than 256 bits is described, not rendered; the row above is corrected. Stated for completeness: a receipt carrying an integer past CPython's conversion limit cannot be rendered at all, so that campaign is reported as `uncertain` and reconciled rather than nominated — the fail-safe of the round-1 "not renderable" rule, and unreachable through the canonical runner | `test_a_large_integer_in_the_receipt_is_described_not_rendered`; M38 |
| D17 (LOW-MEDIUM) | two of the three legs of the round-2 repair were mutation-invisible: no test made the evidence check or the projection's gate call fail | both are exercised, so removing either guard is caught | `test_a_failing_evidence_check_reads_as_unverified_never_as_a_refusal`, `test_a_failing_gate_call_in_the_projection_withholds_the_target`; M42, M43 |
| D18 (LOW) | a Mapping that is not a `dict` renders to a STRING through `default=str`, and every read then raised an unclassified `AttributeError` | classified: "campaign receipt is not an object" | `test_an_unreadable_receipt_shape_is_classified_not_crashed`; M40 |
| D19 (LOW) | the projection echoes the REQUEST, so a receipt about another campaign was reported under this campaign's id and target | the receipt's own id and revision are compared with the request; a mismatch is reported and fails the postcondition | `test_a_receipt_about_another_campaign_does_not_verify_the_postcondition`; M39 |
| D20 (LOW) | an unreadable list shape read as "empty, nothing elided", so the planner could not tell it from "no trials" | `trials_readable` and `negative_outcomes_readable` | the same test; part of M40's suite |
| D21 (LOW) | `budget_equality` passed `"false"` and `0` through, which a JSON consumer reads as true flags | a boolean or nothing | the same test; M41 |
| D22 (LOW) | the truncation marker is text a producer could write itself | stated in `_short`'s docstring; the marker is a hint, and `trials_readable`/`*_elided` are the load-bearing fields | — |

**Not reproducible on this host, stated:** 8.3 short names (the volume has 8dot3
disabled) and a file symbolic link (the token has no `SeCreateSymbolicLink`).
Neither is claimed closed; the junction case exercises the same resolution.

**Still true after this round:** the evidence check is presence during this run,
not causation — no digest ties a receipt to the files it points at. The id now
binds the directory to the operation, which is what D14 needed, but a dishonest
runner remains outside what this adapter can verify.
`receipt_contradicts_request` says what it measures: a receipt that asserts
nothing does not contradict the request, which is weaker than matching it.

**Cerberus round 3 (`3f7de763`): `approve`, the round-2 block lifts.** The
CRITICAL was verified closed by executing both revisions against the same
injected failure. Four low findings, all repaired or written down here: the
comparison above was named "matches" while it measures "does not contradict";
the id composition truncates at 40 characters, which the D14 row now states;
the hard-link refusal also refuses reads inside a `.venv` or a pnpm-style
`node_modules` in the subject (measured: 3810 of 4951 sampled files there are
hard links), which is the right answer for a repair campaign and is now stated
at the check; and a pre-existing one that is NOT this packet's to fix — a
failure text can name a deny-listed target path that the success projection
withholds, because `_safe_failure_text` gates host-path SHAPE, not the
project's deny list. That is recorded on the coordination board beside
G1-ARIADNE-11. Cerberus also re-stated a standing medium it has raised before:
on the TRUSTED lane the secret floor alone applies, so a deny-listed path is
echoed there; the owner should confirm that relaxation is intended.

**Odysseus round 4 (`3f7de763`): every round-3 repair holds under attack.** The
TOCTOU exploit that won 12 of 12 attempts now wins 0 of 3000 threaded
iterations; a hard link refuses under both names, and a read-path census found
that the only subject-tree byte read in the campaign goes through
`read_repository_source`, so nothing bypasses the new check. The id binding,
the freshness window on both edges, the integer bound (a fully loaded receipt
now projects to 44 118 bytes) and the receipt-identity comparison all held, and
all ten guards were re-measured red, including the two that were
mutation-invisible in round 3. Two low residues, both at the campaign's OWN
doors rather than this packet's: an NTFS alternate data stream (`file.py:hidden`)
is accepted by `campaign._admit_target_path` and by the reader's grammar, which
treats a stream that git does not track as repository source — a contract
impurity, not a section 8.1 crossing, since the protected-prefix match still
uses the base path and the computer-loop door refuses `:`. Recorded on the
coordination board for the G1-ARIADNE door owners. The other is the 40-character
label collapse already stated in the D14 row.

## Evidence, expected failures and review

`docs/evidence/G1-IKARUS-47/acceptance.json` with suites, mutation table,
pins, the live receipt projection and ledger rows; the packet document's
tables. Failures are retained.

## Migration and rollback

Revert the packet's commits; no data migration (a stored policy that grants
`daedalus.ariadne_campaign` would then fail `ComputerPolicy` validation and
the owner re-runs `/computer setup` — visible, not silent).

## Sequence

- **G1-IKARUS-48** — `run_campaign(..., evaluator="project-tests")`: each arm
  runs the registered project's `test_command` under the attempt command gate
  with equal budgets; nomination requires the repair arm to pass and the
  baseline to be recorded. The evaluator change that makes a nomination mean
  "the tests still pass". Cerberus BLOCKING.
- **G1-IKARUS-37** — `terminal.run` with an argv allowlist (forward plan C3).
- **Skill `daedalus-jarvis`** — the development skill the owner asked for on
  2026-09-10 15:05: configure the policy with every family, the planner and
  the grants, run objectives and campaigns without re-confirmation for
  reversible work. Promotion stays sealed (invariant 5) unless the owner
  amends it.
- **G1-IKARUS-49** — Genesis from the chat (`genesis_build` offer over the
  existing `run_genesis` door with `request_key` idempotency).
