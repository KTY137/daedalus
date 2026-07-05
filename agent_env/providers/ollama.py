from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..sensitivity import path_write_blocked, read_inlined_context
from ._openai_compat import ProviderHTTPError, chat_completion, chat_raw, server_reachable
from ._report import MAX_CONTEXT_CHARS, blocked_report, build_prompt, coerce_report, extract_json
from .base import Provider, ProviderCapabilities
from .personas import persona_for

# Local server. Because nothing leaves the machine, Ollama is trusted with IP,
# is AGENTIC (drives its own file reads), and MAY WRITE -- but with reduced
# rights vs Claude: the write-guard blocks device/vendor/secret/high-risk paths,
# it only writes when the router grants write mode, and it is confined to repo_root.
DEFAULT_HOST = "http://127.0.0.1:11434"  # not "localhost" -- avoids IPv6 (::1) miss on Windows
DEFAULT_MODEL = "qwen2.5-coder:7b"  # per docs/PROVIDERS_RESEARCH.md
MAX_AGENT_STEPS = 6
MAX_READ_CHARS = 16_000

_READ_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List entries of a repo-relative directory.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file (repo-relative path). Returns its contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]
_WRITE_TOOL: dict[str, Any] = {
    "type": "function", "function": {
        "name": "write_file",
        "description": "Write a UTF-8 text file (repo-relative path). Blocked for device/vendor/"
                       "secret/high-risk paths. Use for low-risk edits only.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}


class OllamaProvider(Provider):
    caps = ProviderCapabilities(
        name="ollama",
        can_write=True,      # reduced rights -- see write-guard below
        local=True,
        trusted_with_ip=True,
        agentic=True,
    )

    def __init__(self) -> None:
        self.host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        self.model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        # abs-path -> original bytes (None = newly created) for clean rollback.
        self._backups: dict[str, bytes | None] = {}
        self._created_dirs: list[str] = []
        self.rollback_failures: list[str] = []

    def available(self) -> bool:
        return server_reachable(self.host, path="/api/tags")

    def rollback(self) -> list[str]:
        """Undo every write this instance made: restore originals, delete new
        files, remove dirs we created. Any path that can't be reverted is
        recorded in ``rollback_failures`` (the escalation is then 'dirty')."""
        restored: list[str] = []
        self.rollback_failures = []
        for path, original in self._backups.items():
            p = Path(path)
            try:
                if original is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.write_bytes(original)
                restored.append(path)
            except OSError:
                self.rollback_failures.append(path)
        for d in sorted(self._created_dirs, key=len, reverse=True):  # deepest first
            try:
                dp = Path(d)
                if dp.is_dir() and not any(dp.iterdir()):
                    dp.rmdir()
            except OSError:
                pass
        self._backups.clear()
        self._created_dirs.clear()
        return restored

    # -- guarded filesystem tools (confined to repo_root) -----------------

    def _resolve(self, repo_root: str, rel: str) -> tuple[Path, str]:
        """Return (absolute target, repo-relative posix path). Raises if the
        resolved target escapes repo_root (traversal / symlink / absolute)."""
        root = Path(repo_root).resolve()
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise ValueError("path escapes repo root")
        return target, target.relative_to(root).as_posix()

    def _dispatch(self, name, args, repo_root, policy, changed, writable) -> str:
        raw_rel = str(args.get("path", ""))
        try:
            target, rel = self._resolve(repo_root, raw_rel)  # rel = RESOLVED path
        except ValueError:
            return f"ERROR: '{raw_rel}' is outside the repository."
        if name == "list_dir":
            if not target.is_dir():
                return f"ERROR: '{rel}' is not a directory."
            return "\n".join(sorted(p.name for p in target.iterdir()))
        if name == "read_file":
            try:
                return target.read_text(encoding="utf-8", errors="replace")[:MAX_READ_CHARS]
            except OSError as exc:
                return f"ERROR: cannot read '{rel}': {exc}"
        if name == "write_file":
            if not writable:
                return "REFUSED: this task is advisory (read-only). Propose the change in your report; do not write."
            if path_write_blocked(rel, policy):  # guard the RESOLVED path
                return (f"REFUSED: '{rel}' is a protected path (device/vendor/secret/high-risk). "
                        "Ollama may not write here -- leave it for Claude.")
            try:
                self._backups.setdefault(str(target), target.read_bytes() if target.exists() else None)
                root = Path(repo_root).resolve()
                for parent in [target.parent, *target.parent.parents]:
                    if parent == root:
                        break
                    if root in parent.parents and not parent.exists():
                        self._created_dirs.append(str(parent))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(args.get("content", "")), encoding="utf-8")
                changed.append(rel)
                return f"OK: wrote {rel}."
            except OSError as exc:
                return f"ERROR: cannot write '{rel}': {exc}"
        return f"ERROR: unknown tool '{name}'."

    # -- agentic loop -----------------------------------------------------

    def _run_agentic(self, objective, repo_root, paths, agent, model, timeout_s, policy, writable):
        changed: list[str] = []
        tools = _READ_TOOLS + ([_WRITE_TOOL] if writable else [])
        action = ("make low-risk edits with write_file (protected paths are refused -- expected)"
                  if writable else "you are ADVISORY: do NOT write; propose edits in your report")
        system = (
            build_prompt(agent, "", "")[0]
            + f"\nYou have tools: list_dir, read_file"
            + (", write_file" if writable else "")
            + f". Read what you need, then {action}. "
            "When done, STOP calling tools and reply with ONLY the json report."
        )
        hint = "Candidate paths: " + ", ".join(paths) if paths else "Explore from the repo root."
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Objective:\n{objective}\n\n{hint}"},
        ]
        base = self.host.rstrip("/") + "/v1"
        report = None
        for _ in range(MAX_AGENT_STEPS):
            msg = chat_raw(base_url=base, model=model or self.model, messages=messages,
                           api_key=None, timeout_s=timeout_s, tools=tools)
            calls = msg.get("tool_calls") or []
            if not calls:
                report = coerce_report(extract_json(msg.get("content") or "{}"))
                break
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch(fn.get("name", ""), args, repo_root, policy, changed, writable)
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "name": fn.get("name", ""), "content": result})
        if report is None:  # exhausted the step budget -- force a final report
            messages.append({"role": "user", "content": "Stop using tools. Output the final json report now."})
            final = chat_raw(base_url=base, model=model or self.model, messages=messages,
                             api_key=None, timeout_s=timeout_s)
            report = coerce_report(extract_json(final.get("content") or "{}"))
        report["files_changed"] = list(dict.fromkeys(changed))  # actual writes are authoritative
        return report

    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int = 300,
        policy: Any | None = None,
        writable: bool = False,   # fail-closed: caller must grant write explicitly
    ) -> dict[str, Any]:
        persona = persona_for(self.caps.name, agent.get("name"))
        try:
            report = self._run_agentic(objective, repo_root, paths, agent, model, timeout_s, policy, writable)
        except (ProviderHTTPError, ValueError) as exc:
            # Fall back to a single-shot advisory read if the tool loop can't run.
            try:
                context, _ = read_inlined_context(
                    paths, repo_root, MAX_CONTEXT_CHARS, allow_sensitive=True, policy=policy
                )
                system, user = build_prompt(agent, objective, context)
                raw = chat_completion(base_url=self.host.rstrip("/") + "/v1",
                                      model=model or self.model, system=system, user=user,
                                      api_key=None, timeout_s=timeout_s, force_json=True, temperature=0.0)
                report = coerce_report(extract_json(raw))
            except (ProviderHTTPError, ValueError):
                return {"provider": self.caps.name, "persona": persona, "agent": agent.get("name"),
                        "report": blocked_report(
                            f"Ollama call failed: {exc}",
                            "Ensure the local server is up and the model is pulled, or use Claude.")}
        return {"provider": self.caps.name, "persona": persona,
                "agent": agent.get("name"), "report": report}
