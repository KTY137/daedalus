"""Read-only HTTP route dispatch behind the legacy web facade."""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
from typing import Any, Callable, Pattern
from urllib.parse import quote, unquote

from ...kairos import drafts
from ... import core
from ...foundation import accelerators
from ...orchestration import control_plane, conversation_requests, editor_context, hierarchy, runtime_registry
from .bootstrap_prompt import claude_bootstrap_prompt
from ...orchestration.context_plan import plan_context
from ...foundation.env import env_status
from ...structcore.churn import co_change_pairs
from ...structcore.report import structure_summary
from ...structcore.topology import spectral_partition
from ...twin.read_projection import fourfold_read_projection
from ... import memory as memory_mod
from .router import parse_request_target

RoutePort = Callable[..., Any]


@dataclass(frozen=True)
class ReadPorts:
    """Legacy-owned helpers injected across the first strangler seam."""

    clip: RoutePort
    conversation_view: RoutePort
    conversation_list_view: RoutePort
    dispatch_status_view: RoutePort
    host_capabilities: RoutePort
    loop_architecture: RoutePort
    loop_attempts: RoutePort
    loop_limit: RoutePort
    loop_queue: RoutePort
    project_list: RoutePort
    provider_status: RoutePort
    structure_index: RoutePort
    task_artifacts: RoutePort
    task_snapshot: RoutePort
    resolve_repo_root: RoutePort
    genesis_preview: RoutePort
    genesis_preview_capability: RoutePort
    genesis_source_archive: RoutePort
    conversation_id_re: Pattern[str]
    task_id_re: Pattern[str]
    loop_max_limit: int


def _graph_node_limit(
    query: dict[str, list[str]], *, default: int
) -> tuple[int | None, bool]:
    """Read the explicit graph scope without silently treating bad input as a cap."""

    raw = (query.get("graph_nodes") or [""])[0].strip().lower()
    if not raw:
        return default, False
    if raw == "all":
        return None, True
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(
            "graph_nodes must be a positive integer or 'all'"
        ) from exc
    if limit < 1:
        raise ValueError("graph_nodes must be a positive integer or 'all'")
    return limit, True


def handle_get(handler: Any, *, ports: ReadPorts) -> None:
    self = handler
    _clip = ports.clip
    _conversation_view = ports.conversation_view
    _conversation_list_view = ports.conversation_list_view
    _dispatch_status_view = ports.dispatch_status_view
    _host_capabilities = ports.host_capabilities
    _loop_architecture = ports.loop_architecture
    _loop_attempts = ports.loop_attempts
    _loop_limit = ports.loop_limit
    _loop_queue = ports.loop_queue
    _project_list = ports.project_list
    _provider_status = ports.provider_status
    _structure_index = ports.structure_index
    _task_artifacts = ports.task_artifacts
    _task_snapshot = ports.task_snapshot
    resolve_repo_root = ports.resolve_repo_root
    genesis_preview = ports.genesis_preview
    genesis_preview_capability = ports.genesis_preview_capability
    _CONVERSATION_ID_RE = ports.conversation_id_re
    _TASK_ID_RE = ports.task_id_re
    LOOP_MAX_LIMIT = ports.loop_max_limit
    target = parse_request_target(self.path)
    qs = target.query
    path = target.path
    if path.startswith("/api/genesis/"):
        from ipaddress import ip_address

        from ...sensitivity import is_loopback_host

        client_host = str((self.client_address or ("",))[0])
        server_address = getattr(self.server, "server_address", ("", 0))
        server_host = str(server_address[0])
        if not is_loopback_host(client_host) or not is_loopback_host(server_host):
            self._send_json(
                {"ok": False, "error": "Genesis preview is loopback-only"},
                status=403,
            )
            return
        numeric_host = ip_address(server_host.strip().strip("[]"))
        csp_host = (
            f"[{numeric_host.compressed}]"
            if numeric_host.version == 6
            else numeric_host.compressed
        )
        preview_origin = f"http://{csp_host}:{int(server_address[1])}"
        expected_host = f"{csp_host}:{int(server_address[1])}"
        host_headers = self.headers.get_all("Host") or []
        if len(host_headers) != 1 or str(host_headers[0]) != expected_host:
            self._send_json(
                {
                    "ok": False,
                    "error": "Genesis preview requires its exact numeric bound Host",
                },
                status=403,
            )
            return
        fetch_sites = self.headers.get_all("Sec-Fetch-Site") or []
        if len(fetch_sites) != 1 or str(fetch_sites[0]).casefold() not in {
            "same-origin",
            "same-site",
            "none",
            "cross-site",
        }:
            self._send_json(
                {
                    "ok": False,
                    "error": "Genesis preview requires valid Sec-Fetch-Site metadata",
                },
                status=403,
            )
            return
        fetch_site = str(fetch_sites[0]).casefold()
        parts = path.split("/")
        if len(parts) == 5 and parts[4] == "source.zip":
            # Only the cockpit's same-origin fetch may read an entire source
            # archive. Preview bearer paths never grant this broader read.
            origins = self.headers.get_all("Origin") or []
            if fetch_site != "same-origin" or (
                origins and (len(origins) != 1 or str(origins[0]) != preview_origin)
            ):
                self._send_json(
                    {"ok": False, "error": "Genesis source download requires same-origin metadata"},
                    status=403,
                )
                return
            run_id = parts[3]
            if not re.fullmatch(r"genesis-[0-9a-f]{24}", run_id):
                self._send_json(
                    {"ok": False, "error": "Genesis source run id is invalid"},
                    status=404,
                )
                return
            digests = qs.get("candidate_sha256", [])
            if (
                set(qs) != {"candidate_sha256"}
                or len(digests) != 1
                or not re.fullmatch(r"[0-9a-f]{64}", digests[0])
                or self.path != f"{path}?candidate_sha256={digests[0]}"
            ):
                self._send_json(
                    {"ok": False, "error": "Genesis source download requires one exact candidate_sha256"},
                    status=400,
                )
                return
            try:
                payload = ports.genesis_source_archive(run_id, digests[0])
            except Exception as exc:
                from ...orchestration.genesis import GenesisPreviewError

                if not isinstance(exc, GenesisPreviewError):
                    raise
                self._send_json({"ok": False, "error": str(exc)}, status=404)
                return
            self._send_response_bytes(
                payload,
                content_type="application/zip",
                headers=(
                    ("Content-Disposition", f'attachment; filename="{run_id}-source.zip"'),
                    ("Cache-Control", "private, no-store"),
                    ("Referrer-Policy", "no-referrer"),
                    ("Cross-Origin-Resource-Policy", "same-origin"),
                    ("Content-Security-Policy", "default-src 'none'; sandbox"),
                    ("X-Daedalus-Candidate-Sha256", digests[0]),
                ),
            )
            return
        if (
            len(parts) < 5
            or parts[1:3] != ["api", "genesis"]
            or unquote(parts[4]) != "preview"
        ):
            self._send_json(
                {"ok": False, "error": f"unknown endpoint {path}"}, status=404
            )
            return
        run_id = unquote(parts[3])
        if not re.fullmatch(r"genesis-[0-9a-f]{24}", run_id):
            self._send_json(
                {"ok": False, "error": "Genesis preview run id is invalid"},
                status=404,
            )
            return
        canonical_scope = f"/api/genesis/{quote(run_id, safe='')}/preview/"
        if not path.startswith(canonical_scope):
            self._send_json(
                {"ok": False, "error": f"unknown endpoint {path}"}, status=404
            )
            return
        expected_capability = genesis_preview_capability(run_id)
        capability_segment = f"~cap-{expected_capability}"
        tail = path[len(canonical_scope):]
        first_segment, separator, remainder = tail.partition("/")
        supplied_capability = (
            first_segment[len("~cap-"):]
            if first_segment.startswith("~cap-")
            else None
        )
        if supplied_capability is None:
            # Fetch Metadata is a browser-controlled header. A foreign page's
            # script/img/frame request must not be allowed to mint the bearer
            # path. Direct navigation and the same-origin cockpit may mint it.
            if fetch_site not in {"same-origin", "none"}:
                self._send_json(
                    {
                        "ok": False,
                        "error": "cross-origin Genesis preview requests are refused",
                    },
                    status=403,
                )
                return
            location = canonical_scope + capability_segment + "/" + tail
            self._send_response_bytes(
                b"",
                status=307,
                headers=(
                    ("Location", location),
                    ("Cache-Control", "private, no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
            return
        if (
            not separator
            or not re.fullmatch(r"[0-9a-f]{64}", supplied_capability)
            or not hmac.compare_digest(supplied_capability, expected_capability)
        ):
            self._send_json(
                {"ok": False, "error": "Genesis preview capability is invalid"},
                status=404,
            )
            return
        preview_scope = f"{preview_origin}{canonical_scope}{capability_segment}/"
        relative_path = "/".join(unquote(part) for part in remainder.split("/"))
        try:
            payload, media_type = genesis_preview(run_id, relative_path)
        except Exception as exc:
            from ...orchestration.genesis import GenesisPreviewError

            if not isinstance(exc, GenesisPreviewError):
                raise
            message = str(exc)
            invalid = "invalid" in message or "not safe" in message
            self._send_json(
                {"ok": False, "error": message}, status=400 if invalid else 404
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'none'; script-src {preview_scope}; "
            f"style-src {preview_scope}; img-src {preview_scope} data:; "
            "connect-src 'none'; worker-src 'none'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'self'; sandbox allow-scripts allow-forms",
        )
        self.end_headers()
        self.wfile.write(payload)
        return
    if path == "/api/host/capabilities":
        self._send_json(core.envelope(
            None, host_capabilities=_host_capabilities()))
    elif path.startswith("/api/editor/contexts/"):
        context_ref = unquote(path[len("/api/editor/contexts/"):])
        try:
            context = editor_context.get_context(context_ref)
        except editor_context.UnknownEditorContext as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        self._send_json(core.envelope(context.get("project"), context=context))
    elif path.startswith("/api/editor/sessions/") and path.endswith("/events"):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 5:
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        try:
            after = int((qs.get("after") or ["0"])[0])
            wait_s = float((qs.get("wait_s") or ["0"])[0])
            rows = editor_context.SESSIONS.events(
                parts[3], self.headers.get("X-Daedalus-Editor-Token", ""),
                after=after, wait_s=wait_s)
        except editor_context.UnknownEditorSession as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        except (ValueError, editor_context.EditorContextError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self._send_json(core.envelope(None, events=rows))
    elif path == "/api/desktop-ready":
        nonce = getattr(self.server, "daedalus_desktop_startup_nonce", "") or ""
        if not nonce:
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        self._send_json({
            "schema": "daedalus-desktop-startup/1",
            "ready": True,
            "nonce": nonce,
        })
    elif path == "/api/dashboard":
        self._send_json(core.get_dashboard((qs.get("project") or [None])[0]))
    elif path == "/api/governance":
        # "May this system promote anything right now, and why not?"
        # Byte-identical to dashboard["governance"] -- same function, no
        # second opinion. tests/test_ui_governance.py pins that equality.
        self._send_json(core.get_governance((qs.get("project") or [None])[0]))
    elif path == "/api/projects":
        self._send_json(_project_list())
    elif path.startswith("/api/projects/") and path.endswith("/hierarchy"):
        project = unquote(path.split("/")[3])
        self._send_json(hierarchy.hierarchy(project))
    elif path.startswith("/api/projects/") and path.endswith("/control-plane"):
        project = unquote(path.split("/")[3])
        self._send_json(control_plane.unified_profiles(project))
    elif path.startswith("/api/projects/") and path.endswith("/bootstrap/claude"):
        project = unquote(path.split("/")[3])
        bootstrap = claude_bootstrap_prompt(project)
        self._send_json(core.envelope(project, prompt=bootstrap["prompt"]))
    elif path == "/api/providers/status":
        self._send_json(_provider_status())
    elif path == "/api/runtimes/status":
        # Cached, and every row says WHEN it was probed. Launching each CLI
        # for its --version makes this call slow by construction and slower
        # with use (owner decision 2026-08-27); the cache stops the relaunch
        # per poll, and measured_at/measured_age_s keep a cached "erreichbar"
        # from lying about a CLI that broke since. The surface shows the age.
        self._send_json(
            core.envelope(None, **runtime_registry.all_status(use_cache=True))
        )
    elif path == "/api/accelerators/status":
        deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
        probe_remote = (
            (qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes")
        )
        self._send_json(
            core.envelope(
                None,
                accelerators=accelerators.accelerator_status(
                    deep=deep,
                    probe_remote=probe_remote,
                ),
            )
        )
    elif path == "/api/env/status":
        self._send_json(core.envelope(None, env=env_status()))
    elif path == "/api/capabilities":
        self._send_json(hierarchy.capabilities())
    elif path == "/api/catalogue":
        # GET /api/catalogue -> daedalus.orchestration.gui_catalogue: the
        # parts a GUI can be built from, as DATA. This is the only reader of
        # that module inside the package; tools/smoke_packaged_resources.py is
        # the other caller. docs/GUI_CATALOGUE.md is the contract.
        #
        # PURE READ, deliberately. load_catalogue() only read_text()s
        # catalogue/gui/*.json, and ranking is the repo's existing BM25 via
        # gui_catalogue.search(). The LATENT half is NOT exposed here: it
        # would open the vector store, and do_GET carries no
        # effect_boundary row (unlike do_POST/do_PUT, which call
        # begin_effect). A GET that opened a store would be an undeclared
        # effect, so `use_latent` stays False and is not a query parameter.
        #
        # `rejected` rides along with `entries` because the refusal path is
        # the point of this module: a reader must see what was REFUSED and
        # why, not just what was admitted. Every row carries `licence` and
        # the code-derived `use_mode`, so no caller ever sees a component
        # without seeing whether its licence lets them copy it.
        query = (qs.get("q") or [""])[0].strip()
        if len(query) > 2000:
            self._send_json(
                {"ok": False, "error": "q must be at most 2000 characters"},
                status=400,
            )
            return
        try:
            limit = int((qs.get("limit") or ["8"])[0])
        except ValueError:
            self._send_json(
                {"ok": False, "error": "limit must be an integer"},
                status=400,
            )
            return
        if not 1 <= limit <= 100:
            self._send_json(
                {"ok": False, "error": "limit must be between 1 and 100"},
                status=400,
            )
            return
        from ...orchestration import gui_catalogue

        catalogue = gui_catalogue.load_catalogue()
        payload: dict[str, Any] = {"catalogue": catalogue.to_dict()}
        if query:
            # Ranked names + the ranking receipt. The caller resolves each
            # hit against `catalogue.entries`, which it already has.
            payload["search"] = gui_catalogue.search(
                catalogue, query, limit=limit, use_latent=False,
            ).to_dict()
        self._send_json(core.envelope(None, **payload))
    elif path == "/api/events":
        self._handle_events((qs.get("project") or [None])[0])
    elif path == "/api/ikarus/stream":
        self._handle_ikarus_stream(qs)
    elif path == "/api/fourfold":
        project = (qs.get("project") or [None])[0]
        if not project:
            self._send_json({"ok": False, "error": "project is required"}, status=400)
            return
        refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
        try:
            graph_nodes, _explicit_scope = _graph_node_limit(qs, default=800)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        # This is a read projection of the canonical legacy Forest adapter.
        # The richer index has a distinct cache scope, so opening Fourfold
        # cannot change the code-only structure baseline.
        idx = _structure_index(project, refresh, fourfold=True)
        self._send_json(core.envelope(
            project,
            fourfold=fourfold_read_projection(
                idx,
                repository_id=project,
                created_at=core.now_iso(),
                max_nodes=graph_nodes,
            ),
        ))
    elif path == "/api/structure":
        project = (qs.get("project") or [None])[0]
        if not project:
            self._send_json({"ok": False, "error": "project is required"}, status=400)
            return
        refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
        idx = _structure_index(project, refresh)
        try:
            graph_nodes, explicit_scope = _graph_node_limit(qs, default=2000)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        graph_edges: int | None = 8000
        if explicit_scope:
            # When the owner explicitly chooses a node projection, include
            # every edge whose endpoints are in it. Otherwise an `all`
            # node view could still be an 8000-edge partial graph.
            graph_edges = None
        self._send_json(core.envelope(
            project,
            structure=structure_summary(
                idx,
                max_graph_nodes=graph_nodes,
                max_graph_edges=graph_edges,
            ),
        ))
    elif path == "/api/topology":
        project = (qs.get("project") or [None])[0]
        if not project:
            self._send_json({"ok": False, "error": "project is required"}, status=400)
            return
        repo_root = resolve_repo_root(None, project)
        refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
        # Reuse the same center/ignore-scoped index as /api/structure.
        topo = spectral_partition(repo_root, idx=_structure_index(project, refresh))
        self._send_json(core.envelope(project, topology=topo))
    elif path == "/api/context/plan":
        project = (qs.get("project") or [None])[0]
        objective = (qs.get("q") or [""])[0].strip()
        if not project:
            self._send_json(
                {"ok": False, "error": "project is required"},
                status=400,
            )
            return
        if not objective:
            self._send_json(
                {"ok": False, "error": "q is required"},
                status=400,
            )
            return
        if len(objective) > 4000:
            self._send_json(
                {"ok": False, "error": "q must be at most 4000 characters"},
                status=400,
            )
            return
        try:
            max_tokens = int((qs.get("max_tokens") or ["8000"])[0])
        except ValueError:
            self._send_json(
                {"ok": False, "error": "max_tokens must be an integer"},
                status=400,
            )
            return
        if not 1 <= max_tokens <= 200_000:
            self._send_json(
                {
                    "ok": False,
                    "error": "max_tokens must be between 1 and 200000",
                },
                status=400,
            )
            return
        refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
        use_latent = (qs.get("latent") or ["0"])[0] in ("1", "true", "yes")
        use_cochange = (
            (qs.get("cochange") or ["0"])[0] in ("1", "true", "yes")
        )
        repo_root = resolve_repo_root(None, project)
        result = plan_context(
            repo_root,
            objective,
            idx=_structure_index(project, refresh),
            project=project,
            token_budget=max_tokens,
            use_latent=use_latent,
            temporal_pairs=(
                co_change_pairs(repo_root) if use_cochange else ()
            ),
        )
        self._send_json(
            core.envelope(project, context_plan=result.to_dict())
        )
    elif path == "/api/latent/search":
        query = (qs.get("q") or [""])[0].strip()
        try:
            limit = int((qs.get("limit") or ["5"])[0])
        except ValueError:
            self._send_json({"ok": False, "error": "limit must be an integer"}, status=400)
            return
        if not 1 <= limit <= 100:
            self._send_json({"ok": False, "error": "limit must be between 1 and 100"}, status=400)
            return
        metric = (qs.get("metric") or ["cosine"])[0]
        if not query:
            self._send_json({"ok": False, "error": "q is required"}, status=400)
            return
        if len(query) > 2000:
            self._send_json({"ok": False, "error": "q must be at most 2000 characters"}, status=400)
            return
        if metric != "cosine":
            self._send_json(
                {"ok": False, "error": "only cosine search is supported"},
                status=400,
            )
            return
        try:
            from ...memory import VECTOR_DB_PATH
            from ...memory.embeddings import EventVectorStore

            store = EventVectorStore(VECTOR_DB_PATH)
            try:
                results = store.search(query, limit=limit, metric=metric)
                hits = [
                    {"event": ev.to_dict(), "score": round(score, 4)}
                    for ev, score in results
                ]
            finally:
                store.close()
            self._send_json(core.envelope(None, results=hits, query=query))
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
    elif path == "/api/events/memory":
        try:
            limit = int((qs.get("limit") or ["50"])[0])
        except ValueError:
            self._send_json({"ok": False, "error": "limit must be an integer"}, status=400)
            return
        if not 1 <= limit <= 1000:
            self._send_json({"ok": False, "error": "limit must be between 1 and 1000"}, status=400)
            return
        events = memory_mod.load_events()[-limit:]
        self._send_json(core.envelope(None, events=events))
    elif path == "/api/loop/queue":
        try:
            limit = _loop_limit(qs, 10)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        project = (qs.get("project") or [None])[0]
        try:
            self._send_json(_loop_queue(project, limit))
        except ValueError as exc:  # unknown / malformed project
            self._send_json({"ok": False, "error": str(exc)}, status=400)
    elif path == "/api/loop/attempts":
        try:
            limit = _loop_limit(qs, 20)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        from ...spine import picker as _picker

        kind = (qs.get("kind") or [_picker.ATTEMPT_INTENT_KIND])[0]
        # "every kind" has to be asked for by name; defaulting to it would
        # widen what this endpoint returns every time a new intent kind is
        # recorded anywhere in the system.
        kind = None if kind == "all" else _clip(kind, 200)
        task_id = _clip((qs.get("task_id") or [""])[0], 200)
        self._send_json(_loop_attempts(kind, limit, task_id))
    elif path == "/api/loop/architecture":
        project = (qs.get("project") or [None])[0]
        try:
            self._send_json(_loop_architecture(project))
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
    elif path == "/api/health":
        # The health surface has fourteen probes and a five-state vocabulary
        # that deliberately cannot collapse into green, plus a MEASURED /
        # INHERITED / ASSUMED tag on every fact. None of it was reachable
        # from the UI, so the browser was re-deriving a weaker version of
        # the same judgement from other payloads. One endpoint, and the
        # provenance travels with the verdict.
        #
        # `deep` and `probe_remote` are OFF unless asked for: the first
        # calls the latent route (~7s cold) and the second embeds against a
        # host that is not this machine. A browser tab must not be able to
        # start either by accident, and the response says which were skipped
        # rather than letting `present` read as `working`.
        try:
            from ... import health as _health

            deep = (qs.get("deep") or ["0"])[0] in ("1", "true", "yes")
            remote = (qs.get("probe_remote") or ["0"])[0] in ("1", "true", "yes")
            only = _clip((qs.get("only") or [""])[0], 100) or None
            payload = _health.to_payload(
                _health.assess(only, deep=deep, probe_remote=remote))
            payload["asked"] = {"deep": deep, "probe_remote": remote,
                                "only": only}
            self._send_json(core.envelope(None, health=payload))
        except Exception as exc:                 # noqa: BLE001
            # A health surface that 500s tells the operator nothing about
            # the system and everything about itself -- so say which.
            self._send_json(
                {"ok": False,
                 "error": f"the health surface itself failed: "
                          f"{type(exc).__name__}: {exc}",
                 "health": None}, status=500)
    elif path == "/api/drafts":
        # SCOPED, AND IT SAYS WHICH SCOPE IT USED.
        #
        # The drafts store is one directory shared by every project, and
        # this route used to return all of it under whichever project the
        # cockpit had selected. `scope` is in the response so the surface
        # can never present an unscoped count as a project's own: null
        # means "every project", a path means "only this repository".
        project = (qs.get("project") or [None])[0]
        root, perr = "", ""
        if project:
            try:
                from ...foundation.projects import load_project

                root = str(load_project(project).get("repo_root") or "")
            except ValueError as exc:
                perr = str(exc)
        warnings = []
        if project and not root:
            # Named a project we cannot resolve to a tree. Returning
            # everything here would be the silent failure toward MORE data
            # under a narrower name -- refuse to guess, and say so.
            warnings.append(perr or f"unknown project '{project}'; no drafts could be scoped to it")
            rows = []
        else:
            rows = drafts.list_drafts(root or None)
        pending = [d for d in rows if d.get("status") == "pending"]
        self._send_json(core.envelope(
            project, drafts=rows, pending_count=len(pending),
            scope=root or None, warnings=warnings))
    elif path.startswith("/api/drafts/"):
        draft_id = unquote(path.split("/", 3)[3])
        d = drafts.get_draft(draft_id)
        self._send_json(core.envelope(None, draft=d) if d else
                        {"ok": False, "error": f"unknown draft {draft_id}"}, status=200 if d else 404)
    elif path.startswith("/api/queue/"):
        # /api/queue/<id>              GET  -> one snapshot (see _task_snapshot)
        # /api/queue/<id>/artifacts    GET  -> what a finished run produced
        # /api/queue/<id>/events       GET  -> SSE progress, one-shot
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) not in (3, 4):
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        task_id = parts[2]
        if not _TASK_ID_RE.match(task_id):
            self._send_json({"ok": False, "error": "invalid task id"}, status=400)
            return
        if len(parts) == 3:
            snap = _task_snapshot(task_id)
            if snap["found"]:
                # Read-only, additive: what a conversation turn recorded
                # about this dispatch, if any ever linked it. None is the
                # normal case for anything queued without a
                # conversation_id. See the "conversation + progress
                # seam" section for why this can lag the `task` block
                # above, which stays the live ground truth regardless.
                snap["conversation_dispatch"] = _dispatch_status_view(task_id)
            self._send_json(
                core.envelope(None, task=snap) if snap["found"] else
                {"ok": False, "error": f"unknown task id {task_id}", "task": snap},
                status=200 if snap["found"] else 404)
            return
        sub = parts[3]
        if sub == "artifacts":
            art = _task_artifacts(task_id)
            if not art.get("found"):
                self._send_json({"ok": False, "error": f"unknown task id {task_id}"}, status=404)
                return
            self._send_json(core.envelope(None, artifacts=art))
            return
        if sub == "events":
            self._handle_task_events(task_id)
            return
        self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
    elif path == "/api/conversations":
        # GET /api/conversations?project=&limit= -> this project's threads,
        # newest first, read from the canonical spine (_conversation_list_view).
        # Listing is a read; minting stays on POST and existence on the first
        # appended turn.
        project = ((qs.get("project") or [""])[0] or "").strip()
        if not project:
            self._send_json({"ok": False, "error": "project is required"}, status=400)
            return
        try:
            limit = _loop_limit(qs, 20)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        try:
            rows = _conversation_list_view(project, limit=limit)
        except Exception as exc:
            self._send_json(
                {"ok": False,
                 "error": f"the conversation store failed: {type(exc).__name__}: {exc}"},
                status=500)
            return
        self._send_json(core.envelope(project, conversations=rows))
    elif path.startswith("/api/conversations/") and "/turns/" in path:
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) not in {5, 6} or parts[:2] != ["api", "conversations"] or parts[3] != "turns":
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        conversation_id = parts[2]
        if not _CONVERSATION_ID_RE.match(conversation_id):
            self._send_json({"ok": False, "error": "invalid conversation id"}, status=400)
            return
        try:
            request_id = int(parts[4])
            status = conversation_requests.default_manager().status(request_id)
        except (ValueError, conversation_requests.UnknownConversationRequest) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=404)
            return
        if status["conversation_id"] != conversation_id:
            self._send_json({"ok": False, "error": "turn request belongs to another conversation"}, status=404)
            return
        if len(parts) == 6:
            if parts[5] != "events":
                self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
                return
            self._handle_conversation_request_events(conversation_id, request_id, qs)
            return
        self._send_json(core.envelope(status["project"], turn_request=status))
    elif path.startswith("/api/conversations/"):
        # GET /api/conversations/<id>[?limit=] -> resumable summary +
        # bounded turn list (see _conversation_view).
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 3:
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        conversation_id = parts[2]
        if not _CONVERSATION_ID_RE.match(conversation_id):
            self._send_json({"ok": False, "error": "invalid conversation id"}, status=400)
            return
        try:
            limit = _loop_limit(qs, LOOP_MAX_LIMIT)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        try:
            view = _conversation_view(conversation_id, limit=limit)
        except Exception as exc:
            self._send_json(
                {"ok": False,
                 "error": f"the conversation store failed: {type(exc).__name__}: {exc}"},
                status=500)
            return
        self._send_json(
            core.envelope(None, conversation=view) if view is not None else
            {"ok": False, "error": f"unknown conversation id {conversation_id}"},
            status=200 if view is not None else 404)
    elif path.startswith("/api/progress/"):
        # GET /api/progress/<unit_id> -> daedalus.progress_sources
        # .snapshot_any: this endpoint's own event log first, then the
        # spine ledger, then the file bridge -- whichever recognises the
        # id. Always 200: `found` inside the payload carries the honest
        # "nobody has heard of this id" answer, matching how
        # snapshot_any itself is designed to be read (see its docstring).
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) != 3:
            self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
            return
        unit_id = parts[2]
        if not _CONVERSATION_ID_RE.match(unit_id):
            self._send_json({"ok": False, "error": "invalid unit id"}, status=400)
            return
        try:
            from ... import progress_sources

            prog = progress_sources.snapshot_any(unit_id)
            self._send_json(core.envelope(None, progress=prog.to_dict()))
        except Exception as exc:
            self._send_json(
                {"ok": False,
                 "error": f"the progress source failed: {type(exc).__name__}: {exc}"},
                status=500)
        return
    elif path.startswith("/api/"):
        self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
    else:
        self._send_static(path)
