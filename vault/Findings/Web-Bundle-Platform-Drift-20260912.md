---
tags: [findings]
created: 2026-09-12
source: PR #382
---

# Web bundle platform drift

**Artefakte (autoritativ):** [`../../.github/workflows/tauri-desktop.yml`](../../.github/workflows/tauri-desktop.yml), [`../../tests/test_desktop_packaging.py`](../../tests/test_desktop_packaging.py)

Der getrackte Vite-Build war gegenueber der Cockpit-Quelle veraltet. Beim
Rebuild zeigte sich zusaetzlich, dass Windows und Linux fuer denselben
Quellstand unterschiedliche JS-Chunk-Hashes erzeugen; deshalb ist der
bestehende Linux-PR-Builder die kanonische Vergleichsumgebung, und ein
Fehllauf behaelt seinen generierten `dist`-Baum kurzzeitig als Diagnoseartefakt.

Provenienz: MEASURED (PR #382, GitHub Actions Runs 34681565873,
34681787373 und 34681875201)

Offene Pruefschritte:

- [ ] Pruefen, ob eine spaetere Vite/Rollup-Version plattformidentische
      Chunk-Inhalte erzeugt; bis dahin keine Cross-Platform-Hashgleichheit
      behaupten.
