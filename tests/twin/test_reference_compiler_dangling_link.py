"""A Markdown link to an undeclared page must refuse, not raise KeyError.

`_markdown` emits a `links_to` edge for every `.md` target it finds, and the
link check in `build_inventory` accepts an undeclared target as long as the file
exists on disk. The edge then points at a node that was never built. Before this
regression test the compiler failed that case with a bare `KeyError` from the
plane lookup, which is a fail-closed violation: `ReferenceCompileError` is the
module's documented failure type, so a caller guarding compilation with it was
silently unprotected.
"""
from __future__ import annotations

import json

import pytest

from daedalus.twin.reference_compiler import (
    ReferenceCompileError,
    compile_reference_project,
)

REVISION = "0" * 40
CREATED_AT = "2026-09-09T00:00:00.000000+00:00"


def _project(tmp_path, *, knowledge_files):
    (tmp_path / "models.py").write_text(
        "from dataclasses import dataclass\n\n\n@dataclass\nclass Event:\n    id: str\n",
        encoding="utf-8",
    )
    (tmp_path / "rows.csv").write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "Index.md").write_text("# Index\n\nSee [Detail](Detail.md).\n", encoding="utf-8")
    (tmp_path / "Detail.md").write_text("# Detail\n\nPlain page.\n", encoding="utf-8")
    (tmp_path / "fourfold.json").write_text(
        json.dumps(
            {
                "schema": "daedalus-fourfold-reference/1",
                "repository_id": "linkcase",
                "code_files": ["models.py"],
                "data_files": ["rows.csv"],
                "knowledge_files": list(knowledge_files),
                "claims": [
                    {
                        "kind": "code_declares_type",
                        "code_file": "models.py",
                        "type_file": "models.py",
                        "type_name": "Event",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_link_to_undeclared_page_refuses_with_compile_error(tmp_path):
    # Detail.md exists on disk but is not declared, so the link resolves while
    # its node is never built.
    root = _project(tmp_path, knowledge_files=["Index.md"])

    with pytest.raises(ReferenceCompileError) as excinfo:
        compile_reference_project(root, source_revision=REVISION, created_at=CREATED_AT)

    message = str(excinfo.value)
    assert "undeclared node" in message
    assert "knowledge:doc:Detail.md" in message


def test_link_to_undeclared_page_does_not_raise_keyerror(tmp_path):
    root = _project(tmp_path, knowledge_files=["Index.md"])

    # The specific regression: a caller catching the documented error type must
    # actually catch this failure.
    with pytest.raises(ReferenceCompileError):
        compile_reference_project(root, source_revision=REVISION, created_at=CREATED_AT)


def test_declaring_the_linked_page_compiles(tmp_path):
    root = _project(tmp_path, knowledge_files=["Index.md", "Detail.md"])

    result = compile_reference_project(
        root, source_revision=REVISION, created_at=CREATED_AT
    )

    statuses = {plane.plane: plane.status for plane in result.snapshot.planes}
    assert statuses == {
        "code": "complete",
        "type": "complete",
        "data": "complete",
        "knowledge": "complete",
    }
