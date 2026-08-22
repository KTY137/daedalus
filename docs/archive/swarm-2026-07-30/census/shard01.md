# Census shard 1/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/mapping/render.py|module|daedalus.mapping.render|Generates architecture map HTML/JSON, manages stamps, narrative, rendering
daedalus/mapping/render.py|class|Stamp|Represents staleness stamp with generation time, revision, dirty state, untracked scanned files
daedalus/mapping/render.py|class|NarrativeSection|Represents a section of the narrative with key, title, body
daedalus/mapping/render.py|class|Narrative|Represents the full narrative document with sections, missing, extra
daedalus/mapping/render.py|function|esc|HTML-escapes a value (returns empty string for None)
daedalus/mapping/render.py|function|_git_dir|Finds .git directory, handling linked worktrees
daedalus/mapping/render.py|function|_resolve_ref|Resolves a git ref to a hash from loose or packed-refs
daedalus/mapping/render.py|function|_head|Returns (revision, branch) from repo root
daedalus/mapping/render.py|function|_dirty|Returns (dirty/clean/unknown, count of dirty paths)
daedalus/mapping/render.py|function|_untracked|Returns (count, sample) of scanned files not tracked by git
daedalus/mapping/render.py|function|git_stamp|Creates a Stamp from repo root, with optional now, probe_dirty, scanned
daedalus/mapping/render.py|function|parse_narrative|Splits narrative text on ## headings using {#key} suffix
daedalus/mapping/render.py|function|load_narrative|Loads narrative file and returns Narrative object
daedalus/mapping/render.py|function|analyse_once|Runs reachability and switch engines once, returns (reach_report, switch_report)
daedalus/mapping/render.py|constant|SCHEMA|Schema identifier string
daedalus/mapping/render.py|constant|MAP_REL|Relative path to output architecture map HTML
daedalus/mapping/render.py|constant|NARRATIVE_REL|Relative path to hand-written narrative markdown file
daedalus/mapping/render.py|constant|STATUS_VOCAB|Tuple of (slug, label, meaning) for status vocabulary
daedalus/mapping/render.py|constant|CLASS_STATUS|Mapping from reachability class to status slug
daedalus/mapping/render.py|constant|CLASS_MEANING|Mapping from reachability class to human-readable meaning
daedalus/mapping/render.py|constant|NARRATIVE_SECTIONS|Tuple of (key, title) for expected narrative sections
daedalus/spine/containment.py|class|ContainedProcess|A contained child process with job object and integrity restrictions.
daedalus/spine/containment.py|class|ContainmentAttestation|Result of containment setup verification.
daedalus/spine/containment.py|class|ContainmentUnavailable|Exception when containment cannot be established.
daedalus/spine/containment.py|constant|JOB_ACTIVE_PROCESS_LIMIT|Maximum concurrent processes inside the gate's job (96).
daedalus/spine/containment.py|constant|JOB_LIMITS_DO_NOT_COVER|Tuple of resource limits the job does not cover.
daedalus/spine/containment.py|constant|JOB_MEMORY_LIMIT_BYTES|Committed memory limit for the whole job (4 GB).
daedalus/spine/containment.py|constant|LOW_APPEND_ACCESS|Access mask for append-only handle across boundary (0x00100084).
daedalus/spine/containment.py|constant|LOW_INTEGRITY_SID|Low mandatory level SID string.
daedalus/spine/containment.py|class|LowIntegrityLog|A low-integrity append-only log file.
daedalus/spine/containment.py|function|integrity_label|Returns the integrity label of a token.
daedalus/spine/containment.py|function|job_accounting|Returns job accounting information.
daedalus/spine/containment.py|function|label_low_integrity|Labels a token with low integrity.
daedalus/spine/containment.py|function|label_low_integrity_file|Labels a file with low integrity.
daedalus/spine/containment.py|function|open_low_append_log|Opens a file for append with low integrity access.
daedalus/spine/containment.py|function|platform_supported|Checks if platform supports containment (Windows NT).
daedalus/spine/containment.py|function|spawn_contained|Spawns a child process with containment.
daedalus/spine/containment.py|function|unmeasured_vectors|Returns tuple of unmeasured attack vectors.
daedalus/eval/correctness.py|module|correctness|Provides the correctness gate for evaluation.
daedalus/eval/correctness.py|class|PytestRun|Dataclass representing one pytest invocation with raw output and per-node statuses.
daedalus/eval/correctness.py|class|PrimaryCheckoutTouch|Exception raised when attempting to run or write in the primary checkout.
daedalus/eval/correctness.py|class|OverlayEscape|Exception raised when a test overlay path points outside the disposable worktree.
daedalus/eval/correctness.py|function|resolve_revision|Resolves a git revision string to its full SHA, or None if unresolvable.
daedalus/eval/correctness.py|function|pytest_node_argv|Constructs the pytest command-line arguments for given node IDs.
daedalus/eval/correctness.py|function|parse_pytest_output|Parses pytest output to return a dict mapping requested node IDs to their statuses.
daedalus/eval/correctness.py|constant|OUTCOME_FIXED|String constant 'fixed' indicating all tests passed after change.
daedalus/eval/correctness.py|constant|OUTCOME_NOT_FIXED|String constant 'not_fixed' indicating change did not turn some fail_to_pass green.
daedalus/eval/correctness.py|constant|OUTCOME_REGRESSED|String constant 'regressed' indicating some pass_to_pass test broke.
daedalus/eval/correctness.py|constant|OUTCOME_COULD_NOT_RUN|String constant 'could_not_run' indicating no verdict obtainable.
daedalus/eval/correctness.py|constant|OUTCOME_TASK_INVALID|String constant 'task_invalid' indicating before-state refuted the task.
daedalus/eval/correctness.py|constant|OUTCOMES|Tuple of all five outcome constants.
daedalus/eval/correctness.py|constant|STATUS_PASSED|String 'passed' indicating test passed.
daedalus/eval/correctness.py|constant|STATUS_FAILED|String 'failed' indicating test failed.
daedalus/eval/correctness.py|constant|STATUS_ERROR|String 'error' indicating test itself errored.
daedalus/eval/correctness.py|constant|STATUS_COLLECT_ERROR|String 'collect_error' indicating file could not be imported.
daedalus/eval/correctness.py|constant|STATUS_SKIPPED|String 'skipped' indicating test was skipped.
daedalus/eval/correctness.py|constant|STATUS_MISSING|String 'missing' indicating node ID does not exist.
daedalus/eval/correctness.py|constant|STATUS_NOT_RUN|String 'not_run' indicating no information available.
daedalus/eval/correctness.py|constant|PROVEN_NOT_PASSING|Frozenset of statuses that prove a node did not pass.
daedalus/eval/correctness.py|constant|NO_VERDICT|Frozenset of statuses carrying no verdict.
daedalus/eval/correctness.py|constant|DEFAULT_TEST_TIMEOUT_S|Float 900.0, default timeout for pytest.
daedalus/eval/correctness.py|constant|DEFAULT_GIT_TIMEOUT_S|Float 120.0, default timeout for git commands.
daedalus/eval/correctness.py|constant|DEFAULT_CORPUS_PATH|String path to default correctness_tasks.json.
daedalus/eval/correctness.py|constant|CORPUS_SCHEMA|Integer 1, schema version for corpus file.
daedalus/loop.py|constant|DEFAULT_MAX_ATTEMPTS_PER_CANDIDATE|Default max attempts per candidate = 2
daedalus/loop.py|constant|DEFAULT_MAX_ITERATIONS|Default max iterations = 5
daedalus/loop.py|constant|DEFAULT_MAX_SPEND_USD|Default max spend in USD = 2.0
daedalus/loop.py|constant|DEFAULT_MAX_WALL_CLOCK_S|Default max wall clock seconds = 1800.0
daedalus/loop.py|constant|STOP_REASONS|Tuple of all possible stop reasons
daedalus/loop.py|constant|PROGRESS_SOURCE|Source identifier for progress reporting: "daedalus.loop"
daedalus/loop.py|class|LoopMisconfigured|Exception raised when a bound is missing or non-positive
daedalus/loop.py|class|LoopBounds|Dataclass holding four bounds for the loop
daedalus/loop.py|class|LoopLedger|Manages attempt memory and path claims per loop run
daedalus/loop.py|class|IterationResult|Result of a single loop iteration
daedalus/loop.py|class|LoopDriver|Main driver class that orchestrates the loop
daedalus/loop.py|class|LoopReport|Report dataclass for loop termination
daedalus/loop.py|constant|ROOT|Path to repo root (parent of daedalus directory)
daedalus/kairos/worktree.py|constant|ALLOC_DIRNAME|Directory for allocation records inside worktree root, never inside a candidate's workspace.
daedalus/kairos/worktree.py|constant|ALLOC_SCHEMA|Schema identifier for allocation records.
daedalus/kairos/worktree.py|class|GitWorktreeManager|Manages creation and lifecycle of per-repo worktree pools with containment checks.
daedalus/kairos/worktree.py|class|WorktreeContainmentError|Exception for when a cleanup target cannot be proven an allocated worktree.
daedalus/kairos/worktree.py|class|WorktreeRemovalRace|Exception for when a reparse point appears above a removal in progress.
Route this task to Claude or local Ollama.
daedalus/structcore/index.py|function|backend_status|Guarantees reporting of tree-sitter and lizard backend availability.
daedalus/structcore/index.py|function|documents_enabled|Guarantees correct boolean for document indexing based on explicit argument or environment variable.
daedalus/structcore/index.py|function|types_enabled|Guarantees correct boolean for type layer indexing based on explicit argument or environment variable.
daedalus/structcore/index.py|function|wiki_enabled|Guarantees correct boolean for wiki link layer indexing based on explicit argument or environment variable.
daedalus/health.py|constant|WORKING|the state for a subsystem exercised just now
daedalus/health.py|constant|PRESENT|the state for code present but not exercised
daedalus/health.py|constant|DEGRADED|the state for a subsystem that ran but returned wrong
daedalus/health.py|constant|ABSENT|the state for a subsystem that is not here
daedalus/health.py|constant|UNKNOWN|the state when the check could not run
daedalus/health.py|constant|STATES|tuple of all five allowed states
daedalus/health.py|constant|NOT_PROVEN|tuple of states that do not prove working
daedalus/health.py|constant|MEASURED|provenance value for values produced by this run
daedalus/health.py|constant|INHERITED|provenance value for values read from a file
daedalus/health.py|constant|ASSUMED|provenance value for defaults or docs
daedalus/health.py|constant|PROVENANCE|tuple of all provenance values
daedalus/health.py|constant|EXIT_OK|exit code 0 when all probes exercised and held
daedalus/health.py|constant|EXIT_BAD|exit code 1 when degraded or missing
daedalus/health.py|constant|EXIT_UNPROVEN|exit code 2 when not all probes proven
daedalus/health.py|constant|PROBE_TEXT|fixed literal for embedding probes; never repo content
daedalus/health.py|constant|LOCAL_OLLAMA|default local Ollama endpoint
daedalus/health.py|constant|BENCH_OLLAMA|bench Ollama endpoint from env or default
daedalus/health.py|constant|EMBED_MODEL|embeddings model name from env or default
daedalus/health.py|constant|BENCH_SSH_HOST|SSH endpoint for bench diagnostics
daedalus/health.py|constant|BENCH_TASK_NAME|scheduled task name on bench host
daedalus/health.py|constant|BENCH_SSH_TIMEOUT_S|ssh timeout in seconds
daedalus/health.py|class|ProvenanceError|raised when fact missing required provenance
daedalus/health.py|class|Fact|one measured/assumed/inherited value with provenance guards
daedalus/health.py|function|measured|create a measured Fact
daedalus/health.py|function|inherited|create an inherited Fact with file age
daedalus/health.py|function|assumed|create an assumed Fact with declaration source
daedalus/health.py|class|Report|aggregate of name, state, facts, remedy
daedalus/health.py|function|working|create a working Report
daedalus/health.py|function|present|create a present Report
daedalus/health.py|function|degraded|create a degraded Report
daedalus/health.py|function|absent|create an absent Report
daedalus/health.py|function|unknown|create an unknown Report
daedalus/health.py|class|ProbeSpec|specification for a probe function
daedalus/health.py|constant|PROBES|list of registered ProbeSpecs
daedalus/health.py|function|probe|decorator to register a probe
daedalus/health.py|class|Ctx|context object passed to probes with paths and flags
daedalus/health.py|function|assess|run all probes and coerce results into Reports
daedalus/health.py|function|verdict|return exit code based on report states
daedalus/health.py|constant|MARKS|mapping of state to display string
daedalus/health.py|function|render|format reports for human output
daedalus/health.py|function|to_payload|convert reports to JSON-serializable dict
tests/test_worktree.py|function|worktree_root|ensures isolated temp root for worktree tests via DAEDALUS_WORKTREE_ROOT env var
tests/test_worktree.py|function|temp_git_repo|ensures temporary git repository with initial commit for testing
tests/test_worktree.py|function|test_create_worktree|guarantees create_worktree produces valid worktree with expected branch and content
tests/test_worktree.py|function|test_placement_is_outside_repo|guarantees worktree is placed outside primary repo and repo stays clean
tests/test_worktree.py|function|test_default_placement_uses_localappdata|guarantees default root uses LOCALAPPDATA and namespaces per repo digest
tests/test_worktree.py|function|test_env_override_controls_placement|guarantees DAEDALUS_WORKTREE_ROOT env overrides default placement
tests/test_worktree.py|function|test_storage_check_consulted_and_fail_closed|guarantees storage check is called and fail-closes on StorageUnavailable
tests/test_worktree.py|function|test_cleanup_worktree|guarantees cleanup removes worktree directory and git worktree list entry
tests/test_worktree.py|function|test_cleanup_failure_surfaces|guarantees removal failure raises RuntimeError with path info
tests/test_worktree.py|function|test_deregistration_failure_surfaces|guarantees git prune failure raises RuntimeError even if directory already gone
tests/test_worktree.py|function|test_commit_candidate|guarantees commit_candidate creates commit with correct message and author
tests/test_worktree.py|function|test_has_changes_tracks_candidate_worktree_only|guarantees has_changes returns False initially, True after modification
tests/test_worktree.py|function|test_reparse_detection_off_windows_rests_on_the_symlink_branch|guarantees _is_reparse_point works with simulated POSIX lstat (no Windows fields)
tests/test_worktree.py|function|test_junction_swap_cannot_delete_the_primary_repo|guarantees junction swap at worktree path raises WorktreeContainmentError and preserves primary
tests/test_worktree.py|function|test_symlink_swap_cannot_delete_the_primary_repo|guarantees symlink swap raises WorktreeContainmentError and preserves primary
tests/test_worktree.py|function|test_junction_at_the_worktree_root_is_refused|guarantees junction at root raises WorktreeContainmentError with reparse point message
tests/test_worktree.py|function|test_cleanup_refuses_a_path_outside_the_worktree_root|guarantees cleanup raises WorktreeContainmentError for path outside root
tests/test_worktree.py|function|test_cleanup_refuses_the_repo_root|guarantees cleanup raises WorktreeContainmentError for repo root
tests/test_worktree.py|function|test_cleanup_refuses_the_repo_parent|guarantees cleanup raises WorktreeContainmentError for ancestor of repo
tests/test_worktree.py|function|test_cleanup_refuses_a_renamed_worktree|guarantees cleanup raises WorktreeContainmentError for renamed worktree
tests/test_worktree.py|function|test_cleanup_refuses_a_directory_the_manager_never_allocated|guarantees cleanup raises WorktreeContainmentError for unallocated directory
tests/test_worktree.py|function|test_cleanup_refuses_the_worktree_root_itself|guarantees cleanup raises WorktreeContainmentError for root itself
tests/test_worktree.py|function|test_removal_does_not_descend_into_a_nested_junction|guarantees nested junction is unlinked, not followed, decoy intact

## DEPENDS

DEPENDS|daedalus/mapping/render.py|daedalus.mapping.reach
DEPENDS|daedalus/mapping/render.py|daedalus.mapping.switches
DEPENDS|daedalus/mapping/render.py|daedalus.mapping.drift
DEPENDS|daedalus/eval/correctness.py|daedalus.kairos.worktree
DEPENDS|daedalus/eval/correctness.py|daedalus.primary_tree
DEPENDS|daedalus/eval/correctness.py|daedalus.spine.attempt
DEPENDS|daedalus/eval/correctness.py|daedalus.eval.tasks
DEPENDS|daedalus/eval/correctness.py|daedalus.spine.cancel (conditional in _spawn_pytest)
DEPENDS|daedalus/loop.py|daedalus.progress
DEPENDS|daedalus/loop.py|daedalus.spine.attempt
DEPENDS|daedalus/loop.py|daedalus.spine.envelope
DEPENDS|daedalus/loop.py|daedalus.spine.killswitch
DEPENDS|daedalus/kairos/worktree.py|daedalus.storage (imports require_storage)
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/languages
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/parse
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/markdown
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/metrics
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/clones
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/perfile
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/cache
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/imports
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/graph
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/tokens
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/typegraph
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/churn
DEPENDS|daedalus/structcore/index.py|daedalus/structcore/ignore
DEPENDS|daedalus/health.py|daedalus.mapping (from .mapping import drift)
DEPENDS|tests/test_worktree.py|daedalus.kairos.worktree
DEPENDS|tests/test_worktree.py|daedalus.storage
DEPENDS|daedalus/spine/picker.py|daedalus.config (imported in _project_config)
DEPENDS|daedalus/spine/picker.py|daedalus.spine.attempt (lazy import in Candidate.to_task_spec)
DEPENDS|tests/test_typegraph_resolve.py|daedalus.structcore.build_index
DEPENDS|tests/test_typegraph_resolve.py|daedalus.structcore.typegraph
DEPENDS|tests/test_typegraph_resolve.py|daedalus.structcore.index

## WRITES

WRITES|daedalus/mapping/render.py|docs/architecture-map.html
WRITES|daedalus/spine/containment.py|Writes to low-labelled log files via open_low_append_log.
WRITES|daedalus/loop.py|path specified at construction (in LoopLedger.save)
WRITES|tests/test_worktree.py|temporary directories via tmp_path and created git repos/worktrees
WRITES|daedalus/mapping/drift.py|docs/architecture-state.json
WRITES|daedalus/memory/embeddings.py|SQLite database at self.db_path (including directory creation)

## READS

READS|daedalus/mapping/render.py|docs/architecture-narrative.md
READS|daedalus/mapping/render.py|.git (HEAD, refs, packed-refs)
READS|daedalus/spine/containment.py|Reads token information, job object information from the kernel.
READS|daedalus/loop.py|path specified at construction (in LoopLedger.load)
READS|daedalus/structcore/index.py|Repository root directory (walked for files)
READS|daedalus/health.py|docs/architecture-state.json (drift.load_snapshot)
READS|daedalus/health.py|git repository (via _git)
READS|daedalus/health.py|Ollama API (implied via _http_json)
READS|tests/test_worktree.py|temporary directories via tmp_path and created git repos/worktrees
READS|daedalus/mapping/drift.py|.daedalusignore

## CLAIMS

CLAIMS|daedalus/mapping/render.py|analyse_once runs reachability and switch engines exactly once per invocation and hands same reports to page, gate, re-baseline
CLAIMS|daedalus/mapping/render.py|Staleness stamp claims to describe a revision only when tree clean and every scanned module tracked
CLAIMS|daedalus/spine/containment.py|"WRITE containment: strong. Eleven distinct write/destroy vectors were tried and refused."
CLAIMS|daedalus/spine/containment.py|"NO CAPABILITY CROSSES THE BOUNDARY THAT THE LOW CHILD COULD NOT HAVE OBTAINED ITSELF."
CLAIMS|daedalus/spine/containment.py|"MIC is a write-up barrier and does not restrict reads at all."
CLAIMS|daedalus/eval/correctness.py|A base revision is only ever checked out through GitWorktreeManager, which places worktrees outside the checkout.
CLAIMS|daedalus/eval/correctness.py|The outcome regressed outranks not_fixed, and both outrank fixed; could_not_run outranks all three.
CLAIMS|daedalus/loop.py|NEVER WRITES THE PRIMARY CHECKOUT, at any setting.
CLAIMS|daedalus/loop.py|When 'daedalus.core.get_governance()' reports 'promotion_allowed: False' the loop still picks, still attempts, still gates -- and promotes nothing.
CLAIMS|daedalus/kairos/worktree.py|Module docstring claims containment via no-follow lstat checks and fresh re-classification before each syscall, but also acknowledges unresolvable microsecond windows and a retry path with multiple syscalls per verification.
CLAIMS|daedalus/structcore/index.py|All index outputs are derived and regenerate-anytime.
CLAIMS|daedalus/structcore/index.py|Dependencies are precise for Python, best-effort for other languages.
CLAIMS|daedalus/structcore/index.py|Duplicate clones are exact (Type-2) and near-miss (Type-3) clusters.
CLAIMS|daedalus/structcore/index.py|Hotspots are complexity ranking multiplied by normalized git churn.
CLAIMS|daedalus/structcore/index.py|Documents and type layers are opt-in and do not affect other outputs.
CLAIMS|daedalus/health.py|Nothing here spends money (but does network calls to Ollama)
CLAIMS|daedalus/health.py|Nothing here writes (but notes opening spine ledger may write)
CLAIMS|tests/test_worktree.py|reparse detection off Windows is the most load-bearing untested line in the module (from test_reparse_detection_off_windows_rests_on_the_symlink_branch)
CLAIMS|tests/test_worktree.py|unfixed walker destroys victim 3/3 in race condition (from test_removal_does_not_follow_a_junction_swapped_in_mid_walk)
CLAIMS|tests/test_worktree.py|shutil.rmtree with junction check fails 3/3 for last entry (from same test)
CLAIMS|daedalus/mapping/drift.py|the gate that makes the generated architecture map stick.
CLAIMS|daedalus/spine/picker.py|"NO TASK WITHOUT EVIDENCE" (module docstring)
CLAIMS|daedalus/spine/picker.py|"Cross-band comparison is therefore NOT a claim that one island beats one hotspot on evidence." (module docstring)
CLAIMS|tests/test_typegraph_resolve.py|I2: Resolution must not modify graph.SymbolResolver.defs_by_file.
CLAIMS|tests/test_typegraph_resolve.py|I5: Ambiguous imports must produce no edge and increment counter.
CLAIMS|daedalus/memory/embeddings.py|One index per search; search_report resolves exactly one index_id
CLAIMS|daedalus/memory/embeddings.py|Declared identity must match the backend; _resolved_spec enforces this
CLAIMS|daedalus/memory/embeddings.py|Dimension agreement on ingest, read, and scoring; no broadcast/truncation/zero-padding
CLAIMS|daedalus/memory/embeddings.py|Empirical coordinate-system identity via identity anchor; drift detection via IDENTITY_DRIFT_TOLERANCE
CLAIMS|daedalus/memory/embeddings.py|Journal append-only-ness enforced for watermark; record_journal_watermark refuses rollback or changed content hash
CLAIMS|daedalus/spine/attempt.py|crash-safe and cannot write to the developer's working tree
CLAIMS|daedalus/spine/attempt.py|single git choke point via _git function

## UNWIRED

UNWIRED|daedalus/mapping/render.py|esc function
UNWIRED|daedalus/mapping/render.py|_slug function
UNWIRED|daedalus/mapping/render.py|_inline function
UNWIRED|daedalus/mapping/render.py|_md_blocks function
UNWIRED|daedalus/mapping/render.py|_render_md function
UNWIRED|daedalus/mapping/render.py|NarrativeSection class (defined but only used internally via Narrative)
UNWIRED|daedalus/mapping/render.py|Narrative class (defined but only used internally)
UNWIRED|daedalus/mapping/render.py|StatusWord class? (not defined, but STATUS_VOCAB used)

## SMELL

SMELL|daedalus/spine/containment.py|JobLimits is listed in __all__ but not defined in this file; likely a missing import or definition.
SMELL|daedalus/spine/containment.py|Large module with many low-level Windows API interactions; may be a god-module.
SMELL|daedalus/loop.py|Sibling integration branches: promote_candidates mints a fresh branch per call off a freshly read primary HEAD, so N iterations leave N unmerged siblings that cannot see each other.
SMELL|daedalus/loop.py|The candidate's own gate is dropped: see LoopDriver._session_for.
SMELL|daedalus/kairos/worktree.py|Public export `remove_tree_no_follow` is listed in __all__ but the actual function definition is `_remove_tree_no_follow` (private). This mismatch may cause ImportError.