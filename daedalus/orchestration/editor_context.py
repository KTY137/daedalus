"""Bounded editor context and transient local editor-session projections.

This module deliberately owns no workflow authority.  Editor selections are
validated against one registered project and persisted with the shared
content-addressed artifact implementation.  Editor sessions are process-local,
short-lived navigation channels; they cannot write files, run shells, enqueue
work, change policy, or approve/promote candidates.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from ..kernel.artifacts import ArtifactIdentityError, store_canonical_json
from ..projects import load_project, resolve_repo_root
from ..sensitivity import load_policy, secret_floor_rule, slice_egress_rule
from ..spine.envelope import canonical_sha


SCHEMA = "daedalus-editor-context/1"
CAPSULE_SCHEMA = "daedalus-context-capsule/1"
CONTEXT_PREFIX = "editor-context:sha256:"
CAPSULE_PREFIX = "context-capsule:sha256:"
MAX_SELECTION_CHARS = 12_000
MAX_DIAGNOSTICS = 20
DEFAULT_CONTEXT_TTL_S = 30 * 60
DEFAULT_SESSION_TTL_S = 30 * 60
ALLOWED_SOURCES = frozenset({"vscode", "openvscode", "cockpit"})
ALLOWED_COMMANDS = frozenset({"reveal_location", "open_diff"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class EditorContextError(ValueError):
    """Base class for a refused or unknown editor-context operation."""


class EditorContextRefused(EditorContextError):
    """The supplied context did not satisfy the project/security contract."""


class UnknownEditorContext(EditorContextError):
    pass


class UnknownEditorSession(EditorContextError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _artifact_root() -> Path:
    override = os.environ.get("DAEDALUS_EDITOR_CONTEXT_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return (Path(__file__).resolve().parents[1] / "runs" / "artifacts" /
            "editor-contexts").resolve()


def _context_dir() -> Path:
    return _artifact_root() / "contexts"


def _capsule_dir() -> Path:
    return _artifact_root() / "capsules"


def _git_head(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EditorContextRefused(
            f"project revision could not be measured: {type(exc).__name__}"
        ) from exc
    revision = (proc.stdout or "").strip().lower()
    if proc.returncode != 0 or not _REVISION_RE.fullmatch(revision):
        raise EditorContextRefused("project has no measurable Git HEAD revision")
    return revision


def _git_path_state(root: Path, relative: str) -> str:
    """Describe whether the selected bytes belong to ``HEAD``.

    ``base_revision`` identifies the project baseline, while ``file_sha256``
    pins the exact bytes the editor showed.  Keeping those facts separate is
    essential for legitimate, uncommitted editor selections: they may be
    attached, but must never be presented as bytes from the base revision.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
            capture_output=True, timeout=5, check=False,
        )
        if tracked.returncode != 0:
            return "untracked"
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", relative],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EditorContextRefused(
            f"selected file state could not be measured: {type(exc).__name__}"
        ) from exc
    if diff.returncode == 0:
        return "base_revision"
    if diff.returncode == 1:
        return "working_tree"
    raise EditorContextRefused("selected file state could not be measured")


def _resolve_project(project: object) -> tuple[str, dict[str, Any], Path, str]:
    name = str(project or "").strip()
    if not name:
        raise EditorContextRefused("project is required")
    try:
        config = load_project(name)
        root = Path(resolve_repo_root(project=name)).resolve(strict=True)
    except Exception as exc:
        raise EditorContextRefused(f"unknown or unreachable project {name!r}") from exc
    if not root.is_dir():
        raise EditorContextRefused(f"registered project {name!r} is unreachable")
    return name, config, root, _git_head(root)


def _relative_file(root: Path, raw_path: object) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise EditorContextRefused("path is required")
    raw = raw_path.strip().replace("\\", "/")
    if PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        raise EditorContextRefused("path must be project-relative")
    if any(part in {"", ".", ".."} for part in PurePosixPath(raw).parts):
        raise EditorContextRefused("path traversal is not allowed")
    try:
        resolved = (root / Path(*PurePosixPath(raw).parts)).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise EditorContextRefused("path is outside the registered project or missing") from exc
    if not resolved.is_file():
        raise EditorContextRefused("path must identify an existing regular file")
    return resolved.relative_to(root).as_posix(), resolved


def _range(value: object) -> dict[str, int] | None:
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise EditorContextRefused("range must be an object")
    names = ("start_line", "start_column", "end_line", "end_column")
    out: dict[str, int] = {}
    for name in names:
        raw = value.get(name)
        if type(raw) is not int or raw < 1:
            raise EditorContextRefused(f"range.{name} must be a positive integer")
        out[name] = raw
    start = (out["start_line"], out["start_column"])
    end = (out["end_line"], out["end_column"])
    if end < start:
        raise EditorContextRefused("range end must not precede its start")
    return out


def _utf16_position(text: str, line_number: int, column_number: int) -> int:
    """Translate a 1-based VS Code position to a Python string offset.

    VS Code columns count UTF-16 code units.  Refusing a position in the middle
    of a surrogate pair is safer than silently attaching a neighbouring range.
    Newlines belong to the preceding line but are not valid column positions.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)
    if not lines:
        lines = [""]
    if normalized.endswith("\n"):
        lines.append("")
    if line_number > len(lines):
        raise EditorContextRefused("range line is outside the declared file")
    prefix = sum(len(item) for item in lines[:line_number - 1])
    line = lines[line_number - 1]
    content = line[:-1] if line.endswith("\n") else line
    wanted_units = column_number - 1
    used_units = 0
    for index, character in enumerate(content):
        if used_units == wanted_units:
            return prefix + index
        width = 2 if ord(character) > 0xFFFF else 1
        if used_units < wanted_units < used_units + width:
            raise EditorContextRefused("range column splits a UTF-16 surrogate pair")
        used_units += width
    if used_units == wanted_units:
        return prefix + len(content)
    raise EditorContextRefused("range column is outside the declared line")


def _selection_matches_range(
        file_text: str, selection: str, declared_range: dict[str, int]) -> bool:
    normalized = file_text.replace("\r\n", "\n").replace("\r", "\n")
    start = _utf16_position(
        normalized, declared_range["start_line"], declared_range["start_column"])
    end = _utf16_position(
        normalized, declared_range["end_line"], declared_range["end_column"])
    return normalized[start:end] == selection.replace("\r\n", "\n").replace("\r", "\n")


def _diagnostics(value: object) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise EditorContextRefused("diagnostics must be a list")
    if len(value) > MAX_DIAGNOSTICS:
        raise EditorContextRefused(
            f"diagnostics exceeds the {MAX_DIAGNOSTICS}-item context limit")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise EditorContextRefused("each diagnostic must be an object")
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        rows.append({
            "message": message[:500],
            "severity": str(item.get("severity") or "unknown")[:40],
            "source": str(item.get("source") or "")[:80],
        })
    return rows


def _ref(prefix: str, digest: str) -> str:
    return prefix + digest


def _digest_from_ref(value: object, prefix: str) -> str:
    text = str(value or "")
    digest = text[len(prefix):] if text.startswith(prefix) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise UnknownEditorContext("invalid context reference")
    return digest


def _expires_at(payload: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise UnknownEditorContext("context has an invalid expiry") from exc


def _load_payload(context_ref: object) -> dict[str, Any]:
    digest = _digest_from_ref(context_ref, CONTEXT_PREFIX)
    path = _context_dir() / f"{digest}.json"
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UnknownEditorContext(str(context_ref)) from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise UnknownEditorContext("context artifact has an unknown schema")
    if canonical_sha(payload) != digest:
        raise ArtifactIdentityError("editor context digest does not match its payload")
    return payload


def _public(payload: dict[str, Any], context_ref: str) -> dict[str, Any]:
    return {
        "context_ref": context_ref,
        "digest": _digest_from_ref(context_ref, CONTEXT_PREFIX),
        "schema": payload["schema"],
        "project": payload["project"],
        "base_revision": payload["base_revision"],
        "source": payload["source"],
        "path": payload["path"],
        "range": payload.get("range"),
        "selection_sha256": payload["selection_sha256"],
        "selection_chars": len(payload.get("selection") or ""),
        "file_sha256": payload["file_sha256"],
        "revision_state": payload.get("revision_state", "unknown"),
        "diagnostics": payload.get("diagnostics", []),
        "created_at": payload["created_at"],
        "expires_at": payload["expires_at"],
        "sensitivity": payload["sensitivity"],
        "inclusion_report": payload["inclusion_report"],
        "expired": _expires_at(payload) <= _now(),
    }


def create_context(
    *,
    project: object,
    source: object,
    path: object,
    selection: object = "",
    range: object = None,
    diagnostics: object = None,
    base_revision: object = None,
    ttl_s: int = DEFAULT_CONTEXT_TTL_S,
) -> dict[str, Any]:
    """Validate and persist one immutable editor selection.

    The client supplies an explicit selection, but the server verifies that it
    occurs in the declared file.  This prevents an adapter from labelling
    arbitrary text as project source while avoiding brittle editor-specific
    column slicing rules for UTF-16/UTF-8 positions.
    """
    project_name, _config, root, measured_revision = _resolve_project(project)
    supplied_revision = str(base_revision or measured_revision).strip().lower()
    if not _REVISION_RE.fullmatch(supplied_revision):
        raise EditorContextRefused("base_revision must be a lowercase 40-hex Git revision")
    if supplied_revision != measured_revision:
        raise EditorContextRefused(
            "base_revision is stale; refresh the editor context before attaching it")

    source_name = str(source or "").strip().lower()
    if source_name not in ALLOWED_SOURCES:
        raise EditorContextRefused(
            f"source must be one of {sorted(ALLOWED_SOURCES)}")
    relative, resolved = _relative_file(root, path)
    raw_selection = str(selection or "")
    if len(raw_selection) > MAX_SELECTION_CHARS:
        raise EditorContextRefused(
            f"selection exceeds the {MAX_SELECTION_CHARS}-character context limit")
    try:
        file_bytes = resolved.read_bytes()
        file_text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EditorContextRefused("selected file is not valid UTF-8 text") from exc
    except OSError as exc:
        raise EditorContextRefused("selected file could not be read") from exc
    declared_range = _range(range)
    if declared_range is not None:
        matches = _selection_matches_range(
            file_text, raw_selection, declared_range)
        if not matches:
            raise EditorContextRefused(
                "selection does not match the declared project file and range")
    elif raw_selection:
        normalized_file = file_text.replace("\r\n", "\n").replace("\r", "\n")
        normalized_selection = raw_selection.replace("\r\n", "\n").replace("\r", "\n")
        matches = normalized_selection in normalized_file
        if not matches:
            raise EditorContextRefused(
                "selection does not match the declared project file and range")
    diagnostic_rows = _diagnostics(diagnostics)
    diagnostic_text = "\n".join(row["message"] for row in diagnostic_rows)
    sensitive_text = "\n".join(filter(None, (
        raw_selection or file_text[:MAX_SELECTION_CHARS], diagnostic_text)))
    floor_reason = secret_floor_rule(relative, sensitive_text)
    if floor_reason is not None:
        raise EditorContextRefused(
            f"selection was rejected by the unconditional secret floor: {floor_reason}")

    ttl = int(ttl_s)
    if ttl <= 0 or ttl > 24 * 60 * 60:
        raise EditorContextRefused("context ttl must be between 1 second and 24 hours")
    created = _now()
    selected = raw_selection
    payload = {
        "schema": SCHEMA,
        "project": project_name,
        "base_revision": measured_revision,
        "source": source_name,
        "path": relative,
        "range": declared_range,
        "selection": selected,
        "selection_sha256": hashlib.sha256(selected.encode("utf-8")).hexdigest(),
        "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "revision_state": _git_path_state(root, relative),
        "diagnostics": diagnostic_rows,
        "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(seconds=ttl)),
        "sensitivity": "secret_floor_passed",
        "inclusion_report": {"accepted": True, "reason": "validated_local_context"},
    }
    ref = store_canonical_json(_context_dir(), payload)
    context_ref = _ref(CONTEXT_PREFIX, ref.sha256)
    return _public(payload, context_ref)


def get_context(context_ref: object) -> dict[str, Any]:
    payload = _load_payload(context_ref)
    return _public(payload, str(context_ref))


def materialize_capsule(
    context_refs: Iterable[object], *, project: object, lane: str
) -> dict[str, Any]:
    """Build a bounded context block after applying the actual egress lane.

    A rejected item is reported and omitted. Nothing is silently truncated and
    no context artifact is rewritten.
    """
    project_name, config, root, measured_revision = _resolve_project(project)
    policy = load_policy(config)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    blocks: list[str] = []
    seen: set[str] = set()
    for raw_ref in context_refs:
        context_ref = str(raw_ref or "")
        if not context_ref or context_ref in seen:
            continue
        seen.add(context_ref)
        try:
            payload = _load_payload(context_ref)
            if payload["project"] != project_name:
                raise EditorContextRefused("context belongs to another project")
            if payload["base_revision"] != measured_revision:
                raise EditorContextRefused("context base revision is stale")
            if _expires_at(payload) <= _now():
                raise EditorContextRefused("context has expired")
            _relative, selected_file = _relative_file(root, payload["path"])
            try:
                current_file_sha = hashlib.sha256(selected_file.read_bytes()).hexdigest()
            except OSError as exc:
                raise EditorContextRefused(
                    "selected file could not be re-read") from exc
            if current_file_sha != payload.get("file_sha256"):
                raise EditorContextRefused(
                    "selected file changed after the editor context was created")
            text = str(payload.get("selection") or "")
            diagnostics = payload.get("diagnostics") or []
            diagnostic_text = "\n".join(
                f"[{row.get('severity', 'unknown')}] {row.get('message', '')}"
                for row in diagnostics if isinstance(row, dict))
            outbound_text = "\n".join(filter(None, (text, diagnostic_text)))
            rule = slice_egress_rule(
                str(payload["path"]), outbound_text, lane=lane, policy=policy)
            if rule is not None:
                raise EditorContextRefused(str(rule))
            accepted.append({
                "context_ref": context_ref,
                "path": payload["path"],
                "range": payload.get("range"),
                "selection_chars": len(text),
                "revision_state": payload.get("revision_state", "unknown"),
            })
            blocks.append(
                f"# Explicit editor context: {payload['path']}\n{outbound_text}"
                if outbound_text else f"# Explicit editor context: {payload['path']} (no selection text)"
            )
        except (EditorContextError, ArtifactIdentityError) as exc:
            rejected.append({"context_ref": context_ref, "reason": str(exc)})

    capsule_payload = {
        "schema": CAPSULE_SCHEMA,
        "project": project_name,
        "base_revision": measured_revision,
        "lane": str(lane),
        "accepted": accepted,
        "rejected": rejected,
        "created_at": _iso(_now()),
    }
    capsule = store_canonical_json(_capsule_dir(), capsule_payload)
    return {
        "capsule_ref": _ref(CAPSULE_PREFIX, capsule.sha256),
        "capsule_sha256": capsule.sha256,
        "text": "\n\n".join(blocks),
        "accepted": accepted,
        "rejected": rejected,
    }


@dataclass
class _Session:
    session_id: str
    token_hash: str
    project: str
    base_revision: str
    adapter: str
    capabilities: tuple[str, ...]
    created_at: float
    expires_at: float
    commands: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)


class EditorSessionRegistry:
    """Process-local, TTL-bound navigation channel for editor adapters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _prune(self) -> None:
        now = time.time()
        expired = [key for key, value in self._sessions.items()
                   if value.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)

    def create(self, *, project: object, adapter: object,
               capabilities: object = None,
               base_revision: object = None,
               ttl_s: int = DEFAULT_SESSION_TTL_S) -> dict[str, Any]:
        project_name, _config, _root, measured_revision = _resolve_project(project)
        supplied_revision = str(base_revision or measured_revision).strip().lower()
        if supplied_revision != measured_revision:
            raise EditorContextRefused("editor session base revision is stale")
        adapter_name = str(adapter or "").strip().lower()
        if adapter_name not in {"vscode", "openvscode"}:
            raise EditorContextRefused("adapter must be vscode or openvscode")
        raw_caps = capabilities or []
        if not isinstance(raw_caps, list):
            raise EditorContextRefused("capabilities must be a list")
        caps = tuple(sorted({str(item) for item in raw_caps
                             if str(item) in ALLOWED_COMMANDS}))
        ttl = int(ttl_s)
        if ttl <= 0 or ttl > 24 * 60 * 60:
            raise EditorContextRefused("session ttl must be between 1 second and 24 hours")
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = _Session(
            session_id="editor_" + uuid.uuid4().hex,
            token_hash=self._token_hash(token),
            project=project_name,
            base_revision=measured_revision,
            adapter=adapter_name,
            capabilities=caps,
            created_at=now,
            expires_at=now + ttl,
        )
        with self._lock:
            self._prune()
            self._sessions[session.session_id] = session
        return {**self.describe(session.session_id), "session_token": token}

    def _get(self, session_id: object, token: object) -> _Session:
        sid = str(session_id or "")
        supplied = str(token or "")
        with self._lock:
            self._prune()
            session = self._sessions.get(sid)
        if session is None:
            raise UnknownEditorSession(sid)
        if not secrets.compare_digest(session.token_hash, self._token_hash(supplied)):
            raise UnknownEditorSession(sid)
        return session

    def describe(self, session_id: object) -> dict[str, Any]:
        sid = str(session_id or "")
        with self._lock:
            self._prune()
            session = self._sessions.get(sid)
        if session is None:
            raise UnknownEditorSession(sid)
        return {
            "session_id": session.session_id,
            "project": session.project,
            "base_revision": session.base_revision,
            "adapter": session.adapter,
            "capabilities": list(session.capabilities),
            "created_at": datetime.fromtimestamp(
                session.created_at, timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(
                session.expires_at, timezone.utc).isoformat(),
        }

    def command(self, session_id: object, token: object,
                command: object, payload: object) -> dict[str, Any]:
        session = self._get(session_id, token)
        name = str(command or "")
        if name not in ALLOWED_COMMANDS or name not in session.capabilities:
            raise EditorContextRefused("editor command is not declared by this session")
        if not isinstance(payload, dict):
            raise EditorContextRefused("editor command payload must be an object")
        relative = str(payload.get("path") or "")
        _project, _config, root, revision = _resolve_project(session.project)
        if revision != session.base_revision:
            raise EditorContextRefused("editor session base revision is stale")
        clean_path, _resolved = _relative_file(root, relative)
        row = {
            "sequence": len(session.commands) + 1,
            "command": name,
            "payload": {**payload, "path": clean_path},
            "created_at": _iso(_now()),
        }
        with session.condition:
            session.commands.append(row)
            session.condition.notify_all()
        return dict(row)

    def events(self, session_id: object, token: object, *, after: int = 0,
               wait_s: float = 0.0) -> list[dict[str, Any]]:
        session = self._get(session_id, token)
        threshold = max(0, int(after))
        with session.condition:
            rows = [dict(item) for item in session.commands
                    if int(item["sequence"]) > threshold]
            if not rows and wait_s > 0:
                session.condition.wait(timeout=min(float(wait_s), 25.0))
                rows = [dict(item) for item in session.commands
                        if int(item["sequence"]) > threshold]
        return rows


SESSIONS = EditorSessionRegistry()


__all__ = [
    "ALLOWED_COMMANDS", "CAPSULE_PREFIX", "CONTEXT_PREFIX",
    "EditorContextError", "EditorContextRefused", "EditorSessionRegistry",
    "MAX_SELECTION_CHARS", "SESSIONS", "UnknownEditorContext",
    "UnknownEditorSession", "create_context", "get_context",
    "materialize_capsule",
]
