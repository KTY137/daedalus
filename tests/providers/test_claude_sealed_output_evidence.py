"""Regression tests for sealed Claude output and executor-owned runtime evidence."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from daedalus import core
from daedalus.providers import claude_cli as subject
from daedalus.providers import claude_sealed_operation as sealed


ATTEMPT_ID = "attempt-runtime-authority-17"
INVOCATION_SHA256 = "c" * 64
TERMINAL_RECEIPT_SHA256 = "d" * 64


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def test_output_evidence_does_not_depend_on_mutable_spine_digest(monkeypatch) -> None:
    """A later project-helper substitution must not redirect broker evidence."""

    invocation_sha256 = "a" * 64
    prompt_sha256 = "b" * 64
    report = {
        "status": "done",
        "summary": "sealed result",
        "files_changed": [],
        "tests_run": ["unit"],
        "risks": [],
        "todos": [],
        "handoff": {},
    }
    report_sha256 = _canonical_sha(report)
    payload = {"invocation_sha256": invocation_sha256}
    value = {
        "agent": "ikarus",
        "prompt_sha256": prompt_sha256,
        "report_sha256": report_sha256,
        "report": report,
    }

    # Isolate the output-evidence half of the operation.  The payload validator
    # has its own tests; here we want a mutation that killed the old design:
    # output_digests used a module-global canonical_sha imported from the wider
    # spine.  Replacing that name changed/refused evidence after admission.
    monkeypatch.setattr(sealed, "_payload", lambda candidate: candidate)
    monkeypatch.setattr(sealed, "canonical_sha", lambda _value: "0" * 64, raising=False)

    expected = _canonical_sha(
        {
            "provider": "claude_cli",
            "agent": "ikarus",
            "invocation_sha256": invocation_sha256,
            "prompt_sha256": prompt_sha256,
            "report_sha256": report_sha256,
            "report": report,
        }
    )

    assert sealed.output_digests(value, payload) == (expected,)


def _provider_result(monkeypatch, tmp_path, *, executed: bool, terminal: bool):
    objective = "verify runtime evidence"
    paths = ["src/ikarus.py"]
    agent = {"name": "qa-critic", "model_tier": "sonnet"}
    model = "sonnet"
    timeout_s = 45
    request_sha256 = "b" * 64
    source_revision = "a" * 40
    authorization = SimpleNamespace(
        request=SimpleNamespace(
            attempt_id=ATTEMPT_ID,
            provenance=SimpleNamespace(source_revision=source_revision),
            digest=request_sha256,
        )
    )
    execution = SimpleNamespace(
        idempotency_key=subject.claude_idempotency_key(INVOCATION_SHA256)
    )
    expected_payload = {
        "objective": objective,
        "worktree": str(tmp_path),
        "paths": paths,
        "agent": agent,
        "model": model,
        "timeout_s": timeout_s,
        "attempt_id": ATTEMPT_ID,
        "source_revision": source_revision,
        "request_sha256": request_sha256,
        "invocation_sha256": INVOCATION_SHA256,
    }
    invocation_payload = SimpleNamespace(to_dict=lambda: {"body": expected_payload})
    terminal_receipt = (
        SimpleNamespace(receipt_sha256=TERMINAL_RECEIPT_SHA256) if terminal else None
    )
    invocation = SimpleNamespace(
        executed=executed,
        start_receipt=SimpleNamespace(receipt_sha256="e" * 64),
        terminal_receipt=terminal_receipt,
        value=(
            {
                "agent": "qa-critic",
                "report": {"status": "done"},
                "prompt_sha256": "f" * 64,
                "report_sha256": "1" * 64,
            }
            if executed
            else None
        ),
    )

    # Admission/broker integrity has its own focused suites. This regression
    # isolates post-broker projection: execution identity must come from the
    # fixed runtime + runtime-bound Attempt + terminal broker receipt.
    monkeypatch.setattr(subject, "_require_sealed_bundle", lambda **_kwargs: None)
    monkeypatch.setattr(
        subject, "_validate_execution_shape", lambda _execution, supplied: list(supplied)
    )
    monkeypatch.setattr(
        subject,
        "_resolve_workspace",
        lambda _repo_root, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(
        subject, "claude_invocation_sha256", lambda **_kwargs: INVOCATION_SHA256
    )
    monkeypatch.setattr(
        subject, "run_sealed_runtime_provider", lambda *_args, **_kwargs: invocation
    )

    return subject.ClaudeCLIProvider().run(
        objective=objective,
        repo_root=str(tmp_path),
        paths=paths,
        agent=agent,
        model=model,
        timeout_s=timeout_s,
        runtime_authorization=authorization,
        effect_execution=execution,
        workspace_grant=object(),
        invocation_authority=object(),
        invocation_payload=invocation_payload,
        invocation_abi=object(),
        executable_registry=object(),
        pre_admission=object(),
        observation_binding_ledger=object(),
    )


def test_claude_provider_emits_authoritative_terminal_execution_identity(
    monkeypatch, tmp_path
) -> None:
    result = _provider_result(monkeypatch, tmp_path, executed=True, terminal=True)

    assert result["runtime_id"] == subject.RUNTIME_ID
    assert result["attempt_id"] == ATTEMPT_ID
    assert result["phase"] == "terminal"
    assert result["terminal_receipt_sha256"] == TERMINAL_RECEIPT_SHA256
    assert "work_item_id" not in result


def test_claude_replay_preserves_receipted_execution_identity(monkeypatch, tmp_path) -> None:
    result = _provider_result(monkeypatch, tmp_path, executed=False, terminal=True)

    assert result["replay"] is True
    assert result["runtime_id"] == subject.RUNTIME_ID
    assert result["attempt_id"] == ATTEMPT_ID
    assert result["phase"] == "terminal"
    assert result["terminal_receipt_sha256"] == TERMINAL_RECEIPT_SHA256
    assert "agent" not in result
    assert "work_item_id" not in result


def test_claude_provider_does_not_invent_terminal_phase_without_terminal_receipt(
    monkeypatch, tmp_path
) -> None:
    result = _provider_result(monkeypatch, tmp_path, executed=False, terminal=False)

    assert result["runtime_id"] == subject.RUNTIME_ID
    assert result["attempt_id"] == ATTEMPT_ID
    assert "phase" not in result
    assert "terminal_receipt_sha256" not in result
    assert "work_item_id" not in result


def test_claude_bridge_terminal_report_uses_provider_execution_evidence(monkeypatch) -> None:
    # Every similarly named request field is adversarial: only provider output
    # may cross the terminal-report evidence boundary.
    request = {
        "objective": "verify runtime evidence",
        "repo_root": "/isolated/worktree",
        "paths": [],
        "model": "sonnet",
        "runtime_id": "request-runtime-must-not-win",
        "work_item_id": "request-work-item-must-not-win",
        "attempt_id": "request-attempt-must-not-win",
        "phase": "request-phase-must-not-win",
        "terminal_receipt_sha256": "9" * 64,
    }
    provider_result = {
        "agent": "qa-critic",
        "report": {"status": "done", "summary": "verified"},
        "runtime_id": subject.RUNTIME_ID,
        "attempt_id": ATTEMPT_ID,
        "phase": "terminal",
        "terminal_receipt_sha256": TERMINAL_RECEIPT_SHA256,
    }
    monkeypatch.setattr(core, "ask_claude", lambda **_kwargs: provider_result)

    report = core._ask_claude_report(request)

    assert report["runtime_id"] == subject.RUNTIME_ID
    assert report["attempt_id"] == ATTEMPT_ID
    assert report["phase"] == "terminal"
    assert report["terminal_receipt_sha256"] == TERMINAL_RECEIPT_SHA256
    assert "work_item_id" not in report
    assert report["request"]["work_item_id"] == "request-work-item-must-not-win"


def test_claude_bridge_never_promotes_requested_execution_identity(monkeypatch) -> None:
    request = {
        "objective": "verify runtime evidence",
        "repo_root": "/isolated/worktree",
        "paths": [],
        "model": "sonnet",
        "runtime_id": "request-runtime-must-not-win",
        "work_item_id": "request-work-item-must-not-win",
        "attempt_id": "request-attempt-must-not-win",
        "phase": "request-phase-must-not-win",
        "terminal_receipt_sha256": "9" * 64,
    }
    monkeypatch.setattr(
        core,
        "ask_claude",
        lambda **_kwargs: {
            "agent": "qa-critic",
            "report": {"status": "done", "summary": "no runtime evidence"},
        },
    )

    report = core._ask_claude_report(request)

    for name in (
        "runtime_id",
        "work_item_id",
        "attempt_id",
        "phase",
        "terminal_receipt_sha256",
    ):
        assert name not in report
