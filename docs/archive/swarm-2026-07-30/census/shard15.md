# Census shard 15/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_shadow_run.py|function|test_the_module_does_not_write_the_primary_checkout|Ensures the shadow run module does not write the primary checkout.
tests/test_primary_tree_fence.py|function|trees|Fixture that creates a stand-in primary checkout and a stand-in worktree as siblings.
tests/test_primary_tree_fence.py|function|test_the_same_write_is_refused_in_the_checkout_and_allowed_in_a_worktree|THE invariant: identical relative path, one tree apart, opposite verdicts.
tests/test_primary_tree_fence.py|function|test_assert_write_allowed_raises_for_the_checkout_and_returns_for_a_worktree|assert_write_allowed raises for checkout and returns resolved path for worktree.
tests/test_primary_tree_fence.py|function|test_a_file_that_does_not_exist_yet_is_judged_by_its_GROUND|A new file is judged by its ground; fence must block creation inside checkout and allow in worktree.
tests/test_primary_tree_fence.py|function|test_a_relative_path_cannot_walk_out_of_the_worktree_into_the_checkout|\"..\" is resolved before comparison; path escaping checkout is blocked, staying is allowed.
tests/test_primary_tree_fence.py|function|test_a_symlink_pointing_into_the_checkout_is_resolved_and_refused|Symlink that lands on checkout is resolved and refused; ordinary dir is allowed.
tests/test_primary_tree_fence.py|function|test_input_that_cannot_be_resolved_is_refused_not_guessed_at|Input that cannot be resolved (None, empty) is refused; real worktree path is allowed.
tests/test_primary_tree_fence.py|function|test_a_checkout_that_cannot_be_examined_refuses_everything|If checkout cannot be examined, everything is refused.
tests/test_primary_tree_fence.py|function|test_the_default_root_is_this_repository_not_unfenced|If no repo_root given, defaults to this repository's root, not unfenced.
tests/test_primary_tree_fence.py|function|test_every_alias_spelling_of_the_real_checkout_is_refused|All alias spellings of the real checkout (lowercased, dotdot, UNC admin share, etc.) are refused.
tests/test_primary_tree_fence.py|function|test_the_alias_test_above_is_not_vacuous|Same alias shapes aimed at a non-checkout directory are allowed (paired half).
tests/test_primary_tree_fence.py|function|test_write_and_overlap_diverge_on_the_contains_direction|overlap_reason and write_blocked_reason diverge on parent directory: container is blocked by overlap but allowed by write fence.
tests/test_primary_tree_fence.py|function|test_attempt_module_uses_the_shared_comparison_not_its_own|Verifies that spine/attempt.py uses shared comparisons from primary_tree, not private copies.
tests/test_primary_tree_fence.py|function|test_nearest_existing_stops_at_the_first_real_directory|nearest_existing returns the first existing ancestor directory.
tests/test_primary_tree_fence.py|function|test_persist_refuses_an_artifact_dir_inside_the_checkout|TaskAttempt._persist refuses artifact_dir inside checkout and does not create directories.
tests/test_primary_tree_fence.py|function|test_persist_writes_happily_into_a_worktree|TaskAttempt._persist writes into a worktree successfully.
daedalus/structcore/churn.py|module|churn|Provides git churn and temporal coupling analysis.
daedalus/structcore/churn.py|function|git_churn|Returns per-file added+deleted lines from git history, degrades to {} on failure.
daedalus/structcore/churn.py|function|co_change_pairs|Returns list of co-change pairs with PMI and lift, degrades to [] on failure.
daedalus/structcore/churn.py|function|temporal_misses|Filters co-change pairs to those without static import edges, excluding documents.
daedalus/structcore/churn.py|constant|COCHANGE_MAX_FILES_PER_COMMIT|Maximum files per commit for co-change analysis (40).
tests/test_dynamic.py|class|DecomposeFallbackTests|When the local model is unreachable, the deterministic split is used.
tests/test_dynamic.py|function|test_multi_path_splits_one_subtask_per_path|Multiple paths are each assigned a subtask with objective preserved.
tests/test_dynamic.py|function|test_single_path_is_one_passthrough_subtask|Single path results in exactly one subtask with that path.
tests/test_dynamic.py|function|test_no_paths_still_returns_one_subtask|No paths returns a single subtask with empty path list.
tests/test_dynamic.py|class|DecomposeModelTests|When the local model answers, its JSON breakdown drives the subtasks.
tests/test_dynamic.py|function|test_parses_mocked_json_breakdown|A mocked JSON response from the model is parsed into subtasks.
tests/test_dynamic.py|function|test_parses_bare_json_array_and_honours_max_subtasks|Bare JSON array is parsed and truncated to max_subtasks.
tests/test_dynamic.py|function|test_garbage_response_falls_back|Non-JSON response falls back to deterministic per-path split.
tests/test_dynamic.py|class|IkarusSpawnTests|Tests for Ikarus spawn behavior.
tests/test_dynamic.py|function|test_spawn_dry_run_returns_a_plan|Dry run returns a plan with assignments, spawned, bounced_to_adam, waves keys.
tests/test_dynamic.py|class|BridgeLaneRoutingTests|process_request routes claude lane to ask_claude and local-capable lanes through Ikarus.
tests/test_dynamic.py|function|test_claude_lane_calls_ask_claude_not_offload|Claude lane calls ask_claude and not offload.
tests/test_dynamic.py|function|test_unknown_or_missing_lane_fails_closed_not_claude|Unknown or missing lane fails closed, never reaching Claude.
tests/test_dynamic.py|function|test_lane_less_request_fails_closed_through_file_bridge|File without lane key fails closed through file bridge.
tests/test_dynamic.py|function|test_local_lane_eligible_runs_offload_not_claude|Eligible local lane runs offload, not Claude.
tests/test_dynamic.py|function|test_local_lane_ineligible_falls_through_to_claude|Ineligible local lane falls through to Claude.
tests/test_dynamic.py|function|test_local_only_lane_never_falls_through_to_claude|Local_only lane never falls through to Claude; fails with error.
daedalus/providers/codex_cli.py|constant|ROOT|root path of the project
daedalus/providers/codex_cli.py|constant|RUN_DIR|directory for run artifacts
daedalus/providers/codex_cli.py|constant|REPORT_SCHEMA|JSON schema for codex output validation
daedalus/providers/codex_cli.py|function|build_prompt|builds the prompt sent to codex exec
daedalus/providers/codex_cli.py|class|CodexCLIProvider|Provider for Codex CLI, handles egress gate and subprocess
tests/test_extension_manifest.py|module|ROOT|Root directory of the project
tests/test_extension_manifest.py|module|EXTENSION_DIR|Path to the vscode-agent-env extension directory
tests/test_extension_manifest.py|module|PACKAGE_JSON_PATH|Path to package.json manifest file
tests/test_extension_manifest.py|module|MAIN_JS_PATH|Path to extension.js source file
tests/test_extension_manifest.py|module|REGISTER_COMMAND_RE|Regex to extract command IDs from vscode.commands.registerCommand calls
tests/test_extension_manifest.py|module|REGISTER_WEBVIEW_RE|Regex to extract view IDs from vscode.window.registerWebviewViewProvider calls
tests/test_extension_manifest.py|module|REGISTER_TREEVIEW_RE|Regex to extract view IDs from vscode.window.registerTreeDataProvider calls
tests/test_extension_manifest.py|module|CREATE_TREEVIEW_RE|Regex to extract view IDs from vscode.window.createTreeView calls
tests/test_extension_manifest.py|module|CFG_GET_RE|Regex to extract configuration keys from cfg().get() calls
tests/test_extension_manifest.py|module|COMMAND_URI_RE|Regex to extract command IDs from command: URIs in markdown
tests/test_extension_manifest.py|function|load_manifest|Load and return the parsed package.json manifest
tests/test_extension_manifest.py|function|load_source|Load and return the raw text of extension.js
tests/test_extension_manifest.py|function|declared_commands|Return set of command IDs declared in manifest's contributes.commands
tests/test_extension_manifest.py|function|registered_commands|Return set of command IDs found via REGISTER_COMMAND_RE in source
tests/test_extension_manifest.py|function|declared_views|Return dict of view IDs to type from contributes.views.daedalus
tests/test_extension_manifest.py|function|registered_webview_ids|Return set of view IDs found via REGISTER_WEBVIEW_RE
tests/test_extension_manifest.py|function|registered_treeview_ids|Return set of view IDs found via REGISTER_TREEVIEW_RE or CREATE_TREEVIEW_RE
tests/test_extension_manifest.py|function|oncommand_activation_targets|Return set of command IDs from activationEvents that start with onCommand:
tests/test_extension_manifest.py|function|onview_activation_targets|Return set of view IDs from activationEvents that start with onView:
tests/test_extension_manifest.py|function|menu_command_refs|Return set of command IDs referenced in contributes.menus entries
tests/test_extension_manifest.py|function|viewswelcome_command_refs|Return set of command IDs extracted from viewsWelcome markdown via COMMAND_URI_RE
tests/test_extension_manifest.py|function|configured_property_short_keys|Return set of configuration property short keys (without daedalus. prefix)
tests/test_extension_manifest.py|function|configured_property_reads|Return set of configuration keys read via cfg().get() in source
tests/test_extension_manifest.py|function|parse_engine_version|Parse a engines.vscode version spec string into a (major, minor, patch) tuple
tests/test_extension_manifest.py|module|MANIFEST|Loaded manifest dictionary for use in tests
tests/test_extension_manifest.py|module|SOURCE|Loaded source text for use in tests
tests/test_extension_manifest.py|class|ManifestJsonTests|Test case for basic package.json structure fields
tests/test_extension_manifest.py|class|CommandRegistrationConsistencyTests|Test case for consistency between declared commands and registerCommand calls
tests/test_extension_manifest.py|class|ViewProviderConsistencyTests|Test case for consistency between declared views and provider registrations
tests/test_extension_manifest.py|class|ActivationEventConsistencyTests|Test case for consistency between activationEvents and declared commands/views
tests/test_extension_manifest.py|class|MenuAndWelcomeReferenceTests|Test case for consistency of command references in menus and viewsWelcome
tests/test_extension_manifest.py|class|ConfigurationPropertyUsageTests|Test case for declared configuration properties being read in source
tests/test_extension_manifest.py|class|MainEntryPointTests|Test case for existence of main and files entries
tests/test_extension_manifest.py|class|EngineVersionTests|Test case for engines.vscode presence and parseability
tests/test_preservation_fixtures.py|constant|BEFORE|Embedded verbatim text of docs/LOCAL_MODELS.md at commit f18ff5c
tests/test_preservation_fixtures.py|constant|AFTER_REGRESSION|Text with exactly the four measured regressions applied
tests/test_preservation_fixtures.py|constant|AFTER_LIVE|Unedited qwen2.5-coder:7b rewrite of BEFORE
tests/test_preservation_fixtures.py|constant|AFTER_LEGIT|Hand-written legitimate improvement with all facts kept
tests/test_typegraph_star_imports.py|constant|REPO_ROOT|Resolved path to repository root used for sys.path and scanning daedalus/.
tests/test_typegraph_star_imports.py|class|AStarDoesNotBindWhatAllExcludes|Tests star import does not bind names excluded by __all__; refusal counted; declaration node persists.
tests/test_typegraph_star_imports.py|class|AStarDoesNotBindAnUnderscoreName|Tests star import does not bind underscore-prefixed names.
tests/test_typegraph_star_imports.py|class|AnInvisibleStarMakesTheAnswerEnvironmental|Tests that when one star module is external, no edge to visible candidate; answer is environmental.
tests/test_typegraph_star_imports.py|class|AStarThatDisagreesWithAnExplicitBinding|Tests star vs explicit binding conflict produces no edge; both candidates named.
tests/test_typegraph_star_imports.py|class|PositiveControls|Tests that ordinary explicit bindings still resolve after fix.
tests/test_typegraph_star_imports.py|class|TwoVisibleStarsAreStillTheOldAmbiguity|Tests two visible stars with same name remain ambiguous.
tests/test_typegraph_star_imports.py|class|TheBlastRadiusIsMeasured|Tests no star import in daedalus/; dotted names still resolve.
tests/test_typegraph_star_imports.py|class|TheInvariantsSurviveTheFix|Tests fix preserves consistency, no edges from refused sites, reproducibility.
daedalus/wiki/links.py|constant|LINKS_VERSION|Version string '1'
daedalus/wiki/links.py|constant|MAX_LINKS_PER_PAGE|Bounded so one page cannot dominate an index.
daedalus/wiki/links.py|constant|MAX_MENTIONS_PER_PAGE|Maximum mentions per page for unlinked mentions.
daedalus/wiki/links.py|constant|MAX_LOCAL_NODES|Maximum nodes in local graph.
daedalus/wiki/links.py|constant|DOC|String 'doc'
daedalus/wiki/links.py|constant|CODE|String 'code'
daedalus/wiki/links.py|constant|TYPE|String 'type'
daedalus/wiki/links.py|constant|VAULT|String 'vault'
daedalus/wiki/links.py|class|WikiLink|Represents a wikilink with kind, target, anchor, alias, embed, line.
daedalus/wiki/links.py|function|extract_wikilinks|Every wikilink in a page body, in source order. No I/O.
daedalus/wiki/links.py|class|LinkIndex|Forward and reverse edges over one vault. Derived; regenerate and it is true.
daedalus/wiki/links.py|function|build_index|Link index over a vault's pages. Deterministic.
daedalus/wiki/links.py|function|backlinks|Pages that link TO this one. The panel users actually read.
daedalus/wiki/links.py|function|unlinked_mentions|Pages whose text names this page's title without linking it. Bounded.
daedalus/wiki/links.py|function|local_graph|The n-hop neighbourhood around one page, undirected. Depth 1 default, bounded.
daedalus/gui/lint.py|constant|BANNED_FACES|tuple of font family strings identified as generated defaults
daedalus/gui/lint.py|class|Metric|dataclass representing one measurement with key, value, unit, tier, note, offenders
daedalus/gui/lint.py|function|contrast_ratio|computes WCAG contrast ratio between two RGB tuples
daedalus/gui/lint.py|function|analyse|takes a capture dict and returns analysis dict with metrics
daedalus/gui/lint.py|function|compare|formats side-by-side comparison table of reports
daedalus/gui/lint.py|function|main|CLI entry point reading JSON capture files and producing report
daedalus/structcore/imports.py|function|extract_imports|Returns list of (raw, kind) import tuples for non-Python files; returns [] for Python.
daedalus/structcore/imports.py|function|resolve_internal|Maps an internal raw import string to a repo file path (posix) or None, best-effort for non-Python.
daedalus/structcore/imports.py|constant|_CANDIDATE_LANGS|Set of language names (java, kotlin, csharp, go, php) that treat all imports as internal candidates.
daedalus/benchmark.py|constant|PRICES|Provides USD per 1M token prices for provider cost calculation
daedalus/benchmark.py|constant|APPLY_IN|Overhead input tokens for Claude reviewing advisory output
daedalus/benchmark.py|constant|APPLY_OUT|Overhead output tokens for Claude reviewing advisory output
daedalus/benchmark.py|constant|POSTURE|Default posture flags for provider availability
daedalus/benchmark.py|class|Task|Represents a benchmark task with name, objective, paths, and token sizes
daedalus/benchmark.py|constant|TASKS|List of representative Task instances for benchmarking
daedalus/benchmark.py|function|run|Runs dry benchmark, computes routed vs baseline costs, prints table or returns JSON
daedalus/benchmark.py|function|run_live|Runs live benchmark by actually executing tasks via offload cascade, measures real costs/fallbacks
daedalus/benchmark.py|function|main|CLI entry point parsing arguments and invoking run or run_live
daedalus/shift.py|constant|SHIFT_VERSION|Version identifier for shift file format.
daedalus/shift.py|constant|SHIFT_REL_PATH|Relative path to the shift state file.
daedalus/shift.py|class|Shift|Data class representing a shift with goal, start, deadline, done_means, notes; provides time-aware status, remaining, elapsed, rendering.
daedalus/shift.py|function|load|Returns a Shift object from the state file, or an empty Shift if file missing or invalid.
daedalus/shift.py|function|start|Creates and atomically writes a new Shift with current time and given goal, until, done_means.
daedalus/shift.py|function|note|Appends a checkpoint to the shift state file under lock.
daedalus/shift.py|function|end|Deletes the shift state file.
daedalus/shift.py|function|main|Command-line interface for start/note/end/status.
daedalus/arch_memory.py|constant|ARCH_MEMORY_VERSION|Version string for the architecture memory format.
daedalus/arch_memory.py|constant|MEMORY_REL_PATH|Relative path where the architecture memory is saved.
daedalus/arch_memory.py|constant|STATE_REL_PATH|Relative path to the architecture state JSON.
daedalus/arch_memory.py|constant|MAX_LINES|Maximum number of lines in the architecture memory.
daedalus/arch_memory.py|constant|MAX_LINE_CHARS|Maximum characters per line.
daedalus/arch_memory.py|constant|NEWLINE|Newline character for file writing.
daedalus/arch_memory.py|class|ArchMemory|Dataclass representing the architecture memory with head, branch, dirty, lines, generated_at, version.
daedalus/arch_memory.py|function|build|Build an ArchMemory object from the repo root.
daedalus/arch_memory.py|function|save|Save an ArchMemory to a JSON file atomically.
daedalus/arch_memory.py|function|load|Load an ArchMemory from the JSON file.
daedalus/arch_memory.py|function|render|Render the architecture memory as a string for display.
daedalus/arch_memory.py|function|render_delta|Render what changed since last shown, or indicate no change.
daedalus/arch_memory.py|function|main|CLI entry point for the module.
daedalus/control_plane.py|constant|AUTONOMY_MODES|tuple of valid autonomy mode strings
daedalus/control_plane.py|constant|CAPABILITY_GATES|list of capability definitions with id, label, default, critical
daedalus/control_plane.py|function|claude_surface|reads Claude config files and returns dict representation of Claude surface for a project
daedalus/control_plane.py|function|codex_surface|reads AGENTS.md and returns dict representation of Codex surface for a project
daedalus/control_plane.py|function|resolve_autonomy|computes resolved autonomy mode for an agent-capability pair based on project config and capability gates
daedalus/control_plane.py|function|unified_profiles|merges agent roles, Claude subagents, Codex surface, and autonomy config into unified profile list

## DEPENDS

DEPENDS|daedalus/tools/inventory.py|daedalus.skills
DEPENDS|daedalus/tools/inventory.py|daedalus.tools.vet
DEPENDS|daedalus/structcore/topology.py|daedalus.structcore.graph
DEPENDS|daedalus/structcore/topology.py|daedalus.structcore.index
DEPENDS|tests/test_evolution_baseline.py|daedalus.kairos.evolution
DEPENDS|tests/test_evolution_baseline.py|daedalus.kairos.shadow_shell
DEPENDS|tests/test_operability_drill.py|tools.operability_drill
DEPENDS|tests/test_operability_drill.py|daedalus.spine.bootstrap
DEPENDS|tests/test_build.py|daedalus.build
DEPENDS|tests/test_build.py|daedalus.bookkeeper
DEPENDS|tests/test_artifacts.py|daedalus.structcore.artifacts
DEPENDS|daedalus/ikarus_chat.py|daedalus/agents_registry
DEPENDS|daedalus/ikarus_chat.py|daedalus/control_plane
DEPENDS|daedalus/ikarus_chat.py|daedalus/core
DEPENDS|daedalus/ikarus_chat.py|daedalus/hierarchy
DEPENDS|daedalus/ikarus_chat.py|daedalus/projects.resolve_repo_root
DEPENDS|tests/test_repair_blast_radius_write.py|daedalus.core
DEPENDS|tests/test_repair_blast_radius_write.py|daedalus.offload
DEPENDS|tests/test_repair_blast_radius_write.py|daedalus.metrics
DEPENDS|tests/test_mission_control.py|daedalus.core
DEPENDS|daedalus/doctor.py|daedalus.budget
DEPENDS|daedalus/doctor.py|daedalus.file_bridge
DEPENDS|daedalus/doctor.py|daedalus.providers.ollama
DEPENDS|tests/test_structcore_cnames.py|daedalus.structcore.clones
DEPENDS|tests/test_structcore_cnames.py|daedalus.structcore.languages
DEPENDS|tests/test_structcore_cnames.py|daedalus.structcore.parse
DEPENDS|daedalus/structcore/__main__.py|daedalus.structcore.index
DEPENDS|daedalus/status.py|daedalus.health
DEPENDS|daedalus/status.py|daedalus.file_bridge
DEPENDS|daedalus/status.py|daedalus.memory
DEPENDS|daedalus/status.py|daedalus.projects
DEPENDS|tests/test_promotion_forgery.py|daedalus.spine.bootstrap
DEPENDS|tests/test_promotion_forgery.py|daedalus.spine.attempt
DEPENDS|tests/test_offload_write_failclose.py|daedalus.metrics

## WRITES

WRITES|daedalus/ikarus_chat.py|.claude/agents/<name>.md (via chat function)
WRITES|daedalus/ikarus_chat.py|team config (via hierarchy.save_team)
WRITES|daedalus/ikarus_chat.py|agent registry (via agents_registry.create_role/update_role)
WRITES|daedalus/structcore/__main__.py|<json output file>
WRITES|tests/test_offload_write_failclose.py|<temporary directory>
WRITES|tests/test_bridge_enqueue_guard.py|runs/_test_outbox_guard/

## READS

READS|tests/test_tools_vet.py|daedalus/tools/vet.py
READS|daedalus/memory/__init__.py|memory/events.local.jsonl
READS|tests/test_self_policy_confinement.py|.agentenv/agentenv.json
READS|tests/test_structcore_graph.py|<temp directory read via build_index>
READS|tests/test_dotenv.py|.env.example
READS|tests/test_dotenv.py|conftest
READS|tests/test_churn.py|git history via subprocess
READS|daedalus/tools/inventory.py|skill directories (SKILL_SCOPES, USER_SKILL_DIRS)
READS|daedalus/tools/inventory.py|MCP config files (MCP_SCOPES)
READS|tests/test_evolution_baseline.py|daedalus/kairos/evolution.py

## CLAIMS

CLAIMS|tests/test_dynamic.py|When the local model is unreachable, the deterministic split is used.
CLAIMS|tests/test_dynamic.py|When the local model answers, its JSON breakdown drives the subtasks.
CLAIMS|tests/test_dynamic.py|process_request must send lane='claude' to ask_claude and local-capable lanes through Ikarus -- both fully mocked.
CLAIMS|daedalus/providers/codex_cli.py|egress-gated exactly like DeepSeek; hard egress gate; a denied path never reaches codex; codex is agentic and can read beyond declared paths
CLAIMS|tests/test_extension_manifest.py|the regexes are anchored to exact VS Code API call shape, not prose, making them safer than matching in comments
CLAIMS|tests/test_typegraph_star_imports.py|A star import can prove an AMBIGUITY. It can never prove a BINDING.
CLAIMS|tests/test_typegraph_star_imports.py|AnInvisibleStarMakesTheAnswerEnvironmental: Only ONE of the two stars is a module we can see. Whether the visible one supplies the name depends on what the other one exports, which is not a property of this source tree.
CLAIMS|tests/test_typegraph_star_imports.py|AStarThatDisagreesWithAnExplicitBinding: An explicit ``from`` binding AND a star that reaches a DIFFERENT declaration of the same name. Which wins is statement order plus the star module's ``__all__``; neither is readable here, so the answer is refused.
CLAIMS|tests/test_typegraph_star_imports.py|PositiveControls: "Refuse everything" must not be able to pass this file.
CLAIMS|tests/test_typegraph_star_imports.py|TwoVisibleStarsAreStillTheOldAmbiguity: The behaviour the fixture corpus already pinned must not have changed: two stars that BOTH declare the name were, and remain, ambiguous.
CLAIMS|tests/test_typegraph_star_imports.py|TheBlastRadiusIsMeasured: What the refusal costs, stated as a number rather than assumed to be small. If a star import ever appears under ``daedalus/`` this test fails and the cost has to be re-argued rather than silently paid.
CLAIMS|tests/test_typegraph_star_imports.py|TheInvariantsSurviveTheFix: The fix must not have bought I5 at the price of another invariant.
CLAIMS|daedalus/wiki/links.py|extract_wikilinks guarantees 'No resolution, no I/O.'
CLAIMS|daedalus/wiki/links.py|build_index guarantees 'Deterministic: every list sorted at the end.'
CLAIMS|daedalus/wiki/links.py|backlinks guarantees 'Pages that link TO this one. The panel users actually read.'
CLAIMS|daedalus/wiki/links.py|unlinked_mentions guarantees 'Bounded on purpose'
CLAIMS|daedalus/wiki/links.py|local_graph guarantees 'Depth 1 by default ... Bounded and it SAYS when it stopped'
CLAIMS|daedalus/gui/lint.py|stdlib only, by design: the capture needs a browser, the rules must not.
CLAIMS|daedalus/gui/lint.py|thresholds are stamped ASSUMED until the corpus is large enough to earn MEASURED
CLAIMS|daedalus/gui/lint.py|every metric returns its count AND the elements behind it
CLAIMS|daedalus/structcore/imports.py|Module docstring claims all-language import extraction and internal resolution.
CLAIMS|daedalus/structcore/imports.py|extract_imports returns [] for Python files.
CLAIMS|daedalus/structcore/imports.py|resolve_internal is best-effort for non-Python.
CLAIMS|daedalus/benchmark.py|It is a dry estimate that does not call any model
CLAIMS|daedalus/benchmark.py|LIVE benchmark actually runs each task through the offload cascade and measures real accept/escalate mix
CLAIMS|daedalus/shift.py|The clock is the operating system's, read fresh on every call.
CLAIMS|daedalus/shift.py|A shift is DECLARED, never inferred.
CLAIMS|daedalus/arch_memory.py|Provides a compact architecture summary that is true and small.
CLAIMS|daedalus/arch_memory.py|Freshness first: first line says which commit and whether it is still HEAD.
CLAIMS|daedalus/arch_memory.py|The summary is derived, never hand-maintained.
CLAIMS|daedalus/control_plane.py|presents one coherent operating model: unified agents, capabilities, autonomy policy, and Claude config status
CLAIMS|daedalus/bookkeeper.py|After every build session (and on demand), it renders docs/ARCHITECTURE.md into a styled, self-contained docs/architecture.html artifact, and files timestamped snapshots into docs/architecture_history/

## UNWIRED

UNWIRED|tests/test_spine_return_arc.py|test_a_shorter_actual_head_does_not_satisfy_a_longer_recorded_one
UNWIRED|tests/test_council_vendors.py|All test_* functions are defined but not called within this module (they are pytest test cases).
UNWIRED|daedalus/kairos/scheduler.py|_paths_overlap
UNWIRED|daedalus/config.py|external_write_lanes_for_repo (defined but not called within this file)
UNWIRED|daedalus/eval/mutate.py|Constant SKIP_PATH_PARTS defined but not referenced within this file.
UNWIRED|daedalus/eval/mutate.py|Constant SKIP_FUNCTIONS defined but not referenced within this file.
UNWIRED|daedalus/eval/mutate.py|Function covered_lines defined but not called within this file.
UNWIRED|daedalus/eval/mutate.py|Function _is_display_constant defined but not called within this file.

## SMELL

SMELL|daedalus/arch_memory.py|Module has multiple responsibilities (build, save, load, render, delta render) — possible god-object.
SMELL|daedalus/arch_memory.py|Duplication: staleness check logic in build and render functions.
SMELL|daedalus/control_plane.py|unified_profiles is a large orchestrator function with high coupling to multiple sub-functions and external modules
SMELL|daedalus/selftest.py|run() has multiple return paths and a finally block that conditionally modifies result dict, increasing risk of logic errors
SMELL|daedalus/kairos/archive.py|Deliberately mirrors OUTCOME_RANK from daedalus.eval.correctness to avoid import; test pins agreement.