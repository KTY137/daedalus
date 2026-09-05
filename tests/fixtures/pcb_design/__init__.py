"""Deterministic KiCad 8 fixture for the effect-free PCB inspection experiment.

The fixture is a *generator*, not a committed ``.kicad_pcb``/``.kicad_sch``
pair, and that is deliberate. ``core.autocrlf`` is true on the owner's host, so
a committed text fixture whose own bytes are hashed into a pinned digest fails
on Windows and passes on Linux from the same commit -- the recorded "CRLF
daemon" family documented at the top of ``.gitattributes``. That file's pin
list is paired with ``tests/test_byte_pin_eol_durability.py`` and is not this
lane's to edit, so this experiment avoids creating a new unlisted byte-pin
subject instead of asking for an exemption.

Python source is read with universal newlines, so the literals below yield LF
regardless of how this file is checked out. :func:`write_fixture` encodes them
with ``newline=""`` semantics (``write_bytes``), so the digests pinned in
``tests/test_pcb_design_inspection.py`` are host-independent.

Whitespace note: KiCad itself indents with tabs; this fixture uses spaces so
the committed Python source carries no ambiguous whitespace. The reader is
whitespace-agnostic and ``test_tab_indentation_is_semantically_identical``
proves it on the tab-indented variant of these same bytes.

Content: a two-layer board with two 0805 footprints (R1 10k, C1 100n), three
named nets (GND, VCC, /SIG) plus KiCad's net 0, a closed four-segment Edge.Cuts
rectangle, two tracks, one via and one unfilled GND zone; and the matching
schematic with two symbols, one hierarchical sheet reference, and one local,
one global and one hierarchical label.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["BOARD_TEXT", "SCHEMATIC_TEXT", "write_fixture"]


BOARD_TEXT = """(kicad_pcb
  (version 20240108)
  (generator "pcbnew")
  (generator_version "8.0")
  (general
    (thickness 1.6)
    (legacy_teardrops no)
  )
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user "B.Adhesive")
    (33 "F.Adhes" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (41 "Cmts.User" user "User.Comments")
    (42 "Eco1.User" user "User.Eco1")
    (43 "Eco2.User" user "User.Eco2")
    (44 "Edge.Cuts" user)
    (45 "Margin" user)
    (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.CrtYd" user "F.Courtyard")
    (48 "B.Fab" user)
    (49 "F.Fab" user)
  )
  (setup
    (pad_to_mask_clearance 0)
    (allow_soldermask_bridges_in_footprints no)
    (pcbplotparams
      (layerselection 0x00010fc_ffffffff)
      (plot_on_all_layers_selection 0x0000000_00000000)
      (disableapertmacros no)
      (usegerberextensions no)
      (usegerberattributes yes)
      (creategerberjobfile yes)
      (svgprecision 4)
      (mode 1)
      (outputformat 1)
      (outputdirectory "")
    )
  )
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (net 3 "/SIG")
  (footprint "Resistor_SMD:R_0805_2012Metric"
    (layer "F.Cu")
    (uuid "11111111-1111-4111-8111-111111111111")
    (at 100 60)
    (descr "Resistor SMD 0805, hand soldering")
    (tags "resistor")
    (property "Reference" "R1"
      (at 0 -1.65 0)
      (layer "F.SilkS")
      (uuid "11111111-1111-4111-8111-111111111112")
      (effects (font (size 1 1) (thickness 0.15)))
    )
    (property "Value" "10k"
      (at 0 1.65 0)
      (layer "F.Fab")
      (uuid "11111111-1111-4111-8111-111111111113")
      (effects (font (size 1 1) (thickness 0.15)))
    )
    (property "Footprint" "Resistor_SMD:R_0805_2012Metric"
      (at 0 0 0)
      (layer "F.Fab")
      (hide yes)
      (uuid "11111111-1111-4111-8111-111111111114")
      (effects (font (size 1.27 1.27)))
    )
    (attr smd)
    (fp_line (start -1.68 -0.95) (end 1.68 -0.95)
      (stroke (width 0.05) (type solid)) (layer "F.CrtYd")
      (uuid "11111111-1111-4111-8111-111111111115")
    )
    (fp_line (start -1.68 0.95) (end 1.68 0.95)
      (stroke (width 0.05) (type solid)) (layer "F.CrtYd")
      (uuid "11111111-1111-4111-8111-111111111116")
    )
    (pad "1" smd roundrect
      (at -0.9375 0)
      (size 1.025 1.4)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.243902)
      (net 2 "VCC")
      (uuid "11111111-1111-4111-8111-111111111117")
    )
    (pad "2" smd roundrect
      (at 0.9375 0)
      (size 1.025 1.4)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.243902)
      (net 3 "/SIG")
      (uuid "11111111-1111-4111-8111-111111111118")
    )
  )
  (footprint "Capacitor_SMD:C_0805_2012Metric"
    (layer "F.Cu")
    (uuid "22222222-2222-4222-8222-222222222221")
    (at 110 60 90)
    (descr "Capacitor SMD 0805")
    (tags "capacitor")
    (property "Reference" "C1"
      (at 0 -1.68 90)
      (layer "F.SilkS")
      (uuid "22222222-2222-4222-8222-222222222222")
      (effects (font (size 1 1) (thickness 0.15)))
    )
    (property "Value" "100n"
      (at 0 1.68 90)
      (layer "F.Fab")
      (uuid "22222222-2222-4222-8222-222222222223")
      (effects (font (size 1 1) (thickness 0.15)))
    )
    (property "Footprint" "Capacitor_SMD:C_0805_2012Metric"
      (at 0 0 0)
      (layer "F.Fab")
      (hide yes)
      (uuid "22222222-2222-4222-8222-222222222224")
      (effects (font (size 1.27 1.27)))
    )
    (attr smd)
    (fp_line (start -1.68 -0.98) (end 1.68 -0.98)
      (stroke (width 0.05) (type solid)) (layer "F.CrtYd")
      (uuid "22222222-2222-4222-8222-222222222225")
    )
    (pad "1" smd roundrect
      (at -0.95 0 90)
      (size 1 1.45)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
      (net 3 "/SIG")
      (uuid "22222222-2222-4222-8222-222222222226")
    )
    (pad "2" smd roundrect
      (at 0.95 0 90)
      (size 1 1.45)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
      (net 1 "GND")
      (uuid "22222222-2222-4222-8222-222222222227")
    )
  )
  (gr_line (start 90 50) (end 130 50)
    (stroke (width 0.05) (type default)) (layer "Edge.Cuts")
    (uuid "33333333-3333-4333-8333-333333333331")
  )
  (gr_line (start 130 50) (end 130 80)
    (stroke (width 0.05) (type default)) (layer "Edge.Cuts")
    (uuid "33333333-3333-4333-8333-333333333332")
  )
  (gr_line (start 130 80) (end 90 80)
    (stroke (width 0.05) (type default)) (layer "Edge.Cuts")
    (uuid "33333333-3333-4333-8333-333333333333")
  )
  (gr_line (start 90 80) (end 90 50)
    (stroke (width 0.05) (type default)) (layer "Edge.Cuts")
    (uuid "33333333-3333-4333-8333-333333333334")
  )
  (gr_text "LANE6 FIXTURE"
    (at 110 53 0)
    (layer "F.SilkS")
    (uuid "33333333-3333-4333-8333-333333333335")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (segment (start 100.9375 60) (end 109.05 60)
    (width 0.25) (layer "F.Cu") (net 3)
    (uuid "44444444-4444-4444-8444-444444444441")
  )
  (segment (start 110.95 60) (end 120 60)
    (width 0.25) (layer "F.Cu") (net 1)
    (uuid "44444444-4444-4444-8444-444444444442")
  )
  (via (at 120 60) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1)
    (uuid "44444444-4444-4444-8444-444444444443")
  )
  (zone
    (net 1)
    (net_name "GND")
    (layers "B.Cu")
    (uuid "55555555-5555-4555-8555-555555555551")
    (hatch edge 0.5)
    (connect_pads (clearance 0.5))
    (min_thickness 0.25)
    (filled_areas_thickness no)
    (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))
    (polygon
      (pts (xy 92 52) (xy 128 52) (xy 128 78) (xy 92 78))
    )
  )
)
"""


SCHEMATIC_TEXT = """(kicad_sch
  (version 20231120)
  (generator "eeschema")
  (generator_version "8.0")
  (uuid "66666666-6666-4666-8666-666666666661")
  (paper "A4")
  (title_block
    (title "Lane 6 KiCad inspection fixture")
    (date "2026-09-05")
    (rev "A")
    (company "Daedalus")
  )
  (lib_symbols
    (symbol "Device:C"
      (pin_numbers (hide yes))
      (pin_names (offset 0.254))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Footprint" "" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Description" "Unpolarized capacitor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "C_0_1"
        (polyline
          (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
          (stroke (width 0.508) (type default))
          (fill (type none))
        )
      )
      (symbol "C_1_1"
        (pin passive line (at 0 3.81 270) (length 2.794)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin passive line (at 0 -3.81 90) (length 2.794)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
    )
    (symbol "Device:R"
      (pin_numbers (hide yes))
      (pin_names (offset 0))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (property "Description" "Resistor" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54)
          (stroke (width 0.254) (type default))
          (fill (type none))
        )
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin passive line (at 0 -3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )
  (junction (at 100 90) (diameter 0) (color 0 0 0 0)
    (uuid "77777777-7777-4777-8777-777777777771")
  )
  (no_connect (at 120 110)
    (uuid "77777777-7777-4777-8777-777777777772")
  )
  (wire (pts (xy 100 80) (xy 100 90))
    (stroke (width 0) (type default))
    (uuid "77777777-7777-4777-8777-777777777773")
  )
  (wire (pts (xy 100 90) (xy 100 100))
    (stroke (width 0) (type default))
    (uuid "77777777-7777-4777-8777-777777777774")
  )
  (wire (pts (xy 100 90) (xy 115 90))
    (stroke (width 0) (type default))
    (uuid "77777777-7777-4777-8777-777777777775")
  )
  (label "SIG"
    (at 105 90 0)
    (fields_autoplaced yes)
    (effects (font (size 1.27 1.27)) (justify left bottom))
    (uuid "88888888-8888-4888-8888-888888888881")
  )
  (global_label "GND"
    (shape input)
    (at 100 110 270)
    (fields_autoplaced yes)
    (effects (font (size 1.27 1.27)) (justify right))
    (uuid "88888888-8888-4888-8888-888888888882")
  )
  (hierarchical_label "VCC_IN"
    (shape input)
    (at 90 70 180)
    (effects (font (size 1.27 1.27)) (justify right))
    (uuid "88888888-8888-4888-8888-888888888883")
  )
  (symbol
    (lib_id "Device:R")
    (at 100 74 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (fields_autoplaced yes)
    (uuid "99999999-9999-4999-8999-999999999991")
    (property "Reference" "R1"
      (at 102 72.9 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Value" "10k"
      (at 102 75.4 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Footprint" "Resistor_SMD:R_0805_2012Metric"
      (at 98.2 74 90)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "~"
      (at 100 74 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (instances
      (project "lane6_fixture"
        (path "/66666666-6666-4666-8666-666666666661"
          (reference "R1") (unit 1)
        )
      )
    )
  )
  (symbol
    (lib_id "Device:C")
    (at 100 104 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (fields_autoplaced yes)
    (uuid "99999999-9999-4999-8999-999999999992")
    (property "Reference" "C1"
      (at 102.5 102.9 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Value" "100n"
      (at 102.5 105.4 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Footprint" "Capacitor_SMD:C_0805_2012Metric"
      (at 100.9 107.8 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "~"
      (at 100 104 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (instances
      (project "lane6_fixture"
        (path "/66666666-6666-4666-8666-666666666661"
          (reference "C1") (unit 1)
        )
      )
    )
  )
  (sheet
    (at 150 70)
    (size 30 20)
    (fields_autoplaced yes)
    (stroke (width 0.1524) (type solid))
    (fill (color 0 0 0 0.0000))
    (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
    (property "Sheetname" "power"
      (at 150 69.3 0)
      (effects (font (size 1.27 1.27)) (justify left bottom))
    )
    (property "Sheetfile" "power.kicad_sch"
      (at 150 90.6 0)
      (effects (font (size 1.27 1.27)) (justify left top))
    )
    (pin "VCC_IN" input
      (at 150 78 180)
      (effects (font (size 1.27 1.27)) (justify right))
      (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
    )
    (instances
      (project "lane6_fixture"
        (path "/66666666-6666-4666-8666-666666666661" (page "2"))
      )
    )
  )
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


PROJECT_TEXT = """{
  "board": {
    "design_settings": {
      "defaults": {},
      "rules": {}
    }
  },
  "meta": {
    "filename": "lane6_fixture.kicad_pro",
    "version": 1
  },
  "net_settings": {
    "classes": [
      {
        "clearance": 0.2,
        "name": "Default",
        "track_width": 0.25
      }
    ]
  },
  "sheets": [
    ["66666666-6666-4666-8666-666666666661", "Root"],
    ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", "power"]
  ]
}
"""


def write_fixture(directory: str | Path, *, name: str = "lane6_fixture") -> dict[str, Path]:
    """Materialize the fixture project under ``directory``.

    Bytes are written with :meth:`Path.write_bytes` so no newline translation
    can occur, which is what makes the pinned report digests portable.
    """

    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    board = base / f"{name}.kicad_pcb"
    schematic = base / f"{name}.kicad_sch"
    project = base / f"{name}.kicad_pro"
    board.write_bytes(BOARD_TEXT.encode("utf-8"))
    schematic.write_bytes(SCHEMATIC_TEXT.encode("utf-8"))
    project.write_bytes(PROJECT_TEXT.encode("utf-8"))
    return {"board": board, "schematic": schematic, "project": project}
