from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from ..lanes import BASELINE_POLICY, WriteAttempt, render_brief, run_checks
from ..lanes.checks import toplevel_defs as _shared_toplevel_defs
from ..lanes.checks import (
    not_substituted as _shared_not_substituted,
    unresolved_first_party_imports as _shared_unresolved_first_party_imports,
)
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

#: Notes are a side channel, not a report. Capping per file keeps a chatty model
#: from burying the one useful observation under twenty restatements of the diff.
MAX_NOTES_PER_FILE = 6

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

#: This lane's own policy over the shared daedalus.lanes baseline -- see
#: providers/ollama.py's identical construction and daedalus/lanes/__init__.py
#: for why the marker tuple is local while everything else is shared.
_CHECK_POLICY = dataclasses.replace(BASELINE_POLICY, elision_markers=_ELISION_MARKERS)

#: Below this many top-level definitions, the survival ratio is noise -- losing
#: one of two functions is an ordinary edit, not a substitution. Re-exported
#: from the shared baseline (below) so existing callers naming this constant
#: keep working; it is no longer this module's own number.
_MIN_SYMBOLS_TO_JUDGE = BASELINE_POLICY.min_symbols_to_judge

#: Import roots that belong to THIS repository. Re-exported from the shared
#: baseline for the same reason.
_FIRST_PARTY = BASELINE_POLICY.first_party_roots


# --------------------------------------------------------------------------
# The three guards below (substitution, unresolved imports, and the AST helper
# they share) used to be defined here, and ONLY here. MEASURED 2026-07-30: the
# night two of them were added, they went into this file and not into
# ``providers/ollama.py``, and within hours the free local default lane was
# strictly weaker than the paid external one for the exact two failures just
# measured. Per-provider copies drift the moment one of them improves.
#
# They now live in ``daedalus.lanes.checks`` as the shared baseline every write
# lane runs, and are re-exported here under their original names so this
# module's own tests and any external caller of these private functions keep
# working unchanged. The docstrings, the measurements, and the thresholds moved
# with them -- read them there.
# --------------------------------------------------------------------------

def _toplevel_defs(source: str) -> frozenset | None:
    return _shared_toplevel_defs(source)


def _substitution_reason(rel: str, original: str, content: str) -> str:
    return _shared_not_substituted(
        WriteAttempt(rel=rel, proposed=content, repo_root=".", original=original),
        BASELINE_POLICY)


def _unresolved_first_party_imports(content: str, repo_root: str) -> list[str]:
    return _shared_unresolved_first_party_imports(content, repo_root, _FIRST_PARTY)


_REWRITE_SYSTEM = (
    "You are a careful software engineer. Apply the requested change and "
    'return ONLY a json object of the form {"content": "<ENTIRE edited file>"}. '
    "The value must be the complete file text -- every line, no omissions, "
    "no markdown fences, no commentary. Preserve the existing style.\n"
    # MEASURED 2026-07-30. A change request naming two files ("add tests for
    # shift.py in tests/test_shift.py") is sent once PER FILE, and the model
    # answered the REQUEST rather than the FILE: asked to rewrite
    # daedalus/shift.py it returned the test module, destroying the real one.
    # Three of five multi-file writes failed this way, each reporting success.
    # The output must be bound to the file that was sent, not to whichever file
    # the prose happens to mention.
    "The change request may mention SEVERAL files. You are being asked about "
    "exactly ONE of them, named below, and you are rewriting only that one. "
    "Return the new contents of THAT file and nothing else -- never the "
    "contents intended for a different file, even when the request describes "
    "one. If the request asks for nothing that belongs in this particular "
    "file, return its current contents unchanged.\n"
    # MEASURED 2026-07-30. Eight agents were sent to REVIEW code with
    # writable=True and returned zero findings between them -- not because they
    # found nothing, but because this path parsed only "content" and hard-coded
    # the report's risks and todos to empty. Whatever they observed was
    # discarded before anyone could read it. An optional second key costs one
    # line and gives the lane back a voice.
    'You may ALSO include an optional key "notes": a list of short strings, '
    "each one thing you noticed about this file that the caller should know -- "
    "a bug you saw but did not fix, a guarantee the docstring makes that the "
    "code does not keep, something the request asked for that does not belong "
    "in this file. Notes are reported to the caller; they never affect what is "
    "written. Omit the key entirely if you have nothing to say, and never pad "
    "it -- an empty list is a perfectly good answer and more useful than "
    "filler."
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

        The restore loop itself is :meth:`Provider._rollback_writes` -- ONE
        implementation, shared with ``OllamaProvider.rollback``, which used to
        hold a byte-identical copy of it. This method stays as the named
        public entrypoint: ``offload`` refuses to grant write rights at all to
        a provider without a callable ``rollback()``, and the Gate-0 effect
        registry resolves ``provider.deepseek.rollback`` to this exact
        module-and-qualname by static AST lookup.
        """
        return self._rollback_writes()

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
        #: What the lane OBSERVED while rewriting, as opposed to what it wrote.
        #: Without this the writable branch has no way to report anything at all.
        notes: list[str] = []
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
            # The path is named BEFORE the change request as well as after it.
            # Measured: with the file named only after a multi-file objective,
            # the model answered the objective and returned another file's
            # contents. Leading with the target makes it the frame the request
            # is read inside rather than a detail at the end of it.
            #
            # MEASURED 2026-07-30: three of seven agent-written files imported
            # something that does not exist under the name they guessed
            # (``daedalus.linting`` for ``daedalus.gui.lint``, ``ShiftManager``
            # for ``Shift``, ``daedalus.wiki_vault`` for ``daedalus.wiki.vault``)
            # -- in every case the real thing existed, just not where the model
            # guessed. No provider module gave it anywhere to look this up; the
            # brief is that lookup. Failure to build it must never block a
            # write, so a brief-less prompt (empty string) degrades to the
            # pre-brief behaviour rather than failing the call.
            brief = render_brief(repo_root, [rel], hops=1)
            brief_block = f"\n\n{brief}" if brief else ""
            if creating:
                user = (f"You are creating exactly one file: {rel}\n\n"
                        f"Change request:\n{objective}\n\n"
                        f"FILE {rel} does NOT exist yet. Return the complete "
                        "initial contents of THIS file only."
                        f"{brief_block}")
            else:
                user = (f"You are rewriting exactly one file: {rel}\n\n"
                        f"Change request:\n{objective}\n\n"
                        f"FILE {rel} (current contents):\n{original}\n\n"
                        f"Return the complete new contents of {rel}."
                        f"{brief_block}")
            try:
                calls += 1
                raw = chat_completion(
                    base_url=self.base_url, model=model or self.model,
                    system=_REWRITE_SYSTEM, user=user, api_key=self.api_key,
                    timeout_s=timeout_s, force_json=True, temperature=0.0,
                )
                parsed = extract_json(raw)
                content = parsed.get("content")
                # Collected BEFORE any of the guards below can `continue` past
                # this file: a note explaining why a rewrite was refused is
                # exactly the note worth keeping.
                for note in (parsed.get("notes") or [])[:MAX_NOTES_PER_FILE]:
                    if isinstance(note, str) and len(note.strip()) >= 8:
                        notes.append(f"{rel}: {note.strip()[:400]}")
            except (ProviderHTTPError, ValueError) as exc:
                skipped[rel] = f"model call failed: {exc}"
                continue
            if not isinstance(content, str) or not content.strip():
                skipped[rel] = "no content returned"
                continue
            if content == original:
                skipped[rel] = "no change produced"
                continue
            # Shared baseline (daedalus.lanes): truncation, parses, content
            # substitution, unresolved first-party imports -- cheapest and most
            # specific refusal first. This lane's own elision markers ride along
            # via _CHECK_POLICY; see daedalus/lanes/__init__.py for why the
            # marker tuple stays local while the rest is shared.
            refusal = run_checks(WriteAttempt(
                rel=rel, proposed=content, repo_root=repo_root,
                original=original, creating=creating,
            ), policy=_CHECK_POLICY)
            if refusal:
                skipped[rel] = refusal
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
            # No longer hard-coded empty. A writable run that noticed something
            # can now say so; a run that noticed nothing still reports nothing,
            # which is the honest default rather than a manufactured finding.
            "risks": notes,
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
        #: Replace the whole system message. ``None`` keeps ``build_prompt``'s,
        #: so no existing caller changes. See the comment at the call site for
        #: why an audit lane needs its own -- the default stack forbids
        #: chain-of-thought and demonstrates an empty findings list.
        system_override: str | None = None,
        #: Decode temperature. 0.0 (the default, and what every caller had) makes
        #: N samples of one prompt IDENTICAL -- so a fan-out asking the same
        #: question three "independent" times at 0.0 buys one answer counted
        #: three times. Corroboration needs > 0.
        temperature: float = 0.0,
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
        # LANE-SPECIFIC SYSTEM PROMPT, opt-in. MEASURED 2026-07-30: an audit fan-out
        # over 169 modules returned 2 findings from 715 answers, and the cause was
        # one layer above the question. ``build_prompt`` prepends
        # ``token_policy.STATIC_PROMPT_PREFIX``, which says "Minimize tokens ...
        # Prefer short summaries ... **Do not include chain-of-thought; include
        # only conclusions and evidence**", and appends ``report_instructions()``,
        # whose worked example shows ``"risks": []``.
        #
        # That stack is correct for the bridge protocol it was written for and
        # wrong for a review task: every defect worth finding (prose contradicting
        # code, a guard that cannot fire, an unreachable branch) is a multi-step
        # COMPARISON, and the highest-authority message in the request forbade the
        # scratchpad while demonstrating the empty answer. No wording of the user
        # prompt can outrank that.
        #
        # Defaults leave every existing caller byte-identical: ``None`` keeps the
        # built prompt, ``0.0`` keeps the deterministic decode.
        if system_override:
            system = system_override
        try:
            kw = dict(base_url=self.base_url, model=model or self.model, system=system,
                      api_key=self.api_key, timeout_s=timeout_s, force_json=True,
                      temperature=temperature)
            raw = chat_completion(user=user, **kw)
            repairs: list[str] = []
            try:
                report = coerce_report(extract_json(raw, repairs=repairs))
            except ValueError:
                # exactly one deterministic re-ask for valid JSON before escalating
                raw = chat_completion(user=user + "\n\nReturn ONLY the json object, no prose.", **kw)
                report = coerce_report(extract_json(raw, repairs=repairs))
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
        if repairs:
            # An answer that only parsed after the harness doubled its invalid
            # escapes is evidence of a different grade than one that parsed
            # clean; the consumer decides what that means, but only if told.
            report["handoff"] = {**report.get("handoff", {}), "harness_repairs": repairs}
        if skipped:
            report["handoff"] = {**report.get("handoff", {}), "skipped_sensitive": skipped}
        return {
            "provider": self.caps.name,
            "persona": persona,
            "agent": agent.get("name"),
            "report": report,
        }
