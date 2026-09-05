"""G1-IKARUS-30 probe: what does launching C:\\Windows\\System32\\notepad.exe start?

Harness-only, no adapter and no policy: this answers whether the owner-fixed
argv[0] is the executable that ends up owning the window, which is what
``_WindowsDesktop.snapshot`` compares against. No image is captured.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time

SCRATCH = Path(r"C:\Users\nukei\AppData\Local\Temp\daedalus-lane10")
FIXTURE = SCRATCH / "fixture" / "lane10-sentinel.txt"
CANDIDATES = [r"C:\Windows\System32\notepad.exe"]
HOME = str(Path.home())

_u = ctypes.WinDLL("user32", use_last_error=True)
_k = ctypes.WinDLL("kernel32", use_last_error=True)
_u.GetForegroundWindow.restype = wintypes.HWND
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u.IsWindowVisible.argtypes = [wintypes.HWND]
_u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_k.OpenProcess.restype = wintypes.HANDLE


def image_of(pid: int) -> str:
    handle = _k.OpenProcess(0x1000, False, pid)
    if not handle:
        return "<process gone or denied>"
    try:
        size = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if not _k.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return "<query failed>"
        return name.value
    finally:
        _k.CloseHandle(handle)


def windows_of(pid: int) -> list[dict]:
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buffer = ctypes.create_unicode_buffer(256)
            _u.GetClassNameW(hwnd, buffer, len(buffer))
            found.append({"class": buffer.value, "visible": bool(_u.IsWindowVisible(hwnd))})
        return True

    _u.EnumWindows(callback, 0)
    return found


def probe(executable: str) -> dict:
    record: dict = {"argv0": executable}
    record["argv0_resolves_to"] = str(Path(executable).resolve())
    process = subprocess.Popen([executable, str(FIXTURE)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record["launched_pid"] = process.pid
    time.sleep(3.0)
    record["launched_pid_image"] = image_of(process.pid)
    record["launched_pid_exit_code"] = process.poll()
    record["launched_pid_windows"] = windows_of(process.pid)
    hwnd = _u.GetForegroundWindow()
    owner = wintypes.DWORD()
    _u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    record["foreground_pid"] = owner.value
    record["foreground_image"] = image_of(owner.value)
    record["foreground_is_launched_pid"] = owner.value == process.pid
    record["adapter_would_match"] = (
        record["foreground_image"].casefold() == record["argv0_resolves_to"].casefold())
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    if owner.value != process.pid:
        subprocess.run(["taskkill", "/PID", str(owner.value), "/T", "/F"], capture_output=True)
    time.sleep(0.5)
    record["cleanup_launched_gone"] = image_of(process.pid).startswith("<")
    record["cleanup_foreground_gone"] = image_of(owner.value).startswith("<")
    return record


def main() -> int:
    report = {"fixture": str(FIXTURE), "probes": [probe(c) for c in CANDIDATES]}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    for spelling in (HOME.replace("\\", "\\\\"), HOME.replace("\\", "/"), HOME):
        text = text.replace(spelling, "<USERPROFILE>")
    (Path(__file__).resolve().parent / "lane10_launch_probe.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
