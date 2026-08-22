# Census shard 12/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_structcore_coverage.py|class|ShellCloneLeakTest|tests for shell clone leak due to naming C/C++ units
tests/test_structcore_coverage.py|class|NonPythonNeighborhoodScopeTest|tests for neighborhood scope for non-Python targets
tests/test_structcore_coverage.py|class|IndexDeterminismTest|tests for index determinism across rebuilds and hash seeds
tests/test_prose_gate.py|class|ProseBranchTests|Tests verifier prose branch: fact preservation, deleted facts block, faithful rewrite passes, missing before image fails closed, created file passes, deleted file blocks, advisory mode, docref correction waiver.
tests/test_prose_gate.py|class|DispatchUsesDiskTruthTests|Tests that unreported but written files are still checked and self-report used when no disk evidence.
tests/test_prose_gate.py|class|VerdictTests|Tests verdict logic: timeout is inconclusive, red suite is fail, real failure outranks timeout, pass.
tests/test_prose_gate.py|class|BeforeImageTests|Tests prose_before_images: backups become repo-relative before images, no backups is no evidence.
tests/test_prose_gate.py|class|DocrefsOverrideTests|Tests docref scanning with overrides: before report from remembered text, override none models non-existent file, override adds document.
tests/test_prose_gate.py|class|DenominatorTests|Tests docref denominator: deleting corpus is refused, correction passes, still broken fails, verify_fixes checks denominator first.
tests/test_prose_gate.py|class|DocrefGateTests|Tests docref gate: real correction passes, unfixed ref fails, deleting document fails on denominator, etc.
daedalus/config.py|constant|REPO_CONFIG|Path to repo-local config file relative to repo root: .agentenv/agentenv.json
daedalus/config.py|constant|TEMPLATE_DIR|Resolved path to templates directory (parents[1] / templates)
daedalus/config.py|constant|WRITE_WAVE_POLICY_LEVELS|Tuple of valid write wave policy levels: never, low_risk, always
daedalus/config.py|constant|DEFAULT_WRITE_WAVE_POLICY|Fail-closed default for write wave policy: never
daedalus/config.py|function|resolve_write_wave_policy|Returns permitted write wave auto-promotion level from project config dict, defaulting to 'never' for missing or invalid values
daedalus/config.py|constant|KNOWN_EXTERNAL_WRITE_LANES|Tuple of recognized external write lane names: deepseek
daedalus/config.py|constant|DEFAULT_EXTERNAL_WRITE_LANES|Fail-closed default for external write lanes: empty tuple
daedalus/config.py|function|resolve_external_write_lanes|Returns intersection of config's external_write_lanes with known lanes, case-insensitive; default empty
daedalus/config.py|function|external_write_lanes_for_repo|Reads repo-local .agentenv/agentenv.json and resolves external write lanes for that repo
daedalus/config.py|constant|STARTER|Template dict for scaffolded agentenv.json, including policy, test settings, and work queue config
daedalus/config.py|constant|TOOL_INSTRUCTION_TEMPLATES|Tuple of tool instruction filenames: CLAUDE.md, AGENTS.md
daedalus/config.py|function|resolve_project|Returns project config dict for given repo_root and optional project name; merges repo-local confinement
daedalus/config.py|function|init_repo|Scaffolds .agentenv/agentenv.json from STARTER, copies template agents and tool instructions; returns path to written config
tests/test_safety_reachability.py|module|test_safety_reachability|Contains unit tests for safety reachability.
tests/test_safety_reachability.py|constant|CODER|Defined coder persona with external_ok=True.
tests/test_safety_reachability.py|constant|AVAIL|Defines available provider flags for testing.
tests/test_safety_reachability.py|constant|OBJECTIVE|Example objective string for clamp helper.
tests/test_safety_reachability.py|class|ReachabilityHelperTests|Tests for fenced_reachability, fenced_fragment, and cycle/truncation behavior.
tests/test_safety_reachability.py|class|GapIsRealTests|Documents the vulnerability that path-local risk does not catch transitive dependencies.
tests/test_safety_reachability.py|class|SelectProviderFenceTests|Tests that select_provider uses repo_root to escalate via blast-radius.
tests/test_safety_reachability.py|class|DominanceGuardrailTests|Tests that fence dominance fallback works correctly.
tests/test_safety_reachability.py|class|DeterminismTests|Tests that blast-radius chain is deterministic across hash seeds.
tests/test_safety_reachability.py|class|LiveMutatePathTests|Tests that route_and_select threads repo_root into the fence.
tests/test_mutation_score.py|class|GeneratorTests|Tests for mutation generation: operator reachability, determinism, spread sampling, compile validity, utf8 offsets, unparseable source, guard operator targeting
tests/test_mutation_score.py|class|AnchorTests|Tests for mutation anchoring: span mutation refuses on shifted file, patch mutation behavior, no-op edit not applicable
tests/test_mutation_score.py|class|ClassificationTests|Tests for mutation classification with fake runner: red baseline inconclusive, timeout inconclusive, expect_test requirement, inapplicable not counted
tests/test_mutation_score.py|class|EndToEndTests|End-to-end tests with real pytest: good tests kill all mutants, weak tests leave named survivors, dropping covering test flips kill to survivor, working tree never written, sandbox destroyed
tests/test_mutation_score.py|class|DropTestControlTests|Tests for drop_test function: removes function and still parses, refuses nonexistent test
tests/test_mutation_score.py|class|RenderTests|Tests for render function: output includes SURVIVED, UNFALSIFIABLE, equivalent mutant, mutation score percentage
tests/test_mutation_score.py|function|build_fixture_repo|Builds a temporary fixture repository with good and weak modules and tests
tests/test_mutation_score.py|constant|GOOD_MODULE|Source code for a well-tested module (is_allowed with DENY and size checks)
tests/test_mutation_score.py|constant|GOOD_TESTS|Test source that fully covers GOOD_MODULE branches
tests/test_mutation_score.py|constant|WEAK_MODULE|Source code for a poorly-tested module (classify incomplete branches)
tests/test_mutation_score.py|constant|WEAK_TESTS|Test source that misses some branches of WEAK_MODULE
tests/test_mutation_score.py|constant|RED_TESTS|Test source that is already failing (baseline non-green)
tests/test_spine_ledger.py|function|db_path|Create a temporary database path nested directory.
tests/test_spine_ledger.py|function|ledger|Yield a SpineLedger instance and close it afterward.
tests/test_spine_ledger.py|function|test_pragmas_are_actually_applied|Verify that WAL, synchronous=NORMAL, busy_timeout=30000, foreign_keys=ON are applied.
tests/test_spine_ledger.py|function|test_pragmas_are_reapplied_on_reopen|Verify that pragmas persist after close/reopen.
tests/test_spine_ledger.py|function|test_foreign_keys_are_enforced|Verify foreign key constraint on intent_events.
tests/test_spine_ledger.py|function|test_default_path_is_under_runs_spine|Verify DEFAULT_DB_PATH and environment override.
tests/test_spine_ledger.py|function|test_parent_directories_are_created|Verify that parent dirs are created on open.
tests/test_spine_ledger.py|function|test_record_intent_commits_before_returning|Verify that intents are visible on disk immediately.
tests/test_spine_ledger.py|function|test_open_intents_and_resolution_lifecycle|Verify open_intents, mark_completed, mark_failed, get.
tests/test_spine_ledger.py|function|test_state_transitions_append_events_and_never_update_the_row|Verify intent row immutable, events appended.
tests/test_spine_ledger.py|function|test_intent_survives_an_uncleanly_abandoned_connection|Verify intent survives abandoned connection (no close).
tests/test_spine_ledger.py|function|test_intent_survives_a_killed_process|Verify intent survives os._exit (killed process).
tests/test_spine_ledger.py|function|test_resolve_by_effect_finds_the_intent|Verify resolve_by_effect returns matching intents.
tests/test_spine_ledger.py|function|test_double_completion_is_rejected|Verify IntentAlreadyResolved on double completion.
tests/test_spine_ledger.py|function|test_resolving_an_unknown_intent_is_rejected|Verify UnknownIntent on unknown id.
tests/test_spine_ledger.py|function|test_unserialisable_values_are_refused_loudly|Verify ValueError on unserialisable payload.
tests/test_spine_ledger.py|function|test_second_writer_waits_out_busy_timeout|Verify second writer waits and succeeds.
tests/test_spine_ledger.py|function|test_without_busy_timeout_the_second_writer_would_fail|Verify without timeout the second writer fails.
tests/test_spine_ledger.py|function|test_concurrent_writers_do_not_corrupt|Verify concurrent writes do not corrupt DB.
tests/test_spine_ledger.py|function|test_canonical_json_round_trips_byte_identically|Verify canonical JSON round-trip.
tests/test_spine_ledger.py|function|test_canonical_json_is_insertion_order_independent|Verify canonical JSON independent of key order.
tests/test_spine_ledger.py|function|test_event_details_are_canonical_json|Verify event details are canonical JSON.
tests/test_spine_ledger.py|function|test_recent_intents_returns_resolved_ones_that_open_intents_cannot|Verify recent_intents returns resolved intents.
tests/test_spine_ledger.py|function|test_recent_intents_is_newest_first_and_includes_open_ones|Verify newest first and open intents included.
tests/test_spine_ledger.py|function|test_recent_intents_limit_and_kind_filter|Verify limit and kind filter.
tests/test_spine_ledger.py|function|test_recent_intents_non_positive_limit_returns_nothing_not_everything|Verify non-positive limit returns empty.
tests/test_spine_ledger.py|function|test_recent_intents_carries_the_resolution_result|Verify recent_intents carries result and effect_id.
tests/test_git_is_a_process_launcher.py|function|arena|Provides a real repo with a linked worktree for testing.
tests/test_git_is_a_process_launcher.py|constant|pytestmark|Marks module as skipped if git is not on PATH.
tests/test_git_is_a_process_launcher.py|function|test_CONTROL_the_attack_works_against_an_unpinned_git|Guarantees the attack vector works without the guard.
tests/test_git_is_a_process_launcher.py|function|test_naming_the_admin_directory_defeats_the_rewritten_pointer|Guarantees naming admin directory defeats rewritten gitdir pointer.
tests/test_git_is_a_process_launcher.py|function|test_the_pointer_is_read_before_the_candidate_can_move_it|Guarantees the pointer is read before candidate code runs.
tests/test_git_is_a_process_launcher.py|function|test_CONTROL_a_filter_in_the_USER_config_fires_from_gitattributes|Guarantees a filter in user config fires without gitdir rewrite.
tests/test_git_is_a_process_launcher.py|function|test_the_user_and_system_config_are_removed_from_the_lookup|Guarantees user/system config are removed from lookup.
tests/test_git_is_a_process_launcher.py|function|test_the_env_drops_variables_whose_empty_value_is_a_valid_command|Guarantees empty string is not equivalent to absence for env vars.
tests/test_git_is_a_process_launcher.py|function|test_the_env_is_actually_passed_to_the_process|Guarantees the hardened env is actually passed to the process.
tests/test_git_is_a_process_launcher.py|function|test_CONTROL_no_ext_diff_alone_still_spawns_a_textconv|Guarantees --no-ext-diff alone does not suppress textconv.
tests/test_git_is_a_process_launcher.py|function|test_no_textconv_suppresses_it|Guarantees --no-textconv suppresses textconv.
tests/test_git_is_a_process_launcher.py|function|test_the_product_pins_no_textconv_in_the_option_list|Guarantees the product passes --no-textconv.
tests/test_git_is_a_process_launcher.py|function|test_CONTROL_an_attributesFile_in_the_admin_config_fires|Guarantees an attributesFile in admin config fires.
tests/test_git_is_a_process_launcher.py|function|test_the_exec_config_keys_are_pinned_empty_on_the_command_line|Guarantees -c beats config files to disable core.attributesFile.
tests/test_git_is_a_process_launcher.py|function|test_a_real_attempt_does_not_execute_the_candidates_filter|Guarantees a real attempt does not execute candidate's filter.
tests/test_git_is_a_process_launcher.py|function|test_an_ordinary_patch_is_still_captured_correctly|Guarantees patch capture still works after hardening.
tests/test_mapping_spectral.py|class|FiedlerGroundTruth|1. Fiedler / algebraic connectivity: find the bridge we planted.
tests/test_mapping_spectral.py|class|ModularityGroundTruth|2. Newman modularity: the planted partition must beat a random one.
tests/test_mapping_spectral.py|class|ConductanceGroundTruth|3. Conductance: rank the leaky package above the tight one.
tests/test_mapping_spectral.py|class|EigengapGroundTruth|4. Eigengap: a barbell has 2 clusters, planted-3 has 3.
tests/test_mapping_spectral.py|class|ReportPlumbing|
tests/test_mapping_spectral.py|class|MathUnavailable|Degrading honestly when the 'math' extra is absent.
daedalus/structcore/graph.py|function|identifiers|Extracts identifier tokens from source code, excluding stop words
daedalus/structcore/graph.py|function|name_index|Builds a name-to-list-of-units index
daedalus/structcore/graph.py|class|SymbolResolver|Per-file symbol table with import edges for name resolution
daedalus/structcore/graph.py|function|build_resolver|Constructs a SymbolResolver from units and import edges
daedalus/structcore/graph.py|function|callees|Returns units that a focus unit likely calls, with optional resolver
daedalus/structcore/graph.py|function|callers|Returns units that likely call a focus unit, with optional resolver
daedalus/structcore/graph.py|function|fenced_fragment|Returns the first matching fenced path fragment for a rel path
daedalus/structcore/graph.py|function|canonical_node|Returns the canonical index node for a given rel path
daedalus/structcore/graph.py|function|fenced_reachability|BFS to find shortest dependency chain from a path to a fenced module
daedalus/structcore/graph.py|function|fenced_dominance|Computes fraction of non-fenced modules that transitively reach fenced modules
daedalus/structcore/graph.py|constant|REACH_VISIT_CAP|Maximum nodes to visit during reachability BFS (5000)
tests/test_picker_outcome.py|constant|TWINS|Provides test data with twin islands for memory experiments.
tests/test_picker_outcome.py|fixture|no_eval|Monkeypatches _load_baseline to keep eval source hermetic.
tests/test_picker_outcome.py|fixture|repo|Creates a temporary inventory with matching git HEAD for testing.
tests/test_picker_outcome.py|function|test_the_twins_are_identical_measurements|Verifies the twins are indistinguishable before memory speaks.
tests/test_picker_outcome.py|function|test_two_identical_candidates_are_ordered_by_their_outcome|Verifies outcome orders identical candidates by score.
tests/test_picker_outcome.py|function|test_at_the_band_floor_clean_is_picked_after_gates_failed|Verifies tie-break: clean after gates_failed at band floor.
tests/test_picker_outcome.py|function|test_severity_outranks_the_attempt_count|Verifies severity is checked before prior_attempts count.
tests/test_picker_outcome.py|function|test_no_outcome_can_move_a_candidate_out_of_its_band|Verifies band invariant for every outcome.
tests/test_picker_outcome.py|function|test_memory_never_promotes_a_candidate|Verifies memory only lowers score, never raises.
tests/test_picker_outcome.py|function|test_no_outcome_removes_work_from_the_queue|Verifies memory is a penalty, not a filter.
tests/test_picker_outcome.py|function|test_every_attempt_state_the_writer_can_produce_is_classified|Verifies all ATTEMPT_STATES are in OUTCOME_POLICY.
tests/test_picker_outcome.py|function|test_the_policy_is_internally_well_formed|Verifies policy rows have valid fields.
tests/test_picker_outcome.py|function|test_the_policy_is_ordered_the_way_its_prose_claims|Verifies residual and severity ordering.
tests/test_picker_outcome.py|function|test_an_unknown_or_missing_outcome_fails_closed|Verifies unknown outcomes map to UNKNOWN_OUTCOME.
tests/test_picker_outcome.py|function|test_an_in_flight_attempt_is_sunk_as_hard_as_a_finished_one|Verifies unresolved intents sink as finished.
tests/test_picker_outcome.py|function|test_repeats_of_a_mild_outcome_compound|Verifies multiple mild outcomes compound.
tests/test_picker_outcome.py|function|test_compounding_counts_the_instruction_not_the_task_id|Verifies compounding uses instruction fingerprint.
tests/test_picker_outcome.py|function|test_the_score_carries_the_argument_that_produced_it|Verifies evidence trail in score.
tests/test_picker_outcome.py|function|test_the_note_names_the_outcomes_it_acted_on|Verifies note includes outcome names.
tests/test_picker_outcome.py|function|test_a_candidate_already_below_its_ceiling_is_reported_as_held|Verifies unmoved candidates are noted.
tests/test_structcore_parallel.py|constant|FN|Provides a Python function template for test code with a placeholder n.
tests/test_structcore_parallel.py|constant|JS|Provides a JavaScript module template for test code with a placeholder n.
tests/test_structcore_parallel.py|class|ParallelDeterminismTest|Tests that parallel index is byte-identical to serial and preserves all_units order.
tests/test_structcore_parallel.py|class|AmbiguousImportDeterminismTest|Tests deterministic resolution of ambiguous imports across directories.
tests/test_structcore_parallel.py|class|PersistentCacheTest|Tests persistent cache behavior including invalidation, key composition, and bounded directory.
tests/test_structcore_parallel.py|class|RefactorEquivalenceTest|Tests that refactored functions (split of import/unit/window pipelines) produce identical results.
tests/test_structcore_parallel.py|class|SingleFlightWithPoolTest|Tests that concurrent callers share one pooled build under single-flight lock.
tests/test_structcore_parallel.py|class|SerialFallbackTest|Tests that zero workers fall back to serial and produce identical index.
daedalus/observe/shape.py|constant|SHAPE_VERSION|Version identifier for the shape format.
daedalus/observe/shape.py|constant|MAX_NAMES|Maximum number of names/keys to extract before truncation.
daedalus/observe/shape.py|constant|MAX_NAME_CHARS|Maximum characters per name before clipping.
daedalus/observe/shape.py|constant|MAX_DEPTH|Maximum recursion depth for nested containers.
daedalus/observe/shape.py|constant|ARRAY|Family for array-like objects (ndarray, tensor, etc.).
daedalus/observe/shape.py|constant|TABLE|Family for table-like objects (DataFrame, etc.).
daedalus/observe/shape.py|constant|RECORD|Family for dicts, dataclasses, namespaces.
daedalus/observe/shape.py|constant|SEQUENCE|Family for lists, tuples, sets.
daedalus/observe/shape.py|constant|TREE|Family for tree-like structures (ROOT, HDF5 groups).
daedalus/observe/shape.py|constant|SCALAR|Family for single values (bool, int, float, etc.).
daedalus/observe/shape.py|constant|TEXT|Family for string objects.
daedalus/observe/shape.py|constant|BINARY|Family for bytes/bytearray objects.
daedalus/observe/shape.py|constant|OPAQUE|Family for objects that cannot be characterized.
daedalus/observe/shape.py|class|Shape|Immutable dataclass representing one shape observation.
daedalus/observe/shape.py|class|ShapeConflict|Dataclass for discrepancies between declared and observed shapes.
daedalus/observe/shape.py|function|describe|Describes a live object's shape without reading its values.
daedalus/observe/shape.py|function|compare_declared|Compares an observed shape to declared field names.
tests/test_structcore_center_naming.py|class|CenterRelativeResolutionTest|Tests center-relative imports resolve, dotted names are package-relative, isolated modules stay isolated, and naming mode is reported.

## DEPENDS

DEPENDS|tests/test_preservation.py|test_preservation_fixtures
DEPENDS|tests/test_stream_hook.py|runs/council/stream_hook.py
DEPENDS|tests/test_spine_map_source.py|daedalus.spine.picker
DEPENDS|tests/test_spine_map_source.py|daedalus.mapping.drift
DEPENDS|daedalus/structcore/cache.py|daedalus/structcore/parse
DEPENDS|daedalus/structcore/cache.py|daedalus/structcore/perfile
DEPENDS|daedalus/structcore/cache.py|daedalus/structcore/tokens
DEPENDS|tests/test_bridge_signals.py|daedalus.file_bridge
DEPENDS|tests/test_bridge_signals.py|daedalus.doctor
DEPENDS|tests/test_gate_containment_job_caps.py|daedalus.spine.attempt
DEPENDS|tests/test_gate_containment_job_caps.py|daedalus.spine.containment
DEPENDS|daedalus/spine/docref_gate.py|daedalus.spine.docrefs
DEPENDS|daedalus/build.py|daedalus.categories
DEPENDS|daedalus/build.py|daedalus.kairos.decompose
DEPENDS|daedalus/build.py|daedalus.kairos.scheduler
DEPENDS|daedalus/build.py|daedalus.router
DEPENDS|daedalus/build.py|daedalus.bookkeeper
DEPENDS|tests/test_context_plan_latent.py|daedalus.context_plan
DEPENDS|tests/test_context_plan_latent.py|daedalus.memory.embeddings
DEPENDS|tests/test_context_plan_latent.py|daedalus.structcore
DEPENDS|tests/test_spine_attempt_containment.py|daedalus.spine.attempt
DEPENDS|tests/test_offload_automint.py|daedalus
DEPENDS|tests/test_offload_automint.py|daedalus.offload
DEPENDS|tests/test_offload_automint.py|daedalus.eval.mint
DEPENDS|tests/test_offload_automint.py|daedalus.providers
DEPENDS|tests/test_offload_automint.py|daedalus.metrics
DEPENDS|daedalus/eval/tasks.py|daedalus.projects
DEPENDS|tests/test_semantic_route_cold_start.py|daedalus.semantic_route
DEPENDS|tests/test_semantic_route_cold_start.py|daedalus.provider_router
DEPENDS|tests/test_semantic_route_cold_start.py|daedalus.router
DEPENDS|tests/test_wiki.py|daedalus.wiki.links
DEPENDS|tests/test_wiki.py|daedalus.wiki.vault
DEPENDS|tests/test_shadow_run.py|daedalus.spine.bootstrap
DEPENDS|tests/test_shadow_run.py|daedalus.spine.attempt

## WRITES

WRITES|daedalus/control_plane.py|project JSON file via PROJECT_DIR
WRITES|daedalus/bookkeeper.py|docs/architecture.html
WRITES|daedalus/bookkeeper.py|docs/architecture_history/
WRITES|daedalus/bookkeeper.py|docs/architecture_history/manifest.json
WRITES|daedalus/bookkeeper.py|docs/architecture_history/index.html
WRITES|daedalus/selftest.py|temporary scratch repo (temp directory with .agentenv, agents, src files)

## READS

READS|daedalus/structcore/ignore.py|<root>/.daedalusignore file
READS|daedalus/structcore/ignore.py|DAEDALUS_IGNORE environment variable
READS|daedalus/structcore/ignore.py|DAEDALUS_CENTER environment variable
READS|daedalus/eval/tasks.py|AGENT_ENV_ROOT (file system parent directory)
READS|daedalus/wiki/vault.py|.md files in vault directories
READS|tests/test_semantic_route_cold_start.py|environment variables: OLLAMA_EMBED_MODEL, OLLAMA_HOST, DAEDALUS_EMBED_TIMEOUT, DAEDALUS_EMBED_COLD_TIMEOUT, DAEDALUS_LATENT
READS|tests/test_shadow_run.py|temporary files via tmp_path
READS|daedalus/providers/codex_cli.py|message_path (codex output file)
READS|daedalus/providers/codex_cli.py|schema_path (schema file)
READS|tests/test_extension_manifest.py|vscode-agent-env/package.json

## CLAIMS

CLAIMS|daedalus/adapters/subprocess_adapter.py|each CLI still needs a verified command profile and provider-specific event parser (module docstring)
CLAIMS|tests/test_comms.py|Docstring states: 'init_repo drops CLAUDE.md/AGENTS.md into the target repo (never overwrites)'
CLAIMS|tests/test_comms.py|Docstring states: '.vscode/tasks.json is valid JSON and contains the bridge watch task'
CLAIMS|tests/test_comms.py|Docstring states: 'docs/COMMS_PROTOCOL.md documents every request field _read_request handles'
CLAIMS|tests/test_canary_livewire.py|The file claims that by driving the gate via spawn sentinel, tests go red if the gate is deleted.
CLAIMS|tests/test_spend_coverage.py|Does the spend ceiling actually cover the ways OUT of this machine? (module docstring)
CLAIMS|tests/test_spend_coverage.py|The architectural fact this audit turned on, pinned so it cannot change silently. (from test_the_guard_is_installed_by_exactly_one_function_in_the_tree)
CLAIMS|tests/test_spend_coverage.py|DRIFT DETECTOR for the hole that produced this whole audit. (from test_no_new_unguarded_spend_entrypoint_has_appeared)
CLAIMS|tests/test_spend_coverage.py|A ledger naming files that no longer exist reads as coverage of files that do. (from test_the_entrypoint_ledger_has_not_rotted)
CLAIMS|tests/test_spend_coverage.py|The paste-worthy one: the SAME call, guarded and unguarded, against an exhausted ceiling. (from test_guard_on_refuses_and_guard_off_spawns)
CLAIMS|daedalus/eval/mutate.py|Module docstring claims 'mechanical, unbiased defect corpus for HELD-OUT validation.'
CLAIMS|daedalus/eval/mutate.py|Function trivially_equivalent docstring claims 'True if the two sources compile to IDENTICAL bytecode.'
CLAIMS|tests/test_containment.py|Every line of the module docstring is an assertion; this file exists to make sure the list stays a measurement rather than becoming a promise
CLAIMS|tests/test_preservation.py|Every guard is tested in both directions: damaging rewrite that must fire and legitimate rewrite that must stay silent.
CLAIMS|tests/test_preservation.py|The test_blindspot_* cases assert the checker is SILENT on damage it structurally cannot see.
CLAIMS|tests/test_preservation.py|test_measured_regression_fails_the_gate: The real rewrite must not be accepted.
CLAIMS|tests/test_preservation.py|test_measured_regression_deleted_cross_reference_is_lost: The path appears nowhere else, so its disappearance is unambiguous.
CLAIMS|tests/test_preservation.py|test_measured_regression_deleted_endpoint_fact_is_reported: The term survives in Option B, so it is REDUCED not LOST.
CLAIMS|tests/test_preservation.py|test_measured_regression_stripped_backticks_are_demoted_not_lost: The word survives, so degradation not deletion.
CLAIMS|tests/test_preservation.py|test_measured_regression_heading_recase_is_churn_not_loss: Heading recase is not loss.
CLAIMS|tests/test_preservation.py|test_measured_regression_reports_every_one_of_the_four: All four edits are visible.
CLAIMS|tests/test_preservation.py|test_legitimate_rewrite_is_completely_silent: Zero findings, not merely ok=True.
CLAIMS|tests/test_preservation.py|test_live_model_rewrite_passes_with_style_churn_only: No LOST or REDUCED, only RECASED.
CLAIMS|tests/test_preservation.py|test_identity_rewrite_is_silent
CLAIMS|tests/test_preservation.py|test_pure_rewrapping_is_silent
CLAIMS|tests/test_preservation.py|test_prose_table_cell_may_be_reworded: Legitimate rewording of prose is not a false positive.
CLAIMS|tests/test_preservation.py|test_tone_emphasis_may_be_dropped: Fact-marker filter keeps this quiet.
CLAIMS|tests/test_preservation.py|test_inline_code_deleted_blocks_but_reworded_prose_does_not: Deletion blocks, reworded prose does not.
CLAIMS|tests/test_preservation.py|test_fence_line_deleted_blocks_but_reindented_fence_does_not: Deletion blocks, reindent does not.
CLAIMS|tests/test_preservation.py|test_whole_fence_removed_is_reported_as_structure: Whole fence removal is STRUCTURE.
CLAIMS|tests/test_preservation.py|test_link_target_deleted_blocks_but_relabelled_link_does_not: Link target deletion blocks, relabel does not.
CLAIMS|tests/test_preservation.py|test_bare_path_reference_deleted_blocks: Deletion of path reference blocks.

## UNWIRED

UNWIRED|tests/test_spine_return_arc.py|test_forget_disables_memory
UNWIRED|tests/test_spine_return_arc.py|test_a_missing_ledger_is_an_empty_memory_not_a_failure
UNWIRED|tests/test_spine_return_arc.py|test_an_unreadable_ledger_is_reported_never_silently_forgotten
UNWIRED|tests/test_spine_return_arc.py|test_a_rewritten_instruction_does_not_inherit_the_old_attempts_memory
UNWIRED|tests/test_spine_return_arc.py|test_the_same_instruction_is_what_sinks_a_candidate
UNWIRED|tests/test_spine_return_arc.py|test_memory_has_no_window_an_old_attempt_is_still_remembered
UNWIRED|tests/test_spine_return_arc.py|test_ranking_a_queue_does_not_modify_the_ledger
UNWIRED|tests/test_spine_return_arc.py|test_ranking_never_initialises_a_ledger_it_merely_reads

## SMELL

SMELL|daedalus/structcore/graph.py|Local import of .markdown.code_modules inside _graph_nodes to avoid circular dependency or for lazy loading
SMELL|daedalus/observe/shape.py|describe function has high cyclomatic complexity with many branching checks for different object types.
SMELL|tests/test_worktree_properties.py|duplication of _make_junction and _init_primary_repo from tests/test_worktree.py
SMELL|daedalus/eval/mutate.py|Module defines multiple unused helper functions (3) not used internally, indicating dead code.
SMELL|tests/test_spine_map_source.py|test_a_forged_head_is_caught_as_a_hand_edit is marked xfail with strict=True, indicating a planned future change.