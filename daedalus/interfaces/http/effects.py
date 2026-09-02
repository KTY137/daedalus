"""Mutation route dispatch behind the registered legacy effect facade."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from ...kairos import drafts
from ... import core, file_bridge, ikarus_os
from ...orchestration import agents_registry, categories, control_plane, conversation_requests, editor_context, hierarchy, ikarus_chat, runtime_registry
from ...foundation.projects import (
    ProjectRegistrationError,
    ProjectRegistryUnavailable,
)
from ...structcore.slice import semantic_slice
from .router import parse_request_target

EffectPort = Callable[..., Any]


@dataclass(frozen=True)
class EffectPorts:
    """Legacy-owned seams whose monkeypatch and target identity must survive."""

    read_body: EffectPort
    structure_index: EffectPort
    resolve_repo_root: EffectPort
    register_project: EffectPort


def read_body(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


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
    register_project = ports.register_project
    path = parse_request_target(self.path).path
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
        # id generation, no store write. The row is created lazily by the
        # FIRST append_turn (via POST /api/ikarus/ask's conversation_id),
        # so this never leaves a conversation-shaped id with no turns
        # behind it that GET /api/conversations/<id> would 404 on forever.
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
        provider = body.get("provider")
        model = body.get("model")
        effort = body.get("effort")
        conversation_id = body.get("conversation_id")
        self._send_json(ikarus_os.ask(
            project, message,
            provider=str(provider) if provider else None,
            model=str(model) if model else None,
            effort=str(effort) if effort else None,
            conversation_id=str(conversation_id) if conversation_id else None,
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
