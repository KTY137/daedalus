"""Mutation route dispatch behind the registered legacy effect facade."""
from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from ...kairos import drafts
from ... import core, file_bridge
from ...orchestration.ikarus import shell as ikarus_os
from ...orchestration import agents_registry, categories, control_plane, conversation_requests, editor_context, hierarchy, runtime_registry
from ...orchestration.ikarus import chat as ikarus_chat
from ...foundation.projects import (
    ProjectRegistrationError,
    ProjectRegistryUnavailable,
)
from ...structcore.slice import semantic_slice
from .router import parse_request_target

EffectPort = Callable[..., Any]
MUTATION_MAX_BODY_BYTES = 64 * 1024
GENESIS_MAX_BODY_BYTES = MUTATION_MAX_BODY_BYTES
ARIADNE_MAX_BODY_BYTES = MUTATION_MAX_BODY_BYTES
_PREPARED_POST_BODY_ATTR = "_daedalus_prepared_post_body"
_PREFLIGHT_POST_PATHS = frozenset({"/api/genesis", "/api/ariadne"})


def mutation_route_wired(path: str) -> bool:
    """True while ``path`` is a wired effectful POST route of this facade.

    One table serves the preflight, the dispatch and every capability flag a
    projection advertises, so a route cannot be removed here and still be
    announced elsewhere (G1-ARIADNE-02 matrix item 7).
    """
    return path in _PREFLIGHT_POST_PATHS
_ARIADNE_FIELDS = (
    "project",
    "source_revision",
    "campaign_id",
    "target_path",
    "before",
    "after",
)


class _MutationRequestBoundaryError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status: int,
        drain_body: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        # The refusal decision has already been made.  A small, unambiguous
        # fixed-length body may still be discarded before the connection is
        # closed so Winsock does not replace the JSON refusal with a TCP reset.
        # Parsed, ambiguous, and oversized bodies must never enter this path.
        self.drain_body = drain_body


@dataclass(frozen=True)
class EffectPorts:
    """Legacy-owned seams whose monkeypatch and target identity must survive."""

    read_body: EffectPort
    structure_index: EffectPort
    resolve_repo_root: EffectPort
    resolve_registered_project_root: EffectPort
    register_project: EffectPort
    genesis_run: EffectPort
    ariadne_run: EffectPort


def read_body(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


def same_origin_request(handler: Any, origin: str) -> bool:
    """Match one HTTP Origin to the server's exact numeric bound authority."""

    try:
        parsed = urlsplit(origin)
        server_host, server_port = getattr(
            handler.server, "server_address", ("", 0)
        )[:2]
        bound_address = ip_address(str(server_host).strip().strip("[]"))
        bound_port = int(server_port)
        origin_address = ip_address(parsed.hostname or "")
        origin_port = parsed.port
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False
    return (
        parsed.scheme == "http"
        and origin_address == bound_address
        and origin_port == bound_port
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and parsed.query == ""
        and parsed.fragment == ""
    )


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


class _DuplicateJSONField(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONField(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _read_bounded_json_body(
    handler: Any,
    *,
    surface: str,
    max_body_bytes: int = MUTATION_MAX_BODY_BYTES,
) -> Any:
    content_types = _header_values(handler, "Content-Type")
    if (
        len(content_types) != 1
        or content_types[0].split(";", 1)[0].strip().casefold()
        != "application/json"
    ):
        raise _MutationRequestBoundaryError(
            f"{surface} requires exactly one Content-Type application/json",
            status=415,
            drain_body=True,
        )

    if _header_values(handler, "Transfer-Encoding"):
        raise _MutationRequestBoundaryError(
            f"{surface} requires a bounded Content-Length, not Transfer-Encoding",
            status=400,
            drain_body=True,
        )
    lengths = _header_values(handler, "Content-Length")
    if len(lengths) != 1:
        raise _MutationRequestBoundaryError(
            f"{surface} requires exactly one bounded Content-Length",
            status=411 if not lengths else 400,
            drain_body=True,
        )
    raw_length = str(lengths[0]).strip()
    if (
        not raw_length.isascii()
        or not raw_length.isdecimal()
        or len(raw_length) > len(str(max_body_bytes))
    ):
        raise _MutationRequestBoundaryError(
            f"{surface} Content-Length must be a bounded decimal integer",
            status=400,
            drain_body=True,
        )
    length = int(raw_length)
    if length <= 0:
        raise _MutationRequestBoundaryError(
            f"{surface} JSON body must not be empty",
            status=400,
            drain_body=True,
        )
    if length > max_body_bytes:
        raise _MutationRequestBoundaryError(
            f"{surface} JSON body exceeds {max_body_bytes} bytes",
            status=413,
            drain_body=True,
        )
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise _MutationRequestBoundaryError(
            f"{surface} JSON body ended before Content-Length bytes",
            status=400,
        )
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_strict_json_object
        )
    except (json.JSONDecodeError, UnicodeDecodeError, _DuplicateJSONField) as exc:
        raise _MutationRequestBoundaryError(
            f"invalid JSON body: {exc}",
            status=400,
        ) from exc


def _validate_genesis_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _MutationRequestBoundaryError(
            "JSON body must be an object", status=400
        )
    allowed = {"prompt", "target", "stack", "request_key"}
    unexpected = sorted(str(key) for key in body if key not in allowed)
    if unexpected:
        raise _MutationRequestBoundaryError(
            "unknown Genesis fields: " + ", ".join(unexpected), status=400
        )
    for required in ("prompt", "request_key"):
        if not isinstance(body.get(required), str):
            raise _MutationRequestBoundaryError(
                f"{required} must be a string", status=400
            )
    for optional in ("target", "stack"):
        if (
            optional in body
            and body[optional] is not None
            and not isinstance(body[optional], str)
        ):
            raise _MutationRequestBoundaryError(
                f"{optional} must be a string", status=400
            )
    return body


def _validate_ariadne_body(body: Any) -> dict[str, str]:
    if not isinstance(body, dict):
        raise _MutationRequestBoundaryError(
            "Ariadne JSON body must be an object", status=400
        )
    allowed = frozenset(_ARIADNE_FIELDS)
    unexpected = sorted(str(key) for key in body if key not in allowed)
    if unexpected:
        raise _MutationRequestBoundaryError(
            "unknown Ariadne fields: " + ", ".join(unexpected), status=400
        )
    missing = sorted(field for field in _ARIADNE_FIELDS if field not in body)
    if missing:
        raise _MutationRequestBoundaryError(
            "missing Ariadne fields: " + ", ".join(missing), status=400
        )
    for field in _ARIADNE_FIELDS:
        if type(body[field]) is not str:
            raise _MutationRequestBoundaryError(
                f"{field} must be a string", status=400
            )
    return body


def _send_boundary_refusal(
    handler: Any,
    message: str,
    *,
    status: int,
    drain_body: bool = False,
) -> bool:
    body_drained = False
    if drain_body:
        drain = getattr(handler, "_drain_rejected_request_body", None)
        if callable(drain):
            body_drained = bool(drain())
    handler.close_connection = True
    handler._send_json({"ok": False, "error": message}, status=status)
    if drain_body and not body_drained:
        # Unsafe framing cannot be trusted for an exact read.  Flush the
        # already-decided refusal first, then discard only bytes which become
        # available inside a tiny bounded window.  This is transport hygiene,
        # not JSON parsing or effect admission.
        flush = getattr(getattr(handler, "wfile", None), "flush", None)
        if callable(flush):
            try:
                flush()
            except OSError:
                return False
        drain_available = getattr(
            handler, "_drain_available_rejected_request_body", None
        )
        if callable(drain_available):
            drain_available()
    return False


def preflight_post(handler: Any) -> bool:
    """Validate sensitive browser requests before ``web.mutations`` starts."""

    if hasattr(handler, _PREPARED_POST_BODY_ATTR):
        delattr(handler, _PREPARED_POST_BODY_ATTR)
    # Compatibility fakes used by outer response/error tests deliberately do
    # not model a request target.  Such callers have no sensitive route to
    # preflight and must retain the legacy dispatcher behavior.
    path = parse_request_target(getattr(handler, "path", "")).path
    if path not in _PREFLIGHT_POST_PATHS:
        return True

    from ...sensitivity import is_loopback_host

    client_host = str((handler.client_address or ("",))[0])
    server_host = str(
        getattr(handler.server, "server_address", ("", 0))[0]
    )
    if not is_loopback_host(client_host) or not is_loopback_host(server_host):
        refusal = (
            "Genesis preview is loopback-only"
            if path == "/api/genesis"
            else "Ariadne campaigns are loopback-only"
        )
        return _send_boundary_refusal(
            handler, refusal, status=403, drain_body=True
        )

    if path == "/api/genesis":
        origins = _header_values(handler, "Origin")
        if len(origins) > 1 or (
            origins and not same_origin_request(handler, origins[0])
        ):
            return _send_boundary_refusal(
                handler,
                "cross-origin Genesis requests are refused",
                status=403,
                drain_body=True,
            )
        surface = "Genesis"
    else:
        origins = _header_values(handler, "Origin")
        if len(origins) != 1 or not same_origin_request(handler, origins[0]):
            return _send_boundary_refusal(
                handler,
                "Ariadne campaigns require the exact numeric bound Origin",
                status=403,
                drain_body=True,
            )
        fetch_sites = _header_values(handler, "Sec-Fetch-Site")
        if len(fetch_sites) != 1 or fetch_sites[0].casefold() != "same-origin":
            return _send_boundary_refusal(
                handler,
                "Ariadne campaigns require Sec-Fetch-Site: same-origin",
                status=403,
                drain_body=True,
            )
        surface = "Ariadne"

    try:
        body = _read_bounded_json_body(handler, surface=surface)
        body = (
            _validate_genesis_body(body)
            if path == "/api/genesis"
            else _validate_ariadne_body(body)
        )
    except _MutationRequestBoundaryError as exc:
        return _send_boundary_refusal(
            handler,
            str(exc),
            status=exc.status,
            drain_body=exc.drain_body,
        )
    setattr(handler, _PREPARED_POST_BODY_ATTR, (path, body))
    return True


def _prepared_post_body(handler: Any, path: str) -> dict[str, Any]:
    prepared = getattr(handler, _PREPARED_POST_BODY_ATTR, None)
    if (
        not isinstance(prepared, tuple)
        or len(prepared) != 2
        or prepared[0] != path
        or not isinstance(prepared[1], dict)
    ):
        raise RuntimeError(f"{path} did not pass the HTTP mutation preflight")
    delattr(handler, _PREPARED_POST_BODY_ATTR)
    return prepared[1]


def handle_put(handler: Any, *, ports: EffectPorts) -> None:
    self = handler
    _read_body = ports.read_body
    _structure_index = ports.structure_index
    resolve_repo_root = ports.resolve_repo_root
    register_project = ports.register_project
    path = parse_request_target(self.path).path
    body = _read_body(self)
    parts = [unquote(p) for p in path.strip("/").split("/")]
    if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "team":
        self._send_json(hierarchy.save_team(parts[2], body))
        return
    if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "autonomy":
        self._send_json(control_plane.save_autonomy(parts[2], body))
        return
    if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "agents":
        repo_root = resolve_repo_root(None, parts[2])
        self._send_json(core.envelope(parts[2], path=str(agents_registry.update_role(parts[4], body, repo_root))))
        return
    if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "categories":
        repo_root = resolve_repo_root(None, parts[2])
        self._send_json(core.envelope(parts[2], path=str(categories.update(parts[4], body, repo_root))))
        return
    self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)


def handle_post(handler: Any, *, ports: EffectPorts) -> None:
    self = handler
    _read_body = ports.read_body
    _structure_index = ports.structure_index
    resolve_repo_root = ports.resolve_repo_root
    resolve_registered_project_root = ports.resolve_registered_project_root
    register_project = ports.register_project
    genesis_run = ports.genesis_run
    ariadne_run = ports.ariadne_run
    path = parse_request_target(self.path).path
    if path in _PREFLIGHT_POST_PATHS:
        body = _prepared_post_body(self, path)
    else:
        try:
            body = _read_body(self)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            if path == "/api/projects":
                self._send_json(
                    {"ok": False, "error": f"invalid JSON body: {exc}"},
                    status=400,
                )
                return
            raise
    if path == "/api/genesis":
        from ipaddress import ip_address

        from ...orchestration.genesis import GenesisConflictError
        try:
            result = genesis_run(
                body["prompt"],
                target=body.get("target"),
                stack=body.get("stack"),
                request_key=body["request_key"],
            )
        except GenesisConflictError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return
        except (TypeError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        preview = result.get("preview")
        if isinstance(preview, dict) and isinstance(preview.get("path"), str):
            server_host = str(
                getattr(self.server, "server_address", ("", 0))[0]
            )
            port = int(getattr(self.server, "server_address", ("", 0))[1])
            numeric_host = ip_address(server_host.strip().strip("[]"))
            authority = (
                f"[{numeric_host.compressed}]"
                if numeric_host.version == 6
                else numeric_host.compressed
            )
            result = {
                **result,
                "preview": {
                    **preview,
                    "url": f"http://{authority}:{port}{preview['path']}",
                },
            }
        self._send_json(core.envelope(None, genesis=result))
        return
    if path == "/api/ariadne":
        from ...ariadne import AriadneCampaignError, AriadneConflictError
        from ...spine.killswitch import LoopHalted

        try:
            repo_root = resolve_registered_project_root(body["project"])
            result = ariadne_run(
                repo_root=repo_root,
                source_revision=body["source_revision"],
                campaign_id=body["campaign_id"],
                target_path=body["target_path"],
                before=body["before"],
                after=body["after"],
            )
        except LoopHalted as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return
        except AriadneConflictError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return
        except (AriadneCampaignError, OSError, TypeError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(core.envelope(body["project"], ariadne=result))
        return
    if path == "/api/editor/contexts":
        if not isinstance(body, dict):
            self._send_json({"ok": False, "error": "JSON body must be an object"}, status=400)
            return
        try:
            context = editor_context.create_context(
                project=body.get("project"),
                source=body.get("source"),
                path=body.get("path"),
                selection=body.get("selection", ""),
                range=body.get("range"),
                diagnostics=body.get("diagnostics"),
                base_revision=body.get("base_revision"),
            )
        except editor_context.EditorContextError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(
            core.envelope(context["project"], context=context), status=201)
        return
    if path == "/api/editor/sessions":
        from ...sensitivity import is_loopback_host

        client_host = str((self.client_address or ("",))[0])
        if not is_loopback_host(client_host):
            self._send_json(
                {"ok": False, "error": "editor sessions are loopback-only"},
                status=403)
            return
        if not isinstance(body, dict):
            self._send_json({"ok": False, "error": "JSON body must be an object"}, status=400)
            return
        try:
            session = editor_context.SESSIONS.create(
                project=body.get("project"),
                adapter=body.get("adapter"),
                capabilities=body.get("capabilities"),
                base_revision=body.get("base_revision"),
            )
        except editor_context.EditorContextError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(core.envelope(session["project"], session=session), status=201)
        return
    if path.startswith("/api/editor/sessions/") and path.endswith("/commands"):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 5:
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        try:
            event = editor_context.SESSIONS.command(
                parts[3], self.headers.get("X-Daedalus-Editor-Token", ""),
                body.get("command") if isinstance(body, dict) else None,
                body.get("payload") if isinstance(body, dict) else None,
            )
        except editor_context.UnknownEditorSession as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        except editor_context.EditorContextError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(core.envelope(None, event=event), status=202)
        return
    if path.startswith("/api/conversations/") and path.endswith("/turns"):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 4 or parts[:2] != ["api", "conversations"]:
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        conversation_id = parts[2]
        try:
            status, created = conversation_requests.default_manager().create(
                conversation_id=conversation_id,
                client_request_id=body.get("client_request_id") if isinstance(body, dict) else None,
                project=body.get("project") if isinstance(body, dict) else None,
                message=body.get("message") if isinstance(body, dict) else None,
                provider=body.get("provider") if isinstance(body, dict) else None,
                model=body.get("model") if isinstance(body, dict) else None,
                effort=body.get("effort") if isinstance(body, dict) else None,
                context_refs=body.get("context_refs") if isinstance(body, dict) else None,
            )
        except conversation_requests.ConflictingConversationRequest as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=409)
            return
        except (ValueError, conversation_requests.ConversationRequestError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(
            core.envelope(
                status["project"], turn_request=status,
                created=created,
                status_url=f"/api/conversations/{conversation_id}/turns/{status['request_id']}",
                events_url=f"/api/conversations/{conversation_id}/turns/{status['request_id']}/events",
            ),
            status=202 if created else 200,
        )
        return
    if (path.startswith("/api/conversations/")
            and path.endswith("/cancel-requests") and "/turns/" in path):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 6 or parts[:2] != ["api", "conversations"] or parts[3] != "turns":
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        conversation_id = parts[2]
        try:
            request_id = int(parts[4])
            manager = conversation_requests.default_manager()
            current = manager.status(request_id)
            if current["conversation_id"] != conversation_id:
                raise conversation_requests.UnknownConversationRequest(str(request_id))
            cancellation = manager.cancel(
                request_id,
                client_cancel_id=(body.get("client_cancel_id")
                                  if isinstance(body, dict) else None),
            )
        except (ValueError, conversation_requests.UnknownConversationRequest) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        except conversation_requests.ConversationRequestError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(core.envelope(None, cancellation=cancellation), status=202)
        return
    if path == "/api/projects":
        if not isinstance(body, dict):
            self._send_json({"ok": False, "error": "JSON body must be an object"}, status=400)
            return
        try:
            registered = register_project(
                body.get("repo_root"), body.get("name")
            )
        except ProjectRegistrationError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except ProjectRegistryUnavailable as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=503)
            return
        self._send_json(core.envelope(
            registered["name"],
            registered_project={
                "name": registered["name"],
                "repo_root": registered["repo_root"],
            },
            created=registered["created"],
        ), status=201 if registered["created"] else 200)
        return
    if path == "/api/queue":
        project = str(body.get("project") or "")
        objective = str(body.get("objective") or "").strip()
        if not project or not objective:
            self._send_json({"ok": False, "error": "project and objective are required"}, status=400)
            return
        # Durable chat attribution is an exact pair. Never infer "the
        # latest turn": an older offer can be clicked after a newer reply,
        # and concurrent completions make recency inherently ambiguous.
        conversation_id = str(body.get("conversation_id") or "").strip() or None
        raw_turn_id = body.get("turn_id")
        linked_turn_id: int | None = None
        if conversation_id is not None:
            if type(raw_turn_id) is not int or raw_turn_id <= 0:
                self._send_json({
                    "ok": False,
                    "error": "conversation_id requires an explicit positive turn_id",
                }, status=400)
                return
            linked_turn_id = raw_turn_id
        elif raw_turn_id is not None:
            self._send_json({
                "ok": False,
                "error": "turn_id requires conversation_id",
            }, status=400)
            return
        result = core.queue_task(
            project,
            objective,
            lane=str(body.get("lane") or "local_only"),
            source=str(body.get("source") or "webapp"),
            strategy=str(body.get("strategy") or "single"),
            paths=[str(p) for p in body.get("paths") or []],
        )
        # `queued` is a filesystem path -- an implementation detail. `id`
        # is that same request's filename stem: the exact key file_bridge
        # itself uses to find the eventual report, and the only id
        # GET /api/queue/<id> (and its /artifacts, /events siblings)
        # accept. Purely additive: `queued` is unchanged, so existing
        # callers see no difference.
        task_id = Path(str(result.get("queued") or "")).stem or None
        result["id"] = task_id
        # Optional: attribute this dispatch to the exact conversation turn
        # that proposed it. The pair was validated before enqueue; a link
        # failure after the queue write is reported rather than pretending
        # the already-published task did not happen.
        if task_id and conversation_id:
            try:
                from ...orchestration import conversation as conv

                link = conv.default_store().link_dispatch(
                    str(conversation_id), task_id,
                    turn_id=linked_turn_id,
                    kind="queue_task")
                link_view = {
                    "conversation_id": link.conversation_id,
                    "turn_id": link.turn_id, "dispatch_ref": link.dispatch_ref,
                    "linked": True}
                result["conversation_link"] = link_view
                # Close the narrow enqueue->link race through the REPORT
                # OWNER. A very fast watcher may have atomically published
                # and archived the terminal report before this link became
                # visible. Reconciliation reads only that fixed report and
                # uses the same source_event_id as process_request, so a
                # concurrent normal projection still yields one spine fact.
                try:
                    projected = file_bridge.reconcile_conversation_report(task_id)
                    if projected is None:
                        link_view["projection"] = {"state": "awaiting_report"}
                    else:
                        link_view["projection"] = {
                            "state": "reported", "event_id": projected.id,
                            "outcome_state": projected.outcome_state,
                        }
                except file_bridge.ConversationProjectionPending as exc:
                    # Linking succeeded. Do not rewrite that fact as false
                    # merely because its informational outcome projection
                    # needs the report-owner's idempotent retry.
                    link_view["projection_pending"] = True
                    link_view["projection_retry_queued"] = bool(exc.retry_queued)
                    link_view["projection"] = {
                        "state": "pending",
                        "error": f"{type(exc.cause).__name__}: {exc.cause}",
                    }
                except Exception as exc:
                    # A malformed/mismatched terminal artifact is also
                    # separate from whether the dispatch link was recorded.
                    link_view["projection"] = {
                        "state": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            except Exception as exc:
                result["conversation_link"] = {
                    "conversation_id": str(conversation_id), "linked": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        self._send_json(result)
        return
    if path == "/api/conversations":
        # Mint only -- see daedalus.orchestration.conversation.new_conversation_id: pure
        # id generation, no store write. The modern request endpoint's atomic
        # generation INSERT claims the project; its resulting append_turn makes
        # the conversation readable. Legacy /api/ikarus/ask may resume only an
        # already exactly-bound id and therefore cannot claim this fresh id.
        from ...orchestration import conversation as conv

        self._send_json(core.envelope(None, conversation_id=conv.new_conversation_id()))
        return
    if path == "/api/ikarus/chat":
        project = str(body.get("project") or "")
        message = str(body.get("message") or "").strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        self._send_json(ikarus_chat.chat(project, message, apply=bool(body.get("apply"))))
        return
    if path == "/api/ikarus/ask":
        project = str(body.get("project") or "")
        message = str(body.get("message") or "").strip()
        if not project or not message:
            self._send_json({"ok": False, "error": "project and message are required"}, status=400)
            return
        raw_conversation_id = body.get("conversation_id")
        conversation_id = (
            None if raw_conversation_id is None else str(raw_conversation_id)
        )
        if conversation_id is not None:
            from ...orchestration import conversation as conv

            try:
                conv.default_store().require_project_binding(
                    conversation_id, project
                )
            except conv.ConversationProjectConflict as exc:
                self._send_json(
                    {
                        "ok": False,
                        "error": str(exc),
                        "code": "conversation_project_conflict",
                    },
                    status=409,
                )
                return
        provider = body.get("provider")
        model = body.get("model")
        effort = body.get("effort")
        self._send_json(ikarus_os.ask(
            project, message,
            provider=str(provider) if provider else None,
            model=str(model) if model else None,
            effort=str(effort) if effort else None,
            conversation_id=conversation_id,
        ))
        return
    if path.startswith("/api/drafts/") and (
            path.endswith("/handoff") or path.endswith("/apply")
            or path.endswith("/dismiss")):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        draft_id, verb = parts[2], parts[3]
        if verb in {"handoff", "apply"}:
            packet = drafts.handoff_payload(draft_id)
            payload = core.envelope(
                None,
                handoff=packet,
                draft_status="handed_off",
                repository_changed=False,
            ) if packet else None
            if payload is not None and verb == "apply":
                payload["deprecated_endpoint"] = "/api/drafts/<id>/apply"
                payload["replacement_endpoint"] = "/api/drafts/<id>/handoff"
            self._send_json(payload if payload is not None else
                            {"ok": False, "error": f"unknown draft {draft_id}"},
                            status=200 if packet else 404)
        else:
            d = drafts.set_status(draft_id, "dismissed")
            self._send_json(core.envelope(None, draft=d) if d else
                            {"ok": False, "error": f"unknown draft {draft_id}"},
                            status=200 if d else 404)
        return
    if path.startswith("/api/runtimes/") and path.endswith("/test"):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) == 4:
            self._send_json(core.envelope(None, test=runtime_registry.test_runtime(parts[2])))
            return
    if path == "/api/distill":
        project = str(body.get("project") or "")
        target = str(body.get("target") or "").strip()
        if not project or not target:
            self._send_json({"ok": False, "error": "project and target are required"}, status=400)
            return
        repo_root = resolve_repo_root(None, project)
        idx = _structure_index(project)
        try:
            res = semantic_slice(repo_root, target, idx=idx)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        res["slice_text"] = res["slice_text"][:20000]
        self._send_json(core.envelope(project, distill=res))
        return
    self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
