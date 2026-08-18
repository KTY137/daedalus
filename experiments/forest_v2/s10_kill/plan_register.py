"""Derive the kill-criteria register from the *living* plan, at check time.

The first version of this slice hard-coded "fifteen kill criteria" in a
docstring, a README line, a coverage percentage and a test constant.  The
living plan (revision 5) lists **sixteen**.  One bullet -- corpus
licensing/provenance -- was absent from the code entirely, and because the
remaining bullets were numbered by hand, the criterion after the gap carried
the *free* index: a reader looking up "14.15" in the plan landed on a
different criterion than the report meant.  The denominator was flattering
(9/15 = 60%) and the test that existed to catch exactly this pinned the
wrong constant with a confident-sounding reason.

The lesson is not "count more carefully".  It is that a register copied by
hand from a document that moves is a stale mirror, and a coverage
percentage computed from a stale mirror is a claim about the mirror.  So:

* the plan text is parsed at check time -- section heading, bullets, and the
  section *number* (which has already moved once, from 13 to 14);
* the code's register is compared **verbatim**, one to one, including the
  ``plan_ref`` index each entry claims;
* the report's coverage is ``n_decided / n_extracted`` and never a literal.

A plan that adds, removes, renumbers or rewords a bullet makes the check
red.  That is the entire point: this module exists to fail.

Read-only.  It reads one Markdown file and hashes it; it writes nothing and
imports nothing outside the standard library.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

#: Where the plan lives, relative to a repository root.
PLAN_PARTS: Tuple[str, ...] = ("docs", "IKARUS_ARIADNE_MASTER_PLAN.md")

#: The section is matched by *title*, not by number, because the number is
#: exactly the thing that drifts.  The captured number becomes the register's
#: ``plan_ref`` prefix.
_HEADING = re.compile(r"^##\s+(\d+)\.\s+Kill criteria\s*$", re.IGNORECASE)
_WS = re.compile(r"\s+")
_TRAILING = re.compile(r"[;.\s]+$")


class PlanRegisterError(Exception):
    """The plan could not be found, or section 'Kill criteria' could not be read."""


@dataclass(frozen=True)
class PlanBullet:
    """One bullet of the plan's kill-criteria list, as the plan words it."""

    index: int          # 1-based position in the list
    plan_ref: str       # e.g. "14.15"
    statement: str      # normalised bullet text, verbatim wording


@dataclass(frozen=True)
class PlanSection:
    plan_path: str
    plan_digest: str    # sha256 of the whole plan file
    section: int        # the section number the plan currently uses
    bullets: Tuple[PlanBullet, ...]

    @property
    def n_extracted(self) -> int:
        return len(self.bullets)


@dataclass(frozen=True)
class RegisterCheck:
    """The 1:1 comparison of the code register against the living plan."""

    section: PlanSection
    n_registered: int
    mismatches: Tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def n_extracted(self) -> int:
        return self.section.n_extracted

    def describe(self) -> str:
        head = (
            f"{self.section.plan_path} section {self.section.section}: "
            f"{self.n_extracted} bullets extracted, {self.n_registered} registered, "
            f"sha256 {self.section.plan_digest[:12]}"
        )
        if self.ok:
            return head + " -- register matches the living plan 1:1"
        lines = [head + f" -- {len(self.mismatches)} MISMATCH(es):"]
        lines.extend("  " + m for m in self.mismatches)
        return "\n".join(lines)


# ------------------------------------------------------------- extraction


def normalise(text: str) -> str:
    """Collapse Markdown line wrapping and drop the bullet's trailing ';'."""
    return _TRAILING.sub("", _WS.sub(" ", text).strip()).strip()


def extract_section(plan_text: str) -> Tuple[int, Tuple[str, ...]]:
    """Return (section number, bullet statements) for the kill-criteria list.

    The first contiguous top-level bullet list after the heading *is* the
    register.  Continuation lines (indented, non-empty) are folded into the
    bullet above them; the first line that is neither ends the list.
    """
    lines = plan_text.splitlines()
    heads = [(i, int(m.group(1))) for i, m in
             ((i, _HEADING.match(ln)) for i, ln in enumerate(lines)) if m]
    if not heads:
        raise PlanRegisterError(
            "no '## <n>. Kill criteria' heading in the plan; the register cannot "
            "be derived and must not be assumed"
        )
    if len(heads) > 1:
        raise PlanRegisterError(
            f"{len(heads)} 'Kill criteria' headings in the plan; ambiguous register"
        )
    start, section = heads[0]

    bullets: List[str] = []
    current: Optional[str] = None
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            if current is not None:
                bullets.append(current)
            current = line[2:].strip()
            continue
        if current is None:
            continue  # the lead-in paragraph, before the list starts
        if line.strip() and (line.startswith("  ") or line.startswith("\t")):
            current = current + " " + line.strip()
            continue
        break  # blank line or unindented text: the list has ended
    if current is not None:
        bullets.append(current)

    if not bullets:
        raise PlanRegisterError(
            f"section {section} 'Kill criteria' contains no bullet list"
        )
    return section, tuple(normalise(b) for b in bullets)


def load_section(plan_path: Optional[Path] = None) -> PlanSection:
    path = Path(plan_path) if plan_path is not None else find_plan()
    if path is None or not path.is_file():
        raise PlanRegisterError(
            f"master plan not found (looked for {'/'.join(PLAN_PARTS)} above "
            f"{Path(__file__).resolve().parent}); the criteria register cannot be "
            f"verified, and an unverified register must not be reported as coverage"
        )
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    section, statements = extract_section(raw.decode("utf-8"))
    bullets = tuple(
        PlanBullet(i, f"{section}.{i}", s) for i, s in enumerate(statements, start=1)
    )
    return PlanSection(str(path), digest, section, bullets)


def find_plan(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from this module looking for the plan; None when not found."""
    here = Path(start) if start is not None else Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent.joinpath(*PLAN_PARTS)
        if candidate.is_file():
            return candidate
    return None


# ------------------------------------------------------------ comparison


def compare(
    section: PlanSection, entries: Sequence[Tuple[str, str]]
) -> RegisterCheck:
    """Compare (plan_ref, statement) pairs against the extracted bullets.

    ``entries`` must already be in plan order.  Every difference is reported;
    the first one does not mask the rest, because a register that drifted
    once usually drifted more than once.
    """
    bullets = section.bullets
    problems: List[str] = []

    refs = [ref for ref, _ in entries]
    duplicates = sorted({r for r in refs if refs.count(r) > 1})
    for dup in duplicates:
        problems.append(f"duplicate plan_ref {dup!r} in the code register")

    if len(entries) != len(bullets):
        problems.append(
            f"count: the plan lists {len(bullets)} kill criteria, the code "
            f"registers {len(entries)}"
        )

    for i in range(max(len(entries), len(bullets))):
        want = bullets[i] if i < len(bullets) else None
        got = entries[i] if i < len(entries) else None
        if want is None:
            problems.append(
                f"position {i + 1}: the code registers {got[0]} {got[1]!r} but the "
                f"plan has no such bullet"
            )
            continue
        if got is None:
            problems.append(
                f"position {i + 1}: the plan lists {want.plan_ref} {want.statement!r} "
                f"but the code registers nothing -- a criterion is missing, not "
                f"out of scope"
            )
            continue
        ref, statement = got
        if ref != want.plan_ref:
            problems.append(
                f"position {i + 1}: plan_ref {ref!r} points at the wrong bullet; "
                f"the plan numbers this one {want.plan_ref!r} ({want.statement!r})"
            )
        if normalise(statement) != want.statement:
            problems.append(
                f"{want.plan_ref}: wording differs\n"
                f"    plan: {want.statement!r}\n"
                f"    code: {normalise(statement)!r}"
            )

    # The misfiling check, separate from position: a criterion whose wording
    # the plan *does* contain, but under a different number.  This is the
    # defect that a dropped bullet produces -- everything after the gap slides
    # up one index, so a reader who looks up a cited ref in the plan lands on
    # a different criterion than the report meant.  Position-wise comparison
    # calls that "wording differs", which is true but does not name the harm.
    by_statement = {b.statement: b.plan_ref for b in bullets}
    for ref, statement in entries:
        where = by_statement.get(normalise(statement))
        if where is not None and where != ref:
            problems.append(
                f"misfiled citation: the register cites {ref} for a criterion the "
                f"plan numbers {where}; anyone looking up {ref} in the plan reads a "
                f"different criterion"
            )

    return RegisterCheck(section, len(entries), tuple(problems))


def verify(entries: Sequence[Tuple[str, str]],
           plan_path: Optional[Path] = None) -> RegisterCheck:
    """Load the living plan and compare the code register against it."""
    return compare(load_section(plan_path), entries)


def verify_quietly(entries: Sequence[Tuple[str, str]]) -> Optional[RegisterCheck]:
    """``verify`` for the report path: None when the plan is not reachable.

    The report says so in words rather than printing an unverified
    denominator as though it had been checked.
    """
    try:
        return verify(entries)
    except (PlanRegisterError, OSError, UnicodeDecodeError):
        return None
