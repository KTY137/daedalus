"""The spend ceiling, attacked from both sides.

Every guard in ``daedalus/budget.py`` is pinned here by a test that was
VERIFIED RED by actually deleting the guard -- the mutation list is in
``tests/_budget_mutants.py``. A test nobody disabled is a test nobody checked;
this repo has already shipped a security-critical file where 18 of 61 guards
survived their own deletion.

Two halves, and both halves matter:

* the REFUSE half -- corrupt ledger, unreadable ceiling, unobtainable lock,
  unpriced vendor, crossed cap;
* the ALLOW half -- a cap that refuses everything passes every refusal test and
  breaks the product, so "with budget remaining, the call proceeds" is pinned
  just as hard.

NOT ONE BILLABLE CALL IS MADE HERE. The process-guard tests interpose over a
spy, never over a real ``subprocess.run``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.request
from pathlib import Path

import pytest

import daedalus.budget as B
from daedalus.budget import (
    DEFAULT_CEILING_USD,
    ENV_CEILING,
    ENV_MAX_CALLS,
    ENV_PERIOD,
    UNKNOWN_CALL_USD,
    BudgetRefused,
    BudgetUnavailable,
    Ledger,
    UnknownPrice,
    classify_argv,
    classify_url,
    price_call,
)
from daedalus.sensitivity import lane_for_host

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Every test starts with NO budget configuration and its own ledger, so a
    stray env var on the developer's box can never make a refusal test pass."""
    for var in (ENV_CEILING, ENV_MAX_CALLS, ENV_PERIOD, B.ENV_ON_UNKNOWN,
                B.ENV_LEDGER, B.ENV_SUBSCRIPTIONS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "ledger.json"))
    B.reset_default_ledger()
    yield
    B.uninstall_process_guard()
    B.reset_default_ledger()


@pytest.fixture
def led(tmp_path):
    """A ledger with a $1.00 ceiling and room for 10 calls."""
    return Ledger(tmp_path / "ledger.json", ceiling_usd=1.00, max_calls=10)


def _est(usd: float, *, calls: int = 1, vendor: str = "deepseek") -> B.Estimate:
    return B.Estimate(vendor=vendor, model="m", usd=usd, calls=calls,
                      basis="worst_case", detail="test")


# ===========================================================================
# 1. FAIL CLOSED -- an unknown balance is a refusal, never an allowance
# ===========================================================================

@pytest.mark.parametrize("payload, why", [
    ("{not json", "corrupt JSON"),
    ("", "present but empty (truncated write)"),
    ("   \n", "whitespace only"),
    ("[]", "not an object"),
    ('{"spent_usd": "0.1", "calls": 0, "open": {}}', "spend is a string"),
    ('{"spent_usd": -5, "calls": 0, "open": {}}', "negative spend"),
    ('{"spent_usd": 1e999, "calls": 0, "open": {}}', "non-finite spend"),
    ('{"spent_usd": true, "calls": 0, "open": {}}', "bool is not a spend"),
    ('{"spent_usd": 0.0, "calls": -1, "open": {}}', "negative call count"),
    ('{"spent_usd": 0.0, "calls": 1.5, "open": {}}', "fractional call count"),
    ('{"spent_usd": 0.0, "calls": 0, "open": []}', "open is not an object"),
    ('{"spent_usd": 0.0, "calls": 0, "open": {"a": 3}}', "open row is not an object"),
    ('{"spent_usd": 0.0, "calls": 0, "open": {"a": {"usd": null}}}', "open row has no price"),
])
def test_unreadable_ledger_refuses(led, payload, why):
    led.path.parent.mkdir(parents=True, exist_ok=True)
    led.path.write_text(payload, encoding="utf-8")
    with pytest.raises(BudgetUnavailable):
        led.state()
    with pytest.raises(BudgetUnavailable):
        led.reserve(_est(0.01), label=f"must refuse: {why}")


def test_a_missing_ledger_is_a_fresh_ledger_not_a_failure(led):
    """The one benign read failure: nothing spent yet is unambiguous.

    RESIDUAL, stated out loud: deleting the ledger therefore resets the period.
    That is the same class of attack as editing ``spent_usd`` to 0 and a plain
    file cannot defend against either.
    """
    assert not led.path.exists()
    assert led.state().spent_usd == 0.0


@pytest.mark.parametrize("var, value", [
    (ENV_CEILING, "abc"), (ENV_CEILING, ""), (ENV_CEILING, "-1"),
    (ENV_CEILING, "0"), (ENV_CEILING, "inf"), (ENV_CEILING, "nan"),
    (ENV_MAX_CALLS, "lots"), (ENV_MAX_CALLS, "0"), (ENV_MAX_CALLS, "-4"),
    (ENV_PERIOD, "forever"), (ENV_PERIOD, "hour"),
])
def test_an_unreadable_ceiling_refuses(tmp_path, monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    unconfigured = Ledger(tmp_path / "ledger.json")
    if value == "" and var == ENV_CEILING:
        # An EMPTY var is "unset", which is the default-ceiling case below.
        assert unconfigured.ceiling_usd() == DEFAULT_CEILING_USD
        return
    with pytest.raises(BudgetUnavailable):
        unconfigured.reserve(_est(0.01), label="unreadable config")


def test_no_configuration_means_the_default_cap_not_infinity(tmp_path):
    """Absence of configuration is not absence of a cap."""
    plain = Ledger(tmp_path / "ledger.json")
    assert plain.ceiling_usd() == DEFAULT_CEILING_USD
    assert plain.max_calls() == B.DEFAULT_MAX_CALLS
    with pytest.raises(BudgetRefused):
        plain.reserve(_est(DEFAULT_CEILING_USD + 0.01), label="over the default")


def test_a_lock_we_cannot_take_refuses(led, monkeypatch):
    """``_RoomLock`` degrades to a no-op when it cannot lock. For money that is
    inverted: unserialised spend is exactly the double-spend this guards."""
    def never(self):
        raise OSError("held by another agent")

    monkeypatch.setattr(B._BudgetLock, "_acquire", never)
    monkeypatch.setattr(B, "LOCK_TIMEOUT_S", 0.0)
    led.lock_timeout_s = 0.0
    with pytest.raises(BudgetUnavailable) as ei:
        led.reserve(_est(0.01), label="unserialised")
    assert "lock" in str(ei.value).lower()


def test_an_unwritable_ledger_refuses(led, monkeypatch):
    def boom(self, data):
        raise BudgetUnavailable("cannot write budget ledger (simulated)")

    monkeypatch.setattr(Ledger, "_store", boom)
    with pytest.raises(BudgetUnavailable):
        led.reserve(_est(0.01), label="cannot record")


# ===========================================================================
# 2. THE CHECK HAPPENS BEFORE THE CALL
# ===========================================================================

def test_reserve_is_on_disk_before_it_returns(led):
    res = led.reserve(_est(0.40), label="pre-flight")
    # A DIFFERENT Ledger object, reading the file cold: the money is committed
    # before the caller has had a chance to make the call.
    cold = Ledger(led.path, ceiling_usd=1.00, max_calls=10)
    assert cold.state().reserved_usd == pytest.approx(0.40)
    assert cold.state().spent_usd == 0.0
    res.settle()
    assert cold.state().spent_usd == pytest.approx(0.40)
    assert cold.state().reserved_usd == 0.0


def test_the_call_itself_sees_the_money_already_committed(led):
    """The discriminator against a 'cap' that only reads the receipt: the fake
    vendor call inspects the ledger from inside, and the spend is already there."""
    seen = {}

    def fake_vendor_call():
        seen["reserved"] = Ledger(led.path, ceiling_usd=1.00).state().reserved_usd
        return "ok"

    with B.guard("deepseek", "m", label="mid-flight", led=led):
        fake_vendor_call()
    assert seen["reserved"] > 0.0


def test_a_second_caller_cannot_spend_what_the_first_reserved(led):
    """Reserved money is committed money. Without this, N callers each see the
    same 'remaining' and each spend it."""
    led.reserve(_est(0.60), label="first, still in flight")
    with pytest.raises(BudgetRefused):
        led.reserve(_est(0.60), label="second")


def test_guard_settles_on_exception_it_does_not_release(led):
    """A timeout after the tokens were generated looks exactly like a connection
    refused. Over-count by one; never under-count without bound."""
    with pytest.raises(RuntimeError):
        with B.guard("deepseek", "m", label="exploded", led=led):
            raise RuntimeError("vendor died mid-call")
    st = led.state()
    assert st.spent_usd > 0.0
    assert st.reserved_usd == 0.0


def test_release_is_the_one_fail_open_lever_and_demands_a_reason(led):
    res = led.reserve(_est(0.30), label="never happened")
    with pytest.raises(ValueError):
        res.release("")
    res.release("argv rejected before spawn")
    st = led.state()
    assert st.spent_usd == 0.0 and st.reserved_usd == 0.0 and st.calls == 0
    entries = json.loads(led.path.read_text(encoding="utf-8"))["entries"]
    assert any(e["kind"] == "release" and e["reason"] for e in entries)


# ===========================================================================
# 3. REFUSAL IS LOUD AND NAMED
# ===========================================================================

def test_refusal_names_ceiling_spend_and_what_was_refused(led):
    led.reserve(_est(0.90), label="already in flight").settle()
    with pytest.raises(BudgetRefused) as ei:
        led.reserve(_est(0.50, vendor="anthropic_cli"), label="canary probe 7/16")
    msg = str(ei.value)
    assert "canary probe 7/16" in msg          # WHAT was refused
    assert "1.0000" in msg                     # the ceiling
    assert "0.9000" in msg                     # what is spent
    assert "0.5000" in msg                     # what was asked for
    assert "anthropic_cli" in msg              # who wanted it
    assert ENV_CEILING in msg                  # how a human unblocks it
    d = ei.value.as_dict()
    assert d["ceiling_usd"] == 1.0 and d["spent_usd"] == pytest.approx(0.90)
    assert d["refused"] == "canary probe 7/16"


def test_the_call_count_cap_is_a_separate_named_axis(tmp_path):
    """Price is the thing we are least sure of; call count is the thing we are
    most sure of. The canary's default fan-out is 16."""
    small = Ledger(tmp_path / "ledger.json", ceiling_usd=1000.0, max_calls=3)
    for i in range(3):
        small.reserve(_est(0.001), label=f"probe {i}").settle()
    with pytest.raises(BudgetRefused) as ei:
        small.reserve(_est(0.001), label="probe 4")
    assert "call-count" in str(ei.value)
    assert ENV_MAX_CALLS in str(ei.value)


def test_a_single_call_larger_than_the_whole_ceiling_is_refused(led):
    with pytest.raises(BudgetRefused):
        led.reserve(_est(1.01), label="one enormous session")


# ===========================================================================
# 4. CONCURRENCY -- two callers must not both spend the same dollar
# ===========================================================================

_RACER = textwrap.dedent(
    """
    import json, os, sys
    sys.path.insert(0, sys.argv[1])
    from daedalus.budget import Ledger, Estimate, BudgetError
    led = Ledger(sys.argv[2], ceiling_usd=1.0, max_calls=100)
    est = Estimate("deepseek", "m", 0.25, 1, "worst_case", "race")
    try:
        led.reserve(est, label="racer " + sys.argv[3]).settle()
        print("OK")
    except BudgetError as exc:
        print("REFUSED")
    """
)


def test_cross_process_race_never_oversubscribes_the_ceiling(tmp_path):
    """Eight processes, a $1.00 ceiling, $0.25 each: exactly four may win.

    This is the real case here -- the writers are separate PROCESSES (CLI, GUI
    server, hooks, sixteen agents), so a ``threading.Lock`` would never have
    applied to it.
    """
    script = tmp_path / "racer.py"
    script.write_text(_RACER, encoding="utf-8")
    ledger_path = tmp_path / "race.json"
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(ROOT), str(ledger_path), str(i)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(8)
    ]
    outs = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        assert p.returncode == 0, f"racer crashed: {err}"
        outs.append(out.strip())

    wins = outs.count("OK")
    assert wins == 4, f"expected exactly 4 winners, got {wins}: {outs}"
    final = Ledger(ledger_path, ceiling_usd=1.0, max_calls=100).state()
    assert final.committed_usd <= 1.0 + 1e-9
    assert final.spent_usd == pytest.approx(1.0)


def test_the_lock_is_actually_exclusive(tmp_path):
    """If this lock does not exclude, the race test above passes by luck."""
    lock_path = tmp_path / "x.lock"
    with B._BudgetLock(lock_path, timeout_s=0.0):
        with pytest.raises(BudgetUnavailable):
            with B._BudgetLock(lock_path, timeout_s=0.0):
                pytest.fail("two holders of the same budget lock")
    # ...and it is released afterwards, or the first refusal jams the harness.
    with B._BudgetLock(lock_path, timeout_s=0.0):
        pass


# ===========================================================================
# 5. AN UNKNOWN PRICE IS NOT A FREE PRICE
# ===========================================================================

@pytest.mark.parametrize("vendor", ["", None, "mystery_llm", "claude-next",
                                    "some_new_vendor_we_added_tonight"])
def test_an_unpriced_vendor_costs_the_worst_case_never_zero(vendor):
    est = price_call(vendor)
    assert est.usd == pytest.approx(UNKNOWN_CALL_USD)
    assert est.basis == "unknown"
    assert est.usd > 0


def test_the_unknown_rate_exceeds_the_most_expensive_measured_call():
    """MEASURED 2026-07-28: one A/B arm through `claude -p` cost $1.43-$1.85.
    An unknown call must never be priced under a known one."""
    assert UNKNOWN_CALL_USD > 1.85
    assert UNKNOWN_CALL_USD >= max(p.per_call_worst_usd for p in B._PRICES.values())


def test_strict_mode_refuses_an_unknown_price_outright(monkeypatch):
    monkeypatch.setenv(B.ENV_ON_UNKNOWN, "refuse")
    with pytest.raises(UnknownPrice):
        price_call("mystery_llm")
    # ...and the refusal reaches the ledger as a refusal, not as a free call.
    with pytest.raises(UnknownPrice):
        B.reserve("mystery_llm", label="strict")


@pytest.mark.parametrize("host, free", [
    ("http://127.0.0.1:11434", True),
    ("http://127.0.0.2:11434", True),
    ("http://[::1]:11434", True),
    ("http://100.119.126.9:11434", False),      # the tailnet bench: someone's GPU
    ("http://localhost:11434", False),          # a name is a DNS indirection
    ("", False),
])
def test_local_is_free_only_where_the_shared_predicate_says_this_machine(host, free):
    est = price_call("ollama", "qwen2.5-coder:14b", host=host)
    if free:
        assert est.usd == 0.0 and est.basis == "free_local"
    else:
        assert est.usd > 0.0, f"{host} priced as free"


def test_a_local_vendor_with_no_host_is_not_provably_local():
    """The OLLAMA_HOST bug in one line: the provider NAME stayed 'ollama' while
    the bytes started going to a machine on the tailnet."""
    est = price_call("local")
    assert est.usd > 0.0
    assert est.basis in ("worst_case", "unknown")


def test_settling_with_an_unknown_actual_charges_the_estimate(led):
    res = led.reserve(_est(0.40), label="no usage reported")
    res.settle(None)
    assert led.state().spent_usd == pytest.approx(0.40)


def test_an_overrun_is_recorded_not_clamped(led):
    res = led.reserve(_est(0.10), label="cheap guess")
    res.settle(0.85)
    assert led.state().spent_usd == pytest.approx(0.85)
    with pytest.raises(BudgetRefused):
        led.reserve(_est(0.20), label="after the overrun")


def test_a_token_estimate_never_prices_a_real_call_at_zero():
    est = price_call("deepseek", "v4", input_tokens=0, output_tokens=0)
    assert est.usd > 0.0


# ===========================================================================
# 6. THE ALLOW SIDE -- a cap that refuses everything is a broken product
# ===========================================================================

def test_with_budget_remaining_the_call_proceeds(led):
    ran = []
    with B.guard("deepseek", "m", label="ordinary work", led=led) as res:
        ran.append(res.usd)
    assert ran and ran[0] > 0
    st = led.state()
    assert st.spent_usd > 0 and st.calls == 1 and st.remaining_usd > 0


def test_many_small_calls_all_proceed_under_the_ceiling(led):
    for i in range(9):
        with B.guard("deepseek", "m", label=f"call {i}", led=led):
            pass
    st = led.state()
    assert st.calls == 9
    assert st.spent_usd == pytest.approx(0.45)     # deepseek flat bound $0.05
    assert st.remaining_usd > 0


def test_a_free_local_call_costs_nothing_and_stays_allowed(led):
    """The call cap bounds BILLABLE fan-out. Charging the local lane against it
    would price local work out of exactly the loop the cap protects."""
    est = price_call("ollama", "qwen", host="http://127.0.0.1:11434")
    assert led.max_calls() == 10
    for i in range(50):
        led.reserve(est, label=f"local {i}").settle()
    assert led.state().spent_usd == 0.0
    assert led.state().calls == 0
    # ...and a billable call is still allowed afterwards.
    led.reserve(_est(0.10), label="paid work after 50 local calls").settle()


def test_a_zero_price_that_is_not_certified_local_still_counts(led):
    """Only ``free_local`` -- which the shared host predicate certifies -- gets
    the free pass. A zero from a mispriced vendor must not buy an escape."""
    zero_but_unproven = B.Estimate("mystery", "m", 0.0, 1, "worst_case", "")
    for i in range(10):
        led.reserve(zero_but_unproven, label=f"suspicious {i}").settle()
    assert led.state().calls == 10
    with pytest.raises(BudgetRefused) as ei:
        led.reserve(zero_but_unproven, label="one too many")
    assert "call-count" in str(ei.value)


def test_the_period_rolls_over_so_the_cap_does_not_become_permanent(tmp_path):
    clock = {"t": 0.0}
    day = Ledger(tmp_path / "l.json", ceiling_usd=1.0, max_calls=100,
                 period="day", now=lambda: clock["t"])
    day.reserve(_est(0.90), label="monday").settle()
    with pytest.raises(BudgetRefused):
        day.reserve(_est(0.50), label="monday again")
    clock["t"] += 60 * 60 * 48                      # two days later
    day.reserve(_est(0.50), label="wednesday").settle()
    assert day.state().spent_usd == pytest.approx(0.50)


def test_a_total_period_never_rolls_over(tmp_path):
    clock = {"t": 0.0}
    tot = Ledger(tmp_path / "l.json", ceiling_usd=1.0, max_calls=100,
                 period="total", now=lambda: clock["t"])
    tot.reserve(_est(0.90), label="ever").settle()
    clock["t"] += 60 * 60 * 24 * 365
    with pytest.raises(BudgetRefused):
        tot.reserve(_est(0.50), label="a year later")


def test_money_in_flight_survives_the_rollover(tmp_path):
    clock = {"t": 0.0}
    day = Ledger(tmp_path / "l.json", ceiling_usd=1.0, max_calls=100,
                 period="day", now=lambda: clock["t"])
    res = day.reserve(_est(0.60), label="long session")
    clock["t"] += 60 * 60 * 48
    assert day.state().reserved_usd == pytest.approx(0.60)
    res.settle()
    assert day.state().spent_usd == pytest.approx(0.60)


# ===========================================================================
# 7. CLASSIFICATION -- what the interposer bills, and what it must not
# ===========================================================================

@pytest.mark.parametrize("argv, vendor", [
    (["claude", "-p"], "anthropic_cli"),
    (["codex", "exec"], "openai_cli"),
    (["C:\\bin\\claude.exe", "-p"], "anthropic_cli"),
    (["/usr/local/bin/codex", "exec"], "openai_cli"),
    (["ssh", "bench", "agy", "-p"], "google_agy"),
    (["ssh", "bench", "claude -p --model opus"], "anthropic_cli"),
    (["bash", "-c", "codex exec < /tmp/p"], "openai_cli"),
    ("claude -p", "anthropic_cli"),
    (["npx", "claude", "-p"], "anthropic_cli"),
])
def test_a_paid_binary_is_recognised_however_it_is_reached(argv, vendor):
    assert classify_argv(argv) == vendor


@pytest.mark.parametrize("argv", [
    ["git", "status", "--porcelain"],
    ["git", "commit", "-m", "fix the claude bridge"],
    ["python", "-m", "pytest"],
    ["node", "--test"],
    ["nvidia-smi", "--query-gpu=name"],
    ["gh", "pr", "comment"],
    [], None, 17,
])
def test_free_work_is_not_billed(argv):
    assert classify_argv(argv) is None


@pytest.mark.parametrize("url, vendor", [
    ("https://api.deepseek.com/v1/chat/completions", "deepseek"),
    ("https://api.anthropic.com/v1/messages", "anthropic_api"),
    ("https://api.openai.com/v1/responses", "openai_api"),
    ("http://100.119.126.9:11434/api/chat", "remote_inference"),
    ("http://100.119.126.9:11434/api/embed", "remote_inference"),
])
def test_a_paid_endpoint_is_recognised(url, vendor):
    assert classify_url(url)[0] == vendor


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434/api/chat",          # this machine: no bill
    "http://127.0.0.1:11434/api/tags",
    "http://100.119.126.9:11434/api/tags",      # remote PROBE: no tokens, no bill
    "http://100.119.126.9:11434/api/version",
    "https://example.com/index.html",
    "", None,
])
def test_free_requests_are_not_billed(url):
    assert classify_url(url)[0] is None


def test_a_urllib_Request_object_is_classified_like_its_url():
    req = urllib.request.Request("https://api.deepseek.com/v1/chat/completions",
                                 data=b"{}")
    assert classify_url(req)[0] == "deepseek"


# ===========================================================================
# 8. THE INTERPOSER -- the chokepoint this repo does not otherwise have
# ===========================================================================

def _spy(monkeypatch, name="run"):
    calls = []

    def fake(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("args"))
        return "spawned"

    monkeypatch.setattr(subprocess, name, fake)
    return calls


def test_the_interposer_refuses_BEFORE_the_binary_is_spawned(monkeypatch, tmp_path):
    """The discriminator: if the check ran AFTER, the spy would record a call."""
    monkeypatch.setenv(ENV_CEILING, "0.01")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    calls = _spy(monkeypatch)
    B.install_process_guard()
    with pytest.raises(BudgetRefused) as ei:
        subprocess.run(["claude", "-p", "build the whole feature"])
    assert calls == [], "the vendor was spawned despite a refusal"
    assert "claude" in str(ei.value)


def test_the_interposer_lets_a_funded_call_through_exactly_once(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CEILING, "50")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    calls = _spy(monkeypatch)
    B.install_process_guard()
    assert subprocess.run(["claude", "-p", "small job"]) == "spawned"
    assert len(calls) == 1
    st = B.ledger().state()
    assert st.calls == 1                                   # NOT 2: run->Popen
    assert st.spent_usd == pytest.approx(B._PRICES["anthropic_cli"].per_call_worst_usd)


def test_the_interposer_does_not_touch_free_work(monkeypatch, tmp_path):
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    calls = _spy(monkeypatch)
    B.install_process_guard()
    subprocess.run(["git", "status"])
    assert len(calls) == 1
    assert B.ledger().state().calls == 0
    assert not (tmp_path / "l.json").exists()      # free work writes no ledger


def test_the_interposer_stops_the_canary_fanout_dead(monkeypatch, tmp_path):
    """4 lanes x 4 probes = 16 billable calls from one invocation. With a cap,
    the run stops at the cap instead of at the card."""
    monkeypatch.setenv(ENV_CEILING, "10")            # ~3 claude sessions
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    calls = _spy(monkeypatch)
    B.install_process_guard()
    refused = 0
    for i in range(16):
        try:
            subprocess.run(["claude", "-p", f"probe {i}"])
        except BudgetRefused:
            refused += 1
    assert refused == 13 and len(calls) == 3
    assert B.ledger().state().spent_usd <= 10.0


def test_an_explicit_reservation_is_not_double_charged_by_the_interposer(
        monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CEILING, "50")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    _spy(monkeypatch)
    B.install_process_guard()
    with B.guard("anthropic_cli", label="explicit site"):
        subprocess.run(["claude", "-p", "job"])
    assert B.ledger().state().calls == 1


def test_urlopen_is_interposed_too(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CEILING, "0.001")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    hits = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: hits.append(a) or "body")
    B.install_process_guard()
    with pytest.raises(BudgetRefused):
        urllib.request.urlopen("https://api.deepseek.com/v1/chat/completions")
    assert hits == []
    assert urllib.request.urlopen("http://127.0.0.1:11434/api/chat") == "body"


def test_install_is_idempotent_and_uninstall_restores(monkeypatch):
    original = subprocess.run
    B.install_process_guard()
    once = subprocess.run
    B.install_process_guard()
    assert subprocess.run is once, "double-wrapping would double-charge"
    B.uninstall_process_guard()
    assert subprocess.run is original


# ===========================================================================
# 9. COVERAGE -- no billable site may exist that this module has never heard of
# ===========================================================================

# Wide on purpose. The interposer can only wrap ``subprocess.run``/``Popen`` and
# ``urllib.request.urlopen``; a site reaching a vendor through ``requests``,
# ``httpx``, ``http.client``, ``os.system`` or a pre-bound ``from subprocess
# import run`` would slip past BOTH the interposer and a narrower detector. None
# exist today -- this regex is what makes the next one visible.
_SPAWN = re.compile(
    r"subprocess\.(run|Popen|call|check_call|check_output)"
    r"|from subprocess import"
    r"|urlopen\(|os\.system\(|os\.spawn"
    r"|requests\.(post|get|request)|httpx\.|aiohttp\.|http\.client")
_VENDOR = re.compile(r"""["'](claude|codex|agy)["']|_exe\(["'](claude|codex)["']\)"""
                     r"""|api\.(anthropic|openai|deepseek)\.com""")

# Files that match the crude scan but do NOT spend, each with the reason.
_NOT_BILLABLE = {
    "daedalus/budget.py": "this module; it names the vendors in order to price them",
    "daedalus/doctor.py": "`codex --version` / `login status`: no tokens generated",
    "daedalus/runtime_registry.py": "`<binary> --version` probe only",
    "daedalus/claude_detect.py": "detects the CLI, never invokes it",
    "daedalus/accelerators.py": "nvidia-smi and a local /api/tags probe",
    "daedalus/core.py": "dispatches to the sites below; spawns nothing itself",
    "daedalus/providers/claude_cli.py": "delegates to claude_bridge.ask_claude",
    "runs/council/room_server.py": "delegates to room.ask_*; its own urlopen is "
                                   "a status probe (_get_json)",
    "daedalus/health.py": "git, a local /api/tags probe, and shutil.which() "
                          "presence checks; invokes no vendor",
}


def _repo_py_files():
    for base in ("daedalus", "runs"):
        for p in (ROOT / base).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            yield p


# The detector's LOGIC lives in these three pure functions, not inline in a
# test. Inline, every assertion has the form "assert this set is empty" -- which
# is vacuously true on a clean tree, so deleting the assertion changes nothing
# and the test passes forever while the detector is dead. Measured: three such
# assertions survived their own deletion before this refactor. As functions they
# can be fed a KNOWN-BAD input and required to fire.

def scan(root, paths) -> set[str]:
    """Repo-relative paths that both spawn something and name a vendor."""
    out = set()
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        if _SPAWN.search(text) and _VENDOR.search(text):
            out.add(Path(path).relative_to(root).as_posix())
    return out


def surprises(found: set[str], known: set[str]) -> list[str]:
    """Spend sites nobody has declared. The drift half."""
    return sorted(found - known)


def blind_spots(found: set[str], sites) -> list[str]:
    """Declared sites the scan can no longer see. The non-vacuity half."""
    should = {s["file"] for s in sites if s.get("static_visible", True)}
    return sorted(should - found)


def explicit_sites(sites) -> list[str]:
    """Sites that claim to reserve for themselves."""
    return sorted(s["file"] + "::" + s["func"] for s in sites if s["explicit"])


def invisible_sites(sites) -> list[str]:
    """Sites no text scan can ever see -- runtime interposition only."""
    return sorted(s["file"] + "::" + s["func"] for s in sites
                  if not s.get("static_visible", True))


def stale_entries(sites, root) -> list[str]:
    """Register rows whose file or function has moved."""
    out = []
    for site in sites:
        path = Path(root) / site["file"]
        if not path.exists():
            out.append(f"{site['file']} (gone)")
            continue
        leaf = site["func"].split(".")[-1]
        if f"def {leaf}" not in path.read_text(encoding="utf-8", errors="replace"):
            out.append(f"{site['file']}::{site['func']} (renamed?)")
    return out


def test_every_vendor_spawn_in_the_tree_is_a_site_we_have_heard_of():
    """DRIFT DETECTOR. Goes red the moment someone adds a new paid call site --
    the failure mode that produced this hole in the first place. It found two
    (runs/council/summarize.py) the first time it ran, and a third
    (daedalus/health.py) an hour later."""
    known = {s["file"] for s in B.BILLABLE_SITES} | set(_NOT_BILLABLE)
    found = scan(ROOT, _repo_py_files())
    assert surprises(found, known) == [], (
        f"unregistered vendor-spawn site(s): {surprises(found, known)}. If it "
        "spends, add it to daedalus.budget.BILLABLE_SITES and guard it; if it "
        "does not, add it to _NOT_BILLABLE above WITH THE REASON.")
    assert blind_spots(found, B.BILLABLE_SITES) == [], (
        "the drift detector no longer sees known spend sites "
        f"{blind_spots(found, B.BILLABLE_SITES)} -- the regexes have rotted, so "
        "it would not see a new one either.")


def test_the_surprise_check_actually_fires_on_a_planted_site(tmp_path):
    """Self-test. A clean tree cannot distinguish a working detector from a
    deleted one, so plant a spend site and require it to be reported."""
    planted = tmp_path / "sneaky_vendor_call.py"
    planted.write_text(
        'import subprocess\n'
        'subprocess.run(["claude", "-p", "spend all the money"])\n',
        encoding="utf-8")
    found = scan(tmp_path, [planted])
    assert found == {"sneaky_vendor_call.py"}
    assert surprises(found, known=set()) == ["sneaky_vendor_call.py"]
    assert surprises(found, known={"sneaky_vendor_call.py"}) == []


def test_the_surprise_check_does_not_fire_on_innocent_code(tmp_path):
    """...and a detector that fires on everything gets its allowlist widened
    until it fires on nothing."""
    innocent = tmp_path / "ordinary.py"
    innocent.write_text(
        'import subprocess\n'
        'subprocess.run(["git", "status"])   # mentions no vendor\n',
        encoding="utf-8")
    assert scan(tmp_path, [innocent]) == set()


def test_the_non_vacuity_check_actually_fires_when_the_regex_dies():
    """A dead regex finds nothing, reports no surprises, and looks green."""
    assert blind_spots(set(), B.BILLABLE_SITES), (
        "with an empty scan result the non-vacuity check must report every "
        "statically-visible site as a blind spot")
    live = {s["file"] for s in B.BILLABLE_SITES}
    assert blind_spots(live, B.BILLABLE_SITES) == []


def test_the_register_bookkeeping_actually_reads_the_register():
    """Self-test for the two pinned expectations below. Both are of the form
    'assert X == <literal>', which a mutation can satisfy by replacing the
    computation with the literal -- measured: both survived their own deletion
    until these fed them a synthetic register."""
    synthetic = [
        {"file": "a.py", "func": "f", "explicit": True},
        {"file": "b.py", "func": "g", "explicit": False},
        {"file": "c.py", "func": "h", "explicit": False, "static_visible": False},
    ]
    assert explicit_sites(synthetic) == ["a.py::f"]
    assert invisible_sites(synthetic) == ["c.py::h"]
    assert explicit_sites([]) == [] and invisible_sites([]) == []


def test_the_staleness_check_actually_fires_on_a_moved_site(tmp_path):
    real = tmp_path / "mod.py"
    real.write_text("def ask_claude():\n    pass\n", encoding="utf-8")
    ok = [{"file": "mod.py", "func": "ask_claude"}]
    renamed = [{"file": "mod.py", "func": "ask_claude_v2"}]
    gone = [{"file": "vanished.py", "func": "ask_claude"}]
    assert stale_entries(ok, tmp_path) == []
    assert stale_entries(renamed, tmp_path) == ["mod.py::ask_claude_v2 (renamed?)"]
    assert stale_entries(gone, tmp_path) == ["vanished.py (gone)"]


@pytest.mark.parametrize("line", [
    'proc = subprocess.run([exe, "-p"])',
    'from subprocess import run',
    'subprocess.check_output(["codex", "exec"])',
    'os.system("claude -p")',
    'requests.post("https://api.anthropic.com/v1/messages")',
    'httpx.post(url)',
    'conn = http.client.HTTPSConnection("api.openai.com")',
    'urlopen(req)',
])
def test_the_drift_detector_sees_every_way_out_of_this_process(line):
    """The detector must be WIDER than the interposer, or the next escape route
    is invisible: the interposer can only wrap subprocess and urlopen."""
    assert _SPAWN.search(line), f"drift detector is blind to: {line}"


def test_the_register_still_matches_the_code_it_describes():
    """A register that has rotted is worse than none: it reads as coverage."""
    stale = stale_entries(B.BILLABLE_SITES, ROOT)
    assert not stale, f"BILLABLE_SITES is stale: {stale}"


def test_the_register_is_honest_about_what_is_not_yet_wired():
    """No empty green. Every site is currently covered ONLY by the interposer;
    when a site starts reserving for itself, flip its flag here and in the
    register, so 'guarded' never drifts into wishful thinking."""
    explicit = explicit_sites(B.BILLABLE_SITES)
    assert explicit == [], (
        "a site now claims an explicit reservation; verify it and update this "
        f"expectation: {explicit}")
    assert len(B.BILLABLE_SITES) >= 17
    # The statically-invisible sites are the ones a text scan can NEVER cover,
    # so they must stay named and few. All are covered at runtime only.
    invisible = invisible_sites(B.BILLABLE_SITES)
    assert invisible == [
        "daedalus/council/vendors.py::AntigravityAdapter._dispatch",
        "daedalus/council/vendors.py::OllamaAdapter._dispatch",
        "daedalus/council/vendors.py::_CliAdapter._dispatch",
        "daedalus/providers/_openai_compat.py::chat_completion",
    ], f"the set of scan-invisible spend sites changed: {invisible}"


# ===========================================================================
# 10. THE PROVIDER-SIDE ADAPTER
# ===========================================================================

def test_a_refused_provider_call_returns_a_VALID_blocked_report(monkeypatch, tmp_path):
    from daedalus.providers._report import reserve_or_report
    from daedalus.schemas import validate_report

    monkeypatch.setenv(ENV_CEILING, "0.001")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    res, envelope = reserve_or_report(
        vendor="deepseek", model="v4", label="review daedalus/budget.py",
        provider="deepseek", persona="Xenon", agent="minos")
    assert res is None and envelope is not None
    report = envelope["report"]
    assert validate_report(report) == []
    assert report["status"] == "blocked"
    assert report["files_changed"] == [] and report["tests_run"] == []
    assert "ceiling" in report["summary"].lower()
    assert report["handoff"]["budget"]["refused"] == "review daedalus/budget.py"


def test_an_unreadable_ledger_also_reaches_the_provider_as_a_blocked_report(
        monkeypatch, tmp_path):
    from daedalus.providers._report import reserve_or_report
    from daedalus.schemas import validate_report

    bad = tmp_path / "l.json"
    bad.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setenv(B.ENV_LEDGER, str(bad))
    B.reset_default_ledger()
    res, envelope = reserve_or_report(
        vendor="deepseek", model="v4", label="anything",
        provider="deepseek", persona="Xenon", agent="minos")
    assert res is None
    assert validate_report(envelope["report"]) == []
    assert envelope["report"]["status"] == "blocked"


def test_a_funded_provider_call_gets_a_reservation_and_no_report(monkeypatch, tmp_path):
    from daedalus.providers._report import reserve_or_report

    monkeypatch.setenv(ENV_CEILING, "50")
    monkeypatch.setenv(B.ENV_LEDGER, str(tmp_path / "l.json"))
    B.reset_default_ledger()
    res, envelope = reserve_or_report(
        vendor="deepseek", model="v4", label="ordinary review",
        provider="deepseek", persona="Xenon", agent="minos", calls=2)
    assert envelope is None and res is not None
    assert res.estimate.calls == 2
    res.settle()
    assert B.ledger().state().calls == 2


def test_the_deepseek_retry_is_priced_as_two_calls():
    """``DeepSeekProvider.run`` re-asks once for valid JSON. A reservation for
    one call would under-count every retry."""
    one = price_call("deepseek", "v4", calls=1).usd
    two = price_call("deepseek", "v4", calls=2).usd
    assert two == pytest.approx(2 * one)


# ===========================================================================
# 11. THE SUBSCRIPTION AXIS -- $0.00 is not the same as unmetered
# ===========================================================================
# A declared subscription vendor (DAEDALUS_SUBSCRIPTION_VENDORS) prices at
# $0.00 on the DOLLAR axis but still consumes a call on the RATE axis -- the
# real constraint on a flat-rate plan. This is a SEPARATE kind of free from
# FREE_VENDORS/free_local: it is free of money, not of egress, and it is read
# only by price_call/reserve, never by lane_for_host or the egress fence.

def test_a_declared_subscription_vendor_prices_at_zero_with_subscription_basis(monkeypatch):
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, "anthropic_cli")
    est = price_call("anthropic_cli", "opus")
    assert est.usd == 0.0
    assert est.basis == "subscription"


def test_a_subscription_call_still_consumes_one_call_against_the_cap(tmp_path, monkeypatch):
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, "anthropic_cli")
    small = Ledger(tmp_path / "ledger.json", ceiling_usd=1000.0, max_calls=3)
    for i in range(3):
        small.reserve(price_call("anthropic_cli", "opus"), label=f"sub {i}").settle()
    assert small.state().calls == 3
    assert small.state().spent_usd == 0.0
    with pytest.raises(BudgetRefused) as ei:
        small.reserve(price_call("anthropic_cli", "opus"), label="one too many")
    assert "call-count" in str(ei.value)


def test_an_undeclared_vendor_is_unchanged_at_its_worst_case_price(monkeypatch):
    monkeypatch.delenv(B.ENV_SUBSCRIPTIONS, raising=False)
    est = price_call("anthropic_cli", "opus")
    assert est.basis == "worst_case"
    assert est.usd == pytest.approx(B._PRICES["anthropic_cli"].per_call_worst_usd)


def test_a_typo_in_the_declaration_is_silently_ignored_and_full_price_stands(monkeypatch):
    """A typo must not widen the free set: an unrecognised name is dropped, so
    the vendor it was meant to name keeps paying worst-case price."""
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, "anthropic_clii")     # typo
    assert B.subscription_vendors() == frozenset()
    est = price_call("anthropic_cli", "opus")
    assert est.basis == "worst_case"
    assert est.usd == pytest.approx(B._PRICES["anthropic_cli"].per_call_worst_usd)


def test_declaring_other_vendors_does_not_free_an_undeclared_one(monkeypatch):
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, "openai_cli,google_agy")
    est = price_call("anthropic_cli", "opus")
    assert est.basis == "worst_case"
    assert est.usd > 0.0


def test_zero_cost_subscription_call_is_not_refused_by_an_exhausted_ceiling(led, monkeypatch):
    """THE REGRESSION THAT MATTERS. The dollar guard changed from
    ``committed + estimate > ceiling`` to ``estimate > 0 and committed +
    estimate > ceiling``: a call that adds nothing to the bill cannot cross a
    dollar ceiling, so a subscription call must sail through even when the
    ceiling is already fully committed."""
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, "anthropic_cli")
    led.reserve(_est(1.00), label="fill the ceiling").settle()
    assert led.state().remaining_usd == pytest.approx(0.0)
    sub_est = price_call("anthropic_cli", "opus")
    assert sub_est.usd == 0.0
    led.reserve(sub_est, label="subscription call after exhaustion").settle()
    assert led.state().calls == 2


def test_a_nonzero_call_at_the_same_exhausted_ceiling_is_still_refused(led):
    """The control for the test above: proves the dollar guard was narrowed
    for zero-cost calls specifically, not disabled outright."""
    led.reserve(_est(1.00), label="fill the ceiling").settle()
    with pytest.raises(BudgetRefused):
        led.reserve(_est(0.01), label="one cent over an exhausted ceiling")


# ===========================================================================
# 12. price_call ORDERING -- a declared subscription must not launder an
#     untrusted host into looking free
# ===========================================================================
# The source comment on the subscription branch claims the host check runs
# BEFORE the subscription check specifically so "a declared subscription can
# never launder an untrusted host into looking local". This is the same SHAPE
# of bug Cerberus found for real in web_api._resolve_bind: a predicate meant
# to answer one question (consent to egress, lane_for_host) got read for a
# different one (is this call free / is this bind safe). That one was fixed
# by splitting the predicate. This section checks whether the analogous claim
# inside price_call actually holds, rather than trusting the comment.

@pytest.mark.parametrize("vendor,declared", [
    ("ollama", "remote_inference"),        # realistic: reassigned to
                                            # remote_inference by the host block
    ("remote_inference", "remote_inference"),
    ("anthropic_cli", "anthropic_cli"),
])
def test_a_declared_subscription_does_not_launder_an_untrusted_host(
        monkeypatch, vendor, declared):
    """A host lane_for_host would NOT certify, paired with a vendor that IS
    declared in DAEDALUS_SUBSCRIPTION_VENDORS: the estimate must not be free
    and must not carry basis=="subscription" -- exactly the assertion named
    for this case.

    MEASURED BEFORE WRITING THIS ASSERTION, not assumed: as of this test,
    price_call returns usd=0.0/basis="subscription" for all three
    parametrizations. Confirmed harmless for EGRESS specifically -- neither
    lane_for_host nor slice_egress_rule ever consult subscription_vendors(),
    so no source code ships anywhere it should not -- but the DOLLAR estimate
    this function returns is laundered to $0 by a declaration that only ever
    claimed to speak about money. This test is expected to be RED against the
    current implementation; it exists so that gap has an executable owner
    instead of a comment that was never checked.
    """
    monkeypatch.setenv(B.ENV_SUBSCRIPTIONS, declared)
    host = "100.119.126.9"          # the tailnet bench; never declared trusted here
    assert lane_for_host(host) == "untrusted"
    est = price_call(vendor, "m", host=host)
    assert est.basis not in ("subscription", "free_local"), (
        f"{vendor!r} over an untrusted host was priced as {est.basis!r} "
        f"(usd={est.usd}) because {declared!r} is declared in "
        f"{B.ENV_SUBSCRIPTIONS}")
    assert est.usd > 0.0
