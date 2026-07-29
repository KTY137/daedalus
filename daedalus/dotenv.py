"""dotenv -- load ``.env`` into the process environment, and refuse to do it
when loading would itself be the leak.

WHY THIS EXISTS
---------------
``.env.example`` has always told the operator to "export them / source `.env`
in your shell", and nothing in this tree ever read the file. That instruction is
the failure mode it warns about: an operator writes ``DEEPSEEK_API_KEY=sk-...``
into ``.env``, the harness reads the PROCESS environment, finds nothing, and the
external lane stays dormant. No error, no warning -- a configured key that does
nothing, which looks exactly like a broken provider.

THREE RULES, AND THE MIDDLE ONE IS THE SECURITY PROPERTY
--------------------------------------------------------
1. **A real environment variable always wins.** ``.env`` fills GAPS; it never
   overwrites. An operator who exports a key for one command must not be
   silently overridden by a file they edited last month. This also makes the
   loader idempotent and safe to call more than once.

2. **A git-TRACKED ``.env`` is refused, loudly.** ``.gitignore`` covers ``.env``
   and ``.env.*`` today, but ``git add -f`` overrides that, and a tracked secret
   file is a leak already in progress. Loading it would make the leak
   convenient; refusing makes it visible. This is the one condition that raises
   rather than warns -- everything else here degrades to "did not load".

3. **Values are never logged, echoed, or returned.** :func:`load` returns the
   NAMES it set and nothing else, so a caller cannot accidentally print a key
   while reporting what it configured.

NOT A DOTENV LIBRARY. This deliberately implements the small subset that
``.env.example`` actually uses -- ``KEY=value``, ``#`` comments, an optional
``export`` prefix, and surrounding quotes. It does not do interpolation,
multi-line values, or command substitution: every one of those is a way for a
config file to execute something, and a secrets file is the last place that
should be possible.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / ".env"

__all__ = ["DotEnvRefused", "parse", "load", "describe"]


class DotEnvRefused(RuntimeError):
    """The file exists but loading it would be unsafe. Never caught-and-ignored
    inside this module: the caller is meant to see it."""


def _is_git_tracked(path: Path) -> bool:
    """True if git tracks this path. A tracked ``.env`` means the secret is
    already in the repository's history, or one commit away from being.

    Any git failure (no repo, no git binary, timeout) returns False: this check
    can only ever ADD a refusal, so an environment where it cannot run must not
    become an environment where nothing loads.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=str(path.parent), capture_output=True, timeout=10,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def parse(text: str) -> dict[str, str]:
    """``KEY=value`` pairs from dotenv text. Malformed lines are SKIPPED, not
    fatal -- one bad line in a config file must not take the whole harness down,
    and the operator finds it via `daedalus doctor` reporting the key missing.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if not all(c.isalnum() or c == "_" for c in key):
            continue
        value = value.strip()
        # Strip ONE matching pair of surrounding quotes. Anything inside stays
        # verbatim -- no escape processing, because a secret is bytes, not code.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def load(path: Path | None = None, *, override: bool = False) -> list[str]:
    """Fill gaps in ``os.environ`` from ``path``. Returns the NAMES set.

    A missing file is the normal case and returns ``[]``. ``override`` exists
    for tests only; production callers leave it False so a real export always
    beats the file.

    Raises :class:`DotEnvRefused` when the file is tracked by git.
    """
    p = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not p.is_file():
        return []
    if _is_git_tracked(p):
        raise DotEnvRefused(
            f"{p} is tracked by git. A committed secrets file is a leak, not a "
            f"config: run `git rm --cached {p.name}`, rotate anything that was "
            f"in it, and confirm .gitignore covers it. Refusing to load."
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []

    names: list[str] = []
    for key, value in parse(text).items():
        # PRESENCE, not truthiness. `os.environ.get(key)` treated an exported-
        # but-EMPTY variable as absent, so the file overwrote it -- and an empty
        # export is exactly how an operator says "clear this list for the
        # session" (e.g. `DAEDALUS_TRUSTED_HOSTS=`). A deliberate narrowing
        # must never be silently re-widened by a config file. Found by Cerberus.
        if not override and key in os.environ:
            continue  # a real export wins; see rule 1
        os.environ[key] = value
        names.append(key)
    return names


def describe(path: Path | None = None) -> dict[str, object]:
    """Report for `doctor`: whether a ``.env`` exists, which KEYS it declares,
    and whether it is safe to load. Deliberately carries no values -- the whole
    point is that a status command can be pasted into an issue.
    """
    p = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not p.is_file():
        return {"path": str(p), "present": False, "tracked": False,
                "keys": [], "safe": True}
    tracked = _is_git_tracked(p)
    try:
        keys = sorted(parse(p.read_text(encoding="utf-8")))
    except OSError:
        keys = []
    return {"path": str(p), "present": True, "tracked": tracked,
            "keys": keys, "safe": not tracked}
