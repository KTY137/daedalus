# Census shard 19/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/claude_bridge.py|function|ask_claude|Executes Claude CLI, returns dict with agent, prompt_path, report_path, and report.
daedalus/claude_bridge.py|function|main|Entry point for command-line usage with argparse.
daedalus/drafts.py|module|daedalus.drafts|Re-exports symbols from daedalus.kairos.drafts for backward compatibility.
daedalus/drafts.py|constant|DRAFT_DIR|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|constant|ROOT|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|apply_payload|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|delete_draft|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|get_draft|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|list_drafts|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|save_draft|Re-exported from daedalus.kairos.drafts.
daedalus/drafts.py|function|set_status|Re-exported from daedalus.kairos.drafts.
tests/test_parallel_dispatch.py|class|ParallelDispatchTests|ensures parallel dispatch enforces sequential execution for writable tasks with whole-repo attribution
daedalus/providers/personas.py|function|persona_for|Return shadow persona call-name for (provider, agent_name)
daedalus/providers/personas.py|function|culture|Return culture for provider
daedalus/providers/personas.py|function|roster|Return list of all named workers on a lane
tests/test_registry_shadowing.py|constant|SELF_PROTECTING|Tuple of paths that must be write-protected under any project name.
tests/test_registry_shadowing.py|class|RegistryMustNotShadowTheRepoTests|Unittest class verifying that naming a project does not weaken write confinement.
tests/test_registry_shadowing.py|class|IntersectWriteAllowTests|Unittest class verifying the intersection logic for write allow lists.
daedalus/eval/__init__.py|module|daedalus.eval|The eval package for measuring slice quality against whole-repo baselines.
daedalus/eval/__init__.py|function|resolve_task_repo|Resolves a task repository path for a given task identifier.
daedalus/eval/__init__.py|function|run_tier1|Runs deterministic tier-1 eval (recall and compression).
daedalus/eval/__init__.py|function|run_tier2|Runs optional tier-2 eval with an LLM to compare slice vs whole-repo performance.
daedalus/eval/__init__.py|constant|TASKS|Dictionary of labelled tasks for the eval harness.
daedalus/dotenv.py|class|DotEnvRefused|Exception raised when loading a git-tracked .env
daedalus/dotenv.py|function|parse|Parse dotenv text into dict of key-value pairs, skipping malformed lines
daedalus/dotenv.py|function|load|Load environment variables from .env file into os.environ, returning names set
daedalus/dotenv.py|function|describe|Return metadata about .env file presence, tracking, and keys without values
daedalus/dotenv.py|constant|ROOT|Absolute path to repository root
daedalus/dotenv.py|constant|DEFAULT_ENV_PATH|Default path to .env file
daedalus/__init__.py|function|route_task|Re-exported from .router
daedalus/__init__.py|class|AgentReport|Re-exported from .schemas
daedalus/__init__.py|class|AgentTask|Re-exported from .schemas
daedalus/__init__.py|class|RunState|Re-exported from .schemas
daedalus/__init__.py|function|validate_report|Re-exported from .schemas
tests/test_fenrir_slice_attack.py|function|test_shell_body_never_enters_a_scoped_symbol_slice|Tests that shell files are not expanded into slices under scoped index.
tests/test_fenrir_slice_attack.py|function|test_symbol_slice_is_byte_identical_across_hash_seeds|Tests that slice output is deterministic regardless of PYTHONHASHSEED.
daedalus/adapters/base.py|class|AgentAdapter|Provides abstract interface for agent adapters.
tests/test_clones_string_literals.py|constant|CPP|spec_for('x.cpp') result
tests/test_clones_string_literals.py|constant|RUST|spec_for('x.rs') result
tests/test_clones_string_literals.py|constant|GO|spec_for('x.go') result
tests/test_clones_string_literals.py|constant|PY|spec_for('x.py') result
tests/test_clones_string_literals.py|class|LineCommentInStringTests|Tests line comment handling inside strings
tests/test_clones_string_literals.py|class|BlockCommentInStringTests|Tests block comment handling inside strings
tests/test_clones_string_literals.py|class|PerLanguageQuotingTests|Tests quoting behavior per language
tests/test_clones_string_literals.py|class|AbstractPathTests|Tests abstract fingerprint distinguishes modified bodies
daedalus/runbook.py|constant|RUN_DIR|Path to runs directory
daedalus/runbook.py|function|create_run|Creates a run brief and stores JSON
daedalus/runbook.py|function|main|CLI entry point for creating a run brief
tests/test_web_api_health.py|function|server|provides a real server on a free loopback port for tests
tests/test_web_api_health.py|function|test_the_endpoint_answers_with_the_five_state_vocabulary|guarantees the endpoint returns 200 with five-state vocabulary
tests/test_web_api_health.py|function|test_present_and_unknown_are_NOT_reported_as_working|guarantees that working claims carry a MEASURED fact
tests/test_web_api_health.py|function|test_the_expensive_probes_are_OFF_unless_asked_and_the_answer_says_so|guarantees that expensive probes are off by default and that is declared
tests/test_web_api_health.py|function|test_asking_for_deep_is_recorded|guarantees that asking for deep is recorded in the response
tests/test_web_api_health.py|function|test_a_failure_of_the_SURFACE_is_distinguishable_from_bad_health|guarantees that a 500 from health surface is distinguishable from bad health
daedalus/providers/claude_cli.py|class|ClaudeCLIProvider|primary lane: agentic, write-capable, trusted Claude CLI provider
tests/test_clones_precision.py|class|AbstractNormalizeTest|Unit tests for abstract normalization of code tokens.
tests/test_clones_precision.py|class|RenamedClusterTest|Unit tests for Type-2 renamed clone clustering.
tests/test_clones_precision.py|class|NearClusterTest|Unit tests for Type-3 near-miss clone clustering.
tests/test_clones_precision.py|constant|ORIG|Original code snippet for clone testing.
tests/test_clones_precision.py|constant|RENAMED|Renamed (Type-2) variant of ORIG.
tests/test_clones_precision.py|constant|NEAR_A|First near-miss (Type-3) code snippet.
tests/test_clones_precision.py|constant|NEAR_B|Second near-miss (Type-3) code snippet.
daedalus/wiki/__init__.py|class|Vault|Represents an Obsidian-compatible vault.
daedalus/wiki/__init__.py|class|Page|Represents a single Markdown page in a vault.
daedalus/wiki/__init__.py|function|vault_rel|Returns the relative path of a page within a vault.
daedalus/wiki/__init__.py|function|read_page|Reads and parses a page from disk.
daedalus/wiki/__init__.py|function|discover_pages|Discovers all pages in a vault directory.
daedalus/wiki/__init__.py|function|discover_vaults|Discovers all vaults in a project directory.
daedalus/wiki/__init__.py|function|page_tree|Builds a hierarchical page tree.
daedalus/wiki/__init__.py|function|parse_frontmatter|Parses YAML frontmatter from a page.
daedalus/wiki/__init__.py|constant|PAGE_SUFFIX|File suffix for vault pages (.md).
daedalus/wiki/__init__.py|constant|PROJECT_VAULT_DIR|Default project vault directory name.
daedalus/wiki/__init__.py|constant|VAULT_VERSION|Version identifier for the vault format.
daedalus/wiki/__init__.py|class|WikiLink|Represents a [[wikilink]] reference.
daedalus/wiki/__init__.py|class|LinkIndex|Index of all wikilinks in a vault.
daedalus/wiki/__init__.py|function|extract_wikilinks|Extracts all wikilinks from a page.
daedalus/wiki/__init__.py|function|build_index|Builds a complete link index for a vault.
daedalus/wiki/__init__.py|function|backlinks|Finds all backlinks to a given page.
daedalus/wiki/__init__.py|function|unlinked_mentions|Finds mentions without corresponding links.
daedalus/wiki/__init__.py|function|local_graph|Builds a local graph of links around a page.
daedalus/wiki/__init__.py|constant|LINKS_VERSION|Version identifier for the link index.
daedalus/wiki/__init__.py|constant|CODE|Link type for code references.
daedalus/wiki/__init__.py|constant|DOC|Link type for documentation references.
daedalus/wiki/__init__.py|constant|TYPE|Link type for type references.
daedalus/wiki/__init__.py|constant|VAULT|Link type for vault references.
tests/test_claude_detect.py|constant|SAMPLE_SINGLE|Provides a sample single-line frontmatter string.
tests/test_claude_detect.py|constant|SAMPLE_FOLDED|Provides a sample folded-description frontmatter string.
tests/test_claude_detect.py|class|ParseFrontmatterTests|Tests parse_frontmatter for single-line, folded, and missing frontmatter.
tests/test_claude_detect.py|class|DetectClaudeCrewTests|Tests detect_claude_crew for agent detection and empty cases, and dashboard integration.
tests/test_structcore.py|constant|JOIN_WORKER|A ~6-line function byte-identical everywhere (Type-1 clone)
tests/test_structcore.py|constant|RAMP_DOWN|Python function for ramp_down
tests/test_structcore.py|constant|JS_BLOCK|JS block for formatStatus function (window clone)
tests/test_structcore.py|class|structcoreTest|Tests for clone detection and safety fencing
tests/test_structcore_api.py|constant|CLONE|Duplicate function definition (clone)
tests/test_structcore_api.py|constant|UTIL|Utility compute function
tests/test_structcore_api.py|constant|CORE|Core module importing util
tests/test_structcore_api.py|class|StructureSummaryTest|Tests structure_summary shape and clone totals
tests/test_structcore_api.py|class|SymbolGraphSliceTest|Tests semantic_slice pulls callee body
daedalus/providers/__init__.py|class|ProviderMetadata|Defines frozen dataclass with fields for provider metadata.
daedalus/providers/__init__.py|function|get_provider|Returns a Provider instance for given name, raises ValueError if unknown.
daedalus/providers/__init__.py|function|list_providers|Returns list of all provider metadata dicts.
daedalus/providers/__init__.py|function|provider_health|Returns list of health status dicts for all providers.
daedalus/providers/__init__.py|function|available_providers|Returns dict of provider names to availability booleans.
daedalus/bootstrap_prompt.py|constant|HARNESS_ROOT|Path to harness root directory.
daedalus/bootstrap_prompt.py|function|claude_bootstrap_prompt|Returns dict with project and prompt string for Claude CLI.
daedalus/metrics.py|module|metrics|Logs routing outcomes and computes fallback rate.
daedalus/metrics.py|constant|ALARM_FALLBACK_RATE|Threshold for fallback alarm.
daedalus/metrics.py|constant|LOG|Path to JSONL log file.
daedalus/metrics.py|constant|ROOT|Root directory of the project.
daedalus/metrics.py|function|record|Log one routing outcome.
daedalus/metrics.py|function|summary|Compute summary of metrics and alarm state.
daedalus/metrics.py|function|main|CLI entry point for offload metrics.
tests/test_storage_watermark.py|module|test_storage_watermark|Tests for storage availability checks.
tests/test_storage_watermark.py|function|test_ok_state|Tests that check_storage returns ok state when free space is sufficient.
tests/test_storage_watermark.py|function|test_unavailable_when_below_watermark|Tests that state is storage_unavailable when below watermark.
tests/test_storage_watermark.py|function|test_unavailable_when_volume_missing|Tests that OSError leads to storage_unavailable.
tests/test_storage_watermark.py|function|test_env_override|Tests DAEDALUS_MIN_FREE_GIB env var and explicit argument wins.
tests/test_storage_watermark.py|function|test_env_override_invalid_falls_back_to_default|Tests that invalid env var falls back to default.
tests/test_storage_watermark.py|function|test_require_storage_raises_with_path|Tests that require_storage raises StorageUnavailable with path info.
tests/test_storage_watermark.py|function|test_require_storage_returns_status_when_ok|Tests that require_storage returns status when ok.
tests/test_categories.py|class|CategoriesTests|Unit tests for categories module including load, validate, update, preset_for, and get_categories.
tests/test_categories.py|method|setUp|Create temporary directory for per-repo tests.
tests/test_categories.py|method|tearDown|Clean up temporary directory.
tests/test_categories.py|method|test_load_global_seed|Verifies that loading global seed returns expected categories.
tests/test_categories.py|method|test_validate_fails_closed|Validates that bad input produces errors and good input passes.
tests/test_categories.py|method|test_per_repo_override_precedence|Ensures per-repo overrides take precedence without affecting global.
tests/test_categories.py|method|test_update_unknown_category_raises|Asserts KeyError when updating unknown category.
tests/test_categories.py|method|test_update_invalid_patch_raises|Asserts ValueError when patch is invalid.
tests/test_categories.py|method|test_preset_for_returns_category_default|Checks preset_for returns lane and tier from category.
tests/test_categories.py|method|test_preset_for_falls_back_when_uncategorized|Checks preset_for falls back to model_tier when no category.
tests/test_categories.py|method|test_get_categories_joins_agents|Checks core.get_categories includes agents in categories.
tests/test_topology.py|function|test_disconnected_graph_uses_component_cut_without_fake_fiedler_vector|Tests that disconnected graph uses component cut and assigns None fiedler values.
tests/test_topology.py|function|test_connected_graph_uses_sparse_compatible_sweep_cut|Tests that connected graph uses normalized laplacian sweep with cut_edges=1.
tests/test_topology.py|function|test_oversized_graph_refuses_dense_or_synchronous_fallback|Tests that oversized graph returns available=False with reason.
daedalus/kairos/orchestrate.py|function|prepare_task|Prepares a task by routing, collecting status, recording memory event, and optionally enqueuing Claude request, returning a dict with all details.
daedalus/kairos/orchestrate.py|function|main|CLI entry point that parses arguments and calls prepare_task, printing JSON result.
tests/test_ikarus_os.py|class|ClassifyTest|Tests intent classification method of ikarus_os for various intents.
tests/test_ikarus_os.py|class|AskTest|Tests ask function of ikarus_os for deterministic behavior, enqueue proposals, and fallback.
daedalus/ikarus.py|class|Ikarus|Alias for KairosScheduler, provided for backward compatibility.
daedalus/ikarus.py|class|MetronScheduler|Alias for KairosScheduler, pre-rename name still importable.
daedalus/ikarus.py|class|Assignment|Re-exported from daedalus.kairos.scheduler.
daedalus/ikarus.py|constant|DEFAULT_AVAILABILITY|Re-exported constant from daedalus.kairos.scheduler.
daedalus/ikarus.py|constant|FREE_LANES|Re-exported constant from daedalus.kairos.scheduler.
daedalus/ikarus.py|class|KairosScheduler|Re-exported class from daedalus.kairos.scheduler.
daedalus/ikarus.py|function|main|Re-exported function from daedalus.kairos.scheduler.
tests/test_context_plan.py|class|ConstantBackend|Provides a constant embedding backend for testing.
tests/test_context_plan.py|function|test_lexical_baseline_uses_path_and_symbol_evidence|Tests that lexical_seed_scores uses path and symbol evidence.
tests/test_context_plan.py|function|test_context_plan_is_deterministic_budgeted_and_uses_measured_costs|Tests determinism and budget adherence of plan_context.
tests/test_context_plan.py|function|test_latent_memory_only_maps_hits_with_explicit_file_evidence|Tests latent memory mapping with explicit file evidence.
tests/test_context_plan.py|function|test_no_latent_index_is_reported_instead_of_read_as_no_matches|Tests behavior when no latent index exists.

## DEPENDS

DEPENDS|tests/test_web_api_health.py|daedalus.web_api
DEPENDS|tests/test_web_api_health.py|daedalus.health
DEPENDS|daedalus/providers/claude_cli.py|daedalus.claude_bridge
DEPENDS|daedalus/providers/claude_cli.py|daedalus.providers.base
DEPENDS|tests/test_clones_precision.py|daedalus.structcore
DEPENDS|tests/test_clones_precision.py|daedalus.structcore.clones
DEPENDS|tests/test_clones_precision.py|daedalus.structcore.languages
DEPENDS|daedalus/wiki/__init__.py|daedalus.wiki.vault
DEPENDS|daedalus/wiki/__init__.py|daedalus.wiki.links
DEPENDS|tests/test_claude_detect.py|daedalus.claude_detect
DEPENDS|tests/test_claude_detect.py|daedalus.core
DEPENDS|tests/test_structcore.py|daedalus.structcore
DEPENDS|tests/test_structcore_api.py|daedalus.structcore
DEPENDS|tests/test_structcore_api.py|daedalus.structcore.report
DEPENDS|daedalus/providers/__init__.py|daedalus.providers.base
DEPENDS|daedalus/providers/__init__.py|daedalus.providers.claude_cli
DEPENDS|daedalus/providers/__init__.py|daedalus.providers.deepseek
DEPENDS|daedalus/providers/__init__.py|daedalus.providers.ollama
DEPENDS|daedalus/providers/__init__.py|daedalus.providers.codex_cli
DEPENDS|daedalus/bootstrap_prompt.py|daedalus.core
DEPENDS|daedalus/bootstrap_prompt.py|daedalus.projects
DEPENDS|tests/test_storage_watermark.py|daedalus.storage
DEPENDS|tests/test_categories.py|daedalus.categories
DEPENDS|tests/test_categories.py|daedalus.core
DEPENDS|tests/test_topology.py|daedalus.structcore.topology
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.file_bridge
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.fallback
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.memory
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.projects
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.router
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.status
DEPENDS|daedalus/kairos/orchestrate.py|daedalus.token_policy
DEPENDS|tests/test_ikarus_os.py|daedalus.ikarus_os
DEPENDS|daedalus/ikarus.py|daedalus.kairos.scheduler

## READS

READS|daedalus/dotenv.py|git repository via subprocess in _is_git_tracked
READS|daedalus/metrics.py|memory/offload_metrics.local.jsonl
READS|tests/test_categories.py|.agentenv/categories.json
READS|tests/test_context_plan.py|Arbitrary files in tmp_path via _index and plan_context
READS|daedalus/shift_hook.py|Project root for shift file via shift_mod.load()
READS|daedalus/arch_hook.py|Project root for architecture snapshot via arch_memory.render_delta()
READS|daedalus/shift_ticker.py|shift state file (via shift_mod.load)
READS|daedalus/env.py|.env file (via ENV_PATH)
READS|daedalus/claude_detect.py|.claude/agents/*.md
READS|daedalus/router.py|agents/ directory (built-in or from repo_root/.agentenv/agents/ or templates/agents/)

## CLAIMS

CLAIMS|daedalus/eval/__init__.py|The package claims that distilled semantic slices beat whole-repo concatenation for token efficiency and context retention.
CLAIMS|daedalus/dotenv.py|A real environment variable always wins (rule 1)
CLAIMS|daedalus/dotenv.py|A git-tracked .env is refused, loudly (rule 2)
CLAIMS|daedalus/dotenv.py|Values are never logged, echoed, or returned (rule 3)
CLAIMS|daedalus/__init__.py|Lightweight event-driven agent harness for local app-building work.
CLAIMS|tests/test_fenrir_slice_attack.py|A SHELL file must not be expanded into, on ANY slice path.
CLAIMS|tests/test_fenrir_slice_attack.py|The distilled slice must be byte-identical across PYTHONHASHSEED.
CLAIMS|tests/test_clones_string_literals.py|Comment stripping must respect string literals to avoid fabricating exact clones.
CLAIMS|tests/test_web_api_health.py|test_present_and_unknown_are_NOT_reported_as_working: guarantee that working claims carry a MEASURED fact
CLAIMS|tests/test_web_api_health.py|test_the_expensive_probes_are_OFF_unless_asked_and_the_answer_says_so: guarantee that expensive probes are off by default and declared
CLAIMS|tests/test_web_api_health.py|test_a_failure_of_the_SURFACE_is_distinguishable_from_bad_health: guarantee that surface failure is distinguishable from bad health
CLAIMS|daedalus/providers/claude_cli.py|ClaudeCLIProvider class docstring: primary lane: agentic, write-capable, trusted Claude CLI
CLAIMS|daedalus/providers/claude_cli.py|run method docstring: unused policy parameter: Claude is agentic + trusted
CLAIMS|tests/test_clones_precision.py|"Movement I.5 / Move 1 — clone precision: Type-2 (renamed) + Type-3 (near-miss). Runs stdlib-only (Python abstraction uses the tokenize lexer). Verifies that a renamed-but-structurally-identical pair lands in renamed_clusters (and NOT in the exact unit_clusters), and a gapped/near copy lands in near_clusters with a similarity score — both additive to the existing exact-clone index and both safety-annotated."
CLAIMS|daedalus/wiki/__init__.py|"READ-ONLY by construction. The write path needs its own gate list and a Cerberus review — kairos.gated_writes is a provider-attempt pipeline, not a write fence, and wiring a human editor's PUT through it would fail every save silently. See docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md."
CLAIMS|tests/test_structcore.py|Runs stdlib-only (no tree-sitter/lizard required). Python clones detected at unit level; cross-language copy-paste at window level; any cluster touching a SAFETY-CLASS path is fenced.
CLAIMS|tests/test_structcore_api.py|Covers data the /api/structure and /api/distill endpoints serve, without standing up the HTTP server.
CLAIMS|daedalus/providers/__init__.py|A provider turns a task brief into a validated structured report.
CLAIMS|daedalus/bootstrap_prompt.py|Session bootstrap prompts for external runtimes.
CLAIMS|daedalus/metrics.py|The most load-bearing practitioner warning: a broken verifier can quietly route ~90% of traffic to the expensive model with no error and no alert.
CLAIMS|tests/test_ikarus_os.py|No real LLM calls happen here: every case uses provider=None or an unwired provider, so the deterministic path answers. Verifies ENQUEUE only *proposes* (nothing executes) and the safety-preserving routing.
CLAIMS|daedalus/ikarus.py|Keep the old API working during that migration.
CLAIMS|tests/test_context_plan.py|test_lexical_baseline_uses_path_and_symbol_evidence: guarantees lexical_seed_scores uses path and symbol evidence
CLAIMS|tests/test_context_plan.py|test_context_plan_is_deterministic_budgeted_and_uses_measured_costs: guarantees plan_context is deterministic and respects token budget
CLAIMS|tests/test_context_plan.py|test_latent_memory_only_maps_hits_with_explicit_file_evidence: guarantees latent_memory_seed_scores only maps events with explicit file evidence
CLAIMS|tests/test_context_plan.py|test_no_latent_index_is_reported_instead_of_read_as_no_matches: guarantees no latent index returns status 'not_configured' and empty scores
CLAIMS|daedalus/shift_hook.py|Makes time, goal, remaining window part of agent input every turn
CLAIMS|daedalus/arch_hook.py|Injects compressed architecture delta every turn when snapshot exists
CLAIMS|daedalus/providers/base.py|ProviderCapabilities: "What a provider is *allowed* and *able* to do. These are structural guarantees enforced by the harness, not promises the model must keep."
CLAIMS|daedalus/providers/base.py|Provider: "Common interface for every model backend. All providers return the same validated ``agent_report_v1`` dict so everything downstream is uniform."
CLAIMS|daedalus/langgraph_adapter.py|build_graph: "The stdlib harness keeps the state contract small and serializable. This adapter is intentionally thin so a future LangGraph graph can reuse the same state keys instead of inventing a second orchestration model."
CLAIMS|daedalus/shift_ticker.py|This is the HUMAN's view. It prints the time, the declared goal, how much of the window is left, and the checkpoints the agent has written.

## UNWIRED

UNWIRED|daedalus/ikarus.py|Ikarus
UNWIRED|daedalus/ikarus.py|MetronScheduler
UNWIRED|daedalus/ikarus.py|Assignment
UNWIRED|daedalus/ikarus.py|DEFAULT_AVAILABILITY
UNWIRED|daedalus/ikarus.py|FREE_LANES
UNWIRED|daedalus/ikarus.py|KairosScheduler
UNWIRED|daedalus/langgraph_adapter.py|build_graph
UNWIRED|daedalus/crew_hook.py|live_agents (no caller visible in slice)

## SMELL

SMELL|daedalus/shift_hook.py|Uses sys.path.insert which is fragile; silently catches all exceptions
SMELL|daedalus/arch_hook.py|Uses sys.path.insert and silently passes exceptions