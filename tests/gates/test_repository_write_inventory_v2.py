from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import daedalus.gates.repository_write_inventory_v2 as inventory_v2
from daedalus.gates.repository_write_inventory import (
    scan_repository_write_surfaces,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2Error,
    scan_repository_write_surfaces_v2,
)
from daedalus.gates.repository_write_stdlib_delta import (
    RepositoryWriteStdlibDelta,
    RepositoryWriteStdlibFinding,
    scan_repository_write_stdlib_delta,
)
from daedalus.spine.envelope import canonical_json
from scripts.report_repository_write_inventory_v2 import main


REVISION = "a" * 40


def _repository(tmp_path: Path, source: str) -> Path:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "surface.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_generation_two_merges_base_and_stdlib_delta(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        "from pathlib import Path\n"
        "import os\n"
        "Path('state').write_text('x')\n"
        "os.write(1, b'x')\n",
    )

    report = scan_repository_write_surfaces_v2(
        root,
        source_revision=REVISION,
    )
    material = report.to_dict()

    assert material["canonical_scanner_integrated"] is True
    assert material["inventory_generation"] == 2
    assert material["inventory_only"] is True
    assert material["primary_checkout_target_proven"] is False
    assert material["closed"] is False
    assert material["blockers"] == [
        "unclassified-production-write-surfaces"
    ]
    assert {surface["origin"] for surface in material["surfaces"]} == {
        "base_v1",
        "stdlib_delta_v1",
    }
    # The canonical scanner does not guess an unresolved receiver type: the
    # `Path('state')` receiver is a call expression, so the surface is named
    # `<expression>.write_text` rather than claiming `pathlib.Path.write_text`.
    # It stays a blocking base surface either way.
    write_text = next(
        surface
        for surface in material["surfaces"]
        if surface["operation"] == "write_text"
    )
    assert write_text["origin"] == "base_v1"
    assert write_text["kind"] == "path_mutation"
    assert write_text["callee"] == "<expression>.write_text"
    assert write_text["blocking"] is True
    assert "os.write" in {surface["callee"] for surface in material["surfaces"]}
    os_write = next(
        surface
        for surface in material["surfaces"]
        if surface["callee"] == "os.write"
    )
    assert os_write["origin"] == "stdlib_delta_v1"
    assert os_write["blocking"] is True
    assert material["surface_count"] == len(material["surfaces"])
    assert material["blocker_count"] == sum(
        surface["blocking"] for surface in material["surfaces"]
    )
    payload = {key: value for key, value in material.items() if key != "digest"}
    assert report.digest == __import__("hashlib").sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()


def test_empty_production_surface_can_close_inventory_only_report(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "VALUE = 1\n")

    report = scan_repository_write_surfaces_v2(
        root,
        source_revision=REVISION,
    )

    assert report.closed is True
    assert report.blockers == ()
    assert report.to_dict()["blockers"] == []
    assert report.to_dict()["canonical_scanner_integrated"] is True
    assert report.to_dict()["primary_checkout_target_proven"] is False


@pytest.mark.parametrize(
    "revision",
    ["", "A" * 40, "a" * 39, "a" * 41, "g" * 40, None],
)
def test_malformed_revision_refuses_before_component_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision: object,
) -> None:
    root = _repository(tmp_path, "VALUE = 1\n")
    called = False

    def unexpected(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("component scanner must not run")

    monkeypatch.setattr(inventory_v2, "scan_repository_write_surfaces", unexpected)

    with pytest.raises(RepositoryWriteInventoryV2Error):
        scan_repository_write_surfaces_v2(  # type: ignore[arg-type]
            root,
            source_revision=revision,
        )
    assert called is False


def test_stale_component_revision_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path, "VALUE = 1\n")
    base = scan_repository_write_surfaces(root, source_revision=REVISION)
    delta = scan_repository_write_stdlib_delta(root, source_revision=REVISION)
    stale_delta = dataclasses.replace(delta, source_revision="b" * 40)
    bases = iter((base, base))

    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_surfaces",
        lambda *args, **kwargs: next(bases),
    )
    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_stdlib_delta",
        lambda *args, **kwargs: stale_delta,
    )

    with pytest.raises(
        RepositoryWriteInventoryV2Error,
        match="source revisions differ",
    ):
        scan_repository_write_surfaces_v2(root, source_revision=REVISION)


def test_stale_byte_projection_between_component_scans_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path, "VALUE = 1\n")
    base = scan_repository_write_surfaces(root, source_revision=REVISION)
    delta = scan_repository_write_stdlib_delta(root, source_revision=REVISION)
    changed_delta = dataclasses.replace(delta, scan_input_sha256="f" * 64)
    bases = iter((base, base))

    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_surfaces",
        lambda *args, **kwargs: next(bases),
    )
    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_stdlib_delta",
        lambda *args, **kwargs: changed_delta,
    )

    with pytest.raises(
        RepositoryWriteInventoryV2Error,
        match="production bytes changed",
    ):
        scan_repository_write_surfaces_v2(root, source_revision=REVISION)


def test_cross_component_position_overlap_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(
        tmp_path,
        "from pathlib import Path\nPath('state').write_text('x')\n",
    )
    base = scan_repository_write_surfaces(root, source_revision=REVISION)
    assert len(base.callsites) == 1
    site = base.callsites[0]
    overlap = RepositoryWriteStdlibFinding(
        path=site.path,
        line=site.line,
        column=site.column,
        kind="filesystem_mutation",
        callee="os.write",
        operation="write",
    )
    delta = RepositoryWriteStdlibDelta(
        source_revision=REVISION,
        base_inventory_digest=base.digest,
        scan_input_sha256=base.scan_input_sha256,
        files_scanned=base.files_scanned,
        findings=(overlap,),
    )
    bases = iter((base, base))

    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_surfaces",
        lambda *args, **kwargs: next(bases),
    )
    monkeypatch.setattr(
        inventory_v2,
        "scan_repository_write_stdlib_delta",
        lambda *args, **kwargs: delta,
    )

    with pytest.raises(
        RepositoryWriteInventoryV2Error,
        match="overlap",
    ):
        scan_repository_write_surfaces_v2(root, source_revision=REVISION)


def test_schema_required_fields_match_report(tmp_path: Path) -> None:
    root = _repository(tmp_path, "VALUE = 1\n")
    material = scan_repository_write_surfaces_v2(
        root,
        source_revision=REVISION,
    ).to_dict()
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "configs/schemas/repository-write-inventory-v2.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert set(schema["required"]) == set(material)
    assert schema["properties"]["schema"]["const"] == material["schema"]
    assert schema["properties"]["inventory_generation"]["const"] == 2
    assert schema["properties"]["canonical_scanner_integrated"]["const"] is True
    assert schema["properties"]["inventory_only"]["const"] is True
    assert (
        schema["properties"]["primary_checkout_target_proven"]["const"]
        is False
    )


def test_cli_emits_schema_and_scoped_closed_assertion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repository(tmp_path, "import os\nos.write(1, b'x')\n")

    assert main([str(root), "--source-revision", REVISION]) == 0
    material = json.loads(capsys.readouterr().out)
    assert material["schema"] == "daedalus-gate0-repository-write-inventory/2"
    assert material["closed"] is False

    assert (
        main(
            [
                str(root),
                "--source-revision",
                REVISION,
                "--require-closed",
            ]
        )
        == 2
    )
    material = json.loads(capsys.readouterr().out)
    assert material["blocker_count"] > 0
