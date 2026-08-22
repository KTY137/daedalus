# Census shard 4/20

Structural facts extracted by 300 independent agents, each of which saw only its own slice. Transcriptions by a cheap model: expect some to be wrong or incomplete.

## Symbols

daedalus/core.py|constant|SUGGESTED_MODELS|List of recommended Ollama models with reasons
daedalus/core.py|constant|GOVERNANCE_STATES|Tuple of possible governance gate states
daedalus/core.py|function|now_iso|Returns current UTC datetime in ISO format
daedalus/core.py|function|envelope|Builds a standardized API response dict with ok, generated_at, project, warnings, and extra payload
daedalus/core.py|function|team_config|Loads and returns team configuration for a project from project config and defaults
daedalus/core.py|function|provider_health|Returns provider health status for ollama and claude_cli
daedalus/core.py|function|model_resources|Queries Ollama for model list, disk usage, and returns resource estimates
daedalus/core.py|function|watcher_status|Finds file_bridge watcher processes and returns their status, detecting stale ones
daedalus/core.py|function|get_queue|Reads pending, report, and processed items from OUTBOX, INBOX, ARCHIVE
daedalus/core.py|function|get_squads|Returns squad configuration with agent details from project config and loaded agents
daedalus/core.py|function|enforcement_status|Checks AGENTS.md, CLAUDE.md for enforcement markers and state file existence
daedalus/core.py|function|get_quality|Returns quality gate status: schema validation, local_only fail-closed, watcher staleness, fallback alarm
daedalus/core.py|function|routing_summary|Recommends a routing lane based on project default, watcher staleness, fallback alarm, and Ollama availability
Route this task to Claude or local Ollama.
daedalus/file_bridge.py|constant|ROOT|Root directory of the project, parent of outbox/inbox/runs.
daedalus/file_bridge.py|constant|OUTBOX|Directory where enqueued request files are placed.
daedalus/file_bridge.py|constant|INBOX|Directory where report files are placed after processing.
daedalus/file_bridge.py|constant|ARCHIVE|Directory where processed requests are moved after completion.
daedalus/file_bridge.py|constant|HEARTBEAT_PATH|Path to the watcher heartbeat file for liveness checks.
daedalus/file_bridge.py|constant|IDLE_BEAT_EVERY_S|Interval in seconds for idle watcher heartbeat.
daedalus/file_bridge.py|constant|STALE_AFTER_S|Time after which a heartbeat is considered stale.
daedalus/file_bridge.py|constant|BUSY_BUDGET_S|Maximum time a watcher can be busy before considered wedged.
daedalus/file_bridge.py|constant|CODEX_INLINE_BRIEF_CHARS|Character threshold for codex inline brief warning.
daedalus/file_bridge.py|constant|MAX_ATTEMPTS|Maximum number of dispatch attempts before quarantine.
daedalus/file_bridge.py|constant|SETTLE_GRACE_S|Grace time for incomplete request file to settle.
daedalus/file_bridge.py|class|WatcherNotRunning|Raised by enqueue() when no watcher is alive to consume the request.
daedalus/file_bridge.py|function|codex_inline_brief_warning|Returns a warning string when codex-lane objective smells like an inline task brief, else None.
daedalus/file_bridge.py|function|enqueue|Drops one task request into the outbox for watcher dispatch, with trace, consumer check, and atomic publication.
daedalus/file_bridge.py|function|quarantine_request|Takes a request out of the watcher's way permanently and visibly, writing a quarantined report and moving the request.
daedalus/file_bridge.py|function|process_request|Processes one request exactly once across crashes, producing report, log line, memory record, and archive move.
daedalus/structcore/markdown.py|constant|DOCUMENT_PARSE_VERSION|Parse version string for document parsing.
daedalus/structcore/markdown.py|constant|MAX_HEADING_LEVEL|Maximum heading level (6).
daedalus/structcore/markdown.py|constant|DOCUMENT_KIND|Discriminator string 'document' for module entries.
daedalus/structcore/markdown.py|constant|WIKI_KINDS|Tuple of wikilink kinds (wiki, code, type, deferred).
daedalus/structcore/markdown.py|function|is_document|Determines if a modules entry is a document based on attributes.
daedalus/structcore/markdown.py|function|code_modules|Returns index modules with documents removed.
daedalus/structcore/markdown.py|function|document_modules|Returns index modules restricted to documents.
daedalus/structcore/markdown.py|function|slugify|Generates GitHub-style anchor slug from heading title.
daedalus/structcore/markdown.py|class|DocSection|Represents a document section with heading, body, and metadata.
daedalus/structcore/markdown.py|class|DocLink|Represents a link occurrence with classification and metadata.
daedalus/structcore/markdown.py|class|DocumentParse|Represents a full document parse with sections and links.
daedalus/skills.py|constant|SPEC_URL|URL of the skill specification
daedalus/skills.py|constant|SPEC_COMMIT|Git commit of the spec revision
daedalus/skills.py|constant|SPEC_BLOB_SHA|Git blob sha of the spec file
daedalus/skills.py|constant|SPEC_SHA256|SHA256 of spec bytes
daedalus/skills.py|constant|SPEC_LICENCE|Licence of the spec
daedalus/skills.py|constant|SKILL_FILENAME|Filename for skill files
daedalus/skills.py|constant|ALLOWED_FRONTMATTER_FIELDS|Closed set of permitted frontmatter keys
daedalus/skills.py|constant|MAX_NAME_CHARS|Max characters for skill name as per spec
daedalus/skills.py|constant|MAX_DESCRIPTION_CHARS|Max characters for description as per spec
daedalus/skills.py|constant|MAX_COMPATIBILITY_CHARS|Max characters for compatibility field as per spec
daedalus/skills.py|constant|MAX_SKILL_MD_BYTES|Max bytes for entire SKILL.md file
daedalus/skills.py|constant|MAX_FRONTMATTER_BYTES|Max bytes for frontmatter block
daedalus/skills.py|constant|MAX_FRONTMATTER_LINES|Max lines for frontmatter block
daedalus/skills.py|constant|MAX_METADATA_KEYS|Max keys in metadata mapping
daedalus/skills.py|constant|MAX_METADATA_VALUE_CHARS|Max chars per metadata value
daedalus/skills.py|constant|MAX_ALLOWED_TOOLS_CHARS|Max chars for allowed-tools field
daedalus/skills.py|constant|MAX_SKILLS_PER_ROOT|Max skills discoverable per root directory
daedalus/skills.py|constant|MAX_BUNDLED_PATHS_LISTED|Max bundled paths listed per skill
daedalus/skills.py|constant|MAX_BODY_CHARS_TO_MODEL|Max body chars rendered to model
daedalus/skills.py|constant|SKILL_DATA_NOTICE|Notice prepended to skill data before model
daedalus/skills.py|constant|SKILL_OPEN|Fence opening for skill data
daedalus/skills.py|constant|SKILL_CLOSE|Fence closing for skill data
daedalus/skills.py|class|SkillError|Exception for skill load failures with all reasons
daedalus/skills.py|class|Skill|Validated skill as inert data with all fields
daedalus/skills.py|class|SkillDefect|Represents a directory that failed to load as a skill
daedalus/skills.py|class|LoadReport|Result of scanning one root: skills, defects, notes
daedalus/skills.py|function|parse_frontmatter|Parses SKILL.md frontmatter into dict and body
daedalus/skills.py|function|validate_frontmatter|Validates parsed frontmatter against constraints
daedalus/skills.py|function|load_skill|Loads a single skill from a directory
daedalus/skills.py|function|discover|Discovers all skills under a root directory
daedalus/skills.py|function|find_skill|Finds a skill by name in a LoadReport
daedalus/skills.py|function|render_untrusted|Renders skill data for model consumption with safety fences
daedalus/skills.py|function|render_catalog|Renders a catalog of skills for listing
daedalus/skills.py|function|describe|Returns a human-readable description of the skill module
daedalus/mapping/switches.py|constant|SCHEMA|Schema identifier for the switch report format.
daedalus/mapping/switches.py|class|EnvSite|Dataclass for one physical read of an environment variable.
daedalus/mapping/switches.py|class|EnvSwitch|Dataclass for all reads of one environment variable, reconciled.
daedalus/mapping/switches.py|class|ParamSwitch|Dataclass for a public entry point boolean parameter that defaults to off.
daedalus/mapping/switches.py|class|ConfigSwitch|Dataclass for a config key whose value is off-shaped.
daedalus/mapping/switches.py|class|DocDrift|Dataclass for a name the docs and the code disagree about.
daedalus/mapping/switches.py|class|SwitchCounts|Dataclass for counts of various switch types.
daedalus/mapping/switches.py|class|SwitchReport|Dataclass for the full switch report, with methods to get dark switches and convert to dict.
daedalus/council/vendors.py|constant|STATUSES|Closed tuple of transport outcomes for one ask
daedalus/council/vendors.py|constant|LANES|Egress lanes: 'trusted' and 'untrusted'
daedalus/council/vendors.py|constant|UNAVAILABLE_REASONS|Machine reasons for unavailable status
daedalus/council/vendors.py|dataclass|VendorReply|One vendor's answer to one question, with transport status and provenance, no verdict field
daedalus/council/vendors.py|dataclass|FloorRefusal|A secret-floor hit, naming the rule and channel
daedalus/council/vendors.py|dataclass|RunResult|What an injected runner must return
daedalus/council/vendors.py|dataclass|CouncilProfile|A read-only, tool-less, one-shot invocation of a vendor CLI
daedalus/council/vendors.py|dict|COUNCIL_PROFILES|Predefined profiles for anthropic and openai vendors
daedalus/council/vendors.py|class|CouncilAdapter|Base adapter enforcing secret floor, token ceiling, timed dispatch, and status mapping
daedalus/council/vendors.py|function|actor_id|Produce namespaced actor id 'council.<vendor>.<model>'
daedalus/council/vendors.py|function|model_family|Coarse weight family for independence classification
daedalus/council/vendors.py|function|floor_check|Run secret floor before anything leaves the process
daedalus/council/vendors.py|function|council_cwd|Return a fresh, empty temp directory for council subprocess, not under repo_root
daedalus/council/vendors.py|function|council_env|Return environment with OLLAMA_HOST stripped, never set or inherited
daedalus/council/vendors.py|function|run_managed|Default runner spawning argv under ManagedProcess with stdin from temp file and timeout tree kill
daedalus/council/vendors.py|constant|DEFAULT_BENCH_OLLAMA_HOST|Default host for bench Ollama (http://100.119.126.9:11434)
daedalus/council/vendors.py|constant|DEFAULT_LOCAL_OLLAMA_HOST|Default host for local Ollama (http://127.0.0.1:11434)
daedalus/council/vendors.py|constant|BENCH_SSH_TARGET|SSH target for bench machine
daedalus/council/vendors.py|constant|PROMPT_DATA_NOTICE|Warning prepended to every outbound prompt that evidence is data, not instructions
tests/test_budget.py|function|led|Provides a fixture for a Ledger with $1.00 ceiling and 10 calls.
tests/test_budget.py|function|test_unreadable_ledger_refuses|Guarantees that unreadable ledger (corrupt, empty, invalid) raises BudgetUnavailable.
tests/test_budget.py|function|test_a_missing_ledger_is_a_fresh_ledger_not_a_failure|Guarantees missing ledger is assumed fresh (spent=0).
tests/test_budget.py|function|test_an_unreadable_ceiling_refuses|Guarantees unreadable environment variables for ceiling/max_calls/period raise BudgetUnavailable.
tests/test_budget.py|function|test_no_configuration_means_the_default_cap_not_infinity|Guarantees no env vars = default cap (not infinity).
tests/test_budget.py|function|test_a_lock_we_cannot_take_refuses|Guarantees that failure to acquire file lock raises BudgetUnavailable.
tests/test_budget.py|function|test_an_unwritable_ledger_refuses|Guarantees that failure to write ledger raises BudgetUnavailable.
tests/test_budget.py|function|test_reserve_is_on_disk_before_it_returns|Guarantees reservation is persisted before return.
tests/test_budget.py|function|test_the_call_itself_sees_the_money_already_committed|Guarantees that call sees reservation committed.
tests/test_budget.py|function|test_a_second_caller_cannot_spend_what_the_first_reserved|Guarantees that reserved money is committed and not double-spent.
tests/test_budget.py|function|test_guard_settles_on_exception_it_does_not_release|Guarantees that exception within guard still settles (spends) and releases reservation.
tests/test_budget.py|function|test_release_is_the_one_fail_open_lever_and_demands_a_reason|Guarantees release requires a reason and zeroes out reservation.
tests/test_budget.py|function|test_refusal_names_ceiling_spend_and_what_was_refused|Guarantees refusal error includes ceiling, spent, asked, vendor, and env var hint.
tests/test_budget.py|function|test_the_call_count_cap_is_a_separate_named_axis|Guarantees call-count cap is separate axis from dollar cap.
tests/test_budget.py|function|test_a_single_call_larger_than_the_whole_ceiling_is_refused|Guarantees single call larger than ceiling is refused.
tests/test_budget.py|function|test_cross_process_race_never_oversubscribes_the_ceiling|Guarantees cross-process race does not oversubscribe ceiling (8 processes, $0.25 each, $1 ceiling -> 4 wins).
tests/test_budget.py|function|test_the_lock_is_actually_exclusive|Guarantees file lock excludes concurrent holders.
tests/test_budget.py|function|test_an_unpriced_vendor_costs_the_worst_case_never_zero|Guarantees unknown vendor is priced at UNKNOWN_CALL_USD.
tests/test_budget.py|function|test_the_unknown_rate_exceeds_the_most_expensive_measured_call|Guarantees unknown rate exceeds most expensive measured call.
tests/test_budget.py|function|test_strict_mode_refuses_an_unknown_price_outright|Guarantees strict mode (ENV_ON_UNKNOWN=refuse) raises UnknownPrice.
tests/test_budget.py|function|test_local_is_free_only_where_the_shared_predicate_says_this_machine|Guarantees only loopback IP prices as free; else cost >0.
tests/test_budget.py|function|test_a_local_vendor_with_no_host_is_not_provably_local|Guarantees vendor named 'local' without host is not priced as free.
tests/test_budget.py|function|test_settling_with_an_unknown_actual_charges_the_estimate|Guarantees settling with None charges the estimate.
tests/test_budget.py|function|test_an_overrun_is_recorded_not_clamped|Guarantees overrun is recorded exactly, not clamped.
tests/test_budget.py|function|test_a_token_estimate_never_prices_a_real_call_at_zero|Guarantees token estimate never zero.
tests/test_budget.py|function|test_with_budget_remaining_the_call_proceeds|Guarantees call proceeds when budget remains.
tests/test_budget.py|function|test_many_small_calls_all_proceed_under_the_ceiling|Guarantees many small calls proceed under ceiling.
tests/test_budget.py|function|test_a_free_local_call_costs_nothing_and_stays_allowed|Guarantees free local call costs nothing and doesn't count against billable caps.
tests/test_budget.py|function|test_a_zero_price_that_is_not_certified_local_still_counts|Guarantees zero price not certified local still counts against call cap.
tests/test_budget.py|function|test_the_period_rolls_over_so_the_cap_does_not_become_permanent|Guarantees period rollover resets spend.
tests/test_budget.py|function|test_a_total_period_never_rolls_over|Guarantees 'total' period never rolls over.
tests/test_budget.py|function|test_money_in_flight_survives_the_rollover|Guarantees in-flight reservations survive rollover.
tests/test_budget.py|function|test_a_paid_binary_is_recognised_however_it_is_reached|Guarantees paid binaries (claude, codex, etc.) are recognized regardless of path or shell.
tests/test_budget.py|function|test_free_work_is_not_billed|Guarantees free work (git, python, etc.) is not billed.
tests/test_budget.py|function|test_a_paid_endpoint_is_recognised|Guarantees paid API endpoints (deepseek, anthropic, openai, remote_inference) are recognized.
tests/test_budget.py|function|test_free_requests_are_not_billed|Guarantees free requests (localhost, non-inference endpoints) are not billed.
tests/test_budget.py|function|test_a_urllib_Request_object_is_classified_like_its_url|Guarantees urllib.Request objects are classified by URL.
tests/test_budget.py|function|test_the_interposer_refuses_BEFORE_the_binary_is_spawned|Guarantees interposer refuses before subprocess.run.
tests/test_budget.py|function|test_the_interposer_lets_a_funded_call_through_exactly_once|Guarantees interposer lets funded call through exactly once.
tests/test_budget.py|function|test_the_interposer_does_not_touch_free_work|Guarantees interposer does not bill free work.
tests/test_budget.py|function|test_the_interposer_stops_the_canary_fanout_dead|Guarantees interposer stops excessive fan-out.
daedalus/mapping/inventory.py|constant|SCHEMA|Identifies the version of the inventory schema.
daedalus/mapping/inventory.py|constant|INVENTORY_REL|Relative path to the feature inventory file.
daedalus/mapping/inventory.py|constant|DIGEST_KEY|Key used for the digest in the inventory document.
daedalus/mapping/inventory.py|constant|AREA_HUMAN_FIELDS|Human-owned fields on an area record.
daedalus/mapping/inventory.py|constant|ENV_HUMAN_FIELDS|Human-owned fields on an env var record.
daedalus/mapping/inventory.py|constant|FEATURE_HUMAN_FIELDS|Human-owned fields on a feature record.
daedalus/mapping/inventory.py|constant|STATUS_BY_CLASS|Maps reach classification to inventory status.
daedalus/mapping/inventory.py|function|annotation_overreach|Returns list of annotation keys carrying fields a human is not allowed to set.

## DEPENDS

DEPENDS|daedalus/core.py|daedalus.sensitivity
DEPENDS|daedalus/council/vendors.py|..providers._ollama_native
DEPENDS|daedalus/council/vendors.py|..providers._openai_compat
DEPENDS|daedalus/council/vendors.py|..sensitivity
DEPENDS|daedalus/council/vendors.py|..spine.cancel
DEPENDS|daedalus/council/vendors.py|..structcore.tokens
DEPENDS|daedalus/council/vendors.py|.bus
DEPENDS|tests/test_budget.py|daedalus.budget
DEPENDS|tests/test_budget.py|daedalus.sensitivity
DEPENDS|tests/test_health_surface.py|daedalus
DEPENDS|tests/test_health_surface.py|daedalus.health
DEPENDS|tests/test_health_surface.py|daedalus.spine.ledger
DEPENDS|tests/test_health_surface.py|daedalus.memory
DEPENDS|tests/test_health_surface.py|daedalus.file_bridge
DEPENDS|tests/test_health_surface.py|daedalus.spine.picker
DEPENDS|tests/test_health_surface.py|daedalus.mapping.drift
DEPENDS|daedalus/gui_catalogue.py|daedalus.context_plan
DEPENDS|daedalus/gui_catalogue.py|daedalus.council.vendors
DEPENDS|daedalus/conversation.py|daedalus.health
DEPENDS|tests/test_eval_correctness.py|daedalus.eval.correctness
DEPENDS|tests/test_eval_correctness.py|daedalus.eval.harness
DEPENDS|tests/test_eval_correctness.py|daedalus.eval.tasks
DEPENDS|tests/test_eval_correctness.py|daedalus.spine.attempt
DEPENDS|daedalus/build_exec.py|daedalus.progress
DEPENDS|daedalus/build_exec.py|daedalus.build
DEPENDS|daedalus/build_exec.py|daedalus.kairos.scheduler
DEPENDS|daedalus/build_exec.py|daedalus.spine.attempt
DEPENDS|daedalus/council/bus.py|daedalus.sensitivity.secret_floor_rule
DEPENDS|tests/test_semantic_route_wired.py|daedalus.semantic_route
DEPENDS|tests/test_semantic_route_wired.py|daedalus.provider_router
DEPENDS|tests/test_semantic_route_wired.py|daedalus.router
DEPENDS|daedalus/provider_router.py|daedalus.config
DEPENDS|daedalus/provider_router.py|daedalus.providers
DEPENDS|daedalus/provider_router.py|daedalus.providers.personas

## WRITES

WRITES|daedalus/cli.py|runs/drafts/ (via drafts module)
WRITES|daedalus/cli.py|runs/build/ (via plan_build snapshot)
WRITES|tests/test_skills.py|temporary directories (tempfile.TemporaryDirectory)
WRITES|daedalus/budget.py|runs/budget/ledger.json
WRITES|daedalus/budget.py|budget lock file (path passed to _BudgetLock)
WRITES|daedalus/council/canary.py|runs/canary/history.jsonl

## READS

READS|daedalus/budget.py|environment variables: DAEDALUS_BUDGET_LEDGER, DAEDALUS_BUDGET_USD, DAEDALUS_BUDGET_MAX_CALLS, DAEDALUS_BUDGET_PERIOD, DAEDALUS_BUDGET_ON_UNKNOWN, DAEDALUS_SUBSCRIPTION_VENDORS
READS|daedalus/budget.py|runs/budget/ledger.json
READS|daedalus/eval/harness.py|repo files via os.walk and open
READS|daedalus/council/canary.py|runs/canary/history.jsonl (via load_history)
READS|daedalus/core.py|Project config files, agent definitions, repo status via git, queue JSON files
READS|daedalus/skills.py|Reads SKILL.md files from directories specified at runtime via discover() and load_skill().
READS|tests/test_budget.py|Environment variables (ENV_CEILING, ENV_MAX_CALLS, ENV_PERIOD, etc.)
READS|tests/test_budget.py|Temporary ledger files (tmp_path/ledger.json)
READS|daedalus/mapping/inventory.py|pyproject.toml
READS|daedalus/conversation.py|runs/ikarus/conversations.sqlite3

## CLAIMS

CLAIMS|daedalus/core.py|_gov_write_confinement measures write confinement by calling the live predicate
CLAIMS|daedalus/structcore/markdown.py|Guarantees len(result) <= len(text) by construction for document_skeleton.
CLAIMS|daedalus/structcore/markdown.py|Guarantees links inside code fences are not parsed.
CLAIMS|daedalus/structcore/markdown.py|Guarantees that a link that does not resolve is dropped and counted, never guessed.
CLAIMS|daedalus/skills.py|This module cannot execute anything: no process-starting stdlib module, dynamic-import machinery, or built-ins that turn a string into running code are named in this file.
CLAIMS|daedalus/skills.py|A skill is loaded whole or not at all; no partial Skill is returned.
CLAIMS|daedalus/skills.py|Malformed skills are reported via SkillDefect, never silently skipped.
CLAIMS|daedalus/skills.py|The frontmatter parser is a strict scanner, not a YAML library, to avoid dependency and attack surface.
CLAIMS|daedalus/skills.py|The allowed-tools field is stored as inert text, never parsed into a permission.
CLAIMS|daedalus/skills.py|This module is deliberately NOT wired into routing, the picker, or any dispatch path.
CLAIMS|daedalus/mapping/switches.py|Mechanical inventory of every switch that can turn a built feature off.
CLAIMS|daedalus/council/vendors.py|Every adapter exposes the same shape -- ask(prompt, *, role, timeout_s, model=None) -> VendorReply -- over four vendors
CLAIMS|daedalus/council/vendors.py|This module produces EVIDENCE, never a decision
CLAIMS|daedalus/council/vendors.py|Nothing here writes, edits, applies or promotes anything
CLAIMS|daedalus/council/vendors.py|Council records are NEVER an input to memory recall
CLAIMS|daedalus/council/vendors.py|A reviewer must be a COMPLETION, NOT AN AGENT
CLAIMS|tests/test_budget.py|test_a_missing_ledger_is_a_fresh_ledger_not_a_failure: The one benign read failure: nothing spent yet is unambiguous.
CLAIMS|tests/test_budget.py|test_no_configuration_means_the_default_cap_not_infinity: Absence of configuration is not absence of a cap.
CLAIMS|tests/test_budget.py|test_an_unpriced_vendor_costs_the_worst_case_never_zero: Unknown vendor costs worst case never zero.
CLAIMS|tests/test_budget.py|test_a_free_local_call_costs_nothing_and_stays_allowed: The call cap bounds BILLABLE fan-out.
CLAIMS|tests/test_budget.py|test_a_zero_price_that_is_not_certified_local_still_counts: Only certified free_local gets free pass.
CLAIMS|daedalus/mapping/inventory.py|This module replaces the typing. It derives every mechanical field from the same single walk of the tree
CLAIMS|daedalus/mapping/inventory.py|LOSSLESS by contract (harvest)
CLAIMS|daedalus/mapping/inventory.py|Does this document's own digest still cover its own derived fields? (digest_ok)
CLAIMS|daedalus/gui_catalogue.py|default-deny for licences: unrecognised licence identifier raises an error
CLAIMS|daedalus/gui_catalogue.py|never decides that source may be copied; use_mode is derived from LICENCE_USE_MODE
CLAIMS|daedalus/gui_catalogue.py|never assumes a licence; requires explicit SPDX or known identifier
CLAIMS|daedalus/conversation.py|A turn can cause zero or more dispatches, each reportable more than once, distinct from spine.ledger's single-resolution contract
CLAIMS|tests/test_eval_correctness.py|Every guard in this file has been verified red by actually disabling it.
CLAIMS|tests/test_eval_correctness.py|An absolute path is refused (but is not a second guard, dominated by containment check).
CLAIMS|tests/test_eval_correctness.py|A skip or missing test is not proof of failure, and cannot contribute to a verdict.
CLAIMS|tests/test_eval_correctness.py|The digest is stable across declaration order and covers all fields that affect outcome.

## UNWIRED

UNWIRED|daedalus/cli.py|_build
UNWIRED|daedalus/cli.py|_init
UNWIRED|daedalus/cli.py|_projects
UNWIRED|daedalus/cli.py|_accelerators
UNWIRED|daedalus/cli.py|_context
UNWIRED|daedalus/cli.py|_agents
UNWIRED|daedalus/cli.py|_categories
UNWIRED|daedalus/cli.py|_drafts

## SMELL

SMELL|tests/test_typegraph_determinism.py|Test file has extensive inline documentation (390+ lines of comments) that duplicates information possibly present in other test files
SMELL|daedalus/structcore/typegraph.py|Large module combining node id generation, naming, resolution, and outcome types; potential for splitting
SMELL|daedalus/core.py|God-object: file handles model resources, queue, squads, governance, health – multiple concerns in one module
SMELL|daedalus/core.py|Side-effect in _probe_local_only_fail_closed: swaps module global _try_ikarus via globals()
SMELL|daedalus/core.py|_CONFINEMENT_PROBE_DENIED defined but only used in truncated part of _gov_write_confinement; may be dead code if that function is never called