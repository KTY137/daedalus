# Ikarus computer configuration

Run `/computer setup` in the Ikarus conversation to create its separate local
workspace and control state. Fresh v0.1.6 setup enables no tools. `/computer
status` reports the workspace, effective capabilities, unavailable
dependencies, current policy digest and the temporary path-I/O release lock.

The explicit owner command `/computer configure <JSON>` replaces the existing
policy. Its JSON object has exactly two fields: `expected_policy_sha256` and
`policy`. Copy the current digest and complete policy, edit the intended scope,
then send the command. A stale digest refuses without replacing the policy.
The configuration command is not in the model's tool inventory.

For example, the following body enables a browser restricted to a local fixture
origin and a named native text editor. Replace the digest and workspace
placeholders with the values from your existing setup, and replace the editor
path with the actual installed native executable. The workspace must already
exist even though this release does not expose it to tools. The example is a
template, not an automatically applied grant.

```json
{
  "expected_policy_sha256": "<current 64-character lowercase digest>",
  "policy": {
    "schema": "daedalus-computer-policy/1",
    "workspace": "<existing absolute computer workspace>",
    "tools": ["app.launch", "browser.navigate", "browser.read", "browser.fill", "browser.click"],
    "origins": ["http://127.0.0.1:8080"],
    "applications": {
      "notes": ["C:\\Windows\\System32\\notepad.exe"]
    },
    "planner_provider": "ollama_http",
    "planner_model": null,
    "allow_remote_context": false,
    "max_steps": 16,
    "timeout_s": 300,
    "max_file_bytes": 1048576
  }
}
```

Send that JSON on the same command after `/computer configure `. Enabling a
tool does not install its dependencies or make unsupported behavior available.
In v0.1.6, `file.list`, `file.read`, `file.write`, `file.mkdir`, `file.move`,
`vision.match` and `vision.changes` are centrally release-disabled. Path-shaped
`vision.inspect` and `vision.ocr` calls are also disabled; those two tools can
only consume a fresh observation token. Old policy files and newly submitted
policy JSON may still contain the disabled names so owners can migrate them,
but neither setup nor a stored grant turns them into an advertised or
executable capability. This is a fail-closed release fence, not a claim that
pathname validation is race-free.

The browser uses a fresh isolated profile, exact allowed origins and static
HTML interaction. JavaScript, form submission, downloads, service workers and
websocket traffic are unavailable in this initial adapter. Redirects require
a separate admitted navigation. It can fill ordinary text fields and follow
admitted links, with field readback and fresh observation tokens.

Desktop tools are `desktop.observe`, `desktop.click`, `desktop.type` and
`desktop.key`. Each requires the corresponding tool grant and an application
whose full foreground executable path matches one of the owner-defined fixed
argument lists. Launcher paths can differ from the eventual GUI process and
will then be refused. Screen observations contain metadata; image bytes stay
private for local vision. Input consumes a fresh observation and reports an
observed action, requiring independent verification of the intended result.

The native Windows screenshot/input matrix has not been exercised against a
live foreground application in this delivery; deterministic refusal tests and
backend initialization are recorded separately. Browser fixture tests use real
Chromium. Neither those tests nor a policy grant establish automation support
for every application. Authorized application behavior is trusted host behavior,
not candidate-process containment.

Configuration keeps the existing kill-switch state. Active work observes the
changed policy and must stop; a new task uses the new policy. A successful
change returns the new policy digest and canonical evidence references. If a
failure says the policy changed but final evidence failed, inspect status before
retrying. To roll back, submit the previous policy values with the new current
digest; completed external effects are not reversed.

Scheduled work uses `/computer schedule <ISO8601-with-timezone> <task>`, for
example `/computer schedule 2026-09-06T10:00:00+02:00 Read the allowed static status page`.
Choose a future time. `/computer scheduled` lists the retained jobs and
`/computer run-due` performs one manual tick. Automatic ticks use the existing
File Bridge watcher for this exact installation; work does not run while that
watcher is stopped. Each tick admits at most one new mission.

A scheduled job freezes the current computer and execution-limit policy, and
expires 24 hours after its due time. Changed policy, cancellation, a stopped
kill switch or expiry prevents execution. Duplicate admission of the same
time, objective and scope retains one schedule. An interrupted claimed job is
shown as `reconciliation_required` and is never automatically repeated;
completed effects still require inspection before an owner reschedules work.
