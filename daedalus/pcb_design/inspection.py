"""Read-only inspection of KiCad boards and schematics.

Every report is a pure function of the artifact's bytes. Nothing here starts a
process, imports ``pcbnew``, follows a sheet reference to another file, or
writes anything. Because the report is byte-determined it carries its own
``report_sha256`` and can be pinned in a test.

What this module deliberately does **not** claim:

* it does not compute connectivity. Wires, junctions and labels are reported as
  *authored geometry*; a netlist is what ``kicad-cli sch export netlist`` says
  it is, and that is a later, effectful packet.
* board net names come from the board file's own net table. That table is the
  generator's claim, not independent evidence.
* it produces no ERC or DRC verdict. A design that inspects cleanly here may be
  electrically wrong; the evaluator boundary is not crossed by a parser.

Every such gap is emitted in the report's ``limitations`` list, so a consumer
sees the boundary in the data rather than only in this docstring.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .sexpr import (
    DEFAULT_MAX_BYTES,
    PcbRefusal,
    SExpr,
    args,
    first,
    head,
    parse_bytes,
    read_artifact,
    sublists,
    to_float,
)

__all__ = [
    "BOARD_VERSIONS",
    "SCHEMATIC_VERSIONS",
    "build_board_report",
    "build_schematic_report",
    "canonical_json",
    "inspect_artifact",
    "payload_digest",
]

# Format gate. Values are the ``version`` token KiCad writes; the mapping is the
# KiCad series that emits it. An unlisted value is refused, never guessed.
BOARD_VERSIONS: dict[int, str] = {20240108: "8.0", 20241229: "9.0"}
SCHEMATIC_VERSIONS: dict[int, str] = {20231120: "8.0", 20250114: "9.0"}

_EDGE_LAYER = "Edge.Cuts"
_COPPER_ORDINAL_MAX = 31


def canonical_json(payload: Any) -> str:
    """Canonical serialization: sorted keys, no incidental whitespace."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _sealed(report: dict[str, Any]) -> dict[str, Any]:
    """Attach ``report_sha256`` over the report without that key."""

    body = {key: value for key, value in report.items() if key != "report_sha256"}
    report["report_sha256"] = payload_digest(body)
    return report


def _num(value: float) -> int | float:
    """Normalize a coordinate for stable JSON (100.0 -> 100, 60.5 -> 60.5)."""

    if value == int(value):
        return int(value)
    return value


def _at(node: SExpr) -> tuple[float, float, float] | None:
    entry = first(node, "at")
    if entry is None:
        return None
    values = [to_float(text) for text in args(entry)]
    if len(values) < 2 or values[0] is None or values[1] is None:
        return None
    rotation = values[2] if len(values) > 2 and values[2] is not None else 0.0
    return values[0], values[1], rotation


def _properties(node: SExpr) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in sublists(node, "property"):
        fields = args(entry)
        if len(fields) >= 2 and fields[0] not in out:
            out[fields[0]] = fields[1]
    return out


def _yes(node: SExpr, name: str, default: bool | None = None) -> bool | None:
    entry = first(node, name)
    if entry is None:
        return default
    values = args(entry)
    if not values:
        return default
    return values[0] == "yes"


def _quoted_arg(node: SExpr, index: int = 0) -> str:
    values = args(node)
    return values[index] if len(values) > index else ""


def _points(node: SExpr) -> list[tuple[float, float]]:
    pts = first(node, "pts")
    if pts is None:
        return []
    out: list[tuple[float, float]] = []
    for entry in sublists(pts, "xy"):
        values = [to_float(text) for text in args(entry)]
        if len(values) >= 2 and values[0] is not None and values[1] is not None:
            out.append((values[0], values[1]))
    return out


def _pair(node: SExpr, name: str) -> tuple[float, float] | None:
    entry = first(node, name)
    if entry is None:
        return None
    values = [to_float(text) for text in args(entry)]
    if len(values) >= 2 and values[0] is not None and values[1] is not None:
        return values[0], values[1]
    return None


def _layer_of(node: SExpr) -> str:
    entry = first(node, "layer")
    return _quoted_arg(entry) if entry is not None else ""


def _require_root(tree: SExpr, expected: str, name: str) -> None:
    actual = head(tree)
    if actual != expected:
        raise PcbRefusal(
            "unexpected_root",
            f"{name}: root is {actual or '<not a symbol>'!r}, expected {expected!r}",
            expected=expected,
            actual=actual,
        )


def _format_block(
    tree: SExpr, table: dict[int, str], *, name: str, allow_unknown_version: bool
) -> tuple[dict[str, Any], list[str]]:
    entry = first(tree, "version")
    raw = _quoted_arg(entry) if entry is not None else ""
    try:
        version = int(raw)
    except (TypeError, ValueError):
        version = None
    series = table.get(version) if version is not None else None
    limitations: list[str] = []
    if series is None:
        if not allow_unknown_version:
            raise PcbRefusal(
                "unsupported_format_version",
                f"{name}: version {raw or '<absent>'} is not a supported KiCad format "
                f"(supported: {sorted(table)})",
                version=raw,
                supported=sorted(table),
            )
        limitations.append(
            f"unsupported_format_version: {raw or '<absent>'} was parsed under "
            "--allow-unknown-version; field meanings are assumed, not verified"
        )
    generator = first(tree, "generator")
    generator_version = first(tree, "generator_version")
    return (
        {
            "version": version if version is not None else raw,
            "version_supported": series is not None,
            "kicad_series": series or "",
            "supported_versions": sorted(table),
            "generator": _quoted_arg(generator) if generator is not None else "",
            "generator_version": (
                _quoted_arg(generator_version) if generator_version is not None else ""
            ),
        },
        limitations,
    )


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def _board_layers(tree: SExpr) -> list[dict[str, Any]]:
    block = first(tree, "layers")
    if block is None:
        return []
    rows: list[dict[str, Any]] = []
    for entry in block:
        if not isinstance(entry, tuple):
            continue
        ordinal_text = head(entry)
        try:
            ordinal = int(ordinal_text)
        except (TypeError, ValueError):
            continue
        fields = args(entry)
        rows.append(
            {
                "ordinal": ordinal,
                "canonical_name": fields[0] if fields else "",
                "type": fields[1] if len(fields) > 1 else "",
                "user_name": fields[2] if len(fields) > 2 else "",
            }
        )
    return rows


def _edge_extents(tree: SExpr) -> dict[str, Any]:
    """Bounding box of top-level Edge.Cuts graphics.

    Curvature is modelled exactly only for ``gr_circle`` (centre plus radius).
    Arcs and curves contribute their control points, which understates a bulge;
    when any such element is present the report says the extents are a lower
    bound instead of pretending they are the outline.
    """

    xs: list[float] = []
    ys: list[float] = []
    counts: dict[str, int] = {}
    endpoints: dict[tuple[float, float], int] = {}
    approximate = False
    polyline_only = True

    for node in tree:
        if not isinstance(node, tuple):
            continue
        kind = head(node)
        if not kind.startswith("gr_") or _layer_of(node) != _EDGE_LAYER:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "gr_line":
            start, end = _pair(node, "start"), _pair(node, "end")
            for point in (start, end):
                if point is None:
                    continue
                xs.append(point[0])
                ys.append(point[1])
                key = (round(point[0], 6), round(point[1], 6))
                endpoints[key] = endpoints.get(key, 0) + 1
        elif kind == "gr_rect":
            start, end = _pair(node, "start"), _pair(node, "end")
            for point in (start, end):
                if point is not None:
                    xs.append(point[0])
                    ys.append(point[1])
        elif kind == "gr_circle":
            centre, edge = _pair(node, "center"), _pair(node, "end")
            polyline_only = False
            if centre is not None and edge is not None:
                radius = ((edge[0] - centre[0]) ** 2 + (edge[1] - centre[1]) ** 2) ** 0.5
                xs.extend((centre[0] - radius, centre[0] + radius))
                ys.extend((centre[1] - radius, centre[1] + radius))
        else:  # gr_arc, gr_poly, gr_curve, gr_bbox and anything later
            polyline_only = False
            approximate = approximate or kind in {"gr_arc", "gr_curve"}
            for name in ("start", "mid", "end", "center"):
                point = _pair(node, name)
                if point is not None:
                    xs.append(point[0])
                    ys.append(point[1])
            for point in _points(node):
                xs.append(point[0])
                ys.append(point[1])

    footprint_edges = 0
    for footprint in sublists(tree, "footprint"):
        for node in footprint:
            if isinstance(node, tuple) and head(node).startswith("fp_") and _layer_of(node) == _EDGE_LAYER:
                footprint_edges += 1

    if not xs or not ys:
        return {
            "present": False,
            "source_layer": _EDGE_LAYER,
            "element_counts": {},
            "footprint_edge_elements": footprint_edges,
            "extents_method": "none",
            "extents_are_lower_bound": False,
            "closed_polyline": None,
            "min_x_mm": None,
            "min_y_mm": None,
            "max_x_mm": None,
            "max_y_mm": None,
            "width_mm": None,
            "height_mm": None,
        }

    closed: bool | None = None
    if polyline_only and counts.get("gr_line"):
        closed = bool(endpoints) and all(degree == 2 for degree in endpoints.values())

    return {
        "present": True,
        "source_layer": _EDGE_LAYER,
        "element_counts": dict(sorted(counts.items())),
        "footprint_edge_elements": footprint_edges,
        "extents_method": "control_points_with_exact_circles",
        "extents_are_lower_bound": approximate,
        "closed_polyline": closed,
        "min_x_mm": _num(min(xs)),
        "min_y_mm": _num(min(ys)),
        "max_x_mm": _num(max(xs)),
        "max_y_mm": _num(max(ys)),
        "width_mm": _num(max(xs) - min(xs)),
        "height_mm": _num(max(ys) - min(ys)),
    }


def _board_footprints(tree: SExpr) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in sublists(tree, "footprint"):
        properties = _properties(node)
        position = _at(node)
        pads = list(sublists(node, "pad"))
        nets: set[str] = set()
        for pad in pads:
            net = first(pad, "net")
            if net is not None:
                values = args(net)
                if len(values) > 1:
                    nets.add(values[1])
        attributes = first(node, "attr")
        rows.append(
            {
                "library_link": _quoted_arg(node),
                "reference": properties.get("Reference", ""),
                "value": properties.get("Value", ""),
                "footprint_field": properties.get("Footprint", ""),
                "layer": _layer_of(node),
                "at_x_mm": _num(position[0]) if position else None,
                "at_y_mm": _num(position[1]) if position else None,
                "rotation_deg": _num(position[2]) if position else None,
                "pad_count": len(pads),
                "attributes": list(args(attributes)) if attributes is not None else [],
                "nets": sorted(nets),
            }
        )
    rows.sort(key=lambda row: (str(row["reference"]), str(row["library_link"])))
    return rows


def build_board_report(
    path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_unknown_version: bool = False,
) -> dict[str, Any]:
    """Inspect one ``.kicad_pcb``. Pure function of the file's bytes."""

    artifact = read_artifact(path, max_bytes=max_bytes)
    tree = parse_bytes(artifact.data)
    _require_root(tree, "kicad_pcb", artifact.name)
    fmt, limitations = _format_block(
        tree, BOARD_VERSIONS, name=artifact.name, allow_unknown_version=allow_unknown_version
    )

    general = first(tree, "general")
    thickness = None
    if general is not None:
        entry = first(general, "thickness")
        if entry is not None:
            value = to_float(_quoted_arg(entry))
            thickness = _num(value) if value is not None else None
    paper = first(tree, "paper")

    layers = _board_layers(tree)
    nets = []
    for node in sublists(tree, "net"):
        values = args(node)
        if not values:
            continue
        try:
            ordinal = int(values[0])
        except ValueError:
            continue
        nets.append({"ordinal": ordinal, "name": values[1] if len(values) > 1 else ""})
    nets.sort(key=lambda row: int(row["ordinal"]))

    footprints = _board_footprints(tree)
    outline = _edge_extents(tree)

    tracks = {
        "segment_count": sum(1 for _ in sublists(tree, "segment")),
        "arc_count": sum(1 for _ in sublists(tree, "arc")),
        "via_count": sum(1 for _ in sublists(tree, "via")),
    }
    zones: list[dict[str, Any]] = []
    for node in sublists(tree, "zone"):
        zone_layers: set[str] = set()
        multi = first(node, "layers")
        if multi is not None:
            zone_layers.update(args(multi))
        single = _layer_of(node)
        if single:
            zone_layers.add(single)
        net_name = first(node, "net_name")
        zones.append(
            {
                "layers": sorted(zone_layers),
                "net_name": _quoted_arg(net_name) if net_name is not None else "",
                "filled_polygon_count": sum(1 for _ in sublists(node, "filled_polygon")),
            }
        )
    zones.sort(key=lambda row: (str(row["net_name"]), tuple(row["layers"])))

    limitations.extend(
        [
            "connectivity is not computed; the net table is the generator's claim, "
            "not independent evidence",
            "no ERC or DRC verdict is produced; that requires kicad-cli under an "
            "admitted effect path",
            "footprint library references are not resolved; no library table is read",
        ]
    )
    if outline["footprint_edge_elements"]:
        limitations.append(
            f"{outline['footprint_edge_elements']} Edge.Cuts element(s) live inside "
            "footprints and are excluded from the extents; footprint placement "
            "transforms are not applied"
        )
    if outline["extents_are_lower_bound"]:
        limitations.append(
            "the outline contains arcs or curves; the extents are a lower bound "
            "derived from control points"
        )

    return _sealed(
        {
            "schema": "daedalus.pcb_design/board-report/1",
            "artifact": {**artifact.identity(), "kind": "kicad_pcb"},
            "format": fmt,
            "board": {
                "thickness_mm": thickness,
                "paper": _quoted_arg(paper) if paper is not None else "",
                "layer_count": len(layers),
                "copper_layer_count": sum(
                    1 for row in layers if int(row["ordinal"]) <= _COPPER_ORDINAL_MAX
                ),
                "layers": layers,
                "outline": outline,
            },
            "nets": nets,
            "net_count": len(nets),
            "named_net_count": sum(1 for row in nets if row["name"]),
            "footprints": footprints,
            "footprint_count": len(footprints),
            "tracks": tracks,
            "zones": zones,
            "zone_count": len(zones),
            # ``complete`` says the format gate passed, nothing more. The
            # ``limitations`` list is structural: it never becomes empty, and a
            # complete report is still not evidence about the design.
            "complete": fmt["version_supported"],
            "limitations": sorted(set(limitations)),
        }
    )


# ---------------------------------------------------------------------------
# Schematic
# ---------------------------------------------------------------------------


def _labels(tree: SExpr, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in sublists(tree, name):
        position = _at(node)
        shape = first(node, "shape")
        rows.append(
            {
                "text": _quoted_arg(node),
                "shape": _quoted_arg(shape) if shape is not None else "",
                "at_x_mm": _num(position[0]) if position else None,
                "at_y_mm": _num(position[1]) if position else None,
                "rotation_deg": _num(position[2]) if position else None,
            }
        )
    rows.sort(key=lambda row: (str(row["text"]), row["at_x_mm"] or 0, row["at_y_mm"] or 0))
    return rows


def build_schematic_report(
    path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_unknown_version: bool = False,
) -> dict[str, Any]:
    """Inspect one ``.kicad_sch``. Pure function of the file's bytes.

    Referenced sub-sheets are listed but never opened: each file is inspected
    alone, so no path outside the given file is read.
    """

    artifact = read_artifact(path, max_bytes=max_bytes)
    tree = parse_bytes(artifact.data)
    _require_root(tree, "kicad_sch", artifact.name)
    fmt, limitations = _format_block(
        tree, SCHEMATIC_VERSIONS, name=artifact.name, allow_unknown_version=allow_unknown_version
    )

    uuid = first(tree, "uuid")
    paper = first(tree, "paper")
    title_block = first(tree, "title_block")
    title_fields: dict[str, str] = {}
    if title_block is not None:
        for key in ("title", "date", "rev", "company"):
            entry = first(title_block, key)
            if entry is not None:
                title_fields[key] = _quoted_arg(entry)

    lib_symbols_block = first(tree, "lib_symbols")
    lib_symbols = (
        sorted({_quoted_arg(node) for node in sublists(lib_symbols_block, "symbol")})
        if lib_symbols_block is not None
        else []
    )

    symbols: list[dict[str, Any]] = []
    for node in sublists(tree, "symbol"):
        lib_id = first(node, "lib_id")
        if lib_id is None:
            # A ``symbol`` without ``lib_id`` at sheet level is a library
            # definition, not a placement; do not report it as an instance.
            continue
        properties = _properties(node)
        position = _at(node)
        unit = first(node, "unit")
        unit_value = None
        if unit is not None:
            parsed = to_float(_quoted_arg(unit))
            unit_value = int(parsed) if parsed is not None else None
        symbols.append(
            {
                "lib_id": _quoted_arg(lib_id),
                "reference": properties.get("Reference", ""),
                "value": properties.get("Value", ""),
                "footprint": properties.get("Footprint", ""),
                "datasheet": properties.get("Datasheet", ""),
                "unit": unit_value,
                "in_bom": _yes(node, "in_bom"),
                "on_board": _yes(node, "on_board"),
                "dnp": _yes(node, "dnp"),
                "at_x_mm": _num(position[0]) if position else None,
                "at_y_mm": _num(position[1]) if position else None,
                "rotation_deg": _num(position[2]) if position else None,
            }
        )
    symbols.sort(key=lambda row: (str(row["reference"]), str(row["lib_id"])))

    sheets: list[dict[str, Any]] = []
    for node in sublists(tree, "sheet"):
        properties = _properties(node)
        position = _at(node)
        size = _pair(node, "size")
        sheets.append(
            {
                "name": properties.get("Sheetname", ""),
                "file": properties.get("Sheetfile", ""),
                "at_x_mm": _num(position[0]) if position else None,
                "at_y_mm": _num(position[1]) if position else None,
                "width_mm": _num(size[0]) if size else None,
                "height_mm": _num(size[1]) if size else None,
                "pin_count": sum(1 for _ in sublists(node, "pin")),
                "followed": False,
            }
        )
    sheets.sort(key=lambda row: (str(row["name"]), str(row["file"])))

    labels = {
        "local": _labels(tree, "label"),
        "global": _labels(tree, "global_label"),
        "hierarchical": _labels(tree, "hierarchical_label"),
        "netclass_flag": _labels(tree, "netclass_flag"),
    }

    graph = {
        "wire_count": sum(1 for _ in sublists(tree, "wire")),
        "bus_count": sum(1 for _ in sublists(tree, "bus")),
        "bus_entry_count": sum(1 for _ in sublists(tree, "bus_entry")),
        "junction_count": sum(1 for _ in sublists(tree, "junction")),
        "no_connect_count": sum(1 for _ in sublists(tree, "no_connect")),
        "text_count": sum(1 for _ in sublists(tree, "text")),
    }

    limitations.extend(
        [
            "connectivity is not computed; wires, junctions and labels are reported "
            "as authored geometry, not as a netlist",
            "sub-sheets are listed but never opened; each file is inspected alone",
            "library symbols are read from the file's own lib_symbols cache; no "
            "symbol library table is resolved",
            "no ERC verdict is produced; that requires kicad-cli under an admitted "
            "effect path",
        ]
    )

    return _sealed(
        {
            "schema": "daedalus.pcb_design/schematic-report/1",
            "artifact": {**artifact.identity(), "kind": "kicad_sch"},
            "format": fmt,
            "sheet": {
                "uuid": _quoted_arg(uuid) if uuid is not None else "",
                "paper": _quoted_arg(paper) if paper is not None else "",
                "title_block": dict(sorted(title_fields.items())),
            },
            "lib_symbols": lib_symbols,
            "lib_symbol_count": len(lib_symbols),
            "symbols": symbols,
            "symbol_count": len(symbols),
            "sheets": sheets,
            "sheet_count": len(sheets),
            "labels": labels,
            "label_count": sum(len(rows) for rows in labels.values()),
            "graph": graph,
            "complete": fmt["version_supported"],
            "limitations": sorted(set(limitations)),
        }
    )


_DISPATCH = {
    ".kicad_pcb": build_board_report,
    ".kicad_sch": build_schematic_report,
}


def inspect_artifact(
    path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_unknown_version: bool = False,
) -> dict[str, Any]:
    """Dispatch on suffix. An unsupported suffix is a typed refusal."""

    suffix = os.path.splitext(str(path))[1].lower()
    builder = _DISPATCH.get(suffix)
    if builder is None:
        raise PcbRefusal(
            "unsupported_suffix",
            f"{suffix or '<none>'} is not inspectable; expected one of "
            f"{sorted(_DISPATCH)}",
            suffix=suffix,
            supported=sorted(_DISPATCH),
        )
    return builder(path, max_bytes=max_bytes, allow_unknown_version=allow_unknown_version)
