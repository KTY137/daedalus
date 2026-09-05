"""G1-IKARUS-30 step 2: live desktop + vision measurement through ComputerService.

No LLM planner. Every step is a direct ``ComputerService.execute`` call with a
fresh attempt id. The harness never writes an image: it records only digests,
OCR word lists, coordinate provenance and the adapter's JSON results, with
``%USERPROFILE%`` replaced by ``<USERPROFILE>``.

Run with the worktree venv and the scratch DAEDALUS_KILLSWITCH exported.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

SCRATCH = Path(r"C:\Users\nukei\AppData\Local\Temp\daedalus-lane10")
AUTHORITY = SCRATCH / "authority"
# The effect-lease identity is canonical_sha({mission, attempt})[:32], so a
# re-run that reuses a mission/attempt pair is refused as a replay of different
# content. Every run therefore carries its own mission id.
MISSION = "lane10-desktop-live-" + time.strftime("%H%M%S")
OUT = Path(__file__).resolve().parent
HOME = str(Path.home())

SENTINELS = ["DAEDALUS", "ZINNOBER", "LANE10", "SENTINEL", "739104"]
TYPED = " KARMESIN99"
TYPED_AFTER_BACKSPACE = "KARMESIN9"

steps: list[dict] = []
_counter = [0]
LAUNCHED: list[int] = []
APP_IMAGE: list[str] = []


def ledger_states(control: Path) -> dict:
    """Count effect-lease execution states; a refusal must not strand STARTED."""
    import sqlite3
    database = control / "effect-leases.sqlite3"
    if not database.exists():
        return {}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return {state: count for state, count in connection.execute(
            "select state, count(*) from effect_executions group by state")}
    finally:
        connection.close()


def sanitize(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    for spelling in (HOME.replace("\\", "\\\\"), HOME.replace("\\", "/"), HOME):
        text = text.replace(spelling, "<USERPROFILE>")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# read-only host probes (harness only, never an adapter effect)                #
# --------------------------------------------------------------------------- #
_u = ctypes.WinDLL("user32", use_last_error=True)
_k = ctypes.WinDLL("kernel32", use_last_error=True)
_u.GetForegroundWindow.restype = wintypes.HWND
_u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_u.GetWindow.restype = wintypes.HWND
_u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_u.SetForegroundWindow.argtypes = [wintypes.HWND]
_u.IsWindowVisible.argtypes = [wintypes.HWND]
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_k.OpenProcess.restype = wintypes.HANDLE
_dwm = ctypes.WinDLL("dwmapi")


def _image_of(pid: int) -> str:
    handle = _k.OpenProcess(0x1000, False, pid)
    if not handle:
        return "<unavailable>"
    try:
        size = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if not _k.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return "<unavailable>"
        return name.value
    finally:
        _k.CloseHandle(handle)


def _class_of(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _u.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def _cloaked(hwnd) -> int:
    value = ctypes.c_int(0)
    _dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(value), ctypes.sizeof(value))
    return value.value


def foreground_probe() -> dict:
    """Read-only: which executable currently owns the foreground window."""
    hwnd = _u.GetForegroundWindow()
    if not hwnd:
        return {"foreground": None}
    pid = wintypes.DWORD()
    _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"foreground_window_class": _class_of(hwnd),
            "foreground_executable": _image_of(pid.value),
            "foreground_pid": pid.value}


def app_windows(image: str) -> list[tuple[int, int]]:
    """Visible top-level windows owned by the authorized executable image.

    The adapter matches on the executable path, not on the pid app.launch
    returned, because Windows 11 hands a launch off to a singleton app host.
    """
    found: list[tuple[int, int]] = []
    target = image.casefold()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if _u.IsWindowVisible(hwnd) and _image_of(owner.value).casefold() == target:
            found.append((hwnd, owner.value))
        return True

    _u.EnumWindows(callback, 0)
    return found


def overlap_diagnostic(hwnd) -> list[dict]:
    """Re-run the adapter's Z-order overlap rule read-only, to name the blocker."""
    rect, point = wintypes.RECT(), wintypes.POINT()
    if not _u.GetClientRect(hwnd, ctypes.byref(rect)) or not _u.ClientToScreen(hwnd, ctypes.byref(point)):
        return [{"error": "coordinate frame unavailable"}]
    width, height = rect.right, rect.bottom
    blockers = []
    above = _u.GetWindow(hwnd, 3)
    while above:
        if _u.IsWindowVisible(above):
            overlay = wintypes.RECT()
            if _u.GetWindowRect(above, ctypes.byref(overlay)) and (
                overlay.left < point.x + width and overlay.right > point.x
                and overlay.top < point.y + height and overlay.bottom > point.y
            ):
                owner = wintypes.DWORD()
                _u.GetWindowThreadProcessId(above, ctypes.byref(owner))
                blockers.append({"class": _class_of(above), "cloaked": _cloaked(above),
                                 "rect": [overlay.left, overlay.top, overlay.right, overlay.bottom],
                                 "executable": Path(_image_of(owner.value)).name})
        above = _u.GetWindow(above, 3)
    return blockers


# --------------------------------------------------------------------------- #
# measurement driver                                                           #
# --------------------------------------------------------------------------- #
def run(service, label: str, tool: str, args: dict, note: str = "") -> dict:
    _counter[0] += 1
    attempt = f"lane10-a{_counter[0]:02d}"
    started = time.monotonic()
    result = service.execute(tool, args, mission_id=MISSION, attempt_id=attempt)
    elapsed = round(time.monotonic() - started, 3)
    record = {"step": label, "attempt_id": attempt, "tool": tool,
              "arguments": sanitize(args), "seconds": elapsed,
              "ok": result.get("ok"), "state": result.get("state"),
              "error": result.get("error"), "error_type": result.get("error_type"),
              "result": sanitize(result.get("result")), "note": note}
    if result.get("ok"):
        evidence = result["evidence"]
        record["evidence_digests"] = {
            "artifact_sha256": evidence["artifact"]["sha256"],
            "lease_sha256": evidence["lease_sha256"],
            "start_sha256": evidence["start_sha256"],
            "terminal_sha256": evidence["terminal_sha256"],
            "operation_sha256": evidence["binding"]["operation_sha256"],
            "execution_id": evidence["binding"]["execution_id"],
        }
    steps.append(record)
    print(f"[{label}] {tool} -> ok={record['ok']} state={record['state']} "
          f"{elapsed}s {record['error'] or ''}", flush=True)
    return result


def words_of(result: dict) -> list[str]:
    return [w["text"] for w in (result.get("result") or {}).get("words", [])]


def main() -> int:
    from daedalus.runtimes.computer import ComputerService
    from daedalus.spine.killswitch import KillSwitch

    report: dict = {"authority_root": sanitize(str(AUTHORITY)), "mission_id": MISSION,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    service = ComputerService(AUTHORITY)
    report["policy_sha256"] = service.policy_digest
    report["limit_policy_mode"] = service.limit_policy.mode
    report["control_root"] = sanitize(str(service.control))
    report["ledger_states_before"] = ledger_states(service.control)
    report["control_root_image_files_before"] = [
        p.name for p in service.control.rglob("*")
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]

    # m00 -- observe while our application is not even running.
    report["foreground_before_launch"] = sanitize(foreground_probe())
    run(service, "m00_observe_without_foreground_app", "desktop.observe", {},
        "Notepad is not running; the owner's own window owns the foreground")

    # PRIVACY PRECONDITION. The packaged Notepad is a singleton with tabs: if the
    # owner already has one open, a launch would join their window and a capture
    # would read their content. Refuse the whole measurement in that case.
    preexisting = app_windows(str(Path(service._policy.applications[0][1][0])))
    report["preexisting_authorized_windows"] = len(preexisting)
    if preexisting:
        report["abort"] = ("the owner already has a window of the authorized application open; "
                           "refusing to launch into it or to capture its content")
        return finish(report, None)

    # m01 -- launch the single authorized application.
    launch = run(service, "m01_app_launch", "app.launch", {"application": "notepad"})
    pid = (launch.get("result") or {}).get("process_id")
    report["launched_pid_recorded"] = pid is not None
    if pid:
        LAUNCHED.append(pid)
    if pid is None:
        report["abort"] = "app.launch produced no process id"
        return finish(report, None)

    authorized = str(Path(service._policy.applications[0][1][0]))
    APP_IMAGE.append(authorized)
    deadline = time.monotonic() + 15
    hwnd = None
    while time.monotonic() < deadline:
        current = _u.GetForegroundWindow()
        owners = {w for w, _ in app_windows(authorized)}
        if current in owners:
            hwnd = current
            break
        time.sleep(0.25)
    report["foreground_after_launch"] = sanitize(foreground_probe())
    report["authorized_image_owns_foreground"] = hwnd is not None
    report["authorized_image_window_count"] = len(app_windows(authorized))
    report["launched_pid_owns_the_window"] = any(
        owner == pid for _, owner in app_windows(authorized))
    for _, owner in app_windows(authorized):
        LAUNCHED.append(owner)
    if hwnd:
        report["overlap_diagnostic_after_launch"] = overlap_diagnostic(hwnd)

    # m02 -- the authorized observation.
    observation = run(service, "m02_observe_foreground", "desktop.observe", {})
    obs = (observation.get("result") or {}).get("observation_id")
    if obs is None:
        report["abort"] = "desktop.observe refused with the launched window in the foreground"
        report["abort_foreground"] = sanitize(foreground_probe())
        if hwnd:
            report["abort_overlap_diagnostic"] = overlap_diagnostic(hwnd)
        return finish(report, pid)
    report["observation_provenance"] = sanitize({
        k: v for k, v in (observation.get("result") or {}).items()
        if k in {"frame", "image_sha256", "captured_at", "observation_id"}})
    obs_created = time.monotonic()

    # m03/m04 -- vision over the same observation token.
    run(service, "m03_vision_inspect", "vision.inspect", {"observation_id": obs})
    ocr = run(service, "m04_vision_ocr", "vision.ocr", {"observation_id": obs})
    found = words_of(ocr)
    report["ocr_words_fixture"] = found
    report["ocr_sentinels_found"] = {s: any(s in w for w in found) for s in SENTINELS}
    report["ocr_confidence_values"] = sorted({
        json.dumps(w.get("confidence")) for w in (ocr.get("result") or {}).get("words", [])})

    # m05 -- stale observation: the same token past the 30 s freshness window.
    wait = 31 - (time.monotonic() - obs_created)
    if wait > 0:
        print(f"[m05] waiting {wait:.1f}s for the observation to go stale", flush=True)
        time.sleep(wait)
    report["stale_age_seconds"] = round(time.monotonic() - obs_created, 1)
    run(service, "m05_vision_ocr_stale_observation", "vision.ocr", {"observation_id": obs},
        "same observation_id, now older than the 30 s freshness window")

    # m06.. -- input into our own window, each with a fresh observation.
    def input_step(label: str, tool: str, build, max_attempts: int = 10):
        attempts = []
        for index in range(max_attempts):
            fresh = run(service, f"{label}_observe{index}", "desktop.observe", {})
            token = (fresh.get("result") or {}).get("observation_id")
            if token is None:
                attempts.append({"attempt": index, "outcome": "observe refused",
                                 "error": fresh.get("error")})
                break
            outcome = run(service, f"{label}_try{index}", tool, build(token))
            attempts.append({"attempt": index, "ok": outcome.get("ok"),
                             "error": outcome.get("error")})
            if outcome.get("ok"):
                return outcome, attempts
        return None, attempts

    end_key, end_attempts = input_step(
        "m06_key_end", "desktop.key",
        lambda t: {"observation_id": t, "key": "END",
                   "expected": "caret at the end of the first fixture line"})
    report["m06_attempts"] = end_attempts

    typed, type_attempts = input_step(
        "m07_type", "desktop.type",
        lambda t: {"observation_id": t, "text": TYPED,
                   "expected": "first line ends with KARMESIN99"})
    report["m07_attempts"] = type_attempts

    # m08 -- independent postcondition verification through a second observation.
    verify = run(service, "m08_observe_after_typing", "desktop.observe", {})
    verify_obs = (verify.get("result") or {}).get("observation_id")
    if verify_obs:
        after = run(service, "m09_vision_ocr_after_typing", "vision.ocr",
                    {"observation_id": verify_obs})
        report["ocr_words_after_typing"] = words_of(after)
        report["postcondition_typed_text_visible"] = any(
            "KARMESIN99" in w for w in words_of(after))

    backspace, backspace_attempts = input_step(
        "m10_key_backspace", "desktop.key",
        lambda t: {"observation_id": t, "key": "BACKSPACE",
                   "expected": "the last typed character is removed"})
    report["m10_attempts"] = backspace_attempts

    verify2 = run(service, "m11_observe_after_backspace", "desktop.observe", {})
    verify2_obs = (verify2.get("result") or {}).get("observation_id")
    if verify2_obs:
        after2 = run(service, "m12_vision_ocr_after_backspace", "vision.ocr",
                     {"observation_id": verify2_obs})
        report["ocr_words_after_backspace"] = words_of(after2)
        report["postcondition_backspace_applied"] = (
            any(TYPED_AFTER_BACKSPACE == w for w in words_of(after2))
            and not any("KARMESIN99" in w for w in words_of(after2)))

    # m13 -- the authorized window loses the foreground while it keeps running.
    if hwnd:
        _u.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        time.sleep(1.0)
        report["foreground_while_minimized"] = sanitize(foreground_probe())
        run(service, "m13_observe_while_minimized", "desktop.observe", {},
            "the authorized application runs but no longer owns the foreground")
        _u.ShowWindow(hwnd, 9)  # SW_RESTORE
        _u.SetForegroundWindow(hwnd)
        time.sleep(1.5)
        report["foreground_restored"] = bool(_u.GetForegroundWindow() == hwnd)

    # m14 -- kill switch stop while a step is pending inside the adapter.
    stopper = KillSwitch(repo_root=AUTHORITY)
    report["killswitch_path"] = sanitize(str(stopper.path))
    pending = run(service, "m14_observe_before_kill", "desktop.observe", {})
    pending_obs = (pending.get("result") or {}).get("observation_id")
    if pending_obs:
        stop_at = [None]

        def stop_soon():
            time.sleep(0.35)
            stop_at[0] = time.monotonic()
            stopper.stop("lane10 kill switch during a pending vision.ocr step")

        thread = threading.Thread(target=stop_soon)
        started = time.monotonic()
        thread.start()
        run(service, "m15_vision_ocr_during_kill", "vision.ocr", {"observation_id": pending_obs},
            "the kill switch is engaged from another thread while OCR polls its checkpoint")
        thread.join()
        report["kill_stop_after_seconds"] = round((stop_at[0] or started) - started, 3)
        report["kill_latch_seconds"] = round(time.monotonic() - (stop_at[0] or started), 3)
        run(service, "m16_observe_after_kill", "desktop.observe", {},
            "the latched switch must refuse every further step in this service")

    # m17 -- operator recovery: re-arm and prove a new service works again.
    rearm = stopper.arm(force=True, note="lane10 measurement recovery")
    report["rearmed"] = rearm.running
    recovered = ComputerService(AUTHORITY)
    run(recovered, "m17_observe_after_rearm", "desktop.observe", {},
        "a new ComputerService after an operator re-arm; the latched object stays latched")
    return finish(report, pid)


def finish(report: dict, pid) -> int:
    # Close the application without saving: a force terminate is the only exit
    # that cannot write the modified buffer back to the fixture file.
    codes = []
    for target in dict.fromkeys(LAUNCHED):
        codes.append(subprocess.run(["taskkill", "/PID", str(target), "/T", "/F"],
                                    capture_output=True).returncode)
    report["cleanup_taskkill_rcs"] = codes
    time.sleep(0.8)
    report["cleanup_windows_remaining"] = len(app_windows(APP_IMAGE[0])) if APP_IMAGE else None
    fixture = SCRATCH / "fixture" / "lane10-sentinel.txt"
    report["fixture_unchanged"] = fixture.read_text(encoding="utf-8") == (
        "DAEDALUS ZINNOBER\nLANE10 SENTINEL 739104\n")
    from daedalus.spine.killswitch import control_root
    control = control_root(AUTHORITY)
    report["ledger_states_after"] = ledger_states(control)
    report["control_root_image_files_after"] = [
        p.name for p in control.rglob("*")
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    report["steps"] = steps
    (OUT / "lane10_measure_result.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "steps"},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        # Never leave the owner's desktop holding a modified, unsaved buffer.
        for stray in LAUNCHED:
            subprocess.run(["taskkill", "/PID", str(stray), "/T", "/F"],
                           capture_output=True, text=True)
        raise
