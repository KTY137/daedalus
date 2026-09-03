"""The TypeScript contract must describe what the backend actually sends.

WHY THIS TEST EXISTS. Three separate iterations of cockpit work each began by
comparing a live payload against `apps/web/src/shared/**` by hand, and each
time that comparison found a real defect:

  2026-09-03  `asked` was typed on `HealthPayload` (the envelope) while
              read.py writes it inside `health`. `payload.asked` was therefore
              always undefined, so the panel could not report whether a health
              read was shallow or scoped -- which read.py sets it to say,
              "rather than letting `present` read as `working`".

  2026-09-03  `RuntimeRow` declared none of `local`, `trusted_with_ip`,
              `can_write`, `agentic`, `command`, `env_key`. The runtime picker
              therefore could not say which runtimes the egress gate treats as
              untrusted with proprietary source. Fixing that surfaced a
              second, worse bug: two registries disagreed about codex_cli and
              the endpoint published the more permissive value.

  2026-09-03  `DashboardPayload` declared none of the `quality` safety-gate
              block, so a card that had the answers in hand rendered a raw
              JSON dump instead, and a failed SAFETY probe was invisible.

The shape is always the same: the backend sends a field, the contract does not
declare it, so the typed path cannot reach it and the surface silently omits
something the backend went to trouble to report. A field that is unreachable
is indistinguishable from a field that does not exist -- until someone reads
the Python and notices.

TWO DIRECTIONS, AND ONLY ONE OF THEM IS NOISE.

  sent-but-undeclared  -> FAIL. This is the bug above, every time.
  required-but-absent  -> FAIL. The contract promises a field on every
                          response and the server did not send it, so every
                          reader is one payload away from `undefined`.
  optional-but-absent  -> fine, and deliberately not reported. `endpoint?` is
                          Ollama-only, `error?` appears on failures,
                          `write_allow?` on one gate of three. Flagging those
                          would bury the real findings in noise -- which is
                          exactly what the hand-run audit did before the
                          optional/required split was added.

THIS IS A LIVE TEST and skips when no server is running. That is a real
limitation, stated rather than hidden: it cannot run in a CI job that has no
backend, so it guards a developer's machine and the packaged desktop, not the
build. It is still worth having, because every defect above was found exactly
this way and none of them were found by anything else.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "apps" / "web" / "src" / "shared"
BASE = os.environ.get("DAEDALUS_GUI_BASE_URL", "http://127.0.0.1:8765")

# Fields every envelope carries; `ApiEnvelope` also has an index signature, so
# a payload may legitimately add more at the top level.
ENVELOPE = {"ok", "generated_at", "project", "warnings", "error"}


def _contract_source() -> str:
    return "\n".join(
        (SHARED / name / "index.ts").read_text(encoding="utf-8")
        for name in ("api", "contracts")
    )


def _interface(name: str) -> tuple[set[str], set[str], bool]:
    """``(required, optional, extends_envelope)`` for one TS interface."""
    src = _contract_source()
    match = re.search(rf"\binterface {name}\b([^{{]*)\{{(.*?)\n\}}", src, re.S)
    assert match, f"interface {name} is not in apps/web/src/shared"
    extends_envelope = "ApiEnvelope" in match.group(1)
    body = re.sub(r"/\*.*?\*/", "", match.group(2), flags=re.S)
    body = re.sub(r"//.*", "", body)
    required = set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\s*:", body, re.M))
    optional = set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\?\s*:", body, re.M))
    return required, optional, extends_envelope


def _get(path: str, timeout: float = 180.0) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _live() -> bool:
    try:
        _get("/api/projects", timeout=10.0)
        return True
    except Exception:  # noqa: BLE001 -- any failure means "not reachable"
        return False


live = pytest.mark.skipif(not _live(), reason=f"no Daedalus server at {BASE}")

# (url, dotted path into the payload, interface name)
#
# The dotted path exists because a row type is only checkable through a real
# row: sampling `runtimes.0` is what surfaced the RuntimeRow gap. Where a list
# may be empty the case is skipped rather than passed.
CASES = [
    ("/api/governance", "", "GovernancePayload"),
    ("/api/governance", "gates.0", "GovernanceGate"),
    ("/api/health", "health", "HealthSnapshot"),
    ("/api/health", "health.subsystems.0", "HealthSubsystem"),
    ("/api/health", "health.subsystems.0.facts.0", "HealthFact"),
    ("/api/accelerators/status", "accelerators", "AcceleratorSnapshot"),
    ("/api/accelerators/status", "accelerators.hardware", "AcceleratorHardware"),
    ("/api/accelerators/status", "accelerators.lanes.0", "AcceleratorLane"),
    ("/api/accelerators/status", "accelerators.remote_compute", "AcceleratorRemoteCompute"),
    ("/api/accelerators/status", "accelerators.remote_rtx_ollama", "AcceleratorRemoteOllama"),
    ("/api/runtimes/status", "runtimes.0", "RuntimeRow"),
    ("/api/providers/status", "providers.0", "ProviderStatusRow"),
    ("/api/projects", "projects.0", "ProjectRow"),
    # The dashboard was NOT in this list when the file was written, and the
    # third defect above lived there. Eight of its fields were still
    # undeclared, so adding it here would have failed immediately -- which is
    # the point: an endpoint the audit cannot watch is an endpoint where the
    # next one hides. `test_every_read_endpoint_is_audited_or_exempt` below now
    # enforces that principle instead of leaving it to whoever remembers.
    ("/api/dashboard?project=daedalus_wt", "", "DashboardPayload"),
    ("/api/catalogue", "", "CataloguePayload"),
    ("/api/loop/queue?project=daedalus_wt", "", "LoopQueuePayload"),
    ("/api/loop/attempts", "", "LoopAttemptsPayload"),
    ("/api/loop/architecture?project=daedalus_wt", "", "LoopArchitecturePayload"),
    ("/api/projects/daedalus_wt/hierarchy", "", "HierarchyPayload"),
    ("/api/projects/daedalus_wt/hierarchy", "capabilities.0", "CapabilityEntry"),
    ("/api/projects/daedalus_wt/control-plane", "", "ControlPlanePayload"),
    ("/api/projects/daedalus_wt/control-plane", "profiles.0", "AgentProfile"),
    ("/api/structure?project=daedalus_wt", "", "StructurePayload"),
    ("/api/topology?project=daedalus_wt", "", "TopologyPayload"),
    ("/api/drafts?project=daedalus_wt", "", "DraftsPayload"),
]

# Read endpoints the cockpit can call that are deliberately NOT audited, each
# with the reason. An entry here is a decision; an endpoint in NEITHER list is
# a gap, and the coverage test below fails on it.
EXEMPT: dict[str, str] = {
    "/api/env/status": "returns a secrets-adjacent inventory; auditing it here "
                       "would print key names into test output",
    "/api/context/plan": "requires request-specific parameters; a bare GET is a "
                         "400 and there is no representative shape to pin",
    "/api/desktop/settings": "desktop-only route, absent from the web server "
                             "this audit runs against",
    "/api/conversations": "row shape is pinned by tests/test_conversation_list.py "
                          "against the store, which is stronger than a live sample",
    "/api/queue": "POST only; this audit compares GET response shapes",
    "/api/queue/": "needs a task id that exists; covered by tests/capability/",
    "/api/drafts/": "needs a draft id that exists",
    "/api/runtimes/": "the /test subpath is a POST probe, not a read",
    "/api/distill": "POST only; this audit compares GET response shapes",
    "/api/ikarus/ask": "POST only, and a call costs money against the "
                       "provider budget",
    "/api/ikarus/chat": "POST only, and a call costs money against the "
                        "provider budget",
    "/api/projects/": "the bare prefix is the registration POST; its GET "
                      "subpaths are audited above",
    "/api/desktop/services/ide/start": "POST only, and it starts a service",
    # Found by the coverage test itself on 2026-09-03: five endpoints the
    # cockpit calls that were in neither list.
    "/api/events": "server-sent events, not a JSON document; its frame shapes "
                   "are pinned by features/mission/live.ts and mission.spec.ts",
    "/api/ikarus/stream": "server-sent events, not a JSON document",
    "/api/conversations/": "the per-conversation subpath needs an id that "
                           "exists; the list shape is audited via its own store test",
    "/api/editor/contexts/": "needs an editor context ref minted by a POST",
    "/api/drafts": "audited above with a project query; this bare prefix is the "
                   "same route",
}

_cache: dict[str, dict] = {}


def _payload(url: str) -> dict:
    if url not in _cache:
        _cache[url] = _get(url)
    return _cache[url]


def _walk(node, dotted: str):
    for part in [p for p in dotted.split(".") if p]:
        if part.isdigit():
            if not isinstance(node, list) or len(node) <= int(part):
                return None
            node = node[int(part)]
        else:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
    return node


@live
@pytest.mark.parametrize(
    "url,dotted,iface", CASES, ids=[f"{i}@{d or 'root'}" for _, d, i in CASES]
)
def test_the_contract_declares_every_field_the_backend_sends(url, dotted, iface) -> None:
    node = _walk(_payload(url), dotted)
    if node is None:
        pytest.skip(f"{url} has nothing at {dotted!r} on this machine")
    if not isinstance(node, dict):
        pytest.skip(f"{url} {dotted!r} is {type(node).__name__}, not an object")

    required, optional, extends_envelope = _interface(iface)
    declared = required | optional
    if extends_envelope:
        declared |= ENVELOPE

    undeclared = sorted(set(node) - declared)
    assert not undeclared, (
        f"{url} {dotted or '(root)'} sends fields that {iface} does not declare, "
        f"so the cockpit cannot reach them through the typed path: {undeclared}. "
        "Every cockpit defect found this way so far was a field the backend "
        "reported deliberately and the surface silently dropped."
    )


@live
@pytest.mark.parametrize(
    "url,dotted,iface", CASES, ids=[f"{i}@{d or 'root'}" for _, d, i in CASES]
)
def test_every_required_field_actually_arrives(url, dotted, iface) -> None:
    """A required field the server omits makes every reader one payload away
    from `undefined`. Optional fields are not checked: their whole point is
    that they are sometimes absent."""
    node = _walk(_payload(url), dotted)
    if node is None:
        pytest.skip(f"{url} has nothing at {dotted!r} on this machine")
    if not isinstance(node, dict):
        pytest.skip(f"{url} {dotted!r} is {type(node).__name__}, not an object")

    required, _optional, extends_envelope = _interface(iface)
    if extends_envelope:
        required |= {"ok", "generated_at", "project", "warnings"}

    missing = sorted(required - set(node))
    assert not missing, (
        f"{iface} declares {missing} as always present, but {url} "
        f"{dotted or '(root)'} did not send them. Either the field is optional "
        "and the contract should say so with `?`, or the server regressed."
    )


def _endpoints_the_cockpit_calls() -> set[str]:
    """Every `/api/...` literal reachable through `shared/api`.

    Read out of the source rather than maintained by hand, because a list
    maintained by hand is exactly what fell behind: the dashboard was missing
    from CASES when this file was written, and that is where a real defect was
    living.
    """
    src = (SHARED / "api" / "index.ts").read_text(encoding="utf-8")
    return set(re.findall(r"[\"'`](/api/[a-z0-9/_.-]*)", src))


def test_every_read_endpoint_is_audited_or_exempt() -> None:
    """No endpoint may be silently unwatched.

    An endpoint absent from both CASES and EXEMPT is a blind spot, and every
    contract defect found so far was in a blind spot. Adding a route to
    `shared/api` therefore forces a decision here: audit it, or say in one
    line why not.
    """
    audited = {url.split("?", 1)[0] for url, _dotted, _iface in CASES}
    known = audited | set(EXEMPT)
    unwatched = sorted(_endpoints_the_cockpit_calls() - known)

    assert not unwatched, (
        "these endpoints are reachable from the cockpit but appear in neither "
        f"CASES nor EXEMPT: {unwatched}. Add a case, or add an EXEMPT entry "
        "saying why one cannot exist. An unwatched endpoint is where the next "
        "undeclared field will live."
    )


def test_exemptions_are_real_endpoints_and_carry_a_reason() -> None:
    """An exemption for an endpoint nobody calls is dead weight that makes the
    list look more considered than it is."""
    live = _endpoints_the_cockpit_calls()
    stale = sorted(set(EXEMPT) - live)
    assert not stale, f"EXEMPT names endpoints the cockpit no longer calls: {stale}"
    for url, reason in EXEMPT.items():
        assert len(reason.strip()) > 15, f"{url} is exempt without a real reason"


def test_the_parser_separates_optional_from_required() -> None:
    """The audit is only quiet enough to be useful because of this split.

    Every false positive the hand-run version produced was an optional field
    legitimately absent -- `endpoint?` is Ollama-only, `error?` appears on
    failures, `write_allow?` on one gate of three. Without the distinction
    those drown the real findings.
    """
    required, optional, extends_envelope = _interface("RuntimeRow")
    assert "id" in required and "id" not in optional
    assert "endpoint" in optional and "endpoint" not in required
    # The six that were undeclared until 2026-09-03, and are optional because
    # an older server sends none of them.
    for field in ("local", "trusted_with_ip", "can_write", "agentic"):
        assert field in optional, f"{field} lost its optional marker"
    assert extends_envelope is False

    _req, _opt, env = _interface("GovernancePayload")
    assert env is True, "GovernancePayload no longer extends ApiEnvelope"
