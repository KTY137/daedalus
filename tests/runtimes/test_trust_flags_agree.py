"""The two runtime registries must agree about who may see your source.

WHY THIS TEST EXISTS. Daedalus describes its runtimes twice:

  `daedalus/runtimes/providers/catalogue.py`  PROVIDER_CATALOGUE -- the
      providers that actually run, whose `trusted_with_ip` is
      "approved to receive proprietary/sensitive source"
      (runtimes/providers/contracts.py) and is ENFORCED: codex_cli declares
      ``trusted_with_ip=False,   # NEVER receives denylisted/sensitive
      content``, and orchestration/ikarus_os.py builds that lane's brain
      context with ``lane="untrusted"``.

  `daedalus/orchestration/runtime_registry.py`  RUNTIMES -- the rows the
      desktop shows, published by GET /api/runtimes/status.

On 2026-09-03 they disagreed about `codex_cli`: the catalogue said False, the
registry said True. Nothing in the kernel reads the registry's copy -- its only
consumer is the HTTP payload -- so the mismatch was invisible, and the endpoint
published the PERMISSIVE of the two values. A cockpit that had rendered it
would have told an operator their proprietary source was safe with a runtime
the egress gate treats as untrusted.

That is the failure mode this pins: not "a flag is wrong" but "the value shown
to a human is more generous than the value the gate enforces".

THE MAPPING IS EXPLICIT, not inferred. The two registries use different ids
(`claude_code_cli` vs `claude_cli`; two Ollama rows against one provider), and
guessing a correspondence from string similarity is how a renamed row silently
stops being checked. A registry id absent from the map fails loudly below.
"""
from __future__ import annotations

import pytest

from daedalus.orchestration.runtime_registry import RUNTIMES
from daedalus.runtimes.providers.catalogue import PROVIDER_CATALOGUE

# registry id -> catalogue key, or None when the registry row has no provider
# behind it yet (a declared slot, nothing to disagree with).
MAPPING: dict[str, str | None] = {
    "claude_code_cli": "claude_cli",
    "codex_cli": "codex_cli",
    "ollama_http": "ollama",
    "ollama_cli": "ollama",
    "anthropic_api": "anthropic_api",
    "openai_api": "openai_api",
}


def test_every_registry_row_is_accounted_for() -> None:
    """A new or renamed runtime must be mapped deliberately, not skipped."""
    unmapped = sorted({r.id for r in RUNTIMES} - set(MAPPING))
    assert not unmapped, (
        "these runtime rows have no entry in MAPPING, so nothing checks their "
        f"trust flag against the provider that enforces it: {unmapped}"
    )


@pytest.mark.parametrize("runtime", RUNTIMES, ids=lambda r: r.id)
def test_the_published_trust_flag_is_never_more_generous(runtime) -> None:
    key = MAPPING.get(runtime.id)
    if key is None:
        pytest.skip(f"{runtime.id} has no provider behind it yet")
    provider = PROVIDER_CATALOGUE.get(key)
    if provider is None:
        pytest.fail(f"MAPPING points {runtime.id} at {key!r}, which is not in PROVIDER_CATALOGUE")

    enforced = bool(provider.trusted_with_ip)
    published = bool(runtime.trusted_with_ip)

    assert published == enforced, (
        f"{runtime.id}: /api/runtimes/status publishes trusted_with_ip="
        f"{published}, but the provider that enforces the egress gate "
        f"({key}) says {enforced}. "
        + ("The published value is the MORE GENEROUS of the two, which is the "
           "dangerous direction: it tells an operator their source is safe "
           "with a runtime the gate treats as untrusted."
           if published and not enforced else
           "The two must agree so the cockpit cannot contradict the gate.")
    )


def test_codex_is_not_advertised_as_trusted_with_source() -> None:
    """The specific regression, named so it cannot quietly come back.

    codex_cli is egress-gated as untrusted. Both registries must say so.
    """
    registry = {r.id: r for r in RUNTIMES}["codex_cli"]
    assert registry.trusted_with_ip is False
    assert PROVIDER_CATALOGUE["codex_cli"].trusted_with_ip is False
