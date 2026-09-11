# W9 — Desktop / Tauri surface (`apps/web/src-tauri/src/lib.rs` + the Python desktop routes)

Base: local main `851ff43c`. Static reading only. Nothing built, launched,
probed or executed.

## Enumeration

- `apps/web/src-tauri/src/lib.rs` — 1777 lines. Read the process-spawn and
  readiness sections (`995-1090`) and the state-migration/allowlist sections
  (`640-700`, `1520-1640`) in detail; the rest structurally.
- `grep -n "#\[tauri::command\]" apps/web/src-tauri/src/lib.rs` -> **0 hits**.
  There is no custom Tauri IPC command surface at all.
- `apps/web/src-tauri/tauri.conf.json` -> `app.security.capabilities` is exactly
  `["project-folder-dialog"]`; `plugins` is **empty**.
- Python desktop routes: `daedalus/interfaces/desktop/http.py` (read fully),
  `daedalus/interfaces/http/server.py`, `daedalus/interfaces/http/read.py:104-113`.
- `grep -rn "STARTUP_NONCE\|startup_nonce" --include=*.py daedalus/ scripts/` -> 13 hits across 5 files.

**Good news first, stated plainly:** the Tauri IPC attack surface is close to
minimal — no `#[tauri::command]` handlers, no plugins, one narrowly-scoped
capability. The classic Tauri findings (over-broad allowlist, `shell.execute`
exposed to the webview, `fs` scope wildcards) **do not apply here**. The spawn
of the backend is a fixed argv with no interpolation (`lib.rs:1010-1020`):

```rust
    let mut command = Command::new(executable);
    command
        .args(["--host", "127.0.0.1", "--port", "8765"])
        .env(DESKTOP_STARTUP_NONCE_ENV, startup_nonce)
        .current_dir(backend_root)
```

The findings below are therefore all on the **Python HTTP surface the shell
spawns**, not in the Rust shell itself.

---

### F-W9-01 The startup nonce is a mutation credential AND is disclosed unauthenticated
- **file:line**: disclosure at `daedalus/interfaces/http/read.py:104-113`; credential use at `daedalus/interfaces/desktop/http.py:73-91`
- **class**: credential-disclosure / auth-bypass / secret-reused-across-purposes
- **severity**: HIGH
- **status**: CONFIRMED

**evidence — the nonce is handed to any caller that asks:**

```python
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
```

This is a `GET` handled by `do_GET`, whose only gate is `_authorized()` — which
returns `True` unconditionally on the default loopback bind
(`daedalus/web_api.py:956-958`).

**evidence — the same nonce is the credential protecting shutdown:**

```python
                if path == "/api/desktop/shutdown":
                    expected = (
                        getattr(self.server, "daedalus_desktop_startup_nonce", "")
                        or ""
                    )
                    supplied = self.headers.get("X-Daedalus-Desktop-Nonce", "")
                    if not expected or not compare_digest(supplied, expected):
                        self._send_json(
                            {"ok": False, "error": "desktop parent nonce required"},
                            status=403,
                        )
                        return
                    manager.close(strict=True, timeout=6.0)
```

**why it matters**: this is the *only* per-route credential check on the entire
desktop surface, and it is defeated in two requests:
`GET /api/desktop-ready` -> read `nonce` -> `POST /api/desktop/shutdown` with
`X-Daedalus-Desktop-Nonce: <nonce>`. The check is written carefully — it uses
`compare_digest` and fails closed on an empty expected value — and all of that
care is undone by publishing the secret on an adjacent unauthenticated route.

**root cause, stated precisely**: one secret is being used for two purposes with
*opposite* disclosure requirements. As a **liveness/identity proof** the nonce
must be disclosed — that is exactly how the Rust shell confirms the listener on
8765 is its own child (`lib.rs:1063-1067`):

```rust
    let expected = format!(
        "{{\"schema\": \"daedalus-desktop-startup/1\", \"ready\": true, \"nonce\": \"{startup_nonce}\"}}"
    );
    status_ok && body == expected
```

As an **authorization credential** it must stay secret. It cannot be both. The
`lib.rs` comment "A raced listener must not win merely because our child
exited..." shows the port-squatting threat was thought through; the secret-reuse
consequence was not.

**reachability**: any local process on the machine (the port is the fixed,
predictable `8765`). **Not** reachable from an arbitrary web page: the CORS
policy only grants read access to `http://127.0.0.1:5173`, so a random site
cannot read the response body. Anything running on or served from the dev-server
origin `127.0.0.1:5173` can.

**suggested direction (not a patch)**: use two values — a disclosed
`instance_id` for the readiness proof, and a separate never-disclosed nonce for
mutation. Or require the nonce as a *request* header on `/api/desktop-ready`
too, so the shell proves possession rather than the server disclosing it.

---

### F-W9-02 Desktop service-control routes have no credential check at all
- **file:line**: `daedalus/interfaces/desktop/http.py:94-109`
- **class**: unauthenticated-effect-trigger / csrf
- **severity**: HIGH
- **status**: CONFIRMED

**evidence** — every branch after the shutdown branch omits the nonce check:

```python
                elif path == "/api/desktop/services/bridge/start":
                    result = manager.ensure_bridge()
                elif path == "/api/desktop/services/ollama/start":
                    result = manager.ensure_ollama()
                    web_api.runtime_registry.reset_status_cache()
                elif path == "/api/desktop/services/ollama/stop":
                    manager.stop_ollama()
                    ...
                elif path == "/api/desktop/services/ide/start":
                    body = web_api._read_body(self)
                    if not isinstance(body, dict):
                        raise desktop_error("request body must be a JSON object")
                    project_root = resolve_project_root(body.get("project"))
                    result = manager.ensure_ide(project_root)
```

**why it matters**: `shutdown` — the *least* damaging of these — is the only one
gated. The routes that **start processes** (`ensure_bridge`, `ensure_ollama`,
`ensure_ide`) are ungated. `ide/start` additionally takes an attacker-supplied
`project` from the request body and passes it through `resolve_project_root`
into `manager.ensure_ide(...)`.

Crucially these are `POST`s reached through `_handle_post`, and the body reader
(`daedalus/interfaces/http/effects.py:44-49`) never checks `Content-Type` — so
these are reachable by **cross-origin CSRF from any website the owner visits**
while the desktop app runs, as a no-preflight simple request. The attacker
cannot read the response, but the process starts anyway. Combined with the fixed
port `8765`, no discovery is needed — the attacker knows the exact URL.

**not verified**: I did not read `manager.ensure_ide` or `resolve_project_root`,
so I cannot say how far an attacker-chosen `project` value travels or whether it
is validated downstream. That is the natural follow-up and it could raise this
to CRITICAL. Treat the *unauthenticated reachability* as confirmed and the
*payload depth* as unquantified.

**relationship to F-W8-05**: same CSRF mechanism, but this is the concrete,
named set of reachable process-starting routes, whereas F-W8-05 relied on the
effect registry's declared effects.

---

### F-W9-03 Settings mutation route is unauthenticated
- **file:line**: `daedalus/interfaces/desktop/http.py:59-68`
- **class**: unauthenticated-effect-trigger
- **severity**: MEDIUM
- **status**: CONFIRMED

**evidence**

```python
        def _handle_put(self) -> None:
            if split_url(self.path).path == "/api/desktop/settings":
                try:
                    snap = manager.save_settings(web_api._read_body(self))
```

**why it matters**: `PUT /api/desktop/settings` writes persisted settings with
no credential. Given that this repository's plan (§4.1) makes *settings* the
place where execution caps are enabled or disabled, a settings writer is a
policy-adjacent authority, not a cosmetic one. `manager.save_settings` presumably
validates its input — I did not read it, so I am not claiming a cap can be
disabled this way. I am claiming the route has no authentication and that the
axis it writes is security-relevant, which is enough to warrant review.

**PLAUSIBLE, not confirmed**: whether `save_settings` can widen an execution
limit. Needs `manager.save_settings` read to resolve. Cross-reference the W10
worker's execution-policy findings.

---

### F-W9-04 A stale, vulnerable build bundle of the backend sits in the tree
- **file:line**: `apps/web/src-tauri/backend/_internal/daedalus/web_api.py:1021`
- **class**: stale-artifact / patch-gap
- **severity**: LOW (INFO for source review; matters for release hygiene)
- **status**: CONFIRMED

**evidence**

```
$ git ls-files --error-unmatch apps/web/src-tauri/backend/_internal/daedalus/web_api.py
error: pathspec ... did not match any file(s) known to git
$ git check-ignore -v ...
apps/web/src-tauri/.gitignore:2:/backend/*
$ diff -q daedalus/web_api.py apps/web/src-tauri/backend/_internal/daedalus/web_api.py
Files ... differ
$ grep -n "WEB_DIST / path.lstrip" apps/web/src-tauri/backend/_internal/daedalus/web_api.py
1021:        target = WEB_DIST / path.lstrip("/")
```

**why it matters**: this is a gitignored PyInstaller output, so it is correctly
*not* a source finding — but three further copies exist
(`apps/web/src-tauri/target/{debug,release}/backend/_internal/...`,
`build/desktop-sidecar/dist/...`) and all carry the path-traversal sink from
F-W8-06. Fixing `daedalus/web_api.py` alone does **not** fix a shipped desktop
build until the sidecar is rebuilt. Recorded so the hardening backlog includes
"rebuild and re-verify the bundle", not just "patch the source". Worth confirming
no release ever ships from a pre-fix bundle.

---

## What I did not cover

- The bulk of `lib.rs` (1777 lines): the state-migration/allowlist logic around
  `lib.rs:640-700` and its tests at `1520-1640` — including
  `state_migration_refuses_a_linked_allowlist_ancestor`, which is plainly the
  **G1-HIER-13 symlink anchor** and is W4's territory. I deliberately left it to
  W4 to avoid duplicate/conflicting analysis.
- `scripts/daedalus_desktop_sidecar.py` — **not read**. It was in my brief and I
  ran out of scope before reaching it. This is a real gap in W9's coverage and
  should be picked up.
- `manager.*` implementations (`ensure_ide`, `ensure_bridge`, `save_settings`,
  `close`) — the depth questions in F-W9-02 and F-W9-03 depend on them.
- `resolve_project_root` validation.
- The webview CSP (I checked `capabilities` and `plugins`, not a `csp` key).
- No dynamic verification: the app was never built or launched. Every claim is
  read from source.
