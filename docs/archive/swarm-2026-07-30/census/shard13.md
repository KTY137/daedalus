# Census shard 13/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_structcore_center_naming.py|class|ShellEligibilityUnchangedTest|Tests that shell files do not bind onto center names and the shell view is unmodified.
tests/test_structcore_center_naming.py|class|NoCenterIsUnchangedTest|Tests that no-center behaves like old global formula, index omits naming block, and determinism.
tests/test_structcore_center_naming.py|class|CollisionPolicyTest|Tests that collisions are deterministic, refuse to bind, and stubs do not shadow real modules.
tests/test_structcore_center_naming.py|class|BothSpellingsResolveToOneIdentityTest|Tests that both package-relative and root spellings resolve to same file and alias is folded.
tests/test_structcore_center_naming.py|class|CenterOwnershipTest|Tests center_of function, longest prefix wins, nested center stripping.
tests/test_structcore_center_naming.py|class|HotspotRankingIsIndependentOfNamingTest|Tests that center naming does not change module heat scores.
tests/test_structcore_ignore.py|class|IgnorePatternTests|Tests pattern semantics of .daedalusignore without indexer.
tests/test_structcore_ignore.py|class|IgnoreIndexTests|Tests integration of ignore rules with build_index, center, caching, and slice boundary.
tests/test_worktree_properties.py|class|TestWorktreeJunctionProperty|property-based test case for worktree cleanup under junction attack
tests/test_worktree_properties.py|class|GuardIsLoadBearingTests|deterministic test confirming guard catches regression
tests/test_worktree_properties.py|class|HypothesisOptionalTests|ensures graceful degradation when hypothesis is missing
daedalus/adapters/subprocess_adapter.py|constant|PromptMode|Restricts prompt delivery mode to one of "argument", "stdin", or "none".
daedalus/adapters/subprocess_adapter.py|class|RuntimeConfig|Verified process-launch contract for one CLI runtime.
daedalus/adapters/subprocess_adapter.py|constant|RUNTIME_PROFILES|Provides built-in runtime profiles for one-shot, non-interactive CLI invocations.
daedalus/adapters/subprocess_adapter.py|class|SubprocessAdapter|Runs a configured CLI in a bounded working directory and normalizes output into AgentEvents.
tests/test_comms.py|constant|ROOT|path to repo root (parent of test directory)
tests/test_comms.py|constant|TASKS_JSON|path to .vscode/tasks.json
tests/test_comms.py|constant|PROTOCOL_MD|path to docs/COMMS_PROTOCOL.md
tests/test_comms.py|constant|EXTENSION_DIR|path to vscode-agent-env directory
tests/test_comms.py|constant|EXTENSION_PACKAGE|path to vscode-agent-env/package.json
tests/test_comms.py|constant|EXTENSION_MAIN|path to vscode-agent-env/extension.js
tests/test_comms.py|class|InitRepoToolInstructionTests|unit tests for init_repo and enforce_repo behavior
tests/test_comms.py|class|VsCodeTasksTests|unit tests for .vscode/tasks.json structure and content
tests/test_comms.py|class|VsCodeExtensionTests|unit tests for VS Code extension manifest and main script
tests/test_comms.py|class|MissionControlEndpointTests|unit tests for core dashboard, squads, watcher, review, models, providers
tests/test_comms.py|class|ProtocolDocTests|unit tests verifying COMMS_PROTOCOL.md covers all request fields and flow
tests/test_canary_livewire.py|fixture|spawn_sentinel|Records every attempt to start a vendor process and blocks it.
tests/test_canary_livewire.py|fixture|no_socket|Blocks any TCP connection attempt.
tests/test_canary_livewire.py|fixture|no_run|Makes any attempt to build or run the canary an outright failure.
tests/test_canary_livewire.py|function|test_run_canary_refuses_real_lanes_without_live|Ensures real lanes refuse without --live and no vendor process is spawned.
tests/test_canary_livewire.py|function|test_the_local_lane_is_gated_too|Ensures the local lane is also gated because it still egresses.
tests/test_canary_livewire.py|function|test_live_true_actually_unlocks_dispatch|Ensures live=True allows real vendor dispatch.
tests/test_canary_livewire.py|function|test_run_canary_defaults_live_to_false|Ensures run_canary's live parameter defaults to False.
tests/test_canary_livewire.py|function|test_refusal_happens_before_anything_is_written|Ensures refusal occurs before any history file is written.
tests/test_canary_livewire.py|function|test_every_default_lane_is_classified_live|Ensures all four shipped lanes are classified as live.
tests/test_canary_livewire.py|function|test_the_canary_reuses_the_council_classifier|Ensures the canary uses the same classifier as the council.
tests/test_canary_livewire.py|function|test_fake_lanes_need_no_opt_in|Ensures fake lanes can run without --live.
tests/test_canary_livewire.py|function|test_a_hand_rolled_lane_around_a_real_adapter_is_still_live|Ensures a hand-rolled lane with real adapter is still classified live.
tests/test_canary_livewire.py|function|test_a_bound_method_of_a_real_adapter_is_still_live|Ensures a lane with bound method of real adapter is still live.
tests/test_canary_livewire.py|function|test_a_one_shot_lane_iterator_is_not_drained_by_the_gate|Ensures the gate does not consume the lane iterator.
tests/test_canary_livewire.py|function|test_cli_refuses_a_bare_canary_invocation|Ensures CLI refuses canary without --live.
tests/test_canary_livewire.py|function|test_cli_refuses_a_bare_invocation_that_carries_other_flags|Ensures CLI refuses even with other flags but without --live.
tests/test_canary_livewire.py|function|test_cli_refuses_live_and_dry_run_together|Ensures CLI refuses conflicting --live and --dry-run flags.
tests/test_canary_livewire.py|function|test_cli_live_flag_authorises_the_spend|Ensures --live flag authorizes the spend.
tests/test_canary_livewire.py|function|test_the_library_gate_still_holds_if_the_cli_gate_is_neutered|Ensures library gate holds even if CLI gate is bypassed.
tests/test_canary_livewire.py|function|test_cli_dry_run_names_the_lanes_live_would_call|Ensures --dry-run lists lanes without calling them.
tests/test_canary_livewire.py|function|test_cli_dry_run_calls_nothing|Ensures --dry-run does not spawn processes or write history.
tests/test_spend_coverage.py|constant|ROOT|Repository root path used for file scanning
tests/test_spend_coverage.py|constant|WRAPPED_VENDOR_ARGV|Test cases for vendors behind process shepherds
tests/test_spend_coverage.py|constant|INNOCENT_ARGV|Test cases for ordinary commands that should not be billed
tests/test_spend_coverage.py|constant|KNOWN_UNGUARDED_ENTRYPOINTS|Dict of files known to be unguarded with reasons
tests/test_spend_coverage.py|function|runnable_spend_entrypoints|Scans repo for directly-runnable spend entry points
tests/test_spend_coverage.py|function|test_a_vendor_behind_a_process_shepherd_is_still_billed|Tests that classify_argv identifies vendors when wrapped
tests/test_spend_coverage.py|function|test_widening_the_wrapper_list_did_not_start_billing_ordinary_commands|Tests that wrapper additions don't bill normal commands
tests/test_spend_coverage.py|function|test_the_wrapper_check_is_not_vacuous|Pins that classification is discriminative
tests/test_spend_coverage.py|function|test_no_new_unguarded_spend_entrypoint_has_appeared|Drift detector for new unguarded spend entry points
tests/test_spend_coverage.py|function|test_the_entrypoint_ledger_has_not_rotted|Ensures ledger entries still exist and are accurate
tests/test_spend_coverage.py|function|test_the_entrypoint_detector_actually_fires|Self-test that the detector works
tests/test_spend_coverage.py|function|test_the_guard_is_installed_by_exactly_one_function_in_the_tree|Pins the set of files that install the guard
tests/test_spend_coverage.py|function|test_guard_on_refuses_and_guard_off_spawns|Tests guard behavior with monkeypatched classifier
tests/test_temporal_ceiling.py|constant|GIT|Indicates git availability for skipping tests.
tests/test_temporal_ceiling.py|class|CleanReachableTest|Tests that a label with sufficient prior co-change is classified REACHABLE on clean arm.
tests/test_temporal_ceiling.py|class|LeakArtifactTest|Tests that the self-prediction leak (clean UNREACHABLE, leaky REACHABLE) is correctly identified.
tests/test_temporal_ceiling.py|class|ClassifyUnitTest|Tests the _classify function's decision order for static edge, no in-scope def, and unreachable.
tests/test_temporal_ceiling.py|class|RenameBoundaryTest|Tests that coupling across file rename is correctly unified.
tests/test_temporal_ceiling.py|class|MaterialityFloorTest|Tests that a single recoverable label among many does not trigger reopen signal when below materiality floor.
tests/test_temporal_ceiling.py|class|CoChangeRevParamTest|Tests that co_change_pairs with rev parameter narrows history and handles unresolvable rev.
daedalus/eval/mutate.py|constant|MUTATE_VERSION|Version string '1' for the mutation module.
daedalus/eval/mutate.py|constant|DROP_CALL|Operator name for dropping a call defect.
daedalus/eval/mutate.py|constant|INVERT_CONDITION|Operator name for inverting a condition defect.
daedalus/eval/mutate.py|constant|WEAKEN_COMPARISON|Operator name for weakening a comparison defect.
daedalus/eval/mutate.py|constant|CHANGE_CONSTANT|Operator name for changing a constant defect.
daedalus/eval/mutate.py|constant|DROP_ARGUMENT|Operator name for dropping an argument defect.
daedalus/eval/mutate.py|constant|EARLY_RETURN|Operator name for early return defect.
daedalus/eval/mutate.py|constant|SKIP_PATH_PARTS|Tuple of path parts to skip during mutation.
daedalus/eval/mutate.py|constant|SKIP_FUNCTIONS|Frozenset of function names to skip during mutation.
daedalus/eval/mutate.py|constant|OPERATORS|Tuple of all operator constants.
daedalus/eval/mutate.py|constant|OPERATOR_CLASS|Mapping from operator to defect class name.
daedalus/eval/mutate.py|class|Mutant|Dataclass representing a generated defect with fields for compatibility.
daedalus/eval/mutate.py|function|trivially_equivalent|Checks if two source strings compile to identical bytecode.
daedalus/eval/mutate.py|function|covered_lines|Returns set of covered lines from existing coverage database.
daedalus/eval/mutate.py|function|generate|Generates a specified number of parseable mutants over real functions deterministically.
tests/test_containment.py|function|test_a_contained_child_can_still_do_its_job|Verifies contained child can write and mkdir inside own worktree
tests/test_containment.py|function|test_the_primary_checkout_cannot_be_written|Verifies contained child cannot write to primary checkout
tests/test_containment.py|function|test_a_file_outside_cannot_be_deleted_or_renamed|Verifies contained child cannot delete or rename files outside worktree
tests/test_containment.py|function|test_THE_MOVE_IN_ATTACK_IS_REFUSED|Verifies move-in attack (rename primary into worktree) is refused
tests/test_containment.py|function|test_a_junction_cannot_be_used_to_reach_outside|Verifies contained child cannot use junction to write outside
tests/test_containment.py|function|test_a_medium_integrity_child_cannot_be_spawned|Verifies contained child cannot spawn an uncontained child process
tests/test_containment.py|function|test_inheritance_is_bounded_and_never_a_plain_boolean|Verifies spawn_contained signature has no unbounded inheritance parameters
tests/test_containment.py|function|test_the_allowlisted_handle_carries_only_the_rights_this_module_chose|Verifies LOW_APPEND_ACCESS mask grants only append rights
tests/test_containment.py|function|test_a_medium_target_is_still_refused_the_way_it_always_was|Verifies LowIntegrityLog refuses a medium-integrity file handle
tests/test_containment.py|function|test_containment_never_downgrades_silently|Verifies containment raises ContainmentUnavailable when platform not supported
tests/test_containment.py|function|test_labelling_a_missing_directory_is_refused_not_ignored|Verifies label_low_integrity raises for missing directory
tests/test_containment.py|function|test_the_module_states_what_it_did_NOT_measure|Verifies unmeasured_vectors includes named pipe, network, reads, and bounded-inheritance limits
tests/test_containment.py|function|test_reads_are_NOT_contained_and_the_docs_say_so|Verifies reads outside worktree are allowed, as documented
tests/test_preservation.py|function|test_measured_regression_fails_the_gate|The real rewrite must not be accepted
tests/test_preservation.py|function|test_measured_regression_deleted_cross_reference_is_lost|The path appears nowhere else, so its disappearance is unambiguous
tests/test_preservation.py|function|test_measured_regression_deleted_endpoint_fact_is_reported|The term survives in Option B, so it is REDUCED not LOST
tests/test_preservation.py|function|test_measured_regression_stripped_backticks_are_demoted_not_lost|The word survives, so degradation not deletion
tests/test_preservation.py|function|test_measured_regression_heading_recase_is_churn_not_loss|Heading recase is not loss
tests/test_preservation.py|function|test_measured_regression_reports_every_one_of_the_four|All four edits are visible
tests/test_preservation.py|function|test_legitimate_rewrite_is_completely_silent|Zero findings, not merely ok=True
tests/test_preservation.py|function|test_live_model_rewrite_passes_with_style_churn_only|No LOST or REDUCED, only RECASED
tests/test_preservation.py|function|test_identity_rewrite_is_silent|Identity rewrite is silent
tests/test_preservation.py|function|test_pure_rewrapping_is_silent|Pure rewrapping is silent
tests/test_preservation.py|function|test_prose_table_cell_may_be_reworded|Legitimate rewording of prose is not a false positive
tests/test_preservation.py|function|test_tone_emphasis_may_be_dropped|Fact-marker filter keeps this quiet
tests/test_preservation.py|function|test_inline_code_deleted_blocks_but_reworded_prose_does_not|Deletion blocks, reworded prose does not
tests/test_preservation.py|function|test_fence_line_deleted_blocks_but_reindented_fence_does_not|Deletion blocks, reindent does not
tests/test_preservation.py|function|test_whole_fence_removed_is_reported_as_structure|Whole fence removal is STRUCTURE
tests/test_preservation.py|function|test_link_target_deleted_blocks_but_relabelled_link_does_not|Link target deletion blocks, relabel does not
tests/test_preservation.py|function|test_bare_path_reference_deleted_blocks|Deletion of path reference blocks
tests/test_preservation.py|function|test_number_with_unit_deleted_blocks_but_unit_spacing_does_not|Deletion blocks, spacing does not
tests/test_preservation.py|function|test_table_row_deleted_blocks_but_recased_header_does_not|Row deletion blocks, header recase does not
tests/test_preservation.py|function|test_acronym_deleted_blocks_but_sentence_initial_words_are_ignored|Acronym deletion blocks, sentence-initial ignored
tests/test_preservation.py|function|test_removed_heading_is_reported_but_does_not_block|Removed heading is SECTION, not blocking
tests/test_preservation.py|function|test_emptied_document_blocks_loudly|Emptied document blocks loudly
tests/test_preservation.py|function|test_only_lost_is_blocking|BLOCKING == frozenset({LOST})
tests/test_preservation.py|function|test_ok_is_exactly_the_absence_of_lost|result.ok == (not result.lost)
tests/test_preservation.py|function|test_summary_is_one_line_and_leads_with_the_blocking_finding|Summary leads with blocking finding
tests/test_preservation.py|function|test_clean_summary_says_so|Clean summary says all fact-bearing artefacts preserved
tests/test_preservation.py|function|test_as_dict_is_json_safe|as_dict is JSON safe
tests/test_preservation.py|function|test_is_prose_path|Returns True for .md, .rst; False for .py, .json
tests/test_preservation.py|function|test_projection_erases_markup_and_wrapping_only|Projection erases markup and wrapping only
tests/test_preservation.py|function|test_checker_is_pure_and_does_no_io|Safe to call inside a gate; no file reads, no subprocesses
tests/test_preservation.py|function|test_blindspot_negation_flip_is_invisible|Negation flip is invisible
tests/test_preservation.py|function|test_blindspot_spelled_out_number_is_invisible|Number spelled out is invisible
tests/test_preservation.py|function|test_blindspot_invented_facts_pass_clean|Never asks what appeared
tests/test_preservation.py|function|test_blindspot_false_prose_around_intact_artefacts_passes_clean|False prose around intact artefacts passes
tests/test_preservation.py|function|test_blindspot_reordering_under_the_wrong_heading_is_invisible|Reordering under wrong heading is invisible
tests/test_stream_hook.py|constant|HOOK_PATH|Path to the stream_hook.py under test
tests/test_stream_hook.py|constant|ABRIDGED|Regex for matching abridged provenance lines
tests/test_stream_hook.py|constant|PARAS|Sample paragraph texts used in tests
tests/test_stream_hook.py|constant|LONG|Long concatenated sample text exceeding LEDE_MAX
tests/test_stream_hook.py|module|hook|Loaded stream_hook module under test
tests/test_stream_hook.py|function|run|Runs stream_hook with monkeypatched env and stdin, returns exit code
tests/test_stream_hook.py|function|run_subprocess|Runs stream_hook as subprocess, returns CompletedProcess
tests/test_stream_hook.py|function|room_text|Returns content of room.md from temp directory
tests/test_stream_hook.py|function|log_lines|Returns non-empty lines from .stream_hook.log
tests/test_stream_hook.py|function|sidecar_body|Returns body of sidecar file without provenance header
tests/test_stream_hook.py|function|test_long_turn_is_abridged_and_the_omission_line_is_true|Guarantees long turns are abridged with correct provenance arithmetic and sidecar integrity
tests/test_stream_hook.py|function|test_short_turn_is_mirrored_whole_with_no_omission_line|Guarantees short turns are mirrored entirely without abridgement or sidecar
tests/test_stream_hook.py|function|test_lede_cuts_at_a_boundary_never_midword|Guarantees abridgement cuts between tokens, not mid-word
tests/test_stream_hook.py|function|test_lede_prefers_the_paragraph_break_inside_the_window|Guarantees lede prefers paragraph breaks within LEDE_MIN-LEDE_MAX window
tests/test_stream_hook.py|function|test_lede_does_not_cut_at_a_version_number_or_a_file_line_reference|Guarantees abridgement avoids cutting at version numbers or file references
tests/test_stream_hook.py|function|test_an_open_code_fence_in_the_lede_is_closed|Guarantees any open code fence in the lede is closed in the room text
tests/test_stream_hook.py|function|test_plumbing_is_never_mirrored|Guarantees plumbing markers are skipped and not mirrored to room
tests/test_stream_hook.py|function|test_empty_turn_is_skipped|Guarantees empty turns are skipped with appropriate log entry
tests/test_stream_hook.py|function|test_dedupe_still_holds|Guarantees identical consecutive turns are deduplicated
tests/test_stream_hook.py|function|test_sidecar_counter_survives_a_restart|Guarantees sidecar counter persists across subprocess restarts
tests/test_stream_hook.py|function|test_counter_continues_past_ids_left_by_an_earlier_day|Guarantees counter continues from existing sidecar IDs from previous runs

## DEPENDS

DEPENDS|tests/test_shadow_run.py|daedalus.spine.picker
DEPENDS|tests/test_primary_tree_fence.py|daedalus.primary_tree
DEPENDS|tests/test_primary_tree_fence.py|daedalus.spine.attempt
DEPENDS|daedalus/structcore/churn.py|daedalus/structcore.markdown
DEPENDS|tests/test_dynamic.py|daedalus.file_bridge
DEPENDS|tests/test_dynamic.py|daedalus.kairos.decompose
DEPENDS|tests/test_dynamic.py|daedalus.kairos.scheduler
DEPENDS|tests/test_dynamic.py|daedalus.core
DEPENDS|tests/test_dynamic.py|daedalus.offload
DEPENDS|tests/test_dynamic.py|daedalus.doctor
DEPENDS|daedalus/providers/codex_cli.py|daedalus.sensitivity
DEPENDS|daedalus/providers/codex_cli.py|daedalus.token_policy
DEPENDS|daedalus/providers/codex_cli.py|daedalus.schemas
DEPENDS|daedalus/providers/codex_cli.py|daedalus.providers._report
DEPENDS|daedalus/providers/codex_cli.py|daedalus.providers.base
DEPENDS|daedalus/providers/codex_cli.py|daedalus.providers.personas
DEPENDS|tests/test_typegraph_star_imports.py|daedalus.structcore.index
DEPENDS|tests/test_typegraph_star_imports.py|daedalus.structcore.typegraph
DEPENDS|tests/test_typegraph_star_imports.py|daedalus.structcore.parse
DEPENDS|daedalus/structcore/imports.py|daedalus/structcore/languages.py
DEPENDS|daedalus/structcore/imports.py|daedalus/structcore/parse.py
DEPENDS|daedalus/benchmark.py|daedalus.provider_router
DEPENDS|daedalus/benchmark.py|daedalus.router
DEPENDS|daedalus/benchmark.py|daedalus.metrics
DEPENDS|daedalus/benchmark.py|daedalus.offload
DEPENDS|daedalus/control_plane.py|daedalus.core
DEPENDS|daedalus/control_plane.py|daedalus.claude_detect
DEPENDS|daedalus/control_plane.py|daedalus.projects
DEPENDS|daedalus/control_plane.py|daedalus.router
DEPENDS|tests/test_mapping_switches.py|daedalus.mapping.switches
DEPENDS|tests/test_era1_robustness.py|daedalus.metrics
DEPENDS|tests/test_era1_robustness.py|daedalus.offload
DEPENDS|tests/test_era1_robustness.py|daedalus.provider_router
DEPENDS|tests/test_era1_robustness.py|daedalus.verifier

## WRITES

WRITES|daedalus/kairos/archive.py|record_attempt writes to caller-specified file path (JSONL).
WRITES|daedalus/memory/__init__.py|memory/events.local.jsonl
WRITES|daedalus/memory/__init__.py|memory/todos.local.md
WRITES|daedalus/memory/__init__.py|memory/vectors.db
WRITES|tests/test_structcore_graph.py|<temp directory written via _write>
WRITES|tests/test_dotenv.py|temporary .env files

## READS

READS|tests/test_extension_manifest.py|vscode-agent-env/extension.js
READS|tests/test_typegraph_star_imports.py|daedalus/ (via TheBlastRadiusIsMeasured)
READS|daedalus/gui/lint.py|runs/gui/*.json (via argv)
READS|daedalus/shift.py|runs/shift.json
READS|daedalus/arch_memory.py|docs/architecture-state.json
READS|daedalus/arch_memory.py|runs/arch_memory.json
READS|daedalus/arch_memory.py|runs/arch_memory.shown
READS|daedalus/arch_memory.py|daedalus/*/__init__.py
READS|daedalus/control_plane.py|.claude/settings.json
READS|daedalus/control_plane.py|.claude/settings.local.json

## CLAIMS

CLAIMS|tests/test_preservation.py|test_number_with_unit_deleted_blocks_but_unit_spacing_does_not: Deletion blocks, spacing does not.
CLAIMS|tests/test_preservation.py|test_table_row_deleted_blocks_but_recased_header_does_not: Row deletion blocks, header recase does not.
CLAIMS|tests/test_preservation.py|test_acronym_deleted_blocks_but_sentence_initial_words_are_ignored: Acronym deletion blocks, sentence-initial ignored.
CLAIMS|tests/test_preservation.py|test_removed_heading_is_reported_but_does_not_block: Removed heading is SECTION, not blocking.
CLAIMS|tests/test_preservation.py|test_emptied_document_blocks_loudly
CLAIMS|tests/test_preservation.py|test_only_lost_is_blocking: BLOCKING == frozenset({LOST})
CLAIMS|tests/test_preservation.py|test_ok_is_exactly_the_absence_of_lost: result.ok == (not result.lost)
CLAIMS|tests/test_preservation.py|test_summary_is_one_line_and_leads_with_blocking
CLAIMS|tests/test_preservation.py|test_clean_summary_says_so
CLAIMS|tests/test_preservation.py|test_as_dict_is_json_safe
CLAIMS|tests/test_preservation.py|test_is_prose_path: returns True for .md, .rst; False for .py, .json
CLAIMS|tests/test_preservation.py|test_projection_erases_markup_and_wrapping_only
CLAIMS|tests/test_preservation.py|test_checker_is_pure_and_does_no_io: Safe to call inside a gate; no file reads, no subprocesses.
CLAIMS|tests/test_preservation.py|test_blindspot_negation_flip_is_invisible: Negation flip is invisible.
CLAIMS|tests/test_preservation.py|test_blindspot_spelled_out_number_is_invisible: Number spelled out is invisible.
CLAIMS|tests/test_preservation.py|test_blindspot_invented_facts_pass_clean: Never asks what appeared.
CLAIMS|tests/test_preservation.py|test_blindspot_false_prose_around_intact_artefacts_passes_clean: False prose around intact artefacts passes.
CLAIMS|tests/test_preservation.py|test_blindspot_reordering_under_the_wrong_heading_is_invisible: Reordering under wrong heading is invisible.
CLAIMS|tests/test_spine_map_source.py|test_a_forged_head_is_caught_as_a_hand_edit: docstring states the attack is caught, but test is xfail (strict=True) awaiting repo_state coverage in digest.
CLAIMS|tests/test_spine_map_source.py|test_a_STALE_snapshot_is_refused_even_though_its_digest_verifies: docstring explains historical bug.
CLAIMS|daedalus/structcore/cache.py|Persistent per-file analysis cache using sqlite, never a correctness dependency.
CLAIMS|tests/test_gate_containment_job_caps.py|Module claims to verify that job caps block forbidden operations and allow legitimate work
CLAIMS|daedalus/spine/docref_gate.py|'nothing here writes, spawns, or reaches the network'
CLAIMS|daedalus/spine/docref_gate.py|'checks: denominator first, then document existence, then each finding'
CLAIMS|daedalus/spine/docref_gate.py|'deliberately does not check fact preservation'
CLAIMS|daedalus/spine/docref_gate.py|'fail closed with exit codes 0 (pass), 1 (fail), 2 (inconclusive)'
CLAIMS|daedalus/spine/docref_gate.py|'verifying zero targets is exit 2, never 0'
CLAIMS|daedalus/ikarus_act.py|may_act guarantees it never calls classify and its verdict never depends on classify's label (from module docstring).
CLAIMS|daedalus/ikarus_act.py|The module does no IO (from module docstring).
CLAIMS|daedalus/build.py|Nothing here writes to a repo, drives a provider, or bypasses a lane gate
CLAIMS|daedalus/build.py|Frontier-first topology
CLAIMS|tests/test_context_plan_latent.py|The latent half of the context planner must be visible, not merely optional.

## UNWIRED

UNWIRED|tests/test_spine_return_arc.py|test_the_reader_cannot_write_even_if_asked
UNWIRED|tests/test_spine_return_arc.py|test_a_read_only_open_does_not_create_a_ledger
UNWIRED|tests/test_spine_return_arc.py|test_memory_only_matches_the_task_it_actually_attempted
UNWIRED|tests/test_spine_return_arc.py|test_head_is_read_off_disk_without_spawning_anything
UNWIRED|tests/test_spine_return_arc.py|test_a_detached_head_holding_a_raw_sha_resolves
UNWIRED|tests/test_spine_return_arc.py|test_a_packed_ref_resolves
UNWIRED|tests/test_spine_return_arc.py|test_a_linked_worktree_resolves_through_commondir
UNWIRED|tests/test_spine_return_arc.py|test_a_directory_that_is_not_a_repo_reads_as_unknown

## SMELL

SMELL|tests/test_spine_map_source.py|test_the_real_repo_snapshot_is_JUDGED_and_ACTED_ON_consistently may skip if no committed architecture-state.json exists, which is a conditional branch in the test.
SMELL|daedalus/ikarus_act.py|The allow rule in may_act is simple (first significant word must be an act verb and not interrogative), but the suspicion signal in _suspect_signal uses regexes and German vocabulary, creating a separation that could be confusing.
SMELL|daedalus/build.py|wave_path_conflicts duplicates logic from daedalus.kairos.scheduler._paths_overlap
SMELL|daedalus/build.py|_chunk_waves mirrors Ikarus.plan sizing logic
SMELL|tests/test_spine_attempt_containment.py|Windows-specific alias tests are conditionally skipped, indicating platform-dependent behavior