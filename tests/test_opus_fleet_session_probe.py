from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from experiments.opus_fleet_watchdog import session_probe as probe
from experiments.opus_fleet_watchdog.core import SessionProbeResult


NOW = 2_000_000_000.0


def _completed(payload: object, *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(["powershell.exe"], returncode, stdout=stdout, stderr="")


def _process_runner(rows: list[dict[str, Any]] | None = None, captured: dict | None = None):
    payload = {"ok": True, "rows": [] if rows is None else rows}

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if captured is not None:
            captured["argv"] = argv
            captured.update(kwargs)
        return _completed(payload)

    return run


def _registry(roots: dict[str, Path]):
    def list_registered() -> list[str]:
        return list(roots)

    def load_registered(name: str) -> dict[str, str]:
        return {"name": name, "repo_root": str(roots[name])}

    return list_registered, load_registered


def _call(
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
    process_runner=None,
    roots: dict[str, Path] | None = None,
    now: float = NOW,
    codex_home: Path | None = None,
) -> SessionProbeResult:
    if roots is None:
        root = tmp_path / "project"
        root.mkdir(exist_ok=True)
        roots = {"project": root}
    lister, loader = _registry(roots)
    return probe.fleet_session_probe(
        now=now,
        platform_name="nt",
        process_runner=process_runner or _process_runner(rows),
        project_lister=lister,
        project_loader=loader,
        codex_home=codex_home or (tmp_path / "isolated-codex-home"),
    )


def _touch_at(path: Path, timestamp: float, text: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (timestamp, timestamp))


def _rollout_path(codex_home: Path, now: float, *, yesterday: bool = False) -> Path:
    day = datetime.fromtimestamp(now).date()
    if yesterday:
        day -= timedelta(days=1)
    return (
        codex_home
        / "sessions"
        / f"{day.year:04d}"
        / f"{day.month:02d}"
        / f"{day.day:02d}"
        / "rollout-fixture.jsonl"
    )


def test_cim_invocation_is_static_bounded_and_does_not_request_pids(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    result = _call(tmp_path, process_runner=_process_runner(captured=captured))

    assert result == SessionProbeResult(True, 0, (), "")
    assert captured["argv"] == [
        *probe.POWERSHELL_ARGV_PREFIX,
        probe.PROCESS_CENSUS_SCRIPT,
    ]
    assert captured["timeout"] == probe.PROCESS_TIMEOUT_S
    assert captured["check"] is False
    assert "shell" not in captured
    assert "Get-CimInstance -ClassName Win32_Process" in probe.PROCESS_CENSUS_SCRIPT
    assert "ProcessId" not in probe.PROCESS_CENSUS_SCRIPT
    assert "ParentProcessId" not in probe.PROCESS_CENSUS_SCRIPT


@pytest.mark.parametrize(
    ("row", "source"),
    [
        (
            {
                "name": "claude.exe",
                "executable_path": r"C:\Users\dev\.local\bin\claude.exe",
                "command_line": "claude.exe -p task --permission-mode auto",
            },
            "windows:claude-cli",
        ),
        (
            {
                "name": "codex.exe",
                "executable_path": r"C:\Users\dev\AppData\Roaming\npm\codex.exe",
                "command_line": "codex.exe exec --full-auto task",
            },
            "windows:codex-cli",
        ),
    ],
)
def test_native_cli_processes_block(
    row: dict[str, Any], source: str, tmp_path: Path
) -> None:
    result = _call(tmp_path, rows=[row])

    assert result.ok is True
    assert result.active_sessions == 1
    assert result.sources == (source,)
    assert result.reason == "active_evidence"


def test_known_claude_and_codex_electron_desktops_are_not_cli_sessions(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "name": "claude.exe",
            "executable_path": (
                r"C:\Program Files\WindowsApps\Claude_1.37937.0.0_x64__vendor"
                r"\app\claude.exe"
            ),
            "command_line": r'"C:\Program Files\WindowsApps\Claude_1\app\claude.exe"',
        },
        {
            "name": "claude.exe",
            "executable_path": (
                r"C:\Program Files\WindowsApps\Claude_1.37937.0.0_x64__vendor"
                r"\app\claude.exe"
            ),
            "command_line": "claude.exe --type=renderer --app-path=C:\\app\\resources\\app.asar",
        },
        {
            "name": "codex.exe",
            "executable_path": (
                r"C:\Program Files\WindowsApps\Codex_1.2.3.0_x64__vendor"
                r"\app\codex.exe"
            ),
            "command_line": "codex.exe --type=renderer",
        },
    ]

    result = _call(tmp_path, rows=rows)

    assert result == SessionProbeResult(True, 0, (), "")


def test_stale_codex_app_server_alone_is_not_activity(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    _touch_at(_rollout_path(codex_home, NOW), NOW - 1801, "stale\n")
    result = _call(
        tmp_path,
        codex_home=codex_home,
        rows=[
            {
                "name": "codex.exe",
                "executable_path": r"C:\Users\dev\.vscode\extensions\openai.chatgpt\bin\codex.exe",
                "command_line": "codex.exe -c features.code_mode_host=true app-server",
            }
        ],
    )

    assert result == SessionProbeResult(True, 0, (), "")


@pytest.mark.parametrize("yesterday", [False, True])
def test_fresh_codex_rollout_mtime_blocks_with_only_a_coarse_source(
    yesterday: bool, tmp_path: Path
) -> None:
    codex_home = tmp_path / "private-codex-home"
    rollout = _rollout_path(codex_home, NOW, yesterday=yesterday)
    _touch_at(rollout, NOW - 20, "RAW SECRET CONTENT MUST NEVER BE READ\n")
    result = _call(
        tmp_path,
        codex_home=codex_home,
        rows=[
            {
                "name": "codex.exe",
                "executable_path": r"C:\private\codex.exe",
                "command_line": "codex.exe app-server",
            }
        ],
    )

    assert result == SessionProbeResult(
        True, 1, ("codex:recent-activity",), "active_evidence"
    )
    assert str(codex_home) not in repr(result)
    assert "SECRET" not in repr(result)


def test_fresh_codex_activity_grace_survives_app_server_exit(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    _touch_at(_rollout_path(codex_home, NOW), NOW - 30, "finished turn\n")

    result = _call(tmp_path, codex_home=codex_home, rows=[])

    assert result == SessionProbeResult(
        True, 1, ("codex:recent-activity",), "active_evidence"
    )


def test_codex_rollout_content_is_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex-home"
    rollout = _rollout_path(codex_home, NOW)
    _touch_at(rollout, NOW - 1, "not-json and deliberately unreadable as data\n")

    def forbidden_read(*args, **kwargs):
        raise AssertionError("rollout content must never be read")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    result = _call(tmp_path, codex_home=codex_home)

    assert result.sources == ("codex:recent-activity",)


def test_vscode_claude_stream_service_needs_recent_hook_activity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    service = {
        "name": "claude.exe",
        "executable_path": (
            r"C:\Users\dev\.vscode\extensions\anthropic.claude-code-2.1.241"
            r"\resources\native-binary\claude.exe"
        ),
        "command_line": "claude.exe --input-format stream-json --permission-mode auto",
    }

    idle = _call(tmp_path, roots={"project": root}, rows=[service])
    _touch_at(root / "runs" / "hooks" / "state-live.json", NOW - 2)
    active = _call(tmp_path, roots={"project": root}, rows=[service])

    assert idle == SessionProbeResult(True, 0, (), "")
    assert active == SessionProbeResult(
        True, 1, ("hooks:project",), "active_evidence"
    )


def test_vscode_claude_batch_flag_is_direct_activity(tmp_path: Path) -> None:
    result = _call(
        tmp_path,
        rows=[
            {
                "name": "claude.exe",
                "executable_path": (
                    r"C:\Users\dev\.vscode\extensions\anthropic.claude-code-2.1.241"
                    r"\resources\native-binary\claude.exe"
                ),
                "command_line": "claude.exe --input-format stream-json --print task",
            }
        ],
    )

    assert result == SessionProbeResult(
        True, 1, ("windows:claude-cli",), "active_evidence"
    )


def test_node_package_launchers_block_but_arbitrary_prose_does_not(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "name": "node.exe",
            "executable_path": r"C:\Program Files\nodejs\node.exe",
            "command_line": (
                r'"C:\Program Files\nodejs\node.exe" '
                r'"C:\npm\node_modules\@anthropic-ai\claude-code\cli.js" -p x'
            ),
        },
        {
            "name": "node.exe",
            "executable_path": r"C:\Program Files\nodejs\node.exe",
            "command_line": "node.exe npx-cli.js @openai/codex exec x",
        },
        {
            "name": "node.exe",
            "executable_path": r"C:\Program Files\nodejs\node.exe",
            "command_line": 'node.exe script.js --prompt "please inspect @openai/codex docs"',
        },
        {
            "name": "powershell.exe",
            "executable_path": r"C:\Windows\System32\WindowsPowerShell\powershell.exe",
            "command_line": "powershell.exe -Command echo claude codex",
        },
    ]

    result = _call(tmp_path, rows=rows)

    assert result.ok is True
    assert result.active_sessions == 2
    assert result.sources == ("windows:claude-cli", "windows:codex-cli")


@pytest.mark.parametrize(
    ("runner", "reason"),
    [
        (
            lambda *a, **k: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("powershell", probe.PROCESS_TIMEOUT_S)
            ),
            "process_census_timeout",
        ),
        (lambda *a, **k: _completed("", returncode=1), "process_census_failed"),
        (lambda *a, **k: _completed(""), "process_census_invalid"),
        (lambda *a, **k: _completed("not-json"), "process_census_invalid"),
        (
            lambda *a, **k: _completed({"ok": True, "rows": {"name": "codex.exe"}}),
            "process_census_invalid",
        ),
        (
            lambda *a, **k: _completed(
                {
                    "ok": True,
                    "rows": [
                        {
                            "name": "codex.exe",
                            "executable_path": None,
                            "command_line": 7,
                        }
                    ],
                }
            ),
            "process_census_invalid",
        ),
    ],
)
def test_incomplete_process_census_fails_closed(
    runner, reason: str, tmp_path: Path
) -> None:
    result = _call(tmp_path, process_runner=runner)

    assert result.ok is False
    assert result.active_sessions == 0
    assert result.sources == ()
    assert result.reason == f"probe_incomplete:{reason}"


@pytest.mark.parametrize(
    ("age", "active"),
    [(1799.0, True), (1800.0, True), (1801.0, False)],
)
def test_hook_state_activity_has_an_exact_30_minute_grace(
    age: float, active: bool, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _touch_at(root / "runs" / "hooks" / "state-session_1.json", NOW - age)

    result = _call(tmp_path, roots={"project": root})

    assert result.ok is True
    assert (result.active_sessions > 0) is active
    assert result.sources == (("hooks:project",) if active else ())


def test_future_hook_mtime_blocks_and_reports_clock_skew(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _touch_at(root / "runs" / "hooks" / "state-future.json", NOW + 60)

    result = _call(tmp_path, roots={"project": root})

    assert result == SessionProbeResult(
        True, 1, ("hooks:project",), "active_evidence:clock_skew"
    )


def test_fresh_hook_ledger_without_state_is_a_blocker(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _touch_at(
        root / "runs" / "hooks" / "ledger.jsonl",
        NOW - 10,
        '{"event":"pre_tool","session":"s"}\n',
    )

    result = _call(tmp_path, roots={"project": root})

    assert result == SessionProbeResult(
        True, 1, ("hooks:project",), "active_evidence"
    )


def test_missing_hook_directory_and_stale_artifacts_are_clear(tmp_path: Path) -> None:
    no_hooks = tmp_path / "no-hooks"
    stale = tmp_path / "stale"
    no_hooks.mkdir()
    stale.mkdir()
    _touch_at(stale / "runs" / "hooks" / "state-old.json", NOW - 1801)
    _touch_at(stale / "runs" / "hooks" / "ledger.jsonl", NOW - 1801, "{}\n")

    result = _call(tmp_path, roots={"no_hooks": no_hooks, "stale": stale})

    assert result == SessionProbeResult(True, 0, (), "")


def test_unreadable_present_hook_directory_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    hooks = root / "runs" / "hooks"
    hooks.mkdir(parents=True)
    real_iterdir = Path.iterdir

    def fail_for_hooks(path: Path):
        if path == hooks:
            raise PermissionError("private absolute path must not escape")
        return real_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_for_hooks)
    result = _call(tmp_path, roots={"project": root})

    assert result.ok is False
    assert result.reason == "probe_incomplete:hook_scan_failed"
    assert str(root) not in repr(result)


def test_every_registered_project_is_scanned_and_duplicate_roots_are_deduped(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    unregistered = tmp_path / "unregistered"
    for root in (first, second, unregistered):
        root.mkdir()
        _touch_at(root / "runs" / "hooks" / "state-live.json", NOW - 1)

    result = _call(
        tmp_path,
        roots={"alpha": first, "alpha_duplicate": first, "beta": second},
    )

    assert result.ok is True
    assert result.active_sessions == 2
    assert result.sources == ("hooks:alpha", "hooks:beta")
    assert "unregistered" not in repr(result)


def test_result_redacts_paths_command_lines_and_pids_and_probe_writes_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "secret-project-path"
    root.mkdir()
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    secret = "TOP-SECRET-PROMPT"
    result = _call(
        tmp_path,
        roots={"project": root},
        rows=[
            {
                "name": "codex.exe",
                "executable_path": str(tmp_path / "private" / "codex.exe"),
                "command_line": f"codex.exe exec {secret}",
                "process_id": 424242,
            }
        ],
    )
    after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}

    rendered = repr(result)
    assert rendered == repr(
        SessionProbeResult(True, 1, ("windows:codex-cli",), "active_evidence")
    )
    assert secret not in rendered
    assert str(tmp_path) not in rendered
    assert "424242" not in rendered
    assert before == after


def test_process_and_hook_evidence_both_block_without_claiming_uniqueness(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _touch_at(root / "runs" / "hooks" / "state-same-session.json", NOW - 1)

    result = _call(
        tmp_path,
        roots={"project": root},
        rows=[
            {
                "name": "claude.exe",
                "executable_path": r"C:\Users\dev\.local\bin\claude.exe",
                "command_line": "claude.exe --resume same-session",
            }
        ],
    )

    assert result.active_sessions == 2
    assert result.sources == ("hooks:project", "windows:claude-cli")
    assert result.reason == "active_evidence"


def test_non_windows_host_fails_closed_without_running_powershell(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    called = False

    def forbidden_runner(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("PowerShell must not run")

    lister, loader = _registry({"project": root})
    result = probe.fleet_session_probe(
        now=NOW,
        platform_name="posix",
        process_runner=forbidden_runner,
        project_lister=lister,
        project_loader=loader,
        codex_home=tmp_path / "isolated-codex-home",
    )

    assert called is False
    assert result == SessionProbeResult(
        False, 0, (), "probe_incomplete:unsupported_host"
    )


@pytest.mark.parametrize("failure", ["raise", "empty", "bad-name", "missing-root"])
def test_project_registry_failures_are_fail_closed(
    failure: str, tmp_path: Path
) -> None:
    valid_root = tmp_path / "valid"
    valid_root.mkdir()

    if failure == "raise":
        def lister():
            raise OSError("private path")

        loader = lambda name: {"repo_root": str(valid_root)}
        expected = "project_registry_failed"
    elif failure == "empty":
        lister = lambda: []
        loader = lambda name: {"repo_root": str(valid_root)}
        expected = "project_registry_empty"
    elif failure == "bad-name":
        lister = lambda: ["../private"]
        loader = lambda name: {"repo_root": str(valid_root)}
        expected = "project_registry_invalid"
    else:
        lister = lambda: ["missing"]
        loader = lambda name: {"repo_root": str(tmp_path / "does-not-exist")}
        expected = "project_root_missing"

    result = probe.fleet_session_probe(
        now=NOW,
        platform_name="nt",
        process_runner=_process_runner(),
        project_lister=lister,
        project_loader=loader,
        codex_home=tmp_path / "isolated-codex-home",
    )

    assert result.ok is False
    assert result.active_sessions == 0
    assert result.reason == f"probe_incomplete:{expected}"
    assert str(tmp_path) not in repr(result)


def test_recent_unknown_state_is_an_anonymous_blocker(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _touch_at(root / "runs" / "hooks" / "state-unknown.json", NOW - 2)

    result = _call(tmp_path, roots={"project": root})

    assert result.active_sessions == 1
    assert result.sources == ("hooks:project",)


@pytest.mark.parametrize(("now", "window"), [(-1, 1800), (NOW, 0), (NOW, float("nan"))])
def test_invalid_time_inputs_are_refused_before_observation(
    now: float, window: float, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    lister, loader = _registry({"project": root})

    with pytest.raises(ValueError):
        probe.fleet_session_probe(
            now=now,
            recent_s=window,
            platform_name="nt",
            process_runner=lambda *a, **k: pytest.fail("must not observe host"),
            project_lister=lister,
            project_loader=loader,
            codex_home=tmp_path / "isolated-codex-home",
        )
