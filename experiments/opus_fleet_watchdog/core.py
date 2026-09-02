"""One-campaign, read-only advisory fleet.

EXPERIMENT, Gate 0.  LangGraph computes a pure slot plan; this module owns the
bounded effects and operational state.  Model output can only land in existing
Council transcripts.  Nothing here imports TaskAttempt or exposes a checkout
write, patch, commit, merge, promotion, or evaluator capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from daedalus.atomic import write_text_atomic
from daedalus.budget import BudgetError, Ledger, guard as budget_guard
from daedalus.council.session import Evidence, convene as council_convene
from daedalus.council.vendors import (
    ClaudeAdapter,
    CodexAdapter,
    CouncilAdapter,
    RunResult,
)
from daedalus.projects import list_projects, resolve_repo_root
from daedalus.spine.cancel import DEFAULT_GRACE_S
from daedalus.spine.killswitch import KillSwitch, LoopHalted


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = ROOT / "runs" / "watchdog"
STATE_SCHEMA = "opus-fleet-watchdog-state/1"
FALLBACK_API_STATUSES = frozenset({429, 503, 529})
# Council's transport-neutral thread cap must outlive the CLI adapter's own
# timeout and ManagedProcess cancellation ladder.  Otherwise Council can
# abandon its daemon seat while that seat is still cancelling a child, release
# the campaign lock, and let the next scheduler tick overlap it.
# ``ManagedProcess.cancel`` may spend DEFAULT_GRACE_S waiting for a graceful
# exit and then another ten seconds waiting after the hard tree kill.  In the
# pathological branch where the contained process still has not reported an
# exit, the surrounding ManagedProcess context calls ``close`` and performs
# the bounded ladder once more.  Cover both ladders plus cleanup before Council
# may abandon the seat and release the fleet lock.
COUNCIL_CANCELLATION_MARGIN_S = 2.0 * (DEFAULT_GRACE_S + 10.0) + 2.0
TERMINAL_SLOT_STATUSES = frozenset(
    {"completed", "failed", "budget_refused", "refused", "suppressed", "unknown"}
)
_CAMPAIGN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ConfigError(ValueError):
    """The explicit campaign configuration or pure plan is unsafe/invalid."""


class CampaignCorrupt(RuntimeError):
    """Durable state no longer binds the requested config/plan."""


class CampaignBusy(RuntimeError):
    """Another process already holds this campaign's execution lock."""


@dataclass(frozen=True)
class ProjectConfig:
    project: str
    objective: str
    context_paths: tuple[str, ...]
    repo_root: Path

    def planner_dict(self) -> dict[str, str]:
        # The pure LangGraph adapter calls this field ``name`` and maps it back
        # to ``project`` on every slot.  Keep that adapter contract exact.
        return {"name": self.project, "objective": self.objective}

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "objective": self.objective,
            "context_paths": list(self.context_paths),
            "repo_root": str(self.repo_root),
        }


@dataclass(frozen=True)
class FleetConfig:
    campaign_id: str
    live: bool
    projects: tuple[ProjectConfig, ...]
    roles: tuple[str, ...]
    max_agents: int
    max_parallel: int
    timeout_s: float
    token_ceiling: int
    max_calls: int
    max_spend_usd: float
    codex_model: str
    max_evidence_bytes: int = 1_000_000

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "live": self.live,
            "projects": [p.canonical_dict() for p in self.projects],
            "roles": list(self.roles),
            "max_agents": self.max_agents,
            "max_parallel": self.max_parallel,
            "timeout_s": self.timeout_s,
            "token_ceiling": self.token_ceiling,
            "max_calls": self.max_calls,
            "max_spend_usd": self.max_spend_usd,
            "codex_model": self.codex_model,
            "max_evidence_bytes": self.max_evidence_bytes,
        }

    @property
    def digest(self) -> str:
        return _digest(self.canonical_dict())

    def project(self, name: str) -> ProjectConfig:
        for project in self.projects:
            if project.project == name:
                return project
        raise ConfigError(f"planner returned project {name!r} outside configured projects")


@dataclass(frozen=True)
class FleetSlot:
    ordinal: int
    slot_id: str
    project: str
    objective: str
    role: str
    probe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "slot_id": self.slot_id,
            "project": self.project,
            "objective": self.objective,
            "role": self.role,
            "probe": self.probe,
        }


@dataclass(frozen=True)
class ClaudeJsonWrapper:
    """Only fields that can affect routing, parsed from the complete JSON body."""

    is_error: bool
    api_error_status: int | None


@dataclass(frozen=True)
class SessionProbeResult:
    """Cross-runtime observation supplied by the 20-minute supervisor."""

    ok: bool
    active_sessions: int
    sources: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class _AskBudgetOutcome:
    """Cross-thread result of the reservation wrapped around ``adapter.ask``."""

    error: BudgetError | None = None
    halted: bool = False
    started: bool = False
    completed: bool = False


class StructuredClaudeAdapter(ClaudeAdapter):
    """Council Claude adapter that retains a typed wrapper observation.

    The base Council adapter correctly treats an error wrapper as a transport
    failure, but intentionally collapses its details.  The experiment needs one
    additional *routing* fact.  It is captured here from the complete JSON
    object, never recovered from prose or stderr.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_json_wrapper: ClaudeJsonWrapper | None = None

    def argv(self, model: str) -> list[str]:
        argv = super().argv(model)
        # The inherited Council profile's explicit deny-list is useful defence
        # in depth but is not closed: a newly introduced Claude tool would not
        # yet be named.  Claude's native empty ``--tools`` value is the closed
        # set.  The remaining flags prevent command/session surfaces from
        # quietly re-introducing state or capabilities around it.
        argv.extend(
            [
                "--tools",
                "",
                "--safe-mode",
                "--disable-slash-commands",
                "--no-session-persistence",
            ]
        )
        return argv

    @property
    def last_json_wrapper(self) -> ClaudeJsonWrapper | None:
        return self._last_json_wrapper

    def _parse_ok(self, result: RunResult) -> dict[str, Any]:
        observation = parse_claude_json_wrapper(result.stdout)
        self._last_json_wrapper = observation
        if observation is not None and observation.is_error:
            return self._error_reply(observation)
        return super()._parse_ok(result)

    def _interpret(self, result: RunResult) -> dict[str, Any]:
        # A timed-out or unspawned call has an unknown outcome even if stdout
        # contains a fragment, so the base classification wins.  Otherwise the
        # complete JSON stdout wrapper is authoritative across both zero and
        # non-zero CLI exit codes: current Claude emits its structured API
        # error wrapper while exiting non-zero.
        if result.spawn_error or result.timed_out:
            self._last_json_wrapper = None
            return super()._interpret(result)
        # Authentication is not capacity.  A non-zero CLI response carrying
        # an auth marker must never be upgraded into a rate-limit fallback,
        # even if its stdout also happens to contain a well-shaped wrapper.
        if self._auth_failure(result):
            self._last_json_wrapper = None
            return super()._interpret(result)
        observation = parse_claude_json_wrapper(result.stdout)
        self._last_json_wrapper = observation
        if observation is not None and observation.is_error:
            return self._error_reply(observation)
        return super()._interpret(result)

    @staticmethod
    def _error_reply(observation: ClaudeJsonWrapper) -> dict[str, Any]:
        usage: dict[str, Any] = {}
        if observation.api_error_status is not None:
            usage["api_error_status"] = observation.api_error_status
        return {
            "status": "error",
            "reason": "bad_response",
            "stderr": "Claude returned a structured JSON error wrapper",
            "usage": usage,
        }


class ExecutableCodexAdapter(CodexAdapter):
    """Pin the native executable on Windows, never an npm shell shim.

    ``shutil.which('codex')`` resolves to ``codex.cmd`` first on the target
    machine.  A shell script is neither needed nor acceptable here: Council
    dispatch is an argv-only ManagedProcess with no shell.  The native binary
    is resolved explicitly; absence therefore becomes the adapter's ordinary
    ``not_on_path``/spawn failure instead of a shell fallback.
    """

    def argv(self, model: str) -> list[str]:
        argv = super().argv(model)
        if os.name == "nt":
            argv[0] = shutil.which("codex.exe") or "codex.exe"
        # Keep authentication, but load neither user MCP/config nor repository
        # rules and persist no Codex session outside the Council transcript.
        # These are native ``codex exec`` flags and must precede the positional
        # ``-`` which carries the prompt on stdin.
        stdin_index = argv.index("-")
        argv[stdin_index:stdin_index] = [
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
        ]
        return argv


Planner = Callable[[list[dict[str, str]], list[str]], Mapping[str, Any]]
AdapterFactory = Callable[[str, FleetConfig, Path], CouncilAdapter]
Convene = Callable[..., Any]
BudgetGuardFactory = Callable[
    [str, str, str, Ledger], AbstractContextManager[Any]
]


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strict_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _finite_float(value: Any, name: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ConfigError(f"{name} must be finite and >= {minimum}")
    return result


def _text(value: Any, name: str, *, max_chars: int = 20_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    result = value.strip()
    if len(result) > max_chars:
        raise ConfigError(f"{name} exceeds {max_chars} characters")
    return result


def _safe_relative_path(value: Any, name: str) -> str:
    raw = _text(value, name, max_chars=500).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ConfigError(f"{name} must stay relative to its registered project root")
    if raw.startswith("/") or "\x00" in raw:
        raise ConfigError(f"{name} is not a safe relative path")
    return raw


def _required(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"configuration is missing required field {key!r}")
    return mapping[key]


def load_config(path: str | Path) -> FleetConfig:
    """Load and validate one explicit JSON configuration.

    Project roots come only from :mod:`daedalus.projects`; the JSON cannot
    smuggle an arbitrary checkout into the experiment.
    """

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load JSON config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")
    allowed = {
        "campaign_id",
        "live",
        "projects",
        "roles",
        "max_agents",
        "max_parallel",
        "timeout_s",
        "token_ceiling",
        "max_calls",
        "max_spend_usd",
        "codex_model",
        "max_evidence_bytes",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"unknown configuration field(s): {', '.join(unknown)}")

    campaign_id = _text(_required(raw, "campaign_id"), "campaign_id", max_chars=64)
    if not _CAMPAIGN_RE.fullmatch(campaign_id):
        raise ConfigError("campaign_id must be filename-safe ASCII")
    live = _required(raw, "live")
    if not isinstance(live, bool):
        raise ConfigError("live must be a JSON boolean")

    project_rows = _required(raw, "projects")
    if not isinstance(project_rows, list) or not project_rows:
        raise ConfigError("projects must be a non-empty list")
    known = set(list_projects())
    projects: list[ProjectConfig] = []
    seen_projects: set[str] = set()
    for index, row in enumerate(project_rows):
        if not isinstance(row, dict):
            raise ConfigError(f"projects[{index}] must be an object")
        extra = sorted(set(row) - {"project", "objective", "context_paths", "enabled"})
        if extra:
            raise ConfigError(f"projects[{index}] has unknown field(s): {', '.join(extra)}")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"projects[{index}].enabled must be a boolean")
        if not enabled:
            continue
        project_name = _text(
            _required(row, "project"), f"projects[{index}].project", max_chars=100
        )
        if project_name not in known:
            raise ConfigError(
                f"unknown project {project_name!r}; known projects: {', '.join(sorted(known)) or 'none'}"
            )
        if project_name in seen_projects:
            raise ConfigError(f"duplicate enabled project {project_name!r}")
        seen_projects.add(project_name)
        objective = _text(
            _required(row, "objective"), f"projects[{index}].objective"
        )
        path_rows = _required(row, "context_paths")
        if not isinstance(path_rows, list) or not path_rows:
            raise ConfigError(f"projects[{index}].context_paths must be non-empty")
        context_paths = tuple(
            _safe_relative_path(item, f"projects[{index}].context_paths[{pos}]")
            for pos, item in enumerate(path_rows)
        )
        if len(set(context_paths)) != len(context_paths):
            raise ConfigError(f"projects[{index}].context_paths contains duplicates")
        repo_root = Path(resolve_repo_root(project=project_name)).resolve()
        if not repo_root.is_dir():
            raise ConfigError(f"registered root for {project_name!r} is not a directory")
        projects.append(
            ProjectConfig(project_name, objective, context_paths, repo_root)
        )
    if not projects:
        raise ConfigError("at least one project must be enabled")

    role_rows = _required(raw, "roles")
    if not isinstance(role_rows, list) or not role_rows:
        raise ConfigError("roles must be a non-empty list")
    roles = tuple(_text(role, f"roles[{i}]", max_chars=500) for i, role in enumerate(role_rows))
    if len(set(roles)) != len(roles):
        raise ConfigError("roles must be unique")

    max_agents = _strict_int(_required(raw, "max_agents"), "max_agents", minimum=1, maximum=20)
    max_parallel = _strict_int(
        _required(raw, "max_parallel"), "max_parallel", minimum=1, maximum=4
    )
    if max_parallel > max_agents:
        raise ConfigError("max_parallel cannot exceed max_agents")
    timeout_s = _finite_float(_required(raw, "timeout_s"), "timeout_s", minimum=1.0)
    if timeout_s > 7_200:
        raise ConfigError("timeout_s cannot exceed 7200 seconds")
    token_ceiling = _strict_int(
        _required(raw, "token_ceiling"), "token_ceiling", minimum=1, maximum=1_000_000
    )
    max_calls = _strict_int(
        _required(raw, "max_calls"), "max_calls", minimum=1, maximum=21
    )
    if max_calls < max_agents + 1:
        raise ConfigError("max_calls must reserve one extra call for the typed probe fallback")
    max_spend_usd = _finite_float(
        _required(raw, "max_spend_usd"), "max_spend_usd", minimum=0.01
    )
    codex_model = _text(_required(raw, "codex_model"), "codex_model", max_chars=200)
    max_evidence_bytes = _strict_int(
        raw.get("max_evidence_bytes", 1_000_000),
        "max_evidence_bytes",
        minimum=1,
        maximum=10_000_000,
    )
    return FleetConfig(
        campaign_id=campaign_id,
        live=live,
        projects=tuple(projects),
        roles=roles,
        max_agents=max_agents,
        max_parallel=max_parallel,
        timeout_s=timeout_s,
        token_ceiling=token_ceiling,
        max_calls=max_calls,
        max_spend_usd=max_spend_usd,
        codex_model=codex_model,
        max_evidence_bytes=max_evidence_bytes,
    )


def parse_claude_json_wrapper(raw: str) -> ClaudeJsonWrapper | None:
    """Parse only an exact Claude JSON wrapper, never embedded/free text."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    is_error = payload.get("is_error")
    if not isinstance(is_error, bool):
        return None
    status = payload.get("api_error_status")
    if isinstance(status, bool) or not isinstance(status, int):
        status = None
    return ClaudeJsonWrapper(is_error=is_error, api_error_status=status)


def fallback_provider(observation: ClaudeJsonWrapper | None) -> str | None:
    """Return ``codex`` only for the three frozen structured API statuses."""

    if (
        type(observation) is ClaudeJsonWrapper
        and observation.is_error is True
        and observation.api_error_status in FALLBACK_API_STATUSES
    ):
        return "codex"
    return None


def _default_planner(
    projects: list[dict[str, str]], roles: list[str], *, capacity: int
) -> Mapping[str, Any]:
    from daedalus.orchestration.langgraph_adapter import plan_advisory_fleet

    return plan_advisory_fleet(projects, roles, capacity=capacity)


def _validate_plan(raw: Mapping[str, Any], config: FleetConfig) -> tuple[FleetSlot, ...]:
    if not isinstance(raw, Mapping):
        raise ConfigError("plan_advisory_fleet must return an object")
    rows = raw.get("slots")
    if not isinstance(rows, list) or not rows:
        raise ConfigError("plan_advisory_fleet returned no slots")
    if len(rows) > config.max_agents or len(rows) > 20:
        raise ConfigError("pure planner exceeded the global fleet capacity")
    slots: list[FleetSlot] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ConfigError(f"planner slot {index} is not an object")
        expected = {"ordinal", "slot_id", "project", "objective", "role", "probe"}
        missing = sorted(expected - set(row))
        extra = sorted(set(row) - expected)
        if missing or extra:
            raise ConfigError(
                f"planner slot {index} shape mismatch; missing={missing}, extra={extra}"
            )
        ordinal = _strict_int(row["ordinal"], f"slots[{index}].ordinal", minimum=0, maximum=10_000)
        slot_id = _text(row["slot_id"], f"slots[{index}].slot_id", max_chars=64)
        if not _SLOT_RE.fullmatch(slot_id):
            raise ConfigError(f"planner slot_id {slot_id!r} is not filename-safe")
        project = _text(row["project"], f"slots[{index}].project", max_chars=100)
        project_config = config.project(project)
        objective = _text(row["objective"], f"slots[{index}].objective")
        if objective != project_config.objective:
            raise ConfigError(f"planner changed the frozen objective for project {project!r}")
        role = _text(row["role"], f"slots[{index}].role", max_chars=500)
        if role not in config.roles:
            raise ConfigError(f"planner returned unconfigured role {role!r}")
        probe = row["probe"]
        if not isinstance(probe, bool):
            raise ConfigError(f"slots[{index}].probe must be a boolean")
        slots.append(FleetSlot(ordinal, slot_id, project, objective, role, probe))
    if len({s.slot_id for s in slots}) != len(slots):
        raise ConfigError("planner returned duplicate slot_id values")
    if len({s.ordinal for s in slots}) != len(slots):
        raise ConfigError("planner returned duplicate ordinal values")
    slots.sort(key=lambda slot: (slot.ordinal, slot.slot_id))
    probes = [slot for slot in slots if slot.probe]
    if len(probes) != 1 or probes[0] != slots[0]:
        raise ConfigError("planner must mark exactly the first slot as the Claude probe")
    return tuple(slots)


def _plan(config: FleetConfig, planner: Callable[..., Mapping[str, Any]] | None) -> tuple[FleetSlot, ...]:
    function = planner or _default_planner
    raw = function(
        [project.planner_dict() for project in config.projects],
        list(config.roles),
        capacity=config.max_agents,
    )
    return _validate_plan(raw, config)


def _mission_dir(config: FleetConfig, runs_root: str | Path | None) -> Path:
    base = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    return base / f"mission-{config.campaign_id}"


def dry_plan(
    config_path: str | Path,
    *,
    planner: Callable[..., Mapping[str, Any]] | None = None,
    runs_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the validated pure plan.  It performs no writes or model calls."""

    config = load_config(config_path)
    slots = _plan(config, planner)
    slot_rows = [slot.to_dict() for slot in slots]
    return {
        "schema": "opus-fleet-watchdog-plan/1",
        "campaign_id": config.campaign_id,
        "config_digest": config.digest,
        "plan_digest": _digest(slot_rows),
        "mission_dir": str(_mission_dir(config, runs_root)),
        "global_slots": len(slots),
        "max_parallel": config.max_parallel,
        "max_calls": config.max_calls,
        "max_spend_usd": config.max_spend_usd,
        "slots": slot_rows,
    }


def _resolve_selected_file(project: ProjectConfig, relative: str) -> Path:
    candidate = (project.repo_root / Path(relative)).resolve(strict=True)
    try:
        candidate.relative_to(project.repo_root)
    except ValueError as exc:
        raise ConfigError(
            f"context path {relative!r} escapes registered root for {project.project!r}"
        ) from exc
    if not candidate.is_file():
        raise ConfigError(f"context path {relative!r} is not a regular file")
    return candidate


def _build_evidence(config: FleetConfig, slot: FleetSlot) -> Evidence:
    project = config.project(slot.project)
    files: list[tuple[str, str]] = []
    charged = 0
    for relative in project.context_paths:
        selected = _resolve_selected_file(project, relative)
        raw = selected.read_bytes()
        charged += len(raw)
        if charged > config.max_evidence_bytes:
            raise ConfigError(
                f"selected evidence for {project.project!r} exceeds max_evidence_bytes"
            )
        files.append((relative, raw.decode("utf-8", "replace")))
    digest = _digest({"project": project.project, "files": files})
    return Evidence(
        label=f"opus-fleet:{config.campaign_id}:{project.project}",
        paths=project.context_paths,
        files=tuple(files),
        digest=digest,
    )


def _question(slot: FleetSlot) -> str:
    return (
        "Produce advisory findings and deterministic checks only. Do not make a "
        "decision, do not propose promotion, and do not claim to have read any "
        "file outside the supplied Evidence.\n\n"
        f"Objective: {slot.objective}\n"
        f"Assigned review role: {slot.role}"
    )


def _default_adapter_factory(provider: str, config: FleetConfig, repo_root: Path) -> CouncilAdapter:
    if provider == "claude":
        return StructuredClaudeAdapter(
            model="opus", repo_root=repo_root, max_prompt_tokens=config.token_ceiling
        )
    if provider == "codex":
        return ExecutableCodexAdapter(
            model=config.codex_model,
            repo_root=repo_root,
            max_prompt_tokens=config.token_ceiling,
        )
    raise ConfigError(f"unsupported advisory provider {provider!r}")


def _default_budget_guard(
    provider: str, model: str, label: str, ledger: Ledger
) -> AbstractContextManager[Any]:
    vendor = "anthropic_cli" if provider == "claude" else "openai_cli"
    return budget_guard(vendor, model, label=label, led=ledger)


def _adapter_observation(adapter: CouncilAdapter) -> ClaudeJsonWrapper | None:
    if not isinstance(adapter, StructuredClaudeAdapter):
        return None
    observation = adapter.last_json_wrapper
    return observation if type(observation) is ClaudeJsonWrapper else None


def _bind_budgeted_ask(
    adapter: CouncilAdapter,
    *,
    provider: str,
    model: str,
    label: str,
    ledger: Ledger,
    budget_guard_factory: BudgetGuardFactory,
    kill_switch: KillSwitch,
    effect_timeout_s: float,
) -> _AskBudgetOutcome:
    """Put reservation and the final stop check at the vendor boundary.

    ``council_convene`` deliberately invokes ``adapter.ask`` on its own thread.
    Daedalus' process-guard double-charge suppression is thread-local, so an
    outer reservation in the caller thread does not cover the ManagedProcess
    spawn.  Binding the already-bound ``ask`` and CLI runner on this *same
    adapter instance* preserves Claude/Codex ``isinstance`` and Council
    live-wire inspection while moving both checks to the actual effect thread.

    For subprocess-backed Council seats the reservation wraps ``_runner``
    rather than the whole ``ask``.  Besides being closer to the spawn, this
    means a secret-floor refusal or prompt-ceiling refusal does not consume a
    provider charge.  A non-CLI injected seat falls back to guarding ``ask``.
    """

    original_ask = adapter.ask
    outcome = _AskBudgetOutcome()
    original_runner = getattr(adapter, "_runner", None)

    def checkpoint() -> None:
        try:
            kill_switch.checkpoint()
        except LoopHalted:
            outcome.halted = True
            raise

    if callable(original_runner):
        def guarded_runner(*args: Any, **kwargs: Any):
            checkpoint()
            try:
                with budget_guard_factory(provider, model, label, ledger):
                    # This is the final cooperative check immediately before
                    # invoking the runner that constructs ManagedProcess.
                    checkpoint()
                    outcome.started = True
                    return original_runner(*args, **kwargs)
            except BudgetError as exc:
                outcome.error = exc
                raise

        adapter._runner = guarded_runner  # type: ignore[attr-defined]

    def guarded_ask(*args: Any, **kwargs: Any):
        checkpoint()
        # Council's join budget includes cancellation grace, while the CLI's
        # actual process deadline remains the configured effect timeout.
        kwargs["timeout_s"] = effect_timeout_s
        if callable(original_runner):
            reply = original_ask(*args, **kwargs)
            outcome.completed = True
            return reply
        try:
            with budget_guard_factory(provider, model, label, ledger):
                checkpoint()
                # A custom non-CLI adapter has no narrower runner seam.  Be
                # conservative: from this point its effect may have started.
                outcome.started = True
                reply = original_ask(*args, **kwargs)
                outcome.completed = True
                return reply
        except BudgetError as exc:
            outcome.error = exc
            raise

    # Instance binding is intentional: ``original_ask`` is already bound, so
    # the closure's first positional argument remains the Council prompt.
    adapter.ask = guarded_ask  # type: ignore[method-assign]
    return outcome


def _record_summary(record: Any) -> dict[str, Any]:
    responded = getattr(record, "responded", None)
    chain_intact = getattr(record, "chain_intact", None)
    if isinstance(responded, bool) or not isinstance(responded, int):
        responded = 0
    return {
        "responded": responded,
        "chain_intact": chain_intact is True,
        "chain_head": str(getattr(record, "chain_head", "") or ""),
        "store_path": str(getattr(record, "store_path", "") or ""),
        "ended": str(getattr(record, "ended", "") or ""),
    }


def _record_succeeded(summary: Mapping[str, Any]) -> bool:
    return summary.get("chain_intact") is True and int(summary.get("responded") or 0) > 0


def _record_failure_reason(summary: Mapping[str, Any]) -> str:
    if summary.get("ended") == "floor_refusal":
        return "secret_floor"
    return "council_no_valid_voice"


class _CampaignLock:
    """OS-released advisory lock; a dead process cannot strand the campaign."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_CampaignLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise CampaignBusy(f"campaign lock is already held: {self.path}") from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()).encode("ascii"))
        self.handle.flush()
        return self

    def __exit__(self, *_exc: Any) -> bool:
        if self.handle is None:
            return False
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
        return False


class _StateStore:
    def __init__(self, path: Path, config: FleetConfig, slots: Sequence[FleetSlot]) -> None:
        self.path = path
        self.config = config
        self.slots = tuple(slots)
        self.plan_digest = _digest([slot.to_dict() for slot in self.slots])
        self.lock = threading.RLock()
        self.state: dict[str, Any]

    def _write(self) -> None:
        self.state["updated_at"] = _utc_now()
        write_text_atomic(
            self.path,
            json.dumps(self.state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="",
        )

    def load_or_create(self) -> dict[str, Any]:
        with self.lock:
            if self.path.exists():
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise CampaignCorrupt(f"cannot read campaign state: {exc}") from exc
                if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
                    raise CampaignCorrupt("campaign state schema is missing or unsupported")
                if state.get("campaign_id") != self.config.campaign_id:
                    raise CampaignCorrupt("campaign state belongs to a different campaign")
                if state.get("config_digest") != self.config.digest:
                    raise CampaignCorrupt("campaign config changed; use a new campaign_id")
                if state.get("plan_digest") != self.plan_digest:
                    raise CampaignCorrupt("pure fleet plan changed; use a new campaign_id")
                existing_ids = [row.get("slot_id") for row in state.get("slots", [])]
                if existing_ids != [slot.slot_id for slot in self.slots]:
                    raise CampaignCorrupt("campaign slot ledger does not match the frozen plan")
                self.state = state
                return state

            now = _utc_now()
            self.state = {
                "schema": STATE_SCHEMA,
                "campaign_id": self.config.campaign_id,
                "config_digest": self.config.digest,
                "plan_digest": self.plan_digest,
                "created_at": now,
                "updated_at": now,
                "status": "ready",
                "provider_decision": "pending",
                "reason": "",
                "calls_claimed": 0,
                # Evidence is intentionally not read or frozen until the
                # cross-runtime session gate reports idle.  A campaign may sit
                # in ``waiting`` across many scheduler ticks while a human is
                # editing its selected context.
                "evidence_frozen_at": "",
                "session_checks": [],
                "slots": [
                    {
                        **slot.to_dict(),
                        "evidence_digest": "",
                        "status": "pending",
                        "provider": "",
                        "reason": "",
                        "attempts": [],
                    }
                    for slot in self.slots
                ],
            }
            self._write()
            return self.state

    def freeze_evidence_digests(self, evidence_digests: Mapping[str, str]) -> None:
        """Seal the first idle-tick snapshot before any provider claim.

        Waiting with no calls is pre-campaign operational state, so selected
        files may legitimately change between active-session ticks.  Once any
        call is claimed, digests are immutable and later reads are compared to
        them by the dispatch path.
        """

        expected_ids = [slot.slot_id for slot in self.slots]
        if set(evidence_digests) != set(expected_ids):
            raise CampaignCorrupt("evidence snapshot does not match the frozen plan")
        if any(
            not isinstance(evidence_digests[slot_id], str)
            or not evidence_digests[slot_id]
            for slot_id in expected_ids
        ):
            raise CampaignCorrupt("evidence snapshot contains an invalid digest")
        with self.lock:
            can_freeze = (
                int(self.state.get("calls_claimed") or 0) == 0
                and self.state.get("provider_decision") == "pending"
                and all(
                    slot.get("status") == "pending"
                    for slot in self.state.get("slots", [])
                )
            )
            if can_freeze:
                for slot_id in expected_ids:
                    self.slot(slot_id)["evidence_digest"] = evidence_digests[slot_id]
                self.state["evidence_frozen_at"] = _utc_now()
                self._write()
                return

            # A resumed, already-dispatched campaign must have a complete
            # immutable seal.  Do not silently bless a partial/legacy state.
            if not self.state.get("evidence_frozen_at") or any(
                not isinstance(self.slot(slot_id).get("evidence_digest"), str)
                or not self.slot(slot_id).get("evidence_digest")
                for slot_id in expected_ids
            ):
                raise CampaignCorrupt(
                    "campaign dispatched without a complete evidence freeze"
                )

    def record_session_check(self, result: SessionProbeResult) -> None:
        """Persist why this scheduler tick dispatched or waited."""

        with self.lock:
            checks = self.state.setdefault("session_checks", [])
            checks.append(
                {
                    "observed_at": _utc_now(),
                    "ok": result.ok,
                    "active_sessions": result.active_sessions,
                    "sources": list(result.sources),
                    "reason": result.reason,
                }
            )
            # This is operational evidence, not an event store.  Bound its
            # growth while retaining enough 20-minute ticks for diagnosis.
            if len(checks) > 100:
                del checks[:-100]
            if not result.ok:
                self.state["status"] = "waiting"
                self.state["reason"] = f"session_probe_error:{result.reason or 'unknown'}"
            elif result.active_sessions > 0:
                self.state["status"] = "waiting"
                self.state["reason"] = "active_sessions_present"
            else:
                self.state["reason"] = "session_probe_clear"
                self._refresh_status()
            self._write()

    def slot(self, slot_id: str) -> dict[str, Any]:
        for row in self.state["slots"]:
            if row["slot_id"] == slot_id:
                return row
        raise CampaignCorrupt(f"missing slot {slot_id!r}")

    def reconcile_stale(self) -> bool:
        """Turn abandoned dispatch into unknown, then halt all unclaimed work."""

        with self.lock:
            stale = False
            for slot in self.state["slots"]:
                if slot.get("status") == "in_flight":
                    stale = True
                    slot["status"] = "unknown"
                    slot["reason"] = "process_restarted_after_durable_claim"
                    for attempt in slot.get("attempts", []):
                        if attempt.get("status") == "claimed":
                            attempt["status"] = "unknown"
                            attempt["reason"] = "dispatch_outcome_unknown_after_restart"
            if stale:
                for slot in self.state["slots"]:
                    if slot.get("status") == "pending":
                        slot["status"] = "suppressed"
                        slot["reason"] = "campaign_halted_after_unknown_outcome"
                self.state["provider_decision"] = "stopped"
                self.state["reason"] = "unknown_outcome_never_auto_retried"
                self.state["status"] = "degraded"
                self._write()
            return stale

    def claim_slot(self, slot_id: str, provider: str) -> None:
        with self.lock:
            slot = self.slot(slot_id)
            if slot.get("status") != "pending":
                raise CampaignCorrupt(
                    f"slot {slot_id!r} cannot be claimed from {slot.get('status')!r}"
                )
            slot["status"] = "in_flight"
            slot["provider"] = provider
            slot["reason"] = ""
            self.state["status"] = "running"
            self._write()

    def try_claim_pending_slot(self, slot_id: str, provider: str) -> bool:
        """Claim queued fan-out work unless an earlier unknown stopped it."""

        with self.lock:
            slot = self.slot(slot_id)
            if slot.get("status") == "suppressed" and self.state.get(
                "provider_decision"
            ) == "stopped":
                return False
            if slot.get("status") != "pending":
                raise CampaignCorrupt(
                    f"slot {slot_id!r} cannot be claimed from {slot.get('status')!r}"
                )
            slot["status"] = "in_flight"
            slot["provider"] = provider
            slot["reason"] = ""
            self.state["status"] = "running"
            self._write()
            return True

    def claim_call(self, slot_id: str, provider: str, council_id: str, store_path: Path) -> int:
        with self.lock:
            if int(self.state.get("calls_claimed") or 0) >= self.config.max_calls:
                raise ConfigError("campaign max_calls exhausted before dispatch")
            slot = self.slot(slot_id)
            if slot.get("status") != "in_flight":
                raise CampaignCorrupt(f"call claim requires in_flight slot {slot_id!r}")
            attempt = {
                "provider": provider,
                "council_id": council_id,
                "store_path": str(store_path),
                "status": "claimed",
                "reason": "",
                "claimed_at": _utc_now(),
                "api_error_status": None,
                "chain_head": "",
            }
            slot.setdefault("attempts", []).append(attempt)
            self.state["calls_claimed"] = int(self.state.get("calls_claimed") or 0) + 1
            self._write()
            return len(slot["attempts"]) - 1

    def settle_call(
        self,
        slot_id: str,
        attempt_index: int,
        *,
        status: str,
        reason: str = "",
        api_error_status: int | None = None,
        record: Mapping[str, Any] | None = None,
    ) -> None:
        with self.lock:
            attempt = self.slot(slot_id)["attempts"][attempt_index]
            if attempt.get("status") != "claimed":
                raise CampaignCorrupt("attempt settlement is not exactly-once")
            attempt["status"] = status
            attempt["reason"] = reason
            attempt["api_error_status"] = api_error_status
            if record:
                attempt["chain_head"] = str(record.get("chain_head") or "")
                attempt["ended"] = str(record.get("ended") or "")
                attempt["responded"] = int(record.get("responded") or 0)
                attempt["chain_intact"] = record.get("chain_intact") is True
            self._write()

    def finish_slot(self, slot_id: str, status: str, reason: str = "") -> None:
        if status not in TERMINAL_SLOT_STATUSES:
            raise CampaignCorrupt(f"invalid terminal slot status {status!r}")
        with self.lock:
            slot = self.slot(slot_id)
            if slot.get("status") != "in_flight":
                raise CampaignCorrupt(f"slot {slot_id!r} is not in_flight")
            slot["status"] = status
            slot["reason"] = reason
            self._refresh_status()
            self._write()

    def finish_probe_transition(
        self,
        slot_id: str,
        *,
        status: str,
        slot_reason: str,
        provider_decision: str,
        decision_reason: str,
        suppress_reason: str = "",
    ) -> None:
        """Atomically terminalise the probe and freeze the routing decision.

        The probe slot and provider decision are one state-machine transition,
        not two facts that may be durably observed in different revisions.  A
        crash before this single atomic replace leaves the slot ``in_flight``
        and is reconciled to unknown; a crash after it sees the complete
        transition.  In particular, a failed Codex fallback can never leave a
        durable ``provider_decision=codex`` with runnable pending slots.
        """

        if status not in TERMINAL_SLOT_STATUSES:
            raise CampaignCorrupt(f"invalid terminal probe status {status!r}")
        if provider_decision not in {"claude", "codex", "stopped"}:
            raise CampaignCorrupt(
                f"invalid probe provider decision {provider_decision!r}"
            )
        if bool(suppress_reason) != (provider_decision == "stopped"):
            raise CampaignCorrupt(
                "stopped probe transitions must suppress pending work exactly once"
            )
        with self.lock:
            slot = self.slot(slot_id)
            if slot.get("status") != "in_flight":
                raise CampaignCorrupt(f"probe slot {slot_id!r} is not in_flight")
            slot["status"] = status
            slot["reason"] = slot_reason
            self.state["provider_decision"] = provider_decision
            self.state["reason"] = decision_reason
            if suppress_reason:
                for pending in self.state["slots"]:
                    if pending.get("status") == "pending":
                        pending["status"] = "suppressed"
                        pending["reason"] = suppress_reason
            self._refresh_status()
            self._write()

    def finish_unknown_slot_and_stop(self, slot_id: str, reason: str) -> None:
        """Record an unattributable dispatch and prevent any new fan-out."""

        with self.lock:
            slot = self.slot(slot_id)
            if slot.get("status") != "in_flight":
                raise CampaignCorrupt(f"unknown slot {slot_id!r} is not in_flight")
            slot["status"] = "unknown"
            slot["reason"] = reason
            self.state["provider_decision"] = "stopped"
            self.state["reason"] = "unknown_dispatch_outcome"
            for pending in self.state["slots"]:
                if pending.get("status") == "pending":
                    pending["status"] = "suppressed"
                    pending["reason"] = "campaign_halted_after_unknown_outcome"
            self._refresh_status()
            self._write()

    def decision(self, provider: str, reason: str = "") -> None:
        if provider not in {"claude", "codex", "stopped"}:
            raise CampaignCorrupt(f"invalid provider decision {provider!r}")
        with self.lock:
            self.state["provider_decision"] = provider
            self.state["reason"] = reason
            self._write()

    def suppress_pending(self, reason: str) -> None:
        with self.lock:
            for slot in self.state["slots"]:
                if slot.get("status") == "pending":
                    slot["status"] = "suppressed"
                    slot["reason"] = reason
            self._refresh_status()
            self._write()

    def _refresh_status(self) -> None:
        statuses = [slot.get("status") for slot in self.state["slots"]]
        if all(status in TERMINAL_SLOT_STATUSES for status in statuses):
            self.state["status"] = (
                "complete" if all(status == "completed" for status in statuses) else "degraded"
            )
        elif any(status == "in_flight" for status in statuses):
            self.state["status"] = "running"
        else:
            self.state["status"] = "ready"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state))


def _council_id(config: FleetConfig, slot: FleetSlot, provider: str, call_number: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", config.campaign_id)[:24]
    digest = hashlib.sha256(slot.slot_id.encode("utf-8")).hexdigest()[:8]
    return f"ofw-{stem}-{slot.ordinal:02d}-{digest}-{provider}-{call_number}"


def _session_observation(session_probe: Callable[[], Any] | None) -> SessionProbeResult:
    """Call and strictly normalise the supervisor's cross-runtime probe.

    There is intentionally no PID-file fallback.  A missing, raising, or
    malformed probe is could-not-tell and therefore no-dispatch.
    """

    if session_probe is None:
        return SessionProbeResult(False, 0, (), "session_probe_not_configured")
    try:
        raw = session_probe()
    except Exception as exc:
        return SessionProbeResult(False, 0, (), f"{type(exc).__name__}")
    if isinstance(raw, SessionProbeResult):
        # Dataclass instances cross the same trust boundary as mappings.  Feed
        # them through the exact same validator (negative counts, malformed
        # sources, and forged runtime types must fail closed).
        raw = {
            "ok": raw.ok,
            "active_sessions": raw.active_sessions,
            "sources": raw.sources,
            "reason": raw.reason,
        }
    if not isinstance(raw, Mapping):
        return SessionProbeResult(False, 0, (), "malformed_session_probe")
    ok = raw.get("ok")
    active = raw.get("active_sessions")
    sources = raw.get("sources", [])
    reason = raw.get("reason", "")
    if (
        not isinstance(ok, bool)
        or isinstance(active, bool)
        or not isinstance(active, int)
        or active < 0
        or not isinstance(sources, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in sources)
        or not isinstance(reason, str)
    ):
        return SessionProbeResult(False, 0, (), "malformed_session_probe")
    return SessionProbeResult(ok, active, tuple(item.strip() for item in sources), reason.strip())


def _dispatch_call(
    *,
    provider: str,
    config: FleetConfig,
    slot: FleetSlot,
    evidence: Evidence,
    mission_dir: Path,
    store: _StateStore,
    ledger: Ledger,
    adapter_factory: AdapterFactory,
    convene_fn: Convene,
    budget_guard_factory: BudgetGuardFactory,
    kill_switch: KillSwitch,
) -> tuple[dict[str, Any] | None, ClaudeJsonWrapper | None, str]:
    # First checkpoint is before even reserving a call number.  The second is
    # after the durable claim and immediately before the effect boundary.  A
    # stop in between is therefore recorded as a known no-dispatch outcome,
    # while a crash after the second remains honestly unknown.
    try:
        kill_switch.checkpoint()
    except LoopHalted:
        return None, None, "kill_switch"
    current_attempts = len(store.slot(slot.slot_id).get("attempts", []))
    council_id = _council_id(config, slot, provider, current_attempts + 1)
    transcript = mission_dir / f"{council_id}.jsonl"
    try:
        attempt_index = store.claim_call(slot.slot_id, provider, council_id, transcript)
    except ConfigError as exc:
        return None, None, f"max_calls:{exc}"

    model = "opus" if provider == "claude" else config.codex_model
    budget_outcome: _AskBudgetOutcome | None = None
    try:
        kill_switch.checkpoint()
        adapter = adapter_factory(
            provider, config, config.project(slot.project).repo_root
        )
        budget_outcome = _bind_budgeted_ask(
            adapter,
            provider=provider,
            model=model,
            label=(
                f"opus-fleet:{config.campaign_id}:{slot.slot_id}:{provider}"
            ),
            ledger=ledger,
            budget_guard_factory=budget_guard_factory,
            kill_switch=kill_switch,
            effect_timeout_s=config.timeout_s,
        )
        council_timeout_s = config.timeout_s + COUNCIL_CANCELLATION_MARGIN_S
        record = convene_fn(
            _question(slot),
            evidence,
            [adapter],
            rounds=1,
            council_id=council_id,
            store_path=transcript,
            roles=[slot.role],
            # Council waits past the adapter deadline so ManagedProcess can
            # finish its bounded cancellation ladder before locks/watchers are
            # released.  ``guarded_ask`` pins the actual vendor timeout back to
            # ``config.timeout_s``.
            per_call_timeout_s=council_timeout_s,
            wall_clock_s=council_timeout_s,
            token_ceiling=config.token_ceiling,
            live=config.live,
        )
    except LoopHalted:
        if budget_outcome is not None and budget_outcome.started:
            store.settle_call(
                slot.slot_id,
                attempt_index,
                status="unknown",
                reason="post_dispatch_loop_halted_without_council_record",
            )
            return None, None, "unknown_after_dispatch:LoopHalted"
        store.settle_call(
            slot.slot_id,
            attempt_index,
            status="cancelled_before_dispatch",
            reason="kill_switch",
        )
        return None, None, "kill_switch"
    except Exception as exc:
        if budget_outcome is not None and budget_outcome.started:
            store.settle_call(
                slot.slot_id,
                attempt_index,
                status="unknown",
                reason=f"post_dispatch_exception:{type(exc).__name__}",
            )
            return None, None, f"unknown_after_dispatch:{type(exc).__name__}"
        store.settle_call(
            slot.slot_id,
            attempt_index,
            status="error",
            reason=type(exc).__name__,
        )
        return None, None, f"dispatch_error:{type(exc).__name__}"

    # Council converts exceptions from its seat thread into chained unavailable
    # turns. Recover the typed stop/budget outcomes from side channels so state
    # does not mislabel them as generic vendor failures.
    assert budget_outcome is not None
    if budget_outcome.started and not budget_outcome.completed:
        store.settle_call(
            slot.slot_id,
            attempt_index,
            status="unknown",
            reason="adapter_still_running_after_council_terminal",
            record=_record_summary(record),
        )
        return None, None, "unknown_after_dispatch:adapter_incomplete"
    if budget_outcome.halted:
        store.settle_call(
            slot.slot_id,
            attempt_index,
            status="cancelled_before_dispatch",
            reason="kill_switch",
            record=_record_summary(record),
        )
        return None, None, "kill_switch"
    if budget_outcome.error is not None:
        store.settle_call(
            slot.slot_id,
            attempt_index,
            status="budget_refused",
            reason=type(budget_outcome.error).__name__,
            record=_record_summary(record),
        )
        return (
            None,
            None,
            f"budget_refused:{type(budget_outcome.error).__name__}",
        )

    summary = _record_summary(record)
    observation = _adapter_observation(adapter)
    succeeded = _record_succeeded(summary)
    reason = "" if succeeded else _record_failure_reason(summary)
    status = "completed" if succeeded else ("refused" if reason == "secret_floor" else "failed")
    store.settle_call(
        slot.slot_id,
        attempt_index,
        status=status,
        reason=reason,
        api_error_status=(observation.api_error_status if observation else None),
        record=summary,
    )
    return summary, observation, reason


def _dispatch_terminal_slot(
    *,
    provider: str,
    config: FleetConfig,
    slot: FleetSlot,
    expected_evidence_digest: str,
    mission_dir: Path,
    store: _StateStore,
    ledger: Ledger,
    adapter_factory: AdapterFactory,
    convene_fn: Convene,
    budget_guard_factory: BudgetGuardFactory,
    kill_switch: KillSwitch,
) -> str:
    try:
        kill_switch.checkpoint()
    except LoopHalted:
        return "kill_switch"
    # Claim in the worker, directly before its dispatch.  Queued futures are
    # not marked in_flight merely because a thread pool knows their names.
    store.claim_slot(slot.slot_id, provider)
    try:
        evidence = _build_evidence(config, slot)
    except (ConfigError, OSError) as exc:
        store.finish_slot(slot.slot_id, "failed", f"evidence_error:{type(exc).__name__}")
        return "failed"
    if evidence.digest != expected_evidence_digest:
        store.finish_slot(slot.slot_id, "suppressed", "evidence_changed_after_campaign_freeze")
        return "suppressed"
    summary, _observation, reason = _dispatch_call(
        provider=provider,
        config=config,
        slot=slot,
        evidence=evidence,
        mission_dir=mission_dir,
        store=store,
        ledger=ledger,
        adapter_factory=adapter_factory,
        convene_fn=convene_fn,
        budget_guard_factory=budget_guard_factory,
        kill_switch=kill_switch,
    )
    if reason.startswith("budget_refused") or reason.startswith("max_calls"):
        store.finish_slot(slot.slot_id, "budget_refused", reason)
    elif reason == "secret_floor":
        store.finish_slot(slot.slot_id, "refused", reason)
    elif summary is not None and _record_succeeded(summary):
        store.finish_slot(slot.slot_id, "completed")
    else:
        store.finish_slot(slot.slot_id, "failed", reason or "council_no_valid_voice")
    return reason or "completed"


def run_campaign(
    config_path: str | Path,
    *,
    planner: Callable[..., Mapping[str, Any]] | None = None,
    adapter_factory: AdapterFactory | None = None,
    convene_fn: Convene | None = None,
    runs_root: str | Path | None = None,
    budget_guard_factory: BudgetGuardFactory | None = None,
    kill_switch: KillSwitch | None = None,
    session_probe: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute or safely resume one bounded campaign.

    `campaign_id` is the re-arm token.  Terminal campaigns return their state
    without dispatching.  A restart with an abandoned call reconciles that call
    to `unknown` and suppresses all unclaimed work.
    """

    config = load_config(config_path)
    if config.live is not True:
        raise ConfigError("run_campaign requires explicit JSON live=true")
    slots = _plan(config, planner)
    mission_dir = _mission_dir(config, runs_root)
    adapter_factory = adapter_factory or _default_adapter_factory
    convene_fn = convene_fn or council_convene
    budget_guard_factory = budget_guard_factory or _default_budget_guard
    kill_switch = kill_switch or KillSwitch(repo_root=ROOT)

    # The outer lock is machine-global for this watchdog root, not campaign
    # local.  Two newly armed campaign IDs therefore cannot both observe an
    # idle machine and start in parallel.  It is an OS advisory lock released
    # by process death, not a PID/heartbeat claim that can lie after a crash.
    with _CampaignLock(mission_dir.parent / "opus-fleet-global.lock"):
        with _CampaignLock(mission_dir / "campaign.lock"):
            with kill_switch.watch():
                store = _StateStore(mission_dir / "state.json", config, slots)
                state = store.load_or_create()
                if state.get("status") in {"complete", "degraded"}:
                    return store.snapshot()
                if store.reconcile_stale():
                    return store.snapshot()

                session_observation = _session_observation(session_probe)
                store.record_session_check(session_observation)
                if (
                    not session_observation.ok
                    or session_observation.active_sessions > 0
                ):
                    return store.snapshot()

                # Only an idle machine freezes campaign evidence.  While a
                # human/Claude/Codex/Daedalus session is active this campaign
                # is merely waiting and selected context may still change.
                # Once clear, read one snapshot per project and bind every
                # project slot to that digest before the first provider claim.
                project_evidence: dict[str, Evidence] = {}
                for slot in slots:
                    if slot.project not in project_evidence:
                        project_evidence[slot.project] = _build_evidence(
                            config, slot
                        )
                evidences = {
                    slot.slot_id: project_evidence[slot.project] for slot in slots
                }
                store.freeze_evidence_digests(
                    {
                        slot_id: evidence.digest
                        for slot_id, evidence in evidences.items()
                    }
                )

                ledger = Ledger(
                    mission_dir / "budget.json",
                    ceiling_usd=config.max_spend_usd,
                    max_calls=config.max_calls,
                    period="total",
                )
                probe = slots[0]
                decision = str(
                    store.state.get("provider_decision") or "pending"
                )

                if decision == "pending":
                    try:
                        kill_switch.checkpoint()
                    except LoopHalted:
                        store.decision("stopped", "kill_switch_before_probe")
                        store.suppress_pending("kill_switch_before_probe")
                        return store.snapshot()
                    store.claim_slot(probe.slot_id, "claude")
                    expected = store.slot(probe.slot_id)["evidence_digest"]
                    evidence = evidences[probe.slot_id]
                    if evidence.digest != expected:
                        store.finish_probe_transition(
                            probe.slot_id,
                            status="suppressed",
                            slot_reason=(
                                "evidence_changed_after_campaign_freeze"
                            ),
                            provider_decision="stopped",
                            decision_reason="probe_evidence_changed",
                            suppress_reason="probe_evidence_changed",
                        )
                        return store.snapshot()
                    summary, wrapper_observation, reason = _dispatch_call(
                        provider="claude",
                        config=config,
                        slot=probe,
                        evidence=evidence,
                        mission_dir=mission_dir,
                        store=store,
                        ledger=ledger,
                        adapter_factory=adapter_factory,
                        convene_fn=convene_fn,
                        budget_guard_factory=budget_guard_factory,
                        kill_switch=kill_switch,
                    )
                    provider = fallback_provider(wrapper_observation)
                    if provider == "codex":
                        assert wrapper_observation is not None
                        store.decision(
                            "codex",
                            "typed_api_error_status:"
                            f"{wrapper_observation.api_error_status}",
                        )
                        fallback_summary, _unused, fallback_reason = _dispatch_call(
                            provider="codex",
                            config=config,
                            slot=probe,
                            evidence=evidence,
                            mission_dir=mission_dir,
                            store=store,
                            ledger=ledger,
                            adapter_factory=adapter_factory,
                            convene_fn=convene_fn,
                            budget_guard_factory=budget_guard_factory,
                            kill_switch=kill_switch,
                        )
                        if (
                            fallback_summary is not None
                            and _record_succeeded(fallback_summary)
                        ):
                            store.finish_probe_transition(
                                probe.slot_id,
                                status="completed",
                                slot_reason="",
                                provider_decision="codex",
                                decision_reason=(
                                    "typed_api_error_status:"
                                    f"{wrapper_observation.api_error_status}"
                                ),
                            )
                        else:
                            terminal = (
                                "budget_refused"
                                if fallback_reason.startswith(
                                    ("budget_refused", "max_calls")
                                )
                                else "failed"
                            )
                            store.finish_probe_transition(
                                probe.slot_id,
                                status=terminal,
                                slot_reason=fallback_reason,
                                provider_decision="stopped",
                                decision_reason="codex_probe_failed",
                                suppress_reason="codex_probe_failed",
                            )
                            return store.snapshot()
                    elif summary is not None and _record_succeeded(summary):
                        store.finish_probe_transition(
                            probe.slot_id,
                            status="completed",
                            slot_reason="",
                            provider_decision="claude",
                            decision_reason="claude_probe_succeeded",
                        )
                    else:
                        terminal = (
                            "budget_refused"
                            if reason.startswith(("budget_refused", "max_calls"))
                            else ("refused" if reason == "secret_floor" else "failed")
                        )
                        store.finish_probe_transition(
                            probe.slot_id,
                            status=terminal,
                            slot_reason=reason or "claude_probe_failed",
                            provider_decision="stopped",
                            decision_reason=(
                                "claude_probe_failed_without_typed_fallback"
                            ),
                            suppress_reason=(
                                "claude_probe_failed_without_typed_fallback"
                            ),
                        )
                        return store.snapshot()
                elif decision not in {"claude", "codex"}:
                    store.suppress_pending("provider_decision_stopped")
                    return store.snapshot()

                provider = str(store.state["provider_decision"])
                pending = [
                    slot
                    for slot in slots
                    if store.slot(slot.slot_id).get("status") == "pending"
                ]
                killed = False
                if pending:
                    # The first gate protects campaign entry.  Probe again at
                    # the fan-out boundary: another interactive Claude/Codex/
                    # Daedalus session may have appeared while the synchronous
                    # provider probe was running.  Busy/could-not-tell leaves
                    # work pending and retains the frozen provider decision;
                    # the next 20-minute tick resumes without another Claude
                    # probe.
                    fanout_observation = _session_observation(session_probe)
                    store.record_session_check(fanout_observation)
                    if (
                        not fanout_observation.ok
                        or fanout_observation.active_sessions > 0
                    ):
                        return store.snapshot()
                    with ThreadPoolExecutor(
                        max_workers=config.max_parallel,
                        thread_name_prefix="opus-fleet-advisory",
                    ) as pool:
                        futures = {}
                        for slot in pending:
                            expected = store.slot(slot.slot_id)[
                                "evidence_digest"
                            ]
                            future = pool.submit(
                                _dispatch_terminal_slot,
                                provider=provider,
                                config=config,
                                slot=slot,
                                expected_evidence_digest=expected,
                                mission_dir=mission_dir,
                                store=store,
                                ledger=ledger,
                                adapter_factory=adapter_factory,
                                convene_fn=convene_fn,
                                budget_guard_factory=budget_guard_factory,
                                kill_switch=kill_switch,
                            )
                            futures[future] = slot.slot_id
                        for future in as_completed(futures):
                            # BaseException is deliberately not caught here: a
                            # process abort leaves the durable claim unknown.
                            killed = future.result() == "kill_switch" or killed
                if killed:
                    store.decision("stopped", "kill_switch")
                    store.suppress_pending("kill_switch")
                return store.snapshot()


def campaign_status(
    config_path: str | Path, *, runs_root: str | Path | None = None
) -> dict[str, Any]:
    """Read operational state only; never runs the planner or a vendor."""

    config = load_config(config_path)
    mission_dir = _mission_dir(config, runs_root)
    state_path = mission_dir / "state.json"
    if not state_path.exists():
        return {
            "schema": STATE_SCHEMA,
            "campaign_id": config.campaign_id,
            "status": "not_started",
            "mission_dir": str(mission_dir),
        }
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignCorrupt(f"cannot read campaign state: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
        raise CampaignCorrupt("campaign state schema is missing or unsupported")
    if state.get("campaign_id") != config.campaign_id:
        raise CampaignCorrupt("campaign state belongs to a different campaign")
    if state.get("config_digest") != config.digest:
        raise CampaignCorrupt("campaign config changed; use a new campaign_id")
    return state
