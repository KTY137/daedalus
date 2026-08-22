# Census shard 14/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_stream_hook.py|function|test_internal_failure_still_exits_zero_and_logs_an_error|Guarantees internal failures exit zero and log error instead of crashing
tests/test_stream_hook.py|function|test_garbage_stdin_exits_zero_and_logs_an_error|Guarantees garbage stdin exits zero and logs error
tests/test_stream_hook.py|function|test_sidecar_failure_is_named_in_the_room_not_hidden|Guarantees sidecar write failure is reported in room text as UNAVAILABLE
tests/test_stream_hook.py|function|test_log_rotates_at_its_cap|Guarantees log rotates at LOG_MAX_BYTES retaining one backup
tests/test_stream_hook.py|function|test_log_records_every_field|Guarantees log entries contain all required tab-separated fields
Route this task to Claude or local Ollama.
daedalus/structcore/cache.py|function|cache_root|Get base directory for on-disk caches, with env override.
daedalus/structcore/cache.py|function|enabled|Check if caching is enabled via environment variable.
daedalus/structcore/cache.py|function|file_key|Content-addressed key for caching, including version and tokenizer identity.
daedalus/structcore/cache.py|class|FileCache|Per-repo sqlite store of FileAnalysis rows, keyed by content.
tests/test_bridge_signals.py|class|UnreadLedgerTests|Tests for unread report ledger, mark_read, note_report_arrival
tests/test_bridge_signals.py|class|BridgeStatusTests|Tests for bridge_status counts and print_status
tests/test_bridge_signals.py|class|HeartbeatTests|Tests for heartbeat write/status, stale, busy, wedged states
tests/test_bridge_signals.py|class|DoctorHeartbeatTests|Tests for doctor heartbeat warnings
tests/test_bridge_signals.py|class|CodexInlineBriefWarningTests|Tests for codex_inline_brief_warning and enqueue warning
tests/test_bridge_signals.py|function|test_two_enqueues_in_the_same_second_do_not_overwrite|Tests two enqueues same second do not overwrite
tests/test_bridge_signals.py|function|test_a_third_collision_also_gets_its_own_name|Tests third collision gets unique name
tests/test_bridge_signals.py|function|test_distinct_objectives_still_get_readable_names|Tests distinct objectives get readable names
tests/test_bridge_signals.py|function|test_PARALLEL_producers_do_not_collide|Tests parallel producers do not collide
tests/test_bridge_signals.py|function|test_a_request_is_published_atomically|Tests atomic publish of request
tests/test_gate_containment_job_caps.py|constant|REPO_ROOT|Path to the repository root for setting PYTHONPATH
tests/test_gate_containment_job_caps.py|constant|pytestmark|Pytest marker to skip tests if platform not supported
tests/test_gate_containment_job_caps.py|function|test_the_process_cap_refuses_a_fork_bomb_without_killing_the_job|Asserts that exceeding ActiveProcessLimit fails spawn with ERROR_NOT_ENOUGH_QUOTA and does not kill the job
tests/test_gate_containment_job_caps.py|function|test_the_memory_cap_refuses_a_commit_larger_than_the_job_allows|Asserts that memory cap prevents committing beyond job memory limit
tests/test_gate_containment_job_caps.py|function|test_the_child_cannot_break_out_of_the_job|Asserts that CREATE_BREAKAWAY_FROM_JOB is refused
tests/test_gate_containment_job_caps.py|function|test_the_caps_can_be_tightened_by_a_caller_and_never_loosened|Asserts that max_processes and max_job_memory_bytes are clamped to module ceilings
tests/test_gate_containment_job_caps.py|function|test_a_job_whose_limits_cannot_be_confirmed_is_refused|Asserts that _create_job raises ContainmentUnavailable when limits are zero
tests/test_gate_containment_job_caps.py|function|test_the_attestation_carries_what_the_kernel_said_not_what_was_asked|Asserts that job limits are read back from kernel, not copied from requested values
tests/test_gate_containment_job_caps.py|function|test_a_refusal_attestation_claims_no_job_limits|Asserts that refusal_attestation returns None job_limits
tests/test_gate_containment_job_caps.py|function|test_the_list_of_things_the_caps_do_not_cover_still_names_the_network|Asserts that C.JOB_LIMITS_DO_NOT_COVER includes 'network' and 'confidentiality'
tests/test_gate_containment_job_caps.py|function|test_a_real_pytest_gate_still_passes_under_the_production_caps|Asserts that a real pytest suite runs successfully under production caps
tests/test_gate_containment_job_caps.py|function|test_the_docref_gate_reaches_a_verdict_as_the_contained_child|Asserts that docref_gate runs and produces a verdict under containment
daedalus/spine/docref_gate.py|constant|EXIT_PASS|codes a successful gate verdict (0)
daedalus/spine/docref_gate.py|constant|EXIT_FAIL|codes a measured failure of the candidate (1)
daedalus/spine/docref_gate.py|constant|EXIT_INCONCLUSIVE|codes that the gate could not reach a verdict (2)
daedalus/spine/docref_gate.py|function|build_parser|constructs an ArgumentParser for the gate CLI
daedalus/spine/docref_gate.py|function|run_gate|executes the gate logic given arguments and returns (exit_code, report_lines); never raises
daedalus/spine/docref_gate.py|function|main|parses CLI args and calls run_gate, prints report, returns exit code
daedalus/ikarus_act.py|module|ikarus_act|Provides the may_act predicate and ActDecision dataclass for capability gating, with vocabularies and helpers.
daedalus/ikarus_act.py|constant|ACT_VERBS|Set of imperative act verbs that widen the allow surface; adding a verb is a safety edit.
daedalus/ikarus_act.py|class|ActDecision|Dataclass holding the capability verdict (allowed, reason, signal, suspected, intent, confirmation_of).
daedalus/ikarus_act.py|function|may_act|Answers whether a message may reach a tool-bearing executor; implements the false-positive budget.
daedalus/ikarus_act.py|function|pending_offer|Extracts the act_offer from the last turn's envelope, returning None if malformed or missing.
daedalus/build.py|constant|FRONTIER_BUILDER|Frontier builder name, default claude
daedalus/build.py|constant|LOCAL_BUILDER|Local builder name, default ollama
daedalus/build.py|constant|LOCAL_LANES|Tuple of local lanes: local, local_only
daedalus/build.py|constant|ROOT|Resolved root path of the repository
daedalus/build.py|constant|RUN_DIR|Runs directory for build snapshots
daedalus/build.py|class|BuildTask|Represents one routed subtask with owner, category, and lifecycle status
daedalus/build.py|class|Wave|Bounded batch of BuildTask objects that may run concurrently
daedalus/build.py|class|BuildSession|Tracks one feature across waves, the unit of coordinated build
daedalus/build.py|function|assign_builder|Maps a category preset lane to builder and frontier flag
daedalus/build.py|function|load_session|Reloads a persisted BuildSession from a JSON snapshot file
daedalus/build.py|function|plan_build|Plans a multi-wave build for a feature, decomposing, routing, and chunking
daedalus/build.py|function|wave_path_conflicts|Diagnostic function to detect overlapping paths within a wave
tests/test_context_plan_latent.py|class|ConstantBackend|Provides a constant embedding vector for deterministic tests.
tests/test_context_plan_latent.py|class|UnreachableBackend|Simulates an unreachable embedding backend.
tests/test_context_plan_latent.py|class|ExplodingBackend|Raises assertion error if latent path is consulted unexpectedly.
tests/test_context_plan_latent.py|function|repo|Creates a temporary repository with two Python files for testing.
tests/test_context_plan_latent.py|function|idx|Builds a knowledge index from the repo fixture.
tests/test_context_plan_latent.py|function|test_latent_off_is_not_consulted_and_says_so|Verifies latent memory not consulted when use_latent=False.
tests/test_context_plan_latent.py|function|test_latent_off_does_not_claim_a_weight_it_never_applied|Ensures latent weight not applied when latent is off.
tests/test_context_plan_latent.py|function|test_latent_on_with_an_answering_backend_is_credited_in_the_receipt|Verifies latent scores credit when backend answers.
tests/test_context_plan_latent.py|function|test_latent_answer_with_no_path_evidence_is_answered_but_empty|Verifies answered-but-empty state is distinct from not asked.
tests/test_context_plan_latent.py|function|test_unreachable_backend_is_named_not_silently_zero|Verifies unreachable backend yields embedder_unavailable status.
tests/test_context_plan_latent.py|function|test_missing_vector_index_reports_not_configured_with_the_path|Verifies not_configured status for missing index file.
tests/test_context_plan_latent.py|function|test_empty_index_reports_index_unavailable|Verifies index_unavailable status for empty index.
tests/test_context_plan_latent.py|function|test_a_broken_index_is_recorded_instead_of_killing_the_plan|Verifies error status for corrupt index and lexical plan survival.
tests/test_context_plan_latent.py|function|test_programmer_error_still_raises|Verifies that invalid arguments raise exceptions.
tests/test_context_plan_latent.py|function|test_empty_latent_side_does_not_dilute_the_lexical_ranking|Verifies lexical ranking unchanged when latent is empty.
tests/test_context_plan_latent.py|function|test_each_latent_state_produces_a_distinct_receipt|Verifies distinct receipt hashes for different latent states.
tests/test_context_plan_latent.py|function|test_receipt_stays_deterministic_and_keeps_the_acceptance_shape|Verifies receipt determinism and JSON shape.
tests/test_spine_attempt_containment.py|constant|ALIAS_SPELLINGS|Provides spellings for Windows path aliases used in tests
tests/test_spine_attempt_containment.py|function|nested|Creates a nested repo structure for testing containment
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_in_a_directory_that_contains_the_checkout|Ensures a mutating git command in a directory containing the checkout raises PrimaryCheckoutWrite and does not stage files
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_in_the_checkout_itself|Ensures mutating git in the checkout itself raises PrimaryCheckoutWrite
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_below_the_checkout|Ensures mutating git in a subdirectory of the checkout raises PrimaryCheckoutWrite
tests/test_spine_attempt_containment.py|function|test_reads_are_still_allowed_against_the_checkout|Ensures non-mutating git commands succeed against the checkout
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_still_allowed_in_a_non_overlapping_directory|Ensures mutating git in a sibling repo not overlapping the checkout works
tests/test_spine_attempt_containment.py|function|test_the_guard_fires_before_the_subprocess|Ensures the guard blocks before subprocess.run is called
tests/test_spine_attempt_containment.py|function|test_a_missing_verb_is_still_rejected_loudly|Ensures missing or non-mutating verb raises ValueError
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_through_a_windows_alias_of_the_checkout|Ensures via various Windows aliases, mutating git is refused
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_in_a_subdirectory_named_through_an_alias|Ensures via alias in subdirectory, mutating git is refused
tests/test_spine_attempt_containment.py|function|test_an_alias_of_an_unrelated_repo_is_not_refused|Ensures alias of unrelated repo is not over-refused
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_when_the_directory_cannot_be_examined|Ensures when cwd cannot be stat, guard fails closed
tests/test_spine_attempt_containment.py|function|test_mutating_git_is_refused_when_the_checkout_cannot_be_examined|Ensures when repo_root cannot be stat, guard fails closed
tests/test_spine_attempt_containment.py|function|test_git_failures_outside_the_checkout_are_still_reported|Ensures unrelated git failures raise GitCommandError
tests/test_spine_attempt_containment.py|function|test_gate_scratch_removal_does_not_follow_a_junction_planted_in_it|Ensures scratch removal does not delete junction target
tests/test_spine_attempt_containment.py|function|test_gate_scratch_removal_is_routed_through_the_guarded_walker|Ensures scratch removal uses _remove_tree_no_follow and reports failures
tests/test_spine_attempt_containment.py|function|test_the_gate_reports_a_scratch_directory_it_could_not_remove|Ensures gate's finally surfaces scratch removal failure without affecting verdict
tests/test_offload_automint.py|class|AutoMintSeamTests|Validates the auto-mint seam invariants: fires on landed writes, never on rolled-back/advisory/dry-run, fail-soft, env-toggle
daedalus/eval/tasks.py|function|resolve_task_repo|Maps a repo label to an absolute repo root, returning the path or raising ValueError.
daedalus/eval/tasks.py|function|is_correctness_task|Returns True if task uses correctness format (fail_to_pass/pass_to_pass keys), preventing false recall scoring.
daedalus/eval/tasks.py|function|task_project_label|Returns a project bucket string for a task, never raises KeyError on missing 'repo'.
daedalus/eval/tasks.py|constant|AGENT_ENV_ROOT|Absolute path to the agent_env repo root (parents[2] of this file).
daedalus/eval/tasks.py|constant|CORRECTNESS_KEYS|Tuple of keys ('fail_to_pass','pass_to_pass') that mark a correctness task.
daedalus/eval/tasks.py|constant|TASKS|List of task dictionaries, each with id, repo, target, must_include, etc. for slice-recall tasks.
daedalus/wiki/vault.py|constant|VAULT_VERSION|Daedalus wiki vault version identifier.
daedalus/wiki/vault.py|constant|PAGE_SUFFIX|Page file suffix ('.md').
daedalus/wiki/vault.py|constant|MAX_PAGES|Maximum number of pages per vault (5000).
daedalus/wiki/vault.py|constant|MAX_PAGE_BYTES|Maximum page file size (2MB).
daedalus/wiki/vault.py|constant|RESERVED_TOP_LEVEL|Reserved top-level directory names (e.g., 'vault').
daedalus/wiki/vault.py|class|VaultPathError|Error raised for rejected vault-relative paths.
daedalus/wiki/vault.py|function|vault_rel|Resolves a vault-relative path safely, returning (path, reason).
daedalus/wiki/vault.py|function|parse_frontmatter|Parses YAML frontmatter from page text, returning (dict, body).
daedalus/wiki/vault.py|function|read_page|Reads one page from a vault, returning (Page, reason).
daedalus/wiki/vault.py|function|discover_pages|Discovers all pages in a vault, returning (pages, refusals).
daedalus/wiki/vault.py|function|discover_vaults|Discovers all vaults (project and optional global) from repo root.
daedalus/wiki/vault.py|function|page_tree|Builds a nested tree from page paths for navigation.
daedalus/wiki/vault.py|class|Vault|Represents a wiki vault with name, root path, and kind.
daedalus/wiki/vault.py|class|Page|Represents a single wiki page with metadata and body.
tests/test_semantic_route_cold_start.py|constant|AVAIL|Indicates availability of LLM providers for tests.
tests/test_semantic_route_cold_start.py|constant|WARM_S|Budget for warm embedding calls (0.25s).
tests/test_semantic_route_cold_start.py|constant|COLD_S|Budget for cold embedding calls (10s).
tests/test_semantic_route_cold_start.py|constant|COLD_LOAD_S|Time for slow first call (1s) to test cold budget.
tests/test_semantic_route_cold_start.py|constant|FOREVER_S|Very long delay (30s) to ensure fallback.
tests/test_semantic_route_cold_start.py|class|SlowOllama|Simulates an Ollama embedding server with configurable delays.
tests/test_semantic_route_cold_start.py|class|ColdStartSurvivesTests|Tests that a slow first embedding does not kill latent routing.
tests/test_semantic_route_cold_start.py|class|DeadlineIsNotADeadHostTests|Tests that timeout errors are reported correctly (not as host unreachable).
tests/test_semantic_route_cold_start.py|class|BudgetEnvironmentTests|Tests that invalid or zero budgets fall back to defaults.
Route this task to Claude or local Ollama.
tests/test_wiki.py|class|VaultPathValidator|Validates vault_rel rejects dangerous path patterns
tests/test_wiki.py|class|Frontmatter|Tests frontmatter parsing from YAML fences
tests/test_wiki.py|class|PageReading|Tests page reading including title precedence, type default, UTF-8 refusal, discover, tree determinism
tests/test_wiki.py|class|WikilinkForms|Tests wikilink extraction for all forms and line numbers
tests/test_wiki.py|class|RefuseToGuess|Tests index building: unresolved links counted, ambiguous titles produce no edge, path link resolves, self-link not edge, type link unresolved, code link staleness
tests/test_wiki.py|class|BacklinksAndMentions|Tests backlinks and unlinked mentions with limits
tests/test_wiki.py|class|LocalGraph|Tests local graph building with depth, max_nodes, determinism
daedalus/structcore/languages.py|class|LanguageSpec|Guarantees language facts for stdlib lexical, tree-sitter, and safety backends.
daedalus/structcore/languages.py|class|DocumentSpec|Guarantees document format facts (hierarchy, unit) for document indexing.
daedalus/structcore/languages.py|constant|SPECS|Guarantees extension-to-LanguageSpec mapping built from _SPECS.
daedalus/structcore/languages.py|constant|DOC_SPECS|Guarantees extension-to-DocumentSpec mapping built from _DOC_SPECS.
daedalus/structcore/languages.py|constant|DOCUMENT_EXTENSIONS|Guarantees set of document extensions from DOC_SPECS.
daedalus/structcore/languages.py|function|spec_for|Guarantees returns LanguageSpec for a path by extension, or None.
daedalus/structcore/languages.py|function|doc_spec_for|Guarantees returns DocumentSpec for a path by extension, or None.
tests/test_shadow_run.py|constant|HEAD|A 40-character hex string used as test HEAD commit.
tests/test_shadow_run.py|function|test_no_receipt_means_unproven_not_fine|Ensures absence of a receipt yields unproven gate.
tests/test_shadow_run.py|function|test_a_receipt_from_another_revision_does_not_count|Ensures a receipt from a different revision does not prove the gate.
tests/test_shadow_run.py|function|test_a_surviving_CRITICAL_class_beats_a_perfect_looking_score|Ensures a critical defect class surviving makes gate unproven despite high kill rate.
tests/test_shadow_run.py|function|test_a_low_kill_rate_is_unproven_even_with_no_critical_survivors|Ensures low kill rate makes gate unproven even without critical survivors.
tests/test_shadow_run.py|function|test_a_corrupt_receipt_is_unproven_not_a_crash|Ensures corrupt receipt yields unproven without crash.
tests/test_shadow_run.py|function|test_a_GOOD_receipt_does_prove_it|Ensures a valid receipt proves the gate.
tests/test_shadow_run.py|function|test_promotion_is_refused_while_discrimination_is_unproven|Ensures promotion is false when discrimination is unproven.
tests/test_shadow_run.py|function|test_there_is_NO_flag_that_allows_promotion_anyway|Ensures no bypass flag allows promotion regardless of discrimination.
tests/test_shadow_run.py|function|test_the_verdict_never_calls_a_green_gate_good|Ensures verdict does not call a green gate good.
tests/test_shadow_run.py|function|test_a_proven_gate_still_does_not_promote_by_itself|Ensures a proven gate still requires human act.
tests/test_shadow_run.py|function|test_a_generator_that_exits_0_without_stamping_is_NOT_success|Ensures exit 0 without stamping is not success.
tests/test_shadow_run.py|function|test_a_generator_that_DOES_stamp_counts_as_success|Ensures a generator that stamps counts as success.
tests/test_shadow_run.py|function|test_a_generator_that_raises_is_reported_not_swallowed|Ensures a generator that raises is reported as failure.
tests/test_shadow_run.py|function|test_no_work_and_could_not_look_are_different_states|Ensures 'no_candidate' and 'sources_unavailable' are distinct states.
tests/test_shadow_run.py|function|test_a_runner_is_required_and_has_no_implicit_default|Ensures runner is required and has no default.

## DEPENDS

DEPENDS|tests/test_era1_robustness.py|daedalus.providers
DEPENDS|tests/test_era1_robustness.py|daedalus.providers.ollama
DEPENDS|daedalus/selftest.py|daedalus.doctor
DEPENDS|daedalus/selftest.py|daedalus.offload
DEPENDS|daedalus/selftest.py|daedalus.kairos.worktree
DEPENDS|tests/test_spine_cancel.py|daedalus.spine.cancel
DEPENDS|daedalus/providers/_ollama_native.py|daedalus.providers._openai_compat
DEPENDS|tests/test_ikarus_stream.py|daedalus.ikarus_os
DEPENDS|tests/test_ikarus_stream.py|daedalus.providers.ollama
DEPENDS|tests/test_ikarus_stream.py|daedalus.providers._openai_compat
DEPENDS|tests/test_egress_lane_by_host.py|daedalus.sensitivity
DEPENDS|tests/test_egress_lane_by_host.py|daedalus.offload
DEPENDS|tests/test_egress_lane_by_host.py|daedalus.providers.ollama
DEPENDS|tests/test_egress_lane_by_host.py|daedalus.ikarus_os
DEPENDS|tests/test_egress_lane_by_host.py|pytest
DEPENDS|tests/test_tools_vet.py|daedalus.skills
DEPENDS|tests/test_tools_vet.py|daedalus.tools.vet
DEPENDS|daedalus/memory/__init__.py|daedalus.memory.embeddings
DEPENDS|tests/test_council_livewire.py|daedalus.cli
DEPENDS|tests/test_council_livewire.py|daedalus.council.session
DEPENDS|tests/test_council_livewire.py|daedalus.council.vendors
DEPENDS|tests/test_council_livewire.py|pytest
DEPENDS|tests/test_council_livewire.py|inspect
DEPENDS|tests/test_council_livewire.py|pathlib.Path
DEPENDS|tests/test_self_policy_confinement.py|daedalus.config
DEPENDS|tests/test_self_policy_confinement.py|daedalus.sensitivity
DEPENDS|tests/test_structcore_graph.py|daedalus.structcore
DEPENDS|tests/test_structcore_graph.py|daedalus.structcore.index
DEPENDS|tests/test_structcore_graph.py|daedalus.structcore.report
DEPENDS|tests/test_ikarus_act.py|daedalus.ikarus_act
DEPENDS|tests/test_ikarus_act.py|daedalus.ikarus_os
DEPENDS|tests/test_dotenv.py|daedalus.dotenv
DEPENDS|tests/test_churn.py|daedalus.structcore.churn
DEPENDS|tests/test_churn.py|daedalus.structcore.churn._parse_numstat

## WRITES

WRITES|tests/test_churn.py|temporary directories via tempfile.TemporaryDirectory
WRITES|tests/test_churn.py|git repositories via subprocess
WRITES|tests/test_evolution_baseline.py|temporary candidate worktree and resolved.txt via _candidate_worktree and subprocess
WRITES|tests/test_operability_drill.py|runs/spine/drill-test.json
WRITES|tests/test_operability_drill.py|runs/spine/drill-test2.json
WRITES|tests/test_operability_drill.py|runs/spine/drill-test3.json

## READS

READS|daedalus/control_plane.py|.mcp.json
READS|daedalus/control_plane.py|AGENTS.md
READS|daedalus/control_plane.py|project JSON file
READS|tests/test_mapping_switches.py|daedalus project root (in test_this_repo_still_analyses)
READS|daedalus/bookkeeper.py|docs/ARCHITECTURE.md
READS|daedalus/bookkeeper.py|docs/architecture_history/manifest.json
READS|daedalus/selftest.py|src/hello.py in scratch repo
READS|daedalus/providers/_ollama_native.py|OLLAMA_NUM_CTX environment variable
READS|tests/test_egress_lane_by_host.py|daedalus/ikarus_os.py (source text via Path(mod.__file__).read_text)
READS|daedalus/kairos/archive.py|load_attempts reads from caller-specified file path.

## CLAIMS

CLAIMS|tests/test_spine_attempt_containment.py|Module docstring states: 'a mutating git verb can never run against the primary checkout'
CLAIMS|tests/test_spine_attempt_containment.py|test_mutating_git_is_refused_when_the_directory_cannot_be_examined: 'Fail closed. A path we cannot stat is not assumed innocent.'
CLAIMS|tests/test_spine_attempt_containment.py|test_mutating_git_is_refused_when_the_checkout_cannot_be_examined: 'If we cannot locate what we are protecting, we protect everything.'
CLAIMS|tests/test_spine_attempt_containment.py|test_gate_scratch_removal_is_routed_through_the_guarded_walker: 'Two claims at once: (1) the delete goes through _remove_tree_no_follow; (2) a delete that could NOT be completed is REPORTED.'
CLAIMS|tests/test_offload_automint.py|fires only on a genuinely landed edit (verified disk change, gate passed, nothing rolled back)
CLAIMS|tests/test_offload_automint.py|exactly one mint + one store write per landed run
CLAIMS|tests/test_offload_automint.py|minted task is QUARANTINE tier; non-quarantine task is REFUSED
CLAIMS|tests/test_offload_automint.py|minter that raises is fail-soft AND loud
CLAIMS|tests/test_offload_automint.py|env flag toggles it, OFF by default
CLAIMS|daedalus/structcore/ignore.py|load_ignore_rules guarantees missing/unreadable file returns empty rules
CLAIMS|daedalus/structcore/ignore.py|IgnoreRules.matches guarantees last-match-win semantics for ignore decisions
CLAIMS|daedalus/structcore/ignore.py|ProjectScope.in_center guarantees returns True if rel is inside any center root (or whole repo if no center)
CLAIMS|daedalus/structcore/ignore.py|ProjectScope.center_of guarantees returns the longest matching center root or None
CLAIMS|daedalus/structcore/ignore.py|ProjectScope.is_shell guarantees returns True if rel is outside center or ignored
CLAIMS|daedalus/structcore/ignore.py|project_scope guarantees center precedence: explicit > env, and ignore composition order with last-match-wins
CLAIMS|daedalus/eval/tasks.py|Labels verified reachable by running semantic_slice (circularity acknowledged)
CLAIMS|daedalus/wiki/vault.py|"This module is READ-ONLY. It discovers, parses and validates; it never writes."
CLAIMS|tests/test_semantic_route_cold_start.py|'NOTHING in semantic_route is mocked.'
CLAIMS|tests/test_semantic_route_cold_start.py|'A COLD embedding model is not a dead host -- and the latent route survives it.'
CLAIMS|tests/test_semantic_route_cold_start.py|'Each test starts a real HTTP server speaking the Ollama /api/embeddings protocol, and makes it SLOW on purpose.'
CLAIMS|tests/test_wiki.py|The wiki's contract: VaultPathValidator pins the guard Momus named as blocker for write path; RefuseToGuess pins rule that unresolved link is counted, never bound to near-match.
CLAIMS|daedalus/structcore/languages.py|LanguageSpec registry — declarative per-language facts, keyed by extension. Adding a language is *data*, not code.
CLAIMS|daedalus/structcore/languages.py|DocumentSpec is independent of LanguageSpec; a path answers non-None to exactly one of them (or neither).
CLAIMS|tests/test_shadow_run.py|"The shadow run: it may collect candidates, it may not confer trust."
CLAIMS|tests/test_shadow_run.py|"Absent evidence is the state the whole repo keeps getting wrong." (test_no_receipt_means_unproven_not_fine)
CLAIMS|tests/test_shadow_run.py|"Ensures that no bypass flag allows promotion regardless of discrimination." (test_there_is_NO_flag_that_allows_promotion_anyway)
CLAIMS|tests/test_primary_tree_fence.py|The primary-checkout write fence: a write aimed at the checkout is refused, the SAME write aimed at a worktree is allowed.
CLAIMS|tests/test_primary_tree_fence.py|Every fence test here is PAIRED. A blocked-only assertion passes just as well when the predicate is "return \"no\"" for everything, which is a guard that is broken in the direction nobody notices until the product stops working; and an allowed-only assertion passes when the predicate is "return None". So each case states both halves against the same input shape.
CLAIMS|daedalus/structcore/churn.py|git_churn guarantees degradation to {} on any failure.
CLAIMS|daedalus/structcore/churn.py|co_change_pairs degrades to [] on any git failure.
CLAIMS|daedalus/structcore/churn.py|temporal_misses ensures co-change pairs exclude those with static import edges and documents.
CLAIMS|tests/test_dynamic.py|Every model/network seam is mocked -- no live Ollama or Claude call is made.

## UNWIRED

UNWIRED|tests/test_spine_return_arc.py|test_a_stale_inventory_is_withheld_loudly_not_ranked
UNWIRED|tests/test_spine_return_arc.py|test_a_matching_inventory_is_ranked_normally
UNWIRED|tests/test_spine_return_arc.py|test_a_dirty_snapshot_alone_does_not_suppress
UNWIRED|tests/test_spine_return_arc.py|test_freshness_fails_open_when_there_is_no_git_to_ask
UNWIRED|tests/test_spine_return_arc.py|test_an_inventory_with_no_recorded_revision_is_not_trusted
UNWIRED|tests/test_spine_return_arc.py|test_stale_inventory_flag_re_admits_the_candidates
UNWIRED|tests/test_spine_return_arc.py|test_a_short_recorded_sha_matches_a_long_head_by_prefix
UNWIRED|tests/test_spine_return_arc.py|test_a_recorded_head_that_is_not_a_real_abbreviated_sha_is_refused

## SMELL

SMELL|daedalus/structcore/churn.py|Deferred import in temporal_misses to avoid circular dependency with index and markdown.
SMELL|tests/test_dynamic.py|Patches private functions (_try_ikarus, _ask_claude_report) indicating tight coupling to internal implementation.
SMELL|daedalus/providers/codex_cli.py|Potential duplication of timeout handling and risk reporting with other providers
SMELL|tests/test_typegraph_star_imports.py|Multiple test classes share identical setUpClass/tearDownClass pattern; could be refactored into a common base to reduce duplication.
SMELL|daedalus/benchmark.py|File bundles dry-run and live-run benchmarks with separate but similar printing functions, increasing coupling