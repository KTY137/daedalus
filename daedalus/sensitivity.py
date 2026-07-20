"""Data-egress and change-risk classification for provider routing.

Two independent axes decide where a task may run:

* **data sensitivity** — may the *bytes* be sent to an untrusted external API?
  Reading a file means sending its contents off-machine, so this gates reads.
* **change risk** — does the task touch high-blast-radius code (HV / motion /
  data-loss / architecture / auth / prod)? This gates whether a free model may
  do more than *review*.

The rule is fail-closed: anything not explicitly allow-listed is treated as
sensitive (``default_deny``). Trusted lanes (Claude, local Ollama) bypass the
egress gate; only untrusted external providers (DeepSeek) are constrained by it.

The rules are **per-project config, not hardcoded**, so this harness is reusable
across repos. Generic secret/allow defaults ship here; project-specific rules
(e.g. instrument-driver denylists) live in ``projects/<name>.json`` under a
``"policy"`` key and are merged on top via :func:`load_policy`.
"""

from __future__ import annotations

import re
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
    # VALUE-SHAPED credential assignment. Cerberus's CRITICAL: the shape-only
    # rules above catch AWS/GitHub/JWT but let an arbitrary plaintext secret
    # (`password = "hunter2..."`, `token = "Bearer ..."`) through the floor
    # silently, on the trusted lane, with withheld=[]. Reproduced across all
    # three slice paths before this was added.
    #
    # The discriminator that distinguishes a secret from Momus's B2 false
    # positive (`api_key=None`, `api_key: str`) is a QUOTED value of real
    # length: a secret is assigned a literal string, a kwarg default is not.
    # `api_key=None` has no quote after `=`; `api_key: str` has no `=` before a
    # quote. `{8,}` keeps it off `mode = "run"`-style short labels. Kept compact
    # and on ONE line -- ``_compile`` silently drops any pattern over 200 chars,
    # and the verbose/indented form blew past that and vanished without error.
    r"""(?i)\b(?:passwd|password|pwd|secret|token|api[_-]?key|access[_-]?key|auth[_-]?token|bearer|client[_-]?secret)\b\s*[=:]\s*(['"])[^'"\n]{8,}\1""",
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
    )


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower()


@dataclass
class DataClass:
    """Result of the data-egress classification."""

    sensitive: bool
    offending: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


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
        if any(frag in _norm(raw) for frag in policy.high_risk_path_substrings):
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
    hardware or safety-critical code. Simulated/base files stay writable."""
    policy = policy or DEFAULT_POLICY
    norm = _norm(path)
    # The generic secret floor wins over EVERYTHING -- even a *_simulated.py
    # suffix (otherwise secrets/keys_simulated.py would be writable by the
    # local model). Project deny entries may include real device trees for data
    # egress; simulated backends still get the explicit write exemption below.
    if any(d in norm for d in GENERIC_DENY_SUBSTRINGS):
        return True
    # For WRITES the only other exemption is a simulated backend. *_base.py is
    # NOT exempt: the real ISEG/motor drivers inherit it, so a bad write there
    # breaks or alters real hardware behaviour.
    if norm.endswith("_simulated.py"):
        return False
    if any(d in norm for d in policy.deny_substrings):
        return True
    return any(h in norm for h in policy.high_risk_path_substrings)


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
    When True (local/trusted provider) everything readable is inlined."""
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
