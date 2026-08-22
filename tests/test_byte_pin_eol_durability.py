"""Owner decision D7: the CRLF pin daemon has no next victim.

WHAT WENT WRONG FOUR TIMES. ``core.autocrlf`` is true on the owner's host, so a
fresh checkout translates LF to CRLF. A file whose OWN BYTES are hashed into an
identity -- a retained package resource verified against its Git blob, a gate
inventory that reads a module's working-tree bytes, a fault executor that
fingerprints itself into its receipt -- was pinned on the LF form. The same
commit then produces one digest on Linux and another on Windows.

Recorded appearances: docs/GATE0_OWNER_DECISIONS_20260817.md sections 5 and 6,
plus the Wave-1 "fixtures stop writing CRLF into byte-exact files" family. It
kept coming back because the fix each time was to add one more line to
.gitattributes by hand, and the NEXT byte-pin subject arrived unlisted.

THIS FILE IS THE PART THAT DOES NOT ROT. It re-derives the census of byte-pin
subjects from the source and fails when one of them is not EOL-pinned. Adding a
module that hashes its own bytes without an attribute is now a red test rather
than a Windows-only surprise three sessions later.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GITATTRIBUTES = ROOT / ".gitattributes"

# The subjects measured on 2026-08-22. Kept as a floor, not as the answer: the
# detectors below must find AT LEAST these, so a detector that silently stops
# matching cannot make this file pass by finding nothing.
KNOWN_SUBJECTS = {
    "daedalus/kairos/_gated_writes_legacy.py.src",
    "daedalus/runtimes/provider_target_receipt_ledger.py",
    "daedalus/runtimes/provider_observation.py",
    "daedalus/runtimes/live_probe_drivers.py",
    "tests/fixtures/container_oom_fault_executor.py",
    "tests/fixtures/effect_ledger_contention_fault_executor.py",
    "tests/fixtures/linux_process_fault_executor.py",
    "tests/fixtures/runtime_trust_contention_fault_executor.py",
    "tests/fixtures/sandbox_unavailable_fault_executor.py",
    "tests/fixtures/unauthorized_egress_fault_executor.py",
    "tests/fixtures/undeclared_secret_fault_executor.py",
    "tests/fixtures/unknown_outcome_reconciliation_fault_executor.py",
}

_SOURCE_PATH_RE = re.compile(r'^_SOURCE_PATH\s*=\s*["\']([^"\']+)["\']', re.M)
_RETAINED_RE = re.compile(r'^_RETAINED_SOURCE_NAME\s*=\s*["\']([^"\']+)["\']', re.M)
_SELF_HASH_MARKERS = (
    "Path(__file__).read_bytes()",
    "_file_sha256(Path(__file__))",
    "def implementation_sha256",
)

_SEARCH_ROOTS = ("daedalus", "tests", "tools")


def _iter_sources():
    for name in _SEARCH_ROOTS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            # This module quotes the detector markers as string literals and
            # would otherwise detect itself -- a census that includes its own
            # source is measuring the wrong thing.
            if path.resolve() == Path(__file__).resolve():
                continue
            yield path


def _census() -> set[str]:
    """Files whose working-tree bytes become an identity.

    Three detectors, matching the three shapes that exist today: a gate
    inventory naming another module in ``_SOURCE_PATH``; a package resource
    named in ``_RETAINED_SOURCE_NAME``; and a module or fixture that hashes its
    own ``__file__``.
    """
    found: set[str] = set()
    for path in _iter_sources():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for match in _SOURCE_PATH_RE.finditer(text):
            found.add(match.group(1).replace("\\", "/"))
        for match in _RETAINED_RE.finditer(text):
            found.add((path.parent / match.group(1)).relative_to(ROOT).as_posix())
        if any(marker in text for marker in _SELF_HASH_MARKERS):
            found.add(rel)
    return found


def _rules() -> list[tuple[str, bool]]:
    """(pattern, text_is_unset) in file order; the LAST match wins, as in git."""
    out: list[tuple[str, bool]] = []
    for raw in GITATTRIBUTES.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        pattern, attrs = parts[0], parts[1:]
        if "-text" in attrs:
            out.append((pattern, True))
        elif any(a == "text" or a.startswith("text=") for a in attrs):
            out.append((pattern, False))
    return out


def _text_unset(rel_path: str) -> bool:
    """Minimal .gitattributes resolution for the patterns this repo uses.

    A pattern without a slash matches the BASENAME at any depth; a pattern with
    one is anchored at the repository root. Deliberately hand-rolled so the
    check has no dependency on a git binary being present in the environment
    that runs it.
    """
    verdict = False
    for pattern, unset in _rules():
        if "/" in pattern:
            matched = fnmatch.fnmatch(rel_path, pattern)
        else:
            matched = fnmatch.fnmatch(rel_path.rsplit("/", 1)[-1], pattern)
        if matched:
            verdict = unset
    return verdict


# --------------------------------------------------------------------------
# DYNAMIC RANGE -- the detector must actually detect
# --------------------------------------------------------------------------

def test_the_census_finds_at_least_the_known_subjects():
    missing = KNOWN_SUBJECTS - _census()
    assert missing == set(), (
        "the byte-pin detector stopped seeing subjects it saw on 2026-08-22: "
        + ", ".join(sorted(missing))
        + ". Fix the detector before trusting the durability test below."
    )


def test_an_ordinary_module_is_not_eol_pinned():
    """Without this, a repo-wide `* -text` would make the guard vacuously green."""
    assert _text_unset("daedalus/router.py") is False


# --------------------------------------------------------------------------
# THE GUARD
# --------------------------------------------------------------------------

def test_every_byte_pin_subject_is_eol_pinned():
    unpinned = sorted(rel for rel in _census() if not _text_unset(rel))
    assert unpinned == [], (
        "these files hash their own bytes into an identity but are still "
        "translated on checkout, so their digest depends on the host rather "
        "than on the revision: " + ", ".join(unpinned) + ". Add a `-text` line "
        "to .gitattributes (owner decision D7)."
    )


@pytest.mark.parametrize("rel", sorted(KNOWN_SUBJECTS))
def test_known_subject_is_eol_pinned(rel):
    assert _text_unset(rel), rel + " lost its -text attribute"


def test_the_retained_package_resource_is_covered_by_the_glob():
    """The plan's exact prescription: `*.py.src -text`, not one file by name.

    A second retained resource must be protected the moment it is added, which
    a per-file line cannot do.
    """
    assert _text_unset("daedalus/kairos/_gated_writes_legacy.py.src")
    assert _text_unset("daedalus/somewhere/_a_future_resource.py.src")


def test_gitattributes_records_why_the_lines_exist():
    """A bare list of paths is what rotted last time.

    The reason has to travel with the rule, or the next person removes a line
    that looks redundant and the family returns for a fifth time.
    """
    text = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "D7" in text
    assert "autocrlf" in text
