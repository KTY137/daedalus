"""Static experiment-isolation and stdout-only boundary checks."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from experiments.forest_v2.tensor_embeddings.contracts import canonical_json_bytes
from experiments.forest_v2.tensor_embeddings.encoding import canonical_source_digest
from experiments.forest_v2.tensor_embeddings.retrievers import FROZEN_HASH_SEEDS


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
RUNTIME_MODULES = tuple(
    path for path in PACKAGE.glob("*.py") if not path.name.startswith("test_")
)
FORBIDDEN_IMPORT_ROOTS = {
    "socket",
    "subprocess",
    "requests",
    "urllib",
    "httpx",
    "aiohttp",
    "sqlite3",
}
FORBIDDEN_MUTATOR_ATTRIBUTES = {
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "rmdir",
    "rename",
    "touch",
    "rmtree",
}


def _trees():
    for path in RUNTIME_MODULES:
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_runtime_has_no_network_subprocess_or_production_store_import() -> None:
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            bad = roots & FORBIDDEN_IMPORT_ROOTS
            if bad:
                offenders.append((path.name, node.lineno, sorted(bad)))
    assert offenders == []


def test_runtime_has_no_filesystem_mutator_or_builtin_open() -> None:
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                offenders.append((path.name, node.lineno, "open"))
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_MUTATOR_ATTRIBUTES
            ):
                offenders.append((path.name, node.lineno, node.func.attr))
    assert offenders == []


def test_no_production_module_imports_or_names_the_experiment() -> None:
    production = REPO / "daedalus"
    offenders = []
    for path in production.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "tensor_embeddings" in text or "forest_v2.tensor" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_cli_source_contains_no_output_path_contract() -> None:
    source = (PACKAGE / "cli.py").read_text(encoding="utf-8")
    assert "--out" not in source
    assert "--write" not in source
    assert "write_text" not in source
    assert "write_bytes" not in source


def _package_snapshot() -> dict[str, tuple[int, str]]:
    return {
        str(path.relative_to(PACKAGE)): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in PACKAGE.rglob("*")
        if path.is_file()
    }


def test_documented_outer_process_cli_is_filesystem_inert() -> None:
    """`python -B` prevents interpreter bytecode writes around the pure CLI."""

    before = _package_snapshot()
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "experiments.forest_v2.tensor_embeddings", "spec"],
        cwd=REPO,
        env=environment,
        check=True,
        capture_output=True,
    )
    output = json.loads(completed.stdout.decode("utf-8", "strict"))
    assert output["automatic_promotions"] == 0
    assert _package_snapshot() == before


def test_encoding_bytes_are_equal_across_fresh_processes_for_every_seed() -> None:
    content = "def parse_record(value): return value"
    payload = canonical_json_bytes(
        {
            "source_id": "src/parser.py",
            "source_digest": canonical_source_digest(content),
            "revision": "0123456789abcdef0123456789abcdef01234567",
            "plane": "code",
            "fields": {
                "path": "src/parser.py",
                "symbol": "parse_record",
                "content": content,
                "neighbor": "",
            },
        }
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for seed in FROZEN_HASH_SEEDS:
        command = [
            sys.executable,
            "-B",
            "-m",
            "experiments.forest_v2.tensor_embeddings",
            "encode",
            "--seed",
            str(seed),
        ]
        outputs = [
            subprocess.run(
                command,
                cwd=REPO,
                env=environment,
                input=payload,
                check=True,
                capture_output=True,
            ).stdout
            for _ in range(2)
        ]
        assert outputs[0] == outputs[1]
