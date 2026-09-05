"""Regression tests for the sealed Claude operation's output-evidence boundary."""
from __future__ import annotations

import hashlib
import json

from daedalus.providers import claude_sealed_operation as sealed


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
