# G1 general computer assistance — evidence inventory

Date: 2026-09-05
Base revision: `585b7ea4e141332928ad6c9578b9c9997e55f247` (branch
`codex/ikarus-computer-assistant-20260905`, working tree dirty: 73 entries)
Plan: revision 12, SHA-256 `126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`
[MEASURED] — unchanged from the digest pinned in G1-IKARUS-18.
Interpreter: `.venv/Scripts/python.exe`, Python 3.13.14, pytest 9.1.1, Windows 11.
All pytest runs used `-q --color=no -p no:cacheprovider`.

Classification: **ALIGNED** — read-only inventory plus three new test files that
pin existing guards. No production code, no plan, no amendment chain touched.

## Why this document exists

Plan §11, Gate 1, general computer assistance strand:

> Each capability activates only after its bounded Work Packet, independent
> review and acceptance matrix pass. Required evidence includes real adapter
> execution, verified postconditions, policy refusal, stale-target handling,
> cancellation, timeout and crash recovery.

The individual Work Packets each record their own counts. Nothing in the tree
put those seven evidence classes against §7.2's capability list in one place, so
no one could see which cells were empty. This is that table.

### Reading the table

- `real` — the live adapter or the live store on this host.
- `fixture` — a fake adapter or an in-process double; **offline fixtures prove
  contract behaviour only, never live isolation** (plan Revision 3, item 2).
- `GAP` — no test supplies this cell.
- `n/a` — the capability has no such surface (see the per-row note; an `n/a` is
  a claim about the design, not a discharged obligation).
- Every count is stamped `[MEASURED]` (run during this session, at this
  revision) or `[INHERITED]` (read from a named packet, not re-run here).

Node ids are abbreviated: a leading `~/` means `tests/`, and a bare `::name`
continues the previous file in the same cell.

---

## Matrix — capability × evidence class

Legend for the compact grid: `R` real, `F` fixture, `R+F` both, `-` GAP,
`n/a` no such surface.

| Capability | real adapter exec | verified postconditions | policy refusal | stale target | cancellation | timeout | crash recovery |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. File | R | R+F | F | F | F | F | **-** (partial) |
| 2. Application / desktop | **-** | F (guard only) | F | F | F | F | **-** |
| 3. Terminal | **n/a** (absent) | n/a | F | n/a | n/a | n/a | n/a |
| 4. Browser | R | R | R+F | R+F | F | **-** | **-** |
| 5. Document | **-** | **-** | **-** | **-** | **-** | **-** | **-** |
| 6. Integration / connectors | **-** | **-** | **-** | **-** | **-** | **-** | **-** |
| 7. Scheduled tasks | R+F | F | F | F | F | F (partial) | F |
| 8. Persistent goals / autonomy | F | F | F | F | F | F | F |
| 9. Product memory | R | R | R | R | **-** | R (partial) | R (partial) |
| 10. Skills (computer strand) | **-** (fenced) | **-** | F | **-** | **-** | **-** | **-** |
| 11. Computer vision | R | R | F | R+F | F (OCR only) | R+F | **n/a** |

**Covered cells: 44 of 77** (11 capabilities × 7 classes).
Breakdown: 44 covered, 26 `GAP`, 7 `n/a`.
Excluding the two capabilities that do not exist at all (Document,
Integration — 14 `GAP` cells): **44 of 63**.

A cell marked covered can still be partial. Three are, and they appear in the
GAP table further down alongside the empty cells: Browser × cancellation covers
only the pre-start checkpoint, Vision × cancellation covers only the OCR path,
and Scheduled × timeout covers the locks but not the mission `timeout_s`.

---

## Row detail

### 1. File — `file.list|read|write|mkdir|move`

Owner: another agent holds `tests/runtimes/test_computer_files.py` and the file
adapter today. **Inventoried only; not touched by this session.**

Packets: G1-IKARUS-24 (handle-anchored workspace files, status **HOLD** for the
crash-recovery/service contract), G1-IKARUS-25 (fence lift, phases 1 and 2 done).

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | real | `~/runtimes/test_computer_files.py` — the real Win32 handle-anchored adapter, 87 passed [MEASURED]; `~/runtimes/test_computer_service_files.py::test_file_tools_execute_through_the_anchored_adapter_with_persisted_leases` |
| verified postconditions | real+fixture | `~/runtimes/test_computer_service_files.py::test_file_tools_execute_through_the_anchored_adapter_with_persisted_leases`; byte-equality read-back cases in `~/runtimes/test_computer_files.py` |
| policy refusal | fixture | `~/kernel/test_computer_policy.py::test_traversal_ads_devices_and_control_paths_are_refused`, `::test_link_escape_is_refused`, `::test_linked_workspace_root_is_refused`, `::test_hardlinked_file_is_refused`, `::test_replacing_an_existing_file_stays_fenced`, `::test_file_tools_are_admitted_after_the_handle_anchored_lift`; `~/runtimes/test_computer_service_files.py::test_secret_content_is_refused_before_the_adapter_and_withheld_on_read`, `::test_file_tools_are_unavailable_outside_windows_in_this_release` |
| stale target | fixture | `~/runtimes/test_computer_service_files.py::test_ancestor_swap_at_the_checkpoint_is_blocked_with_zero_effect`, `::test_parent_moved_out_of_the_workspace_never_receives_model_bytes`, `::test_stale_or_missing_hash_refusals_are_blocked_not_reconciliation`; `~/runtimes/test_computer_service.py::test_ancestor_swap_at_the_checkpoint_never_writes_outside_the_workspace` |
| cancellation | fixture | `~/runtimes/test_computer_service.py::test_policy_drift_and_cancel_prevent_all_file_effects` |
| timeout | fixture | `~/runtimes/test_computer_service.py::test_deadline_refuses_before_admission` |
| crash recovery | **GAP (partial)** | `~/runtimes/test_computer_service.py::test_a_refusal_observed_after_the_effect_landed_is_never_reported_as_no_effect`, `::test_failure_records_persist_the_adapter_recovery_paths` give typed uncertainty. Restart/replay of an interrupted replacement is explicitly open: G1-IKARUS-24 is on HOLD and `docs/work-packets/G1-IKARUS-27_REPLACEMENT_CRASH_RECONCILIATION.md` exists as an untracked packet |

### 2. Application / desktop — `desktop.observe|click|type|key`, `app.launch`

Packet: G1-IKARUS-18. Its own Status line says "native desktop live acceptance
remains unmeasured" [INHERITED, G1-IKARUS-18 line 14].

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | **GAP** | `~/runtimes/test_computer_desktop.py` injects `FakeDesktop` into `DesktopAdapter._host`. The real `_WindowsDesktop` backend (foreground snapshot, capture, `SendInput`) is never executed by any test |
| verified postconditions | fixture (guard only) | The adapter deliberately returns `postcondition_verified: False` and never claims task success. What is now pinned is the *requirement* of an explicit expected postcondition: **NEW** `~/runtimes/test_computer_evidence_desktop.py::test_input_without_a_usable_expected_postcondition_performs_nothing` (15 params), `::test_an_omitted_expected_key_is_refused_as_well` |
| policy refusal | fixture | `~/runtimes/test_computer_desktop.py::test_policy_denial_precedes_capture`, `::test_fixed_launch_args_and_denial_precede_process_creation`; **NEW** `~/runtimes/test_computer_evidence_desktop.py::test_key_outside_the_allowlist_reaches_neither_capture_nor_input` (8 params), `::test_unbounded_or_control_text_reaches_neither_capture_nor_input` (7 params), `::test_caller_supplied_capture_scope_is_refused_before_any_capture` (3 params); **NEW** `~/runtimes/test_computer_evidence_terminal.py` (interpreter fence on `app.launch`, see row 3) |
| stale target | fixture | `~/runtimes/test_computer_desktop.py::test_changed_or_stale_observation_performs_zero_input[pixels\|focus\|age]`, `::test_focus_change_during_capture_discards_image`, `::test_outside_window_refuses_without_recapture` |
| cancellation | fixture | `~/runtimes/test_computer_desktop.py::test_cancel_mid_typing_prevents_next_input_and_replay` |
| timeout | fixture | `~/runtimes/test_computer_desktop.py::test_desktop_lock_contention_prevents_input` — the `ExclusiveFileLock(timeout_s=1)` that serialises interactive desktop input |
| crash recovery | **GAP** | `::test_unknown_input_outcome_consumes_token` proves an unknown outcome consumes the observation token and is never blind-replayed — the no-replay half. No test restarts the process across an interrupted input group |

### 3. Terminal

**Deliberately absent.** `ALL_COMPUTER_TOOLS` has exactly four families —
`file`, `vision`, `desktop`, `browser` (plus `app.launch`) — and no command
execution tool [MEASURED, see the new test below]. Plan §7.2 lists terminal
tasks in the strand's scope, so the capability is *listed but not activated*;
activation needs its own Work Packet under §11.

The only thing that can be evidenced today is the fence, and it was weak:
`ComputerPolicy.__post_init__` refuses 13 interpreter stems, but the single
existing test used `sys.executable`, so 12 of the 13 stems could be deleted
without a red test.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | n/a | no adapter exists (correct state) |
| verified postconditions | n/a | — |
| policy refusal | fixture | **NEW** `~/runtimes/test_computer_evidence_terminal.py::test_every_interpreter_stem_is_refused_as_a_trusted_application` (13 params), `::test_interpreter_refusal_is_case_insensitive` (4), `::test_a_shell_shaped_tool_cannot_be_configured_or_admitted` (4), `::test_the_canonical_vocabulary_contains_no_command_execution_tool`, `::test_app_launch_is_refused_when_the_owner_did_not_enable_the_application`, `::test_a_non_interpreter_application_is_still_admitted` (positive control); pre-existing `~/interfaces/test_computer_configuration.py::test_host_configuration_cannot_grant_candidate_or_interpreter_execution[interpreter\|candidate]` |
| stale target / cancellation / timeout / crash recovery | n/a | — |

Not counted here: `~/test_ikarus_os_boundary.py` (20 tests) and
`~/test_ikarus_shells.py` (42 tests) cover the *harness's own* process/egress
doors and chat routing. They are not the assistant's terminal capability and
must not be presented as its evidence.

### 4. Browser — `browser.navigate|read|click|fill`

Packet: G1-IKARUS-18.

Confirmed on this host: Playwright and the Chromium distribution are installed,
so `~/runtimes/test_computer_browser.py` really launched Chromium — the batch
below reported **0 skipped** [MEASURED]. The `real` qualifier is bounded: real
browser, disposable in-process `ThreadingHTTPServer` origin, no external network.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | real | `~/runtimes/test_computer_browser.py` — 11 collected, all against real headless Chromium |
| verified postconditions | real | `::test_live_fill_works_but_dynamic_script_actions_remain_unavailable` — the adapter re-reads `input_value()` and only then sets `field_value_verified`. This is the **only** adapter in the strand that verifies any postcondition; every other one returns `postcondition_verified: False` |
| policy refusal | real+fixture | real: `::test_ambiguous_submission_and_external_target_refused[.duplicate\|#submit\|#outside\|#download]`, `::test_password_fields_and_replayed_observations_refused`, `::test_redirect_is_not_followed`, `::test_page_script_cannot_submit_non_read_request`, `::test_script_execution_and_connect_channels_are_disabled`. offline: **NEW** `~/runtimes/test_computer_evidence_browser.py::test_a_tool_the_owner_did_not_enable_never_starts_a_browser` (3), `::test_navigation_outside_the_admitted_origin_never_starts_a_browser` (5), `::test_non_http_or_credential_urls_never_start_a_browser` (4), `::test_unknown_or_missing_browser_arguments_never_start_a_browser` (6), `::test_navigate_without_a_url_is_refused_by_policy_before_start`, `::test_the_start_tripwire_is_reachable_for_an_admitted_request` (positive control). Also `~/kernel/test_computer_policy.py::test_browser_origin_is_exact_not_hostname_prefix`, `::test_non_http_or_credential_urls_are_refused` |
| stale target | real+fixture | real: `::test_document_mutation_refuses_before_input`, `::test_password_fields_and_replayed_observations_refused`. offline: **NEW** `~/runtimes/test_computer_evidence_browser.py::test_input_without_any_observation_never_touches_the_page` (2), `::test_a_replayed_or_expired_observation_never_touches_the_page[replayed_id\|expired]`, `::test_the_page_tripwire_is_reachable_for_a_fresh_observation` (positive control) |
| cancellation | fixture | `~/runtimes/test_computer_browser.py::test_cancellation_stops_before_browser_start`; **NEW** `~/runtimes/test_computer_evidence_browser.py::test_cancellation_before_start_leaves_no_browser`. Partial: nothing cancels mid-navigation |
| timeout | **GAP** | the adapter pins `set_default_timeout(5000)`, `goto(timeout=10000)`, `fill/click(timeout=5000)` and `route.fetch(timeout=10000)`. No test makes any of them fire |
| crash recovery | **GAP** | no test kills the Chromium process or the owning worker mid-action; `close()` is exercised only on the teardown path |

Why the offline half matters: `~/runtimes/test_computer_browser.py` opens with
`pytest.importorskip("playwright.sync_api")` and skips again when the Chromium
distribution is missing. On a host without the optional `computer` extra the
whole browser policy-refusal and stale-target row silently vanishes from the
evidence. The new file holds those two rows with no browser installed.

### 5. Document

**Absent.** `grep -riE "docx|pdf|xlsx|DocumentAdapter" daedalus/runtimes/
daedalus/kernel/policy/computer.py daedalus/orchestration/ikarus/` returns
nothing [MEASURED]. There is no `document.*` tool, no adapter and no admission
seam. All seven cells are `GAP` by absence. Documents are reachable today only
as opaque bytes through the file capability.

### 6. Integration / connectors

**Absent.** No connector adapter, no admission seam; the only hit for
"connector" in the Ikarus tree is a routing keyword in
`daedalus/orchestration/ikarus/chat.py` [MEASURED]. All seven cells are `GAP`
by absence.

### 7. Scheduled tasks

Packets: G1-IKARUS-20 (scheduling), G1-IKARUS-21 (durable autonomy).
This is the best-covered capability in the strand.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | real+fixture | real kernel path: real `SpineLedger`, real CAS, real `ExclusiveFileLock`, real canonical receipts on disk throughout `~/test_ikarus_computer_schedule.py` and `~/test_ikarus_computer_schedule_autonomy.py`. Two occurrences drive a real local Chromium / real OS OCR: `~/test_ikarus_computer_schedule_autonomy.py::test_live_recurring_browser_observation_uses_real_mission_and_terminal_receipts`, `::test_canonical_ocr_observation_name_continues_with_actual_kernel_receipts`. The host tool behind an ordinary occurrence is a private fixture adapter |
| verified postconditions | fixture | `~/test_ikarus_computer_schedule_autonomy.py::test_uncertain_failed_or_unverified_occurrence_never_continues[...]`, `::test_other_missions_real_terminal_evidence_cannot_authorize_recurrence`, `::test_recurring_finite_chain_retains_policy_and_waits_after_actual_finish` |
| policy refusal | fixture | `~/test_ikarus_computer_schedule.py::test_scheduled_release_locked_tool_is_unavailable_without_retry`, `::test_secret_objective_is_refused_before_any_retention`, `::test_authority_root_filter_never_dispatches_another_root`, `::test_unconfirmed_and_naive_time_have_no_schedule_effect`; `~/test_ikarus_computer_schedule_autonomy.py::test_queue_cancel_and_recurring_require_explicit_owner`, `::test_recurrence_bounds_refuse_before_retention` |
| stale target | fixture | `~/test_ikarus_computer_schedule.py::test_revoked_expired_and_cancelled_jobs_never_invoke_runner[...]`, `::test_corrupt_spec_is_visible_and_never_dispatched`, `::test_duplicate_admission_preserves_original_receipt`; `~/test_ikarus_computer_schedule_autonomy.py::test_successor_still_checks_frozen_scope_and_expiry[...]`, `::test_cancelled_pending_rows_are_closed_and_not_read_on_later_ticks` |
| cancellation | fixture | `~/test_ikarus_computer_schedule_autonomy.py::test_cancellation_is_durable_idempotent_and_covers_entire_series`, `::test_running_callback_observes_durable_cancel_and_no_successor`, `::test_cancel_between_dispatch_selection_and_claim_never_creates_claim`, `::test_cancellation_works_after_policy_revoke_but_never_for_other_root`; `~/interfaces/test_computer_watcher.py::test_existing_request_cancellation_prevents_scheduled_tick` |
| timeout | fixture (partial) | `~/test_ikarus_computer_schedule.py::test_interrupted_claim_requires_reconciliation_without_retry`, `::test_only_one_due_mission_per_tick`, `::test_competing_dispatchers_make_one_committed_claim` (exercises the `timeout_s=5` claim/metadata locks). Partial: no test drives an occurrence past the mission's own `timeout_s` |
| crash recovery | fixture | `~/test_ikarus_computer_schedule_autonomy.py::test_crash_after_terminal_recovers_metadata_without_replaying_effect[...]`, `::test_open_crashed_claim_never_repeats_or_overlaps_queued_work`; `~/test_ikarus_computer_schedule.py::test_interrupted_claim_requires_reconciliation_without_retry`, `::test_runner_exception_is_not_claimed_as_safe_failure_to_retry`; `~/interfaces/test_computer_watcher.py::test_due_failure_does_not_kill_existing_watcher` |

### 8. Persistent goals / durable autonomy and adaptive planning

Packets: G1-IKARUS-21, -22, -23, G1-WP-IKARUS-COMPUTER-LOOP-01.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | fixture | real spine/CAS/mission path with a fake planner and fake tool adapter throughout `~/test_ikarus_computer_loop.py` and `~/test_ikarus_computer_autonomy.py`. Live local-planner runs (Qwen2.5-Coder 7B) are retained in `docs/evidence/ikarus-computer-local-2026-09-05.json` as historical integration and negative evidence that **predates the release fence** [INHERITED, G1-WP-IKARUS-COMPUTER-LOOP-01] |
| verified postconditions | fixture | `~/test_ikarus_computer_loop.py::test_failed_postcondition_stops_planner_even_with_completed_receipt`, `::test_adapter_failure_cannot_be_rewritten_as_model_success`, `::test_unverified_observation_can_be_followed_by_another_tool`; `~/test_ikarus_computer_autonomy.py::test_adapter_refusal_unknown_or_failed_postcondition_never_replans[...]`, `::test_three_unchanged_read_observations_stall_despite_fresh_receipts`, `::test_distinct_content_or_target_evidence_is_progress` |
| policy refusal | fixture | `~/test_ikarus_computer_autonomy.py::test_plan_cannot_add_authority`, `::test_runtime_path_release_fence_inventory_is_preserved`, `::test_global_mission_id_cannot_replay_unscoped_or_other_authority[...]`, `::test_secret_response_is_hashed_withheld_and_never_repaired`; `~/test_ikarus_computer_loop.py::test_unavailable_or_malformed_tool_performs_zero_effects[...]`, `::test_unconfigured_computer_never_creates_mission`, `::test_secret_objective_refused_before_storage_or_model`, `::test_local_context_refuses_external_provider` |
| stale target | fixture | `~/test_ikarus_computer_loop.py::test_frozen_schedule_policy_is_checked_before_model_or_mission`, `::test_terminal_mission_replay_never_calls_adapter`; `~/test_ikarus_computer_autonomy.py::test_plan_and_replan_are_advisory_mission_bound_artifacts` |
| cancellation | fixture | `~/test_ikarus_computer_loop.py::test_stop_after_model_prevents_next_effect`, `::test_cancellation_after_model_prevents_next_effect`, `::test_stream_cancellation_reaches_inflight_computer_planner`; `~/test_ikarus_computer_autonomy.py::test_cancellation_before_suspended_model_call_prevents_it`, `::test_cancellation_after_correction_model_call_prevents_tool`, `::test_generator_close_clears_native_cancellation_probe`, `::test_owned_service_closes_even_before_mission_admission[...]`; `~/test_ikarus_computer_history.py::test_runtime_checkpoints_observe_cooperative_cancel_before_policy_read` |
| timeout | fixture | `~/test_ikarus_computer_loop.py::test_planner_exhausts_timeout_before_tool`, `::test_step_limit_is_enforced`; `~/test_ikarus_computer_autonomy.py::test_plan_cannot_extend_shared_timeout`, `::test_owner_disabled_attempts_remove_numeric_retry_and_call_caps`, `::test_identical_invalid_output_stalls_when_retry_axis_is_disabled` |
| crash recovery | fixture | `~/test_ikarus_computer_loop.py::test_interrupted_mission_requires_reconciliation`, `::test_terminal_mission_replay_never_calls_adapter`; `~/test_ikarus_computer_history.py::test_corrupt_or_missing_cas_never_claims_completion`, `::test_missing_ledger_reads_create_nothing_and_legacy_content_stays_hidden` |

### 9. Product memory

Packet: G1-IKARUS-CONTEXT-01.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | real | `~/test_ikarus_computer_context.py::test_note_persists_in_real_fact_and_cas_and_reads_after_reopen` — real fact store and real CAS on disk |
| verified postconditions | real | `::test_note_persists_in_real_fact_and_cas_and_reads_after_reopen`, `::test_identical_remember_is_idempotent`, `::test_note_count_and_aggregate_text_bounds_preserve_prior_revision` |
| policy refusal | real | `::test_different_authority_does_not_receive_product_notes`, `::test_missing_owner_and_secret_refuse_without_creating_state`, `::test_empty_read_creates_no_canonical_database` |
| stale target | real | `::test_corrupt_fact_is_reported_without_guessing_context`, `::test_missing_policy_does_not_block_reading_retained_notes`, `::test_note_count_and_aggregate_text_bounds_preserve_prior_revision` |
| cancellation | **GAP** | `daedalus/orchestration/ikarus/computer_context.py` takes no `checkpoint` callable and has no cooperative-cancel seam at all; its only interruption boundary is `ExclusiveFileLock(..., timeout_s=2)` [MEASURED by inspection] |
| timeout | real (partial) | `::test_parallel_owner_notes_have_no_lost_updates` exercises that 2 s context lock under real contention |
| crash recovery | real (partial) | `::test_forget_retains_tombstone_and_history_without_resurrection`, `::test_parallel_owner_notes_have_no_lost_updates`, `::test_corrupt_fact_is_reported_without_guessing_context`. No process-kill test |

### 10. Skills (computer strand)

Packet: G1-IKARUS-CONTEXT-01. **The computer-side skill seam is release-locked**
(`RELEASE_*` constants in `daedalus/kernel/policy/computer.py`), so the
capability is listed in §7.2 but not activated. The fence itself is tested; the
capability behind it is not, because there is nothing running to test.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | **GAP (fenced)** | `~/test_ikarus_computer_context.py::test_v016_skill_selection_is_release_locked_before_workspace_read` pins that it does *not* run |
| policy refusal | fixture | `::test_skill_path_scope_refuses_before_state_write[...]`, `::test_skill_secret_and_oversized_sources_are_never_retained`, `::test_linked_skill_bundle_does_not_reach_outside_inventory`, `::test_legacy_selected_skill_metadata_is_unavailable_but_can_be_cleared`, `::test_v016_skill_selection_is_release_locked_before_workspace_read`; `~/runtimes/test_computer_service_files.py::test_vision_path_forms_and_skill_reads_stay_fenced_after_the_lift` |
| all other classes | **GAP** | fenced off; no seam |

`~/test_skills.py` (73 collected [MEASURED]) covers
`daedalus/foundation/skills.py` as a library. It is **not** evidence for the
computer capability and is deliberately excluded from this row's counts.

### 11. Computer vision — OpenCV, OCR, optional VLM

Packet: G1-IKARUS-CV-01. `vision.match` and `vision.changes` are release-
DISABLED; only `vision.inspect` and `vision.ocr` are admitted, and only in an
observation-bound shape with no pathname.

| Class | Kind | Evidence |
| --- | --- | --- |
| real adapter execution | real | `~/runtimes/test_computer_vision.py` (45 collected) runs real OpenCV decode/matching on generated images; `~/runtimes/test_computer_ocr.py::test_real_os_ocr_reads_generated_fixture_with_grounded_boxes` runs the real `Windows.Media.Ocr` engine on this host — it ran, it did not skip [MEASURED, 0 skipped]. **Optional vision-language inference: GAP, not implemented** |
| verified postconditions | real | `~/runtimes/test_computer_vision.py::test_unique_template_has_expected_coordinate_provenance`, `::test_exact_diff_regions_and_unchanged_status`, `::test_local_ocr_adapter_retains_text_and_coordinates`, `::test_ocr_failure_does_not_invent_text`, `::test_invalid_ocr_result_fails_visibly[...]`; `~/runtimes/test_computer_ocr.py::test_native_boxes_round_outward_and_do_not_invent_confidence` |
| policy refusal | fixture | `~/kernel/test_computer_policy.py::test_v016_release_fence_refuses_every_vision_path_shape[...]`, `::test_observation_backed_vision_does_not_open_the_path_fence`, `::test_observation_only_kernel_admission_requires_exact_token_shape[...]`; `~/runtimes/test_computer_service.py::test_generic_issuer_refuses_non_observation_vision_shapes_without_state[...]`, `::test_unavailable_release_capability_refuses_before_lease_or_state`, `::test_release_capability_projection_contains_no_path_based_vision_schema` |
| stale target | real+fixture | `~/runtimes/test_computer_service.py::test_missing_current_observation_refuses_before_lease_or_state`, `::test_observation_backed_vision_succeeds_with_desktop_coordinate_frame`; `~/runtimes/test_computer_vision.py::test_duplicate_matches_are_ambiguous_even_when_return_limit_is_one`, `::test_overlapping_repeated_templates_remain_ambiguous`, `::test_absent_template_does_not_invent_a_target` |
| cancellation | fixture (OCR only) | `~/runtimes/test_computer_ocr.py::test_checkpoint_cancellation_cancels_native_operation`. **GAP for the OpenCV path**: `daedalus/runtimes/computer_vision.py` has no checkpoint parameter (synchronous native call) |
| timeout | real+fixture | `~/runtimes/test_computer_ocr.py::test_ocr_refuses_invalid_timeout[...]`, `::test_timeout_cancels_native_operation_and_closes_resources`. The OpenCV path bounds by size instead: `~/runtimes/test_computer_vision.py::test_byte_and_pixel_limits_apply`, `::test_forged_huge_png_dimensions_refused_before_decode`, `::test_forged_huge_jpeg_dimensions_refused_before_decode` |
| crash recovery | n/a | vision is a pure read with no durable effect to reconcile. Native resource release is covered by `~/runtimes/test_computer_ocr.py::test_timeout_cancels_native_operation_and_closes_resources`, `::test_running_event_loop_requires_worker_thread` |

### 0. Shared canonical admission spine (supports every row above)

Not a §7.2 capability, so it is not a matrix row, but every cell depends on it:
`~/runtimes/test_computer_service.py` (27 collected),
`~/kernel/test_computer_policy.py` (56),
`~/interfaces/test_computer_configuration.py` (21) [MEASURED].

---

## Suite state today

All runs at revision `585b7ea4` with a dirty tree, on a loaded box (76 matching
`python`/`node`/`claude` processes counted at the start of the session).
**Counts only. No timing number from this session is trustworthy and none is
reported as a performance claim.**

| Command (all with `-q --color=no -p no:cacheprovider`) | Result | Stamp |
| --- | --- | --- |
| `tests/runtimes/test_computer_desktop.py test_computer_browser.py test_computer_vision.py test_computer_ocr.py test_computer_evidence_desktop.py test_computer_evidence_browser.py test_computer_evidence_terminal.py` | **170 passed** | [MEASURED] |
| `tests/runtimes/test_computer_service.py test_computer_service_files.py tests/kernel/test_computer_policy.py tests/interfaces/test_computer_configuration.py test_computer_watcher.py` | **113 passed** | [MEASURED] |
| `tests/test_ikarus_computer_schedule.py test_ikarus_computer_schedule_autonomy.py test_ikarus_computer_context.py test_ikarus_computer_history.py test_ikarus_computer_loop.py test_ikarus_computer_autonomy.py` | **161 passed** | [MEASURED] |
| `tests/runtimes/test_computer_files.py` (inventory only, another agent's lane) | **87 passed** | [MEASURED] |
| `tests/test_skills.py` (library, not the computer capability) | 73 collected | [MEASURED] |

Per-file collected counts [MEASURED]: desktop 11, browser 11, vision 45, ocr 16,
service 27, service_files 7, files 87, policy 56, configuration 21, watcher 3,
schedule 17, schedule_autonomy 35, context 18, history 20, loop 29, autonomy 42.

### Retained negative evidence from this session

An earlier run of the service/policy group during this session returned
**1 failed, 112 passed**, the failure being
`tests/runtimes/test_computer_service.py::test_failure_records_persist_the_adapter_recovery_paths`
(`assert terminals == []` versus one `CANCELLED` terminal). `stat` showed that
file had been written 1 minute 52 seconds earlier by the concurrent
file-capability agent. The same suite is **113 passed** at the current tree. The
red is recorded here as a mid-edit artifact of a shared dirty tree, not as a
standing defect, and not as evidence that the guard is broken.

---

## Remaining GAPs and why each is not cheap

| # | Capability × class | Why it is not cheap here |
| --- | --- | --- |
| 1 | Desktop × real adapter execution | `_WindowsDesktop` calls foreground-window APIs and `SendInput` against the owner's live interactive session. Out of scope for this session (no live desktop/keyboard/mouse) and unsafe while dozens of agent processes share the box. Already named as open by G1-IKARUS-18 [INHERITED] |
| 2 | Desktop × crash recovery | Needs a process-kill harness around a live input group. The observation token lives only in adapter memory, so there is nothing durable for a restarted process to reconcile — the seam that *should* carry it is the canonical ledger, which the service writes, not the adapter. **Missing seam**, so a test would pin nothing |
| 3 | Browser × timeout | Needs a deliberately hanging local server plus real Chromium, and the assertion is a wall-clock one. On a box under this load a wall-clock number is wrong, not slow |
| 4 | Browser × crash recovery | Requires killing the Chromium process mid-action; not deterministic offline |
| 5 | Browser × cancellation mid-navigation | The checkpoints inside `goto`/`fill`/`click` only run against a live page. A fake page deep enough to reach them would be testing the stub, not the adapter |
| 6 | Terminal × every execution class | No adapter exists. This is the correct state; plan §11 requires a bounded Work Packet before activation. Writing execution tests would fabricate a capability |
| 7 | Document × all seven | No adapter, no tool, no admission seam anywhere in the tree |
| 8 | Integration/connectors × all seven | Same: no adapter, no tool, no seam |
| 9 | Skills (computer strand) × all execution classes | Release-fenced in `daedalus/kernel/policy/computer.py`. The fence is tested; lifting it is packet work (a production change), which this session may not make |
| 10 | Product memory × cancellation | `computer_context.py` accepts no `checkpoint` callable. Adding one is a production-code edit, forbidden for this session |
| 11 | Vision (OpenCV path) × cancellation | Same reason: `computer_vision.py` has no checkpoint parameter. The OCR path does, and is tested |
| 12 | Vision × optional vision-language inference | Not implemented. Would require a model call, so it cannot be deterministic and offline |
| 13 | File × crash recovery | Owned by another agent this session; G1-IKARUS-24 is on HOLD for exactly this and `G1-IKARUS-27_REPLACEMENT_CRASH_RECONCILIATION` is the open packet. Inventoried, not touched |
| 14 | "Real adapter execution" as a strand-wide claim | Browser and OCR run real engines, but against loopback/synthetic inputs. Live external browsing needs egress admission plus owner consent, and is a separate decision, not a test |

## New tests added by this session

Three new files, all under `tests/runtimes/`, all offline, deterministic, and
with no live desktop, browser, keyboard or mouse. **No production file was
edited.** The file capability was not touched.

| File | Result | Rows it fills |
| --- | --- | --- |
| `tests/runtimes/test_computer_evidence_terminal.py` | **24 passed** [MEASURED] | Terminal × policy refusal; Desktop × policy refusal (`app.launch` interpreter fence) |
| `tests/runtimes/test_computer_evidence_desktop.py` | **36 passed** [MEASURED] | Desktop × policy refusal; Desktop × verified-postcondition guard |
| `tests/runtimes/test_computer_evidence_browser.py` | **27 passed** [MEASURED] | Browser × policy refusal (offline); Browser × stale target (offline); Browser × cancellation (offline) |

Each file's docstring names the exact production change that turns it red, and
each refusal family has a paired **positive control** proving the assertion
discriminates rather than passing vacuously:

- terminal: `test_a_non_interpreter_application_is_still_admitted` — the same
  policy shape with a non-interpreter executable constructs fine, so the 13
  stem refusals are caused by the stem set and nothing else;
- desktop: `test_an_enabled_key_still_reaches_the_host` and
  `test_scopeless_observe_is_the_admitted_shape` — `TAB` does reach
  `host.input`, so the allowlist is what refuses `F4` / `CTRL+ALT+DELETE`;
- browser: `test_the_start_tripwire_is_reachable_for_an_admitted_request` and
  `test_the_page_tripwire_is_reachable_for_a_fresh_observation` — the `_start`
  and live-page tripwires *do* fire on an admitted request, so a removed guard
  would trip them instead of quietly passing.

Guards these newly pin, which no test covered before [MEASURED by inspection at
this revision]:

1. 12 of the 13 interpreter stems in `ComputerPolicy.__post_init__`
   (`cmd`, `powershell`, `pwsh`, `bash`, `sh`, `node`, `python3`, `pythonw`,
   `wscript`, `cscript`, `mshta`, `rundll32`) — only `python` was pinned, via
   `sys.executable`, and the `.casefold()` was unpinned entirely.
2. The absence of any command-execution tool in `ALL_COMPUTER_TOOLS`.
3. `DesktopAdapter`'s `desktop.key` allowlist ("desktop key is not enabled").
4. `DesktopAdapter`'s `desktop.type` printable/length bound.
5. `DesktopAdapter`'s mandatory explicit `expected` postcondition — plan §7.2
   makes this constitutional ("Every action binds a current observation, target
   and expected postcondition"); the cases keep the argument key set exact so
   the neighbouring key-set check cannot mask a removal.
6. `DesktopAdapter`'s refusal of caller-supplied `desktop.observe` capture scope.
7. The browser policy/argument/freshness refusals *without* Playwright
   installed, so they stay in the evidence on a host lacking the optional extra.

---

Iron Plan: ALIGNED
Iron Gate: 1
Evidence: 170 + 113 + 161 + 87 passed [MEASURED] across the general-computer
suites at `585b7ea4`; three new offline test files, 24 + 36 + 27 passed
[MEASURED]; 43 of 63 existing-capability evidence cells covered, 27 GAPs
enumerated above with the reason each is blocked (live host, absent adapter,
release fence, or missing production seam).
