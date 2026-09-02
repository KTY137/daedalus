---
tags:
- findings
created: 2026-08-20
source: runs/higher_twin_nc/runs/pilot-20260820/
permalink: main/findings/higher-twin-nc-erstmessung-20260820
---

# Higher-Twin-NC: Erste K-Matrix-Messung

**Artefakt (autoritativ):** `../../runs/higher_twin_nc/runs/pilot-20260820/`
(kmatrix.json, report.md, receipts.jsonl) — Spec:
`../../runs/higher_twin_nc/SPEC.md`, Theorie:
`../../docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md`

Einordnung: Erste real ausgeführte A/B/AB/BA/Sham-Interventionsmatrix des
Experiments `higher-twin-nc-v1` (38 Läufe, hash-verkettete Rezepte, Kette
verifiziert, Zweitlauf byte-identisch). Die Matrix zeigt alle vorhergesagten
Zelltypen: asymmetrische Nichtkomponierbarkeit, echte Verhaltens-
Nichtkommutation (scale∘clip), sound-aber-unvollständige Footprint-Zertifikate
(7/7 bzw. 7/12) und eine korrekte Anomalie-Null. Damit existiert erstmals
Messinfrastruktur, die Nichtkommutativität von Software-Patches als
kontinuierliche Größe erhebt statt als binäres Konfliktflag.

Provenienz: MEASURED (Pilot-Smoke auf autorenkonstruiertem Fixture —
Kalibrierung, kein Effektclaim; Messkonstruktionsregel 2026-08-18 beachtet)

Offene Prüfschritte:

- [ ] H-ANOM gegen injizierte Kopplung mit Ground Truth
- [ ] Externe Fixtures/Repos, um Autoren-Zirkularität zu brechen