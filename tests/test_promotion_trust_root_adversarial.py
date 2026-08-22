"""The five cases the trunk HMAC root FAILED, as regression tests.

Source: ``docs/inventory/2026-08-21/preruling/trust_root_report.json``, Phase-0
adversarial trust-root suite. TRUNK scored 19 PASS / 5 FAIL against the
checkpoint verifier's 23 PASS / 0 FAIL. Those five are the requirements D5's
implementation has to meet; each test below names its case id and quotes the
measured observation it exists to prevent from recurring.

Every one of them was ``expected: fail-closed (refuse)`` and
``observed: accepted``.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

from daedalus.kernel import sandbox as sandbox_mod
from daedalus.kernel.promotion_trust_root import (
    ApprovalVerdict,
    SecondFactorOutcome,
    claim_approval,
    evaluate_promotion_trust,
    scrubbed_child_env,
    second_factor_ledger_path,
)

_PINNED_IMAGE = "python@sha256:" + "0" * 64


def _policy(workspace: Path) -> "sandbox_mod.DockerSandboxPolicy":
    return sandbox_mod.DockerSandboxPolicy(
        image=_PINNED_IMAGE,
        candidate_workspace=workspace,
        network="none",
        timeout_s=30,
    )


CANDIDATE = "9" * 64
EVIDENCE = "8" * 64
REVISION = "7" * 40


def _approved(nonce: str = "nonce-adversarial") -> ApprovalVerdict:
    return ApprovalVerdict(
        approved=True,
        reason="test double: owner signature verified",
        candidate_sha256=CANDIDATE,
        tag=f"promote/{CANDIDATE}",
        owner_approval_ref="artifact-locator:sha256:" + ("6" * 64),
        signer="owner@example",
        expires_at="2026-08-22T23:00:00+00:00",
        nonce=nonce,
        evidence_sha256=EVIDENCE,
        source_revision=REVISION,
        signed_at="2026-08-22T11:00:00+00:00",
    )


# --------------------------------------------------------------------------- #
# A10 / A10b -- the ordinary-mint family                                       #
# --------------------------------------------------------------------------- #
def test_A10_a_process_holding_only_the_env_secret_cannot_reach_the_root(
    tmp_path: Path,
) -> None:
    """A10, MEASURED on TRUNK: 'an ordinary subprocess holding the secret mints
    an approval for an artifact no owner reviewed; the verifier accepts it'
    (returned owner_id=owner key_id=key-1 ... the minting process was an
    ordinary child holding only the env secret).

    Structural closure: the root verifies against PUBLIC keys committed at
    HEAD, so an environment secret mints nothing it will accept. Here the
    repository has no signed tag and no committed allowed-signers file at all,
    which is exactly the state an env-secret holder can produce, and the root
    refuses.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    decision = evaluate_promotion_trust(
        repo_root=tmp_path,
        candidate_artifact_sha256=CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        source_revision=REVISION,
        stage="sealed",
        _second_factor=SecondFactorOutcome(
            valid=True, reason="a self-minted HMAC approval that authenticates"
        ),
    )
    assert decision.promote is False
    assert decision.cell == (False, True)
    assert decision.deny_receipt()["failing_factors"] == ["root:git-signed-tag"]


def test_A10b_a_self_minted_approval_consumed_by_the_real_ledger_grants_nothing(
    tmp_path: Path,
) -> None:
    """A10b, MEASURED on TRUNK: 'the self-minted approval is consumed through
    the real ledger' -> accepted.

    Closure by DEMOTION, not by making consumption harder: a successful
    consumption is now recorded and never granting. The assertion that matters
    is that a fully valid second factor still yields REJECT, and that the
    successful consumption is nonetheless written down.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    decision = evaluate_promotion_trust(
        repo_root=tmp_path,
        candidate_artifact_sha256=CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        source_revision=REVISION,
        stage="sealed",
        _second_factor=SecondFactorOutcome(
            valid=True,
            reason="consumed through the real ledger",
            consumption_sha256="5" * 64,
        ),
    )
    assert decision.promote is False
    assert decision.second_factor.valid is True
    written = second_factor_ledger_path(tmp_path).read_text(encoding="utf-8")
    assert '"hmac_valid":true' in written.replace(" ", "")
    assert '"table_outcome":"REJECT"' in written.replace(" ", "")


# --------------------------------------------------------------------------- #
# A12 -- replay against a caller-supplied ledger                               #
# --------------------------------------------------------------------------- #
def test_A12_the_replay_store_is_not_a_parameter() -> None:
    """A12, MEASURED on TRUNK: 'spent approval re-authenticated against a
    SECOND, caller-supplied ledger holding a copied consumption row' ->
    accepted, because 'uniqueness is per-database and the ledger is a
    caller-supplied parameter'.

    The fix is the absence of the parameter. If this assertion ever needs
    relaxing, the finding is back.
    """
    claim_params = set(inspect.signature(claim_approval).parameters)
    assert "spent_root" not in claim_params
    assert claim_params == {"repo_root", "verdict"}

    decide_params = set(inspect.signature(evaluate_promotion_trust).parameters)
    forbidden = {"spent_root", "ledger_path", "replay_store", "spent_path"}
    assert not (decide_params & forbidden)


def test_A12_a_spent_approval_cannot_be_spent_again(tmp_path: Path) -> None:
    """The uniqueness itself, at the one canonical location."""
    verdict = _approved(nonce="nonce-a12-single-use")
    first, first_reason = claim_approval(tmp_path, verdict)
    second, second_reason = claim_approval(tmp_path, verdict)
    assert first is True, first_reason
    assert second is False
    assert "already spent" in second_reason


def test_A12_only_the_sealed_stage_spends_the_approval(tmp_path: Path) -> None:
    """Two sealed evaluations of the same approval cannot both promote."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    def decide(stage: str):
        return evaluate_promotion_trust(
            repo_root=tmp_path,
            candidate_artifact_sha256=CANDIDATE,
            evidence_packet_sha256=EVIDENCE,
            source_revision=REVISION,
            stage=stage,
            _root_verifier=lambda *a, **k: _approved("nonce-a12-stage"),
            _second_factor=SecondFactorOutcome(valid=True, reason="test double"),
        )

    preflight = decide("preauthorization")
    assert preflight.promote is True
    assert preflight.claimed is False

    sealed = decide("sealed")
    assert sealed.promote is True
    assert sealed.claimed is True

    replay = decide("sealed")
    assert replay.promote is False
    assert "already spent" in replay.deny_reason


# --------------------------------------------------------------------------- #
# A9a -- the canary-env leak                                                   #
# --------------------------------------------------------------------------- #
def test_A9a_a_child_cannot_read_the_approval_secret(monkeypatch) -> None:
    """A9a, MEASURED on TRUNK: 'plain child of the verifier reads the
    approval-secret env var' -> child stdout=CANARY-b67d58decad63a4ad...
    leaked=True; inherited the verifier's environment verbatim.
    """
    canary = "CANARY-a9a-regression"
    monkeypatch.setenv("DAEDALUS_OWNER_APPROVAL_SECRET_CANARY", canary)
    monkeypatch.setenv("DAEDALUS_OWNER_APPROVAL_SECRET", canary)
    monkeypatch.setenv("DAEDALUS_KEEP_ME", "ordinary")

    env = scrubbed_child_env()
    assert "DAEDALUS_OWNER_APPROVAL_SECRET_CANARY" not in env
    assert "DAEDALUS_OWNER_APPROVAL_SECRET" not in env
    assert env["DAEDALUS_KEEP_ME"] == "ordinary"

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os;print(os.environ.get('DAEDALUS_OWNER_APPROVAL_SECRET_CANARY',''))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert canary not in proc.stdout
    assert proc.stdout.strip() == ""
    # the leak is real without the scrub -- otherwise this test proves nothing
    leaky = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os;print(os.environ.get('DAEDALUS_OWNER_APPROVAL_SECRET_CANARY',''))",
        ],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert canary in leaky.stdout


def test_A9a_the_candidate_gate_child_uses_the_scrubbed_environment() -> None:
    """The one child that runs CANDIDATE code, specifically."""
    from daedalus.spine import attempt as attempt_mod

    source = inspect.getsource(attempt_mod._contained_gate_child)
    assert "scrubbed_child_env()" in source
    assert "env = dict(os.environ)" not in source
    assert "scrubbed_child_env()" in inspect.getsource(attempt_mod._git_env)


# --------------------------------------------------------------------------- #
# A9c1 -- an unreachable engine is not a completed attempt                     #
# --------------------------------------------------------------------------- #
def test_A9c1_an_unreachable_docker_engine_is_refused_before_start(
    monkeypatch, tmp_path: Path
) -> None:
    """A9c1, MEASURED on TRUNK: 'attempt path classifies an unreachable Docker
    engine as a COMPLETED attempt rather than refused-before-start'
    (launch_state='completed' returncode=1 error_code=None;
    run_in_docker_sandbox maps only exit code 125 to refused-before-start, and
    the Docker CLI exits 1 when the engine pipe is absent).
    """

    class FakeProc:
        returncode = 1
        stdout = b""
        stderr = (
            b"error during connect: Head "
            b'"http://%2F%2F.%2Fpipe%2Fdocker_engine/_ping": '
            b"open //./pipe/docker_engine: The system cannot find the file specified."
        )

    monkeypatch.setattr(sandbox_mod.subprocess, "run", lambda *a, **k: FakeProc())
    policy = _policy(tmp_path)
    receipt = sandbox_mod.run_in_docker_sandbox(policy, ["python", "-c", "pass"])
    assert receipt.refused_before_start is True
    assert receipt.launch_state == "refused-before-start"
    assert receipt.error_code == "runtime-engine-unreachable"
    assert receipt.returncode is None


def test_A9c1_a_real_container_failure_is_still_a_completed_attempt(
    monkeypatch, tmp_path: Path
) -> None:
    """The discriminating half: the fix must not swallow genuine failures."""

    class FakeProc:
        returncode = 1
        stdout = b""
        stderr = b"AssertionError: the candidate's own test failed"

    monkeypatch.setattr(sandbox_mod.subprocess, "run", lambda *a, **k: FakeProc())
    policy = _policy(tmp_path)
    receipt = sandbox_mod.run_in_docker_sandbox(policy, ["python", "-c", "pass"])
    assert receipt.launch_state == "completed"
    assert receipt.returncode == 1
    assert receipt.error_code is None
