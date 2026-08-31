"""OpenAI Codex CLI provider -- an external, agentic, write-capable lane.

``codex exec`` runs the Codex agent non-interactively against a target repo:
it reads the repo itself and edits files IN PLACE, so (like Claude, unlike
DeepSeek) it needs no inlined context and no draft-apply step. The offload
seam's existing disk-changed verifier semantics apply to its results -- this
provider adds no parallel verification mechanism.

POLICY (non-negotiable): Codex is an EXTERNAL API -- bytes leave the machine
to OpenAI. It is therefore NOT trusted with proprietary IP, and every task is
gated through the same per-project egress policy as DeepSeek
(:func:`daedalus.sensitivity.classify_data`, fail-closed default-deny) BEFORE
the CLI is ever spawned. A denied path never reaches ``codex``.

Residual risk (documented, not hidden): codex is agentic, so once dispatched
it can read repo files beyond the declared ``paths``. The gate refuses tasks
whose declared paths/objective are sensitive, and the prompt instructs codex
to keep out of policy-denied trees, but only the pre-dispatch refusal is a
hard guarantee. Keep sensitive-repo work on the local bench or Claude.

Flags used (grounded in ``codex exec --help``, codex-cli 0.144.1):

* ``--cd <DIR>``                  agent working root = the target repo
* ``--sandbox workspace-write``   write mode; ``read-only`` for advisory
* ``--skip-git-repo-check``       target repos are not always git repos
* ``--output-schema <FILE>``      JSON Schema for the final response shape
* ``--output-last-message <FILE>``the final agent message (our report JSON)
* ``--color never``               no ANSI noise in captured output
* ``--model <MODEL>``             only when explicitly configured

``codex exec`` is the documented non-interactive mode; it never prompts for
approval, so no approval flag is needed (``--ask-for-approval`` is only
documented for the interactive CLI). Auth comes from ``codex login`` (run by
the operator); this provider never triggers a login flow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..limit_policy import ExecutionLimitPolicy
from ..runtimes.contracts.provider_report import REPORT_KEYS
from ..sensitivity import classify_data
from ..runtimes.providers.token_policy import (
    MAX_SUMMARY_CHARS,
    STATIC_PROMPT_PREFIX,
    trim_paths,
)
from ._report import (
    blocked_report,
    bounded_execution_limit_policy,
    coerce_report,
    extract_json,
    provider_http_timeout,
)
from .base import Provider, ProviderCapabilities
from .personas import persona_for

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "runs"

# Same shape claude_bridge enforces -- given to codex via --output-schema.
REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked", "needs_review", "failed"]},
        "summary": {"type": "string", "maxLength": MAX_SUMMARY_CHARS},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "todos": {"type": "array", "items": {"type": "string"}},
        # OpenAI structured-output strict mode (which backs codex
        # --output-schema) rejects any object without additionalProperties:
        # false and with non-required properties (400 invalid_json_schema,
        # live-fired 2026-07-11 task C2). A free-form object is therefore not
        # expressible; carry free-form handoff content in a single notes
        # string instead.
        "handoff": {
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "required": ["notes"],
            "additionalProperties": False,
        },
    },
    "required": sorted(REPORT_KEYS),
    "additionalProperties": False,
}


def build_prompt(
    agent: dict[str, Any],
    objective: str,
    paths: list[str],
    writable: bool,
    policy: Any | None,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> str:
    limit_policy = bounded_execution_limit_policy(execution_limit_policy)
    paths = trim_paths(paths, limit_policy=limit_policy)
    prefix = (
        STATIC_PROMPT_PREFIX
        if limit_policy.enforces("tokens")
        else "Daedalus Bridge Protocol v1."
    )
    action = ("Apply the change directly by editing files in place, then report."
              if writable else
              "You are ADVISORY (read-only sandbox): do NOT edit files; propose "
              "the change as text inside handoff.")
    denied = ""
    if policy is not None:
        frags = ", ".join(getattr(policy, "deny_substrings", ())[:20])
        if frags:
            denied = ("\n- Policy-denied path fragments (do not open or modify): "
                      f"{frags}")
    detail_hint = (
        "\n- The summary remains compact for the report schema; put any "
        "unabridged detail in handoff.notes."
        if not limit_policy.enforces("tokens")
        else ""
    )
    return f"""{prefix}

You are acting as {agent.get('call_name', '?')} / {agent.get('name', '?')}, a stateless specialist.
Work alone; do not ask another agent. Do not use full chat history.

Objective:
{objective}

Relevant paths (repo-relative):
{json.dumps(paths, indent=2)}

Constraints:
- {action}
- Stay inside the repository working root; never touch files outside it.
- Do not run commands that can reach real hardware or external services.{denied}
- Keep summary under {MAX_SUMMARY_CHARS} characters.{detail_hint}
- Your FINAL message must be ONLY a json object with exactly these keys:
  status (done|blocked|needs_review|failed), summary, files_changed,
  tests_run, risks, todos, handoff. No prose around it.
"""


class CodexCLIProvider(Provider):
    """External write-capable lane: the OpenAI Codex CLI in ``exec`` mode.

    Egress-gated exactly like DeepSeek (``trusted_with_ip=False``): a task with
    policy-denied paths/content is refused before any subprocess is spawned."""

    caps = ProviderCapabilities(
        name="codex_cli",
        can_write=True,          # edits files in place (workspace-write sandbox)
        local=False,             # external API -- bytes leave the machine
        trusted_with_ip=False,   # NEVER receives denylisted/sensitive content
        agentic=True,            # reads the repo itself
    )

    def available(self) -> bool:
        return shutil.which("codex") is not None

    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        # Measured live 2026-07-11: real repo tasks (C1/C2) take 8-20 min in
        # codex exec; 300s killed C2's wrapper while codex kept working and
        # the report went out as blocked despite good disk changes.
        timeout_s: int | float | None = 1500,
        policy: Any | None = None,
        writable: bool = False,  # fail-closed: caller must grant write explicitly
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ) -> dict[str, Any]:
        limit_policy = bounded_execution_limit_policy(execution_limit_policy)
        effective_timeout = provider_http_timeout(
            limit_policy,
            timeout_s,
            bounded_default=1500.0,
        )
        persona = persona_for(self.caps.name, agent.get("name"))

        def _out(report: dict[str, Any]) -> dict[str, Any]:
            return {"provider": self.caps.name, "persona": persona,
                    "agent": agent.get("name"), "report": report,
                    "execution_limit_policy": limit_policy.as_dict(),
                    "execution_limit_policy_sha256": (
                        limit_policy.fingerprint_sha256
                    )}

        # HARD EGRESS GATE (non-negotiable): same enforcement path as DeepSeek.
        # Refuse BEFORE spawning the CLI -- a denied path never reaches codex.
        verdict = classify_data(paths, extra_text=objective, policy=policy)
        if verdict.sensitive:
            return _out(blocked_report(
                "Refused: task contains sensitive/proprietary content that must "
                "not leave the machine. " + "; ".join(verdict.reasons)[:300],
                "Route this task to Claude or local Ollama.",
                offending=verdict.offending,
            ))

        prompt = build_prompt(
            agent,
            objective,
            paths,
            writable,
            policy,
            execution_limit_policy=limit_policy,
        )
        try:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            (RUN_DIR / "last_codex_prompt.md").write_text(prompt, encoding="utf-8")
        except OSError:
            pass  # debug breadcrumb only -- never fatal

        with tempfile.TemporaryDirectory(prefix="daedalus-codex-") as td:
            schema_path = Path(td) / "report_schema.json"
            schema_path.write_text(json.dumps(REPORT_SCHEMA), encoding="utf-8")
            message_path = Path(td) / "last_message.json"

            # npm installs `codex` as a .CMD shim on Windows; subprocess cannot
            # spawn it by bare name (WinError 2), so resolve the real path.
            codex = shutil.which("codex") or "codex"
            cmd = [
                codex, "exec",
                "--cd", repo_root,
                "--sandbox", "workspace-write" if writable else "read-only",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-schema", str(schema_path),
                "--output-last-message", str(message_path),
            ]
            chosen_model = model or os.environ.get("CODEX_MODEL", "")
            if chosen_model:
                cmd += ["--model", chosen_model]
            cmd.append(prompt)

            try:
                completed = subprocess.run(
                    cmd, cwd=repo_root, text=True, capture_output=True,
                    # codex emits UTF-8 (em-dashes, box-drawing chars); WITHOUT
                    # an explicit encoding, text=True decodes with the Windows
                    # locale (cp1252) and the capture reader-thread dies on
                    # bytes like 0x9d -> corrupted/empty output, watcher thread
                    # crash (live-fired 2026-07-12, tasks C2/C3). Force UTF-8
                    # and never let a stray byte kill the reader.
                    encoding="utf-8", errors="replace",
                    # stdin MUST be closed: with a prompt arg, `codex exec`
                    # still appends piped/inherited stdin as a <stdin> block
                    # and blocks until EOF. Under the file-bridge watcher the
                    # inherited stdin never closes -> codex hangs at ~0 CPU
                    # (live-fired 2026-07-11, task C1).
                    stdin=subprocess.DEVNULL,
                    timeout=effective_timeout, check=False,
                )
            except subprocess.TimeoutExpired:
                timeout_label = (
                    f" after {effective_timeout:g}s"
                    if effective_timeout is not None
                    else ""
                )
                report = blocked_report(
                    f"Codex CLI timed out{timeout_label}.",
                    "Retry with a longer timeout or fall back to Claude.",
                    disk_may_be_dirty=writable,
                )
                if writable:
                    report["risks"] = ["codex was killed mid-run in write mode; "
                                       "the repo may contain partial edits."]
                return _out(report)
            except OSError as exc:
                return _out(blocked_report(
                    f"Codex CLI could not be launched: {exc}",
                    "Check `codex --version` / PATH, then retry or fall back to Claude.",
                ))

            if completed.returncode != 0:
                tail = (completed.stderr or completed.stdout or "").strip()[-400:]
                report = blocked_report(
                    f"Codex CLI failed with exit code {completed.returncode}: {tail}"[:MAX_SUMMARY_CHARS],
                    "Check `codex login status` / retry, or fall back to Claude.",
                    exit_code=completed.returncode,
                    disk_may_be_dirty=writable,
                )
                if writable:
                    report["risks"] = ["codex exited abnormally in write mode; "
                                       "the repo may contain partial edits."]
                return _out(report)

            try:
                raw = message_path.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            if not raw.strip():
                return _out(blocked_report(
                    "Codex CLI produced no final message (empty --output-last-message file).",
                    "Retry, or fall back to Claude.",
                ))
            try:
                report = coerce_report(
                    extract_json(raw),
                    execution_limit_policy=limit_policy,
                )
            except (ValueError, json.JSONDecodeError):
                return _out(blocked_report(
                    "Codex CLI returned a malformed report (not the agent_report_v1 json).",
                    "Retry, or fall back to Claude.",
                    raw_tail=raw.strip()[-400:],
                ))

        try:
            (RUN_DIR / "last_codex_report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8")
        except OSError:
            pass
        return _out(report)
