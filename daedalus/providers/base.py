from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider is *allowed* and *able* to do. These are structural
    guarantees enforced by the harness, not promises the model must keep."""

    name: str
    can_write: bool         # may mutate the repo (apply edits / run tools)
    local: bool             # runs on this machine; no network egress at all
    trusted_with_ip: bool   # approved to receive proprietary/sensitive source
    agentic: bool           # can read the repo itself vs. needs inlined context


class Provider(abc.ABC):
    """Common interface for every model backend. All providers return the same
    validated ``agent_report_v1`` dict so everything downstream is uniform."""

    caps: ProviderCapabilities

    @abc.abstractmethod
    def available(self) -> bool:
        """True if this provider can be reached right now (key set / server up)."""

    @abc.abstractmethod
    def run(
        self,
        *,
        objective: str,
        repo_root: str,
        paths: list[str],
        agent: dict[str, Any],
        model: str | None = None,
        timeout_s: int | float | None = 300,
        policy: Any | None = None,
        execution_limit_policy: Any | None = None,
    ) -> dict[str, Any]:
        """Execute under one captured limit policy and return a report."""

    # -- shared helpers ---------------------------------------------------

    def _rollback_writes(self) -> list[str]:
        """THE restore loop, for every write-capable provider. One copy.

        Undo every write the instance made: restore originals, delete files it
        created, remove directories it created. Any path that cannot be
        reverted is recorded in ``rollback_failures`` (the escalation is then
        'dirty'), and one unrestorable path never aborts the rest.

        The instance supplies the state, and the contract is the same wherever
        this is used:

        * ``_backups``: absolute path -> original bytes, or ``None`` for a file
          that did not exist before (rollback deletes it rather than restoring
          it). It must be populated BEFORE the write, with the exact pre-write
          bytes -- the verifier's prose before-image reads originals out of
          this dict, so a late or lossy entry corrupts more than the undo.
        * ``_created_dirs``: absolute paths of directories the write created;
          pruned deepest-first and only while empty.
        * ``rollback_failures``: rebound to a fresh list per call, then filled
          with the paths that could not be reverted.

        This lived twice -- ``DeepSeekProvider.rollback`` and
        ``OllamaProvider.rollback`` held AST- and bytecode-identical bodies in
        two files, differing only in their docstrings. That is the undo path
        for the external write lane that, on 2026-07-30, wrote one file's
        content into another and destroyed three of five modules while
        reporting success; a second copy of it is a second thing to get wrong
        in the one place that has to be right when everything else already
        went wrong. ``tests/test_provider_rollback_single_source.py`` keeps the
        copy from coming back.

        Its existence is load-bearing beyond tidiness: ``offload`` refuses to
        grant write rights at all to a provider without a callable
        ``rollback()``, so a provider that loses it routes "write" and is then
        silently downgraded to advisory.
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

    def _enforce_read_only(self, report: dict[str, Any]) -> dict[str, Any]:
        """A read-only provider can neither edit files nor run tests. Any change
        it proposes is advisory: it is moved into ``handoff.suggested_files``
        and the mutating fields are forced empty so nothing can be auto-applied.

        The key is ``suggested_files``. This docstring said ``handoff.suggestions``
        for as long as it existed, seven lines above the assignment that writes
        the real name, and no such key is produced anywhere in the repository --
        so a reader who trusted it searched for a field that has never existed
        and found nothing, silently. The written contract is
        ``suggested_files``: :meth:`daedalus.providers.deepseek` writes it, and
        ``tests/test_hardening.py`` and ``tests/test_deepseek_write_toggle.py``
        assert on it by that name.
        """
        if self.caps.can_write:
            return report
        proposed = report.get("files_changed") or []
        handoff = report.get("handoff") or {}
        if proposed:
            handoff = {**handoff, "suggested_files": proposed}
        report["handoff"] = handoff
        report["files_changed"] = []
        report["tests_run"] = []
        if report.get("status") == "done":
            # A model that cannot write cannot legitimately be "done" applying a
            # change; downgrade to advisory review.
            report["status"] = "needs_review"
        return report
