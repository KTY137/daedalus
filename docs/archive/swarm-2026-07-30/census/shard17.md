# Census shard 17/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_dotenv.py|function|test_every_example_key_is_pinned_by_the_suite_conftest|Ensures all keys in .env.example are cleared in conftest to prevent leakage
tests/test_churn.py|class|NumstatParseTest|Tests _parse_numstat parsing and sum.
tests/test_churn.py|class|GracefulDegradeTest|Tests graceful degradation to empty and hotspots with zero churn.
tests/test_churn.py|class|ChurnRankingTest|Tests churn ranking with git history.
tests/test_churn.py|class|CoChangePairsTest|Tests co_change_pairs with PMI and mega-commit cap.
tests/test_churn.py|class|TemporalMissesExclusionTest|Tests temporal_misses exclusion and reporting.
tests/test_churn.py|constant|GIT|Path to git executable or None.
daedalus/tools/inventory.py|constant|INVENTORY_VERSION|Version string for the inventory format
daedalus/tools/inventory.py|constant|SKILL_SCOPES|Precedence-ordered list of (scope, relative_path) pairs for skill directories
daedalus/tools/inventory.py|constant|USER_SKILL_DIRS|Tuple of user-level skill directories
daedalus/tools/inventory.py|constant|MCP_SCOPES|Precedence-ordered list of (scope, relative_path) pairs for MCP config files
daedalus/tools/inventory.py|class|ToolRecord|Dataclass representing one tool with provenance and verdict
daedalus/tools/inventory.py|function|collect_skills|Collects all skills from project and user scopes, vetting each
daedalus/tools/inventory.py|function|collect_mcp_servers|Collects all MCP servers from project and user scopes, vetting each
daedalus/tools/inventory.py|function|build|Returns the whole inventory as a deterministic dict
daedalus/tools/inventory.py|function|render|Returns a flat table string for terminal display of inventory
daedalus/tools/inventory.py|function|main|CLI entry point that prints inventory as JSON or table
daedalus/structcore/topology.py|function|spectral_partition|Analyzes the import graph and returns a two-way visualization cut using normalized Laplacian sweep, refusing oversized graphs and handling disconnected components.
tests/test_evolution_baseline.py|function|test_bare_pytest_does_not_reach_the_candidates_own_code|Verifies bare pytest does not reach candidate's own code (shadowing defect)
tests/test_evolution_baseline.py|function|test_evaluator_invokes_an_interpreter_qualified_pytest|Guards that evaluate_candidates uses sys.executable -m pytest
tests/test_evolution_baseline.py|function|test_fitness_is_binary_so_there_is_no_ordering_among_green_candidates|Verifies selection is first-green-wins
tests/test_evolution_baseline.py|function|test_no_candidate_is_selected_when_none_is_green|Verifies no selection when all red
tests/test_evolution_baseline.py|function|test_the_fitness_function_has_no_caller|Verifies evaluate_candidates has no callers
tests/test_evolution_baseline.py|function|test_evaluator_bounds_the_candidate_test_run|Guards that evolution.py has per-candidate timeout
tests/test_operability_drill.py|constant|ROOT|Root path of the repository, resolved to two directories above the test file.
tests/test_operability_drill.py|function|test_incomplete_is_never_rounded_up_to_a_pass|Ensures EXIT_PASS, EXIT_FAIL, and EXIT_INCOMPLETE are distinct values.
tests/test_operability_drill.py|function|test_one_failure_outranks_any_number_of_passes|Ensures a single failure results in EXIT_FAIL regardless of passes.
tests/test_operability_drill.py|function|test_a_single_unexercised_control_blocks_the_verdict|Ensures one incomplete control results in EXIT_INCOMPLETE.
tests/test_operability_drill.py|function|test_a_proof_from_another_revision_fails_the_drill|Ensures staleness detection returns FAIL if the measured head does not match.
tests/test_operability_drill.py|function|test_a_proof_for_THIS_revision_passes|Ensures staleness detection returns PASS if the measured head matches.
tests/test_operability_drill.py|function|test_a_control_that_raises_is_INCOMPLETE_and_says_so|Ensures a crashing control is recorded as INCOMPLETE with the exception detail.
tests/test_operability_drill.py|function|test_the_receipt_records_the_revision_it_was_measured_at|Ensures the receipt JSON contains 'head' and 'scheduling_defensible'.
tests/test_operability_drill.py|function|test_scheduling_defensible_is_true_ONLY_on_a_clean_exit|Ensures scheduling_defensible is False when a control fails.
tests/test_operability_drill.py|function|test_the_drill_does_not_start_anything_by_itself|Ensures the drill module does not contain scheduling-related code.
Route this task to Claude or local Ollama.
tests/test_build.py|class|AssignBuilderTests|Tests assign_builder returns correct builder and frontier flag for various lanes.
tests/test_build.py|class|PlanBuildShapeTests|Tests plan_build wave structure, metadata, and frontier vs local classification.
tests/test_build.py|class|RoundTripTests|Tests to_dict/from_dict and persistence round-trips.
tests/test_build.py|class|SingleSubtaskTests|Tests that a single subtask yields one wave.
tests/test_build.py|class|BookkeeperIsolationTests|Tests that update_architecture flag controls bookkeeper call.
tests/test_artifacts.py|class|LiteralExtraction|Tests for extract_literals across languages and determinism.
tests/test_artifacts.py|function|test_latex_input_and_figures|Guarantees extraction of \input, \includegraphics, \bibliography with correct relations.
tests/test_artifacts.py|function|test_python_reader_and_writer_calls_carry_direction|Guarantees Python file reads and writes are tagged 'reads' and 'writes'.
tests/test_artifacts.py|function|test_cpp_root_calls|Guarantees C++ TFile::Open and new TFile produce 'reads' and 'writes' relations.
tests/test_artifacts.py|function|test_a_language_with_no_rules_yields_nothing_rather_than_guessing|Guarantees unknown language returns empty list, not guess.
tests/test_artifacts.py|function|test_extraction_is_deterministic|Guarantees same input produces identical output.
tests/test_artifacts.py|class|RefuseToGuess|Tests for resolve_literals: unresolved, ambiguous, resolved, external, provenance.
tests/test_artifacts.py|function|test_an_unresolved_literal_is_counted_never_bound_to_a_near_match|Guarantees unresolved literals produce no edges and are counted.
tests/test_artifacts.py|function|test_an_ambiguous_literal_produces_no_edge_and_is_counted|Guarantees ambiguous literals produce no edge and list candidates.
tests/test_artifacts.py|function|test_a_single_extension_candidate_resolves|Guarantees single candidate resolves to an edge.
tests/test_artifacts.py|function|test_an_off_tree_url_is_an_attribute_not_an_edge|Guarantees external URLs are not resolved as edges.
tests/test_artifacts.py|function|test_edges_carry_their_provenance|Guarantees edges have provenance attribute.
tests/test_artifacts.py|class|SchemaReading|Tests for read_schema: CSV, JSON, NumPy, unsupported, unreadable, truncated.
tests/test_artifacts.py|function|test_csv_header_becomes_columns|Guarantees CSV header becomes column names.
tests/test_artifacts.py|function|test_json_object_keys_with_types|Guarantees JSON object keys and types are extracted.
tests/test_artifacts.py|function|test_npy_header_is_parsed_with_stdlib|Guarantees NumPy structured array header parsed.
tests/test_artifacts.py|function|test_an_unsupported_format_is_NOT_an_empty_schema|Guarantees unsupported format returns NOT_SUPPORTED status.
tests/test_artifacts.py|function|test_an_unreadable_file_is_unreadable_not_clean|Guarantees unreadable file returns UNREADABLE status.
tests/test_artifacts.py|function|test_a_truncated_read_is_flagged_on_the_result|Guarantees truncated read sets truncated flag.
tests/test_artifacts.py|class|TheJoin|Tests for compare_schema: missing fields, refused comparison.
tests/test_artifacts.py|function|test_a_declared_field_missing_from_the_artifact_is_the_finding|Guarantees missing declared fields reported in missing_in_artifact.
tests/test_artifacts.py|function|test_it_refuses_to_compare_against_a_schema_it_never_read|Guarantees unread schema is not comparable.
tests/test_artifacts.py|class|Chain|Tests for chain_from: chain construction and bounding.
tests/test_artifacts.py|function|test_the_paper_to_data_chain_walks_backwards|Guarantees chain includes producers like paper.tex and plot.py.
tests/test_artifacts.py|function|test_the_walk_is_bounded_and_says_when_it_stopped|Guarantees max_hops bound and truncation indicator.
daedalus/ikarus_chat.py|constant|BLUEPRINTS|Defines six role blueprints (network-architect, frontend-studio, api-steward, qa-sentinel, memory-scribe, research-scout) with triggers, ownership, and must_read files.
daedalus/ikarus_chat.py|function|draft|Generates a deterministic agent-network draft from a project name and message by selecting blueprints and producing a team patch and subagent specifications.
daedalus/ikarus_chat.py|function|chat|Applies the draft to Daedalus and Claude Code configuration when apply=True, creating/updating roles, subagent markdown files, and team config.
tests/test_repair_blast_radius_write.py|class|OffloadPostWriteFenceTests|Tests that offload post-write fence escalates undeclared writes reaching fenced modules and accepts island-file writes.
tests/test_repair_blast_radius_write.py|class|CodexLaneFenceTests|Tests that the forced codex lane consults reachability pre-check and does not grant workspace write for declared leaves reaching fenced modules.
tests/test_mission_control.py|class|FakeOllamaResponse|Minimal stand-in for urllib.request.urlopen response.
tests/test_mission_control.py|class|MissionControlContractTest|Provides common setUp for all contract tests, patching external effects.
tests/test_mission_control.py|class|DashboardContractTest|Verifies the contract of get_dashboard: top-level keys and field types.
tests/test_mission_control.py|class|ModelResourcesContractTest|Verifies the contract of model_resources: keys, types, and offline handling.
tests/test_mission_control.py|class|QueueContractTest|Verifies the contract of get_queue: keys and types.
tests/test_mission_control.py|class|SquadsContractTest|Verifies the contract of get_squads: keys, types, and default squads.
tests/test_mission_control.py|class|QualityContractTest|Verifies the contract of get_quality: invariant keys and stale_watchers.
tests/test_mission_control.py|class|RoutingSummaryContractTest|Verifies the contract of routing_summary: keys and local_only default.
daedalus/doctor.py|function|codex_status|Returns dict with presence, version, logged_in, refused for Codex CLI; handles BudgetRefused separately.
daedalus/doctor.py|function|check|Returns dict summarizing readiness: claude_cli, codex_cli, ollama_up, host, model desired/present, deepseek_key, can_offload_local.
daedalus/doctor.py|function|main|Prints human-readable doctor report with color-coded statuses and watcher heartbeat info.
daedalus/structcore/__main__.py|function|print_summary|prints a formatted structural summary to stdout
daedalus/structcore/__main__.py|function|main|parses CLI args, builds index, optionally writes JSON, prints summary, returns 0
daedalus/status.py|module|daedalus.status|Provides CLI for subsystem health assessment
daedalus/status.py|constant|ROOT|Resolved path to the repository root
daedalus/status.py|function|collect_status|Collects six counters (repo_root, git_branch, git_status, outbox_count, inbox_count, memory_events, open_todos, todo_snapshot)
daedalus/status.py|function|print_counters|Prints the old counter output with disclaimers
daedalus/status.py|function|main|Entry point for CLI, parses args, calls health.assess, handles exit codes
tests/test_promotion_forgery.py|class|UnreadableRevisionMustRefuseTests|ensures gate_discrimination refuses when git revision is unreadable
tests/test_promotion_forgery.py|class|ImpossibleCountsMustRefuseTests|ensures gate_discrimination rejects internally inconsistent kill rates
tests/test_offload_write_failclose.py|class|WritableFailCloseTests|Tests write grant fail-close when provider lacks rollback and rollback-capable providers keep writable=True.
tests/test_offload_write_failclose.py|class|SnapshotSkipTests|Tests that .daedalus_worktrees is excluded from repo snapshot.
tests/test_budget_is_installed.py|function|test_the_cli_entry_point_installs_the_guard|Ensures CLI main() calls install_process_guard.
tests/test_budget_is_installed.py|function|test_the_guard_is_installed_BEFORE_any_subcommand_dispatch|Ensures guard installs before dispatch chain.
tests/test_budget_is_installed.py|function|test_installing_it_does_NOT_break_an_ordinary_subprocess|Ensures guard does not break normal subprocess calls.
tests/test_budget_is_installed.py|function|test_things_can_still_SUBCLASS_Popen_while_the_guard_is_installed|Ensures guard allows subclassing Popen and asyncio import works.
tests/test_budget_is_installed.py|function|test_the_guard_is_idempotent_and_reversible|Ensures double install is idempotent and uninstall restores original.
tests/test_budget_is_installed.py|function|test_a_vendor_spawn_IS_intercepted_when_installed|Ensures vendor spawns are intercepted when guard is installed.
tests/test_honest_denominator.py|module|tests.test_honest_denominator|Module providing tests for honest denominator token exactness.
tests/test_honest_denominator.py|constant|MOD|Template for test module files with prose-heavy docstring.
tests/test_honest_denominator.py|constant|MAIN|Template for main file importing modules.
tests/test_honest_denominator.py|class|HonestDenominatorTest|Test case containing tests for index total_tokens, slice denominator, cache round-trip, legacy fallback, and staleness.
tests/test_kairos_archive.py|class|TestOutcomeVocabulary|Tests outcome vocabulary matches evaluator and unknown outcome sorting
tests/test_kairos_archive.py|class|TestRoundTrip|Tests attempt persistence, truncation, torn lines, missing files, and no code field
tests/test_kairos_archive.py|class|TestDigest|Tests digest consistency
tests/test_kairos_archive.py|class|TestSampling|Tests sampling ordering, dedup, exclusion, diversity, determinism, and no provider imports
tests/test_kairos_archive.py|class|TestEvaluatorInterpreter|Tests evaluator spawns qualified pytest and has timeout
tests/test_bridge_enqueue_guard.py|class|EnqueueRefusesWithoutAConsumer|Tests that enqueue refuses when watcher is not running (stale, none), does not leave files, includes remedy message, passes for alive/busy, warns for wedged, and force-queue works.
tests/test_bridge_enqueue_guard.py|class|TheRealHeartbeatStillClassifiesTheRealIncident|Tests that the real heartbeat classification correctly identifies the stale condition from the 2026 incident.
tests/test_rewrite.py|constant|ORIGINAL|Provides a sample original source string for tests.
tests/test_rewrite.py|constant|EDITED|Provides a sample edited source string for tests.
tests/test_rewrite.py|class|RewriteApplyTests|Tests application of rewrite including no-ops, truncation, elision, protected paths, escape, and rollback.
tests/test_rewrite.py|class|RunRoutingTests|Tests routing between rewrite and agentic loop based on writable flag.
tests/test_deepseek_substitution_guard.py|constant|MODULE|A sample module string used as original content in substitution tests.
tests/test_deepseek_substitution_guard.py|constant|TEST_MODULE_FOR_IT|A sample test module string used as substituted content in substitution tests.
tests/test_deepseek_substitution_guard.py|class|TheMeasuredFailure|Tests that the specific measured failure (module replaced by its test module) is caught and named.
tests/test_deepseek_substitution_guard.py|class|OrdinaryEditsSurvive|Tests that ordinary edits (adding, renaming, rewriting) are not rejected as substitutions.
tests/test_deepseek_substitution_guard.py|class|RefusesToJudgeWhatItCannotRead|Tests that non-Python files or unparseable originals are not judged, and unparseable rewrites are refused.
tests/test_deepseek_substitution_guard.py|class|ToplevelOnly|Tests that only top-level definitions are considered for substitution detection.
tests/test_agent_env.py|class|DaedalusTests|Guarantees correct behavior of daedalus components via unit tests.
tests/test_agent_env.py|function|test_routes_gui_paths_to_ui_agent|Guarantees route_task returns ui-ux-dev agent for gui paths.
tests/test_agent_env.py|function|test_routes_driver_paths_to_hardware_agent|Guarantees route_task returns hardware-dev agent for device paths.
tests/test_agent_env.py|function|test_active_agents_filter_routes_within_enabled_team|Guarantees route_task falls back to active agent when original not in team.
tests/test_agent_env.py|function|test_no_active_agents_raises|Guarantees route_task raises RuntimeError if no active agents match.
tests/test_agent_env.py|function|test_validates_report_schema|Guarantees validate_report passes on valid report.
tests/test_agent_env.py|function|test_rejects_chatty_report|Guarantees validate_report rejects report with long summary.
tests/test_agent_env.py|function|test_rejects_empty_summary|Guarantees validate_report returns error for empty summary.
tests/test_agent_env.py|function|test_extracts_result_wrapped_json|Guarantees _extract_json extracts status from wrapped JSON.
tests/test_agent_env.py|function|test_prompt_contains_pruned_context|Guarantees build_prompt includes STATIC_PROMPT_PREFIX and mentions limited history.
tests/test_agent_env.py|function|test_converts_claude_limit_to_blocked_report|Guarantees _blocked_report_from_wrapper returns blocked report with fallback for 429.
tests/test_agent_env.py|function|test_request_uses_default_repo_root|Guarantees _read_request uses provided repo_root and sets default paths.
tests/test_agent_env.py|function|test_memory_event_record_shape|Guarantees MemoryEvent.to_record returns dict with correct keys.
tests/test_agent_env.py|function|test_project_profile_resolves_repo_root|Guarantees load_project returns repo_root for known project.
tests/test_agent_env.py|function|test_project_registry_lists_projects|Guarantees list_projects contains known project.
tests/test_agent_env.py|function|test_ikarus_loads_project_team_controls|Guarantees KairosScheduler loads max_workers and active_agents from project config.
tests/test_agent_env.py|function|test_done_events_close_matching_todos|Guarantees _count_open_todos correctly counts open todos ignoring case.
tests/test_agent_env.py|function|test_infers_existing_paths|Guarantees _infer_paths returns paths matching file in user input.
tests/test_agent_env.py|function|test_fallback_allows_codex_when_claude_blocked|Guarantees fallback_decision returns continue with codex_solo for normal risk.
tests/test_agent_env.py|function|test_fallback_can_block_when_user_requires_claude|Guarantees fallback_decision returns continue false when user requires claude.
tests/test_agent_env.py|function|test_token_policy_trims_paths_and_text|Guarantees trim_paths deduplicates and trim_text truncates with ellipsis.
tests/test_agent_env.py|function|test_usage_summary_detects_rate_limit|Guarantees should_checkpoint triggers on rate limit error.
tests/test_agent_env.py|function|test_usage_summary_detects_large_context|Guarantees should_checkpoint triggers on large cache_read_input_tokens.
tests/test_agent_env.py|function|test_checkpoint_status_has_stable_trigger_key|Guarantees checkpoint_if_needed returns status with trigger_key.
tests/test_fence_anchoring.py|constant|CODER|A dictionary representing a coder agent configuration.
tests/test_fence_anchoring.py|constant|AVAIL|A dictionary representing availability of providers.
tests/test_fence_anchoring.py|constant|OBJECTIVE|A string objective used in tests.
tests/test_fence_anchoring.py|class|TopLevelFenceAnchoringTests|Regression tests for D1: top-level fenced tree must escalate/block, sibling must not.
tests/test_fence_anchoring.py|class|OffloadSurfacesReachabilityTests|Regression tests for D3: dominance stand-down must be visible in offload result.
daedalus/structcore/perfile.py|constant|ANALYSIS_VERSION|Version identifier for FileAnalysis schema, incremented when meaning of rows changes.
daedalus/structcore/perfile.py|dataclass|FileAnalysis|Data container for per-file analysis results including metrics, units, imports, type facts.
daedalus/structcore/perfile.py|function|analyze_file|Pure function that analyzes a single file given text and language spec, returns FileAnalysis.

## DEPENDS

DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/parse
DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/tokens
DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/imports
DEPENDS|tests/test_cascade.py|daedalus.metrics
DEPENDS|tests/test_cascade.py|daedalus.semantic_route
DEPENDS|tests/test_cascade.py|daedalus.verifier
DEPENDS|tests/test_cascade.py|daedalus.offload.offload
DEPENDS|tests/test_cascade.py|daedalus.provider_router.route_and_select
DEPENDS|tests/test_cascade.py|daedalus.projects.load_project
DEPENDS|tests/test_cascade.py|daedalus.sensitivity.load_policy
DEPENDS|tests/test_cascade.py|daedalus.sensitivity.path_write_blocked
DEPENDS|daedalus/runtime_registry.py|daedalus.env
DEPENDS|daedalus/runtime_registry.py|daedalus.providers.ollama
DEPENDS|tests/test_categories_integration.py|daedalus.categories
DEPENDS|tests/test_categories_integration.py|daedalus.core
DEPENDS|tests/test_categories_integration.py|daedalus.router
DEPENDS|tests/test_categories_integration.py|daedalus.file_bridge
DEPENDS|daedalus/memory/__main__.py|daedalus.memory
DEPENDS|daedalus/eval/__main__.py|daedalus.eval.harness
DEPENDS|daedalus/eval/__main__.py|daedalus.eval.mint
DEPENDS|daedalus/eval/__main__.py|daedalus.eval.report
DEPENDS|daedalus/eval/__main__.py|daedalus.eval.tasks
DEPENDS|tests/test_index_wiki_layer.py|daedalus.structcore.index
DEPENDS|daedalus/kairos/evolution.py|daedalus.kairos.shadow_shell
DEPENDS|daedalus/hierarchy.py|daedalus/core
DEPENDS|daedalus/hierarchy.py|daedalus/projects
DEPENDS|daedalus/hierarchy.py|daedalus/router
DEPENDS|tests/test_envelope_coverage.py|daedalus.spine.envelope
DEPENDS|tests/test_ollama_rescue_reason.py|daedalus.providers.ollama
DEPENDS|tests/test_ollama_rescue_reason.py|daedalus.providers._openai_compat
DEPENDS|daedalus/projects.py|json
DEPENDS|daedalus/projects.py|pathlib.Path
DEPENDS|daedalus/projects.py|typing.Any
DEPENDS|tests/test_dss.py|daedalus.structcore.dss

## WRITES

WRITES|tests/test_parallel_dispatch.py|temporary directories via tempfile
WRITES|daedalus/dotenv.py|Process environment (os.environ) via load
WRITES|daedalus/runbook.py|runs/ directory (writes JSON run briefs)
WRITES|daedalus/metrics.py|memory/offload_metrics.local.jsonl
WRITES|tests/test_categories.py|.agentenv/categories.json
WRITES|tests/test_context_plan.py|Arbitrary files in tmp_path via _write

## READS

READS|daedalus/status.py|OUTBOX directory
READS|daedalus/status.py|INBOX directory
READS|daedalus/status.py|TODO_PATH
READS|daedalus/status.py|events file via load_events
READS|daedalus/status.py|git repository via _git
READS|tests/test_offload_write_failclose.py|<temporary directory>
READS|tests/test_budget_is_installed.py|daedalus/cli.py
READS|tests/test_kairos_archive.py|daedalus/kairos/evolution.py
READS|tests/test_bridge_enqueue_guard.py|runs/_test_hb_guard.json
READS|tests/test_cascade.py|project files via load_policy(load_project(...))

## CLAIMS

CLAIMS|tests/test_council_livewire.py|test_offline_fakes_need_no_opt_in docstring states replay harness must never need --live.
CLAIMS|tests/test_council_livewire.py|test_injected_runner_counts_as_offline docstring states that a shipped adapter with substituted transport is not live.
CLAIMS|tests/test_council_livewire.py|test_unknown_adapter_shapes_are_assumed_live docstring states fail-closed assumption: unknown subclasses are live.
CLAIMS|tests/test_council_livewire.py|test_rebinding_the_module_default_cannot_disarm_the_gate docstring states shipped-transport set snapshotted at import.
CLAIMS|tests/test_council_livewire.py|test_cli_refuses_a_bare_council_invocation docstring states CLI used to call four vendors, now refuses.
CLAIMS|tests/test_council_livewire.py|test_cli_live_flag_authorises_the_spend docstring states --live must reach convene as live=True.
CLAIMS|tests/test_council_livewire.py|test_cli_dry_run_names_the_seats_live_would_call docstring states plan must state price before --live.
CLAIMS|tests/test_self_policy_confinement.py|The self-policy must CONFINE writes, not merely describe confinement.
CLAIMS|tests/test_self_policy_confinement.py|test_file_entries_do_not_extend_to_descendants: 'REGRESSION, found by Codex in review one hour after shipping.'
CLAIMS|tests/test_self_policy_confinement.py|test_general_source_is_blocked: 'The 8 paths that leaked under the drafted policy...' and 'RED-WHEN-DISABLED RECEIPT, measured by actually disabling...'
CLAIMS|tests/test_structcore_graph.py|'no dangling edges — every edge\'s source/target is a node, even truncated'
CLAIMS|tests/test_structcore_graph.py|'one consistent node namespace — rel paths for EVERY language'
CLAIMS|tests/test_structcore_graph.py|'truncation is honest — truncated flips True and the *_total counts stay accurate, while invariant 1 still holds'
CLAIMS|tests/test_structcore_graph.py|'hotspots == module_heat[:15]; score_modules ranks every module'
CLAIMS|tests/test_churn.py|Module docstring guarantees graceful degradation and churn ranking behavior.
CLAIMS|daedalus/tools/inventory.py|Derived, never hand-maintained — regenerate and it is true by construction
CLAIMS|daedalus/tools/inventory.py|It reads files and returns data
CLAIMS|daedalus/structcore/topology.py|the module docstring states it is an analysis/visualization aid and warns that a low graph cut does not establish write-safety
CLAIMS|daedalus/structcore/topology.py|spectral_partition docstring states it returns an honest two-way visualization cut
CLAIMS|tests/test_evolution_baseline.py|test_the_fitness_function_has_no_caller: evaluate_candidates has no callers in the repository
CLAIMS|tests/test_operability_drill.py|The drill decides whether autonomy is defensible, so the drill needs guards.
CLAIMS|tests/test_operability_drill.py|Three properties: INCOMPLETE IS NOT A PASS, ONE FAIL IS A FAIL, A STALE PROOF IS A MISSING CONTROL.
CLAIMS|tests/test_build.py|BookkeeperIsolationTests: plan_build's persist path must not touch the real architecture artifact unless asked to (regression: the suite used to rewrite docs/architecture.html)
CLAIMS|tests/test_artifacts.py|The data layer's contract: refuse to guess, and never confuse 'we could not look' with 'there is nothing there'.
CLAIMS|daedalus/ikarus_chat.py|The file guarantees deterministic draft generation and application only when explicitly requested.
CLAIMS|tests/test_repair_blast_radius_write.py|Two confirmed CRITICALs closed: offload writable lane and codex lane fence escapes.
CLAIMS|tests/test_mission_control.py|Pin the Mission Control backend contract in daedalus/core.py
CLAIMS|daedalus/doctor.py|all probes are read-only (HTTP GET + PATH lookups); nothing is started or installed.
CLAIMS|daedalus/doctor.py|codex_status probes are cheap and non-interactive, never triggering a login flow or model call.
CLAIMS|daedalus/structcore/__main__.py|Prints a derived, multi-language structural summary for distillation targeting.
CLAIMS|daedalus/status.py|This file used to print six numbers and a git diff... The answer is :mod:`daedalus.health`, which reports each subsystem as one of five things -- working, present, degraded, absent, unknown -- and can never render the last two as a pass.
CLAIMS|daedalus/status.py|EXIT CODES, and the one exception... The human path exits 0 only when every subsystem was exercised and held; 1 when something is degraded or missing; 2 when nothing that ran is broken but not everything ran. --json always exits 0, because the VS Code extension shells out with execFile and treats a non-zero exit as a crashed command.

## UNWIRED

UNWIRED|tests/test_preservation_fixtures.py|AFTER_LEGIT
UNWIRED|daedalus/wiki/links.py|backlinks
UNWIRED|daedalus/wiki/links.py|unlinked_mentions
UNWIRED|daedalus/wiki/links.py|local_graph
UNWIRED|daedalus/bookkeeper.py|main
UNWIRED|daedalus/structcore/topology.py|spectral_partition (no callers visible in this slice)
UNWIRED|daedalus/kairos/evolution.py|EvolutionaryOrchestrator
UNWIRED|daedalus/dotenv.py|load function is defined but not called within this file

## SMELL

SMELL|tests/test_bridge_enqueue_guard.py|Modifies sys.path, which may affect other tests if run in same process.
SMELL|tests/test_agent_env.py|Depends on private APIs (e.g., _blocked_report_from_wrapper, _read_request, _infer_paths, _count_open_todos) increasing brittleness.
SMELL|tests/test_cascade.py|duplicate setUp/tearDown logic for metrics.LOG in MetricsTests, OffloadRoutingTests, and OffloadFailClosedTests
SMELL|daedalus/runtime_registry.py|_run_version contains logic duplicated from providers/codex_cli.py and doctor.py (comment acknowledges).
SMELL|daedalus/kairos/evolution.py|Redundant assignment: 'best = valid[0]' immediately followed by 'return valid[0]'