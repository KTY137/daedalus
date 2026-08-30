from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
from collections import namedtuple
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..lanes import BASELINE_POLICY, WriteAttempt, run_checks
from ..limit_policy import ExecutionLimitPolicy, LimitPolicyError
from ..sensitivity import path_write_blocked
from ..structcore.tokens import count_tokens
from ._ollama_native import (
    OUTPUT_RESERVE_TOKENS,
    effective_input_window,
    native_chat,
    num_ctx_value,
)
from ._openai_compat import ProviderHTTPError, server_reachable
from ._report import (
    MAX_CONTEXT_CHARS,
    admit_execution_limit_policy,
    attempt_numbers,
    blocked_report,
    build_prompt,
    coerce_report,
    extract_json,
    provider_http_timeout,
    read_provider_context,
    render_provider_brief,
)
from .base import Provider, ProviderCapabilities
from .personas import persona_for

# Local server. Because nothing leaves the machine, Ollama is trusted with IP,
# is AGENTIC (drives its own file reads), and MAY WRITE -- but with reduced
# rights vs Claude: the write-guard blocks device/vendor/secret/high-risk paths,
# it only writes when the router grants write mode, and it is confined to repo_root.
DEFAULT_HOST = "http://127.0.0.1:11434"  # not "localhost" -- avoids IPv6 (::1) miss on Windows
DEFAULT_MODEL = "qwen2.5-coder:7b"  # per docs/PROVIDERS_RESEARCH.md

# Operator consent for ONE named remote Ollama endpoint (an RTX bench across a
# tailnet is the motivating case). Holds the host itself, never a boolean --
# see ``_remote_consented``. Unset by default, so the provider's refusal to be
# a network lane stands until somebody names the machine on purpose. Consent
# does not make the lane "trusted": ``lane_for_host`` still answers by host, so
# the default-deny allow-list and the unbypassable secret floor both keep
# running over everything sent there.
REMOTE_CONSENT_VAR = "DAEDALUS_OLLAMA_REMOTE_OK"
# BEFORE CHANGING THIS, KNOW WHAT THE AXIS ACTUALLY IS. Measured 2026-07-29 on
# an RTX 5080, 3 trials x 2 agent-shaped tasks per model, native `tools` array:
#
#     qwen2.5-coder 1.5b / 7b / 14b     0% structured tool_calls
#     devstral:latest                   0%
#     qwen3.6 (36B MoE)                 100%
#
# Size is not the axis. Doubling 7b to 14b bought exactly nothing, and every one
# of those models ADVERTISES the `tools` capability -- Ollama's badge is
# necessary and not sufficient. The three that scored zero decided correctly and
# narrated the decision in prose, which `_run_agentic` read as a finished report:
# a successful turn that changed nothing.
#
# This default is defensible only BECAUSE of `_schema_rescue` below, which
# re-asks with the call shape constrained at the sampler and takes all three to
# 100%. A future maintainer picking a different default on size or benchmark
# score alone, without checking structured-output reliability, will reintroduce
# the silent-no-op failure this file spent a day removing.

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

#: Structural-brief budget for the LOCAL lane. Far smaller than DeepSeek's
#: default (daedalus/lanes/graph_brief.DEFAULT_BUDGET_CHARS, 12k): the local
#: context window is the scarcest resource on this path, and the brief is the
#: first thing shed when a file's own content already fills it. 1-hop symbols
#: plus one import line for a typical file fits well inside this.
_LOCAL_BRIEF_BUDGET_CHARS = 2_000

# --------------------------------------------------------------------------- #
# WINDOWED rewrite -- an edit that does not require reprinting the file        #
# --------------------------------------------------------------------------- #
# MEASURED 2026-07-29, the first live self-improvement runs: three docref
# attempts against docs/HANDOFF.md (2496 lines / 148_291 bytes) all ended
# no_change/write_gate_failed. The file never reached the model -- 148 KB is
# 6x MAX_REWRITE_CHARS, so _run_rewrite skipped it "too large for full rewrite"
# and the write gate correctly saw no diff. Raising the cap does not fix it: the
# rewrite-only reliability finding was measured on SMALL files, and a 7B model
# asked to reprint 2500 lines echoes or truncates.
#
# The candidate already knows WHICH lines are wrong (the docref scan reports
# them), so it can ask for a WINDOW instead of a reprint: the model sees +-N
# lines around each broken line, returns only those lines corrected, and the
# harness splices them back at exact positions. Everything outside a window is
# byte-identical BY CONSTRUCTION (list-slice assignment on the original lines,
# original line endings re-attached), not by the model's good behaviour.
DEFAULT_WINDOW_RADIUS = 40
MAX_WINDOW_LINES = 400      # past this it is a full rewrite wearing a window's name
# Matches the picker's own cap on docref `detail` (12 references per document):
# a file needing more windows than that wants a human, not a 7B.
MAX_WINDOWS_PER_FILE = 12
# Share of the original window's non-blank lines that must come back verbatim.
# One corrected reference in an 81-line window should return ~99% untouched;
# anything under half means the model rewrote the neighbourhood instead of
# correcting it, which the line count alone would not catch.
WINDOW_ANCHOR_FRAC = 0.5

# Marker appended when a tool result is head-truncated to make the forced final
# report call fit the local context window (visible so the model knows it lost tail).
_TOOL_TRUNC_MARKER = "\n[...tool output truncated to fit the local context window]"

# --------------------------------------------------------------------------- #
# what a schema rescue actually produced -- three worlds, not one empty list    #
# --------------------------------------------------------------------------- #
#: The model named a tool: `calls` is non-empty and `detail` is the tool name.
RESCUE_CALLS = "calls"
#: The model looked at the work and said it is done. The ONLY empty outcome that
#: means "done"; everything below is a failure wearing the same empty list.
RESCUE_FINISHED = "finished"
#: The transport failed -- refused, timed out, HTTP error. Nothing was asked, so
#: nothing was answered, and "no tool calls" says nothing about the work.
RESCUE_UNREACHABLE = "unreachable"
#: It answered, but not with the json shape the sampler was constrained to.
RESCUE_MALFORMED = "malformed"

RescueOutcome = namedtuple("RescueOutcome", "calls kind detail")

# Elision markers (per docs/RESEARCH_LOCAL_EDITING.md): a rewrite containing one
# of these almost certainly dropped code instead of returning the whole file.
# Only rejected when the marker is NEW (absent from the original) to avoid
# false positives on files that legitimately contain such text.
_ELISION_MARKERS = (
    "rest of the file", "rest of the code", "rest of code",
    "remains unchanged", "remain unchanged", "existing code here",
    "... existing code", "unchanged code omitted", "code omitted",
)

# This lane's own policy over the shared daedalus.lanes baseline. The marker
# tuple stays a LOCAL literal on purpose -- see daedalus/lanes/__init__.py: it
# is a claim about what THIS model emits, and deepseek.py keeps its own tuple
# so the two lanes stay free to diverge without silently re-tuning each other.
# Everything else about "is this a safe write" (truncation, parses, substitution,
# unresolved first-party imports) is the shared baseline, wired in below --
# closing the gap measured 2026-07-30: the two guards added to deepseek.py that
# night (substitution, invented imports) never reached this file, so the free
# local default lane was strictly weaker than the paid external one for the
# exact two failures measured that night.
_CHECK_POLICY = dataclasses.replace(BASELINE_POLICY, elision_markers=_ELISION_MARKERS)

def _normalize_rewrite_windows(spec: Any, n_lines: int,
                               radius: int = DEFAULT_WINDOW_RADIUS) -> list[tuple[int, int]]:
    """Normalize ONE file's window hint into sorted, merged, clamped
    1-based-inclusive ``(start, end)`` pairs.

    Accepted item shapes -- all JSON-native, because the hint travels through a
    candidate's evidence and a task spec before it reaches this file:

    * ``int``                        -> that line, +- ``radius``
    * ``{"line": L, "radius": R}``   -> ``radius`` optional
    * ``{"start": S, "end": E}``
    * a 2-sequence ``[S, E]``        -> START AND END. A bare 2-tuple is
      ambiguous with ``(line, radius)``; this file picks one reading and says
      so rather than guessing per call. Use the mapping form for line+radius.

    ``spec`` itself is a LIST of those items. A bare 2-sequence at the TOP level
    is therefore two line numbers, not one ``(start, end)`` -- wrap it
    (``[[S, E]]``) to mean a range.

    An unusable hint yields ``[]``, which degrades to the existing full-file
    behaviour. This function never invents a window.
    """
    if n_lines <= 0 or not spec:
        return []
    items = spec if isinstance(spec, (list, tuple)) else [spec]
    raw: list[tuple[int, int]] = []
    for item in items:
        start = end = None
        if isinstance(item, bool):          # bool is an int; never a line number
            continue
        if isinstance(item, int):
            start, end = item - abs(radius), item + abs(radius)
        elif isinstance(item, Mapping):
            try:
                if item.get("line") is not None:
                    line = int(item["line"])
                    rad = abs(int(item.get("radius", radius)))
                    start, end = line - rad, line + rad
                elif item.get("start") is not None and item.get("end") is not None:
                    start, end = int(item["start"]), int(item["end"])
            except (TypeError, ValueError):
                continue
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                start, end = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
        if start is None or end is None or end < start:
            continue
        start, end = max(1, start), min(n_lines, end)
        if start > n_lines or end < start:
            continue
        raw.append((start, end))
    # Merge touching/overlapping windows: two windows that share a line would
    # splice over each other, and adjacent ones are cheaper as one call.
    merged: list[tuple[int, int]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _strip_code_fence(text: str) -> str:
    """Drop a markdown fence wrapping the WHOLE payload. Narrow on purpose: the
    fence must open the first line and close the last, so a fragment that
    legitimately contains fenced code inside it is left alone."""
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def _window_replacement_lines(old_slice: list[str], returned: str, *,
                              at_eof: bool) -> list[str]:
    """Validate a model-returned window and render it with the ORIGINAL line
    endings. Raises ``ValueError(reason)`` on any fail-closed check.

    ``old_slice`` is the corresponding slice of ``splitlines(keepends=True)``,
    so the endings are available to re-attach: joining with a bare ``"\\n"``
    would silently convert a CRLF file and turn a two-line fix into a
    whole-file diff -- the opposite of what a window is for.
    """
    body = _strip_code_fence(returned)
    if not body.strip():
        raise ValueError("returned window was empty")
    new_lines = body.splitlines()
    old_plain = [ln.rstrip("\r\n") for ln in old_slice]
    if len(new_lines) != len(old_plain):
        raise ValueError(
            f"returned {len(new_lines)} lines for a {len(old_plain)}-line "
            "window; exact line count required")
    low_new, low_old = body.lower(), "".join(old_slice).lower()
    elided = next((m for m in _ELISION_MARKERS if m in low_new and m not in low_old), None)
    if elided:
        raise ValueError(f"elision marker in returned window ('{elided}')")
    anchors = [ln for ln in old_plain if ln.strip()]
    # A one-line correction necessarily has zero byte-identical line anchors:
    # applying the general 50% rule there would reject every possible edit.
    # Exact line count, identifier removal, the curated gate, and rollback are
    # the structural guards for these surgical windows.
    if len(old_plain) >= 3 and anchors:
        survivors = set(new_lines)
        kept = sum(1 for ln in anchors if ln in survivors)
        if kept < WINDOW_ANCHOR_FRAC * len(anchors):
            raise ValueError(f"only {kept}/{len(anchors)} original non-blank lines came back "
                             "verbatim -- the window was rewritten, not corrected")
    # Exact line count lets us preserve EACH original terminator, including
    # mixed-EOL fragments and a final unterminated line. ``at_eof`` remains in
    # the signature as an explicit caller assertion and for API compatibility.
    def _ending(raw: str) -> str:
        if raw.endswith("\r\n"):
            return "\r\n"
        if raw.endswith("\n"):
            return "\n"
        if raw.endswith("\r"):
            return "\r"
        return ""

    rendered = [ln + _ending(old) for ln, old in zip(new_lines, old_slice)]
    return rendered


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


def ollama_http_base_url(host: str | None) -> str:
    """Return an HTTP base URL while preserving Ollama's schemeless host form.

    The Ollama CLI documents/accepts ``HOST:PORT`` in ``OLLAMA_HOST``. Python's
    HTTP clients require a scheme, so the same portable configuration used to
    be detected by the CLI but rejected as an ``unknown url type`` by Ikarus.
    Only the request spelling is normalised; endpoint admission still receives
    the operator's original value and therefore keeps exact remote consent.
    """
    value = (host or DEFAULT_HOST).strip().rstrip("/")
    if "://" not in value:
        value = "http://" + value
    return value


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
    host = ollama_http_base_url(host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
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


def remote_endpoint_consented(host: str | None) -> bool:
    """True only when the operator named THIS endpoint, exactly.

    ``DAEDALUS_OLLAMA_REMOTE_OK`` holds a HOST, not a boolean, for the reason
    spelled out on :meth:`OllamaProvider._remote_consented`: a ``=1`` flag is
    consent to every future endpoint including one a config change substitutes
    silently.  Normalisation is ``strip().rstrip("/")`` on both sides, and that
    exact spelling is what the embedding index binds its endpoint with, so
    consent and binding can never disagree about which string a host is.
    """
    declared = os.environ.get(REMOTE_CONSENT_VAR, "").strip().rstrip("/")
    return bool(declared) and declared == (host or "").strip().rstrip("/")


def ollama_endpoint_admission(host: str | None) -> tuple[bool, str, str]:
    """THE host-admission decision for the ollama lane: (allowed, lane, why).

    This is the ``provider.egress_policy`` contract for anything that speaks
    the Ollama HTTP transport, expressed once.  It answers only "may bytes go
    to this endpoint at all"; :func:`daedalus.sensitivity.slice_egress_rule`
    still answers "which bytes", and the secret floor still runs underneath
    both.  ``lane`` is :func:`daedalus.sensitivity.lane_for_host`'s verdict,
    which is the ONLY implementation of "does this leave the machine".

    Fails closed: an empty, unparseable, or unrecognised host is ``untrusted``
    and, without exact-endpoint consent, denied.  The returned reason names the
    host, because a refusal a reader cannot attribute to an endpoint is a
    refusal nobody can fix.
    """
    from ..sensitivity import lane_for_host

    lane = lane_for_host(host)
    if lane == "trusted":
        return True, lane, (
            f"lane_for_host({host!r}) == 'trusted': the endpoint is this "
            f"machine, so no bytes reach a wire"
        )
    if remote_endpoint_consented(host):
        return True, lane, (
            f"lane_for_host({host!r}) == {lane!r}; {REMOTE_CONSENT_VAR} names "
            f"this exact endpoint, so the operator declared the egress lane"
        )
    return False, lane, (
        f"lane_for_host({host!r}) == {lane!r}: the endpoint is not this "
        f"machine and {REMOTE_CONSENT_VAR} does not name it, so this would be "
        f"an undeclared network egress lane"
    )


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
        if self._remote_consented():
            # CONSENT IS PERMISSION TO USE THE LANE, NEVER PERMISSION TO SKIP
            # THE GATE THAT POLICES IT. ``egress_lane`` still reports
            # "untrusted" for this host, so ``slice_egress_rule`` keeps its
            # default-deny allow-list on and the secret floor keeps running --
            # exactly the posture any other network provider gets. What the
            # operator has waived is only this provider's blanket refusal to
            # be a network lane at all, which is the door the fence's own
            # message points at ("route the work through a provider whose
            # egress posture is declared"). It is declared here.
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

    def _remote_consented(self) -> bool:
        """True only when the operator named THIS endpoint, exactly.

        The variable holds a HOST, not a boolean. ``=1`` would be consent to
        every remote endpoint forever, including one a later config change
        substitutes without anybody noticing -- and "where do the bytes go" is
        precisely the question that must not be answered by a flag that has
        forgotten which host it was set for. Matching the resolved host means
        repointing ``OLLAMA_HOST`` at a different machine silently revokes the
        consent and the refusal returns, which is the direction this should
        fail.

        Comparison is against ``self.host`` as resolved, so it covers the
        DEFAULT_HOST fallback too, and an unset or blank variable is no
        consent at all.

        THE PREDICATE ITSELF LIVES AT MODULE LEVEL
        (:func:`remote_endpoint_consented`) so a non-provider caller on the
        same lane -- the embedding transport in ``daedalus/memory/embeddings.py``
        is one -- asks the same question of the same variable instead of
        growing a second answer.  This method is the instance-bound spelling of
        it, nothing more.
        """
        return remote_endpoint_consented(self.host)

    def __init__(self) -> None:
        self.host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        self.model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        # abs-path -> original bytes (None = newly created) for clean rollback.
        self._backups: dict[str, bytes | None] = {}
        self._created_dirs: list[str] = []
        self.rollback_failures: list[str] = []
        # GROUND TRUTH for run()'s own report: repo-relative paths THIS
        # instance has actually written to disk (never the model's
        # self-report). Populated only at the two places a real
        # target.write_text() succeeds (_dispatch's write_file branch and
        # _run_rewrite's write loop); reset per call at the top of run().
        self._written: list[str] = []

    def available(self) -> bool:
        return server_reachable(self.host, path="/api/tags")

    def rollback(self) -> list[str]:
        """Undo every write this instance made: restore originals, delete new
        files, remove dirs we created. Any path that can't be reverted is
        recorded in ``rollback_failures`` (the escalation is then 'dirty').

        The restore loop itself is :meth:`Provider._rollback_writes` -- ONE
        implementation, shared with ``DeepSeekProvider.rollback``, which used
        to hold a byte-identical copy of it. This method stays as the named
        public entrypoint: ``offload`` refuses to grant write rights at all to
        a provider without a callable ``rollback()``, and the Gate-0 effect
        registry resolves ``provider.ollama.rollback`` to this exact
        module-and-qualname by static AST lookup.
        """
        return self._rollback_writes()

    # -- guarded filesystem tools (confined to repo_root) -----------------

    def _resolve(self, repo_root: str, rel: str) -> tuple[Path, str]:
        """Return (absolute target, repo-relative posix path). Raises if the
        resolved target escapes repo_root (traversal / symlink / absolute)."""
        root = Path(repo_root).resolve()
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise ValueError("path escapes repo root")
        return target, target.relative_to(root).as_posix()

    def _dispatch(
        self,
        name,
        args,
        repo_root,
        policy,
        changed,
        writable,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ) -> str:
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        tool_timeout = 20 if limit_policy.enforces("wall_time") else None

        def tool_text(value: str) -> str:
            return (
                value[:MAX_READ_CHARS]
                if limit_policy.enforces("tokens")
                else value
            )

        if name == "git_status":
            try:
                completed = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=repo_root,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=tool_timeout,
                    check=False,
                )
                return tool_text(completed.stdout or completed.stderr)
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
                    timeout=tool_timeout,
                    check=False,
                )
                return tool_text(
                    completed.stdout or completed.stderr or "NO TRACKED DIFF"
                )
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
                return tool_text(
                    target.read_text(encoding="utf-8", errors="replace")
                )
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
                self._written.append(rel)  # ground truth, survives a later exception
                return f"OK: wrote {rel}."
            except OSError as exc:
                return f"ERROR: cannot write '{rel}': {exc}"
        return f"ERROR: unknown tool '{name}'."

    # -- agentic loop -----------------------------------------------------

    @staticmethod
    def _decision_schema(tools: list) -> dict:
        """The tool decision, as a shape the sampler can be forced into.

        ``finish`` is in the enum and is not optional: Ollama has no
        ``tool_choice``, so a constrained turn ALWAYS produces an object. Without
        an explicit way to say "nothing further", a model that is genuinely done
        would be compelled to invent one more call -- trading a turn that wrote
        nothing for a turn that writes something wrong, which is worse.
        """
        names = [((t.get("function") or {}).get("name") or "") for t in (tools or [])]
        names = [n for n in names if n]
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": names + ["finish"]},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["action"],
        }

    def _schema_rescue(self, messages, model, tools, timeout_s) -> RescueOutcome:
        """Re-ask the last turn with the call SHAPE constrained.

        Returns a :class:`RescueOutcome`, NOT a bare list. It used to return
        ``[]`` for every outcome, which made three different worlds
        indistinguishable to the caller:

          * the bench is not answering at all,
          * it answered with something that is not the json we forced,
          * the model looked at the work and said it is finished.

        Only the third means "done". Collapsing the first two into it produced
        the exact failure this whole rescue exists to prevent -- a write task
        that wrote nothing, reported as a finished turn -- just one level up.
        The caller must be able to tell them apart, so it is handed the reason.

        Still never raises: a broken rescue degrades to a NAMED empty result,
        which is the point. Empty-and-nameless was the bug.
        """
        schema = self._decision_schema(tools)
        nudge = list(messages) + [{
            "role": "user",
            "content": ("Respond with ONE json object: the next tool to call and its "
                        "arguments, or action \"finish\" if the work is complete. "
                        "For write_file, content must be the FULL new file."),
        }]
        try:
            msg = native_chat(host=self.host, model=model or self.model, messages=nudge,
                              force_json=schema, keep_alive=keep_alive_value(),
                              timeout_s=timeout_s)
        except (ProviderHTTPError, OSError) as exc:
            # The transport failed: nothing was asked, so nothing was answered.
            return RescueOutcome([], RESCUE_UNREACHABLE, f"{type(exc).__name__}: {exc}")
        try:
            obj = json.loads((msg.get("content") or "").strip())
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            # It answered, just not with the shape we constrained it to. That is
            # a statement about the MODEL, not about the bench, and the two get
            # different remedies -- so they get different reasons.
            return RescueOutcome([], RESCUE_MALFORMED, f"{type(exc).__name__}: {exc}")
        if not isinstance(obj, dict):
            return RescueOutcome([], RESCUE_MALFORMED,
                                 f"expected a json object, got {type(obj).__name__}")
        action = str(obj.get("action") or "").strip()
        if not action or action == "finish":
            return RescueOutcome([], RESCUE_FINISHED,
                                 "the model reports the work is complete")
        args = {k: obj[k] for k in ("path", "content") if isinstance(obj.get(k), str)}
        return RescueOutcome(
            [{"function": {"name": action, "arguments": json.dumps(args)}}],
            RESCUE_CALLS, action)

    def _run_agentic(self, objective, repo_root, paths, agent, model, timeout_s, policy,
                     writable, slice_texts=None,
                     execution_limit_policy: ExecutionLimitPolicy | None = None):
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        changed: list[str] = []
        tools = _READ_TOOLS + ([_WRITE_TOOL] if writable else [])
        action = ("APPLY every change by calling the write_file tool with the FULL new file "
                  "contents. Do NOT describe edits in prose -- a change you do not write via "
                  "write_file does not count and will be REJECTED. Read the file, then write it "
                  "back edited. (Protected paths are refused -- that is expected.)"
                  if writable else "you are ADVISORY: do NOT write; propose edits in your report")
        system = (
            build_prompt(agent, "", "", limit_policy)[0]
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
        window = effective_input_window() if limit_policy.enforces("tokens") else None
        # PRE-FLIGHT: never make a call we know the server will head-truncate.
        # count_tokens is cl100k, which OVER-counts qwen tokens, so this refuses
        # a bit early (honest escalation) rather than letting the system prompt
        # be silently eaten. Same downstream semantics as a provider failure.
        est = count_tokens(system) + count_tokens(first_user) + 8 * len(messages)
        if window is not None and est > window:
            return blocked_report(
                f"objective/context exceed the local context window (~{est} of ~{window} tokens)",
                "Route to Claude, or trim the objective.")
        report = None
        for i in attempt_numbers(limit_policy, MAX_AGENT_STEPS):
            if i > 0 and window is not None:
                # MID-LOOP EVICTION: tool results grow the history. Before every
                # round after the first, if the full conversation would overflow,
                # do NOT send it (the server would head-truncate the system
                # prompt). Evict to a minimal form and force the report instead.
                grown = (sum(count_tokens(str(m.get("content") or "")) for m in messages)
                         + 8 * len(messages))
                if grown > window:
                    report = self._forced_report(
                        messages, model, timeout_s, window, limit_policy
                    )
                    break
            msg = native_chat(host=self.host, model=model or self.model, messages=messages,
                              tools=tools, keep_alive=keep_alive_value(), timeout_s=timeout_s)
            calls = msg.get("tool_calls") or []
            if not calls and writable and not changed:
                # THE EXPENSIVE FAILURE, CAUGHT. A write task that stops calling
                # tools without having written anything is almost never "done" --
                # it is a model that decided correctly and then narrated the
                # decision in prose instead of emitting it. The line below would
                # read that prose as a finished report: a successful turn that
                # changed nothing, which is the shape this repo built the
                # full-file-rewrite fallback to route around.
                #
                # MEASURED 2026-07-29: qwen2.5-coder 7b/14b and devstral emit 0%
                # structured tool_calls on agent-shaped tasks and 100% when the
                # shape is constrained at the sampler. So ask once more, with the
                # shape compelled, before believing "done".
                #
                # Gated on ``writable and not changed`` on purpose: models that
                # emit calls natively (qwen3.6 scored 100%) reach here only when
                # genuinely finished, and pay nothing.
                rescue = None
                for _rescue_no in attempt_numbers(limit_policy, 1):
                    rescue = self._schema_rescue(
                        messages, model, tools, timeout_s
                    )
                    calls = rescue.calls
                    if calls or rescue.kind == RESCUE_FINISHED:
                        break
                assert rescue is not None
                if not calls and rescue.kind != RESCUE_FINISHED:
                    # FAIL LOUD, NEVER EMPTY. A write task that wrote nothing,
                    # whose constrained re-ask could not even be delivered (or
                    # came back as something other than the shape it was forced
                    # into), is not a finished turn. Reading the model's prose as
                    # a report here is precisely how "unreachable bench" and
                    # "model chose finish" became the same observable outcome.
                    report = blocked_report(
                        f"the local executor did not complete the turn "
                        f"({rescue.kind}): {rescue.detail}",
                        "unreachable -> check the Ollama server is up and the "
                        "model is pulled; malformed -> the model ignored the "
                        "constrained shape, route this task to a stronger one.",
                        rescue_kind=rescue.kind, rescue_detail=rescue.detail)
                    break
            if not calls:
                try:
                    report = coerce_report(
                        extract_json(msg.get("content") or "{}"), limit_policy
                    )
                except ValueError:
                    if limit_policy.enforces("attempts"):
                        raise
                    messages.extend([
                        msg,
                        {"role": "user", "content": (
                            "Return ONLY the valid final json report, no prose."
                        )},
                    ])
                    continue
                break
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._dispatch(
                    fn.get("name", ""), args, repo_root, policy, changed,
                    writable, limit_policy,
                )
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "name": fn.get("name", ""), "content": result})
        if report is None:  # exhausted the step budget -- force a final report
            messages.append({"role": "user", "content": "Stop using tools. Output the final json report now."})
            final = native_chat(host=self.host, model=model or self.model, messages=messages,
                                keep_alive=keep_alive_value(), timeout_s=timeout_s)
            report = coerce_report(
                extract_json(final.get("content") or "{}"), limit_policy
            )
        report["files_changed"] = list(dict.fromkeys(changed))  # actual writes are authoritative
        return report

    def _forced_report(
        self,
        messages,
        model,
        timeout_s,
        window,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ):
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
        return coerce_report(
            extract_json(final.get("content") or "{}"),
            execution_limit_policy,
        )

    # -- rewrite prompts: whole file, or one window at a time ----------------

    def _full_file_content(self, objective, rel, original, creating, slice_texts,
                           dropped, model, timeout_s, repo_root=None, telemetry=None,
                           execution_limit_policy: ExecutionLimitPolicy | None = None):
        """Ask for the ENTIRE edited file. Returns ``(content, None)`` or
        ``(None, reason)``. Behaviour is byte-for-byte what it was before the
        windowed path existed -- this is an extraction, not a change; ``dropped``
        is appended to in place because shedding the distilled slice is
        provenance the caller reports.

        ``telemetry`` is the same in-place channel for the SHED decision: one
        row per full-file prompt built, appended whether or not the brief was
        shed (see :meth:`_run_rewrite`)."""
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        if (
            limit_policy.enforces("tokens")
            and len(original) > MAX_REWRITE_CHARS
        ):
            return None, "too large for full rewrite"
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
        # The structural brief (daedalus.lanes.graph_brief): what exists, so a
        # local model does not have to guess a name the way three of seven
        # agent-written files did on 2026-07-30 (see deepseek.py for the same
        # measurement). Kept SMALL here on purpose -- the local context window
        # is the tightest resource on this whole path, and a brief the caller
        # cannot afford is worse than none: it is the first thing shed below.
        # Failure to build it must never block a write.
        brief = (
            render_provider_brief(
                repo_root,
                [rel],
                bounded_chars=_LOCAL_BRIEF_BUDGET_CHARS,
                execution_limit_policy=limit_policy,
            )
            if repo_root
            else ""
        )
        brief_block = f"\n\n{brief}" if brief else ""
        if creating:
            user = (f"Change request:\n{objective}\n\nFILE {rel} does NOT exist yet. "
                    "Create it: return the complete initial contents of this new file."
                    f"{brief_block}")
        elif had_slice:
            user = (f"Change request:\n{objective}\n\n"
                    "Project context (distilled, read-only -- the neighborhood of this file):\n"
                    f"{slice_texts[rel]}\n\nFILE {rel} (current contents):\n{original}"
                    f"{brief_block}")
        else:
            user = (f"Change request:\n{objective}\n\nFILE {rel} (current contents):\n{original}"
                    f"{brief_block}")
        # OUTPUT-RESERVE window check (never let the server truncate a rewrite).
        # count_tokens is cl100k -> OVER-counts qwen tokens -> we over-skip
        # (honest escalation) rather than under-count into silent truncation.
        est_in = count_tokens(system) + count_tokens(user)
        output_reserve = count_tokens(original) + OUTPUT_RESERVE_TOKENS
        window = (
            effective_input_window(output_reserve)
            if limit_policy.enforces("tokens")
            else None
        )
        # SHED TELEMETRY. Whether this prompt carried the structural brief is
        # the TREATMENT variable of any graph-conditioning measurement, and it
        # is assigned right here -- by est_in against the window, i.e. by task
        # size. Unrecorded, treatment and task size are confounded and no later
        # comparison of briefed against unbriefed runs can be read (giga plan
        # Phase 3; Lens E dissent 4 / Lens D for_codex 5). Three fields, fixed
        # meanings: ``est_in`` is the estimate the decision was MADE on (brief
        # still in the prompt, cl100k over-count -- the assignment variable, not
        # the tokens the server saw); ``brief_shed`` is whether the brief was
        # then removed to fit; ``brief_bytes`` is the UTF-8 size of the brief
        # block that actually reached the model, so 0 once it is shed and 0 when
        # none was built. The row is appended BEFORE the decision and amended in
        # place, so a refusal below cannot lose it.
        shed_row = {
            "rel": rel,
            "brief_shed": False,
            "est_in": int(est_in),
            "brief_bytes": len(brief_block.encode("utf-8")),
        }
        if telemetry is not None:
            telemetry.append(shed_row)
        if window is not None and est_in > window and brief_block:
            # Shed the brief FIRST: it is a convenience against a specific,
            # measured failure mode, not project context the caller curated for
            # this task the way the slice is.
            user = user.replace(brief_block, "")
            brief_block = ""
            est_in = count_tokens(system) + count_tokens(user)
            shed_row["brief_shed"] = True
            shed_row["brief_bytes"] = 0
        if window is not None and est_in > window:
            if had_slice:  # shed the distilled context next, then re-check
                user = f"Change request:\n{objective}\n\nFILE {rel} (current contents):\n{original}"
                dropped.append(rel)
                had_slice = False
                est_in = count_tokens(system) + count_tokens(user)
            if est_in > window:
                return None, (f"file needs ~{est_in} input tok but the local context "
                              f"window leaves ~{window} tok after a ~{output_reserve}-tok "
                              "generation reserve")
        last_failure = "no usable content returned"
        for _attempt_no in attempt_numbers(limit_policy, 1):
            try:
                msg = native_chat(host=self.host, model=model or self.model,
                                  messages=[{"role": "system", "content": system},
                                            {"role": "user", "content": user}],
                                  force_json=True, keep_alive=keep_alive_value(),
                                  timeout_s=timeout_s, temperature=0.0)
                content = extract_json(msg.get("content") or "{}").get("content")
            except (ProviderHTTPError, ValueError) as exc:
                last_failure = f"model call failed: {exc}"
                continue
            if not isinstance(content, str) or not content.strip():
                last_failure = "no content returned"
                continue
            return content, None
        return None, last_failure

    def _rewrite_by_window(self, objective, rel, original, windows, model, timeout_s,
                           repo_root=None,
                           execution_limit_policy: ExecutionLimitPolicy | None = None):
        """Correct ONLY the given line windows and return the FULL spliced file.

        Returns ``(content, None)`` on success or ``(None, reason)`` on refusal.
        The rollback for a bad window is structural rather than after-the-fact:
        every window is validated and spliced IN MEMORY, and one failed window
        refuses the whole file, so nothing reaches the disk unless every window
        passed. The caller's single write site then takes the backup, so the
        exact-original-bytes contract ``_backups`` carries is untouched.
        """
        lines = original.splitlines(keepends=True)
        total = len(lines)
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        if (
            limit_policy.enforces("work_scope")
            and len(windows) > MAX_WINDOWS_PER_FILE
        ):
            return None, (f"{len(windows)} rewrite windows exceeds the cap of "
                          f"{MAX_WINDOWS_PER_FILE}")
        oversize = (
            next(
                ((s, e) for s, e in windows if e - s + 1 > MAX_WINDOW_LINES),
                None,
            )
            if limit_policy.enforces("work_scope")
            else None
        )
        if oversize:
            return None, (f"window {oversize[0]}-{oversize[1]} spans "
                          f"{oversize[1] - oversize[0] + 1} lines (cap {MAX_WINDOW_LINES}) "
                          "-- that is a full rewrite wearing a window's name")
        system = (
            "You are a careful editor working on ONE FRAGMENT of a larger file. "
            'Return ONLY a json object of the form {"content": "<the corrected fragment>"}. '
            "The value must be that fragment and nothing else: no line numbers, no markdown "
            "fences, no commentary, and no other part of the file. Lines that need no change "
            "must come back byte for byte. Preserve the existing style and indentation. "
            "For a broken documentation reference, the obsolete identifier must not remain. "
            "If the exact replacement name is not known from the supplied text, preserve the "
            "claim by rephrasing it as ordinary prose without asserting a code identifier."
        )
        out = list(lines)
        applied = 0
        # BOTTOM-UP. Splicing the last window first keeps every not-yet-applied
        # window's line numbers valid even when a correction changes the line
        # count above it.
        for start, end in sorted(windows, reverse=True):
            old_slice = lines[start - 1:end]
            window_text = "".join(old_slice)
            if limit_policy.enforces("tokens"):
                context_start = max(1, start - 2)
                context_end = min(total, end + 2)
            else:
                context_start, context_end = 1, total
            surrounding = "".join(lines[context_start - 1:context_end])
            broken_here: list[str] = []
            broken_modules: dict[str, str] = {}
            for match in re.finditer(
                    r"(?mi)^\s*line\s+(\d+)\s*:\s*(.+?)\s+--\s+(.+)$", objective):
                try:
                    ref_line = int(match.group(1))
                except ValueError:
                    continue
                raw_ref = match.group(2).strip()
                if start <= ref_line <= end and raw_ref and raw_ref in window_text:
                    broken_here.append(raw_ref)
                    module_match = re.search(
                        r"([A-Za-z0-9_./\\-]+\.py)\b", match.group(3))
                    if module_match:
                        broken_modules[raw_ref] = module_match.group(1)
            code_context: list[str] = []
            if repo_root:
                root = Path(repo_root).resolve()
                for raw_ref, module_rel in broken_modules.items():
                    candidate_path = (root / module_rel).resolve()
                    try:
                        candidate_path.relative_to(root)
                        module_lines = candidate_path.read_text(
                            encoding="utf-8", errors="strict").splitlines()
                    except (OSError, UnicodeDecodeError, ValueError):
                        continue
                    needle = raw_ref.rsplit(".", 1)[-1].lower()
                    hit = next((i for i, text in enumerate(module_lines)
                                if needle in text.lower()), None)
                    if hit is None:
                        continue
                    if limit_policy.enforces("tokens"):
                        lo, hi = max(0, hit - 6), min(len(module_lines), hit + 7)
                    else:
                        lo, hi = 0, len(module_lines)
                    snippet = "\n".join(
                        f"{i + 1}: {module_lines[i]}" for i in range(lo, hi))
                    code_context.append(
                        f"CURRENT CODE CONTEXT FROM {module_rel} "
                        f"(read-only; use it to find the current name):\n{snippet}")
            if (
                limit_policy.enforces("tokens")
                and len(window_text) > MAX_REWRITE_CHARS
            ):
                return None, (f"window {start}-{end} is {len(window_text)} chars "
                              f"(cap {MAX_REWRITE_CHARS})")
            user = (f"Change request:\n{objective}\n\n"
                    f"You are editing FILE {rel}, lines {start} to {end} of {total}. "
                    "The measured defect is inside THIS fragment: correct it here; "
                    "returning the fragment unchanged fails the task. Return ONLY "
                    "those lines, corrected."
                    + (f" These exact obsolete identifiers MUST NOT remain: "
                       f"{', '.join(broken_here)}." if broken_here else "")
                    + (" Preserve the fragment's punctuation structure, including "
                       "the same net opening/closing delimiters."
                       if broken_here else "")
                    + (f"\n\nSURROUNDING CONTEXT {context_start}-{context_end} "
                       "(read-only; do not return it):\n"
                       f"{surrounding}\n"
                       + (("\n\n" + "\n\n".join(code_context) + "\n")
                          if code_context else "")
                       + f"EDITABLE LINES {start}-{end} (return exactly these):\n"
                       f"{window_text}"))
            est_in = count_tokens(system) + count_tokens(user)
            reserve = count_tokens(window_text) + OUTPUT_RESERVE_TOKENS
            window_budget = (
                effective_input_window(reserve)
                if limit_policy.enforces("tokens")
                else None
            )
            if window_budget is not None and est_in > window_budget:
                return None, (f"window {start}-{end} needs ~{est_in} input tok but the local "
                              f"context window leaves ~{window_budget} tok after a "
                              f"~{reserve}-tok generation reserve")
            # The expected answer is the same fragment plus a tiny edit.
            # Without an output cap Ollama may keep a malformed JSON string
            # alive until the whole remaining context is exhausted; the first
            # real 81-line window did exactly that for >7 minutes. Twice the
            # source estimate leaves room for JSON escaping and modest reflow.
            output_cap = (
                min(1536, max(384, (2 * count_tokens(window_text)) + 128))
                if limit_policy.enforces("tokens")
                else None
            )
            content_schema = {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
                "additionalProperties": False,
            }
            replacement = None
            last_failure = "no usable content returned"
            for attempt_no in attempt_numbers(limit_policy, 2):
                attempt_user = user
                if attempt_no:
                    attempt_user += (
                        "\n\nRETRY: Your previous answer was unusable or unchanged. "
                        + (f"Remove or replace exactly: {', '.join(broken_here)}. "
                           if broken_here else
                           "The obsolete identifier MUST NOT remain. ")
                        + "Rephrase that one "
                        "line as ordinary prose if needed, keep the exact same number "
                        "of lines, preserve its delimiter balance, and preserve all "
                        "other text.")
                try:
                    request_timeout = provider_http_timeout(
                        limit_policy, timeout_s, bounded_default=60.0
                    )
                    if request_timeout is not None:
                        request_timeout = min(request_timeout, 60.0)
                    call_kwargs = dict(
                        host=self.host,
                        model=model or self.model,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": attempt_user}],
                        force_json=content_schema,
                        keep_alive=keep_alive_value(),
                        timeout_s=request_timeout,
                        temperature=0.0,
                        think=False,
                    )
                    if output_cap is not None:
                        call_kwargs["num_predict"] = output_cap
                    msg = native_chat(**call_kwargs)
                    returned = extract_json(msg.get("content") or "{}").get("content")
                except (ProviderHTTPError, ValueError) as exc:
                    last_failure = f"model call failed: {exc}"
                    continue
                if not isinstance(returned, str) or not returned.strip():
                    last_failure = "no content returned"
                    continue
                try:
                    candidate = _window_replacement_lines(
                        old_slice, returned, at_eof=(end == total))
                except ValueError as exc:
                    last_failure = f"refused: {exc}"
                    continue
                if candidate == old_slice:
                    last_failure = "fragment came back unchanged"
                    continue
                remaining = [raw for raw in broken_here if raw in "".join(candidate)]
                if remaining:
                    last_failure = (
                        "obsolete identifier(s) remained: " + ", ".join(remaining))
                    continue
                if broken_here:
                    old_fragment = "".join(old_slice)
                    new_fragment = "".join(candidate)
                    changed_balance = next((
                        (left, right)
                        for left, right in (("(", ")"), ("[", "]"), ("{", "}"))
                        if (old_fragment.count(left) - old_fragment.count(right))
                        != (new_fragment.count(left) - new_fragment.count(right))
                    ), None)
                    if changed_balance:
                        last_failure = (
                            "delimiter balance changed for "
                            f"{changed_balance[0]}{changed_balance[1]}")
                        continue
                replacement = candidate
                break
            if replacement is None:
                return None, (f"window {start}-{end} failed after 2 attempts: "
                              f"{last_failure}")
            out[start - 1:end] = replacement
            applied += 1
        if not applied:
            return None, "every window came back unchanged"
        return "".join(out), None

    # -- full-file-rewrite write path --------------------------------------

    def _run_rewrite(self, objective, repo_root, paths, model, timeout_s, policy,
                     slice_texts=None, rewrite_windows=None,
                     execution_limit_policy: ExecutionLimitPolicy | None = None):
        """Apply a scoped write WITHOUT the tool loop. The live benchmark showed
        7B-class models narrate edits but never emit write_file calls -- yet the
        same model reliably returns the COMPLETE edited file as json. So: model
        returns content, the harness writes it deterministically, the verifier
        still gates it. Every skip reason is recorded so a no-op escalation is
        explainable instead of silent."""
        changed: list[str] = []
        skipped: dict[str, str] = {}
        dropped: list[str] = []            # rels whose slice context we shed to fit
        shed: list[dict[str, Any]] = []    # one row per full-file prompt (see below)
        slice_texts = slice_texts or {}
        rewrite_windows = rewrite_windows or {}
        windowed: list[str] = []           # rels edited through a line window
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        rewrite_paths = (
            paths[:MAX_REWRITE_FILES]
            if limit_policy.enforces("work_scope")
            else paths
        )
        for raw_rel in rewrite_paths:
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
                disk_original = ""
            else:
                try:
                    disk_original = target.read_bytes().decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    skipped[rel] = f"unreadable: {exc}"
                    continue
            # WINDOWED path: the caller named the lines that are wrong, so the
            # model is asked for those lines instead of a reprint. No hint (or
            # an unusable one) falls through to the unchanged full-file
            # behaviour below -- a window is never invented here.
            windows = ([] if creating else _normalize_rewrite_windows(
                rewrite_windows.get(rel), disk_original.count("\n") + 1))
            if windows:
                # Keep raw decoded line endings for byte-stable splicing.
                original = disk_original
                content, reason = self._rewrite_by_window(
                    objective, rel, original, windows, model, timeout_s,
                    repo_root=repo_root,
                    execution_limit_policy=limit_policy)
                if reason:
                    skipped[rel] = reason
                    continue
                windowed.append(rel)
            else:
                # Preserve the pre-window full-rewrite contract: text-mode
                # reads expose universal newlines to the prompt and text-mode
                # writes restore the platform convention.
                original = (disk_original.replace("\r\n", "\n").replace("\r", "\n"))
                content, reason = self._full_file_content(
                    objective, rel, original, creating, slice_texts, dropped,
                    model, timeout_s, repo_root=repo_root, telemetry=shed,
                    execution_limit_policy=limit_policy)
                if reason:
                    skipped[rel] = reason
                    continue
            if not isinstance(content, str) or not content.strip():
                skipped[rel] = "no content returned"
                continue
            if content == original:
                skipped[rel] = "no change produced"
                continue
            # Shared baseline (daedalus.lanes): truncation, parses, content
            # substitution, unresolved first-party imports -- in that order,
            # cheapest and most specific refusal first. Substitution and
            # imports are the two guards this lane was measured to be missing
            # on 2026-07-30; they are not optional extras, they are baseline.
            refusal = run_checks(WriteAttempt(
                rel=rel, proposed=content, repo_root=repo_root,
                original=original, creating=creating,
            ), policy=_CHECK_POLICY)
            if refusal:
                skipped[rel] = refusal
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
            if windows:
                # Do not route through text-mode newline translation. Window
                # splicing promises that bytes outside the measured fragment
                # stay identical even when the checkout uses LF on Windows.
                target.write_bytes(content.encode("utf-8"))
            else:
                target.write_text(content, encoding="utf-8")
            changed.append(rel)
            self._written.append(rel)  # ground truth, mirrors the tool-loop write site

        # WHICH KIND of rewrite landed is provenance, not decoration: a windowed
        # edit saw only a fragment of the file, so a reviewer reading "rewrite"
        # must not assume the model considered the whole document.
        if changed:
            how = ", ".join(f"{rel} ({'windowed' if rel in windowed else 'full-file'})"
                            for rel in changed)
            summary = f"Applied rewrite to: {how}."
        else:
            summary = "Rewrite produced no applicable change."
        if skipped:
            summary += " Skipped: " + "; ".join(f"{k} ({v})" for k, v in skipped.items())
        handoff: dict[str, Any] = {}
        # UNCONDITIONAL, empty list included. Every other handoff key here is a
        # conditional annotation; this one is a covariate, and a covariate that
        # is only present when it is interesting cannot be regressed on -- an
        # absent key would be indistinguishable from "no brief decision was ever
        # made". Empty means exactly that: no full-file prompt was built (a
        # windowed edit carries no brief), which is itself the honest reading.
        # It rides `handoff` rather than the top level because schemas.REPORT_KEYS
        # is a closed set and validate_report rejects unknown top-level keys.
        handoff["shed_telemetry"] = shed
        if windowed:
            handoff["windowed_rewrite"] = windowed
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
        timeout_s: float | None = 300,
        policy: Any | None = None,
        writable: bool = False,   # fail-closed: caller must grant write explicitly
        slice_texts: dict[str, str] | None = None,  # rel -> caller-gated distilled context
        # rel -> line windows to correct instead of reprinting the file. See
        # _normalize_rewrite_windows for the accepted item shapes. Absent (the
        # default) keeps the full-file behaviour exactly as it was.
        rewrite_windows: dict[str, Any] | None = None,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ) -> dict[str, Any]:
        # BEFORE any prompt is built: every path below this line puts repository
        # content on the wire (the rewrite prompt carries whole file bodies, the
        # tool loop returns read_file results, the fallback inlines with
        # allow_sensitive=True). None of that may reach an endpoint that is not
        # this machine.
        refusal = self._refuse_if_remote()
        if refusal is not None:
            return {**refusal, "persona": persona_for(self.caps.name, agent.get("name")),
                    "wrote": [], "did_work": False}

        persona = persona_for(self.caps.name, agent.get("name"))
        try:
            limit_policy = admit_execution_limit_policy(execution_limit_policy)
        except LimitPolicyError as exc:
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": blocked_report(
                    f"Invalid execution-limit policy: {exc}",
                    "Fix DAEDALUS_EXECUTION_LIMIT_POLICY before retrying.",
                ),
                "wrote": [],
                "did_work": False,
            }
        request_timeout = provider_http_timeout(limit_policy, timeout_s)

        # GROUND TRUTH for THIS call. Reset here (not only in __init__) so an
        # instance reused across more than one run() never reports a PRIOR
        # call's writes as this one's. _dispatch's write_file branch and
        # _run_rewrite's write loop both append to self._written the moment a
        # real target.write_text() succeeds -- never from the model's own
        # self-reported files_changed. Being on self (not a local var) means
        # it also survives an exception raised mid-_run_agentic, so the
        # exception-fallback branch below still reports honestly instead of
        # losing track of writes that already landed on disk before the model
        # call that follows them failed.
        #
        # NOTE: this key does NOT go inside `report` -- schemas.REPORT_KEYS is
        # a closed set (validate_report rejects unknown keys, and that
        # validation runs again downstream in verifier.verify), so "wrote"/
        # "did_work" live only on this outer dict, as siblings of "report".
        self._written = []
        try:
            if (
                writable
                and paths
                and (
                    not limit_policy.enforces("work_scope")
                    or len(paths) <= MAX_REWRITE_FILES
                )
            ):
                # Scoped write -> full-file rewrite (deterministic apply; the
                # benchmark proved the tool loop never actually writes at 7B).
                report = self._run_rewrite(
                    objective, repo_root, paths, model, request_timeout,
                    policy, slice_texts, rewrite_windows, limit_policy,
                )
            else:
                report = self._run_agentic(
                    objective, repo_root, paths, agent, model,
                    request_timeout, policy, writable, slice_texts, limit_policy,
                )
        except (ProviderHTTPError, ValueError) as exc:
            # Fall back to a single-shot advisory read if the tool loop can't run.
            try:
                context, _ = read_provider_context(
                    paths,
                    repo_root,
                    max_chars=MAX_CONTEXT_CHARS,
                    allow_sensitive=True,
                    sensitivity_policy=policy,
                    execution_limit_policy=limit_policy,
                )
                system, user = build_prompt(
                    agent, objective, context, limit_policy
                )
                msg = native_chat(host=self.host, model=model or self.model,
                                  messages=[{"role": "system", "content": system},
                                            {"role": "user", "content": user}],
                                  force_json=True, keep_alive=keep_alive_value(),
                                  timeout_s=request_timeout, temperature=0.0)
                report = coerce_report(
                    extract_json(msg.get("content") or "{}"), limit_policy
                )
            except (ProviderHTTPError, ValueError):
                wrote = list(dict.fromkeys(self._written))
                return {"provider": self.caps.name, "persona": persona, "agent": agent.get("name"),
                        "report": blocked_report(
                            f"Ollama call failed: {exc}",
                            "Ensure the local server is up and the model is pulled, or use Claude."),
                        "wrote": wrote, "did_work": bool(wrote)}
        wrote = list(dict.fromkeys(self._written))
        return {"provider": self.caps.name, "persona": persona,
                "agent": agent.get("name"), "report": report,
                "wrote": wrote, "did_work": bool(wrote)}
