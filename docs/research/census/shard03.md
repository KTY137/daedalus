# Census shard 3/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/providers/ollama.py|function|keep_alive_value|Return OLLAMA_KEEP_ALIVE env var or default
daedalus/providers/ollama.py|function|warm_model|Pin model in VRAM via Ollama native endpoint
daedalus/providers/ollama.py|function|warm_model_async|Fire-and-forget warm_model on daemon thread
daedalus/providers/ollama.py|class|OllamaProvider|Ollama provider with write capabilities and guarded filesystem tools
daedalus/kairos/gated_writes.py|function|rebase_declared_path|Repo-relative form of one declared write path
daedalus/kairos/gated_writes.py|function|rebase_declared_paths|Apply rebase_declared_path to a list of paths
daedalus/kairos/gated_writes.py|class|GatedCandidate|One write Assignment's outcome from Phase 1, carrying spec and result
daedalus/kairos/gated_writes.py|class|PromotionUnavailable|The cross-process promotion lock could not be taken
daedalus/kairos/gated_writes.py|function|gate_candidates|PHASE 1: run every write Assignment through TaskAttempt concurrently
tests/test_typegraph_parse.py|constant|CORPUS|Tuple of fixture file names as repo-relative POSIX paths.
tests/test_typegraph_parse.py|class|CorpusIsWhatWeThinkItIs|Verifies the fixture corpus file list is documented.
tests/test_typegraph_parse.py|class|UnitsAreUntouched|Ensures the new entry point is a strict superset of the old one and that type records are not shaped like code units.
tests/test_typegraph_parse.py|class|DeclarationKinds|Tests classification of declaration shapes (dataclass, class, namedtuple, typeddict, enum, protocol) and other declaration-level properties.
tests/test_typegraph_parse.py|class|Fields|Tests field extraction from dataclasses, classes, enums, typeddicts, namedtuples, instance attributes, and annotated attributes.
tests/test_typegraph_parse.py|class|Signatures|Tests signature extraction including parameter positions, defaults, annotations, async, decorators, owner, and uniqueness per code unit.
tests/test_typegraph_index.py|constant|REPO_ROOT|Root path of the daedalus repo
tests/test_typegraph_index.py|constant|FIXTURE|Path to the typegraph test fixture
tests/test_typegraph_index.py|constant|COUNTS_BASELINE|Baseline counts for the fixture
tests/test_typegraph_index.py|constant|EDGES_BY_RELATION_BASELINE|Baseline edge counts by relation
tests/test_typegraph_index.py|constant|OUTCOMES_BASELINE|Baseline resolution outcomes
tests/test_typegraph_index.py|constant|NODE_KEYS|Expected keys in every type node
tests/test_typegraph_index.py|constant|TYPES_KEYS|Expected keys in the types block
tests/test_typegraph_index.py|constant|ADDITIVE_KEYS|Keys that must be byte-identical between builds
tests/test_typegraph_index.py|class|_OnAndOff|Base class for tests comparing builds with and without types
tests/test_typegraph_index.py|class|TheLayerIsAdditive|Tests that the layer does not modify existing blocks
tests/test_typegraph_index.py|class|TheFenceDenominatorCannotMove|Tests that graph nodes and dominance are unchanged
tests/test_typegraph_index.py|class|TheResolverIsUntouched|Tests that the resolver is not polluted by type nodes
tests/test_typegraph_index.py|class|TheBlocksHaveTheDocumentedShape|Tests that the published blocks have the expected structure and values
tests/test_typegraph_index.py|class|ItSaysWhatItRefusedToDo|Tests coverage buckets and self-reported confidence
tests/test_typegraph_determinism.py|constant|REPO_ROOT|Root of the repository, used to locate fixtures and insert into sys.path for subprocesses
tests/test_typegraph_determinism.py|constant|FIXTURE|Path to the typegraph fixture directory
tests/test_typegraph_determinism.py|constant|ANY_SITES|Number of bare Any sites in the fixture that should be counted as unresolved
tests/test_typegraph_determinism.py|constant|ANY_INSIDE_SITES|Number of non-bare Any sites (Any inside type hints) in the fixture
tests/test_typegraph_determinism.py|constant|AMBIGUOUS_ATTEMPTS|Number of ambiguous attempts (e.g., Result from two imports) in the fixture
tests/test_typegraph_determinism.py|constant|UNRESOLVED_ATTEMPTS|Number of unresolved attempts (names that cannot be resolved) in the fixture
tests/test_typegraph_determinism.py|constant|UNION_IDS|Expected union IDs for the three union sites in the fixture
tests/test_typegraph_determinism.py|constant|UNION_EDGES|Expected number of union member edges (6)
tests/test_typegraph_determinism.py|constant|SEEDS|PYTHONHASHSEED values to test: 0, 1, 2, 12345, 98765, random
tests/test_typegraph_determinism.py|function|setUpModule|Saves and clears environment variables that could affect determinism, sets a temporary cache directory
tests/test_typegraph_determinism.py|function|tearDownModule|Restores saved environment variables and removes temporary directories
tests/test_typegraph_determinism.py|class|ByteIdentityAcrossHashSeeds|Tests that the type layer output is byte-identical across different PYTHONHASHSEED values, including parallel scan
daedalus/structcore/parse.py|class|CodeUnit|Represents a parsed code unit with language, module, name, lines, loc, and source.
daedalus/structcore/parse.py|function|tree_sitter_available|Returns True if tree_sitter_language_pack is importable.
daedalus/structcore/parse.py|function|extract_units|Returns list of CodeUnit from a module text based on language spec.
daedalus/structcore/parse.py|function|python_units_and_imports|Returns tuple of CodeUnits and import records from a single parse.
daedalus/structcore/parse.py|function|python_import_records|Returns raw import records from a Python source text.
daedalus/structcore/parse.py|function|resolve_python_imports|Resolves raw import records to set of internal dotted modules.
daedalus/structcore/parse.py|function|python_imports|Returns set of internal modules imported by a Python source (parse+resolve).
daedalus/structcore/parse.py|constant|TYPE_FACTS_VERSION|Version string for type facts format.
daedalus/structcore/parse.py|constant|ANY_SENTINEL|Sentinel string for bare Any annotation.
daedalus/structcore/parse.py|class|TypeDecl|Represents a type declaration with qualname, kind, lines, bases, decorators.
daedalus/structcore/parse.py|class|FieldDecl|Represents a field declaration with owner, annotation, origin.
daedalus/structcore/parse.py|class|ParamDecl|Represents a parameter declaration with position, annotation, kind.
daedalus/structcore/parse.py|class|SignatureDecl|Represents a function signature with params, returns, receiver.
daedalus/structcore/parse.py|class|AliasImport|Represents a name binding from an import statement.
daedalus/structcore/parse.py|class|PyTypeFacts|Container for all type facts from one Python file.
daedalus/structcore/parse.py|class|Annotation|Normalized reading of a raw annotation string.
daedalus/structcore/typegraph.py|constant|TYPE_GRAPH_VERSION|Guarantees version string for the type graph.
daedalus/structcore/typegraph.py|constant|TYPE_NODE_KIND|Guarantees node kind string for types.
daedalus/structcore/typegraph.py|constant|FIELD_NODE_KIND|Guarantees node kind string for fields.
daedalus/structcore/typegraph.py|constant|REL_HAS_FIELD|Guarantees relation name for has_field.
daedalus/structcore/typegraph.py|constant|REL_FIELD_TYPE|Guarantees relation name for field_type.
daedalus/structcore/typegraph.py|constant|REL_INHERITS|Guarantees relation name for inherits.
daedalus/structcore/typegraph.py|constant|REL_CONSUMES|Guarantees relation name for consumes.
daedalus/structcore/typegraph.py|constant|REL_PRODUCES|Guarantees relation name for produces.
daedalus/structcore/typegraph.py|constant|REL_ALIAS_OF|Guarantees relation name for alias_of.
daedalus/structcore/typegraph.py|constant|RELATIONS|Guarantees tuple of all relation names.
daedalus/structcore/typegraph.py|constant|DEFAULT_HUB_CAP|Guarantees default hub cap for relation fan-in.
daedalus/structcore/typegraph.py|constant|STRUCTURAL_MIN_MEMBERS|Guarantees minimum members for structural matching.
daedalus/structcore/typegraph.py|constant|STRUCTURAL_MAX_MATCHES|Guarantees maximum matches for structural matching.
daedalus/structcore/typegraph.py|constant|RESOLVED|Guarantees outcome string for resolved.
daedalus/structcore/typegraph.py|constant|UNRESOLVED|Guarantees outcome string for unresolved.
daedalus/structcore/typegraph.py|constant|AMBIGUOUS|Guarantees outcome string for ambiguous.
daedalus/structcore/typegraph.py|constant|EXTERNAL|Guarantees outcome string for external.
daedalus/structcore/typegraph.py|constant|BUILTIN|Guarantees outcome string for builtin.
daedalus/structcore/typegraph.py|constant|VOCABULARY|Guarantees outcome string for vocabulary.
daedalus/structcore/typegraph.py|function|type_node_id|Returns a forest node id for a type declaration.
daedalus/structcore/typegraph.py|function|field_node_id|Returns a forest node id for one member of a type.
daedalus/structcore/typegraph.py|function|function_ref|Returns stable identity of a function for edge attributes.
daedalus/structcore/typegraph.py|function|is_type_node_id|Checks if a node id is a type or field node id.
daedalus/structcore/typegraph.py|class|PlainNaming|Provides the repo-root dotted namespace without importing index.
daedalus/structcore/typegraph.py|function|types_by_file|Returns the resolution table keyed by file and qualname, invariant I2.
daedalus/structcore/typegraph.py|class|TypeGraph|Represents the resolved layer with nodes, edges, coverage.
tests/test_skills.py|function|write_skill|Helper to create a skill directory with optional text.
tests/test_skills.py|class|TempRoot|Base class for tests that manages a temporary directory.
tests/test_skills.py|class|NothingExecutes|Tests that the skills module does not execute anything (subprocess, eval, etc.).
tests/test_skills.py|class|NoSafetyAuthority|Tests that Skill has no safety-decision fields.
tests/test_skills.py|class|SpecPinning|Tests that spec constants (MAX_NAME_CHARS, etc.) are correct.
tests/test_skills.py|class|Parsing|Tests successful loading of minimal and full skill files.
tests/test_skills.py|class|Refusals|Tests error cases: missing frontmatter, bounds, traversal, etc.
daedalus/budget.py|constant|ROOT|Resolved project root directory.
daedalus/budget.py|constant|DEFAULT_LEDGER_PATH|Default path for the budget ledger file.
daedalus/budget.py|constant|ENV_LEDGER|Environment variable name to override the ledger path.
daedalus/budget.py|constant|ENV_CEILING|Environment variable name to set the budget ceiling in USD.
daedalus/budget.py|constant|ENV_MAX_CALLS|Environment variable name to set the maximum number of calls.
daedalus/budget.py|constant|ENV_PERIOD|Environment variable name to set the budget period.
daedalus/budget.py|constant|ENV_ON_UNKNOWN|Environment variable name to set behaviour on unknown price.
daedalus/budget.py|constant|DEFAULT_CEILING_USD|Default cap of $5.00; spending above is a deliberate decision.
daedalus/budget.py|constant|DEFAULT_MAX_CALLS|Default max calls = 40; second axis beyond price.
daedalus/budget.py|constant|UNKNOWN_CALL_USD|Cost of one unknown-price call: $5.00, exceeds most expensive measured call.
daedalus/budget.py|constant|PERIODS|Tuple of available ledger periods: ("day", "total").
daedalus/budget.py|constant|DEFAULT_PERIOD|Default budget period: "day".
daedalus/budget.py|constant|LOCK_TIMEOUT_S|Timeout for the cross-process lock: 30 seconds.
daedalus/budget.py|constant|MAX_ENTRIES|Maximum number of ledger entries: 500.
daedalus/budget.py|constant|ENV_SUBSCRIPTIONS|Environment variable for subscription vendor names.
daedalus/budget.py|constant|FREE_VENDORS|Frozenset of vendors that cost nothing because no bytes leave the machine: {"local", "local_inference"}.
daedalus/budget.py|class|BudgetError|Base for every refuse; callers should catch to report, never retry.
daedalus/budget.py|class|BudgetUnavailable|Refusal because budget state could not be established.
daedalus/budget.py|class|BudgetRefused|Refusal because ceiling would be crossed; carries all numbers.
daedalus/budget.py|class|UnknownPrice|Strict mode refusal when price cannot be determined.
daedalus/budget.py|class|VendorPrice|Dataclass holding vendor name and pricing bounds (flat worst-case and optional per-token rates).
daedalus/budget.py|class|Estimate|Dataclass for what a call is assumed to cost before execution.
daedalus/budget.py|class|BudgetState|Dataclass describing current budget state: ceiling, spent, reserved, calls, period.
daedalus/budget.py|class|Reservation|Represents money committed to the ledger for a call not yet happened; provides settle and release methods.
daedalus/budget.py|function|subscription_vendors|Returns frozenset of vendors declared flat-rate via environment variable.
daedalus/budget.py|function|price_call|Upper-bounds the cost of specified number of calls to a vendor, considering host, tokens, and unknown price policy.
daedalus/eval/harness.py|function|all_tasks|Returns hardcoded TASKS plus minted tasks
daedalus/eval/harness.py|function|eval_task_tier1|Deterministic Tier-1 result for a single task, never raises
daedalus/eval/harness.py|function|run_tier1|Run Tier 1 over tasks, returns per-provenance aggregates
daedalus/eval/harness.py|function|eval_task_arms|Deterministic A/B/C comparison for one task
daedalus/council/canary.py|constant|CANARY_STATUSES|Closed vocabulary: ok, wrong_answer, timeout, unavailable, error
daedalus/council/canary.py|constant|SEVERITIES|Closed vocabulary: liveness, quality
daedalus/council/canary.py|constant|SCHEMA_VERSION|Schema version string: dcanary/1
daedalus/council/canary.py|constant|DEFAULT_HISTORY_PATH|Default path: runs/canary/history.jsonl
daedalus/council/canary.py|constant|DEFAULT_BENCH_OLLAMA_HOST|Re-exported from vendors
daedalus/council/canary.py|constant|DEFAULT_LOCAL_OLLAMA_HOST|Re-exported from vendors
daedalus/council/canary.py|constant|DEFAULT_PER_PROBE_TIMEOUT_S|Default: 120.0
daedalus/council/canary.py|constant|DEFAULT_WALL_CLOCK_S|Default: 420.0
daedalus/council/canary.py|constant|DEFAULT_MAX_PARALLEL|Default: 4
daedalus/council/canary.py|constant|DEFAULT_OLLAMA_MODEL|Default: qwen2.5-coder:7b
daedalus/council/canary.py|constant|VENDOR_KEYS|Tuple: anthropic, openai, google, local
daedalus/council/canary.py|class|ProbeSpec|Dataclass for a probe with name, severity, build/check/expect callables
daedalus/council/canary.py|class|ProbeResult|Dataclass for one probe outcome including vendor, model, endpoint, status, etc.
daedalus/council/canary.py|constant|PROBES|Tuple of four ProbeSpec instances
daedalus/council/canary.py|constant|QUICK_PROBE|Name: arrival
daedalus/council/canary.py|function|probes_for|Returns tuple of probes by name or all
daedalus/council/canary.py|function|new_nonce|Generates a fresh nonce string
daedalus/council/canary.py|function|build_arrival|Builds arrival prompt
daedalus/council/canary.py|function|check_arrival|Checks arrival reply
daedalus/council/canary.py|function|build_instruction|Builds instruction prompt
daedalus/council/canary.py|function|check_instruction|Checks instruction reply
daedalus/council/canary.py|function|build_anchoring|Builds anchoring prompt
daedalus/council/canary.py|function|check_anchoring|Checks anchoring reply
daedalus/council/canary.py|function|build_comprehension|Builds comprehension prompt
daedalus/council/canary.py|function|check_comprehension|Checks comprehension reply
daedalus/core.py|constant|ROOT|Absolute path to the repository root (parent of daedalus/)
daedalus/core.py|constant|OUTBOX|Path to the outbox directory for pending work
daedalus/core.py|constant|INBOX|Path to the inbox directory for incoming reports
daedalus/core.py|constant|ARCHIVE|Path to the archive directory for processed items
daedalus/core.py|constant|DEFAULT_OLLAMA|Default Ollama server URL: http://127.0.0.1:11434
daedalus/core.py|constant|DEFAULT_SQUADS|Mapping of squad names to default agent lists

## DEPENDS

DEPENDS|daedalus/cli.py|daedalus.projects
DEPENDS|daedalus/cli.py|daedalus.build
DEPENDS|daedalus/cli.py|daedalus.config
DEPENDS|daedalus/cli.py|daedalus.accelerators
DEPENDS|daedalus/cli.py|daedalus.context_plan
DEPENDS|daedalus/cli.py|daedalus.structcore.churn
DEPENDS|daedalus/cli.py|daedalus.structcore.index
DEPENDS|daedalus/cli.py|daedalus.agents_registry
DEPENDS|daedalus/cli.py|daedalus.categories
DEPENDS|daedalus/cli.py|daedalus.kairos.drafts
DEPENDS|daedalus/cli.py|daedalus.council.session
DEPENDS|daedalus/cli.py|daedalus.council.vendors
DEPENDS|daedalus/structcore/typegraph.py|daedalus/structcore/parse.py
DEPENDS|tests/test_skills.py|daedalus.skills
DEPENDS|daedalus/budget.py|daedalus.sensitivity
DEPENDS|daedalus/eval/harness.py|daedalus.structcore.index
DEPENDS|daedalus/eval/harness.py|daedalus.structcore.languages
DEPENDS|daedalus/eval/harness.py|daedalus.structcore.parse
DEPENDS|daedalus/eval/harness.py|daedalus.structcore.slice
DEPENDS|daedalus/eval/harness.py|daedalus.structcore.tokens (optional)
DEPENDS|daedalus/eval/harness.py|.mint
DEPENDS|daedalus/eval/harness.py|.tasks
DEPENDS|daedalus/council/canary.py|daedalus.council.session
DEPENDS|daedalus/council/canary.py|daedalus.council.vendors
DEPENDS|daedalus/core.py|daedalus.metrics
DEPENDS|daedalus/core.py|daedalus.claude_bridge
DEPENDS|daedalus/core.py|daedalus.claude_detect
DEPENDS|daedalus/core.py|daedalus.projects
DEPENDS|daedalus/core.py|daedalus.providers
DEPENDS|daedalus/core.py|daedalus.router
DEPENDS|daedalus/core.py|daedalus.status
DEPENDS|daedalus/core.py|daedalus.schemas
DEPENDS|daedalus/core.py|daedalus.spine.picker
DEPENDS|daedalus/core.py|daedalus.spine.bootstrap

## WRITES

WRITES|tests/test_typegraph_index.py|_TMP_CACHE (temp dir)
WRITES|tests/test_typegraph_determinism.py|temporary directories created by tempfile.mkdtemp (cleaned up in tearDownModule)
WRITES|daedalus/cli.py|.agentenv/agentenv.json (via init_repo)
WRITES|daedalus/cli.py|.agentenv/agents/ (via agents_registry.create_role)
WRITES|daedalus/cli.py|.agentenv/categories.json (via categories.update)
WRITES|daedalus/cli.py|runs/council/ (via council.session)

## READS

READS|daedalus/spine/attempt.py|worktree contents for diff generation
READS|daedalus/providers/ollama.py|environment variables OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_KEEP_ALIVE
READS|daedalus/providers/ollama.py|repo_root files via read_file tool
READS|daedalus/kairos/gated_writes.py|git repository (via git rev-parse)
READS|daedalus/kairos/gated_writes.py|spine ledger database
READS|daedalus/kairos/gated_writes.py|project configuration
READS|tests/test_typegraph_parse.py|tests/fixtures/typegraph/
READS|tests/test_typegraph_index.py|FIXTURE (fixture directory)
READS|tests/test_typegraph_determinism.py|tests/fixtures/typegraph/ directory
READS|tests/test_skills.py|daedalus/skills.py (reads source to check for forbidden tokens)

## CLAIMS

CLAIMS|tests/test_skills.py|'a bundled script is never even OPENED, enforced by recording every call to builtins.open'
CLAIMS|tests/test_skills.py|'Skill carries no lane, provider, host or path-policy field'
CLAIMS|tests/test_skills.py|'allowed-tools is recorded as a claim, never parsed into a permission'
CLAIMS|tests/test_skills.py|'every bound refuses, and refuses with a reason a human can act on'
CLAIMS|tests/test_skills.py|'a malformed skill is REPORTED as a defect and never silently skipped'
CLAIMS|tests/test_skills.py|'../ in a skill name is refused'
CLAIMS|tests/test_skills.py|'skill text rendered for a model is fenced as untrusted data'
CLAIMS|tests/test_skills.py|'Every test runs offline against temp directories. No model, no network.'
CLAIMS|daedalus/budget.py|A HARD CEILING on money. Ledger-backed, cross-process, fail-closed.
CLAIMS|daedalus/budget.py|FAIL CLOSED. If the budget state cannot be read... the answer is BudgetUnavailable, never 'allow'.
CLAIMS|daedalus/budget.py|THE CHECK HAPPENS BEFORE THE CALL.
CLAIMS|daedalus/budget.py|REFUSAL IS LOUD AND NAMED.
CLAIMS|daedalus/budget.py|CONCURRENCY... under a cross-process advisory lock
CLAIMS|daedalus/budget.py|AN UNKNOWN PRICE IS NOT A FREE PRICE.
CLAIMS|daedalus/eval/harness.py|_correctness_task_row: Refuses correctness tasks to avoid inflating recall metrics
CLAIMS|daedalus/eval/harness.py|eval_task_tier1: NEVER RAISES; catches exceptions as ERRORED rows
CLAIMS|daedalus/eval/harness.py|run_tier1: No top-level blended recall/compression; reports per-provenance-tier
CLAIMS|daedalus/eval/harness.py|_by_provenance: Callers must pre-filter errored and focus_withheld rows
CLAIMS|daedalus/eval/harness.py|_recall: Empty label list -> recall 1.0 vacuously
CLAIMS|daedalus/eval/harness.py|_task_error_row: Absent recall/compression keys cause KeyError if not filtered
CLAIMS|daedalus/eval/harness.py|_focus_withheld_row: Absent recall/compression keys ensure honest aggregation
CLAIMS|daedalus/eval/harness.py|_whole_repo_text: New default walks entire repo untruncated
CLAIMS|daedalus/eval/harness.py|_repo_chunks: dirnames sorted for deterministic order
CLAIMS|daedalus/council/canary.py|never reads repo source files
CLAIMS|daedalus/council/canary.py|checks are deterministic Python, not LLM
CLAIMS|daedalus/council/canary.py|never sets OLLAMA_HOST environment variable
CLAIMS|daedalus/council/canary.py|spend is opt-in via --live flag
CLAIMS|daedalus/core.py|envelope returns a standardized API envelope with ok, generated_at, project, warnings
CLAIMS|daedalus/core.py|_safe_load_project degrades to {} + warning instead of raising on unknown/malformed project
CLAIMS|daedalus/core.py|_safe_collect_status wraps collect_status and degrades on OSError, SubprocessError, ValueError
CLAIMS|daedalus/core.py|_worst_state returns the worst state from a list using a severity order, never an average
CLAIMS|daedalus/core.py|_gov_discrimination evaluates if a gate has been shown to separate good patches from bad

## UNWIRED

UNWIRED|daedalus/structcore/index.py|types_enabled
UNWIRED|daedalus/structcore/index.py|wiki_enabled
UNWIRED|daedalus/memory/embeddings.py|_embed_batch (compatibility helper; usage not visible in provided excerpt)
UNWIRED|daedalus/kairos/gated_writes.py|_artifact_root_functions (defined but not called within module)
UNWIRED|daedalus/kairos/gated_writes.py|_provider_receipt (defined but not called within module)
UNWIRED|daedalus/kairos/gated_writes.py|_PromotionLock (defined but never used)
UNWIRED|tests/test_typegraph_determinism.py|REPO_ROOT is defined but only used for subprocess path insertion and fixture path resolution
UNWIRED|daedalus/cli.py|_spawn

## SMELL

SMELL|daedalus/mapping/drift.py|god-object: single file handles multiple concerns (acceptance, documentation scanning, snapshot state, ignore config, drift detection).
SMELL|daedalus/mapping/drift.py|implicit dependency on reach and switches modules not expressed via imports.
SMELL|daedalus/memory/embeddings.py|Large module-level docstring mixing usage, guarantees, and stated limits; risk of fragmentation
SMELL|daedalus/providers/ollama.py|File contains provider logic, write guard, windowed rewrite, and dispatch; candidate for separation of concerns
SMELL|daedalus/kairos/gated_writes.py|Several internal functions (_artifact_root_for, _provider_receipt, _PromotionLock) are defined but never called within the module, suggesting dead code.