from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..sensitivity import (
    classify_data,
    path_write_blocked,
    read_inlined_context,
    secret_floor_rule,
    slice_egress_rule,
)
from ._openai_compat import ProviderHTTPError, chat_completion
from ._report import MAX_CONTEXT_CHARS, blocked_report, build_prompt, coerce_report, extract_json
from .base import Provider, ProviderCapabilities
from .personas import persona_for

# DeepSeek exposes an OpenAI-compatible endpoint. Per docs/PROVIDERS_RESEARCH.md:
# json_object mode only (no GA strict schema) -> validate-and-retry; and the
# legacy deepseek-chat/reasoner ids deprecate 2026-07-24, so default to v4-flash.
# POLICY: DeepSeek trains on inputs by default and is PRC-hosted -> non-sensitive
# content only (enforced below by classify_data).
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

#: Write-path bounds. Deliberately the SAME numbers the local bench uses
#: (providers/ollama.py): they are not window limits -- DeepSeek's window is far
#: larger -- they are BLAST-RADIUS limits. An occasional external write ("ab und
#: zu") is a scoped edit to a handful of files; a fan-out wider than this belongs
#: to Ikarus, where it can be planned and reviewed, not to a paid lane looping
#: over whatever path list it was handed. MAX_REWRITE_CHARS also caps what a
#: single request can put on an untrusted wire.
MAX_REWRITE_FILES = 3
MAX_REWRITE_CHARS = 24_000

#: Elision markers (per docs/RESEARCH_LOCAL_EDITING.md): a "full file" rewrite
#: containing one of these almost certainly dropped code instead of returning the
#: whole file. Only rejected when the marker is NEW (absent from the original),
#: so a file that legitimately contains the phrase is not permanently unwritable.
#: Kept as this module's own tuple rather than imported from the local-bench
#: provider: this is a claim about what an EXTERNAL model emits, and the two must
#: be free to diverge without one lane silently re-tuning the other's guard.
_ELISION_MARKERS = (
    "rest of the file", "rest of the code", "rest of code",
    "remains unchanged", "remain unchanged", "existing code here",
    "... existing code", "unchanged code omitted", "code omitted",
)

_REWRITE_SYSTEM = (
    "You are a careful software engineer. Apply the requested change and "
    'return ONLY a json object of the form {"content": "<ENTIRE edited file>"}. '
    "The value must be the complete file text -- every line, no omissions, "
    "no markdown fences, no commentary. Preserve the existing style."
)


class DeepSeekProvider(Provider):
    """Cheap external lane. NON-SENSITIVE ONLY: it may never receive denylisted
    (device/vendor/IP) content.

    Advisory by default, and write-capable ONLY when the operator opts in. Two
    independent things have to be true before a byte is written:

    * the repository names this lane in its policy ``external_write_lanes``
      (:func:`daedalus.config.resolve_external_write_lanes`), which is what
      makes :func:`daedalus.provider_router._mode` return "write"; and
    * the caller passes ``writable=True`` to :meth:`run`, which defaults to
      False so a caller that never heard of this feature cannot trigger it.

    Neither of those relaxes the egress fence. The rewrite prompt carries WHOLE
    FILE BODIES to a PRC-hosted API that trains on inputs, which is strictly
    more exposure than the advisory path's distilled context, so every file is
    re-classified individually before its body goes on the wire -- the run-level
    verdict is not treated as a per-file permit. Writes are additionally
    confined by ``path_write_blocked``, and every touched file is backed up
    byte-exactly for :meth:`rollback`.
    """

    caps = ProviderCapabilities(
        name="deepseek",
        # Honest capability, NOT authorization: the write path below is real, so
        # advertising False would be a lie to any caller that reads caps to
        # decide what this lane can be asked to do. Whether a given RUN may write
        # is a separate question, answered per run by `writable` -- see
        # `_enforce_read_only`, which is overridden here precisely because the
        # base class answers it from this (class-level) flag.
        can_write=True,
        local=False,
        trusted_with_ip=False,
        agentic=False,
    )

    def __init__(self) -> None:
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self.model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        # abs-path -> original bytes (None = newly created) for clean rollback.
        # Same contract as providers/ollama.py: the verifier's prose
        # before-image reads ORIGINAL BYTES out of this dict, so it must hold
        # the exact pre-write content and must be populated BEFORE the write.
        self._backups: dict[str, bytes | None] = {}
        self._created_dirs: list[str] = []
        self.rollback_failures: list[str] = []
        # GROUND TRUTH for run()'s own report: repo-relative paths THIS instance
        # actually wrote to disk. Never the model's self-reported files_changed.
        self._written: list[str] = []
        # Was THIS run granted write rights? Drives the advisory scrub below.
        self._writable = False

    def available(self) -> bool:
        return bool(self.api_key)

    def _enforce_read_only(self, report: dict[str, Any]) -> dict[str, Any]:
        """Run-scoped advisory scrub.

        :class:`~daedalus.providers.base.Provider` keys its scrub on the
        CLASS-level ``caps.can_write``, which is now True for this provider
        because the write path is real. Capability is not authorization: an
        ADVISORY run must still be scrubbed exactly as it was when this lane
        could not write at all, or a model's hallucinated ``files_changed``
        would start flowing downstream as though something had been applied.
        So the question is re-asked per run instead of per class.

        Same precedent as ``OllamaProvider.egress_lane``: ``caps`` states a fact
        about a NAME, and the instance knows the fact about THIS run. The body
        below is deliberately behaviour-identical to the base implementation for
        a non-writable run; ``tests`` pins it against the base so it cannot
        drift.
        """
        if self._writable:
            return report
        proposed = report.get("files_changed") or []
        handoff = report.get("handoff") or {}
        if proposed:
            handoff = {**handoff, "suggested_files": proposed}
        report["handoff"] = handoff
        report["files_changed"] = []
        report["tests_run"] = []
        if report.get("status") == "done":
            report["status"] = "needs_review"
        return report

    def rollback(self) -> list[str]:
        """Undo every write this instance made: restore originals, delete new
        files, remove dirs we created. Any path that can't be reverted is
        recorded in ``rollback_failures`` (the escalation is then 'dirty').

        Mirrors ``OllamaProvider.rollback``. Its existence is load-bearing well
        beyond tidiness: ``offload`` refuses to grant write rights at all to a
        provider without a callable ``rollback()``, so without this the toggle
        would route "write" and then be silently downgraded to advisory.
        """
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

    def _resolve(self, repo_root: str, rel: str) -> tuple[Path, str]:
        """Return (absolute target, repo-relative posix path). Raises if the
        resolved target escapes repo_root (traversal / symlink / absolute)."""
        root = Path(repo_root).resolve()
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise ValueError("path escapes repo root")
        return target, target.relative_to(root).as_posix()

    # -- write path: full-file rewrite -----------------------------------

    def _run_rewrite(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        model: str | None,
        timeout_s: int,
        policy: Any | None,
    ) -> dict[str, Any]:
        """One request per file: send the whole current file, write back the
        whole edited file. Same shape as the local bench's rewrite flow, with
        one deliberate difference -- every file passes an INDIVIDUAL egress
        check before its body is put on an untrusted wire.

        Each file costs one paid API call. The call goes through
        :func:`_openai_compat.chat_completion` for exactly that reason: budget
        accounting is interposed at ``urlopen``
        (``daedalus.budget._guarded_urlopen``), so every request here is priced
        and reserved individually and a bypass would need a new socket, not a
        new code path. Nothing in this method opens one.
        """
        changed: list[str] = []
        skipped: dict[str, str] = {}
        calls = 0
        for raw_rel in paths[:MAX_REWRITE_FILES]:
            try:
                target, rel = self._resolve(repo_root, raw_rel)
            except ValueError:
                skipped[str(raw_rel)] = "path escapes repo root"
                continue
            # WRITE confinement, on the RESOLVED path (guards traversal too).
            if path_write_blocked(rel, policy):
                skipped[rel] = ("protected path (device/vendor/secret/high-risk) "
                                "-- an external lane may not write here")
                continue
            creating = not target.exists()
            if not creating and not target.is_file():
                skipped[rel] = "not a file"
                continue
            if creating:
                original = ""
            else:
                # EGRESS, per file. The run-level verdict covered the DECLARED
                # path list; this is the check that governs the bytes actually
                # leaving. It is not redundant with it -- the rewrite prompt
                # carries the whole file body, which is strictly more than the
                # distilled context the run-level gate was weighed against, and
                # a denylisted file must be refused here exactly as this
                # provider's docstring promises.
                verdict = classify_data([rel], policy=policy)
                if verdict.sensitive:
                    skipped[rel] = ("refused egress: sensitive/proprietary content "
                                    "must not leave the machine (" +
                                    "; ".join(verdict.reasons)[:160] + ")")
                    continue
                try:
                    original = target.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    skipped[rel] = f"unreadable: {exc}"
                    continue
                egress_rule = slice_egress_rule(
                    rel, original, lane="untrusted", policy=policy)
                if egress_rule:
                    skipped[rel] = (
                        "refused egress: sensitive/proprietary content must not "
                        f"leave the machine ({egress_rule})")
                    continue
                if len(original) > MAX_REWRITE_CHARS:
                    skipped[rel] = "too large for full rewrite"
                    continue
            if creating:
                user = (f"Change request:\n{objective}\n\nFILE {rel} does NOT exist yet. "
                        "Create it: return the complete initial contents of this new file.")
            else:
                user = f"Change request:\n{objective}\n\nFILE {rel} (current contents):\n{original}"
            try:
                calls += 1
                raw = chat_completion(
                    base_url=self.base_url, model=model or self.model,
                    system=_REWRITE_SYSTEM, user=user, api_key=self.api_key,
                    timeout_s=timeout_s, force_json=True, temperature=0.0,
                )
                content = extract_json(raw).get("content")
            except (ProviderHTTPError, ValueError) as exc:
                skipped[rel] = f"model call failed: {exc}"
                continue
            if not isinstance(content, str) or not content.strip():
                skipped[rel] = "no content returned"
                continue
            if content == original:
                skipped[rel] = "no change produced"
                continue
            if not creating and len(content) < 0.5 * len(original):
                # classic full-rewrite failure mode: silent truncation
                skipped[rel] = "suspected truncation (under half the original size)"
                continue
            low_new, low_old = content.lower(), original.lower()
            elided = next((m for m in _ELISION_MARKERS if m in low_new and m not in low_old), None)
            if elided:
                skipped[rel] = f"elision marker in output ('{elided}') -- file not fully rewritten"
                continue
            # Backup BEFORE the write, exact bytes; None = created file, which
            # tells rollback to delete rather than restore. Parent dirs we
            # create are tracked so rollback can prune them too.
            try:
                self._backups.setdefault(
                    str(target), target.read_bytes() if target.exists() else None)
                root = Path(repo_root).resolve()
                for parent in [target.parent, *target.parent.parents]:
                    if parent == root:
                        break
                    if root in parent.parents and not parent.exists():
                        self._created_dirs.append(str(parent))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                skipped[rel] = f"cannot write: {exc}"
                continue
            changed.append(rel)
            self._written.append(rel)  # ground truth, never the model's claim

        summary = (f"DeepSeek applied full-file rewrite to: {', '.join(changed)}."
                   if changed else "DeepSeek rewrite produced no applicable change.")
        if skipped:
            summary += " Skipped: " + "; ".join(f"{k} ({v})" for k, v in skipped.items())
        handoff: dict[str, Any] = {"paid_calls": calls}
        if skipped:
            handoff["skipped"] = skipped
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
    ) -> dict[str, Any]:
        persona = persona_for(self.caps.name, agent.get("name"))
        # Per-call state. Reset here (not only in __init__) so an instance reused
        # across more than one run() never reports a PRIOR call's writes as this
        # one's, and never carries a stale write grant into an advisory run.
        self._written = []
        # A write needs the caller's grant AND a scoped path list. No paths means
        # nothing to rewrite; too many means a fan-out that belongs to Ikarus.
        self._writable = bool(writable) and bool(paths) and len(paths) <= MAX_REWRITE_FILES
        # Hard egress gate: refuse if the task itself is sensitive. Checked
        # BEFORE the write branch below, so a refused task never writes either.
        verdict = classify_data(paths, extra_text=objective, policy=policy)
        objective_floor = secret_floor_rule("", objective)
        path_floor_hits = [
            (str(path), rule)
            for path in paths
            if (rule := secret_floor_rule(str(path), str(path))) is not None
        ]
        if verdict.sensitive or objective_floor or path_floor_hits:
            reasons = list(verdict.reasons)
            if objective_floor:
                reasons.append(objective_floor)
            reasons.extend(f"{path}: {rule}" for path, rule in path_floor_hits)
            offending = list(dict.fromkeys(
                list(verdict.offending) + [path for path, _ in path_floor_hits]))
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": blocked_report(
                    "Refused: task contains sensitive/proprietary content that must "
                    "not leave the machine. " + "; ".join(reasons)[:300],
                    "Route this task to Claude or local Ollama.",
                    offending=offending,
                ),
            }

        if self._writable:
            # Opted-in write lane. Reports its OWN files_changed from real
            # on-disk writes, so it deliberately bypasses the advisory scrub
            # (which would empty exactly the field that is ground truth here).
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": self._run_rewrite(
                    objective=objective, repo_root=repo_root, paths=paths,
                    model=model, timeout_s=timeout_s, policy=policy,
                ),
            }

        context, skipped = read_inlined_context(
            paths, repo_root, MAX_CONTEXT_CHARS, allow_sensitive=False, policy=policy
        )
        system, user = build_prompt(agent, objective, context)
        try:
            kw = dict(base_url=self.base_url, model=model or self.model, system=system,
                      api_key=self.api_key, timeout_s=timeout_s, force_json=True, temperature=0.0)
            raw = chat_completion(user=user, **kw)
            try:
                report = coerce_report(extract_json(raw))
            except ValueError:
                # exactly one deterministic re-ask for valid JSON before escalating
                raw = chat_completion(user=user + "\n\nReturn ONLY the json object, no prose.", **kw)
                report = coerce_report(extract_json(raw))
        except (ProviderHTTPError, ValueError) as exc:
            return {
                "provider": self.caps.name,
                "persona": persona,
                "agent": agent.get("name"),
                "report": blocked_report(
                    f"DeepSeek call failed: {exc}", "Retry or fall back to Claude."
                ),
            }

        report = self._enforce_read_only(report)
        if skipped:
            report["handoff"] = {**report.get("handoff", {}), "skipped_sensitive": skipped}
        return {
            "provider": self.caps.name,
            "persona": persona,
            "agent": agent.get("name"),
            "report": report,
        }
