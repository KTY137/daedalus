"""Desktop route composition for the existing authenticated HTTP facade."""
from __future__ import annotations

from typing import Any, Callable


def install_web_integration(
    web_api: Any,
    manager: Any,
    *,
    desktop_error: type[Exception],
    project_registry_unavailable: type[Exception],
    resolve_project_root: Callable[[Any], str],
    compare_digest: Callable[[str, str], bool],
    split_url: Callable[[str], Any],
) -> None:
    """Add desktop routes without creating a second HTTP/control server."""

    base = web_api.DaedalusHandler

    class ManagedHandler(base):
        def _handle_get(self) -> None:
            path = split_url(self.path).path
            if path == "/api/host/capabilities":
                snapshot = manager.snapshot()
                projector = getattr(web_api, "_host_capabilities", None)
                capabilities = (
                    projector("desktop", snapshot)
                    if callable(projector)
                    else {
                        "host_mode": "desktop",
                        "can_manage_openvscode": bool(
                            snapshot.get("services", {})
                            .get("ide", {})
                            .get("available")
                            is True
                        ),
                        "can_open_external_editor": bool(
                            snapshot.get("services", {})
                            .get("ide", {})
                            .get("reachable")
                            is True
                        ),
                        "can_send_editor_commands": False,
                        "editor_commands_require_session": True,
                    }
                )
                self._send_json(
                    web_api.core.envelope(None, host_capabilities=capabilities)
                )
                return
            if path == "/api/desktop/settings":
                self._send_json(
                    web_api.core.envelope(None, desktop=manager.snapshot())
                )
                return
            super()._handle_get()

        def _handle_put(self) -> None:
            if split_url(self.path).path == "/api/desktop/settings":
                try:
                    snap = manager.save_settings(web_api._read_body(self))
                    web_api.runtime_registry.reset_status_cache()
                    self._send_json(web_api.core.envelope(None, desktop=snap))
                except (ValueError, desktop_error) as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            super()._handle_put()

        def _handle_post(self) -> None:
            path = split_url(self.path).path
            try:
                if path == "/api/desktop/shutdown":
                    expected = (
                        getattr(
                            self.server,
                            "daedalus_desktop_startup_nonce",
                            "",
                        )
                        or ""
                    )
                    supplied = self.headers.get("X-Daedalus-Desktop-Nonce", "")
                    if not expected or not compare_digest(supplied, expected):
                        self._send_json(
                            {
                                "ok": False,
                                "error": "desktop parent nonce required",
                            },
                            status=403,
                        )
                        return
                    manager.close(strict=True, timeout=6.0)
                    result = {"closed": True}
                elif path == "/api/desktop/services/bridge/start":
                    result = manager.ensure_bridge()
                elif path == "/api/desktop/services/ollama/start":
                    result = manager.ensure_ollama()
                    web_api.runtime_registry.reset_status_cache()
                elif path == "/api/desktop/services/ollama/stop":
                    manager.stop_ollama()
                    web_api.runtime_registry.reset_status_cache()
                    result = manager.snapshot()["services"]["ollama"]
                elif path == "/api/desktop/services/ide/start":
                    body = web_api._read_body(self)
                    if not isinstance(body, dict):
                        raise desktop_error("request body must be a JSON object")
                    project_root = resolve_project_root(body.get("project"))
                    result = manager.ensure_ide(project_root)
                elif path == "/api/desktop/services/ide/stop":
                    manager.stop_ide(strict=True)
                    result = manager.snapshot()["services"]["ide"]
                else:
                    super()._handle_post()
                    return
                self._send_json(web_api.core.envelope(None, service=result))
            except project_registry_unavailable as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=503)
            except (ValueError, desktop_error) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    web_api.DaedalusHandler = ManagedHandler
