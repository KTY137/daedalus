from __future__ import annotations

import ast
from pathlib import Path

from daedalus.gates.repository_write_inventory_v2 import (
    scan_repository_write_surfaces_v2,
)
from scripts.declare_write_surfaces import (
    NameIndex,
    _dominance,
    resolve_central_doors,
)


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
EXECUTOR_PATH = "daedalus/chip_design/executor.py"
CHIP_ENTRYPOINT = "cli.daedalus_chip"


def _enclosing_function_names(
    source_path: Path,
    positions: set[tuple[int, int]],
) -> dict[tuple[int, int], str]:
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    owners: dict[tuple[int, int], str] = {}
    for node in ast.walk(tree):
        position = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
        if not isinstance(node, ast.Call) or position not in positions:
            continue
        current = parents.get(id(node))
        while current is not None and not isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            current = parents.get(id(current))
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owners[position] = current.name
    return owners


def test_chip_capture_writes_are_directly_lease_dominated() -> None:
    inventory = scan_repository_write_surfaces_v2(
        ROOT,
        source_revision=REVISION,
    )
    surfaces = tuple(
        surface for surface in inventory.surfaces if surface.path == EXECUTOR_PATH
    )

    assert len(surfaces) == 2
    assert {surface.callee for surface in surfaces} == {"tempfile.TemporaryFile"}
    assert all(surface.blocking for surface in surfaces)

    positions = {(surface.line, surface.column) for surface in surfaces}
    owners = _enclosing_function_names(ROOT / EXECUTOR_PATH, positions)
    assert owners == {position: "run_admitted_eda" for position in positions}

    doors, skipped = resolve_central_doors(ROOT)
    chip_doors = tuple(door for door in doors if door.door_id == CHIP_ENTRYPOINT)
    assert len(chip_doors) == 1, skipped
    assert chip_doors[0].rel_path == EXECUTOR_PATH

    dominance = _dominance(ROOT, chip_doors[0], NameIndex.build(ROOT))
    assert dominance.leased_refusal == ""
    assert positions <= dominance.leased_positions
