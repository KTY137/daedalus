# G1-HYG-01 — First-party source provenance watermark

**Status:** VERIFIED

**Klassifikation:** `ALIGNED`

**Aktives Gate:** 1 — Renovation ignition slice

**Owner:** repository owner

**Base revision:** `c773a94dce21f28d5d149fe3e984d4508292d793`

**Plan-Digest:**
`7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704`

## Eine Behauptung

Eindeutig eigener, veränderbarer Quellcode trägt einen syntaktisch neutralen,
deterministisch prüfbaren SPDX-Hinweis auf Kaya Yesilyurt und Apache-2.0.
Repositoryweite Attribution, Snapshot-Digests und eine abgesetzte Signatur
machen den Rollout reproduzierbar, ohne Historie, Tags, Archive, Kandidaten-
identitäten oder zurückbehaltene Evidenz umzuschreiben.

## Berührte Grenzen

- Invariant 2, Artifact identity: keine History-Rewrite, kein Force-Push und
  keine Änderung an content-addressed Fixtures oder Archivankern.
- Invariant 7, Provenance: Policy, Dateiliste, SHA-256 und Signatur benennen
  exakt den attestierten First-Party-Snapshot.
- Invariant 10, No silent constitution change: Masterplan, Amendment-Chain und
  aktive Instruktionen sind verboten und bleiben unverändert.

## Eingefrorener Scope

In scope:

- `NOTICE`;
- `provenance/source-watermark-policy.json`, Manifest und Signatur;
- das strikt read-only `tools/source_provenance.py` und fokussierte Tests;
- ein schmaler read-only CI-Check;
- ausschließlich die in der Policy ausgewählten First-Party-Quellpfade;
- normale, signierte Commits/PRs auf `main` und danach den live ermittelten
  offenen PR-Heads `g1/ikarus-runtime-invocation-binding-07d3`,
  `exp/tensor-kernel-contract-01`, `exp/tensor-latent-ceiling-01`,
  `ops/gardener-campaign-20260929` und
  `g2/knowledge-correlation-bootstrap`.

Explizit verboten:

- Force-Push, Rebase/Filter-Rewrite, Tag-Umschreibung oder Auto-Merge;
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Amendment-Chain, `AGENTS.md` oder
  andere aktive Instruktionen;
- `archive/legacy-20260830`, alle Tags, `experiment/deepseek-lab` und der
  bereits gemergte stale Branch `feature/chip-design-rtl-tcl` sowie der
  vollständig gemergte Residual-Branch
  `g1/gardener-post-release-containment-03`;
- `references/**`, `experiments/**`, `runs/**`, `vault/**`, `.room/**`,
  `tests/fixtures/**`, generierte Bundles und separat lizenziertes
  `vscode-agent-env/**`.

## Baseline

Auf der Base-Revision fehlte `NOTICE`. In den ausgewählten First-Party-Pfaden
bestand keine einheitliche SPDX-Konvention; die zwei gefundenen SPDX-Dateien
lagen ausschließlich in ausgeschlossenen generierten Design-Prototypen. Der
saubere Worktree startete mit null Änderungen.

Während des Builds rückte `origin/main` um den Sicherheits-Commit `3b4e4886`
vor. Der Worktree wurde vor Veröffentlichung fast-forward aktualisiert; dessen
Löschung von `tools/branch_consolidate_20260830.py` und der beiden zugehörigen
Workflows wurde ausdrücklich beibehalten. Manifest und Signatur wurden nur auf
der aktualisierten Base erzeugt.

Vor der Attestation wurde anschließend auch der normale Merge von PR #306
(`cfe9f40a`) fast-forward integriert. Dessen neue First-Party-Quellen werden
vom selben Policy-Census erfasst; der nun gemergte Head scheidet aus der Liste
der separat zu aktualisierenden Draft-Branches aus.

Nach der ersten Draft-Veröffentlichung mergte PR #291 als `c773a94d` nach
`main`. Der Feature-Branch integrierte diesen Stand durch einen normalen,
signierten Merge ohne Rebase oder Force-Push. Die beiden neu hinzugekommenen
First-Party-Quellen werden in demselben Index-Snapshot erfasst; der nun
gemergte Nemesis-Head scheidet aus der separaten Propagation aus.

## Akzeptanzmatrix (eingefroren)

| # | Behauptung | Rot wenn |
|---|---|---|
| 1 | Jede Policy-Datei trägt beide exakten SPDX-Zeilen. | `check` meldet einen Pfad. |
| 2 | Exkludierte Fremd-, Fixture-, Archiv- und Evidenzbytes bleiben unverändert. | Ein ausgeschlossener Pfad erscheint im Diff. |
| 3 | Shebang, Python-Encoding, BOM, Zeilenenden und HTML-Doctype bleiben erhalten. | Unit-Test oder Byte-Audit widerspricht. |
| 4 | Die reine Header-Transformation ist idempotent und überschreibt keine fremde SPDX-Präambel; die ausgelieferte CLI besitzt keinen Write-/Apply-Pfad. | Zweite Transformation ändert Bytes, ein Konflikt wird still ersetzt oder die CLI schreibt. |
| 5 | Das Manifest deckt exakt alle gestagten Policy-Dateien mit SHA-256 der Git-Blobbytes ab und verifiziert vollständig. | Zählung/Digest/Policy/NOTICE driftet oder eine Dateizeile kann entfallen. |
| 6 | Die abgesetzte SSH-Signatur und die signierten Git-Commits verifizieren mit dem normalen Provenienzschlüssel; der Promotion-Key ist getrennt. | `ssh-keygen -Y verify`, `git verify-commit` oder der Key-Separation-Audit scheitert. |
| 7 | Python/Frontend/Rust-Quelltext bleibt syntaktisch gültig. | Compile-, Build- oder fokussierter Test scheitert. |
| 8 | GitHub-Veröffentlichung bleibt reviewbar und nicht promotend. | Direktpush auf `main`, Force-Push oder Auto-Merge tritt auf. |

## Budgets und Rollback

Keine neue Laufzeitabhängigkeit und kein Egress im Checker. GitHub-Aktionen
erhalten nur `contents: read` und fünf Minuten Timeout. Rollback ist ein
normaler Revert der branchspezifischen Commits; historische SHAs bleiben
erhalten.

## Verifikation

- Policy-Census und Arbeitsbaum: `source provenance: ok (1110 files)`.
- Git-Index-Manifest: 1.110 vollständige, sortierte Pfade; alle SHA-256-Werte
  werden gegen die exakten gestagten Git-Blobbytes geprüft. Der Renderer gab
  auf Windows exakt 169.809 UTF-8-Bytes mit 4.463 LF und null CR aus; Signatur
  und gestagtes Manifest decken damit dieselben Bytes ab.
- Diff-Audit: 1.107 bestehende Quelldateien entsprechen bytegenau der reinen
  Header-Transformation; drei neue Prüfinfrastruktur-Quellen und sieben
  Nicht-Quellartefakte ergeben insgesamt 1.117 geänderte Pfade. Kein
  ausgeschlossener Pfad ist enthalten.
- Provenienz-, Terminal-Rendering- und die auf der finalen Base
  hinzugekommenen Tier-2-Integritätstests: 66 Tests und acht Subtests
  bestanden. `compileall` bestand für Checker, Tests und die neuen Base-Dateien;
  `git -c core.whitespace=cr-at-eol diff --cached --check` blieb leer. Der
  Default-Check markiert ausschließlich die bewusst bytegleich erhaltenen
  CRLF-Enden der drei per `.gitattributes` als `-text` gepinnten Dateien
  `daedalus/kairos/drafts.py`, `daedalus/kernel/effect_replay.py` und
  `daedalus/kernel/offload_lease.py`; es wurden keine Leerzeichen angehängt.
- Der frühere polyglotte Durchlauf bestand für TypeScript/Vite, 134 Motion-
  Spezifikationen, `cargo check --locked`, Node-Syntax, Bash-Syntax und fünf
  PowerShell-Dateien. Es entstanden keine Buildreste im Repository.
- Detached Signature: erfolgreich mit Namespace
  `daedalus-source-provenance` und dem normalen ED25519-Key
  `SHA256:i1jXwe6dQbOa9dHS0w3TiLnm6kPJqhpZ27Yjl/W49s4` verifiziert.
- Der vollständige Pytest-Baseline-Lauf erreichte 43 bestandene und zwei
  übersprungene Tests bis zu einer eingefrorenen Experiment-Erwartung
  (erwartet 4203, vorhanden 4881). Die saubere Base scheiterte dort identisch.
  Zwei fokussierte Ignition-Tests scheiterten ebenfalls auf Änderung und
  sauberer Base identisch an bereits vorhandener Kill-Switch-/EvidencePacket-
  Konfiguration; diese negativen Baseline-Ergebnisse bleiben ausdrücklich
  erhalten.
- Der unabhängige Release-Review der Provenienzmechanik endete nach
  adversarialen Byte-, Scope-, Signatur-, CLI- und Diff-Prüfungen mit `PASS`
  und ohne offenen release-blockierenden Defekt. Nach dem Merge von PR #291
  wurden derselbe vollständige Candidate-Set-, Blob-, Header-, Renderer- und
  Signatur-Audit sowie die 66 Tests und acht Subtests auf `c773a94d` erneut
  erfolgreich ausgeführt.
