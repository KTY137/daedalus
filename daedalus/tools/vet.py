"""vet.py — the gate a tool must pass before an agent may be given it.

WHY THIS EXISTS
---------------
``daedalus/skills.py`` reads a ``SKILL.md`` as inert data and says so in its own
docstring: "nothing here is a capability, and nothing here participates in a
safety decision". That was correct and it left a hole: something has to MAKE the
safety decision, and until now that something was a human squinting at a
directory listing. On 2026-07-30 that human ran ``grep`` for network calls,
``exec`` and injection strings across 1.7 MB of a community skill's CSV data
before installing it. This module is that pass, written down.

The exposure is real and asymmetric:

* a **skill** is text that reaches a model, so its attack surface is PROMPT
  INJECTION and instruction smuggling — plus whatever its bundled ``scripts/``
  would do if something ran them;
* an **MCP server** is a PROCESS with a socket, so its attack surface is
  EXECUTION and EGRESS.

Published survey numbers for community agent skills, cited in the Snyk writeup
the owner sent (2026-07-30): 13% carried critical security flaws and 36%
contained prompt injection. A layer that installs these without a gate is a hole
straight through the safety fence.

THE INVARIANTS
--------------
1. **STATIC ONLY.** Vetting never executes the thing being vetted, never imports
   it, never resolves it over the network, and never starts an MCP server to ask
   it what it does. You do not run untrusted code to decide whether to trust it.
   The whole module is file reads and regex.
2. **FAIL CLOSED, and "unknown" is not "clean".** Every verdict distinguishes
   *scanned and found nothing* from *could not scan*. An unreadable file, a
   binary blob, a truncated read and a missing directory all produce
   ``UNSCANNABLE``, never ``CLEAR``. Absence of evidence is reported as absence
   of evidence.
3. **Findings, not scores.** A verdict carries the file, the line and the matched
   text, so a human can overrule it by looking rather than by arguing. A number
   with no evidence behind it is how a gate becomes a superstition.
4. **This module owns no policy about hosts.** Whether bytes may leave the
   machine has exactly one implementation, ``sensitivity.lane_for_host``, and
   this module calls it rather than re-deciding. Same rule the router follows.
5. **A declaration is a request, never a grant.** ``allowed-tools`` in a skill's
   frontmatter is what its author would like. It is reported as an ask and it
   escalates the review; it never authorises anything.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not install, enable, route to, or run anything. It returns a verdict.
Provisioning and capability routing are separate concerns and separate reviews —
in particular, routing touches ``provider_router``, which owns lane policy, and
must not be bolted on from here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..sensitivity import lane_for_host

# Bump when the MEANING of a verdict changes, so a stored verdict from an older
# ruleset is detectable rather than silently trusted.
VET_VERSION = "1"

CLEAR = "clear"                 # scanned in full, nothing matched
REVIEW = "review"               # scanned, something a human must look at
BLOCK = "block"                 # scanned, something disqualifying
UNSCANNABLE = "unscannable"     # could NOT scan — never treat as clear

_ORDER = {CLEAR: 0, REVIEW: 1, UNSCANNABLE: 2, BLOCK: 3}

# Read bounds. A skill that ships a 40 MB file is not scanned "mostly" — it is
# reported as unscannable, because a partial scan that reads as clean is a lie.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES_SCANNED = 400

# Extensions whose contents we can meaningfully read as text.
TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx", ".json",
    ".csv", ".tsv", ".yml", ".yaml", ".toml", ".sh", ".ps1", ".bat", ".cmd",
    ".rb", ".pl", ".lua", ".sql", ".html", ".css", ".xml", ".ini", ".cfg",
})

# ── rule table ──────────────────────────────────────────────────────────────
# Each rule: (id, severity, compiled pattern, why it matters).
# Patterns are deliberately broad. This gate over-reports on purpose: a false
# REVIEW costs a human thirty seconds, a missed exfiltration costs a machine.

_EXEC = [
    ("exec.subprocess", BLOCK, r"\bsubprocess\.(?:run|call|Popen|check_output)\b",
     "spawns a process"),
    ("exec.os_system", BLOCK, r"\bos\.system\s*\(", "spawns a shell"),
    ("exec.eval", BLOCK, r"(?<![\w.])(?:eval|exec)\s*\(", "evaluates code at runtime"),
    ("exec.dynamic_import", REVIEW, r"__import__\s*\(", "imports by computed name"),
    ("exec.node_child_process", BLOCK, r"require\s*\(\s*['\"]child_process['\"]|from\s+['\"]child_process['\"]",
     "spawns a process"),
    ("exec.shell_pipe", REVIEW, r"\|\s*(?:bash|sh|powershell|iex)\b", "pipes content into a shell"),
]

_NET = [
    ("net.python_http", REVIEW, r"\b(?:urllib\.request|httpx|requests)\.\w+\s*\(|\brequests\.(?:get|post)\b",
     "makes an outbound request"),
    ("net.socket", BLOCK, r"\bsocket\.socket\s*\(", "opens a raw socket"),
    ("net.fetch", REVIEW, r"\bfetch\s*\(\s*['\"]https?://", "makes an outbound request"),
    ("net.curl_wget", REVIEW, r"\b(?:curl|wget)\s+(?:-\S+\s+)*https?://", "downloads at runtime"),
    ("net.websocket", REVIEW, r"\bnew\s+WebSocket\s*\(", "opens a persistent connection"),
]

_SECRET = [
    ("secret.env_read", REVIEW, r"\bos\.environ(?:\.get)?\s*[\[(]\s*['\"](?!PATH|HOME|TMPDIR|TEMP)",
     "reads an environment variable"),
    # NARROWED after calibration run 1 (2026-07-30). The first version was
    # r"\.env\b", which fired 14 times inside a design-rule CSV whose rows
    # merely DISCUSS environment files ("Expose secrets to client") and blocked
    # a skill a human had already read and cleared. A gate that blocks on prose
    # is a gate that gets switched off, so the rule now demands a path or an API
    # context: a quoted/slashed path, or a dotenv loader by name.
    ("secret.dotenv", BLOCK,
     r"""(?:['"/\\]\.env(?:\.\w+)?\b|\bload_dotenv\b|\bdotenv\.config\b|\bfrom\s+dotenv\b)""",
     "reads a secrets file"),
    ("secret.credential_path", BLOCK,
     r"(?:\.ssh/|\.aws/credentials|\.npmrc|\.git-credentials|id_rsa|\.pem\b)",
     "references a credential path"),
    ("secret.keyword", REVIEW, r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|bearer)\b\s*[:=]",
     "assigns something named like a credential"),
]

# Injection: a skill's body is DATA that reaches a model. Text that tries to
# address the model as an instruction is the attack, and skills.py's
# BEGIN SKILL (DATA, NOT INSTRUCTIONS) fence is the mitigation, not the fix.
_INJECT = [
    ("inject.override", BLOCK,
     r"ignore\s+(?:all\s+)?(?:previous|prior|above|the\s+preceding)\s+(?:instructions?|prompts?|rules?)",
     "tries to discard the operator's instructions"),
    ("inject.disregard", BLOCK, r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|earlier)\s+\w+",
     "tries to discard prior context"),
    ("inject.persona", REVIEW, r"you\s+are\s+now\s+(?:a|an|the)\b", "attempts to reassign the model's role"),
    ("inject.system_prompt", REVIEW, r"\b(?:system\s+prompt|reveal\s+your\s+(?:instructions|prompt))\b",
     "asks about or for the system prompt"),
    ("inject.exfil", BLOCK, r"(?:send|post|upload|exfiltrate)\b[^.\n]{0,40}\b(?:to\s+https?://|webhook)",
     "asks for content to be sent somewhere"),
    ("inject.hidden_directive", REVIEW, r"<!--[^>]{0,200}?(?:instruction|prompt|ignore)[^>]{0,200}?-->",
     "carries a directive inside a comment"),
]

_DESTRUCTIVE = [
    ("fs.rmtree", BLOCK, r"\bshutil\.rmtree\s*\(|\brm\s+-rf\b|\bRemove-Item\b[^\n]*-Recurse",
     "deletes a tree"),
    ("fs.write_outside", REVIEW, r"\bopen\s*\([^)]*['\"][wa]", "writes to a file"),
]

RULES = [(rid, sev, re.compile(pat, re.I | re.M), why)
         for rid, sev, pat, why in (_EXEC + _NET + _SECRET + _INJECT + _DESTRUCTIVE)]


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    where: str          # repo-relative-ish path, or "<frontmatter>"
    line: int           # 1-based, 0 when not line-addressable
    excerpt: str        # the matched text, clipped — the evidence
    why: str
    #: Set when a human has acknowledged this capability for this subject. The
    #: severity is then downgraded to REVIEW — never to CLEAR, because the
    #: capability still exists and the operator still deserves to see it.
    acknowledged: str | None = None

    def to_dict(self) -> dict:
        d = {"rule": self.rule, "severity": self.severity, "where": self.where,
             "line": self.line, "excerpt": self.excerpt, "why": self.why}
        if self.acknowledged:
            d["acknowledged"] = self.acknowledged
        return d


# ── acknowledged capabilities ───────────────────────────────────────────────
# Some tools exist in order to do the thing the rule flags. The room skill's
# whole job is launching vendor CLIs, so ``exec.subprocess`` is not a defect in
# it — it is the feature. Softening the rule for everyone would be the wrong fix;
# instead a human names the subject, the rule and the reason, once, in writing.
#
# FAIL-CLOSED PROPERTIES, all deliberate:
#   * an acknowledgement must name BOTH the subject and the exact rule id;
#     there is no wildcard, because "trust this tool entirely" is not a thing
#     anyone can mean responsibly;
#   * it DOWNGRADES to REVIEW, never to CLEAR — an acknowledged capability is
#     still reported on every run, with its reason attached;
#   * an unparseable allowance file is an error that degrades the report, never
#     an empty allowance set that silently blocks everything.
ALLOWANCE_PATH = ".agentenv/tool-allowances.json"


def load_allowances(repo_root) -> tuple[dict[str, dict[str, str]], list[str]]:
    """``{subject: {rule_id: reason}}`` plus read errors. Absent file is fine."""
    import json as _json
    p = Path(repo_root) / ALLOWANCE_PATH
    try:
        raw = _json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as exc:
        return {}, [f"{p}: {exc.__class__.__name__}: {exc}"]
    out: dict[str, dict[str, Any]] = {}
    errs: list[str] = []
    for subject, rules in (raw.get("allow") or {}).items():
        if not isinstance(rules, dict):
            errs.append(f"{p}: allow[{subject!r}] must be an object of rule -> reason")
            continue
        clean: dict[str, Any] = {}
        for rid, entry in rules.items():
            # TWO accepted shapes, and the PINNED one is the point. An
            # adversarial review on 2026-07-30 found this loader rejecting the
            # exact form `apply_allowances` reads -- it required `entry` to be a
            # str, so `{"reason": ..., "body_sha256": ...}` was discarded with a
            # "needs a non-empty reason" error and the whole subject vanished.
            #
            # Consequence, measured: `pinned` could never be non-empty, so
            # `mcp_spec_digest`, the `identity=` arguments and the
            # pin-mismatch refusal were all unreachable, and EVERY allowance
            # anyone could actually write was the weak name-keyed kind. The
            # byte-binding written to close the name-inheritance breach was
            # present in the reader, absent from the writer, and documented as
            # working. It failed closed (the BLOCK stood) but it was reported
            # as a mitigation that did not exist.
            if isinstance(entry, dict):
                reason = entry.get("reason")
                pinned = entry.get("body_sha256")
                if not isinstance(reason, str) or not reason.strip():
                    errs.append(f"{p}: allow[{subject!r}][{rid!r}] needs a "
                                "non-empty reason")
                    continue
                if pinned is not None and (not isinstance(pinned, str)
                                           or not pinned.strip()):
                    errs.append(f"{p}: allow[{subject!r}][{rid!r}].body_sha256 "
                                "must be a non-empty string when present")
                    continue
                item: dict[str, str] = {"reason": reason.strip()}
                if pinned:
                    item["body_sha256"] = pinned.strip()
                clean[str(rid)] = item
            elif isinstance(entry, str) and entry.strip():
                clean[str(rid)] = entry.strip()
            else:
                errs.append(f"{p}: allow[{subject!r}][{rid!r}] must be a "
                            "non-empty reason string, or an object with a "
                            "'reason' and an optional 'body_sha256'")
                continue
        if clean:
            out[str(subject)] = clean
    return out, errs


def mcp_spec_digest(spec) -> str:
    """A stable identity for an MCP server: what will actually be launched.

    An allowance must bind to a THING, never to a NAME -- a name is chosen by
    whoever writes the config, so a name-keyed acknowledgement lets a project
    inherit a user-scope allowance simply by reusing its name. A skill has a file
    body to pin. An MCP server has no body: it is a command line. So its identity
    is that command line.

    Env VALUES are deliberately excluded and only the KEYS are hashed. Including
    values would make the digest churn every time a token rotated, which quietly
    invalidates every pinned allowance and teaches operators to write unpinned
    ones instead -- the exact failure this function exists to prevent. The keys
    still capture WHAT is being injected, which is the part a reviewer judged.
    """
    import hashlib
    import json as _json

    if not isinstance(spec, dict):
        return ""
    env = spec.get("env")
    canonical = {
        "command": str(spec.get("command") or ""),
        "args": [str(a) for a in (spec.get("args") or [])],
        "env_keys": sorted(str(k) for k in env) if isinstance(env, dict) else [],
    }
    blob = _json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def apply_allowances(findings, subject: str, allowances, *, identity: str = "") -> list[Finding]:
    """Downgrade acknowledged BLOCK findings to REVIEW, carrying the reason.

    AN ALLOWANCE BINDS TO BYTES, NOT TO A NAME. An adversarial review on
    2026-07-30 showed why: skills come from several scopes, so a project-scope
    skill called ``room`` inherited the acknowledgement written for the
    user-scope ``room`` and its ``subprocess`` call was downgraded from BLOCK to
    REVIEW. A name is not an identity; anyone who can place a directory can
    choose one.

    So an allowance MAY pin ``body_sha256``. When it does, the acknowledgement
    applies only to the exact bytes a human reviewed -- a different skill of the
    same name does not match, and neither does the SAME skill after it is
    edited, which is the more valuable half. An allowance without a pin still
    works (they are written by hand, and demanding a digest up front would mean
    nobody writes one) but it is reported as UNPINNED so the weaker form is
    visible rather than assumed.
    """
    allowed = (allowances or {}).get(subject) or {}
    out = []
    for f in findings:
        entry = allowed.get(f.rule)
        if not entry or f.severity != BLOCK:
            out.append(f)
            continue
        if isinstance(entry, dict):
            reason = str(entry.get("reason") or "")
            pinned = str(entry.get("body_sha256") or "")
        else:
            reason, pinned = str(entry), ""
        if pinned and pinned != identity:
            # The acknowledgement names other bytes -- or names bytes we could
            # not compute an identity for at all. Refuse it and SAY so, rather
            # than silently falling through to BLOCK with no explanation.
            #
            # `identity` is deliberately NOT part of this condition any more.
            # It used to read `if pinned and identity and pinned != identity`,
            # which fails OPEN in the one case that matters most: a pinned
            # allowance checked against an EMPTY identity was applied, and
            # rendered with no UNPINNED note, so the strongest-looking form --
            # verified against nothing -- was indistinguishable from a real pin
            # match. A pin whose counterpart cannot be computed is a pin that
            # cannot be honoured.
            why = (" (an allowance exists but pins a different body_sha256, so "
                   "it does not apply here)" if identity else
                   " (an allowance exists and pins a body_sha256, but no "
                   "identity could be computed for this subject, so the pin "
                   "cannot be verified and is refused)")
            out.append(Finding(f.rule, f.severity, f.where, f.line, f.excerpt,
                               f.why + why))
            continue
        note = reason if pinned else reason + "  [UNPINNED: this allowance names a "
        if not pinned:
            note += "NAME, not a digest, so any skill answering to this name inherits it]"
        out.append(Finding(f.rule, REVIEW, f.where, f.line, f.excerpt, f.why, note))
    return out


@dataclass(frozen=True)
class Verdict:
    """What a human is being asked to decide, with the evidence attached."""
    subject: str                 # what was vetted
    kind: str                    # "skill" | "mcp_server"
    outcome: str                 # CLEAR | REVIEW | BLOCK | UNSCANNABLE
    findings: tuple[Finding, ...] = ()
    scanned_files: int = 0
    skipped: tuple[str, ...] = ()          # why each unscannable thing was skipped
    notes: tuple[str, ...] = ()
    version: str = VET_VERSION

    @property
    def cleared(self) -> bool:
        """True ONLY for a full scan with nothing found. Everything else — including
        an unreadable file — is not cleared. This property is the whole fail-closed
        contract; callers must not re-derive it from ``findings`` being empty."""
        return self.outcome == CLEAR and not self.skipped

    def to_dict(self) -> dict:
        return {"subject": self.subject, "kind": self.kind, "outcome": self.outcome,
                "cleared": self.cleared, "scanned_files": self.scanned_files,
                "findings": [f.to_dict() for f in self.findings],
                "skipped": list(self.skipped), "notes": list(self.notes),
                "version": self.version}


def _worst(*outcomes: str) -> str:
    return max(outcomes, key=lambda o: _ORDER.get(o, 0))


def _clip(s: str, n: int = 120) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


#: Characters that render as nothing and split a keyword in half. An adversarial
#: review on 2026-07-30 broke every exec rule with ``e​val(`` -- the regex
#: sees two tokens, a Python parser sees one identifier, and a MODEL reading the
#: skill sees "eval". Their presence inside source or instructions is itself a
#: signal, so they are stripped for matching AND reported.
_INVISIBLE = dict.fromkeys(
    [0x00AD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF]
    + list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)))


def _defang(text: str) -> tuple[str, int]:
    """Text with invisible characters removed, and how many were removed.

    Removal, not replacement: a zero-width space between ``e`` and ``val``
    should make the scanner see ``eval``, which is what the interpreter and the
    reader both see. Positions shift, so line numbers come from the ORIGINAL
    text -- see ``scan_text``.
    """
    stripped = text.translate(_INVISIBLE)
    return stripped, len(text) - len(stripped)


def scan_text(text: str, where: str) -> list[Finding]:
    """Every rule hit in one blob. Deterministic: rules in table order, matches in
    file order, so two runs over the same bytes produce identical findings.

    Scanning happens on the DEFANGED text so invisible characters cannot split a
    keyword. Line numbers are computed from the defanged text too, which can
    differ from the original by at most the number of stripped characters on
    preceding lines -- an acceptable drift, and the finding names the rule and
    the excerpt, so a human can still find it.
    """
    out: list[Finding] = []
    text, n_invisible = _defang(text)
    if n_invisible:
        out.append(Finding("obfuscation.invisible_chars", REVIEW, where, 0,
                           f"{n_invisible} zero-width/bidi character(s) removed before scanning",
                           "invisible characters can split a keyword past a scanner "
                           "while a parser and a reader both still see it"))
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for rid, sev, rx, why in RULES:
        for m in rx.finditer(text):
            out.append(Finding(rid, sev, where, line_of(m.start()),
                               _clip(m.group(0)), why))
    return out


def _scan_file(path: Path, rel: str) -> tuple[list[Finding], str | None]:
    """Findings for one file, or a reason it could not be scanned."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return [], f"{rel}: cannot stat ({exc.__class__.__name__})"
    if size > MAX_FILE_BYTES:
        return [], f"{rel}: {size} bytes exceeds the {MAX_FILE_BYTES}-byte scan bound"
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return [], f"{rel}: {path.suffix or 'no'} suffix is not scannable as text"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [], f"{rel}: cannot read ({exc.__class__.__name__})"
    if b"\x00" in raw[:4096]:
        return [], f"{rel}: looks binary (NUL byte in the first 4 KiB)"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Decoding with replacement would let a crafted byte sequence hide a
        # match, so an undecodable file is unscannable, not best-effort.
        return [], f"{rel}: not valid UTF-8"
    return scan_text(text, rel), None


def vet_skill(skill, *, allowances=None) -> Verdict:
    """Vet one ``skills.Skill``. Static, fail-closed.

    Takes the parsed dataclass rather than a path so there is exactly one
    ``SKILL.md`` parser in this repo — ``skills.load_skill`` — and this module
    cannot disagree with it about what a skill is.
    """
    findings: list[Finding] = list(scan_text(skill.body, "SKILL.md"))
    skipped: list[str] = []
    notes: list[str] = []
    scanned = 1

    if skill.allowed_tools_declared:
        notes.append(
            "declares allowed-tools "
            f"{_clip(skill.allowed_tools_declared, 80)!r} — recorded as a REQUEST by the "
            "skill's author, never a grant; a human decides what it actually gets"
        )
        findings.append(Finding("meta.allowed_tools_request", REVIEW, "<frontmatter>", 0,
                                _clip(skill.allowed_tools_declared, 80),
                                "asks for pre-approved tools"))

    if skill.bundled_truncated:
        skipped.append("bundled file listing was truncated by the parser — "
                       "some shipped files were never enumerated, let alone scanned")

    root = Path(skill.directory)
    rels = sorted(skill.bundled_paths)
    if len(rels) > MAX_FILES_SCANNED:
        skipped.append(f"{len(rels)} bundled files exceeds the {MAX_FILES_SCANNED}-file "
                       f"scan bound; {len(rels) - MAX_FILES_SCANNED} were not scanned")
        rels = rels[:MAX_FILES_SCANNED]

    # A ``__pycache__/x.cpython-*.pyc`` is a DERIVATIVE of an ``x.py`` we scanned,
    # so it carries no information the scan of the source did not already cover.
    # Skipping it silently would be a hole (bytecode can outlive or replace its
    # source), so the exemption is conditional: the sibling source must actually
    # be in the scanned set. A planted or orphaned .pyc still lands in `skipped`
    # and still makes the verdict UNSCANNABLE. Without this, every skill that has
    # ever been run sits permanently at UNSCANNABLE, and a gate that is always
    # amber is a gate nobody reads.
    scanned_sources = set()
    deferred: list[str] = []
    for rel in rels:
        if "__pycache__/" in rel.replace("\\", "/") and rel.endswith(".pyc"):
            deferred.append(rel)
            continue
        f, why = _scan_file(root / rel, rel)
        if why:
            skipped.append(why)
        else:
            scanned += 1
            scanned_sources.add(rel.replace("\\", "/"))
        findings.extend(f)

    for rel in deferred:
        posix = rel.replace("\\", "/")
        stem = Path(posix).name.split(".")[0]
        parent = str(Path(posix).parent.parent).replace("\\", "/").lstrip(".").strip("/")
        source = f"{parent}/{stem}.py" if parent else f"{stem}.py"
        if source in scanned_sources:
            notes.append(f"{posix}: bytecode for {source}, which was scanned — not re-read")
        else:
            skipped.append(f"{posix}: compiled bytecode with no scanned source "
                           f"(expected {source}) — cannot be read as text")

    if skill.bundles_code:
        notes.append(f"ships {len(skill.script_paths)} file(s) under scripts/ — "
                     "this repo never executes them, but they were scanned as text")

    findings = apply_allowances(findings, skill.name, allowances,
                                identity=getattr(skill, 'body_sha256', ''))
    for f in findings:
        if f.acknowledged:
            notes.append(f"{f.rule} acknowledged: {f.acknowledged}")

    outcome = CLEAR
    for f in findings:
        outcome = _worst(outcome, f.severity)
    if skipped:
        outcome = _worst(outcome, UNSCANNABLE)

    return Verdict(subject=skill.name, kind="skill", outcome=outcome,
                   findings=tuple(findings), scanned_files=scanned,
                   skipped=tuple(skipped), notes=tuple(notes))


# ── MCP servers ─────────────────────────────────────────────────────────────
# An MCP server is a command line, so what can be judged statically is the
# command line: what it runs, from where, pinned or not, and where its bytes go.

_UNPINNED = re.compile(r"@latest\b|^(?:git\+)?https?://", re.I)
_URL_IN_ARG = re.compile(r"https?://([^/\s'\"]+)", re.I)
_REMOTE_FETCHERS = ("npx", "uvx", "pipx", "bunx", "pnpm", "dlx")


def vet_mcp_server(name: str, spec, *, allowances=None) -> Verdict:
    """Vet one ``.mcp.json`` server entry. Nothing is started or contacted."""
    findings: list[Finding] = []
    notes: list[str] = []
    skipped: list[str] = []

    if not isinstance(spec, dict):
        return Verdict(subject=name, kind="mcp_server", outcome=UNSCANNABLE,
                       skipped=(f"{name}: entry is {type(spec).__name__}, not an object — "
                                "nothing to inspect",))

    cmd = str(spec.get("command") or "")
    args = [str(a) for a in (spec.get("args") or [])]
    line = " ".join([cmd] + args)
    if not cmd:
        skipped.append(f"{name}: no command declared")

    if cmd.lower() in _REMOTE_FETCHERS or any(a.lower() in _REMOTE_FETCHERS for a in args[:1]):
        notes.append(f"launched through {cmd!r}, which fetches code at start-up — "
                     "what runs tomorrow is not what was reviewed today")
        findings.append(Finding("mcp.remote_fetch", REVIEW, f"<mcp:{name}>", 0,
                                _clip(line, 100), "resolves its code from a remote registry at launch"))

    for tok in [cmd] + args:
        if _UNPINNED.search(tok):
            findings.append(Finding("mcp.unpinned", REVIEW, f"<mcp:{name}>", 0, _clip(tok, 80),
                                    "unpinned version or a bare URL — not reproducible"))
            break

    # Where do the bytes go? One implementation of that question exists; call it.
    hosts = sorted({m.group(1).split(":")[0] for a in [cmd] + args for m in _URL_IN_ARG.finditer(a)})
    for h in hosts:
        lane = lane_for_host(h)
        sev = REVIEW if lane == "untrusted" else CLEAR
        if sev != CLEAR:
            findings.append(Finding("mcp.egress", REVIEW, f"<mcp:{name}>", 0, h,
                                    f"reaches {h}, which sensitivity.lane_for_host calls {lane}"))
        else:
            notes.append(f"{h} is on the trusted lane (this machine)")

    env = spec.get("env")
    if isinstance(env, dict) and env:
        keys = sorted(str(k) for k in env)
        findings.append(Finding("mcp.env_injected", REVIEW, f"<mcp:{name}>", 0,
                                _clip(", ".join(keys), 100),
                                "environment values are handed to the server process"))

    findings = apply_allowances(findings, name, allowances,
                                identity=mcp_spec_digest(spec))
    outcome = CLEAR
    for f in findings:
        outcome = _worst(outcome, f.severity)
    if skipped:
        outcome = _worst(outcome, UNSCANNABLE)

    notes.append("static inspection of the launch command only — the server was not started, "
                 "so what it actually exposes at runtime is UNKNOWN, not cleared")
    return Verdict(subject=name, kind="mcp_server", outcome=outcome,
                   findings=tuple(findings), scanned_files=0,
                   skipped=tuple(skipped), notes=tuple(notes))


def summarise(verdicts) -> dict:
    """Counts by outcome, plus the blocking subjects. Sorted; no I/O."""
    vs = list(verdicts)
    by = {CLEAR: 0, REVIEW: 0, BLOCK: 0, UNSCANNABLE: 0}
    for v in vs:
        by[v.outcome] = by.get(v.outcome, 0) + 1
    return {
        "total": len(vs),
        "by_outcome": by,
        "blocking": sorted(v.subject for v in vs if v.outcome == BLOCK),
        "unscannable": sorted(v.subject for v in vs if v.outcome == UNSCANNABLE),
        "cleared": sorted(v.subject for v in vs if v.cleared),
        "version": VET_VERSION,
    }
