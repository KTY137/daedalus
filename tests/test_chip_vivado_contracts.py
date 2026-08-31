from __future__ import annotations

import ctypes
import hashlib
import json
import os
import tkinter
from collections.abc import Mapping
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from daedalus.chip_design import cli as chip_cli
from daedalus.chip_design.manifest import (
    VivadoManifestError,
    build_vivado_project_manifest,
    canonical_path_identity,
)
from daedalus.chip_design.publication import (
    vivado_message_report_passed,
    vivado_rule_report_passed,
)
from daedalus.chip_design.vivado_reports import (
    parse_vivado_drc,
    parse_vivado_message_counts,
    parse_vivado_message_counts_bytes,
    parse_vivado_methodology,
    parse_vivado_report,
    parse_vivado_report_bytes,
    parse_vivado_route_status,
    parse_vivado_timing_summary,
    parse_vivado_utilization,
    vivado_artifact_identity,
)
from daedalus.chip_design.vivado_tcl import (
    VivadoTclContractError,
    build_vivado_flow_argv,
    trusted_vivado_tcl,
)


PART = "xc7a35ticsg324-1L"
BOARD = "digilentinc.com:arty-a7-35:part0:1.1"


def _write_project(
    root: Path,
    *,
    project_path_metadata: str = "portable/demo.xpr",
    bad_references: bool = False,
    run_state: str = "current",
    volatile_run_root: str = "$PRUNDIR",
    synth_strategy: str = "Vivado Synthesis Defaults",
    synth_auto_incremental: str = "false",
) -> Path:
    rtl = root / "demo.srcs" / "sources_1" / "new" / "top.sv"
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    xci = bd.parent / "ip" / "timer" / "timer.xci"
    xdc = root / "demo.srcs" / "constrs_1" / "new" / "pins.xdc"
    for path, text in (
        (rtl, "module top; endmodule\n"),
        (
            bd,
            '{"design":{"design_info":{"gen_directory":'
            '"../../../../demo.gen/sources_1/bd/system"}}}\n',
        ),
        (
            xci,
            '{"schema":"xilinx.com:schema:json_instance:1.0",'
            '"ip_inst":{"component_reference":"xilinx.com:ip:timer:1.0",'
            '"gen_directory":'
            '"../../../../../../demo.gen/sources_1/bd/system/ip/timer",'
            '"parameters":{"component_parameters":{},'
            '"runtime_parameters":{"OUTPUTDIR":[{"value":'
            '"../../../../../../demo.gen/sources_1/bd/system/ip/timer"}],'
            '"SHAREDDIR":[{"value":"../../ipshared"}]}}}}\n',
        ),
        (xdc, "set_property PACKAGE_PIN A1 [get_ports clk]\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    extra_files = ""
    if bad_references:
        outside = root.parent / "outside-active.sv"
        outside.write_text("module outside_active; endmodule\n", encoding="utf-8")
        extra_files = f"""
      <File Path="{escape(str(outside))}">
        <FileInfo><Attr Name="UsedIn" Val="synthesis"/></FileInfo>
      </File>
      <File Path="$PSRCDIR/sources_1/new/missing.sv"/>
      <File Path="$UNKNOWN_ROOT/not-resolved.sv"/>
"""

    xpr = root / "demo.xpr"
    xpr.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Project Product="Vivado" Version="7" Minor="64" Path="{escape(project_path_metadata)}">
  <Configuration>
    <Option Name="Part" Val="{PART}"/>
    <Option Name="BoardPart" Val="{BOARD}"/>
  </Configuration>
  <FileSets>
    <FileSet Name="sources_1" Type="DesignSrcs">
      <File Path="$PSRCDIR/sources_1/new/top.sv">
        <FileInfo>
          <Attr Name="UsedIn" Val="synthesis"/>
          <Attr Name="ImportPath" Val="../historical/top.sv"/>
        </FileInfo>
      </File>
      <File Path="$PSRCDIR/sources_1/bd/system/system.bd">
        <CompFileExtendedInfo FileRelPathName="ip/timer/timer.xci"/>
      </File>
{extra_files}      <Config><Option Name="TopModule" Val="top"/></Config>
    </FileSet>
    <FileSet Name="constrs_1" Type="Constrs">
      <File Path="$PSRCDIR/constrs_1/new/pins.xdc">
        <FileInfo><Attr Name="UsedIn" Val="implementation"/></FileInfo>
      </File>
    </FileSet>
  </FileSets>
  <Runs>
    <Run Id="synth_1" Type="Ft3:Synth" SrcSet="sources_1" ConstrsSet="constrs_1" Part="{PART}" Description="Synthesis label" AutoIncrementalCheckpoint="{escape(synth_auto_incremental)}" State="{escape(run_state)}" Dir="{escape(volatile_run_root)}/synth_1" AutoIncrementalDir="{escape(volatile_run_root)}/auto/synth_1" AutoRQSDir="{escape(volatile_run_root)}/rqs/synth_1" IncludeInArchive="true" ParallelReportGen="true">
      <Strategy Version="1" Minor="2">
        <StratHandle Name="{escape(synth_strategy)}" Flow="Vivado Synthesis 2025"/>
        <Step Id="synth_design">
          <Option Id="flatten_hierarchy" Val="rebuilt"/>
        </Step>
      </Strategy>
      <GeneratedRun Dir="{escape(volatile_run_root)}" File="gen_run.xml"/>
      <ReportStrategy Name="Vivado Synthesis Default Reports" Flow="Vivado Synthesis 2025"/>
      <Report Name="SYNTH_DESIGN.REPORT_UTILIZATION" Enabled="1"/>
    </Run>
    <Run Id="impl_1" Type="Ft2:EntireDesign" SrcSet="sources_1" ConstrsSet="constrs_1" SynthRun="synth_1" Part="{PART}" State="{escape(run_state)}" Dir="{escape(volatile_run_root)}/impl_1">
      <Strategy Version="1" Minor="2">
        <StratHandle Name="Vivado Implementation Defaults" Flow="Vivado Implementation 2025"/>
        <Step Id="opt_design"/>
        <Step Id="place_design"/>
        <Step Id="route_design"/>
      </Strategy>
      <GeneratedRun Dir="{escape(volatile_run_root)}" File="gen_run.xml"/>
    </Run>
  </Runs>
</Project>
""",
        encoding="utf-8",
    )
    return xpr


def _write(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


TIMING_REPORT = """
| Tool Version : Vivado v.2025.1.1 (win64) Build 6233196
| Design       : top
| Device       : xc7a35ticsg324-1L
| Design State : Routed
Timing Summary Report
1. checking no_clock (0)
2. checking unconstrained_internal_endpoints (0)
3. checking no_output_delay (13)
Design Timing Summary
    WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) THS Failing Endpoints THS Total Endpoints WPWS(ns) TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints
    ------- ------- --------------------- ------------------- ------- ------- --------------------- ------------------- -------- -------- ---------------------- --------------------
      0.162   0.000 0 25854 0.021 0.000 0 25818 1.020 0.000 0 8720
All user specified timing constraints are met.
"""

UTILIZATION_REPORT = """
| Tool Version : Vivado v.2025.1.1 (win64) Build 6233196
| Design       : top
| Device       : xc7a35ticsg324-1L
| Design State : Routed
Utilization Design Information
| Slice LUTs      | 7,368 | 0 | 0 | 20,800 | 35.42 |
| Slice Registers | 7,262 | 0 | 0 | 41,600 | 17.46 |
| Block RAM Tile  | 45    | 0 | 0 | 50     | 90.00 |
| DSPs            | 3     | 0 | 0 | 90     | 3.33  |
"""

DRC_REPORT = """
Report DRC
Checks found: 7
| Rule      | Severity | Description                                    | Checks |
| CFGBVS-1  | Warning  | Missing configuration voltage                  | 1      |
| REQP-1840 | Warning  | RAMB18 async control check                     | 5      |
| RTSTAT-10 | Warning  | No routable loads                              | 1      |
"""

ROUTE_REPORT = """
Design Route Status
   # of logical nets.......................... :       24574 :
       # of nets not needing routing.......... :       12237 :
       # of routable nets..................... :       12337 :
           # of fully routed nets............. :       12337 :
       # of nets with routing errors.......... :           0 :
"""


def test_manifest_binds_xpr_bd_xci_and_classifies_bad_references(tmp_path: Path) -> None:
    root = tmp_path / "project with spaces $[safe]"
    root.mkdir()
    xpr = _write_project(root, bad_references=True)

    manifest = build_vivado_project_manifest(xpr, project_root=root)
    body = manifest.to_dict()
    refs = {(ref.reference_type, ref.raw_path): ref for ref in manifest.file_references}

    assert manifest.part == PART
    assert manifest.board_part == BOARD
    assert manifest.top == "top"
    assert [item.name for item in manifest.filesets] == ["sources_1", "constrs_1"]
    assert [item.name for item in manifest.runs] == ["impl_1", "synth_1"]
    assert body["project"]["path"] == "demo.xpr"
    assert body["project"]["sha256"] == hashlib.sha256(xpr.read_bytes()).hexdigest()
    assert body["source_identity_sha256"] == manifest.source_identity_sha256
    assert body["complete"] is False

    bd = refs[("file", "$PSRCDIR/sources_1/bd/system/system.bd")]
    xci = refs[("ip_configuration", "ip/timer/timer.xci")]
    assert (bd.kind, bd.status, len(bd.sha256 or "")) == (
        "vivado_block_design",
        "present",
        64,
    )
    assert (xci.kind, xci.status, len(xci.sha256 or "")) == (
        "vivado_ip_configuration",
        "present",
        64,
    )
    outside = next(
        ref
        for ref in manifest.file_references
        if ref.status == "outside" and ref.reference_type == "file"
    )
    assert outside.exists is True
    assert outside.sha256 is None
    assert "$PSRCDIR/sources_1/new/missing.sv" in manifest.missing_references
    assert "$UNKNOWN_ROOT/not-resolved.sv" in manifest.unresolved_references


def test_source_identity_survives_xpr_relocation_metadata_but_exact_xpr_does_not(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "source"
    second_root = tmp_path / "isolated-workspace"
    first_root.mkdir()
    second_root.mkdir()
    first = build_vivado_project_manifest(
        _write_project(first_root, project_path_metadata=r"C:\source\demo.xpr")
    )
    second = build_vivado_project_manifest(
        _write_project(
            second_root,
            project_path_metadata=r"D:\workspace\demo.xpr",
            run_state="needs_refresh",
            volatile_run_root="$PPRDIR/demo.runs",
        )
    )

    assert first.project.sha256 != second.project.sha256
    assert first.sha256 != second.sha256
    assert first.source_identity_body() == second.source_identity_body()
    assert first.source_identity_sha256 == second.source_identity_sha256
    run_identity = first.source_identity_body()["runs"][0]
    assert "directory" not in run_identity
    assert len(run_identity["configuration_sha256"]) == 64
    assert first.runs[0].directory != second.runs[0].directory


def test_source_identity_binds_run_strategy_and_semantic_configuration(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    strategy_root = tmp_path / "strategy-change"
    configuration_root = tmp_path / "configuration-change"
    baseline_root.mkdir()
    strategy_root.mkdir()
    configuration_root.mkdir()

    baseline = build_vivado_project_manifest(_write_project(baseline_root))
    strategy_change = build_vivado_project_manifest(
        _write_project(strategy_root, synth_strategy="Flow_PerfOptimized_high")
    )
    configuration_change = build_vivado_project_manifest(
        _write_project(configuration_root, synth_auto_incremental="true")
    )

    baseline_synth = next(run for run in baseline.runs if run.name == "synth_1")
    strategy_synth = next(run for run in strategy_change.runs if run.name == "synth_1")
    configuration_synth = next(
        run for run in configuration_change.runs if run.name == "synth_1"
    )
    assert baseline_synth.configuration_sha256 != strategy_synth.configuration_sha256
    assert baseline_synth.configuration_sha256 != configuration_synth.configuration_sha256
    assert baseline.source_identity_sha256 != strategy_change.source_identity_sha256
    assert baseline.source_identity_sha256 != configuration_change.source_identity_sha256


def test_source_identity_binds_file_order_and_xdc_execution_metadata(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline-file-contract"
    reordered_root = tmp_path / "reordered-file-contract"
    metadata_root = tmp_path / "metadata-file-contract"
    for root in (baseline_root, reordered_root, metadata_root):
        root.mkdir()

    baseline = build_vivado_project_manifest(_write_project(baseline_root))

    reordered_xpr = _write_project(reordered_root)
    reordered_text = reordered_xpr.read_text(encoding="utf-8")
    source_block = """      <File Path="$PSRCDIR/sources_1/new/top.sv">
        <FileInfo>
          <Attr Name="UsedIn" Val="synthesis"/>
          <Attr Name="ImportPath" Val="../historical/top.sv"/>
        </FileInfo>
      </File>
"""
    block_design = """      <File Path="$PSRCDIR/sources_1/bd/system/system.bd">
        <CompFileExtendedInfo FileRelPathName="ip/timer/timer.xci"/>
      </File>
"""
    assert source_block + block_design in reordered_text
    reordered_xpr.write_text(
        reordered_text.replace(
            source_block + block_design,
            block_design + source_block,
            1,
        ),
        encoding="utf-8",
    )
    reordered = build_vivado_project_manifest(reordered_xpr)

    metadata_xpr = _write_project(metadata_root)
    metadata_text = metadata_xpr.read_text(encoding="utf-8")
    old_xdc = (
        '<FileInfo><Attr Name="UsedIn" Val="implementation"/></FileInfo>'
    )
    new_xdc = """<FileInfo>
          <Attr Name="UsedIn" Val="implementation"/>
          <Attr Name="FileType" Val="XDC"/>
          <Attr Name="ProcessingOrder" Val="LATE"/>
          <Attr Name="ScopedToRef" Val="system"/>
          <Attr Name="ScopedToCells" Val="u_core"/>
        </FileInfo>"""
    assert old_xdc in metadata_text
    metadata_xpr.write_text(
        metadata_text.replace(old_xdc, new_xdc, 1),
        encoding="utf-8",
    )
    metadata = build_vivado_project_manifest(metadata_xpr)
    xdc = next(ref for ref in metadata.file_references if ref.kind == "constraint")

    assert baseline.source_identity_sha256 != reordered.source_identity_sha256
    assert baseline.source_identity_sha256 != metadata.source_identity_sha256
    assert (xdc.file_type, xdc.processing_order) == ("XDC", "LATE")
    assert (xdc.scoped_to_ref, xdc.scoped_to_cells) == ("system", "u_core")


def test_source_identity_binds_all_fileset_configuration(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline-fileset"
    changed_root = tmp_path / "changed-fileset"
    baseline_root.mkdir()
    changed_root.mkdir()
    baseline = build_vivado_project_manifest(_write_project(baseline_root))
    changed_xpr = _write_project(changed_root)
    payload = changed_xpr.read_text(encoding="utf-8")
    marker = '<Config><Option Name="TopModule" Val="top"/></Config>'
    replacement = (
        '<Config><Option Name="TopModule" Val="top"/>'
        '<Option Name="VerilogDefines" Val="WORKSPACE_ONLY=1"/></Config>'
    )
    assert marker in payload
    changed_xpr.write_text(
        payload.replace(marker, replacement, 1),
        encoding="utf-8",
    )
    changed = build_vivado_project_manifest(changed_xpr)
    baseline_sources = next(row for row in baseline.filesets if row.name == "sources_1")
    changed_sources = next(row for row in changed.filesets if row.name == "sources_1")

    assert baseline_sources.configuration_sha256 != (
        changed_sources.configuration_sha256
    )
    assert baseline.source_identity_sha256 != changed.source_identity_sha256


def test_source_identity_binds_project_configuration_and_normalizes_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-project"
    workspace_root = tmp_path / "nested" / "workspace-project"
    changed_root = tmp_path / "changed-project"
    shared_board_repo = tmp_path / "shared-board-repo"
    for root in (source_root, workspace_root, changed_root, shared_board_repo):
        root.mkdir(parents=True)

    def configured(root: Path, *, default_lib: str) -> Path:
        xpr = _write_project(root)
        payload = xpr.read_text(encoding="utf-8")
        marker = f'<Option Name="BoardPart" Val="{BOARD}"/>'
        relative_repo = os.path.relpath(shared_board_repo, root).replace("\\", "/")
        replacement = (
            marker
            + f'\n    <Option Name="BoardPartRepoPaths" Val="$PPRDIR/{relative_repo}"/>'
            + f'\n    <Option Name="DefaultLib" Val="{default_lib}"/>'
        )
        assert marker in payload
        xpr.write_text(payload.replace(marker, replacement, 1), encoding="utf-8")
        return xpr

    source = build_vivado_project_manifest(
        configured(source_root, default_lib="xil_defaultlib")
    )
    relocated = build_vivado_project_manifest(
        configured(workspace_root, default_lib="xil_defaultlib")
    )
    changed = build_vivado_project_manifest(
        configured(changed_root, default_lib="workspace_only")
    )

    assert source.project_configuration_sha256 == (
        relocated.project_configuration_sha256
    )
    assert source.source_identity_sha256 == relocated.source_identity_sha256
    assert source.project_configuration_sha256 != (
        changed.project_configuration_sha256
    )
    assert source.source_identity_sha256 != changed.source_identity_sha256


@pytest.mark.parametrize(
    ("option_name", "attribute_name"),
    (
        ("IPRepoPath", "custom_ip_repository_paths"),
        ("IPRepoPaths", "custom_ip_repository_paths"),
        ("IP_REPO_PATHS", "custom_ip_repository_paths"),
        ("BoardPartRepoPaths", "custom_board_repository_paths"),
        ("BoardRepoPaths", "custom_board_repository_paths"),
        ("IncludeDirs", "include_directory_values"),
        ("VerilogIncludeDirs", "include_directory_values"),
    ),
)
def test_manifest_reports_and_refuses_unbound_repository_or_include_roots(
    tmp_path: Path,
    option_name: str,
    attribute_name: str,
) -> None:
    root = tmp_path / option_name
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = f'<Option Name="BoardPart" Val="{BOARD}"/>'
    injected = marker + f'\n    <Option Name="{option_name}" Val="$PPRDIR/external"/>'
    xpr.write_text(payload.replace(marker, injected, 1), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert getattr(manifest, attribute_name) == ("$PPRDIR/external",)
    assert manifest.complete is False


def test_manifest_recognizes_element_form_repository_properties(
    tmp_path: Path,
) -> None:
    root = tmp_path / "element-form-property"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = "  </Configuration>"
    xpr.write_text(
        payload.replace(
            marker,
            "    <BoardPartRepoPaths>$PPRDIR/boards</BoardPartRepoPaths>\n"
            + marker,
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert manifest.custom_board_repository_paths == ("$PPRDIR/boards",)
    assert manifest.complete is False


@pytest.mark.parametrize("suffix", (".xcix", ".xco"))
def test_manifest_refuses_core_containers_from_extended_info(
    tmp_path: Path,
    suffix: str,
) -> None:
    root = tmp_path / "core-container"
    root.mkdir()
    xpr = _write_project(root)
    xci = root / "demo.srcs" / "sources_1" / "bd" / "system" / "ip" / "timer" / "timer.xci"
    container = xci.with_suffix(suffix)
    xci.rename(container)
    payload = xpr.read_text(encoding="utf-8")
    xpr.write_text(payload.replace("timer.xci", f"timer{suffix}"), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(path.endswith(f"timer{suffix}") for path in manifest.refused_core_container_files)
    assert manifest.complete is False


@pytest.mark.parametrize("suffix", (".xcix", ".xco"))
def test_manifest_refuses_direct_core_container_files(
    tmp_path: Path,
    suffix: str,
) -> None:
    root = tmp_path / f"direct-{suffix[1:]}"
    root.mkdir()
    xpr = _write_project(root)
    container = root / "demo.srcs" / "sources_1" / "new" / f"opaque{suffix}"
    container.write_bytes(b"opaque core container")
    payload = xpr.read_text(encoding="utf-8")
    marker = '      <Config><Option Name="TopModule" Val="top"/></Config>'
    addition = (
        f'      <File Path="$PSRCDIR/sources_1/new/opaque{suffix}"/>\n'
        + marker
    )
    xpr.write_text(payload.replace(marker, addition, 1), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(path.endswith(f"opaque{suffix}") for path in manifest.refused_core_container_files)
    assert manifest.complete is False


@pytest.mark.parametrize(
    "attribute_value",
    ("$PPRDIR/../outside", "$UNKNOWN/fileset"),
)
def test_manifest_refuses_unbounded_fileset_roots(
    tmp_path: Path,
    attribute_value: str,
) -> None:
    root = tmp_path / "fileset-root"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = '<FileSet Name="sources_1" Type="DesignSrcs"'
    xpr.write_text(
        payload.replace(
            marker,
            marker + f' RelGenDir="{attribute_value}"',
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert manifest.refused_fileset_roots
    assert manifest.complete is False


@pytest.mark.parametrize(
    ("attribute_name", "attribute_value"),
    (
        ("RelGenDir", "$PSRCDIR/sources_1/new"),
        ("RelSrcDir", "$PGENDIR/sources_1"),
    ),
)
def test_manifest_refuses_fileset_roots_that_overlap_the_wrong_write_domain(
    tmp_path: Path,
    attribute_name: str,
    attribute_value: str,
) -> None:
    root = tmp_path / f"overlap-{attribute_name}"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = '<FileSet Name="sources_1" Type="DesignSrcs"'
    xpr.write_text(
        payload.replace(
            marker,
            marker + f' {attribute_name}="{attribute_value}"',
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert any(attribute_name in row for row in manifest.refused_fileset_roots)
    assert manifest.complete is False


def test_manifest_refuses_block_design_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "bd-path-escape"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    document = json.loads(bd.read_text(encoding="utf-8"))
    document["design"]["design_info"]["gen_directory"] = "$PPRDIR/../outside"
    bd.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any("outside project root" in row for row in manifest.refused_block_design_files)
    assert manifest.complete is False


def test_manifest_refuses_block_design_generation_inside_source_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bd-source-overlap"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    document = json.loads(bd.read_text(encoding="utf-8"))
    document["design"]["design_info"]["gen_directory"] = (
        "$PSRCDIR/sources_1/new"
    )
    bd.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "gen_directory outside generated root" in row
        for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


@pytest.mark.parametrize("invalid", ("duplicate", "nonfinite"))
def test_manifest_refuses_ambiguous_or_nonstandard_block_design_json(
    tmp_path: Path,
    invalid: str,
) -> None:
    root = tmp_path / f"bd-json-{invalid}"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    payload = bd.read_text(encoding="utf-8")
    if invalid == "duplicate":
        payload = payload.replace(
            '"gen_directory":',
            '"gen_directory":"../../../../demo.gen/duplicate",'
            '"gen_directory":',
            1,
        )
    else:
        payload = payload.replace('"design_info":{', '"design_info":{"ratio":NaN,', 1)
    bd.write_text(payload, encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "unsupported BD JSON" in row for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


def test_manifest_checks_every_nested_block_design_generation_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bd-nested-generation-root"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    document = json.loads(bd.read_text(encoding="utf-8"))
    document["design"]["nested"] = {
        "gen_directory": "$PSRCDIR/sources_1/new"
    }
    bd.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "gen_directory outside generated root" in row
        for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


def test_manifest_scans_transitive_block_design_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "nested-bd-dependency"
    root.mkdir()
    xpr = _write_project(root)
    nested = (
        root
        / "demo.srcs"
        / "sources_1"
        / "bd"
        / "system"
        / "nested"
        / "child.bd"
    )
    nested.parent.mkdir()
    nested.write_text(
        '{"design":{"design_info":{"gen_directory":'
        '"$PSRCDIR/sources_1/new"}}}\n',
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        row.startswith("demo.srcs/sources_1/bd/system/nested/child.bd:")
        and "outside generated root" in row
        for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


@pytest.mark.parametrize("field", ("artifact_uri", "source_location"))
def test_manifest_refuses_unknown_pathlike_block_design_fields(
    tmp_path: Path,
    field: str,
) -> None:
    root = tmp_path / f"bd-unknown-{field}"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    document = json.loads(bd.read_text(encoding="utf-8"))
    document["design"][field] = "../unbound.coe"
    bd.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        f"unclassified field {field}" in row
        for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


def test_manifest_refuses_unbound_block_design_path_parameter(tmp_path: Path) -> None:
    root = tmp_path / "bd-user-file"
    root.mkdir()
    xpr = _write_project(root)
    bd = root / "demo.srcs" / "sources_1" / "bd" / "system" / "system.bd"
    document = json.loads(bd.read_text(encoding="utf-8"))
    document["design"]["user_parameters"] = {
        "Coe_File": "../../../../outside.coe"
    }
    bd.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "unbound path field Coe_File" in row
        for row in manifest.refused_block_design_files
    )
    assert manifest.complete is False


def test_manifest_refuses_xci_output_escape_and_unbound_user_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "xci-path-escape"
    root.mkdir()
    xpr = _write_project(root)
    xci = root / "demo.srcs" / "sources_1" / "bd" / "system" / "ip" / "timer" / "timer.xci"
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["gen_directory"] = "$PPRDIR/../outside"
    document["ip_inst"]["parameters"]["component_parameters"]["Coe_File"] = [
        {
            "value": "../../outside.coe",
            "resolve_type": "user",
            "enabled": True,
        }
    ]
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any("gen_directory outside" in row for row in manifest.refused_ip_configuration_files)
    assert any("unbound user file" in row for row in manifest.refused_ip_configuration_files)
    assert manifest.complete is False


@pytest.mark.parametrize("invalid", ("duplicate", "nonfinite"))
def test_manifest_refuses_ambiguous_or_nonstandard_xci_json(
    tmp_path: Path,
    invalid: str,
) -> None:
    root = tmp_path / f"xci-json-{invalid}"
    root.mkdir()
    xpr = _write_project(root)
    xci = (
        root
        / "demo.srcs"
        / "sources_1"
        / "bd"
        / "system"
        / "ip"
        / "timer"
        / "timer.xci"
    )
    payload = xci.read_text(encoding="utf-8")
    if invalid == "duplicate":
        payload = payload.replace(
            '"component_reference":',
            '"component_reference":"xilinx.com:ip:other:1.0",'
            '"component_reference":',
            1,
        )
    else:
        payload = payload.replace('"ip_inst":{', '"ip_inst":{"ratio":Infinity,', 1)
    xci.write_text(payload, encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "unsupported XCI JSON" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


def test_manifest_refuses_non_vendor_xci_component_reference(tmp_path: Path) -> None:
    root = tmp_path / "xci-non-vendor-reference"
    root.mkdir()
    xpr = _write_project(root)
    xci = (
        root
        / "demo.srcs"
        / "sources_1"
        / "bd"
        / "system"
        / "ip"
        / "timer"
        / "timer.xci"
    )
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["component_reference"] = "evil.example:ip:timer:1.0"
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "non-vendor or missing component_reference" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


def test_manifest_refuses_malformed_model_path_value_and_unknown_xci_uri(
    tmp_path: Path,
) -> None:
    root = tmp_path / "xci-model-path"
    root.mkdir()
    xpr = _write_project(root)
    xci = (
        root
        / "demo.srcs"
        / "sources_1"
        / "bd"
        / "system"
        / "ip"
        / "timer"
        / "timer.xci"
    )
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["parameters"]["model_parameters"] = {
        "INIT_FILE": [{"value": 123, "enabled": True}]
    }
    document["ip_inst"]["payload_uri"] = "../unbound.mem"
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "malformed file parameter INIT_FILE value" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert any(
        "path-like unclassified field payload_uri" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


def test_manifest_refuses_xci_output_inside_source_tree(tmp_path: Path) -> None:
    root = tmp_path / "xci-source-overlap"
    root.mkdir()
    xpr = _write_project(root)
    xci = root / "demo.srcs" / "sources_1" / "bd" / "system" / "ip" / "timer" / "timer.xci"
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["parameters"]["runtime_parameters"]["OUTPUTDIR"][0][
        "value"
    ] = "$PSRCDIR/sources_1/new"
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "OUTPUTDIR outside dedicated output roots" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


def test_manifest_refuses_bd_shared_output_exception_for_direct_xci(
    tmp_path: Path,
) -> None:
    root = tmp_path / "direct-xci-shared-output"
    root.mkdir()
    xpr = _write_project(root)
    direct = root / "demo.srcs" / "sources_1" / "new" / "direct.xci"
    document = {
        "schema": "xilinx.com:schema:json_instance:1.0",
        "ip_inst": {
            "gen_directory": "../../../../demo.gen/sources_1/direct",
            "parameters": {
                "component_parameters": {},
                "runtime_parameters": {
                    "OUTPUTDIR": [
                        {"value": "../../../../demo.gen/sources_1/direct"}
                    ],
                    "SHAREDDIR": [{"value": "../../ipshared"}],
                },
            },
        },
    }
    direct.write_text(json.dumps(document), encoding="utf-8")
    payload = xpr.read_text(encoding="utf-8")
    marker = '      <Config><Option Name="TopModule" Val="top"/></Config>'
    xpr.write_text(
        payload.replace(
            marker,
            '      <File Path="$PSRCDIR/sources_1/new/direct.xci"/>\n'
            + marker,
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "SHAREDDIR outside dedicated output roots" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


def test_manifest_refuses_unsafe_xci_vendor_resource_path(tmp_path: Path) -> None:
    root = tmp_path / "xci-vendor-resource-escape"
    root.mkdir()
    xpr = _write_project(root)
    xci = root / "demo.srcs" / "sources_1" / "bd" / "system" / "ip" / "timer" / "timer.xci"
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["contents"] = {
        "implementation": {
            "bootloop_file": [{"value": "../../outside.elf"}]
        }
    }
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "unbound vendor resource field bootloop_file" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


@pytest.mark.parametrize(
    "marker",
    (
        {"resolve_type": "generated"},
        {"value_src": "ip_propagated"},
    ),
)
def test_manifest_refuses_generated_parameter_path_traversal(
    tmp_path: Path,
    marker: dict[str, str],
) -> None:
    root = tmp_path / "xci-generated-path-traversal"
    root.mkdir()
    xpr = _write_project(root)
    xci = root / "demo.srcs" / "sources_1" / "bd" / "system" / "ip" / "timer" / "timer.xci"
    document = json.loads(xci.read_text(encoding="utf-8"))
    document["ip_inst"]["parameters"]["component_parameters"]["Coe_File"] = [
        {"value": "../../outside.coe", **marker}
    ]
    xci.write_text(json.dumps(document), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any(
        "unsafe generated file parameter Coe_File" in row
        for row in manifest.refused_ip_configuration_files
    )
    assert manifest.complete is False


@pytest.mark.parametrize("token", ("`include", "$readmemh", "$readmemb"))
def test_manifest_refuses_verilog_transitive_input_directives(
    tmp_path: Path,
    token: str,
) -> None:
    root = tmp_path / token.replace("$", "read-").replace("`", "tick-")
    root.mkdir()
    xpr = _write_project(root)
    rtl = root / "demo.srcs" / "sources_1" / "new" / "top.sv"
    rtl.write_text(f"module top; // conservative {token} refusal\nendmodule\n")

    manifest = build_vivado_project_manifest(xpr)

    assert manifest.verilog_transitive_input_directive_files == (
        "demo.srcs/sources_1/new/top.sv",
    )
    assert manifest.complete is False


@pytest.mark.parametrize(
    "source",
    (
        "FILE RamFile : text is in RamFileName;",
        "file_open(status, handle, name, read_mode);",
        "readline(handle, line_buffer);",
    ),
)
def test_manifest_refuses_vhdl_transitive_input_directives(
    tmp_path: Path,
    source: str,
) -> None:
    root = tmp_path / "vhdl-transitive-input"
    root.mkdir()
    xpr = _write_project(root)
    vhdl = root / "demo.srcs" / "sources_1" / "new" / "reader.vhd"
    vhdl.write_text(source + "\n", encoding="utf-8")
    payload = xpr.read_text(encoding="utf-8")
    marker = '      <Config><Option Name="TopModule" Val="top"/></Config>'
    addition = (
        '      <File Path="$PSRCDIR/sources_1/new/reader.vhd"/>\n'
        + marker
    )
    xpr.write_text(payload.replace(marker, addition, 1), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert manifest.vhdl_transitive_input_directive_files == (
        "demo.srcs/sources_1/new/reader.vhd",
    )
    assert manifest.complete is False


@pytest.mark.parametrize(
    ("file_type", "source", "attribute_name"),
    (
        ("SystemVerilog", "module payload; initial $readmemh(\"x.mem\", m); endmodule", "verilog_transitive_input_directive_files"),
        ("VHDL 2008", "FILE DataFile : text is in DataFileName;", "vhdl_transitive_input_directive_files"),
    ),
)
def test_manifest_scans_rtl_by_file_type_even_with_nonstandard_suffix(
    tmp_path: Path,
    file_type: str,
    source: str,
    attribute_name: str,
) -> None:
    root = tmp_path / "file-type-rtl"
    root.mkdir()
    xpr = _write_project(root)
    payload_path = root / "demo.srcs" / "sources_1" / "new" / "payload.txt"
    payload_path.write_text(source + "\n", encoding="utf-8")
    payload = xpr.read_text(encoding="utf-8")
    marker = '      <Config><Option Name="TopModule" Val="top"/></Config>'
    addition = (
        '      <File Path="$PSRCDIR/sources_1/new/payload.txt">\n'
        "        <FileInfo>"
        f'<Attr Name="FileType" Val="{file_type}"/>'
        '<Attr Name="UsedIn" Val="synthesis"/>'
        "</FileInfo>\n"
        "      </File>\n"
        + marker
    )
    xpr.write_text(payload.replace(marker, addition, 1), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert getattr(manifest, attribute_name) == (
        "demo.srcs/sources_1/new/payload.txt",
    )
    assert any("FILE_TYPE" in row for row in manifest.refused_active_file_modes)
    assert manifest.complete is False


def test_manifest_refuses_path_bearing_run_more_options(tmp_path: Path) -> None:
    root = tmp_path / "run-more-options"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = '<Option Id="flatten_hierarchy" Val="rebuilt"/>'
    xpr.write_text(
        payload.replace(
            marker,
            marker
            + '<Option Id="More Options" Val="-include_dirs ../outside"/>',
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert any("More Options" in row for row in manifest.refused_run_argument_values)
    assert manifest.complete is False


@pytest.mark.parametrize("launch_options", ("-file ../outside.v", "-jobs 4"))
def test_manifest_refuses_any_nonempty_launch_options(
    tmp_path: Path,
    launch_options: str,
) -> None:
    root = tmp_path / ("launch-options-" + launch_options.split()[0].lstrip("-"))
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = '<Run Id="synth_1"'
    xpr.write_text(
        payload.replace(
            marker,
            f'<Run LaunchOptions="{launch_options}" Id="synth_1"',
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)

    assert any("LaunchOptions" in row for row in manifest.refused_run_argument_values)
    assert manifest.complete is False


@pytest.mark.parametrize(
    ("marker", "replacement", "expected"),
    (
        (
            '<Project Product="Vivado" Version="7" Minor="64"',
            '<Project Product="Vivado" Version="7" Minor="64"',
            "DefaultLaunch.Dir",
        ),
        (
            '<GeneratedRun Dir="$PRUNDIR" File="gen_run.xml"/>',
            '<GeneratedRun Dir="$PPRDIR/../outside" File="gen_run.xml"/>',
            "synth_1.GeneratedRun.Dir",
        ),
    ),
)
def test_manifest_refuses_run_state_path_escapes(
    tmp_path: Path,
    marker: str,
    replacement: str,
    expected: str,
) -> None:
    root = tmp_path / expected.replace(".", "-")
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    if expected == "DefaultLaunch.Dir":
        insertion = replacement + ' Path="portable/demo.xpr">\n  <DefaultLaunch Dir="$PPRDIR/../outside"'
        payload = payload.replace(marker + ' Path="portable/demo.xpr">', insertion + "/>\n", 1)
    else:
        payload = payload.replace(marker, replacement, 1)
    xpr.write_text(payload, encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert expected in manifest.refused_run_state_paths
    assert manifest.complete is False


def test_manifest_refuses_run_directory_inside_source_tree(tmp_path: Path) -> None:
    root = tmp_path / "run-source-overlap"
    root.mkdir()
    xpr = _write_project(root, volatile_run_root="$PSRCDIR/sources_1/new")

    manifest = build_vivado_project_manifest(xpr)

    assert "synth_1.Dir" in manifest.refused_run_state_paths
    assert "impl_1.Dir" in manifest.refused_run_state_paths
    assert manifest.complete is False


def test_manifest_refuses_generated_run_file_outside_declared_run_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated-run-file-escape"
    root.mkdir()
    xpr = _write_project(root)
    (root / "authored.sv").write_text("module authored; endmodule\n", encoding="utf-8")
    payload = xpr.read_text(encoding="utf-8")
    payload = payload.replace(
        '<GeneratedRun Dir="$PRUNDIR" File="gen_run.xml"/>',
        '<GeneratedRun Dir="$PRUNDIR" File="../authored.sv"/>',
        1,
    )
    xpr.write_text(payload, encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert "synth_1.GeneratedRun.File" in manifest.refused_run_state_paths
    assert manifest.complete is False


def test_manifest_refuses_inverse_xdc_file_type_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "inverse-xdc"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = '<Attr Name="UsedIn" Val="synthesis"/>'
    replacement = marker + '<Attr Name="FileType" Val="XDC"/>'
    xpr.write_text(payload.replace(marker, replacement, 1), encoding="utf-8")

    manifest = build_vivado_project_manifest(xpr)

    assert any("FILE_TYPE XDC" in row for row in manifest.refused_active_file_modes)
    assert manifest.complete is False


def test_source_identity_binds_unlisted_block_design_dependency_bytes(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "bd-dependency-first"
    second_root = tmp_path / "bd-dependency-second"
    first_root.mkdir()
    second_root.mkdir()
    first_xpr = _write_project(first_root)
    second_xpr = _write_project(second_root)
    relative = Path("demo.srcs/sources_1/bd/system/ip/unlisted/unlisted.xci")
    for root, value in ((first_root, "one"), (second_root, "two")):
        dependency = root / relative
        dependency.parent.mkdir(parents=True)
        dependency.write_text(f'{{"value":"{value}"}}\n', encoding="utf-8")

    first = build_vivado_project_manifest(first_xpr)
    second = build_vivado_project_manifest(second_xpr)

    dependency = next(
        row
        for row in first.file_references
        if row.path.endswith("ip/unlisted/unlisted.xci")
    )
    assert dependency.reference_type == "block_design_dependency"
    assert first.source_identity_sha256 != second.source_identity_sha256


def test_arbitrary_generated_and_checkpoint_inputs_cannot_launder_source_identity(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "derived-first"
    second_root = tmp_path / "derived-second"
    first_root.mkdir()
    second_root.mkdir()

    def configured(root: Path, *, value: str) -> Path:
        xpr = _write_project(root)
        generated = root / "demo.gen" / "sources_1" / "generated.v"
        checkpoint = root / "demo.srcs" / "utils" / "active.dcp"
        generated.parent.mkdir(parents=True)
        checkpoint.parent.mkdir(parents=True)
        generated.write_text(f"module generated; // {value}\nendmodule\n")
        checkpoint.write_bytes(value.encode("ascii"))
        payload = xpr.read_text(encoding="utf-8")
        marker = '      <Config><Option Name="TopModule" Val="top"/></Config>'
        addition = (
            '      <File Path="$PGENDIR/sources_1/generated.v"/>\n'
            '      <File Path="$PSRCDIR/utils/active.dcp"/>\n'
            + marker
        )
        xpr.write_text(payload.replace(marker, addition, 1), encoding="utf-8")
        return xpr

    first = build_vivado_project_manifest(configured(first_root, value="one"))
    second = build_vivado_project_manifest(configured(second_root, value="two"))

    origins = {row.origin for row in first.file_references}
    assert {"generated", "project"}.issubset(origins)
    assert first.source_identity_sha256 != second.source_identity_sha256
    assert first.sha256 != second.sha256
    assert not first.complete
    assert any(
        "active design checkpoint input" in row
        for row in first.refused_active_file_modes
    )


def test_manifest_exactly_inventories_derived_state_without_binding_its_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "derived-inventory"
    root.mkdir()
    xpr = _write_project(root)
    before = build_vivado_project_manifest(xpr)
    expected = {
        "generated": (root / "demo.gen" / "state" / "generated.v", b"gen\n"),
        "cache": (root / "demo.cache" / "state.bin", b"cache\x00"),
        "ip_user_files": (
            root / "demo.ip_user_files" / "scripts" / "ip.tcl",
            b"puts ip\n",
        ),
        "runs": (root / "demo.runs" / "synth_1" / "runme.log", b"run\n"),
    }
    for path, payload in expected.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    after = build_vivado_project_manifest(xpr)
    rows = {row.role: row for row in after.derived_state_roots}

    assert set(rows) == set(expected)
    for role, (path, payload) in expected.items():
        row = rows[role]
        assert row.status == "present"
        assert len(row.files) == 1
        assert row.files[0].path == path.relative_to(root).as_posix()
        assert row.files[0].byte_length == len(payload)
        assert row.files[0].sha256 == hashlib.sha256(payload).hexdigest()
        assert len(row.tree_sha256) == 64
    assert before.sha256 != after.sha256
    assert before.source_identity_sha256 == after.source_identity_sha256


def test_manifest_refuses_a_direct_xpr_symlink(tmp_path: Path) -> None:
    root = tmp_path / "linked-xpr"
    root.mkdir()
    target = _write_project(root)
    linked = root / "linked.xpr"
    try:
        linked.symlink_to(target.name)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(VivadoManifestError, match="linked component"):
        build_vivado_project_manifest(linked, project_root=root)


def test_source_identity_excludes_xci_declared_bd_shared_outputs(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "ipshared-empty"
    second_root = tmp_path / "ipshared-materialized"
    first_root.mkdir()
    second_root.mkdir()
    first = build_vivado_project_manifest(_write_project(first_root))
    second_xpr = _write_project(second_root)
    generated = (
        second_root
        / "demo.srcs"
        / "sources_1"
        / "bd"
        / "system"
        / "ipshared"
        / "generated.v"
    )
    generated.parent.mkdir()
    generated.write_text("module generated; endmodule\n", encoding="utf-8")
    second = build_vivado_project_manifest(second_xpr)

    assert "demo.srcs/sources_1/bd/system/ipshared" in (
        first.declared_generated_output_roots
    )
    assert first.source_identity_sha256 == second.source_identity_sha256
    assert first.sha256 != second.sha256


def test_import_history_does_not_shift_active_input_sequence(tmp_path: Path) -> None:
    first_root = tmp_path / "history-first"
    second_root = tmp_path / "history-second"
    first_root.mkdir()
    second_root.mkdir()
    first = build_vivado_project_manifest(_write_project(first_root))
    second_xpr = _write_project(second_root)
    payload = second_xpr.read_text(encoding="utf-8")
    payload = payload.replace(
        '          <Attr Name="ImportPath" Val="../historical/top.sv"/>\n',
        "",
        1,
    )
    second_xpr.write_text(payload, encoding="utf-8")
    second = build_vivado_project_manifest(second_xpr)

    first_active = [
        (row.path, row.sequence)
        for row in first.file_references
        if row.reference_type != "import_origin"
    ]
    second_active = [
        (row.path, row.sequence)
        for row in second.file_references
        if row.reference_type != "import_origin"
    ]
    assert first_active == second_active
    assert first.source_identity_sha256 == second.source_identity_sha256


def test_manifest_refuses_entity_bearing_xml(tmp_path: Path) -> None:
    xpr = tmp_path / "hostile.xpr"
    xpr.write_text(
        '<!DOCTYPE Project [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
        '<Project Product="Vivado">&leak;</Project>',
        encoding="utf-8",
    )
    with pytest.raises(VivadoManifestError, match="DTD/entity"):
        build_vivado_project_manifest(xpr)


def test_manifest_refuses_entity_declaration_after_long_xml_prolog(
    tmp_path: Path,
) -> None:
    xpr = tmp_path / "hostile-long-prolog.xpr"
    xpr.write_text(
        '<?xml version="1.0"?>\n'
        + (" " * 8192)
        + '<!DOCTYPE Project [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
        + '<Project Product="Vivado">&leak;</Project>',
        encoding="utf-8",
    )
    with pytest.raises(VivadoManifestError, match="DTD/entity"):
        build_vivado_project_manifest(xpr)


def test_manifest_refusal_diagnostics_exclude_import_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "diagnostic"
    root.mkdir()
    xpr = _write_project(root)
    payload = xpr.read_text(encoding="utf-8")
    marker = f'<Option Name="BoardPart" Val="{BOARD}"/>'
    xpr.write_text(
        payload.replace(
            marker,
            marker
            + '\n    <Option Name="BoardPartRepoPaths" Val="$PPRDIR/external"/>',
            1,
        ),
        encoding="utf-8",
    )

    manifest = build_vivado_project_manifest(xpr)
    reasons = chip_cli._manifest_refusal_reasons(manifest)

    assert "custom board repositories=1" in reasons
    assert not any(reason.startswith("outside references=") for reason in reasons)


def _trusted_tcl_proc_interpreter() -> tkinter.Tcl:
    interpreter = tkinter.Tcl()
    text = Path(trusted_vivado_tcl().path).read_text(encoding="utf-8")
    procedures = text.split('if {[llength $argv] != 10}', 1)[0]
    interpreter.eval(procedures)
    interpreter.eval(
        "rename daedalus_fail daedalus_process_exit_fail;"
        'proc daedalus_fail {message code} {error "$code:$message"}'
    )
    return interpreter


def _repository_guard_interpreter() -> tkinter.Tcl:
    interpreter = _trusted_tcl_proc_interpreter()
    interpreter.eval(
        """
        array set properties {
            project {IP_REPO_PATHS INCLUDE_DIRS BOARD_PART_REPO_PATHS BOARD_REPO_PATHS}
            sources_1 {IP_REPO_PATHS INCLUDE_DIRS BOARD_PART_REPO_PATHS BOARD_REPO_PATHS}
        }
        array set values {
            project,IP_REPO_PATHS {}
            project,INCLUDE_DIRS {}
            project,BOARD_PART_REPO_PATHS {}
            project,BOARD_REPO_PATHS {}
            sources_1,IP_REPO_PATHS {}
            sources_1,INCLUDE_DIRS {}
            sources_1,BOARD_PART_REPO_PATHS {}
            sources_1,BOARD_REPO_PATHS {}
            ip0,IPDEF {xilinx.com:ip:counter:1.0}
        }
        set ambient_board_paths {}
        set read_error {}
        proc current_project {} {return project}
        proc get_filesets {args} {return {sources_1}}
        proc get_ips {args} {return {ip0}}
        proc list_property {object} {return $::properties($object)}
        proc get_property {name object} {
            if {$::read_error eq "$object,$name"} {error {injected read fault}}
            return $::values($object,$name)
        }
        proc get_param {name} {return $::ambient_board_paths}
        """
    )
    return interpreter


def test_tcl_repository_and_vendor_guards_accept_only_empty_vendor_state() -> None:
    interpreter = _repository_guard_interpreter()

    interpreter.call("daedalus_refuse_custom_ip_repositories", "sources_1")
    interpreter.call("daedalus_refuse_include_directories", "sources_1")
    interpreter.call("daedalus_refuse_custom_board_repositories")
    interpreter.call("daedalus_require_vendor_ip_definitions")


@pytest.mark.parametrize(
    ("guard", "variable", "value", "message"),
    (
        (
            "daedalus_refuse_custom_ip_repositories",
            "values(sources_1,IP_REPO_PATHS)",
            "C:/custom-ip",
            "custom IP_REPO_PATHS",
        ),
        (
            "daedalus_refuse_include_directories",
            "values(sources_1,INCLUDE_DIRS)",
            "C:/include",
            "transitive INCLUDE_DIRS",
        ),
        (
            "daedalus_refuse_custom_board_repositories",
            "values(project,BOARD_PART_REPO_PATHS)",
            "C:/boards",
            "custom board repository",
        ),
        (
            "daedalus_refuse_custom_board_repositories",
            "ambient_board_paths",
            "C:/ambient-boards",
            "ambient board.repoPaths",
        ),
        (
            "daedalus_require_vendor_ip_definitions",
            "values(ip0,IPDEF)",
            "example.org:user:counter:1.0",
            "non-vendor IP definition",
        ),
    ),
)
def test_tcl_repository_and_vendor_guards_fail_closed(
    guard: str,
    variable: str,
    value: str,
    message: str,
) -> None:
    interpreter = _repository_guard_interpreter()
    interpreter.call("set", variable, value)
    arguments = (
        ("sources_1",)
        if guard
        in {
            "daedalus_refuse_custom_ip_repositories",
            "daedalus_refuse_include_directories",
        }
        else ()
    )

    with pytest.raises(tkinter.TclError, match=message):
        interpreter.call(guard, *arguments)


def test_tcl_repository_guard_refuses_unreadable_property() -> None:
    interpreter = _repository_guard_interpreter()
    interpreter.call("set", "read_error", "sources_1,IP_REPO_PATHS")

    with pytest.raises(tkinter.TclError, match="cannot read IP_REPO_PATHS"):
        interpreter.call("daedalus_refuse_custom_ip_repositories", "sources_1")


@pytest.mark.parametrize(
    ("filename", "file_type", "message"),
    (
        ("payload.txt", "VHDL", "VHDL FILE_TYPE requires"),
        ("payload.txt", "SystemVerilog", "Verilog FILE_TYPE requires"),
        ("opaque.xcix", "IP", "opaque IP/core-container"),
        ("opaque.xco", "IP", "opaque IP/core-container"),
    ),
)
def test_tcl_active_file_guard_behavior(
    tmp_path: Path,
    filename: str,
    file_type: str,
    message: str,
) -> None:
    source = tmp_path / filename
    source.write_bytes(b"input")
    interpreter = _trusted_tcl_proc_interpreter()
    interpreter.call("set", "source_path", str(source))
    interpreter.call("set", "source_type", file_type)
    interpreter.eval(
        """
        proc get_files {args} {return {source0}}
        proc get_property {name object} {
            if {$name eq "NAME"} {return $::source_path}
            if {$name eq "FILE_TYPE"} {return $::source_type}
            error {unexpected property}
        }
        """
    )

    with pytest.raises(tkinter.TclError, match=message):
        interpreter.call("daedalus_check_active_files", str(tmp_path))


def test_tcl_run_argument_guard_behavior() -> None:
    interpreter = _trusted_tcl_proc_interpreter()
    interpreter.eval(
        """
        set more_options {}
        proc get_runs {args} {return {synth_1}}
        proc list_property {object} {
            return [list {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS}]
        }
        proc get_property {name object} {return $::more_options}
        """
    )
    interpreter.call("daedalus_refuse_run_input_overrides")
    interpreter.call("set", "more_options", "-file ../outside.v")

    with pytest.raises(tkinter.TclError, match="run input override is refused"):
        interpreter.call("daedalus_refuse_run_input_overrides")


def test_tcl_disables_and_revalidates_selected_implementation_incremental_reuse() -> None:
    interpreter = _trusted_tcl_proc_interpreter()
    interpreter.eval(
        """
        array set properties {
            synth_1 {AUTO_INCREMENTAL_CHECKPOINT INCREMENTAL_CHECKPOINT WRITE_INCREMENTAL_SYNTH_CHECKPOINT WRITE_INCREMENTAL_SYNTH_DCP}
            impl_1 {AUTO_INCREMENTAL_CHECKPOINT INCREMENTAL_CHECKPOINT}
        }
        array set values {
            synth_1,IS_SYNTHESIS 1
            synth_1,AUTO_INCREMENTAL_CHECKPOINT 1
            synth_1,INCREMENTAL_CHECKPOINT old-synth.dcp
            synth_1,WRITE_INCREMENTAL_SYNTH_CHECKPOINT 1
            synth_1,WRITE_INCREMENTAL_SYNTH_DCP 1
            impl_1,IS_SYNTHESIS 0
            impl_1,AUTO_INCREMENTAL_CHECKPOINT 1
            impl_1,INCREMENTAL_CHECKPOINT old-impl.dcp
        }
        proc get_runs {args} {return {synth_1 impl_1}}
        proc list_property {object} {return $::properties($object)}
        proc get_property {name object} {return $::values($object,$name)}
        proc set_property {name value object} {set ::values($object,$name) $value}
        """
    )

    interpreter.call("daedalus_disable_incremental_reuse", "synth_1", "impl_1")

    assert interpreter.getvar("values(impl_1,AUTO_INCREMENTAL_CHECKPOINT)") == "0"
    assert interpreter.getvar("values(impl_1,INCREMENTAL_CHECKPOINT)") == ""
    assert interpreter.getvar("values(synth_1,INCREMENTAL_CHECKPOINT)") == ""


@pytest.mark.parametrize(
    ("object_name", "property_name", "poison_relative"),
    (
        ("project", "DEFAULT_LAUNCH_DIR", "demo.srcs/launch"),
        ("project", "IP_OUTPUT_REPO", "demo.srcs/cache"),
        ("project", "IP.USER_FILES_DIR", "demo.srcs/ip-user"),
        ("project", "IP_DEFAULT_OUTPUT_PATH", "demo.srcs/generated"),
        ("project", "IP_STATIC_SOURCE_DIR", "demo.srcs/static"),
        ("project", "SIM.IPSTATIC_SOURCE_DIR", "demo.srcs/sim-static"),
        ("synth_1", "DIRECTORY", "demo.srcs/synth_1"),
        ("impl_1", "DIRECTORY", "demo.srcs/impl_1"),
    ),
)
def test_tcl_write_root_guard_refuses_cross_domain_paths(
    tmp_path: Path,
    object_name: str,
    property_name: str,
    poison_relative: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    generated = root / "demo.gen"
    cache = root / "demo.cache"
    ip_user = root / "demo.ip_user_files"
    runs = root / "demo.runs"
    interpreter = _trusted_tcl_proc_interpreter()
    interpreter.call("set", "project_root", str(root))
    interpreter.call("set", "generated_root", str(generated))
    interpreter.call("set", "cache_root", str(cache))
    interpreter.call("set", "ip_user_root", str(ip_user))
    interpreter.call("set", "run_root", str(runs))
    interpreter.eval(
        """
        array set properties {
            project {DIRECTORY DEFAULT_LAUNCH_DIR IP_OUTPUT_REPO IP.USER_FILES_DIR IP_USER_FILES_DIR IP_DEFAULT_OUTPUT_PATH IP_STATIC_SOURCE_DIR SIM.IPSTATIC_SOURCE_DIR}
            synth_1 {DIRECTORY}
            impl_1 {DIRECTORY}
        }
        array set values {}
        set values(project,DIRECTORY) $project_root
        set values(project,DEFAULT_LAUNCH_DIR) [file join $run_root launch]
        set values(project,IP_OUTPUT_REPO) $cache_root
        set values(project,IP.USER_FILES_DIR) $ip_user_root
        set values(project,IP_USER_FILES_DIR) $ip_user_root
        set values(project,IP_DEFAULT_OUTPUT_PATH) $generated_root
        set values(project,IP_STATIC_SOURCE_DIR) $ip_user_root
        set values(project,SIM.IPSTATIC_SOURCE_DIR) $ip_user_root
        set values(synth_1,IS_SYNTHESIS) 1
        set values(synth_1,DIRECTORY) [file join $run_root synth_1]
        set values(impl_1,IS_SYNTHESIS) 0
        set values(impl_1,DIRECTORY) [file join $run_root impl_1]
        proc current_project {} {return project}
        proc get_runs {args} {return {synth_1 impl_1}}
        proc list_property {object} {return $::properties($object)}
        proc get_property {name object} {return $::values($object,$name)}
        """
    )
    interpreter.call(
        "daedalus_check_write_roots",
        str(root),
        str(generated),
        str(cache),
        str(ip_user),
        str(runs),
    )
    interpreter.call(
        "set",
        f"values({object_name},{property_name})",
        str(root / poison_relative),
    )

    with pytest.raises(tkinter.TclError, match="declared root"):
        interpreter.call(
            "daedalus_check_write_roots",
            str(root),
            str(generated),
            str(cache),
            str(ip_user),
            str(runs),
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 identity contract")
def test_windows_long_and_short_path_spellings_have_one_identity(tmp_path: Path) -> None:
    root = tmp_path / "Vivado Long Project Name"
    root.mkdir()
    xpr = _write_project(root)
    buffer = ctypes.create_unicode_buffer(32768)
    written = ctypes.windll.kernel32.GetShortPathNameW(str(root), buffer, len(buffer))
    if not written or written >= len(buffer) or buffer.value == str(root):
        pytest.skip("8.3 aliases are disabled for the temporary volume")
    short_root = Path(buffer.value)

    assert canonical_path_identity(short_root) == canonical_path_identity(root)
    long_manifest = build_vivado_project_manifest(xpr, project_root=root)
    short_manifest = build_vivado_project_manifest(
        short_root / xpr.name, project_root=short_root
    )
    assert long_manifest.to_dict() == short_manifest.to_dict()
    assert long_manifest.sha256 == short_manifest.sha256


def test_trusted_tcl_is_static_hashed_and_argv_values_stay_discrete(tmp_path: Path) -> None:
    root = tmp_path / "project $[not Tcl]"
    root.mkdir()
    xpr = _write_project(root)
    output = root / ".daedalus-chip" / "evidence $[phase]"
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

    trusted = trusted_vivado_tcl()
    argv = build_vivado_flow_argv(
        "impl",
        xpr,
        project_root=root,
        output_dir=output,
        expected_part=PART,
        expected_top="top",
        jobs=3,
    )
    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    payload = Path(trusted.path).read_bytes()
    tclargs = argv.index("-tclargs")

    assert before == after
    assert not output.exists()
    assert trusted.sha256 == hashlib.sha256(payload).hexdigest()
    assert trusted.byte_length == len(payload)
    assert argv[:tclargs] == [
        "vivado",
        "-mode",
        "batch",
        "-nojournal",
        "-nolog",
        "-notrace",
        "-source",
        trusted.path,
    ]
    assert argv[tclargs + 1 :] == [
        "impl",
        str(root.resolve()),
        str(xpr.resolve()),
            str(output.resolve()),
            PART,
            "",
            "top",
        "synth_1",
        "impl_1",
        "3",
    ]
    text = payload.decode("utf-8")
    assert str(root) not in text
    assert not any(line.strip().startswith("source ") for line in text.splitlines())
    assert "daedalus_clear_run_hooks" in text
    extension_line = next(
        line for line in text.splitlines() if "refused_automation_extensions" in line
    )
    assert set(extension_line.split("{", 1)[1].split("}", 1)[0].split()) == {
        ".tcl",
        ".bat",
        ".cmd",
        ".exe",
        ".ps1",
    }
    assert ".xdc" not in extension_line
    assert 'if {$source_extension eq ".xdc"}' in text
    assert "Suffix alone is therefore not an admission decision" in text
    assert "get_property FILE_TYPE" in text
    assert 'string equal -nocase $file_type "Tcl"' in text
    assert text.index("get_property FILE_TYPE") < text.index(
        'if {$source_extension eq ".xdc"}'
    )
    assert 'string equal -nocase $file_type "XDC"' in text
    assert "active project automation is refused" in text
    assert "proc daedalus_check_write_roots" in text
    for property_name in (
        "DIRECTORY",
        "IP_OUTPUT_REPO",
        "IP.USER_FILES_DIR",
        "IP_USER_FILES_DIR",
        "IP_DEFAULT_OUTPUT_PATH",
        "IP_STATIC_SOURCE_DIR",
        "SIM.IPSTATIC_SOURCE_DIR",
    ):
        assert property_name in text
    assert "daedalus_refuse_custom_ip_repositories" in text
    assert "IP_REPO_PATHS" in text
    assert "daedalus_refuse_custom_board_repositories" in text
    assert "board.repoPaths" in text
    assert "daedalus_refuse_include_directories" in text
    assert "INCLUDE_DIRS" in text
    assert "daedalus_require_vendor_ip_definitions" in text
    assert "get_property IPDEF" in text
    assert 'string match "xilinx.com:*"' in text
    assert "daedalus_assert_no_run_hooks" in text
    assert "daedalus_refuse_run_input_overrides" in text
    assert "proc daedalus_disable_incremental_reuse" in text
    assert "selected_implementation" in text
    assert "required incremental property" in text
    assert "AUTO_INCREMENTAL_CHECKPOINT 0" in text
    assert "INCREMENTAL_CHECKPOINT {}" in text
    assert "proc daedalus_validate_expanded_graph" in text
    assert 'source_extension in {.xcix .xco}' in text
    assert 'file_type "XDC"' in text
    assert "$run DIRECTORY $run_root" in text
    assert (
        "daedalus_check_write_roots $project_root $generated_root "
        "$cache_root $ip_user_files_root $run_root"
    ) in text
    assert "proc daedalus_prepare_ip_sources" in text
    assert "config_ip_cache -disable_cache" in text
    assert "get_property IP_CACHE_PERMISSIONS" in text
    assert "reset_target all $targets" in text
    assert "generate_target -force all $targets" in text
    assert 'puts $summary_file "ip_cache=disabled"' in text
    post_generation_start = text.index(
        "set regenerated_ip_source_count [daedalus_prepare_ip_sources $project_root]"
    )
    first_synthesis_launch = text.index(
        "launch_runs $synth_run",
        post_generation_start,
    )
    validator_call = (
        "daedalus_validate_expanded_graph $project_root $generated_root "
            "$cache_root $ip_user_files_root $run_root $primary_source_set_name "
            "$expected_part $expected_board_part $expected_top"
        )
    main_start = text.index("if {[catch {open_project $project_file}")
    ambient_board_guard = text.rindex(
        "daedalus_refuse_ambient_board_repositories",
        0,
        main_start,
    )
    assert ambient_board_guard < main_start
    initial_update = text.index(
        "update_compile_order -fileset $primary_source_set",
        main_start,
    )
    pre_generation_validation = text.index(validator_call, initial_update)
    assert initial_update < pre_generation_validation < post_generation_start
    first_post_generation_validation = text.index(
        validator_call,
        post_generation_start,
    )
    second_update = text.index(
        "update_compile_order -fileset $primary_source_set",
        first_post_generation_validation,
    )
    second_post_generation_validation = text.index(
        validator_call,
        second_update,
    )
    assert (
        post_generation_start
        < first_post_generation_validation
        < second_update
        < second_post_generation_validation
        < first_synthesis_launch
    )
    implementation_launch = text.index(
        "launch_runs $impl_run -to_step write_bitstream"
    )
    final_incremental_guard = text.rindex(
        "daedalus_disable_incremental_reuse $synth_run $impl_run",
        0,
        implementation_launch,
    )
    assert final_incremental_guard < implementation_launch
    validator_definition = text[
        text.index("proc daedalus_validate_expanded_graph") : main_start
    ]
    for required_call in (
        "get_property PART [current_project]",
        "get_property TOP $primary_source_set",
        "daedalus_refuse_custom_ip_repositories $primary_source_set",
        "daedalus_refuse_include_directories $primary_source_set",
        "daedalus_refuse_custom_board_repositories",
        "daedalus_require_vendor_ip_definitions",
        (
            "daedalus_check_write_roots $project_root $generated_root "
            "$cache_root $ip_user_files_root $run_root"
        ),
        "daedalus_check_active_files $project_root",
        "daedalus_refuse_run_input_overrides",
        "daedalus_clear_run_hooks",
        "daedalus_assert_no_run_hooks",
    ):
        assert required_call in validator_definition
    assert "-report_unconstrained -check_timing_verbose" in text
    assert "write_bitstream -force" in text

    with pytest.raises(VivadoTclContractError, match="proper descendant"):
        build_vivado_flow_argv(
            "impl",
            xpr,
            project_root=root,
            output_dir=root.parent / "escaped-evidence",
            expected_part=PART,
            expected_top="top",
        )
    with pytest.raises(VivadoTclContractError, match="AMD Vivado launcher"):
        build_vivado_flow_argv(
            "impl",
            xpr,
            project_root=root,
            output_dir=output,
            expected_part=PART,
            expected_top="top",
            command="cmd.exe",
        )


def test_native_report_parsers_preserve_zero_missing_and_unparseable_states(
    tmp_path: Path,
) -> None:
    timing = parse_vivado_timing_summary(_write(tmp_path / "timing.rpt", TIMING_REPORT))
    utilization = parse_vivado_utilization(
        _write(tmp_path / "utilization.rpt", UTILIZATION_REPORT)
    )
    drc = parse_vivado_drc(_write(tmp_path / "drc.rpt", DRC_REPORT))
    methodology = parse_vivado_methodology(
        _write(tmp_path / "methodology.rpt", "Report Methodology\nChecks found: 0")
    )
    route = parse_vivado_route_status(_write(tmp_path / "route.rpt", ROUTE_REPORT))
    messages = parse_vivado_message_counts(
        _write(
            tmp_path / "runme.log",
            "1 Info, 2 Warnings, 3 Critical Warnings and 4 Errors encountered.\n"
            "194 Infos, 102 Warnings, 0 Critical Warnings and 0 Errors encountered.",
        )
    )

    assert timing.status == "parsed"
    assert timing.metrics["wns_ns"] == pytest.approx(0.162)
    assert timing.metrics["constraints_met"] is True
    assert timing.metrics["check_timing"]["no_output_delay"] == 13
    assert utilization.metrics["resources"]["bram_tile"]["util_percent"] == 90.0
    assert drc.metrics["checks_found"] == 7
    assert drc.metrics["severity_counts"] == {"warning": 7}
    assert vivado_rule_report_passed(drc) is False
    assert methodology.metrics["checks_found"] == 0
    assert methodology.metrics["rules"] == ()
    assert vivado_rule_report_passed(methodology) is True
    assert route.metrics["complete"] is True
    assert messages.metrics["errors"] == 0
    assert messages.metrics["summary_count"] == 2
    assert vivado_message_report_passed(messages) is True
    retained_payload = (
        b"194 Infos, 102 Warnings, 6 Critical Warnings and 0 Errors encountered."
    )
    retained_messages = parse_vivado_message_counts_bytes(
        retained_payload, display_path="cas:stdout"
    )
    assert retained_messages.status == "parsed"
    assert retained_messages.sha256 == hashlib.sha256(retained_payload).hexdigest()
    assert retained_messages.metrics["critical_warnings"] == 6
    assert vivado_message_report_passed(retained_messages) is False

    missing = parse_vivado_timing_summary(tmp_path / "absent.rpt")
    malformed_path = _write(tmp_path / "malformed.rpt", "Timing Summary Report")
    malformed = parse_vivado_timing_summary(malformed_path)
    assert (missing.status, missing.sha256, missing.byte_length) == (
        "missing",
        None,
        None,
    )
    assert malformed.status == "unparseable"
    assert malformed.sha256 == hashlib.sha256(malformed_path.read_bytes()).hexdigest()
    assert malformed.metrics == {}
    with pytest.raises(ValueError, match="unknown Vivado report kind"):
        parse_vivado_report("not-a-report", tmp_path / "ignored")


@pytest.mark.parametrize(
    ("kind", "report_text", "metric_path", "expected"),
    (
        ("timing", TIMING_REPORT, ("wns_ns",), pytest.approx(0.162)),
        (
            "utilization",
            UTILIZATION_REPORT,
            ("resources", "bram_tile", "used"),
            45,
        ),
        ("drc", DRC_REPORT, ("checks_found",), 7),
        (
            "methodology",
            "Report Methodology\nChecks found: 0",
            ("checks_found",),
            0,
        ),
        ("route_status", ROUTE_REPORT, ("complete",), True),
    ),
)
def test_retained_report_bytes_are_authoritative_for_each_native_report_kind(
    tmp_path: Path,
    kind: str,
    report_text: str,
    metric_path: tuple[str, ...],
    expected: object,
) -> None:
    payload = (report_text.strip() + "\n").encode("utf-8")
    display_path = tmp_path / f"retained-{kind}.rpt"
    display_path.write_bytes(b"this live file must not be parsed\n")

    result = parse_vivado_report_bytes(
        kind,
        payload,
        display_path=str(display_path),
    )

    metric: object = result.metrics
    for key in metric_path:
        assert isinstance(metric, Mapping)
        metric = metric[key]
    assert result.status == "parsed"
    assert result.kind == kind
    assert result.path == str(display_path)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.byte_length == len(payload)
    assert result.sha256 != hashlib.sha256(display_path.read_bytes()).hexdigest()
    assert metric == expected


def test_retained_report_bytes_preserve_invalid_identity_and_refuse_unknown_input() -> None:
    invalid_payload = b"\xffnot-utf8"

    invalid = parse_vivado_report_bytes(
        "timing",
        invalid_payload,
        display_path="cas:invalid-timing",
    )

    assert invalid.status == "unparseable"
    assert invalid.path == "cas:invalid-timing"
    assert invalid.sha256 == hashlib.sha256(invalid_payload).hexdigest()
    assert invalid.byte_length == len(invalid_payload)
    assert invalid.metrics == {}
    assert "not UTF-8" in invalid.error
    with pytest.raises(ValueError, match="unknown Vivado report kind"):
        parse_vivado_report_bytes("not-a-report", b"ignored")
    with pytest.raises(TypeError, match="payload must be bytes"):
        parse_vivado_report_bytes("timing", bytearray(b"ignored"))  # type: ignore[arg-type]


def test_timing_parser_refuses_prose_numeric_contradictions(tmp_path: Path) -> None:
    numeric_failure = TIMING_REPORT.replace(
        "      0.162   0.000 0 25854",
        "     -0.162  -1.000 2 25854",
        1,
    )
    assert numeric_failure != TIMING_REPORT
    false_pass = parse_vivado_timing_summary(
        _write(tmp_path / "false-pass.rpt", numeric_failure)
    )
    assert false_pass.status == "unparseable"
    assert "contradicts" in false_pass.error

    false_failure = TIMING_REPORT.replace(
        "All user specified timing constraints are met.",
        "Timing constraints are not met.",
        1,
    )
    false_fail = parse_vivado_timing_summary(
        _write(tmp_path / "false-failure.rpt", false_failure)
    )
    assert false_fail.status == "unparseable"
    assert "contradicts" in false_fail.error


def test_binary_artifact_identity_never_requires_utf8(tmp_path: Path) -> None:
    artifact = tmp_path / "design.bit"
    payload = bytes(range(256)) + b"\xff\xfe\x00\x80"
    artifact.write_bytes(payload)

    identity = vivado_artifact_identity(artifact, kind="bitstream")

    assert identity.status == "parsed"
    assert identity.byte_length == len(payload)
    assert identity.sha256 == hashlib.sha256(payload).hexdigest()
    assert identity.metrics == {}


REAL_PROJECT_ROOT = Path(r"C:\daedalus_eda\tdc_20260830\tdc_light_version")


@pytest.mark.skipif(
    not (REAL_PROJECT_ROOT / "tdc_light_version.xpr").is_file(),
    reason="supplied Vivado evidence is not installed on this machine",
)
def test_supplied_project_and_native_evidence_match_the_frozen_contract() -> None:
    evidence = REAL_PROJECT_ROOT / "daedalus_evidence"
    manifest = build_vivado_project_manifest(
        REAL_PROJECT_ROOT / "tdc_light_version.xpr", project_root=REAL_PROJECT_ROOT
    )
    timing = parse_vivado_timing_summary(evidence / "fresh_impl_timing_summary.rpt")
    utilization = parse_vivado_utilization(evidence / "fresh_impl_utilization.rpt")
    drc = parse_vivado_drc(evidence / "fresh_impl_drc.rpt")
    methodology = parse_vivado_methodology(evidence / "fresh_impl_methodology.rpt")
    route = parse_vivado_route_status(evidence / "fresh_impl_route_status.rpt")
    messages = parse_vivado_message_counts(evidence / "fresh_impl_runme.log")
    bitstream = vivado_artifact_identity(
        evidence / "fresh_impl_system_wrapper.bit", kind="bitstream"
    )

    assert (manifest.part, manifest.board_part, manifest.top) == (
        PART,
        BOARD,
        "system_wrapper",
    )
    assert manifest.complete is False
    assert len(manifest.custom_board_repository_paths) == 1
    assert "xilinx_board_store" in manifest.custom_board_repository_paths[0]
    assert any(ref.kind == "vivado_block_design" for ref in manifest.file_references)
    assert any(ref.kind == "vivado_ip_configuration" for ref in manifest.file_references)
    assert sum(
        ref.reference_type == "block_design_dependency"
        for ref in manifest.file_references
    ) == 6
    assert timing.status == "parsed"
    assert timing.metrics["wns_ns"] == pytest.approx(0.162)
    assert timing.metrics["whs_ns"] == pytest.approx(0.021)
    assert timing.metrics["constraints_met"] is True
    assert utilization.metrics["resources"]["lut"]["used"] == 7368
    assert utilization.metrics["resources"]["bram_tile"]["used"] == 45
    assert drc.metrics["checks_found"] == 7
    assert methodology.metrics["checks_found"] == 62
    assert route.metrics["routable_nets"] == 12337
    assert route.metrics["fully_routed_nets"] == 12337
    assert route.metrics["routing_errors"] == 0
    assert messages.metrics["errors"] == 0
    assert bitstream.status == "parsed"
    assert bitstream.byte_length == 2_192_141
