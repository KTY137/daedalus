"""OS-owned variables are not Daedalus switches, and are not reported as ones.

WHY (G1-MAP-04, 2026-09-03). ``daedalus/mapping/switches.py`` carries a
``_PLATFORM_ENV`` set whose comment states its whole purpose:

    Platform variables the OS owns. They are read, but they are not Daedalus
    switches and marking them dark would bury the ones that are.

It listed ``USERNAME`` and ``USERPROFILE`` but not ``USER``, ``USERDOMAIN`` or
``PROCESSOR_IDENTIFIER`` -- the same category of account-and-host identity,
simply not encountered when the set was written. So the drift gate reported
three OS variables as undocumented Daedalus switches, which is the exact
burying the comment says the set exists to prevent.

WHY NOT JUST DOCUMENT THEM. Writing "the environment variable USER" in a doc
does close the ``code-only`` row -- and immediately opens a ``doc-only`` one,
because a name in the strict operator form that no Daedalus module owns then
reads as "docs tell an operator to set it; no module reads it". Documenting an
OS variable to silence a gate trades one false row for another. The set is the
right lever: it says the name is out of scope, once, where the scope is defined.

WHAT IS DELIBERATELY NOT CLAIMED: that these variables are unread. They are
read -- ``tools/gate_host_preflight.py`` reads two of them and
``docs/recovery/production_key_ceremony_kit.py`` reads the third. The claim is
only that Daedalus does not define them, so their absence from Daedalus's own
documentation is not a defect in Daedalus.
"""
from __future__ import annotations

from pathlib import Path

from daedalus.mapping import switches as sw


ROOT = Path(__file__).resolve().parents[1]

#: Read somewhere in this tree, owned by the operating system.
OS_OWNED = ("USER", "USERDOMAIN", "PROCESSOR_IDENTIFIER")


def test_account_and_host_identity_variables_are_platform_owned() -> None:
    for name in OS_OWNED:
        assert name in sw._PLATFORM_ENV, name


def test_the_set_still_carries_the_names_it_already_had() -> None:
    """A regression guard: this packet ADDS, it does not curate."""
    for name in ("PATH", "HOME", "TEMP", "USERNAME", "USERPROFILE",
                 "VIRTUAL_ENV", "PYTHONPATH"):
        assert name in sw._PLATFORM_ENV, name


def test_daedalus_owned_switches_are_not_swept_into_the_platform_set() -> None:
    """The failure mode of a too-eager exclusion list."""
    for name in sorted(sw._PLATFORM_ENV):
        assert not name.startswith("DAEDALUS_"), name


def test_this_repository_reports_no_os_variable_as_an_undocumented_switch() -> None:
    """The finding, pinned against the real tree."""
    report = sw.analyse(ROOT)
    code_only = {
        entry.read for entry in report.drift
        if entry.kind == "read_never_documented"
    }
    for name in OS_OWNED:
        assert name not in code_only, (
            f"{name} is owned by the OS; reporting it as an undocumented "
            f"Daedalus switch buries the ones that are"
        )


def test_no_os_variable_becomes_documented_never_read_either() -> None:
    """The mirror row this change must not create.

    Excluding a name from ``read`` while a document still names it in the
    strict operator form would flip the finding rather than retire it.
    """
    report = sw.analyse(ROOT)
    doc_only = {
        entry.documented for entry in report.drift
        if entry.kind == "documented_never_read"
    }
    for name in OS_OWNED:
        assert name not in doc_only, (
            f"{name} moved from code-only to doc-only instead of being retired"
        )
