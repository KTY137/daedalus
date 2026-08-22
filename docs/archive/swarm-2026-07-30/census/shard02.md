# Census shard 2/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

tests/test_worktree.py|function|test_removal_does_not_follow_a_junction_swapped_in_mid_walk|guarantees mid-walk junction swap does not cause deletion of primary repo
tests/test_worktree.py|function|test_removal_refuses_when_a_guarded_ancestor_becomes_a_reparse_point|guarantees ancestor reparse point raises WorktreeContainmentError (inferred from partial context)
Route this task to Claude or local Ollama.
daedalus/mapping/drift.py|constant|SNAPSHOT_REL|Relative path to the committed architecture state JSON file.
daedalus/mapping/drift.py|constant|SCHEMA_VERSION|Current schema version for the snapshot.
daedalus/mapping/drift.py|constant|MAX_HORIZON_DAYS|Maximum horizon days for acceptance expiry.
daedalus/mapping/drift.py|constant|MIN_WHY_CHARS|Minimum characters for acceptance 'why' field.
daedalus/mapping/drift.py|constant|ISLAND_CLASSES|Reach classes treated as islands.
daedalus/mapping/drift.py|constant|UNKNOWN_CLASSES|Reach classes treated as unknown.
daedalus/mapping/drift.py|constant|SHIM_CLASSES|Reach classes treated as shims.
daedalus/mapping/drift.py|constant|UNREACHED_CLASSES|Union of island, unknown, shim classes.
daedalus/mapping/drift.py|constant|REACHED_CLASSES|Reach classes that are reached.
daedalus/mapping/drift.py|constant|IGNORE_FILENAME|Filename for ignore configuration.
daedalus/mapping/drift.py|constant|IGNORE_ENV|Environment variable for ignore configuration.
daedalus/mapping/drift.py|constant|DOC_DIRS|Directories searched for documentation.
daedalus/mapping/drift.py|constant|DOC_SUFFIX|File suffix for documentation files.
daedalus/mapping/drift.py|constant|DOC_EXTRA_FILES|Extra files to include in documentation search.
daedalus/mapping/drift.py|constant|GENERATED_DOCS|Files considered generated and excluded from documentation scan.
daedalus/mapping/drift.py|constant|MIN_DOC_DESC_CHARS|Minimum characters of prose beside a switch name to count as documented.
daedalus/mapping/drift.py|constant|NEW_ISLAND|Kind string for new island drift.
daedalus/mapping/drift.py|constant|NEW_UNKNOWN|Kind string for new unknown drift.
daedalus/mapping/drift.py|constant|NEW_SHIM|Kind string for new shim drift.
daedalus/mapping/drift.py|constant|ENGINE_DISAGREEMENT|Kind string for engine disagreement.
daedalus/mapping/drift.py|constant|NEW_DARK_SWITCH|Kind string for new dark switch drift.
daedalus/mapping/drift.py|constant|BECAME_ISLAND|Kind string for became island drift.
daedalus/mapping/drift.py|constant|NOW_REACHED|Kind string for now reached drift.
daedalus/mapping/drift.py|constant|DOC_DRIFT|Kind string for documentation drift.
daedalus/mapping/drift.py|constant|VANISHED|Kind string for vanished drift.
daedalus/mapping/drift.py|constant|TEST_ONLY|Kind string for test-only drift.
daedalus/mapping/drift.py|constant|UNPARSABLE|Kind string for unparsable drift.
daedalus/mapping/drift.py|constant|IGNORE_DRIFT|Kind string for ignore configuration drift.
daedalus/mapping/drift.py|constant|STALE_ACCEPTANCE|Kind string for stale acceptance.
daedalus/mapping/drift.py|constant|INVALID_ACCEPTANCE|Kind string for invalid acceptance.
daedalus/mapping/drift.py|constant|INVALID_SNAPSHOT|Kind string for invalid snapshot.
daedalus/mapping/drift.py|constant|KIND_ORDER|Ordered tuple of drift kinds for rendering.
daedalus/mapping/drift.py|constant|NON_BLOCKING_KINDS|Frozenset of drift kinds that do not block.
daedalus/mapping/drift.py|constant|ACCEPTABLE_KINDS|Frozenset of drift kinds that can be accepted.
daedalus/mapping/drift.py|function|ignore_config|Returns the ignore configuration fingerprint for a repo root.
daedalus/mapping/drift.py|function|repo_state|Returns the current repository state (head, branch, dirty flag).
daedalus/mapping/drift.py|class|DocIndex|Index of documentation lines for environment variable documentation checking.
daedalus/mapping/drift.py|class|ScanResult|Dataclass holding scan state, sites, reach, and switches.
daedalus/spine/picker.py|constant|ROOT|Resolved repo root path
daedalus/spine/picker.py|constant|INVENTORY_REL_PATH|Relative path to feature inventory JSON
daedalus/spine/picker.py|constant|WORK_QUEUE_SCHEMA|Schema identifier for work queue
daedalus/spine/picker.py|constant|DEFAULT_WORK_QUEUE_REL_PATH|Default relative path for work queue JSON
daedalus/spine/picker.py|constant|DEFAULT_SPINE_DB_REL_PATH|Default relative path for spine SQLite database
daedalus/spine/picker.py|constant|SOURCE_BANDS|Dictionary of source priority bands
daedalus/spine/picker.py|constant|BAND_SPAN|Maximum offset within a band
daedalus/spine/picker.py|constant|SOURCE_ORDER|Tuple of source names in priority order
daedalus/spine/picker.py|constant|DEFAULT_LIMIT|Default number of candidates to pick
daedalus/spine/picker.py|constant|EXIT_CANDIDATE|Exit code for candidate available
daedalus/spine/picker.py|constant|EXIT_FAILED|Exit code for attempt failure
daedalus/spine/picker.py|constant|EXIT_NO_CHANGE|Exit code for attempt with no change
daedalus/spine/picker.py|constant|EXIT_SOURCE_UNAVAILABLE|Exit code for unavailable source
daedalus/spine/picker.py|constant|EXIT_BY_STATE|Mapping from outcome state to exit code
daedalus/spine/picker.py|constant|STATUS_ISLAND|Constant for 'island' status
daedalus/spine/picker.py|constant|STATUS_STALE|Constant for 'stale' status
daedalus/spine/picker.py|class|Candidate|Frozen dataclass representing a unit of work with evidence
daedalus/spine/picker.py|class|PickedQueue|Frozen dataclass representing a ranked queue with source status
daedalus/spine/picker.py|class|NoEvidence|Exception raised when a candidate lacks evidence
daedalus/spine/picker.py|class|WorkQueueInvalid|Exception for invalid work queue configuration
daedalus/spine/picker.py|function|apply_attempt_memory|Applies attempt outcome memory penalty to candidate score
daedalus/spine/picker.py|function|attempt_history|Retrieves attempt history from ledger
daedalus/spine/picker.py|function|build_queue|Builds the ranked queue from all sources
daedalus/spine/picker.py|function|eval_baseline_candidates|Generates candidates from eval baseline
daedalus/spine/picker.py|function|eval_gate_candidates|Generates candidates from eval gates
daedalus/spine/picker.py|function|hotspot_candidates|Generates candidates from code hotspots
daedalus/spine/picker.py|function|instruction_fingerprint|Computes a fingerprint of instruction text
daedalus/spine/picker.py|function|inventory_candidates|Generates candidates from feature inventory
daedalus/spine/picker.py|function|inventory_freshness|Checks freshness of inventory file
daedalus/spine/picker.py|function|load_inventory|Loads feature inventory from file
daedalus/spine/picker.py|function|load_map_state|Loads map state from architecture state file
daedalus/spine/picker.py|function|load_work_queue|Loads the configured work queue from file
daedalus/spine/picker.py|function|main|Entry point for the 'daedalus improve' command
daedalus/spine/picker.py|function|map_candidates|Generates candidates from architecture state map
daedalus/spine/picker.py|function|map_state_trustworthy|Checks if map state is trustworthy (with digest)
daedalus/spine/picker.py|function|outcome_policy|Returns outcome policy for a given source
daedalus/spine/picker.py|function|rank|Ranks a list of candidates by score
daedalus/spine/picker.py|function|render_queue|Renders the queue for human review
daedalus/spine/picker.py|function|review_packet|Generates review packet for a candidate
daedalus/spine/picker.py|function|resolve_spine_db_path|Resolves the spine database path
daedalus/spine/picker.py|function|work_queue_candidates|Generates candidates from the work queue JSON
tests/test_typegraph_resolve.py|constant|ALPHA|Type node ID for result_alpha.py Result
tests/test_typegraph_resolve.py|constant|BETA|Type node ID for result_beta.py Result
tests/test_typegraph_resolve.py|class|AmbiguityIsRefusedAndCounted|Tests that ambiguous imports produce no edges and are counted
tests/test_typegraph_resolve.py|class|ResolvingIsStillRequired|Positive control that cross-module resolution still works
tests/test_typegraph_resolve.py|class|UnresolvedIsCountedNotGuessed|Tests that unresolved types are counted but not minted into nodes
tests/test_typegraph_resolve.py|class|TheResolverTableIsSeparate|Tests that annotation resolution uses separate types_by_file table
daedalus/memory/embeddings.py|class|AgentEvent|A projection input, not the authoritative event record; provides to_dict/from_dict for serialization
daedalus/memory/embeddings.py|class|EmbeddingSpec|Identity of one mutually compatible embedding coordinate system; defines index_id via SHA-256 of canonical spec
daedalus/memory/embeddings.py|class|JournalPosition|A position in the authoritative journal this index is derived from; supports optional content_hash for append-only check
daedalus/memory/embeddings.py|class|ProjectionFilter|Exact-match provenance filters applied before vector scoring
daedalus/memory/embeddings.py|class|OperationStatus|Machine-readable status for projection and query operations
daedalus/memory/embeddings.py|class|IngestReport|Status and counts for an ingest operation
daedalus/memory/embeddings.py|class|SearchReport|Status and matches for a search operation; includes freshness field (default unanchored)
daedalus/memory/embeddings.py|class|IndexStatus|Status and metadata for an index; includes identity_anchor provenance and revision_pinned flag
daedalus/memory/embeddings.py|class|EmbeddingError|Base class for expected embedder failures
daedalus/memory/embeddings.py|class|EmbeddingUnavailableError|The embedding service could not be reached
daedalus/memory/embeddings.py|class|EmbeddingProtocolError|The embedding service returned a malformed response
daedalus/memory/embeddings.py|class|EmbeddingBackend|Protocol for testable backend seam; requires embed method
daedalus/memory/embeddings.py|class|OllamaEmbeddingBackend|Ollama's current batched POST /api/embed transport
daedalus/memory/embeddings.py|class|EventVectorStore|Append-only, versioned event projection index backed by SQLite; provides _init_db for schema migration
daedalus/memory/embeddings.py|constant|EMBED_MODEL|Default embedding model from OLLAMA_EMBED_MODEL env var
daedalus/memory/embeddings.py|constant|EVENT_PROJECTOR_VERSION|Projector version string 'agent-event-v1'
daedalus/memory/embeddings.py|constant|SCHEMA_VERSION|Database schema version (2)
daedalus/memory/embeddings.py|constant|IDENTITY_DRIFT_TOLERANCE|Maximum cosine distance for identity anchor re-embedding
daedalus/memory/embeddings.py|constant|MOVABLE_TAG_PROVIDERS|Set of providers with movable model tags (frozenset({'ollama'}))
daedalus/spine/attempt.py|constant|ATTEMPT_STATES|Defines all valid attempt state constants as a tuple.
daedalus/spine/attempt.py|constant|BRANCH_PREFIX|Prefix for git branch names created by attempts.
daedalus/spine/attempt.py|constant|DEFAULT_GATE_TIMEOUT_S|Default timeout for gate execution in seconds.
daedalus/spine/attempt.py|constant|DEFAULT_GIT_TIMEOUT_S|Default timeout for git commands in seconds.
daedalus/spine/attempt.py|constant|GATE_OUTPUT_TAIL_CHARS|Maximum bytes of gate output retained in GateResult.
daedalus/spine/attempt.py|constant|INTENT_KIND|Intent kind string for candidate attempts.
daedalus/spine/attempt.py|constant|READ_ONLY_REPO_VERBS|Frozenset of git verbs allowed on the primary checkout.
daedalus/spine/attempt.py|constant|ROOT|Resolved path to the Daedalus repository root.
daedalus/spine/attempt.py|constant|STATE_CANCELLED|State constant for attempts cancelled by token.
daedalus/spine/attempt.py|constant|STATE_CLEAN|State constant for successful attempts with gates passed.
daedalus/spine/attempt.py|constant|STATE_GATES_FAILED|State constant for attempts where gates rejected the patch.
daedalus/spine/attempt.py|constant|STATE_NO_CHANGE|State constant for attempts where runner made no changes.
daedalus/spine/attempt.py|constant|STATE_RUNNER_FAILED|State constant for attempts where runner raised an exception.
daedalus/spine/attempt.py|constant|STATE_STORAGE_UNAVAILABLE|State constant when storage check fails before any effect.
daedalus/spine/attempt.py|constant|STATE_WORKTREE_FAILED|State constant when worktree creation or patch capture fails.
daedalus/spine/attempt.py|class|AttemptResult|Represents the outcome of a task attempt, including state and artifact.
daedalus/spine/attempt.py|class|GateResult|Represents the result of a gate check against a candidate patch.
daedalus/spine/attempt.py|class|GitCommandError|Exception raised when a git command fails.
daedalus/spine/attempt.py|class|PatchArtifact|Inert patch bytes with metadata, produced by an attempt.
daedalus/spine/attempt.py|class|PrimaryCheckoutWrite|Exception raised when an attempt tries to write to the primary checkout.
daedalus/spine/attempt.py|class|RunnerContext|Context passed to runners and gates, containing worktree path and spec.
daedalus/spine/attempt.py|class|TaskAttempt|Orchestrates the attempt lifecycle: worktree, runner, gates, resolution.
daedalus/spine/attempt.py|class|TaskSpec|Describes the task to be attempted, with description and metadata.
daedalus/spine/attempt.py|function|command_gate|Returns a gate that runs a shell command and checks exit code.
daedalus/spine/attempt.py|function|offload_runner|Returns a runner that executes a shell command and captures diff.
daedalus/spine/attempt.py|function|pytest_gate|Returns a gate that runs pytest on the modified worktree.
daedalus/spine/attempt.py|function|pytest_gate_argv|Returns a gate that runs pytest with custom arguments.
daedalus/spine/attempt.py|function|run_attempt|Convenience function to create a TaskAttempt and run it.
daedalus/providers/ollama.py|constant|DEFAULT_HOST|Local Ollama server URI
daedalus/providers/ollama.py|constant|DEFAULT_MODEL|Default model name
daedalus/providers/ollama.py|constant|DEFAULT_KEEP_ALIVE|Default keep-alive duration
daedalus/providers/ollama.py|constant|MAX_AGENT_STEPS|Maximum agent steps
daedalus/providers/ollama.py|constant|MAX_READ_CHARS|Maximum characters for read operations
daedalus/providers/ollama.py|constant|MAX_REWRITE_FILES|Maximum rewrite files
daedalus/providers/ollama.py|constant|MAX_REWRITE_CHARS|Maximum rewrite characters
daedalus/providers/ollama.py|constant|DEFAULT_WINDOW_RADIUS|Default window radius for edits
daedalus/providers/ollama.py|constant|MAX_WINDOW_LINES|Maximum window lines
daedalus/providers/ollama.py|constant|MAX_WINDOWS_PER_FILE|Maximum windows per file
daedalus/providers/ollama.py|constant|WINDOW_ANCHOR_FRAC|Minimum anchor fraction for windows
daedalus/providers/ollama.py|constant|RESCUE_CALLS|Rescue outcome constant for tool calls
daedalus/providers/ollama.py|constant|RESCUE_FINISHED|Rescue outcome constant for finished
daedalus/providers/ollama.py|constant|RESCUE_UNREACHABLE|Rescue outcome constant for unreachable
daedalus/providers/ollama.py|constant|RESCUE_MALFORMED|Rescue outcome constant for malformed
daedalus/providers/ollama.py|class|RescueOutcome|Namedtuple for schema rescue outcomes

## DEPENDS

DEPENDS|tests/test_typegraph_resolve.py|daedalus.structcore.parse
DEPENDS|daedalus/memory/embeddings.py|daedalus.adapters.events
DEPENDS|daedalus/memory/embeddings.py|daedalus.providers.ollama
DEPENDS|daedalus/spine/attempt.py|daedalus.kairos.worktree
DEPENDS|daedalus/spine/attempt.py|daedalus.primary_tree
DEPENDS|daedalus/spine/attempt.py|daedalus.spine.ledger
DEPENDS|daedalus/spine/attempt.py|daedalus.storage
DEPENDS|daedalus/providers/ollama.py|daedalus/sensitivity
DEPENDS|daedalus/providers/ollama.py|daedalus/structcore/tokens
DEPENDS|daedalus/providers/ollama.py|daedalus/providers/_ollama_native
DEPENDS|daedalus/providers/ollama.py|daedalus/providers/_openai_compat
DEPENDS|daedalus/providers/ollama.py|daedalus/providers/_report
DEPENDS|daedalus/providers/ollama.py|daedalus/providers/base
DEPENDS|daedalus/providers/ollama.py|daedalus/providers/personas
DEPENDS|daedalus/kairos/gated_writes.py|daedalus.spine.attempt (lazy import)
DEPENDS|daedalus/kairos/gated_writes.py|daedalus.config.resolve_project (lazy import)
DEPENDS|daedalus/kairos/gated_writes.py|daedalus.spine.picker.resolve_spine_db_path (lazy import)
DEPENDS|daedalus/kairos/gated_writes.py|.worktree.GitWorktreeManager
DEPENDS|tests/test_typegraph_parse.py|daedalus.structcore.languages
DEPENDS|tests/test_typegraph_parse.py|daedalus.structcore.parse
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.index
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.graph
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.typegraph
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.cache
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.ignore
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.parse
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.perfile
DEPENDS|tests/test_typegraph_index.py|daedalus.structcore.languages
DEPENDS|tests/test_typegraph_determinism.py|daedalus.structcore.build_index
DEPENDS|tests/test_typegraph_determinism.py|daedalus.structcore.typegraph
DEPENDS|tests/test_typegraph_determinism.py|daedalus.structcore.forest.build_knowledge_forest
DEPENDS|tests/test_typegraph_determinism.py|daedalus.structcore.parse.ANY_SENTINEL and python_type_facts
DEPENDS|daedalus/structcore/parse.py|.languages
DEPENDS|daedalus/cli.py|daedalus.kairos.scheduler

## WRITES

WRITES|daedalus/memory/embeddings.py|Legacy table renamed to legacy_agent_events_v1
WRITES|daedalus/spine/attempt.py|worktree directory (via GitWorktreeManager)
WRITES|daedalus/spine/attempt.py|artifact_dir (caller-provided, fenced)
WRITES|daedalus/spine/attempt.py|spine ledger (repo/runs/spine/spine.sqlite3)
WRITES|daedalus/spine/attempt.py|git branch refs in primary repo
WRITES|daedalus/providers/ollama.py|repo_root files via write_file tool

## READS

READS|daedalus/mapping/drift.py|docs/*.md, .env.example, .env.template
READS|daedalus/spine/picker.py|docs/FEATURE_INVENTORY.json (via INVENTORY_REL_PATH)
READS|daedalus/spine/picker.py|<repo>/.agentenv/work-queue.json (via DEFAULT_WORK_QUEUE_REL_PATH)
READS|daedalus/spine/picker.py|<repo>/runs/spine/spine.sqlite3 (via DEFAULT_SPINE_DB_REL_PATH)
READS|tests/test_typegraph_resolve.py|tests/fixtures/typegraph/
READS|tests/test_typegraph_resolve.py|daedalus/structcore/typegraph.py
READS|daedalus/memory/embeddings.py|SQLite database at self.db_path
READS|daedalus/memory/embeddings.py|Ollama embedding service via HTTP POST /api/embed
READS|daedalus/spine/attempt.py|primary checkout via read-only git verbs
READS|daedalus/spine/attempt.py|git config for inherited settings

## CLAIMS

CLAIMS|daedalus/spine/attempt.py|runner is never told where the repo is (no repo_root in RunnerContext)
CLAIMS|daedalus/spine/attempt.py|no apply path exists: deliverable is inert PatchArtifact bytes
CLAIMS|daedalus/providers/ollama.py|warm_model docstring claims to pin model in VRAM via native endpoint
CLAIMS|daedalus/providers/ollama.py|warm_model_async docstring claims fire-and-forget on daemon thread
CLAIMS|daedalus/providers/ollama.py|OllamaProvider.egress_lane docstring claims 'trusted' only if talking to this machine
CLAIMS|daedalus/providers/ollama.py|OllamaProvider._refuse_if_remote docstring claims the enforcement point for non-loopback
CLAIMS|daedalus/providers/ollama.py|OllamaProvider.rollback docstring claims to undo every write made
CLAIMS|daedalus/kairos/gated_writes.py|Never touches the primary checkout
CLAIMS|tests/test_typegraph_parse.py|The extractor reads every declaration shape and annotation spelling in the adversarial fixture corpus without moving extract_units.
CLAIMS|tests/test_typegraph_index.py|Tests for the type layer's index wiring
CLAIMS|tests/test_typegraph_index.py|Invariant I1: duplication is byte-identical
CLAIMS|tests/test_typegraph_index.py|Invariant I4: modules and import_edges are byte-identical
CLAIMS|tests/test_typegraph_index.py|Invariant I2: resolver is untouched
CLAIMS|tests/test_typegraph_index.py|All published keys have documented shape
CLAIMS|tests/test_typegraph_index.py|Coverage reports own confidence
CLAIMS|tests/test_typegraph_determinism.py|Two processes must produce byte-identical output, and every name the layer could not pin down must produce NO edge and a COUNTER
CLAIMS|tests/test_typegraph_determinism.py|union_id is content-derived, never counted; resolving union_shapes.py ALONE yields the same three ids as resolving all sixteen files
CLAIMS|daedalus/cli.py|_spawn: Decompose one objective into subtasks and plan (default) or dispatch (--live) them across the local bench via Kairos.
CLAIMS|daedalus/cli.py|_build: Plan a multi-wave build for one feature objective: decompose it, route each subtask to its owner, assign a frontier builder (Claude) or the local bench off the category lane, and group into bounded waves.
CLAIMS|daedalus/cli.py|_init: Scaffold .agentenv/agentenv.json (enables writes)
CLAIMS|daedalus/cli.py|_projects: list registered projects
CLAIMS|daedalus/cli.py|_accelerators: Report evidence-based CUDA/RTX backend readiness.
CLAIMS|daedalus/cli.py|_context: Plan read-only, token-budgeted context with lexical/optional versioned-latent seeds and deterministic DSS graph propagation.
CLAIMS|daedalus/cli.py|_agents: Create / list / edit / delete agent-role definitions at runtime -- the roles Ikarus routes to.
CLAIMS|daedalus/cli.py|_categories: List / show / recolor role categories -- the icon/color/lane/tier presets that group agent roles for the UI.
CLAIMS|daedalus/cli.py|_drafts: List / show / remove persisted advisory drafts (runs/drafts/).
CLAIMS|daedalus/cli.py|_council: Convene the cross-vendor council over a patch or a question.
CLAIMS|daedalus/structcore/typegraph.py|I2: defs_by_file is not touched
CLAIMS|daedalus/structcore/typegraph.py|I5: refusal to guess (two-pass, no tie-break)
CLAIMS|daedalus/structcore/typegraph.py|I6: lens, not diffusion channel
CLAIMS|daedalus/structcore/typegraph.py|determinism via sorted iterations and total order
CLAIMS|tests/test_skills.py|'the module cannot execute anything, enforced by reading its own source'

## UNWIRED

UNWIRED|daedalus/mapping/render.py|CLASS_MEANING constant (defined but not obviously used outside this file)
UNWIRED|daedalus/mapping/render.py|NARRATIVE_SECTIONS constant (defined but used only inside file)
UNWIRED|daedalus/mapping/render.py|_SECTION_KEY_RE constant (defined but only used in parse_narrative)
UNWIRED|daedalus/mapping/render.py|_SLUG_RE constant (defined but only used in _slug)
UNWIRED|daedalus/mapping/render.py|analyse_once function (called from within file or elsewhere? Possibly not called directly externally)
UNWIRED|daedalus/mapping/render.py|esc function (defined but may be used externally? Not obvious from context)
UNWIRED|daedalus/structcore/index.py|backend_status
UNWIRED|daedalus/structcore/index.py|documents_enabled

## SMELL

SMELL|daedalus/structcore/index.py|knowledge_links parser had no consumer until gating; dead branch before flag added.
SMELL|daedalus/health.py|God-object: module contains vocabulary, fact system, report system, probe registry, rendering, and concrete probes in one file.
SMELL|tests/test_worktree.py|dying test and load-bearing untested line flagged in docstring of test_reparse_detection_off_windows_rests_on_the_symlink_branch
SMELL|tests/test_worktree.py|race condition tests rely on timing and threading, potentially flaky
SMELL|tests/test_worktree.py|numerous platform-dependent tests skipped on non-Windows, limiting coverage