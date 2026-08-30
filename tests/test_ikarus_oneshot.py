"""G1-IKARUS-04: stateless one-shot request and runtime-evidence binding."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.ikarus_oneshot import (
    OneShotContractError,
    OneShotRequest,
    OneShotRuntimeRefused,
    bind_oneshot_runtime_evidence,
)
from daedalus.ikarus_runtime_role import (
    SOURCE_ONLY_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
)
from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    assemble_recorded_conformance,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ContractProvenance,
    ResourceBudget,
    RuntimeCapabilities,
    RuntimeManifest,
)

HERMES_COMMIT = "fcbd1076a93841fa88855acce810e342a5b78101"
NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)


def _binding(*, adapter_version: str = "v2026.8.19"):
    row = RuntimeRoleBinding(
        role="assistant",
        runtime_id="hermes_agent",
        adapter_id="hermes.oneshot-adapter",
        adapter_version=adapter_version,
        source_revision=HERMES_COMMIT,
        origin="https://github.com/NousResearch/hermes-agent",
        execution_mode=SOURCE_ONLY_EXECUTION_MODE,
        refusal_reason="source-only until broker-bound execution is admitted",
    )
    snapshot = RuntimeRoleRegistry((row,)).snapshot(row.role, row.runtime_id)
    assert snapshot is not None
    return snapshot


def _manifest(*, tools=(), adapter_version: str = "v2026.8.19", cost=True):
    return RuntimeManifest(
        runtime_id="hermes_agent",
        runtime_version="v0.20.5",
        adapter_id="hermes.oneshot-adapter",
        adapter_version=adapter_version,
        source_revision=HERMES_COMMIT,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            tool_events=bool(tools),
            timeout=True,
            cost_reporting=cost,
        ),
        declared_tools=tuple(tools),
        egress_transports=("provider-api",),
        workspace_modes=("read-only",),
        cost_model="provider-reported" if cost else "unknown",
        provenance=ContractProvenance(
            origin="tests.ikarus-oneshot",
            source_revision=HERMES_COMMIT,
            created_at=NOW.isoformat(),
            input_digests=(),
        ),
    )


def _conformance(manifest: RuntimeManifest, tmp_path: Path):
    observations = {
        name: RecordedObservation(
            passed=True,
            detail="offline fixture",
            transcript={"check": name, "result": "passed"},
        )
        for name in RUNTIME_CONFORMANCE_CHECKS
    }
    return assemble_recorded_conformance(
        manifest,
        observations=observations,
        artifact_root=tmp_path / "runtime-evidence",
        receipt_id="ikarus-oneshot-runtime",
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
    )


def _request(binding=None, *, budget=None, instructions="Be concise.", user_input="Summarize this."):
    binding = binding or _binding()
    return OneShotRequest.from_runtime_binding(
        binding,
        purpose="summary",
        instructions=instructions,
        user_input=user_input,
        budget=budget
        or ResourceBudget(
            max_tokens=1024,
            max_cost_microusd=100_000,
            max_wall_time_s=60,
            max_attempts=1,
        ),
    )


def test_request_is_structurally_sessionless_and_single_turn():
    request = _request()
    subject = request.subject()

    assert set(subject) == {
        "schema",
        "purpose",
        "role",
        "runtime_id",
        "runtime_binding_sha256",
        "messages",
        "budget",
        "iteration_limit",
        "tool_scope",
    }
    assert subject["iteration_limit"] == 1
    assert subject["tool_scope"] == []
    assert [row["role"] for row in subject["messages"]] == ["system", "user"]
    assert not ({"session", "session_id", "thread", "history", "memory", "transcript"} & set(subject))


def test_instructions_only_still_has_exactly_one_user_message():
    request = _request(user_input="")
    assert [(row.role, row.content) for row in request.messages] == [
        ("system", "Be concise."),
        ("user", ""),
    ]


def test_request_requires_prompt_token_walltime_and_single_attempt_bounds():
    binding = _binding()
    with pytest.raises(OneShotContractError, match="instructions or user_input"):
        _request(binding, instructions="", user_input="")
    with pytest.raises(OneShotContractError, match="max_tokens"):
        _request(binding, budget=ResourceBudget(max_wall_time_s=60))
    with pytest.raises(OneShotContractError, match="max_wall_time_s"):
        _request(binding, budget=ResourceBudget(max_tokens=100))
    with pytest.raises(OneShotContractError, match="more than one"):
        _request(
            binding,
            budget=ResourceBudget(max_tokens=100, max_wall_time_s=60, max_attempts=2),
        )


def test_request_digest_binds_prompt_budget_and_runtime_identity():
    binding = _binding()
    baseline = _request(binding)
    assert baseline.digest == _request(binding).digest
    assert baseline.digest != _request(binding, user_input="Different input").digest
    assert baseline.digest != _request(
        binding,
        budget=ResourceBudget(
            max_tokens=2048,
            max_cost_microusd=100_000,
            max_wall_time_s=60,
            max_attempts=1,
        ),
    ).digest
    assert baseline.digest != _request(_binding(adapter_version="v2026.8.19-r2")).digest


def test_current_toolless_runtime_evidence_is_bound_without_execution(tmp_path):
    binding = _binding()
    manifest = _manifest()
    receipt = _conformance(manifest, tmp_path)
    request = _request(binding)

    evidence_binding = bind_oneshot_runtime_evidence(
        request,
        binding,
        manifest,
        receipt,
        now=NOW + timedelta(seconds=2),
    )

    assert evidence_binding.request_sha256 == request.digest
    assert evidence_binding.runtime_binding_sha256 == binding.digest
    assert evidence_binding.runtime_manifest_sha256 == manifest.digest
    assert evidence_binding.runtime_conformance_sha256 == receipt.digest
    assert evidence_binding.runtime_id == "hermes_agent"
    assert evidence_binding.source_revision == HERMES_COMMIT


def test_stale_or_identity_drifted_runtime_evidence_refuses(tmp_path):
    binding = _binding()
    manifest = _manifest()
    receipt = _conformance(manifest, tmp_path)
    request = _request(binding)

    with pytest.raises(OneShotRuntimeRefused, match="not current"):
        bind_oneshot_runtime_evidence(
            request,
            binding,
            manifest,
            receipt,
            now=NOW + timedelta(days=8),
        )

    drifted = _manifest(adapter_version="v2026.8.19-r2")
    with pytest.raises(OneShotRuntimeRefused, match="adapter_version"):
        bind_oneshot_runtime_evidence(
            request,
            binding,
            drifted,
            _conformance(drifted, tmp_path / "drifted"),
            now=NOW + timedelta(seconds=2),
        )


def test_tools_and_unmetered_cost_fail_closed_before_live_adapter(tmp_path):
    binding = _binding()
    request = _request(binding)

    with_tools = _manifest(tools=("read-file",))
    with pytest.raises(OneShotRuntimeRefused, match="deny-by-default"):
        bind_oneshot_runtime_evidence(
            request,
            binding,
            with_tools,
            _conformance(with_tools, tmp_path / "tools"),
            now=NOW + timedelta(seconds=2),
        )

    no_cost = _manifest(cost=False)
    with pytest.raises(OneShotRuntimeRefused, match="cost reporting"):
        bind_oneshot_runtime_evidence(
            request,
            binding,
            no_cost,
            _conformance(no_cost, tmp_path / "cost"),
            now=NOW + timedelta(seconds=2),
        )


def test_module_is_projection_only_not_a_hidden_provider_or_session_runtime():
    path = Path(__file__).resolve().parents[1] / "daedalus" / "ikarus_oneshot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert not ({"subprocess", "socket", "requests", "httpx", "sqlite3", "os"} & imports)
    assert not ({"open", "exec", "eval"} & calls)
    source = path.read_text(encoding="utf-8")
    assert "PROMPT_TEMPLATES" not in source
    assert "call_llm(" not in source
    assert "run_runtime_provider(" not in source
