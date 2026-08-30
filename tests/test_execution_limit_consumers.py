from __future__ import annotations

import json
from unittest.mock import patch

from daedalus.kairos.decompose import decompose
from daedalus.limit_policy import ExecutionLimitPolicy, MODE_UNBOUNDED_EXECUTION
from daedalus.token_policy import trim_paths


UNBOUNDED = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)


def test_unbounded_work_scope_does_not_trim_request_paths():
    paths = [f"src/module_{index}.py" for index in range(20)]

    assert trim_paths(paths, limit=3, limit_policy=UNBOUNDED) == paths


def test_unbounded_decomposition_keeps_every_model_subtask_and_has_no_deadline():
    payload = json.dumps(
        {
            "subtasks": [
                {"objective": f"task {index}", "paths": [f"p{index}.py"]}
                for index in range(7)
            ]
        }
    )
    with patch(
        "daedalus.kairos.decompose.server_reachable", return_value=True
    ), patch(
        "daedalus.kairos.decompose.chat_completion", return_value=payload
    ) as call:
        rows = decompose(
            "split all work",
            "/repo",
            max_subtasks=2,
            limit_policy=UNBOUNDED,
        )

    assert len(rows) == 7
    assert call.call_args.kwargs["timeout_s"] is None
    assert "every useful independent" in call.call_args.kwargs["user"]


def test_bounded_decomposition_still_uses_configured_scope_and_deadline():
    payload = json.dumps(
        [{"objective": f"task {index}", "paths": []} for index in range(5)]
    )
    with patch(
        "daedalus.kairos.decompose.server_reachable", return_value=True
    ), patch(
        "daedalus.kairos.decompose.chat_completion", return_value=payload
    ) as call:
        rows = decompose("split", "/repo", max_subtasks=2)

    assert len(rows) == 2
    assert call.call_args.kwargs["timeout_s"] == 60.0
    assert "at most 2" in call.call_args.kwargs["user"]
