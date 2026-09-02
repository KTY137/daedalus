"""Verifier gate -- the cascade's quality check.

Before a local-model result is *accepted*, it must pass cheap deterministic
checks. This is what turns risk-tier routing into a real FrugalGPT cascade and
closes the "silent escalation" hole: bad local output is caught here and
escalated to Claude instead of being shipped or looping forever.

Checks (fast by default): report schema validity + Python syntax of any files
the worker wrote. The project's test suite is opt-in (pass ``test_command``),
since running it on every small edit is too slow.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..limit_policy import ExecutionLimitPolicy
from ..preservation import check_preservation, is_prose_path
from ..runtimes.contracts.provider_report import validate_report

# How long the project suite may run before we kill it. This is a RUNAWAY
# guard, not a performance budget: its job is to stop a wedged test process
# from pinning the harness forever, not to express an opinion about how fast a
# repo's suite ought to be. Repos whose suite legitimately needs longer declare
# ``test_timeout_s`` in their project config; the default must stay 120 so that
# adding that knob does not silently re-time every other repo's gate.
DEFAULT_TEST_TIMEOUT_S = 120

#: Per-check ``status`` values that mean THE CHECK NEVER REACHED A VERDICT about
#: the candidate. A check that timed out, blew up, or had no evidence to work
#: with has said nothing about whether the write is good -- it has only said
#: that we do not know. Every one of them still blocks (``ok=False``), because
#: unknown is not permission; what they must never do is get RECORDED as "the
#: model broke it".
#:
#: Why this is a constant and not a string test at each call site: the accept /
#: reject gate is one function, but the reason a rejection happened is consumed
#: somewhere else entirely -- routing metrics, the escalation note, the queue's
#: verdict. Today exactly one caller (``offload``) remembers to dig ``status``
#: out of the ``tests`` check by name; a second caller reintroduces the conflation
#: by construction rather than by mistake, because nothing tells it the
#: distinction exists. Measured cost of getting it wrong, from the concurrency
#: review: under load a suite overruns its budget, a GOOD patch is rolled back
#: and the task escalates to a PAID lane, and the local lane's statistics record
#: a correctness failure it did not commit.
INCONCLUSIVE_STATUSES = frozenset({"timeout", "error", "unknown", "unavailable"})


def _check_status(check: dict) -> str:
    """The status of a check, defaulted for checks that declare none."""
    status = check.get("status")
    if status:
        return str(status)
    return "pass" if check.get("ok") else "fail"


@dataclass
class VerifyResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [c["name"] for c in self.checks if not c["ok"]]

    @property
    def inconclusive(self) -> list[str]:
        """Names of blocking checks that never reached a verdict.

        A non-empty list with ``ok is False`` means "we could not tell", which is
        a different diagnosis from "the write is bad" and must be routed as one.
        """
        return [c["name"] for c in self.checks
                if not c["ok"] and _check_status(c) in INCONCLUSIVE_STATUSES]

    @property
    def verdict(self) -> str:
        """``pass`` / ``fail`` / ``inconclusive`` -- the routing-grade answer.

        ``fail`` wins over ``inconclusive`` when both are present: a check that
        DID reach a verdict and said no is a real finding about the candidate,
        and a timeout elsewhere in the same run does not soften it. Only when
        every blocking check is inconclusive is the whole run inconclusive.

        ``ok`` keeps its exact old meaning and is still the accept/reject bit.
        Nothing here may ever read ``inconclusive`` as permission to proceed.
        """
        if self.ok:
            return "pass"
        return "inconclusive" if len(self.inconclusive) == len(self.failed) else "fail"

    def reason_note(self) -> str:
        """One comma-separated line naming each blocking check AND its status.

        This is the string metrics and escalation records should carry. It is a
        method on the result rather than a comprehension at the call site so the
        next caller cannot forget that a status exists -- see
        :data:`INCONCLUSIVE_STATUSES`.
        """
        return ",".join(
            f"{c['name']}:{_check_status(c)}" if _check_status(c) != "fail"
            else str(c["name"])
            for c in self.checks if not c["ok"])

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks, "failed": self.failed,
                "verdict": self.verdict, "inconclusive": self.inconclusive}


def _py_compile(repo_root: str, rel: str) -> tuple[bool, str]:
    target = Path(repo_root) / rel
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    return proc.returncode == 0, (proc.stderr.strip()[:300] or "ok")


def _lint_py(repo_root: str, rel: str) -> tuple[bool, str]:
    """Best-effort static lint of a changed .py file -- catches undefined names
    and unused imports that py_compile (syntax-only) misses. Prefers ruff, falls
    back to pyflakes; if NEITHER is installed it skips cleanly (never blocks a
    write on a missing dev tool). Only a real lint error fails the gate."""
    import shutil
    target = str(Path(repo_root) / rel)
    if shutil.which("ruff"):
        cmd = ["ruff", "check", "--quiet", "--select", "E,F", target]
    else:
        try:
            import pyflakes  # noqa: F401
        except ImportError:
            return True, "no linter (ruff/pyflakes) -- skipped"
        cmd = [sys.executable, "-m", "pyflakes", target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=30, cwd=repo_root)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"lint unavailable ({exc}) -- skipped"
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (" | ".join(lines[-3:])[:300] or "clean")


def _js_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Syntax-check a written .js file via `node --check` when node is on PATH;
    skip cleanly otherwise (never block a write on a missing dev tool)."""
    import shutil
    node = shutil.which("node")
    if not node:
        return True, "node not on PATH -- skipped"
    try:
        proc = subprocess.run([node, "--check", str(Path(repo_root) / rel)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"node check unavailable ({exc}) -- skipped"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-2:]
    return proc.returncode == 0, (" | ".join(tail)[:300] or "ok")


def _html_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Cheap structural gate for a written .html file. The dominant local-model
    failure is TRUNCATION (file cut off mid-tag), which shows up as unbalanced
    <script>/<style> containers or an empty file -- both break rendering hard.
    This is a truncation tripwire, not a full validator."""
    import re
    try:
        text = (Path(repo_root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"cannot read: {exc}"[:200]
    if not text.strip():
        return False, "empty html file"
    for tag in ("script", "style"):
        opens = len(re.findall(rf"<{tag}\b[^>]*>", text, re.I))
        closes = len(re.findall(rf"</{tag}\s*>", text, re.I))
        if opens != closes:
            return False, f"unbalanced <{tag}> tags ({opens} open / {closes} close) -- truncated output?"
    if text.rstrip().endswith(("<", "</")):
        return False, "file ends mid-tag -- truncated output"
    return True, "non-empty, script/style balanced"


def _config_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Parse a written .json/.yaml file so a corrupted config is caught."""
    try:
        text = (Path(repo_root) / rel).read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"cannot read: {exc}"[:200]
    if rel.endswith(".json"):
        try:
            json.loads(text)
            return True, "valid json"
        except json.JSONDecodeError as exc:
            return False, f"invalid json: {exc}"[:200]
    try:
        import yaml  # optional; skip cleanly if the parser isn't installed
    except ImportError:
        return True, "yaml parser unavailable -- skipped"
    try:
        yaml.safe_load(text)
        return True, "valid yaml"
    except yaml.YAMLError as exc:
        return False, f"invalid yaml: {exc}"[:200]


def _norm_rel(rel: object) -> str:
    """Repo-relative, forward slashes, no ``./`` prefix."""
    text = str(rel).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def prose_before_images(backups: "dict[str, bytes | None] | None",
                        repo_root: str) -> dict[str, str | None]:
    """Turn a writer's rollback backups into before-images for :func:`verify`.

    The provider that performs local writes already keeps the exact original
    bytes of every file it touched, because it needs them to roll back. Those
    bytes -- not ``git show HEAD:``, not a re-read -- are the only truthful
    before-image: they are what the file said at the instant before the write,
    which is the question the preservation tripwire asks. A working tree that
    was already dirty makes HEAD a lie, and a re-read after the fact returns the
    damage rather than the original.

    Keys are absolute paths (as the writer records them) and come back
    repo-relative. A value of ``None`` means the file did NOT exist before, which
    the prose check reads as "created" rather than as missing evidence.
    """
    out: dict[str, str | None] = {}
    if not backups:
        return out
    root = Path(repo_root).resolve()
    for abs_path, original in backups.items():
        try:
            rel = Path(abs_path).resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            rel = _norm_rel(abs_path)
        if original is None:
            out[rel] = None
        else:
            try:
                out[rel] = original.decode("utf-8", errors="replace")
            except (AttributeError, UnicodeError):
                out[rel] = None
    return out


def _prose_check(repo_root: str, rel: str,
                 prose_before: "dict[str, str | None] | None"
                 ) -> tuple[bool, str, str]:
    """Fact-preservation tripwire for a written prose file. ``(ok, detail, status)``.

    WHY THIS BRANCH EXISTS. The dispatch below judges ``.py``, ``.json``,
    ``.js`` and ``.html``. Prose fell off the end of that chain, so a ``.md``
    write was accepted on "the report parsed and a file changed" -- the empty
    green the rest of this harness exists to refuse. The installed local write
    policy permits ``docs/``, ``tests/`` and ``README.md``, so prose is not a
    corner of the local lane, it is most of it.

    MEASURED failure it catches (qwen2.5-coder:7b rewriting
    ``docs/LOCAL_MODELS.md`` under an instruction to keep every fact): "pointed
    at an OpenAI-compatible endpoint via three env vars" became "configured via
    three environment variables". That sentence carries no markdown at all, so
    nothing structural would ever have seen it go.

    FAIL CLOSED, AND SAY WHICH KIND OF NOT-OK IT IS. Without a before-image
    there is nothing to compare, so the check cannot run -- and a check that
    cannot run must not be reported as a check that ran and passed. It blocks
    with ``status="unknown"``, which :class:`VerifyResult` classifies as
    inconclusive so the local lane is not blamed for a verdict nobody reached.
    """
    key = _norm_rel(rel)
    if prose_before is None or key not in prose_before:
        return False, (
            "no before-image of this file was captured, so the fact-preservation "
            "tripwire COULD NOT RUN. This is not a finding about the write -- it "
            "is the absence of one. Pass prose_before= (see prose_before_images) "
            "to make prose verifiable; until then a prose write is refused rather "
            "than accepted unchecked."), "unknown"

    before = prose_before[key]
    if before is None:
        return True, "file did not exist before this write -- nothing could be lost", "created"

    target = Path(repo_root) / key
    if target.exists():
        try:
            after = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return False, f"cannot read written prose file: {exc}"[:200], "unreadable"
    else:
        # Deleted. Not an error and not missing evidence: every fact the file
        # carried really is gone, and check_preservation says so precisely.
        after = ""

    result = check_preservation(before, after)
    if result.ok:
        return True, result.summary(), "checked"

    # A stale code reference is the one intentional deletion the docref lane
    # exists to make. The generic preservation tripwire sees the old inline
    # identifier disappear and calls it LOST; the docref gate sees the same
    # event as either ``fixed`` or ``claim_withdrawn``. Requiring both without
    # reconciling them made every correct docref edit structurally impossible:
    # the full suite passed, then preservation rolled the patch back before the
    # curated docref gate could judge it.
    #
    # Waive ONLY blocking inline-code losses that are independently proven to
    # have been broken in the before-image, whose fixes keep the resolving
    # denominator intact. Any other lost fact remains blocking.
    blocking = result.blocking
    lost_code = [f for f in blocking if f.kind == "code"]
    if lost_code and len(lost_code) == len(blocking):
        try:
            from ..spine.docrefs import scan, verify_fixes

            before_report = scan(repo_root, overrides={key: before})
            targets = [
                ref for ref in before_report.broken
                if ref.doc_path == key
                and any(ref.raw == finding.artefact for finding in lost_code)
            ]
            expected = {finding.artefact for finding in lost_code}
            found = {ref.raw for ref in targets}
            after_report = scan(repo_root)
            allowed, verdicts = verify_fixes(
                before_report.n_resolving, after_report, targets)
        except Exception:  # an unavailable proof is not a waiver
            allowed, verdicts, expected, found = False, (), set(), set()
        if allowed and found == expected:
            kinds = ", ".join(v.verdict for v in verdicts)
            return True, (
                f"{result.summary()} | allowed docref correction(s): {kinds}; "
                f"resolving {before_report.n_resolving}->{after_report.n_resolving}"
            ), "checked"

    return False, result.summary(), "checked"


def _effective_timeout(timeout_s: object) -> int | float:
    """Coerce a project-declared ``test_timeout_s`` to a usable positive budget.

    Fail-SAFE, not fail-open: a junk or non-positive value falls back to the
    default rather than to "no timeout". ``subprocess.run(timeout=None)`` waits
    forever, so treating a malformed config as "unlimited" would turn a typo
    into a wedged harness -- the one outcome a runaway guard exists to prevent.
    A ``0`` is likewise not honoured literally: it would expire instantly and
    make every gate report a timeout, silently disabling the local lane.

    A positive value is passed through EXACTLY, never truncated to int:
    ``int(0.5)`` is ``0``, which would quietly convert a small fractional
    budget into the instant-expiry case this function exists to reject.
    ``subprocess.run`` accepts a float timeout, so there is nothing to gain by
    rounding. ``bool`` is excluded because ``True`` is an ``int`` of value 1 and
    a config that says ``true`` means a typo, not a one-second suite.
    """
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        return DEFAULT_TEST_TIMEOUT_S
    return timeout_s if timeout_s > 0 else DEFAULT_TEST_TIMEOUT_S


def _run_tests(
    test_command: str, cwd: str, timeout_s: int | float | None
) -> tuple[bool, str, str]:
    """Run the project suite. Returns ``(ok, detail, status)``.

    ``status`` is the MACHINE-READABLE outcome and is deliberately finer than
    ``ok``: ``pass`` / ``fail`` / ``timeout`` / ``error``.

    Why it must not collapse into ``ok``: a red suite means the write under
    verification is bad, whereas a timeout means *we* set the budget too low
    for a suite that never got to finish. Both must block the write -- but they
    are opposite diagnoses, and the escalation they trigger is recorded against
    the local lane's routing metrics. Reporting a budget shortfall as "the
    local model broke the tests" teaches the router to distrust a lane that did
    nothing wrong. Every non-``pass`` status is ``ok=False``; nothing here may
    ever read a timeout as a pass.
    """
    try:
        proc = subprocess.run(
            shlex.split(test_command), cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"tests did not finish within the {timeout_s}s budget and were killed. "
            f"This is NOT a test failure -- the suite never reported a verdict. "
            f"Raise 'test_timeout_s' in the project config or narrow 'test_command'."
        )[:300], "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run tests: {exc}"[:300], "error"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    ok = proc.returncode == 0
    return ok, " | ".join(tail)[:300], ("pass" if ok else "fail")


def verify(
    report: dict,
    repo_root: str,
    *,
    test_command: str | None = None,
    test_cwd: str | None = None,
    timeout_s: int | float = DEFAULT_TEST_TIMEOUT_S,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
    require_changes: bool = False,
    disk_changed: list[str] | None = None,
    prose_before: dict[str, str | None] | None = None,
) -> VerifyResult:
    checks: list[dict] = []

    errs = validate_report(report)
    checks.append({"name": "schema", "ok": not errs, "detail": "; ".join(errs) or "valid"})

    # Close the silent-ACCEPTANCE hole: a write-mode task that produced no file
    # changes is a no-op (small models often narrate "I edited X" without ever
    # calling the write tool). Accepting it fakes 100% savings while nothing got
    # done -- so the work would silently be lost. Fail it -> escalate to Claude.
    #
    # CRITICAL: ``report["files_changed"]`` is the model's SELF-REPORT and a
    # narrating model claims edits it never wrote (the exact fake-offload repro).
    # When the caller has real evidence -- content-hash diffs of the target paths
    # taken before/after the run, passed as ``disk_changed`` -- that verified list
    # is the ONLY thing that may satisfy the gate; the self-report is ignored.
    # ``disk_changed is None`` means the caller supplied no evidence (e.g. a
    # direct/unit call); we fall back to the self-report there, but the live
    # offload seam ALWAYS supplies ``disk_changed`` so production never trusts it.
    if require_changes:
        if disk_changed is not None:
            did_write = bool(disk_changed)
            detail = (f"verified on disk: {', '.join(disk_changed)}" if did_write else
                      "write task changed NO files on disk -- model narrated an edit "
                      "without writing (self-reported files_changed is not trusted)")
        else:
            did_write = bool(report.get("files_changed"))
            detail = ("wrote files (self-report; no disk evidence supplied)" if did_write else
                      "write task produced NO file changes (model narrated instead of editing)")
        checks.append({"name": "did_work", "ok": did_write, "detail": detail})

    # WHICH FILES GET CHECKED. Same argument as did_work directly above, applied
    # one loop lower: this used to iterate ``report["files_changed"]``, the
    # model's SELF-REPORT. That let a writer dodge every per-file check by
    # writing to disk and reporting nothing -- did_work passed on the disk diff
    # while the dispatch below saw an empty list and ran no check at all. When
    # the caller has real evidence, the evidence is the work list; the
    # self-report is only used when there is none (advisory / direct unit calls,
    # where nothing was written and the list is a draft's claim).
    changed = ([_norm_rel(r) for r in disk_changed] if disk_changed is not None
               else [_norm_rel(r) for r in report.get("files_changed", [])])

    for rel in changed:
        s = str(rel)
        if is_prose_path(s):
            # Only in write mode: outside it nothing was written, so there is no
            # after-image to judge and the path is a draft's claim, not an edit.
            if require_changes:
                ok, detail, status = _prose_check(repo_root, s, prose_before)
                checks.append({"name": f"prose:{s}", "ok": ok,
                               "status": status, "detail": detail})
        elif s.endswith(".py"):
            ok, detail = _py_compile(repo_root, s)
            checks.append({"name": f"syntax:{s}", "ok": ok, "detail": detail})
            lok, ldetail = _lint_py(repo_root, s)
            checks.append({"name": f"lint:{s}", "ok": lok, "detail": ldetail})
        elif s.endswith((".json", ".yaml", ".yml")):
            ok, detail = _config_check(repo_root, s)
            checks.append({"name": f"parse:{s}", "ok": ok, "detail": detail})
        elif s.endswith((".js", ".mjs", ".cjs")):
            ok, detail = _js_check(repo_root, s)
            checks.append({"name": f"jscheck:{s}", "ok": ok, "detail": detail})
        elif s.endswith((".html", ".htm")):
            ok, detail = _html_check(repo_root, s)
            checks.append({"name": f"htmlcheck:{s}", "ok": ok, "detail": detail})

    if test_command:
        import os
        # test_cwd is relative to the TARGET repo, not the offload process cwd.
        cwd = repo_root if test_cwd in (None, "", ".") else os.path.join(repo_root, test_cwd)
        limit_policy = execution_limit_policy or ExecutionLimitPolicy()
        if not isinstance(limit_policy, ExecutionLimitPolicy):
            raise TypeError(
                "execution_limit_policy must be an ExecutionLimitPolicy"
            )
        budget = (
            _effective_timeout(timeout_s)
            if limit_policy.enforces("wall_time") else None
        )
        ok, detail, status = _run_tests(test_command, cwd, budget)
        # ``status`` rides alongside ``ok`` so a consumer can tell a red suite
        # from a budget shortfall without string-matching English out of a
        # 300-char-truncated ``detail``. ``ok`` keeps its exact old meaning.
        checks.append({"name": "tests", "ok": ok, "status": status,
                       "timeout_s": budget,
                       "wall_time_ceiling_enabled": (
                           limit_policy.enforces("wall_time")
                       ),
                       "execution_limit_policy_sha256": (
                           limit_policy.fingerprint_sha256
                       ),
                       "detail": detail})

    return VerifyResult(ok=all(c["ok"] for c in checks), checks=checks)
