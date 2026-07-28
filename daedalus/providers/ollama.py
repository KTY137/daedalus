from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..sensitivity import path_write_blocked, read_inlined_context
from ..structcore.tokens import count_tokens
from ._ollama_native import (
    OUTPUT_RESERVE_TOKENS,
    effective_input_window,
    native_chat,
    num_ctx_value,
)
from ._openai_compat import ProviderHTTPError, server_reachable
from ._report import MAX_CONTEXT_CHARS, blocked_report, build_prompt, coerce_report, extract_json
from .base import Provider, ProviderCapabilities
from .personas import persona_for

# Local server. Because nothing leaves the machine, Ollama is trusted with IP,
# is AGENTIC (drives its own file reads), and MAY WRITE -- but with reduced
# rights vs Claude: the write-guard blocks device/vendor/secret/high-risk paths,
# it only writes when the router grants write mode, and it is confined to repo_root.
DEFAULT_HOST = "http://127.0.0.1:11434"  # not "localhost" -- avoids IPv6 (::1) miss on Windows
DEFAULT_MODEL = "qwen2.5-coder:7b"  # per docs/PROVIDERS_RESEARCH.md

# How long Ollama keeps the model resident in VRAM after a request. Ollama's
# default is 5 minutes; past that the next chat turn pays a full reload (measured
# ~44s cold vs ~1.4s warm first token for qwen2.5-coder:7b on this box). Override
# with OLLAMA_KEEP_ALIVE (any Ollama duration string, e.g. "10m", "2h", "-1" for
# forever, "0" to disable pinning).
DEFAULT_KEEP_ALIVE = "30m"
MAX_AGENT_STEPS = 6
MAX_READ_CHARS = 16_000
MAX_REWRITE_FILES = 3       # scoped writes only; bigger fan-outs go through Ikarus
MAX_REWRITE_CHARS = 24_000  # full-file rewrite above this risks truncation

# Marker appended when a tool result is head-truncated to make the forced final
# report call fit the local context window (visible so the model knows it lost tail).
_TOOL_TRUNC_MARKER = "\n[...tool output truncated to fit the local context window]"

# Elision markers (per docs/RESEARCH_LOCAL_EDITING.md): a rewrite containing one
# of these almost certainly dropped code instead of returning the whole file.
# Only rejected when the marker is NEW (absent from the original) to avoid
# false positives on files that legitimately contain such text.
_ELISION_MARKERS = (
    "rest of the file", "rest of the code", "rest of code",
    "remains unchanged", "remain unchanged", "existing code here",
    "... existing code", "unchanged code omitted", "code omitted",
)

_READ_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "git_status",
        "description": "Return `git status --short` for the repository.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "git_diff",
        "description": "Return `git diff -- <path>` for one repo-relative path, or the full tracked diff when path is empty.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
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


def keep_alive_value() -> str:
    return os.environ.get("OLLAMA_KEEP_ALIVE", DEFAULT_KEEP_ALIVE)


def warm_model(host: str | None = None, model: str | None = None,
               keep_alive: str | None = None, timeout_s: float = 60.0) -> bool:
    """Pin ``model`` in VRAM for ``keep_alive`` via Ollama's NATIVE /api/generate.

    Why native and not the OpenAI-compat body: Ollama's /v1/chat/completions
    shim SILENTLY DROPS an unknown ``keep_alive`` field — measured, the TTL
    stayed at the 5-minute default. Sending it here is the only thing that
    actually moves the expiry (verified: expires_at jumped to 30.0 minutes).

    An empty prompt makes this a pure load/refresh (`done_reason: "load"`), so
    it costs nothing once the model is already resident. Local-only, no spend,
    no egress. Returns True if the pin was accepted; never raises.
    """
    host = (host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)).rstrip("/")
    model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    keep_alive = keep_alive or keep_alive_value()
    if str(keep_alive) == "0":  # explicitly disabled
        return False
    import urllib.request

    # Pin at the same num_ctx the real offload calls request, so the runner is
    # pre-sized and the first real call doesn't pay a reload to grow the window.
    body = json.dumps({"model": model, "keep_alive": keep_alive,
                       "options": {"num_ctx": num_ctx_value()}}).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/generate", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False  # best-effort: a cold model is slow, never fatal


def warm_model_async(host: str | None = None, model: str | None = None,
                     keep_alive: str | None = None) -> None:
    """Fire-and-forget :func:`warm_model` on a daemon thread.

    Used to refresh the residency TTL around a chat turn without adding the
    pin's latency to the user's reply.
    """
    import threading

    threading.Thread(
        target=warm_model, args=(host, model, keep_alive), daemon=True
    ).start()


class OllamaProvider(Provider):
    caps = ProviderCapabilities(
        name="ollama",
        can_write=True,      # reduced rights -- see write-guard below
        local=True,
        trusted_with_ip=True,
        agentic=True,
    )

    @property
    def egress_lane(self) -> str:
        """``"trusted"`` only if this instance will talk to THIS machine.

        ``caps`` above declares ``local=True, trusted_with_ip=True`` as STATIC
        facts about a provider named "ollama". They are not static: ``host``
        comes from ``OLLAMA_HOST``, so the same class talks to 127.0.0.1 or to
        an RTX bench across a tailnet with no code change. Everything that reads
        ``caps.local`` is therefore reading a claim about a name, and this is
        the fact.
        """
        from ..sensitivity import lane_for_host

        return lane_for_host(self.host)

    def _refuse_if_remote(self) -> dict[str, Any] | None:
        """The enforcement point: a non-loopback endpoint may not be fed source.

        Placed in the PROVIDER, not only in the callers, because the callers are
        where this went wrong the first time. ``offload`` refuses its distilled
        slice for a remote host, but the rewrite prompt carries WHOLE FILE
        BODIES, the agentic loop can return ``read_file`` results over
        subsequent requests, and the single-shot fallback inlines with
        ``allow_sensitive=True``. Closing only the slice door left three others
        open, which is what an independent review found. A guard here covers
        every one of them, including any caller written later.
        """
        if self.egress_lane == "trusted":
            return None
        return {
            "ok": False,
            "refused": "remote_ollama_endpoint",
            "host": self.host,
            "error": (
                f"refusing to send repository content to OLLAMA_HOST={self.host!r}: "
                f"that endpoint is not this machine, so this is a network egress "
                f"lane wearing the name 'ollama'. The provider's capabilities "
                f"declare local=True/trusted_with_ip=True, which is only true for "
                f"a loopback host. Point OLLAMA_HOST at 127.0.0.1, or route the "
                f"work through a provider whose egress posture is declared."),
            "report": {"files_changed": [], "summary": "refused: remote endpoint"},
        }

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
        if name == "git_status":
            try:
                completed = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=repo_root,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                return (completed.stdout or completed.stderr)[:MAX_READ_CHARS]
            except (OSError, subprocess.SubprocessError) as exc:
                return f"ERROR: cannot run git status: {exc}"
        if name == "git_diff":
            raw_rel = str(args.get("path", ""))
            cmd = ["git", "diff", "--"]
            if raw_rel:
                try:
                    _, rel = self._resolve(repo_root, raw_rel)
                except ValueError:
                    return f"ERROR: '{raw_rel}' is outside the repository."
                cmd.append(rel)
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=repo_root,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                return (completed.stdout or completed.stderr or "NO TRACKED DIFF")[:MAX_READ_CHARS]
            except (OSError, subprocess.SubprocessError) as exc:
                return f"ERROR: cannot run git diff: {exc}"
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

    def _run_agentic(self, objective, repo_root, paths, agent, model, timeout_s, policy,
                     writable, slice_texts=None):
        changed: list[str] = []
        tools = _READ_TOOLS + ([_WRITE_TOOL] if writable else [])
        action = ("APPLY every change by calling the write_file tool with the FULL new file "
                  "contents. Do NOT describe edits in prose -- a change you do not write via "
                  "write_file does not count and will be REJECTED. Read the file, then write it "
                  "back edited. (Protected paths are refused -- that is expected.)"
                  if writable else "you are ADVISORY: do NOT write; propose edits in your report")
        system = (
            build_prompt(agent, "", "")[0]
            + f"\nYou have tools: git_status, git_diff, list_dir, read_file"
            + (", write_file" if writable else "")
            + f". Read what you need, then {action}. "
            "When done, STOP calling tools and reply with ONLY the json report."
        )
        hint = "Candidate paths: " + ", ".join(paths) if paths else "Explore from the repo root."
        # Slice context (already gated by the caller) goes between the objective
        # and the hint. Empty/None -> byte-identical to the pre-slice message.
        if slice_texts:
            block = "\n\n".join(slice_texts[k] for k in sorted(slice_texts))
            first_user = (f"Objective:\n{objective}\n\n"
                          f"Distilled project context (read-only, may be partial):\n{block}\n\n{hint}")
        else:
            first_user = f"Objective:\n{objective}\n\n{hint}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": first_user},
        ]
        window = effective_input_window()
        # PRE-FLIGHT: never make a call we know the server will head-truncate.
        # count_tokens is cl100k, which OVER-counts qwen tokens, so this refuses
        # a bit early (honest escalation) rather than letting the system prompt
        # be silently eaten. Same downstream semantics as a provider failure.
        est = count_tokens(system) + count_tokens(first_user) + 8 * len(messages)
        if est > window:
            return blocked_report(
                f"objective/context exceed the local context window (~{est} of ~{window} tokens)",
                "Route to Claude, or trim the objective.")
        report = None
        for i in range(MAX_AGENT_STEPS):
            if i > 0:
                # MID-LOOP EVICTION: tool results grow the history. Before every
                # round after the first, if the full conversation would overflow,
                # do NOT send it (the server would head-truncate the system
                # prompt). Evict to a minimal form and force the report instead.
                grown = (sum(count_tokens(str(m.get("content") or "")) for m in messages)
                         + 8 * len(messages))
                if grown > window:
                    report = self._forced_report(messages, model, timeout_s, window)
                    break
            msg = native_chat(host=self.host, model=model or self.model, messages=messages,
                              tools=tools, keep_alive=keep_alive_value(), timeout_s=timeout_s)
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
            final = native_chat(host=self.host, model=model or self.model, messages=messages,
                                keep_alive=keep_alive_value(), timeout_s=timeout_s)
            report = coerce_report(extract_json(final.get("content") or "{}"))
        report["files_changed"] = list(dict.fromkeys(changed))  # actual writes are authoritative
        return report

    def _forced_report(self, messages, model, timeout_s, window):
        """Evict the conversation to a minimal form and make ONE final report call.

        Called mid-loop when accumulated tool output would overflow the local
        context window. Sending the full history would let the server
        head-truncate the SYSTEM prompt (the exact historic defect); instead we
        keep only the system prompt, the original objective, the LAST tool result,
        and a report-now instruction -- head-truncating the tool result ourselves
        (keeping its HEAD, marking the cut) if even that overflows. This call must
        never be head-truncated by the server."""
        system_msg, first_user_msg = messages[0], messages[1]
        last_tool_msg = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        stop_msg = {"role": "user", "content": "Stop using tools. Output the final json report now."}
        final_msgs: list[dict[str, Any]] = [system_msg, first_user_msg]
        if last_tool_msg is not None:
            last_tool_msg = dict(last_tool_msg)  # copy: truncation must not mutate history
            final_msgs.append(last_tool_msg)
        final_msgs.append(stop_msg)

        def _fits(msgs):
            return (sum(count_tokens(str(m.get("content") or "")) for m in msgs)
                    + 8 * len(msgs)) <= window

        if last_tool_msg is not None:
            original = str(last_tool_msg.get("content") or "")
            keep = len(original)
            while keep > 0 and not _fits(final_msgs):
                keep //= 2
                last_tool_msg["content"] = original[:keep] + _TOOL_TRUNC_MARKER
        final = native_chat(host=self.host, model=model or self.model, messages=final_msgs,
                            keep_alive=keep_alive_value(), timeout_s=timeout_s)
        return coerce_report(extract_json(final.get("content") or "{}"))

    # -- full-file-rewrite write path --------------------------------------

    def _run_rewrite(self, objective, repo_root, paths, model, timeout_s, policy, slice_texts=None):
        """Apply a scoped write WITHOUT the tool loop. The live benchmark showed
        7B-class models narrate edits but never emit write_file calls -- yet the
        same model reliably returns the COMPLETE edited file as json. So: model
        returns content, the harness writes it deterministically, the verifier
        still gates it. Every skip reason is recorded so a no-op escalation is
        explainable instead of silent."""
        changed: list[str] = []
        skipped: dict[str, str] = {}
        dropped: list[str] = []            # rels whose slice context we shed to fit
        slice_texts = slice_texts or {}
        for raw_rel in paths[:MAX_REWRITE_FILES]:
            try:
                target, rel = self._resolve(repo_root, raw_rel)
            except ValueError:
                skipped[raw_rel] = "outside repo"
                continue
            # Greenfield CREATE: a path that doesn't exist yet is a creation
            # request, not an error -- the same guard gates it, the backup is
            # None (rollback deletes it), and the quality checks that compare
            # against the original are skipped because there is no original.
            creating = not target.exists()
            if target.exists() and not target.is_file():
                skipped[raw_rel] = "not a file"
                continue
            if path_write_blocked(rel, policy):  # same guard as the tool loop
                skipped[rel] = "protected path"
                continue
            if creating:
                original = ""
            else:
                try:
                    original = target.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    skipped[rel] = f"unreadable: {exc}"
                    continue
            if len(original) > MAX_REWRITE_CHARS:
                skipped[rel] = "too large for full rewrite"
                continue
            system = (
                "You are a careful software engineer. Apply the requested change and "
                'return ONLY a json object of the form {"content": "<ENTIRE edited file>"}. '
                "The value must be the complete file text -- every line, no omissions, "
                "no markdown fences, no commentary. Preserve the existing style."
            )
            # Slice context (caller-gated) goes between the change request and the
            # file body -- never for a greenfield CREATE (no neighborhood, and the
            # index only slices paths that exist). had_slice lets us shed it to
            # fit the window before skipping the file outright.
            had_slice = (not creating) and (rel in slice_texts)
            if creating:
                user = (f"Change request:\n{objective}\n\nFILE {rel} does NOT exist yet. "
                        "Create it: return the complete initial contents of this new file.")
            elif had_slice:
                user = (f"Change request:\n{objective}\n\n"
                        "Project context (distilled, read-only -- the neighborhood of this file):\n"
                        f"{slice_texts[rel]}\n\nFILE {rel} (current contents):\n{original}")
            else:
                user = f"Change request:\n{objective}\n\nFILE {rel} (current contents):\n{original}"
            # OUTPUT-RESERVE window check (never let the server truncate a rewrite).
            # count_tokens is cl100k -> OVER-counts qwen tokens -> we over-skip
            # (honest escalation) rather than under-count into silent truncation.
            est_in = count_tokens(system) + count_tokens(user)
            output_reserve = count_tokens(original) + OUTPUT_RESERVE_TOKENS
            window = effective_input_window(output_reserve)
            if est_in > window:
                if had_slice:  # shed the distilled context first, then re-check
                    user = f"Change request:\n{objective}\n\nFILE {rel} (current contents):\n{original}"
                    dropped.append(rel)
                    had_slice = False
                    est_in = count_tokens(system) + count_tokens(user)
                if est_in > window:
                    skipped[rel] = (f"file needs ~{est_in} input tok but the local context "
                                    f"window leaves ~{window} tok after a ~{output_reserve}-tok "
                                    "generation reserve")
                    continue
            try:
                msg = native_chat(host=self.host, model=model or self.model,
                                  messages=[{"role": "system", "content": system},
                                            {"role": "user", "content": user}],
                                  force_json=True, keep_alive=keep_alive_value(),
                                  timeout_s=timeout_s, temperature=0.0)
                content = extract_json(msg.get("content") or "{}").get("content")
            except (ProviderHTTPError, ValueError) as exc:
                skipped[rel] = f"model call failed: {exc}"
                continue
            if not isinstance(content, str) or not content.strip():
                skipped[rel] = "no content returned"
                continue
            if content == original:
                skipped[rel] = "no change produced"
                continue
            if len(content) < 0.5 * len(original):
                # classic full-rewrite failure mode: silent truncation
                skipped[rel] = "suspected truncation (under half the original size)"
                continue
            low_new, low_old = content.lower(), original.lower()
            elided = next((m for m in _ELISION_MARKERS if m in low_new and m not in low_old), None)
            if elided:
                skipped[rel] = f"elision marker in output ('{elided}') -- file not fully rewritten"
                continue
            # Backup None = created file (rollback deletes it). Track any parent
            # dirs we create so rollback can prune them too (mirrors the tool loop).
            self._backups.setdefault(str(target), target.read_bytes() if target.exists() else None)
            root = Path(repo_root).resolve()
            for parent in [target.parent, *target.parent.parents]:
                if parent == root:
                    break
                if root in parent.parents and not parent.exists():
                    self._created_dirs.append(str(parent))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            changed.append(rel)

        summary = (f"Applied full-file rewrite to: {', '.join(changed)}."
                   if changed else "Rewrite produced no applicable change.")
        if skipped:
            summary += " Skipped: " + "; ".join(f"{k} ({v})" for k, v in skipped.items())
        handoff: dict[str, Any] = {}
        if skipped:
            handoff["skipped"] = skipped
        if dropped:
            handoff["slice_context_dropped"] = dropped
        return {
            "status": "done" if changed else "needs_review",
            "summary": summary[:600],
            "files_changed": changed,
            "tests_run": [],
            "risks": [],
            "todos": [],
            "handoff": handoff,
        }

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
        slice_texts: dict[str, str] | None = None,  # rel -> caller-gated distilled context
    ) -> dict[str, Any]:
        # BEFORE any prompt is built: every path below this line puts repository
        # content on the wire (the rewrite prompt carries whole file bodies, the
        # tool loop returns read_file results, the fallback inlines with
        # allow_sensitive=True). None of that may reach an endpoint that is not
        # this machine.
        refusal = self._refuse_if_remote()
        if refusal is not None:
            return {**refusal, "persona": persona_for(self.caps.name, agent.get("name"))}

        persona = persona_for(self.caps.name, agent.get("name"))
        try:
            if writable and paths and len(paths) <= MAX_REWRITE_FILES:
                # Scoped write -> full-file rewrite (deterministic apply; the
                # benchmark proved the tool loop never actually writes at 7B).
                report = self._run_rewrite(objective, repo_root, paths, model, timeout_s, policy, slice_texts)
            else:
                report = self._run_agentic(objective, repo_root, paths, agent, model, timeout_s,
                                           policy, writable, slice_texts)
        except (ProviderHTTPError, ValueError) as exc:
            # Fall back to a single-shot advisory read if the tool loop can't run.
            try:
                context, _ = read_inlined_context(
                    paths, repo_root, MAX_CONTEXT_CHARS, allow_sensitive=True, policy=policy
                )
                system, user = build_prompt(agent, objective, context)
                msg = native_chat(host=self.host, model=model or self.model,
                                  messages=[{"role": "system", "content": system},
                                            {"role": "user", "content": user}],
                                  force_json=True, keep_alive=keep_alive_value(),
                                  timeout_s=timeout_s, temperature=0.0)
                report = coerce_report(extract_json(msg.get("content") or "{}"))
            except (ProviderHTTPError, ValueError):
                return {"provider": self.caps.name, "persona": persona, "agent": agent.get("name"),
                        "report": blocked_report(
                            f"Ollama call failed: {exc}",
                            "Ensure the local server is up and the model is pulled, or use Claude.")}
        return {"provider": self.caps.name, "persona": persona,
                "agent": agent.get("name"), "report": report}
