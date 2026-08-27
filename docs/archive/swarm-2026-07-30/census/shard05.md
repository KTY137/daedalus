# Census shard 5/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/mapping/inventory.py|function|digest_ok|Checks if a document's digest is still valid for its derived fields.
daedalus/mapping/inventory.py|function|harvest|Lifts human half from old inventory, lossless.
tests/test_health_surface.py|class|Vocabulary|Ensures the closed set of states and distinct marks.
tests/test_health_surface.py|class|Provenance|Ensures provenance rules and inheritance.
tests/test_health_surface.py|class|CannotRunIsNeverGreen|Ensures probes that fail to run report unknown.
tests/test_health_surface.py|class|Verdict|Ensures verdict logic correct.
tests/test_health_surface.py|class|Rendering|Ensures rendering logic does not launder not-proven states.
tests/test_health_surface.py|class|ProbesDoNotMutate|Ensures probes do not mutate the system.
tests/test_health_surface.py|class|ProbesReportBadNews|Ensures individual probes report correctly when things are broken.
daedalus/gui_catalogue.py|constant|CATALOGUE_SCHEMA|Schema identifier for the catalogue format
daedalus/gui_catalogue.py|constant|CATALOGUE_DIR|Relative path to seeded catalogue files
daedalus/gui_catalogue.py|constant|ENTRY_KINDS|Accepted entry types (component, layout, primitive, hook, token, style, library)
daedalus/gui_catalogue.py|constant|USE_MODES|Permitted usage modes (copy_in, reciprocal, reference_only)
daedalus/gui_catalogue.py|constant|LICENCE_USE_MODE|Mapping from SPDX identifiers to use modes
daedalus/gui_catalogue.py|constant|DERIVED_FIELDS|Fields that are derived and cannot be present in entry files
daedalus/gui_catalogue.py|class|CatalogueError|Exception for entry admission failures
daedalus/gui_catalogue.py|class|PropSpec|Specification of a single prop (name, type, required, default, description)
daedalus/gui_catalogue.py|class|Provenance|Provenance information (origin, url, retrieval date, source_path, note)
daedalus/gui_catalogue.py|class|CatalogueEntry|A single catalogue entry with name, kind, title, purpose, licence, provenance, etc.
daedalus/gui_catalogue.py|class|RejectedEntry|Record of an entry that could not be admitted and why
daedalus/gui_catalogue.py|class|Catalogue|Aggregate of admitted entries, rejected entries, and sources
daedalus/gui_catalogue.py|function|use_mode_for_licence|Determines allowed use mode from a licence identifier, default-deny
daedalus/gui_catalogue.py|function|load_catalogue|Loads and parses all catalogue entries from the catalogue directory (not visible in excerpt)
daedalus/gui_catalogue.py|function|parse_entry|Parses a single entry dictionary into a CatalogueEntry (not visible in excerpt)
daedalus/gui_catalogue.py|function|search|Performs a search against the catalogue using lexical and latent seeds (not visible in excerpt)
daedalus/gui_catalogue.py|function|render_for_prompt|Renders search results for inclusion in a prompt with untrusted data notices (not visible in excerpt)
daedalus/gui_catalogue.py|class?|SearchHit|Expected search hit type (not defined in visible excerpt)
daedalus/gui_catalogue.py|class?|SearchResult|Expected search result type (not defined in visible excerpt)
daedalus/conversation.py|module|conversation|Multi-turn conversation state with append-only logs and crash-safe SQLite store
daedalus/conversation.py|class|ConversationStore|Crash-safe conversation/turn/dispatch store over one SQLite file with WAL and event-sourced status
daedalus/conversation.py|class|Turn|Frozen dataclass for a single conversation turn
daedalus/conversation.py|class|DispatchLink|Frozen dataclass representing a link from a turn to a dispatch
daedalus/conversation.py|class|DispatchEvent|Frozen dataclass representing an event in a dispatch's lifecycle
daedalus/conversation.py|class|ConversationError|Base exception for store refusals
daedalus/conversation.py|class|UnknownConversation|Exception for unknown conversation
daedalus/conversation.py|class|UnknownTurn|Exception for unknown turn
daedalus/conversation.py|class|UnknownDispatch|Exception for unknown dispatch
daedalus/conversation.py|class|DuplicateDispatchRef|Exception for duplicate dispatch_ref
daedalus/conversation.py|constant|STATUS_ANSWERED|Chat turn status: reply produced without side effect
daedalus/conversation.py|constant|STATUS_PROPOSED|Chat turn status: action proposed but not dispatched
daedalus/conversation.py|constant|STATUS_ERROR|Chat turn status: exception during reply
daedalus/conversation.py|constant|TURN_STATUSES|Tuple of valid turn statuses
daedalus/conversation.py|constant|LIFECYCLE_DISPATCHED|Dispatch lifecycle event: work was sent
daedalus/conversation.py|constant|LIFECYCLE_REPORTED|Dispatch lifecycle event: report arrived
daedalus/conversation.py|constant|DISPATCH_LIFECYCLE|Tuple of valid dispatch lifecycle stages
daedalus/conversation.py|constant|OUTCOME_STATES|Re-exported from daedalus.health: closed set of outcome states
daedalus/conversation.py|constant|WORKING|Re-exported health state: working
daedalus/conversation.py|constant|PRESENT|Re-exported health state: present
daedalus/conversation.py|constant|DEGRADED|Re-exported health state: degraded
daedalus/conversation.py|constant|ABSENT|Re-exported health state: absent
daedalus/conversation.py|constant|UNKNOWN|Re-exported health state: unknown
daedalus/conversation.py|function|new_conversation_id|Generates a fresh, filename-safe, sortable conversation id
daedalus/conversation.py|function|default_db_path|Returns the path for the conversation SQLite database, overridable via environment variable
daedalus/conversation.py|function|default_store|(assumed) Returns a default ConversationStore instance
daedalus/conversation.py|function|recent_turns_context|(assumed) Builds a context string from recent turns for prompt injection
tests/test_eval_correctness.py|function|a_task|returns a standard task dict with defaults for testing
tests/test_eval_correctness.py|class|ScriptedRunner|injected test runner that returns pre-scripted statuses and records calls
tests/test_eval_correctness.py|class|SchemaTests|tests task schema validation and anti-vacuity rule
tests/test_eval_correctness.py|class|BeforeStateTests|tests before-state evaluation including G4, G5, G7, G13 guards
tests/test_eval_correctness.py|class|AfterStateTests|tests after-state evaluation and outcome precedence including G6, G7 guards
tests/test_eval_correctness.py|class|SelectionTests|tests frozen selection and run widening/narrowing with G10, G16 guards
tests/test_eval_correctness.py|class|ParseTests|tests parsing of real pytest output including G14, G15 guards
tests/test_eval_correctness.py|class|PrimaryCheckoutGuardTests|tests refusal of primary checkout as pytest directory or patch target
tests/test_eval_correctness.py|class|OverlayEscapeTests|tests overlay path escape prevention
tests/test_eval_correctness.py|class|GitReadTests|tests git verb allowlist
tests/test_eval_correctness.py|constant|F2P|module-level constant for fail_to_pass test node id
tests/test_eval_correctness.py|constant|P2P|module-level constant for pass_to_pass test node id
daedalus/build_exec.py|class|UnsafeParallelWriteError|Raised when parallel=True is requested for a wave containing write tasks, refusing the unsafe operation.
daedalus/build_exec.py|class|WaveResult|Dataclass holding the outcome of dispatching a single wave.
daedalus/build_exec.py|class|BuildRunReport|Dataclass holding the complete report of running a BuildSession.
daedalus/build_exec.py|class|WaveExecutor|Executes waves from a BuildSession via KairosScheduler.
daedalus/build_exec.py|constant|PROGRESS_SOURCE|Attribution string for progress events from this module.
daedalus/council/bus.py|constant|ENTRY_VERSION|Identifies the record format version ('dcouncil/1')
daedalus/council/bus.py|constant|ANCHOR_VERSION|Identifies the anchor file version ('dcouncil-anchor/1')
daedalus/council/bus.py|constant|ROOT|Resolved project root path (two levels up from this file)
daedalus/council/bus.py|constant|DEFAULT_COUNCIL_DIR|Default directory for council transcripts (runs/council)
daedalus/council/bus.py|constant|TURN_STATUS|Tuple of valid turn status values
daedalus/council/bus.py|constant|UNAVAILABLE_REASONS|Tuple of machine reasons for unavailable status
daedalus/council/bus.py|constant|ANOMALY_REASONS|Tuple of machine reasons for anomaly status
daedalus/council/bus.py|constant|PARTICIPANT_OUTCOMES|Tuple of participant outcome labels
daedalus/council/bus.py|constant|MAX_CONTENT_CHARS|Maximum character count for a single turn content
daedalus/council/bus.py|function|canonical_body|Returns record copy without position/identity fields for hashing
daedalus/council/bus.py|function|canonical_body_json|Returns JSON string of canonical body for deterministic hashing
daedalus/council/bus.py|function|actor_id|Generates council actor ID per ADR-010 format
daedalus/council/bus.py|function|evidence_ref|Creates evidence citation with path and SHA256 of shown bytes
daedalus/council/bus.py|function|council_store_path|Returns the JSONL file path for a given council ID
daedalus/council/bus.py|function|anchor_path|Returns the anchor file path beside a transcript
tests/test_semantic_route_wired.py|constant|AVAIL|Maps provider names to booleans indicating availability for tests.
tests/test_semantic_route_wired.py|constant|CROSS_AVAIL|Maps provider names to booleans for cross-lane availability scenario.
tests/test_semantic_route_wired.py|constant|RECEIPT_KEYS|Set of keys that the receipt must contain.
tests/test_semantic_route_wired.py|constant|INTRA_OBJECTIVE|Objective string for intra-lane tests.
tests/test_semantic_route_wired.py|constant|INTRA_TARGET|Target role for intra-lane tests.
tests/test_semantic_route_wired.py|constant|CROSS_OBJECTIVE|Objective string for cross-lane tests.
tests/test_semantic_route_wired.py|constant|CROSS_TARGET|Target role for cross-lane tests.
tests/test_semantic_route_wired.py|class|FakeOllama|Implements a real HTTP server faking the Ollama embeddings API.
tests/test_semantic_route_wired.py|class|LatentRouteSteersTests|Tests that the latent route actually steers production routing.
tests/test_semantic_route_wired.py|class|LaneGuardTests|Tests that the lane guard prevents cross-lane latent decisions.
tests/test_semantic_route_wired.py|class|FailSoftTests|Tests that no latent failure breaks routing and all are logged.
tests/test_semantic_route_wired.py|class|KillSwitchTests|Tests for the environment variable kill switch.
tests/test_semantic_route_wired.py|class|RosterThreadingTests|Tests that active_agents bounds the latent choice.
daedalus/spine/docrefs.py|constant|DOC_GLOBS|Tuple of glob patterns for documentation files to scan
daedalus/spine/docrefs.py|class|DocRefReport|Encapsulates the measurement results (resolving, broken, skipped references) with counts and to_dict method
daedalus/spine/docrefs.py|class|FixVerdict|Encapsulates the result of verifying a fix attempt (ok, verdict, detail, counts before/after)
daedalus/spine/docrefs.py|class|Reference|Represents a single documentation reference with its doc path, line, raw text, resolved module/symbol, state, and reason
daedalus/spine/docrefs.py|function|check_denominator|Verifies that an edit does not reduce the number of resolving references, enforcing the anti-gaming invariant
daedalus/spine/docrefs.py|function|extract_references|Pulls candidate code references from a prose file, returning unresolved references and lines dropped as code
daedalus/spine/docrefs.py|function|iter_doc_files|Yields sorted, deduplicated Path objects for all prose files matching DOC_GLOBS in the repo
daedalus/spine/docrefs.py|function|reference_key|Returns a stable identity string for a reference across edits (ignoring line number)
daedalus/spine/docrefs.py|function|resolve_reference|Decides whether a reference names code that exists, using AST parsing and suffix-based module resolution
daedalus/spine/docrefs.py|function|scan|Performs a full scan of the documentation corpus, returning a DocRefReport with all references resolved
daedalus/spine/docrefs.py|function|verify_fix|Verifies that a proposed fix (a string diff) actually fixes broken references without reducing resolving count
daedalus/spine/docrefs.py|function|verify_fix_counts|Compares before/after scan results and returns FixVerdict
daedalus/spine/docrefs.py|function|verify_fixes|Batch verifies multiple fixes against a precomputed report
daedalus/provider_router.py|constant|LATENT_ENV|Operator kill switch for latent route; if set to 0/false/off disables embedding-based routing.
daedalus/provider_router.py|constant|LATENT_DISABLED|Mechanism recorded when operator switched latent route off.
daedalus/provider_router.py|constant|LATENT_OVERRULED|Latent route ran and was overruled due to lane change.
daedalus/provider_router.py|constant|FENCE_DOMINANCE_THRESHOLD|Fraction threshold for blast-radius fence dominance; if exceeded, reachability check stands down.
daedalus/provider_router.py|constant|FENCE_DOMINANCE_MIN_SAMPLE|Minimum sample size for fence dominance fraction to be considered.
daedalus/provider_router.py|class|ProviderDecision|Dataclass representing provider decision with fields: provider, mode, persona, reason, sensitive, risk, reachability, latent_route.
daedalus/provider_router.py|function|select_provider|Main routing function: selects provider based on agent, objective, paths, availability, policy, repo_root, idx.
daedalus/progress.py|module|progress|Monotonic event log for work progress with closed vocabulary and mechanical evidence enforcement.
daedalus/progress.py|constant|EVENT_KINDS|Tuple of allowed event kinds.
daedalus/progress.py|constant|QUEUED|String constant "queued".
daedalus/progress.py|constant|CLAIMED|String constant "claimed".
daedalus/progress.py|constant|HEARTBEAT|String constant "heartbeat".
daedalus/progress.py|constant|GENERATING|String constant "generating".
daedalus/progress.py|constant|TOOL_RAN|String constant "tool_ran".
daedalus/progress.py|constant|GATE_VERDICT|String constant "gate_verdict".
daedalus/progress.py|constant|DISK_CHANGED|String constant "disk_changed".
daedalus/progress.py|constant|NO_CHANGE|String constant "no_change".
daedalus/progress.py|constant|PATCH_PRODUCED|String constant "patch_produced".
daedalus/progress.py|constant|DONE|String constant "done".
daedalus/progress.py|constant|DISK_EVIDENCE_BASES|Tuple of valid bases for disk change evidence.
daedalus/progress.py|constant|DEFAULT_STALL_BUDGET_S|Float default stall budget in seconds.
daedalus/progress.py|class|ProgressError|Base exception for progress module refusals.
daedalus/progress.py|class|UnknownUnit|Exception for unknown unit_id.
daedalus/progress.py|class|ProgressEvent|Immutable dataclass for one observation of work.
daedalus/progress.py|class|ProgressLog|Append-only JSONL log for events.
daedalus/progress.py|constant|DEFAULT_LOG_PATH|Default path for the progress log file.
daedalus/progress.py|function|default_log|Returns the process-wide default ProgressLog instance.
daedalus/progress.py|function|reset_default_log|Drops the cached default log instance.
daedalus/progress.py|function|open_unit|Records QUEUED, mints and returns a unit_id if none provided.
daedalus/progress.py|function|claim_unit|Records CLAIMED event.
daedalus/progress.py|function|heartbeat|Records HEARTBEAT event.
daedalus/progress.py|function|record_generating|Records GENERATING with byte count.
daedalus/progress.py|function|record_tool_ran|Records TOOL_RAN with tool name and success.
daedalus/progress.py|function|record_gate_verdict|Records GATE_VERDICT with gate name and pass status.
daedalus/progress.py|function|record_disk_change|Records DISK_CHANGED or NO_CHANGE, requires mechanical evidence basis.
daedalus/progress.py|function|record_patch_produced|Records PATCH_PRODUCED with diff hash and applied=False.
daedalus/progress.py|function|record_done|Records DONE with separate succeeded/applied facts.

## DEPENDS

DEPENDS|daedalus/provider_router.py|daedalus.semantic_route
DEPENDS|daedalus/provider_router.py|daedalus.sensitivity
DEPENDS|daedalus/provider_router.py|daedalus.structcore.graph
DEPENDS|daedalus/provider_router.py|daedalus.structcore.index
DEPENDS|daedalus/provider_router.py|daedalus.sensitivity
DEPENDS|daedalus/progress.py|daedalus.health
DEPENDS|daedalus/progress.py|daedalus.spine.envelope
DEPENDS|daedalus/memory/projection_worker.py|daedalus.providers.ollama
DEPENDS|daedalus/memory/projection_worker.py|daedalus.memory
DEPENDS|daedalus/memory/projection_worker.py|daedalus.memory.embeddings
DEPENDS|daedalus/eval/mint.py|daedalus.sensitivity.secret_floor_rule
DEPENDS|daedalus/eval/mint.py|daedalus.structcore.index.cached_index
DEPENDS|daedalus/eval/mint.py|daedalus.structcore.languages.spec_for
DEPENDS|daedalus/eval/mint.py|daedalus.structcore.parse.extract_units
DEPENDS|daedalus/structcore/dss.py|daedalus/structcore/forest
DEPENDS|tests/test_typegraph_forest.py|daedalus.structcore.dss
DEPENDS|tests/test_typegraph_forest.py|daedalus.structcore.typegraph
DEPENDS|tests/test_typegraph_forest.py|daedalus.structcore.forest
DEPENDS|tests/test_typegraph_forest.py|daedalus.structcore.index
DEPENDS|daedalus/offload.py|daedalus.metrics
DEPENDS|daedalus/offload.py|daedalus.kairos.scheduler
DEPENDS|daedalus/offload.py|daedalus.provider_router
DEPENDS|daedalus/offload.py|daedalus.verifier
DEPENDS|daedalus/offload.py|daedalus.config
DEPENDS|daedalus/offload.py|daedalus.sensitivity
DEPENDS|daedalus/offload.py|daedalus.providers
DEPENDS|daedalus/offload.py|daedalus.providers.ollama
DEPENDS|daedalus/offload.py|daedalus.doctor
DEPENDS|daedalus/offload.py|daedalus.structcore.index
DEPENDS|daedalus/offload.py|daedalus.structcore.slice
DEPENDS|daedalus/offload.py|daedalus.eval.mint
DEPENDS|tests/test_eval_mint.py|daedalus.eval.mint
DEPENDS|tests/test_killswitch.py|daedalus.spine.containment
DEPENDS|tests/test_killswitch.py|daedalus.spine.attempt

## WRITES

WRITES|daedalus/core.py|OUTBOX, INBOX, ARCHIVE directories and their JSON files
WRITES|tests/test_budget.py|Temporary ledger files (tmp_path/ledger.json)
WRITES|daedalus/mapping/inventory.py|docs/FEATURE_INVENTORY.json
WRITES|daedalus/conversation.py|runs/ikarus/conversations.sqlite3
WRITES|daedalus/council/bus.py|runs/council/<council_id>.jsonl
WRITES|daedalus/council/bus.py|runs/council/<council_id>.jsonl.anchor.json

## READS

READS|daedalus/build_exec.py|runs/build/<slug>-<ts>.json (via load_session)
READS|daedalus/council/bus.py|runs/council/<council_id>.jsonl
READS|daedalus/council/bus.py|runs/council/<council_id>.jsonl.anchor.json
READS|daedalus/spine/docrefs.py|docs/**/*.md, README.md, and Python modules under repo root
READS|daedalus/provider_router.py|environment variables: OLLAMA_HOST, DAEDALUS_LATENT_ROUTE
READS|daedalus/provider_router.py|config file (via external_write_lanes_for_repo)
READS|daedalus/provider_router.py|import graph index (via cached_index)
READS|daedalus/progress.py|runs/progress/events.jsonl
READS|daedalus/memory/projection_worker.py|memory/events.local.jsonl
READS|daedalus/eval/mint.py|<repo_root>/.git

## CLAIMS

CLAIMS|daedalus/build_exec.py|This module enforces concurrent write safety: refuses parallel=True for writes rather than silently downgrading.
CLAIMS|daedalus/council/bus.py|The transcript is tamper-evident via hash chain, fail-loud, and human-diffable.
CLAIMS|daedalus/council/bus.py|Council turns are never an input to memory recall.
CLAIMS|daedalus/council/bus.py|Silence is never an absence: every requested participant produces exactly one chained turn per round.
CLAIMS|daedalus/spine/docrefs.py|'Nothing here writes anything' and 'never imports the code it inspects'
CLAIMS|daedalus/provider_router.py|ProviderDecision: 'write = may apply; advisory = read-only proposal'
CLAIMS|daedalus/provider_router.py|_deepseek_write_allowed: 'The single source of truth for this question.'
CLAIMS|daedalus/progress.py|"The vocabulary is closed — same discipline as daedalus.health"
CLAIMS|daedalus/progress.py|"A snapshot is never cached and never reused across calls"
CLAIMS|daedalus/progress.py|"NO FABRICATED PERCENTAGE. There is deliberately no percent_complete field"
CLAIMS|daedalus/progress.py|"DURABILITY POSTURE, STATED HONESTLY: this is a plain buffered append under a process-local lock"
CLAIMS|daedalus/memory/projection_worker.py|Claims resumability via watermark stored in index, idempotency via content addressing and uniqueness constraint, and never-ahead-of-itself watermark recording.
CLAIMS|daedalus/eval/mint.py|Minted labels come from diffs that the slicer never used in its own graph, ensuring independence
CLAIMS|daedalus/eval/mint.py|Labels are scoped to files in cached_index["modules"], matching the slicer's neighborhood expansion boundary
CLAIMS|daedalus/eval/mint.py|Labels never include symbols from the target file itself, preventing circularity
CLAIMS|daedalus/eval/mint.py|Junk keywords, cross-language families, and secret-floor filters are applied to labels with transparent diagnostics
CLAIMS|daedalus/structcore/dss.py|the module is dependency-free and read-only; it selects context and never changes source code or treats relevance as fitness signal
CLAIMS|tests/test_typegraph_forest.py|The layer is additive and does not alter the file half (docstring of TheFileHalfDoesNotMove)
CLAIMS|tests/test_typegraph_forest.py|Type nodes cannot be packed (docstring of ATypeNodeCannotBePacked)
CLAIMS|tests/test_typegraph_forest.py|The lens is not a diffusion channel (docstring of TheLensIsNotAChannel)
CLAIMS|tests/test_typegraph_forest.py|Builds are deterministic (docstring of TheBuildIsDeterministic)
CLAIMS|daedalus/offload.py|docstring: 'The offload bridge -- the single seam that actually hands work to the free bench'
CLAIMS|daedalus/offload.py|_auto_mint docstring: 'Mint one quarantined eval task from a LANDED write'
CLAIMS|daedalus/offload.py|_repo_snapshot docstring: 'Content-hash every smallish text file under the repo'
CLAIMS|daedalus/offload.py|_slice_context docstring: 'Gated distilled context for the LOCAL (trusted) lane'
CLAIMS|tests/test_eval_mint.py|Every assertion here ultimately serves the ANTI-CIRCULARITY guarantee the module exists for
CLAIMS|tests/test_killswitch.py|The kill switch must actually stop things, and the latency must be MEASURED.
CLAIMS|tests/test_killswitch.py|Measured numbers are printed and asserted, so the bound is enforced on every run rather than admired once.
CLAIMS|tests/test_gate_discrimination.py|The real measurement is deliberately NOT part of this file.
CLAIMS|tests/test_gate_containment.py|The gate is the execution point, containment requires bounded handle inheritance with exactly one append-only Low-integrity handle crossing the boundary.
CLAIMS|tests/test_gate_containment.py|test_LOW_APPEND_THROUGH_THE_INHERITED_HANDLE_WORKS: if this test fails, the rest of the file's refusal tests become worthless.
CLAIMS|tests/test_gate_containment.py|The shipped mask is exactly 0x00100084 and os.fstat is the reason FILE_READ_ATTRIBUTES is included.

## UNWIRED

UNWIRED|daedalus/cli.py|_council
UNWIRED|daedalus/core.py|provider_health (public function not called within core.py)
UNWIRED|daedalus/core.py|model_resources (public function not called within core.py)
UNWIRED|daedalus/core.py|get_queue (public function not called within core.py)
UNWIRED|daedalus/core.py|get_squads (public function not called within core.py)
UNWIRED|daedalus/core.py|enforcement_status (public function not called within core.py)
UNWIRED|daedalus/core.py|get_quality (public function not called within core.py)
UNWIRED|daedalus/core.py|routing_summary (public function not called within core.py)

## SMELL

SMELL|daedalus/structcore/markdown.py|Fence detection logic duplicated in _headings and _content_lines.
SMELL|tests/test_eval_correctness.py|unused import: harness from daedalus.eval is imported but never referenced in the file.
SMELL|daedalus/build_exec.py|Depends on private function daedalus.spine.attempt._as_predicate
SMELL|daedalus/build_exec.py|Provided file content truncated; missing implementation of write-containing wave dispatch.
SMELL|daedalus/provider_router.py|select_provider is a large function (90+ lines) with multiple branches covering different policies and fallbacks; could be a god-function.