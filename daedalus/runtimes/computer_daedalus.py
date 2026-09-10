"""Read-only Daedalus observations for the Ikarus computer loop (G1-IKARUS-46).

Until this module existed the computer loop could observe a workspace, a
browser origin and a desktop window, but not the project the chat is bound
to: the assistant that is supposed to run Daedalus had no tool that looked at
Daedalus. These five observations close that gap without opening an effect:

* ``daedalus.status``     -- the registered project's git counters and the
                            file-bridge queue/watcher facts;
* ``daedalus.structure``  -- the structcore summary (hotspots, clone
                            clusters, fan-in) of the project;
* ``daedalus.slice``      -- the distilled semantic slice of one module,
                            through the SAME egress gate the Voice uses;
* ``daedalus.docrefs``    -- documentation references the repository's own
                            resolver calls broken (``spine.docrefs``);
* ``daedalus.tasks``      -- recent file-bridge reports of the project.

WHAT THEY DO ON THE HOST. Nothing in the workspace or the project tree is
written, moved, launched or sent by this module: the structcore index is
built ``effect_free`` (no SQLite cache write or eviction under the profile,
no process pool, no churn ``git log``), and the status reader runs the
repository's ``git branch`` / ``git status`` exactly as the dashboard does --
read-only commands, though ``git status`` may refresh git's own index file
(Cerberus N8). The service records every result with ``host_mutation``
False and scope ``project-registry-read-only``.

WHAT THEY SEND. Every observation is the planner's prompt, so with a remote
planner it leaves the machine. That is why EVERY observation, not only the
slice, passes the project's egress gate before it is returned: each path
and each text fragment goes through ``sensitivity.slice_egress_rule`` on the
planner's lane -- the unconditional secret floor on every lane, plus the
project's default-deny allow-list and ``deny_content`` words (from
``projects/<name>.json``) on the untrusted lane. Withheld rows are counted,
never silently dropped. Every value is rendered ONCE and gated on that
rendering; an absolute-location shape refuses a field (``_looks_like_host_path``,
``_mentions_host_path``) and is redacted span by span inside the slice text
(``_redact_host_paths``, counted); reader and producer failures are refused by
class name only; ``docrefs`` scanner errors are reported as a count only.
Cerberus review of 2026-09-10 found the first draft gating the slice alone;
nine review rounds later this is the repair.

The lane is decided per call by :func:`planner_lane` from the owner-configured
planner: a loopback Ollama or the Claude CLI is ``trusted`` (the same answer
the chat gives in ``shell._llm``); Codex and DeepSeek are ``untrusted``.
``allow_remote_context`` never promotes a destination. The observations read
the REGISTERED project (``projects/<name>.json``) that the conversation
selected; a session without a bound project cannot execute them, an unknown
project is a refusal, and a project whose policy row cannot be loaded is a
refusal too -- never the generic policy.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, DAEDALUS_TOOLS


@dataclass(frozen=True)
class ProjectReaders:
    """The three project readers the service hands in.

    ``daedalus.status`` (git counters, queue) and ``daedalus.file_bridge``
    (report briefs) already sit inside the repository's largest import cycle
    with ``runtimes.computer``; importing them here would pull this adapter
    into that cycle (MEASURED 2026-09-10 by the SCC census: 19 -> 21 modules).
    The orchestration layer, which is in the cycle already, supplies them;
    this module names no orchestration, bridge or status module.
    """

    git_counters: Callable[[str], Mapping[str, Any]]
    bridge_status: Callable[[str | None], Mapping[str, Any]]
    report_briefs: Callable[[str | None], list]


#: Neighbourhood budget for one slice observation. Smaller than the Voice's
#: 12k because the loop keeps every observation in its prompt history.
SLICE_MAX_TOKENS = 6000
#: Hard cap on any text field that reaches the planner through an observation.
MAX_TEXT_CHARS = 24_000
#: Rows per list in structure/docrefs/tasks observations.
TOP = 10
#: git counters are read with this timeout; a hung git is a refusal, not a wait.
GIT_TIMEOUT_S = 15.0
_TRUSTED_PLANNERS = frozenset({"claude_code_cli"})
_LOCAL_PLANNERS = frozenset({"ollama_http", "ollama"})


def planner_host_for(provider: object) -> str | None:
    """The address a LOCAL planner connects to -- the raw ``OLLAMA_HOST`` value,
    exactly as ``shell._local_lane`` passes it, so the predicates own the wire
    grammar (``[::1]`` included). ``None`` for every other planner."""
    if provider in _LOCAL_PLANNERS:
        from daedalus.providers.ollama import DEFAULT_HOST
        return os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    return None


def planner_host(policy: ComputerPolicy) -> str | None:
    return planner_host_for(policy.planner_provider)


def planner_leaves_machine_for(provider: object) -> bool:
    """:func:`planner_leaves_machine` for a bare provider name -- the status
    line, the mission report and the chat offer only know the name (Cerberus
    round 5: those three surfaces derived "Kontext hat den Rechner verlassen"
    from the consent flag, so a tailnet Ollama read *nein*)."""
    host = planner_host_for(provider)
    if host is None:
        return True
    from daedalus.sensitivity import is_loopback_host
    return not is_loopback_host(host)


def planner_lane(policy: ComputerPolicy) -> str:
    """The egress lane of the configured planner: ``trusted`` or ``untrusted``.

    A local Ollama is trusted only when ``OLLAMA_HOST`` is this machine or an
    address the owner declared in ``DAEDALUS_TRUSTED_HOSTS``
    (``sensitivity.lane_for_host``, the one implementation of that question);
    the Claude CLI is trusted-with-IP exactly as in ``shell._llm``; every other
    planner is untrusted. ``allow_remote_context`` does not widen this: it
    admits that observations leave the machine, it does not promote the
    destination to a trusted one. The lane answers CONSENT (which filter
    applies); whether bytes cross a wire is :func:`planner_leaves_machine`.
    """
    host = planner_host(policy)
    if host is not None:
        from daedalus.sensitivity import lane_for_host
        return lane_for_host(host)
    if policy.planner_provider in _TRUSTED_PLANNERS:
        return "trusted"
    return "untrusted"


def planner_leaves_machine(policy: ComputerPolicy) -> bool:
    """Whether an observation handed to the planner crosses a wire -- physics,
    not consent. Cerberus round 4 (H3): an owner's ``DAEDALUS_TRUSTED_HOSTS``
    entry makes a tailnet bench a TRUSTED lane (only the secret floor filters),
    and the grant then said "nothing leaves this machine" while packets crossed
    the tunnel. ``sensitivity.is_loopback_host`` cannot be widened by any
    declaration; a remote vendor planner always leaves."""
    return planner_leaves_machine_for(policy.planner_provider)


def _looks_like_host_path(value: str) -> bool:
    """An absolute Windows or POSIX path (``C:\\…``, ``\\\\server``, ``/home/…``)."""
    text = value.strip()
    if not text:
        return False
    if os.path.isabs(text):
        return True
    # ``os.path.isabs`` is host-specific; the observation must not depend on
    # which host renders it, so both spellings are refused everywhere.
    return bool(len(text) > 2 and text[1] == ":" and text[2] in "\\/") or text.startswith(("\\\\", "/"))


#: An absolute host path EMBEDDED in longer text (an error message, a task
#: summary): a drive spelling, a UNC prefix, or a POSIX home/system root.
#: Odysseus 2026-09-10 (defect 3): the whole-value check above let
#: ``"…: PermissionError: 'C:\\Users\\…'"`` through.
#: Odysseus round 2 (D3) widened this from a root-name list to the SHAPES of
#: an absolute location: a drive (``C:\``, ``C:/``), a UNC in either slash
#: direction (``\\nas\``, ``//nas/``), a ``file://`` URL, ``~/``, an expanded
#: environment root (``%USERPROFILE%\``, ``${HOME}/``, ``$env:X\``), a
#: scheme'd host URL (``file://``, ``smb://``, ``https://`` -- withheld, the
#: safe direction for a text that names a host), or any POSIX absolute path
#: (``/usr/lib/x``, ``/proc/self/environ``, a bare ``/etc``). A repository-
#: relative spelling such as ``pkg/mod.py``, ``docs/a.md -> docs/b.md`` or
#: ``50/50`` has no leading separator and is not matched; a root-anchored
#: markdown link (``](/docs/x.md)``) is, and lands in the withheld count.
_EMBEDDED_HOST_PATH = re.compile(
    r"[A-Za-z]:[\\/](?!/)"                      # drive, anywhere (``checkoutC:\``; not the ``p://`` of a URL scheme)
    r"|(?<![A-Za-z0-9])[A-Z]:[A-Za-z_.]"        # drive-relative (``C:temp\x``; Cerberus round 3)
    r"|\\\\[^\s\\]+"                            # UNC host, with or without a share
    r"|(?<![A-Za-z0-9:_.\\/-])//[^\s/]+/"      # UNC, forward slashes
    r"|\b[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/'\"<>()\[\]{},;|]+|(?=/))"  # any scheme'd URL with a host or a path (file:///, smb://, https://)
    r"|(?<![A-Za-z0-9])~[^\s/\\]*[\\/]"         # home shorthand, ``~/`` or ``~user/``
    r"|%[A-Za-z_][A-Za-z0-9_]*%[\\/]"           # expanded Windows environment root
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?[\\/]"     # expanded POSIX environment root, ``$HOME/`` or ``${HOME}/``
    r"|\$env:[A-Za-z_][A-Za-z0-9_]*[\\/]"       # PowerShell environment root
    # POSIX absolute path, any first segment: the slash may follow ANY character
    # that is not itself part of a path token (Odysseus round 8, D29: ``{``,
    # ``|``, ``*``, ``&`` and ``@`` before the slash slipped past a fixed list).
    r"|(?:^|(?<=[^A-Za-z0-9_.\\/-]))/[^\s/\\'\"()<>\[\]{},;:|*&@]+(?=[\\/\s'\")\]>}|,;:*&@]|$)"
)


#: The SHAPE of a withheld block: a banner comment whose first word after the
#: comment markers and any rule characters is "withheld", the comment lines
#: under it, and a per-file breadcrumb naming a file, a rule in parentheses and
#: a ROLE in brackets. Used on ONE narrow path (see ``_slice``): a text the
#: adapter's own bound truncated, which therefore cannot contain the slicer's
#: own block unless that block diverged from the pinned spelling AND sat in the
#: head. Matching the bare word instead deleted ordinary source lines -- this
#: adapter, the slicer and 75 other tracked modules talk about withholding --
#: and counted them as withheld (Cerberus round 12, F-2).
_WITHHELD_BANNER = re.compile(r"^\s*#+[\s=*#~<>|-]*withheld\b", re.IGNORECASE)
_BREADCRUMB = re.compile(r"^\s*#\s*\S+\s+\(.*\)\s+\[[^\]]*\]\s*$")
_COMMENT_LINE = re.compile(r"^\s*#")


def _mentions_host_path(text: str) -> bool:
    return bool(_EMBEDDED_HOST_PATH.search(text or ""))


_PATH_TOKEN_END = frozenset(" \t\r\n'\"()<>[]{},;|*&")
#: A backtick is a QUOTE, not a token end. A markdown code span says where the
#: path stops -- a backtick-quoted absolute path in a docstring is the
#: producer-reachable case -- while a backtick INSIDE a token must not stop the
#: walk: ending the token there left the rest of the path raw where round 9 had
#: redacted through it (Cerberus round 10, F2).
_QUOTES = frozenset("'\"`")
_LEADING_DELIMITERS = _PATH_TOKEN_END | _QUOTES | frozenset("=:@")
#: How many space-separated runs the unquoted continuation may look ahead over:
#: two, so exactly ONE separator-free run is bridged (``C:\\Users\\First Last\\x``,
#: ``C:\\Users\\Jean Luc Picard\\x``). See the residue named in the docstring.
_SPACE_LOOKAHEAD = 2


def _walk_token(text: str, end: int) -> int:
    """Where an unquoted path token ends: at the next token-end character, then
    across a space while a run within the lookahead still carries a separator.

    Both the quoted and the unquoted branch use this walk -- an opening quote
    whose closing partner never arrives must not make the redaction SHORTER
    than it would be without the quote (measured against the round-9 function:
    104 of 200 000 generated inputs, every one a path behind an unclosed
    backtick).
    """
    while end < len(text) and text[end] not in _PATH_TOKEN_END:
        end += 1
    # An UNQUOTED path with spaces (``C:\\Users\\First Last\\x``,
    # ``C:\\Program Files\\nodejs\\npx.cmd`` in a docstring) continues
    # while a run within the lookahead still carries a separator
    # (Odysseus round 9, D31: the surname after the space survived;
    # Cerberus round 10, F1: a separator-free run in the MIDDLE of the
    # path -- ``Jean Luc Picard\\Desktop\\x`` -- stopped the walk).
    while end < len(text) and text[end] == " ":
        bridged = None
        probe = end
        for _ in range(_SPACE_LOOKAHEAD):
            if probe >= len(text) or text[probe] != " ":
                break
            stop = probe + 1
            while stop < len(text) and text[stop] not in _PATH_TOKEN_END:
                stop += 1
            run = text[probe + 1:stop]
            if not run:
                break
            if "\\" in run or "/" in run:
                bridged = stop
                break
            probe = stop
        if bridged is None:
            break
        end = bridged
    return end


def _redact_host_paths(text: str) -> tuple[str, int]:
    """Replace every absolute-location shape in a text by ``<host-path>`` and
    return the text and the number of spans replaced.

    The detector matches the SHAPE (a drive, a UNC head, a first segment);
    redaction must cover the whole token, so each match is extended to the
    next whitespace, quote or bracket, and a leading delimiter the shape
    matched is kept.

    Named residue (Cerberus round 10, F1; the pinning test is
    ``test_the_tail_of_an_unquoted_path_after_two_separator_free_words``):
    an unquoted path whose remaining segments are TWO OR MORE consecutive
    separator-free runs, or whose last segment carries no separator and no
    closing quote (``see C:\\Users\\First Last``), is redacted only to where
    the lookahead reaches; the trailing run survives. Extending further would
    swallow the prose after every path. Quoted, backtick-quoted and
    single-bridge spellings are covered. Two adjacent paths merge into one
    span, so the returned number counts SPANS, not paths.
    """
    text = text or ""
    out: list[str] = []
    cursor = 0
    count = 0
    for match in _EMBEDDED_HOST_PATH.finditer(text):
        start = match.start()
        while start < match.end() and text[start] in _LEADING_DELIMITERS:
            start += 1
        if start < cursor:
            continue
        end = max(match.end(), start)
        # Inside a quoted string the token runs to the closing quote -- a path
        # with a space (``C:\\Program Files\\…``, ``C:\\Users\\First Last\\…``)
        # otherwise leaked its later segments (Odysseus round 8, D28).
        quote = text[start - 1] if start > 0 and text[start - 1] in _QUOTES else None
        if quote is not None:
            close = text.find(quote, end)
            newline = text.find("\n", end)
            end = close if close != -1 and (newline == -1 or close < newline) else _walk_token(text, end)
        else:
            end = _walk_token(text, end)
        out.append(text[cursor:start])
        out.append("<host-path>")
        cursor = end
        count += 1
    out.append(text[cursor:])
    return "".join(out), count


_MODULE_UNAVAILABLE = ("module is not available to this planner: not in the project's index or withheld by "
                       "the egress gate; name an indexed source file")
#: The slicer's withheld block header; the block is kept LAST in the slice
#: text and every line after it is a per-file breadcrumb ``# <file>  (<rule>)
#: [<role>]`` (structcore/slice.py). Both name what the project withholds, so
#: the block is REBUILT from the gated rows -- no file-name grammar (spaces,
#: CRLF) can slip a name past a regex (Odysseus round 4, D12).
_WITHHELD_HEADER = "# ===== WITHHELD (egress gate) ====="
_TRIMMED_MARKER = "# ===== CONTEXT TRIMMED"
#: Every rule string the gate returns quotes what it fired on: ``<path>:
#: denylisted path fragment '<fragment>'``, ``<path>: path not on the external
#: allow-list (default-deny)``, ``content matches sensitive marker
#: /<pattern>/``, ``secret path marker '<fragment>'``, ``secret content:
#: <label>`` (sensitivity.py). The withheld path, the project's own deny
#: fragment and the marker word are exactly what must not travel (Odysseus
#: round 4, D9: the round-3 redaction knew one of the five shapes). Only a
#: fixed class leaves; the rule text never does.
_RULE_CLASSES = (("secret path marker", "secret_path"), ("secret content", "secret_content"),
                 ("denylisted path fragment", "denylisted_path"), ("default-deny", "default_deny"),
                 ("sensitive marker", "deny_content"))


def _rule_class(rule: object) -> str:
    text = str(rule)
    for needle, label in _RULE_CLASSES:
        if needle in text:
            return label
    return "egress_rule"


class _Unrenderable(Exception):
    """A value ``_json_safe`` cannot serialise (NaN, a non-string dict key, an
    object whose ``str()`` raises): withheld and counted, never a crash out of
    the observation (Odysseus round 5, D16)."""


def _strings_in(value: Any) -> list[str]:
    """Every string a value hands on once ``_json_safe`` serialises it.

    The value is RENDERED first, through the very same ``json.dumps`` call
    ``_json_safe`` makes (same ``default`` hook, same flags), and the strings
    are read off the rendering: a set has no JSON form, so the hook emits the
    whole container as one text built from element ``repr()``s -- gating the
    elements' ``str()`` (round 4) missed a ``Path`` whose repr carries the
    host path (Odysseus round 5, D14). One renderer, so what is gated is
    byte-for-byte what leaves (Cerberus round 6: a separate decode pass let a
    non-dict Mapping with its own ``__repr__`` diverge).
    """
    return _rendered_strings(_render_value(value))


def _render_value(value: Any) -> Any:
    """The JSON-native form of a value -- rendered ONCE. The gate reads its
    strings off this form and the observation EMITS this form, so a value whose
    ``str()`` changes between two calls cannot be gated as one text and emitted
    as another (Odysseus round 6, D20)."""
    try:
        return json.loads(_render(value))
    except Exception as exc:  # noqa: BLE001 - the hook runs foreign __str__ code; any failure withholds
        raise _Unrenderable(f"{type(exc).__name__}: {exc}"[:200]) from exc


def _render_default(value: Any) -> str:
    """The one ``default`` hook: bytes as their decoded text, everything else
    as ``str()`` -- what a planner or a retained artifact would see."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_render_default, allow_nan=False)


def _rendered_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in _rendered_strings(key) + _rendered_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _rendered_strings(item)]
    return []


def _bounded_text(value: object, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[:limit], True
    return text, False


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so the observation is exactly what is retained --
    through the same renderer the gate used."""
    return json.loads(_render(value))


def _status_line_paths(line: str) -> list[str]:
    """The path(s) named by one ``git status --short`` line (renames name two)."""
    body = line[3:] if len(line) > 3 else line
    body = body.strip()
    if " -> " in body:
        return [part.strip() for part in body.split(" -> ") if part.strip()]
    return [body] if body else []


class DaedalusObservation:
    """The five read-only project observations behind one dispatch seam."""

    def __init__(self, policy: ComputerPolicy, project: str | None,
                 checkpoint: Callable[[], None], authority_root: Path,
                 readers: ProjectReaders) -> None:
        if project is not None and (not isinstance(project, str) or not project.strip()):
            raise ComputerRefused("computer session project must be a non-empty name")
        if not isinstance(readers, ProjectReaders):
            raise ComputerRefused("project readers must be supplied by the computer service")
        self._readers = readers
        self._policy = policy
        self._project = project.strip() if isinstance(project, str) else None
        self._checkpoint = checkpoint
        self._authority_root = Path(authority_root)
        self._index: dict | None = None

    # ------------------------------------------------------------------ project
    @property
    def project(self) -> str | None:
        return self._project

    @property
    def lane(self) -> str:
        """Re-derived on every read: an ``OLLAMA_HOST`` that stops being
        loopback mid-task must not keep a stale ``trusted`` verdict (Cerberus m-2)."""
        return planner_lane(self._policy)

    def _repo_root(self) -> str:
        if self._project is None:
            raise ComputerRefused("computer session has no registered project; run it from a project conversation")
        from daedalus.foundation.projects import resolve_repo_root
        try:
            return resolve_repo_root(None, self._project)
        except Exception as exc:  # unknown row, unreadable registry, unsafe root
            # Class only: the message may carry the registry file's host path
            # (Odysseus round 7, D25; Cerberus round 7, L3).
            raise ComputerRefused(f"project is not registered or unreadable: {type(exc).__name__}") from exc

    def _project_policy(self):
        """The project's egress policy, re-read on every call -- refused, never
        the generic one, when the registry row cannot be read (Cerberus m-4);
        never memoised, so a row tightened mid-mission takes effect (N5)."""
        from daedalus.foundation.projects import load_project
        from daedalus.sensitivity import load_policy
        try:
            config = load_project(self._project or "")
        except Exception as exc:
            raise ComputerRefused(f"project policy is unavailable: {type(exc).__name__}") from exc
        try:
            return load_policy(config)
        except Exception as exc:  # noqa: BLE001 - a malformed row is a refusal naming the class
            raise ComputerRefused(f"project policy is unavailable: {type(exc).__name__}") from exc

    # ------------------------------------------------------------------ egress gate
    def _admit(self, path: str, text: str = "") -> bool:
        """May this path/text reach the planner on the current lane?

        The Voice's own gate, ``sensitivity.slice_egress_rule``: the secret
        floor on every lane; the project's default-deny allow-list and
        ``deny_content`` words on the untrusted lane. Called per row, so one
        withheld row is attributable and never poisons the observation.
        """
        from daedalus.sensitivity import slice_egress_rule
        if _looks_like_host_path(path) or _mentions_host_path(text) or _mentions_host_path(path):
            return False
        # The path itself is also content: ``classify_data`` applies the
        # project's ``deny_content`` markers to the TEXT argument only, so a
        # codename inside an allow-listed path would pass without this
        # (Odysseus round 2, D2).
        return slice_egress_rule(path, f"{path} {text}".strip(), lane=self.lane,
                                 policy=self._project_policy()) is None

    def _admit_text(self, text: str) -> bool:
        """May this path-less text (a clone name, a report summary) reach the planner?

        The secret floor on every lane; on the untrusted lane additionally the
        project's ``deny_content`` markers, exactly the content half of
        ``sensitivity.classify_data`` (the allow-list half needs a path and
        would refuse every synthetic name).
        """
        from daedalus.sensitivity import secret_floor_rule
        if _looks_like_host_path(text) or _mentions_host_path(text) or secret_floor_rule("observation.txt", text):
            return False
        if self.lane != "trusted":
            policy = self._project_policy()
            if any(pattern.search(text) for pattern in policy.deny_content):
                return False
        return True

    def _admit_rows(self, rows: Iterable[Mapping[str, Any]], path_keys: tuple[str, ...],
                    text_keys: tuple[str, ...] = (), *,
                    keep_keys: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], int]:
        """Keep the rows whose named paths and texts the gate admits; count the rest.

        Fail-closed: a row that names neither a path nor a text is withheld,
        not passed ungated (Cerberus N3). ``keep_keys`` projects each kept row
        to an allow-listed key set, so a field a producer adds later cannot
        join the planner's prompt silently (N4).
        """
        kept: list[dict[str, Any]] = []
        withheld = 0
        if not isinstance(rows, (list, tuple)):
            # A producer field that is not a list is withheld as one row, never
            # iterated into a crash (Odysseus round 8, D30: ``sites=None``).
            return kept, 1
        for row in rows:
            if not isinstance(row, Mapping):
                withheld += 1
                continue
            # The projected row is RENDERED once; its strings are gated and the
            # rendering is what is kept (D20). EVERY string that will be handed
            # on is gated, not only the named text keys: a kept field outside
            # ``text_keys`` (``phase`` on a task brief) carried a host path to
            # the planner (Odysseus round 2, D1).
            try:
                projected = {key: _render_value(row[key]) for key in keep_keys if key in row} if keep_keys \
                    else {str(key): _render_value(value) for key, value in row.items()}
            except _Unrenderable:
                withheld += 1
                continue
            paths = [str(row[key]) for key in path_keys if isinstance(row.get(key), str) and row.get(key)]
            # Without ``keep_keys`` the producer chose the KEY names too: they are
            # strings handed on and gated like the values (Cerberus round 7, L1).
            handed_on = [text for key, value in projected.items() if key not in path_keys
                         for text in _rendered_strings(value) + ([] if keep_keys else [key])]
            named = [str(row[key]) for key in text_keys if isinstance(row.get(key), str) and row.get(key)]
            text = " ".join(dict.fromkeys(named + handed_on))
            if not paths and not text:
                withheld += 1
                continue
            if (paths and not all(self._admit(path, text) for path in paths)) or (
                    not paths and not self._admit_text(text)):
                withheld += 1
                continue
            kept.append(projected)
        return kept, withheld

    def _cached_index(self, repo_root: str) -> dict:
        if self._index is None:
            from daedalus.structcore.index import cached_index
            self._checkpoint()
            # effect_free: no persistent cache write or eviction under the
            # profile, no process pool, no churn ``git log`` (Cerberus MAJOR 1).
            self._index = self._produce("index", lambda: cached_index(repo_root, effect_free=True))
            self._checkpoint()
        return self._index

    # ------------------------------------------------------------------ dispatch
    def execute(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool not in DAEDALUS_TOOLS:
            raise ComputerRefused("unknown Daedalus observation")
        if type(arguments) is not dict:
            raise ComputerRefused("tool arguments must be an object")
        self._checkpoint()
        handler = {
            "daedalus.status": self._status,
            "daedalus.structure": self._structure,
            "daedalus.slice": self._slice,
            "daedalus.docrefs": self._docrefs,
            "daedalus.tasks": self._tasks,
        }[tool]
        try:
            result = handler(arguments)
        except ComputerRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - consuming a foreign payload can raise; class only (D33)
            raise ComputerRefused(f"observation failed ({tool}): {type(exc).__name__}") from exc
        try:
            result.setdefault("kind", "observation")
            result.setdefault("project", self._project)
            result.setdefault("host_mutation", False)
            result.setdefault("lane", self.lane)
            return _json_safe(result)
        except ComputerRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - rendering the result is consumption too (round 10)
            raise ComputerRefused(f"observation failed ({tool}): {type(exc).__name__}") from exc

    # ------------------------------------------------------------------ tools
    def _status(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        git = self._produce("git counters", lambda: self._readers.git_counters(repo_root))
        if not isinstance(git, Mapping):
            raise ComputerRefused("observation producer failed (git counters): no mapping")
        self._checkpoint()
        bridge = self._produce("bridge status", lambda: self._readers.bridge_status(self._project))
        if not isinstance(bridge, Mapping):
            raise ComputerRefused("observation producer failed (bridge status): no mapping")
        queue_raw = {key: bridge.get(key) for key in (
            "queue_depth", "in_flight", "unread_count", "reports_total")}
        watcher = bridge.get("watcher") if isinstance(bridge.get("watcher"), dict) else {}
        queue_raw["watcher"] = watcher.get("state", "unknown")
        # Host paths never reach the planner: the registry row is the
        # projection, the absolute path is not part of the observation.
        # MEASURED 2026-09-10 (live run 3): ``collect_status`` also carries
        # ``todo_snapshot``, an absolute path. Every value is gated by SHAPE
        # through every string it would hand on -- a list, a dict, a set, a
        # Path or an exception included (Odysseus round 4, D10: the round-3
        # gate looked at str values only, so a list of paths passed).
        observed: dict[str, Any] = {}
        withheld_paths = 0
        withheld_fields = 0
        for key, value in git.items():
            if key == "repo_root":
                continue
            if key == "git_status" and isinstance(value, str):
                # Every line names a repository path: each goes through the
                # project's gate (``?? .env`` is floored on every lane; a
                # ``policy.deny`` path is withheld on the untrusted lane).
                kept_lines = []
                for line in value.splitlines():
                    paths = _status_line_paths(line)
                    if paths and all(self._admit(path, line) for path in paths):
                        kept_lines.append(line)
                    elif paths:
                        withheld_paths += 1
                observed[key] = "\n".join(kept_lines)
                continue
            admitted, rendered = self._gate_value(key, value)
            if admitted:
                observed[key] = rendered
            else:
                withheld_fields += 1
        observed["git_status_withheld"] = withheld_paths
        observed["fields_withheld"] = withheld_fields
        queue: dict[str, Any] = {}
        queue_withheld = 0
        for key, value in queue_raw.items():
            admitted, rendered = self._gate_value(key, value)
            if admitted:
                queue[key] = rendered
            else:
                queue_withheld += 1
        queue["fields_withheld"] = queue_withheld
        return {"git": observed, "queue": queue, "registered": True}

    def _gate_value(self, key: str, value: Any) -> tuple[bool, Any]:
        """``(admitted, rendered)``: a scalar or container is admitted only if
        every string of its ONE rendering passes the shape check and the
        project's gate, and that rendering is what the observation emits
        (D20); a value that cannot be rendered is withheld (D16)."""
        try:
            rendered = _render_value(value)
        except _Unrenderable:
            return False, None
        admitted = all(not _looks_like_host_path(text) and self._admit(f"{key}.txt", text)
                       for text in _rendered_strings(rendered))
        return admitted, rendered

    def _admit_value(self, key: str, value: Any) -> bool:
        return self._gate_value(key, value)[0]

    def _gated_fields(self, source: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[dict[str, Any], int]:
        """Project ``keys`` of a producer's payload through the gate (D23: a
        counter is a value like any other; a producer that put a path into
        ``n_files`` would have handed it on)."""
        observed: dict[str, Any] = {}
        withheld = 0
        for key in keys:
            admitted, rendered = self._gate_value(key, source.get(key))
            if admitted:
                observed[key] = rendered
            else:
                withheld += 1
        return observed, withheld

    def _produce(self, label: str, call: Callable[[], Any]) -> Any:
        """Run a reader or producer; a failure is a refusal that names the
        failure CLASS only -- its message may carry the very host path the
        gate exists to withhold (Odysseus round 6, D21: a PermissionError from
        ``collect_status`` reached the planner's history verbatim)."""
        try:
            return call()
        except ComputerRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - every producer failure is a refusal, never a message
            raise ComputerRefused(f"observation producer failed ({label}): {type(exc).__name__}") from exc

    def _structure(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.report import structure_summary
        idx = self._cached_index(repo_root)
        summary = self._produce("structure summary", lambda: structure_summary(
            idx, top_hotspots=TOP * 2, top_clones=TOP * 2, top_windows=0,
            top_fanin=TOP * 2, top_renamed=0, top_near=0, max_graph_nodes=0, max_graph_edges=0))
        if not isinstance(summary, Mapping):
            raise ComputerRefused("observation producer failed (structure summary): no mapping")
        ignored = summary.get("ignored") if isinstance(summary.get("ignored"), Mapping) else {}
        hotspots, hotspots_withheld = self._admit_rows(
            summary.get("hotspots", []), ("module",),
            keep_keys=("module", "score", "loc", "long_functions", "guard_count", "cc_max"))
        fan_in, fan_in_withheld = self._admit_rows(summary.get("fan_in", []), ("module",),
                                                   keep_keys=("module", "count"))
        clones: list[dict[str, Any]] = []
        clones_withheld = 0
        clone_rows = summary.get("clones", [])
        if not isinstance(clone_rows, (list, tuple)):
            clone_rows, clones_withheld = [], 1
        for row in clone_rows:
            # The clone row is rendered ONCE and every string of that rendering
            # is gated -- ``count``/``loc`` included, which are counters only by
            # convention (Odysseus round 7, D24: the row was copied raw, so the
            # emitter rendered a second time and two fields passed ungated).
            if not isinstance(row, Mapping):
                clones_withheld += 1
                continue
            try:
                head = {key: _render_value(row[key]) for key in ("name", "language", "count", "loc", "safety")
                        if key in row}
            except _Unrenderable:
                clones_withheld += 1
                continue
            if not all(self._admit_text(text) for text in _rendered_strings(head)) or not head.get("name"):
                clones_withheld += 1
                continue
            sites, sites_withheld = self._admit_rows(row.get("sites", []), ("module",),
                                                     keep_keys=("module", "line"))
            if not sites:
                clones_withheld += 1
                continue
            clones.append({**head, "sites": sites, "sites_withheld": sites_withheld})
        # ``ignored.source`` is the absolute path of the ignore file and
        # ``ignored.sample`` names withheld files (MEASURED 2026-09-10, live run
        # 3): only the counts and the ignore PATTERNS (key ``ignore_patterns``;
        # Cerberus N7) are observed -- and the patterns name exactly the trees
        # a project wants withheld, so each one passes the text gate like any
        # other string (Cerberus round 3, H1).
        raw_patterns = ignored.get("ignore_patterns") or []
        patterns = [str(p) for p in raw_patterns] if isinstance(raw_patterns, (list, tuple)) else []
        admitted_patterns = [p for p in patterns if self._admit_text(p)]
        # ``*_withheld`` counts gate refusals; ``*_elided`` counts the admitted
        # rows the TOP bound drops, so a short list is never mistaken for a
        # complete one (Odysseus round 4, D13).
        counters, counters_withheld = self._gated_fields(summary, ("n_files", "languages", "totals"))
        ignored_counters, ignored_withheld = self._gated_fields(ignored, ("count", "n_files_scanned"))
        return {**counters,
                "ignored": {**ignored_counters,
                            "ignore_patterns": admitted_patterns[:TOP],
                            "ignore_patterns_withheld": len(patterns) - len(admitted_patterns),
                            "ignore_patterns_elided": max(0, len(admitted_patterns) - TOP),
                            "fields_withheld": ignored_withheld},
                "fields_withheld": counters_withheld,
                "hotspots": hotspots[:TOP], "hotspots_withheld": hotspots_withheld,
                "hotspots_elided": max(0, len(hotspots) - TOP),
                "clones": clones[:TOP], "clones_withheld": clones_withheld,
                "clones_elided": max(0, len(clones) - TOP),
                "fan_in": fan_in[:TOP], "fan_in_withheld": fan_in_withheld,
                "fan_in_elided": max(0, len(fan_in) - TOP),
                "churn": "not measured (effect-free index)"}

    def _resolve_module(self, idx: dict, module: object) -> str:
        if not isinstance(module, str) or not module.strip() or len(module) > 1000 or "\x00" in module:
            raise ComputerRefused("module must be a bounded repository-relative path")
        token = module.strip().replace("\\", "/")
        modules = idx.get("modules", {})
        if token in modules:
            if not self._admit(token, ""):
                raise ComputerRefused(_MODULE_UNAVAILABLE)
            return token
        hits = sorted(m for m in modules if m == token or m.endswith("/" + token))
        if len(hits) == 1:
            # A unique hit the gate withholds answers exactly like a miss: a
            # basename must not confirm that a withheld file exists (Odysseus
            # round 5, D18). The ambiguity branch below still counts, which is
            # the same disclosure ``*_withheld`` makes everywhere.
            if not self._admit(hits[0], ""):
                raise ComputerRefused(_MODULE_UNAVAILABLE)
            return hits[0]
        if len(hits) > 1:
            # The refusal text reaches the planner's history like any result
            # (runtimes/computer.py ``outcome["error"]``), so the candidates go
            # through the same gate as a ``module`` row of ``daedalus.structure``
            # -- a basename the model chooses must not enumerate the paths the
            # project withholds (Cerberus round 4, H4).
            # No count either (Odysseus round 6, D22): "2 candidates, all
            # withheld" confirmed the existence the unique branch denies.
            admitted = [hit for hit in hits if self._admit(hit, "")]
            if len(admitted) == 1:
                # One admitted candidate resolves as if it were unique: saying
                # "ambiguous" with one name would reveal that a withheld
                # second exists (Odysseus round 7, D27).
                return admitted[0]
            if admitted:
                raise ComputerRefused("module is ambiguous; name one of: " + ", ".join(admitted[:TOP]))
            raise ComputerRefused(_MODULE_UNAVAILABLE)
        raise ComputerRefused(_MODULE_UNAVAILABLE)

    def _slice(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.structcore.slice import semantic_slice
        idx = self._cached_index(repo_root)
        # The index decides what a module is, so no path shape can escape the
        # indexed source set: traversal, absolute paths and unknown files are
        # all "not in the index".
        target = self._resolve_module(idx, arguments.get("module"))
        self._checkpoint()
        lane = self.lane
        policy = self._project_policy()
        result = self._produce("slice", lambda: semantic_slice(repo_root, target, idx=idx, lane=lane,
                                                               policy=policy, max_tokens=SLICE_MAX_TOKENS))
        if not isinstance(result, Mapping):
            raise ComputerRefused("observation producer failed (slice): no mapping")
        text, elided = _bounded_text(result.get("slice_text", ""))
        withheld = result.get("withheld") or []
        # The withheld rows name the FILES the gate refused -- on the untrusted
        # lane exactly the paths the project keeps from the vendor (Cerberus
        # round 3, H2) -- and the RULE names the path, the deny fragment or the
        # marker again (Odysseus round 4, D9). Only the role and a rule CLASS
        # travel; the count says how many.
        if isinstance(withheld, (list, tuple)):
            # An element that is not a Mapping is not dropped: filtering it out
            # left NO rows, so no branch below fired, the slicer's raw block
            # passed, and the payload said ``withheld_count: 0`` while carrying
            # the file name and the rule -- the output lying about what it
            # withheld (Cerberus round 11, F-B). An unreadable element counts
            # as one unknown withheld row.
            rows = [{"role": str(row.get("role", "")), "rule": _rule_class(row.get("rule", ""))}
                    if isinstance(row, Mapping) else {"role": "unknown", "rule": "egress_rule"}
                    for row in withheld]
        else:
            # A shape the slicer never produces is not trusted either way: ONE
            # unknown withheld row, so the block below is rebuilt and the
            # slicer's own breadcrumbs never travel (Odysseus round 9, D32).
            # ``withheld`` was coerced to a list above, so this branch is the
            # truthy non-list case and ``withheld_count`` is then a FLOOR, not
            # a measurement of the payload (Cerberus round 10, F3).
            rows = [{"role": "unknown", "rule": "egress_rule"}]
        shown = rows[:TOP]
        block_lines = 0
        rebuilt = ("".join(f"\n# <withheld>  ({row['rule']})  [{row['role']}]" for row in shown)
                   + (f"\n# ... {len(rows) - len(shown)} more withheld" if len(rows) > len(shown) else ""))
        if any(row["role"] == "focus" for row in rows):
            # A withheld focus yields no slice at all: the slicer's whole text
            # is its two-line refusal naming the file and the rule. Rebuilt.
            text = (f"# ===== WITHHELD: <withheld> ({shown[0]['rule']}) =====\n"
                    f"# focus file withheld by the egress gate (lane={lane}); slice refused (fail-closed).")
            elided = False
        elif rows and _WITHHELD_HEADER in text:
            # The slicer keeps its withheld block LAST: everything after the
            # header is a per-file breadcrumb naming the file and the rule.
            # Rebuilt from the gated rows; only a CONTEXT TRIMMED marker (counts
            # only) is carried over from the original tail. The LAST occurrence
            # is the slicer's; a focus file that itself contains the literal
            # (this module does) keeps its text (Odysseus round 5, D15).
            head, tail = text.rsplit(_WITHHELD_HEADER, 1)
            trimmed = [line.rstrip("\r") for line in tail.splitlines() if line.startswith(_TRIMMED_MARKER)]
            text = (head + _WITHHELD_HEADER + rebuilt
                    + "".join("\n" + line for line in trimmed))
        elif rows and not elided:
            # Files were withheld, the text was NOT bounded, and it carries no
            # block this rebuild knows: the slicer's header spelling diverged
            # from the one pinned here, so ANY of its lines may be a breadcrumb
            # in a spelling no pattern here recognises. Round 11 tried a keyword
            # filter and three of the reviewer's spellings walked through it
            # carrying the withheld file name and the project's own deny
            # fragment (Cerberus round 12, F-1). The text answers like a
            # withheld hit instead (fail-closed).
            text = (_WITHHELD_HEADER + rebuilt
                    + "\n# slice text withheld: the withheld block could not be rebuilt (fail-closed).")
        elif rows:
            # Files were withheld and this adapter's own bound cut the end off,
            # which is where the slicer keeps its block. A block in the HEAD is
            # therefore a divergent one (Cerberus round 11, F-A: a divergent
            # block need not be last, so truncation does not take it with it).
            # Only the SHAPE of a block is dropped here, and the count says what
            # it counted -- lines matching that shape, not files the gate
            # refused. Withholding the whole text on this path would throw away
            # every long slice that has any withheld file at all.
            kept, block_lines, in_block = [], 0, False
            for line in text.splitlines():
                if _WITHHELD_BANNER.match(line):
                    in_block, block_lines = True, block_lines + 1
                    continue
                if in_block and _COMMENT_LINE.match(line):
                    block_lines += 1  # the banner's own comment block, to the first line of code
                    continue
                in_block = False
                if _BREADCRUMB.match(line):
                    block_lines += 1
                    continue
                kept.append(line)
            text = ("\n".join(kept).rstrip("\n") + "\n" + _WITHHELD_HEADER + rebuilt
                    + (f"\n# ... {block_lines} line(s) shaped like a withheld block were dropped from the head"
                       if block_lines else ""))
        # The resolved focus path is disclosed only if the gate admits it: a
        # basename resolves to its full indexed path, which on the untrusted
        # lane may be exactly the directory the project withholds (Cerberus
        # round 4, H4 corollary).
        focus = target if self._admit(target, "") else "<withheld>"
        counters, counters_withheld = self._gated_fields(
            {**result, "trimmed_count": result.get("trimmed_count", 0)}, ("slice_tokens", "n_included", "trimmed_count"))
        # Source text is the one string this observation hands on that the
        # per-file gate did not judge by shape: an absolute host path in a
        # string literal would leave with it (Odysseus round 7, D26). Each such
        # span is redacted and counted; the file's other text stays useful.
        text, redacted = _redact_host_paths(text)
        return {"focus_file": focus, "lane": lane, **counters, "fields_withheld": counters_withheld,
                "withheld": shown, "withheld_count": len(rows),
                # Separate from ``text_elided``: the bound is one cause, the
                # block-shape filter another (Cerberus round 12, F-2).
                "text_block_lines_dropped": block_lines,
                "withheld_elided": max(0, len(rows) - TOP),
                "text": text, "text_elided": elided, "text_host_paths_redacted": redacted}

    def _docrefs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        repo_root = self._repo_root()
        from daedalus.spine import docrefs
        report = self._produce("docrefs", lambda: docrefs.scan(repo_root))
        self._checkpoint()
        payload = self._produce("docrefs", lambda: report.to_dict())
        if not isinstance(payload, Mapping):
            raise ComputerRefused("observation producer failed (docrefs): no mapping")
        broken, withheld = self._admit_rows(payload.get("broken", []),
                                            ("doc_path", "module_path"), ("raw", "symbol"),
                                            keep_keys=("doc_path", "line", "raw", "module_path", "symbol", "state"))
        # Scanner error strings carry the absolute path of the unreadable file
        # (Cerberus MAJOR 2): only their number is observed.
        counters, counters_withheld = self._gated_fields(
            payload, ("n_resolving", "n_broken", "n_skipped", "files_scanned"))
        errors = payload.get("errors")
        return {**counters, "fields_withheld": counters_withheld,
                "broken": broken[:TOP], "broken_elided": max(0, len(broken) - TOP),
                "broken_withheld": withheld,
                "errors_count": (len(errors) if isinstance(errors, (list, tuple, set, frozenset, Mapping))
                                 else 1 if errors else 0)}

    def _tasks(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self._repo_root()  # a task list is still scoped to a registered project
        # Computer-mission history lives in ``orchestration.ikarus.computer_history``;
        # reading it from a runtime adapter would close a runtimes<->orchestration
        # import cycle (see ProjectReaders), so this observation stays with the
        # file-bridge reports. The chat's ``/computer tasks`` remains the door to
        # mission history.
        briefs = self._produce("report briefs", lambda: list(self._readers.report_briefs(self._project)))
        reports, withheld = self._admit_rows(
            briefs, (), ("summary", "name", "agent", "provider", "lane", "project"),
            keep_keys=("name", "status", "lane", "project", "agent", "provider", "phase", "summary"))
        # Gate first, bound after (the most recent TOP admitted rows), and say
        # how many admitted rows the bound dropped (Odysseus round 5, D19).
        return {"reports": reports[-TOP:], "reports_withheld": withheld,
                "reports_elided": max(0, len(reports) - TOP),
                "computer_missions": "use /computer tasks in the chat"}
