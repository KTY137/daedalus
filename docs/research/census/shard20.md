# Census shard 20/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/shift_hook.py|function|main|Renders the shift line and prints it, may append warning if expired.
tests/test_adapters.py|function|test_subprocess_adapter_claude_profile|Claude profile has streaming True, resume False
tests/test_adapters.py|function|test_subprocess_adapter_codex_profile|Codex profile has streaming True
tests/test_adapters.py|function|test_subprocess_adapter_from_name|from_name returns adapter with correct capabilities
tests/test_adapters.py|function|test_runtime_profiles_match_verified_cli_contracts|RUNTIME_PROFILES has keys claude and codex with correct args
tests/test_adapters.py|function|test_from_name_unknown_raises|unknown name raises ValueError
tests/test_adapters.py|function|test_custom_adapter_honors_session_cwd_and_reports_exit|custom adapter respects cwd and reports exit code
tests/test_adapters.py|function|test_transport_record_round_trip_preserves_payload_and_provenance|serialization round-trip preserves payload and metadata
tests/test_adapters.py|function|test_events_dataclasses|event dataclasses can be instantiated with expected fields
daedalus/providers/base.py|class|ProviderCapabilities|frozen dataclass defining provider capabilities: name, can_write, local, trusted_with_ip, agentic
daedalus/providers/base.py|class|Provider|abstract base class for model providers with abstract methods available and run and helper _enforce_read_only
daedalus/langgraph_adapter.py|function|langgraph_available|returns True if langgraph is importable
daedalus/langgraph_adapter.py|function|build_graph|builds production graph when LangGraph is installed, raises RuntimeError if not installed, currently raises NotImplementedError
daedalus/shift_ticker.py|constant|BAR|Defines width of progress bar (28 characters).
daedalus/shift_ticker.py|function|render|Returns a formatted string showing shift status.
daedalus/shift_ticker.py|function|main|Entry point for command-line ticker that periodically prints shift status.
daedalus/structcore/metrics.py|function|lizard_available|Returns True if lizard library is available.
daedalus/structcore/metrics.py|function|file_metrics|Computes and returns a dictionary of per-file health metrics.
tests/test_kairos_evolution.py|class|DummyAdapter|A minimal adapter for testing that implements AgentAdapter with dummy methods and async event stream that yields SessionEnded.
tests/test_kairos_evolution.py|function|mock_worktree_manager|Fixture that returns a MagicMock simulating a worktree manager with create_worktree, commit_candidate, and has_changes methods.
tests/test_kairos_evolution.py|function|mock_adapter|Fixture that returns a DummyAdapter instance.
tests/test_kairos_evolution.py|function|test_shadow_shell_manager|Tests that ShadowShellManager.run_task returns a completed CandidateBranch with correct attributes and calls worktree manager methods.
tests/test_kairos_evolution.py|function|test_evolution_generate|Tests that EvolutionaryOrchestrator.generate_candidates yields the requested number of completed candidates.
tests/test_kairos_evolution.py|function|test_evolution_select|Tests that select_best returns the candidate with the highest score among completed ones.
tests/test_kairos_evolution.py|function|test_evolution_never_selects_a_failing_candidate|Tests that select_best returns None when the only candidate has a low score with an error.
daedalus/env.py|constant|ROOT|The resolved parent directory of the current file, assumed to be the project root.
daedalus/env.py|constant|ENV_PATH|The path to the .env file at the project root.
daedalus/env.py|constant|SECRET_KEYS|Tuple of environment variable keys considered secret.
daedalus/env.py|constant|PUBLIC_KEYS|Tuple of environment variable keys considered public.
daedalus/env.py|function|load_env|Loads .env file values into os.environ and returns redacted metadata from env_status.
daedalus/env.py|function|env_status|Returns a dictionary with environment status including provider configurations and public/secret key info.
daedalus/council/__init__.py|module|ENTRY_VERSION|re-exported constant from bus
daedalus/council/__init__.py|module|TURN_STATUS|re-exported constant from bus
daedalus/council/__init__.py|function|actor_id|re-exported from bus
daedalus/council/__init__.py|function|append_roster|re-exported from bus
daedalus/council/__init__.py|function|append_round|re-exported from bus
daedalus/council/__init__.py|function|append_turn|re-exported from bus
daedalus/council/__init__.py|function|council_store_path|re-exported from bus
daedalus/council/__init__.py|function|evidence_ref|re-exported from bus
daedalus/council/__init__.py|function|load_transcript|re-exported from bus
daedalus/council/__init__.py|function|transcript_head|re-exported from bus
daedalus/council/__init__.py|function|verify_chain|re-exported from bus
daedalus/kairos/shadow_shell.py|class|CandidateBranch|dataclass holding branch metadata and completion status
daedalus/kairos/shadow_shell.py|class|ShadowShellManager|manages spawning adapter in worktree and returns CandidateBranch
daedalus/mission_control.py|function|dashboard|re-exported from kairos.control
daedalus/mission_control.py|function|main_dashboard|re-exported from kairos.control
daedalus/mission_control.py|function|main_models|re-exported from kairos.control
daedalus/mission_control.py|function|main_review_diff|re-exported from kairos.control
daedalus/mission_control.py|function|main_squads|re-exported from kairos.control
daedalus/mission_control.py|function|main_watcher|re-exported from kairos.control
daedalus/mission_control.py|function|ollama_models|re-exported from kairos.control
daedalus/mission_control.py|function|quality_gates|re-exported from kairos.control
daedalus/mission_control.py|function|queue_timeline|re-exported from kairos.control
daedalus/mission_control.py|function|review_diff|re-exported from kairos.control
daedalus/mission_control.py|function|squads|re-exported from kairos.control
daedalus/mission_control.py|function|watcher_status|re-exported from kairos.control
daedalus/crew_hook.py|constant|MIN_PARALLEL|ensures minimum of 4 agents running in parallel
daedalus/crew_hook.py|constant|LIVE_WINDOW_S|defines 180-second window for live agent detection
daedalus/crew_hook.py|constant|TARGETS|provides named destinations for idle dispatch
daedalus/crew_hook.py|function|live_agents|returns tuple (count, names) of agents with recent task transcripts
daedalus/crew_hook.py|function|main|entry point that prints crew status and exits with code 0
daedalus/claude_detect.py|function|parse_frontmatter|returns dict of top-level scalar keys from YAML frontmatter block
daedalus/claude_detect.py|function|detect_claude_crew|scans .claude/agents/ directory and returns list of subagent metadata
daedalus/structcore/__init__.py|function|spec_for|guaranteed to provide the LanguageSpec for a given file extension or language name
daedalus/structcore/__init__.py|constant|SPECS|guaranteed to be the dictionary mapping language identifiers to LanguageSpec objects
daedalus/structcore/__init__.py|function|build_index|guaranteed to build a multi-language structural index from a repository root
daedalus/structcore/__init__.py|function|backend_status|guaranteed to report status of optional backends (tree_sitter, lizard)
daedalus/structcore/__init__.py|function|cached_index|guaranteed to return a cached or fresh index
daedalus/structcore/__init__.py|function|semantic_slice|guaranteed to perform semantic slicing (lazy import)
daedalus/structcore/__init__.py|function|estimate_tokens|guaranteed to estimate token counts (lazy import)
daedalus/structcore/__init__.py|class|ForestNode|guaranteed to represent a node in the knowledge forest
daedalus/structcore/__init__.py|class|ForestEdge|guaranteed to represent an edge in the knowledge forest
daedalus/structcore/__init__.py|class|ForestHyperedge|guaranteed to represent a hyperedge in the knowledge forest
daedalus/structcore/__init__.py|class|KnowledgeForest|guaranteed to be the full knowledge forest structure
daedalus/structcore/__init__.py|function|build_knowledge_forest|guaranteed to construct a KnowledgeForest from an index
daedalus/structcore/__init__.py|class|ForestHierarchy|guaranteed to represent a hierarchical slice of the forest
daedalus/structcore/__init__.py|class|DSSConfig|guaranteed to hold configuration for DSS (Diffusion-Synthesis-Sampling)
daedalus/structcore/__init__.py|class|ContextPlan|guaranteed to represent a context plan for DSS
daedalus/structcore/__init__.py|class|DSSReceipt|guaranteed to be the receipt from a DSS operation
daedalus/structcore/__init__.py|class|DSSResult|guaranteed to be the result of a DSS operation
daedalus/structcore/__init__.py|function|build_forest_hierarchy|guaranteed to build a ForestHierarchy
daedalus/structcore/__init__.py|function|semantic_super_sample|guaranteed to perform super-sampling of forest
daedalus/structcore/__init__.py|class|DocumentSpec|guaranteed to specify a document type
daedalus/structcore/__init__.py|function|doc_spec_for|guaranteed to return DocumentSpec for a file extension
daedalus/structcore/__init__.py|constant|DOC_SPECS|guaranteed to be the mapping of extensions to DocumentSpec
daedalus/structcore/__init__.py|function|documents_enabled|guaranteed to check if document indexing is enabled
daedalus/structcore/__init__.py|constant|DOCUMENT_KIND|guaranteed to be the constant representing document node kind
daedalus/structcore/__init__.py|class|DocSection|guaranteed to represent a section within a document
daedalus/structcore/__init__.py|class|DocSkeleton|guaranteed to represent the skeleton of a document
daedalus/structcore/__init__.py|class|DocumentParse|guaranteed to hold the parsed result of a document
daedalus/structcore/__init__.py|function|parse_document|guaranteed to parse a document file
daedalus/structcore/__init__.py|function|document_skeleton|guaranteed to extract the skeleton of a document
daedalus/structcore/__init__.py|function|is_document|guaranteed to check if a file path is a document
daedalus/structcore/__init__.py|function|code_modules|guaranteed to return code module paths
daedalus/structcore/__init__.py|function|document_modules|guaranteed to return document module paths
daedalus/structcore/__init__.py|function|types_enabled|guaranteed to check if type indexing is enabled
daedalus/structcore/__init__.py|constant|TYPE_NODE_KIND|guaranteed to be the constant for type node kind
daedalus/structcore/__init__.py|constant|FIELD_NODE_KIND|guaranteed to be the constant for field node kind
daedalus/structcore/__init__.py|constant|RELATIONS|guaranteed to be the dictionary of relation definitions
daedalus/structcore/__init__.py|constant|DEFAULT_HUB_CAP|guaranteed to be the default hub capacity
daedalus/structcore/__init__.py|class|TypeGraph|guaranteed to be the type graph structure
daedalus/structcore/__init__.py|function|resolve_type_graph|guaranteed to resolve the type graph from an index
daedalus/structcore/__init__.py|function|type_node_id|guaranteed to generate a type node ID
daedalus/structcore/__init__.py|function|field_node_id|guaranteed to generate a field node ID
daedalus/structcore/__init__.py|function|is_type_node_id|guaranteed to check if a string is a type node ID
daedalus/router.py|constant|ROOT|guaranteed to be the absolute path of the parent of the daedalus package
daedalus/router.py|constant|AGENT_DIR|guaranteed to be the built-in agents directory (ROOT / 'agents')
daedalus/router.py|constant|TEMPLATE_AGENT_DIR|guaranteed to be the template agents directory (ROOT / 'templates' / 'agents')
daedalus/router.py|function|load_agents|guaranteed to load agent role JSON files from the appropriate directory, optionally filtering by active_agents
daedalus/router.py|function|route_task|guaranteed to return the best-matching agent dict for a given objective and paths
daedalus/enforce.py|module|enforce|Provides functions to enforce daedalus harness instructions.
daedalus/enforce.py|constant|BEGIN|Marker for start of enforced block.
daedalus/enforce.py|constant|END|Marker for end of enforced block.
daedalus/enforce.py|function|enforce_repo|Enforces harness by adding blocks to AGENTS.md and CLAUDE.md and writing state file.
daedalus/enforce.py|function|main|CLI entry point for enforce command.
tests/test_bookkeeper.py|module|test_bookkeeper|Unit tests for the bookkeeper module.
tests/test_bookkeeper.py|class|RenderTests|Tests for markdown rendering.
tests/test_bookkeeper.py|class|HistoryTests|Tests for history snapshot behavior.
daedalus/observe/__init__.py|module|observe|Exports behavioral observation constructs.
daedalus/observe/__init__.py|constant|SHAPE_VERSION|Version constant for shape module.
daedalus/observe/__init__.py|constant|ARRAY|Shape constant.
daedalus/observe/__init__.py|constant|TABLE|Shape constant.
daedalus/observe/__init__.py|constant|RECORD|Shape constant.
daedalus/observe/__init__.py|constant|SEQUENCE|Shape constant.
daedalus/observe/__init__.py|constant|TREE|Shape constant.
daedalus/observe/__init__.py|constant|SCALAR|Shape constant.
daedalus/observe/__init__.py|constant|TEXT|Shape constant.
daedalus/observe/__init__.py|constant|BINARY|Shape constant.
daedalus/observe/__init__.py|constant|OPAQUE|Shape constant.
daedalus/observe/__init__.py|class|Shape|Base shape class.
daedalus/observe/__init__.py|class|ShapeConflict|Exception for shape conflicts.
daedalus/observe/__init__.py|function|describe|Describe a live object's shape.
daedalus/observe/__init__.py|function|compare_declared|Compare declared shape to observed shape.

## DEPENDS

DEPENDS|tests/test_context_plan.py|daedalus.context_plan
DEPENDS|tests/test_context_plan.py|daedalus.memory.embeddings
DEPENDS|tests/test_context_plan.py|daedalus.structcore
DEPENDS|daedalus/shift_hook.py|daedalus.shift
DEPENDS|daedalus/arch_hook.py|daedalus.arch_memory
DEPENDS|tests/test_adapters.py|daedalus.adapters
DEPENDS|tests/test_adapters.py|daedalus.adapters.events
DEPENDS|daedalus/shift_ticker.py|daedalus.shift
DEPENDS|daedalus/structcore/metrics.py|daedalus.structcore.languages
DEPENDS|daedalus/structcore/metrics.py|daedalus.structcore.parse
DEPENDS|tests/test_kairos_evolution.py|daedalus.kairos.shadow_shell
DEPENDS|tests/test_kairos_evolution.py|daedalus.kairos.evolution
DEPENDS|tests/test_kairos_evolution.py|daedalus.adapters.base
DEPENDS|tests/test_kairos_evolution.py|daedalus.adapters.events
DEPENDS|daedalus/council/__init__.py|daedalus.council.bus
DEPENDS|daedalus/kairos/shadow_shell.py|daedalus.adapters.base
DEPENDS|daedalus/kairos/shadow_shell.py|daedalus.adapters.events
DEPENDS|daedalus/kairos/shadow_shell.py|daedalus.kairos.worktree
DEPENDS|daedalus/mission_control.py|daedalus.kairos.control
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.languages
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.index
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.markdown
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.forest
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.typegraph
DEPENDS|daedalus/structcore/__init__.py|daedalus.structcore.dss
DEPENDS|daedalus/router.py|json
DEPENDS|daedalus/router.py|pathlib.Path
DEPENDS|daedalus/enforce.py|daedalus.config
DEPENDS|daedalus/enforce.py|daedalus.projects
DEPENDS|tests/test_bookkeeper.py|daedalus.bookkeeper
DEPENDS|daedalus/observe/__init__.py|daedalus.observe.shape

## READS

READS|daedalus/enforce.py|AGENTS.md
READS|daedalus/enforce.py|CLAUDE.md
READS|tests/test_bookkeeper.py|bk.SOURCE

## CLAIMS

CLAIMS|daedalus/structcore/metrics.py|Per-file health metrics — the 'code health' signal, comment-aware per language. Stdlib-only baseline... If lizard is installed, real cyclomatic complexity is added.
CLAIMS|daedalus/env.py|The web UI and VS Code wrapper must never receive secret values; only redacted readiness metadata is exposed.
CLAIMS|daedalus/env.py|Returns redacted metadata only (from load_env docstring)
CLAIMS|daedalus/council/__init__.py|council records are never an input to memory recall
CLAIMS|daedalus/council/__init__.py|falsification protocol is stated in advance and module is deleted if it fails
CLAIMS|daedalus/kairos/shadow_shell.py|adapter is required to honor cwd at process launch
CLAIMS|daedalus/crew_hook.py|counts what is actually running to enforce minimum parallel agents
CLAIMS|daedalus/claude_detect.py|parses frontmatter with stdlib only, best-effort and dependency-free
CLAIMS|daedalus/structcore/__init__.py|stdlib-first — works with ZERO third-party deps
CLAIMS|daedalus/structcore/__init__.py|degrade cleanly — if tree_sitter_language_pack is installed, unit-level clone detection and precise metrics light up
CLAIMS|daedalus/structcore/__init__.py|derive, don't maintain — regenerate and it is true by construction
CLAIMS|tests/test_bookkeeper.py|Tests pin the markdown renderer's core constructs and change-detection/history behavior.
CLAIMS|daedalus/observe/__init__.py|Deliberately outside structcore, feeds observed provenance edges.

## UNWIRED

UNWIRED|daedalus/crew_hook.py|main (no caller visible in slice)
UNWIRED|daedalus/claude_detect.py|detect_claude_crew (no caller visible in slice)
UNWIRED|daedalus/router.py|_norm (private, used only in route_task)