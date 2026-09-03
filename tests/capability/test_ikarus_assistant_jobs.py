"""What Ikarus can actually DO, measured rather than assumed.

Twelve probes across the assistant's real capabilities: the bridge verdict, the
dispatch contract, conversation attribution, chat, the spend guard, and the
honesty rules the cockpit renders. They exist because on 2026-09-03 the cockpit
had never run a single work attempt on this machine -- 0 attempts, 0 draft
reports -- so every guarantee in the UI was verified against fixtures and none
against a real run.

The first real dispatch found a backend bug in under a minute. That is why
these are here.

TWO KINDS OF TEST, AND THE SPLIT IS DELIBERATE.

The pure ones drive `snapshot_from_bridge` against a temporary directory and
run everywhere, always. The live ones need the server on 127.0.0.1:8765 and
skip -- loudly, never silently passing -- when it is absent. A live test that
quietly turns green when the thing it tests is switched off is worse than no
test, so each one asserts something about the answer it got, not merely that
an answer arrived.

MODEL CALLS COST MONEY AND THE GUARD MAY REFUSE THEM. That refusal is itself a
capability, and it is tested (test 9). A test that needs a model reports the
refusal rather than failing on it: being unable to spend is not a defect.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from daedalus import progress as P
from daedalus import progress_sources as PS

BASE = os.environ.get("DAEDALUS_GUI_BASE_URL", "http://127.0.0.1:8765")
TIMEOUT = 30.0


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _get(path: str, timeout: float = TIMEOUT) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _post(path: str, body: dict, timeout: float = TIMEOUT) -> tuple[int, dict]:
    """POST returning (status, payload). A 4xx is DATA here, not an exception:
    several of these probes are about how the API refuses."""
    req = urllib.request.Request(
        f"{BASE}{path}", method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return fh.status, json.loads(fh.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _live() -> bool:
    # Deliberately NOT /api/health: that one probes twenty subsystems and can
    # take longer than any sane liveness timeout, so using it here skipped the
    # whole live half of this file while the server was up and answering.
    try:
        _get("/api/projects", timeout=10.0)
        return True
    except Exception:  # noqa: BLE001 -- any failure means "not reachable"
        return False


live = pytest.mark.skipif(not _live(), reason=f"no Daedalus server at {BASE}")


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    """A bridge whose four directories are empty and ours."""
    from daedalus import file_bridge as fb

    for name in ("ARCHIVE", "INBOX", "OUTBOX"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(fb, name, d, raising=True)
    monkeypatch.setattr(fb, "quarantined_requests", lambda: [], raising=False)
    monkeypatch.setattr(fb, "heartbeat_status", lambda **_: {}, raising=False)
    return tmp_path


def _archive(bridge: Path, key: str) -> None:
    # What the watcher really files: the REQUEST, with no outcome field at all.
    (bridge / "archive" / f"{key}.json").write_text(json.dumps({
        "objective": "x", "lane": "local_only", "project": "p", "paths": []}),
        encoding="utf-8")


def _report(bridge: Path, key: str, status: str | None) -> None:
    body: dict = {"lane": "local_only", "request_sha256": "0" * 64}
    if status is not None:
        body["bridge_status"] = status
        if status != "done":
            body["error"] = "the trusted local bench did not accept the task"
    (bridge / "inbox" / f"{key}.report.json").write_text(
        json.dumps(body), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1-3 -- the bridge verdict. A REAL BUG, found by the first real dispatch.     #
# --------------------------------------------------------------------------- #
def test_an_archived_failure_is_not_reported_as_a_success(bridge):
    """The regression that motivated this file.

    `snapshot_from_bridge` checked the archive FIRST and returned
    `succeeded=True, applied=True` for anything filed there. But
    `runs/processed/{key}.json` is the enqueued REQUEST -- objective, lane,
    paths -- with no status field of any kind, and the watcher archives
    failures exactly as it archives successes.

    Measured on a real dispatch, 2026-09-03: task.state=failed,
    error="the trusted local bench did not accept the task", and
    progress.succeeded=true. Two projections of one run, disagreeing, with the
    optimistic one winning -- and the cockpit's timeline takes its colour from
    `succeeded`, so a failed run rendered green.
    """
    key = "k-failed"
    _archive(bridge, key)
    _report(bridge, key, "failed")

    snap = PS.snapshot_from_bridge(key)
    assert snap is not None
    assert snap.succeeded is False, "an archived FAILURE reported success"
    assert snap.applied is not True, "claimed a write it has no evidence for"


def test_an_archive_without_a_report_is_unproven_not_successful(bridge):
    """No report retained means no evidence either way.

    `None` and `False` are different answers and the surface draws them
    differently: unproven is amber, a measured failure is red. Returning
    `False` here would invent a failure exactly as the old code invented a
    success.
    """
    key = "k-bare"
    _archive(bridge, key)

    snap = PS.snapshot_from_bridge(key)
    assert snap is not None
    assert snap.succeeded is None, "invented a verdict from a file with no outcome in it"
    assert snap.applied is None


def test_archived_and_unarchived_never_disagree_about_one_report(bridge):
    """The two branches share `_report_verdict`, so they cannot drift.

    The archive branch runs BEFORE the report branch and masks it. When those
    two disagreed, archiving silently changed a run's verdict -- the same run,
    the same report, a different answer depending on whether the watcher had
    got round to filing it.
    """
    for status, expected in (("done", True), ("failed", False), ("ok", True)):
        key = f"k-{status}"
        _report(bridge, key, status)
        before = PS.snapshot_from_bridge(key)          # report branch
        _archive(bridge, key)
        after = PS.snapshot_from_bridge(key)           # archive branch

        assert before is not None and after is not None
        assert before.succeeded is expected
        assert after.succeeded is before.succeeded, (
            f"filing the task changed its verdict for bridge_status={status!r}")


# --------------------------------------------------------------------------- #
# 4 -- a report with no status is not a failure                               #
# --------------------------------------------------------------------------- #
def test_a_report_with_no_status_is_unproven(bridge):
    key = "k-nostatus"
    _report(bridge, key, None)
    snap = PS.snapshot_from_bridge(key)
    assert snap is not None
    assert snap.succeeded is None, '"the watcher wrote no status" is not "the watcher wrote a failure"'


# --------------------------------------------------------------------------- #
# 5 -- an unknown key is never guessed at                                     #
# --------------------------------------------------------------------------- #
def test_an_unknown_task_returns_nothing_rather_than_a_guess(bridge):
    assert PS.snapshot_from_bridge("k-never-existed") is None


# --------------------------------------------------------------------------- #
# 6-7 -- the dispatch contract                                                #
# --------------------------------------------------------------------------- #
@live
def test_a_dispatch_without_an_objective_is_refused():
    status, body = _post("/api/queue", {"project": "daedalus_wt"})
    assert status == 400
    assert body.get("ok") is False
    assert "objective" in str(body.get("error", ""))


@live
def test_conversation_attribution_refuses_an_ambiguous_pair():
    """Attribution is an exact pair or it is nothing.

    The API refuses `conversation_id` without an explicit positive `turn_id`
    rather than inferring "the latest turn": an older offer can be clicked
    after a newer reply, and concurrent completions make recency ambiguous.
    Guessing here would attribute a dispatch to the wrong message.
    """
    status, body = _post("/api/queue", {
        "project": "daedalus_wt", "objective": "probe",
        "conversation_id": "c-1"})
    assert status == 400, "accepted a conversation_id with no turn_id"
    assert "turn_id" in str(body.get("error", ""))

    status, body = _post("/api/queue", {
        "project": "daedalus_wt", "objective": "probe", "turn_id": 3})
    assert status == 400, "accepted a turn_id with no conversation_id"
    assert "conversation_id" in str(body.get("error", ""))


# --------------------------------------------------------------------------- #
# 8 -- the queue refuses to accept work nothing will consume                  #
# --------------------------------------------------------------------------- #
@live
def test_the_queue_either_runs_the_task_or_says_why_not():
    """Either a watcher exists and the task gets an id, or the enqueue is
    REFUSED with the command that would fix it.

    What must never happen is the third thing: accepting the task and letting
    it sit in the outbox "looking successfully queued". Both branches are a
    pass; silence is not.
    """
    status, body = _post("/api/queue", {
        "project": "daedalus_wt",
        "objective": "Capability probe: no-op.",
        "lane": "local_only", "source": "capability-probe"})

    if body.get("ok"):
        assert body.get("id"), "queued a task but returned no id to track it by"
        snap = _get(f"/api/queue/{body['id']}")
        assert snap["task"]["found"] is True, "the id it returned is not readable back"
    else:
        error = str(body.get("error", ""))
        assert "watcher" in error, f"refused for an unexplained reason: {error[:200]}"
        assert "file_bridge" in error, "refused without naming the command that fixes it"


# --------------------------------------------------------------------------- #
# 9 -- chat, and the spend guard                                              #
# --------------------------------------------------------------------------- #
@live
def test_chat_answers_and_names_the_provider_that_answered():
    """Ikarus replies, and says WHICH runtime produced the reply.

    A reply with no attribution is the shape that lets a fallback masquerade
    as the model you chose. If the spend guard refuses the call, that is a
    pass with a report: being unable to spend is not a defect, and the refusal
    is asserted in the next test.
    """
    status, body = _post("/api/ikarus/ask", {
        "project": "daedalus_wt",
        "message": "Reply with the single word ACKNOWLEDGED."}, timeout=200.0)
    assert status == 200
    assert body.get("ok") is True

    if body.get("intent") == "error":
        pytest.skip(f"provider unavailable or refused: {str(body.get('assistant'))[:160]}")

    assert body.get("assistant"), "an empty reply reported as a successful answer"
    assert body.get("provider_used"), "answered without naming the runtime that answered"
    llm = body.get("llm") or {}
    assert llm.get("execution_limit_policy"), "answered without recording the limits it ran under"


@live
def test_a_refused_call_says_who_refused_it_and_on_what_evidence():
    """The guard's refusal is a first-class answer, not an error string.

    Measured on 2026-09-03: "I didn't make that call. The budget.process_guard
    contract refused it before anything left this machine ... estimate $3.0000
    (basis=worst_case), committed $3.0000 of $5.0000". That names the contract,
    the endpoint, the basis, and the arithmetic. A bare "request failed" would
    leave a reader unable to tell a refusal from an outage.

    Skips when the guard is not currently refusing -- there is nothing to
    assert about a refusal that did not happen.
    """
    status, body = _post("/api/ikarus/ask", {
        "project": "daedalus_wt", "message": "ping"}, timeout=200.0)
    assert status == 200
    if body.get("intent") != "error":
        pytest.skip("no refusal to inspect: the call was permitted")

    said = str(body.get("assistant") or "")
    assert "refused" in said.lower() or "denied" in said.lower()
    assert "$" in said or "ceiling" in said.lower(), "refused without naming the limit"
    assert body.get("shell") == "deterministic", (
        "a guard refusal was narrated by a model rather than stated by the guard")


# --------------------------------------------------------------------------- #
# 10 -- governance has exactly one source                                     #
# --------------------------------------------------------------------------- #
@live
def test_the_promotion_verdict_has_one_source_of_truth():
    """`/api/governance` and `dashboard["governance"]` are the same function.

    Two endpoints that could disagree about whether promotion is allowed is
    precisely the "parallel control plane" the plan forbids.
    """
    standalone = _get("/api/governance")
    embedded = (_get("/api/dashboard") or {}).get("governance")
    assert embedded is not None, "the dashboard stopped carrying governance"

    for field in ("promotion_allowed", "state", "verdict", "head"):
        assert standalone.get(field) == embedded.get(field), (
            f"the two governance views disagree about {field!r}")


# --------------------------------------------------------------------------- #
# 11 -- health keeps five states and stamps every number                      #
# --------------------------------------------------------------------------- #
@live
def test_health_never_collapses_to_a_boolean_and_stamps_its_facts():
    payload = _get("/api/health", timeout=90.0)
    snap = payload.get("health") or {}
    subsystems = snap.get("subsystems") or []
    assert subsystems, "health reported no subsystems at all"

    allowed = {"working", "present", "degraded", "absent", "unknown"}
    stamps = {"MEASURED", "INHERITED", "ASSUMED"}
    for sub in subsystems:
        assert sub.get("state") in allowed, f"{sub.get('name')} left the vocabulary: {sub.get('state')!r}"
        assert sub.get("asks"), f"{sub.get('name')} does not say what question it answers"
        for fact in sub.get("facts") or []:
            assert fact.get("provenance") in stamps, (
                f"{sub.get('name')}/{fact.get('label')} carries an unlabelled number")


# --------------------------------------------------------------------------- #
# 12 -- progress refuses a percentage it cannot honestly compute              #
# --------------------------------------------------------------------------- #
def test_a_single_unit_refuses_to_invent_a_denominator(tmp_path):
    """One unit has no total, so there is no fraction -- and the refusal is a
    SENTENCE rather than a silently absent field.

    A missing field lets a caller substitute its own zero. A sentence cannot
    be mistaken for a measurement.
    """
    snap = P.snapshot("u-1", log=P.ProgressLog(tmp_path / "empty.jsonl"))
    assert snap.found is False
    assert snap.fraction_hint, "declined to say WHY there is no percentage"
    assert "%" not in snap.fraction_hint
    assert snap.succeeded is None and snap.applied is None
