# W8 — web_api.py + file_bridge.py: auth claims vs reality

Base: local main `851ff43c`. Static reading only; no requests were issued, no
tests run, nothing executed. Every "CONFIRMED" below is confirmed *statically*
(the code path is quoted end to end), not by exploitation.

## Enumeration

Greps run (all excluding `daedalus/lanes/`, and excluding the stale duplicate
trees `.claude/worktrees/`, `.daedalus_worktrees/`, `build/`,
`apps/web/src-tauri/backend/`, `apps/web/src-tauri/target/`):

- `grep -n "authenticat\|Authenticat" daedalus/web_api.py` -> 7 hits
- `grep -n "authenticat\|Authenticat" daedalus/file_bridge.py` -> **0 hits**
- `grep -rn "authenticated_bind" --include=*.py daedalus/ tests/` -> 10 hits
  (5 in `spine/effect_boundary.py`, 2 in `web_api.py`, 1 test)
- `grep -rn "authenticated" --include=*.py daedalus/spine/ daedalus/interfaces/ daedalus/kernel/` -> 24 hits
- `grep -n "Origin\|origin" daedalus/web_api.py` -> 1 hit (a response header, not a check)
- `grep -rn "csrf\|CSRF" --include=*.py daedalus/` -> **0 hits repo-wide**

Sizes: `web_api.py` 1226 lines, `file_bridge.py` 1110 lines.

Request-handling chain traced in full:
`do_GET/do_POST/do_PUT` -> `_authorized()` -> `_handle_*` ->
`daedalus/interfaces/http/{read,effects}.py` -> `parse_request_target` ->
handler bodies. All five files read.

**The three docstrings that say "authenticated" where the default configuration
is not authenticated are F-W8-01, F-W8-02 and F-W8-03 below.** A fourth, related
overclaim (the entrypoint registry) is F-W8-04.

---

### F-W8-01 `_bind_decision()` records the auth guard as PASSED when no authentication occurred
- **file:line**: `daedalus/web_api.py:987-997`
- **class**: overclaim / misleading-evidence-record
- **severity**: HIGH
- **status**: CONFIRMED

**evidence**

```python
    def _bind_decision(self):
        """The web.authenticated_bind decision this request just passed."""
        from daedalus.spine.effect_boundary import GuardDecision

        token = getattr(self.server, "daedalus_auth_token", "") or ""
        return GuardDecision(
            "web.authenticated_bind",
            True,
            "loopback bind (no packet leaves the machine)" if not token
            else "non-loopback opt-in bind; bearer token verified",
        )
```

The second positional argument is the literal `True`. There is no branch in
which this guard records a failure. On the default loopback bind `token` is
empty, so the decision recorded into the effect ledger is a **pass** for a
contract named `web.authenticated_bind`, while the corresponding check —

```python
        token = getattr(self.server, "daedalus_auth_token", "") or ""
        if not token:
            return True          # daedalus/web_api.py:956-958
```

— returned `True` without examining a single credential.

**why it matters**: the docstring says the request "just passed" the
`web.authenticated_bind` decision. In the default configuration nothing was
authenticated. Anyone later auditing receipts sees a guard named
*authenticated_bind* marked satisfied on every request. This is precisely the
class this repository's own review rules make release-blocking ("a hook or
instruction advertised as a complete security guarantee"). The rationale string
is honest about the bind class; the guard *name* and the boolean are not.

Note the stated rationale — "no packet leaves the machine" — answers the wrong
question. The risk on a loopback bind is not egress; it is that every local
process and every web page the browser loads can reach *in* (see F-W8-05).

---

### F-W8-02 Desktop facade module docstring asserts the HTTP facade is authenticated
- **file:line**: `daedalus/interfaces/desktop/http.py:1`
- **class**: overclaim
- **severity**: MEDIUM
- **status**: CONFIRMED

**evidence**

```python
"""Desktop route composition for the existing authenticated HTTP facade."""
```

**why it matters**: unqualified and false in the default configuration. The
desktop path is exactly the configuration that binds loopback with no token, so
the facade this module composes routes onto is the *un*authenticated one. Unlike
F-W8-01 this carries no compensating rationale — a reader takes "authenticated"
at face value. This is the docstring most likely to mislead a future
implementer into assuming a credential check they then do not add.

---

### F-W8-03 Registry declares a mechanical implementation of `web.authenticated_bind` exists
- **file:line**: `daedalus/spine/effect_boundary.py:137-156`
- **class**: overclaim
- **severity**: MEDIUM
- **status**: CONFIRMED

**evidence**

```python
# Named contracts stay in their existing modules; this registry does not
# reimplement their decisions.  The boolean says whether a concrete mechanical
# implementation exists today.
GUARD_CONTRACT_IMPLEMENTED: Mapping[str, bool] = MappingProxyType(
    {
        ...
        "web.authenticated_bind": True,
    }
)
```

**why it matters**: the comment defines the boolean as "whether a concrete
mechanical implementation exists today". For the default bind the concrete
mechanical implementation is `if not token: return True` — i.e. none. The flag
should be conditional on bind class, or the contract should be renamed to
something that is true in both modes (e.g. `web.bind_class_recorded`).

---

### F-W8-04 Five effect entrypoints — including one with SPEND and PROCESS_SPAWN — are guarded only by this contract
- **file:line**: `daedalus/spine/effect_boundary.py:224, 239, 825, 840, 1708`
- **class**: overclaim / unguarded-effect-path
- **severity**: HIGH
- **status**: CONFIRMED

**evidence** (the `web.mutations` row, `effect_boundary.py:229-250`)

```python
    EntrypointSpec(
        id="web.mutations",
        surface=Surface.WEB_API,
        target="daedalus.web_api:DaedalusHandler.do_POST",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=("web.authenticated_bind",),
        wiring=Wiring.CENTRAL,
        ...
        migration="complete for the web.mutations entrypoint",
    ),
```

**why it matters**: `web.mutations` declares the four heaviest effects in the
system — filesystem write, **process spawn**, network egress and **spend** — and
names exactly one guard contract, the one shown above to be a constant pass on
the default bind. The row is marked `Wiring.CENTRAL` and
`migration="complete"`, which reads as "this entrypoint is fully guarded".

In fairness the row's own `notes` field is honest: *"the recorded decision names
the bind class (loopback vs token-verified)"*. The defect is that the honesty
lives in a free-text note while the machine-readable fields
(`guard_contracts`, `Wiring.CENTRAL`, `migration="complete"`,
`GUARD_CONTRACT_IMPLEMENTED=True`) all say guarded. Any tooling that reads the
registry rather than the prose concludes the effect path is protected.

---

### F-W8-05 No CSRF or Origin check: a visited web page can drive SPEND and PROCESS_SPAWN
- **file:line**: `daedalus/interfaces/http/effects.py:44-49`; `daedalus/web_api.py:932-939, 1021-1033`
- **class**: csrf / unauthenticated-effect-trigger
- **severity**: HIGH (CRITICAL if the desktop app is run while browsing)
- **status**: CONFIRMED (statically; not exercised)

**evidence** — the body reader never inspects Content-Type:

```python
def read_body(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}
```

and `grep -rn "csrf\|CSRF" --include=*.py daedalus/` returns **zero** hits
repo-wide, while the only `Origin` occurrence is an emitted response header, not
a validation:

```python
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
```

**why it matters**: because `read_body` accepts any Content-Type, a cross-origin
`fetch()` with `Content-Type: text/plain` is a CORS **simple request** — the
browser sends it with *no preflight*. `do_POST` then runs `_authorized()` (which
returns `True` on the default loopback bind), starts the effect, and executes.
The attacker's page cannot *read* the response (that is all
`Access-Control-Allow-Origin` buys), but the effect — declared by the registry
itself as FILESYSTEM_WRITE, PROCESS_SPAWN, NETWORK_EGRESS, SPEND — has already
happened.

So: any website the owner visits while the desktop app is running can, without
any credential, cause this process to spawn processes and spend money. The CORS
header is doing confidentiality work and is being relied on for integrity work.
`do_OPTIONS` also answers `204` before any auth check (`web_api.py:941-946`),
which is correct per spec but confirms preflight is not a barrier.

**caveat / not verified**: I did not enumerate which concrete POST routes reach
a spawn or a spend. The effects list is the registry's own declaration for the
entrypoint, not a traced call path to a specific `subprocess` call. Treat the
*mechanism* as confirmed and the *worst reachable payload* as unquantified.

---

### F-W8-06 Unbounded path traversal in static file serving → arbitrary file read, no auth
- **file:line**: `daedalus/web_api.py:1049-1068`, reached from `daedalus/interfaces/http/read.py:594`
- **class**: path-traversal / arbitrary-file-read
- **severity**: HIGH
- **status**: CONFIRMED

**evidence** — the sink applies no containment whatsoever:

```python
    def _send_static(self, path: str) -> None:
        target = WEB_DIST / path.lstrip("/")
        if path in ("", "/"):
            target = WEB_DIST / "index.html"
        if not target.exists() or not target.is_file():
            target = WEB_DIST / "index.html"
        ...
        content = target.read_bytes()
        ...
        self.wfile.write(content)
```

There is no `resolve()`, no `relative_to(WEB_DIST)`, no `..` rejection. `WEB_DIST`
is `ROOT / "apps" / "web" / "dist"` (`web_api.py:57`).

The path arrives unnormalized. `read.py:594` is the catch-all GET branch:

```python
    elif path.startswith("/api/"):
        self._send_json({"ok": False, "error": f"unknown endpoint {path}"}, status=404)
    else:
        self._send_static(path)
```

and `path` comes from `parse_request_target(self.path).path`
(`read.py:72-74`), which is a bare `urlparse` with the path *deliberately* left
undecoded and unnormalized (`daedalus/interfaces/http/router.py:20-22`):

```python
def parse_request_target(raw_target: str) -> RequestTarget:
    parsed = urlparse(raw_target)
    return RequestTarget(path=parsed.path, query=parse_qs(parsed.query))
```

`http.server.BaseHTTPRequestHandler` does not normalize `self.path` either —
unlike `SimpleHTTPRequestHandler.translate_path`, which is the sanitizer this
code does not use.

**why it matters**: this is an **arbitrary file read** limited only by what the
server process can open — repository source, `.git` objects, the spend ledger,
the approval SQLite database, and anything readable in the user profile.
`GET /../../../.env` resolves `dist -> web -> apps -> ROOT`. `pathlib` does not
collapse `..`; the OS does, at the `exists()`/`read_bytes()` call, so traversal
succeeds. The `if not exists -> index.html` fallback means a *wrong* guess is
silent, so this probes cleanly.

**Correction on impact, measured rather than assumed**: I initially wrote that
this yields provider API keys via `.env`. Checking without reading contents:
`.env` **does exist** at ROOT (203 bytes, 3 non-empty lines), but a scan for
credential-shaped *names* (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`)
returned **no matches**. So on this machine `.env` is probably not the crown
jewel. The severity rests on arbitrary-file-read generally — in particular the
approval ledger and spend ledger — not on that one file. I did not read `.env`'s
contents. Where the provider keys actually live is W3's question, and W3 found 8
credential-shaped env names in use, which suggests they are supplied by the
environment rather than by this file.

**reachability**: any local process, or any client that does not pre-normalize
the request path (`curl --path-as-is`, a raw socket). Browsers normalize `../`
in the URL before sending, so **drive-by exploitation from a visited web page is
not available for this finding** — this one is local-process reach, unlike
F-W8-05. On a non-loopback bind the bearer token gates it.

**mitigating**: percent-encoded `%2e%2e%2f` does *not* work, because
`parse_request_target` deliberately leaves the path encoded and `pathlib` treats
`%2e%2e` as a literal segment. Plain `..` is the working form.

---

### F-W8-07 `file_bridge.py` makes no authentication claim — and has no authentication
- **file:line**: `daedalus/file_bridge.py:27-32`
- **class**: INFO (honest gap, recorded for completeness)
- **severity**: INFO
- **status**: CONFIRMED

**evidence**: `grep -n "authenticat" daedalus/file_bridge.py` -> zero hits. The
bridge is a filesystem inbox/outbox:

```python
ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
```

**why it matters**: this is listed as a *non*-finding for the auth-overclaim
question — the module does not claim protection it lacks. Its trust boundary is
the filesystem ACL on `inbox/`, which is a legitimate design for a single-user
desktop. It is recorded here so the "which surfaces claim auth" question has a
complete, auditable answer rather than a silent omission.

**not covered**: I did not audit what an `inbox/` drop can *cause* (dispatch,
spawn, queue semantics). That is a real effect-entrypoint question and it is
out of W8's scope — recommend it as follow-up work, since anything that can
write one file into `inbox/` appears to obtain whatever authority the dispatcher
has.

---

## What I did not cover

- Which specific POST/PUT routes reach a concrete spawn or spend call (F-W8-05
  relies on the registry's declared effects, not a traced call path).
- The SSE endpoints (`_handle_events`, `_handle_ikarus_stream`,
  `_handle_task_events`) — auth is applied at `do_GET`, but I did not review
  their own handling.
- `file_bridge.py` dispatch semantics and the `inbox/` authority question above.
- The desktop route bodies installed by `interfaces/desktop/http.py` (only its
  docstring was in scope here); note it receives a `compare_digest` port, which
  suggests it has its own token check — unreviewed, and it may partially redeem
  F-W8-02.
- No dynamic verification of any kind. Traversal and CSRF are reasoned from the
  code as written.
