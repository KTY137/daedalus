from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from daedalus.gates.python_target_structure import (
    PythonTargetBindingError,
    PythonTargetSourceError,
    PythonTargetStructure,
    PythonTargetStructureError,
    module_repository_path,
    parse_python_target,
    resolve_python_target_structure,
)


TARGET = "daedalus.sample:Guard.check"
PATH = "daedalus/sample.py"
SOURCE = b"""raise RuntimeError('must not execute')

class Guard:
    @unknown_decorator
    def check(self, value: int) -> bool:
        return value > 0
"""


def _write(root: Path, source: bytes = SOURCE) -> str:
    target = root / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    return hashlib.sha256(source).hexdigest()


def test_structural_target_binds_exact_source_without_execution(
    tmp_path: Path,
) -> None:
    digest = _write(tmp_path)
    result = resolve_python_target_structure(
        tmp_path,
        TARGET,
        expected_source_sha256=digest,
    )
    assert result.target == TARGET
    assert result.module_name == "daedalus.sample"
    assert result.object_path == ("Guard", "check")
    assert result.source_path == PATH
    assert result.source_sha256 == digest
    assert result.source_size == len(SOURCE)
    assert result.definition_kind == "function"
    assert result.chain_kinds == ("class", "function")
    assert result.line == 5
    assert result.column == 4
    payload = result.to_dict()
    assert payload["structural_target_verified"] is True
    assert payload["behavior_verified"] is False
    assert payload["executed"] is False
    assert payload["source_sha256"] == digest


def test_top_level_async_function_is_supported(tmp_path: Path) -> None:
    source = b"async def run():\n    return 1\n"
    path = tmp_path / "daedalus/worker.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(source)
    result = resolve_python_target_structure(
        tmp_path,
        "daedalus.worker:run",
        expected_source_sha256=hashlib.sha256(source).hexdigest(),
    )
    assert result.definition_kind == "async_function"
    assert result.chain_kinds == ("async_function",)


@pytest.mark.parametrize(
    "target",
    [
        "",
        "sample:run",
        "daedalus.sample",
        "daedalus/sample:run",
        "daedalus.sample:bad-name",
        "daedalus.sample:.run",
        "daedalus.sample:Run.",
        "daedalus..sample:run",
    ],
)
def test_target_grammar_is_strict(target: str) -> None:
    with pytest.raises(
        PythonTargetStructureError,
        match="canonical Daedalus Python target",
    ):
        parse_python_target(target)


def test_module_path_mapping_is_deterministic() -> None:
    assert module_repository_path("daedalus.sample") == "daedalus/sample.py"
    assert (
        module_repository_path("daedalus.kernel.attempt_ledger")
        == "daedalus/kernel/attempt_ledger.py"
    )


def test_missing_source_is_wrapped_in_target_domain(tmp_path: Path) -> None:
    with pytest.raises(PythonTargetSourceError, match="cannot be read"):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256="a" * 64,
        )


def test_stale_source_digest_fails_before_ast_projection(tmp_path: Path) -> None:
    _write(tmp_path)
    with pytest.raises(
        PythonTargetBindingError,
        match="digest differs",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256="a" * 64,
        )


def test_invalid_python_source_fails_closed(tmp_path: Path) -> None:
    source = b"def broken(:\n"
    digest = _write(tmp_path, source)
    with pytest.raises(
        PythonTargetSourceError,
        match="not a valid bounded Python module",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256=digest,
        )


def test_missing_definition_fails(tmp_path: Path) -> None:
    source = b"class Other:\n    def check(self):\n        pass\n"
    digest = _write(tmp_path, source)
    with pytest.raises(
        PythonTargetBindingError,
        match="definition is missing",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256=digest,
        )


@pytest.mark.parametrize(
    "source",
    [
        b"class Guard:\n    pass\nclass Guard:\n    pass\n",
        (
            b"class Guard:\n"
            b"    def check(self):\n        pass\n"
            b"    def check(self):\n        pass\n"
        ),
    ],
)
def test_duplicate_definition_chain_is_ambiguous(
    tmp_path: Path,
    source: bytes,
) -> None:
    digest = _write(tmp_path, source)
    with pytest.raises(
        PythonTargetBindingError,
        match="definition is ambiguous",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256=digest,
        )


def test_only_classes_may_contain_qualified_children(tmp_path: Path) -> None:
    source = b"def Guard():\n    def check():\n        pass\n"
    digest = _write(tmp_path, source)
    with pytest.raises(
        PythonTargetBindingError,
        match="only classes",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256=digest,
        )


def test_expected_digest_shape_is_strict(tmp_path: Path) -> None:
    _write(tmp_path)
    with pytest.raises(
        PythonTargetStructureError,
        match="lowercase sha256",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256="A" * 64,
        )


def test_changed_bytes_refuse_the_old_target_subject(tmp_path: Path) -> None:
    digest = _write(tmp_path)
    target = tmp_path / PATH
    target.write_bytes(SOURCE.replace(b"value > 0", b"value >= 0"))
    with pytest.raises(
        PythonTargetBindingError,
        match="digest differs",
    ):
        resolve_python_target_structure(
            tmp_path,
            TARGET,
            expected_source_sha256=digest,
        )


def test_structure_rejects_detached_chain_terminal(tmp_path: Path) -> None:
    digest = _write(tmp_path)
    result = resolve_python_target_structure(
        tmp_path,
        TARGET,
        expected_source_sha256=digest,
    )
    with pytest.raises(ValueError, match="chain terminal"):
        dataclasses.replace(result, definition_kind="async_function")
