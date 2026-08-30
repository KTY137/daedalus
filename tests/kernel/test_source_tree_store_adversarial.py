# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore


REVISION = "a" * 40
NOW = "2026-08-03T21:00:00+00:00"


def _capture(store: SourceTreeStore, source: Path, **changes):
    values = dict(
        tree_id="candidate-tree-adversarial",
        source_revision=REVISION,
        origin="tests.source-tree-adversarial",
        created_at=NOW,
    )
    values.update(changes)
    return store.capture_tree(source, **values)


def test_metadata_exclusions_are_case_insensitive_at_capture(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "kept.py").write_text("value = 1\n", encoding="utf-8")
    (source / ".GIT").mkdir()
    (source / ".GIT" / "config").write_text("secret\n", encoding="utf-8")
    (source / ".DAEDALUS").mkdir()
    (source / ".DAEDALUS" / "state").write_text("runtime\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")

    captured = _capture(store, source)

    assert [entry.path for entry in captured.manifest.entries] == ["kept.py"]


def test_casefold_duplicate_ignore_configuration_is_refused_before_walk(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    store = SourceTreeStore(tmp_path / "cas")
    walked = False

    def forbidden_walk(*_args, **_kwargs):
        nonlocal walked
        walked = True
        raise AssertionError("walk must not start")

    monkeypatch.setattr("daedalus.kernel.source_trees.os.walk", forbidden_walk)
    with pytest.raises(ValueError, match="case-insensitively unique"):
        _capture(
            store,
            source,
            ignored_roots=(".git", ".GIT", ".daedalus"),
        )
    assert walked is False


@pytest.mark.parametrize(
    ("operation", "argument"),
    [
        ("capture_file", True),
        ("capture_total", -1),
        ("materialize_file", True),
        ("materialize_total", -1),
        ("manifest", True),
    ],
)
def test_all_read_and_materialization_limits_refuse_bool_and_negative(
    tmp_path, operation, argument
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("payload\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")
    captured = _capture(store, source)

    with pytest.raises(ValueError, match="non-negative integer"):
        if operation == "capture_file":
            _capture(store, source, max_file_bytes=argument)
        elif operation == "capture_total":
            _capture(store, source, max_total_bytes=argument)
        elif operation == "materialize_file":
            store.materialize_tree(
                captured.ref,
                tmp_path / "output-file",
                max_file_bytes=argument,
            )
        elif operation == "materialize_total":
            store.materialize_tree(
                captured.ref,
                tmp_path / "output-total",
                max_total_bytes=argument,
            )
        else:
            store.load_tree(captured.ref, max_manifest_bytes=argument)


def test_legacy_locator_view_is_read_only_alias_of_shared_artifact_ref(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("payload\n", encoding="utf-8")
    captured = _capture(SourceTreeStore(tmp_path / "cas"), source)
    assert captured.locator == captured.ref.locator
