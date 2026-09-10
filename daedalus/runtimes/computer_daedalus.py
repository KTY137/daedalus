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

WHAT THEY DO ON THE HOST. Nothing is written, moved, launched or sent by this
module: the structcore index is built ``effect_free`` (no SQLite cache write
or eviction under the profile, no process pool, no churn ``git log``), and
the status reader runs the repository's read-only ``git branch`` / ``git
status`` exactly as the dashboard does. The service records every result
with ``host_mutation`` False and scope ``project-registry-read-only``.

WHAT THEY SEND. Every observation is the planner's prompt, so with a remote
planner it leaves the machine. That is why EVERY observation, not only the
slice, passes the project's egress gate before it is returned: each path
and each text fragment goes through ``sensitivity.slice_egress_rule`` on the
planner's lane -- the unconditional secret floor on every lane, plus the
project's default-deny allow-list and ``deny_content`` words (from
``projects/<name>.json``) on the untrusted lane. Withheld rows are counted,
never silently dropped. No absolute host path is returned by shape
(``_looks_like_host_path``), and ``docrefs`` scanner errors are reported as a
count only. Cerberus review of 2026-09-10 found the first draft gating the
slice alone; this is the repair.

The lane is decided per call by :func:`planner_lane` from the owner-configured
planner: a loopback Ollama or the Claude CLI is ``trusted`` (the same answer
the chat gives in ``shell._llm``); Codex and DeepSeek are ``untrusted``.
``allow_remote_context`` never promotes a destination. The observations read
the REGISTERED project (``projects/<name>.json``) that the conversation
selected; a session without a bound project cannot execute them, an unknown
project is a refusal, and a project whose policy row cannot be loaded is a
refusal too -- never the generic policy.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, DAEDALUS_TOOLS


@dataclass(frozen=True)
class ProjectReaders:
    """The three project readers the service hands in.

    ``daedalus.status`` (git counters, queue) and ``daedalus.file_bridge``
    (report briefs) already sit inside the repository's largest import cycle
    with ``runtimes.computer``; importing them here would pull this adapter
    into that cycle (MEASURED 2026-09-10 by the SCC census: 19 -> 21 modules).
    The orchestration layer, which is in the cycle already, supplies them;
    this module names no orchestration, bridge or status module.
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


#: An absolute host path EMBEDDED in longer text (an error message, a task
#: summary): a drive spelling, a UNC prefix, or a POSIX home/system root.
#: Odysseus 2026-09-10 (defect 3): the whole-value check above let
#: ``"…: PermissionError: 'C:\\Users\\…'"`` through.
_EMBEDDED_HOST_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\s\\]+\\|(?:^|[\s'\"(])/(?:home|Users|root|tmp|var|etc|mnt|opt|srv)/")


def _mentions_host_path(text: str) -> bool:
    return bool(_EMBEDDED_HOST_PATH.search(text or ""))


def _bounded_text(value: object, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so the observation is exactly what is retained."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


def _status_line_paths(line: str) -> list[str]:
    """The path(s) named by one ``git status --short`` line (renames name two)."""
    body = line[3:] if len(line) > 3 else line
    body = body.strip()
    if " -> " in body:
        return [part.strip() for part in body.split(" -> ") if part.strip()]
    return [body] if body else []


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
        self._index: dict | None = None
        self._egress_policy = None

    # ------------------------------------------------------------------ project
    @property
    def project(self) -> str | None:
        return self._project

    @property
    def lane(self) -> str:
        """Re-derived on every read: an ``OLLAMA_HOST`` that stops being
        loopback mid-task must not keep a stale ``trusted`` verdict (Cerberus m-2)."""
        return planner_lane(self._policy)

    def _repo_root(self) -> str:
        if self._project is None:
            raise ComputerRefused("computer session has no registered project; run it from a project conversation")
        from daedalus.foundation.projects import resolve_repo_root
        try:
            return resolve_repo_root(None, self._project)
        except Exception as exc:  # unknown row, unreadable registry, unsafe root
            raise ComputerRefused(f"project is not registered or unreadable: {type(exc).__name__}: {exc}") from exc

    def _project_policy(self):
        """The project's egress policy -- refused, never the generic one, when
        the registry row cannot be read (Cerberus m-4)."""
        if self._egress_policy is None:
            from daedalus.foundation.projects import load_project
            from daedalus.sensitivity import load_policy
            try:
                config = load_project(self._project or "")
            except Exception as exc:
                raise ComputerRefused(f"project policy is unavailable: {type(exc).__name__}: {exc}") from exc
            self._egress_policy = load_policy(config)
        return self._egress_policy

    # ------------------------------------------------------------------ egress gate
    def _admit(self, path: str, text: str = "") -> bool:
        """May this path/text reach the planner on the current lane?

        The Voice's own gate, ``sensitivity.slice_egress_rule``: the secret
        floor on every lane; the project's default-deny allow-list and
        ``deny_content`` words on the untrusted lane. Called per row, so one
        withheld row is attributable and never poisons the observation.
        """
        from daedalus.sensitivity import slice_egress_rule
        if _looks_like_host_path(path) or _mentions_host_path(text):
            return False
        return slice_egress_rule(path, text, lane=self.lane, policy=self._project_policy()) is None

    def _admit_text(self, text: str) -> bool:
        """May this path-less text (a clone name, a report summary) reach the planner?

        The secret floor on every lane; on the untrusted lane additionally the
        project's ``deny_content`` markers, exactly the content half of
        ``sensitivity.classify_data`` (the allow-list half needs a path and
        would refuse every synthetic name).
        """
        from daedalus.sensitivity import secret_floor_rule
        if _mentions_host_path(text) or secret_floor_rule("observation.txt", text):
            return False
        if self.lane != "trusted":
            policy = self._project_policy()
            if any(pattern.search(text) for pattern in policy.deny_content):
                return False
        return True

    def _admit_rows(self, rows: Iterable[Mapping[str, Any]], path_keys: tuple[str, ...],
                    text_keys: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], int]:
        """Keep the rows whose named paths and texts the gate admits; count the rest."""
        kept: list[dict[str, Any]] = []
        withheld = 0
        for row in rows:
            if not isinstance(row, Mapping):
                withheld += 1
                continue
            paths = [str(row[key]) for key in path_keys if isinstance(row.get(key), str) and row.get(key)]
            text = " ".join(str(row[key]) for key in text_keys if isinstance(row.get(key), str))
            if (paths and not all(self._admit(path, text) for path in paths)) or (
                    not paths and text and not self._admit_text(text)):
                withheld += 1
                continue
            kept.append(dict(row))
        return kept, withheld

    def _cached_index(self, repo_root: str) -> dict:
        if self._index is None:
            from daedalus.structcore.index import cached_index
            self._checkpoint()
            # effect_free: no persistent cache write or eviction under the
            # profile, no process pool, no churn ``git log`` (Cerberus MAJOR 1).
            self._index = cached_index(repo_root, effect_free=True)
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
        result.setdefault("lane", self.lane)
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
        observed: dict[str, Any] = {}
        withheld_paths = 0
        withheld_fields = 0
        for key, value in git.items():
            if key == "repo_root":
                continue
            if key == "git_status" and isinstance(value, str):
                # Every line names a repository path: each goes through the
                # project's gate (``?? .env`` is floored on every lane; a
                # ``policy.deny`` path is withheld on the untrusted lane).
                kept_lines = []
                for line in value.splitlines():
                    paths = _status_line_paths(line)
                    if paths and all(self._admit(path, line) for path in paths):
                        kept_lines.append(line)
                    elif paths:
                        withheld_paths += 1
                observed[key] = "\n".join(kept_lines)
                continue
            if isinstance(value, str):
                if _looks_like_host_path(value) or not self._admit(f"{key}.txt", value):
                    withheld_fields += 1
                    continue
            observed[key] = value
        observed["git_status_withheld"] = withheld_paths
        observed["fields_withheld"] = withheld_fields
        return {"git": observed, "queue": queue, "registered": True}

    def _structure(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.report import structure_summary
        idx = self._cached_index(repo_root)
        summary = structure_summary(idx, top_hotspots=TOP * 2, top_clones=TOP * 2, top_windows=0,
                                    top_fanin=TOP * 2, top_renamed=0, top_near=0,
                                    max_graph_nodes=0, max_graph_edges=0)
        ignored = summary.get("ignored") if isinstance(summary.get("ignored"), dict) else {}
        hotspots, hotspots_withheld = self._admit_rows(summary.get("hotspots", []), ("module",))
        fan_in, fan_in_withheld = self._admit_rows(summary.get("fan_in", []), ("module",))
        clones: list[dict[str, Any]] = []
        clones_withheld = 0
        for row in summary.get("clones", []):
            if not isinstance(row, Mapping) or not self._admit_text(str(row.get("name", ""))):
                clones_withheld += 1
                continue
            sites, sites_withheld = self._admit_rows(row.get("sites", []), ("module",))
            if not sites:
                clones_withheld += 1
                continue
            clones.append({**dict(row), "sites": sites, "sites_withheld": sites_withheld})
        # ``ignored.source`` is the absolute path of the ignore file (MEASURED
        # 2026-09-10, live run 3): only the count and the patterns are observed.
        return {"n_files": summary.get("n_files"),
                "ignored": {"count": ignored.get("count", 0), "patterns": list(ignored.get("patterns") or [])[:TOP]},
                "languages": summary.get("languages"), "totals": summary.get("totals"),
                "hotspots": hotspots[:TOP], "hotspots_withheld": hotspots_withheld,
                "clones": clones[:TOP], "clones_withheld": clones_withheld,
                "fan_in": fan_in[:TOP], "fan_in_withheld": fan_in_withheld,
                "churn": "not measured (effect-free index)"}

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
        lane = self.lane
        result = semantic_slice(repo_root, target, idx=idx, lane=lane,
                                policy=self._project_policy(), max_tokens=SLICE_MAX_TOKENS)
        text, elided = _bounded_text(result.get("slice_text", ""))
        withheld = result.get("withheld") or []
        rows = [dict(row) for row in withheld] if isinstance(withheld, list) else []
        return {"focus_file": result.get("focus_file"), "lane": lane,
                "slice_tokens": result.get("slice_tokens"), "n_included": result.get("n_included"),
                "trimmed_count": result.get("trimmed_count", 0),
                "withheld": rows[:TOP], "withheld_elided": max(0, len(rows) - TOP),
                "text": text, "text_elided": elided}

    def _docrefs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.spine import docrefs
        report = docrefs.scan(repo_root)
        self._checkpoint()
        payload = report.to_dict()
        broken, withheld = self._admit_rows(payload.get("broken", []),
                                            ("doc_path", "module_path"), ("raw", "symbol"))
        # Scanner error strings carry the absolute path of the unreadable file
        # (Cerberus MAJOR 2): only their number is observed.
        return {"n_resolving": payload.get("n_resolving"), "n_broken": payload.get("n_broken"),
                "n_skipped": payload.get("n_skipped"), "files_scanned": payload.get("files_scanned"),
                "broken": broken[:TOP], "broken_elided": max(0, len(broken) - TOP),
                "broken_withheld": withheld,
                "errors_count": len(payload.get("errors", []))}

    def _tasks(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self._repo_root()  # a task list is still scoped to a registered project
        # Computer-mission history lives in ``orchestration.ikarus.computer_history``;
        # reading it from a runtime adapter would close a runtimes<->orchestration
        # import cycle (see ProjectReaders), so this observation stays with the
        # file-bridge reports. The chat's ``/computer tasks`` remains the door to
        # mission history.
        briefs = list(self._readers.report_briefs(self._project))[-TOP:]
        reports, withheld = self._admit_rows(
            briefs, (), ("summary", "name", "agent", "provider", "lane", "project"))
        return {"reports": reports, "reports_withheld": withheld,
                "computer_missions": "use /computer tasks in the chat"}
