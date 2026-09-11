# Work Packet: G1-CODEX-10 Safe laptop state import

Status: review packet  
Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  

## Primary claim

Codex sessions and generated memory artifacts can be imported from an offline
laptop `CODEX_HOME` without copying credentials, live SQLite databases, logs,
or machine-local configuration, and without overwriting divergent files.

## Acceptance

- Dry-run is the default and reports copied, identical, and conflicting files.
- Apply copies only missing regular files under `sessions/` and the bounded
  memory artifact roots.
- Symlinks, auth/config, SQLite, logs, and temporary state never enter scope.
- A conflicting relative path fails closed and preserves both sides.
- Windows, Linux, and macOS paths are accepted.

## Forbidden

- No shared live SQLite database and no bidirectional concurrent writer setup.
- No `auth.json`, tokens, config, logs, or whole-`CODEX_HOME` copy.
- No claim that ChatGPT web memory and local Codex memory are the same store.
