"""What does and does not clear a repository write surface.

These tests pin the coverage semantics that ``daedalus/gates/report_v3.py``
actually implements, because the semantics are easy to assume wrongly.  The
assumption worth refuting is that a write surface stops being a blocker once
some registered entrypoint covers the file it lives in.  It does not: the v3
report derives ``repository_write_failures`` from the generation-2 inventory
alone, and that inventory blocks on the syntactic kind of the callsite.  There
is no door lookup, no anchor reachability, and no declaration table in that
path at all.

The remaining tests pin the two scanner corrections that removed genuine false
positives without opening a hole: an unnameable receiver no longer hides the
mode of ``X.open(...)``, and the stdlib delta no longer restates an ``open``
the base scanner already decided.

See docs/inventory/2026-08-22/WRITE_SURFACE_CLOSURE.md.
"""
from __future__ import annotations

import collections
import functools
from pathlib import Path

import pytest

from daedalus.gates import repository_write_inventory as base_inventory
from daedalus.gates.repository_write_inventory import scan_repository_write_surfaces
from daedalus.gates.repository_write_inventory_v2 import (
    scan_repository_write_surfaces_v2,
)
from daedalus.gates.repository_write_stdlib_delta import (
    scan_repository_write_stdlib_delta,
)
from daedalus.spine.effect_boundary import ENTRYPOINTS


REVISION = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def _repository_inventory():
    """One full-tree scan for the whole module.

    A generation-2 scan of this repository walks ~290 production files three
    times (base, delta, base again for the drift fence) and costs tens of
    seconds.  Every test below reads the same revision-bound result, so it is
    computed once.
    """

    return scan_repository_write_surfaces_v2(ROOT, source_revision=REVISION)


def _repository(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "surface.py").write_text(source, encoding="utf-8")
    return root


def _surfaces(tmp_path: Path, source: str):
    return scan_repository_write_surfaces_v2(
        _repository(tmp_path, source),
        source_revision=REVISION,
    ).surfaces


def _rows(surfaces):
    return [(item.line, item.callee, item.kind, item.operation) for item in surfaces]


# --------------------------------------------------------------------------
# The coverage rule itself.
# --------------------------------------------------------------------------


def test_a_registered_door_does_not_clear_the_write_surfaces_behind_it() -> None:
    """Door reachability is not a coverage channel, and must not become one silently.

    ``daedalus/cli.py`` is the target module of a registered entrypoint that
    already declares ``FILESYSTEM_WRITE`` and ``REPOSITORY_MUTATION``.  Its
    write surfaces are still blockers, and every other module reached only
    through that door is blocking on its own callsites.  If someone later
    subtracts door-covered surfaces from the report without an evidence
    binding, this test goes red.
    """

    door_modules = {
        spec.target.split(":")[0] for spec in ENTRYPOINTS if spec.target
    }
    assert "daedalus.cli" in door_modules

    inventory = _repository_inventory()
    assert inventory.surfaces, "the scanner must find production write surfaces"

    def module_of(path: str) -> str:
        return path[:-3].replace("/", ".").removesuffix(".__init__")

    behind_a_door = [
        surface
        for surface in inventory.surfaces
        if module_of(surface.path) in door_modules
    ]
    assert behind_a_door, "expected surfaces inside registered door modules"
    assert all(surface.blocking for surface in behind_a_door)

    # And the report-level consequence: every surface the scanner emits is a
    # blocker except the one kind the scanner itself proves harmless.
    non_blocking = {
        surface.kind for surface in inventory.surfaces if not surface.blocking
    }
    assert non_blocking <= {"sqlite_read_only"}


def test_blocking_is_decided_by_kind_alone() -> None:
    """No declaration table participates in the v3 blocker decision."""

    allowed = base_inventory._ALLOWED_KINDS
    blocking = base_inventory._BLOCKING_KINDS
    assert allowed - blocking == {"sqlite_read_only"}

    # A surface carries no field a declaration could bind to: path, position,
    # origin, kind, callee, operation, blocking.  If a coverage field is ever
    # added, this test is the place that must be revisited on purpose.
    surface_fields = {
        "path",
        "line",
        "column",
        "origin",
        "kind",
        "callee",
        "operation",
        "blocking",
    }
    inventory = _repository_inventory()
    assert set(inventory.surfaces[0].to_dict()) == surface_fields


# --------------------------------------------------------------------------
# The correction: an unnameable receiver no longer hides a decided mode.
# --------------------------------------------------------------------------


AMBIGUOUS_RECEIVER_OPENS = """
from pathlib import Path


def use(name, dynamic_mode):
    path = Path(name)
    path.open('rb')
    path.open('r', encoding='utf-8')
    path.open()
    path.open(encoding='utf-8')
    path.open('wb')
    path.open('a')
    path.open(mode='x')
    path.open(dynamic_mode)
    path.open('some/database')
"""


def test_a_proven_read_on_an_unnameable_receiver_is_not_a_write_surface(
    tmp_path: Path,
) -> None:
    """``path`` is rebound in the module, so the scanner cannot name the receiver.

    The mode argument settles the call anyway, and a read is not a write
    surface.  Before this correction all nine calls were emitted as
    ``ambiguous_binding``.
    """

    rows = _rows(_surfaces(tmp_path, AMBIGUOUS_RECEIVER_OPENS))
    lines = {line for line, _, _, _ in rows}

    # The four proven reads are gone.
    assert lines.isdisjoint({7, 8, 9, 10})


def test_a_proven_write_on_an_unnameable_receiver_keeps_its_exact_mode(
    tmp_path: Path,
) -> None:
    rows = _rows(_surfaces(tmp_path, AMBIGUOUS_RECEIVER_OPENS))
    decided = {
        line: (kind, operation)
        for line, _, kind, operation in rows
        if line in {11, 12, 13}
    }
    assert decided == {
        11: ("write_mode_open", "wb"),
        12: ("write_mode_open", "a"),
        13: ("write_mode_open", "x"),
    }


def test_an_undecidable_writer_on_an_unnameable_receiver_still_blocks(
    tmp_path: Path,
) -> None:
    """The correction must not become a way out for a writer nobody can read.

    A dynamic mode keeps the binding blocker.  A string literal that is not a
    mode string is evidence that the inspected argument is not the mode
    argument -- ``shelve.open(path)`` creates its database -- so it keeps the
    binding blocker too, rather than being read as proof of a read.
    """

    surfaces = _surfaces(tmp_path, AMBIGUOUS_RECEIVER_OPENS)
    undecidable = {
        line: (kind, operation)
        for line, _, kind, operation in _rows(surfaces)
        if line in {14, 15}
    }
    assert undecidable == {
        14: ("ambiguous_binding", "rebound-or-conflicting-binding"),
        15: ("ambiguous_binding", "rebound-or-conflicting-binding"),
    }
    assert all(surface.blocking for surface in surfaces)


def test_a_bare_rebound_open_is_still_a_binding_blocker(tmp_path: Path) -> None:
    """Rebinding a bare ``open`` changes which callable runs, not which object opens.

    The mode argument cannot settle that, so the undotted case stays outside
    the correction.
    """

    rows = _rows(
        _surfaces(
            tmp_path,
            """
def use(open):
    open('x', 'rb')
""",
        )
    )
    assert rows == [(3, "open", "ambiguous_binding", "rebound-or-conflicting-binding")]


# --------------------------------------------------------------------------
# The correction: the delta does not restate a base-owned ``open``.
# --------------------------------------------------------------------------


BASE_OWNED_OPENS = """
import os


def use(path):
    with open(path, 'r', encoding='utf-8') as fh:
        fh.read()
    descriptor = os.open(path, os.O_RDONLY)
    os.close(descriptor)
    with open(path, 'wb') as out:
        out.write(b'x')
"""


def test_the_delta_does_not_restate_a_read_the_base_scanner_cleared(
    tmp_path: Path,
) -> None:
    """The base scanner proves both reads harmless; the delta must not resurrect them."""

    root = _repository(tmp_path, BASE_OWNED_OPENS)
    findings = scan_repository_write_stdlib_delta(
        root, source_revision=REVISION
    ).findings
    assert [item.callee for item in findings if item.callee in {"open", "os.open"}] == []

    surfaces = scan_repository_write_surfaces_v2(
        root, source_revision=REVISION
    ).surfaces
    # Only the write open and the write on its handle survive.  The handle is
    # bound by the ``with`` statement, so the delta reports it under its
    # ambiguous-binding kind rather than as a resolved stream sink -- still
    # blocking, which is the point.
    assert [(item.line, item.callee, item.kind) for item in surfaces] == [
        (10, "open", "write_mode_open"),
        (11, "out.write", "ambiguous_stdlib_binding"),
    ]


def test_the_base_scanner_still_owns_the_write_open(tmp_path: Path) -> None:
    """Removing the delta's restatement must not remove the surface itself."""

    sites = scan_repository_write_surfaces(
        _repository(tmp_path, BASE_OWNED_OPENS),
        source_revision=REVISION,
    ).callsites
    assert [(item.line, item.kind, item.operation) for item in sites] == [
        (10, "write_mode_open", "wb")
    ]


def test_an_aliased_compression_open_stays_with_the_delta(tmp_path: Path) -> None:
    """The five mode-openers resolve before any terminal fallback, so they are unaffected."""

    root = _repository(
        tmp_path,
        """
import gzip
import tarfile

gzip.open('a.gz', 'wb')
tarfile.open('a.tar', 'w:gz')
""",
    )
    writers = {
        (item.callee, item.kind)
        for item in scan_repository_write_surfaces_v2(
            root, source_revision=REVISION
        ).surfaces
    }
    assert ("gzip.open", "write_mode_open") in writers
    assert ("tarfile.open", "write_mode_open") in writers


# --------------------------------------------------------------------------
# The three worked kernel files.
# --------------------------------------------------------------------------


# Multisets of (kind, callee, operation), pinned by content rather than line
# number so an unrelated edit above a callsite does not move the pin.  Every
# entry is a real write-capable callsite reached through a caller-supplied
# path; none of these modules is an entrypoint of its own.
KERNEL_FILE_SURFACES: dict[str, dict[tuple[str, str, str], int]] = {
    "daedalus/atomic.py": {
        ("ambiguous_binding", "target.parent.mkdir", "rebound-or-conflicting-binding"): 3,
        ("ambiguous_binding", "tmp.unlink", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "tmp.write_bytes", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "tmp.write_text", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_stdlib_binding", "fh.write", "rebound-or-conflicting-binding"): 1,
        ("filesystem_mutation", "os.link", "link"): 1,
        ("filesystem_mutation", "os.replace", "replace"): 1,
        ("filesystem_mutation", "os.unlink", "unlink"): 1,
        ("write_mode_open", "tmp.open", "xb"): 1,
    },
    "daedalus/kernel/promotion_trust_root.py": {
        ("ambiguous_binding", "path.parent.mkdir", "rebound-or-conflicting-binding"): 2,
        ("ambiguous_binding", "root.mkdir", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_stdlib_binding", "fh.write", "rebound-or-conflicting-binding"): 4,
        ("filesystem_mutation", "os.unlink", "unlink"): 1,
        ("filesystem_mutation", "tempfile.mkstemp", "mkstemp"): 1,
        ("os_open_write", "os.open", "O_CREAT+O_EXCL+O_WRONLY"): 1,
        ("process_effect_unknown", "subprocess.run", "dynamic-command"): 1,
        ("write_mode_open", "open", "a"): 2,
    },
    "daedalus/kernel/source_trees.py": {
        ("ambiguous_binding", "output.chmod", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "output.parent.mkdir", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "raw.mkdir", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "self.objects.mkdir", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_binding", "target.parent.mkdir", "rebound-or-conflicting-binding"): 2,
        ("ambiguous_binding", "temporary.unlink", "rebound-or-conflicting-binding"): 1,
        ("ambiguous_os_open_flags", "os.open", "dynamic-flags"): 2,
        ("ambiguous_stdlib_binding", "stream.write", "rebound-or-conflicting-binding"): 2,
        ("filesystem_mutation", "os.link", "link"): 1,
        ("filesystem_mutation", "os.replace", "replace"): 1,
        ("filesystem_mutation", "shutil.rmtree", "rmtree"): 1,
        ("filesystem_mutation", "tempfile.mkdtemp", "mkdtemp"): 1,
        ("filesystem_mutation", "tempfile.mkstemp", "mkstemp"): 1,
        ("write_mode_open", "output.open", "xb"): 1,
    },
}


@pytest.mark.parametrize("relative", sorted(KERNEL_FILE_SURFACES))
def test_the_worked_kernel_files_are_classified_as_the_document_says(
    relative: str,
) -> None:
    inventory = _repository_inventory()
    observed = collections.Counter(
        (surface.kind, surface.callee, surface.operation)
        for surface in inventory.surfaces
        if surface.path == relative
    )
    assert dict(observed) == KERNEL_FILE_SURFACES[relative]


@pytest.mark.parametrize("relative", sorted(KERNEL_FILE_SURFACES))
def test_the_worked_kernel_files_are_not_doors_of_their_own(relative: str) -> None:
    """None of the three is an entrypoint; each is reached through a caller.

    That is why none of them gains a registry row, and -- per the coverage rule
    above -- why a row would not have cleared a single surface anyway.
    """

    module = relative[:-3].replace("/", ".")
    targets = {spec.target.split(":")[0] for spec in ENTRYPOINTS if spec.target}
    assert module not in targets
    source = (ROOT / relative).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' not in source
    assert "argparse" not in source
