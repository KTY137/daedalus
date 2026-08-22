# Census shard 10/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_latent_index_integrity.py|function|test_dangling_identity_anchor_is_reported_as_a_corrupt_index|Test that orphaned anchor projection yields invalid_index.
tests/test_latent_index_integrity.py|function|test_search_without_a_journal_position_reports_unanchored_never_fresh|Test default freshness is unanchored.
tests/test_latent_index_integrity.py|function|test_search_over_a_stale_index_says_so_instead_of_ready|Test stale journal returns stale status.
tests/test_latent_index_integrity.py|function|test_watermark_refuses_to_move_backwards|Test that journal position cannot decrease.
tests/test_latent_index_integrity.py|function|test_watermark_refuses_a_rewritten_journal_at_an_unchanged_position|Test that journal content hash must match.
tests/test_latent_index_integrity.py|function|test_search_refuses_when_the_journal_forked_under_the_index|Test forked journal returns journal_forked.
tests/test_latent_index_integrity.py|function|test_unknown_journal_id_is_unanchored_not_fresh|Test unknown journal ID yields unanchored.
tests/test_latent_index_integrity.py|function|test_journal_position_rejects_nonsense|Test JournalPosition validation.
tests/test_latent_index_integrity.py|function|test_an_offline_backend_is_not_reported_as_drift|Test offline backend yields embedder_unavailable.
Route this task to Claude or local Ollama.
tests/test_host_predicate.py|constant|TABLE|Provides the complete contract mapping host strings to expected lanes and reasons.
tests/test_host_predicate.py|constant|HOSTS|Tuple of host strings extracted from TABLE for parametrization.
tests/test_host_predicate.py|function|test_the_shared_predicate_answers_the_whole_table|Verifies that lane_for_host returns expected lane for every entry in TABLE.
tests/test_host_predicate.py|function|test_none_fails_closed|Verifies that lane_for_host(None) returns "untrusted".
tests/test_host_predicate.py|function|test_ollama_adapter_local_flag_is_the_shared_predicate|Ensures OllamaAdapter.local matches lane_for_host for all hosts.
tests/test_host_predicate.py|function|test_available_vendors_lane_is_the_shared_predicate|Ensures availability rows lane matches lane_for_host.
tests/test_host_predicate.py|function|test_local_and_lane_can_never_disagree_about_one_host|Ensures adapter.local and row.lane are consistent.
tests/test_host_predicate.py|function|test_the_two_shipped_defaults_still_land_where_they_must|Verifies default local and bench hosts produce correct lanes and local flags.
tests/test_host_predicate.py|function|test_WIDENED_numeric_loopback_the_old_regex_could_not_parse|Pins that numeric loopbacks now return trusted.
tests/test_host_predicate.py|function|test_NARROWED_names_the_council_used_to_call_local|Pins that names like localhost now return untrusted.
tests/test_host_predicate.py|function|test_unset_env_reproduces_the_old_fail_closed_default|Verifies unset DAEDALUS_TRUSTED_HOSTS leaves bench untrusted.
tests/test_host_predicate.py|function|test_empty_env_is_the_same_as_unset|Verifies empty env same as unset.
tests/test_host_predicate.py|function|test_a_declared_numeric_address_is_trusted_with_or_without_scheme_or_port|Verifies declared numeric address becomes trusted regardless of formatting.
tests/test_host_predicate.py|function|test_declaring_one_address_does_not_trust_its_neighbour|Ensures exact address equality only.
tests/test_host_predicate.py|function|test_a_declared_hostname_is_dropped_never_resolved|Verifies hostname in env is ignored.
tests/test_host_predicate.py|function|test_an_unparseable_entry_narrows_rather_than_widens|Verifies malformed env entries are dropped.
tests/test_host_predicate.py|function|test_a_bad_entry_does_not_poison_a_good_one_in_the_same_list|Verifies only bad entries dropped, good ones kept.
tests/test_host_predicate.py|function|test_multiple_declared_addresses_are_all_honoured|Verifies multiple trusted addresses work.
tests/test_host_predicate.py|function|test_a_scheme_and_port_on_the_declaration_itself_are_stripped|Verifies normalization of declared host.
tests/test_host_predicate.py|function|test_is_loopback_host_true_for_numeric_loopback_only|Verifies is_loopback_host returns True for numeric loopbacks.
tests/test_host_predicate.py|function|test_is_loopback_host_false_for_everything_else|Verifies is_loopback_host returns False for other hosts.
tests/test_host_predicate.py|function|test_is_loopback_host_stays_false_for_a_declared_trusted_host|Pins security property: is_loopback_host false for declared trusted host.
tests/test_host_predicate.py|function|test_is_loopback_host_ignores_the_declared_trust_list_entirely|Verifies is_loopback_host unaffected by env.
tests/test_host_predicate.py|function|test_is_loopback_host_none_fails_closed|Verifies is_loopback_host(None) returns False.
tests/test_host_predicate.py|function|test_no_caller_keeps_its_own_copy_of_the_host_predicate|Ensures no new duplicate host predicates appear.
tests/test_host_predicate.py|function|test_vendors_has_no_local_host_table_left|Pins that vendors.py no longer contains old local-host symbols.
tests/test_host_predicate.py|function|test_the_allowlist_does_not_rot|Ensures _OWNED_ELSEWHERE entries still have duplicates.
tests/test_host_predicate.py|function|test_the_known_divergences_are_still_divergences|Pins specific disagreements between allowed copies and shared predicate.
tests/test_council_vendors.py|constant|REPO_ROOT|Defines the repository root path for test isolation.
tests/test_council_vendors.py|constant|PLANTED_KEY|A fake AWS key id used for secret floor tests.
tests/test_council_vendors.py|class|RecordingRunner|Captures spawn calls for assertion.
tests/test_council_vendors.py|class|ExplodingRunner|Asserts that no spawn occurs.
tests/test_council_vendors.py|function|test_vendor_reply_carries_no_verdict_field|Ensures VendorReply has no verdict-related field names.
tests/test_council_vendors.py|function|test_status_vocabulary_is_closed|Verifies statuses are a closed set.
tests/test_council_vendors.py|function|test_no_council_profile_grants_write_or_agency|Ensures council profiles have no write or agency flags.
tests/test_council_vendors.py|function|test_council_profiles_are_not_the_runtime_profiles|Verifies council profiles differ from runtime profiles.
tests/test_council_vendors.py|function|test_forbidden_flag_in_a_profile_is_rejected|Tests that a profile with workspace-write is rejected.
tests/test_council_vendors.py|function|test_module_exposes_no_write_or_apply_surface|Checks no write/apply symbols are exposed.
tests/test_council_vendors.py|function|test_spawn_cwd_is_fresh_empty_and_outside_the_repo|Verifies cwd is empty and outside repo.
tests/test_council_vendors.py|function|test_two_calls_get_different_cwds|Ensures each call gets a unique cwd.
tests/test_council_vendors.py|function|test_council_cwd_refuses_a_cwd_inside_the_declared_repo_root|Verifies refusal when cwd would be inside repo.
tests/test_council_vendors.py|function|test_council_env_never_carries_ollama_host|Ensures OLLAMA_HOST is stripped from env.
tests/test_council_vendors.py|function|test_ollama_adapter_does_not_set_ollama_host_in_this_process|Verifies local process env unchanged.
tests/test_council_vendors.py|function|test_subprocess_env_strips_ollama_host|Checks subprocess env has no OLLAMA_HOST.
tests/test_council_vendors.py|function|test_prompt_bytes_never_appear_in_argv|Ensures prompt is sent via stdin, not argv.
tests/test_council_vendors.py|function|test_ssh_argv_fails_fast_and_reads_the_prompt_from_stdin|Verifies agy adapter uses stdin for prompt.
tests/test_council_vendors.py|function|test_naive_whole_prompt_floor_call_misses_an_added_dotenv|Documents why floor_check uses evidence_paths.
tests/test_council_vendors.py|function|test_added_secret_path_is_refused_and_never_dispatched|Ensures secrets in evidence_paths are refused before dispatch.
tests/test_council_vendors.py|function|test_planted_key_in_evidence_is_refused_and_never_reaches_the_runner|Verifies planted AWS key in evidence_files is refused.
tests/test_council_vendors.py|function|test_planted_key_pasted_into_the_question_is_caught_by_the_backstop|Checks planted key in prompt is caught.
tests/test_council_vendors.py|function|test_ollama_refusal_never_calls_the_chat_transport|Ensures refused prompt does not call chat.
tests/test_council_vendors.py|function|test_clean_evidence_is_not_refused|Verifies non-secret evidence passes.
tests/test_council_vendors.py|function|test_untrusted_lane_withholds_contents_and_names_the_paths|Checks untrusted lane withholds proprietary content.
tests/test_council_vendors.py|function|test_trusted_lane_withholds_nothing|Verifies trusted lane sends all content.
tests/test_council_vendors.py|function|test_every_prompt_states_that_evidence_is_data|Ensures prompt includes data disclaimer.
tests/test_council_vendors.py|function|test_claude_success_maps_to_ok_with_usage_and_latency|Tests successful Claude adapter output.
tests/test_council_vendors.py|function|test_claude_non_json_body_is_an_error_not_usable_prose|Ensures non-JSON stdout results in error.
tests/test_council_vendors.py|function|test_codex_success_maps_to_ok|Tests successful Codex adapter output.
tests/test_council_vendors.py|function|test_nonzero_exit_is_error_and_retains_stderr|Tests nonzero exit code handling.
tests/test_council_vendors.py|function|test_missing_binary_is_unavailable_not_a_traceback|Checks unavailable status on missing binary.
tests/test_council_vendors.py|function|test_hanging_runner_hits_the_timeout_path|Tests timeout path on hanging runner.
tests/test_council_vendors.py|function|test_a_raising_runner_cannot_take_the_council_down|Ensures exception in runner is caught.
tests/test_council_vendors.py|function|test_agy_unsigned_in_is_unavailable_and_spawns_nothing|Verifies unsigned agy is unavailable without spawn.
tests/test_council_vendors.py|function|test_agy_signin_message_on_stderr_maps_to_unavailable|Checks sign-in error detected.
tests/test_council_vendors.py|function|test_agy_unreachable_bench_maps_to_connect_failed|Tests connection timeout handling.
tests/test_council_vendors.py|function|test_agy_success_parses_json|Tests successful agy response parsing.
tests/test_council_vendors.py|function|test_ollama_success_maps_to_ok_and_passes_the_host_explicitly|Tests successful Ollama adapter.
tests/test_council_vendors.py|function|test_bench_ollama_is_not_local_but_loopback_is|Checks local vs bench Ollama flags.
tests/test_council_vendors.py|function|test_ollama_over_budget_prompt_is_refused_loudly_not_truncated|Ensures over-budget prompt is refused.
tests/test_council_vendors.py|function|test_ollama_unreachable_maps_to_connect_failed|Tests unreachable Ollama host handling.
tests/test_council_vendors.py|function|test_ollama_bad_shape_is_an_error|Tests malformed Ollama response.
tests/test_council_vendors.py|function|test_same_weights_on_two_hosts_collide_into_one_independence_class|Tests independence class grouping.
tests/test_council_vendors.py|function|test_model_family_merges_the_qwen_size_line|Verifies model family merging.
tests/test_council_vendors.py|function|test_distinct_vendors_are_distinct_classes|Ensures distinct vendors have different independence classes.
tests/test_council_vendors.py|function|test_actor_ids_are_namespaced_per_adr_010|Checks actor ID format.
tests/test_council_vendors.py|function|test_reply_actor_id_cannot_drift_from_the_transcript_formatter|Ensures consistency between vendor and bus actor IDs.
tests/test_council_vendors.py|function|test_unknown_model_is_recorded_never_omitted|Verifies unknown model and version are recorded.
tests/test_council_vendors.py|function|test_prompt_token_ceiling_is_charged_before_dispatch|Ensures over-token-ceiling prompt is refused before dispatch.
tests/test_council_vendors.py|function|test_registry_reports_availability_without_invoking_any_model|Tests available_vendors without model invocation.
tests/test_council_vendors.py|function|test_registry_marks_bench_ollama_untrusted_and_loopback_trusted|Checks lane assignment for different Ollama hosts.
daedalus/dctx.py|constant|RECEIPT_VERSION|identifies receipt version string 'dctx/1'
daedalus/dctx.py|constant|DIGEST_VERSION|identifies digest version string 'dctx-unit/1'
daedalus/dctx.py|constant|LABEL_PROVENANCE|shared cross-track vocabulary for label provenance
daedalus/dctx.py|function|compile|slice target and mint verifiable receipt for the result
daedalus/dctx.py|function|verify|re-check a receipt against a checkout offline
daedalus/dctx.py|function|main|CLI entry point for minting or verifying receipts
tests/test_bridge_restart.py|class|Crash|A test exception simulating a crash.
tests/test_bridge_restart.py|constant|SEAMS|List of crash seam names for parametrized tests.
tests/test_bridge_restart.py|function|test_restart_after_a_crash_produces_exactly_one_of_everything|Ensures exactly one of each artifact after crash at any seam.
tests/test_bridge_restart.py|function|test_work_is_redispatched_only_when_the_report_never_landed|Ensures work re-dispatch only if report never landed.
tests/test_bridge_restart.py|function|test_a_completed_request_reprocessed_outright_changes_nothing|Ensures reprocessing a completed request is idempotent.
tests/test_bridge_restart.py|function|test_two_different_requests_are_not_deduped_into_one|Ensures different requests are not merged.
tests/test_bridge_restart.py|function|test_the_memory_recovery_scan_is_not_paid_on_the_happy_path|Ensures memory scan not called on happy path.
tests/test_bridge_restart.py|function|test_an_interrupted_cross_device_archive_move_leaves_one_copy|Ensures interrupted archive move leaves one copy.
tests/test_bridge_restart.py|function|test_a_truncated_report_is_not_mistaken_for_a_finished_one|Ensures truncated report triggers full reprocess.
tests/test_bridge_restart.py|function|test_the_report_is_published_atomically|Ensures report body is written atomically.
tests/test_bridge_restart.py|function|test_malformed_json_is_quarantined_not_silently_skipped|Ensures malformed JSON is quarantined.
tests/test_bridge_restart.py|function|test_a_half_written_request_is_left_to_settle_not_destroyed|Ensures half-written request is left to settle.
tests/test_bridge_restart.py|function|test_a_structurally_invalid_request_is_poison_immediately|Ensures structurally invalid request is quarantined immediately.
tests/test_bridge_restart.py|function|test_a_failing_quarantine_does_not_take_the_watcher_down|Ensures failing quarantine does not crash watcher.
tests/test_bridge_restart.py|function|test_the_watch_loop_survives_poison_and_keeps_working|Ensures watch loop continues despite poison.
tests/test_bridge_restart.py|function|test_a_locked_poison_file_does_not_re_report_every_poll|Ensures locked poison file not re-reported each poll.
tests/test_bridge_restart.py|function|test_a_request_that_hard_kills_the_process_is_not_dispatched_forever|Ensures crash-causing request is bounded by MAX_ATTEMPTS.
tests/test_bridge_restart.py|function|test_status_shows_quarantined_requests|Ensures bridge status includes quarantined info.
daedalus/eval/ceiling.py|constant|CLASSES|Tuple of classification strings for missed labels: REACHABLE, UNREACHABLE, STATIC_EDGE, NO_INSCOPE_DEF.
daedalus/eval/ceiling.py|constant|REOPEN_MIN_SHARE|Materiality floor for reopening the temporal enrichment lane (share of labels).
daedalus/eval/ceiling.py|constant|REOPEN_MIN_TASKS|Materiality floor for reopening the temporal enrichment lane (number of tasks).
daedalus/eval/ceiling.py|function|temporal_ceiling|Computes both arms of the ceiling over miss tasks; returns dict with per-task classifications, summaries, and reopen signal.
daedalus/eval/ceiling.py|function|render_ceiling|Returns ASCII-only render of the ceiling result with honest framing and reopen trigger statement.
daedalus/eval/ceiling.py|function|main|CLI entry point parsing --min-count and printing the rendered ceiling.
tests/test_codex_provider.py|module|test_codex_provider|Contains offline tests for the Codex CLI provider.
tests/test_codex_provider.py|constant|VALID_REPORT|A sample valid report dictionary used in tests.
tests/test_codex_provider.py|class|CodexProviderRunTests|Tests for CodexCLIProvider.run method.
tests/test_codex_provider.py|class|CodexEgressGateTests|Tests that policy-denied paths are refused before subprocess dispatch.
tests/test_codex_provider.py|class|CodexRoutingTests|Tests for routing decisions involving codex provider.
tests/test_codex_provider.py|class|CodexLaneBridgeTests|Tests for codex lane bridge dispatch and egress policy enforcement.
tests/test_codex_provider.py|class|DoctorCodexTests|Tests for doctor codex status checks and doctor main rendering.
tests/test_dead_letter_replay.py|class|DeadLetterTestCase|Provides temp dir setup and helper methods for dead letter replay tests
tests/test_dead_letter_replay.py|class|ReplayLandsTurnsThroughAppendTurn|Ensures replayed turn lands via append_turn and verify is clean
tests/test_dead_letter_replay.py|class|ReplayIsIdempotent|Ensures replaying twice does not duplicate a turn
tests/test_dead_letter_replay.py|class|FailedEntriesStayQueued|Ensures entries that still cannot be chained stay in the spool
tests/test_dead_letter_replay.py|class|MalformedLineDoesNotAbortReplay|Ensures malformed lines are reported and kept, good lines still replay
tests/test_dead_letter_replay.py|class|ReplayNeverBypassesAppendTurn|Ensures replay touches room.md only through append_turn
tests/test_dead_letter_replay.py|class|DryRunChangesNothing|Ensures --dry-run reports but mutates neither room nor spool
tests/test_dead_letter_replay.py|class|CLIEntryPoint|Ensures CLI commands work correctly
tests/test_dead_letter_replay.py|class|TheFullLoopCloses|Ensures end-to-end dead letter recovery from stream_hook is clean and idempotent
daedalus/spine/cancel.py|constant|DEFAULT_GRACE_S|Default grace period in seconds for cancellation.
daedalus/spine/cancel.py|constant|STAGE_NOT_STARTED|Indicates cancellation stage: not started.
daedalus/spine/cancel.py|constant|STAGE_ALREADY_EXITED|Indicates cancellation stage: process already exited.
daedalus/spine/cancel.py|constant|STAGE_GRACEFUL|Indicates cancellation stage: graceful signal succeeded.
daedalus/spine/cancel.py|constant|STAGE_TREE_KILL|Indicates cancellation stage: tree kill used.
daedalus/spine/cancel.py|class|CancellationUnavailable|Raised when a process cannot be spawned inside a killable container.
daedalus/spine/cancel.py|class|CancelResult|Which rung of the ladder actually stopped the tree.
daedalus/spine/cancel.py|class|WindowsJobBackend|Contain the tree in a Job Object that dies with its handle.
daedalus/spine/cancel.py|class|PosixSessionBackend|Contain the tree in its own session/process group.
daedalus/spine/cancel.py|class|ManagedProcess|A child process whose whole tree can be cancelled.
daedalus/spine/cancel.py|function|console_ctrl_available|Whether stage 1 (CTRL_BREAK_EVENT) can be delivered at all.
daedalus/spine/cancel.py|function|select_backend|Pick the containment backend for a platform string.
daedalus/spine/cancel.py|function|live_managed_processes|Snapshot of every contained child alive in THIS interpreter.
daedalus/spine/cancel.py|function|cancel_all_managed|Cancel every live ManagedProcess tree.
daedalus/spine/cancel.py|function|cancel_all_managed|Cancel every live ManagedProcess tree.

## DEPENDS

DEPENDS|tests/test_envelope_join.py|daedalus.spine.envelope
DEPENDS|tests/test_envelope_join.py|daedalus.spine.ledger
DEPENDS|tests/test_semantic_route_live.py|daedalus.semantic_route
DEPENDS|tests/test_semantic_route_live.py|daedalus.router
DEPENDS|daedalus/kairos/scheduler.py|..provider_router
DEPENDS|daedalus/kairos/scheduler.py|..providers
DEPENDS|daedalus/kairos/scheduler.py|..providers.personas
DEPENDS|daedalus/kairos/scheduler.py|..sensitivity
DEPENDS|daedalus/kairos/scheduler.py|..projects
DEPENDS|daedalus/kairos/scheduler.py|..offload
DEPENDS|daedalus/kairos/scheduler.py|.gated_writes
DEPENDS|daedalus/kairos/scheduler.py|.decompose
DEPENDS|daedalus/kairos/scheduler.py|..agents_registry
DEPENDS|daedalus/kairos/scheduler.py|..benchmark
DEPENDS|tests/test_structcore_coverage.py|daedalus.structcore.index
DEPENDS|tests/test_structcore_coverage.py|daedalus.structcore.parse
DEPENDS|tests/test_structcore_coverage.py|daedalus.structcore.slice
DEPENDS|tests/test_prose_gate.py|daedalus.verifier
DEPENDS|tests/test_prose_gate.py|daedalus.spine.docref_gate
DEPENDS|tests/test_prose_gate.py|daedalus.spine.docrefs
DEPENDS|daedalus/config.py|daedalus.sensitivity (intersect_write_allow)
DEPENDS|tests/test_safety_reachability.py|daedalus.provider_router
DEPENDS|tests/test_safety_reachability.py|daedalus.sensitivity
DEPENDS|tests/test_safety_reachability.py|daedalus.structcore.graph
DEPENDS|tests/test_safety_reachability.py|daedalus.structcore.index
DEPENDS|tests/test_mutation_score.py|tools/mutation_score
DEPENDS|tests/test_spine_ledger.py|daedalus.spine.ledger
DEPENDS|tests/test_git_is_a_process_launcher.py|daedalus.spine.attempt._git
DEPENDS|tests/test_git_is_a_process_launcher.py|daedalus.spine.attempt._git_env
DEPENDS|tests/test_git_is_a_process_launcher.py|daedalus.spine.attempt._read_gitdir_pointer
DEPENDS|tests/test_git_is_a_process_launcher.py|daedalus.spine.attempt.TaskAttempt
DEPENDS|tests/test_git_is_a_process_launcher.py|daedalus.spine.attempt.TaskSpec
DEPENDS|tests/test_mapping_spectral.py|daedalus.mapping.spectral
DEPENDS|daedalus/structcore/graph.py|daedalus/structcore/parse (CodeUnit)

## WRITES

WRITES|tests/test_gate_containment_job_caps.py|temporary directories created by tmp_path fixture
WRITES|daedalus/build.py|runs/build/ directory
WRITES|daedalus/build.py|docs/architecture.html
WRITES|tests/test_shadow_run.py|temporary files via tmp_path
WRITES|daedalus/providers/codex_cli.py|RUN_DIR/last_codex_prompt.md
WRITES|daedalus/providers/codex_cli.py|RUN_DIR/last_codex_report.json

## READS

READS|daedalus/config.py|.agentenv/agentenv.json (from repo_root)
READS|daedalus/config.py|templates/agents/*.json, templates/CLAUDE.md, templates/AGENTS.md (via init_repo)
READS|tests/test_safety_reachability.py|daedalus.structcore.index.build_index
READS|tests/test_mutation_score.py|fixture files (goodmod.py, weakmod.py, etc.)
READS|tests/test_picker_outcome.py|temporary .git HEAD and FEATURE_INVENTORY.json
READS|tests/test_structcore_parallel.py|temporary filesystem and environment variables
READS|tests/test_comms.py|.vscode/tasks.json
READS|tests/test_comms.py|docs/COMMS_PROTOCOL.md
READS|tests/test_comms.py|vscode-agent-env/package.json
READS|tests/test_comms.py|vscode-agent-env/extension.js

## CLAIMS

CLAIMS|tests/test_envelope_join.py|One spelling. Six formats disagreeing about id NAMES is the defect.
CLAIMS|tests/test_envelope_join.py|A database written before the column existed must open, migrate, and hand back its rows unchanged with trace_id NULL.
CLAIMS|tests/test_envelope_join.py|The case a migration cannot save: mode=ro forbids the ALTER, so a reader against an un-migrated file sees rows with NO trace_id column at all.
CLAIMS|tests/test_envelope_join.py|A producer that stamped its own argument would corrupt a payload the caller still holds.
CLAIMS|tests/test_envelope_join.py|ABSORPTION F3: borrow the names, claim no conformance, export nothing.
CLAIMS|tests/test_semantic_route_live.py|FakeOllama: Real HTTP server that answers /api/embeddings however you tell it to.
CLAIMS|tests/test_semantic_route_live.py|LatentRouteRunsTests: The route RUNS when the backend answers and overrides keyword choice.
CLAIMS|tests/test_semantic_route_live.py|HonestFailureTests: The route REPORTS HONESTLY when the backend does not answer.
CLAIMS|tests/test_semantic_route_live.py|CacheRecoveryTests: One blip must not disable the route forever.
CLAIMS|tests/test_semantic_route_live.py|PathOwnershipTests: Path ownership short-circuit is a DESIGN skip, not a failure.
CLAIMS|tests/test_semantic_route_live.py|VisibilityTests: A skipped route cannot be silent.
CLAIMS|tests/test_semantic_route_live.py|RosterTests: The latent route must see the caller's agents.
CLAIMS|tests/test_semantic_route_live.py|RealBackendTests: What the REAL local backend does right now (measured, not assumed).
CLAIMS|daedalus/kairos/scheduler.py|Kairos never talks to the user, never decides trust, and bounces anything that belongs to the senior crew back to the trusted orchestration layer.
CLAIMS|tests/test_structcore_coverage.py|the neighbouring methods must NOT be dragged in -- that is the bug
CLAIMS|tests/test_structcore_coverage.py|S1 x scope: naming C/C++ units is what makes a shell leak POSSIBLE.
CLAIMS|tests/test_prose_gate.py|The prose lane's gate: fact preservation, the docref denominator, and the difference between a check that failed and a check that never ran.
CLAIMS|daedalus/config.py|resolve_write_wave_policy: "Anything other than one of WRITE_WAVE_POLICY_LEVELS resolves to DEFAULT_WRITE_WAVE_POLICY"
CLAIMS|daedalus/config.py|resolve_external_write_lanes: "Unknown names are DISCARDED; intersection with KNOWN_EXTERNAL_WRITE_LANES"
CLAIMS|tests/test_safety_reachability.py|the fence must ask the import graph, not just the edited path string
CLAIMS|tests/test_mutation_score.py|the scorer must be falsifiable: good tests score 100%, weak tests yield survivors, removing a covering test flips a caught mutant to survived
CLAIMS|tests/test_mutation_score.py|three rules: red baseline is not a score, inapplicable mutation is not a survivor, nothing touches the working repository
CLAIMS|tests/test_git_is_a_process_launcher.py|Module docstring claims the vector was found via adversarial sweep and describes three guards.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_CONTROL_the_attack_works_against_an_unpinned_git claims the attack works without the guard.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_naming_the_admin_directory_defeats_the_rewritten_pointer claims naming admin directory defeats rewritten gitdir pointer.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_pointer_is_read_before_the_candidate_can_move_it claims the pointer is read before candidate code runs.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_CONTROL_a_filter_in_the_USER_config_fires_from_gitattributes claims a filter in user config fires without gitdir rewrite.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_user_and_system_config_are_removed_from_the_lookup claims user/system config are removed from lookup.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_env_drops_variables_whose_empty_value_is_a_valid_command claims empty string is not equivalent to absence for env vars.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_the_env_is_actually_passed_to_the_process claims the hardened env is actually passed to the process.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_CONTROL_no_ext_diff_alone_still_spawns_a_textconv claims --no-ext-diff alone does not suppress textconv.
CLAIMS|tests/test_git_is_a_process_launcher.py|test_no_textconv_suppresses_it claims --no-textconv suppresses textconv.

## UNWIRED

UNWIRED|daedalus/structcore/dss.py|RECEIPT_SCHEMA_VERSION (constant) - not used within this file
UNWIRED|daedalus/eval/graph_delta.py|commit_shas
UNWIRED|daedalus/eval/graph_delta.py|measure_commit
UNWIRED|daedalus/eval/graph_delta.py|_git
UNWIRED|daedalus/structcore/slice.py|_skeleton (defined but not called in visible code; may be called elsewhere)
UNWIRED|tests/test_generated_inventory.py|None (all symbols are used by pytest or other tests)
UNWIRED|daedalus/structcore/clones.py|_overlap function is defined but may be unused if near_clusters is missing.
UNWIRED|daedalus/structcore/artifacts.py|SCHEMA_FROM_CODE: constant defined but not used within this file; likely an external hook.

## SMELL

SMELL|daedalus/semantic_route.py|Back-compat shims (_embed, _role_vectors) duplicate detailed versions; legacy semantic_route wraps explained version with logging.
SMELL|tests/test_host_predicate.py|High test count with many parametrized cases; possible maintenance burden but necessary for comprehensive coverage.
SMELL|tests/test_host_predicate.py|Uses _OWNED_ELSEWHERE allowlist that must be manually updated; if forgotten, test_no_caller_keeps_its_own_copy may miss new duplicates.
SMELL|daedalus/dctx.py|duplicate units in manifest kept, leading to potential confusion about unique files
SMELL|daedalus/dctx.py|receipt SHA reproducibility depends on tokenizer when max_tokens is set (stated in docstring)