---
tags:
- meta
- report
created: 2026-08-17
permalink: main/environment-report
---

# Environment-Report — Claude-Code-Power-Setup für Daedalus

Gebaut am 2026-08-17 auf Branch `checkpoint/2026-07-20-session`.
Klassifikation: **ALIGNED** (additives Tooling; kein neuer Kernel-Pfad, keine
geschützten Artefakte berührt). Gate 0 aktiv.

## 1. Was gebaut wurde

### Vault (`vault/`) — das Projektgehirn

| Datei | Zweck |
| --- | --- |
| `Home.md` | Dashboard (Dataview-frei: Links, Tabellen, Callouts) |
| `Memory-Map.md` | Trennung Auto-Memory / Serena / Vault / `daedalus/wiki` |
| `Gates/Gate-Status.md` | Gate-Leiter, Gate-0-Exit-Kriterium, Artefakt-Links, Journal |
| `Amendments/Amendments.md` | Amendment-Kette + offene Vorschläge 002–005 |
| `Findings/Index.md` + 3 Link-Notizen | Recovery-Artefakte verlinkt (nie kopiert) |
| `Sessions/2026-08-17.md` | Erste Daily Note |
| `Templates/` (Session, Finding, Amendment-Proposal) | Vorlagen |
| `.obsidian/` (app, daily-notes, templates, core-plugins) | Grundkonfig — Daily Notes → `Sessions/`, Templates → `Templates/` |
| `.gitignore` | hält Obsidian-Laufzeitzustand aus dem Repo |
| `SETUP.md` | Owner-Schritte (Obsidian, Plugins, MCP-Upgrade-Pfad) |

Der Vault ist bewusst **Wissensoberfläche, nicht Zustand**: kein zweiter
Event-Store, keine Policy-Autorität, kein Orchestrierungszustand (Iron Plan
§0, §7, §12). `daedalus/wiki/vault.py` bleibt der programmatische, fail-closed
Pfad; dieser Vault ist die menschenlesbare Oberfläche im selben Format.

### MCP (`.mcp.json`, nur ergänzt)

Neuer Server `obsidian-vault`: offizieller
`@modelcontextprotocol/server-filesystem`, gescoped auf `vault/`.
Auswahlbegründung: robustester Windows-Pfad — kein Plugin, kein API-Key,
läuft ohne offene Obsidian-App; die REST-Variante (`MarkusPfundstein/
mcp-obsidian`, meistgenutzter Obsidian-MCP) ist als 2-Minuten-Upgrade in
`SETUP.md` dokumentiert. Bestehende Server (serena, playwright, context7,
shadcn) unangetastet.

### Vorschläge (`.claude/proposals/`, NICHT aktiv — settings.json ist geschützt)

- `statusline.py` — Modell, Verzeichnis, Branch, Kontext-% (farbcodiert ab 60/85 %), Kosten; pure stdlib, kein jq.
- `hook_precompact_vault.py` — PreCompact-Audit-Zeile in die Daily Note (blockiert nie).
- `hook_notification_toast.py` — Windows-Popup bei permission_prompt / agent_needs_input / agent_completed.
- `settings.statusline.snippet.json`, `settings.hooks.snippet.json`, `README.md` — Merge-Anleitung.

### Skills (`.claude/skills/`)

- `vault-sync` — Session-Erkenntnisse → Daily Note/Findings, append-only, Provenienz-Stempel.
- `vault-recall` — Vault-Retrieval VOR der Arbeit; ASSUMED bleibt ASSUMED.

Beide sind in der Session-Skill-Liste registriert (MEASURED).

## 2. Was der Owner selbst tun muss

1. (5 min) Obsidian installieren, `vault/` als Vault öffnen — `SETUP.md` §1.
2. (3 min, optional) Statusline-/Hook-Snippets in settings.json oder settings.local.json mergen — `.claude/proposals/README.md`.
3. (2 min, optional) Local-REST-API-Plugin + `obsidian-rest`-Eintrag für Obsidian-interne MCP-Features — `SETUP.md` §3.
4. (1 min) Neue Claude-Session starten, damit der `obsidian-vault`-MCP-Server geladen wird.

## 3. MEASURED vs ASSUMED

| Behauptung | Status |
| --- | --- |
| Skills `vault-sync`/`vault-recall` werden vom Harness registriert | MEASURED (erschienen in der Skill-Liste dieser Session) |
| Statusline-/Hook-Skripte laufen mit Mock-stdin fehlerfrei | siehe Smoke-Test-Zeile in `Sessions/2026-08-17.md` |
| `obsidian-vault`-Server startet via npx | ASSUMED bis zum ersten Sessionstart (offizieller Anthropic-Server, npx-Standardpfad) |
| Filesystem-MCP ist die robusteste Windows-Variante | INHERITED (contextbolt.com-Vergleich; nicht selbst gebenchmarkt) |
| Obsidian-App rendert die `.obsidian`-Grundkonfig korrekt | ASSUMED (App hier nicht installiert — Owner-Schritt 1) |

## 4. Recherche-Quellen

- Offizielle Doku Statusline: code.claude.com/docs/en/statusline (stdin-JSON: `model.display_name`, `workspace.current_dir`, `context_window.used_percentage`, `cost.total_cost_usd`)
- Offizielle Doku Hooks: code.claude.com/docs/en/hooks (PreCompact kann blocken; Notification-Matcher `permission_prompt|agent_needs_input|…`)
- Obsidian-MCP-Vergleich: contextbolt.com/blog/obsidian-mcp-claude (Filesystem vs. REST; Empfehlung Filesystem als Startpunkt) + github.com/MarkusPfundstein/mcp-obsidian
- Setup-Architektur 2026 (CLAUDE.md schlank, Prozeduren in Skills, Erzwingung in Hooks): smartscope.blog Claude-Code-Best-Practices 2026
- Community-Referenz-Setup mit Obsidian-Second-Brain (kurze Notizen, [[Links]], Rohnotizen nie editieren): okhlopkov.com Claude-Code-Setup 2026
- Kuratierte Listen: github.com/jqueryscript/awesome-claude-code, github.com/VoltAgent/awesome-claude-code-subagents

## 5. Bewusst NICHT gebaut

- Kein weiterer Subagent (20+ Rollen existieren; Lücke war Wissens-Persistenz, nicht Rollen).
- Kein Output-Style (Iron-Plan-Hooks prägen den Ton bereits; ein Style-Override würde mit dem Handoff-Format konkurrieren).
- Kein Obsidian-Git-Plugin, kein zweiter Sync-Mechanismus (Repo-Git ist die Versionierung).
- Keine Änderung an geschützten Artefakten; `.claude/settings.json` nur als Snippet-Vorschlag adressiert.