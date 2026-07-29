"""Does the spend ceiling actually cover the ways OUT of this machine?

``tests/test_budget.py`` asks "is every billable site in the register". This
file asks the two questions that one cannot:

1. **Does the guard exist in the process that spends?** The ceiling is not a
   syscall hook. It is three monkeypatched Python functions
   (``subprocess.run``, ``subprocess.Popen``, ``urllib.request.urlopen``)
   installed by exactly one call, in exactly one function -- ``daedalus.cli
   :main``. Any OTHER way to start a Python process that spends money is
   entirely outside the ceiling. MEASURED 2026-07-29: five in-repo entry points
   are, plus the out-of-repo ``~/.claude/skills/room/room.py``.

2. **Can the classifier still recognise the vendor once it is wrapped?** The
   guard only bills what ``classify_argv`` names. A vendor reached through a
   process shepherd the classifier has never heard of is spawned for free.

Both halves are drift detectors with declared ledgers, not aspirational
assertions: they are GREEN today against a named list of known holes and go RED
the moment a new one appears. The holes themselves are written up in
``docs/SPEND_AND_EGRESS_COVERAGE.md``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus import budget as B

ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# 1. THE CLASSIFIER -- a vendor behind a wrapper is still a vendor
# ===========================================================================

# Every one of these was MEASURED to return None before the 2026-07-29 fix, on
# a machine where `uv`, `uvx`, `npx` and `codex` are all installed. The comment
# on each is why the shape is realistic rather than adversarial.
WRAPPED_VENDOR_ARGV = [
    # `uv` and `uvx` are INSTALLED on this machine; this bypass was live.
    (["uv", "run", "claude", "-p", "hi"], "anthropic_cli"),
    (["uvx", "claude", "-p", "hi"], "anthropic_cli"),
    # The npm binary name for the same CLI. `npx @openai/codex` survived only
    # because basename("@openai/codex") == "codex"; the Anthropic spec does not
    # have that luck.
    (["claude-code", "-p", "hi"], "anthropic_cli"),
    (["npx", "@anthropic-ai/claude-code", "-p", "hi"], "anthropic_cli"),
    (["npx", "-y", "@anthropic-ai/claude-code"], "anthropic_cli"),
    # The ordinary process-shepherd verbs. An agent that wants a time limit or
    # a detached child reaches for exactly these.
    (["timeout", "60", "codex", "exec", "x"], "openai_cli"),
    (["nohup", "claude", "-p", "hi"], "anthropic_cli"),
    (["xargs", "claude", "-p"], "anthropic_cli"),
    (["stdbuf", "-o0", "claude", "-p"], "anthropic_cli"),
    (["winpty", "claude", "-p"], "anthropic_cli"),
    (["start", "/b", "claude", "-p"], "anthropic_cli"),
    (["nice", "-n", "10", "codex", "exec"], "openai_cli"),
    (["setsid", "claude", "-p"], "anthropic_cli"),
    (["script", "-c", "claude -p hi", "/dev/null"], "anthropic_cli"),
]


@pytest.mark.parametrize("argv,vendor", WRAPPED_VENDOR_ARGV,
                         ids=[" ".join(a[:3]) for a, _ in WRAPPED_VENDOR_ARGV])
def test_a_vendor_behind_a_process_shepherd_is_still_billed(argv, vendor):
    """RED-VERIFIED: with the 2026-07-29 additions reverted out of
    ``_WRAPPERS``/``_PAID_EXECUTABLES``, every case here returns None and this
    test fails 14/14. The receipt is in docs/SPEND_AND_EGRESS_COVERAGE.md."""
    assert B.classify_argv(argv) == vendor, (
        f"{' '.join(argv)} reaches a paid vendor but classify_argv did not "
        "recognise it, so the process guard would spawn it for free")


# A guard that bills everything gets switched off, and then there is no guard.
INNOCENT_ARGV = [
    ["git", "status"],
    ["timeout", "60", "git", "fetch"],
    ["uv", "run", "pytest", "-q"],
    ["npx", "vite", "build"],
    ["nice", "-n", "10", "make"],
    ["python", "-m", "pytest"],
    ["ssh", "bench", "--", "nvidia-smi"],
]


@pytest.mark.parametrize("argv", INNOCENT_ARGV, ids=[" ".join(a) for a in INNOCENT_ARGV])
def test_widening_the_wrapper_list_did_not_start_billing_ordinary_commands(argv):
    """The wrapper list is only safe because it still requires a vendor token.
    If this goes red, the guard has become the thing someone deletes at 3am."""
    assert B.classify_argv(argv) is None, (
        f"{' '.join(argv)} spends no money but would now be billed and refused")


def test_the_wrapper_check_is_not_vacuous():
    """A classifier that returned the expected vendor for EVERYTHING would pass
    the parametrised test above. Pin the discrimination itself."""
    assert B.classify_argv(["uv", "run", "claude", "-p"]) == "anthropic_cli"
    assert B.classify_argv(["uv", "run", "ruff", "check"]) is None
    assert B.classify_argv([]) is None


# ===========================================================================
# 2. THE ENTRY POINTS -- the guard covers one process, and there are many
# ===========================================================================

_SPAWN = re.compile(
    r"subprocess\.(run|Popen|call|check_call|check_output)"
    r"|from subprocess import"
    r"|urlopen\(|os\.system\(|os\.popen\(|os\.spawn"
    r"|requests\.(post|get|request)|httpx\.|aiohttp\.|http\.client"
    r"|create_subprocess")
_VENDOR = re.compile(
    r"""["'](claude|codex|agy|antigravity)["']"""
    r"""|_exe\(["'](claude|codex)["']\)"""
    r"""|api\.(anthropic|openai|deepseek)\.com"""
    r"""|generativelanguage\.googleapis\.com|openrouter\.ai"""
    r"""|/api/(chat|generate|embed)"""
    r"""|/v1/(chat/completions|messages|responses|completions)""")
_MAIN = re.compile(r"__name__\s*==\s*['\"]__main__['\"]")
_INSTALLS = re.compile(r"install_process_guard")

_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "build",
               "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs"}


def runnable_spend_entrypoints(root: Path) -> dict[str, bool]:
    """``{repo-relative path: installs_the_guard}`` for every file that is BOTH
    directly runnable (``python <file>``) and able to reach a paid vendor.

    Deliberately walks the WHOLE repo. ``test_budget.py`` walks only
    ``daedalus/`` and ``runs/``; a spend site added under ``tools/`` or
    ``agents/`` is invisible to it. MEASURED 2026-07-29: nothing lives out
    there today, which is exactly when a scope guard is worth installing.
    """
    out: dict[str, bool] = {}
    for path in Path(root).rglob("*.py"):
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not (_SPAWN.search(text) and _VENDOR.search(text) and _MAIN.search(text)):
            continue
        out[path.relative_to(root).as_posix()] = bool(_INSTALLS.search(text))
    return out


# THE HONEST LEDGER. Every directly-runnable entry point that can spend money
# WITHOUT the ceiling, each with what it spends and why it is still open.
# MEASURED 2026-07-29 by running each under a `sitecustomize` probe that reports
# whether subprocess.run/Popen/urlopen are wrapped in the live process:
#
#     python -m daedalus.cli ...      -> run=True  Popen=True  urlopen=True
#     python runs/council/room.py     -> run=False Popen=False urlopen=False
#     python runs/council/summarize.py-> run=False Popen=False urlopen=False
#     python runs/council/room_server.py -> False/False/False
#     python runs/ab/run_arm.py       -> run=False Popen=False urlopen=False
#     python daedalus/claude_bridge.py-> run=False Popen=False urlopen=False
#
# CLOSED 2026-07-29. All five were given `install_process_guard()` at the top of
# their `__main__`, so they are no longer in this ledger -- a ledger that keeps
# confessing a hole after it is filled is worse than no ledger, because the next
# reader budgets attention for a risk that is gone. The scan above is the record
# of what they were; `test_the_entrypoint_ledger_has_not_rotted` is what forced
# their removal, by failing the moment the guard appeared in a listed file.
#
#     runs/council/room.py         the cross-vendor chatroom, spends per turn
#     runs/council/room_server.py  HTTP front end, delegates to room.ask_*
#     runs/council/summarize.py    CLI + ollama summarisers over the transcript
#     runs/ab/run_arm.py           MEASURED $1.43-$1.85 per arm, the most
#                                  expensive single call this repo ever made
#     daedalus/claude_bridge.py    ask_claude() has a __main__
#
# `run_arm.py` needed a `sys.path.insert` before the import would resolve at
# all: its only existing one lives inside `distilled_context()`, so importing
# `daedalus.budget` at module top would have crashed the runner outright.
#
# This ledger still exists so a NEW unguarded entry point cannot be added
# silently. The decision record is docs/SPEND_AND_EGRESS_COVERAGE.md.
KNOWN_UNGUARDED_ENTRYPOINTS = {
    # Present but NOT billable -- they exist in this dict so the detector's
    # output is fully accounted for. Version/health probes generate no tokens.
    "daedalus/doctor.py": "NOT BILLABLE: `--version` / `login status` probes",
    "daedalus/health.py": "NOT BILLABLE: git, shutil.which, local /api/tags",
    # Flagged by the scan, INSPECTED 2026-07-29, verified not to spend. These
    # two live under tools/ -- outside the daedalus/+runs/ scope that
    # test_budget.py walks -- so nothing had ever looked at them before.
    "tools/gate_discrimination.py":
        "NOT BILLABLE: the `agy` token is inside a STRING LITERAL holding a "
        "seeded-defect fixture (lines 263-286); its real spawns are git and "
        "pytest",
    "tools/system_check.py":
        "NOT BILLABLE: spawns `python -m daedalus.cli web` and "
        "`daedalus.file_bridge watch`; the `claude` token is a room SPEAKER "
        "NAME passed to `room.py say`, which only appends to the transcript",
}

# Test modules are excluded from the entry-point scan, and this is the reason,
# stated rather than silently globbed away: they are not run as `python
# <file>`, they name vendors in order to MOCK them, and the five that the scan
# flagged (test_codex_provider, test_health_surface, test_ikarus_context,
# test_ikarus_stream, test_wires) were each INSPECTED 2026-07-29 and found to
# patch every vendor call -- 23-48 mock/monkeypatch sites apiece.
#
# WHAT THIS EXCLUSION DOES NOT COVER, stated because it is a real residual
# risk: `pytest` itself runs WITHOUT the ceiling installed, so a test that
# genuinely spawned a vendor would spend unmetered. No such test exists today
# (verified by inspecting every unmocked `subprocess.run(["claude"...])` match
# in tests/), but nothing prevents one.
_EXCLUDED_TEST_DIRS = ("tests/",)


def test_no_new_unguarded_spend_entrypoint_has_appeared():
    """DRIFT DETECTOR for the hole that produced this whole audit.

    The ceiling is installed in ONE function. Every new `if __name__ ==
    "__main__"` that can reach a vendor is a new uncapped process, and the way
    that gets discovered today is a surprising invoice.
    """
    found = runnable_spend_entrypoints(ROOT)
    unguarded = {f for f, guarded in found.items()
                 if not guarded and not f.startswith(_EXCLUDED_TEST_DIRS)}
    surprises = sorted(unguarded - set(KNOWN_UNGUARDED_ENTRYPOINTS))
    assert surprises == [], (
        f"new directly-runnable spend entry point(s) with NO spend ceiling: "
        f"{surprises}. Either call daedalus.budget.install_process_guard() at "
        "the top of its __main__, or add it to KNOWN_UNGUARDED_ENTRYPOINTS "
        "WITH THE REASON and record it in docs/SPEND_AND_EGRESS_COVERAGE.md.")


def test_the_entrypoint_ledger_has_not_rotted():
    """A ledger naming files that no longer exist reads as coverage of files
    that do. Also catches a hole being CLOSED without the ledger being updated,
    which would otherwise leave a permanent false confession."""
    found = runnable_spend_entrypoints(ROOT)
    for name, reason in KNOWN_UNGUARDED_ENTRYPOINTS.items():
        assert (ROOT / name).exists(), f"ledger names a file that is gone: {name}"
        if name in found and found[name]:
            pytest.fail(
                f"{name} now installs the guard ({reason}) -- remove it from "
                "KNOWN_UNGUARDED_ENTRYPOINTS so the ledger stops confessing a "
                "hole that has been closed")


def test_the_entrypoint_detector_actually_fires(tmp_path):
    """Self-test. A clean tree cannot tell a working detector from a deleted
    one, and 'assert surprises == []' is vacuously true on an empty scan."""
    guarded = tmp_path / "guarded.py"
    guarded.write_text(
        "import subprocess\n"
        "from daedalus.budget import install_process_guard\n"
        "if __name__ == '__main__':\n"
        "    install_process_guard()\n"
        "    subprocess.run(['claude', '-p', 'hi'])\n", encoding="utf-8")
    naked = tmp_path / "naked.py"
    naked.write_text(
        "import subprocess\n"
        "if __name__ == '__main__':\n"
        "    subprocess.run(['claude', '-p', 'spend it all'])\n", encoding="utf-8")
    library = tmp_path / "library.py"      # spends, but is not runnable
    library.write_text(
        "import subprocess\n"
        "def go():\n    subprocess.run(['codex', 'exec'])\n", encoding="utf-8")
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "import subprocess\n"
        "if __name__ == '__main__':\n"
        "    subprocess.run(['git', 'status'])\n", encoding="utf-8")

    found = runnable_spend_entrypoints(tmp_path)
    assert found == {"guarded.py": True, "naked.py": False}, found
    unguarded = {f for f, g in found.items() if not g}
    assert sorted(unguarded - set()) == ["naked.py"]
    assert sorted(unguarded - {"naked.py"}) == []


def test_the_guard_is_installed_by_exactly_one_function_in_the_tree():
    """The architectural fact this audit turned on, pinned so it cannot change
    silently. If a second install site appears, the coverage story changed and
    docs/SPEND_AND_EGRESS_COVERAGE.md needs rewriting."""
    installers = set()
    for path in Path(ROOT).rglob("*.py"):
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        if path.name.startswith("test_") or path.parts[-2:][0] == "tests":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # A CALL, not the definition and not a mention in a docstring.
        if re.search(r"^\s*(?:\w+\.)?install_process_guard\(\)", text, re.M):
            installers.add(path.relative_to(ROOT).as_posix())
    assert installers == {
        "daedalus/cli.py",
        "tools/operability_drill.py",
        # Widened 2026-07-29 from two sites to seven. The audit that created
        # this test found the ceiling installed in exactly ONE function and
        # named five directly-runnable spend entry points that bypassed it;
        # those five now install it themselves. The pin is updated rather than
        # relaxed to a `>=` so that the SIXTH addition still has to be a
        # deliberate edit here -- an assertion that only ever grows stops
        # being able to notice anything.
        "daedalus/claude_bridge.py",
        "runs/ab/run_arm.py",
        "runs/council/room.py",
        "runs/council/room_server.py",
        "runs/council/summarize.py",
        # The loop driver: of every entry point in this tree, the one whose
        # missing ceiling would cost the most, because it is the only one that
        # spends REPEATEDLY by design. Its bounds (iterations, wall-clock,
        # spend) are its own; the process guard is the floor under all three.
        "daedalus/loop.py",
    }, (
        f"the set of processes that install the spend ceiling changed: "
        f"{sorted(installers)}. That is the coverage story; update the "
        "findings document.")


# ===========================================================================
# 3. THE GUARD ITSELF -- red-verified, by disabling it
# ===========================================================================

def test_guard_on_refuses_and_guard_off_spawns(tmp_path, monkeypatch):
    """The paste-worthy one: the SAME call, guarded and unguarded, against an
    exhausted ceiling. Uses `python -c pass` rather than a real vendor so the
    test costs nothing, with classify_argv monkeypatched to call it a vendor --
    the classifier has its own tests above.
    """
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "0.01")   # exhausted by any call
    B.reset_default_ledger()
    B.uninstall_process_guard()

    argv = [sys.executable, "-c", "pass"]
    monkeypatch.setattr(B, "classify_argv",
                        lambda a: "anthropic_cli" if a is argv else None)

    # --- guard OFF: the call goes through, money would have moved -----------
    assert subprocess.run(argv).returncode == 0

    # --- guard ON: refused before the process is created --------------------
    B.install_process_guard()
    try:
        with pytest.raises(B.BudgetRefused) as caught:
            subprocess.run(argv)
        assert "spend ceiling would be crossed" in str(caught.value)
    finally:
        B.uninstall_process_guard()
        B.reset_default_ledger()

    # --- and OFF again: proves the refusal came from the guard, not the env --
    assert subprocess.run(argv).returncode == 0
