"""Read-only Daedalus observations for the Ikarus computer loop (G1-IKARUS-46).

Until this module existed the computer loop could observe a workspace, a
browser origin and a desktop window, but not the project the chat is bound
to: the assistant that is supposed to run Daedalus had no tool that looked at
Daedalus. These five observations close that gap without opening an effect:

* ``daedalus.status``     -- the registered project's git counters and the
                            file-bridge queue/watcher facts;
* ``daedalus.structure``  -- the structcore summary (hotspots, clone
                            clusters, fan-in) of the project;
* ``daedalus.slice``      -- the distilled semantic slice of one module,
                            through the SAME egress gate the Voice uses;
* ``daedalus.docrefs``    -- documentation references the repository's own
                            resolver calls broken (``spine.docrefs``);
* ``daedalus.tasks``      -- recent file-bridge reports of the project.

Every observation is bounded, JSON-only and mutates nothing on the host: no
write, no move, no launch, no network. The service records them with
``host_mutation`` False and scope ``project-registry-read-only``. They read
the REGISTERED project (``projects/<name>.json``) that the conversation
selected; a session without a bound project cannot execute them, and an
unknown project is a refusal, never a guess.

Egress is decided once, by :func:`planner_lane`, from the owner-configured
planner: a loopback Ollama or the Claude CLI is the ``trusted`` lane (same
answer the chat gives in ``shell._llm``); Codex and DeepSeek are
``untrusted`` and receive the slice only through the project's default-deny
allow-list. The unconditional secret floor runs in every lane inside
``semantic_slice`` and again over every result in ``ComputerService.execute``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from dataclasses import dataclass

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, DAEDALUS_TOOLS


@dataclass(frozen=True)
class ProjectReaders:
    """The three project readers the service hands in.

    ``daedalus.status`` (git counters, queue) and ``daedalus.file_bridge``
    (report briefs) already sit inside the repository's largest import cycle
    with ``runtimes.computer``; importing them here would pull this adapter
    into that cycle (MEASURED 2026-09-10 by the SCC census: 19 -> 21 modules).
    The service, which is in the cycle already, supplies them; this module
    names no orchestration, bridge or status module.
    """

    git_counters: Callable[[str], Mapping[str, Any]]
    bridge_status: Callable[[str | None], Mapping[str, Any]]
    report_briefs: Callable[[str | None], list]


#: Neighbourhood budget for one slice observation. Smaller than the Voice's
#: 12k because the loop keeps every observation in its prompt history.
SLICE_MAX_TOKENS = 6000
#: Hard cap on any text field that reaches the planner through an observation.
MAX_TEXT_CHARS = 24_000
#: Rows per list in structure/docrefs/tasks observations.
TOP = 10
#: git counters are read with this timeout; a hung git is a refusal, not a wait.
GIT_TIMEOUT_S = 15.0
_TRUSTED_PLANNERS = frozenset({"claude_code_cli"})
_LOCAL_PLANNERS = frozenset({"ollama_http", "ollama"})


def planner_lane(policy: ComputerPolicy) -> str:
    """The egress lane of the configured planner: ``trusted`` or ``untrusted``.

    A local Ollama is trusted only when ``OLLAMA_HOST`` really is this machine
    (``sensitivity.lane_for_host``, the one implementation of that question);
    the Claude CLI is trusted-with-IP exactly as in ``shell._llm``; every other
    planner is untrusted. ``allow_remote_context`` does not widen this: it
    admits that observations leave the machine, it does not promote the
    destination to a trusted one.
    """
    provider = policy.planner_provider
    if provider in _LOCAL_PLANNERS:
        from daedalus.providers.ollama import DEFAULT_HOST
        from daedalus.sensitivity import lane_for_host
        # The raw OLLAMA_HOST value, exactly as ``shell._local_lane`` passes
        # it: the predicate owns the wire grammar (``[::1]`` included).
        return lane_for_host(os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    if provider in _TRUSTED_PLANNERS:
        return "trusted"
    return "untrusted"


def _looks_like_host_path(value: str) -> bool:
    """An absolute Windows or POSIX path (``C:\\…``, ``\\\\server``, ``/home/…``)."""
    text = value.strip()
    if not text:
        return False
    if os.path.isabs(text):
        return True
    # ``os.path.isabs`` is host-specific; the observation must not depend on
    # which host renders it, so both spellings are refused everywhere.
    return bool(len(text) > 2 and text[1] == ":" and text[2] in "\\/") or text.startswith(("\\\\", "/"))


def _bounded_text(value: object, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so the observation is exactly what is retained."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


class DaedalusObservation:
    """The five read-only project observations behind one dispatch seam."""

    def __init__(self, policy: ComputerPolicy, project: str | None,
                 checkpoint: Callable[[], None], authority_root: Path,
                 readers: ProjectReaders) -> None:
        if project is not None and (not isinstance(project, str) or not project.strip()):
            raise ComputerRefused("computer session project must be a non-empty name")
        if not isinstance(readers, ProjectReaders):
            raise ComputerRefused("project readers must be supplied by the computer service")
        self._readers = readers
        self._policy = policy
        self._project = project.strip() if isinstance(project, str) else None
        self._checkpoint = checkpoint
        self._authority_root = Path(authority_root)
        self._lane = planner_lane(policy)
        self._index: dict | None = None

    # ------------------------------------------------------------------ project
    @property
    def project(self) -> str | None:
        return self._project

    @property
    def lane(self) -> str:
        return self._lane

    def _repo_root(self) -> str:
        if self._project is None:
            raise ComputerRefused("computer session has no registered project; run it from a project conversation")
        from daedalus.foundation.projects import resolve_repo_root
        try:
            return resolve_repo_root(None, self._project)
        except Exception as exc:  # unknown row, unreadable registry, unsafe root
            raise ComputerRefused(f"project is not registered or unreadable: {type(exc).__name__}: {exc}") from exc

    def _project_policy(self):
        from daedalus.foundation.projects import load_project
        from daedalus.sensitivity import load_policy
        try:
            config = load_project(self._project or "")
        except Exception:
            config = None
        return load_policy(config)

    def _cached_index(self, repo_root: str) -> dict:
        if self._index is None:
            from daedalus.structcore.index import cached_index
            self._checkpoint()
            self._index = cached_index(repo_root)
            self._checkpoint()
        return self._index

    # ------------------------------------------------------------------ dispatch
    def execute(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool not in DAEDALUS_TOOLS:
            raise ComputerRefused("unknown Daedalus observation")
        if type(arguments) is not dict:
            raise ComputerRefused("tool arguments must be an object")
        self._checkpoint()
        handler = {
            "daedalus.status": self._status,
            "daedalus.structure": self._structure,
            "daedalus.slice": self._slice,
            "daedalus.docrefs": self._docrefs,
            "daedalus.tasks": self._tasks,
        }[tool]
        result = handler(arguments)
        result.setdefault("kind", "observation")
        result.setdefault("project", self._project)
        result.setdefault("host_mutation", False)
        return _json_safe(result)

    # ------------------------------------------------------------------ tools
    def _status(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        git = dict(self._readers.git_counters(repo_root))
        self._checkpoint()
        bridge = dict(self._readers.bridge_status(self._project))
        queue = {key: bridge.get(key) for key in (
            "queue_depth", "in_flight", "unread_count", "reports_total")}
        watcher = bridge.get("watcher") if isinstance(bridge.get("watcher"), dict) else {}
        queue["watcher"] = watcher.get("state", "unknown")
        # Host paths never reach the planner: the registry row is the
        # projection, the absolute path is not part of the observation.
        # MEASURED 2026-09-10 (live run 3): ``collect_status`` also carries
        # ``todo_snapshot``, an absolute path; every absolute-path value is
        # dropped by shape, not by name, so a later counter cannot leak one.
        return {"git": {k: v for k, v in git.items()
                        if k != "repo_root" and not (isinstance(v, str) and _looks_like_host_path(v))},
                "queue": queue, "registered": True}

    def _structure(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.report import structure_summary
        idx = self._cached_index(repo_root)
        summary = structure_summary(idx, top_hotspots=TOP, top_clones=TOP, top_windows=0,
                                    top_fanin=TOP, top_renamed=0, top_near=0,
                                    max_graph_nodes=0, max_graph_edges=0)
        ignored = summary.get("ignored") if isinstance(summary.get("ignored"), dict) else {}
        # ``ignored.source`` is the absolute path of the ignore file (MEASURED
        # 2026-09-10, live run 3): only the count and the patterns are observed.
        return {"n_files": summary.get("n_files"),
                "ignored": {"count": ignored.get("count", 0), "patterns": list(ignored.get("patterns") or [])[:TOP]},
                "languages": summary.get("languages"), "totals": summary.get("totals"),
                "hotspots": summary.get("hotspots", [])[:TOP],
                "clones": summary.get("clones", [])[:TOP],
                "fan_in": summary.get("fan_in", [])[:TOP]}

    def _resolve_module(self, idx: dict, module: object) -> str:
        if not isinstance(module, str) or not module.strip() or len(module) > 1000 or "\x00" in module:
            raise ComputerRefused("module must be a bounded repository-relative path")
        token = module.strip().replace("\\", "/")
        modules = idx.get("modules", {})
        if token in modules:
            return token
        hits = sorted(m for m in modules if m == token or m.endswith("/" + token))
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ComputerRefused("module is ambiguous; name one of: " + ", ".join(hits[:TOP]))
        raise ComputerRefused("module is not in the project's index; name an indexed source file")

    def _slice(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.slice import semantic_slice
        idx = self._cached_index(repo_root)
        # The index decides what a module is, so no path shape can escape the
        # indexed source set: traversal, absolute paths and unknown files are
        # all "not in the index".
        target = self._resolve_module(idx, arguments.get("module"))
        self._checkpoint()
        result = semantic_slice(repo_root, target, idx=idx, lane=self._lane,
                                policy=self._project_policy(), max_tokens=SLICE_MAX_TOKENS)
        text, elided = _bounded_text(result.get("slice_text", ""))
        withheld = result.get("withheld") or []
        return {"focus_file": result.get("focus_file"), "lane": self._lane,
                "slice_tokens": result.get("slice_tokens"), "n_included": result.get("n_included"),
                "trimmed_count": result.get("trimmed_count", 0),
                "withheld": [dict(row) for row in withheld][:TOP] if isinstance(withheld, list) else withheld,
                "text": text, "text_elided": elided}

    def _docrefs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.spine import docrefs
        report = docrefs.scan(repo_root)
        self._checkpoint()
        payload = report.to_dict()
        broken = payload.get("broken", [])
        return {"n_resolving": payload.get("n_resolving"), "n_broken": payload.get("n_broken"),
                "n_skipped": payload.get("n_skipped"), "files_scanned": payload.get("files_scanned"),
                "broken": broken[:TOP], "broken_elided": max(0, len(broken) - TOP),
                "errors": list(payload.get("errors", []))[:TOP]}

    def _tasks(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self._repo_root()  # a task list is still scoped to a registered project
        # Computer-mission history lives in ``orchestration.ikarus.computer_history``;
        # reading it from a runtime adapter would close a runtimes<->orchestration
        # import cycle (see ProjectReaders), so this observation stays with the
        # file-bridge reports. The chat's ``/computer tasks`` remains the door to
        # mission history.
        briefs = list(self._readers.report_briefs(self._project))[-TOP:]
        return {"reports": briefs, "computer_missions": "use /computer tasks in the chat"}
