"""publish.py -- the GitHub-PR bridge for the cross-vendor Council.

THE BUS IS CANONICAL; THE PR IS A RENDERING
-------------------------------------------
The council's own record is the append-only, hash-chained JSONL bus at
``runs/council/<council_id>.jsonl`` (``bus.py``, the memstore pattern). This
module NEVER writes to that record and never derives authority from GitHub. It
does two things:

  * renders a deliberation into human-readable markdown and posts it as a PR
    comment, so a human can watch four vendors argue without tailing a JSONL;
  * reads the PR's comments back, so a later council round can consume what a
    human -- or another agent -- replied. That is the async-channel half.

If the PR and the bus ever disagree, the bus is right. A comment can be edited,
deleted, or rate-limited away; a chain link cannot. Every rendering therefore
carries the bus path and the chain head digest so a reader can verify the
transcript offline against the file, rather than trusting the comment.

ADVISORY ONLY
-------------
A council verdict promotes nothing. THE GATE DECIDES, NOT A MODEL. The advisory
banner is emitted unconditionally -- even if a caller hands us a verdict whose
``advisory`` marker is missing or False, which is a contract violation we render
LOUDLY rather than honour.

EGRESS GATE
-----------
Every string that would leave this machine for GitHub -- the whole rendered
comment body, the PR reference, the repo slug, and any evidence path -- runs
through ``sensitivity.secret_floor_rule`` BEFORE the runner is touched. The floor
is the same unconditional every-lane rule ``memstore.append_entry`` uses; it
cannot be weakened by project policy. A hit is a STATUS (``refused_secret``), not
an exception, and the offending string never reaches the runner, the argv, or the
child's stdin. The refusal detail names the CHANNEL and the RULE only -- never the
matched text (echoing it into a log or a caller's report would be the same leak
by another route).

The gate runs in dry-run mode too. A dry run is a rehearsal of the live call, not
a bypass: if a body would be refused live it is refused dry, so a preview can
never show an operator a comment the gate would not actually post.

DUCK-TYPED INPUTS
-----------------
``verdict`` and ``transcript`` are read structurally (attribute OR dict key, with
tolerant field aliases) rather than imported from ``bus.py`` / ``vendors.py`` /
``session.py``. Those modules are being written alongside this one; binding to
their concrete classes would couple the renderer to a contract still in motion,
and would make this module unimportable whenever one of them is mid-edit. The
only hard dependency is the secret floor, which is not negotiable.

INJECTED RUNNER
---------------
``gh`` is reached only through a ``runner(argv, stdin_text) -> RunResult``
callable. The default shells out; tests pass a fake and assert on exactly what it
received. The comment body travels on the child's STDIN (``--body-file -``), not
in argv: a full deliberation blows past the Windows command-line limit, and
stdin keeps the payload equally inspectable by a fake runner.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..sensitivity import secret_floor_rule

# --------------------------------------------------------------------------- #
# status vocabulary -- CLOSED and explicit                                     #
# --------------------------------------------------------------------------- #
# Every exit from publish_to_pr / read_pr_thread is one of these strings. No
# call raises for an operational condition (missing gh, bad auth, absent PR,
# rate limit, secret refusal): the caller branches on a status it can enumerate,
# because a swallowed exception and an unnamed failure are the same bug.
STATUS_PUBLISHED = "published"            # comment posted; comment_url set when gh printed one
STATUS_DRY_RUN = "dry_run"                # rendered and gated; gh never invoked
STATUS_READ_OK = "read_ok"                # PR thread read and parsed
STATUS_REFUSED_SECRET = "refused_secret"  # secret floor fired; nothing left the machine
STATUS_GH_MISSING = "gh_missing"          # gh not on PATH / could not be launched
STATUS_GH_UNAUTHENTICATED = "gh_unauthenticated"  # gh present, no valid credentials
STATUS_PR_NOT_FOUND = "pr_not_found"      # no such PR (or no access to it)
STATUS_RATE_LIMITED = "rate_limited"      # primary/secondary rate limit or abuse detection
STATUS_BAD_PAYLOAD = "bad_payload"        # gh exited 0 but its JSON was unparseable
STATUS_GH_ERROR = "gh_error"              # explicit catch-all: gh failed for another reason

PUBLISH_STATUSES: frozenset[str] = frozenset({
    STATUS_PUBLISHED, STATUS_DRY_RUN, STATUS_REFUSED_SECRET, STATUS_GH_MISSING,
    STATUS_GH_UNAUTHENTICATED, STATUS_PR_NOT_FOUND, STATUS_RATE_LIMITED,
    STATUS_GH_ERROR,
})
READ_STATUSES: frozenset[str] = frozenset({
    STATUS_READ_OK, STATUS_REFUSED_SECRET, STATUS_GH_MISSING,
    STATUS_GH_UNAUTHENTICATED, STATUS_PR_NOT_FOUND, STATUS_RATE_LIMITED,
    STATUS_BAD_PAYLOAD, STATUS_GH_ERROR,
})
STATUSES: frozenset[str] = PUBLISH_STATUSES | READ_STATUSES

DEFAULT_TIMEOUT_S = 60
DEFAULT_BUS_DIR = "runs/council"

# Neutral hint path for CONTENT scans. ``secret_floor_rule`` checks its ``path``
# argument against secret path markers (.env, .pem, id_rsa, ...); feeding it a
# real repo path here would conflate "this file is a secret" with "this text
# contains a secret". Evidence paths get their own, separate path-marker scan.
_EGRESS_HINT = "<council-pr-comment>"

# The degraded-quorum banner marker. Exported so tests (and any other renderer
# consumer) assert on a constant rather than on prose that may be reworded.
DEGRADED_QUORUM_MARKER = "DEGRADED QUORUM"


# --------------------------------------------------------------------------- #
# runner protocol                                                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunResult:
    """What a runner returns. Mirrors the subset of ``subprocess.CompletedProcess``
    this module reads, so a fake is three fields, not a mock framework."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


# runner(argv, stdin_text) -> RunResult. stdin_text is None when the call sends
# nothing on stdin (every read path); it carries the comment body on publish.
Runner = Callable[[Sequence[str], "str | None"], RunResult]


def _subprocess_runner(argv: Sequence[str], stdin_text: str | None = None,
                       timeout_s: int = DEFAULT_TIMEOUT_S) -> RunResult:
    """Default runner: actually invoke ``gh``. Never raises -- a launch failure
    becomes a RunResult the classifier can map to a status."""
    argv = list(argv)
    # gh installs as a .CMD shim under some Windows package managers; subprocess
    # cannot spawn it by bare name (WinError 2), so resolve the real path first
    # -- the same lesson codex_cli.py records for the codex shim.
    exe = shutil.which(argv[0]) or argv[0]
    try:
        completed = subprocess.run(
            [exe] + argv[1:],
            text=True, capture_output=True,
            # gh emits UTF-8 (smart quotes in PR titles, box drawing); without an
            # explicit encoding text=True decodes with the Windows locale and a
            # stray byte kills the capture thread.
            encoding="utf-8", errors="replace",
            # Always pass input (possibly ""): it closes the child's stdin, so gh
            # cannot block waiting on an inherited handle that never reaches EOF.
            input=stdin_text if stdin_text is not None else "",
            timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        return RunResult(127, "", f"gh not found on PATH: {exc}")
    except OSError as exc:
        return RunResult(127, "", f"gh could not be launched: {exc}")
    except subprocess.TimeoutExpired:
        return RunResult(124, "", f"gh timed out after {timeout_s}s")
    return RunResult(completed.returncode, completed.stdout or "",
                     completed.stderr or "")


# --------------------------------------------------------------------------- #
# results                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PublishResult:
    """Outcome of a publish attempt. ``status`` is always in PUBLISH_STATUSES.

    ``markdown`` is populated on ``dry_run`` and ``published``; it is EMPTY on
    ``refused_secret`` -- handing the caller a body the floor just rejected
    invites it straight back into a log file."""

    status: str
    detail: str = ""
    markdown: str = ""
    comment_url: str = ""


@dataclass(frozen=True)
class PRTurn:
    """One comment on the PR, as a council turn. ``author`` is the GitHub login
    (a human or another agent); ``created_at`` is GitHub's ISO timestamp."""

    author: str
    created_at: str
    body: str
    url: str = ""


@dataclass(frozen=True)
class ThreadResult:
    """Outcome of a PR-thread read. ``status`` is always in READ_STATUSES."""

    status: str
    detail: str = ""
    turns: tuple[PRTurn, ...] = ()


# --------------------------------------------------------------------------- #
# structural field access -- tolerant of dataclass OR dict                     #
# --------------------------------------------------------------------------- #
def _field(obj: Any, *names: str, default: Any = None) -> Any:
    """First present, non-None value among ``names``, read as a mapping key or an
    attribute. Deliberately alias-tolerant: this renderer must keep working while
    the council's own dataclasses are still being named."""
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, Mapping):
            val = obj.get(name)
        else:
            val = getattr(obj, name, None)
        if val is not None:
            return val
    return default


def _as_list(val: Any) -> list[Any]:
    if val is None:
        return []
    if isinstance(val, Mapping):
        # dict-keyed collections (e.g. {vendor: stats}) are flattened into rows
        # carrying their key, so a mapping and a list of rows render identically.
        out = []
        for key, item in val.items():
            if isinstance(item, Mapping):
                row = dict(item)
                row.setdefault("vendor", key)
                out.append(row)
            else:
                out.append({"vendor": key, "value": item})
        return out
    if isinstance(val, (str, bytes)):
        return [val]
    if isinstance(val, Iterable):
        return list(val)
    return [val]


def _text(val: Any) -> str:
    return "" if val is None else str(val)


# --------------------------------------------------------------------------- #
# rendering helpers                                                            #
# --------------------------------------------------------------------------- #
def _fence_for(text: str) -> str:
    """A backtick fence longer than the longest backtick run inside ``text``.

    Dissents are reproduced VERBATIM, and a dissent that itself contains a code
    fence would otherwise terminate ours early -- silently truncating another
    vendor's objection, which is the one thing this rendering exists to preserve.
    """
    longest = run = 0
    for ch in text:
        if ch == "`":
            run += 1
            if run > longest:
                longest = run
        else:
            run = 0
    return "`" * max(3, longest + 1)


def _verbatim(text: str) -> str:
    """Fence ``text`` exactly as given -- no reflow, no escaping, no truncation."""
    body = _text(text)
    fence = _fence_for(body)
    return f"{fence}text\n{body}\n{fence}"


def _short(digest: Any, n: int = 12) -> str:
    d = _text(digest)
    return d[:n] if d else ""


def _bus_path(verdict: Any, transcript: Any) -> str:
    """Where the canonical record lives. Explicit field wins; otherwise derived
    from the council id, which is how ``bus.py`` names the file."""
    path = _field(transcript, "bus_path", "path", "store_path")
    if path:
        return _text(path)
    path = _field(verdict, "bus_path", "path", "store_path")
    if path:
        return _text(path)
    council_id = _text(_field(verdict, "council_id", "id", default=""))
    if council_id:
        return f"{DEFAULT_BUS_DIR}/{council_id}.jsonl"
    return "(bus path not recorded)"


def _turns_of(transcript: Any) -> list[Any]:
    """A transcript may be the turn list itself, or an object/dict carrying one."""
    if transcript is None:
        return []
    if isinstance(transcript, Mapping):
        return _as_list(_field(transcript, "turns", "records", "entries", default=[]))
    if isinstance(transcript, (list, tuple)):
        return list(transcript)
    turns = _field(transcript, "turns", "records", "entries")
    return _as_list(turns)


def _chain_head(verdict: Any, transcript: Any) -> str:
    """The chain head digest a reader verifies the bus against. Explicit field
    wins; otherwise the last turn's entry_sha, which IS the head by construction
    in an append-only chain."""
    head = _field(transcript, "chain_head", "head", "head_sha", "entry_sha")
    if not head:
        head = _field(verdict, "chain_head", "head", "head_sha")
    if not head:
        turns = _turns_of(transcript)
        if turns:
            head = _field(turns[-1], "entry_sha", "sha", "digest")
    return _text(head)


def _quorum_counts(verdict: Any) -> tuple[int, int, list[str], list[str]]:
    """(answered, requested, answered_vendors, missing_vendors).

    Counts are derived from the vendor LISTS when present, because a list is
    checkable against the transcript and a bare integer is not."""
    answered_v = [_text(v) for v in _as_list(
        _field(verdict, "vendors_answered", "answered", "participants",
               "vendors", default=[]))]
    requested_v = [_text(v) for v in _as_list(
        _field(verdict, "vendors_requested", "requested", "roster", default=[]))]
    answered_n = _field(verdict, "quorum_achieved", "quorum", "n_answered")
    requested_n = _field(verdict, "quorum_requested", "n_requested",
                         "quorum_target")
    answered = int(answered_n) if isinstance(answered_n, int) else len(answered_v)
    requested = int(requested_n) if isinstance(requested_n, int) else len(requested_v)
    if not requested:
        requested = answered
    missing = [v for v in requested_v if v not in answered_v]
    return answered, requested, answered_v, missing


def _evidence_paths(verdict: Any) -> list[str]:
    """Paths named by the evidence, for the path-marker half of the floor."""
    out: list[str] = []
    for item in _as_list(_field(verdict, "evidence", "evidence_digests", default=[])):
        if isinstance(item, (str, bytes)):
            out.append(_text(item))
            continue
        label = _field(item, "path", "file", "label", "name")
        if label:
            out.append(_text(label))
    for p in _as_list(_field(verdict, "paths", default=[])):
        out.append(_text(p))
    return [p for p in out if p]


# --------------------------------------------------------------------------- #
# render_markdown -- the human-facing rendering of the bus                     #
# --------------------------------------------------------------------------- #
def render_markdown(verdict: Any, transcript: Any = None) -> str:
    """Render one council deliberation as markdown.

    Order is deliberate and load-bearing: outcome and the quorum honesty line
    lead, so a degraded council is the first thing a reader sees and cannot be
    skimmed past. Then EVERY dissent verbatim with its author -- BEFORE the
    convergence, because the dissent is the only part that could not have come
    from asking one model twice. Then where the vendors converged, evidence
    digests, per-vendor cost/latency, the deliberation itself, and finally the
    provenance footer (bus path + chain head) that lets a reader verify all of it
    offline. Pure: no I/O, no network, no gate."""
    council_id = _text(_field(verdict, "council_id", "id", default="(unnamed)"))
    question = _text(_field(verdict, "question", "topic", "objective",
                            default="(question not recorded)"))
    outcome = _text(_field(verdict, "outcome", "position", "decision", "verdict",
                           default="(no outcome recorded)"))
    # CONVERGENCE, not "majority". A majority is a DECISION; convergence is an
    # OBSERVATION about what the vendors said. The council package carries no
    # approve/reject/score/majority/consensus field on purpose -- absence of the
    # field is the control, not a docstring -- and a rendering that reintroduces
    # the word structurally reintroduces the temptation to read it as a verdict.
    # The legacy aliases are kept only so an older payload still renders.
    convergence = _text(_field(verdict, "convergence", "converged", "agreement",
                               "majority", "majority_position", default=""))
    advisory = _field(verdict, "advisory", default=None)
    answered, requested, answered_v, missing = _quorum_counts(verdict)

    lines: list[str] = []
    lines.append(f"# Council verdict -- {question}")
    lines.append("")
    lines.append(f"**Outcome: {outcome}**")
    lines.append("")

    # The advisory banner is UNCONDITIONAL. A verdict arriving without the marker
    # is a contract violation, so we say so instead of quietly rendering it as if
    # it carried authority.
    lines.append("**ADVISORY ONLY -- this verdict promotes nothing. "
                 "THE GATE DECIDES, NOT A MODEL.**")
    if advisory is not True:
        lines.append("")
        lines.append(f"> [!CAUTION]"
                     f"\n> This verdict arrived with `advisory={advisory!r}`, not `True`. "
                     f"It is treated as ADVISORY regardless: nothing here promotes, "
                     f"merges, or gates anything.")
    lines.append("")

    # Quorum honesty, at the top. A short council is a weaker signal and that
    # must be impossible to miss -- it is a warning block, not a footnote.
    if requested and answered < requested:
        missing_txt = ", ".join(missing) if missing else "not recorded"
        lines.append("> [!WARNING]")
        lines.append(f"> **{DEGRADED_QUORUM_MARKER} -- {answered} of {requested} "
                     f"requested vendors answered.**")
        lines.append(f"> Did not answer: {missing_txt}. This deliberation is a "
                     f"WEAKER signal than a full council: the absent vendors' "
                     f"independence is exactly what the roster buys, and it was "
                     f"not obtained here.")
    else:
        lines.append(f"**Quorum: {answered} of {requested} requested vendors "
                     f"answered** (full roster).")
    if answered_v:
        lines.append("")
        lines.append(f"Answered: {', '.join(answered_v)}.")
    lines.append("")

    # DISSENT LEADS. Not a stylistic choice: the dissent is the only content in
    # this document that could not have been produced by asking one model twice.
    # Convergence among vendors with overlapping training data is cheap; the
    # objection is what four egress paths were actually paid for. Rendering it
    # after -- and therefore below -- the agreement makes the informative half
    # read as a footnote to the uninformative half.
    dissents = _as_list(_field(verdict, "dissents", "dissent", default=[]))
    lines.append(f"## Dissents ({len(dissents)})")
    lines.append("")
    if not dissents:
        lines.append("_No vendor dissented. Note that unanimity among models "
                     "sharing training data is not independent confirmation._")
        lines.append("")
    for item in dissents:
        if isinstance(item, (str, bytes)):
            author, text, model = "(unattributed)", _text(item), ""
        else:
            author = _text(_field(item, "author", "vendor", "actor", "agent",
                                  "name", default="(unattributed)"))
            text = _text(_field(item, "text", "position", "body", "content",
                                default=""))
            model = _text(_field(item, "model", default=""))
        heading = f"### Dissent -- {author}"
        if model:
            heading += f" (`{model}`)"
        lines.append(heading)
        lines.append("")
        # A vendor that did not speak has no content; an empty fence is noise
        # that makes a silent turn look like an empty answer.
        if text:
            lines.append(_verbatim(text))
            lines.append("")

    lines.append("## Where the vendors converged")
    lines.append("")
    if convergence:
        lines.append(_verbatim(convergence))
    else:
        lines.append("_(no convergence recorded)_")
    lines.append("")
    lines.append("_Convergence is an OBSERVATION about what these vendors said, "
                 "not a decision and not a vote. Models with overlapping training "
                 "data agreeing is not independent confirmation, and nothing here "
                 "counts as a passed gate._")
    lines.append("")

    # Evidence digests: what was actually deliberated over, by hash.
    evidence = _as_list(_field(verdict, "evidence", "evidence_digests", default=[]))
    lines.append("## Evidence")
    lines.append("")
    if not evidence:
        lines.append("_No evidence digests recorded._")
        lines.append("")
    else:
        lines.append("| evidence | sha256 |")
        lines.append("| --- | --- |")
        for item in evidence:
            if isinstance(item, (str, bytes)):
                lines.append(f"| {_text(item)} | (no digest) |")
                continue
            label = _text(_field(item, "label", "name", "path", "file",
                                 default="(unlabelled)"))
            digest = _text(_field(item, "sha256", "sha", "digest", "hash",
                                  default=""))
            lines.append(f"| {label} | `{digest or '(no digest)'}` |")
        lines.append("")

    # Per-vendor cost and latency: what the opinion cost, per independent voice.
    stats = _as_list(_field(verdict, "vendor_stats", "costs", "usage",
                            "per_vendor", default=[]))
    lines.append("## Cost and latency")
    lines.append("")
    if not stats:
        lines.append("_No per-vendor cost/latency recorded._")
        lines.append("")
    else:
        lines.append("| vendor | model | cost (USD) | latency (s) |")
        lines.append("| --- | --- | --- | --- |")
        for row in stats:
            vendor = _text(_field(row, "vendor", "name", "author",
                                  default="(unnamed)"))
            model = _text(_field(row, "model", default=""))
            cost = _field(row, "cost_usd", "cost", default=None)
            latency = _field(row, "latency_s", "latency", "elapsed_s",
                             default=None)
            cost_txt = "n/a" if cost is None else _text(cost)
            lat_txt = "n/a" if latency is None else _text(latency)
            lines.append(f"| {vendor} | {model or 'n/a'} | {cost_txt} | {lat_txt} |")
        lines.append("")

    # The deliberation itself -- this comment IS the rendering of the bus.
    turns = _turns_of(transcript)
    lines.append(f"## Deliberation ({len(turns)} "
                 f"{'turn' if len(turns) == 1 else 'turns'})")
    lines.append("")
    if not turns:
        lines.append("_No turns rendered; read the bus file directly._")
        lines.append("")
    for turn in turns:
        author = _text(_field(turn, "author", "vendor", "actor", "agent", "role",
                              default="(unattributed)"))
        ts = _text(_field(turn, "ts", "timestamp", "created_at", default=""))
        sha = _short(_field(turn, "entry_sha", "sha", "digest", default=""))
        text = _text(_field(turn, "text", "body", "content", "message", default=""))
        stamp = " ".join(x for x in (ts, f"`{sha}`" if sha else "") if x)
        lines.append(f"**{author}**{(' -- ' + stamp) if stamp else ''}")
        # A turn that did not SPEAK is the quorum honesty story at turn level:
        # bus.py records "refused" / "unavailable" / "budget_exhausted" /
        # "anomaly" rather than dropping the vendor, so rendering the status is
        # the difference between "three vendors agreed" and "one was never asked".
        status = _text(_field(turn, "status", default=""))
        if status and status != "spoke":
            lines.append("")
            reason = _text(_field(turn, "reason", default=""))
            lines.append(f"> [!NOTE]"
                         f"\n> This vendor did not speak: `{status}`"
                         f"{(' -- ' + reason) if reason else ''}.")
        # Paths an egress lane declined to send are NAMED, not counted -- a
        # vendor reasoning over less evidence than the others is not an equal
        # voice, and hiding that would make the roster look stronger than it was.
        withheld = [_text(w) for w in _as_list(_field(turn, "withheld", default=[]))]
        if withheld:
            lines.append("")
            lines.append(f"> [!NOTE]"
                         f"\n> Withheld from this vendor by the egress gate: "
                         f"{', '.join('`' + w + '`' for w in withheld)}. It "
                         f"reasoned over less evidence than the others.")
        lines.append("")
        lines.append(_verbatim(text))
        lines.append("")

    # Provenance footer: how to check this rendering against the record.
    bus_path = _bus_path(verdict, transcript)
    head = _chain_head(verdict, transcript)
    lines.append("---")
    lines.append("")
    lines.append("## Verify this offline")
    lines.append("")
    lines.append(f"- council id: `{council_id}`")
    lines.append(f"- canonical bus (append-only, hash-chained): `{bus_path}`")
    lines.append(f"- chain head: `{head or '(not recorded)'}`")
    lines.append("")
    lines.append("This comment is a RENDERING. The bus file is the record: it is "
                 "append-only and hash-chained, so a tampered or truncated "
                 "transcript is detectable and this comment is not. If the two "
                 "disagree, the bus is right.")
    lines.append("")
    lines.append("_Advisory. No gate was passed, nothing was promoted, and no "
                 "model decided anything._")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# egress gate                                                                  #
# --------------------------------------------------------------------------- #
def screen_egress(channels: Mapping[str, str],
                  paths: Sequence[str] = ()) -> tuple[str, str] | None:
    """Run the unconditional secret floor over everything bound for GitHub.

    Returns ``(channel, rule)`` for the FIRST hit, or None if clean. The returned
    rule is a fixed label / path fragment from ``sensitivity`` -- never matched
    text, so a refusal can be logged and reported without re-leaking the secret
    it refused (memstore's ``_scan_secret`` posture, same floor, same reason)."""
    for p in paths:
        if not p:
            continue
        hit = secret_floor_rule(str(p), "")
        if hit:
            return (f"evidence path {p!r}", hit)
    for channel, text in channels.items():
        if not text:
            continue
        hit = secret_floor_rule(_EGRESS_HINT, str(text))
        if hit:
            return (channel, hit)
    return None


def _gh_argv(base: list[str], repo: str | None) -> list[str]:
    return base + (["--repo", str(repo)] if repo else [])


def _classify_failure(result: RunResult) -> tuple[str, str]:
    """Map a failed gh invocation to (status, detail). Order matters.

    Auth is tested before not-found because GitHub answers 404 -- not 403 -- for a
    private repo you are not authenticated to see; classifying that as
    ``pr_not_found`` would send an operator hunting for a PR that exists and is
    merely invisible to a logged-out CLI."""
    blob = f"{result.stderr}\n{result.stdout}".lower()
    if result.returncode == 127 or any(m in blob for m in (
            "command not found", "not recognized as an internal",
            "no such file or directory", "executable file not found",
            "gh not found", "could not be launched", "winerror 2")):
        return STATUS_GH_MISSING, (result.stderr or "gh is not installed or not on PATH").strip()
    if any(m in blob for m in (
            "gh auth login", "not logged in", "not logged into",
            "authentication required", "requires authentication",
            "bad credentials", "unauthorized", "401", "no valid oauth token",
            "authentication failed")):
        return STATUS_GH_UNAUTHENTICATED, (result.stderr or "gh is not authenticated").strip()
    if any(m in blob for m in (
            "rate limit", "secondary rate limit", "abuse detection",
            "too many requests", "429", "retry-after")):
        return STATUS_RATE_LIMITED, (result.stderr or "GitHub rate limit hit").strip()
    if any(m in blob for m in (
            "could not resolve to a pullrequest", "could not resolve to a pull request",
            "no pull requests found", "no such pull request", "not found", "404")):
        return STATUS_PR_NOT_FOUND, (result.stderr or "no such pull request").strip()
    return STATUS_GH_ERROR, (result.stderr or result.stdout or
                             f"gh exited {result.returncode}").strip()


def _first_url(text: str) -> str:
    for token in (text or "").split():
        if token.startswith("http://") or token.startswith("https://"):
            return token.strip()
    return ""


# --------------------------------------------------------------------------- #
# publish_to_pr -- the outbound half                                           #
# --------------------------------------------------------------------------- #
def publish_to_pr(verdict: Any,
                  transcript: Any = None,
                  pr: str | int = "",
                  repo: str | None = None,
                  *,
                  runner: Runner | None = None,
                  dry_run: bool = False) -> PublishResult:
    """Render the deliberation and post it as a PR comment. Never raises for an
    operational failure -- every outcome is a status in ``PUBLISH_STATUSES``.

    ``dry_run=True`` renders and gates but does NOT invoke the runner at all; the
    markdown comes back on the result. The gate still runs, so a dry run is an
    honest rehearsal rather than a way around the floor.

    The body goes to gh on STDIN via ``--body-file -``: a deliberation exceeds the
    Windows argv limit, and stdin keeps the payload inspectable by a fake runner
    in tests exactly as argv would be."""
    body = render_markdown(verdict, transcript)

    # EGRESS GATE. Runs before the runner exists as far as this function is
    # concerned -- on refusal we return without ever constructing a call.
    hit = screen_egress(
        {
            "council comment body": body,
            "pr reference": _text(pr),
            "repo slug": _text(repo),
        },
        paths=_evidence_paths(verdict),
    )
    if hit:
        channel, rule = hit
        return PublishResult(
            status=STATUS_REFUSED_SECRET,
            # Channel + rule name only. The matched text is never echoed, and the
            # markdown is withheld so a caller cannot log the refused body.
            detail=(f"secret floor fired on {channel}: {rule}. Nothing was sent "
                    f"to GitHub; the bus remains the canonical record."),
        )

    if dry_run:
        return PublishResult(status=STATUS_DRY_RUN, markdown=body,
                             detail="dry run: gh was not invoked")

    if not _text(pr):
        return PublishResult(
            status=STATUS_PR_NOT_FOUND,
            detail="no PR reference given; nothing to comment on")

    run = runner or _subprocess_runner
    argv = _gh_argv(["gh", "pr", "comment", _text(pr), "--body-file", "-"], repo)
    result = run(argv, body)
    if result.returncode != 0:
        status, detail = _classify_failure(result)
        return PublishResult(status=status, detail=detail)
    return PublishResult(status=STATUS_PUBLISHED, markdown=body,
                         comment_url=_first_url(result.stdout),
                         detail="comment posted; the bus remains canonical")


# --------------------------------------------------------------------------- #
# read_pr_thread -- the inbound (async-channel) half                           #
# --------------------------------------------------------------------------- #
def read_pr_thread(pr: str | int = "",
                   repo: str | None = None,
                   *,
                   runner: Runner | None = None) -> ThreadResult:
    """Read the PR's comments back as structured turns, so a later council round
    can consume what a human or another agent replied.

    Never raises for an operational failure; every outcome is a status in
    ``READ_STATUSES``. Nothing read here is authoritative: a reply is INPUT to a
    later round, not a verdict, and it is not on the hash-chained bus until the
    council appends it there."""
    hit = screen_egress({"pr reference": _text(pr), "repo slug": _text(repo)})
    if hit:
        channel, rule = hit
        return ThreadResult(
            status=STATUS_REFUSED_SECRET,
            detail=f"secret floor fired on {channel}: {rule}. gh was not invoked.")
    if not _text(pr):
        return ThreadResult(status=STATUS_PR_NOT_FOUND,
                            detail="no PR reference given; nothing to read")

    run = runner or _subprocess_runner
    argv = _gh_argv(["gh", "pr", "view", _text(pr), "--json", "comments"], repo)
    result = run(argv, None)
    if result.returncode != 0:
        status, detail = _classify_failure(result)
        return ThreadResult(status=status, detail=detail)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return ThreadResult(status=STATUS_BAD_PAYLOAD,
                            detail=f"gh returned unparseable JSON: {exc}")
    if not isinstance(payload, Mapping):
        return ThreadResult(status=STATUS_BAD_PAYLOAD,
                            detail="gh returned JSON that is not an object")
    turns = tuple(_parse_comment(c) for c in _as_list(payload.get("comments")))
    return ThreadResult(status=STATUS_READ_OK, turns=turns,
                        detail=f"{len(turns)} comment(s) read")


def _parse_comment(raw: Any) -> PRTurn:
    """One gh comment object -> one PRTurn. Tolerant of the two author shapes gh
    uses (``author.login`` from the GraphQL-backed ``pr view --json``,
    ``user.login`` from the REST-backed ``gh api``)."""
    author_obj = _field(raw, "author", "user", default=None)
    if isinstance(author_obj, (str, bytes)):
        author = _text(author_obj)
    else:
        author = _text(_field(author_obj, "login", "name", default="(unknown)"))
    return PRTurn(
        author=author or "(unknown)",
        created_at=_text(_field(raw, "createdAt", "created_at", "ts", default="")),
        body=_text(_field(raw, "body", "text", default="")),
        url=_text(_field(raw, "url", "html_url", default="")),
    )
