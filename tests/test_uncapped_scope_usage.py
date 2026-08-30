"""Regression proofs for policy-aware read-only scope and concurrency."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from daedalus import ikarus_os, token_monitor
from daedalus.limit_policy import (
    ExecutionLimitPolicy,
    MODE_UNBOUNDED_EXECUTION,
)
from daedalus.spine import picker
from daedalus.structcore import index as index_mod


BOUNDED = ExecutionLimitPolicy()
UNBOUNDED = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)


def _source_tree(root: Path, count: int = 3) -> None:
    for position in range(count):
        path = root / f"module_{position}.py"
        path.write_text(f"VALUE_{position} = {position}\n", encoding="utf-8")


def test_build_index_removes_only_the_daedalus_file_cap_when_unbounded(tmp_path):
    _source_tree(tmp_path)

    bounded = index_mod.build_index(
        tmp_path, max_files=1, limit_policy=BOUNDED)
    unbounded = index_mod.build_index(
        tmp_path, max_files=1, limit_policy=UNBOUNDED)

    assert bounded["n_files"] == 1
    assert bounded["effective_max_files"] == 1
    assert bounded["execution_limit_policy"] == BOUNDED.as_dict()
    assert unbounded["n_files"] == 3
    assert unbounded["effective_max_files"] is None
    assert unbounded["execution_limit_policy"] == UNBOUNDED.as_dict()
    assert unbounded["execution_limit_policy_sha256"] == (
        UNBOUNDED.fingerprint_sha256
    )


def test_cached_index_separates_policy_and_effective_file_limit(tmp_path):
    _source_tree(tmp_path)

    bounded_one = index_mod.cached_index(
        tmp_path, max_files=1, limit_policy=BOUNDED)
    bounded_two = index_mod.cached_index(
        tmp_path, max_files=2, limit_policy=BOUNDED)
    unbounded = index_mod.cached_index(
        tmp_path, max_files=1, limit_policy=UNBOUNDED)

    assert bounded_one["n_files"] == 1
    assert bounded_two["n_files"] == 2
    assert unbounded["n_files"] == 3
    assert len({
        bounded_one["scope_key"],
        bounded_two["scope_key"],
        unbounded["scope_key"],
    }) == 3


def test_unbounded_index_workers_use_os_capacity_not_daedalus_eight_cap(
    monkeypatch,
):
    monkeypatch.delenv("DAEDALUS_SCAN_WORKERS", raising=False)
    monkeypatch.setattr(index_mod.os, "cpu_count", lambda: 32)

    assert index_mod._worker_count(BOUNDED) == 8
    assert index_mod._worker_count(UNBOUNDED) == 32

    monkeypatch.setenv("DAEDALUS_SCAN_WORKERS", "2")
    assert index_mod._worker_count(BOUNDED) == 2
    assert index_mod._worker_count(UNBOUNDED) == 32


def test_ikarus_threads_captured_policy_into_project_indexing():
    index = {"modules": {"pkg/widget.py": {}}}
    slice_result = {
        "slice_text": "# ===== FOCUS: pkg/widget.py =====\ndef widget(): pass",
        "withheld_count": 0,
        "focus_file": "pkg/widget.py",
        "n_included": 1,
        "trimmed_count": 0,
    }
    with mock.patch.object(
        ikarus_os, "resolve_repo_root", return_value="C:/repo"
    ), mock.patch(
        "daedalus.structcore.index.cached_index", return_value=index
    ) as cached, mock.patch(
        "daedalus.structcore.slice.semantic_slice", return_value=slice_result
    ):
        context = ikarus_os._project_context(
            "project",
            "explain widget.py",
            limit_policy=UNBOUNDED,
        )

    cached.assert_called_once_with("C:/repo", limit_policy=UNBOUNDED)
    assert context.focus_file == "pkg/widget.py"


def _usage_log(path: Path, position: int) -> Path:
    path.write_text(
        json.dumps({
            "timestamp": f"2026-08-30T00:00:{position:02d}Z",
            "sessionId": str(position),
            "message": {
                "model": "claude",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }) + "\n",
        encoding="utf-8",
    )
    return path


def test_token_monitor_reads_all_logs_when_work_scope_is_disabled(
    tmp_path,
    monkeypatch,
):
    logs = [_usage_log(tmp_path / f"{i}.jsonl", i) for i in range(23)]
    monkeypatch.setattr(token_monitor, "_iter_project_logs", lambda _root=None: logs)

    bounded = token_monitor.read_usage_samples(
        max_files=20, limit_policy=BOUNDED)
    unbounded = token_monitor.read_usage_samples(
        max_files=20, limit_policy=UNBOUNDED)

    assert len(bounded) == 20
    assert len(unbounded) == 23
    assert token_monitor.summarize_usage(unbounded)["total_fresh_tokens"] == 46


@pytest.mark.parametrize(
    ("policy", "expected_limit"),
    ((BOUNDED, 1), (UNBOUNDED, None)),
)
def test_direct_picker_cli_ignores_limit_only_when_work_scope_is_disabled(
    policy,
    expected_limit,
    monkeypatch,
    capsys,
):
    observed = {}

    def fake_queue(_repo_root, **kwargs):
        observed["limit"] = kwargs["limit"]
        return picker.PickedQueue(())

    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", policy.to_env_value())
    monkeypatch.setattr(picker, "build_queue", fake_queue)
    monkeypatch.setattr(
        "daedalus.budget.process_guard_boundary_decision", lambda: object())
    monkeypatch.setattr(
        "daedalus.spine.effect_boundary.begin_effect", lambda *_a, **_kw: None)

    assert picker.main(["--dry-run", "--limit", "1", "--json"]) == 0
    capsys.readouterr()
    assert observed["limit"] == expected_limit
