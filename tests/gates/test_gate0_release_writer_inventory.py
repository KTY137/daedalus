from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from daedalus.gates.release import Gate0ReleaseBindingError, Gate0ReleaseBlocked
from daedalus.gates.report import GateReport
from daedalus.spine.writer_inventory import scan_event_store_writers

ROOT = Path(__file__).resolve().parents[2]
BASE_TEST = ROOT / "tests" / "gates" / "test_gate0_release_assessment.py"


def _load_base():
    name = "daedalus_test_gate0_release_assessment_helpers"
    spec = importlib.util.spec_from_file_location(name, BASE_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()


def _legacy_writer(root: Path) -> None:
    (root / "daedalus" / "legacy_writer.py").write_text(
        "from daedalus.spine import SpineLedger\n"
        "SpineLedger('state.sqlite3')\n",
        encoding="utf-8", newline="\n",
    )


def _bound_inputs(root: Path, report: GateReport):
    index = base._release_index(base.fixture._index(), report)
    bundle = base.fixture._bundle(index, root)
    return index, bundle


def test_release_refuses_forged_empty_writer_failure_projection(tmp_path: Path) -> None:
    root, _, _, _ = base._inputs(tmp_path / "base")
    _legacy_writer(root)
    inventory = scan_event_store_writers(
        root,
        source_revision=base.fixture.REVISION,
    )
    assert inventory.blockers
    forged = GateReport(
        gate=0,
        source_revision=base.fixture.REVISION,
        registry_sha256=base.fixture.REGISTRY,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256=inventory.digest,
        event_store_writer_failures=(),
    )
    assert forged.closed is True
    index, bundle = _bound_inputs(root, forged)

    with pytest.raises(
        Gate0ReleaseBindingError,
        match="event_store_writer_failures",
    ):
        base._historical_assess(forged, index, bundle, root)


def test_release_reports_live_writer_blockers_before_generic_open_report(
    tmp_path: Path,
) -> None:
    root, _, _, _ = base._inputs(tmp_path / "base")
    _legacy_writer(root)
    inventory = scan_event_store_writers(
        root,
        source_revision=base.fixture.REVISION,
    )
    failures = tuple(
        f"{site.path}:{site.line}:{site.column}:{site.kind}:{site.callee}"
        for site in inventory.blockers
    )
    blocked = GateReport(
        gate=0,
        source_revision=base.fixture.REVISION,
        registry_sha256=base.fixture.REGISTRY,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256=inventory.digest,
        event_store_writer_failures=failures,
    )
    assert blocked.closed is False
    index, bundle = _bound_inputs(root, blocked)

    with pytest.raises(
        Gate0ReleaseBlocked,
        match="live Event-Store writer blockers remain",
    ):
        base._historical_assess(blocked, index, bundle, root)
