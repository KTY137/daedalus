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
        target="daedalus.cli:main",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.REPOSITORY_MUTATION,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(GuardAnchor("daedalus.cli:main", "install_process_guard"),),
        notes="Console script installs the spend guard, then dispatches local subcommands.",
    ),
    EntrypointSpec(
        id="web.server",
        surface=Surface.WEB_API,
        target="daedalus.web_api:run",
        effects=(Effect.LISTEN_SOCKET,),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(GuardAnchor("daedalus.web_api:run", "_resolve_bind"),),
        notes="Bind is loopback-only unless explicit authenticated remote opt-in succeeds.",
    ),
    EntrypointSpec(
        id="web.mutations",
        surface=Surface.WEB_API,
        target="daedalus.web_api:DaedalusHandler.do_POST",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.INVENTORY_ONLY,
        anchors=(GuardAnchor("daedalus.web_api:DaedalusHandler.do_POST", "_authorized"),),
        notes="Request auth exists; one canonical per-request effect start does not.",
    ),
    EntrypointSpec(
        id="file_bridge.enqueue",
        surface=Surface.FILE_BRIDGE,
        target="daedalus.file_bridge:enqueue",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("file_bridge.crash_journal",),
        wiring=Wiring.INVENTORY_ONLY,
        notes="Atomic queue publication; dispatch policy is evaluated by the watcher.",
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
        wiring=Wiring.INVENTORY_ONLY,
        notes="Durable before-dispatch journal exists; no shared effect-start lease exists.",
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
        wiring=Wiring.INVENTORY_ONLY,
        notes="Direct python -m watcher can run without installing the process spend guard.",
    ),
    EntrypointSpec(
        id="python.attempt",
        surface=Surface.PYTHON,
        target="daedalus.spine.attempt:run_attempt",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("spine.intent_ledger", "containment.attempt"),
        wiring=Wiring.LOCAL_GUARDS,
        notes="Canonical attempt path, but direct Python callers do not yet obtain a boundary receipt.",
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
        wiring=Wiring.INVENTORY_ONLY,
        notes="Verified argv profiles exist; cwd/write/egress policy is not centrally leased.",
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
        notes="Provider delegates to ask_claude; direct Python use bypasses CLI spend installation.",
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
        notes="Egress is fail-closed and write defaults false; direct write mode remains an unleased path.",
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
        id="provider.ollama_native",
        surface=Surface.OLLAMA,
        target="daedalus.providers._ollama_native:native_chat",
        effects=(Effect.NETWORK_EGRESS,),
        guard_contracts=("provider.egress_policy",),
        wiring=Wiring.INVENTORY_ONLY,
        runtime_id="ollama_http",
        notes="Low-level HTTP helper accepts a host and has no independent lane decision.",
    ),
    EntrypointSpec(
        id="worktree.create",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.create_worktree",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.create_worktree",
                "_refuse_if_repo_adjacent",
            ),
        ),
        notes="Allocation is confined and recorded before git worktree creation.",
    ),
    EntrypointSpec(
        id="worktree.commit",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.commit_candidate",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.commit_candidate",
                "_require_allocated_worktree",
            ),
        ),
        notes="Only a worktree allocated by this manager may be staged and committed.",
    ),
    EntrypointSpec(
        id="worktree.cleanup",
        surface=Surface.WORKTREE,
        target="daedalus.kairos.worktree:GitWorktreeManager.cleanup_worktree",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.REPOSITORY_MUTATION),
        guard_contracts=("containment.worktree",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(
            GuardAnchor(
                "daedalus.kairos.worktree:GitWorktreeManager.cleanup_worktree",
                "_require_allocated_worktree",
            ),
        ),
        notes="Removal revalidates allocation and path identity; it is not generic rmtree.",
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
        wiring=Wiring.INVENTORY_ONLY,
        anchors=(GuardAnchor("tools.guarded_call:main", "run"),),
        notes=(
            "Process-boundary door for external-environment callers; budget and "
            "secret-floor refusals live in DeepSeekProvider.run (the anchored "
            "delegated call). The static scanner cannot see this cross-module "
            "sink, so spend/secrets here are hand-declared."
        ),
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
        wiring=Wiring.INVENTORY_ONLY,
        anchors=(GuardAnchor("tools.audit_swarm:main", "fan_out"),),
        notes=(
            "Paid fan-out. The spend guard is installed fail-closed inside the "
            "anchored fan_out callee (daedalus.lanes.fanout), not by this "
            "entrypoint itself; no canonical effect start exists yet."
        ),
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
        wiring=Wiring.INVENTORY_ONLY,
        anchors=(
            GuardAnchor("tools.funnel:main", "fan_out"),
            GuardAnchor("tools.funnel:main", "budget_verdict"),
        ),
        notes=(
            "Paid tiered fan-out. Local budget verdict runs before dispatch and "
            "the spend guard is installed fail-closed inside the anchored "
            "fan_out callee; no canonical effect start exists yet."
        ),
    ),
)

# Additional currently advertised/direct Python starts found by the static
# inventory.  They remain rows in the *same* registry rather than an exemption
# list: adding another such callable creates an ``entrypoint.unregistered``
# blocker, while deleting one makes its row stale.  These rows are intentionally
# concise because their next Gate-0 action is consolidation behind the primary
# rows above, not preservation as separate architecture.
_LEGACY_ENTRYPOINT_ROWS: tuple[
    tuple[str, Surface, str, tuple[Effect, ...], Wiring], ...
] = (
    (
        "adapter.subprocess.send",
        Surface.PYTHON,
        "daedalus.adapters.subprocess_adapter:SubprocessAdapter.send",
        (Effect.PROCESS_CONTROL,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "adapter.subprocess.interrupt",
        Surface.PYTHON,
        "daedalus.adapters.subprocess_adapter:SubprocessAdapter.interrupt",
        (Effect.PROCESS_CONTROL,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "adapter.subprocess.terminate",
        Surface.PYTHON,
        "daedalus.adapters.subprocess_adapter:SubprocessAdapter.terminate",
        (Effect.PROCESS_CONTROL,),
        Wiring.INVENTORY_ONLY,
    ),
    ("cli.arch_memory", Surface.CLI, "daedalus.arch_memory:main", (Effect.PROCESS_SPAWN,), Wiring.INVENTORY_ONLY),
    (
        "cli.bookkeeper",
        Surface.CLI,
        "daedalus.bookkeeper:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.claude_bridge",
        Surface.CLI,
        "daedalus.claude_bridge:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.dctx",
        Surface.CLI,
        "daedalus.dctx:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.doctor",
        Surface.CLI,
        "daedalus.doctor:main",
        (Effect.NETWORK_EGRESS, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    ("cli.enforce", Surface.CLI, "daedalus.enforce:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.eval_ceiling", Surface.CLI, "daedalus.eval.ceiling:main", (Effect.PROCESS_SPAWN,), Wiring.INVENTORY_ONLY),
    (
        "cli.eval_correctness",
        Surface.CLI,
        "daedalus.eval.correctness:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.eval_graph_delta",
        Surface.CLI,
        "daedalus.eval.graph_delta:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    ("cli.file_bridge", Surface.CLI, "daedalus.file_bridge:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.gui_lint", Surface.CLI, "daedalus.gui.lint:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.mapping_drift", Surface.CLI, "daedalus.mapping.drift:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    (
        "cli.mapping_inventory",
        Surface.CLI,
        "daedalus.mapping.inventory:main",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.mapping_render",
        Surface.CLI,
        "daedalus.mapping.render:main",
        (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.memory",
        Surface.CLI,
        "daedalus.memory.__init__:main",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    ("cli.runbook", Surface.CLI, "daedalus.runbook:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.selftest", Surface.CLI, "daedalus.selftest:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.shift", Surface.CLI, "daedalus.shift:main", (Effect.FILESYSTEM_WRITE,), Wiring.INVENTORY_ONLY),
    ("cli.status", Surface.CLI, "daedalus.status:main", (Effect.PROCESS_SPAWN,), Wiring.INVENTORY_ONLY),
    (
        "cli.structcore",
        Surface.CLI,
        "daedalus.structcore.__main__:main",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.structcore_slice",
        Surface.CLI,
        "daedalus.structcore.slice:main",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "cli.token_monitor",
        Surface.CLI,
        "daedalus.token_monitor:main",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    ("cli.web_api", Surface.CLI, "daedalus.web_api:main", (Effect.LISTEN_SOCKET,), Wiring.INVENTORY_ONLY),
    (
        # Corrected 2026-08-17 per the Gate-0 effect-boundary inventory:
        # run reads DEEPSEEK_API_KEY, and chat_completion is priced through
        # daedalus.budget._guarded_urlopen, so the busiest paid lane declares
        # spend/egress/secrets instead of filesystem_write alone.
        "provider.deepseek",
        Surface.PYTHON,
        "daedalus.providers.deepseek:DeepSeekProvider.run",
        (
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "provider.deepseek.rollback",
        Surface.PYTHON,
        "daedalus.providers.deepseek:DeepSeekProvider.rollback",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "provider.ollama.rollback",
        Surface.OLLAMA,
        "daedalus.providers.ollama:OllamaProvider.rollback",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "python.command_gate",
        Surface.PYTHON,
        "daedalus.spine.attempt:command_gate",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "web.mutations_put",
        Surface.WEB_API,
        "daedalus.web_api:DaedalusHandler.do_PUT",
        (Effect.FILESYSTEM_WRITE,),
        Wiring.INVENTORY_ONLY,
    ),
    (
        "worktree.reap",
        Surface.WORKTREE,
        "daedalus.kairos.worktree:GitWorktreeManager.reap_branches",
        (
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        Wiring.INVENTORY_ONLY,
    ),
)

ENTRYPOINTS += tuple(
    EntrypointSpec(
        id=row_id,
        surface=surface,
        target=target,
        effects=effects,
        guard_contracts=(),
        wiring=wiring,
        notes=(
            "Legacy direct start retained in the Gate-0 inventory; consolidate "
            "behind a canonical boundary row before declaring Gate 0 closed."
        ),
    )
    for row_id, surface, target, effects, wiring in _LEGACY_ENTRYPOINT_ROWS
)


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
SCAN_PACKAGES: tuple[str, ...] = ("daedalus", "tools")


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
    if model.module == "daedalus.web_api" and qualname == "run":
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
