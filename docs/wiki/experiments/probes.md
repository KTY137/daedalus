---
title: Einzelsonden
type: experiment
status: living
updated: 2026-09-05
covers: experiments/concurrency, experiments/tensor_gpu
---

# Einzelsonden

Zwei Experimente, die je aus einer Datei bestehen und deshalb im Seitenplan
von [`daedalus/wiki/plan.py`](../../../daedalus/wiki/plan.py) (mindestens zwei
Module je Thema) keine eigene Seite bekommen haben. Beide sind isolierte,
lesende Messinstrumente im Sinne von Masterplan Abschnitt 1: kein
Produktionspfad importiert sie, keines befoerdert etwas.

## Module

| Datei | Zweck | Symbole |
| --- | --- | --- |
| [probe_append_atomicity.py](../../../experiments/concurrency/probe_append_atomicity.py) | Misst auf **dieser** Maschine, welcher Append-Mechanismus sechs gleichzeitige Schreiber ueberlebt (`WRITERS`, `TURNS`, `RECORD_PAD`). Anlass laut Docstring: ein Journal dieses Repositories verlor unter vier Schreibern 13 Prozent seiner Datensaetze. Ausgabe ist gefunden-gegen-erwartet; alles unter erwartet ist stiller Datenverlust. | `payload`, `run`, `main` |
| [cuda_boolean_probe.py](../../../experiments/tensor_gpu/cuda_boolean_probe.py) | Begrenzte CUDA-Sonde: kann ein FP16/BF16-GEMM ueber PyTorch/cuBLAS den Boolean-Support eines `TypedRelationBlock` schneller reproduzieren? Der stdlib-Block bleibt das Orakel; der Bericht schreibt hoechstens `tensor_core_candidate=true` und behauptet nie Hardware-Einheiten. Ohne CUDA endet die Sonde als `ProbeBlocked` mit Grund. | `ProbeCase`, `ProbeBlocked`, `build_boolean_case`, `run_case`, `run_probe`, `blocked_report`, `write_report`, `estimate_dense_device_bytes`, `exact_reference_operation_count`, `main` |

## Trust-Grenzen / Effekte

- Die Append-Sonde startet echte Kindprozesse und schreibt in eine
  Messdatei; sie ist ein Experiment-Skript, keine registrierte Tuer der
  [Spine](../architecture/spine.md), und darf deshalb nur von Hand unter dem
  im Docstring genannten Interpreter laufen.
- Die CUDA-Sonde schreibt ihren JSON-Bericht nur ueber `write_report` an den
  auf der Kommandozeile genannten Pfad und laedt PyTorch erst in `_load_torch`,
  damit ein Host ohne GPU die Sonde importieren und als blockiert melden kann.

## Tests

Keine eigenen Tests unter `tests/` (gemessen 2026-09-05, kein Treffer fuer
`probe_append_atomicity` oder `cuda_boolean_probe`). Die CUDA-Sonde prueft
ihr Ergebnis selbst gegen das exakte Orakel (`_same_support`).

## Verwandt

- [Fourfold Hybrid Retrieval](fourfold-hybrid-retrieval.md) -- der
  `TypedRelationBlock`, dessen Boolean-Support die CUDA-Sonde reproduziert.
- [Forest v2 -- Semantic-Composite-Tensor](forest-v2-tensor-semantic-composite.md)
  und [Tensor-Embeddings](forest-v2-tensor-embeddings.md) -- die
  Tensor-Experimente, zu denen die GPU-Frage gehoert.
- [Lanes](../architecture/lanes.md) und [Kernel-Events](../architecture/kernel-events.md)
  -- die Schreibpfade, fuer die die Append-Messung relevant ist.
- [Wiki](../architecture/wiki.md) -- warum Ein-Datei-Experimente im Plan
  keine eigene Seite bekommen.

## Ungeklaert

- **Ungeklaert:** ob das Ergebnis der Append-Sonde je in eine Entscheidung
  ueber den Journal-Schreibpfad eingeflossen ist; im Verzeichnis liegt kein
  Ergebnisartefakt.
- **Ungeklaert:** ob die CUDA-Sonde auf diesem Host (2 GB GPU) je ueber
  `blocked_report` hinausgekommen ist.
