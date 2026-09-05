"""Private trusted Windows adapter, called only behind canonical effect admission.

Images stay in memory. Input tokens are single-use and are invalidated before
an effect, including an effect whose result becomes unknown. This is not an OS
sandbox for an authorized application's own behavior.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable
import uuid

from daedalus.atomic import ExclusiveFileLock
from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused


class _WindowsDesktop:
    def __init__(self) -> None:
        if os.name != "nt":
            raise ComputerRefused("desktop adapter is unavailable on this platform")
        import ctypes
        from ctypes import wintypes
        self.c, self.w = ctypes, wintypes
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.u.GetWindow.restype = wintypes.HWND
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.u.IsWindowVisible.argtypes = [wintypes.HWND]
        self.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.u.MonitorFromWindow.restype = wintypes.HANDLE
        self.u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k.OpenProcess.restype = wintypes.HANDLE
        self.k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        session = wintypes.DWORD()
        if not self.k.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise ComputerRefused("cannot identify interactive desktop session")
        self.session_id = str(session.value)

    def snapshot(self, applications: tuple) -> dict[str, Any]:
        c, w, u = self.c, self.w, self.u
        previous = u.SetThreadDpiAwarenessContext(c.c_void_p(-4))
        if not previous:
            raise ComputerRefused("per-monitor DPI coordinates unavailable")
        try:
            hwnd = u.GetForegroundWindow()
            if not hwnd or not u.IsWindowVisible(hwnd):
                raise ComputerRefused("no visible foreground application")
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, c.byref(pid))
            handle = self.k.OpenProcess(0x1000, False, pid.value)
            if not handle:
                raise ComputerRefused("foreground application identity unavailable")
            try:
                size = w.DWORD(32768)
                name = c.create_unicode_buffer(size.value)
                if not self.k.QueryFullProcessImageNameW(handle, 0, name, c.byref(size)):
                    raise ComputerRefused("foreground executable cannot be verified")
                executable = os.path.normcase(str(Path(name.value).resolve()))
            finally:
                self.k.CloseHandle(handle)
            allowed = {os.path.normcase(str(Path(argv[0]).resolve())) for _, argv in applications}
            if executable not in allowed:
                raise ComputerRefused("foreground executable is not owner-authorized")
            class GUIThreadInfo(c.Structure):
                _fields_ = [("size", w.DWORD), ("flags", w.DWORD), ("active", w.HWND),
                            ("focus", w.HWND), ("capture", w.HWND), ("menu", w.HWND),
                            ("move", w.HWND), ("caret", w.HWND), ("caret_rect", w.RECT)]
            info = GUIThreadInfo()
            info.size = c.sizeof(info)
            self.u.GetGUIThreadInfo.argtypes = [w.DWORD, c.POINTER(GUIThreadInfo)]
            if not self.u.GetGUIThreadInfo(0, c.byref(info)) or info.active != hwnd:
                raise ComputerRefused("foreground input focus is unavailable or changed")
            focus_class = c.create_unicode_buffer(256)
            if info.focus:
                self.u.GetClassNameW(info.focus, focus_class, len(focus_class))
                if focus_class.value.lower() == "edit" and self.u.GetWindowLongW(info.focus, -16) & 0x20:
                    raise ComputerRefused("password control requires unavailable separate authority")
            rect, point = w.RECT(), w.POINT()
            if not u.GetClientRect(hwnd, c.byref(rect)) or not u.ClientToScreen(hwnd, c.byref(point)):
                raise ComputerRefused("window coordinate frame unavailable")
            width, height = rect.right, rect.bottom
            if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 16_777_216:
                raise ComputerRefused("window capture dimensions are outside supported bounds")
            # mss reads displayed pixels: refuse other visible windows above
            # this app so their contents cannot enter a scoped capture.
            above = u.GetWindow(hwnd, 3)  # GW_HWNDPREV, descending Z order
            while above:
                if u.IsWindowVisible(above):
                    overlay = w.RECT()
                    if u.GetWindowRect(above, c.byref(overlay)) and (
                        overlay.left < point.x + width and overlay.right > point.x
                        and overlay.top < point.y + height and overlay.bottom > point.y
                    ):
                        raise ComputerRefused("another window overlaps the authorized capture")
                above = u.GetWindow(above, 3)
            return {"window_id": str(hwnd), "monitor_id": str(u.MonitorFromWindow(hwnd, 2)),
                    "focus_window_id": str(info.focus),
                    "process_id": pid.value, "executable": executable,
                    "origin_x": point.x, "origin_y": point.y, "width": width, "height": height,
                    "dpi": int(u.GetDpiForWindow(hwnd)), "coordinate_space": "desktop",
                    "scale_x": 1.0, "scale_y": 1.0, "crop_x": 0, "crop_y": 0}
        finally:
            u.SetThreadDpiAwarenessContext(previous)

    def capture(self, frame: dict[str, Any]) -> bytes:
        try:
            import mss
            import mss.tools
        except ImportError as exc:
            raise ComputerRefused("screen capture unavailable; install the computer extra") from exc
        previous = self.u.SetThreadDpiAwarenessContext(self.c.c_void_p(-4))
        if not previous:
            raise ComputerRefused("per-monitor capture coordinates unavailable")
        try:
            with mss.mss() as screen:
                shot = screen.grab({"left": frame["origin_x"], "top": frame["origin_y"],
                                    "width": frame["width"], "height": frame["height"]})
                return mss.tools.to_png(shot.rgb, shot.size)
        finally:
            self.u.SetThreadDpiAwarenessContext(previous)

    def input(self, kind: str, value: Any) -> None:
        # The absolute SendInput frame must use the same per-monitor physical
        # coordinates as capture, including on mixed-DPI and negative monitors.
        previous = self.u.SetThreadDpiAwarenessContext(self.c.c_void_p(-4))
        if not previous:
            raise ComputerRefused("per-monitor input coordinates unavailable")
        try:
            self._input(kind, value)
        finally:
            self.u.SetThreadDpiAwarenessContext(previous)

    def _input(self, kind: str, value: Any) -> None:
        c, w = self.c, self.w
        # Existing human modifiers would change the meaning of generated input.
        if any(self.u.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            raise ComputerRefused("human modifier key is active; re-observe after release")
        class Keyboard(c.Structure):
            _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
                        ("time", w.DWORD), ("extra", c.c_size_t)]
        class Mouse(c.Structure):
            _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("data", w.DWORD),
                        ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        class Payload(c.Union):
            _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
        class Input(c.Structure):
            _fields_ = [("type", w.DWORD), ("payload", Payload)]
        events = []
        def key(vk: int, scan: int = 0, flags: int = 0) -> Input:
            return Input(1, Payload(keyboard=Keyboard(vk, scan, flags, 0, 0)))
        if kind == "text":
            encoded = value.encode("utf-16-le")
            for pos in range(0, len(encoded), 2):
                scan = int.from_bytes(encoded[pos:pos + 2], "little")
                events.extend((key(0, scan, 4), key(0, scan, 6)))
        elif kind == "key":
            keys = {"TAB": (9,), "ESC": (27,), "LEFT": (37,), "UP": (38,),
                    "RIGHT": (39,), "DOWN": (40,), "HOME": (36,), "END": (35,),
                    "BACKSPACE": (8,), "DELETE": (46,), "CTRL+A": (17, 65), "CTRL+S": (17, 83)}[value]
            events = [key(vk) for vk in keys] + [key(vk, flags=2) for vk in reversed(keys)]
        else:
            x, y = value
            left, top = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)
            width, height = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
            if width < 2 or height < 2:
                raise ComputerRefused("virtual desktop coordinates unavailable")
            dx, dy = round((x-left)*65535/(width-1)), round((y-top)*65535/(height-1))
            events = [Input(0, Payload(mouse=Mouse(dx, dy, 0, 0xC001, 0, 0))),
                      Input(0, Payload(mouse=Mouse(0, 0, 0, 2, 0, 0))),
                      Input(0, Payload(mouse=Mouse(0, 0, 0, 4, 0, 0)))]
        batch = (Input * len(events))(*events)
        self.u.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
        if self.u.SendInput(len(events), batch, c.sizeof(Input)) != len(events):
            raise ComputerRefused("desktop input outcome unknown; re-observe, do not repeat")


class DesktopAdapter:
    def __init__(self, policy: ComputerPolicy, checkpoint: Callable[[], None], control_root: Path) -> None:
        self.policy, self.checkpoint, self.control_root = policy, checkpoint, Path(control_root)
        self._host: Any = None
        self._observation: dict[str, Any] | None = None
        self._png: bytes | None = None

    def _backend(self) -> Any:
        if self._host is None:
            self._host = _WindowsDesktop()
        return self._host

    def _frame(self) -> dict[str, Any]:
        self.checkpoint()
        return self._backend().snapshot(self.policy.applications)

    def _capture(self) -> tuple[dict[str, Any], bytes]:
        frame = self._frame()
        self.checkpoint()
        png = self._backend().capture(frame)
        if self._frame() != frame:
            raise ComputerRefused("foreground changed during capture; image discarded")
        return frame, png

    def capture_png(self, observation_id: str) -> tuple[bytes, dict[str, Any]]:
        """For trusted local vision only; caller must separately admit vision use."""
        self.checkpoint()
        self.require_fresh_observation(observation_id)
        obs = self._observation
        assert obs is not None
        if self._frame() != obs["frame"]:
            raise ComputerRefused("desktop focus changed")
        assert self._png is not None
        return self._png, {**obs["frame"], "captured_at": obs["captured_at"]}

    def require_fresh_observation(self, observation_id: str) -> None:
        """Check the in-memory token only; safe to call before effect admission."""
        obs = self._observation
        if not obs or obs["observation_id"] != observation_id or time.monotonic() - obs["created"] > 30:
            raise ComputerRefused("desktop observation is stale or unavailable")

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.policy.admit(tool, args)
        self.checkpoint()
        if tool == "app.launch" and set(args) != {"application"}:
            raise ComputerRefused("application arguments are fixed by the owner")
        if tool not in {"app.launch", "desktop.observe", "desktop.click", "desktop.type", "desktop.key"}:
            raise ComputerRefused("unsupported desktop tool")
        host = self._backend()
        # All authority roots below the canonical control directory share one
        # interactive desktop; per-authority locks would permit concurrent input.
        with ExclusiveFileLock(self.control_root.parent / f"computer-desktop-session-{host.session_id}.lock",
                               timeout_s=1, label="interactive desktop input"):
            self.checkpoint()
            if tool == "app.launch":
                argv = dict(self.policy.applications)[args["application"]]
                self._observation, self._png = None, None
                self.checkpoint()
                process = subprocess.Popen(argv, cwd=self.policy.workspace, shell=False,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"status": "observed", "application": args["application"], "process_id": process.pid,
                        "postcondition_verified": False}
            if tool == "desktop.observe":
                if args:
                    raise ComputerRefused("desktop.observe takes no caller capture scope")
                self._observation, self._png = None, None
                frame, png = self._capture()
                obs = {"observation_id": uuid.uuid4().hex, "frame": frame,
                       "image_sha256": hashlib.sha256(png).hexdigest(), "created": time.monotonic(),
                       "captured_at": datetime.now(timezone.utc).isoformat()}
                self._observation, self._png = obs, png
                return {k: v for k, v in {"status": "observed", **obs, "postcondition_verified": False}.items() if k != "created"}
            obs = self._observation
            if not obs or args.get("observation_id") != obs["observation_id"] or time.monotonic() - obs["created"] > 30:
                raise ComputerRefused("fresh desktop observation required")
            if not isinstance(args.get("expected"), str) or not 1 <= len(args["expected"]) <= 1000:
                raise ComputerRefused("desktop input requires an explicit expected postcondition")
            extra = {"desktop.click": {"x", "y"}, "desktop.type": {"text"}, "desktop.key": {"key"}}[tool]
            if set(args) != {"observation_id", "expected"} | extra:
                raise ComputerRefused("unknown desktop action arguments")
            if tool == "desktop.click":
                x, y = args["x"], args["y"]
                if type(x) is not int or type(y) is not int or not 0 <= x < obs["frame"]["width"] or not 0 <= y < obs["frame"]["height"]:
                    raise ComputerRefused("click lies outside the observed window")
                values = [("click", (obs["frame"]["origin_x"] + x, obs["frame"]["origin_y"] + y))]
            elif tool == "desktop.type":
                text = args["text"]
                if not isinstance(text, str) or not 1 <= len(text) <= 4096 or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in text):
                    raise ComputerRefused("typing requires bounded printable Unicode text")
                values = [("text", ch) for ch in text]
            else:
                if args["key"] not in {"TAB", "ESC", "LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "BACKSPACE", "DELETE", "CTRL+A", "CTRL+S"}:
                    raise ComputerRefused("desktop key is not enabled")
                values = [("key", args["key"])]
            frame, png = self._capture()
            if frame != obs["frame"] or hashlib.sha256(png).hexdigest() != obs["image_sha256"]:
                self._observation, self._png = None, None
                raise ComputerRefused("desktop pixels or focus changed; observe again")
            # Consume before effect: exceptions/cancellation cannot replay input.
            self._observation, self._png = None, None
            for kind, value in values:
                if self._frame() != frame:
                    raise ComputerRefused("foreground changed during input; outcome may be partial")
                self.checkpoint()
                host.input(kind, value)
            return {"status": "observed", "observation_id": obs["observation_id"],
                    "expected": args["expected"], "input_groups": len(values),
                    "postcondition_verified": False, "next_step": "observe and independently verify the postcondition"}
