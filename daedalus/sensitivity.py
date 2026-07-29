"""Egress, write-confinement and change-risk classification for provider routing.

Three independent gates live here. They read **disjoint** config fields and
have **different defaults**; do not describe one using the other's rule.

* **data egress** — may the *bytes* leave for an untrusted external API?
  Reading a file means sending its contents off-machine, so this gates reads.
  Predicate: :func:`classify_data` via :func:`_path_is_sensitive`.
  Fields: ``allow_substrings``, ``allow_exceptions``, ``deny_substrings``,
  ``default_deny``. **Fail-closed**: a path not on the allow-list is sensitive.
* **write confinement** — may a local agentic writer put bytes on disk here?
  Predicate: :func:`path_write_blocked`. Field: ``write_allow`` (plus the
  denylists). **NOT fail-closed by default**: an empty ``write_allow`` means
  *unconfined*, and only the denylists apply. Confinement is opt-in per
  project; when set, the list is the whole permission and denials stack on top.
* **change risk** — does the task touch high-blast-radius code (HV / motion /
  data-loss / architecture / auth / prod)? This gates whether a free model may
  do more than *review*.

The egress axis's allow-list has never been consulted by the write axis. Prose
that said otherwise once made 8 of 12 supposedly-denied paths writable,
including ``daedalus/config.py``, which *loads the policy* — see the long note
on :func:`path_write_blocked`. State each gate's default separately or repeat
that bug. Trusted lanes (Claude, local Ollama) bypass the egress gate; only
untrusted external providers (DeepSeek) are constrained by it.

The rules are **per-project config, not hardcoded**, so this harness is reusable
across repos. Generic secret/allow defaults ship here; project-specific rules
(e.g. instrument-driver denylists) live in ``projects/<name>.json`` under a
``"policy"`` key and are merged on top via :func:`load_policy`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


_MAX_PATTERN_LEN = 200  # reject over-long / likely-catastrophic repo-supplied regexes


def _compile(patterns) -> tuple[re.Pattern[str], ...]:
    """Compile defensively: skip non-str, over-long, or invalid patterns rather
    than raising. deny_content is partly repo-controlled (portable policy files),
    so a bad pattern must fail SAFE, not crash the run or open a ReDoS hole."""
    out: list[re.Pattern[str]] = []
    for p in patterns:
        if not isinstance(p, str) or len(p) > _MAX_PATTERN_LEN:
            continue
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    return tuple(out)


# --- generic, project-agnostic defaults -----------------------------------

# Secret-bearing paths that must never reach an untrusted external API, in ANY
# project. Project policies are unioned on top of these; they can extend but
# never remove these baseline protections.
GENERIC_DENY_SUBSTRINGS: tuple[str, ...] = (
    ".env", "secret", "credential", "password", "api_key", "apikey",
    "id_rsa", ".pem", ".key", "/.ssh/", "token",
)
GENERIC_ALLOW_SUBSTRINGS: tuple[str, ...] = ("docs/", "/tests/", "test_", ".md", "readme")
GENERIC_DENY_CONTENT: tuple[str, ...] = (
    r"-----begin [a-z ]*private key-----",
    r"\bapi[_-]?key\b\s*[=:]",
    r"\bsecret\b\s*[=:]",
    r"\bpassword\b\s*[=:]",
)
# --- SECRET FLOOR (slice egress gate, tier 1) -----------------------------
#
# This is DELIBERATELY NOT ``GENERIC_DENY_SUBSTRINGS``. That list is tuned for
# the egress question "may these bytes go to an UNTRUSTED external API?" and it
# carries the bare substring ``"token"`` (matches token_monitor.py,
# token_policy.py, structcore/tokens.py -- the latter a *direct dependency of
# slice.py itself*), plus ``"secret"``/``"password"``/``"api_key"`` which match
# ordinary source and function parameters. Reusing it as the floor would make
# the engine un-distillable by itself -- the exact bootstrap this gate exists to
# unblock. So the floor is a SEPARATE, high-precision, secret-ONLY ruleset:
# markers that are secrets by construction (a .pem, an id_rsa, a .env), never a
# keyword that merely appears in secret-handling code. A private key must never
# enter a slice, in ANY lane, even a local one -- but ``token_policy.py`` is not
# a secret and must slice cleanly.
SECRET_FLOOR_PATH_SUBSTRINGS: tuple[str, ...] = (
    ".env", ".ssh/", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".pem", ".pfx", ".p12", ".keystore", ".jks", ".key",
)
# Value-SHAPED secret detectors: they match the shape of a real credential, not
# a keyword. ``api_key=None`` / ``password:`` do NOT match here (that is the B2
# false-positive the egress ``deny_content`` regexes suffer). Applied PER FILE,
# never all-or-nothing over the assembled slice.
SECRET_FLOOR_CONTENT: tuple[str, ...] = (
    r"-----begin [a-z0-9 ]*private key-----",   # RSA/EC/OPENSSH/DSA PEM blocks
    r"\bAKIA[0-9A-Z]{16}\b",                     # AWS access key id
    r"\bASIA[0-9A-Z]{16}\b",                     # AWS temporary access key id
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b",   # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{22,}\b",        # GitHub fine-grained PAT
    r"\bxox[baprs]-[0-9A-Za-z]{10,48}\b",       # Slack tokens
    r"\bAIza[0-9A-Za-z_\-]{35}\b",              # Google API key
    r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b",     # Stripe live key
    r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b",  # JWT
    # VALUE-SHAPED credential assignment. Cerberus's CRITICAL (twice): the
    # shape-only rules above catch AWS/GitHub/JWT but let an arbitrary plaintext
    # secret -- a credential-named identifier bound to a quoted string literal --
    # through the floor silently, on the trusted lane, with withheld=[].
    # Reproduced across all three slice paths.
    #
    # The discriminator that distinguishes a secret from Momus's B2 false
    # positive (api_key=None, api_key: str) is a QUOTED value of real length: a
    # secret is assigned a literal string; a kwarg default is not. api_key=None
    # has no quote after the operator; api_key: str has no quoted value at all.
    #
    # The first cut used \b...\b word boundaries and a bare single/double quote,
    # which left SIX bypass classes open across two Cerberus re-reviews of the
    # slice egress gate. Classes 1-4 (first review of d714128):
    #   1. underscore/camelCase-glued names -- \b never fires inside DB_PASSWORD,
    #      access_token, SECRET_KEY, refreshToken. So the keyword is matched as a
    #      SUB-token of the identifier: no left \b, and \w* consumes the rest of
    #      the identifier up to the operator (that is how SECRET_KEY reaches =).
    #   2. string prefixes between the operator and the quote -- f"", b"", r"",
    #      rb"". Allowed via [bruf]{0,2} (IGNORECASE covers B/R/U/F).
    #   3. triple-quoted values -- the [^'"\n] value class dies on the 2nd quote,
    #      so triple quotes get their OWN entry below (opening quote + \1\1).
    #   4. short values -- {8,} let a real short secret slip (a 6-char value
    #      bound to a credential-named identifier). Lowered to {4,}: a keyword
    #      followed by a quoted literal is a strong signal on its own, and the
    #      safety asymmetry favours withholding a 4-char value (a PIN / short
    #      pwd) over leaking it to a paid lane. A scan of daedalus/ + apps/web/src
    #      found ZERO benign 4-7 char keyword assignments, so {4,} costs nothing.
    # Classes 5-6 (second review) are the mainstream typed/config forms:
    #   5. ANNOTATED assignment -- a typed field (pydantic/dataclass/settings):
    #      a credential name, a ':' type, then '=' quoted value. The optional
    #      (?::[^='"\n]{1,60})? consumes the type; excluding = ' " keeps it from
    #      running into the operator or the value, and the {1,60} bound plus NO
    #      trailing \s* keeps backtracking finite -- an earlier draft that let the
    #      type class overlap an adjacent \s* was O(n^2) and hung on a padded line.
    #   6. QUOTED-KEY form -- a dict-literal / JSON secret where the keyword sits
    #      inside quotes, so its closing quote blocked the ':' adjacency. The
    #      optional ['"]? after \w* steps over that closing quote. 'authorization'
    #      was added to the keyword set for the HTTP-header config case.
    #
    # SPLIT into two index-aligned entries (single/double vs triple quote) so
    # each stays under ``_compile``'s 200-char cap -- a monster one-line regex
    # that silently blew the cap and vanished is exactly the failure that let the
    # original leak ship. The value match stays LINEAR (negated class, bounded
    # type, no nested/overlapping quantifiers): a 200k-char pathological line is
    # ~70ms. A shape-based floor still cannot reach these (documented, not chased):
    # unquoted values (password: secret / YAML unquoted), a secret split across
    # lines, or a value whose first embedded escaped quote is within 4 chars.
    r"""(?i)(?:passwd|password|pwd|secret|token|api[_-]?key|access[_-]?key|auth[_-]?token|authorization|bearer|client[_-]?secret)\w*['"]?[ \t]*(?::[^='"\n]{1,60})?[=:][ \t]*[bruf]{0,2}(['"])[^'"\n]{4,}\1""",
    r"""(?i)(?:passwd|password|pwd|secret|token|api[_-]?key|access[_-]?key|auth[_-]?token|authorization|bearer|client[_-]?secret)\w*['"]?[ \t]*(?::[^='"\n]{1,60})?[=:][ \t]*[bruf]{0,2}(['"])\1\1[^\n]{4,}""",
)

# Human-readable label per floor-content pattern, so the ``withheld`` report
# names the rule that fired instead of echoing a raw regex at the operator (and,
# in the value-shape case, echoing the secret-keyword list itself). Index-aligned
# with SECRET_FLOOR_CONTENT.
SECRET_FLOOR_CONTENT_LABELS: tuple[str, ...] = (
    "PEM private key block",
    "AWS access key id",
    "AWS temporary access key id",
    "GitHub token",
    "GitHub fine-grained PAT",
    "Slack token",
    "Google API key",
    "Stripe live key",
    "JWT",
    "credential assigned a quoted literal value",
    "credential assigned a triple-quoted literal value",
)
assert len(SECRET_FLOOR_CONTENT_LABELS) == len(SECRET_FLOOR_CONTENT), \
    "SECRET_FLOOR_CONTENT_LABELS must stay index-aligned with SECRET_FLOOR_CONTENT"

GENERIC_HIGH_RISK_TERMS: tuple[str, ...] = (
    "delete", "drop table", "migration", "auth", "payment", "production",
    "deploy", "rm -rf", "credential", "rewrite", "architecture",
)
# Mid-risk: real logic changes, but not safety-critical or irreversible. A local
# 7B model may *advise* here (read-only proposal); it never writes mid-risk.
GENERIC_MID_RISK_TERMS: tuple[str, ...] = (
    "refactor", "optimize", "performance", "algorithm", "concurrency",
    "threading", "race", "calculation", "convert", "parser", "parsing",
    "edge case", "fix bug", "validation",
)
# High-blast-radius path floor. Like the secret denylist, this is ALWAYS unioned
# in (any repo-local policy extends it, never removes it) so that dropping the
# harness onto an arbitrary repo can't leave hardware/safety/system code writable
# by the local model just because the operator didn't enumerate those paths.
GENERIC_HIGH_RISK_PATHS: tuple[str, ...] = (
    "/devices/", "/drivers/", "/firmware/", "/hardware/", "/controller",
    "state_machine", "interlock", "/safety", "/hv", "motion/", "/kernel/", "/boot/",
)


@dataclass(frozen=True)
class Policy:
    """Per-project egress/risk rules. All matching is substring/regex on the
    forward-slashed, lower-cased path or on inlined content."""

    deny_substrings: tuple[str, ...] = GENERIC_DENY_SUBSTRINGS
    allow_substrings: tuple[str, ...] = GENERIC_ALLOW_SUBSTRINGS
    allow_exceptions: tuple[str, ...] = ()
    deny_content: tuple[re.Pattern[str], ...] = field(default_factory=lambda: _compile(GENERIC_DENY_CONTENT))
    high_risk_terms: tuple[str, ...] = GENERIC_HIGH_RISK_TERMS
    mid_risk_terms: tuple[str, ...] = GENERIC_MID_RISK_TERMS
    high_risk_path_substrings: tuple[str, ...] = GENERIC_HIGH_RISK_PATHS
    default_deny: bool = True
    # OPT-IN WRITE CONFINEMENT. Empty (the default) means "no confinement" --
    # exactly today's behaviour for every repo that does not set it. Non-empty
    # means this list is the WHOLE write permission: anything not matching is
    # blocked. See :func:`path_write_blocked` for why this is a separate field
    # rather than a reuse of ``allow``/``default_deny``.
    write_allow: tuple[str, ...] = ()


DEFAULT_POLICY = Policy()


def load_policy(project_config: dict | None) -> Policy:
    """Build a :class:`Policy` from a project config dict (the parsed
    ``projects/<name>.json``). Generic secret protections are always unioned in
    so a project can extend, but never weaken, the baseline."""
    p = (project_config or {}).get("policy") or {}
    return Policy(
        deny_substrings=tuple(dict.fromkeys(GENERIC_DENY_SUBSTRINGS + tuple(p.get("deny", ())))),
        allow_substrings=tuple(p.get("allow", GENERIC_ALLOW_SUBSTRINGS)),
        allow_exceptions=tuple(p.get("allow_exceptions", ())),
        deny_content=_compile(list(GENERIC_DENY_CONTENT) + list(p.get("deny_content", ()))),
        high_risk_terms=tuple(p.get("high_risk_terms", GENERIC_HIGH_RISK_TERMS)),
        mid_risk_terms=tuple(p.get("mid_risk_terms", GENERIC_MID_RISK_TERMS)),
        # ALWAYS unioned (like the secret denylist): a project can extend the
        # high-blast-radius floor but never remove it.
        high_risk_path_substrings=tuple(dict.fromkeys(
            GENERIC_HIGH_RISK_PATHS + tuple(p.get("high_risk_paths", ())))),
        default_deny=bool(p.get("default_deny", True)),
        # NORMALISED AT LOAD, deliberately. Matching happens against ``_norm``
        # (forward-slashed, lower-cased), so a policy entry like "README" or
        # "Docs\\" could never match anything -- a DEAD ALLOW ENTRY, which under
        # a confinement list reads as "I permitted this" while permitting
        # nothing. Normalising here makes an operator's natural spelling work
        # instead of silently confining harder than they asked.
        write_allow=tuple(dict.fromkeys(
            _norm(str(a)) for a in p.get("write_allow", ()) if str(a).strip())),
    )


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower()


def _fence_norm(path: str) -> str:
    """Root-anchored path for HIGH-BLAST-RADIUS fragment matching, mirroring
    ``structcore.graph._fence_norm``.

    The generic fence ships slash-anchored fragments (``/controller``,
    ``/safety``, ``/hv``) so they match a fenced *subtree* anywhere. A repo-
    relative TOP-LEVEL path -- ``controller/core.py`` -- has no leading slash, so
    a bare-substring test (``_norm``) structurally cannot match ``/controller``
    against it, and a literally-fenced top-level file scored ``low`` and reached
    the local write lane. Anchoring with a leading '/' closes that: it can only
    ever match MORE (over-escalation), which is the sole direction this fence is
    allowed to err in. Deliberately NOT applied to the egress deny/allow lists,
    whose bare substrings (``.env``, ``token``, ``/tests/``) are tuned to match
    anywhere and would change meaning under a forced anchor.
    """
    return "/" + _norm(path).lstrip("/")


@dataclass
class DataClass:
    """Result of the data-egress classification."""

    sensitive: bool
    offending: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _within_write_allow(path: str, allow: tuple[str, ...]) -> bool:
    """Root-anchored PREFIX match of ``path`` against a confinement list.

    Deliberately NOT the substring test the rest of this module uses. Every
    other list here is a DENY list, where a loose match errs toward blocking --
    the safe direction. A confinement list is the opposite: a loose match errs
    toward PERMITTING. Substring-matching ``"docs/"`` would admit
    ``evildocs/payload.py`` and ``daedalus/docs/../core.py``-shaped names, i.e.
    the confinement would leak in exactly the direction it exists to stop.

    Semantics: an entry ending in ``/`` names a subtree; any other entry names
    THAT ONE FILE and nothing under it. Both are anchored at the repo root, so
    ``readme.md`` permits ``/readme.md`` and neither ``/vendor/readme.md`` nor
    ``/readme.md/payload.py``.

    THE SECOND HALF OF THAT SENTENCE WAS PROSE, NOT CODE, FOR ONE HOUR. The
    first version read::

        anchored == e or anchored.startswith(e if e.endswith("/") else e + "/")

    which admits every DESCENDANT of a file entry -- ``README.md/payload.py``
    passed the confinement while the docstring above it said file entries name
    one file. Found by Codex in review, on the same day the same defect was
    found in a document describing this very fence. A confinement list is the
    one place in this module where a loose match errs toward PERMITTING, so the
    non-directory case must be equality and nothing else.
    """
    anchored = "/" + _norm(path).lstrip("/")
    for entry in allow:
        e = "/" + entry.lstrip("/")
        if anchored == e:
            return True
        # ONLY a directory entry extends to descendants. No `else` branch here
        # on purpose: a file entry that is not an exact match is a miss.
        if e.endswith("/") and anchored.startswith(e):
            return True
    return False


def intersect_write_allow(a: Sequence[str], b: Sequence[str]) -> tuple[str, ...]:
    """The confinement that admits a path only if BOTH lists admit it.

    Exists because a write confinement can be declared in two places at once --
    a repo's own ``.agentenv/agentenv.json`` and a registry entry named on the
    command line -- and MEASURED, naming a project silently dropped the repo's
    own confinement entirely::

        resolve_project(root, None)         -> write_allow ('docs/','tests/','readme.md')
        resolve_project(root, "agent_env")  -> write_allow ()  == UNCONFINED

    With `--project agent_env`, `daedalus/sensitivity.py`, `daedalus/config.py`
    and `.agentenv/agentenv.json` itself all became writable. The invariant this
    restores: **naming a project must never grant more write permission than
    not naming one.**

    An empty list means "unconfined", so it contributes no restriction and the
    other list wins outright. When both confine, the result is their
    intersection -- computed by keeping whichever entries are the MORE SPECIFIC,
    since entries are root-anchored prefixes: ``docs/sub/`` survives an
    intersection with ``docs/``, and ``docs/`` does not survive one with
    ``docs/sub/``.
    """
    a = tuple(a or ())
    b = tuple(b or ())
    if not a:
        return b
    if not b:
        return a
    kept = [e for e in a if _within_write_allow(e, b)]
    kept += [e for e in b if _within_write_allow(e, a)]
    # dict.fromkeys keeps first-seen order; an empty result is CORRECT and means
    # the two confinements do not overlap, i.e. nothing may be written. That is
    # the fail-closed direction, so it is deliberately not special-cased into
    # "unconfined" -- which is exactly the bug this function exists to stop.
    return tuple(dict.fromkeys(kept))


def _path_is_sensitive(norm_path: str, policy: Policy) -> str | None:
    """Return a reason string if the path is sensitive, else None."""
    if any(exc in norm_path for exc in policy.allow_exceptions):
        return None
    for deny in policy.deny_substrings:
        if deny in norm_path:
            return f"denylisted path fragment '{deny}'"
    if any(allow in norm_path for allow in policy.allow_substrings):
        return None
    if policy.default_deny:
        return "path not on the external allow-list (default-deny)"
    return None


def classify_data(
    paths: list[str] | None = None,
    extra_text: str = "",
    policy: Policy | None = None,
) -> DataClass:
    """Classify whether these paths/text may leave the machine to an
    *untrusted* external API. Fail-closed."""
    policy = policy or DEFAULT_POLICY
    offending: list[str] = []
    reasons: list[str] = []
    for raw in paths or []:
        reason = _path_is_sensitive(_norm(raw), policy)
        if reason:
            offending.append(raw)
            reasons.append(f"{raw}: {reason}")
    for pat in policy.deny_content:
        if pat.search(extra_text):
            reasons.append(f"content matches sensitive marker /{pat.pattern}/")
            break
    return DataClass(sensitive=bool(reasons), offending=offending, reasons=reasons)


# Compiled once, PAIRED WITH LABELS. ``_compile`` silently drops any pattern
# over 200 chars (it cost a debugging round when the value-shape rule, written
# verbose, blew past the cap and vanished). For a SAFETY table a silently
# missing rule is the worst failure, so we compile each pattern individually and
# assert none was dropped -- a dropped secret rule must be loud, not inferred.
def _compile_labeled(patterns, labels):
    out = []
    for src, label in zip(patterns, labels):
        c = _compile([src])
        if not c:
            raise ValueError(
                f"secret-floor pattern for '{label}' failed to compile or "
                f"exceeded the length cap; it would be silently absent")
        out.append((c[0], label))
    return tuple(out)


_SECRET_FLOOR_CONTENT_LABELED = _compile_labeled(
    SECRET_FLOOR_CONTENT, SECRET_FLOOR_CONTENT_LABELS)
# Back-compat alias for any caller that iterates the compiled patterns directly.
_SECRET_FLOOR_CONTENT: tuple[re.Pattern[str], ...] = tuple(
    p for p, _ in _SECRET_FLOOR_CONTENT_LABELED)


def secret_floor_rule(path: str, text: str = "") -> str | None:
    """The UNCONDITIONAL secret floor -- runs in EVERY lane, no bypass.

    Returns a short reason string naming the rule that fired, or ``None`` if the
    file is clean. Precision is the whole point: this must catch a planted
    ``.env`` / private key / real credential and must NOT catch ordinary engine
    source (``token_policy.py``, ``api_key=None`` kwargs). Independent of the
    egress denylist and of any project policy, so it behaves identically on any
    repo and cannot be weakened by a project config.

    ``text`` is scanned PER FILE by the caller -- never over concatenated slice
    text -- so a hit is always attributable to one path.
    """
    norm = _norm(path)
    for frag in SECRET_FLOOR_PATH_SUBSTRINGS:
        if frag in norm:
            return f"secret path marker '{frag}'"
    for pat, label in _SECRET_FLOOR_CONTENT_LABELED:
        if pat.search(text):
            return f"secret content: {label}"
    return None


# Hosts that are the SAME MACHINE. "Local" in this project's security model
# means "no bytes leave this host", so nothing else qualifies -- the RTX bench
# at 100.119.126.9 is reached over a tailnet and is emphatically not local.
_LOOPBACK_LITERALS = frozenset({"127.0.0.1", "::1", "[::1]"})


ENV_TRUSTED_HOSTS = "DAEDALUS_TRUSTED_HOSTS"


def declared_trusted_hosts() -> frozenset[str]:
    """Addresses the operator has DECLARED to be inside their trust boundary.

    ``DAEDALUS_TRUSTED_HOSTS=100.119.126.9`` (comma-separated for several). Empty
    and therefore inert unless somebody sets it, so the fail-closed default this
    module is built on is untouched for every configuration that stays silent.

    Exists because the shipped predicate answers "is this THIS machine", and for
    a private-tunnel bench the honest answer is "no, and I trust it anyway".
    Refusing to let that be expressible does not make the setup safer -- it makes
    the operator point OLLAMA_HOST at a tunnel and lose the distinction
    entirely, which is the failure this module already survived once.

    Three hardenings carried over deliberately from the loopback rule:

    * **Numeric literals only.** A name is dropped, not resolved. That is the
      whole reason ``localhost`` is refused here: a name that resolves to your
      bench when checked can resolve elsewhere when connected, and this
      predicate cannot see the difference.
    * **Exact address equality.** No CIDR, no prefixes. Declaring ``.9`` must
      never quietly trust ``.99``; a trust list that grows by arithmetic is a
      trust list nobody can audit.
    * **Unparseable entries are dropped**, never guessed at. A typo shrinks the
      list rather than widening it.

    Normalised through :mod:`ipaddress` so equivalent spellings of one address
    compare equal, and a port or scheme accidentally left on an entry is
    stripped rather than silently producing an entry that matches nothing.
    """
    import os  # local, matching this module's deliberately small import surface

    raw = os.environ.get(ENV_TRUSTED_HOSTS, "") or ""
    out: set[str] = set()
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        try:
            from urllib.parse import urlsplit

            parsed = urlsplit(entry if "//" in entry else f"//{entry}")
            candidate = (parsed.hostname or entry).strip().lower()
            import ipaddress

            out.add(str(ipaddress.ip_address(candidate)))
        except (ValueError, UnicodeError):
            continue  # a typo must NARROW the list, never widen it
    return frozenset(out)


def lane_for_host(host: str | None) -> str:
    """``"trusted"`` only if ``host`` is THIS machine; ``"untrusted"`` otherwise.

    THE ONLY IMPLEMENTATION. There is exactly one answer to "do the bytes leave
    this machine", and it lives here, next to the gate it switches
    (:func:`slice_egress_rule`). Do not re-derive it at a call site: within a
    day of this predicate landing the repo held FIVE independent versions of the
    question (``council/vendors.py``, ``council/session.py``,
    ``council/canary.py``, an inline set literal in ``accelerators.py``, and
    this one) and they returned three different answers for ``[::1]``. A caller
    that needs a boolean writes ``lane_for_host(h) == "trusted"``; a caller that
    needs the lane string uses the return value directly. Both are pinned by
    ``tests/test_host_predicate.py``, which also fails if a module grows its own
    copy of the host table.

    THE BUG THIS EXISTS TO PREVENT. ``lane="trusted"`` turns OFF the
    default-deny allow-list in :func:`slice_egress_rule`, leaving only the
    secret floor. That was previously chosen by PROVIDER NAME -- "ollama is
    local, so trusted" -- while the Ollama client resolves its endpoint from
    ``OLLAMA_HOST``, an environment variable
    (``providers/ollama.py``: ``os.environ.get("OLLAMA_HOST", DEFAULT_HOST)``).
    Exporting ``OLLAMA_HOST=http://100.119.126.9:11434`` therefore kept the name
    "ollama", kept the lane "trusted", and silently converted a no-egress lane
    into a network one: distilled source that the allow-list would have withheld
    from any external provider goes over the wire with only the secret floor
    applied. Nothing in the code said so, and no test noticed.

    So the question this answers is never "which provider is this" but "where do
    the bytes actually go".

    FAILS CLOSED. An empty, unparseable, or unrecognised host is
    ``"untrusted"`` -- if we cannot tell where the bytes go, they are treated as
    leaving. ``0.0.0.0`` is deliberately NOT loopback: it is a bind address, and
    as a connect target it is not a promise about this machine.

    NUMERIC ONLY. ``localhost`` is NOT accepted. It was, on the reasoning that
    refusing a name would push real setups into disabling the check — but the
    shipped default is already numeric (``providers/ollama.py`` ``DEFAULT_HOST =
    "http://127.0.0.1:11434"``), so the argument cost nothing to give up and the
    name buys a DNS/hosts-file indirection this predicate cannot see. A name
    that resolves to loopback when checked can resolve elsewhere when connected:
    the same check-then-use shape that produced this repo's worktree CRITICALs,
    with egress instead of deletion at the end of it. Refusing names removes the
    window rather than narrowing it.

    WIDER THAN THE AD-HOC PREDICATES IT REPLACED, DELIBERATELY. The council's
    copies matched ``^https?://([^/:]+)`` against a three-name frozenset, so
    they answered ``untrusted`` for ``http://[::1]:11434``, for a scheme-less
    ``127.0.0.1:11434`` (the literal shape ``OLLAMA_HOST`` takes), and for every
    127.0.0.0/8 address other than ``127.0.0.1``. Consolidating onto this
    function makes those three ``trusted``, which is a REAL widening of the
    egress boundary and is argued rather than assumed:

    * The old ``untrusted`` was a PARSING ACCIDENT, not a policy. That regex
      cannot span a bracketed IPv6 literal (``[^/:]+`` dies on the first colon,
      yielding the host ``"["``) and requires a scheme. Nobody decided ``::1``
      was off-machine; a character class did.
    * All three are loopback by specification -- 127.0.0.0/8 is reserved for
      loopback entire (RFC 1122 3.2.1.3) and ``::1`` is the IPv6 loopback
      (RFC 4291 2.5.3). Packets to them provably do not reach a wire.
    * The widening admits NUMERIC LITERALS ONLY, so it does not reopen the DNS
      indirection that ``localhost`` was refused for. That refusal still holds,
      and consolidation NARROWS the council in that direction: its copies called
      ``http://localhost:11434`` local, and this one does not.
    """
    raw = (host or "").strip()
    if not raw:
        return "untrusted"
    try:
        from urllib.parse import urlsplit

        # A bare "127.0.0.1:11434" has no scheme, and urlsplit would read the
        # host as a path; give it one so hostname parsing works either way.
        parsed = urlsplit(raw if "//" in raw else f"//{raw}")
        name = (parsed.hostname or "").strip().lower()
    except (ValueError, UnicodeError):
        return "untrusted"
    if not name:
        return "untrusted"
    if name in _LOOPBACK_LITERALS:
        return "trusted"
    if name in declared_trusted_hosts():
        # OPERATOR-DECLARED trust boundary. The owner asserts this address is
        # inside it -- typically a private-tunnel bench on the same tailnet.
        #
        # WHY THIS IS NOT THE BUG THIS MODULE EXISTS TO PREVENT. That bug was
        # trust inferred from a PROVIDER NAME while the host came from
        # OLLAMA_HOST: nothing named the host, so nothing could review it. Here
        # the host is the declaration. It is empty by default, so the
        # fail-closed posture is unchanged for anyone who says nothing, and a
        # reader of the configuration can see exactly which addresses were
        # trusted and go disagree with the person who wrote them down.
        #
        # It keeps every hardening the loopback rule earned: numeric literals
        # only (no DNS/hosts indirection, the reason `localhost` is refused),
        # EXACT address equality (no CIDR, no prefixes -- trusting .9 must never
        # trust .99), and anything unparseable is dropped rather than guessed.
        return "trusted"
    # The whole 127.0.0.0/8 block is loopback, not just 127.0.0.1.
    try:
        import ipaddress

        return "trusted" if ipaddress.ip_address(name).is_loopback else "untrusted"
    except ValueError:
        return "untrusted"


def slice_egress_rule(
    path: str,
    text: str = "",
    lane: str = "trusted",
    policy: Policy | None = None,
) -> str | None:
    """Full two-tier slice egress gate for one file. Returns the rule that
    fired, or ``None`` to allow.

    Tier 1 -- SECRET FLOOR: ``secret_floor_rule``, unconditional, every lane.
    Tier 2 -- ALLOW-LIST / default-deny: only when ``lane != "trusted"`` (an
    untrusted external provider such as DeepSeek). This is the existing
    ``classify_data`` egress behaviour; it withholds non-allow-listed source and
    is therefore NEVER applied to trusted lanes (Claude, local Ollama, the local
    eval harness, the local web distill view), where it would shred the product.

    Applied per file, so the ``deny_content`` first-match-break cannot poison a
    whole slice, and every withheld path is attributable to its own rule.
    """
    rule = secret_floor_rule(path, text)
    if rule:
        return rule
    if lane != "trusted":
        dc = classify_data([path], extra_text=text, policy=policy)
        if dc.sensitive:
            return dc.reasons[0] if dc.reasons else "egress policy: default-deny"
    return None


def change_risk(objective: str, paths: list[str] | None = None, policy: Policy | None = None) -> str:
    """Return 'high', 'mid', or 'low' for the task's change risk. High-blast-radius
    paths (device drivers, controller, state machine) force 'high' regardless of
    wording; safety/irreversible terms force 'high'; logic-change terms give 'mid'."""
    policy = policy or DEFAULT_POLICY
    obj = objective.lower()
    for raw in paths or []:
        if any(frag in _fence_norm(raw) for frag in policy.high_risk_path_substrings):
            return "high"
    if any(term in obj for term in policy.high_risk_terms):
        return "high"
    if any(term in obj for term in policy.mid_risk_terms):
        return "mid"
    return "low"


def path_write_blocked(path: str, policy: Policy | None = None) -> bool:
    """True if a local agentic writer (Ollama) must NOT write here. Blocks the
    denylist (device drivers, vendor IP, secrets) and high-blast-radius trees
    (devices/, controller/, state machine) so a weak local model can't clobber
    hardware or safety-critical code. Simulated/base files stay writable.

    THIS PREDICATE IS DENY-ONLY BY DEFAULT, AND THAT SURPRISED ITS OWN AUTHOR.
    ``policy.allow_substrings`` and ``policy.default_deny`` are read by
    :func:`classify_data` -- the EGRESS axis -- and were never consulted here.
    A drafted self-policy for this repo said, in prose, "the allow-list is the
    whole permission"; measured against this function, 8 of 12 paths it claimed
    to deny were writable, including ``daedalus/config.py``, which *loads the
    policy*. Same shape as the two-predicates-for-one-question bug in
    :func:`read_inlined_context` above: a document described a fence the code
    did not have.

    ``write_allow`` is the fix, and it is a SEPARATE, OPT-IN field on purpose:

    * Reusing ``allow``/``default_deny`` would silently confine every existing
      repo's write lane the moment this shipped -- an egress list retro-fitted
      as a write list, which is exactly the conflation that caused the bug.
    * Empty ``write_allow`` therefore means "unconfined", byte-identical to the
      previous behaviour.
    * Non-empty means the list is the WHOLE write permission, and the deny
      lists below still run on top of it. Confinement narrows; it never widens.
    """
    policy = policy or DEFAULT_POLICY
    norm = _norm(path)
    # The generic secret floor wins over EVERYTHING -- even a *_simulated.py
    # suffix (otherwise secrets/keys_simulated.py would be writable by the
    # local model). Project deny entries may include real device trees for data
    # egress; simulated backends still get the explicit write exemption below.
    if any(d in norm for d in GENERIC_DENY_SUBSTRINGS):
        return True
    if policy.write_allow:
        if not _within_write_allow(norm, policy.write_allow):
            return True
        # Confinement in force: fall through to the deny lists WITHOUT the
        # *_simulated.py exemption. That exemption exists so a weak model may
        # touch fake hardware backends in a device repo; under an explicit
        # confinement it would instead be a way for `docs/adrs/x_simulated.py`
        # to skip the high-risk check below. A repo that opts into confinement
        # is asking for fewer exemptions, not more.
    # For WRITES the only other exemption is a simulated backend. *_base.py is
    # NOT exempt: the real ISEG/motor drivers inherit it, so a bad write there
    # breaks or alters real hardware behaviour.
    elif norm.endswith("_simulated.py"):
        return False
    if any(d in norm for d in policy.deny_substrings):
        return True
    # Root-anchored (not bare ``norm``) so a top-level fenced tree -- the
    # repo-relative ``controller/core.py`` a slash-anchored ``/controller``
    # cannot substring-match -- is still blocked from the local write lane.
    return any(h in _fence_norm(path) for h in policy.high_risk_path_substrings)


def read_inlined_context(
    paths: list[str],
    repo_root: str,
    max_bytes: int,
    allow_sensitive: bool = False,
    policy: Policy | None = None,
) -> tuple[str, list[str]]:
    """Read files into an inlined-context string, capped at ``max_bytes`` total.
    Returns (text, skipped_paths).

    When ``allow_sensitive`` is False (untrusted external provider) sensitive
    files are skipped by both path and content — this is the enforcement point.
    When True (local/trusted provider) everything readable is inlined, EXCEPT
    what the secret floor refuses.

    THE FLOOR RUNS HERE TOO, AND IT DID NOT USED TO. This function is the second
    enforcement point in this module, and it was consulting only
    :func:`classify_data`, which is a weaker predicate than
    :func:`secret_floor_rule`. Two predicates for "is this a secret", and the
    enforcement point used the weaker one — the same shape as the five host
    predicates that returned three different answers for ``[::1]``.

    Measured, before the fix::

        docs/notes.md containing "use `AKIA...` as the key"
          classify_data(extra_text=...)  -> sensitive=False   (crossed)
          secret_floor_rule(path, text)  -> "secret content: AWS access key id"

    `.md` is in ``GENERIC_ALLOW_SUBSTRINGS``, so prose passes the PATH check and
    the content check was the only thing left — and it did not recognise a bare
    AWS key id, a GitHub PAT, a Slack or Stripe token, a JWT or a private key
    block. With markdown indexable as context, a design document or the council
    transcript could carry a live key to an external provider.

    The floor is applied on BOTH lanes because that is what it is: this module
    documents it as "the UNCONDITIONAL secret floor -- runs in EVERY lane, no
    bypass", and ``allow_sensitive=True`` is a statement about SOURCE
    sensitivity, never about credentials. A local model has no more need of a
    live key than a remote one does.
    """
    policy = policy or DEFAULT_POLICY
    chunks: list[str] = []
    skipped: list[str] = []
    used = 0
    root = Path(repo_root)
    for raw in paths:
        if not allow_sensitive and classify_data([raw], policy=policy).sensitive:
            skipped.append(raw)
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            data = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(raw)
            continue
        # TIER 1, unconditional, before the lane-dependent check below.
        if secret_floor_rule(raw, data) is not None:
            skipped.append(raw)
            continue
        if not allow_sensitive and classify_data([], extra_text=data, policy=policy).sensitive:
            skipped.append(raw)
            continue
        header = f"\n===== FILE: {raw} =====\n"
        budget = max_bytes - used
        if budget <= len(header):
            skipped.append(raw)
            continue
        body = data[: budget - len(header)]
        chunks.append(header + body)
        used += len(header) + len(body)
    return "".join(chunks), skipped
