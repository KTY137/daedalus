# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace

import pytest

from daedalus.kernel.runtime_conformance import RuntimeConformanceError
from daedalus.runtimes import verify_production_runtime_envelope


def test_exact_envelope_must_be_present_in_external_trust_set(monkeypatch) -> None:
    calls = []

    def fake_verify(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "daedalus.runtimes.trust.verify_runtime_envelope", fake_verify
    )
    envelope = SimpleNamespace(digest="a" * 64)
    with pytest.raises(RuntimeConformanceError, match="trusted evidence set"):
        verify_production_runtime_envelope(
            envelope,
            object(),
            object(),
            object(),
            trusted_envelope_sha256s=("b" * 64,),
            now=object(),
        )
    assert calls == []

    verify_production_runtime_envelope(
        envelope,
        object(),
        object(),
        object(),
        trusted_envelope_sha256s=("a" * 64,),
        now="instant",
    )
    assert len(calls) == 1
    assert calls[0][1] == {"now": "instant", "require_live": True}


def test_malformed_trusted_envelope_digest_refuses_before_verification(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "daedalus.runtimes.trust.verify_runtime_envelope",
        lambda *args, **kwargs: pytest.fail("structural verifier must not run"),
    )
    with pytest.raises(ValueError, match="sha256"):
        verify_production_runtime_envelope(
            SimpleNamespace(digest="a" * 64),
            object(),
            object(),
            object(),
            trusted_envelope_sha256s=("not-a-digest",),
            now=object(),
        )
