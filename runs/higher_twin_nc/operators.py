"""Typed, deterministic edit operators for higher-twin-nc-v1 fixtures.

Every operator is a pure text transformation on a copied fixture tree.
No model calls, no randomness, no clock reads: the causal ground truth of
the assay must be exactly reproducible.

Footprints are declared statically as read/write resource sets. Resources:
  "field:<name>"  the cross-plane slice of one schema field
  "field:*"       wildcard, intersects every field slice
  "layout"        the field-set membership (schema array / CSV header shape)
An empty footprint (sham) is disjoint from everything.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

DOC_HEADER = (
    "# Field reference\n"
    "\n"
    "Data contract for `data/events.csv`, kept in sync with `schema.json`.\n"
)

CODE_FILES = ("calib.py", "checks.py")


# ---------------------------------------------------------------- helpers

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _load_schema(tree: Path) -> dict:
    return json.loads(_read(tree / "schema.json"))


def _dump_schema(tree: Path, schema: dict) -> None:
    _write(tree / "schema.json", json.dumps(schema, indent=2) + "\n")


def _schema_names(tree: Path) -> list:
    return [f["name"] for f in _load_schema(tree)["fields"]]


def _fmt(value: float) -> str:
    return f"{value:g}"


def _doc_section(name: str, ftype: str, unit: str) -> str:
    unit_text = unit or "none"
    return f"\n## `{name}`\n\nField `{name}` of type {ftype}. Unit: {unit_text}.\n"


def render_docs(schema: dict) -> str:
    parts = [DOC_HEADER]
    for f in schema["fields"]:
        parts.append(_doc_section(f["name"], f["type"], f["unit"]))
    return "".join(parts)


def _edit_docs_section(tree: Path, name: str, transform: Callable[[str], str]) -> None:
    docs = tree / "docs" / "fields.md"
    lines = _read(docs).split("\n")
    out = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line == f"## `{name}`"
        out.append(transform(line) if inside else line)
    _write(docs, "\n".join(out))


def _map_csv_column(tree: Path, name: str, cell_transform: Callable[[str], str]) -> None:
    csv_path = tree / "data" / "events.csv"
    lines = _read(csv_path).rstrip("\n").split("\n")
    header = lines[0].split(",")
    idx = header.index(name)
    out = [lines[0]]
    for line in lines[1:]:
        cells = line.split(",")
        cells[idx] = cell_transform(cells[idx])
        out.append(",".join(cells))
    _write(csv_path, "\n".join(out) + "\n")


# ---------------------------------------------------------------- operator core

@dataclass(frozen=True)
class Op:
    name: str
    reads: frozenset
    writes: frozenset
    pre: Callable[[Path], Optional[str]] = field(repr=False)
    run: Callable[[Path], None] = field(repr=False)

    def precondition(self, tree: Path) -> Optional[str]:
        return self.pre(tree)

    def apply(self, tree: Path) -> None:
        self.run(tree)


def _touches(a: frozenset, b: frozenset) -> bool:
    for x in a:
        for y in b:
            if x == y:
                return True
            if x == "field:*" and y.startswith("field:"):
                return True
            if y == "field:*" and x.startswith("field:"):
                return True
    return False


def conflict(a: Op, b: Op) -> bool:
    """Bernstein condition: potential interference of two operators."""
    return bool(
        _touches(a.writes, b.writes)
        or _touches(a.writes, b.reads)
        or _touches(a.reads, b.writes)
    )


# ---------------------------------------------------------------- operators

def rename_field(old: str = "voltage", new: str = "bias_voltage") -> Op:
    def pre(tree: Path) -> Optional[str]:
        names = _schema_names(tree)
        if old not in names:
            return f"field '{old}' not in schema"
        if new in names:
            return f"field '{new}' already in schema"
        return None

    def run(tree: Path) -> None:
        word = re.compile(rf"\b{re.escape(old)}\b")
        for fname in CODE_FILES + ("docs/fields.md",):
            path = tree / fname
            _write(path, word.sub(new, _read(path)))
        schema = _load_schema(tree)
        for f in schema["fields"]:
            if f["name"] == old:
                f["name"] = new
        _dump_schema(tree, schema)
        csv_path = tree / "data" / "events.csv"
        lines = _read(csv_path).rstrip("\n").split("\n")
        lines[0] = ",".join(new if tok == old else tok for tok in lines[0].split(","))
        _write(csv_path, "\n".join(lines) + "\n")

    return Op(
        name=f"rename_{old}_to_{new}",
        reads=frozenset({f"field:{old}"}),
        # 'layout' is written because renaming changes field-set membership
        # (schema array entries, CSV header) — a layout-only reader must not
        # be certified as disjoint to a rename.
        writes=frozenset({f"field:{old}", f"field:{new}", "layout"}),
        pre=pre,
        run=run,
    )


def scale_values(name: str = "voltage", factor: float = 1000.0, new_unit: str = "mV") -> Op:
    def pre(tree: Path) -> Optional[str]:
        if name not in _schema_names(tree):
            return f"field '{name}' not in schema"
        return None

    def run(tree: Path) -> None:
        schema = _load_schema(tree)
        entry = next(f for f in schema["fields"] if f["name"] == name)
        old_unit = entry["unit"] or "none"
        entry["unit"] = new_unit
        _dump_schema(tree, schema)
        _map_csv_column(tree, name, lambda cell: _fmt(float(cell) * factor))
        _edit_docs_section(
            tree, name,
            lambda line: line.replace(f"Unit: {old_unit}.", f"Unit: {new_unit}."),
        )

    return Op(
        name=f"scale_{name}_x{_fmt(factor)}",
        reads=frozenset({f"field:{name}"}),
        writes=frozenset({f"field:{name}"}),
        pre=pre,
        run=run,
    )


def clip_values(name: str = "voltage", vmax: float = 2.5) -> Op:
    def pre(tree: Path) -> Optional[str]:
        if name not in _schema_names(tree):
            return f"field '{name}' not in schema"
        return None

    def run(tree: Path) -> None:
        _map_csv_column(
            tree, name,
            lambda cell: _fmt(vmax) if float(cell) > vmax else cell,
        )

    return Op(
        name=f"clip_{name}_at{_fmt(vmax)}",
        reads=frozenset({f"field:{name}"}),
        writes=frozenset({f"field:{name}"}),
        pre=pre,
        run=run,
    )


def add_field(name: str = "temperature", default: str = "20.0",
              ftype: str = "number", unit: str = "C") -> Op:
    def pre(tree: Path) -> Optional[str]:
        if name in _schema_names(tree):
            return f"field '{name}' already in schema"
        return None

    def run(tree: Path) -> None:
        schema = _load_schema(tree)
        schema["fields"].append({"name": name, "type": ftype, "unit": unit})
        _dump_schema(tree, schema)
        csv_path = tree / "data" / "events.csv"
        lines = _read(csv_path).rstrip("\n").split("\n")
        lines[0] += f",{name}"
        lines[1:] = [line + f",{default}" for line in lines[1:]]
        _write(csv_path, "\n".join(lines) + "\n")
        docs = tree / "docs" / "fields.md"
        _write(docs, _read(docs) + _doc_section(name, ftype, unit))

    return Op(
        name=f"add_{name}",
        reads=frozenset({"layout"}),
        writes=frozenset({f"field:{name}", "layout"}),
        pre=pre,
        run=run,
    )


def tighten_type(name: str = "sample_id") -> Op:
    def pre(tree: Path) -> Optional[str]:
        schema = _load_schema(tree)
        entry = next((f for f in schema["fields"] if f["name"] == name), None)
        if entry is None:
            return f"field '{name}' not in schema"
        if entry["type"] != "number":
            return f"field '{name}' is not of type number"
        return None

    def run(tree: Path) -> None:
        schema = _load_schema(tree)
        entry = next(f for f in schema["fields"] if f["name"] == name)
        entry["type"] = "integer"
        _dump_schema(tree, schema)
        _map_csv_column(tree, name, lambda cell: str(int(float(cell))))
        _edit_docs_section(
            tree, name,
            lambda line: line.replace("of type number.", "of type integer."),
        )

    return Op(
        name=f"tighten_{name}_to_integer",
        reads=frozenset({f"field:{name}"}),
        writes=frozenset({f"field:{name}"}),
        pre=pre,
        run=run,
    )


def normalize_by_pressure(honest: bool, voltage: str = "voltage",
                          pressure: str = "pressure") -> Op:
    """Divide each voltage cell by the same row's pressure cell.

    Ground-truth instrument for H-ANOM: the transformation READS the pressure
    column. The honest twin declares that read; the liar declares only the
    voltage slice, exactly the kind of false self-report the anomaly detector
    must catch (declared-disjoint pair with measurable order effect).
    """
    def pre(tree: Path) -> Optional[str]:
        names = _schema_names(tree)
        for name in (voltage, pressure):
            if name not in names:
                return f"field '{name}' not in schema"
        return None

    def run(tree: Path) -> None:
        csv_path = tree / "data" / "events.csv"
        lines = _read(csv_path).rstrip("\n").split("\n")
        header = lines[0].split(",")
        v_idx = header.index(voltage)
        p_idx = header.index(pressure)
        out = [lines[0]]
        for line in lines[1:]:
            cells = line.split(",")
            cells[v_idx] = _fmt(float(cells[v_idx]) / float(cells[p_idx]))
            out.append(",".join(cells))
        _write(csv_path, "\n".join(out) + "\n")

    reads = {f"field:{voltage}"}
    if honest:
        reads.add(f"field:{pressure}")
    suffix = "honest" if honest else "liar"
    return Op(
        name=f"normalize_{voltage}_by_{pressure}_{suffix}",
        reads=frozenset(reads),
        writes=frozenset({f"field:{voltage}"}),
        pre=pre,
        run=run,
    )


def regen_docs() -> Op:
    def pre(tree: Path) -> Optional[str]:
        return None

    def run(tree: Path) -> None:
        _write(tree / "docs" / "fields.md", render_docs(_load_schema(tree)))

    return Op(
        name="regen_docs",
        reads=frozenset({"field:*", "layout"}),
        writes=frozenset({"field:*"}),
        pre=pre,
        run=run,
    )


def sham() -> Op:
    def pre(tree: Path) -> Optional[str]:
        return None

    def run(tree: Path) -> None:
        path = tree / "calib.py"
        _write(path, _read(path) + "# sham intervention: semantically inert\n")

    return Op(
        name="sham",
        reads=frozenset(),
        writes=frozenset(),
        pre=pre,
        run=run,
    )


def standard_ops() -> dict:
    """The six typed operators of the sensorlab pilot, in canonical order."""
    return {
        "rename": rename_field(),
        "scale": scale_values(),
        "clip": clip_values(),
        "add": add_field(),
        "tighten": tighten_type(),
        "regen": regen_docs(),
    }
