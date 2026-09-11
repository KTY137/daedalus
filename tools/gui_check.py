"""Browser-level acceptance for the Daedalus cockpit.

WHY THIS EXISTS. ``tools/system_check.py`` starts the web server, waits for it
to answer, and kills it. That proves the SERVER runs. It does not prove a human
could operate the product: a server that answers 200 on every route is
indistinguishable, from the outside, from one whose bundle throws on module
evaluation and renders a white screen. This drives the BUILT app in a real
browser against a REAL server and asks the questions a person would.

THE SAME THREE OUTCOMES, AND ONLY ONE IS SUCCESS.

    0   PASS         every spec ran and held
    1   FAIL         a spec ran and did NOT hold
    2   INCOMPLETE   the specs could NOT be run here, so this proves nothing

A MISSING BROWSER IS INCOMPLETE, NEVER PASS. So is a missing ``node``, a
missing ``@playwright/test``, and an ``apps/web/dist`` that was never built --
the last one especially, because the server answers 200 with a placeholder page
in that case and every naive check goes green on it.

WHAT IS STARTED, AND HOW IT DIES. One ``daedalus web`` on a free LOOPBACK port,
killed in a ``finally`` on every path including failure and including
``KeyboardInterrupt``. The non-loopback opt-in environment variables are
scrubbed from the child's environment rather than merely left unset, so an
ambient ``DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS`` cannot turn an acceptance run into
a network service. Server output is captured in a temporary file rather than an
undrained PIPE, so a verbose real-server acceptance run cannot deadlock when an
OS pipe buffer fills.

    python tools/gui_check.py                     # against this checkout
    python tools/gui_check.py --json              # machine-readable receipt
    python tools/gui_check.py --repo-root <dir>   # serve a disposable clone
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from daedalus.atomic import publish_bytes_once

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

PASS, FAIL, INCOMPLETE = "PASS", "FAIL", "INCOMPLETE"
EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE = 0, 1, 2

READINESS_S = 60.0          # the server has this long to answer GET /
BROWSER_PREFLIGHT_TIMEOUT_S = 180.0
SERVER_DRAIN_TIMEOUT_S = 10.0
SERVER_SHUTDOWN_TIMEOUT_S = 20.0
AGGREGATE_TIMEOUT_MARGIN_S = 30.0
SUITE_TIMEOUT_DEFAULT_S = 600   # one playwright invocation, on a quiet box
SUITE_TIMEOUT_ENV = "DAEDALUS_GUI_SUITE_TIMEOUT_S"
ACCEPTANCE_PROJECT_ENV = "DAEDALUS_GUI_PROJECT"
SHELL_SHARDS = 4
NOT_BUILT_MARKER = "Run npm install"


def suite_timeout_s(env: dict[str, str] | None = None) -> float:
    """How long one playwright invocation may take.

    The default is unchanged and this is not a way to make a hanging suite
    pass -- a timeout is still a FAIL. It exists because the budget was sized
    for a machine running only this: [MEASURED 2026-09-03] the shell suite
    took 13.9 minutes on this box while parallel agent sessions held ~87
    python processes, so the harness reported "did not finish within 600s"
    for a suite that is entirely green. A verdict of FAIL that means "the
    machine was busy" is the kind of number this repository refuses to
    report, so the operator can say how slow their box is instead.

    A non-numeric or non-positive value is ignored rather than obeyed: it
    would otherwise be a way to disable the bound by typo.
    """
    raw = (os.environ if env is None else env).get(SUITE_TIMEOUT_ENV, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return float(SUITE_TIMEOUT_DEFAULT_S)
    return value if value > 0 else float(SUITE_TIMEOUT_DEFAULT_S)


def timeout_message(budget: float) -> str:
    """What a timed-out suite says. A verdict nobody can act on costs the
    next person an hour of guessing which of the two causes they have."""
    return (f"the browser suite did not finish within {budget:g}s. If the machine "
            f"is under load rather than the suite being stuck, raise "
            f"{SUITE_TIMEOUT_ENV} and report the value with the verdict.")

# Environment that must never reach the server we start. Not "not set" --
# actively removed, because inheriting one of these from an operator's shell is
# exactly how a loopback tool becomes a LAN service by accident.
SCRUB_ENV = ("DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS", "DAEDALUS_WEB_TOKEN")


class Outcome:
    def __init__(self, outcome: str, detail: str = "", evidence: dict | None = None):
        self.outcome, self.detail, self.evidence = outcome, detail, (evidence or {})

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "detail": self.detail, "evidence": self.evidence}


# --------------------------------------------------------------------------- #
# preflight -- everything that makes this INCOMPLETE rather than FAILED        #
# --------------------------------------------------------------------------- #
def _node() -> str | None:
    return shutil.which("node")


def _playwright_cli(web_root: Path) -> Path | None:
    cli = web_root / "node_modules" / "playwright" / "cli.js"
    return cli if cli.is_file() else None


def _browser_installed(web_root: Path, node: str, cli: Path) -> tuple[bool, str]:
    """Ask Playwright itself where it expects the browser, then look there.

    Parsing ``--dry-run`` rather than guessing a path keeps this correct across
    Playwright's browser-revision bumps: the install location is whatever the
    installed version says it is, not whatever this file remembered.
    """
    try:
        proc = subprocess.run(
            [node, str(cli), "install", "chromium", "--only-shell", "--dry-run"],
            cwd=str(web_root), capture_output=True, encoding="utf-8",
            errors="replace", timeout=BROWSER_PREFLIGHT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not ask playwright where its browser lives: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    # Per BLOCK, not a flat regex over the whole output: ffmpeg and winldd also
    # print "Install location:", and a flat scan would happily accept ffmpeg's
    # directory as proof that a browser is present.
    wanted: list[str] = []
    for block in re.split(r"\n\s*\n", out):
        head = block.strip().splitlines()[0] if block.strip() else ""
        if not re.search(r"chromium|chrome headless shell", head, re.IGNORECASE):
            continue
        loc = re.search(r"Install location:\s*(.+)", block)
        if loc:
            wanted.append(loc.group(1).strip())
    if not wanted:
        return False, f"playwright named no chromium install location: {out[-300:]!r}"
    missing = [w for w in wanted if not Path(w).is_dir()]
    if missing:
        return False, f"browser not downloaded: {missing}"
    return True, wanted[0]


def preflight(web_root: Path) -> tuple[Outcome | None, dict]:
    """``None`` means clear to run. Anything else is INCOMPLETE."""
    info: dict = {"web_root": str(web_root)}

    node = _node()
    if not node:
        return Outcome(INCOMPLETE, "node is not on PATH, so no browser can be driven here",
                       info), info
    info["node"] = node

    cli = _playwright_cli(web_root)
    if cli is None:
        return Outcome(INCOMPLETE,
                       f"@playwright/test is not installed in {web_root}. "
                       f"Install it with:  npm install --prefix {web_root}",
                       info), info
    info["playwright_cli"] = str(cli)

    ok, where = _browser_installed(web_root, node, cli)
    if not ok:
        return Outcome(INCOMPLETE,
                       f"the chromium headless shell is not installed ({where}). "
                       f"Download it with:  npx --prefix {web_root} playwright "
                       f"install chromium --only-shell",
                       info), info
    info["browser"] = where
    return None, info


# --------------------------------------------------------------------------- #
# the server we start, and are responsible for killing                         #
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _acceptance_project_target(repo_root: Path) -> tuple[str, Path]:
    """Reserve this run's identity before publishing any registry row."""
    root = repo_root.resolve()
    if not root.is_dir():
        raise OSError(f"the checkout does not exist or is not a directory: {root}")
    project_dir = root / "projects"
    project_dir.mkdir(exist_ok=True)
    resolved_project_dir = project_dir.resolve()
    try:
        resolved_project_dir.relative_to(root)
    except ValueError as exc:
        raise OSError(
            f"the project registry resolves outside the checkout: {resolved_project_dir}"
        ) from exc

    name = f"000_gui_acceptance_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    return name, resolved_project_dir / f"{name}.json"


def _install_acceptance_project(repo_root: Path, name: str, path: Path) -> None:
    """Atomically register this exact checkout for live browser reads.

    A clean CI checkout has no local project registry, while a developer's
    checkout can contain several machine-local rows. Letting the browser pick
    the first reachable row made the acceptance gate depend on whichever
    unrelated repository happened to sort first. The temporary row is inside
    the specimen so ``--repo-root`` still tests that specimen's code and data.
    """
    root = repo_root.resolve()
    expected = (root / "projects").resolve() / f"{name}.json"
    if path != expected:
        raise OSError("the acceptance-project target does not match this checkout")
    payload = {
        "name": name,
        "repo_root": str(root),
        "center": ["daedalus", "apps/web/src"],
        "ignore": ["@tests", "daedalus/eval/fixtures/"],
    }
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    if not publish_bytes_once(path, encoded):
        raise OSError(f"the acceptance-project row already exists: {path.name}")


def _remove_acceptance_project(path: Path | None, *, retry_s: float = 1.0) -> str:
    """Remove only this run's row; return a diagnostic instead of raising."""
    if path is None:
        return ""
    deadline = time.monotonic() + max(0.0, retry_s)
    while True:
        try:
            path.unlink(missing_ok=True)
            return ""
        except FileNotFoundError:
            return ""
        except OSError as exc:
            if time.monotonic() >= deadline:
                return f"could not remove acceptance-project row '{path}': {exc}"
            time.sleep(0.02)


def _suite_plan() -> list[tuple[str, list[str]]]:
    """Bound each serial invocation without introducing concurrent browsers."""
    shell = [
        (
            f"shell-{current}/{SHELL_SHARDS}",
            ["--grep-invert", "@loopui", "--shard", f"{current}/{SHELL_SHARDS}"],
        )
        for current in range(1, SHELL_SHARDS + 1)
    ]
    return [*shell, ("loop-ui", ["--grep", "@loopui"])]


def _child_env(repo_root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in SCRUB_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo_root), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    return env


def _wait_ready(port: int, proc: subprocess.Popen) -> tuple[bool, str, str]:
    """(ready, body_of_GET_/, why_not)."""
    deadline, last = time.time() + READINESS_S, "no attempt completed"
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, "", f"the server exited with {proc.returncode} before answering"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                return True, r.read(4096).decode("utf-8", "replace"), ""
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
            time.sleep(0.4)
    return False, "", f"no answer within {READINESS_S:.0f}s: {last}"


def _drain(proc: subprocess.Popen, output_file) -> str:
    """Whatever the dead server said. The traceback is the whole diagnosis."""
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=SERVER_DRAIN_TIMEOUT_S)
        except Exception:
            pass
    try:
        output_file.flush()
        output_file.seek(0)
        return output_file.read().decode("utf-8", "replace")
    except Exception:
        return ""


# The DOCUMENTED entry point first -- that is the command a human types and the
# only one whose health is a product claim. The module path is a DIAGNOSTIC
# fallback, never a way to turn a red run green: when the documented path fails,
# `gui_run` reports FAIL no matter how the specs then do. What the fallback buys
# is the sentence that actually helps -- "the CLI wrapper is broken, the server
# is fine" versus "something about the web did not work".
SERVER_ENTRIES = (
    ("daedalus web (the documented entry point)", ["-m", "daedalus.interfaces.cli.entry", "web"]),
    ("python -m daedalus.interfaces.http.web_api (diagnostic fallback)", ["-m", "daedalus.interfaces.http.web_api"]),
)


def aggregate_timeout_s(env: dict[str, str] | None = None) -> int:
    """Outer bound for preflight, both server attempts, suites and cleanup."""
    startup = len(SERVER_ENTRIES) * (READINESS_S + SERVER_DRAIN_TIMEOUT_S)
    suites = len(_suite_plan()) * suite_timeout_s(env)
    return math.ceil(
        BROWSER_PREFLIGHT_TIMEOUT_S
        + startup
        + suites
        + SERVER_SHUTDOWN_TIMEOUT_S
        + AGGREGATE_TIMEOUT_MARGIN_S
    )


def _start_server(repo_root: Path, port: int, verbose: bool):
    """(proc, body, entry_label, documented_entry_error, output_file).

    ``documented_entry_error`` is non-empty when ``daedalus web`` itself could
    not start; the caller must FAIL on it. Output is file-backed rather than a
    PIPE: nobody needs to drain it while the browser suite is running, and a
    chatty server therefore cannot stop serving because a pipe buffer filled.
    """
    documented_error = ""
    for label, argv in SERVER_ENTRIES:
        output_file = tempfile.TemporaryFile(mode="w+b")
        try:
            proc = subprocess.Popen(
                [PY, *argv, "--port", str(port)], cwd=str(repo_root),
                stdout=output_file, stderr=subprocess.STDOUT,
                env=_child_env(repo_root))
        except OSError as exc:
            output_file.close()
            documented_error = documented_error or f"{label} could not be spawned: {exc}"
            continue
        try:
            ready, body, why = _wait_ready(port, proc)
        except BaseException:
            _drain(proc, output_file)
            output_file.close()
            raise
        if ready:
            return proc, body, label, documented_error, output_file
        tail = _drain(proc, output_file).strip().replace("\n", " | ")[-700:]
        output_file.close()
        if not documented_error:
            documented_error = f"{label} did not come up: {why}. Server said: {tail}"
        if verbose:
            print(f"  [!!] {label} did not come up -- {why}")
    return None, "", "", documented_error or "no server entry point came up", None


# --------------------------------------------------------------------------- #
# the specs                                                                    #
# --------------------------------------------------------------------------- #
def _read_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _specs(report: dict) -> list[dict]:
    """Flatten Playwright's nested JSON report into one row per test."""
    rows: list[dict] = []

    def walk(suite: dict, trail: list[str]) -> None:
        here = trail + [suite.get("title") or ""]
        for spec in suite.get("specs") or ():
            title = spec.get("title") or ""
            results = [r for t in spec.get("tests") or () for r in t.get("results") or ()]
            status = "unknown"
            if results:
                status = results[-1].get("status") or "unknown"
            errs = [e.get("message") or "" for r in results for e in r.get("errors") or ()]
            rows.append({
                "title": title,
                "file": (here[0] if here else "").strip(),
                "ok": bool(spec.get("ok")),
                "status": status,
                "error": _first_line(errs[0]) if errs else "",
            })
        for child in suite.get("suites") or ():
            walk(child, here)

    for suite in report.get("suites") or ():
        walk(suite, [])
    return rows


def _first_line(msg: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", msg or "")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Playwright leads with "Error: <our message>"; the message is the point.
    body = " ".join(lines[:6])
    return body[:600]


def _run_suite(node: str, cli: Path, web_root: Path, grep: list[str],
               env: dict, report_path: Path) -> tuple[int, str, dict]:
    if report_path.exists():
        report_path.unlink()
    # NO --reporter here on purpose: passing it on the command line REPLACES the
    # config's reporters, and the json reporter would then take its output path
    # from PLAYWRIGHT_JSON_OUTPUT_NAME instead of the one this process chose.
    # playwright.config.ts already wires the json reporter to DAEDALUS_GUI_REPORT.
    cmd = [node, str(cli), "test", *grep]
    budget = suite_timeout_s()
    try:
        proc = subprocess.run(cmd, cwd=str(web_root), capture_output=True,
                              encoding="utf-8", errors="replace",
                              timeout=budget, env=env)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        def decoded(value: str | bytes | None) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return value or ""

        partial = decoded(exc.stdout) + decoded(exc.stderr)
        detail = timeout_message(budget)
        if partial.strip():
            detail += f"\nLast Playwright output before timeout:\n{partial[-1800:]}"
        return 124, detail, {}
    except OSError as exc:
        return 127, f"could not execute playwright: {exc}", {}
    return rc, out, _read_report(report_path)


# Playwright's own words for "the browser binary is not here". Classified as
# INCOMPLETE, never FAIL -- and never, ever as PASS.
_MISSING_BROWSER = re.compile(
    r"Executable doesn't exist|please run the following command to download|"
    r"browserType\.launch:.*ENOENT|Chromium distribution .* is not found",
    re.IGNORECASE)


def gui_run(repo_root: Path, web_root: Path, *, verbose: bool = True) -> Outcome:
    pre, info = preflight(web_root)
    if pre is not None:
        return pre

    node, cli = info["node"], Path(info["playwright_cli"])
    port = _free_port()
    # A port allocated and immediately released: the specs navigate to it to
    # prove they would notice a dead server rather than passing from cache.
    dead_port = _free_port()

    work = Path(tempfile.mkdtemp(prefix="daedalus-gui-"))
    report_path = work / "report.json"
    proc = None
    server_output = None
    acceptance_project_path: Path | None = None
    outcome: Outcome | None = None
    try:
        try:
            acceptance_project, acceptance_project_path = _acceptance_project_target(
                repo_root
            )
            _install_acceptance_project(
                repo_root, acceptance_project, acceptance_project_path
            )
        except OSError as exc:
            outcome = Outcome(
                FAIL,
                f"could not establish the checkout-local browser fixture: {exc}",
                info,
            )
            return outcome
        info["acceptance_project"] = acceptance_project
        if verbose:
            print(f"  serving {repo_root} on http://127.0.0.1:{port} (loopback only)")
        proc, body, entry, documented_error, server_output = _start_server(
            repo_root, port, verbose
        )
        info["server_entry"] = entry or "(none started)"
        if documented_error:
            info["documented_entry_error"] = documented_error
        if proc is None:
            outcome = Outcome(
                FAIL,
                f"no cockpit server could be started, so the GUI could "
                f"not be exercised at all: {documented_error}",
                info,
            )
            return outcome
        if verbose and documented_error:
            print(f"  [!!] running the specs against the fallback entry point; "
                  f"this run CANNOT pass")

        # THE PLACEHOLDER TRAP. When apps/web/dist is missing the server answers
        # 200 with "Run npm install && npm run build in apps/web." Every
        # readiness probe ever written goes green on that. There is no app to
        # accept here, so this is INCOMPLETE -- not a pass, and not a failure of
        # the product either.
        if NOT_BUILT_MARKER in body:
            unbuilt = (f"{repo_root / 'apps' / 'web' / 'dist'} is not built: the server "
                       f"served its placeholder page instead of the app. "
                       f"Build it with:  npm --prefix apps/web run build")
            # An ESTABLISHED failure outranks an unrunnable check, matching
            # system_check's own verdict() precedence -- otherwise a broken
            # entry point could hide behind a missing build.
            if documented_error:
                outcome = Outcome(
                    FAIL,
                    f"{documented_error} -- and additionally, {unbuilt}",
                    {**info, "served": body[:200]},
                )
                return outcome
            outcome = Outcome(
                INCOMPLETE, unbuilt, {**info, "served": body[:200]}
            )
            return outcome

        env = {
            **{k: v for k, v in os.environ.items() if k not in SCRUB_ENV},
            "DAEDALUS_GUI_BASE_URL": f"http://127.0.0.1:{port}",
            "DAEDALUS_GUI_DEAD_URL": f"http://127.0.0.1:{dead_port}/",
            "DAEDALUS_GUI_REPORT": str(report_path),
            ACCEPTANCE_PROJECT_ENV: acceptance_project,
            "PLAYWRIGHT_JSON_OUTPUT_NAME": str(report_path),  # belt and braces
            "DAEDALUS_GUI_OUTDIR": str(work / "artifacts"),
            "PLAYWRIGHT_HTML_OPEN": "never",
            "CI": "1",  # never open a browser report window at the end
        }

        rows: list[dict] = []
        raw_tail = ""
        nonzero_rc = 0
        # Shell shards remain strictly serial. They bound one runner process
        # after the suite grew beyond a single timeout budget without bringing
        # back interleaved route interception. Loop CONTRACT and SURFACE still
        # report separately: missing loop UI and wrong loop UI have different
        # owners.
        for label, grep in _suite_plan():
            rc, out, report = _run_suite(node, cli, web_root, grep, env, report_path)
            raw_tail = out[-1500:]
            if _MISSING_BROWSER.search(out):
                outcome = Outcome(
                    INCOMPLETE,
                    "playwright could not launch a browser (binary missing). "
                    "Download it with:  npx --prefix apps/web playwright "
                    "install chromium --only-shell",
                    {**info, "output_tail": raw_tail},
                )
                return outcome
            if rc in (124, 127):
                outcome = Outcome(
                    FAIL, f"{label}: {out}", {**info, "suite": label}
                )
                return outcome
            got = _specs(report)
            if not got and rc != 0:
                outcome = Outcome(
                    FAIL,
                    f"the {label} suite failed before running any spec "
                    f"(rc={rc}): {out[-500:]!r}",
                    info,
                )
                return outcome
            for row in got:
                row["suite"] = label
            rows.extend(got)
            nonzero_rc = nonzero_rc or rc

        failed = [r for r in rows if not r["ok"]]
        skipped = [r for r in rows if r["status"] == "skipped"]
        # A test that NEVER RAN is not a passing test. `maxFailures` stops the
        # invocation, and Playwright marks everything after the stop
        # `ok: true, status: "unknown"` -- so the `ok` flag alone counted it as
        # a pass, and the skip guard below never fired because the status is
        # `unknown` rather than `skipped`. Measured 2026-09-11: one real
        # failure in this file reported as `271 specs, 270 passed`, with two
        # tests that had not executed among the 270. This tool exists to refuse
        # exactly that shape of green.
        # `== "unknown"` is the PROPERTY -- `_specs` sets that status if and
        # only if the spec has no results, which is exactly "never executed".
        # `not in ("passed", "skipped")` was a guess at the complement, and it
        # was wider than the thing it names: an expected failure (`test.fail()`)
        # ran exactly as designed and would have been reported INCOMPLETE, and
        # an `interrupted` result carries results and `ok: false`, so it belongs
        # in `failed` rather than here.
        unrun = [r for r in rows if r["ok"] and r["status"] == "unknown"]
        evidence = {
            **info,
            "port": port,
            "specs": len(rows),
            "passed": sum(1 for r in rows if r["ok"] and r["status"] == "passed"),
            "not_run": [{"suite": r["suite"], "title": r["title"], "status": r["status"]}
                        for r in unrun],
            "failed": [{"suite": r["suite"], "title": r["title"], "why": r["error"]}
                       for r in failed],
            "skipped": [r["title"] for r in skipped],
        }
        if not rows:
            outcome = Outcome(INCOMPLETE, "no browser spec ran at all", evidence)
            return outcome
        # THE DOCUMENTED ENTRY POINT IS PART OF THE PRODUCT. If `daedalus web`
        # cannot start, this run is FAILED however well the specs then did
        # against the fallback -- otherwise the fallback would be a way to
        # report a broken command as a working one.
        if documented_error:
            outcome = Outcome(
                FAIL,
                f"the documented entry point is broken: {documented_error}",
                evidence,
            )
            return outcome
        # A skip is not a pass. If a spec declined to run, this run does not
        # prove what that spec was for.
        if skipped:
            outcome = Outcome(
                INCOMPLETE,
                f"spec(s) did not run: {[r['title'] for r in skipped]}",
                evidence,
            )
            return outcome
        if failed:
            summary = "; ".join(f"{r['title']} -- {r['error']}" for r in failed[:4])
            outcome = Outcome(FAIL, summary, evidence)
            return outcome
        # A test that never ran is not a pass either, and this sits AFTER the
        # failure check on purpose: an abort happens BECAUSE something failed,
        # and FAIL names the cause while INCOMPLETE would hide it. What this
        # catches is the case with no failure to point at -- `maxFailures`
        # reached in another shard, a crashed worker, a runner that stopped for
        # its own reasons. Today those also carry a non-zero exit code, so the
        # guard below would catch them; this makes the rule the code's own
        # rather than a side effect of the runner's exit status.
        if unrun:
            outcome = Outcome(
                INCOMPLETE,
                f"spec(s) never executed: {[r['title'] for r in unrun]}",
                evidence,
            )
            return outcome
        if nonzero_rc:
            # Every spec is green and the runner still exited non-zero: that is
            # the runner telling us something the report does not carry, and
            # trusting the report over it is how a green lie gets told.
            outcome = Outcome(
                FAIL,
                f"every spec passed but playwright exited {nonzero_rc}: "
                f"{raw_tail[-400:]!r}",
                evidence,
            )
            return outcome
        outcome = Outcome(PASS, "", evidence)
        return outcome
    finally:
        # EVERY PATH. This repo has orphaned servers before.
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=SERVER_SHUTDOWN_TIMEOUT_S)
            except Exception:
                pass
        if server_output is not None:
            try:
                server_output.close()
            except Exception:
                pass
        cleanup_error = _remove_acceptance_project(acceptance_project_path)
        if cleanup_error:
            if outcome is not None:
                outcome.outcome = FAIL
                outcome.detail = (
                    f"{outcome.detail} -- {cleanup_error}"
                    if outcome.detail
                    else cleanup_error
                )
                outcome.evidence["cleanup_error"] = cleanup_error
            else:
                print(cleanup_error, file=sys.stderr)
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="the checkout to SERVE (a disposable clone, normally)")
    ap.add_argument("--web-root", default=str(ROOT / "apps" / "web"),
                    help="where the specs and node_modules live -- the HARNESS, "
                         "which is deliberately allowed to differ from the "
                         "checkout under test")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    web_root = Path(args.web_root).resolve()

    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.gui_check",
        REGISTRY_BY_ID["tools.gui_check"].effects,
        (process_guard_boundary_decision(),),
    )
    if not args.json:
        print(f"daedalus GUI acceptance -- a real browser against a real server")
        print(f"  serving : {repo_root}")
        print(f"  harness : {web_root}\n")

    try:
        res = gui_run(repo_root, web_root, verbose=not args.json)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INCOMPLETE

    if args.json:
        print(json.dumps(res.to_dict(), indent=2, default=str))
    else:
        print(f"\n{'=' * 70}")
        ev = res.evidence
        if ev.get("specs"):
            print(f"{ev.get('passed', 0)} pass / {len(ev.get('failed') or [])} FAIL "
                  f"of {ev['specs']} browser specs")
        for row in ev.get("failed") or ():
            print(f"  * [{row['suite']}] {row['title']}\n      {row['why']}")
        print(f"\nVERDICT: " + {
            PASS: "PASS -- a human could operate this cockpit",
            FAIL: "FAIL -- the cockpit does not do what it says",
            INCOMPLETE: "INCOMPLETE -- the browser specs could not be run, so "
                        "this proves nothing",
        }[res.outcome])
        if res.detail:
            print(f"  {res.detail}")
        print("=" * 70)

    return {PASS: EXIT_OK, FAIL: EXIT_FAILED, INCOMPLETE: EXIT_INCOMPLETE}[res.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
