"""Gate-0 registry and conformance contract for effectful runtime entrypoints.

This module is deliberately *not* an operating-system sandbox and does not
pretend that a Python caller cannot bypass it.  It does two smaller, testable
jobs for the canonical Daedalus kernel:

* keep one deterministic inventory of externally reachable runtime starts;
* refuse an effect start when its entrypoint, effect set, or required guard
  decisions are unknown.

Existing policy modules remain authoritative.  A ``GuardDecision`` is evidence
that one of those contracts ran; this module never broadens that decision and
contains no second allow-list.  The static conformance pass makes legacy direct
starts and newly discovered, unregistered starts visible.  Gate 0 is not closed
until every production-capable row is wired through :func:`begin_effect`.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


class Surface(str, Enum):
    CLI = "cli"
    WEB_API = "web_api"
    FILE_BRIDGE = "file_bridge"
    MCP = "mcp"
    PYTHON = "python"
    CLAUDE = "claude"
    CODEX = "codex"
    OLLAMA = "ollama"
    WORKTREE = "worktree"


class Effect(str, Enum):
    FILESYSTEM_WRITE = "filesystem_write"
    PROCESS_SPAWN = "process_spawn"
    PROCESS_CONTROL = "process_control"
    NETWORK_EGRESS = "network_egress"
    LISTEN_SOCKET = "listen_socket"
    REPOSITORY_MUTATION = "repository_mutation"
    SPEND = "spend"
    SECRETS = "secrets"


class Wiring(str, Enum):
    """How a row reaches the canonical start contract today."""

    CENTRAL = "central"
    LOCAL_GUARDS = "local_guards"
    INVENTORY_ONLY = "inventory_only"
    UNGUARDED = "unguarded"
    ABSENT = "absent"


@dataclass(frozen=True)
class GuardAnchor:
    """A mechanically checkable call expected at a local legacy boundary."""

    target: str
    call: str


@dataclass(frozen=True)
class EntrypointSpec:
    id: str
    surface: Surface
    target: str
    effects: tuple[Effect, ...]
    guard_contracts: tuple[str, ...]
    wiring: Wiring
    runtime_id: str = ""
    anchors: tuple[GuardAnchor, ...] = ()
    notes: str = ""
    migration: str = ""
    discoverable: bool = True


@dataclass(frozen=True)
class GuardDecision:
    """Result of an existing policy/containment contract.

    ``contract`` must be one of the contracts declared by the registry row.
    ``evidence`` is an inspectable locator or terse deterministic reason.  A
    model assertion such as ``"looks safe"`` is not a valid evidence boundary;
    callers are responsible for invoking the named contract.
    """

    contract: str
    allowed: bool
    evidence: str


@dataclass(frozen=True)
class EffectStartReceipt:
    entrypoint_id: str
    target: str
    runtime_id: str
    requested_effects: tuple[str, ...]
    guard_decisions: tuple[GuardDecision, ...]
    registry_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "entrypoint_id": self.entrypoint_id,
            "target": self.target,
            "runtime_id": self.runtime_id,
            "requested_effects": list(self.requested_effects),
            "guard_decisions": [asdict(row) for row in self.guard_decisions],
            "registry_sha256": self.registry_sha256,
            "receipt_sha256": self.receipt_sha256,
            "security_boundary_claimed": False,
        }


class EffectBoundaryError(RuntimeError):
    pass


class UnregisteredEntrypoint(EffectBoundaryError):
    pass


class EffectStartRefused(EffectBoundaryError):
    pass


# Named contracts stay in their existing modules; this registry does not
# reimplement their decisions.  The boolean says whether a concrete mechanical
# implementation exists today.  Owner approval is implemented as an authenticated, one-use capability and
# is mechanically checked before the legacy promotion worktree is created. A
# missing contract can be required by an UNGUARDED row but can never be used to
# open a CENTRAL row.
GUARD_CONTRACT_IMPLEMENTED: Mapping[str, bool] = MappingProxyType(
    {
        "budget.process_guard": True,
        "containment.attempt": True,
        "containment.worktree": True,
        "file_bridge.crash_journal": True,
        "provider.egress_policy": True,
        "provider.write_policy": True,
        "promotion.owner_approval": True,
        "runtime.adapter_profile": True,
        "spine.intent_ledger": True,
        "web.authenticated_bind": True,
    }
)
POLICY_CONTRACTS = frozenset(GUARD_CONTRACT_IMPLEMENTED)


# Revision-1 Gate-0 inventory.  Rows with LOCAL_GUARDS name the protection that
# actually exists in the source today.  INVENTORY_ONLY is an explicit Gate-0
# gap, not a euphemism for conformance.  UNGUARDED is also a default conformance
# blocker.  ABSENT records a required surface that does not exist (there is MCP
# configuration inspection, but no Daedalus MCP runtime).
ENTRYPOINTS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        id="cli.daedalus",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.entry:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(GuardAnchor("daedalus.interfaces.cli.entry:main", "install_process_guard"),),
        notes="Console script installs the spend guard, then dispatches local subcommands.",
    ),
    EntrypointSpec(
        id="cli.daedalus_chip",
        surface=Surface.CLI,
        target="daedalus.chip_design.cli:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
        ),
        guard_contracts=(
            "budget.process_guard",
            "provider.write_policy",
            "containment.attempt",
        ),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.chip_design.cli:main", "run_admitted_eda"),
            GuardAnchor(
                "daedalus.chip_design.executor:run_admitted_eda",
                "begin_effect",
            ),
        ),
        notes=(
            "The daedalus-chip console owner delegates each admitted live EDA "
            "run through run_admitted_eda with an injected non-runtime effect "
            "authorization. One anchor proves the direct CLI delegation and "
            "the second names the durable begin_effect consumption that owns "
            "the workspace writes. Dry-run inspection is effect-free. The "
            "live row requests and grants no kernel network-egress or secret "
            "capability; without an OS sandbox this is not proof that Vivado "
            "has no ambient host network, filesystem, or secret access."
        ),
        migration=(
            "G1-EDA-01 central owner; live execution is mechanically anchored "
            "at run_admitted_eda and its durable begin_effect"
        ),
    ),
    EntrypointSpec(
        id="web.server",
        surface=Surface.WEB_API,
        target="daedalus.interfaces.http.web_api:run",
        effects=(Effect.LISTEN_SOCKET,),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(GuardAnchor("daedalus.interfaces.http.web_api:run", "_resolve_bind"),),
        notes="Bind is loopback-only unless explicit authenticated remote opt-in succeeds.",
    ),
    EntrypointSpec(
        id="web.mutations",
        surface=Surface.WEB_API,
        target="daedalus.interfaces.http.web_api:DaedalusHandler.do_POST",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.interfaces.http.web_api:DaedalusHandler.do_POST", "_authorized"),
            GuardAnchor("daedalus.interfaces.http.web_api:DaedalusHandler.do_POST", "begin_effect"),
        ),
        notes=(
            "Each POST starts centrally after request auth; the recorded "
            "decision names the bind class (loopback vs token-verified)."
        ),
        migration="complete for the web.mutations entrypoint",
    ),
    EntrypointSpec(
        id="file_bridge.enqueue",
        surface=Surface.FILE_BRIDGE,
        target="daedalus.file_bridge:enqueue",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("file_bridge.crash_journal",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.file_bridge:enqueue", "begin_effect"),),
        notes=(
            "Atomic queue publication starts at the central boundary after "
            "the consumer check, with the verified durable-journal decision; "
            "a refusal still leaves no request file behind."
        ),
        migration="complete for the file_bridge.enqueue entrypoint",
    ),
    EntrypointSpec(
        id="file_bridge.process",
        surface=Surface.FILE_BRIDGE,
        target="daedalus.file_bridge:process_request",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("file_bridge.crash_journal",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.file_bridge:process_request", "begin_effect"),),
        notes=(
            "Exactly-once dispatch starts at the central boundary with the "
            "verified durable-journal decision for the request key."
        ),
        migration="complete for the file_bridge.process entrypoint",
    ),
    EntrypointSpec(
        id="file_bridge.watch",
        surface=Surface.FILE_BRIDGE,
        target="daedalus.file_bridge:watch",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("file_bridge.crash_journal", "budget.process_guard"),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.file_bridge:watch", "begin_effect"),),
        notes=(
            "The watcher loop starts at the central boundary with the journal "
            "decision AND the really-installed process spend net, so a direct "
            "python -m watcher can no longer run unpriced."
        ),
        migration="complete for the file_bridge.watch entrypoint",
    ),
    EntrypointSpec(
        id="python.attempt",
        surface=Surface.PYTHON,
        target="daedalus.spine.attempt:run_attempt",
        # UNCHANGED, and checked against what the path really does: the
        # isolated worktree and the artifact deposit are FILESYSTEM_WRITE, the
        # gate child is PROCESS_SPAWN, and `git worktree add -b` writes a
        # branch ref into the primary .git, which is REPOSITORY_MUTATION.
        # NETWORK_EGRESS and SPEND are deliberately absent: the model call
        # belongs to the INJECTED runner, which crosses its own `python.offload`
        # boundary under its own lease. Declaring them here would claim this row
        # bounds a spend it neither meters nor limits -- see
        # `receipts.SPEND_GRANT_REASON`.
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=(
            "spine.intent_ledger",
            "containment.worktree",
            "containment.attempt",
            "budget.process_guard",
            # Declared 2026-08-23 so the effect-lease issuer can draw the
            # FILESYSTEM_WRITE/REPOSITORY_MUTATION scope from a contract the
            # row names (issuable_row conjunct 5). The attempt path has always
            # run the primary-tree write fence; naming the policy contract is
            # what lets a lease bound the same writes instead of refusing the
            # row wholesale (the measured Gate-0 wall, B5 handoff).
            "provider.write_policy",
        ),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.spine.attempt:TaskAttempt.run", "begin_effect"),
        ),
        notes=(
            "The attempt starts at the central boundary before the intent "
            "write, the worktree, the runner and the gate. The anchor names "
            "TaskAttempt.run rather than the registered run_attempt wrapper "
            "because TaskAttempt(...).run() is a live call shape, and a "
            "boundary a caller can walk around by choosing a constructor is "
            "not a boundary. The receipt is the source of the canonical "
            "PolicyDecision (receipts.attempt_policy_decision)."
        ),
        migration="complete for the python.attempt entrypoint",
    ),
    EntrypointSpec(
        id="kernel.attempt.begin",
        surface=Surface.PYTHON,
        target="daedalus.kernel.attempt_ledger:AttemptLedger.begin",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kernel.attempt_ledger:AttemptLedger.begin",
                "record_intent",
            ),
        ),
        notes=(
            "Persists one canonical Attempt start in the shared Event Store after "
            "exact source-tree and workspace binding checks."
        ),
        migration=(
            "Require the exact persisted EffectLease, runtime-conformance authority "
            "and Docker sandbox capability before upgrading this lifecycle write to central."
        ),
    ),
    EntrypointSpec(
        id="kernel.attempt.complete",
        surface=Surface.PYTHON,
        target="daedalus.kernel.attempt_ledger:AttemptLedger.complete",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kernel.attempt_ledger:AttemptLedger.complete",
                "mark_completed",
            ),
        ),
        notes=(
            "Persists the single terminal Attempt receipt in the same canonical "
            "Event Store and rebinds all retained CAS material."
        ),
        migration=(
            "Require the exact persisted EffectLease, runtime-conformance authority "
            "and Docker sandbox capability before upgrading this lifecycle write to central."
        ),
    ),
    EntrypointSpec(
        id="kernel.attempt.prepare",
        surface=Surface.PYTHON,
        target="daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger", "containment.attempt"),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare",
                "begin",
            ),
            GuardAnchor(
                "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare",
                "materialize_tree",
            ),
        ),
        notes=(
            "Creates only a checkout-external workspace after protected-topology "
            "preflight and a durable canonical Attempt start."
        ),
        migration=(
            "Require the exact persisted EffectLease, Runtime Manifest, current "
            "RuntimeConformanceReceipt and Docker sandbox before upgrading to central."
        ),
    ),
    EntrypointSpec(
        id="python.offload",
        surface=Surface.PYTHON,
        target="daedalus.offload:offload",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=(
            "provider.egress_policy",
            "provider.write_policy",
            "budget.process_guard",
            "containment.attempt",
        ),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.offload:offload", "begin_effect"),
        ),
        notes=(
            "every live call consumes a persisted Effect Lease; write mode also "
            "requires the private TaskAttempt workspace grant and cannot mutate "
            "the primary checkout directly"
        ),
        migration="complete for the python.offload entrypoint",
    ),
    EntrypointSpec(
        id="python.promote_candidates",
        surface=Surface.PYTHON,
        target="daedalus.kairos.gated_writes:promote_candidates",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=(
            "spine.intent_ledger",
            "containment.worktree",
            "promotion.owner_approval",
        ),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.gated_writes:promote_candidates",
                "authorize_promotion",
            ),
            GuardAnchor(
                "daedalus.kairos.gated_writes:promote_candidates",
                "resolve_live_target_revision",
            ),
        ),
        notes=(
            "The public callable now requires a consumed owner capability, exact "
            "candidate/evidence binding, and a live target-HEAD recheck before any "
            "integration worktree or lock is created. Effect-lease centralization "
            "remains a later Gate-0 migration."
        ),
        migration=(
            "Route the authorized promotion operation through a persisted EffectLease "
            "before upgrading this row from local_guards to central."
        ),
    ),
    EntrypointSpec(
        id="adapter.subprocess",
        surface=Surface.PYTHON,
        target="daedalus.adapters.subprocess_adapter:SubprocessAdapter.create_session",
        effects=(Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS, Effect.FILESYSTEM_WRITE),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.adapters.subprocess_adapter:SubprocessAdapter.create_session",
                "begin_effect",
            ),
        ),
        notes=(
            "Every spawn passes the central boundary with a real adapter-profile "
            "decision (verified profile vs explicit config, bounded repo root) "
            "before create_subprocess_exec; the receipt is retained per session."
        ),
        migration="complete for the adapter.subprocess entrypoint",
    ),
    EntrypointSpec(
        id="adapter.subprocess.send",
        surface=Surface.PYTHON,
        target="daedalus.adapters.subprocess_adapter:SubprocessAdapter.send",
        effects=(Effect.PROCESS_CONTROL,),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.adapters.subprocess_adapter:SubprocessAdapter.send",
                "begin_effect",
            ),
        ),
        notes=(
            "Stdin control of a live session starts at the central boundary "
            "with the same adapter-profile decision as the spawn."
        ),
        migration="complete for the adapter.subprocess.send entrypoint",
    ),
    EntrypointSpec(
        id="adapter.subprocess.interrupt",
        surface=Surface.PYTHON,
        target="daedalus.adapters.subprocess_adapter:SubprocessAdapter.interrupt",
        effects=(Effect.PROCESS_CONTROL,),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.adapters.subprocess_adapter:SubprocessAdapter.interrupt",
                "begin_effect",
            ),
        ),
        notes=(
            "SIGINT to a tracked live session requires a central effect start; "
            "unknown or finished sessions remain a no-op without one."
        ),
        migration="complete for the adapter.subprocess.interrupt entrypoint",
    ),
    EntrypointSpec(
        id="adapter.subprocess.terminate",
        surface=Surface.PYTHON,
        target="daedalus.adapters.subprocess_adapter:SubprocessAdapter.terminate",
        effects=(Effect.PROCESS_CONTROL,),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.adapters.subprocess_adapter:SubprocessAdapter.terminate",
                "begin_effect",
            ),
        ),
        notes=(
            "Terminate/kill of a tracked session refuses before any process "
            "control when the central boundary does not accept the start; a "
            "refused terminate leaves the session tracked."
        ),
        migration="complete for the adapter.subprocess.terminate entrypoint",
    ),
    # CLI mains wired through the central boundary.  The family contract is
    # budget.process_guard: each main actually installs the process-wide spend
    # net (daedalus.budget.process_guard_boundary_decision) and passes its
    # decision to begin_effect before the first effect.  Read-only inspection
    # paths (status/summary printing) stay fail-open by design.
    EntrypointSpec(
        id="cli.loop",
        surface=Surface.CLI,
        target="daedalus.orchestration.loop:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.orchestration.loop:main", "begin_effect"),),
        notes=(
            "`python -m daedalus.orchestration.loop` is a SECOND console door into the same "
            "effects as cli.daedalus and never passes through cli.main's "
            "dispatch. It installed the spend guard by hand, which is the "
            "right effect and the wrong evidence: nothing mechanically "
            "required it, so deleting that line would have left the loop "
            "driver -- the single entrypoint that spends the most per "
            "invocation -- silently unpriced. The row plus the begin_effect "
            "anchor make the install a checked precondition of the start "
            "instead of a remembered habit."
        ),
        migration="complete for the cli.loop entrypoint",
    ),
    EntrypointSpec(
        id="cli.enforce",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.enforce:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.enforce:main", "begin_effect"),),
        notes="Harness-instruction writes into a target repo start centrally.",
        migration="complete for the cli.enforce entrypoint",
    ),
    EntrypointSpec(
        id="cli.gui_lint",
        surface=Surface.CLI,
        target="daedalus.gui.lint:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.gui.lint:main", "begin_effect"),),
        notes="GUI capture lint report write starts centrally.",
        migration="complete for the cli.gui_lint entrypoint",
    ),
    EntrypointSpec(
        id="cli.runbook",
        surface=Surface.CLI,
        target="daedalus.orchestration.runbook:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.orchestration.runbook:main", "begin_effect"),),
        notes="Run-brief creation starts centrally.",
        migration="complete for the cli.runbook entrypoint",
    ),
    EntrypointSpec(
        id="cli.selftest",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.selftest:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.NETWORK_EGRESS),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.selftest:main", "begin_effect"),),
        notes=(
            "Live Ollama write round-trip; network_egress is hand-declared "
            "(the request leaves via the provider path the scanner does not "
            "follow) and the installed spend net prices it."
        ),
        migration="complete for the cli.selftest entrypoint",
    ),
    EntrypointSpec(
        id="cli.shift",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.shift:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.shift:main", "begin_effect"),),
        notes=(
            "start/note/end state writes begin centrally; the status "
            "subcommand stays fail-open read-only inspection."
        ),
        migration="complete for the cli.shift entrypoint",
    ),
    EntrypointSpec(
        id="cli.structcore",
        surface=Surface.CLI,
        target="daedalus.structcore.__main__:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.structcore.__main__:main", "begin_effect"),),
        notes=(
            "Index/LPG artifact writes begin centrally; pure indexing with "
            "the printed summary stays fail-open read-only inspection."
        ),
        migration="complete for the cli.structcore entrypoint",
    ),
    EntrypointSpec(
        id="cli.structcore_slice",
        surface=Surface.CLI,
        target="daedalus.structcore.slice:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.structcore.slice:main", "begin_effect"),),
        notes=(
            "Slice/JSON artifact writes begin centrally; slicing with the "
            "printed report stays fail-open read-only inspection."
        ),
        migration="complete for the cli.structcore_slice entrypoint",
    ),
    EntrypointSpec(
        id="cli.token_monitor",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.token_monitor:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.token_monitor:main", "begin_effect"),),
        notes=(
            "Checkpoint writes (one-shot and watch loop) begin centrally, at "
            "the top of main() BEFORE argument parsing, so both doors pass "
            "it: the `daedalus tokens` subcommand in daedalus/interfaces/cli/entry.py and the "
            "`python -m daedalus.interfaces.cli.token_monitor` module tail. WRITE ROOTS, "
            "exhaustively: memory/ -- token_status.local.json, the event "
            "journal, the TODO snapshot -- is the report it produces. The "
            "budget lock file beside runs/budget/ledger.json and the WAL "
            "sidecars beside runs/spine/spine.sqlite3 are touched only as a "
            "consequence of READING those two stores: the ledger through "
            "Ledger.state(), the spine opened read_only=True so SQLite "
            "refuses a write at the engine. No spend and no promotion is "
            "declared because the monitor decides nothing -- "
            "should_checkpoint() sees the token summary and nothing else."
        ),
        migration=(
            "complete for the cli.token_monitor entrypoint; reachable as "
            "`daedalus tokens` since the dispatch row landed"
        ),
    ),
    EntrypointSpec(
        id="cli.arch_memory",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.arch_memory:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.arch_memory:main", "begin_effect"),),
        notes=(
            "Memory build/save (git probes plus the memory-file write, "
            "hand-declared) begins centrally; --show stays fail-open."
        ),
        migration="complete for the cli.arch_memory entrypoint",
    ),
    EntrypointSpec(
        id="cli.bookkeeper",
        surface=Surface.CLI,
        target="daedalus.interfaces.cli.bookkeeper:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.cli.bookkeeper:main", "begin_effect"),),
        notes="architecture.html render plus history snapshot begin centrally.",
        migration="complete for the cli.bookkeeper entrypoint",
    ),
    EntrypointSpec(
        id="cli.dctx",
        surface=Surface.CLI,
        target="daedalus.dctx:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.dctx:main", "begin_effect"),),
        notes=(
            "Receipt minting begins centrally; --verify stays fail-open "
            "read-only inspection."
        ),
        migration="complete for the cli.dctx entrypoint",
    ),
    EntrypointSpec(
        id="cli.doctor",
        surface=Surface.CLI,
        target="daedalus.doctor:main",
        effects=(Effect.NETWORK_EGRESS, Effect.PROCESS_SPAWN, Effect.SECRETS),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.doctor:main", "begin_effect"),),
        notes=(
            "Diagnostic probes really spawn CLIs and reach the local model "
            "host, so the whole run begins centrally with the spend net on. "
            "SECRETS is not decoration and not inheritance: main() -> check() "
            "reads DEEPSEEK_API_KEY out of the environment at doctor.py:93, "
            "INSIDE the door, and prints its presence. The value enters this "
            "process, which is the whole distinction -- a row that merely "
            "spawns a child that authenticates itself does NOT earn this "
            "effect, or secrets would become a synonym for process_spawn. "
            "Secrets stays hand-declared for the scanner (see the "
            "adapter.mcp_stdio note); the AST rule that keeps this row honest "
            "is tests/test_provider_secrets_rows.py."
        ),
        migration="complete for the cli.doctor entrypoint",
    ),
    EntrypointSpec(
        id="cli.eval_ceiling",
        surface=Surface.CLI,
        target="daedalus.eval.ceiling:main",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.eval.ceiling:main", "begin_effect"),),
        notes="Advisory report, but its git history probes spawn processes.",
        migration="complete for the cli.eval_ceiling entrypoint",
    ),
    EntrypointSpec(
        id="cli.eval_correctness",
        surface=Surface.CLI,
        target="daedalus.eval.correctness:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.eval.correctness:main", "begin_effect"),),
        notes=(
            "verify/run/seed spawn pytest in disposable worktrees and begin "
            "centrally; --derive stays fail-open (prints, writes nothing)."
        ),
        migration="complete for the cli.eval_correctness entrypoint",
    ),
    EntrypointSpec(
        id="cli.eval_graph_delta",
        surface=Surface.CLI,
        target="daedalus.eval.graph_delta:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.eval.graph_delta:main", "begin_effect"),),
        notes="Every mode writes its evidence JSON, so the run begins centrally.",
        migration="complete for the cli.eval_graph_delta entrypoint",
    ),
    EntrypointSpec(
        id="cli.memory",
        surface=Surface.CLI,
        target="daedalus.memory.__init__:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.memory.__init__:main", "begin_effect"),),
        notes=(
            "add/snapshot/done event writes begin centrally; bare help "
            "output stays fail-open."
        ),
        migration="complete for the cli.memory entrypoint",
    ),
    EntrypointSpec(
        id="cli.web_api",
        surface=Surface.CLI,
        target="daedalus.interfaces.http.web_api:main",
        effects=(Effect.LISTEN_SOCKET,),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.interfaces.http.web_api:main", "begin_effect"),),
        notes=(
            "The listen socket starts centrally with the real _resolve_bind "
            "verdict as its decision; a refused non-loopback bind still "
            "refuses before the boundary is consulted."
        ),
        migration="complete for the cli.web_api entrypoint",
    ),
    EntrypointSpec(
        id="web.mutations_put",
        surface=Surface.WEB_API,
        target="daedalus.interfaces.http.web_api:DaedalusHandler.do_PUT",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.interfaces.http.web_api:DaedalusHandler.do_PUT", "begin_effect"),
        ),
        notes=(
            "Each PUT starts centrally after request auth, mirroring "
            "web.mutations."
        ),
        migration="complete for the web.mutations_put entrypoint",
    ),
    EntrypointSpec(
        id="python.command_gate",
        surface=Surface.PYTHON,
        target="daedalus.spine.attempt:command_gate",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("containment.attempt",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.spine.attempt:command_gate", "begin_effect"),),
        notes=(
            "Gate construction starts centrally; candidate execution inside "
            "the gate remains containment-enforced with refusal instead of "
            "downgrade (no contained=False exists)."
        ),
        migration="complete for the python.command_gate entrypoint",
    ),
    EntrypointSpec(
        id="worktree.reap",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.reap_branches",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.reap_branches",
                "begin_effect",
            ),
        ),
        notes=(
            "Branch reaping starts centrally; deletion still requires this "
            "manager's in-process allocation record AND git reachability, "
            "per the method's trust model."
        ),
        migration="complete for the worktree.reap entrypoint",
    ),
    EntrypointSpec(
        id="cli.file_bridge",
        surface=Surface.CLI,
        target="daedalus.file_bridge:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.file_bridge:main", "begin_effect"),),
        notes=(
            "watch/enqueue/once/mark-read begin centrally (the delegated "
            "bridge functions carry their own central rows); the status "
            "subcommand stays fail-open read-only inspection."
        ),
        migration="complete for the cli.file_bridge entrypoint",
    ),
    EntrypointSpec(
        id="cli.mapping_drift",
        surface=Surface.CLI,
        target="daedalus.mapping.drift:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.mapping.drift:main", "begin_effect"),),
        notes=(
            "--refresh/--init baseline writes begin centrally; the drift "
            "comparison gate stays fail-open read-only inspection."
        ),
        migration="complete for the cli.mapping_drift entrypoint",
    ),
    EntrypointSpec(
        id="cli.mapping_inventory",
        surface=Surface.CLI,
        target="daedalus.mapping.inventory:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.mapping.inventory:main", "begin_effect"),),
        notes=(
            "--refresh inventory rewrite begins centrally; --check/--json "
            "stay fail-open (they write nothing)."
        ),
        migration="complete for the cli.mapping_inventory entrypoint",
    ),
    EntrypointSpec(
        id="cli.mapping_render",
        surface=Surface.CLI,
        target="daedalus.mapping.render:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.mapping.render:main", "begin_effect"),),
        notes=(
            "Map/snapshot/inventory rewrites and --accept records begin "
            "centrally; --json/--check stay fail-open (they write nothing)."
        ),
        migration="complete for the cli.mapping_render entrypoint",
    ),
    EntrypointSpec(
        id="cli.status",
        surface=Surface.CLI,
        target="daedalus.status:main",
        effects=(Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.status:main", "begin_effect"),),
        notes=(
            "Health probes really spawn processes and --probe-remote reaches "
            "the bench host (network_egress hand-declared), so the run "
            "begins centrally with the spend net on."
        ),
        migration="complete for the cli.status entrypoint",
    ),
    EntrypointSpec(
        id="provider.claude",
        surface=Surface.CLAUDE,
        target="daedalus.providers.claude_cli:ClaudeCLIProvider.run",
        effects=(
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.FILESYSTEM_WRITE,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard", "provider.write_policy"),
        wiring=Wiring.INVENTORY_ONLY,
        runtime_id="claude_code_cli",
        anchors=(
            GuardAnchor(
                "daedalus.providers.claude_cli:ClaudeCLIProvider.run",
                "run_runtime_provider",
            ),
        ),
        notes=(
            "Provider delegates to ask_claude; direct Python use bypasses CLI "
            "spend installation. SHARPENED REMAINDER 2026-08-18 (supersedes "
            "the 2026-08-18 'until that chain lands' note, whose condition has "
            "silently already passed and would now mislead a reader into "
            "calling this row stale): the runtime-bound lease/broker chain HAS "
            "landed. run() is fail-closed on runtime-bound Effect-Lease "
            "authority and brokers its whole execution seam through "
            "run_runtime_provider -> RuntimeBoundEffectAuthorization."
            "begin_effect -> EffectLeaseLedger.begin -> begin_effect, and the "
            "anchor below pins that seam. This row nevertheless stays "
            "inventory_only ON PURPOSE, because it is the activation blocker "
            "the Claude bypass-removal packet deliberately left standing: see "
            "tests/providers/test_claude_bypass_inventory.py::"
            "test_canonical_registry_activation_remains_an_explicit_blocker, "
            "which pins this exact value so default lease issuance stays "
            "impossible. CONDITION UNDER WHICH IT FALLS, both halves required: "
            "(1) caller injection -- some production caller actually mints a "
            "RuntimeBoundEffectAuthorization. MEASURED 2026-08-18: zero such "
            "callers outside tests/, so the lane is unreachable and flipping "
            "the row would only remove a counted blocker without enabling a "
            "single real start; (2) exact-head verification, per that packet. "
            "Flipping this row before both is routing around a guard, not "
            "wiring a door -- broker._validate_binding refuses non-CENTRAL "
            "rows, so this value is the last thing holding activation."
        ),
    ),
    EntrypointSpec(
        id="provider.codex",
        surface=Surface.CODEX,
        target="daedalus.providers.codex_cli:CodexCLIProvider.run",
        effects=(
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.FILESYSTEM_WRITE,
            Effect.SPEND,
        ),
        guard_contracts=("provider.egress_policy", "provider.write_policy", "budget.process_guard"),
        wiring=Wiring.INVENTORY_ONLY,
        runtime_id="codex_cli",
        anchors=(
            GuardAnchor(
                "daedalus.providers.codex_cli:CodexCLIProvider.run",
                "classify_data",
            ),
        ),
        notes=(
            "Egress is fail-closed and write defaults false; direct write "
            "mode remains an unleased path. SHARPENED REMAINDER 2026-08-18: "
            "the runtime-bound lease/broker chain now exists and "
            "provider.claude demonstrates the shape (run() fail-closed on "
            "authority, execution seam through run_runtime_provider). This row "
            "has NOT adopted it: codex_cli imports nothing from the kernel or "
            "the broker and run() takes no authorization argument. That is "
            "precisely why it must not be stamped central -- "
            "broker._validate_binding refuses non-CENTRAL rows, so CENTRAL is "
            "what admits a start; stamping it while run() still starts "
            "unleased would authorize a plain begin_effect start that skips "
            "the lease entirely, which is weaker than the honest gap. "
            "CONDITION UNDER WHICH IT FALLS: codex_cli.run adopts the brokered "
            "seam (runtime authorization + effect execution + workspace grant "
            "+ observation authority, as claude_cli has), after which it "
            "inherits the same activation criteria as provider.claude."
        ),
    ),
    EntrypointSpec(
        id="provider.ollama",
        surface=Surface.OLLAMA,
        target="daedalus.providers.ollama:OllamaProvider.run",
        effects=(Effect.NETWORK_EGRESS, Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("provider.egress_policy", "provider.write_policy"),
        wiring=Wiring.LOCAL_GUARDS,
        runtime_id="ollama_http",
        notes="Remote-host refusal and resolved-path write checks exist locally.",
    ),
    EntrypointSpec(
        id="memory.embeddings",
        surface=Surface.OLLAMA,
        target="daedalus.memory.embeddings:OllamaEmbeddingBackend.embed",
        effects=(Effect.NETWORK_EGRESS,),
        guard_contracts=("provider.egress_policy",),
        wiring=Wiring.CENTRAL,
        runtime_id="ollama_http",
        anchors=(
            GuardAnchor(
                "daedalus.memory.embeddings:OllamaEmbeddingBackend.embed",
                "_authorize_egress",
            ),
            GuardAnchor(
                "daedalus.memory.embeddings:_authorize_egress",
                "begin_effect",
            ),
        ),
        notes=(
            "The embedding transport POSTs projection text to a "
            "CALLER-SELECTED host. Unlike provider.ollama_native this one "
            "takes its own resolved-host decision -- ollama_endpoint_admission "
            "-- immediately before the request object exists, so the sluice "
            "sits above the socket rather than below the lane decision, and "
            "the row is central rather than inventory_only. The two anchors "
            "pin both halves: embed() must call the guard, and the guard must "
            "start at this boundary. A refusal raises "
            "EmbeddingEgressRefused carrying a deny receipt that names the "
            "host, so a withheld POST is attributable instead of silent."
        ),
        migration="complete for the memory.embeddings entrypoint",
    ),
    EntrypointSpec(
        id="provider.ollama_native",
        surface=Surface.OLLAMA,
        target="daedalus.providers._ollama_native:native_chat",
        effects=(Effect.NETWORK_EGRESS,),
        guard_contracts=("provider.egress_policy",),
        wiring=Wiring.INVENTORY_ONLY,
        runtime_id="ollama_http",
        notes=(
            "Low-level HTTP helper accepts a host and has no independent lane "
            "decision. SHARPENED REMAINDER 2026-08-18: the reason is narrower "
            "than 'runtime-bearing'. The remote-host refusal for this lane "
            "lives in the CALLER (provider.ollama, LOCAL_GUARDS), not here; "
            "native_chat is handed an already-resolved host. Starting the "
            "boundary inside the helper would place the sluice below the point "
            "where the lane decision is actually made, so the receipt would "
            "name an egress decision this function never took. CONDITION UNDER "
            "WHICH IT FALLS: either native_chat grows its own resolved-host "
            "egress decision, or OllamaProvider.run becomes the brokered "
            "runtime row -- in which case the caller's start already covers "
            "this helper and the row consolidates into it rather than being "
            "wired separately."
        ),
    ),
    EntrypointSpec(
        id="worktree.create",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.create_worktree",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.create_worktree",
                "_refuse_if_repo_adjacent",
            ),
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.create_worktree",
                "begin_effect",
            ),
        ),
        notes=(
            "Allocation is confined and recorded before git worktree creation. "
            "BOTH anchors are kept deliberately: the central start is what "
            "makes this row leasable, and the local check is the thing its "
            "receipt quotes -- an anchor on begin_effect alone would let the "
            "confinement proof be deleted while the receipt kept claiming it."
        ),
        migration="complete for the worktree.create entrypoint",
    ),
    EntrypointSpec(
        id="worktree.commit",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.commit_candidate",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.commit_candidate",
                "_require_allocated_worktree",
            ),
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.commit_candidate",
                "begin_effect",
            ),
        ),
        notes=(
            "Only a worktree allocated by this manager may be staged and "
            "committed, and the six allocation proofs now precede a central "
            "start rather than only a bare `git add -A`."
        ),
        migration="complete for the worktree.commit entrypoint",
    ),
    EntrypointSpec(
        id="worktree.cleanup",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.cleanup_worktree",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.cleanup_worktree",
                "_require_allocated_worktree",
            ),
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.cleanup_worktree",
                "begin_effect",
            ),
        ),
        notes=(
            "Removal revalidates allocation and path identity; it is not "
            "generic rmtree. The central start sits between the revalidation "
            "and the first unlink, so a receipt exists for a tree that is "
            "about to be deleted and not merely for one that was."
        ),
        migration="complete for the worktree.cleanup entrypoint",
    ),
    EntrypointSpec(
        id="mcp.runtime",
        surface=Surface.MCP,
        target="<absent>",
        effects=(
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.FILESYSTEM_WRITE,
        ),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.ABSENT,
        notes="Daedalus inventories/vets MCP config but does not implement an MCP runtime boundary.",
        discoverable=False,
    ),
    EntrypointSpec(
        id="tools.guarded_call",
        surface=Surface.CLI,
        target="tools.guarded_call:main",
        effects=(Effect.NETWORK_EGRESS, Effect.SPEND, Effect.SECRETS),
        guard_contracts=("budget.process_guard", "provider.egress_policy"),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("tools.guarded_call:main", "run"),
            GuardAnchor("tools.guarded_call:main", "begin_effect"),
        ),
        notes=(
            "Process-boundary door for external-environment callers. The "
            "central start installs the real spend net and runs the secret "
            "floor over the outbound payload; a boundary refusal follows the "
            "door's JSON protocol. Deeper budget/secret refusals still live "
            "in DeepSeekProvider.run (the anchored delegated call); "
            "spend/secrets remain hand-declared for the scanner."
        ),
        migration="complete for the tools.guarded_call entrypoint",
    ),
    EntrypointSpec(
        id="tools.audit_swarm",
        surface=Surface.CLI,
        target="tools.audit_swarm:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("tools.audit_swarm:main", "fan_out"),
            GuardAnchor("tools.audit_swarm:main", "begin_effect"),
        ),
        notes=(
            "Paid fan-out starts at the central boundary with the "
            "really-installed spend net; --plan stays fail-open. The anchored "
            "fan_out callee keeps its own fail-closed installation as "
            "defense in depth."
        ),
        migration="complete for the tools.audit_swarm entrypoint",
    ),
    EntrypointSpec(
        id="tools.funnel",
        surface=Surface.CLI,
        target="tools.funnel:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("tools.funnel:main", "fan_out"),
            GuardAnchor("tools.funnel:main", "budget_verdict"),
            GuardAnchor("tools.funnel:main", "begin_effect"),
        ),
        notes=(
            "Paid tiered fan-out starts at the central boundary with the "
            "really-installed spend net; the projection stays fail-open. The "
            "local budget verdict and the fan_out callee's own installation "
            "remain as defense in depth."
        ),
        migration="complete for the tools.funnel entrypoint",
    ),
    # Repository-mutation tier of the effect-boundary inventory.  The scanner
    # can never infer repository_mutation (git argv), so it is hand-declared
    # here; the discovered fs-write/spawn effects stay declared alongside.
    #
    # RETIRED 2026-08-22, one row removed from this tier: ``tools.iron_plan_guard``
    # (target ``tools.iron_plan_guard:main``, effects filesystem_write +
    # process_spawn + repository_mutation, wiring inventory_only).  Commit
    # 79825b57 -- "unify(2026-08-22): main is the g0 trunk, the iron guard is
    # retired by owner decision" -- DELETED ``tools/iron_plan_guard.py``, and a
    # registry row whose target no longer exists is a false door: it reads as
    # coverage of a mechanism nobody can run, and ``check_conformance`` reported
    # it as a permanent ``registry.target_missing`` blocker that no amount of
    # correct wiring could clear.  The removal is not a weakening: the door it
    # inventoried is gone, so there is nothing left to inventory.  Its long note
    # (protected artifact; "a sluice before the sluice"; the guard must not
    # depend at runtime on the module it exists to protect) survives in git
    # history at 57a2e7cb and is the record to read if an owner-approved
    # amendment ever restores a plan guard -- a restored guard needs a NEW row,
    # argued from scratch, not this one resurrected.  The tier is now four
    # git-touching tool entrypoints, not five.
    EntrypointSpec(
        id="tools.gate_discrimination",
        surface=Surface.CLI,
        target="tools.gate_discrimination:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.gate_discrimination:main", "begin_effect"),),
        notes=(
            "Clone/mutate/pytest measurement begins centrally; --dry-run "
            "anchor validation stays fail-open."
        ),
        migration="complete for the tools.gate_discrimination entrypoint",
    ),
    EntrypointSpec(
        id="tools.bootstrap_receipt",
        surface=Surface.CLI,
        target="tools.bootstrap_receipt:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.bootstrap_receipt:main", "begin_effect"),),
        notes=(
            "Bootstrap evidence run (git-touching) begins centrally with the "
            "really-installed process spend net."
        ),
        migration="complete for the tools.bootstrap_receipt entrypoint",
    ),
    EntrypointSpec(
        id="tools.operability_drill",
        surface=Surface.CLI,
        target="tools.operability_drill:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.operability_drill:main", "begin_effect"),),
        notes="The end-to-end control drill begins centrally.",
        migration="complete for the tools.operability_drill entrypoint",
    ),
    EntrypointSpec(
        id="tools.gate_host_preflight",
        surface=Surface.CLI,
        target="tools.gate_host_preflight:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.gate_host_preflight:main", "begin_effect"),),
        notes="Host preflight probes begin centrally.",
        migration="complete for the tools.gate_host_preflight entrypoint",
    ),
    EntrypointSpec(
        id="tools.gui_check",
        surface=Surface.CLI,
        target="tools.gui_check:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_CONTROL,
            Effect.PROCESS_SPAWN,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.gui_check:main", "begin_effect"),),
        notes=(
            "node/playwright spawns and the local dev-server lifecycle begin "
            "centrally."
        ),
        migration="complete for the tools.gui_check entrypoint",
    ),
    # Write-only / spawn-only tool entrypoints; effects as discovered.
    EntrypointSpec(
        id="tools.mutation_score",
        surface=Surface.CLI,
        target="tools.mutation_score:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.mutation_score:main", "begin_effect"),),
        notes=(
            "Scoring (pytest spawns against mutated trees, hand-declared) "
            "begins centrally; --list stays fail-open."
        ),
        migration="complete for the tools.mutation_score entrypoint",
    ),
    EntrypointSpec(
        id="tools.audit_triage",
        surface=Surface.CLI,
        target="tools.audit_triage:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.audit_triage:main", "begin_effect"),),
        notes=(
            "The JSON worklist write begins centrally; the printed triage "
            "stays fail-open read-only inspection."
        ),
        migration="complete for the tools.audit_triage entrypoint",
    ),
    EntrypointSpec(
        id="tools.agent_findings",
        surface=Surface.CLI,
        target="tools.agent_findings:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.agent_findings:main", "begin_effect"),),
        notes="Findings digest writes begin centrally.",
        migration="complete for the tools.agent_findings entrypoint",
    ),
    EntrypointSpec(
        id="tools.lane_invariants",
        surface=Surface.CLI,
        target="tools.lane_invariants:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.lane_invariants:main", "begin_effect"),),
        notes=(
            "The JSON result write begins centrally; the printed invariant "
            "check stays fail-open read-only inspection."
        ),
        migration="complete for the tools.lane_invariants entrypoint",
    ),
    EntrypointSpec(
        id="tools.funnel_report",
        surface=Surface.CLI,
        target="tools.funnel_report:main",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.funnel_report:main", "begin_effect"),),
        notes=(
            "Reads a finished funnel run directory (fan_out mention in its "
            "source is docstring only); its declared spawn begins centrally."
        ),
        migration="complete for the tools.funnel_report entrypoint",
    ),
    EntrypointSpec(
        id="tools.run_gate_checks",
        surface=Surface.CLI,
        target="tools.run_gate_checks:main",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.run_gate_checks:main", "begin_effect"),),
        notes=(
            "Gate verification pytest spawns begin centrally; --list stays "
            "fail-open."
        ),
        migration="complete for the tools.run_gate_checks entrypoint",
    ),
    # RETIRED 2026-08-22, second of the two plan-guard rows removed in this
    # sweep: ``tools.iron_plan_hook_runner`` (target
    # ``tools.iron_plan_hook_runner:main``, effects process_spawn, wiring
    # inventory_only).  Same cause as ``tools.iron_plan_guard`` above -- commit
    # 79825b57 deleted ``tools/iron_plan_hook_runner.py`` by owner decision, so
    # ``check_conformance`` reported a second permanent
    # ``registry.target_missing`` blocker.  Its note argued a third reason
    # beyond the guard's two: a refusable boundary in front of a hook shim
    # fails OPEN on the protection path (a refusal there does not block a risky
    # commit, it silently stops checking commits).  That argument is worth
    # re-reading in git history at 57a2e7cb before any future hook shim is
    # wired, but it describes a file that no longer exists.
    EntrypointSpec(
        id="tools.system_check",
        surface=Surface.CLI,
        target="tools.system_check:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_CONTROL,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.system_check:main", "begin_effect"),),
        notes=(
            "End-to-end acceptance probe: clones the working tree, spawns "
            "servers, opens sockets and writes probe files. Dispatch goes "
            "through the CHECKS table, so the static scanner cannot classify "
            "it -- every effect here is hand-declared. The run (including "
            "--self-test) begins centrally."
        ),
        migration="complete for the tools.system_check entrypoint",
    ),
    # daedalus/runtimes/ -- the runtime fault-matrix drivers.  All three are
    # discovered as filesystem_write only: their spawn, containment and secret
    # effects live behind a cross-module callee or a closure the literal-name
    # sink match cannot follow, so those effects are hand-declared here.
    EntrypointSpec(
        id="runtimes.container_fault_driver",
        surface=Surface.CLI,
        target="daedalus.runtimes.container_fault_driver:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
        ),
        guard_contracts=("containment.attempt", "budget.process_guard"),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.runtimes.container_fault_driver:"
                "ContainerFaultDriver._run_script",
                "run_in_docker_sandbox",
            ),
            GuardAnchor(
                "daedalus.runtimes.container_fault_driver:main",
                "begin_effect",
            ),
        ),
        notes=(
            "Drives the linux-host fault scenarios into a Docker container. It "
            "never invokes docker itself -- the spawn and the bounded-effect "
            "policy (read-only root, network=none, dropped caps, timeout_s) "
            "both live in daedalus.kernel.sandbox.run_in_docker_sandbox, which "
            "the scanner cannot see across the module edge. The anchor pins "
            "that containment call so the row cannot rot into a raw spawn. "
            "Wired 2026-08-18: the 'wait for the live-runtime lane' remainder "
            "did not survive review -- this row carries no runtime_id and "
            "needs no lease, so nothing about it was ever waiting on that "
            "chain. main() now starts centrally with two real decisions: the "
            "installed spend net, and a containment decision that resolves "
            "run_in_docker_sandbox's defining module at the boundary and "
            "refuses the start if the spawn path is no longer the bounded "
            "sandbox. Docker availability is deliberately excluded from the "
            "decision: a host without docker must still record every scenario "
            "as blocked and retain that evidence."
        ),
        migration="complete for the runtimes.container_fault_driver entrypoint",
    ),
    EntrypointSpec(
        id="runtimes.fixture_fault_collector",
        surface=Surface.CLI,
        target="daedalus.runtimes.fixture_fault_collector:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.runtimes.fixture_fault_collector:main",
                "subprocess_pytest_runner",
            ),
            GuardAnchor(
                "daedalus.runtimes.fixture_fault_collector:main",
                "begin_effect",
            ),
        ),
        notes=(
            "Spawns one pytest subprocess per fixture fault row and retains "
            "the evidence. The subprocess.run (with its timeout, hence "
            "process_control) sits in a closure returned by "
            "subprocess_pytest_runner, which the scanner does not enter; the "
            "anchor pins main's use of that runner seam instead. Wired "
            "2026-08-18: the 'wait for the live-runtime lane' remainder did "
            "not survive review -- this row carries no runtime_id and needs no "
            "lease, so its spawns were never waiting on the runtime-bound "
            "chain. main() now installs the real spend net and starts "
            "centrally before the first pytest spawn."
        ),
        migration="complete for the runtimes.fixture_fault_collector entrypoint",
    ),
    EntrypointSpec(
        id="runtimes.live_fault_collector",
        surface=Surface.CLI,
        target="daedalus.runtimes.live_fault_collector:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "daedalus.runtimes.live_fault_collector:main",
                "begin_effect",
            ),
        ),
        notes=(
            "Runs the two live-runtime fault rows and retains their evidence. It "
            "spawns nothing: the binary-drift probe copies the provider image into "
            "a temp dir and mutates the copy, so the only effect is filesystem "
            "write. It holds no signing key and grants no trust. Wired "
            "2026-08-18 on the same footing as runs.ab.blind, the existing "
            "filesystem_write-only central row: the start is receipted and the "
            "in-process spend net is really installed. Stated plainly so the "
            "green is not read as more than it is -- the decision that runs is "
            "the spend net, and it does NOT certify the evidence write; there "
            "is no filesystem-write contract in GUARD_CONTRACT_IMPLEMENTED to "
            "make a stronger claim with. The call sits after the "
            "canonical-module delegation in main(), so it fires exactly once "
            "even when the module is loaded as __main__. KNOWN RESIDUAL, named "
            "rather than hidden: this row registers the CLI door (main), and "
            "the module's library functions (run_live_fault_catalog, "
            "retain_live_fault_run) stay reachable without it -- the owner-run "
            "key-ceremony kit calls them directly. That surface predates this "
            "wiring and is not closed by it."
        ),
        migration="complete for the runtimes.live_fault_collector entrypoint",
    ),
    EntrypointSpec(
        id="runtimes.fault_attestation_issuer",
        surface=Surface.CLI,
        target="daedalus.runtimes.fault_attestation_issuer:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.SECRETS),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
        notes=(
            "Signs retained linux-host fault observations into an attestation "
            "bundle. It reads the signing key from the environment "
            "(_secret_from_env), so secrets is hand-declared: a signing door "
            "that stayed green while handling a key is exactly the row this "
            "inventory exists to name. It grants authenticity, never a "
            "verdict. SHARPENED REMAINDER 2026-08-18: its two sibling "
            "collectors were wired centrally in the same pass, so 'owned by "
            "another lane' is no longer the reason -- this row is different in "
            "kind. Its dominant effect is secrets, and "
            "GUARD_CONTRACT_IMPLEMENTED contains no secrets or key-custody "
            "contract. The only decision available to it is the in-process "
            "spend net, which says nothing whatever about how a signing key is "
            "sourced, held, or destroyed. Stamping the row central on that "
            "basis would advertise cover it does not have on exactly the "
            "effect that matters, which is the failure mode this inventory "
            "exists to prevent rather than to commit. CONDITION UNDER WHICH IT "
            "FALLS: a secrets/key-custody contract is added to "
            "GUARD_CONTRACT_IMPLEMENTED with a real implementation that can "
            "decide key provenance and custody at the boundary; this row then "
            "declares it and starts centrally on that decision."
        ),
    ),
    # runs/ -- production-capable entrypoints that spend money; five of these
    # functions appear in daedalus.budget.BILLABLE_SITES.  spend/secrets/
    # repository_mutation are hand-declared (section-5 limits of the scanner).
    EntrypointSpec(
        id="runs.council.room",
        surface=Surface.CLI,
        target="runs.council.room:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.council.room:main", "begin_effect"),),
        notes=(
            "Cross-vendor room: every transcript-appending or vendor-asking "
            "subcommand starts centrally with the really-installed spend "
            "net; show/who/verify stay fail-open read-only inspection."
        ),
        migration="complete for the runs.council.room entrypoint",
    ),
    EntrypointSpec(
        id="runs.council.summarize",
        surface=Surface.CLI,
        target="runs.council.summarize:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.council.summarize:main", "begin_effect"),),
        notes=(
            "Billable summarisers (cli/ollama, found by the budget drift "
            "detector) start centrally; --dry-run stays fail-open."
        ),
        migration="complete for the runs.council.summarize entrypoint",
    ),
    EntrypointSpec(
        id="runs.council.room_server",
        surface=Surface.CLI,
        target="runs.council.room_server:main",
        effects=(
            Effect.LISTEN_SOCKET,
            Effect.FILESYSTEM_WRITE,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.council.room_server:main", "begin_effect"),),
        notes=(
            "Binds a loopback HTTP server through a ThreadingHTTPServer "
            "SUBCLASS, which defeats the scanner's literal-name sink match -- "
            "listen_socket is hand-declared. Drives the paid room; the bind "
            "starts centrally with the spend net installed."
        ),
        migration="complete for the runs.council.room_server entrypoint",
    ),
    EntrypointSpec(
        id="runs.council.room_server.post",
        surface=Surface.WEB_API,
        target="runs.council.room_server:Handler.do_POST",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("runs.council.room_server:Handler.do_POST", "begin_effect"),
        ),
        notes=(
            "Room-server mutation handler: each request starts centrally "
            "after the existing loopback request guard, whose pass is the "
            "recorded bind decision."
        ),
        migration="complete for the runs.council.room_server.post entrypoint",
    ),
    EntrypointSpec(
        id="runs.council.stream_hook",
        surface=Surface.CLI,
        target="runs.council.stream_hook:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.council.stream_hook:main", "begin_effect"),),
        notes=(
            "Streams room events into the transcript; starts centrally and a "
            "boundary refusal writes nothing (hook protocol: exit 0)."
        ),
        migration="complete for the runs.council.stream_hook entrypoint",
    ),
    EntrypointSpec(
        id="daedalus.hooks",
        surface=Surface.CLI,
        target="daedalus.hooks.__main__:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.hooks.__main__:main", "begin_effect"),),
        notes=(
            "Claude Code hooks dispatcher (python -m daedalus.hooks <event>): "
            "writes runs/hooks/ state and ledger, spawns git for tree facts, "
            "probes Serena's loopback dashboard port, and -- only when "
            "DAEDALUS_CROSSTALK=on -- spawns gh to reach github.com for the "
            "Discussions crosstalk (2026-09-03: the egress is no longer "
            "loopback-only, and this note says so rather than letting the "
            "old justification stand). Starts centrally; a boundary refusal "
            "prints to stderr and exits 0 (hook protocol)."
        ),
        migration="complete for the daedalus.hooks entrypoint (2026-08-23)",
    ),
    EntrypointSpec(
        id="daedalus.hooks.crosstalk",
        surface=Surface.CLI,
        target="daedalus.hooks.crosstalk:main",
        effects=(Effect.NETWORK_EGRESS, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.hooks.crosstalk:main", "begin_effect"),),
        notes=(
            'python -m daedalus.hooks.crosstalk say "...": posts one '
            "model-written line into the branch's GitHub Discussions via gh. "
            "No token is handled here -- gh holds the credential, which is why "
            "this row declares no SECRETS effect. Off unless "
            "DAEDALUS_CROSSTALK=on; refuses a non-private repository without "
            "DAEDALUS_CROSSTALK_PUBLIC=1; exits 0 on every failure."
        ),
        migration="complete for the daedalus.hooks.crosstalk entrypoint (2026-09-03)",
    ),
    EntrypointSpec(
        id="tools.watchdog",
        surface=Surface.CLI,
        target="tools.watchdog:main",
        effects=(
            Effect.PROCESS_SPAWN,
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.watchdog:main", "begin_effect"),),
        notes=(
            "Background docs/work watchdog (Windows scheduled tasks): measures "
            "drift and health mechanically, spawns `claude -p` (haiku) only on "
            "evidence and through budget.guard, commits docs fixes with a "
            "pathspec only. Never blocks anything."
        ),
        migration="complete for the tools.watchdog entrypoint (2026-08-23)",
    ),
    EntrypointSpec(
        id="runs.council.dead_letter_replay",
        surface=Surface.CLI,
        target="runs.council.dead_letter_replay:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("runs.council.dead_letter_replay:main", "begin_effect"),
        ),
        notes=(
            "Replays dead-lettered room messages into the transcript; replay "
            "starts centrally, spool listing stays fail-open."
        ),
        migration="complete for the runs.council.dead_letter_replay entrypoint",
    ),
    EntrypointSpec(
        id="runs.ab.run_arm",
        surface=Surface.CLI,
        target="runs.ab.run_arm:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.ab.run_arm:main", "begin_effect"),),
        notes=(
            "Billable A/B arm (call_claude in BILLABLE_SITES); mutates its "
            "arm worktree and starts centrally."
        ),
        migration="complete for the runs.ab.run_arm entrypoint",
    ),
    EntrypointSpec(
        id="runs.ab.score",
        surface=Surface.CLI,
        target="runs.ab.score:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.ab.score:main", "begin_effect"),),
        notes="Scores A/B arms (git-touching) and starts centrally.",
        migration="complete for the runs.ab.score entrypoint",
    ),
    EntrypointSpec(
        id="runs.ab.oracle_check",
        surface=Surface.CLI,
        target="runs.ab.oracle_check:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.ab.oracle_check:main", "begin_effect"),),
        notes="Runs the oracle over finished arms centrally.",
        migration="complete for the runs.ab.oracle_check entrypoint",
    ),
    EntrypointSpec(
        id="runs.ab.blind",
        surface=Surface.CLI,
        target="runs.ab.blind:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("runs.ab.blind:main", "begin_effect"),),
        notes=(
            "Writes the blinded comparison sheet centrally; an existing seal "
            "still refuses before the boundary is consulted."
        ),
        migration="complete for the runs.ab.blind entrypoint",
    ),
    EntrypointSpec(
        id="runs.gate0_matrix.verify_whole_matrix",
        surface=Surface.CLI,
        target="runs.gate0-matrix-2026-08-17.verify_whole_matrix:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.SECRETS),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
        notes=(
            "Assembles both collector columns into one matrix and writes the "
            "whole-matrix verdict. It reads BOTH issuer keys from the "
            "environment, so secrets is hand-declared. KNOWN FRAGILITY, named "
            "rather than hidden: the target carries a dated run directory, so "
            "the next matrix run mints a fresh unregistered blocker and this "
            "row goes stale the day its evidence folder is pruned. Moving the "
            "verifier to a stable path is an owner decision -- the script is "
            "deliberately retained beside the evidence it produced. SHARPENED "
            "REMAINDER 2026-08-18: two independent reasons, either one "
            "sufficient. (1) Same secrets gap as "
            "runtimes.fault_attestation_issuer: it reads BOTH issuer keys and "
            "no key-custody contract exists to decide on them, so a central "
            "stamp would rest on a spend-net decision that covers none of the "
            "risk. (2) The target is a file inside a dated, retained evidence "
            "directory. Editing it to insert a boundary call would mutate a "
            "retained evidence artifact after the fact -- the run that "
            "produced the evidence did not have that call -- which is a worse "
            "outcome than an honest inventory row. CONDITION UNDER WHICH IT "
            "FALLS: the owner moves the verifier to a stable path (severing "
            "reason 2) AND a key-custody contract exists (severing reason 1). "
            "Until then this row is also the registry's known staleness "
            "candidate: it goes stale the day its evidence folder is pruned."
        ),
    ),
)

# Additional currently advertised/direct Python starts found by the static
# inventory.  They remain rows in the *same* registry rather than an exemption
# list: adding another such callable creates an ``entrypoint.unregistered``
# blocker, while deleting one makes its row stale.  These rows are intentionally
# concise because their next Gate-0 action is consolidation behind the primary
# rows above, not preservation as separate architecture.
# The former legacy tuple block is gone: every direct start now carries a
# full spec (central where the real begin_effect path exists, inventory_only
# with a reasoned note where it honestly does not).
# cli.claude_bridge was deleted from this inventory 2026-08-17: the target
# is now a fail-closed stub (parser.error, no effect), so its row declared
# effects the code cannot perform and produced the registry's only
# entrypoint.not_rediscovered staleness finding.  If the bridge regains an
# effectful body the scanner will rediscover it as an unregistered blocker.
_REMAINDER_PROVIDER_ROWS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        # Corrected 2026-08-17 per the Gate-0 effect-boundary inventory:
        # run reads DEEPSEEK_API_KEY, and chat_completion is priced through
        # daedalus.budget._guarded_urlopen, so the busiest paid lane declares
        # spend/egress/secrets instead of filesystem_write alone.
        id="provider.deepseek",
        surface=Surface.PYTHON,
        target="daedalus.providers.deepseek:DeepSeekProvider.run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
        notes=(
            "Busiest paid lane. SHARPENED REMAINDER 2026-08-18: the chain the "
            "old note deferred to now exists (provider.claude shows the "
            "shape), but deepseek.py imports nothing from the kernel or the "
            "broker and run() takes no authorization argument, so this row has "
            "not adopted it. CENTRAL is what admits a start -- stamping it "
            "here while run() is still unleased would authorize a plain start "
            "that skips the lease on the lane that spends the most money, "
            "which is worse than an honest gap. The mitigation that already "
            "exists: this lane's process-boundary door (the guarded "
            "external-call CLI) IS centrally wired and runs the real spend net "
            "plus a secret floor over the outbound payload, so the reachable "
            "production path is covered even while the direct Python method is "
            "not. CONDITION UNDER WHICH IT FALLS: DeepSeekProvider.run adopts "
            "the brokered seam, then inherits provider.claude's activation "
            "criteria."
        ),
    ),
    EntrypointSpec(
        id="provider.deepseek.rollback",
        surface=Surface.PYTHON,
        target="daedalus.providers.deepseek:DeepSeekProvider.rollback",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
        notes=(
            "SHARPENED REMAINDER 2026-08-18: the old 'same lifecycle as run' "
            "note was too weak to survive review -- this method carries no "
            "runtime_id, needs no lease, and would otherwise be trivially "
            "wirable. The real reason is that it is the UNDO path. rollback() "
            "restores the originals this provider backed up; it is called "
            "exactly when a write went wrong. begin_effect is a refusing gate "
            "(denied decision, unimplemented contract, kill-switch generation, "
            "exhausted budget), and every one of those conditions is MORE "
            "likely at rollback time than at write time. Gating the undo path "
            "behind it converts a recoverable half-written tree into an "
            "unrecoverable one: the guard would fire precisely when recovery "
            "is needed. CONDITION UNDER WHICH IT FALLS: rollback is invoked "
            "inside the runtime lease's terminal reconciliation, where the "
            "start receipt for the write already exists and covers the undo -- "
            "then it needs no separate start at all and this row consolidates "
            "away instead of turning central."
        ),
    ),
    EntrypointSpec(
        id="provider.ollama.rollback",
        surface=Surface.OLLAMA,
        target="daedalus.providers.ollama:OllamaProvider.rollback",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
        notes=(
            "SHARPENED REMAINDER 2026-08-18: identical body and identical "
            "reason to provider.deepseek.rollback -- this is the UNDO path, "
            "and begin_effect is a refusing gate whose refusal conditions "
            "(denied decision, kill switch, exhausted budget) are most likely "
            "exactly when a rollback is needed. Gating it would turn a "
            "recoverable half-written tree into an unrecoverable one. Note "
            "also that offload refuses to grant write rights to a provider "
            "without a callable rollback(), so a rollback that can be refused "
            "at the boundary would silently weaken the write lane it exists to "
            "make safe. CONDITION UNDER WHICH IT FALLS: rollback runs inside "
            "the runtime lease's terminal reconciliation, covered by the "
            "write's own start receipt, and this row consolidates away."
        ),
    ),
)

ENTRYPOINTS += _REMAINDER_PROVIDER_ROWS


# The Ikarus chat surface.  ``daedalus/budget.py`` has named ikarus_os.py as one
# of the four independent vendor-spend origins since the ceiling was written,
# and the registry had no row for it: the two public doors reach four provider
# runtimes (two HTTP, two vendor CLIs), so a chat turn could spend money and
# open a socket without any canonical start.  The scanner cannot see it -- its
# effects are all one call deeper than ``ask``/``ask_stream`` -- which is
# exactly why the rows are hand-declared here rather than waiting to be
# discovered.  Expect these three targets among the ``entrypoint.not_rediscovered``
# review rows for that reason; the AST existence check still catches staleness.
_IKARUS_CHAT_ROWS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        id="ikarus_os.ask",
        surface=Surface.PYTHON,
        target="daedalus.orchestration.ikarus.shell:ask",
        effects=(
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.orchestration.ikarus.shell:ask", "begin_effect"),),
        notes=(
            "The blocking chat door. The boundary is the FIRST statement of "
            "ask(), above intent classification and above provider selection, "
            "so no route can reach a runtime without having passed it and the "
            "process-wide spend net is really installed before the turn "
            "branches. Declared effects are the union of what the four "
            "provider branches do one call deeper: network_egress "
            "(_ollama/_deepseek over urllib), process_spawn (_claude/_codex "
            "spawn the vendor CLI), spend (deepseek/claude/codex) and secrets "
            "(DEEPSEEK_API_KEY is read in-process; the two CLIs carry their "
            "own credentials). The per-transport admission is a separate start "
            "-- see ikarus_os.provider_call -- because the endpoint is not "
            "known at the door and a status turn must not be refused for an "
            "egress it never performs."
        ),
        migration="complete for the ikarus_os.ask entrypoint",
    ),
    EntrypointSpec(
        id="ikarus_os.ask_stream",
        surface=Surface.PYTHON,
        target="daedalus.orchestration.ikarus.shell:ask_stream",
        effects=(
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.orchestration.ikarus.shell:ask_stream", "_ask_stream_inner"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_ask_stream_inner", "begin_effect"),
        ),
        notes=(
            "The streaming twin, same effects and same door discipline. "
            "ask_stream() is a thin tap that only persists the final turn, so "
            "the boundary sits at the top of _ask_stream_inner() -- the "
            "generator that actually selects a provider -- and both anchors "
            "are pinned: the delegation and the start. Putting it in the tap "
            "instead would leave a caller that drives the inner generator "
            "directly unguarded."
        ),
        migration="complete for the ikarus_os.ask_stream entrypoint",
    ),
    EntrypointSpec(
        id="ikarus_os.provider_call",
        surface=Surface.PYTHON,
        target="daedalus.orchestration.ikarus.shell:_provider_start",
        effects=(
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard", "provider.egress_policy"),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.orchestration.ikarus.shell:_provider_start", "begin_effect"),
            # One anchor per sink so deleting the admission from any single
            # transport is a conformance blocker, not a silent regression.
            GuardAnchor("daedalus.orchestration.ikarus.shell:_ollama", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_ollama_cli", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_deepseek", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_claude", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_codex", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_ollama_stream", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_deepseek_stream", "_provider_start"),
            GuardAnchor("daedalus.orchestration.ikarus.shell:_claude_stream", "_provider_start"),
        ),
        notes=(
            "ONE transport start, taken inside each of the eight sink "
            "functions before the request object or the argv exists, so "
            "'zero connects on refusal' is a property of the control flow. "
            "Each branch requests only the effects it performs (ollama: "
            "network_egress; deepseek: network_egress/spend/secrets; "
            "claude+codex: process_spawn/spend). provider.egress_policy is "
            "ollama_endpoint_admission -- the same lane_for_host decision the "
            "embedding backend takes -- so a repointed OLLAMA_HOST is refused "
            "before connect with a receipt that names the host. "
            "budget.process_guard installs the net and then mirrors "
            "Ledger.reserve's own two refusal conditions (dollar ceiling, "
            "call cap) as a READ, never a reservation: the interposer still "
            "does the reserving at the socket, so the money is counted once "
            "and the pre-flight only makes the same verdict legible and "
            "early. It fails closed on an unreadable ledger or an unpriceable "
            "vendor."
        ),
        migration="complete for the ikarus_os.provider_call entrypoint",
    ),
)

ENTRYPOINTS += _IKARUS_CHAT_ROWS


# Phase 4 of the giga plan: "register or remove surviving unregistered doors".
#
# The doors below are module tails -- ``python -m daedalus.<module>`` -- that
# the static scanner does NOT rediscover, and that is the whole reason they
# survived.  ``discover_entrypoints`` drops a CLI ``main`` whose *module-local*
# AST shows no sink (``if not effects and surface is Surface.CLI: continue``),
# and every one of these mains delegates its effects across a module boundary:
# ``health.main`` spawns git through ``_git``, ``picker.main`` reaches a
# worktree through ``run_attempt``, ``eval.__main__`` writes the baseline
# through ``harness.write_baseline``.  So they raised no
# ``entrypoint.unregistered`` blocker while being exactly the doors the
# blocker exists to catch.  Registering them costs an
# ``entrypoint.not_rediscovered`` REVIEW finding each -- the registry's own
# honest label for "a registered target the conservative scanner cannot
# classify" -- which is the correct trade: a named review line beats silence.
#
# HOW THE EFFECT SETS WERE DERIVED, and why they are not painted on.  Each
# effect below is justified by a NAMED function whose own AST contains the
# sink, reached from the door through repository-local calls;
# ``tests/test_registry_new_doors.py`` re-derives every one of them with
# ``_direct_effects`` -- the scanner's own sink table -- and fails in BOTH
# directions: an effect with no reachable sink is a painted label, and a
# reachable sink with no declared effect is an under-declaration.  SPEND has
# no AST sink at all (no call shape means "money"), so it is derived from
# ``daedalus.budget.BILLABLE_SITES`` -- the repository's own list of paid call
# sites -- and never from judgement.
#
# WIRING.  Every row is CENTRAL against a ``begin_effect`` call at the TOP of
# the entry function, above argument parsing, in the c67fd116 shape:
# ``process_guard_boundary_decision()`` installs the process-wide spend net
# and returns the decision naming what it interposed, so the receipt cannot
# cite a guard that never ran.  For the five doors that are ALSO reachable as
# a ``daedalus`` subcommand (health, benchmark, project-memory, improve,
# metrics) that placement means both doors pass the same boundary rather than
# the subcommand being guarded and the tail not.
#
# FIVE OF THE FOURTEEN CANDIDATES GOT NO ROW, and each refusal is checked by a
# test rather than asserted here:
#   * ``daedalus.memory.__init__:main`` -- already registered as ``cli.memory``
#     since the memory door landed; a second row would be a duplicate target.
#   * ``daedalus.metrics:main`` and ``daedalus.progress:main`` -- read-only
#     reporters.  ``metrics.record`` and ``ProgressLog.append`` write, and
#     neither main calls them; the registry's own rule drops an effect-free
#     CLI main from the matrix, and Gate 0 exits on fail-OPEN read-only
#     inspection.  Painting a row on a reporter would make the matrix say
#     less, not more.
#   * ``daedalus.claude_bridge:main`` -- a fail-closed stub (``parser.error``
#     after ``parse_args``, no reachable effect).  Its row was deliberately
#     DELETED on 2026-08-17 for exactly this reason; re-adding one would
#     re-create the staleness finding that deletion removed.
#   * ``daedalus.structcore.index`` -- a library with no tail.  Its effectful
#     runners (``build_index``/``cached_index`` -> ``churn.git_churn``) are
#     reached only through doors that already carry a row: ``cli.daedalus``,
#     ``cli.picker``, ``cli.benchmark``, ``cli.eval``, ``cli.bootstrap``.
_PHASE4_DOOR_ROWS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        id="cli.killswitch",
        surface=Surface.CLI,
        target="daedalus.spine.killswitch:_main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.spine.killswitch:_main", "begin_effect"),),
        notes=(
            "The operator's stop command, and the one door in this registry "
            "whose whole job is to end effects. There is no `daedalus "
            "killswitch` subcommand, so `python -m daedalus.spine.killswitch "
            "stop|arm|clear` is the ONLY way in -- an unregistered door in "
            "front of invariant 8's kill switch. FILESYSTEM_WRITE: stop() "
            "writes marker and permit through _atomic_write -> "
            "daedalus.atomic:write_text_atomic (mkdir/write_text), arm() and "
            "clear() os.unlink the marker. PROCESS_SPAWN: arm() consults "
            "control_check -> verify_control_root -> _cross_process_visible, "
            "which runs `cmd /c type` (or `cat`) through subprocess.run to "
            "prove a second process can see the control root. No SPEND: the "
            "probe spawns a shell built-in against a file this module wrote "
            "and no vendor is reachable from it."
        ),
        migration="complete for the cli.killswitch entrypoint",
    ),
    EntrypointSpec(
        id="cli.health",
        surface=Surface.CLI,
        target="daedalus.health:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.PROCESS_SPAWN,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.health:main", "begin_effect"),),
        notes=(
            "Two doors, one boundary: `daedalus health` and `python -m "
            "daedalus.health`. PROCESS_SPAWN: _git runs git through "
            "subprocess.run and _ssh_powershell runs ssh. NETWORK_EGRESS: "
            "_http_json urlopens the model host, reached from _ollama_alive, "
            "_embed_probe and hand_state. "
            "FILESYSTEM_WRITE, and this one is a CORRECTION worth recording "
            "because the first draft of this row denied it: the probes work "
            "hard not to create what they observe -- _p_ledger opens the "
            "spine read-only precisely because the normal constructor mkdirs "
            "and migrates -- so 'a status read writes nothing' reads as "
            "obviously true and is false. _p_picker calls picker.build_queue, "
            "which reaches structcore.cache:FileCache.__init__: that mkdirs "
            "the cache root and opens a sqlite index read-write. The "
            "derivation in tests/test_registry_new_doors.py found it; reading "
            "the probes did not. No SPEND: no reachable function appears in "
            "daedalus.budget.BILLABLE_SITES, and the bench probes talk to a "
            "local/lab host over ssh and /api/tags. No SECRETS: the "
            "credential-read derivation finds none on this door, unlike the "
            "four doors below that reach doctor:check."
        ),
        migration="complete for the cli.health entrypoint",
    ),
    EntrypointSpec(
        id="cli.progress",
        surface=Surface.CLI,
        target="daedalus.progress:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.progress:main", "begin_effect"),),
        notes=(
            "This row exists because the derivation refused the verdict the "
            "reading gave. `python -m daedalus.progress` renders observed "
            "in-flight progress and looked like a pure reporter -- it never "
            "calls ProgressLog.append, which is the module's only writer -- "
            "so the first pass put it in the no-row column beside "
            "daedalus.metrics. It is not: --ledger reaches "
            "progress_sources:open_attempts, which opens SpineLedger with "
            "read_only=True, and ledger.py's own docstring records the honest "
            "limit that a read-only WAL open still creates the -wal/-shm "
            "sidecars. That is the SAME write cli.token_monitor declares for "
            "the same reason, and declaring it here keeps the two rows "
            "consistent rather than having one door call the sidecars a write "
            "and its neighbour call them nothing. Nothing else: no spawn, no "
            "socket, no credential -- the ledger is opened query_only, so "
            "SQLite refuses a content write at the engine."
        ),
        migration="complete for the cli.progress entrypoint",
    ),
    EntrypointSpec(
        id="cli.project_memory",
        surface=Surface.CLI,
        target="daedalus.memory.projection_worker:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.NETWORK_EGRESS),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.memory.projection_worker:main", "begin_effect"),
        ),
        notes=(
            "`daedalus project-memory` and the module tail. FILESYSTEM_WRITE: "
            "ProjectionWorker.run constructs EventVectorStore, whose __init__ "
            "mkdirs the parent and opens the sqlite index read-write, and "
            "then calls record_journal_watermark. NETWORK_EGRESS: a batch is "
            "one POST from OllamaEmbeddingBackend.embed. That egress ALSO "
            "carries its own row (memory.embeddings) taking the "
            "ollama_endpoint_admission decision at the socket; this row is "
            "the START of the run, not a second copy of that decision -- "
            "different target, different id, no duplicate. --dry-run touches "
            "no backend, but the boundary is above the flag on purpose: a "
            "start that is only guarded on some argument vectors is guarded "
            "by the caller, not by the function."
        ),
        migration="complete for the cli.project_memory entrypoint",
    ),
    EntrypointSpec(
        id="cli.eval",
        surface=Surface.CLI,
        target="daedalus.eval.__main__:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.eval.__main__:main", "begin_effect"),),
        notes=(
            "The missing sibling of cli.eval_ceiling/correctness/graph_delta: "
            "`python -m daedalus.eval` is the eval package's advertised "
            "front door and was the only one of the four without a row. "
            "FILESYSTEM_WRITE: --update-baseline reaches harness.write_baseline "
            "(open(..., 'w')) and --mint-commit reaches mint.save_minted_tasks "
            "-- the two flags that persist anything, and the mint store is a "
            "task corpus, so an unguarded write there is a leakage surface as "
            "well as a write. PROCESS_SPAWN: mint runs git through "
            "subprocess.run, and every tier reaches structcore.churn:git_churn "
            "through cached_index. NETWORK_EGRESS: harness.detect_provider "
            "urlopens /api/tags. SPEND: --tier2 reaches "
            "providers._openai_compat:chat_completion, which "
            "daedalus.budget.BILLABLE_SITES lists as billable BECAUSE the "
            "vendor arrives as base_url at runtime -- the default host is a "
            "local Ollama and costs nothing, but the row cannot know that and "
            "must not pretend to."
        ),
        migration="complete for the cli.eval entrypoint",
    ),
    EntrypointSpec(
        id="cli.approvals",
        surface=Surface.CLI,
        target="daedalus.kernel.approvals:main",
        effects=(Effect.SECRETS,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.kernel.approvals:main", "begin_effect"),),
        notes=(
            "The console door that MINTS owner approvals -- the capability "
            "invariant 5 makes promotion depend on. It writes no file, spawns "
            "nothing and opens no socket: the only effect is SECRETS, and it "
            "is earned under cli.doctor's rule rather than inherited. The "
            "signing key enters THIS process at approvals.py:732 "
            "(`os.environ.get(secret_env)` in _cli_issue) and again at :767 "
            "in _cli_verify, and is used to compute or check the HMAC. "
            "MEASURED GAP, named rather than hidden: "
            "tests/test_provider_secrets_rows.py derives SECRETS from "
            "credential-SHAPED LITERAL environment names, and this door takes "
            "the variable name from --secret-env, so that rule cannot see "
            "this read -- which is why tests/test_registry_new_doors.py pins "
            "it separately. No promotion.owner_approval contract is declared "
            "because this door ISSUES approvals rather than presenting one; "
            "declaring the contract it implements would be circular. That "
            "leaves budget.process_guard as the only decision actually taken "
            "here, and it guards spend, not key custody -- an honest Gate-0 "
            "gap, the same one runtimes.fault_attestation_issuer records."
        ),
        migration="complete for the cli.approvals entrypoint",
    ),
    EntrypointSpec(
        id="cli.picker",
        surface=Surface.CLI,
        target="daedalus.spine.picker:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SECRETS,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.spine.picker:main", "begin_effect"),),
        notes=(
            "`daedalus improve` and `python -m daedalus.spine.picker`. The "
            "default is a dry run and the row still declares the whole set, "
            "because a row describes what the door CAN start: --once --live "
            "reaches _default_attempt -> spine.attempt:run_attempt, which "
            "creates a git worktree (REPOSITORY_MUTATION -- `git worktree "
            "add -b` writes a branch ref into the primary .git), deposits "
            "artifacts (FILESYSTEM_WRITE), spawns the gate child and git "
            "(PROCESS_SPAWN), and runs offload_runner -> offload, which "
            "reaches a provider (NETWORK_EGRESS, SPEND). Those inner "
            "boundaries stay where they are: python.attempt and python.offload "
            "each take their own decisions under their own leases. This row "
            "is the CONSOLE start above them, which is why it declares the "
            "union python.attempt deliberately refuses -- it installs the "
            "process-wide spend net for the whole run, so unlike python.attempt "
            "it does meter what it names. "
            "PROCESS_CONTROL and SECRETS are both CORRECTIONS the derivation "
            "made against this row's first draft, and neither is inheritance. "
            "PROCESS_CONTROL: spine.cancel:ManagedProcess spawns the gate "
            "child through subprocess.Popen and kills it, which is the sink "
            "table's own process-control shape. SECRETS: offload reaches "
            "doctor:check, which reads DEEPSEEK_API_KEY out of the "
            "environment at doctor.py:93, and providers.deepseek's "
            "constructor reads it again -- both IN THIS PROCESS, which is "
            "cli.doctor's rule for earning the label rather than inheriting "
            "it from a child that authenticates itself. cli.eval reaches "
            "neither and does not declare it, which is how the rule stays "
            "worth having."
        ),
        migration="complete for the cli.picker entrypoint",
    ),
    EntrypointSpec(
        id="cli.benchmark",
        surface=Surface.CLI,
        target="daedalus.orchestration.benchmark:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SECRETS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.orchestration.benchmark:main", "begin_effect"),),
        notes=(
            "The legacy live benchmark path is retired: --live now refuses "
            "and the command produces planning estimates only. NETWORK_EGRESS "
            "and SPEND were therefore removed instead of left as painted "
            "labels. The remaining effects are those reached through the "
            "shared central start/process-guard machinery on this head; the "
            "door stays registered so the compatibility CLI cannot regain a "
            "live path outside the canonical matrix unnoticed."
        ),
        migration="complete for the cli.benchmark entrypoint",
    ),
    EntrypointSpec(
        id="cli.build_exec",
        surface=Surface.CLI,
        target="daedalus.build_exec:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SECRETS,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.build_exec:main", "begin_effect"),),
        notes=(
            "The wave executor: the half of the build-session abstraction "
            "that actually runs things, and it has no subcommand at all -- "
            "`daedalus build` only PLANS. --live dispatches each wave through "
            "KairosScheduler, whose write path gates every write task in its "
            "own TaskAttempt worktree (REPOSITORY_MUTATION) and whose accepted "
            "tasks reach offload (FILESYSTEM_WRITE, NETWORK_EGRESS, "
            "PROCESS_SPAWN, SPEND, and SECRETS via doctor:check's read of "
            "DEEPSEEK_API_KEY). One invocation can start a whole multi-wave "
            "run, so this is the highest-fanout console door in the tree and "
            "was the least visible. "
            "REPOSITORY_MUTATION IS THE ONE EFFECT HERE THAT NO .py SCAN CAN "
            "SEE, and it is declared with its bridge named rather than "
            "asserted: run_wave hands the write path to "
            "kairos.gated_writes:run_write_wave, which lives in the RETAINED "
            "LEGACY SOURCE daedalus/kairos/_gated_writes_legacy.py.src -- "
            "loaded through importlib.resources behind a sha1 verification, "
            "and invisible to SCAN_PACKAGES because its suffix is not `.py`. "
            "That blob imports GitWorktreeManager and calls run_attempt "
            "(lines 83 and 391). tests/test_registry_new_doors.py parses the "
            "`.src` file itself and fails if either disappears, so the bridge "
            "is checked rather than believed."
        ),
        migration="complete for the cli.build_exec entrypoint",
    ),
    EntrypointSpec(
        id="cli.bootstrap",
        surface=Surface.CLI,
        target="daedalus.spine.bootstrap:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SECRETS,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.spine.bootstrap:main", "begin_effect"),),
        notes=(
            "One SHADOW iteration of the self-improvement circle: refresh "
            "sources, pick, attempt, gate. No subcommand; the tail is the "
            "only door. shadow_run builds the picker queue (PROCESS_SPAWN via "
            "structcore.churn:git_churn) and runs "
            "spine.attempt:offload_runner through the attempt path, which "
            "means a worktree (REPOSITORY_MUTATION), artifacts "
            "(FILESYSTEM_WRITE), the gate child under spine.cancel:"
            "ManagedProcess (PROCESS_CONTROL) and a provider call "
            "(NETWORK_EGRESS, SPEND, and SECRETS via doctor:check's read of "
            "DEEPSEEK_API_KEY) with --live. Same effect set as cli.picker, "
            "because it is the same attempt path with a source-refresh step "
            "in front of it. Promotion is refused inside shadow_run and this "
            "row does not soften that: it declares the start, not a "
            "permission."
        ),
        migration="complete for the cli.bootstrap entrypoint",
    ),
)

ENTRYPOINTS += _PHASE4_DOOR_ROWS


# Doors that appeared AFTER the Phase-4 sweep, registered the same way instead
# of exempted.  All three were reported as ``entrypoint.unregistered`` blockers
# by ``python -m daedalus.gates report --gate 0`` at 0430c07f -- the first two
# because a wiki lane added two new module tails, the third because a docs
# reporter grew a git spawn.  A blocker that appears because someone added a
# door is the registry working; the answer is a row, not a wider exemption.
#
# EFFECTS ARE DERIVED, NOT PAINTED.  ``discover_entrypoints`` at that revision
# reports ``filesystem_write`` for both wiki tails (evidence ``mkdir@243`` /
# ``write_text@244`` and ``mkdir@372`` / ``write_text@373`` -- pre-patch line
# numbers) and ``process_spawn`` alone for the docs reporter (evidence
# ``delegates:_resolve_candidates``, ``delegates:scan``).  Nothing else is
# claimed: neither wiki tail spawns, opens a socket, or reads a credential, and
# the docs reporter creates no file.  ``tests/test_registry_new_doors.py``
# re-derives all three in BOTH directions, so an under-declaration and a
# painted label fail the same way the ten Phase-4 rows do.
_LATE_DOOR_ROWS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        id="cli.wiki_plan",
        surface=Surface.CLI,
        target="daedalus.wiki.plan:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.wiki.plan:main", "begin_effect"),),
        notes=(
            "`python -m daedalus.wiki.plan <root> [authors] [wiki-dir]` is the "
            "only door; there is no `daedalus wiki-plan` subcommand. "
            "FILESYSTEM_WRITE: the tail of main mkdirs `<root>/runs` and "
            "writes `wiki_plan.json` there, and <root> is whatever path the "
            "operator passes -- the write target is argument-controlled, which "
            "is the reason the boundary sits above argument handling rather "
            "than next to the write. The survey half (survey/assign/"
            "build_plan) only reads, so no further effect is declared: no "
            "subprocess, no urlopen, no credential-shaped environment read is "
            "reachable from this door."
        ),
        migration="complete for the cli.wiki_plan entrypoint",
    ),
    EntrypointSpec(
        id="cli.wiki_verify",
        surface=Surface.CLI,
        target="daedalus.wiki.verify:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.wiki.verify:main", "begin_effect"),),
        notes=(
            "The wiki lane's own verifier, and its sibling door to "
            "cli.wiki_plan. FILESYSTEM_WRITE for the same argument-controlled "
            "reason: main mkdirs `<root>/runs` and writes `wiki_verify.json`. "
            "Worth stating plainly because this door PRINTS A VERDICT: the "
            "artifact it leaves behind is evidence, and evidence produced "
            "outside the boundary is exactly the shape this registry exists to "
            "refuse. Reading the tree (index_symbols, tree_vocabulary, "
            "_config_keys) performs no other effect."
        ),
        migration="complete for the cli.wiki_verify entrypoint",
    ),
    EntrypointSpec(
        id="tools.docs_reference_check",
        surface=Surface.CLI,
        target="tools.docs_reference_check:main",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.docs_reference_check:main", "begin_effect"),),
        notes=(
            "Reports markdown references to files that no longer exist. "
            "PROCESS_SPAWN and nothing else: _tracked_markdown runs `git "
            "ls-files` and _resolve_candidates runs git once per candidate "
            "name through subprocess.run, so a single invocation fans out into "
            "many children -- the cost this door actually imposes is process "
            "count, not bytes written. It creates no file (every output goes "
            "to stdout/stderr), which is why FILESYSTEM_WRITE is absent here "
            "while both wiki rows above carry it; that difference is the "
            "discrimination that keeps the effect column informative."
        ),
        migration="complete for the tools.docs_reference_check entrypoint",
    ),
    EntrypointSpec(
        id="cli.ignition",
        surface=Surface.CLI,
        target="daedalus.ignition.__main__:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor("daedalus.ignition.__main__:main", "begin_effect"),
        ),
        notes=(
            "Public Gate-1 ignition command. FILESYSTEM_WRITE covers its "
            "receipt and content-addressed evidence stores; PROCESS_SPAWN and "
            "PROCESS_CONTROL cover Git/gate children and their managed "
            "lifetime. This outer command boundary precedes argument parsing; "
            "the inner python.attempt boundaries still authorize and lease "
            "each TaskAttempt. The command nominates at most and never "
            "promotes."
        ),
        migration="complete for the cli.ignition entrypoint",
    ),
)

ENTRYPOINTS += _LATE_DOOR_ROWS


# Portable maintenance/build tools that are direct executable module tails.
# They use the same canonical process-guard boundary as the other tool rows;
# dry-run/default behavior does not erase the effects the door can perform.
_PORTABLE_TOOL_ROWS: tuple[EntrypointSpec, ...] = (
    EntrypointSpec(
        id="tools.desktop_sidecar_build",
        surface=Surface.CLI,
        target="tools.build_tauri_sidecar:main",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.build_tauri_sidecar:main", "begin_effect"),),
        notes=(
            "Release build helper: replaces only the bounded desktop build/backend "
            "directories and starts the pinned local PyInstaller module."
        ),
        migration="complete for the desktop sidecar build entrypoint",
    ),
    EntrypointSpec(
        id="tools.desktop_sidecar_smoke",
        surface=Surface.CLI,
        target="tools.smoke_tauri_sidecar:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.PROCESS_CONTROL,
            Effect.NETWORK_EGRESS,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.smoke_tauri_sidecar:main", "begin_effect"),),
        notes=(
            "Bounded release smoke: copies a frozen backend into a temporary "
            "directory, owns that child lifecycle, and probes loopback HTTP only."
        ),
        migration="complete for the desktop sidecar smoke entrypoint",
    ),
    EntrypointSpec(
        id="tools.codex_state_import",
        surface=Surface.CLI,
        target="tools.import_codex_state:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("tools.import_codex_state:main", "begin_effect"),),
        notes=(
            "Explicit offline state-import door. Dry-run is the default; --apply "
            "copies only the allowlisted, non-credential files into an existing "
            "destination and never overwrites a conflict."
        ),
        migration="complete for the safe Codex state-import entrypoint",
    ),
    EntrypointSpec(
        id="tools.desktop_release_assets",
        surface=Surface.CLI,
        target="tools.select_desktop_release_assets:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(
            GuardAnchor(
                "tools.select_desktop_release_assets:main", "begin_effect"
            ),
        ),
        notes=(
            "Release-asset admission helper. The select branch is read-only; "
            "the archive branch creates one bounded .app.tar.gz via a sibling "
            "temporary file and refuses overwrite or ambiguous app bundles."
        ),
        migration="complete for the desktop release-asset entrypoint",
    ),
)

ENTRYPOINTS += _PORTABLE_TOOL_ROWS


REGISTRY_BY_ID: Mapping[str, EntrypointSpec] = MappingProxyType(
    {row.id: row for row in ENTRYPOINTS}
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def registry_sha256(registry: Sequence[EntrypointSpec] = ENTRYPOINTS) -> str:
    body = [
        {
            **asdict(row),
            "surface": row.surface.value,
            "effects": [effect.value for effect in row.effects],
            "wiring": row.wiring.value,
        }
        for row in sorted(registry, key=lambda item: item.id)
    ]
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def begin_effect(
    entrypoint_id: str,
    requested_effects: Iterable[Effect | str],
    decisions: Iterable[GuardDecision],
    *,
    registry: Mapping[str, EntrypointSpec] = REGISTRY_BY_ID,
) -> EffectStartReceipt:
    """Validate an effect start and return a content-addressed receipt.

    Unknown entrypoints, undeclared effects, duplicate decisions, missing
    decisions, denials, empty evidence, and rows not centrally wired all fail
    closed.  The function is pure: it does not itself perform the effect.
    """

    spec = registry.get(str(entrypoint_id))
    if spec is None:
        raise UnregisteredEntrypoint(
            f"effect entrypoint {entrypoint_id!r} is not registered"
        )
    if spec.id != entrypoint_id:
        raise EffectStartRefused(
            f"registry key {entrypoint_id!r} points at mismatched id {spec.id!r}"
        )
    if spec.wiring is not Wiring.CENTRAL:
        raise EffectStartRefused(
            f"{entrypoint_id} is registered as {spec.wiring.value}, not central"
        )
    unknown_required = sorted(set(spec.guard_contracts) - POLICY_CONTRACTS)
    if unknown_required:
        raise EffectStartRefused(
            f"{entrypoint_id} requires unknown guard contracts: "
            + ", ".join(unknown_required)
        )
    unavailable_required = sorted(
        name
        for name in spec.guard_contracts
        if not GUARD_CONTRACT_IMPLEMENTED.get(name, False)
    )
    if unavailable_required:
        raise EffectStartRefused(
            f"{entrypoint_id} requires unimplemented guard contracts: "
            + ", ".join(unavailable_required)
        )

    wanted: list[str] = []
    for raw in requested_effects:
        try:
            value = raw.value if isinstance(raw, Effect) else Effect(str(raw)).value
        except ValueError as exc:
            raise EffectStartRefused(f"unknown effect {raw!r}") from exc
        if value not in wanted:
            wanted.append(value)
    if not wanted:
        raise EffectStartRefused("an effect start must declare at least one effect")
    declared = {effect.value for effect in spec.effects}
    undeclared = sorted(set(wanted) - declared)
    if undeclared:
        raise EffectStartRefused(
            f"{entrypoint_id} did not declare effects: {', '.join(undeclared)}"
        )

    rows: dict[str, GuardDecision] = {}
    for decision in decisions:
        if decision.contract in rows:
            raise EffectStartRefused(
                f"duplicate guard decision for {decision.contract}"
            )
        rows[decision.contract] = decision
    unknown = sorted(set(rows) - set(spec.guard_contracts))
    if unknown:
        raise EffectStartRefused(
            f"{entrypoint_id} received undeclared guard decisions: {', '.join(unknown)}"
        )
    missing = sorted(set(spec.guard_contracts) - set(rows))
    if missing:
        raise EffectStartRefused(
            f"{entrypoint_id} is missing guard decisions: {', '.join(missing)}"
        )
    for contract in sorted(rows):
        decision = rows[contract]
        if not decision.evidence.strip():
            raise EffectStartRefused(f"{contract} supplied no evidence")
        if not decision.allowed:
            raise EffectStartRefused(
                f"{entrypoint_id} denied by {contract}: {decision.evidence}"
            )

    ordered = tuple(rows[name] for name in sorted(rows))
    reg_sha = registry_sha256(tuple(registry.values()))
    payload = {
        "entrypoint_id": spec.id,
        "target": spec.target,
        "runtime_id": spec.runtime_id,
        "requested_effects": sorted(wanted),
        "guard_decisions": [asdict(row) for row in ordered],
        "registry_sha256": reg_sha,
    }
    receipt_sha = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return EffectStartReceipt(
        entrypoint_id=spec.id,
        target=spec.target,
        runtime_id=spec.runtime_id,
        requested_effects=tuple(sorted(wanted)),
        guard_decisions=ordered,
        registry_sha256=reg_sha,
        receipt_sha256=receipt_sha,
    )


@dataclass(frozen=True)
class DiscoveredEntrypoint:
    target: str
    surface: Surface
    effects: tuple[Effect, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ConformanceFinding:
    code: str
    severity: str
    subject: str
    detail: str


@dataclass(frozen=True)
class ConformanceReport:
    registry_sha256: str
    discoveries: tuple[DiscoveredEntrypoint, ...]
    findings: tuple[ConformanceFinding, ...]
    matrix: tuple[EntrypointSpec, ...]

    @property
    def structurally_conformant(self) -> bool:
        return not any(row.severity == "blocker" for row in self.findings)

    @property
    def gate0_closed(self) -> bool:
        return self.structurally_conformant and all(
            row.wiring is Wiring.CENTRAL for row in self.matrix
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "registry_sha256": self.registry_sha256,
            "structurally_conformant": self.structurally_conformant,
            "gate0_closed": self.gate0_closed,
            "security_boundary_claimed": False,
            "guard_contracts": dict(GUARD_CONTRACT_IMPLEMENTED),
            "discoveries": [
                {
                    "target": row.target,
                    "surface": row.surface.value,
                    "effects": [effect.value for effect in row.effects],
                    "evidence": list(row.evidence),
                }
                for row in self.discoveries
            ],
            "findings": [asdict(row) for row in self.findings],
            "matrix": [
                {
                    "id": row.id,
                    "surface": row.surface.value,
                    "target": row.target,
                    "effects": [effect.value for effect in row.effects],
                    "wiring": row.wiring.value,
                    "blocking": row.wiring is Wiring.UNGUARDED,
                    "guards": list(row.guard_contracts),
                    "notes": row.notes,
                    "migration": row.migration,
                }
                for row in self.matrix
            ],
        }


_HIGH_IMPACT_CALLS: Mapping[str, Effect] = {
    "subprocess.run": Effect.PROCESS_SPAWN,
    "subprocess.Popen": Effect.PROCESS_SPAWN,
    "subprocess.check_call": Effect.PROCESS_SPAWN,
    "subprocess.check_output": Effect.PROCESS_SPAWN,
    "asyncio.create_subprocess_exec": Effect.PROCESS_SPAWN,
    "asyncio.create_subprocess_shell": Effect.PROCESS_SPAWN,
    "send_signal": Effect.PROCESS_CONTROL,
    "terminate": Effect.PROCESS_CONTROL,
    "kill": Effect.PROCESS_CONTROL,
    "urllib.request.urlopen": Effect.NETWORK_EGRESS,
    "http.client.HTTPConnection": Effect.NETWORK_EGRESS,
    "http.client.HTTPSConnection": Effect.NETWORK_EGRESS,
    "socket.create_connection": Effect.NETWORK_EGRESS,
    "http.server.ThreadingHTTPServer": Effect.LISTEN_SOCKET,
    "ThreadingHTTPServer": Effect.LISTEN_SOCKET,
}

_PUBLIC_ADAPTER_METHODS = {
    "create_session",
    "send",
    "interrupt",
    "terminate",
}
_WORKTREE_METHODS = {
    "create_worktree",
    "cleanup_worktree",
    "commit_candidate",
    "reap_branches",
}
_FILE_BRIDGE_FUNCTIONS = {"enqueue", "process_request", "watch"}


@dataclass
class _ModuleModel:
    module: str
    path: Path
    tree: ast.Module
    aliases: dict[str, str]
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    class_bases: dict[str, tuple[str, ...]]


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


def _name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


#: Directories the drift detector reads. `tools` is not decoration.
#:
#: MEASURED 2026-07-30: the scan globbed ``root/"daedalus"`` and nothing else,
#: so a new effectful entrypoint added under ``tools/`` was invisible to it --
#: verified by adding one and watching the matrix not change. Counting by hand
#: at that moment: 18 of 19 python files under ``tools/`` are an entrypoint
#: that spawns processes, writes files, mutates the repository or spends money,
#: including ``audit_swarm.py`` (which has billed ~750 external calls) and
#: ``gate_discrimination.py``.
#:
#: The registry documents its limits carefully -- dynamic imports, native code,
#: shell and JS, external clients. An entire tracked directory of effectful
#: Python that the scan never opens was not among them, and an undocumented
#: blind spot is worse than a documented one: the honest gaps invite scrutiny
#: while this one quietly answered "no drift" for code it had never read.
#: Widened 2026-08-17: ``runs`` is production-capable and spends money --
#: ``daedalus.budget.BILLABLE_SITES`` lists five of its functions as billable
#: (council room vendors, summarisers, ab run_arm) -- yet the scan never
#: opened the directory.  Same lesson as ``tools`` above: an unscanned
#: directory of effectful Python is an undocumented blind spot that quietly
#: answers "no drift".  ``scripts`` and ``tests`` remain outside the scan
#: deliberately until an explicit harness classification exists, so widening
#: does not turn ~90 dev-harness entrypoints into blockers overnight; that
#: exclusion is documented here rather than silent.
SCAN_PACKAGES: tuple[str, ...] = ("daedalus", "tools", "runs")

#: Dev-harness directories the conformance pass reads and CLASSIFIES without
#: policing them as production surface.  Measured 2026-08-17: 74 mutation-run
#: scripts and 17 test fixtures are effectful entrypoints.  Leaving them
#: unscanned would repeat the blind-spot mistake documented above; promoting
#: them to blockers would turn the gate off rather than close it (nobody
#: registers 91 dev runners honestly in one sitting).  So every discovered,
#: unregistered entrypoint here becomes an explicit ``entrypoint.harness``
#: review finding: named, counted, and outside Gate-0 wiring by declaration
#: rather than by silence.
HARNESS_PACKAGES: tuple[str, ...] = ("scripts", "tests")


def _models(
    root: Path, packages: Sequence[str] = SCAN_PACKAGES,
) -> tuple[list[_ModuleModel], list[ConformanceFinding]]:
    present = [root / name for name in packages if (root / name).is_dir()]
    if not present:
        return [], [
            ConformanceFinding(
                "scan.package_missing",
                "blocker",
                str(root / packages[0]),
                "cannot inspect entrypoints because no scanned package "
                f"({', '.join(packages)}) is present",
            )
        ]
    models: list[_ModuleModel] = []
    findings: list[ConformanceFinding] = []
    for path in sorted(p for pkg in present for p in pkg.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(
                ConformanceFinding(
                    "scan.source_unreadable",
                    "blocker",
                    str(path.relative_to(root)),
                    f"source could not be inspected: {exc}",
                )
            )
            continue
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        aliases[alias.asname] = alias.name
                    else:
                        head = alias.name.split(".")[0]
                        aliases[head] = head
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                for alias in node.names:
                    aliases[alias.asname or alias.name] = (
                        f"{prefix}.{alias.name}" if prefix else alias.name
                    )
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        class_bases: dict[str, tuple[str, ...]] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                class_bases[node.name] = tuple(_name(base, aliases) for base in node.bases)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions[f"{node.name}.{child.name}"] = child
        models.append(
            _ModuleModel(
                module=_module_name(root, path),
                path=path,
                tree=tree,
                aliases=aliases,
                functions=functions,
                class_bases=class_bases,
            )
        )
    return models, findings


def _direct_effects(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: Mapping[str, str],
) -> tuple[set[Effect], set[str], set[str]]:
    effects: set[Effect] = set()
    evidence: set[str] = set()
    local_calls: set[str] = set()

    def visit(current: ast.AST) -> None:
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(current, ast.Call):
            called = _name(current.func, aliases)
            local_calls.add(called)
            for sink, effect in _HIGH_IMPACT_CALLS.items():
                if called == sink or called.endswith("." + sink):
                    effects.add(effect)
                    evidence.add(f"{called}@{current.lineno}")
            if called.rsplit(".", 1)[-1] in {
                "write_text",
                "write_bytes",
                "unlink",
                "rmdir",
                "mkdir",
            }:
                effects.add(Effect.FILESYSTEM_WRITE)
                evidence.add(f"{called.rsplit('.', 1)[-1]}@{current.lineno}")
            if called in {
                "os.remove",
                "os.unlink",
                "os.rename",
                "os.replace",
                "os.rmdir",
                "shutil.rmtree",
                "shutil.move",
                "shutil.copy",
                "shutil.copy2",
            }:
                effects.add(Effect.FILESYSTEM_WRITE)
                evidence.add(f"{called}@{current.lineno}")
            if called in {"open", "io.open"}:
                mode = current.args[1] if len(current.args) >= 2 else next(
                    (
                        item.value
                        for item in current.keywords
                        if item.arg == "mode"
                    ),
                    None,
                )
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                    if any(flag in mode.value for flag in "wax+"):
                        effects.add(Effect.FILESYSTEM_WRITE)
                        evidence.add(f"{called}({mode.value!r})@{current.lineno}")
        for child in ast.iter_child_nodes(current):
            visit(child)

    visit(node)
    return effects, evidence, local_calls


def _class_surface(model: _ModuleModel, class_name: str) -> Surface | None:
    if (
        model.module == "daedalus.kernel.attempt_ledger"
        and class_name == "AttemptLedger"
    ):
        return Surface.PYTHON
    if (
        model.module == "daedalus.kernel.attempt_workspace"
        and class_name == "IsolatedAttemptCoordinator"
    ):
        return Surface.PYTHON
    bases = model.class_bases.get(class_name, ())
    if any(base.endswith("BaseHTTPRequestHandler") for base in bases):
        return Surface.WEB_API
    if any(base.endswith("AgentAdapter") for base in bases):
        return Surface.PYTHON
    if any(base.endswith("Provider") for base in bases):
        lowered = model.module.casefold()
        if "claude" in lowered:
            return Surface.CLAUDE
        if "codex" in lowered:
            return Surface.CODEX
        if "ollama" in lowered:
            return Surface.OLLAMA
        return Surface.PYTHON
    if class_name.endswith("WorktreeManager"):
        return Surface.WORKTREE
    return None


def _surface_for_function(model: _ModuleModel, qualname: str) -> Surface | None:
    if "." in qualname:
        class_name, method = qualname.split(".", 1)
        surface = _class_surface(model, class_name)
        if (
            surface is Surface.PYTHON
            and model.module == "daedalus.kernel.attempt_ledger"
            and qualname in {"AttemptLedger.begin", "AttemptLedger.complete"}
        ):
            return surface
        if (
            surface is Surface.PYTHON
            and model.module == "daedalus.kernel.attempt_workspace"
            and qualname == "IsolatedAttemptCoordinator.prepare"
        ):
            return surface
        if surface is Surface.WEB_API and method in {"do_POST", "do_PUT", "do_DELETE"}:
            return surface
        if surface is Surface.WORKTREE and method in _WORKTREE_METHODS:
            return surface
        if surface is not None and method in _PUBLIC_ADAPTER_METHODS | {"run", "rollback"}:
            return surface
        return None
    if model.module == "daedalus.file_bridge" and qualname in _FILE_BRIDGE_FUNCTIONS:
        return Surface.FILE_BRIDGE
    if model.module == "daedalus.interfaces.http.web_api" and qualname == "run":
        return Surface.WEB_API
    if (
        model.module == "daedalus.providers._ollama_native"
        and qualname == "native_chat"
    ):
        return Surface.OLLAMA
    if model.module == "daedalus.spine.attempt" and qualname in {
        "command_gate",
        "run_attempt",
    }:
        return Surface.PYTHON
    if model.module == "daedalus.offload" and qualname == "offload":
        return Surface.PYTHON
    if (
        model.module == "daedalus.kairos.gated_writes"
        and qualname == "promote_candidates"
    ):
        return Surface.PYTHON
    if qualname == "main":
        return Surface.CLI
    return None


def discover_entrypoints(
    root: str | Path,
    *,
    _preloaded: tuple[
        list[_ModuleModel], list[ConformanceFinding]
    ] | None = None,
    _console_scripts: bool = True,
) -> tuple[
    tuple[DiscoveredEntrypoint, ...], tuple[ConformanceFinding, ...]
]:
    """Discover high-risk external starts without importing repository code.

    The scanner intentionally targets advertised starts (``main``), provider
    and adapter lifecycle methods, HTTP mutation handlers, File Bridge starts,
    Python attempt starts, and worktree mutation methods.  It is a deterministic
    drift detector, not whole-program reachability or proof of containment.
    """

    root_path = Path(root).resolve()
    models, findings = _preloaded if _preloaded is not None else _models(root_path)
    findings = list(findings)
    rows: dict[str, DiscoveredEntrypoint] = {}

    for model in models:
        direct: dict[str, tuple[set[Effect], set[str], set[str]]] = {
            name: _direct_effects(node, model.aliases)
            for name, node in model.functions.items()
        }
        # Resolve same-module calls to a fixed point.  This catches `main ->
        # run -> ThreadingHTTPServer` and `watch -> process_request` without
        # claiming cross-module whole-program analysis.
        changed = True
        while changed:
            changed = False
            for qualname, (effects, evidence, calls) in direct.items():
                for called in tuple(calls):
                    local = called.split(".")[-1]
                    candidate = local
                    if "." in qualname:
                        class_name = qualname.split(".", 1)[0]
                        class_candidate = f"{class_name}.{local}"
                        if class_candidate in direct:
                            candidate = class_candidate
                    target = direct.get(candidate)
                    if target is None:
                        continue
                    before = (len(effects), len(evidence))
                    effects.update(target[0])
                    if target[0]:
                        evidence.add(f"delegates:{called}")
                    if before != (len(effects), len(evidence)):
                        changed = True

        for qualname, (effects, evidence, _calls) in direct.items():
            surface = _surface_for_function(model, qualname)
            if surface is None:
                continue
            # Provider/adapter/handler/worktree lifecycle methods are effectful
            # by contract even when the sink is in a delegated module.  A main
            # function with no observed effect is read-only and is not part of
            # the effect matrix.
            if not effects and surface is Surface.CLI:
                continue
            if not effects:
                if surface in {
                    Surface.CLAUDE,
                    Surface.CODEX,
                    Surface.OLLAMA,
                    Surface.WEB_API,
                    Surface.WORKTREE,
                    Surface.FILE_BRIDGE,
                    Surface.PYTHON,
                }:
                    evidence.add("effectful-interface-contract")
                    if surface in {Surface.CLAUDE, Surface.CODEX, Surface.OLLAMA}:
                        effects.update(
                            {
                                Effect.PROCESS_SPAWN,
                                Effect.NETWORK_EGRESS,
                                Effect.FILESYSTEM_WRITE,
                            }
                        )
                    elif surface is Surface.WEB_API:
                        effects.add(Effect.FILESYSTEM_WRITE)
                    elif surface is Surface.WORKTREE:
                        effects.update(
                            {
                                Effect.FILESYSTEM_WRITE,
                                Effect.REPOSITORY_MUTATION,
                            }
                        )
                    elif "." in qualname and any(
                        base.endswith("AgentAdapter")
                        for base in model.class_bases.get(qualname.split(".", 1)[0], ())
                    ):
                        effects.add(Effect.PROCESS_CONTROL)
                    else:
                        effects.add(Effect.FILESYSTEM_WRITE)
            target = f"{model.module}:{qualname}"
            rows[target] = DiscoveredEntrypoint(
                target=target,
                surface=surface,
                effects=tuple(sorted(effects, key=lambda item: item.value)),
                evidence=tuple(sorted(evidence)),
            )

    # The installed console script is another advertised path.  Python 3.10 is
    # supported and has no tomllib, so parse only this deliberately tiny TOML
    # table instead of adding a runtime dependency.  Unexpected syntax inside
    # the table is a blocker rather than a silently ignored line.
    if not _console_scripts:
        return tuple(sorted(rows.values(), key=lambda row: row.target)), tuple(findings)

    pyproject = root_path / "pyproject.toml"
    try:
        scripts = _project_scripts(pyproject.read_text(encoding="utf-8"))
        for name, target in sorted(scripts.items()):
            normalized = str(target)
            row = rows.get(normalized)
            located = _target_node(
                {model.module: model for model in models}, normalized
            )
            if located is None:
                findings.append(
                    ConformanceFinding(
                        "scan.console_target_missing",
                        "blocker",
                        str(name),
                        f"console script target {target!r} does not resolve",
                    )
                )
            elif row is None:
                rows[normalized] = DiscoveredEntrypoint(
                    target=normalized,
                    surface=Surface.CLI,
                    effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
                    evidence=(f"pyproject.console_script:{name}",),
                )
    except (OSError, UnicodeError, ValueError) as exc:
        findings.append(
            ConformanceFinding(
                "scan.pyproject_unreadable",
                "blocker",
                str(pyproject),
                f"console entrypoints could not be inspected: {exc}",
            )
        )

    return tuple(sorted(rows.values(), key=lambda row: row.target)), tuple(findings)


_TOML_KEY = re.compile(r"^(?:[A-Za-z0-9_-]+|\"[^\"]+\"|'[^']+')$")


def _project_scripts(text: str) -> dict[str, str]:
    in_scripts = False
    seen = False
    scripts: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_scripts:
                break
            in_scripts = stripped == "[project.scripts]"
            seen = seen or in_scripts
            continue
        if not in_scripts or not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ValueError(f"invalid [project.scripts] line {number}")
        raw_key, raw_value = (part.strip() for part in stripped.split("=", 1))
        if not _TOML_KEY.fullmatch(raw_key):
            raise ValueError(f"invalid script key on line {number}")
        try:
            key = ast.literal_eval(raw_key) if raw_key[:1] in "\"'" else raw_key
            value = ast.literal_eval(raw_value)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"invalid script value on line {number}") from exc
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"script key/value on line {number} must be strings")
        if key in scripts:
            raise ValueError(f"duplicate script key {key!r}")
        scripts[key] = value
    if not seen:
        return {}
    return scripts


def _target_node(
    models: Mapping[str, _ModuleModel], target: str
) -> tuple[_ModuleModel, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    if ":" not in target:
        return None
    module, qualname = target.split(":", 1)
    model = models.get(module)
    if model is None:
        return None
    node = model.functions.get(qualname)
    return (model, node) if node is not None else None


def _called_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef, aliases: Mapping[str, str]
) -> set[str]:
    _effects, _evidence, calls = _direct_effects(node, aliases)
    return calls


@lru_cache(maxsize=8)
def _harness_scan(
    root: str,
) -> tuple[tuple[DiscoveredEntrypoint, ...], tuple[ConformanceFinding, ...]]:
    """Read HARNESS_PACKAGES once per process and root.

    The harness population (~550 files) dominates conformance wall time, and
    a test session calls :func:`check_conformance` many times against the same
    tree.  The cache is per-process only: the CLI and CI pay the scan exactly
    once per invocation, so drift detection across runs is unaffected.  Within
    one long-lived process a harness file edited after the first scan is seen
    only after ``_harness_scan.cache_clear()`` -- an accepted, stated bound,
    not a silent one.  Production packages are never cached.
    """
    root_path = Path(root)
    models, findings = _models(root_path, HARNESS_PACKAGES)
    downgraded = tuple(
        ConformanceFinding(
            "scan.harness_source_unreadable", "review", row.subject, row.detail
        )
        for row in findings
        if row.code != "scan.package_missing"
        # a repo without harness dirs has nothing to classify
    )
    rows, _scan_findings = discover_entrypoints(
        root_path, _preloaded=(models, []), _console_scripts=False
    )
    return rows, downgraded


def check_conformance(
    root: str | Path,
    *,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> ConformanceReport:
    root_path = Path(root).resolve()
    models_list, model_findings = _models(root_path)
    discoveries, scan_findings = discover_entrypoints(
        root_path, _preloaded=(models_list, model_findings)
    )
    findings = list(scan_findings)
    models = {model.module: model for model in models_list}

    ids: set[str] = set()
    targets: set[str] = set()
    for row in registry:
        if row.id in ids:
            findings.append(
                ConformanceFinding(
                    "registry.duplicate_id", "blocker", row.id, "entrypoint id is duplicated"
                )
            )
        ids.add(row.id)
        if row.discoverable and row.target in targets:
            findings.append(
                ConformanceFinding(
                    "registry.duplicate_target",
                    "blocker",
                    row.target,
                    "effectful target has more than one registry owner",
                )
            )
        if row.discoverable:
            targets.add(row.target)
        if not row.effects:
            findings.append(
                ConformanceFinding(
                    "registry.effects_empty",
                    "blocker",
                    row.id,
                    "effectful entrypoint declares no effects",
                )
            )
        unknown_contracts = sorted(set(row.guard_contracts) - POLICY_CONTRACTS)
        if unknown_contracts:
            findings.append(
                ConformanceFinding(
                    "registry.guard_unknown",
                    "blocker",
                    row.id,
                    "unknown policy contracts: " + ", ".join(unknown_contracts),
                )
            )
        if row.wiring is Wiring.CENTRAL and not row.guard_contracts:
            findings.append(
                ConformanceFinding(
                    "registry.central_without_guards",
                    "blocker",
                    row.id,
                    "central effect starts require at least one guard contract",
                )
            )
        unavailable_contracts = sorted(
            name
            for name in row.guard_contracts
            if not GUARD_CONTRACT_IMPLEMENTED.get(name, False)
        )
        if row.wiring is Wiring.CENTRAL and unavailable_contracts:
            findings.append(
                ConformanceFinding(
                    "registry.central_guard_unimplemented",
                    "blocker",
                    row.id,
                    "central row requires missing contracts: "
                    + ", ".join(unavailable_contracts),
                )
            )
        if row.discoverable and _target_node(models, row.target) is None:
            findings.append(
                ConformanceFinding(
                    "registry.target_missing",
                    "blocker",
                    row.id,
                    f"registered target {row.target} does not exist",
                )
            )
        for anchor in row.anchors:
            located = _target_node(models, anchor.target)
            if located is None:
                findings.append(
                    ConformanceFinding(
                        "registry.anchor_target_missing",
                        "blocker",
                        row.id,
                        f"anchor target {anchor.target} does not exist",
                    )
                )
                continue
            model, node = located
            calls = _called_names(node, model.aliases)
            if not any(
                called == anchor.call or called.endswith("." + anchor.call)
                for called in calls
            ):
                findings.append(
                    ConformanceFinding(
                        "registry.guard_anchor_missing",
                        "blocker",
                        row.id,
                        f"{anchor.target} no longer calls {anchor.call}",
                    )
                )

    discovered_targets = {row.target for row in discoveries}
    specs_by_target = {row.target: row for row in registry if row.discoverable}
    for row in discoveries:
        if row.target not in targets:
            findings.append(
                ConformanceFinding(
                    "entrypoint.unregistered",
                    "blocker",
                    row.target,
                    "discovered effectful entrypoint is outside the canonical registry",
                )
            )
            continue
        spec = specs_by_target[row.target]
        if row.surface is not spec.surface:
            findings.append(
                ConformanceFinding(
                    "entrypoint.surface_drift",
                    "blocker",
                    row.target,
                    (
                        f"discovered as {row.surface.value}, registry declares "
                        f"{spec.surface.value}"
                    ),
                )
            )
        extra_effects = sorted(
            {effect.value for effect in row.effects}
            - {effect.value for effect in spec.effects}
        )
        if extra_effects:
            # An "effectful-interface-contract" discovery with no observed
            # sink is a DEFAULT the scanner applies out of admitted ignorance
            # (a provider-surface method whose only call it could not resolve
            # -- e.g. an inherited ``self._rollback_writes`` since the
            # rollback single-sourcing). Measured 2026-08-23: that default
            # out-voted the reviewed 2026-08-18 declaration on
            # provider.ollama.rollback and blocked as "drift" although
            # nothing was observed to drift. A default may question a
            # declaration; it may not overrule one -- so ignorance is named
            # as a review finding, and only an OBSERVED effect (a sink or a
            # resolved delegate in the evidence) still blocks.
            observed = any(
                item.startswith("delegates:") or "@" in item
                for item in row.evidence
            )
            if "effectful-interface-contract" in row.evidence and not observed:
                findings.append(
                    ConformanceFinding(
                        "entrypoint.effect_default_exceeds_declaration",
                        "review",
                        row.target,
                        "the scanner's interface-default effects exceed the "
                        "declaration and no sink was observed: "
                        + ", ".join(extra_effects),
                    )
                )
            else:
                findings.append(
                    ConformanceFinding(
                        "entrypoint.effect_drift",
                        "blocker",
                        row.target,
                        "new undeclared effects: " + ", ".join(extra_effects),
                    )
                )
    for target in sorted(targets - discovered_targets):
        # Registered delegated boundaries can be real even if the conservative
        # scanner does not infer their sink.  The AST existence check above is
        # authoritative for staleness; this is an explicit review finding.
        findings.append(
            ConformanceFinding(
                "entrypoint.not_rediscovered",
                "review",
                target,
                "registered target exists but static sink discovery did not classify it",
            )
        )

    present_surfaces = {row.surface for row in registry}
    for surface in Surface:
        if surface not in present_surfaces:
            findings.append(
                ConformanceFinding(
                    "registry.surface_missing",
                    "blocker",
                    surface.value,
                    "Gate-0 surface has no inventory row",
                )
            )
    for row in registry:
        if row.wiring is Wiring.UNGUARDED:
            findings.append(
                ConformanceFinding(
                    "gate0.unguarded_entrypoint",
                    "blocker",
                    row.id,
                    (
                        f"{row.target} can perform protected effects without the "
                        f"central boundary; migration: {row.migration or 'not specified'}"
                    ),
                )
            )
        if row.wiring is not Wiring.CENTRAL:
            findings.append(
                ConformanceFinding(
                    "gate0.not_central",
                    "gap",
                    row.id,
                    f"{row.target} is {row.wiring.value}; Gate 0 is not closed",
                )
            )

    # Dev-harness classification: read the harness directories with the same
    # discovery, but emit review findings instead of blockers.  A harness
    # entrypoint is out of Gate-0 wiring scope by DECLARATION; silence would
    # be the old blind spot and blockers would just get the gate disabled.
    harness_rows, harness_findings = _harness_scan(str(root_path))
    findings.extend(harness_findings)
    for row in harness_rows:
        if row.target in targets:
            continue
        findings.append(
            ConformanceFinding(
                "entrypoint.harness",
                "review",
                row.target,
                (
                    "dev-harness entrypoint ("
                    + ", ".join(effect.value for effect in row.effects)
                    + ") outside the production registry; explicitly classified "
                    "out-of-scope for Gate-0 wiring, not silently unscanned"
                ),
            )
        )

    findings.append(
        ConformanceFinding(
            "scan.static_scope",
            "review",
            "python-ast",
            (
                "static Python discovery is a drift detector, not whole-program "
                "reachability; dynamic imports, native code, shell/JS, and external "
                "clients still require an effect boundary or OS containment"
            ),
        )
    )

    return ConformanceReport(
        registry_sha256=registry_sha256(registry),
        discoveries=discoveries,
        findings=tuple(
            sorted(findings, key=lambda row: (row.severity, row.code, row.subject))
        ),
        matrix=tuple(registry),
    )


def human_matrix(report: ConformanceReport) -> str:
    lines = [
        "Daedalus Gate-0 effect-boundary matrix",
        f"registry sha256: {report.registry_sha256}",
        "security boundary claimed: NO",
        f"structural conformance: {'PASS' if report.structurally_conformant else 'BLOCKED'}",
        f"Gate 0 closed: {'YES' if report.gate0_closed else 'NO'}",
        "",
        "surface       wiring          id                         target",
    ]
    for row in report.matrix:
        lines.append(
            f"{row.surface.value:<13} {row.wiring.value:<15} "
            f"{row.id:<26} {row.target}"
        )
    if report.findings:
        lines.extend(("", "findings:"))
        for finding in report.findings:
            lines.append(
                f"[{finding.severity.upper():7}] {finding.code}: "
                f"{finding.subject} -- {finding.detail}"
            )
    return "\n".join(lines)


__all__ = [
    "ConformanceFinding",
    "ConformanceReport",
    "DiscoveredEntrypoint",
    "Effect",
    "EffectBoundaryError",
    "EffectStartReceipt",
    "EffectStartRefused",
    "EntrypointSpec",
    "ENTRYPOINTS",
    "GuardAnchor",
    "GuardDecision",
    "GUARD_CONTRACT_IMPLEMENTED",
    "POLICY_CONTRACTS",
    "REGISTRY_BY_ID",
    "Surface",
    "UnregisteredEntrypoint",
    "Wiring",
    "begin_effect",
    "check_conformance",
    "discover_entrypoints",
    "human_matrix",
    "registry_sha256",
]
