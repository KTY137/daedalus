---
tags:
- findings
- gate0
- recovery
created: 2026-08-17
permalink: main/findings/gate0-recovery-patches
---

# Gate-0-Recovery-Patches (2026-08-17)

**Artefakte (autoritativ, unter `docs/recovery/`):**

- `../../docs/recovery/fix_fsync_readonly_windows.patch` — fsync auf readonly-Handle bricht unter Windows
- `../../docs/recovery/fix_gate0_release_cli_import.patch` — Release-CLI-Importfehler
- `../../docs/recovery/gate0_fixture_fixes_20260817.patch` — Fixture-Reparaturen für die Gate-0-Suite
- `../../docs/recovery/lane_diffs/` — Lane-Diffs der Recovery-Session
- `../../docs/recovery/amendment_005_kit.py` — Werkzeug zum Amendment-Vorschlag 005

Link-Notiz — Einordnung: Patches liegen als Dateien vor, sind also womöglich noch
nicht (vollständig) im Baum gelandet. Vor Anwendung: `git apply --check`.

Status je Patch bitte hier nachtragen, wenn geprüft:

- [ ] fsync/readonly angewendet oder obsolet?
- [ ] release-CLI-Import angewendet oder obsolet?
- [ ] Fixture-Fixes angewendet oder obsolet?