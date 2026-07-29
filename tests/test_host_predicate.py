"""ONE answer to "do the bytes leave this machine", pinned host by host.

``tests/test_egress_lane_by_host.py`` closed the live breach: ``lane="trusted"``
switches OFF the default-deny allow-list in ``sensitivity.slice_egress_rule``,
and it used to be chosen from the PROVIDER NAME ("ollama is local") while the
Ollama client resolves its endpoint from ``OLLAMA_HOST``. Pointing that at the
off-machine RTX bench kept the name, kept the lane, and turned a no-egress lane
into a network one.

THIS file closes the follow-on defect: the fix left FIVE implementations of the
same safety question in the tree, and they DISAGREED. Measured before
consolidation (T = local/trusted, U = untrusted):

    host                          sensitivity  vendors  session  canary  accel
    http://127.0.0.1:11434            T           T        T       T       T
    127.0.0.1:11434                   T           U        U       U       T
    http://127.0.0.2:11434            T           U        U       U       U
    http://[::1]:11434                T           U        U       U       T
    ::1                               U           T        U       U       T
    http://localhost:11434            U           T        T       T       T
    localhost                         U           T        U       U       T
    http://100.119.126.9:11434        U           U        U       U       U
    http://0.0.0.0:11434              U           U        U       U       U
    ""                                U           U        U       U       T

Three answers to one question. Nobody chose any of it: the council copies match
``^https?://([^/:]+)`` against a three-name frozenset, and that regex cannot
span a bracketed IPv6 literal (``[^/:]+`` dies on the first colon and yields the
host ``"["``), requires a scheme, and knows only one address out of 127.0.0.0/8.
The divergences are PARSING ACCIDENTS wearing the clothes of a policy.

So the predicate is consolidated onto ``sensitivity.lane_for_host`` -- the
safety core, next to the gate it switches -- and these tests pin both halves:
the shared answers, and the absence of any caller-local copy.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import daedalus.council.vendors as V
from daedalus.sensitivity import (
    ENV_TRUSTED_HOSTS,
    declared_trusted_hosts,
    is_loopback_host,
    lane_for_host,
)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _REPO_ROOT / "daedalus"


# --------------------------------------------------------------------------- #
# the table -- one expected answer per host, and the reason it is that answer  #
# --------------------------------------------------------------------------- #
#: ``(host, expected_lane, why)``. This is the whole contract; every consolidated
#: caller is asserted against THIS list rather than against a copy of it.
TABLE: tuple[tuple[str, str, str], ...] = (
    # -- loopback literals: the bytes provably never reach a wire ------------
    ("http://127.0.0.1:11434", "trusted", "the shipped default"),
    ("http://127.0.0.1", "trusted", "no port"),
    ("127.0.0.1:11434", "trusted", "no scheme -- what a bare OLLAMA_HOST looks like"),
    ("http://127.0.0.2:11434", "trusted", "127.0.0.0/8 is loopback entire"),
    ("http://127.5.5.5:11434", "trusted", "127.0.0.0/8 is loopback entire"),
    ("http://127.255.255.254:11434", "trusted", "top of the loopback block"),
    ("http://[::1]:11434", "trusted", "IPv6 loopback, bracketed per RFC 3986"),
    # -- names: refused on purpose, however loopback-ish they look -----------
    ("http://localhost:11434", "untrusted", "a name is a DNS indirection"),
    ("localhost:11434", "untrusted", "a name is a DNS indirection"),
    ("localhost", "untrusted", "a name is a DNS indirection"),
    ("http://bench.local:11434", "untrusted", "a name is a DNS indirection"),
    ("::1", "untrusted", "bare IPv6 without brackets is not parseable as a host"),
    # -- other machines -----------------------------------------------------
    ("http://100.119.126.9:11434", "untrusted", "the actual RTX bench, over a tailnet"),
    ("http://10.0.0.5:11434", "untrusted", "LAN"),
    ("http://192.168.1.20:11434", "untrusted", "LAN"),
    ("https://ollama.example.com", "untrusted", "the open internet"),
    ("http://169.254.169.254", "untrusted", "cloud metadata, emphatically not local"),
    # -- fail closed --------------------------------------------------------
    ("", "untrusted", "empty"),
    ("   ", "untrusted", "whitespace"),
    ("://", "untrusted", "malformed"),
    ("http://", "untrusted", "no host"),
    ("!!!", "untrusted", "garbage"),
    ("http://0.0.0.0:11434", "untrusted", "a bind address is not a connect promise"),
    ("0.0.0.0", "untrusted", "a bind address is not a connect promise"),
)

HOSTS = tuple(h for h, _, _ in TABLE)


@pytest.mark.parametrize("host,expected,why", TABLE, ids=[h or "<empty>" for h in HOSTS])
def test_the_shared_predicate_answers_the_whole_table(host, expected, why):
    assert lane_for_host(host) == expected, f"{host!r}: {why}"


def test_none_fails_closed():
    # Not in the table because it is not a string; the callers below never pass
    # it, but the predicate must still refuse rather than raise.
    assert lane_for_host(None) == "untrusted"


# --------------------------------------------------------------------------- #
# every consolidated caller gives the SAME answer as the predicate             #
# --------------------------------------------------------------------------- #
# These are the tests that go red if a caller grows its own copy again. They
# compare against ``lane_for_host`` rather than against a literal, so a caller
# cannot pass by hardcoding today's table -- it has to actually delegate.


@pytest.mark.parametrize("host", HOSTS, ids=[h or "<empty>" for h in HOSTS])
def test_ollama_adapter_local_flag_is_the_shared_predicate(host):
    """``OllamaAdapter.local`` labels every council record the adapter produces.

    Before consolidation it was ``_endpoint_host(host) in _LOCAL_HOSTS``, which
    called ``http://localhost:11434`` local and ``http://[::1]:11434`` remote --
    both wrong, in opposite directions.
    """
    adapter = V.OllamaAdapter(host=host, chat=lambda **kw: {"content": ""})
    assert adapter.local is (lane_for_host(host) == "trusted"), host


@pytest.mark.parametrize("host", HOSTS, ids=[h or "<empty>" for h in HOSTS])
def test_available_vendors_lane_is_the_shared_predicate(host):
    """The lane on the availability row IS the predicate's return value.

    Injected probes only: no CLI on PATH, no network, no model invoked.
    """
    rows = {
        r.vendor: r
        for r in V.available_vendors(
            which=lambda n: None,
            http_probe=lambda h, **kw: False,
            ollama_host=host,
        )
    }
    assert rows["local"].lane == lane_for_host(host), host


@pytest.mark.parametrize("host", HOSTS, ids=[h or "<empty>" for h in HOSTS])
def test_local_and_lane_can_never_disagree_about_one_host(host):
    """The invariant the three-way split destroyed.

    ``local`` (what the record CLAIMS about egress) and ``lane`` (what the gate
    DOES about egress) answered the same question from two different tables. A
    record reading ``local=True, lane="untrusted"`` -- or worse, the reverse --
    is a transcript that lies about where the bytes went.
    """
    adapter = V.OllamaAdapter(host=host, chat=lambda **kw: {"content": ""})
    row = {
        r.vendor: r
        for r in V.available_vendors(
            which=lambda n: None, http_probe=lambda h, **kw: False, ollama_host=host
        )
    }["local"]
    assert adapter.local is (row.lane == "trusted"), (
        f"{host!r}: adapter.local={adapter.local} but availability lane="
        f"{row.lane!r} -- two answers to one egress question")


def test_the_two_shipped_defaults_still_land_where_they_must():
    """The control. Without it, a predicate that answered ``untrusted`` for
    everything would pass every refusal test in this file while making the local
    bench unusable and the remote one indistinguishable from it."""
    assert lane_for_host(V.DEFAULT_LOCAL_OLLAMA_HOST) == "trusted"
    assert lane_for_host(V.DEFAULT_BENCH_OLLAMA_HOST) == "untrusted"
    assert V.OllamaAdapter(host=V.DEFAULT_LOCAL_OLLAMA_HOST,
                           chat=lambda **kw: {}).local is True
    assert V.OllamaAdapter(host=V.DEFAULT_BENCH_OLLAMA_HOST,
                           chat=lambda **kw: {}).local is False


# --------------------------------------------------------------------------- #
# the cases whose ANSWER CHANGED, named one at a time                          #
# --------------------------------------------------------------------------- #
# Consolidation is not allowed to move the egress boundary by accident. It moved
# it in both directions, and each direction is pinned here so the change is a
# thing a reviewer reads rather than a thing a diff hides.


@pytest.mark.parametrize("host", [
    "http://[::1]:11434",
    "127.0.0.1:11434",
    "http://127.0.0.2:11434",
    "http://127.5.5.5:11434",
])
def test_WIDENED_numeric_loopback_the_old_regex_could_not_parse(host):
    """WIDER than before: these were ``untrusted`` in the council, now trusted.

    This is a real widening of the egress boundary and it is argued, not
    assumed (see ``sensitivity.lane_for_host``): 127.0.0.0/8 is reserved for
    loopback entire (RFC 1122 3.2.1.3) and ``::1`` is the IPv6 loopback
    (RFC 4291 2.5.3), so no packet to any of them reaches a wire. The old
    ``untrusted`` came from ``^https?://([^/:]+)`` -- a character class that
    dies on the first colon of a bracketed IPv6 literal and requires a scheme --
    not from anyone deciding these hosts were off-machine.

    The widening admits NUMERIC LITERALS ONLY, so it does not reopen the DNS
    indirection ``localhost`` is refused for.
    """
    assert lane_for_host(host) == "trusted"
    assert V.OllamaAdapter(host=host, chat=lambda **kw: {}).local is True


@pytest.mark.parametrize("host", ["http://localhost:11434", "localhost", "::1"])
def test_NARROWED_names_the_council_used_to_call_local(host):
    """STRICTER than before: the council called these local, and no longer does.

    Narrowing needs no argument -- being stricter about egress cannot leak --
    but it is pinned because it is the half of the consolidation an operator can
    FEEL: seating Ollama on ``http://localhost:11434`` now lands on the
    untrusted lane and the allow-list applies. The remedy is to seat it on
    ``127.0.0.1``, which is already the shipped default, and which is exactly
    why refusing names cost nothing.
    """
    assert lane_for_host(host) == "untrusted"
    assert V.OllamaAdapter(host=host, chat=lambda **kw: {}).local is False


# --------------------------------------------------------------------------- #
# declared_trusted_hosts -- the operator-declared trust boundary               #
# --------------------------------------------------------------------------- #
# DAEDALUS_TRUSTED_HOSTS lets an operator assert that a specific NUMERIC
# address (typically a private-tunnel bench) is inside their trust boundary,
# without reopening the DNS indirection or the CIDR-creep the loopback rule
# was hardened against. Every property below was a DELIBERATE hardening
# carried over from that rule -- see daedalus.sensitivity.declared_trusted_hosts.


def test_unset_env_reproduces_the_old_fail_closed_default(monkeypatch):
    """No declaration at all: the tailnet bench stays untrusted, exactly the
    behaviour this module had before DAEDALUS_TRUSTED_HOSTS existed."""
    monkeypatch.delenv(ENV_TRUSTED_HOSTS, raising=False)
    assert declared_trusted_hosts() == frozenset()
    assert lane_for_host("100.119.126.9") == "untrusted"
    assert lane_for_host("http://100.119.126.9:11434") == "untrusted"


def test_empty_env_is_the_same_as_unset(monkeypatch):
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "")
    assert declared_trusted_hosts() == frozenset()
    assert lane_for_host("100.119.126.9") == "untrusted"


@pytest.mark.parametrize("host", [
    "100.119.126.9",
    "http://100.119.126.9",
    "http://100.119.126.9:11434",
    "100.119.126.9:11434",
], ids=["bare", "scheme-no-port", "scheme-and-port", "port-no-scheme"])
def test_a_declared_numeric_address_is_trusted_with_or_without_scheme_or_port(
        monkeypatch, host):
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9")
    assert declared_trusted_hosts() == frozenset({"100.119.126.9"})
    assert lane_for_host(host) == "trusted"


def test_declaring_one_address_does_not_trust_its_neighbour(monkeypatch):
    """EXACT address equality only -- no CIDR, no prefix. Declaring .9 must
    never trust .99; a trust list that grows by arithmetic is a trust list
    nobody can audit."""
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9")
    assert lane_for_host("100.119.126.99") == "untrusted"
    assert lane_for_host("100.119.126.90") == "untrusted"


def test_a_declared_hostname_is_dropped_never_resolved(monkeypatch):
    """Numeric literals only, even in the declaration itself. This is the same
    reason `localhost` is refused as a CHECKED host: a name that resolves to
    the bench when checked can resolve elsewhere when connected, and the
    predicate cannot see the difference -- so a declared name is dropped
    rather than trusted."""
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "localhost")
    assert declared_trusted_hosts() == frozenset()
    assert lane_for_host("localhost") == "untrusted"


def test_an_unparseable_entry_narrows_rather_than_widens(monkeypatch):
    """A typo must shrink the declared set to nothing, never expand it to
    match everything -- an unparseable entry is dropped, not guessed at."""
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "not a valid host!!!")
    assert declared_trusted_hosts() == frozenset()
    assert lane_for_host("100.119.126.9") == "untrusted"


def test_a_bad_entry_does_not_poison_a_good_one_in_the_same_list(monkeypatch):
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9, not a valid host!!!")
    assert declared_trusted_hosts() == frozenset({"100.119.126.9"})
    assert lane_for_host("100.119.126.9") == "trusted"


def test_multiple_declared_addresses_are_all_honoured(monkeypatch):
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9,10.0.0.5")
    assert declared_trusted_hosts() == frozenset({"100.119.126.9", "10.0.0.5"})
    assert lane_for_host("100.119.126.9") == "trusted"
    assert lane_for_host("10.0.0.5") == "trusted"
    assert lane_for_host("10.0.0.6") == "untrusted"


def test_a_scheme_and_port_on_the_declaration_itself_are_stripped(monkeypatch):
    """The declaration is normalised the same way a checked host is: a scheme
    or port left on the env value by accident must not produce an entry that
    matches nothing."""
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "http://100.119.126.9:11434")
    assert declared_trusted_hosts() == frozenset({"100.119.126.9"})
    assert lane_for_host("100.119.126.9") == "trusted"


# --------------------------------------------------------------------------- #
# is_loopback_host -- physics, not consent; the split that closed a CRITICAL   #
# --------------------------------------------------------------------------- #
# lane_for_host answers "may repository content go to this host" -- consent,
# widenable via DAEDALUS_TRUSTED_HOSTS. is_loopback_host answers "is this host
# PHYSICALLY this machine" -- never widenable; no env var reaches it. Found by
# review: web_api._resolve_bind was asking the second question but reading the
# first predicate's answer, so declaring a bench trusted for INFERENCE egress
# also handed out an unauthenticated control-plane bind (spine ledger,
# role-rewriting PUTs, model-invoking POSTs) to anything on that tailnet. The
# divergence between the two predicates on a declared address is now a
# security property, pinned here.

@pytest.mark.parametrize("host", [
    "127.0.0.1", "http://127.0.0.1", "http://127.0.0.1:11434",
    "127.0.0.1:11434", "127.0.0.2", "127.5.5.5", "127.255.255.254",
    "[::1]", "http://[::1]:11434",
])
def test_is_loopback_host_true_for_numeric_loopback_only(host):
    assert is_loopback_host(host) is True


@pytest.mark.parametrize("host", [
    "localhost", "http://localhost:11434",   # a name -- DNS indirection
    "::1",                                   # unbracketed: not host-parseable
    "100.119.126.9", "10.0.0.5", "192.168.1.20",   # other machines
    "0.0.0.0",                               # a bind address, not a promise
    "", None, "!!!", "://",                  # fails closed
])
def test_is_loopback_host_false_for_everything_else(host):
    assert is_loopback_host(host) is False


def test_is_loopback_host_stays_false_for_a_declared_trusted_host(monkeypatch):
    """THE SECURITY PROPERTY. Declaring an address trusted makes
    lane_for_host return "trusted" for it -- that is the whole point of
    DAEDALUS_TRUSTED_HOSTS. is_loopback_host must disagree with it on that
    SAME address: a private-tunnel bench does not become physically this
    machine because an operator consented to sending it inference bytes.
    This is exactly the divergence web_api._resolve_bind now depends on."""
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9")
    assert lane_for_host("100.119.126.9") == "trusted"
    assert is_loopback_host("100.119.126.9") is False


def test_is_loopback_host_ignores_the_declared_trust_list_entirely(monkeypatch):
    """No env var reaches this predicate at all. Unlike lane_for_host, which
    consults declared_trusted_hosts(), is_loopback_host must answer identically
    for a host whether or not it is declared trusted -- undeclarable is the
    whole design."""
    monkeypatch.delenv(ENV_TRUSTED_HOSTS, raising=False)
    before = is_loopback_host("100.119.126.9")
    monkeypatch.setenv(ENV_TRUSTED_HOSTS, "100.119.126.9")
    after = is_loopback_host("100.119.126.9")
    assert before is False and after is False


def test_is_loopback_host_none_fails_closed():
    assert is_loopback_host(None) is False


# --------------------------------------------------------------------------- #
# structural: no caller keeps its own copy                                     #
# --------------------------------------------------------------------------- #
#: How a private copy of the predicate looks in source. Deliberately shape-based
#: rather than name-based: the next copy will not be called ``_LOCAL_HOSTS``.
_DUPLICATE_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a named local-host table", re.compile(r"^[ \t]*_?LOCAL_HOSTS[ \t]*=", re.M)),
    ("a local-host predicate", re.compile(r"^[ \t]*def[ \t]+_?is_local_?\w*[ \t]*\(", re.M)),
    ("an inline local-host table",
     re.compile(r"""\{[^{}\n]*['"]127\.0\.0\.1['"][^{}\n]*\}""")),
)

#: The ONE module allowed to hold the table: it is the predicate's home, and the
#: gate it switches (``slice_egress_rule``) is in the same file.
_THE_HOME = "daedalus/sensitivity.py"

#: Copies that still exist and are owned by other agents in this session. Each
#: entry is a KNOWN, REPORTED divergence, not an exemption on the merits -- see
#: :func:`test_the_allowlist_does_not_rot`, which fails the moment an entry is
#: no longer needed, so this list cannot quietly outlive the problem.
_OWNED_ELSEWHERE: frozenset[str] = frozenset({
    # Same shape as the copy removed from vendors.py; decides the Ollama lane in
    # ``default_participants``. Needs: ``lane=lane_for_host(host)``.
    "daedalus/council/session.py",
    # A verbatim clone of session.py's copy, in an untracked new module -- the
    # predicted "next person adds a fourth", already realised. Needs the same
    # one-line change in ``default_lanes``.
    "daedalus/council/canary.py",
    # Not an egress lane: an inline table behind a plaintext-HTTP WARNING. Same
    # question, same drift risk, lower blast radius.
    "daedalus/accelerators.py",
})


def _duplicate_predicates() -> dict[str, list[str]]:
    """Every module under ``daedalus/`` that answers "is this host local" itself."""
    found: dict[str, list[str]] = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel == _THE_HOME:
            continue
        source = path.read_text(encoding="utf-8")
        hits = [label for label, rx in _DUPLICATE_MARKERS if rx.search(source)]
        if hits:
            found[rel] = hits
    return found


def test_no_caller_keeps_its_own_copy_of_the_host_predicate():
    """The guard that stops a sixth implementation.

    Three answers to one safety question is two too many, and the failure mode
    is not that someone argues for a different boundary -- it is that the next
    person to need the check picks whichever copy they find first, and no test
    notices that it disagrees with the gate.
    """
    offenders = _duplicate_predicates()
    unexpected = {k: v for k, v in offenders.items() if k not in _OWNED_ELSEWHERE}
    assert not unexpected, (
        "these modules answer 'is this host local' with their own table instead "
        "of daedalus.sensitivity.lane_for_host:\n  "
        + "\n  ".join(f"{k}: {', '.join(v)}" for k, v in sorted(unexpected.items()))
        + "\n\nUse lane_for_host(host) (it returns the lane string directly) or "
          "lane_for_host(host) == 'trusted' for a boolean. A second table is a "
          "second answer to the question that switches the egress allow-list.")


def test_vendors_has_no_local_host_table_left():
    """The specific copy this change removed, pinned by NAME as well as by shape.

    ``_LOCAL_HOSTS``/``_endpoint_host``/``_HOST_RE`` disagreed with the shared
    predicate on ``[::1]``, on 127.0.0.0/8 and on ``localhost``. Re-adding any
    of them must be loud.
    """
    for gone in ("_LOCAL_HOSTS", "_endpoint_host", "_HOST_RE"):
        assert not hasattr(V, gone), (
            f"council.vendors.{gone} is back; the host question has one "
            f"implementation, sensitivity.lane_for_host")
    source = Path(V.__file__).read_text(encoding="utf-8")
    assert "lane_for_host" in source, (
        "vendors.py no longer imports the shared predicate -- if the table is "
        "gone AND the import is gone, the lane is being decided some third way")


def test_the_allowlist_does_not_rot():
    """An allowlist that outlives its reason is a hole with a comment on it.

    Every entry in ``_OWNED_ELSEWHERE`` must still actually contain a duplicate.
    When the owning agent consolidates one, this test fails and tells you to
    delete the line -- so the guard widens back automatically instead of
    silently staying narrow.
    """
    offenders = _duplicate_predicates()
    stale = sorted(_OWNED_ELSEWHERE - set(offenders))
    assert not stale, (
        "these files no longer have their own host predicate, so the allowlist "
        "entry is stale and is now hiding future copies. Delete from "
        "_OWNED_ELSEWHERE in this file:\n  " + "\n  ".join(stale))


def test_the_known_divergences_are_still_divergences():
    """The measurement, kept executable rather than left in a commit message.

    Each allowlisted copy is asserted to STILL disagree with the shared
    predicate on a specific host. If one of them silently starts agreeing, this
    test says so and the entry can go; if one of them silently starts
    disagreeing somewhere NEW, the table above is the place to look.
    """
    from daedalus.council import canary, session

    for mod in (session, canary):
        # Stricter than the shared predicate: a parsing accident, not unsafe.
        assert mod._is_local_http("http://[::1]:11434") is False
        assert lane_for_host("http://[::1]:11434") == "trusted"
        # MORE PERMISSIVE than the shared predicate. This is the direction that
        # matters: these modules hand `lane="trusted"` to a DNS name, which
        # turns the tier-2 allow-list off on a host they cannot see through.
        assert mod._is_local_http("http://localhost:11434") is True
        assert lane_for_host("http://localhost:11434") == "untrusted"
