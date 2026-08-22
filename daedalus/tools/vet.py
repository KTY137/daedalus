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
    # Odysseus 2026-08-21 F7. A PowerShell MODULE (.psm1) and its manifest
    # (.psd1) carry exactly the code a .ps1 does, and an .mdx doc reaches a model
    # the way an .md doc does; .jsonc is JSON with comments. Without these a
    # payload in one was skipped as unscannable, not scanned.
    ".psm1", ".psd1", ".mdx", ".jsonc",
})

# ── rule table ──────────────────────────────────────────────────────────────
# Each rule: (id, severity, compiled pattern, why it matters).
# Patterns are deliberately broad. This gate over-reports on purpose: a false
# REVIEW costs a human thirty seconds, a missed exfiltration costs a machine.

# Odysseus 2026-08-21 F5. The generic ``exec.eval`` rule keeps its negative
# lookbehind ``(?<![\w.])`` ON PURPOSE: without it, every ``df.eval(...)``
# (pandas), ``cursor.exec(...)`` and other harmless method call floods the gate
# with a BLOCK a human then learns to ignore. So the qualified DANGEROUS
# spellings are not caught by loosening that rule — they are named EXACTLY, one
# namespace at a time, so ``builtins.exec`` blocks while ``obj.exec`` stays
# quiet. Naming the module is what buys the strictness without the flood.
_EXEC = [
    ("exec.subprocess", BLOCK,
     r"\bsubprocess\.(?:run|call|Popen|check_output|check_call|getoutput|getstatusoutput)\b",
     "spawns a process"),
    ("exec.os_system", BLOCK, r"\bos\.system\s*\(", "spawns a shell"),
    # ``os.execv``/``execve``/``spawnv``/``spawnl``/``posix_spawn``/``popen`` all
    # hand control to another program; the ``os.`` qualifier is the whole reason
    # a benign local ``.popen`` or ``.spawn`` method does not match.
    ("exec.os_exec", BLOCK,
     r"\bos\.(?:popen|exec[lv]\w*|spawn[lv]\w*|posix_spawn\w*)\s*\(",
     "hands control to another program"),
    ("exec.eval", BLOCK, r"(?<![\w.])(?:eval|exec)\s*\(", "evaluates code at runtime"),
    # ``builtins.exec(``/``builtins.eval(`` is the qualified spelling the
    # lookbehind above deliberately drops; nobody's own object is named
    # ``builtins``, so naming it is safe.
    ("exec.builtins", BLOCK, r"\bbuiltins\.(?:eval|exec)\s*\(",
     "evaluates code at runtime through builtins"),
    ("exec.pty_spawn", BLOCK, r"\bpty\.spawn\s*\(", "spawns a shell on a pseudo-terminal"),
    ("exec.dynamic_import", REVIEW, r"__import__\s*\(", "imports by computed name"),
    ("exec.node_child_process", BLOCK, r"require\s*\(\s*['\"]child_process['\"]|from\s+['\"]child_process['\"]",
     "spawns a process"),
    ("exec.shell_pipe", REVIEW, r"\|\s*(?:bash|sh|powershell|iex)\b", "pipes content into a shell"),
    # PowerShell dynamic evaluation. REVIEW, not BLOCK: ``iex`` is a bare word
    # with legitimate (if rare) uses and ``Invoke-Expression`` appears in real
    # automation, so the newly-captured spelling costs a human thirty seconds
    # rather than a false refusal. Odysseus 2026-08-21 F5.
    ("exec.powershell_iex", REVIEW, r"\bInvoke-Expression\b|(?<![\w-])iex(?![\w-])",
     "evaluates a string as PowerShell"),
    # ``-EncodedCommand`` / its ``-enc`` abbreviation runs base64'd PowerShell.
    # ``-enc(?:odedcommand)?\b`` matches ``-enc`` and ``-EncodedCommand`` but NOT
    # ``-Encoding`` (no word boundary after ``-enc`` in ``encoding``), so the
    # extremely common ``Set-Content -Encoding`` does not flood the gate.
    ("exec.powershell_encoded", REVIEW, r"-enc(?:odedcommand)?\b",
     "runs a base64-encoded PowerShell command"),
]

_NET = [
    ("net.python_http", REVIEW, r"\b(?:urllib\.request|httpx|requests)\.\w+\s*\(|\brequests\.(?:get|post)\b",
     "makes an outbound request"),
    # Odysseus 2026-08-21 F5. A bare ``urlopen(`` (``from urllib.request import
    # urlopen``) never reached ``urllib.request.\w+``; ``socket.create_connection``
    # opens a connection the same as ``socket.socket``; ``http.client``'s
    # connection classes are the stdlib HTTP client under another name.
    ("net.urlopen", REVIEW, r"\burlopen\s*\(", "makes an outbound request"),
    ("net.socket", BLOCK, r"\bsocket\.(?:socket|create_connection)\s*\(",
     "opens a socket connection"),
    ("net.http_client", REVIEW, r"\b(?:http\.client\.)?HTTPS?Connection\s*\(",
     "opens an HTTP client connection"),
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

#: Rule ids minted inline rather than pattern-matched, so a severity index built
#: only from :data:`RULES` would call them unknown. Every one is REVIEW — which
#: is precisely why an allowance naming one does nothing; see
#: :func:`load_allowances`.
_SYNTHETIC_RULE_SEVERITY = {
    "obfuscation.invisible_chars": REVIEW,
    "meta.allowed_tools_request": REVIEW,
    "mcp.remote_fetch": REVIEW,
    "mcp.unpinned": REVIEW,
    # BLOCK, not REVIEW -- Odysseus 2026-08-21 F2/F3. An MCP server is the harder
    # class (a process AND a socket), and this finding is emitted ONLY when
    # `lane_for_host` calls the destination non-trusted, i.e. the bytes leave
    # this machine. Egress off-box on an untrusted lane is a refusal, not an ask.
    # Keeping it at REVIEW also made `mcp_spec_digest` / the body_sha256 pin
    # unreachable, because `apply_allowances` only ever downgrades a BLOCK: a
    # wrong pin had no effect to have. A trusted-lane (loopback) destination
    # produces no finding at all, so this never fires for this machine.
    "mcp.egress": BLOCK,
    "mcp.env_injected": REVIEW,
}

#: Every rule id this gate can emit, mapped to the severity it emits. The only
#: consumer is the inert-allowance check in :func:`load_allowances`: an
#: acknowledgement is a downgrade from BLOCK, so naming any other rule buys
#: nothing, and an operator who wrote one believes they bought something.
RULE_SEVERITY: dict[str, str] = {rid: sev for rid, sev, _pat, _why in RULES}
RULE_SEVERITY.update(_SYNTHETIC_RULE_SEVERITY)


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

    # WELL-FORMED JSON IS NOT A WELL-FORMED ALLOWANCE FILE, and the docstring
    # above promises a degraded report rather than a crash. An adversarial
    # review on 2026-07-30 found three payloads that parse and then raise
    # AttributeError out of this function -- `[]`, `null` and `{"allow":"x"}` --
    # so a malformed file took down whatever was calling the gate instead of
    # being reported by it. A gate that raises is a gate that gets wrapped in a
    # bare `except` and thereby switched off.
    if not isinstance(raw, dict):
        return {}, [f"{p}: expected a JSON object with an 'allow' key, "
                    f"got {type(raw).__name__} — no allowances were loaded"]
    allow_raw = raw.get("allow")
    if allow_raw is None:
        allow_raw = {}
    if not isinstance(allow_raw, dict):
        return {}, [f"{p}: 'allow' must be an object of subject -> "
                    f"{{rule: reason}}, got {type(allow_raw).__name__} — no "
                    "allowances were loaded"]

    out: dict[str, dict[str, Any]] = {}
    errs: list[str] = []
    for subject, rules in allow_raw.items():
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

        # AN ACKNOWLEDGEMENT THAT CANNOT FIRE IS REPORTED, NOT IGNORED.
        # `apply_allowances` downgrades BLOCK and skips everything else, so an
        # allowance naming a REVIEW rule -- or a rule id that no longer exists
        # -- is inert. It failed safe, and it read to whoever wrote it as a
        # decision that had been recorded and taken. The live file carried one:
        # `room` -> `net.python_http`, which is REVIEW, acknowledged in writing
        # by a human who had no way to learn it did nothing.
        #
        # These degrade the report; they never empty the allowance set. An
        # inert entry stays in `clean` because removing it would make the
        # message describe a state the loader had already discarded.
        for rid in sorted(clean):
            sev = RULE_SEVERITY.get(rid)
            if sev is None:
                errs.append(
                    f"{p}: allow[{subject!r}][{rid!r}] names no rule this gate "
                    f"defines (vet version {VET_VERSION}) — it has no effect")
            elif sev != BLOCK:
                errs.append(
                    f"{p}: allow[{subject!r}][{rid!r}] names a {sev.upper()} "
                    f"rule, but an allowance only downgrades {BLOCK.upper()} — "
                    "this entry has no effect and the finding is reported "
                    "unchanged")

        if clean:
            out[str(subject)] = clean
    return out, errs


#: Environment variables whose VALUE decides what code runs, and which are
#: therefore hashed in full by :func:`mcp_spec_digest` rather than by key alone.
#:
#: The test for membership is not "is it sensitive" -- it is: **can changing this
#: value alone cause different code to execute, with the command line unchanged?**
#: A credential fails that test (it authenticates; it does not redirect
#: execution) and is deliberately absent, so rotating one still does not
#: invalidate a pinned allowance.
#:
#: Measured entry, and the one that made this necessary:
#: ``NODE_OPTIONS=--require /tmp/evil.js`` collided with a reviewed
#: ``NODE_OPTIONS=--max-old-space-size=4096``.
#:
#: Compared case-insensitively: Windows environment variables are
#: case-insensitive, so a check against the exact spelling would be evaded by
#: ``node_options``.
_EXEC_DIRECTING_ENV = frozenset({
    # interpreter flags that can load arbitrary code
    "NODE_OPTIONS", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME",
    "PYTHONEXECUTABLE", "RUBYOPT", "PERL5OPT", "PERL5LIB",
    # dynamic-linker injection
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    # which binary gets found at all
    "PATH", "PATHEXT", "VIRTUAL_ENV", "CONDA_PREFIX",
    # where packages are fetched from -- redirects the SUPPLY, which for an
    # `npx`/`uvx` server is the entire body of code that will run
    "NPM_CONFIG_REGISTRY", "npm_config_registry", "YARN_REGISTRY",
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "UV_INDEX_URL",
    "UV_DEFAULT_INDEX", "CARGO_REGISTRIES_CRATES_IO_PROTOCOL",
    # tool-specific hooks that run code on startup
    "BASH_ENV", "ENV", "PROMPT_COMMAND", "GIT_SSH_COMMAND",
    "GIT_EXTERNAL_DIFF", "GIT_PROXY_COMMAND",
})


def mcp_spec_digest(spec) -> str:
    """A stable identity for an MCP server: what will actually be launched.

    An allowance must bind to a THING, never to a NAME -- a name is chosen by
    whoever writes the config, so a name-keyed acknowledgement lets a project
    inherit a user-scope allowance simply by reusing its name. A skill has a file
    body to pin. An MCP server has no body: it is a command line. So its identity
    is that command line.

    Most env VALUES are excluded and only the KEYS are hashed. Including every
    value would make the digest churn each time a token rotated, which quietly
    invalidates every pinned allowance and teaches operators to write unpinned
    ones instead -- the exact failure this function exists to prevent.

    ADVERSARIAL REVIEW 2026-07-30 showed that "keys capture WHAT is being
    injected" is false for a specific and dangerous class of variable. Proven
    collisions, same digest, materially different server:

        NODE_OPTIONS=--max-old-space-size=4096   vs
        NODE_OPTIONS=--require /tmp/evil.js      -> e85a5746d6b3...

    The second is arbitrary code execution into a server whose digest still
    matched the one a human reviewed. So the split is no longer keys-vs-values,
    it is **does the value decide what executes**:

    * ``_EXEC_DIRECTING_ENV`` values are hashed in full. They select an
      interpreter, a preload, a module search path or a package registry, and
      two servers differing only there are not the same server.
    * every other value is excluded, so token rotation still does not invalidate
      a pin. That was the right instinct and it is preserved exactly.

    Three further collisions from the same review, all closed here:

    * ``cwd`` was in nothing. ``/home/me/reviewed`` and ``/tmp/attacker``
      hashed identically.
    * ``type``/``url``/``headers`` were in nothing, so EVERY command-less
      (remote) spec shared one constant digest -- a single pinned allowance
      would have covered every remote server anyone could add.
    * a non-dict ``env`` (``[["API_KEY","x"]]``, ``"API_KEY=x"``) hashed the
      same as a MISSING env, so malformed config was indistinguishable from
      absent config. Its shape is now recorded instead.

    Header VALUES stay excluded for the original reason: that is where bearer
    tokens live, and their keys already say what is being sent.

    Changing this changes every digest. That is safe to do exactly now and
    would not have been a week from now: until the loader was fixed in the same
    beat as this review, a pinned allowance could not be expressed at all, so
    there are no pins in the wild to invalidate.
    """
    import hashlib
    import json as _json

    if not isinstance(spec, dict):
        return ""
    env = spec.get("env")
    headers = spec.get("headers")
    if isinstance(env, dict):
        env_keys = sorted(str(k) for k in env)
        env_shape = "dict"
        # Sorted pairs, not a dict, so the JSON encoding cannot depend on
        # insertion order for two specs a reader would call identical.
        exec_env = sorted(
            (str(k), str(v)) for k, v in env.items()
            if str(k).upper() in _EXEC_DIRECTING_ENV)
    else:
        env_keys = []
        # NOT "absent". A list-of-pairs or a "K=V" string is a configuration
        # mistake, and a mistake that hashes as absent is a mistake a pinned
        # allowance silently covers.
        env_shape = "absent" if env is None else type(env).__name__
        exec_env = []
    canonical = {
        "command": str(spec.get("command") or ""),
        "args": [str(a) for a in (spec.get("args") or [])],
        "cwd": str(spec.get("cwd") or ""),
        "type": str(spec.get("type") or ""),
        "url": str(spec.get("url") or ""),
        "header_keys": (sorted(str(k) for k in headers)
                        if isinstance(headers, dict) else []),
        "env_keys": env_keys,
        "env_shape": env_shape,
        "exec_directing_env": exec_env,
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
    # A UTF-8 BOM decodes to U+FEFF, which is in `_INVISIBLE`, so every file
    # PowerShell's `Set-Content` writes would otherwise raise a false
    # obfuscation.invisible_chars finding (Odysseus 2026-08-21 F6). skills.py:409
    # strips it before its own scan; match that here so the two agree.
    raw = raw.removeprefix(b"\xef\xbb\xbf")
    # Odysseus 2026-08-21 F8. The old check read only the first 4 KiB, so a NUL
    # byte after that offset read as clean text. A NUL anywhere means the file
    # cannot be honestly read as text, so scan the WHOLE buffer -- it is already
    # bounded by MAX_FILE_BYTES above, so this is a single membership test over
    # at most a couple of megabytes.
    if b"\x00" in raw:
        return [], f"{rel}: looks binary (contains a NUL byte)"
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
    # The body is not the only text a model reads. `skills.render_catalog`
    # surfaces `description` (and `compatibility`) into the listing a model sees
    # BEFORE it ever opens the body -- Odysseus 2026-08-21 F1: a payload placed
    # there reached `scan_text` from nowhere, so the description was the one
    # field most likely to reach a model and the one field never scanned. Each
    # gets its own frontmatter locator so a human can find it.
    findings += scan_text(skill.description or "", "<frontmatter:description>")
    if skill.compatibility:
        findings += scan_text(skill.compatibility, "<frontmatter:compatibility>")
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

#: A URL anywhere on the command line. ``ws``/``wss`` are here because an MCP
#: server is frequently reached over a WebSocket, and until an adversarial
#: review on 2026-07-30 this pattern matched ``https?`` only: a spec of
#: ``{"type":"ws","url":"wss://evil.tld/mcp"}`` reached the egress check with
#: nothing to check, so the one question this gate exists to ask about a remote
#: server was never asked. The match is used WHOLE, never dissected -- see the
#: egress block in :func:`vet_mcp_server`.
_URL_IN_ARG = re.compile(r"(?:https?|wss?)://[^/\s'\"]+", re.I)

#: The floor, applied to every token whether or not a launcher was recognised.
#: This is the pre-2026-07-30 rule and it is kept verbatim in effect so the
#: hardening below can only ever add findings, never remove one.
_UNPINNED_ANY = re.compile(
    r"@(?:latest|next|beta|canary|rc|dev|alpha|nightly|edge|experimental)\b"
    r"|^(?:git\+)?https?://", re.I)

#: Launchers whose entire purpose is to fetch code and then run it.
#:
#: ADVERSARIAL REVIEW 2026-07-30 (Cerberus, high 4). The test used to be
#: ``cmd.lower() in _REMOTE_FETCHERS or any(... for a in args[:1])``. Four
#: evasions, all of them ordinary ways to write a real config, not exotica:
#:
#:   ``npx.cmd``                          -- the Windows shim, PATHEXT resolves it
#:   ``C:\Program Files\nodejs\npx.cmd``  -- an absolute path
#:   ``cmd /c npx ...``                   -- the launcher is now ``args[1]``
#:   ``uv tool run ...``                  -- ``uv`` was not in the set at all
#:
#: So membership is tested against a NORMALISED name (basename, executable
#: suffix stripped) over every WORD of every token — not the raw command plus
#: one argument, and not one token per JSON array element.
#:
#: THE WORD/TOKEN DISTINCTION IS THE POINT, and a second review on the same day
#: found this comment claiming coverage the code did not have. Only the
#: SPACE-SEPARATED spelling ``args:["/c","npx",...]`` was caught; the ordinary
#: one, ``args:["/c","npx -y evil-mcp"]``, is a single JSON string and cleared
#: with zero findings. See :func:`_shell_tokens`.
#:
#: KNOWN-INCOMPLETE, AND DELIBERATELY SO. This set and
#: :data:`_FETCHING_SUBCOMMANDS` are an ALLOWLIST of the ecosystems this repo
#: actually launches MCP servers from (node and python), not a survey of every
#: package manager that exists. ``go run``, ``cargo run``, ``pip install``,
#: ``dnx``, ``gem``, ``composer`` and their siblings fetch code at launch too
#: and are NOT detected here. Chasing every ecosystem would make this table the
#: thing that has to be right, and it would still be behind. So the contract is
#: stated instead of implied: a MISSING ``mcp.remote_fetch`` finding means "no
#: launcher from a known-incomplete list was recognised", never "this command
#: line does not fetch code". Add an entry when this repo starts using an
#: ecosystem, and read the command line yourself in the meantime.
_ALWAYS_FETCHERS = frozenset({"npx", "uvx", "bunx", "dlx"})

#: Package managers that fetch only under certain subcommands. ``uv run``
#: resolves from a registry, ``uv venv`` does not. Flagging the binary
#: unconditionally would report every locally-installed server, and a gate that
#: reports everything is a gate nobody reads.
_FETCHING_SUBCOMMANDS = {
    "uv": frozenset({"run", "tool", "tools"}),
    "npm": frozenset({"exec", "x"}),
    "pnpm": frozenset({"dlx", "exec"}),
    "yarn": frozenset({"dlx"}),
    "bun": frozenset({"x"}),
    "deno": frozenset({"run"}),
    "pipx": frozenset({"run"}),
}

#: Stripped before the membership test, so ``npx.cmd`` and ``npx`` are one
#: launcher. These are the suffixes Windows resolves through ``PATHEXT``.
_EXE_SUFFIXES = (".cmd", ".exe", ".bat", ".ps1", ".com")

#: Flags whose VALUE names the package to fetch. ``uvx --from git+https://...``
#: puts the entire supply chain in the argument after the flag.
_SPEC_BEARING_FLAGS = frozenset({
    "--from", "--with", "--package", "-p", "--spec", "--index-url",
})

#: A version that is a moving pointer rather than a version.
_DIST_TAGS = frozenset({
    "latest", "next", "beta", "alpha", "canary", "rc", "dev",
    "experimental", "nightly", "edge", "unstable", "main", "master", "head",
})

#: THE ONLY SPELLING OF "THIS EXACT CODE": a full three-part semantic version,
#: with the optional prerelease and build metadata semver allows.
#:
#: ADVERSARIAL REVIEW 2026-07-30 (Cerberus, medium). The previous test was
#: "starts with a digit and contains no range character", which accepted
#: ``pkg@1`` and ``pkg@1.0`` as pinned. npm resolves both as X-RANGES —
#: ``1`` means ``>=1.0.0 <2.0.0`` — so the two shapes that read most like a pin
#: to a human are among the widest ranges the registry accepts, and the gate
#: was quiet about exactly them.
#:
#: THE LEADING ``v`` IS ACCEPTED, and this is the deliberate call the review
#: asked for. ``pkg@v1.2.3`` used to be reported UNPINNED although it resolves
#: to precisely one version (npm strips the ``v``). Reporting an exact pin as
#: unpinned is the expensive direction of wrong here: it teaches an operator
#: that pinning does not buy silence, and an operator who believes that stops
#: pinning. ``v`` is a spelling of the same number, so it is treated as one.
_EXACT_VERSION = re.compile(
    r"v?\d+\.\d+\.\d+"          # major.minor.patch — all three, or it is a range
    r"(?:-[0-9A-Za-z.-]+)?"     # prerelease:  1.2.3-rc.1
    r"(?:\+[0-9A-Za-z.-]+)?"    # build meta:  1.2.3+build.5
)


def _exe_name(token: str) -> str:
    """The bare launcher name: no directory, no Windows executable suffix.

    Returns ``""`` for anything carrying a scheme, so a URL whose last path
    segment happens to read like a launcher (``.../bin/npx``) cannot be
    mistaken for one.
    """
    raw = str(token).strip().strip('"').strip("'")
    if "://" in raw:
        return ""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].lower()
    # Odysseus 2026-08-21 F10. Quotes INSIDE the word are stripped, not just the
    # surrounding pair: a shell reads ``n"p"x`` as the single program ``npx``,
    # and without this the token normalised to ``n"p"x`` and matched nothing.
    # Removal only ever concatenates, so it can reveal a hidden launcher but
    # never hide a visible one -- the strict direction.
    name = name.replace('"', '').replace("'", "")
    for suf in _EXE_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


#: What ends one word and starts another INSIDE a single JSON string. A shell
#: wrapper's payload is one argument to ``json.load`` and a whole command line
#: to the shell that receives it, and it is the shell's reading that decides
#: what executes.
_WORD_SEPARATORS = re.compile(r"[\s;&|`()<>]+")


def _shell_tokens(parts) -> list[str]:
    """Every WORD on this command line, with shell wrappers flattened out.

    ADVERSARIAL REVIEW 2026-07-30 (Cerberus, critical 1). ``_exe_name`` never
    splits on whitespace, so a launcher hidden inside a quoted payload was one
    opaque token and the gate reported ZERO findings for all of:

        {"command":"cmd",       "args":["/c",      "npx -y evil-mcp"]}
        {"command":"sh",        "args":["-c",      "npx -y evil-mcp"]}
        {"command":"bash",      "args":["-c",      "uvx evil-mcp"]}
        {"command":"powershell","args":["-Command","npx -y evil-mcp"]}

    Splitting first makes every one of them an ordinary token list, so the
    existing normalisation and membership tests do the work unchanged. The
    separator set covers shell word boundaries too (``a&&npx``, ``a;npx``,
    ``$(npx)``), because a payload is free to use them and the cost of being
    wrong in that direction is one extra REVIEW line.

    Splitting a Windows path that contains spaces is harmless: the basename
    still lands in its own word, so ``C:\\Program Files\\nodejs\\npx.cmd``
    still normalises to ``npx``.
    """
    out: list[str] = []
    for part in parts:
        for word in _WORD_SEPARATORS.split(str(part)):
            if word:
                out.append(word)
    return out


def _remote_fetch_reason(cmd: str, args) -> str:
    """Why this command line fetches code at launch, or ``""`` if it does not.

    Every word is considered — see :func:`_shell_tokens` for why a token is not
    a word. A shell wrapper (``cmd /c npx``) or a subcommand (``uv tool run``)
    puts the real launcher arbitrarily far to the right, and the position it
    lands in is chosen by whoever wrote the config.

    The fetching subcommand is searched for ANYWHERE after its manager, not just
    in the next position: the same review showed ``uv --directory /path run
    server.py`` clearing, because one non-flag token between ``uv`` and ``run``
    shifted the subcommand out of the single slot that was being examined, and
    a manager accepts any number of those. The looser test cannot invent a
    ``uv venv`` false positive — ``venv`` is not a fetching subcommand — but it
    can fire on a manager whose ARGUMENT happens to be spelled like one
    (a directory named ``run``). That is the direction this gate over-reports
    in on purpose.
    """
    tokens = [_exe_name(t) for t in _shell_tokens([cmd, *args])]
    for i, tok in enumerate(tokens):
        if not tok:
            continue
        if tok in _ALWAYS_FETCHERS:
            return tok
        subs = _FETCHING_SUBCOMMANDS.get(tok)
        if subs:
            rest = [t for t in tokens[i + 1:] if t and not t.startswith("-")]
            hit = next((t for t in rest if t in subs), "")
            if hit:
                return f"{tok} {hit}"
    return ""


def _unpinned_reason(token: str) -> str:
    """Why this package spec is not reproducible, or ``""`` if it is pinned.

    The rule this closes: ``npx -y @upstash/context7-mcp`` carries no version
    at all, so a pattern hunting for ``@latest`` saw nothing to report while the
    config resolved to whatever the registry called current that morning. This
    repo's own ``.mcp.json`` was the instance that proved it.

    The leading ``@`` of a scoped npm package is a SCOPE, not a version, and
    treating it as one is how a correct pin gets reported as unpinned.

    "Pinned" means one thing only: :data:`_EXACT_VERSION`, a full three-part
    version. A partial one (``pkg@1``, ``pkg@1.0``) is an npm X-range wearing a
    pin's clothes and is reported; ``pkg@v1.2.3`` is that same number spelled
    with a ``v`` and is not.
    """
    t = str(token).strip().strip('"').strip("'")
    if not t or t.startswith("-"):
        return ""
    low = t.lower()
    if "://" in low or low.startswith(("git+", "github:", "file:", "git@")):
        return ("resolved from a URL, so what it installs can change without "
                "the config changing")
    if "==" in t:                      # PEP 508 exact pin
        return ""
    if any(op in t for op in (">=", "<=", "~=", "!=", ">", "<")):
        return f"{t!r} is a version RANGE — it resolves to whatever is newest at launch"

    body = t
    if body.startswith("@"):           # npm scope: @scope/name[@version]
        slash = body.find("/")
        if slash == -1:
            return ""                  # not a package spec at all
        body = body[slash + 1:]
    at = body.rfind("@")
    if at <= 0:
        # No version component. Only meaningful for something that LOOKS like a
        # package name -- a bare path or a subcommand must not be reported.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", body):
            return ""
        return ("no version at all — it resolves to whatever the registry "
                "calls current at launch")
    ver = body[at + 1:].strip()
    if not ver:
        return "an empty version component"
    if ver.lower() in _DIST_TAGS:
        return f"@{ver} is a dist-tag — a moving pointer, not a version"
    if _EXACT_VERSION.fullmatch(ver):
        return ""
    if any(c in ver for c in "^~*<>| ") or any(s in ("x", "X", "*")
                                               for s in ver.split(".")):
        return f"@{ver} is a range or a wildcard, not an exact version"
    if re.fullmatch(r"v?\d+(?:\.\d+)?", ver):
        # `pkg@1` and `pkg@1.0`. These LOOK pinned, which is exactly why they
        # are worth a sentence: npm reads a partial version as an X-range, so
        # `1` is `>=1.0.0 <2.0.0` and the next major-compatible publish is
        # picked up without the config changing.
        return (f"@{ver} is a PARTIAL version — npm resolves it as the range "
                f"{ver}.x, so it is not the code that was reviewed")
    return f"@{ver} is not an exact three-part version"


def _package_spec_tokens(cmd: str, args) -> list[str]:
    """The tokens on this command line that name a package to be fetched.

    Two shapes, both real: the value of a spec-bearing flag (``--from X``), and
    the first bare argument after the launcher, which is what ``npx`` and
    ``uvx`` treat as the package.

    Both shapes are looked for in the WORD view as well as the raw one, for the
    same reason as :func:`_shell_tokens`: once a wrapped payload like
    ``cmd /c "npx -y evil-mcp"`` is recognised as a fetch, the package inside it
    must be reachable too, or the gate reports that code will be downloaded
    while staying silent about the fact that the config does not say which code.
    The raw view is consulted FIRST, and only for flag values, because quoting
    is what holds a spaced spec together — see the comment below.
    """
    def flag_values(toks: list[str]) -> list[str]:
        return [toks[i + 1] for i, t in enumerate(toks)
                if t.strip().lower() in _SPEC_BEARING_FLAGS and i + 1 < len(toks)]

    # A spec-bearing flag's value is read from the RAW arguments FIRST, because
    # quoting is what holds a spaced spec together: PEP 508 permits
    # ``--from "pkg == 1.4.2"``, and in the word view that is three words whose
    # first one, ``pkg``, reads as a package with no version — reporting a
    # correct pin as unpinned, which is the one direction of wrong this
    # function's docstring says not to be. The word view is the FALLBACK, for
    # when the flag itself is inside a wrapped payload.
    raw = [str(a) for a in [cmd, *args]]
    tokens = _shell_tokens(raw)
    out = flag_values(raw) or flag_values(tokens)
    if out:
        # A spec-bearing flag already named the package, so the bare argument
        # after it is the ENTRY POINT, not a second package: in
        # ``uvx --from pkg==1.4.2 srv``, ``srv`` is the console script the
        # package installs. Reading it as a package spec reported a correctly
        # pinned config as unpinned — a false positive here is worse than a
        # miss, because it teaches operators that pinning does not help.
        return out
    launcher_seen = False
    launcher = ""
    skip_next = False
    for tok in tokens:
        s = tok.strip()
        if skip_next:
            skip_next = False
            continue
        if s.lower() in _SPEC_BEARING_FLAGS:
            skip_next = True
            continue
        low = _exe_name(s)
        if low in _ALWAYS_FETCHERS or low in _FETCHING_SUBCOMMANDS:
            launcher_seen = True
            launcher = low
            continue
        if s.startswith("-"):
            continue
        if launcher_seen and low in _FETCHING_SUBCOMMANDS.get(launcher, frozenset()):
            continue
        if any(s.lower() in subs for subs in _FETCHING_SUBCOMMANDS.values()):
            continue                    # a subcommand word, not a package
        if launcher_seen:
            out.append(s)
            break
    return out


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
    url = str(spec.get("url") or "")
    stype = str(spec.get("type") or "")
    line = " ".join([cmd, *args]).strip()
    if not cmd:
        if url:
            # A remote server has no launch command: the code is not on this
            # machine at all. That is not "nothing to inspect" — it is the
            # strongest available statement about where the bytes go. Until
            # this review `url` reached no rule, so a spec of
            # {"type":"http","url":"https://evil.tld/mcp"} produced ZERO
            # findings and read as an ordinary unscannable entry.
            skipped.append(f"{name}: remote {stype or 'url'} server — no local command to "
                           f"inspect; everything it runs lives at {url}")
        else:
            skipped.append(f"{name}: no command declared")

    fetch = _remote_fetch_reason(cmd, args)
    if fetch:
        notes.append(f"launched through {fetch!r}, which fetches code at start-up — "
                     "what runs tomorrow is not what was reviewed today")
        findings.append(Finding("mcp.remote_fetch", REVIEW, f"<mcp:{name}>", 0,
                                _clip(line, 100), "resolves its code from a remote registry at launch"))

    for tok in [cmd, *args]:
        if _UNPINNED_ANY.search(tok):
            findings.append(Finding("mcp.unpinned", REVIEW, f"<mcp:{name}>", 0, _clip(tok, 80),
                                    "unpinned version or a bare URL — not reproducible"))
            break
    else:
        # The floor matched nothing. Only now is the more expensive question
        # worth asking, and only where the command line actually fetches:
        # NO VERSION AT ALL is unpinned too, and that is the shape this repo's
        # own context7 entry was written in — `npx -y @upstash/context7-mcp`.
        for tok in (_package_spec_tokens(cmd, args) if fetch else ()):
            why = _unpinned_reason(tok)
            if why:
                findings.append(Finding("mcp.unpinned", REVIEW, f"<mcp:{name}>", 0,
                                        _clip(tok, 80), why))
                break

    # Where do the bytes go? One implementation of that question exists; call
    # it, and give it the URL RATHER THAN A HOST THIS MODULE PARSED OUT.
    #
    # ADVERSARIAL REVIEW 2026-07-30 (Cerberus, critical 2). This block used to
    # read `m.group(1).split(":")[0]`, which is a second, worse host parser
    # sitting directly on top of the invariant in this module's docstring:
    # lane decisions have exactly one implementation. It got loopback wrong in
    # the ATTACKER'S favour, twice:
    #
    #   http://127.0.0.1:8080@evil.tld/mcp -> "127.0.0.1"  (userinfo, not host)
    #       -> lane "trusted" -> no finding, and the verdict printed
    #          "127.0.0.1 is on the trusted lane (this machine)" for a server
    #          whose bytes go to evil.tld.
    #   http://[::1]:8080/mcp              -> "["          (bracketed IPv6)
    #       -> lane "untrusted" -> a finding whose evidence was one character.
    #
    # `lane_for_host` already parses with `urlsplit().hostname`, which strips
    # userinfo and unwraps brackets. Handing it the whole match deletes the
    # second parser instead of repairing it, and the finding then quotes the
    # URL that was actually written -- which is the evidence a human needs.
    # Odysseus 2026-08-21 F9 / Cerberus residual. A destination can hide in an
    # env VALUE (``WEBHOOK=https://evil.tld/x``) or in ``cwd`` as easily as on the
    # command line, and those reached no lane check. Env values are OPAQUE, so
    # only a real ``scheme://host`` (what `_URL_IN_ARG` already matches) is
    # considered -- a plain token is never reported as egress.
    egress_sources = [cmd, url, *args]
    cwd = spec.get("cwd")
    if isinstance(cwd, str):
        egress_sources.append(cwd)
    env = spec.get("env")
    if isinstance(env, dict):
        egress_sources.extend(str(v) for v in env.values())
    urls = sorted({m.group(0) for a in egress_sources
                   for m in _URL_IN_ARG.finditer(a)})
    for u in urls:
        lane = lane_for_host(u)
        if lane != "trusted":
            # BLOCK, not REVIEW: this branch is only reached for a non-trusted
            # lane, i.e. bytes that leave this machine. See _SYNTHETIC_RULE_
            # SEVERITY["mcp.egress"]. A body_sha256-pinned allowance can downgrade
            # it to REVIEW; nothing else can.
            findings.append(Finding("mcp.egress", BLOCK, f"<mcp:{name}>", 0, u,
                                    f"reaches {u}, which sensitivity.lane_for_host "
                                    f"calls {lane}"))
        else:
            notes.append(f"{u} is on the trusted lane (this machine)")

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
