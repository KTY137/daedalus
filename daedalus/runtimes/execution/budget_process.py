"""Runtime-owned process spend classification and interposition.

The kernel ledger owns money state. This module adapts process and urllib
calls to that ledger and accepts explicit classifier/reservation ports at
installation so the stable daedalus.budget effect facade retains its
documented monkeypatch seams without reverse-importing the facade.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from daedalus.kernel.policy.ledger import Ledger, Reservation, reserve


@contextmanager
def guard(
    vendor: str | None,
    model: str | None = None,
    *,
    label: str,
    calls: int = 1,
    host: str | None = None,
    led: Ledger | None = None,
) -> Iterator[Reservation]:
    """Reserve, run the body, settle.

    ON EXCEPTION THIS SETTLES, IT DOES NOT RELEASE. An exception raised while a
    vendor call is in flight tells you nothing about whether the request
    reached the vendor -- a timeout after the tokens were generated looks
    exactly like a connection refused. Charging for a call that may not have
    happened over-counts by at most one call; the reverse under-counts without
    bound.
    """
    res = reserve(vendor, model, label=label, calls=calls, host=host, led=led)
    token = _enter_explicit()
    try:
        yield res
    finally:
        _exit_explicit(token)
        res.settle()


# --------------------------------------------------------------------------
# classification -- what is a billable call, seen from the syscall boundary
# --------------------------------------------------------------------------

# argv[0] basenames that ARE a paid vendor.
#
# ``claude-code`` is the npm-package binary name for the same Anthropic CLI that
# ships as ``claude`` (`npx @anthropic-ai/claude-code -p ...`). MEASURED
# 2026-07-29: before it was listed here, ``classify_argv`` returned None for
# both ``["claude-code", "-p", ...]`` and ``["npx", "@anthropic-ai/claude-code",
# ...]`` -- the wrapper scan takes the basename of the package spec, which is
# "claude-code", not "claude". The OpenAI spec (`@openai/codex`) survived only
# by luck: its basename happens to be exactly "codex".
_PAID_EXECUTABLES: dict[str, str] = {
    "claude": "anthropic_cli",
    "claude-code": "anthropic_cli",
    "codex": "openai_cli",
    "agy": "google_agy",
    "antigravity": "google_agy",
}

# Exact vendor commands that inspect the installed CLI/account without asking
# a model to generate anything.  This is deliberately an argv allowlist rather
# than a prefix allowlist: ``claude --version explain this`` and
# ``codex login status --some-new-mode`` have extra semantics we have not
# audited, so they remain paid/refused like every other vendor invocation.
#
# Only direct vendor executables qualify.  Runtime discovery already resolves
# npm shims before spawning them (for example ``...\\codex.cmd`` on Windows),
# and :func:`_basename` normalises those paths.  A shell/process wrapper still
# takes the conservative path below because its quoting and argument boundary
# cannot be proved from this coarse syscall view.
_READ_ONLY_VENDOR_PROBES: dict[str, frozenset[tuple[str, ...]]] = {
    "claude": frozenset({("--version",)}),
    "codex": frozenset({("--version",), ("login", "status")}),
}
# argv[0] basenames that RUN something else; scan their arguments too, because
# `ssh bench agy -p ...` and `cmd /c claude -p ...` spend exactly as much money
# as `claude -p ...` does.
#
# The second row was added 2026-07-29 after MEASURING that each one carried a
# vendor past the guard. ``uv``/``uvx`` are the live ones -- both are installed
# on this machine, so `uv run claude -p ...` was a working bypass. The rest are
# the ordinary process-shepherd verbs an agent reaches for when it wants a
# timeout or a detached child; none of them is exotic, and each is one word away
# from a spend nobody counted. Adding a wrapper cannot over-bill on its own: the
# scan still requires an actual vendor token in the arguments, so
# `timeout 60 git status` is passed through untouched.
_WRAPPERS = frozenset({"ssh", "cmd", "cmd.exe", "sh", "bash", "zsh", "pwsh",
                       "powershell", "npx", "bunx", "env", "wsl", "wsl.exe",
                       "uv", "uvx", "timeout", "nohup", "xargs", "stdbuf",
                       "winpty", "start", "sudo", "doas", "time", "script",
                       "nice", "setsid"})

# Host suffixes that are a paid inference API.
_PAID_API_HOSTS: dict[str, str] = {
    "api.anthropic.com": "anthropic_api",
    "api.openai.com": "openai_api",
    "api.deepseek.com": "deepseek",
    "generativelanguage.googleapis.com": "google_api",
    "openrouter.ai": "openai_api",
}
# Path fragments that mean "this request will generate tokens" (as opposed to
# /api/tags and /api/version, which are free probes and must not be billed).
_INFERENCE_PATHS = ("/v1/chat/completions", "/v1/completions", "/v1/messages",
                    "/v1/responses", "/api/chat", "/api/generate", "/api/embed",
                    "/api/embeddings", ":generatecontent", ":streamgeneratecontent")


def _basename(token: str) -> str:
    # Recognise resolved Windows executables even when classification runs on
    # a non-Windows host (as the Linux CI tests do).  ``os.path.basename`` only
    # treats the current platform's separator as special.
    raw = str(token or "").strip().strip('"').replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1", ".sh"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    return name


def _is_read_only_vendor_probe(executable: str, arguments: list[str]) -> bool:
    """Whether this direct CLI argv is an audited, no-generation probe."""

    allowed = _READ_ONLY_VENDOR_PROBES.get(executable)
    return allowed is not None and tuple(arguments) in allowed


def classify_argv(argv: Any) -> str | None:
    """Vendor id if this argv spends money, else None.

    Conservative in the direction that matters: an unrecognised binary is NOT
    billed (billing `git` would make the guard unusable and it would be turned
    off), but a recognised vendor reached THROUGH a wrapper IS.
    """
    if isinstance(argv, (str, bytes, os.PathLike)):
        tokens = [os.fspath(argv) if isinstance(argv, os.PathLike) else argv]
        if isinstance(tokens[0], bytes):
            tokens[0] = tokens[0].decode("utf-8", "replace")
        # A shell string: split loosely and scan every token.
        tokens = str(tokens[0]).replace('"', " ").split()
        scan_all = True
    else:
        try:
            tokens = [os.fspath(t) if isinstance(t, os.PathLike) else
                      (t.decode("utf-8", "replace") if isinstance(t, bytes) else str(t))
                      for t in argv]
        except TypeError:
            return None
        scan_all = False
    if not tokens:
        return None

    head = _basename(tokens[0])
    if head in _PAID_EXECUTABLES:
        if _is_read_only_vendor_probe(head, tokens[1:]):
            return None
        return _PAID_EXECUTABLES[head]
    if scan_all or head in _WRAPPERS:
        # Split on whitespace as well: `bash -c "agy -p ..."` and
        # `ssh bench 'claude -p'` hand the whole command over as ONE token.
        for tok in tokens[1:]:
            for word in str(tok).replace("'", " ").replace('"', " ").split():
                vendor = _PAID_EXECUTABLES.get(_basename(word))
                if vendor:
                    return vendor
    return None


def classify_url(url: Any) -> tuple[str | None, str | None]:
    """``(vendor, host)`` if this request spends money, else ``(None, host)``.

    Two ways to be billable: a known paid API host, or an INFERENCE endpoint on
    a host that :func:`daedalus.sensitivity.lane_for_host` will not certify as
    this machine. The second is the OLLAMA_HOST case -- same provider name,
    same code path, somebody else's GPU.
    """
    from urllib.parse import urlsplit

    raw = url
    if hasattr(raw, "full_url"):                      # urllib.request.Request
        raw = raw.full_url
    if hasattr(raw, "get_full_url"):
        try:
            raw = raw.get_full_url()
        except Exception:                              # noqa: BLE001
            pass
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    try:
        parts = urlsplit(raw if "//" in raw else f"//{raw}")
        host = (parts.hostname or "").lower()
    except (ValueError, UnicodeError):
        return None, None
    if not host:
        return None, None

    for suffix, vendor in _PAID_API_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return vendor, raw
    path = (parts.path or "").lower() + (parts.query or "").lower()
    if not any(frag in path for frag in _INFERENCE_PATHS):
        return None, raw                               # /api/tags etc: a free probe

    from ...sensitivity import lane_for_host

    if lane_for_host(host) == "trusted":
        return None, raw                               # this machine; no bill
    return "remote_inference", raw


# --------------------------------------------------------------------------
# process-wide interposition -- the chokepoint the architecture lacks
# --------------------------------------------------------------------------

_EXPLICIT = threading.local()


def _enter_explicit() -> None:
    _EXPLICIT.depth = getattr(_EXPLICIT, "depth", 0) + 1


def _exit_explicit(_token: Any = None) -> None:
    _EXPLICIT.depth = max(0, getattr(_EXPLICIT, "depth", 0) - 1)


def _inside_explicit() -> bool:
    return getattr(_EXPLICIT, "depth", 0) > 0


_INSTALLED: dict[str, Any] = {}


def _guarded_spawn(
    original: Callable[..., Any],
    kind: str,
    *,
    argv_classifier: Callable[[Any], str | None] = classify_argv,
    reserve_call: Callable[..., Reservation] = reserve,
) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        argv = kwargs.get("args", args[0] if args else None)
        vendor = None if _inside_explicit() else argv_classifier(argv)
        if vendor is None:
            return original(*args, **kwargs)
        label = f"{kind}: {_render(argv)}"
        res = reserve_call(vendor, label=label)
        # ``subprocess.run`` calls ``subprocess.Popen`` through the MODULE
        # GLOBAL, which this function has also replaced -- without this the same
        # spawn would be reserved twice. Standing the interposer down for the
        # duration of the original call is also what stops it double-charging a
        # site that already reserved explicitly.
        _enter_explicit()
        try:
            return original(*args, **kwargs)
        finally:
            _exit_explicit()
            res.settle()
    wrapper.__wrapped__ = original           # type: ignore[attr-defined]
    wrapper.__daedalus_budget__ = True       # type: ignore[attr-defined]
    return wrapper


def _guarded_popen(
    original: type,
    *,
    argv_classifier: Callable[[Any], str | None] = classify_argv,
    reserve_call: Callable[..., Reservation] = reserve,
) -> type:
    """Guard `subprocess.Popen` AS A CLASS, because things subclass it.

    MEASURED, and it broke the CLI outright. Replacing Popen with a plain
    function made every later `import asyncio` fail:

        File "asyncio/windows_utils.py", line 125, in <module>
            class Popen(subprocess.Popen):
        TypeError: function() argument 'code' must be code, not str

    asyncio derives a class from `subprocess.Popen` at import time, and a
    function cannot be a base class. The guard installs at the CLI entry point,
    so any subcommand that reaches asyncio afterwards -- `daedalus web` does,
    through context_plan -> memory.embeddings -> adapters -> asyncio -- died
    with a traceback instead of doing its job.

    That is the exact failure the wiring commit warned about in the abstract:
    "if a non-vendor spawn were charged or mangled, every git and pytest call
    would break, and the fix somebody reaches for at 3am is to delete the
    guard. Then there is no cap." The test for it only exercised
    `subprocess.run`, so it did not see this.

    A subclass keeps isinstance, subclassing, and every classmethod intact
    while still reserving before the process starts.

    NOT A CLASS, NOT WRAPPED. A test's ``mock.patch("subprocess.Popen")``
    leaves a MagicMock INSTANCE in the slot; subclassing it "works" and then
    ``original.__name__`` raises ``AttributeError: __name__`` out of
    ``install_process_guard`` -- which ``ikarus_os`` reports, correctly, as
    "the spend net could not be installed", refusing every vendor call in the
    test (MEASURED 2026-08-23: 3 red in test_ikarus_stream, 74 such lines in
    the full suite). A mock is not a process spawn; it is returned as found
    and uninstall's identity check then leaves it alone as well.
    """
    if not isinstance(original, type):
        return original

    class GuardedPopen(original):                     # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            argv = kwargs.get("args", args[0] if args else None)
            vendor = None if _inside_explicit() else argv_classifier(argv)
            if vendor is None:
                super().__init__(*args, **kwargs)
                return
            res = reserve_call(
                vendor,
                label=f"subprocess.Popen: {_render(argv)}",
            )
            _enter_explicit()
            try:
                super().__init__(*args, **kwargs)
            finally:
                _exit_explicit()
                res.settle()

    GuardedPopen.__name__ = original.__name__
    GuardedPopen.__qualname__ = original.__qualname__
    GuardedPopen.__wrapped__ = original               # type: ignore[attr-defined]
    GuardedPopen.__daedalus_budget__ = True           # type: ignore[attr-defined]
    return GuardedPopen


def _guarded_urlopen(
    original: Callable[..., Any],
    *,
    url_classifier: Callable[[Any], tuple[str | None, str | None]] = classify_url,
    reserve_call: Callable[..., Reservation] = reserve,
) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        url = kwargs.get("url", args[0] if args else None)
        vendor, shown = (
            (None, None) if _inside_explicit() else url_classifier(url)
        )
        if vendor is None:
            return original(*args, **kwargs)
        res = reserve_call(vendor, label=f"urlopen: {str(shown)[:200]}")
        _enter_explicit()
        try:
            return original(*args, **kwargs)
        finally:
            _exit_explicit()
            res.settle()
    wrapper.__wrapped__ = original           # type: ignore[attr-defined]
    wrapper.__daedalus_budget__ = True       # type: ignore[attr-defined]
    return wrapper


def _render(argv: Any) -> str:
    if isinstance(argv, (str, bytes)):
        return str(argv)[:200]
    try:
        return " ".join(str(t) for t in argv)[:200]
    except TypeError:
        return repr(argv)[:200]


def install_process_guard(
    *,
    argv_classifier: Callable[[Any], str | None] = classify_argv,
    url_classifier: Callable[[Any], tuple[str | None, str | None]] = classify_url,
    reserve_call: Callable[..., Reservation] = reserve,
) -> Callable[[], None]:
    """Put EVERY vendor spawn and inference request in this process behind the
    ceiling, without editing the call sites.

    This exists because the repo has no single chokepoint: paid calls leave from
    ``providers/``, ``council/vendors.py``, ``ikarus_os.py`` and ``runs/``
    independently. It is coarse -- it prices by vendor, not by task -- and it is
    opt-in, so it is a NET, not a substitute for an explicit
    :func:`guard` at a site that knows its own cost. Idempotent; returns the
    uninstaller.
    """
    import subprocess
    import urllib.request

    if _INSTALLED:
        return uninstall_process_guard

    # Each record is (what was there, what we put there). The second half is
    # what makes uninstall safe: it restores ONLY if the attribute still holds
    # our wrapper. Measured 2026-08-23 (full suite, 400 red): a test mocked
    # `subprocess.run`, called into ikarus_os, which installed this guard
    # AROUND THE MOCK; the mock's context exit put the real function back, and
    # the conftest teardown's uninstall then wrote the MOCK back over it --
    # every later process spawn in the interpreter returned `stdout="ok"` with
    # a MagicMock returncode, and the kill switch's cross-process probe
    # refused to arm 119 times for a reason that had nothing to do with it.
    wrapped_run = _guarded_spawn(
        subprocess.run,
        "subprocess.run",
        argv_classifier=argv_classifier,
        reserve_call=reserve_call,
    )
    wrapped_popen = _guarded_popen(
        subprocess.Popen,
        argv_classifier=argv_classifier,
        reserve_call=reserve_call,
    )
    wrapped_urlopen = _guarded_urlopen(
        urllib.request.urlopen,
        url_classifier=url_classifier,
        reserve_call=reserve_call,
    )
    _INSTALLED["subprocess.run"] = (subprocess.run, wrapped_run)
    _INSTALLED["subprocess.Popen"] = (subprocess.Popen, wrapped_popen)
    _INSTALLED["urllib.request.urlopen"] = (urllib.request.urlopen, wrapped_urlopen)
    subprocess.run = wrapped_run                                                 # type: ignore[assignment]
    subprocess.Popen = wrapped_popen                                             # type: ignore[assignment]
    urllib.request.urlopen = wrapped_urlopen                                     # type: ignore[assignment]
    return uninstall_process_guard


def uninstall_process_guard() -> list[str]:
    """Take the net down. Returns the names it did NOT restore.

    An attribute that no longer holds this guard's wrapper was replaced by
    somebody else after we installed (a test's ``mock.patch``, another
    interposer). Writing our remembered original over THEIR value would undo
    a replacement we never made -- or, after their context has already
    restored the real function, would resurrect their fake. So those are left
    exactly as found and reported by name; the record is dropped either way,
    so the guard can be installed again.
    """
    import subprocess
    import urllib.request

    if not _INSTALLED:
        return []
    left: list[str] = []
    original, wrapper = _INSTALLED.pop("subprocess.run")
    if subprocess.run is wrapper:
        subprocess.run = original                                                # type: ignore[assignment]
    else:
        left.append("subprocess.run")
    original, wrapper = _INSTALLED.pop("subprocess.Popen")
    if subprocess.Popen is wrapper:
        subprocess.Popen = original                                              # type: ignore[assignment]
    else:
        left.append("subprocess.Popen")
    original, wrapper = _INSTALLED.pop("urllib.request.urlopen")
    if urllib.request.urlopen is wrapper:
        urllib.request.urlopen = original                                        # type: ignore[assignment]
    else:
        left.append("urllib.request.urlopen")
    _INSTALLED.clear()
    return left


# --------------------------------------------------------------------------
# the coverage register -- what spends, and whether it is guarded YET
# --------------------------------------------------------------------------

# EVERY known billable site in this repo, audited 2026-07-29. ``explicit`` is
# True only when the site itself reserves; the rest are covered ONLY when
# install_process_guard() has run in their process. This list is the honest
# accounting: a hole named in code is a hole someone can close, a hole in a
# report is a hole nobody reads twice. tests/test_budget.py fails if a NEW
# vendor spawn appears in the tree that is not listed here.
BILLABLE_SITES: tuple[dict[str, Any], ...] = (
    {"file": "daedalus/claude_bridge.py", "func": "ask_claude",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    {"file": "daedalus/providers/codex_cli.py", "func": "CodexCLIProvider.run",
     "vendor": "openai_cli", "how": "subprocess.run", "explicit": False},
    # STATICALLY INVISIBLE for the mirror-image reason: the spawn is here but
    # the vendor is not -- the host arrives as ``base_url`` from the caller.
    {"file": "daedalus/providers/_openai_compat.py", "func": "chat_completion",
     "vendor": "deepseek", "how": "urlopen(base_url)",
     "explicit": False, "static_visible": False},
    # STATICALLY INVISIBLE. The argv is built here but SPAWNED in
    # spine/cancel.py::ManagedProcess (subprocess.Popen), so no text scan of
    # this file finds a spawn, and no text scan of cancel.py finds a vendor.
    # Only the runtime interposer sees these -- the argv is concrete by then.
    {"file": "daedalus/council/vendors.py", "func": "_CliAdapter._dispatch",
     "vendor": "anthropic_cli|openai_cli", "how": "run_managed->spine.cancel.Popen",
     "explicit": False, "static_visible": False},
    {"file": "daedalus/council/vendors.py", "func": "AntigravityAdapter._dispatch",
     "vendor": "google_agy", "how": "run_managed->spine.cancel.Popen",
     "explicit": False, "static_visible": False},
    # Also invisible: the request is issued in providers/_ollama_native.py, and
    # whether it costs anything depends on ``self.host`` at runtime.
    {"file": "daedalus/council/vendors.py", "func": "OllamaAdapter._dispatch",
     "vendor": "remote_inference", "how": "_chat->_ollama_native.urlopen",
     "explicit": False, "static_visible": False},
    {"file": "daedalus/orchestration/ikarus_os.py", "func": "_claude",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    {"file": "daedalus/orchestration/ikarus_os.py", "func": "_codex",
     "vendor": "openai_cli", "how": "subprocess.run", "explicit": False},
    {"file": "daedalus/orchestration/ikarus_os.py", "func": "_claude_stream",
     "vendor": "anthropic_cli", "how": "subprocess.Popen", "explicit": False},
    {"file": "runs/council/room.py", "func": "ask_codex",
     "vendor": "openai_cli", "how": "subprocess.run", "explicit": False},
    {"file": "runs/council/room.py", "func": "ask_fable",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    {"file": "runs/council/room.py", "func": "ask_opus",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    {"file": "runs/council/room.py", "func": "ask_agy",
     "vendor": "google_agy", "how": "subprocess.run(ssh)", "explicit": False},
    {"file": "runs/council/room.py", "func": "ask_ollama",
     "vendor": "remote_inference", "how": "urlopen", "explicit": False},
    {"file": "runs/ab/run_arm.py", "func": "call_claude",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    # These two were MISSED by the hand audit and found by the drift detector in
    # tests/test_budget.py the first time it ran. That is the argument for
    # keeping the detector: a hand-maintained list of spend sites rots within a
    # week in a repo where sixteen agents are adding code.
    {"file": "runs/council/summarize.py", "func": "cli_summariser",
     "vendor": "anthropic_cli", "how": "subprocess.run", "explicit": False},
    {"file": "runs/council/summarize.py", "func": "ollama_summariser",
     "vendor": "remote_inference", "how": "urlopen", "explicit": False},
)


__all__ = [
    "BILLABLE_SITES",
    "classify_argv",
    "classify_url",
    "guard",
    "install_process_guard",
    "uninstall_process_guard",
]
