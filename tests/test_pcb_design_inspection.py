"""Board and schematic inspection against a deterministic KiCad 8 fixture.

The fixture is hand-counted, so the assertions below are independent of the
implementation: two footprints, three named nets plus KiCad's net 0, a closed
four-segment Edge.Cuts rectangle 40 x 30 mm, two tracks and one via.

The pinned ``report_sha256`` values are the byte-determinism claim. They come
from the fixture generator, which writes LF bytes explicitly, so they hold on
Windows and Linux from the same commit.
"""
from __future__ import annotations

import hashlib

import pytest

from fixtures.pcb_design import BOARD_TEXT, SCHEMATIC_TEXT, write_fixture

from daedalus.pcb_design import (
    BOARD_VERSIONS,
    SCHEMATIC_VERSIONS,
    PcbRefusal,
    build_board_report,
    build_schematic_report,
    canonical_json,
    inspect_artifact,
    payload_digest,
)

# Pinned 2026-09-05 on Windows 11 / CPython 3.13.14. A change to either value
# is a change to the inspector's output contract and must be deliberate.
BOARD_REPORT_SHA256 = "149fd4f36e65a0aae17d9706e7b9ae86ecf9b34767ae01c6465946d3fb30fcd8"
SCHEMATIC_REPORT_SHA256 = "d5cbea196ac860b63d6dcba51ea08a16628a785560940af69cba8793350ae18d"
BOARD_BYTES_SHA256 = "12f7b274b876d8394e7a606d2fe00af4712c3da0065b27e723c555e3a33ec44e"
SCHEMATIC_BYTES_SHA256 = "f4e9affd6f9a829895612228d59a6100d100408f4e952337f3caf345bba19b4d"


@pytest.fixture
def project(tmp_path):
    return write_fixture(tmp_path / "lane6")


@pytest.fixture
def board(project):
    return build_board_report(project["board"])


@pytest.fixture
def schematic(project):
    return build_schematic_report(project["schematic"])


# ---------------------------------------------------------------------------
# Identity and determinism
# ---------------------------------------------------------------------------


def test_the_artifact_identity_is_the_bytes_on_disk(project, board):
    payload = project["board"].read_bytes()
    assert board["artifact"] == {
        "name": "lane6_fixture.kicad_pcb",
        "kind": "kicad_pcb",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert board["artifact"]["sha256"] == BOARD_BYTES_SHA256


def test_the_schematic_identity_is_the_bytes_on_disk(project, schematic):
    payload = project["schematic"].read_bytes()
    assert schematic["artifact"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert schematic["artifact"]["sha256"] == SCHEMATIC_BYTES_SHA256


def test_the_board_report_digest_is_pinned(board):
    assert board["report_sha256"] == BOARD_REPORT_SHA256


def test_the_schematic_report_digest_is_pinned(schematic):
    assert schematic["report_sha256"] == SCHEMATIC_REPORT_SHA256


def test_the_digest_covers_the_report_minus_the_digest_field(board):
    body = {key: value for key, value in board.items() if key != "report_sha256"}
    assert payload_digest(body) == board["report_sha256"]


def test_inspection_is_repeatable_and_relocation_stable(tmp_path, board):
    elsewhere = write_fixture(tmp_path / "a" / "deeper" / "place")
    again = build_board_report(elsewhere["board"])
    assert again == board, "the report must not depend on the directory it was read from"


def test_canonical_json_round_trips_and_sorts(board):
    import json

    text = canonical_json(board)
    assert "\n" not in text
    assert json.loads(text) == board
    keys = list(json.loads(text).keys())
    assert keys == sorted(keys)


def test_tab_indentation_is_semantically_identical(tmp_path, board):
    """KiCad indents with tabs; the fixture uses spaces. Prove it cannot matter."""

    tabbed = "\n".join(
        "\t" * ((len(line) - len(line.lstrip(" "))) // 2) + line.lstrip(" ")
        for line in BOARD_TEXT.split("\n")
    )
    assert "\t" in tabbed and tabbed != BOARD_TEXT
    target = tmp_path / "tabbed.kicad_pcb"
    target.write_bytes(tabbed.encode("utf-8"))
    other = build_board_report(target)

    ignored = {"artifact", "report_sha256"}
    assert {k: v for k, v in other.items() if k not in ignored} == {
        k: v for k, v in board.items() if k not in ignored
    }
    assert other["artifact"]["sha256"] != board["artifact"]["sha256"]


# ---------------------------------------------------------------------------
# Board content, hand-counted from the fixture
# ---------------------------------------------------------------------------


def test_board_format_is_gated_not_guessed(board):
    assert board["format"]["version"] == 20240108
    assert board["format"]["version_supported"] is True
    assert board["format"]["kicad_series"] == "8.0"
    assert board["format"]["generator"] == "pcbnew"
    assert board["format"]["generator_version"] == "8.0"
    assert board["format"]["supported_versions"] == sorted(BOARD_VERSIONS)
    assert board["complete"] is True


def test_board_metadata_and_layer_stack(board):
    assert board["board"]["thickness_mm"] == 1.6
    assert board["board"]["paper"] == "A4"
    assert board["board"]["layer_count"] == 20
    assert board["board"]["copper_layer_count"] == 2
    assert board["board"]["layers"][0] == {
        "ordinal": 0,
        "canonical_name": "F.Cu",
        "type": "signal",
        "user_name": "",
    }
    assert {
        "ordinal": 36,
        "canonical_name": "B.SilkS",
        "type": "user",
        "user_name": "B.Silkscreen",
    } in board["board"]["layers"]


def test_board_outline_extents_are_the_edge_cuts_rectangle(board):
    outline = board["board"]["outline"]
    assert outline["present"] is True
    assert outline["element_counts"] == {"gr_line": 4}
    assert (outline["min_x_mm"], outline["min_y_mm"]) == (90, 50)
    assert (outline["max_x_mm"], outline["max_y_mm"]) == (130, 80)
    assert (outline["width_mm"], outline["height_mm"]) == (40, 30)
    assert outline["closed_polyline"] is True
    assert outline["extents_are_lower_bound"] is False
    assert outline["footprint_edge_elements"] == 0


def test_a_board_without_edge_cuts_says_so_instead_of_inventing_a_box(tmp_path):
    # Move every graphic off Edge.Cuts without touching the layer table, which
    # still declares the layer. An outline is graphics, not a declaration.
    stripped = BOARD_TEXT.replace('(layer "Edge.Cuts")', '(layer "Cmts.User")')
    assert '(44 "Edge.Cuts" user)' in stripped
    target = tmp_path / "no_edges.kicad_pcb"
    target.write_bytes(stripped.encode("utf-8"))
    outline = build_board_report(target)["board"]["outline"]
    assert outline["present"] is False
    assert outline["min_x_mm"] is None and outline["width_mm"] is None
    assert outline["closed_polyline"] is None
    assert outline["extents_method"] == "none"


def test_an_open_outline_is_reported_as_open(tmp_path):
    opened = BOARD_TEXT.replace("(start 90 80) (end 90 50)", "(start 90 80) (end 90 55)")
    target = tmp_path / "open.kicad_pcb"
    target.write_bytes(opened.encode("utf-8"))
    outline = build_board_report(target)["board"]["outline"]
    assert outline["closed_polyline"] is False


def test_an_arc_outline_is_declared_a_lower_bound(tmp_path):
    with_arc = BOARD_TEXT.replace(
        '  (gr_text "LANE6 FIXTURE"',
        '  (gr_arc (start 90 50) (mid 85 65) (end 90 80)\n'
        '    (stroke (width 0.05) (type default)) (layer "Edge.Cuts")\n'
        '    (uuid "33333333-3333-4333-8333-33333333333a")\n'
        "  )\n"
        '  (gr_text "LANE6 FIXTURE"',
    )
    target = tmp_path / "arc.kicad_pcb"
    target.write_bytes(with_arc.encode("utf-8"))
    report = build_board_report(target)
    outline = report["board"]["outline"]
    assert outline["extents_are_lower_bound"] is True
    assert outline["closed_polyline"] is None, "closure is not claimed for curved outlines"
    assert any("lower bound" in item for item in report["limitations"])


def test_board_nets_come_from_the_files_own_table(board):
    assert board["nets"] == [
        {"ordinal": 0, "name": ""},
        {"ordinal": 1, "name": "GND"},
        {"ordinal": 2, "name": "VCC"},
        {"ordinal": 3, "name": "/SIG"},
    ]
    assert board["net_count"] == 4
    assert board["named_net_count"] == 3


def test_board_footprints_are_reported_in_reference_order(board):
    assert board["footprint_count"] == 2
    assert [row["reference"] for row in board["footprints"]] == ["C1", "R1"]
    resistor = board["footprints"][1]
    assert resistor == {
        "library_link": "Resistor_SMD:R_0805_2012Metric",
        "reference": "R1",
        "value": "10k",
        "footprint_field": "Resistor_SMD:R_0805_2012Metric",
        "layer": "F.Cu",
        "at_x_mm": 100,
        "at_y_mm": 60,
        "rotation_deg": 0,
        "pad_count": 2,
        "attributes": ["smd"],
        "nets": ["/SIG", "VCC"],
    }
    assert board["footprints"][0]["rotation_deg"] == 90


def test_board_tracks_and_zones_are_counted(board):
    assert board["tracks"] == {"segment_count": 2, "arc_count": 0, "via_count": 1}
    assert board["zone_count"] == 1
    assert board["zones"][0] == {
        "layers": ["B.Cu"],
        "net_name": "GND",
        "filled_polygon_count": 0,
    }


def test_the_board_report_states_what_it_does_not_prove(board):
    joined = " | ".join(board["limitations"])
    assert "connectivity is not computed" in joined
    assert "no ERC or DRC verdict" in joined
    assert "library references are not resolved" in joined


# ---------------------------------------------------------------------------
# Schematic content
# ---------------------------------------------------------------------------


def test_schematic_format_and_title_block(schematic):
    assert schematic["format"]["version"] == 20231120
    assert schematic["format"]["kicad_series"] == "8.0"
    assert schematic["format"]["supported_versions"] == sorted(SCHEMATIC_VERSIONS)
    assert schematic["sheet"]["paper"] == "A4"
    assert schematic["sheet"]["uuid"] == "66666666-6666-4666-8666-666666666661"
    assert schematic["sheet"]["title_block"] == {
        "company": "Daedalus",
        "date": "2026-09-05",
        "rev": "A",
        "title": "Lane 6 KiCad inspection fixture",
    }


def test_schematic_symbols_are_placements_not_library_definitions(schematic):
    assert schematic["symbol_count"] == 2
    assert [row["reference"] for row in schematic["symbols"]] == ["C1", "R1"]
    assert schematic["symbols"][1] == {
        "lib_id": "Device:R",
        "reference": "R1",
        "value": "10k",
        "footprint": "Resistor_SMD:R_0805_2012Metric",
        "datasheet": "~",
        "unit": 1,
        "in_bom": True,
        "on_board": True,
        "dnp": False,
        "at_x_mm": 100,
        "at_y_mm": 74,
        "rotation_deg": 0,
    }
    # The lib_symbols cache also contains ``symbol`` nodes; they are library
    # definitions and must never be counted as placed instances.
    assert schematic["lib_symbols"] == ["Device:C", "Device:R"]
    assert schematic["lib_symbol_count"] == 2


def test_schematic_sheets_are_listed_but_never_opened(schematic):
    assert schematic["sheet_count"] == 1
    assert schematic["sheets"][0] == {
        "name": "power",
        "file": "power.kicad_sch",
        "at_x_mm": 150,
        "at_y_mm": 70,
        "width_mm": 30,
        "height_mm": 20,
        "pin_count": 1,
        "followed": False,
    }


def test_a_missing_sub_sheet_file_does_not_change_the_report(project, schematic):
    """The referenced power.kicad_sch does not exist, and that is not an error."""

    assert not (project["schematic"].parent / "power.kicad_sch").exists()
    assert schematic["complete"] is True
    assert any("never opened" in item for item in schematic["limitations"])


def test_schematic_labels_are_separated_by_kind(schematic):
    assert schematic["label_count"] == 3
    assert [row["text"] for row in schematic["labels"]["local"]] == ["SIG"]
    assert schematic["labels"]["global"][0] == {
        "text": "GND",
        "shape": "input",
        "at_x_mm": 100,
        "at_y_mm": 110,
        "rotation_deg": 270,
    }
    assert schematic["labels"]["hierarchical"][0]["text"] == "VCC_IN"
    assert schematic["labels"]["netclass_flag"] == []


def test_schematic_graph_counts_are_authored_geometry(schematic):
    assert schematic["graph"] == {
        "wire_count": 3,
        "bus_count": 0,
        "bus_entry_count": 0,
        "junction_count": 1,
        "no_connect_count": 1,
        "text_count": 0,
    }
    assert any(
        "authored geometry, not as a netlist" in item for item in schematic["limitations"]
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unsupported_format_version_is_refused_not_guessed(tmp_path):
    target = tmp_path / "future.kicad_pcb"
    target.write_bytes(BOARD_TEXT.replace("20240108", "20260101").encode("utf-8"))
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(target)
    assert caught.value.reason == "unsupported_format_version"
    assert caught.value.context["version"] == "20260101"
    assert caught.value.context["supported"] == sorted(BOARD_VERSIONS)


def test_an_unsupported_version_may_be_force_parsed_but_stays_incomplete(tmp_path):
    target = tmp_path / "future.kicad_pcb"
    target.write_bytes(BOARD_TEXT.replace("20240108", "20260101").encode("utf-8"))
    report = build_board_report(target, allow_unknown_version=True)
    assert report["complete"] is False
    assert report["format"]["version_supported"] is False
    assert report["format"]["kicad_series"] == ""
    assert any("unsupported_format_version" in item for item in report["limitations"])
    # It still parsed, so the content is there -- flagged, not discarded.
    assert report["footprint_count"] == 2


def test_a_legacy_or_absent_version_token_is_refused(tmp_path):
    target = tmp_path / "legacy.kicad_pcb"
    target.write_bytes(BOARD_TEXT.replace("  (version 20240108)\n", "").encode("utf-8"))
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(target)
    assert caught.value.reason == "unsupported_format_version"
    assert caught.value.context["version"] == ""


def test_a_schematic_offered_as_a_board_is_refused_on_its_root(tmp_path):
    target = tmp_path / "mislabelled.kicad_pcb"
    target.write_bytes(SCHEMATIC_TEXT.encode("utf-8"))
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(target)
    assert caught.value.reason == "unexpected_root"
    assert caught.value.context == {"expected": "kicad_pcb", "actual": "kicad_sch"}


def test_a_truncated_board_is_a_typed_refusal(tmp_path):
    target = tmp_path / "truncated.kicad_pcb"
    target.write_bytes(BOARD_TEXT[: len(BOARD_TEXT) // 2].encode("utf-8"))
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(target)
    assert caught.value.reason == "malformed_sexpr"


def test_random_bytes_named_like_a_board_are_refused(tmp_path):
    target = tmp_path / "garbage.kicad_pcb"
    target.write_bytes(b"\x00\x01\x02 not a board at all \xff")
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(target)
    assert caught.value.reason in {"invalid_encoding", "malformed_sexpr"}


def test_an_oversized_board_is_refused_before_parsing(project):
    with pytest.raises(PcbRefusal) as caught:
        build_board_report(project["board"], max_bytes=64)
    assert caught.value.reason == "input_too_large"


def test_dispatch_refuses_a_suffix_it_cannot_inspect(project):
    with pytest.raises(PcbRefusal) as caught:
        inspect_artifact(project["project"])
    assert caught.value.reason == "unsupported_suffix"
    assert caught.value.context["suffix"] == ".kicad_pro"
    assert caught.value.context["supported"] == [".kicad_pcb", ".kicad_sch"]


def test_dispatch_routes_by_suffix(project, board, schematic):
    assert inspect_artifact(project["board"]) == board
    assert inspect_artifact(project["schematic"]) == schematic
