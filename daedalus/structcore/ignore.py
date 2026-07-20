"""Per-repo structural ignore rules (``.daedalusignore``).

WHY THIS EXISTS, AND WHY IT IS NOT ``_IGNORE_DIRS``
---------------------------------------------------
``index._IGNORE_DIRS`` is a fixed blocklist of things that are *never* source
anywhere (``.git``, ``node_modules``, ``__pycache__``). It cannot express the
case this module serves: material that is real, checked-in, source-shaped, and
still not *this project's* code -- vendored references, spec copies, generated
skeletons, textbook examples kept for lookup. Only the repo knows that, so the
rules live in the repo.

SEMANTICS (deliberate, and not the obvious choice)
--------------------------------------------------
An ignored file is **excluded from metrics, but kept for import resolution**:

  * it still occupies the file-set indexes, so a real file importing *into*
    ``references/`` still resolves to a real edge instead of silently
    degrading to "external";
  * it is still parsed, so its own outgoing edges stay honest too;
  * it is withheld from ``modules``, ``hotspots``/``module_heat``, every clone
    pass, and the language/LOC summary.

The cost of that choice is near zero and the payoff is large, because of where
scan time actually goes: the per-file parse is ~1.9s of a ~102s warm scan while
the clone passes are ~96% of it. Keeping the parse buys an honest dependency
graph for ~2% of the budget; dropping ignored files from clone clustering skips
the part that is actually expensive.

Withholding is therefore never silent -- ``build_index`` reports the counts and
the rules that produced them, in the same spirit as ``report.truncated``.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

IGNORE_FILENAME = ".daedalusignore"


@dataclass(frozen=True)
class _Rule:
    pattern: str      # normalised, no leading '!', no trailing '/'
    negated: bool     # '!foo' re-includes something an earlier rule excluded
    dir_only: bool    # 'foo/' matches the directory and everything under it
    anchored: bool    # 'a/b' is repo-root-relative; 'b' matches at any depth


def _parse_line(raw: str) -> _Rule | None:
    line = raw.rstrip("\n").rstrip()
    if not line or line.lstrip().startswith("#"):
        return None
    negated = line.startswith("!")
    if negated:
        line = line[1:]
    dir_only = line.endswith("/")
    line = line.strip("/") if dir_only else line.lstrip("/")
    if not line:
        return None
    # A pattern containing a slash is repo-root anchored, exactly as gitignore
    # defines it: 'docs/vendor' means that path, not any directory named
    # 'vendor' inside any 'docs'.
    anchored = "/" in line or raw.lstrip().startswith("/")
    return _Rule(pattern=line, negated=negated, dir_only=dir_only, anchored=anchored)


@dataclass
class IgnoreRules:
    """Ordered rule list. Last match wins, so ``!`` can carve exceptions."""

    rules: list[_Rule] = field(default_factory=list)
    source: str = ""          # path the rules came from, "" when none
    fingerprint: str = ""     # stable hash; part of the index cache key

    def __bool__(self) -> bool:
        return bool(self.rules)

    def matches(self, rel: str) -> bool:
        """True when repo-relative POSIX path ``rel`` is ignored.

        Last-match-wins, so ordering is load-bearing and callers must not
        reorder the file. A directory rule matches every descendant, which is
        the only reason ``references/`` covers ``references/a/b.py``.
        """
        verdict = False
        segments = rel.split("/")
        for rule in self.rules:
            if self._hit(rule, rel, segments):
                verdict = not rule.negated
        return verdict

    @staticmethod
    def _hit(rule: _Rule, rel: str, segments: list[str]) -> bool:
        pat = rule.pattern
        if rule.anchored:
            if fnmatchcase(rel, pat):
                return True
            # Directory prefix: 'docs/vendor' must swallow 'docs/vendor/x.py'.
            if rel.startswith(pat + "/"):
                return True
            # '**' spans separators, which fnmatch's '*' does not.
            return "**" in pat and fnmatchcase(rel, pat.replace("**/", "*"))
        # Unanchored: match any path segment. For dir_only rules only the
        # directory segments count -- 'build/' must not swallow a FILE named
        # 'build', which is why the last segment is excluded there.
        candidates = segments[:-1] if rule.dir_only else segments
        return any(fnmatchcase(seg, pat) for seg in candidates)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_ignore_rules(root) -> IgnoreRules:
    """Read ``<root>/.daedalusignore``. Missing/unreadable file -> empty rules.

    The fingerprint covers the raw file bytes and is folded into the index
    cache key by ``cached_index``. Without that, editing the ignore file would
    hand back the previous process-cached index and look like the feature
    simply did not work.
    """
    path = Path(root) / IGNORE_FILENAME
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return IgnoreRules(rules=[], source="", fingerprint="")
    rules = [r for r in (_parse_line(ln) for ln in text.splitlines()) if r is not None]
    return IgnoreRules(rules=rules, source=str(path), fingerprint=_fingerprint(text))


def env_extra_patterns() -> list[str]:
    """``DAEDALUS_IGNORE`` -- os.pathsep-separated patterns, applied after the
    file. Exists so a scan can be scoped without editing a tracked file."""
    raw = os.environ.get("DAEDALUS_IGNORE", "").strip()
    if not raw:
        return []
    return [p for p in (s.strip() for s in raw.split(os.pathsep)) if p]


def _norm_center(entries) -> tuple[str, ...]:
    """Normalise center paths to repo-relative POSIX, no leading/trailing '/'."""
    out = []
    for e in entries or ():
        s = str(e).replace("\\", "/").strip().strip("/")
        if s and s != ".":
            out.append(s)
    # Sorted + de-duplicated: this feeds the cache fingerprint, so two configs
    # that name the same roots in a different order must not build twice.
    return tuple(sorted(set(out)))


@dataclass(frozen=True)
class ProjectScope:
    """Concentric scope for a repo: a CENTER, a SHELL, and everything outside.

    ``.daedalusignore`` answers "what is not my code?" by enumeration, which is
    open-ended -- every newly vendored directory is a rule you forgot to add.
    ``center`` answers the same question by declaration: *this* is the project;
    everything else in the repo is periphery. One line that stays correct.

    Three zones, and the middle one is the point:

      * **core**   -- inside a center root. Full metrics, clone passes,
        hotspots, and free slice expansion.
      * **shell**  -- in the repo, outside the center (vendored trees, spec
        copies, generated skeletons). Still indexed and still resolvable as an
        import target, so edges pointing at it stay true, but withheld from
        every metric and treated as a BOUNDARY by the slicer: you may name it,
        you do not expand through it.
      * **outside** -- not in the repo at all. An external dependency; a name.

    An empty center means the whole repo is the core, which is the historical
    behaviour and what every un-configured repo keeps getting.
    """

    center: tuple[str, ...] = ()
    ignore: IgnoreRules = field(default_factory=IgnoreRules)

    @property
    def fingerprint(self) -> str:
        return _fingerprint("|".join(self.center) + "#" + self.ignore.fingerprint)

    def in_center(self, rel: str) -> bool:
        if not self.center:
            return True
        return any(rel == c or rel.startswith(c + "/") for c in self.center)

    def is_shell(self, rel: str) -> bool:
        """True when ``rel`` is indexed-but-peripheral: outside the declared
        center, or matched by an ignore rule. These are the files withheld from
        metrics and not expanded through."""
        return (not self.in_center(rel)) or self.ignore.matches(rel)

    def describe(self) -> dict:
        return {
            "center": list(self.center),
            "ignore_patterns": [
                ("!" if r.negated else "") + r.pattern + ("/" if r.dir_only else "")
                for r in self.ignore.rules
            ],
            "source": self.ignore.source,
        }


def env_center() -> tuple[str, ...]:
    """``DAEDALUS_CENTER`` -- os.pathsep-separated repo-relative roots."""
    raw = os.environ.get("DAEDALUS_CENTER", "").strip()
    if not raw:
        return ()
    return _norm_center(raw.split(os.pathsep))


# Tests are real, first-class code -- but they are not DISTILLATION TARGETS, and
# they dominate the rankings they pollute: on project_tct's TCT_app, two of the
# top six hotspots were test files. "What should I refactor?" should not answer
# with the test suite. Offered as a named preset so a project says
# ``"ignore": ["@tests"]`` instead of re-deriving five patterns by hand.
IGNORE_PRESETS: dict[str, tuple[str, ...]] = {
    "@tests": ("tests/", "test/", "test_*.py", "*_test.py", "*_test.go",
               "conftest.py", "__tests__/", "*.test.ts", "*.test.tsx",
               "*.test.js", "*.spec.ts", "*.spec.js"),
}


def expand_presets(patterns) -> list[str]:
    """Replace ``@name`` entries with their preset patterns, order preserved.

    An unknown ``@name`` is passed through untouched rather than dropped: a
    silent no-op would look exactly like a preset that did nothing.
    """
    out: list[str] = []
    for p in patterns or ():
        s = str(p).strip()
        if s in IGNORE_PRESETS:
            out.extend(IGNORE_PRESETS[s])
        elif s:
            out.append(s)
    return out


def project_scope(root, center=None, extra_ignore=None) -> ProjectScope:
    """Resolve the scope for ``root``.

    ``center`` precedence: explicit argument (project config / CLI flag) over
    ``DAEDALUS_CENTER``. Ignore rules compose in a fixed order -- center says
    which tree is yours, ignore carves exceptions *within* it:

        .daedalusignore  ->  DAEDALUS_IGNORE  ->  extra_ignore (project config)

    Later wins, because ``matches()`` is last-match-wins. That ordering lets a
    project config re-include something the repo file excluded (``!path``),
    which is the only way a shared repo file and a per-project override can
    coexist.
    """
    chosen = _norm_center(center) if center else env_center()
    rules = effective_rules(root)
    extra = expand_presets(extra_ignore)
    if extra:
        parsed = [r for r in (_parse_line(p) for p in extra) if r is not None]
        rules = IgnoreRules(
            rules=rules.rules + parsed,
            source=", ".join(filter(None, [rules.source, "project config"])),
            fingerprint=_fingerprint(rules.fingerprint + "|" + "|".join(extra)),
        )
    return ProjectScope(center=chosen, ignore=rules)


def effective_rules(root) -> IgnoreRules:
    """File rules plus ``DAEDALUS_IGNORE``, in that order (env wins on tie)."""
    base = load_ignore_rules(root)
    extra = env_extra_patterns()
    if not extra:
        return base
    parsed = [r for r in (_parse_line(p) for p in extra) if r is not None]
    combined = base.rules + parsed
    return IgnoreRules(
        rules=combined,
        source=", ".join(filter(None, [base.source, "DAEDALUS_IGNORE"])),
        fingerprint=_fingerprint(base.fingerprint + "|" + "|".join(extra)),
    )
