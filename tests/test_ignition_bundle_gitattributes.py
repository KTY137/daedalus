"""Git's own identity machinery, audited against the Gate-1 evaluator bundle.

WHAT THIS CLOSES. `daedalus/ignition/bundle.py` names each evaluator's
identity by git's own blob sha (`git hash-object`), which is ALREADY
checkout-stable without a `-text` pin -- that mechanism is what
`test_the_digest_does_not_move_with_line_endings` in test_ignition_bundle.py
measures. What was NOT pinned is narrower and real: `evaluator_bundle` also
records `running_bytes_sha256`, the RAW bytes that actually executed, marked
`platform_dependent` because on a host with `core.autocrlf=true` those bytes
differ from the committed LF form -- the exact defect already found and fixed
for the Gate-1 fixture tree (`tests/fixtures/ignition/voltage/** -text`) and
for several review subjects since (`b05f80be`, `89132d83`). This file proves
the SAME closure -- the bundle's full transitive file list, not one named
file at a time -- carries an explicit, non-autocrlf-dependent
`.gitattributes` declaration, using `git check-attr` itself rather than a
hand-rolled pattern matcher, so the audit is asking git the question git will
actually answer at checkout time.

INSTRUMENT HONESTY. A `git check-attr` call that fails (git absent, a
timeout, a non-repository cwd) must be told apart from "checked every file
and found no gap" -- an empty result and a broken query read identically to a
careless caller, and this project has hit that exact confusion four times in
48h (dominance analysis reading `declared: 0` as an answer instead of a
limit; mutation anchors resolving twice and refusing silently; an empty scope
declaration reading as a pass; a killed suite run read as a result with no
summary section). `_git_check_attr` returns ``None`` on failure, never `{}`,
and `test_every_bundle_file_has_a_filter_stable_declaration` refuses to
interpret a `None` as "no gaps" -- it fails loudly, naming the instrument
broken rather than the census clean.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from daedalus.ignition import bundle as ignition_bundle

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "ignition" / "voltage"


def _bundle_full_file_list() -> list[str]:
    """Every file the Gate-1 bundle's transitive closure touches: the
    evaluator roots, their import closure, and the fixture tree those
    evaluators judge and that gets copied verbatim into every candidate
    (`daedalus.ignition.gate1.prepare_ignition_repo`). The criterion source
    itself is not a separate file -- it is a Python string constant baked into
    `daedalus/ignition/checks.py`, which is already a closure member.
    """

    closure = ignition_bundle.import_closure(ROOT, ignition_bundle.EVALUATOR_MODULES)
    fixture_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file()
    )
    return sorted(set(closure) | set(ignition_bundle.EVALUATOR_MODULES) | set(fixture_files))


def _git_check_attr(
    root: Path, rels: Sequence[str]
) -> dict[str, dict[str, str]] | None:
    """``{rel: {"text": ..., "eol": ..., "filter": ...}}`` via ONE
    ``git check-attr --stdin`` call, or ``None`` when git itself could not
    answer -- never ``{}``, which ``git check-attr`` does not produce for a
    non-empty input and which a caller could otherwise misread as "asked, and
    every file came back with no attributes" instead of "did not ask".
    """

    if not rels:
        return {}
    # BYTES, NOT text=True. `subprocess.run(..., text=True)` writes stdin
    # through a TextIOWrapper opened with newline=None, which translates every
    # "\n" to os.linesep on the way out -- "\r\n" on Windows -- so each path
    # arrived at git as "daedalus/x.py\r", a DIFFERENT string that resolves to
    # no attributes at all. MEASURED: this exact bug, in this exact function,
    # on the first run -- the same CRLF-in-a-payload shape the fixture tree
    # and the review subjects hit, now inside the auditor meant to catch it.
    payload = ("\n".join(rels) + "\n").encode("utf-8")
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "check-attr", "text", "eol", "filter", "--stdin"],
            input=payload,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out: dict[str, dict[str, str]] = {}
    for line in proc.stdout.decode("utf-8").splitlines():
        try:
            path, attr, value = line.split(": ", 2)
        except ValueError:
            continue
        out.setdefault(path, {})[attr] = value
    return out


def _is_filter_stable(attrs: Mapping[str, str]) -> bool:
    """``-text`` (git treats the file as binary: checkout leaves the bytes
    alone) or a forced ``eol`` (checkout always normalises to one ending,
    regardless of ``core.autocrlf``) both make a checkout's bytes independent
    of the host's line-ending configuration. Anything else -- ``text: auto``,
    unspecified, or a bare ``text`` attribute without a forced eol -- still
    depends on ``core.autocrlf`` and git's binary/text content heuristic.
    """

    return attrs.get("text") == "unset" or attrs.get("eol") in ("lf", "crlf")


# --------------------------------------------------------------------------- #
# the census                                                                   #
# --------------------------------------------------------------------------- #
def test_the_full_file_list_reaches_the_measured_floor():
    """A floor, not the answer, mirroring KNOWN_SUBJECTS in
    test_byte_pin_eol_durability.py: the detector must find AT LEAST what was
    measured on 2026-08-24, so a detector that quietly stops matching cannot
    make the guard below pass by finding fewer files."""

    files = _bundle_full_file_list()
    assert len(files) >= 124 + 7, (
        f"only {len(files)} files found; the evaluator closure was 124 modules "
        "and the fixture tree 7 files when this was measured"
    )
    assert "daedalus/ignition/bundle.py" in files
    assert "daedalus/twin/_reference_claims.py" in files, (
        "the module the closure exists to reach (Codex round 3) is missing "
        "from the census"
    )
    assert "tests/fixtures/ignition/voltage/data/events.csv" in files


def test_an_ordinary_module_outside_the_closure_is_not_asserted_pinned():
    """Without this, a bug that reported every file in the repository as part
    of the bundle's file list would still pass the guard below. `cli.py` is a
    real, tracked daedalus module (MEASURED 2026-08-24: not reachable from the
    evaluator roots' import closure) -- not a fictitious path, so this proves
    the census has a real boundary rather than one that happens to exclude
    nothing."""

    assert "daedalus/cli.py" not in _bundle_full_file_list()


# --------------------------------------------------------------------------- #
# the instrument -- must say "could not measure", never a silent clean pass    #
# --------------------------------------------------------------------------- #
def test_check_attr_instrument_reports_unmeasurable_when_git_cannot_answer(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise FileNotFoundError("no git on PATH")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert _git_check_attr(ROOT, ["daedalus/ignition/bundle.py"]) is None


def test_check_attr_instrument_reports_unmeasurable_on_nonzero_exit(monkeypatch):
    class _Proc:
        returncode = 129
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    assert _git_check_attr(ROOT, ["daedalus/ignition/bundle.py"]) is None


def test_check_attr_instrument_answers_for_a_real_file():
    attrs = _git_check_attr(ROOT, ["daedalus/ignition/bundle.py"])
    assert attrs is not None, "git could not be asked at all on this host"
    assert "daedalus/ignition/bundle.py" in attrs
    assert attrs["daedalus/ignition/bundle.py"]["text"] == "unset"


# --------------------------------------------------------------------------- #
# the guard                                                                    #
# --------------------------------------------------------------------------- #
def test_every_bundle_file_has_a_filter_stable_declaration():
    """The mechanical closure this test exists to hold shut: every file the
    Gate-1 bundle's transitive closure touches must carry an explicit,
    non-autocrlf-dependent .gitattributes declaration, checked the same way
    git itself resolves attributes at checkout time.
    """

    files = _bundle_full_file_list()
    attrs = _git_check_attr(ROOT, files)
    assert attrs is not None, (
        "git check-attr could not be run; this is an unmeasured gap, not a "
        "clean one -- do not read the absence of a failure below as a pass"
    )
    missing = sorted(rel for rel in files if not _is_filter_stable(attrs.get(rel, {})))
    assert missing == [], (
        f"{len(missing)} of {len(files)} Gate-1 evaluator-bundle files have no "
        "explicit, non-autocrlf-dependent .gitattributes declaration (-text or "
        "a forced eol): " + ", ".join(missing[:15])
        + (f" ... and {len(missing) - 15} more" if len(missing) > 15 else "")
    )


def test_no_bundle_file_carries_a_custom_filter():
    """A clean/smudge filter driver (``filter=...``) could rewrite content on
    checkout in a way neither the blob sha nor a bare -text pin would catch.
    None is declared in this repository today; this is the check that would
    notice one arriving on a bundle file."""

    files = _bundle_full_file_list()
    attrs = _git_check_attr(ROOT, files)
    assert attrs is not None
    filtered = sorted(
        rel for rel in files if attrs.get(rel, {}).get("filter") not in (None, "unspecified")
    )
    assert filtered == [], f"unexpected filter= attribute on: {', '.join(filtered)}"


def test_the_gitattributes_pin_is_an_explicit_list_not_a_wildcard():
    """MEASURED, and the opposite conclusion from this file's first draft: a
    wildcard (``daedalus/**/*.py -text``) looked like the self-maintaining
    choice -- the closure grows with every refactor -- but checked against
    this worktree it would silently -text-pin roughly 170 OTHER daedalus
    modules the Gate-1 bundle never reads, most of them ALSO CRLF-on-disk over
    an LF-committed blob. That is exactly the "whole-repository EOL policy"
    the D7 section above declined to make for `*.py`, just scoped to one
    directory instead of the repository -- and the next `git add -A` to touch
    one of those 170 files would have silently flipped its committed line
    endings. The fix is one explicit line per closure file; the guard test
    above (`test_every_bundle_file_has_a_filter_stable_declaration`) gives the
    SAME self-healing property a wildcard would have, by recomputing the
    closure from source every run, without the blast radius a wildcard
    measured to carry here."""

    # The ACTIVE rules only. Read as raw text this test failed on its own
    # rationale: the comment above explains why `daedalus/**/*.py -text` was
    # rejected, and quoting the pattern in prose is not declaring it. A rule
    # file's meaning lives in its rule lines; a test that greps the whole file
    # pins the SPELLING of a thing when it means the FACT of it.
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert "daedalus/**/*.py -text" not in rules, "reintroduces the measured blast radius"
    assert "daedalus/** -text" not in rules, "reintroduces the measured blast radius"
    missing = sorted(
        rel for rel in _bundle_full_file_list()
        if rel.startswith("daedalus/") and f"{rel} -text" not in rules
    )
    assert missing == [], (
        f"{len(missing)} closure files have no explicit .gitattributes line: "
        + ", ".join(missing[:10])
    )
