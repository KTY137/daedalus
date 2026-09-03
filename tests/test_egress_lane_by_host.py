"""The lane is decided by WHERE THE BYTES GO, not by the provider's name.

The breach this closes, which Momus raised against the council and which was
sitting in the offload wire the whole time: ``lane="trusted"`` switches OFF the
default-deny allow-list in ``slice_egress_rule``, leaving only the secret floor.
It was chosen from the provider name -- "ollama is local, so trusted" -- while
the Ollama client resolves its endpoint from ``OLLAMA_HOST``, an environment
variable. Exporting

    OLLAMA_HOST=http://100.119.126.9:11434       # the RTX bench, over a tailnet

kept the name "ollama", kept the lane "trusted", and turned a no-egress lane
into a network one. Distilled source that the allow-list withholds from every
external provider would have gone over the wire with only the secret floor
applied. No code changed; no test noticed.

The tests below are written so that reverting either half -- the host-derived
lane, or the refusal in the wire -- turns them red.
"""
from __future__ import annotations

import pytest

from daedalus.sensitivity import lane_for_host


# --------------------------------------------------------------------------- #
# the predicate                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("host", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1",
    "127.0.0.1:11434",              # no scheme -- what a bare env value looks like
    "http://[::1]:11434",
    "http://127.5.5.5:11434",       # the whole 127.0.0.0/8 block is loopback
])
def test_this_machine_is_trusted(host):
    assert lane_for_host(host) == "trusted", host


@pytest.mark.parametrize("host", ["http://localhost:11434", "localhost:11434"])
def test_a_NAME_is_never_trusted_even_when_it_means_loopback(host):
    """`localhost` is refused on purpose.

    A name is an indirection this predicate cannot see through: it can resolve
    to loopback when checked and elsewhere when connected -- the check-then-use
    shape that produced this repo's worktree CRITICALs, with egress at the end
    instead of deletion. The shipped default is numeric, so refusing names costs
    nothing real.
    """
    assert lane_for_host(host) == "untrusted"


@pytest.mark.parametrize("host", [
    "http://100.119.126.9:11434",   # the actual RTX bench in this project
    "http://10.0.0.5:11434",
    "http://192.168.1.20:11434",
    "http://bench.local:11434",
    "https://ollama.example.com",
    "http://169.254.169.254",       # cloud metadata, and very much not local
])
def test_anywhere_else_is_untrusted(host):
    assert lane_for_host(host) == "untrusted", host


@pytest.mark.parametrize("host", ["", "   ", None, "://", "http://", "!!!"])
def test_an_unreadable_host_fails_closed(host):
    # "I cannot tell where the bytes go" must never read as "they stay here".
    assert lane_for_host(host) == "untrusted"


def test_bind_all_is_not_loopback():
    # 0.0.0.0 is a bind address. As a CONNECT target it promises nothing about
    # which machine answers, so it must not buy the trusted lane.
    assert lane_for_host("http://0.0.0.0:11434") == "untrusted"


def test_the_default_host_is_trusted():
    # The control: if the default were untrusted, every test above would pass
    # while the wire was dead for its actual intended use.
    from daedalus.providers.ollama import DEFAULT_HOST

    assert lane_for_host(DEFAULT_HOST) == "trusted"


# --------------------------------------------------------------------------- #
# the wire                                                                     #
# --------------------------------------------------------------------------- #
def test_offload_resolves_its_lane_from_the_env_not_the_provider_name(monkeypatch):
    from daedalus.offload import _resolved_ollama_lane

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    assert _resolved_ollama_lane()[0] == "trusted"

    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    lane, host = _resolved_ollama_lane()
    assert lane == "untrusted"
    assert host == "http://100.119.126.9:11434"


def test_the_distilled_context_wire_refuses_a_remote_bench(monkeypatch, tmp_path):
    """The end the operator actually sees: no slice is built, and it says why."""
    from daedalus.offload import _slice_context

    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    texts, meta = _slice_context(str(tmp_path), ["a.py"], None,
                                 include_focus=True, budget=4000)
    assert texts == {}, "source was distilled for a host that is not this machine"
    assert meta["lane"] == "untrusted"
    assert meta["injected"] is False
    assert "not this machine" in meta["reason"]
    assert "100.119.126.9" in meta["reason"]


def test_the_refusal_outranks_the_budget_check(monkeypatch, tmp_path):
    # Ordering matters: if the budget check ran first, an operator with the wire
    # ENABLED and a remote host would get the egress path, and the test above
    # would still pass for the wrong reason (budget 0 -> nothing built).
    from daedalus.offload import _slice_context

    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    _, meta = _slice_context(str(tmp_path), ["a.py"], None,
                             include_focus=True, budget=0)
    assert "not this machine" in meta["reason"], (
        "with the budget at 0 the wire reported 'disabled' instead of "
        "'refused' -- the egress decision must not depend on a budget")


def test_ikarus_chat_context_follows_the_resolved_host_too(monkeypatch):
    """The SECOND live instance of the same bug, in the user-facing chat path.

    ``ikarus_os``'s LOCAL branch hardcoded ``lane="trusted"`` while
    ``_ollama``/``_ollama_stream`` resolve their endpoint from ``OLLAMA_HOST``.
    Same class as the offload wire, different door -- which is why the fix is a
    shared predicate rather than a patch at one call site.
    """
    from daedalus.orchestration.ikarus.shell import _local_lane

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    assert _local_lane() == "trusted"

    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    assert _local_lane() == "untrusted"


def test_no_local_branch_still_names_its_lane_literally():
    """Structural: the trusted lane may not be re-hardcoded next to an
    OLLAMA_MODEL lookup, which is what the LOCAL branches look like.

    A comment saying "ollama is local" is a claim; this is the control.
    """
    import re
    from pathlib import Path

    import daedalus.orchestration.ikarus.shell as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for match in re.finditer(r'OLLAMA_MODEL.*?\n(.*?)\n', source):
        following = match.group(1)
        assert 'lane="trusted"' not in following, (
            "a LOCAL (ollama) branch names lane=\"trusted\" literally again; "
            "it must derive it from the resolved host via _local_lane()")


# --------------------------------------------------------------------------- #
# the DISPATCH -- the leak the first fix did not close                          #
# --------------------------------------------------------------------------- #
def test_the_provider_itself_refuses_a_remote_endpoint(monkeypatch, tmp_path):
    """The hole an independent review found in the first version of this fix.

    Refusing the distilled slice closed ONE door. The rewrite prompt carries
    whole file bodies, the agentic tool loop returns read_file results over
    subsequent requests, and the single-shot fallback inlines with
    allow_sensitive=True -- three more doors, all downstream of the slice.
    The guard therefore lives in the PROVIDER, before any prompt is built, so it
    covers every path including ones written later.
    """
    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    from daedalus.providers.ollama import OllamaProvider

    prov = OllamaProvider()
    assert prov.egress_lane == "untrusted"

    (tmp_path / "secret.py").write_text("API_TOKEN = 'x'\n", encoding="utf-8")
    out = prov.run(objective="rewrite it", repo_root=str(tmp_path),
                   paths=["secret.py"], agent={"name": "generalist-dev"},
                   writable=True)

    assert out["ok"] is False
    assert out["refused"] == "remote_ollama_endpoint"
    assert "100.119.126.9" in out["error"]
    assert out["report"]["files_changed"] == []


def test_the_provider_does_not_refuse_a_loopback_endpoint(monkeypatch):
    # The control. Without it, a provider that refused unconditionally would
    # pass the test above while making the local bench unusable.
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    from daedalus.providers.ollama import OllamaProvider

    assert OllamaProvider().egress_lane == "trusted"
    assert OllamaProvider()._refuse_if_remote() is None


def test_the_declared_capabilities_are_not_the_egress_authority(monkeypatch):
    """`caps.local`/`caps.trusted_with_ip` are CLASS constants; the host is not.

    Anything that reads the capability block to decide egress is reading a claim
    about a provider's NAME. This pins that the two can disagree, so a future
    reader cannot mistake the static flag for the fact.
    """
    monkeypatch.setenv("OLLAMA_HOST", "http://100.119.126.9:11434")
    from daedalus.providers.ollama import OllamaProvider

    prov = OllamaProvider()
    assert prov.caps.local is True and prov.caps.trusted_with_ip is True
    assert prov.egress_lane == "untrusted", (
        "the declared capabilities and the resolved endpoint agree, so this "
        "test proves nothing -- check that OLLAMA_HOST is actually read")


def test_a_local_host_still_reaches_the_budget_path(monkeypatch, tmp_path):
    # The control for the two tests above: with a LOCAL host the wire proceeds
    # far enough to make its own decisions. Without this, a _slice_context that
    # refused everything unconditionally would pass every refusal test here.
    from daedalus.offload import _slice_context

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    _, meta = _slice_context(str(tmp_path), ["a.py"], None,
                             include_focus=True, budget=0)
    assert meta["lane"] == "trusted"
    assert "disabled" in meta["reason"]
