# Census shard 18/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/structcore/perfile.py|function|analyze_chunk|Worker entry point for batch analysis of files, tags results with original index for order restoration.
tests/test_cascade.py|class|VerifierTests|Tests for daedalus.verifier.verify schema and syntax checks
tests/test_cascade.py|class|MetricsTests|Tests for daedalus.metrics record and summary functions
tests/test_cascade.py|class|OffloadRoutingTests|Tests for daedalus.offload.offload and route_and_select routing logic
tests/test_cascade.py|class|SemanticFallbackTests|Tests for daedalus.semantic_route.semantic_route fallback behavior
tests/test_cascade.py|class|WriteGuardTests|Regression tests for write guard policy based on Mary's findings
tests/test_cascade.py|class|OffloadFailClosedTests|Tests that live writes without policy are refused (fail-closed)
Route this task to Claude or local Ollama.
daedalus/runtime_registry.py|module|runtime_registry|Provides a runtime registry with specifications for CLI and API runtimes, functions to check status of individual runtimes
daedalus/runtime_registry.py|class|RuntimeSpec|Data class defining a runtime's id, label, mode, command, env_key, local, trusted_with_ip, can_write, agentic, and notes.
daedalus/runtime_registry.py|constant|RUNTIMES|Tuple of RuntimeSpec instances for six predefined runtimes.
daedalus/runtime_registry.py|function|runtime_status|Given a runtime_id, returns a dict with runtime spec fields plus available, auth_status, command_path, version, models, selected_model, model_present, last_error.
daedalus/runtime_registry.py|function|all_status|Returns a dict with 'runtimes' key containing list of status dicts for all runtimes.
daedalus/runtime_registry.py|function|test_runtime|Given a runtime_id, returns a dict with runtime, ok, mode, detail.
Route this task to Claude or local Ollama.
tests/test_categories_integration.py|class|DashboardCarriesCategoriesTest|Tests that dashboard carries categories joined with agents and matches direct get_categories
tests/test_categories_integration.py|function|DashboardCarriesCategoriesTest.setUp|Sets up mocks for list_projects, _process_rows, and urlopen
tests/test_categories_integration.py|function|DashboardCarriesCategoriesTest.test_dashboard_includes_categories_joined_with_agents|Ensures dashboard includes categories with agents and count
tests/test_categories_integration.py|function|DashboardCarriesCategoriesTest.test_dashboard_categories_match_get_categories_directly|Ensures dashboard categories match direct get_categories
tests/test_categories_integration.py|class|CategoryOverrideRoundTripTest|Tests per-repo override round-trip for a category
tests/test_categories_integration.py|function|CategoryOverrideRoundTripTest.setUp|Creates temporary directory
tests/test_categories_integration.py|function|CategoryOverrideRoundTripTest.test_update_writes_per_repo_override_and_does_not_leak_into_global|Ensures override writes to .agentenv/categories.json and global unchanged
tests/test_categories_integration.py|class|QueueTaskCategoryStampTest|Tests queue_task stamps category from routed agent without altering lane
tests/test_categories_integration.py|function|QueueTaskCategoryStampTest.setUp|Mocks resolve_repo_root and route_task
tests/test_categories_integration.py|function|QueueTaskCategoryStampTest.test_queue_task_stamps_category_without_altering_requested_lane|Ensures category is stamped and lane unchanged
tests/test_categories_integration.py|function|QueueTaskCategoryStampTest.test_queue_task_falls_back_to_empty_category_when_routing_fails|Ensures empty category fallback on routing failure
Route this task to Claude or local Ollama.
daedalus/eval/__main__.py|function|main|Processes command-line arguments and runs the appropriate evaluation or maintenance task, returning exit code 0 on success or 1 on error.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
tests/test_index_wiki_layer.py|class|TheGate|Ensures wiki layer is off by default and only activated when explicitly requested with documents.
tests/test_index_wiki_layer.py|function|test_it_is_off_by_default|Asserts wiki_enabled() returns False by default.
tests/test_index_wiki_layer.py|function|test_an_explicit_argument_wins_over_the_environment|Asserts wiki_enabled(True) returns True and wiki_enabled(False) returns False.
tests/test_index_wiki_layer.py|function|test_no_wiki_block_appears_unless_asked_for|Asserts no wiki keys in index when wiki=False.
tests/test_index_wiki_layer.py|function|test_the_layer_needs_documents_indexed|Asserts wiki key not in index when documents=False.
tests/test_index_wiki_layer.py|class|ItIsAdditive|Ensures wiki layer does not modify existing edge sets and adds separate wiki-specific keys.
tests/test_index_wiki_layer.py|function|test_document_links_are_byte_identical_with_the_gate_on|Asserts document_links unchanged with wiki=True.
tests/test_index_wiki_layer.py|function|test_the_scope_key_distinguishes_the_two_builds|Asserts scope_key ends with '+wiki' when wiki=True.
tests/test_index_wiki_layer.py|function|test_code_modules_and_import_edges_do_not_move|Asserts import_edges and modules unchanged.
tests/test_index_wiki_layer.py|class|RelationsStayApart|Ensures each type of wiki link is stored in its own relation and totals are reported.
tests/test_index_wiki_layer.py|function|test_a_doc_to_doc_edge_is_resolved|Asserts b.md is in wiki_links for a.md.
tests/test_index_wiki_layer.py|function|test_a_doc_to_code_edge_is_its_own_relation|Asserts m.py in wiki_code_links not in wiki_links.
tests/test_index_wiki_layer.py|function|test_a_type_reference_is_carried_as_an_unresolved_NAME|Asserts 'Foo' in wiki_type_refs and deferred count.
tests/test_index_wiki_layer.py|function|test_the_totals_are_reported_including_the_refusals|Asserts all expected keys in wiki dict.
tests/test_index_wiki_layer.py|class|RefuseToGuess|Ensures the wiki layer does not fabricate edges for missing or ambiguous links.
tests/test_index_wiki_layer.py|function|test_a_link_to_nothing_is_counted_not_invented|Asserts no wiki_links for unresolvable link and unresolved count >0.
tests/test_index_wiki_layer.py|function|test_an_ambiguous_bare_name_produces_no_edge|Asserts no wiki_links for ambiguous name and ambiguous count >0.
tests/test_index_wiki_layer.py|class|Determinism|Ensures wiki layer produces deterministic results.
tests/test_index_wiki_layer.py|function|test_two_builds_agree|Asserts wiki keys identical between two builds.
Route this task to Claude or local Ollama.
daedalus/kairos/evolution.py|constant|DEFAULT_EVAL_TIMEOUT_S|Wall-clock ceiling for one candidate's test run.
daedalus/kairos/evolution.py|class|EvolutionaryOrchestrator|Generates, evaluates, and selects candidates for code evolution.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
daedalus/hierarchy.py|constant|CAPABILITIES|Defines the static list of capabilities with their metadata.
daedalus/hierarchy.py|function|capabilities|Returns an envelope with the capability list.
daedalus/hierarchy.py|function|hierarchy|Builds and returns the full hierarchy graph for a project.
daedalus/hierarchy.py|function|save_team|Saves team configuration changes for a project.
Route this task to Claude or local Ollama.
tests/test_envelope_coverage.py|function|record_producers|Returns a set of module paths that serialize a structured record into run state, used as the source of truth for the drift detector.
tests/test_envelope_coverage.py|function|test_the_scan_finds_the_producers_that_were_actually_converted|Ensures the scan heuristic still detects the three known converted producers, otherwise calibration is broken.
tests/test_envelope_coverage.py|function|test_no_new_record_producer_has_appeared_undeclared|Asserts no new record producer appears that is not in the declared ledger.
tests/test_envelope_coverage.py|function|test_the_producer_ledger_has_not_rotted|Asserts that every file named in the ledger still exists on disk.
tests/test_envelope_coverage.py|function|test_a_module_is_not_declared_both_converted_and_unconverted|Asserts no overlap between converted and unconverted producer sets.
tests/test_envelope_coverage.py|function|test_every_converted_producer_says_where_the_trace_lives|Asserts every converted producer's note includes the TRACE_KEY.
tests/test_envelope_coverage.py|function|test_every_unconverted_producer_states_a_cost_or_a_reason|Asserts every unconverted producer's note is substantive and includes a cost or reason keyword.
tests/test_envelope_coverage.py|function|test_the_three_converted_producers_are_the_declared_three|Asserts the three converted producers match the docstring claim.
tests/test_ollama_rescue_reason.py|class|RescueOutcomeTest|Tests for _schema_rescue returning distinguishable outcomes.
tests/test_ollama_rescue_reason.py|class|LoudFailureInTheLoopTest|Tests that rescue failures block agent turns instead of being reported as success.
daedalus/projects.py|constant|ROOT|Root directory of the daedalus project (parent of daedalus/).
daedalus/projects.py|constant|PROJECT_DIR|Directory where project JSON files are stored (ROOT/projects).
daedalus/projects.py|function|list_projects|Returns sorted list of project names from .json files in PROJECT_DIR.
daedalus/projects.py|function|load_project|Loads a project by name from PROJECT_DIR, validates repo_root.
daedalus/projects.py|function|resolve_repo_root|Resolves repo_root from either explicit argument or project name.
tests/test_dss.py|function|test_hierarchy_restriction_and_bounded_prolongation_are_deterministic|Tests that hierarchy restriction and bounded prolongation are deterministic.
tests/test_dss.py|function|test_temporal_carry_uses_exact_ids_and_explicit_rename_confidence|Tests that temporal carry uses exact IDs and rename confidence.
tests/test_dss.py|function|test_relation_diffusion_keeps_import_cochange_and_clone_channels_separate|Tests that relation diffusion keeps import, co-change, and clone channels separate.
tests/test_dss.py|function|test_end_to_end_plan_is_budgeted_ranked_and_content_addressed|Tests that end-to-end plan is budgeted, ranked, and content-addressed.
tests/test_dss.py|function|test_receipt_changes_when_seed_or_budget_changes|Tests that receipt changes when seed or budget changes.
tests/test_dss.py|function|test_invalid_paths_and_scores_fail_closed|Tests that invalid paths and scores fail closed.
daedalus/spine/__init__.py|module|daedalus.spine|Mission Spine light package.
daedalus/spine/__init__.py|constant|__all__|List of public names re-exported from .ledger.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
daedalus/structcore/report.py|function|structure_summary|Trims a full build_index result into a compact API payload for the cockpit Structure sheet.
daedalus/mapping/__init__.py|constant|CLASSES|Re-exports CLASSES from daedalus.mapping.reach
daedalus/mapping/__init__.py|constant|ENTRY_KINDS|Re-exports ENTRY_KINDS from daedalus.mapping.reach
daedalus/mapping/__init__.py|constant|SCHEMA|Re-exports SCHEMA from daedalus.mapping.reach
daedalus/mapping/__init__.py|class|EntryPoint|Re-exports EntryPoint from daedalus.mapping.reach
daedalus/mapping/__init__.py|class|ModuleFacts|Re-exports ModuleFacts from daedalus.mapping.reach
daedalus/mapping/__init__.py|class|ReachReport|Re-exports ReachReport from daedalus.mapping.reach
daedalus/mapping/__init__.py|function|analyse|Re-exports analyse from daedalus.mapping.reach
daedalus/kairos/drafts.py|function|save_draft|Persists an advisory report to the drafts store with safety checks.
daedalus/kairos/drafts.py|function|list_drafts|Returns newest-first summaries of stored drafts.
daedalus/kairos/drafts.py|function|get_draft|Fetches a single draft by id, subject to path safety.
daedalus/kairos/drafts.py|function|delete_draft|Deletes a draft file if id is safe.
daedalus/kairos/drafts.py|function|set_status|Transitions a draft's lifecycle status.
daedalus/kairos/drafts.py|function|apply_payload|Returns a review packet for human/Claude apply and marks draft applied.
daedalus/tools/__init__.py|constant|CLEAR|Verdict indicating no issues.
daedalus/tools/__init__.py|constant|REVIEW|Verdict indicating needs review.
daedalus/tools/__init__.py|constant|BLOCK|Verdict indicating blocked.
daedalus/tools/__init__.py|constant|UNSCANNABLE|Verdict indicating unscannable.
daedalus/tools/__init__.py|constant|VET_VERSION|Version of the vet module.
daedalus/tools/__init__.py|class|Finding|Represents a single inspection finding.
daedalus/tools/__init__.py|class|Verdict|Represents the overall verdict of an inspection.
daedalus/tools/__init__.py|function|vet_skill|Scans a skill for safety concerns.
daedalus/tools/__init__.py|function|vet_mcp_server|Scans an MCP server for safety concerns.
daedalus/tools/__init__.py|function|scan_text|Scans arbitrary text for safety.
daedalus/tools/__init__.py|function|summarise|Summarizes findings into a verdict.
daedalus/tools/__init__.py|constant|INVENTORY_VERSION|Version of the inventory module.
daedalus/tools/__init__.py|class|ToolRecord|Represents a record in the tool inventory.
daedalus/tools/__init__.py|function|build|Builds the inventory from a project.
daedalus/tools/__init__.py|function|render|Renders the inventory as a string.
Route this task to Claude or local Ollama.
Route this task to Claude or local Ollama.
daedalus/adapters/__init__.py|class|AgentAdapter|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|AgentCapabilities|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|SessionEnded|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|TransportRecord|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|function|event_to_transport_record|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|TransportSink|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|CompositeTransportSink|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|InMemoryTransportSink|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|JsonlTransportSink|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|SubprocessAdapter|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|class|RuntimeConfig|Part of the universal CLI agent runtime interface.
daedalus/adapters/__init__.py|constant|RUNTIME_PROFILES|Part of the universal CLI agent runtime interface.
tests/test_system_check.py|constant|TOOLS|The parent directory of tools/ used to import system_check and self_test.
tests/test_system_check.py|function|test_all_pass_is_the_only_zero|Ensures all PASS results yield EXIT_OK.
tests/test_system_check.py|function|test_any_failure_is_one|Ensures any FAIL yields EXIT_FAILED.
tests/test_system_check.py|function|test_unavailable_on_a_CORE_check_is_incomplete_not_success|Ensures core UNAVAILABLE yields EXIT_INCOMPLETE.
tests/test_system_check.py|function|test_unavailable_on_an_OPTIONAL_check_does_not_block|Ensures optional UNAVAILABLE yields EXIT_OK.
tests/test_system_check.py|function|test_failure_outranks_incomplete|Ensures FAIL outranks UNAVAILABLE.
tests/test_system_check.py|function|test_the_three_outcomes_are_distinct|Ensures PASS, FAIL, UNAVAILABLE and EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE are distinct.
tests/test_system_check.py|function|test_every_check_declares_what_it_proves|Ensures all CHECKS have a non-empty 'proves' field.
tests/test_system_check.py|function|test_every_check_declares_a_stage_and_core_flag|Ensures all CHECKS have stage and core flag.
tests/test_system_check.py|function|test_check_names_are_unique|Ensures no duplicate check names.
tests/test_system_check.py|function|test_the_spine_and_safety_properties_are_all_covered|Ensures required checks are present.
tests/test_system_check.py|function|test_a_check_that_raises_is_a_FAIL_not_a_skip|Ensures a crashing check yields FAIL.
tests/test_system_check.py|function|test_the_self_test_exists_and_seeds_defects_for_the_sharpest_checks|Ensures self_test has mutations for required checks.
tests/test_system_check.py|function|test_every_seeded_defect_names_a_real_check|Ensures self_test mutations point to existing checks.
tests/test_system_check.py|function|test_the_self_test_is_offered_by_the_cli|Ensures --self-test flag appears in source.
daedalus/orchestrate.py|function|prepare_task|Re-exports prepare_task from daedalus.kairos.orchestrate for compatibility.
daedalus/claude_bridge.py|module|daedalus.claude_bridge|Provides functions to prompt Claude and parse structured reports.
daedalus/claude_bridge.py|constant|ROOT|Resolved parent directory of this file (Path).
daedalus/claude_bridge.py|constant|RUN_DIR|Directory for runs (Path to runs/ under ROOT).
daedalus/claude_bridge.py|constant|REPORT_SCHEMA|JSON schema for validating Claude reports.
daedalus/claude_bridge.py|function|build_prompt|Constructs a prompt string for Claude given objective, repo_root, paths, and agent dict.

## DEPENDS

DEPENDS|tests/test_dss.py|daedalus.structcore.forest
DEPENDS|daedalus/spine/__init__.py|daedalus.spine.ledger
DEPENDS|daedalus/mapping/__init__.py|daedalus.mapping.reach
DEPENDS|daedalus/tools/__init__.py|daedalus.tools.vet
DEPENDS|daedalus/tools/__init__.py|daedalus.tools.inventory
DEPENDS|daedalus/adapters/__init__.py|daedalus.adapters.base
DEPENDS|daedalus/adapters/__init__.py|daedalus.adapters.events
DEPENDS|daedalus/adapters/__init__.py|daedalus.adapters.subprocess_adapter
DEPENDS|daedalus/adapters/__init__.py|daedalus.adapters.transport
DEPENDS|tests/test_system_check.py|tools.system_check
DEPENDS|tests/test_system_check.py|tools.self_test
DEPENDS|daedalus/orchestrate.py|daedalus.kairos.orchestrate
DEPENDS|daedalus/claude_bridge.py|daedalus.fallback
DEPENDS|daedalus/claude_bridge.py|daedalus.router
DEPENDS|daedalus/claude_bridge.py|daedalus.schemas
DEPENDS|daedalus/claude_bridge.py|daedalus.token_policy
DEPENDS|daedalus/claude_bridge.py|daedalus.budget
DEPENDS|daedalus/drafts.py|daedalus.kairos.drafts
DEPENDS|tests/test_parallel_dispatch.py|daedalus.kairos.scheduler
DEPENDS|tests/test_parallel_dispatch.py|daedalus.metrics
DEPENDS|tests/test_parallel_dispatch.py|daedalus.offload
DEPENDS|tests/test_registry_shadowing.py|daedalus.config
DEPENDS|tests/test_registry_shadowing.py|daedalus.sensitivity
DEPENDS|daedalus/eval/__init__.py|daedalus.eval.tasks
DEPENDS|daedalus/eval/__init__.py|daedalus.eval.harness
DEPENDS|daedalus/__init__.py|daedalus/router
DEPENDS|daedalus/__init__.py|daedalus/schemas
DEPENDS|tests/test_fenrir_slice_attack.py|daedalus.structcore.index
DEPENDS|tests/test_fenrir_slice_attack.py|daedalus.structcore.slice
DEPENDS|daedalus/adapters/base.py|daedalus.adapters.events
DEPENDS|tests/test_clones_string_literals.py|daedalus.structcore.clones
DEPENDS|tests/test_clones_string_literals.py|daedalus.structcore.languages
DEPENDS|daedalus/runbook.py|daedalus.router
DEPENDS|daedalus/runbook.py|daedalus.schemas

## WRITES

WRITES|daedalus/kairos/shadow_shell.py|worktree via GitWorktreeManager
WRITES|daedalus/enforce.py|AGENTS.md
WRITES|daedalus/enforce.py|CLAUDE.md
WRITES|daedalus/enforce.py|.agentenv/enforcement.json
WRITES|tests/test_bookkeeper.py|temporary directory via bk.DOCS

## READS

READS|daedalus/hierarchy.py|daedalus/projects (load_project)
READS|daedalus/hierarchy.py|daedalus/router (load_agents)
READS|tests/test_envelope_coverage.py|daedalus/ and runs/ subdirectories for .py files
READS|daedalus/projects.py|ROOT/projects
READS|daedalus/kairos/drafts.py|runs/drafts/
READS|daedalus/claude_bridge.py|repo_root (via --add-dir)
READS|daedalus/claude_bridge.py|Claude CLI output
READS|tests/test_parallel_dispatch.py|.agentenv directory structure
READS|daedalus/providers/personas.py|personas.json
READS|daedalus/dotenv.py|.env file via load and describe

## CLAIMS

CLAIMS|daedalus/status.py|RELATION TO tools/system_check.py. That harness clones the tree and RUNS the product; it answers 'does the pipeline execute end to end'. This reads the live artefacts in the tree you are standing in.
CLAIMS|tests/test_offload_write_failclose.py|Fail-close the routed write lane on rollback capability (Momus CRITICAL #1)
CLAIMS|tests/test_budget_is_installed.py|"A guard that is not reached is not a guard"
CLAIMS|tests/test_bridge_enqueue_guard.py|These tests fail if that silence ever comes back.
CLAIMS|tests/test_deepseek_substitution_guard.py|the guard catches a rewrite returning the wrong file
CLAIMS|daedalus/structcore/perfile.py|Pure: same inputs -> same outputs, no I/O, no globals.
CLAIMS|daedalus/structcore/perfile.py|Workers must not re-enter the single-flight build lock.
CLAIMS|daedalus/structcore/perfile.py|Unconditional extraction to ensure cache correctness.
CLAIMS|tests/test_cascade.py|WriteGuardTests: regression tests for Mary's findings on the write-guard
CLAIMS|tests/test_cascade.py|OffloadFailClosedTests: Mary #1: a live write with no project policy loaded must be refused
CLAIMS|daedalus/runtime_registry.py|"Daedalus orchestration should depend on runtime capabilities, not on random subprocess calls scattered through the app."
CLAIMS|tests/test_categories_integration.py|The suite is deterministic and hermetic on any box because everything network- or real-file-touching is mocked
CLAIMS|daedalus/eval/__main__.py|--gate is never wired into anything automatic; run it by hand before shipping a slice-heuristic change.
CLAIMS|daedalus/eval/__main__.py|--mint-commit/--confirm-mint are the ONLY entry points that persist a task to the mint store; every other flag only READS it via harness.all_tasks(); there is no automatic caller.
CLAIMS|tests/test_index_wiki_layer.py|These tests pin the wiring AND the three things it must not do: move an existing edge set, appear without being asked for, or publish an unresolved name as if it were an edge.
CLAIMS|daedalus/kairos/evolution.py|This is not autonomous code evolution and it is not a promotion boundary.
CLAIMS|daedalus/kairos/evolution.py|The evaluate_candidates method's docstring claims that -m pytest is load-bearing to ensure candidate's code is tested instead of primary checkout.
CLAIMS|daedalus/hierarchy.py|Hierarchy graph projection for the Agent OS webapp.
CLAIMS|tests/test_envelope_coverage.py|The scan cannot detect SQLite producers or paths built entirely from variables, and the ledger is hand-maintainable.
CLAIMS|tests/test_ollama_rescue_reason.py|_schema_rescue returns a REASON, not a bare empty list
CLAIMS|daedalus/projects.py|load_project raises ValueError if project unknown or missing repo_root
CLAIMS|daedalus/spine/__init__.py|a crash can never leave an effect the system has no record of intending
CLAIMS|daedalus/structcore/report.py|The raw index carries a per-file modules dict and full clone-site lists — far too large to ship to the UI.
CLAIMS|daedalus/mapping/__init__.py|Two halves: mechanical (here) derived on every run from the tree itself, narrative in docs/adrs/*.md
CLAIMS|daedalus/kairos/drafts.py|The free lane produces a PROPOSAL that a write-capable, trusted lane applies later.
CLAIMS|daedalus/adapters/__init__.py|Provides universal interface for CLI agent runtimes with pre-built profiles and custom runtime support.
CLAIMS|tests/test_system_check.py|The exit code is the verdict: 0 means all pass, 1 means failure, 2 means incomplete.
CLAIMS|tests/test_system_check.py|Every check declares what it proves.
CLAIMS|daedalus/orchestrate.py|Compatibility CLI for daedalus.kairos.orchestrate.
CLAIMS|daedalus/drafts.py|Compatibility wrapper for daedalus.kairos.drafts
CLAIMS|tests/test_parallel_dispatch.py|writable tasks run sequentially with whole-repo attribution even when their hints are disjoint
CLAIMS|tests/test_registry_shadowing.py|The tests guarantee that resolve_project does not drop write confinement when a project name is supplied.

## UNWIRED

UNWIRED|daedalus/dotenv.py|describe function is defined but not called within this file
UNWIRED|daedalus/adapters/base.py|AgentAdapter|No concrete subclass or direct usage visible in this slice.
UNWIRED|daedalus/providers/__init__.py|list_providers
UNWIRED|daedalus/bootstrap_prompt.py|claude_bootstrap_prompt
UNWIRED|daedalus/metrics.py|main
UNWIRED|daedalus/kairos/orchestrate.py|prepare_task
UNWIRED|tests/test_ikarus_os.py|ClassifyTest
UNWIRED|tests/test_ikarus_os.py|AskTest

## SMELL

SMELL|daedalus/hierarchy.py|hierarchy function is a god function handling multiple responsibilities (loading, graph construction, health calculation).
SMELL|tests/test_envelope_coverage.py|Duplicates the structure of tests/test_spend_coverage.py.
SMELL|tests/test_system_check.py|Modifies global sc.CHECKS list in test_a_check_that_raises_is_a_FAIL_not_a_skip, side effect on module state.
SMELL|daedalus/providers/claude_cli.py|run method has an unused policy parameter, which may indicate dead branch
SMELL|daedalus/providers/claude_cli.py|available() checks for external binary 'claude', creating an implicit dependency