"""Owner-scoped policy for the canonical computer-use effect.

Configuration is outside candidate workspaces. This is a trusted host adapter
policy, not containment of arbitrary Python or arbitrary child processes.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from daedalus.spine.envelope import canonical_sha


class ComputerRefused(ValueError):
    pass


FILE_TOOLS = ("file.list", "file.read", "file.write", "file.mkdir", "file.move")
VISION_TOOLS = ("vision.inspect", "vision.match", "vision.changes", "vision.ocr")
DESKTOP_TOOLS = ("desktop.observe", "desktop.click", "desktop.type", "desktop.key", "app.launch")
BROWSER_TOOLS = ("browser.navigate", "browser.read", "browser.click", "browser.fill")
ALL_COMPUTER_TOOLS = frozenset(FILE_TOOLS + VISION_TOOLS + DESKTOP_TOOLS + BROWSER_TOOLS)
# v0.1.6 release fence.  ``Path.resolve`` plus a later pathname operation is
# not a write-root boundary: another process can replace a checked ancestor
# with a symlink/junction between those two operations.  Keep legacy policy
# files readable so owners can remove old grants, but never turn those grants
# into runtime authority.  Observation-backed vision does not open a workspace
# path and remains a separate, explicitly constrained capability.
PATH_IO_RELEASE_REFUSAL = (
    "workspace path tools are disabled in v0.1.6 until handle-relative, "
    "reparse-safe I/O is independently verified"
)
RELEASE_DISABLED_TOOLS = frozenset(FILE_TOOLS + ("vision.match", "vision.changes"))
RELEASE_OBSERVATION_ONLY_TOOLS = frozenset(("vision.inspect", "vision.ocr"))
_PROTECTED = frozenset({".git", ".agentenv", ".codex", "agents.md", "computer-policy.json",
                        "ikarus_ariadne_master_plan.md", "ikarus_ariadne_master_plan.amendments.jsonl"})


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ComputerRefused(f"{name} must be an integer between {low} and {high}")
    return value


def origin(url: str) -> str:
    if not isinstance(url, str) or len(url) > 8192:
        raise ComputerRefused("invalid URL")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        hostname = parsed.hostname.lower()
        if ":" in hostname:
            hostname = f"[{hostname}]"
        return f"{parsed.scheme}://{hostname}:{port}"
    except ValueError as exc:
        raise ComputerRefused("URL must use http(s) without embedded credentials") from exc


def enforce_release_tool_fence(tool: str, arguments: Mapping[str, Any]) -> None:
    """Refuse every v0.1.6 tool shape that would reopen a workspace pathname.

    This is a temporary capability fence, not a claim that pathname checks have
    become race-free.  It is deliberately evaluated again by the canonical
    lease issuer through :meth:`ComputerPolicy.admit`.
    """
    if tool in RELEASE_DISABLED_TOOLS:
        raise ComputerRefused(PATH_IO_RELEASE_REFUSAL)
    if tool in RELEASE_OBSERVATION_ONLY_TOOLS:
        # The lease issuer calls this same admission seam independently of the
        # runtime.  Bind the complete release shape here: accepting merely the
        # absence of the literal ``path`` key would let empty or path-aliased
        # operations receive a canonical computer-effect lease.
        if (set(arguments) != {"observation_id"}
                or not isinstance(arguments.get("observation_id"), str)
                or not arguments["observation_id"]):
            raise ComputerRefused(PATH_IO_RELEASE_REFUSAL)


def refuse_workspace_path_io() -> None:
    """Fail closed at private path-I/O seams as defence in depth."""
    raise ComputerRefused(PATH_IO_RELEASE_REFUSAL)


@dataclass(frozen=True)
class ComputerPolicy:
    workspace: Path
    tools: tuple[str, ...] = ()
    origins: tuple[str, ...] = ()
    applications: tuple[tuple[str, tuple[str, ...]], ...] = ()
    planner_provider: str = "ollama_http"
    planner_model: str | None = None
    allow_remote_context: bool = False
    max_steps: int = 16
    timeout_s: int = 300
    max_file_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        root = Path(self.workspace).expanduser()
        if not root.is_absolute():
            raise ComputerRefused("workspace must be absolute")
        for item in (root, *root.parents):
            try:
                info = item.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ComputerRefused("workspace ancestry must not contain links or junctions")
        object.__setattr__(self, "workspace", root.resolve())
        if not isinstance(self.tools, tuple) or len(set(self.tools)) != len(self.tools) or any(t not in ALL_COMPUTER_TOOLS for t in self.tools):
            raise ComputerRefused("tools must be unique known computer tools")
        if type(self.allow_remote_context) is not bool:
            raise ComputerRefused("allow_remote_context must be boolean")
        _integer(self.max_steps, "max_steps", 1, 1000)
        _integer(self.timeout_s, "timeout_s", 1, 86400)
        _integer(self.max_file_bytes, "max_file_bytes", 1, 16_777_216)
        if self.planner_provider not in {"ollama_http", "ollama", "claude_code_cli", "codex_cli", "deepseek"}:
            raise ComputerRefused("unknown planner provider")
        if self.planner_model is not None and (not isinstance(self.planner_model, str) or len(self.planner_model) > 200):
            raise ComputerRefused("invalid planner model")
        object.__setattr__(self, "origins", tuple(sorted({origin(x) for x in self.origins})))
        names: set[str] = set()
        for name, argv in self.applications:
            if not isinstance(name, str) or not name or name in names or not isinstance(argv, tuple) or not argv:
                raise ComputerRefused("applications require unique names and fixed argument lists")
            names.add(name)
            if any(not isinstance(x, str) or "\x00" in x for x in argv) or not Path(argv[0]).is_absolute():
                raise ComputerRefused("application executable must be absolute; arguments are owner-fixed")
            executable = Path(argv[0]).resolve()
            if executable.is_relative_to(self.workspace):
                raise ComputerRefused("candidate executables cannot run as trusted host applications")
            if executable.stem.casefold() in {"python", "python3", "pythonw", "node", "cmd", "powershell", "pwsh", "bash", "sh", "wscript", "cscript", "mshta", "rundll32"}:
                raise ComputerRefused("interpreters require a contained terminal adapter, not trusted app.launch")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "daedalus-computer-policy/1", "workspace": str(self.workspace),
                "tools": list(self.tools), "origins": list(self.origins),
                "applications": {name: list(argv) for name, argv in self.applications},
                "planner_provider": self.planner_provider, "planner_model": self.planner_model,
                "allow_remote_context": self.allow_remote_context, "max_steps": self.max_steps,
                "timeout_s": self.timeout_s, "max_file_bytes": self.max_file_bytes}

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComputerPolicy":
        if not isinstance(value, dict):
            raise ComputerRefused("computer policy must be an object")
        body = dict(value)
        if body.pop("schema", None) != "daedalus-computer-policy/1":
            raise ComputerRefused("unknown computer policy schema")
        for field in ("tools", "origins"):
            items = body.get(field, [])
            if not isinstance(items, list) or any(not isinstance(x, str) for x in items):
                raise ComputerRefused(f"{field} must be a string list")
            body[field] = tuple(items)
        apps = body.get("applications", {})
        if not isinstance(apps, dict) or any(not isinstance(v, list) for v in apps.values()):
            raise ComputerRefused("applications must map names to argument lists")
        body["applications"] = tuple((k, tuple(v)) for k, v in sorted(apps.items()))
        try:
            return cls(**body)
        except (TypeError, KeyError) as exc:
            raise ComputerRefused("invalid computer policy fields") from exc

    def path(self, value: Any, *, must_exist: bool = False) -> Path:
        if not isinstance(value, str) or len(value) > 1000 or "\x00" in value:
            raise ComputerRefused("path must be bounded text")
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if normalized.startswith("/") or any(p == ".." or ":" in p or p.rstrip(" .") != p for p in parts if p != "."):
            raise ComputerRefused("path must remain relative to the computer workspace")
        if any(p.casefold() in _PROTECTED for p in parts):
            raise ComputerRefused("policy and repository control paths are protected")
        from pathlib import PureWindowsPath
        # Python 3.13 provides the Windows API that replaces the deprecated
        # PurePath method; retain the lexical fallback on older/non-Windows hosts.
        reserved = getattr(os.path, "isreserved", None)
        if any(reserved(p) if reserved else PureWindowsPath(p).is_reserved() for p in parts):
            raise ComputerRefused("Windows device names are not files")
        path = self.workspace.joinpath(*parts)
        # Reject links and junctions along the complete path, including the root.
        for item in (path, *path.parents):
            try:
                info = item.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ComputerRefused("linked paths and reparse points are not computer workspaces")
            if item == self.workspace:
                break
        resolved = path.resolve(strict=must_exist)
        if not resolved.is_relative_to(self.workspace):
            raise ComputerRefused("path escapes the computer workspace")
        if resolved.exists() and resolved.is_file() and resolved.stat().st_nlink != 1:
            raise ComputerRefused("hard-linked files are refused")
        return resolved

    def admit(self, tool: str, arguments: Mapping[str, Any]) -> None:
        if tool not in self.tools:
            raise ComputerRefused(f"tool is not enabled: {tool}")
        if type(arguments) is not dict or len(json.dumps(arguments, allow_nan=False)) > 2 * self.max_file_bytes:
            raise ComputerRefused("tool arguments must be a bounded JSON object")
        enforce_release_tool_fence(tool, arguments)
        for key in ("path", "source", "destination", "template", "before", "after"):
            if key in arguments:
                self.path(arguments[key])
        if tool == "browser.navigate" and origin(arguments.get("url")) not in self.origins:
            raise ComputerRefused("browser origin is not enabled")
        if tool == "app.launch" and arguments.get("application") not in dict(self.applications):
            raise ComputerRefused("application is not enabled")


def policy_path(authority_root: Path) -> Path:
    from daedalus.spine.killswitch import control_root
    return control_root(authority_root) / "computer-policy.json"


def load_policy(authority_root: Path) -> ComputerPolicy:
    path = policy_path(authority_root)
    try:
        if path.stat().st_size > 65536 or path.is_symlink():
            raise ComputerRefused("computer policy is oversized or linked")
        policy = ComputerPolicy.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise ComputerRefused(f"computer policy unavailable: {type(exc).__name__}") from exc
    control = path.parent.resolve()
    if policy.workspace.is_relative_to(control) or control.is_relative_to(policy.workspace):
        raise ComputerRefused("computer workspace must be disjoint from kernel control state")
    installation = Path(__file__).resolve().parents[3]
    if policy.workspace.is_relative_to(installation) or installation.is_relative_to(policy.workspace):
        raise ComputerRefused("computer workspace must be disjoint from the Daedalus installation")
    policy.path(".")
    return policy


def admit_operation(authority_root: Path, operation: Mapping[str, Any]) -> ComputerPolicy:
    policy = load_policy(authority_root)
    if set(operation) != {"tool", "arguments", "policy_sha256"} or operation.get("policy_sha256") != policy.digest:
        raise ComputerRefused("operation must bind the current computer policy")
    policy.admit(operation["tool"], operation["arguments"])
    return policy
