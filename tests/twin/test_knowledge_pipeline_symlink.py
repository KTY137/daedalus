"""Filesystem-boundary regression for the offline knowledge pipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus.twin.knowledge_pipeline import main


CREATED_AT = "2026-08-02T20:00:00Z"


def _dump(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daedalus-confluence-dump/1",
                "pages": [
                    {
                        "page_id": "1",
                        "version": 1,
                        "title": "Safe output",
                        "space_key": "E4",
                        "body_storage": "<p><code>Event.voltage</code> is required.</p>",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable in this test environment: {exc}")


def test_force_replaces_output_symlink_entry_not_its_target(tmp_path: Path) -> None:
    dump = tmp_path / "dump.json"
    _dump(dump)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_bytes(b"DO-NOT-OVERWRITE")
    output = tmp_path / "corpus.json"
    _symlink_or_skip(sentinel, output)

    assert main(
        [
            "ingest-confluence",
            "--input",
            str(dump),
            "--instance-id",
            "test",
            "--imported-at",
            CREATED_AT,
            "--output",
            str(output),
            "--force",
        ]
    ) == 0

    assert sentinel.read_bytes() == b"DO-NOT-OVERWRITE"
    assert not output.is_symlink()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "daedalus-knowledge-corpus/1"


def test_input_symlink_is_refused(tmp_path: Path, capsys) -> None:
    dump = tmp_path / "dump.json"
    _dump(dump)
    linked = tmp_path / "linked.json"
    _symlink_or_skip(dump, linked)

    assert main(
        [
            "ingest-confluence",
            "--input",
            str(linked),
            "--instance-id",
            "test",
            "--imported-at",
            CREATED_AT,
            "--output",
            str(tmp_path / "out.json"),
        ]
    ) == 2
    assert "must not be a symbolic link" in capsys.readouterr().err
