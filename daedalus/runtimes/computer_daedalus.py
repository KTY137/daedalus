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

WHAT THEY DO ON THE HOST. Nothing in the workspace or the project tree is
written, moved, launched or sent by this module: the structcore index is
built ``effect_free`` (no SQLite cache write or eviction under the profile,
no process pool, no churn ``git log``), and the status reader runs the
repository's ``git branch`` / ``git status`` exactly as the dashboard does --
read-only commands, though ``git status`` may refresh git's own index file
(Cerberus N8). The service records every result with ``host_mutation``
False and scope ``project-registry-read-only``.

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


def planner_host(policy: ComputerPolicy) -> str | None:
    """The address a LOCAL planner connects to -- the raw ``OLLAMA_HOST`` value,
    exactly as ``shell._local_lane`` passes it, so the predicates own the wire
    grammar (``[::1]`` included). ``None`` for every other planner."""
    if policy.planner_provider in _LOCAL_PLANNERS:
        from daedalus.providers.ollama import DEFAULT_HOST
        return os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    return None


def planner_lane(policy: ComputerPolicy) -> str:
    """The egress lane of the configured planner: ``trusted`` or ``untrusted``.

    A local Ollama is trusted only when ``OLLAMA_HOST`` is this machine or an
    address the owner declared in ``DAEDALUS_TRUSTED_HOSTS``
    (``sensitivity.lane_for_host``, the one implementation of that question);
    the Claude CLI is trusted-with-IP exactly as in ``shell._llm``; every other
    planner is untrusted. ``allow_remote_context`` does not widen this: it
    admits that observations leave the machine, it does not promote the
    destination to a trusted one. The lane answers CONSENT (which filter
    applies); whether bytes cross a wire is :func:`planner_leaves_machine`.
    """
    host = planner_host(policy)
    if host is not None:
        from daedalus.sensitivity import lane_for_host
        return lane_for_host(host)
    if policy.planner_provider in _TRUSTED_PLANNERS:
        return "trusted"
    return "untrusted"


def planner_leaves_machine(policy: ComputerPolicy) -> bool:
    """Whether an observation handed to the planner crosses a wire -- physics,
    not consent. Cerberus round 4 (H3): an owner's ``DAEDALUS_TRUSTED_HOSTS``
    entry makes a tailnet bench a TRUSTED lane (only the secret floor filters),
    and the grant then said "nothing leaves this machine" while packets crossed
    the tunnel. ``sensitivity.is_loopback_host`` cannot be widened by any
    declaration; a remote vendor planner always leaves."""
    host = planner_host(policy)
    if host is None:
        return True
    from daedalus.sensitivity import is_loopback_host
    return not is_loopback_host(host)


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
#: Odysseus round 2 (D3) widened this from a root-name list to the SHAPES of
#: an absolute location: a drive (``C:\``, ``C:/``), a UNC in either slash
#: direction (``\\nas\``, ``//nas/``), a ``file://`` URL, ``~/``, an expanded
#: environment root (``%USERPROFILE%\``, ``${HOME}/``, ``$env:X\``), a
#: scheme'd host URL (``file://``, ``smb://``, ``https://`` -- withheld, the
#: safe direction for a text that names a host), or any POSIX absolute path
#: (``/usr/lib/x``, ``/proc/self/environ``, a bare ``/etc``). A repository-
#: relative spelling such as ``pkg/mod.py``, ``docs/a.md -> docs/b.md`` or
#: ``50/50`` has no leading separator and is not matched; a root-anchored
#: markdown link (``](/docs/x.md)``) is, and lands in the withheld count.
_EMBEDDED_HOST_PATH = re.compile(
    r"[A-Za-z]:[\\/]"                           # drive, anywhere (``checkoutC:\`` included; Odysseus round 3)
    r"|(?<![A-Za-z0-9])[A-Z]:[A-Za-z_.]"        # drive-relative (``C:temp\x``; Cerberus round 3)
    r"|\\\\[^\s\\]+"                            # UNC host, with or without a share
    r"|(?<![A-Za-z0-9:])//[^\s/]+/"            # UNC, forward slashes
    r"|\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/]+/"    # any scheme'd host URL (file://, smb://, https://): a host is named
    r"|(?<![A-Za-z0-9])~[^\s/\\]*[\\/]"         # home shorthand, ``~/`` or ``~user/``
    r"|%[A-Za-z_][A-Za-z0-9_]*%[\\/]"           # expanded Windows environment root
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?[\\/]"     # expanded POSIX environment root, ``$HOME/`` or ``${HOME}/``
    r"|\$env:[A-Za-z_][A-Za-z0-9_]*[\\/]"       # PowerShell environment root
    r"|(?:^|[\s'\"(=<>\[,;:])/[^\s/\\'\"()<>\[\],;:]+(?=[\\/\s'\")\]>,;:]|$)"  # POSIX absolute path, any first segment
)


def _mentions_host_path(text: str) -> bool:
    return bool(_EMBEDDED_HOST_PATH.search(text or ""))


#: The slicer's withheld block header; the block is kept LAST in the slice
#: text and every line after it is a per-file breadcrumb ``# <file>  (<rule>)
#: [<role>]`` (structcore/slice.py). Both name what the project withholds, so
#: the block is REBUILT from the gated rows -- no file-name grammar (spaces,
#: CRLF) can slip a name past a regex (Odysseus round 4, D12).
_WITHHELD_HEADER = "# ===== WITHHELD (egress gate) ====="
_TRIMMED_MARKER = "# ===== CONTEXT TRIMMED"
#: Every rule string the gate returns quotes what it fired on: ``<path>:
#: denylisted path fragment '<fragment>'``, ``<path>: path not on the external
#: allow-list (default-deny)``, ``content matches sensitive marker
#: /<pattern>/``, ``secret path marker '<fragment>'``, ``secret content:
#: <label>`` (sensitivity.py). The withheld path, the project's own deny
#: fragment and the marker word are exactly what must not travel (Odysseus
#: round 4, D9: the round-3 redaction knew one of the five shapes). Only a
#: fixed class leaves; the rule text never does.
_RULE_CLASSES = (("secret path marker", "secret_path"), ("secret content", "secret_content"),
                 ("denylisted path fragment", "denylisted_path"), ("default-deny", "default_deny"),
                 ("sensitive marker", "deny_content"))


def _rule_class(rule: object) -> str:
    text = str(rule)
    for needle, label in _RULE_CLASSES:
        if needle in text:
            return label
    return "egress_rule"


def _strings_in(value: Any) -> list[str]:
    """Every string a value hands on once ``_json_safe`` serialises it: nested
    lists, tuples, sets, dict KEYS and values, bytes, and the ``str()`` of any
    other object -- a ``Path``, an exception -- because ``default=str`` renders
    exactly that. Odysseus round 4 (D4/D10/D11): the round-3 flattener knew str,
    list, tuple and Mapping values; a set, a Path and a dict key carried a host
    path past it."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, bytes):
        return _strings_in(value.decode("utf-8", "replace"))
    if isinstance(value, Mapping):
        return [text for key, item in value.items() for text in _strings_in(key) + _strings_in(item)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [text for item in value for text in _strings_in(item)]
    if value is None or isinstance(value, (bool, int, float)):
        return []
    return _strings_in(str(value))


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
        """The project's egress policy, re-read on every call -- refused, never
        the generic one, when the registry row cannot be read (Cerberus m-4);
        never memoised, so a row tightened mid-mission takes effect (N5)."""
        from daedalus.foundation.projects import load_project
        from daedalus.sensitivity import load_policy
        try:
            config = load_project(self._project or "")
        except Exception as exc:
            raise ComputerRefused(f"project policy is unavailable: {type(exc).__name__}: {exc}") from exc
        return load_policy(config)

    # ------------------------------------------------------------------ egress gate
    def _admit(self, path: str, text: str = "") -> bool:
        """May this path/text reach the planner on the current lane?

        The Voice's own gate, ``sensitivity.slice_egress_rule``: the secret
        floor on every lane; the project's default-deny allow-list and
        ``deny_content`` words on the untrusted lane. Called per row, so one
        withheld row is attributable and never poisons the observation.
        """
        from daedalus.sensitivity import slice_egress_rule
        if _looks_like_host_path(path) or _mentions_host_path(text) or _mentions_host_path(path):
            return False
        # The path itself is also content: ``classify_data`` applies the
        # project's ``deny_content`` markers to the TEXT argument only, so a
        # codename inside an allow-listed path would pass without this
        # (Odysseus round 2, D2).
        return slice_egress_rule(path, f"{path} {text}".strip(), lane=self.lane,
                                 policy=self._project_policy()) is None

    def _admit_text(self, text: str) -> bool:
        """May this path-less text (a clone name, a report summary) reach the planner?

        The secret floor on every lane; on the untrusted lane additionally the
        project's ``deny_content`` markers, exactly the content half of
        ``sensitivity.classify_data`` (the allow-list half needs a path and
        would refuse every synthetic name).
        """
        from daedalus.sensitivity import secret_floor_rule
        if _looks_like_host_path(text) or _mentions_host_path(text) or secret_floor_rule("observation.txt", text):
            return False
        if self.lane != "trusted":
            policy = self._project_policy()
            if any(pattern.search(text) for pattern in policy.deny_content):
                return False
        return True

    def _admit_rows(self, rows: Iterable[Mapping[str, Any]], path_keys: tuple[str, ...],
                    text_keys: tuple[str, ...] = (), *,
                    keep_keys: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], int]:
        """Keep the rows whose named paths and texts the gate admits; count the rest.

        Fail-closed: a row that names neither a path nor a text is withheld,
        not passed ungated (Cerberus N3). ``keep_keys`` projects each kept row
        to an allow-listed key set, so a field a producer adds later cannot
        join the planner's prompt silently (N4).
        """
        kept: list[dict[str, Any]] = []
        withheld = 0
        for row in rows:
            if not isinstance(row, Mapping):
                withheld += 1
                continue
            projected = {key: row[key] for key in keep_keys if key in row} if keep_keys else dict(row)
            paths = [str(row[key]) for key in path_keys if isinstance(row.get(key), str) and row.get(key)]
            # EVERY string that will be handed on is gated, not only the named
            # text keys: a kept field outside ``text_keys`` (``phase`` on a task
            # brief) carried a host path to the planner (Odysseus round 2, D1).
            handed_on = [text for key, value in projected.items() if key not in path_keys
                         for text in _strings_in(value)]
            named = [str(row[key]) for key in text_keys if isinstance(row.get(key), str) and row.get(key)]
            text = " ".join(dict.fromkeys(named + handed_on))
            if not paths and not text:
                withheld += 1
                continue
            if (paths and not all(self._admit(path, text) for path in paths)) or (
                    not paths and not self._admit_text(text)):
                withheld += 1
                continue
            kept.append(projected)
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
        queue_raw = {key: bridge.get(key) for key in (
            "queue_depth", "in_flight", "unread_count", "reports_total")}
        watcher = bridge.get("watcher") if isinstance(bridge.get("watcher"), dict) else {}
        queue_raw["watcher"] = watcher.get("state", "unknown")
        # Host paths never reach the planner: the registry row is the
        # projection, the absolute path is not part of the observation.
        # MEASURED 2026-09-10 (live run 3): ``collect_status`` also carries
        # ``todo_snapshot``, an absolute path. Every value is gated by SHAPE
        # through every string it would hand on -- a list, a dict, a set, a
        # Path or an exception included (Odysseus round 4, D10: the round-3
        # gate looked at str values only, so a list of paths passed).
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
            if self._admit_value(key, value):
                observed[key] = value
            else:
                withheld_fields += 1
        observed["git_status_withheld"] = withheld_paths
        observed["fields_withheld"] = withheld_fields
        queue: dict[str, Any] = {}
        queue_withheld = 0
        for key, value in queue_raw.items():
            if self._admit_value(key, value):
                queue[key] = value
            else:
                queue_withheld += 1
        queue["fields_withheld"] = queue_withheld
        return {"git": observed, "queue": queue, "registered": True}

    def _admit_value(self, key: str, value: Any) -> bool:
        """A scalar or container is admitted only if every string it would hand
        on passes the shape check and the project's gate."""
        return all(not _looks_like_host_path(text) and self._admit(f"{key}.txt", text)
                   for text in _strings_in(value))

    def _structure(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.report import structure_summary
        idx = self._cached_index(repo_root)
        summary = structure_summary(idx, top_hotspots=TOP * 2, top_clones=TOP * 2, top_windows=0,
                                    top_fanin=TOP * 2, top_renamed=0, top_near=0,
                                    max_graph_nodes=0, max_graph_edges=0)
        ignored = summary.get("ignored") if isinstance(summary.get("ignored"), dict) else {}
        hotspots, hotspots_withheld = self._admit_rows(
            summary.get("hotspots", []), ("module",),
            keep_keys=("module", "score", "loc", "long_functions", "guard_count", "cc_max"))
        fan_in, fan_in_withheld = self._admit_rows(summary.get("fan_in", []), ("module",),
                                                   keep_keys=("module", "count"))
        clones: list[dict[str, Any]] = []
        clones_withheld = 0
        for row in summary.get("clones", []):
            if not isinstance(row, Mapping) or not self._admit_text(
                    " ".join(str(row.get(key, "")) for key in ("name", "language", "safety") if row.get(key))):
                clones_withheld += 1
                continue
            sites, sites_withheld = self._admit_rows(row.get("sites", []), ("module",),
                                                     keep_keys=("module", "line"))
            if not sites:
                clones_withheld += 1
                continue
            clones.append({**{key: row[key] for key in ("name", "language", "count", "loc", "safety") if key in row},
                           "sites": sites, "sites_withheld": sites_withheld})
        # ``ignored.source`` is the absolute path of the ignore file and
        # ``ignored.sample`` names withheld files (MEASURED 2026-09-10, live run
        # 3): only the counts and the ignore PATTERNS (key ``ignore_patterns``;
        # Cerberus N7) are observed -- and the patterns name exactly the trees
        # a project wants withheld, so each one passes the text gate like any
        # other string (Cerberus round 3, H1).
        patterns = [str(p) for p in (ignored.get("ignore_patterns") or [])]
        admitted_patterns = [p for p in patterns if self._admit_text(p)]
        # ``*_withheld`` counts gate refusals; ``*_elided`` counts the admitted
        # rows the TOP bound drops, so a short list is never mistaken for a
        # complete one (Odysseus round 4, D13).
        return {"n_files": summary.get("n_files"),
                "ignored": {"count": ignored.get("count", 0),
                            "n_files_scanned": ignored.get("n_files_scanned"),
                            "ignore_patterns": admitted_patterns[:TOP],
                            "ignore_patterns_withheld": len(patterns) - len(admitted_patterns),
                            "ignore_patterns_elided": max(0, len(admitted_patterns) - TOP)},
                "languages": summary.get("languages"), "totals": summary.get("totals"),
                "hotspots": hotspots[:TOP], "hotspots_withheld": hotspots_withheld,
                "hotspots_elided": max(0, len(hotspots) - TOP),
                "clones": clones[:TOP], "clones_withheld": clones_withheld,
                "clones_elided": max(0, len(clones) - TOP),
                "fan_in": fan_in[:TOP], "fan_in_withheld": fan_in_withheld,
                "fan_in_elided": max(0, len(fan_in) - TOP),
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
            # The refusal text reaches the planner's history like any result
            # (runtimes/computer.py ``outcome["error"]``), so the candidates go
            # through the same gate as a ``module`` row of ``daedalus.structure``
            # -- a basename the model chooses must not enumerate the paths the
            # project withholds (Cerberus round 4, H4).
            admitted = [hit for hit in hits if self._admit(hit, "")]
            withheld = len(hits) - len(admitted)
            if admitted:
                raise ComputerRefused(
                    f"module is ambiguous ({len(hits)} indexed candidates, {withheld} withheld by the egress "
                    f"gate); name one of: " + ", ".join(admitted[:TOP]))
            raise ComputerRefused(
                f"module is ambiguous ({len(hits)} indexed candidates, all withheld by the egress gate); "
                "name a fuller repository-relative path")
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
        # The withheld rows name the FILES the gate refused -- on the untrusted
        # lane exactly the paths the project keeps from the vendor (Cerberus
        # round 3, H2) -- and the RULE names the path, the deny fragment or the
        # marker again (Odysseus round 4, D9). Only the role and a rule CLASS
        # travel; the count says how many.
        rows = [{"role": str(row.get("role", "")), "rule": _rule_class(row.get("rule", ""))}
                for row in withheld if isinstance(row, Mapping)] if isinstance(withheld, list) else []
        shown = rows[:TOP]
        if any(row["role"] == "focus" for row in rows):
            # A withheld focus yields no slice at all: the slicer's whole text
            # is its two-line refusal naming the file and the rule. Rebuilt.
            text = (f"# ===== WITHHELD: <withheld> ({shown[0]['rule']}) =====\n"
                    f"# focus file withheld by the egress gate (lane={lane}); slice refused (fail-closed).")
            elided = False
        elif _WITHHELD_HEADER in text:
            # The slicer keeps its withheld block LAST: everything after the
            # header is a per-file breadcrumb naming the file and the rule.
            # Rebuilt from the gated rows; only a CONTEXT TRIMMED marker (counts
            # only) is carried over from the original tail.
            head, tail = text.split(_WITHHELD_HEADER, 1)
            trimmed = [line.rstrip("\r") for line in tail.splitlines() if line.startswith(_TRIMMED_MARKER)]
            text = (head + _WITHHELD_HEADER
                    + "".join(f"\n# <withheld>  ({row['rule']})  [{row['role']}]" for row in shown)
                    + (f"\n# ... {len(rows) - len(shown)} more withheld" if len(rows) > len(shown) else "")
                    + "".join("\n" + line for line in trimmed))
        # The resolved focus path is disclosed only if the gate admits it: a
        # basename resolves to its full indexed path, which on the untrusted
        # lane may be exactly the directory the project withholds (Cerberus
        # round 4, H4 corollary).
        focus = target if self._admit(target, "") else "<withheld>"
        return {"focus_file": focus, "lane": lane,
                "slice_tokens": result.get("slice_tokens"), "n_included": result.get("n_included"),
                "trimmed_count": result.get("trimmed_count", 0),
                "withheld": shown, "withheld_count": len(rows),
                "withheld_elided": max(0, len(rows) - TOP),
                "text": text, "text_elided": elided}

    def _docrefs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.spine import docrefs
        report = docrefs.scan(repo_root)
        self._checkpoint()
        payload = report.to_dict()
        broken, withheld = self._admit_rows(payload.get("broken", []),
                                            ("doc_path", "module_path"), ("raw", "symbol"),
                                            keep_keys=("doc_path", "line", "raw", "module_path", "symbol", "state"))
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
            briefs, (), ("summary", "name", "agent", "provider", "lane", "project"),
            keep_keys=("name", "status", "lane", "project", "agent", "provider", "phase", "summary"))
        return {"reports": reports, "reports_withheld": withheld,
                "computer_missions": "use /computer tasks in the chat"}
