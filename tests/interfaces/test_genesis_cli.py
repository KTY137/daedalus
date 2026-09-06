from __future__ import annotations

import json
import sys

import pytest

from daedalus.interfaces.cli import entry
import daedalus.orchestration.genesis as genesis


def _result(status: str = "preview-ready") -> dict[str, object]:
    return {
        "run_id": "genesis-run-test",
        "status": status,
        "target": "web",
        "candidate": {
            "sha256": "1" * 64,
            "locator": f"artifact-locator:sha256:{'1' * 64}",
        },
        "evidence": {
            "sha256": "2" * 64,
            "status": "passed" if status == "preview-ready" else "failed",
        },
        "preview": {
            "status": "available" if status == "preview-ready" else "not-requested",
            "path": "/api/genesis/genesis-run-test/preview/index.html"
            if status == "preview-ready"
            else None,
        },
        "blockers": [] if status == "preview-ready" else [f"Genesis {status}"],
    }


def test_genesis_command_forwards_arguments_and_emits_json_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}
    result = _result()

    def fake_run(prompt: str, **kwargs: object) -> dict[str, object]:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return result

    monkeypatch.setattr(genesis, "run_genesis", fake_run)
    monkeypatch.setattr("daedalus.foundation.dotenv.load", lambda: None)
    monkeypatch.setattr("daedalus.budget.install_process_guard", lambda: None)
    repo_root = tmp_path / "authority"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daedalus",
            "genesis",
            "Build a private reading list",
            "--target",
            "web",
            "--stack",
            "stdlib-pwa",
            "--request-key",
            "request-17",
            "--repo-root",
            str(repo_root),
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as stopped:
        entry.main()

    assert stopped.value.code == 0
    assert captured == {
        "prompt": "Build a private reading list",
        "target": "web",
        "stack": "stdlib-pwa",
        "request_key": "request-17",
        "repo_root": str(repo_root),
    }
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": True, "genesis": result}


def test_genesis_defaults_repo_root_to_invocation_cwd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run(prompt: str, **kwargs: object) -> dict[str, object]:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return _result()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(genesis, "run_genesis", fake_run)

    assert entry._genesis(["Build from this repository", "--json"]) == 0

    assert captured["repo_root"] == str(tmp_path)
    assert captured["prompt"] == "Build from this repository"
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["ok"] is True


def test_genesis_plain_output_points_to_the_embedded_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _result()
    preview_path = str(result["preview"]["path"])
    monkeypatch.setattr(genesis, "run_genesis", lambda *_args, **_kwargs: result)

    assert entry._genesis(["Build something"]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "open /?view=genesis" in output.out
    assert "sandboxed embedded preview" in output.out
    assert preview_path not in output.out


@pytest.mark.parametrize("status", ("blocked", "failed"))
def test_genesis_blocked_or_failed_result_is_json_but_exits_nonzero(
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _result(status)
    monkeypatch.setattr(genesis, "run_genesis", lambda *_args, **_kwargs: result)

    code = entry._genesis(["Build something", "--json"])

    assert code == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": True, "genesis": result}


@pytest.mark.parametrize(
    "error",
    (
        genesis.GenesisConflictError("request key belongs to another request"),
        genesis.GenesisError("candidate verification failed"),
        OSError("candidate store unavailable"),
        TypeError("invalid injected dependency"),
        ValueError("invalid request material"),
    ),
    ids=("conflict", "genesis", "os", "type", "value"),
)
def test_genesis_expected_conflicts_and_errors_are_refused_cleanly(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(genesis, "run_genesis", fail)

    assert entry._genesis(["Build something", "--json"]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"Genesis refused: {error}\n"


def test_genesis_does_not_swallow_unexpected_programmer_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("unexpected defect")

    monkeypatch.setattr(genesis, "run_genesis", fail)

    with pytest.raises(AssertionError, match="unexpected defect"):
        entry._genesis(["Build something", "--json"])
