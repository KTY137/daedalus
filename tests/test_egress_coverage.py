"""Which paths ship file BODIES to a third party without the secret floor?

``daedalus/sensitivity.py`` holds two independent egress rules:

* :func:`secret_floor_rule` -- unconditional, every lane, including local. A
  hit means REFUSE; there is no redact-and-send.
* :func:`classify_data` -- allow-list / default-deny, untrusted lanes only.

A path that reads a file off disk and inlines its BODY into a prompt bound for
a paid vendor, without consulting the floor, will ship a credential the first
time one lands in its selection. This file finds those paths and pins them.

MEASURED 2026-07-29, both by running the code rather than reading it:

* ``runs/council/room.py::_attach`` DOES apply the floor, fail-closed
  (``_floor`` returns "secret floor unavailable" if the import fails).
* ``runs/ab/run_arm.py::distilled_context`` does NOT. It inlines whole file
  bodies from ``C:\\Users\\nukei\\Desktop\\PnP_App`` into a ``claude`` prompt.
* ``~/.claude/skills/room/room.py::_attach`` does NOT, and it is outside this
  repo so no test here can gate it. Receipt in
  ``docs/SPEND_AND_EGRESS_COVERAGE.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from daedalus.sensitivity import secret_floor_rule

ROOT = Path(__file__).resolve().parents[1]

# A credential-shaped body. FAKE -- the key material is filler, but it is the
# SHAPE the floor matches on, which is the point.
FAKE_SECRET_BODY = (
    "ANTHROPIC_API_KEY='sk-ant-api03-" + "F" * 90 + "AA'\n"
    "AWS_SECRET_ACCESS_KEY=wJalrFAKEXAMPLEKEYfakeEXAMPLEKEYfakeEXAMP\n"
)


# ===========================================================================
# 1. POSITIVE CONTROL -- the floor recognises what we are about to test with
# ===========================================================================

def test_the_floor_catches_the_probe_body_by_path_and_by_content():
    """Every assertion below is worthless if the probe does not trip the floor.
    Both channels are checked independently, because driving them together with
    an empty path silently kills the path tier."""
    assert secret_floor_rule(".env", ""), "path channel dead"
    assert secret_floor_rule("notes.txt", FAKE_SECRET_BODY), "content channel dead"
    assert secret_floor_rule("README.md", "just some prose\n") is None, (
        "the floor fires on ordinary prose; it would be disabled within a day")


# ===========================================================================
# 2. THE REPO ROOM -- the pattern that is done correctly, pinned
# ===========================================================================

def test_the_repo_room_refuses_to_attach_a_secret(tmp_path, monkeypatch):
    """``runs/council/room.py`` is the reference implementation: it consults the
    floor per attached file and REFUSES rather than redacting. Pinned so a
    refactor cannot quietly turn it into the skills-room shape."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "repo_room", ROOT / "runs" / "council" / "room.py")
    room = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(room)

    secret = tmp_path / ".env"
    secret.write_text(FAKE_SECRET_BODY, encoding="utf-8")
    monkeypatch.setattr(room, "REPO_ROOT", tmp_path)

    out = room._attach([".env"])
    assert "sk-ant-api03-" not in out, (
        "the repo room inlined a credential into a vendor prompt")
    assert "wJalr" not in out
    # ...and it must SAY it withheld something, not silently drop it.
    assert re.search(r"secret|withheld|refus|floor", out, re.I), (
        f"the room dropped the file without telling anyone: {out[:400]!r}")


def test_the_repo_room_still_attaches_ordinary_files(tmp_path, monkeypatch):
    """A floor that blocks everything is a floor someone removes."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "repo_room2", ROOT / "runs" / "council" / "room.py")
    room = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(room)

    ordinary = tmp_path / "hello.py"
    ordinary.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    monkeypatch.setattr(room, "REPO_ROOT", tmp_path)

    out = room._attach(["hello.py"])
    assert "return 'world'" in out, "the room refused an ordinary source file"


# ===========================================================================
# 3. DRIFT DETECTOR -- new body-inlining paths must consult the floor
# ===========================================================================

# Reading a file's full body and putting it in a string that reaches a vendor.
_INLINES_BODY = re.compile(r"\.read_text\(|\.read_bytes\(|open\([^)]*\)\.read\(")
_VENDOR_PROMPT = re.compile(
    r"""["'](claude|codex|agy|antigravity)["']"""
    r"""|api\.(anthropic|openai|deepseek)\.com"""
    r"""|/v1/(chat/completions|messages)|/api/(chat|generate)""")
_CONSULTS_FLOOR = re.compile(r"secret_floor_rule|_floor\(|classify_data")

_SKIP_PARTS = {"__pycache__", "node_modules", ".git", ".venv", "venv", "build",
               "daedalus.egg-info", ".pytest_cache", "dist", "structcore-rs",
               "tests"}


def body_inlining_vendor_paths(
    root: Path,
    candidate_paths: set[str] | None = None,
) -> dict[str, bool]:
    """``{repo-relative path: consults_a_fence}`` for files that BOTH read file
    bodies off disk AND name a paid vendor destination.

    ``candidate_paths`` lets the production check compose with the billable-site
    registry instead of treating an unrelated config read and a vendor name
    anywhere in the same large module as a data flow.  The self-test leaves it
    unset so a synthetic new file is still discovered by a whole-directory
    scan.
    """
    out: dict[str, bool] = {}
    paths = (
        ((Path(root) / rel) for rel in sorted(candidate_paths))
        if candidate_paths is not None
        else Path(root).rglob("*.py")
    )
    for path in paths:
        if not path.is_file() or path.suffix != ".py":
            continue
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not (_INLINES_BODY.search(text) and _VENDOR_PROMPT.search(text)):
            continue
        out[path.relative_to(root).as_posix()] = bool(_CONSULTS_FLOOR.search(text))
    return out


# The honest ledger of repo paths that inline file bodies toward a paid vendor
# WITHOUT consulting either fence. Each entry is a decision someone has to make,
# not a bug someone can fix blind -- see docs/SPEND_AND_EGRESS_COVERAGE.md.
KNOWN_UNFLOORED_EGRESS = {
    "runs/ab/run_arm.py":
        "distilled_context() (lines 79-85) inlines whole file bodies from "
        "C:/Users/nukei/Desktop/PnP_App -- a DIFFERENT repo, chosen by "
        "plan_context, not by a human -- into a `claude` prompt. If the "
        "planner ever selects a .env or a credentialled config it ships "
        "verbatim. CRITICAL; open because the fix is a design decision about "
        "whether an A/B arm may silently drop a selected file (which would "
        "change what the two arms are comparing).",
}

# The textual detector deliberately over-approximates within one registered
# billable module. This inspected co-location is not an egress path: the read is
# the CLI's response file after the vendor process has produced it, not input
# placed into the prompt.
KNOWN_NON_EGRESS_COLOCATIONS = {
    "daedalus/ikarus_os.py":
        "_claude_stream reads the vendor's response message file; prompt input "
        "is assembled separately and the bytes flow vendor -> disk -> caller",
}


def _billable_python_paths() -> set[str]:
    """The production scope, owned by the spend-site coverage surface."""
    from daedalus.budget import BILLABLE_SITES

    return {
        str(site["file"]).replace("\\", "/")
        for site in BILLABLE_SITES
        if str(site.get("file", "")).endswith(".py")
    }


def test_no_new_unfloored_body_inlining_path_has_appeared():
    """DRIFT DETECTOR. Goes red when a new path starts shipping file bodies to
    a vendor without consulting the secret floor."""
    found = body_inlining_vendor_paths(ROOT, _billable_python_paths())
    unfloored = {f for f, floored in found.items() if not floored}
    surprises = sorted(
        unfloored
        - set(KNOWN_UNFLOORED_EGRESS)
        - set(KNOWN_NON_EGRESS_COLOCATIONS)
    )
    assert surprises == [], (
        f"new path(s) inlining file bodies toward a paid vendor with NO secret "
        f"floor: {surprises}. Call daedalus.sensitivity.secret_floor_rule on "
        "every file body before it enters the prompt -- see "
        "runs/council/room.py::_floor for the fail-closed pattern -- or add it "
        "to KNOWN_UNFLOORED_EGRESS with the reason.")


def test_the_egress_ledger_has_not_rotted():
    found = body_inlining_vendor_paths(ROOT, _billable_python_paths())
    for name in KNOWN_UNFLOORED_EGRESS:
        assert (ROOT / name).exists(), f"ledger names a file that is gone: {name}"
        if found.get(name):
            pytest.fail(
                f"{name} now consults a fence -- remove it from "
                "KNOWN_UNFLOORED_EGRESS so the ledger stops confessing a hole "
                "that has been closed")
    for name, reason in KNOWN_NON_EGRESS_COLOCATIONS.items():
        assert found.get(name) is False, (
            f"{name} no longer has the inspected unfloored co-location "
            f"({reason}); re-measure it and remove this exception")


def test_the_egress_detector_actually_fires(tmp_path):
    """Self-test: 'assert surprises == []' is vacuously true on an empty scan,
    so feed the detector a known-bad file and require it to be reported."""
    leaky = tmp_path / "leaky.py"
    leaky.write_text(
        "from pathlib import Path\n"
        "import subprocess\n"
        "body = Path('secrets.env').read_text()\n"
        "subprocess.run(['claude', '-p', body])\n", encoding="utf-8")
    floored = tmp_path / "floored.py"
    floored.write_text(
        "from pathlib import Path\n"
        "import subprocess\n"
        "from daedalus.sensitivity import secret_floor_rule\n"
        "body = Path('secrets.env').read_text()\n"
        "if not secret_floor_rule('secrets.env', body):\n"
        "    subprocess.run(['claude', '-p', body])\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text(
        "from pathlib import Path\n"
        "body = Path('notes.md').read_text()\n"
        "print(body)\n", encoding="utf-8")

    found = body_inlining_vendor_paths(tmp_path)
    assert found == {"leaky.py": False, "floored.py": True}, found
    unfloored = {f for f, ok in found.items() if not ok}
    assert sorted(unfloored) == ["leaky.py"]


# ===========================================================================
# 4. THE OUT-OF-REPO ROOM -- documented, not gated
# ===========================================================================

SKILLS_ROOM = Path.home() / ".claude" / "skills" / "room" / "room.py"


@pytest.mark.skipif(not SKILLS_ROOM.exists(),
                    reason="the portable room skill is not installed here")
def test_the_skills_room_is_still_missing_the_floor():
    """A WITNESS, not a gate. ``~/.claude/skills/room/room.py`` is outside this
    repo -- no test here can stop it shipping -- but its state can be recorded,
    so that "we knew" is provable and a future fix is noticed.

    MEASURED 2026-07-29: `_attach` inlined a fake ANTHROPIC_API_KEY verbatim
    into the prompt bound for `codex` (OpenAI) and, over SSH, `agy` (Google).

    If this test FAILS, the skill has been fixed -- delete the test and update
    docs/SPEND_AND_EGRESS_COVERAGE.md.
    """
    text = SKILLS_ROOM.read_text(encoding="utf-8", errors="replace")
    assert "secret_floor_rule" not in text and "classify_data" not in text, (
        "the portable room skill now consults a fence -- this witness is stale")
    assert "def _attach" in text, "the skill's attachment path moved; re-measure"
