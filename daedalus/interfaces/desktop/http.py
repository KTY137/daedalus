"""Desktop route composition for the existing authenticated HTTP facade."""
from __future__ import annotations

from typing import Any, Callable

from ..http.effects import same_origin_request
from .effects import (
    DesktopEffectRefused,
    DesktopEffectUnavailable,
    DesktopFeatureUnavailable,
    DesktopPolicyDenied,
    DesktopValidationError,
)


DESKTOP_MUTATION_MAX_BODY_BYTES = 64 * 1024


def _header_values(handler: Any, name: str) -> tuple[str, ...]:
    headers = getattr(handler, "headers", None)
    if headers is None:
        return ()
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        return tuple(str(value) for value in (get_all(name) or ()))
    get_one = getattr(headers, "get", None)
    if not callable(get_one):
        return ()
    value = get_one(name)
    return () if value is None else (str(value),)


def _desktop_mutation_refusal(handler: Any, path: str) -> str | None:
    origins = _header_values(handler, "Origin")
    if len(origins) != 1 or not same_origin_request(handler, origins[0]):
        return "desktop mutations require the exact numeric bound Origin"

    fetch_sites = _header_values(handler, "Sec-Fetch-Site")
    if len(fetch_sites) != 1 or fetch_sites[0].casefold() != "same-origin":
        return "desktop mutations require Sec-Fetch-Site: same-origin"

    if path == "/api/desktop/shutdown":
        return None

    content_types = _header_values(handler, "Content-Type")
    if (
        len(content_types) != 1
        or content_types[0].split(";", 1)[0].strip().casefold()
        != "application/json"
    ):
        return "desktop mutations require Content-Type application/json"
    if _header_values(handler, "Transfer-Encoding"):
        return "desktop mutations require a bounded Content-Length"
    lengths = _header_values(handler, "Content-Length")
    if len(lengths) != 1:
        return "desktop mutations require one bounded non-empty Content-Length"
    raw_length = lengths[0].strip()
    if (
        not raw_length.isascii()
        or not raw_length.isdecimal()
        or len(raw_length) > len(str(DESKTOP_MUTATION_MAX_BODY_BYTES))
    ):
        return "desktop mutation Content-Length is invalid"
    length = int(raw_length)
    if not 0 < length <= DESKTOP_MUTATION_MAX_BODY_BYTES:
        return "desktop mutation body must be non-empty and bounded"
    return None


def _error_payload(error: DesktopEffectRefused) -> dict[str, Any]:
    return {
        "ok": False,
        "error": str(error),
        "error_code": error.error_code,
        "committed": error.committed,
    }


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
        def _send_desktop_error(self, error: DesktopEffectRefused) -> None:
            self._send_json(_error_payload(error), status=error.status_code)

        def _desktop_mutation_is_refused(self) -> bool:
            path = split_url(self.path).path
            if not path.startswith("/api/desktop/"):
                return False
            refusal = _desktop_mutation_refusal(self, path)
            if refusal is None:
                return False
            self.close_connection = True
            self._send_desktop_error(DesktopPolicyDenied(refusal))
            return True

        def do_PUT(self) -> None:
            if self._desktop_mutation_is_refused():
                return
            super().do_PUT()

        def do_POST(self) -> None:
            if self._desktop_mutation_is_refused():
                return
            super().do_POST()

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
                            .get("managed_start_available")
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
                desktop = dict(manager.snapshot())
                desktop["settings_update_contract"] = "section_updates_v1"
                self._send_json(
                    web_api.core.envelope(None, desktop=desktop)
                )
                return
            super()._handle_get()

        def _handle_put(self) -> None:
            if split_url(self.path).path == "/api/desktop/settings":
                try:
                    snap = dict(manager.save_settings(web_api._read_body(self)))
                    snap["settings_update_contract"] = "section_updates_v1"
                    web_api.runtime_registry.reset_status_cache()
                    self._send_json(web_api.core.envelope(None, desktop=snap))
                except DesktopEffectRefused as exc:
                    self._send_desktop_error(exc)
                except ValueError as exc:
                    self._send_desktop_error(DesktopValidationError(str(exc)))
                except desktop_error as exc:
                    self._send_desktop_error(DesktopEffectUnavailable(str(exc)))
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
                        self._send_desktop_error(
                            DesktopPolicyDenied("desktop parent nonce required")
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
                    result = {"stopped": True}
                elif path == "/api/desktop/services/ide/start":
                    # Refuse the unavailable feature before reading an
                    # attacker-controlled body or resolving a project path.
                    result = manager.ensure_ide()
                elif path == "/api/desktop/services/ide/stop":
                    manager.stop_ide(strict=True)
                    result = {"stopped": True}
                else:
                    super()._handle_post()
                    return
                self._send_json(web_api.core.envelope(None, service=result))
            except project_registry_unavailable as exc:
                self._send_desktop_error(DesktopFeatureUnavailable(str(exc)))
            except DesktopEffectRefused as exc:
                self._send_desktop_error(exc)
            except ValueError as exc:
                self._send_desktop_error(DesktopValidationError(str(exc)))
            except desktop_error as exc:
                self._send_desktop_error(DesktopEffectUnavailable(str(exc)))

    web_api.DaedalusHandler = ManagedHandler
