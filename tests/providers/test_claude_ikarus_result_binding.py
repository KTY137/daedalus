"""The real broker result must satisfy Ikarus' evidence consumer contract.

Reuse the existing persisted authority fixture. Only the vendor process is a
controlled test double; no fake broker result substitutes for ledger evidence.
"""
from pathlib import Path
import json
import pytest
import daedalus.claude_bridge as bridge
from daedalus.providers.claude_cli import ClaudeCLIProvider
from tests.providers.test_claude_runtime_broker import (
    RUNTIME, _stack, _run_kwargs, _execution_row, _successful_subprocess_run,
)


@pytest.mark.parametrize("replay", [False, True])
def test_broker_result_preserves_identity_required_by_ikarus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, replay: bool,
) -> None:
    """Use the real broker and persisted receipts, not a manufactured result.

    Only the vendor child is controlled by the existing subprocess fixture.
    Runtime/Attempt identity must come from admission, never from model output.
    A replay retains identity but must not claim a new terminal observation.
    """
    authorization, execution, authority, ledger = _stack(
        tmp_path, monkeypatch, subprocess_run=_successful_subprocess_run,
    )
    kwargs = _run_kwargs(tmp_path, authorization, execution, authority, ledger)
    first = ClaudeCLIProvider().run(**kwargs)
    if replay:
        def no_second_child(*args, **kw):
            raise AssertionError("replaying a result started another vendor child")
        monkeypatch.setattr(bridge.subprocess, "run", no_second_child)
        result = ClaudeCLIProvider().run(**kwargs)
    else:
        result = first

    assert result["runtime_id"] == RUNTIME
    assert result["attempt_id"] == authorization.request.attempt_id
    assert "work_item_id" not in result  # Projection belongs to Ikarus, not the model.
    if replay:
        assert result["replay"] is True
        assert result["runtime_receipt"]["executed"] is False
        assert "phase" not in result
        assert "terminal_receipt_sha256" not in result
    else:
        row = _execution_row(tmp_path, execution.execution_id)
        terminal = json.loads(row["terminal_receipt_json"])
        assert result["phase"] == "terminal"
        assert result["terminal_receipt_sha256"] == terminal["receipt_sha256"]
        assert result["terminal_receipt_sha256"] == result["runtime_receipt"]["terminal_receipt_sha256"]
