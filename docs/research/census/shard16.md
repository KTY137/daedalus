# Census shard 16/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/control_plane.py|function|save_autonomy|writes autonomy configuration patch to project file and returns updated unified profiles
tests/test_mapping_switches.py|function|report|Provides a report object with analysed switch inventory for tests.
tests/test_mapping_switches.py|function|test_schema_and_determinism|Tests that the schema matches and analysis is deterministic.
tests/test_mapping_switches.py|function|test_dark_gate_is_classified_dark|Verifies dark gates are classified correctly.
tests/test_mapping_switches.py|function|test_env_name_behind_a_module_constant_is_resolved|Resolves env name behind a module constant.
tests/test_mapping_switches.py|function|test_zero_default_int_gate_is_dark|Confirms zero default int gate is dark.
tests/test_mapping_switches.py|function|test_override_with_a_fallback_is_not_dark|Ensures override with fallback is not dark.
tests/test_mapping_switches.py|function|test_inverted_switch_is_never_dark|Validates inverted switch is never dark.
tests/test_mapping_switches.py|function|test_real_default_reads_as_on|Checks real default reads as ON.
tests/test_mapping_switches.py|function|test_multi_default_conflict_is_reported|Reports multi-default conflict correctly.
tests/test_mapping_switches.py|function|test_default_imported_from_another_module_is_resolved|Resolves default imported from another module.
tests/test_mapping_switches.py|function|test_one_alias_bound_to_two_modules_resolves_per_line|Resolves alias bound to two modules per line.
tests/test_mapping_switches.py|function|test_required_read_is_not_dark|Confirms required read is not dark.
tests/test_mapping_switches.py|function|test_registry_declared_env_key_is_found|Finds registry-declared env key.
tests/test_mapping_switches.py|function|test_documented_but_never_read|Identifies documented but never read switches.
tests/test_mapping_switches.py|function|test_read_but_never_documented|Identifies read but never documented switches.
tests/test_mapping_switches.py|function|test_near_miss_name_mismatch_is_the_silent_bug|Captures near-miss name mismatch.
tests/test_mapping_switches.py|function|test_unrelated_names_are_not_accused_of_being_the_same_variable|Ensures unrelated names are not confused.
tests/test_mapping_switches.py|function|test_param_gates_split_from_safety_flags|Splits param gates from safety flags.
tests/test_mapping_switches.py|function|test_config_keys_are_classified|Classifies config keys correctly.
tests/test_mapping_switches.py|function|test_counts_agree_with_the_listings|Verifies counts agree with listings.
tests/test_mapping_switches.py|function|test_report_is_json_serialisable|Confirms report is JSON serialisable.
tests/test_mapping_switches.py|function|test_syntax_error_is_reported_not_raised|Reports syntax error instead of raising.
tests/test_mapping_switches.py|function|test_this_repo_still_analyses|Guards the invariant that the artifact always exists.
daedalus/bookkeeper.py|constant|ROOT|Root path of the repository (parent of script's directory)
daedalus/bookkeeper.py|constant|DOCS|Path to docs directory (ROOT/docs)
daedalus/bookkeeper.py|constant|SOURCE|Path to ARCHITECTURE.md (DOCS/ARCHITECTURE.md)
daedalus/bookkeeper.py|constant|ARTIFACT|Path to output architecture.html (DOCS/architecture.html)
daedalus/bookkeeper.py|constant|HISTORY|Path to architecture_history directory (DOCS/architecture_history)
daedalus/bookkeeper.py|function|render_markdown|Converts a subset of Markdown to HTML (headings, lists, tables, code, blockquote, hr, inline)
daedalus/bookkeeper.py|function|update|Renders ARCHITECTURE.md to artifact, snapshots on content change, returns summary dict
daedalus/bookkeeper.py|function|main|CLI entry point for the bookkeeper actions
tests/test_era1_robustness.py|class|RepoRootRoutingTests|Fix 2: per-repo agent rosters are visible to routing.
tests/test_era1_robustness.py|class|WroteFieldTests|Fix 1: result['wrote'] is disk ground truth in every outcome.
tests/test_era1_robustness.py|class|DirtyRollbackTests|When rollback can't revert a bad write, the leftover must be surfaced.
tests/test_era1_robustness.py|class|RewriteCreateTests|Fix 3: the rewrite path can CREATE a new file (greenfield).
tests/test_era1_robustness.py|class|HtmlJsGateTests|Fix 4: .html truncation tripwire and .js node --check gate.
daedalus/selftest.py|function|run|Runs the live round-trip and returns result dict
daedalus/selftest.py|function|main|Entry point for CLI; parses args, calls run and emits result
tests/test_spine_cancel.py|function|test_backend_selection_is_explicit_per_platform|Guarantees that select_backend returns WindowsJobBackend for win32 and PosixSessionBackend for linux/darwin/freebsd.
tests/test_spine_cancel.py|function|test_backend_names_are_distinct|Guarantees that WindowsJobBackend.name and PosixSessionBackend.name are different.
tests/test_spine_cancel.py|function|test_empty_argv_rejected|Guarantees that ManagedProcess([]) raises ValueError.
tests/test_spine_cancel.py|function|test_fast_exit_reports_returncode|Guarantees that wait() returns the exit code of a fast-exiting process.
tests/test_spine_cancel.py|function|test_stdout_is_capturable|Guarantees that stdout can be captured via subprocess.PIPE.
tests/test_spine_cancel.py|function|test_cancel_on_exited_process_is_noop|Guarantees that cancel on an already-exited process returns stage 'already_exited' and does not send signals.
tests/test_spine_cancel.py|function|test_close_is_idempotent|Guarantees that close() on an already-exited process is safe and returns None.
tests/test_spine_cancel.py|function|test_cancel_kills_grandchild|Guarantees that cancel kills both parent and grandchild processes and no file writes continue.
tests/test_spine_cancel.py|function|test_context_manager_exit_kills_tree|Guarantees that the context manager kills the entire process tree on exit.
tests/test_spine_cancel.py|function|test_grace_timeout_escalates|Guarantees that if grace period is ignored, the process is killed after the grace window.
tests/test_spine_cancel.py|function|test_graceful_stage_when_child_handles_the_signal|Guarantees that graceful handling works when the child catches the signal and exits with code 7.
tests/test_spine_cancel.py|function|test_spawn_fails_closed_when_containment_fails|Guarantees that if containment fails, the spawned process is killed to avoid resource leak.
daedalus/providers/_ollama_native.py|constant|DEFAULT_NUM_CTX|Measured VRAM-safe context window size (6144)
daedalus/providers/_ollama_native.py|constant|OUTPUT_RESERVE_TOKENS|Tokens held back for response generation inside Ollama's full context window (1024)
daedalus/providers/_ollama_native.py|function|num_ctx_value|Returns context window to request from Ollama, with env override and clamp
daedalus/providers/_ollama_native.py|function|effective_input_window|Returns usable input tokens = full context minus generation reserve
daedalus/providers/_ollama_native.py|function|native_chat|POST messages to Ollama native /api/chat and return adapted assistant message
tests/test_ikarus_stream.py|class|ChatStreamTest|Verifies chat_stream yields text deltas, sends stream:true, tolerates malformed frames, and raises ProviderHTTPError on unreachable host.
tests/test_ikarus_stream.py|class|KeepAliveTest|Verifies warm_model targets native /api/generate with keep_alive, respects env override, zero disables, and failure is non-fatal.
tests/test_ikarus_stream.py|class|AskStreamTest|Tests ask_stream for intent detection, enqueue proposal, local lane streaming, fallback on errors, unwired provider degradation, and empty message safety.
tests/test_ikarus_stream.py|class|ClaudeStreamFrameTest|Verifies parsing of text deltas from Claude CLI stream-json, correct flags, and graceful handling of missing CLI or spawn failure.
tests/test_ikarus_stream.py|class|NonStreamingUnchangedTest|Verifies deterministic ask, blocking ollama with pin side-effect, failure returns None, and effort caps preserved.
tests/test_egress_lane_by_host.py|function|test_this_machine_is_trusted|Asserts that loopback IPs (127.x.x.x, [::1]) yield lane 'trusted'.
tests/test_egress_lane_by_host.py|function|test_a_NAME_is_never_trusted_even_when_it_means_loopback|Asserts that 'localhost' (a name) yields lane 'untrusted'.
tests/test_egress_lane_by_host.py|function|test_anywhere_else_is_untrusted|Asserts that non-loopback IPs and domain names yield lane 'untrusted'.
tests/test_egress_lane_by_host.py|function|test_an_unreadable_host_fails_closed|Asserts that malformed or empty hosts yield lane 'untrusted'.
tests/test_egress_lane_by_host.py|function|test_bind_all_is_not_loopback|Asserts that 0.0.0.0 yields lane 'untrusted'.
tests/test_egress_lane_by_host.py|function|test_the_default_host_is_trusted|Asserts that the default Ollama host yields lane 'trusted'.
tests/test_egress_lane_by_host.py|function|test_offload_resolves_its_lane_from_the_env_not_the_provider_name|Asserts that _resolved_ollama_lane() uses OLLAMA_HOST to determine lane.
tests/test_egress_lane_by_host.py|function|test_the_distilled_context_wire_refuses_a_remote_bench|Asserts that _slice_context refuses with appropriate metadata for a remote host.
tests/test_egress_lane_by_host.py|function|test_the_refusal_outranks_the_budget_check|Asserts that the refusal reason is 'not this machine' even when budget is 0.
tests/test_egress_lane_by_host.py|function|test_ikarus_chat_context_follows_the_resolved_host_too|Asserts that _local_lane() in ikarus_os uses OLLAMA_HOST.
tests/test_egress_lane_by_host.py|function|test_no_local_branch_still_names_its_lane_literally|Asserts that no LOCAL branch in ikarus_os hardcodes lane='trusted'.
tests/test_egress_lane_by_host.py|function|test_the_provider_itself_refuses_a_remote_endpoint|Asserts that OllamaProvider refuses a remote endpoint with 'refused' response.
tests/test_egress_lane_by_host.py|function|test_the_provider_does_not_refuse_a_loopback_endpoint|Asserts that OllamaProvider does not refuse a loopback endpoint.
tests/test_egress_lane_by_host.py|function|test_the_declared_capabilities_are_not_the_egress_authority|Asserts that caps.local and caps.trusted_with_ip can differ from egress_lane.
tests/test_egress_lane_by_host.py|function|test_a_local_host_still_reaches_the_budget_path|Asserts that with a local host, the offload wire reaches the budget path.
daedalus/kairos/archive.py|constant|MAX_SUMMARY_CHARS|Maximum length for candidate-influenced summary text (600).
daedalus/kairos/archive.py|constant|NUM_DIVERSE|Number of diverse attempts to sample (2).
daedalus/kairos/archive.py|constant|NUM_ELITE|Number of elite attempts to sample (3).
daedalus/kairos/archive.py|constant|OUTCOME_RANK|Ranking of outcome strings from worst to best.
daedalus/kairos/archive.py|class|Attempt|Represents one evaluated candidate, reduced to what the next attempt can use.
daedalus/kairos/archive.py|function|digest_patch|Returns stable short SHA-256 digest for a patch.
daedalus/kairos/archive.py|function|load_attempts|Reads JSONL notebook and returns tuple of Attempts; never raises.
daedalus/kairos/archive.py|function|record_attempt|Appends one attempt to JSONL notebook; truncates summary.
daedalus/kairos/archive.py|function|sample_inspirations|Picks few prior attempts for inspiration using elite and diverse selection.
tests/test_tools_vet.py|class|StaticOnly|verifies vetting never runs, imports or contacts what it inspects
tests/test_tools_vet.py|class|FailClosed|verifies 'could not scan' is never 'clean'
tests/test_tools_vet.py|class|Detection|verifies detection of prompt injection, exec calls, dotenv secrets
tests/test_tools_vet.py|class|Acknowledgements|verifies acknowledgement downgrades but never hides
tests/test_tools_vet.py|class|BytecodeExemption|verifies conditional exemption for .pyc files
tests/test_tools_vet.py|class|McpServers|verifies MCP server vetting rules
tests/test_tools_vet.py|class|Determinism|verifies findings are reproducible and ordered
daedalus/memory/__init__.py|constant|ROOT|Resolved path to repository root (two parents up).
daedalus/memory/__init__.py|constant|MEMORY_DIR|Path to the memory directory.
daedalus/memory/__init__.py|constant|EVENTS_PATH|Path to events.local.jsonl.
daedalus/memory/__init__.py|constant|TODO_PATH|Path to todos.local.md.
daedalus/memory/__init__.py|constant|VECTOR_DB_PATH|Path to vectors.db.
daedalus/memory/__init__.py|class|MemoryEvent|Dataclass for a memory event with fields for kind, summary, source, etc.
daedalus/memory/__init__.py|function|append_event|Append a MemoryEvent to the journal and refresh todo snapshot; optionally forward to vector store.
daedalus/memory/__init__.py|function|projection_event_from_record|Derive an AgentEvent projection from a journal record for vector indexing.
daedalus/memory/__init__.py|function|load_events|Load all events from events.local.jsonl as a list of dicts.
daedalus/memory/__init__.py|function|refresh_todo_snapshot|Regenerate todos.local.md from current events.
daedalus/memory/__init__.py|function|record_from_bridge_report|Create a memory event from a bridge report and append it.
daedalus/memory/__init__.py|function|main|CLI entry point for manual event addition, snapshot regeneration, and TODO marking.
tests/test_council_livewire.py|constant|CLEAN_DIFF|A sample diff string used as test evidence
tests/test_council_livewire.py|function|spawn_sentinel|Fixture that intercepts vendor process spawning and records attempts
tests/test_council_livewire.py|function|no_convene|Fixture that prevents any call to convene or default_participants
tests/test_council_livewire.py|function|test_convene_refuses_real_vendor_seats_without_live|Tests that convene raises LiveCouncilRefused without --live and spawns nothing
tests/test_council_livewire.py|function|test_live_true_actually_unlocks_dispatch|Tests that --live flag allows vendor process spawning
tests/test_council_livewire.py|function|test_convene_defaults_live_to_false|Tests that the live parameter defaults to False
tests/test_council_livewire.py|function|test_every_default_participant_is_classified_live|Tests that all shipped adapters are classified as live
tests/test_council_livewire.py|function|test_offline_fakes_need_no_opt_in|Tests that fake offline adapters do not require --live
tests/test_council_livewire.py|function|test_a_one_shot_roster_is_not_drained_by_the_gate|Tests that an iterator roster is not consumed by the gate check
tests/test_council_livewire.py|function|test_injected_runner_counts_as_offline|Tests that a shipped adapter with a substituted runner is considered offline
tests/test_council_livewire.py|function|test_unknown_adapter_shapes_are_assumed_live|Tests that unknown subclasses of shipped adapters are assumed live
tests/test_council_livewire.py|function|test_rebinding_the_module_default_cannot_disarm_the_gate|Tests that monkeypatching run_managed after import does not change gate classification
tests/test_council_livewire.py|function|test_cli_refuses_a_bare_council_invocation|Tests that CLI refuses council invocation without --live
tests/test_council_livewire.py|function|test_cli_refuses_live_and_dry_run_together|Tests that CLI refuses contradictory --live and --dry-run
tests/test_council_livewire.py|function|test_cli_live_flag_authorises_the_spend|Tests that --live reaches convene with live=True
tests/test_council_livewire.py|function|test_cli_dry_run_names_the_seats_live_would_call|Tests that --dry-run prints the seats without calling convene
tests/test_self_policy_confinement.py|constant|REPO_ROOT|Resolved path to the repository root for file path operations.
tests/test_self_policy_confinement.py|constant|LEAKED_UNDER_THE_DRAFT|Tuple of 8 paths that leaked under the original drafted policy, used as regression list in test_general_source_is_blocked.
tests/test_self_policy_confinement.py|constant|CONFINED|Sample policy configuration with write_allow set to docs/, tests/, and README.md, used in WriteAllowSemanticsTests.
tests/test_self_policy_confinement.py|class|WriteAllowSemanticsTests|Tests that write_allow semantics are prefix-anchored, allow subtrees, and prevent file->descendant and substring matching bugs. Includes regression test for file entry descendant leak.
tests/test_self_policy_confinement.py|class|ConfinementNarrowsButNeverWidensTests|Tests that write_allow does not bypass other safety mechanisms like secret_floor and high_risk_paths, and disables simulated exemptions.
tests/test_self_policy_confinement.py|class|InstalledSelfPolicyTests|Tests the actual installed policy from .agentenv/agentenv.json to ensure write_allow is present and confines writes correctly, including that key safety files and the policy itself are not writable.
Route this task to Claude or local Ollama.
tests/test_structcore_graph.py|class|GraphInvariantsTest|ensures graph payload invariants: no dangling edges, consistent rel-path node namespace, honest truncation reporting (truncated flag, n_edges_eligible, n_edges_shown, n_edges_offmap), and edge cap behavior
tests/test_structcore_graph.py|class|ScoreModulesAndHotspotsTest|ensures hotspots is exactly the top 15 of module_heat and score_modules ranks every module
tests.test_ikarus_act|module|test_ikarus_act|Contains test cases for ikarus_act
tests.test_ikarus_act|class|MayActAllowsTest|Tests allow cases
tests.test_ikarus_act|class|MayActRefusesTest|Tests refuse cases
tests.test_ikarus_act|class|MayActSuspectsTest|Tests suspect cases
tests.test_ikarus_act|class|ConfirmationTest|Tests confirmation logic
tests.test_ikarus_act|class|DivergenceTest|Tests divergence between act and classify
tests/test_dotenv.py|function|repo|Provides a real git repository fixture for testing git-tracked .env detection
tests/test_dotenv.py|function|test_a_real_export_is_never_overridden_by_the_file|Ensures a pre-existing env var takes precedence over .env
tests/test_dotenv.py|function|test_the_file_fills_a_gap_the_shell_left_open|Ensures .env fills missing env vars
tests/test_dotenv.py|function|test_load_is_idempotent_and_safe_to_call_more_than_once|Verifies idempotency of load: second call does not overwrite existing env
tests/test_dotenv.py|function|test_override_flag_exists_only_for_tests|Tests the override parameter overrides existing env vars
tests/test_dotenv.py|function|test_a_git_tracked_env_file_is_refused|Verifies load raises DotEnvRefused for git-tracked .env
tests/test_dotenv.py|function|test_the_refusal_names_the_remedy|Checks that refusal message suggests 'git rm --cached'
tests/test_dotenv.py|function|test_an_untracked_env_file_in_the_same_repo_loads_fine|Confirms untracked .env in git repo loads successfully
tests/test_dotenv.py|function|test_describe_reports_tracked_and_unsafe_without_raising|Verifies describe reports tracked status without raising
tests/test_dotenv.py|function|test_describe_reports_untracked_as_safe|Verifies describe reports untracked .env as safe
tests/test_dotenv.py|function|test_malformed_lines_are_skipped_not_fatal|Ensures parse skips malformed lines and extracts valid ones
tests/test_dotenv.py|function|test_load_survives_a_file_full_of_malformed_lines|Verifies load handles files with malformed lines
tests/test_dotenv.py|function|test_describe_never_carries_values|Ensures describe() returns only key names, not values
tests/test_dotenv.py|function|test_describe_keys_are_sorted_names_only|Verifies describe returns sorted key names
tests/test_dotenv.py|function|test_missing_file_load_returns_empty_list|Confirms load returns empty list for missing file
tests/test_dotenv.py|function|test_missing_file_describe_is_present_false_and_safe_true|Confirms describe for missing file returns present=False, safe=True

## DEPENDS

DEPENDS|tests/test_offload_write_failclose.py|daedalus.offload
DEPENDS|tests/test_offload_write_failclose.py|daedalus.providers
DEPENDS|tests/test_budget_is_installed.py|daedalus.budget
DEPENDS|tests/test_budget_is_installed.py|daedalus.cli
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.cache
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.index
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.perfile
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.languages
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.slice
DEPENDS|tests/test_honest_denominator.py|daedalus.structcore.tokens
DEPENDS|tests/test_kairos_archive.py|daedalus.kairos.archive
DEPENDS|tests/test_kairos_archive.py|daedalus.eval.correctness
DEPENDS|tests/test_kairos_archive.py|daedalus.kairos.evolution
DEPENDS|tests/test_bridge_enqueue_guard.py|daedalus.file_bridge
DEPENDS|tests/test_rewrite.py|daedalus.providers.ollama
DEPENDS|tests/test_deepseek_substitution_guard.py|daedalus.providers.deepseek
DEPENDS|tests/test_agent_env.py|daedalus.claude_bridge
DEPENDS|tests/test_agent_env.py|daedalus.file_bridge
DEPENDS|tests/test_agent_env.py|daedalus.fallback
DEPENDS|tests/test_agent_env.py|daedalus.memory
DEPENDS|tests/test_agent_env.py|daedalus.kairos.orchestrate
DEPENDS|tests/test_agent_env.py|daedalus.kairos.scheduler
DEPENDS|tests/test_agent_env.py|daedalus.projects
DEPENDS|tests/test_agent_env.py|daedalus.router
DEPENDS|tests/test_agent_env.py|daedalus.status
DEPENDS|tests/test_agent_env.py|daedalus.schemas
DEPENDS|tests/test_agent_env.py|daedalus.token_policy
DEPENDS|tests/test_agent_env.py|daedalus.token_monitor
DEPENDS|tests/test_fence_anchoring.py|daedalus.offload
DEPENDS|tests/test_fence_anchoring.py|daedalus.provider_router
DEPENDS|tests/test_fence_anchoring.py|daedalus.sensitivity
DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/clones
DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/languages
DEPENDS|daedalus/structcore/perfile.py|daedalus/structcore/metrics

## WRITES

WRITES|tests/test_bridge_enqueue_guard.py|runs/_test_hb_guard.json
WRITES|tests/test_cascade.py|metrics.LOG (JSONL file in temp dir)
WRITES|daedalus/hierarchy.py|daedalus/projects (project JSON files via save_team)
WRITES|daedalus/kairos/drafts.py|runs/drafts/
WRITES|daedalus/claude_bridge.py|runs/last_claude_prompt.md
WRITES|daedalus/claude_bridge.py|runs/last_claude_report.json

## READS

READS|tests/test_operability_drill.py|runs/spine/drill-test.json
READS|tests/test_operability_drill.py|runs/spine/drill-test2.json
READS|tests/test_operability_drill.py|runs/spine/drill-test3.json
READS|daedalus/ikarus_chat.py|project root (via resolve_repo_root)
READS|daedalus/ikarus_chat.py|team config (via core.team_config)
READS|daedalus/doctor.py|environment: OLLAMA_HOST
READS|daedalus/doctor.py|environment: OLLAMA_MODEL
READS|daedalus/doctor.py|environment: DEEPSEEK_API_KEY
READS|daedalus/doctor.py|PATH (via shutil.which)
READS|daedalus/structcore/__main__.py|<repo root directory>

## CLAIMS

CLAIMS|tests/test_era1_robustness.py|Era-1 robustness fixes each pinned by regression test: offload result carries wrote, route_and_select/offload thread repo_root, _run_rewrite supports greenfield CREATE, Verifier gates .js and .html.
CLAIMS|daedalus/selftest.py|Performs a real Ollama write round-trip, separate from unit tests
CLAIMS|daedalus/selftest.py|run() returns result dict and is silent (no console noise)
CLAIMS|tests/test_spine_cancel.py|Cancellation must kill the whole tree, not just the child we hold a handle to.
CLAIMS|daedalus/providers/_ollama_native.py|num_ctx_value never raises, falls back to default on invalid env
CLAIMS|daedalus/providers/_ollama_native.py|effective_input_window reserves tokens for generation, callers must fail loud against this budget
CLAIMS|daedalus/providers/_ollama_native.py|native_chat raises ProviderHTTPError on any HTTP error or unreachable host
CLAIMS|tests/test_ikarus_stream.py|Covers the branches added for the chat-latency fix — SSE delta parsing, the stream-json frame shape, the fail-closed fallbacks, and the keep_alive pin that must go to the NATIVE Ollama API (the /v1 shim silently drops it).
CLAIMS|tests/test_egress_lane_by_host.py|The lane is decided by WHERE THE BYTES GO, not by the provider's name.
CLAIMS|tests/test_egress_lane_by_host.py|`localhost` is refused on purpose.
CLAIMS|tests/test_egress_lane_by_host.py|An unreadable host must fail closed.
CLAIMS|tests/test_egress_lane_by_host.py|The distilled context wire refuses a remote bench.
CLAIMS|tests/test_egress_lane_by_host.py|The refusal outranks the budget check.
CLAIMS|tests/test_egress_lane_by_host.py|The ikarus chat context follows the resolved host.
CLAIMS|tests/test_egress_lane_by_host.py|No local branch still names its lane literally.
CLAIMS|tests/test_egress_lane_by_host.py|The provider itself refuses a remote endpoint.
CLAIMS|tests/test_egress_lane_by_host.py|The declared capabilities are not the egress authority.
CLAIMS|daedalus/kairos/archive.py|No MAP-Elites feature grid, no islands, no migration; everything bounded; no egress of candidate code.
CLAIMS|daedalus/kairos/archive.py|digest_patch returns stable short identity for a change to recognize duplicates.
CLAIMS|daedalus/kairos/archive.py|record_attempt truncates candidate-influenced text to MAX_SUMMARY_CHARS.
CLAIMS|daedalus/kairos/archive.py|load_attempts never raises; skips unparseable lines.
CLAIMS|daedalus/kairos/archive.py|sample_inspirations deduplicates by digest; excludes current attempt; does not filter to winners.
CLAIMS|tests/test_tools_vet.py|StaticOnly: vetting never runs, imports or contacts what it inspects
CLAIMS|tests/test_tools_vet.py|FailClosed: 'could not scan' is never 'clean'
CLAIMS|tests/test_tools_vet.py|Acknowledgements: an acknowledgement downgrades, it never hides
CLAIMS|tests/test_tools_vet.py|BytecodeExemption: the exemption is conditional on the source having been scanned
CLAIMS|tests/test_tools_vet.py|McpServers: a server is never reported as cleared because it was not started
CLAIMS|daedalus/memory/__init__.py|Indexing is explicitly secondary to the append-only operational log.
CLAIMS|tests/test_council_livewire.py|Module docstring states live-wire gate purpose and test methodology end-to-end.
CLAIMS|tests/test_council_livewire.py|spawn_sentinel fixture docstring: 'Record every attempt to start a vendor process, and start none.'
CLAIMS|tests/test_council_livewire.py|test_convene_refuses_real_vendor_seats_without_live docstring states expected behavior of refusal and no spawns.
CLAIMS|tests/test_council_livewire.py|test_live_true_actually_unlocks_dispatch docstring states that live=True is the only thing separating from paid vendor calls.

## UNWIRED

UNWIRED|daedalus/eval/mutate.py|Function _looks_like_a_guard defined but not called within this file.
UNWIRED|tests/test_spine_map_source.py|_real_head (called within _stamped, which is called by tests)
UNWIRED|daedalus/structcore/languages.py|spec_for
UNWIRED|daedalus/structcore/languages.py|doc_spec_for
UNWIRED|daedalus/structcore/languages.py|DOCUMENT_EXTENSIONS
UNWIRED|tests/test_preservation_fixtures.py|BEFORE
UNWIRED|tests/test_preservation_fixtures.py|AFTER_REGRESSION
UNWIRED|tests/test_preservation_fixtures.py|AFTER_LIVE

## SMELL

SMELL|daedalus/memory/__init__.py|Single module handles event logging, TODO snapshot, vector indexing bridge, and CLI; potential god-object.
SMELL|daedalus/ikarus_chat.py|Duplicate mapping of blueprint names to squads in _team_patch and _select_blueprints.
SMELL|tests/test_repair_blast_radius_write.py|test_declared_island_file_keeps_workspace_write assertion (writable_seen False) contradicts comment that island file keeps workspace write.
SMELL|tests/test_promotion_forgery.py|No coverage for receipt integrity protection (docstring acknowledges gap)
SMELL|tests/test_offload_write_failclose.py|Test is tightly coupled to specific provider names (codex_cli, ollama) which may change.