"""The two contracts the wave-offload issuer used to accept on the caller's word.

Both holes were MEASURED, not theorised:

``provider.write_policy``
    ``sensitivity.path_write_blocked(path, None)`` falls back to
    ``DEFAULT_POLICY``, whose empty ``write_allow`` means UNCONFINED. A loop run
    without ``--project`` therefore handed the issuer an empty
    ``write_policy_blocked`` list and the receipt recorded "cleared every
    declared path" for a guard that had never run.

``containment.attempt``
    ``contained=True, containment_evidence=""`` from any script that can
    ``import daedalus`` produced a signed, persisted lease whose ALLOW reason
    read "wave containment was asserted by the caller with no evidence".

Every test here fails if the issuer goes back to believing its caller.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from daedalus.kernel.offload_lease import (
    CALLER_POLICY_ORIGIN,
    WaveLeaseDenied,
    WaveOffloadLease,
    WritePolicySource,
    acquire_wave_offload_lease,
    resolve_write_policy,
)
from daedalus.sensitivity import Policy
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[1])
AGENTENV = Path(REPO_ROOT) / ".agentenv" / "agentenv.json"
REVISION = "0" * 40
MECHANISM = ("gated_writes.run_write_wave: one TaskAttempt worktree per write task")


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """An armed permit in a throwaway control root -- the ledger and the issuer
    key land beside it, so no test touches the real one."""
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    return sw


def _lease(switch, attempt_id, *, repo_root=REPO_ROOT, **kw):
    body = dict(
        source_revision=REVISION,
        mission_id="lease-policy-test",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=switch,
    )
    body.update(kw)
    return acquire_wave_offload_lease(repo_root, attempt_id=attempt_id, **body)


def _bare_repo(tmp_path: Path) -> Path:
    """A git checkout with NO ``.agentenv/agentenv.json`` -- the fail-closed case."""
    root = tmp_path / "bare"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _reason(result, contract: str) -> str:
    return next(r for r in result.reasons if r.startswith(contract + ":"))


# --------------------------------------------------------------------------- #
# provider.write_policy: the issuer resolves the fence, it does not accept one  #
# --------------------------------------------------------------------------- #
def test_absent_project_policy_falls_back_to_the_repositorys_own_agentenv(switch):
    """policy=None must mean "ask this repository", never "allow everything"."""
    denied = _lease(switch, "w-none", writable_paths=(".agentenv/agentenv.json",))
    assert isinstance(denied, WaveLeaseDenied)
    evidence = _reason(denied, "provider.write_policy")
    # The path the verdict came from is IN the reason, so a reader can fetch it.
    assert str(AGENTENV) in evidence
    assert ".agentenv/agentenv.json" in evidence
    # Before the fix this was a granted lease whose receipt said
    # "cleared every declared path".
    assert denied.receipt()["verdict"] == "deny"
    assert denied.receipt()["lease_id"] is None


def test_a_repo_with_no_policy_is_denied_rather_than_defaulted(switch, tmp_path):
    """No policy is not a permission. DEFAULT_POLICY is unconfined; refuse."""
    root = _bare_repo(tmp_path)
    denied = _lease(switch, "w-nopolicy", repo_root=str(root))
    assert isinstance(denied, WaveLeaseDenied)
    evidence = _reason(denied, "provider.write_policy")
    assert "no usable 'policy' block" in evidence
    assert "UNCONFINED" in evidence
    block = denied.receipt()["write_policy"]
    assert block["sha256"] == ""
    assert block["error"] and "no usable 'policy' block" in block["error"]


def test_the_receipt_names_which_policy_cleared_the_paths(switch):
    """A cleared path is only meaningful next to the text that cleared it."""
    lease = _lease(switch, "w-allow")
    assert isinstance(lease, WaveOffloadLease)
    block = lease.receipt()["write_policy"]
    assert block["origin"] == str(AGENTENV)
    assert block["sha256"] == hashlib.sha256(AGENTENV.read_bytes()).hexdigest()
    assert block["error"] is None
    # ...and the guard evidence stamps the same identity.
    evidence = next(r for r in lease.policy_decision.reasons
                    if r.startswith("provider.write_policy:"))
    assert block["sha256"][:16] in evidence


def test_a_caller_supplied_policy_is_used_and_identified(switch):
    """An explicit Policy is honoured -- and named as caller-supplied, not as a file."""
    lease = _lease(switch, "w-caller",
                   write_policy=Policy(write_allow=("docs/",)))
    assert isinstance(lease, WaveOffloadLease)
    block = lease.receipt()["write_policy"]
    assert block["origin"] == CALLER_POLICY_ORIGIN
    assert len(block["sha256"]) == 64


def test_the_callers_blocklist_can_only_add_refusals(switch):
    """``write_policy_blocked`` stays corroboration; it never removes a refusal
    and it is still honoured when it names something the file cleared."""
    denied = _lease(switch, "w-union", write_policy_blocked=("docs/x.md",))
    assert isinstance(denied, WaveLeaseDenied)
    assert "docs/x.md" in _reason(denied, "provider.write_policy")


def test_declaring_no_paths_declares_the_whole_checkout_and_is_refused(switch):
    """``writable_paths=()`` becomes ``(".",)``. Under a confining policy that is
    a refusal, which is the right reading of "this wave declared no bound"."""
    denied = _lease(switch, "w-unbounded", writable_paths=())
    assert isinstance(denied, WaveLeaseDenied)
    assert _reason(denied, "provider.write_policy")


def test_the_policy_identity_travels_inside_the_decision_digest(switch):
    """Two waves identical except for the fence must not share a policy digest."""
    a = _lease(switch, "w-dig-a", write_policy=Policy(write_allow=("docs/",)))
    b = _lease(switch, "w-dig-b", write_policy=Policy(write_allow=("docs/", "tests/")))
    assert isinstance(a, WaveOffloadLease) and isinstance(b, WaveOffloadLease)
    assert a.policy_decision.policy_sha256 != b.policy_decision.policy_sha256


def test_resolve_write_policy_reports_every_failure_mode_as_unusable(tmp_path):
    """Absent, malformed, and policy-less all resolve to "no fence", never to one."""
    root = tmp_path / "r"
    (root / ".agentenv").mkdir(parents=True)
    absent = resolve_write_policy(tmp_path / "does-not-exist")
    assert isinstance(absent, WritePolicySource) and not absent.usable

    cfg = root / ".agentenv" / "agentenv.json"
    cfg.write_text("{ not json", encoding="utf-8")
    assert not resolve_write_policy(root).usable

    cfg.write_text(json.dumps({"test_command": None}), encoding="utf-8")
    assert not resolve_write_policy(root).usable

    cfg.write_text(json.dumps({"policy": {"write_allow": ["docs/"]}}),
                   encoding="utf-8")
    loaded = resolve_write_policy(root)
    assert loaded.usable
    assert loaded.sha256 == hashlib.sha256(cfg.read_bytes()).hexdigest()


def test_resolve_explicit_write_policy_is_authority_confined_and_byte_bound(tmp_path):
    root = tmp_path / "authority"
    policy = root / "control" / "chip.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps({"policy": {"write_allow": ["."]}}), encoding="utf-8"
    )

    loaded = resolve_write_policy(root, policy_path="control/chip.json")

    assert loaded.usable and loaded.confined
    assert loaded.origin == str(policy.resolve())
    assert loaded.sha256 == hashlib.sha256(policy.read_bytes()).hexdigest()

    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"policy": {"write_allow": ["."]}}), encoding="utf-8"
    )
    refused = resolve_write_policy(root, policy_path=outside)
    assert not refused.usable
    assert "outside" in refused.error


# --------------------------------------------------------------------------- #
# containment.attempt: derived, not asserted                                   #
# --------------------------------------------------------------------------- #
def test_an_unevidenced_containment_assertion_is_refused(switch):
    """THE MEASURED GRANT. This exact call produced a signed, persisted lease
    whose allow reason was "asserted by the caller with no evidence"."""
    denied = _lease(switch, "w-f2", contained=True, containment_evidence="")
    assert isinstance(denied, WaveLeaseDenied)
    assert "named no containment mechanism" in _reason(denied, "containment.attempt")
    assert denied.receipt()["lease_id"] is None


def test_whitespace_is_not_a_containment_mechanism(switch):
    denied = _lease(switch, "w-f2ws", contained=True, containment_evidence="   \n")
    assert isinstance(denied, WaveLeaseDenied)
    assert "named no containment mechanism" in _reason(denied, "containment.attempt")


def test_named_isolation_is_granted_and_the_derivation_is_in_the_receipt(switch):
    lease = _lease(switch, "w-f2ok")
    assert isinstance(lease, WaveOffloadLease)
    evidence = next(r for r in lease.policy_decision.reasons
                    if r.startswith("containment.attempt:"))
    # The DERIVED half -- the issuer's own check -- leads; the caller's
    # mechanism is recorded after it, not instead of it.
    assert "primary_tree.planned_overlap_reason" in evidence
    assert MECHANISM in evidence


def test_a_failed_derivation_denies_even_with_caller_evidence(switch, monkeypatch):
    """The caller's mechanism cannot rescue an isolation root that overlaps."""
    import daedalus.kernel.offload_lease as module

    # The stub takes the derivation's real shape -- subject root, the caller's
    # planned worktree root, and the authority root it is also measured against
    # -- so a signature change here fails as a signature change rather than
    # silently stubbing a narrower contract than the issuer calls.
    monkeypatch.setattr(
        module, "derive_wave_containment",
        lambda root, worktree_root=None, *, authority_root=None: (
            False, "the attempt isolation root overlaps the checkout"))
    denied = _lease(switch, "w-f2derive")
    assert isinstance(denied, WaveLeaseDenied)
    assert "overlaps the checkout" in _reason(denied, "containment.attempt")


def test_a_denied_lease_still_produces_a_canonical_record(switch):
    """A deny decision is a contract, and ``issue_effect_lease`` refuses to turn
    one into a lease -- so refusal and record cannot drift apart. This also pins
    the deduped ``input_digests``: on the deny path the subject digest IS the
    policy digest, and ``ContractProvenance`` rejects duplicates, so the record
    could not be built at all the moment the write contract began refusing."""
    denied = _lease(switch, "w-record", containment_evidence="")
    assert isinstance(denied, WaveLeaseDenied)
    assert denied.policy_decision.verdict == "deny"
    assert not denied.policy_decision.effect_scope.has_effects
    digests = denied.policy_decision.provenance.input_digests
    assert len(digests) == len(set(digests))
