"""Arm A of EXPERIMENT ``tensor-embedding-v1``: binding fidelity vs. slots.

Hypothesis H-A: identity, plane, revision and provenance can be bound into one
fixed-width vector and each field recovered by unbinding plus cleanup.

The point of this arm is NOT the capacity curve -- that is Plate 1995 and needs
no re-deriving. The point is the mandatory baseline: slot concatenation writes
the same fields into disjoint sections of a vector of the same total width and
recovers them exactly, by construction. Reported side by side, the question
becomes the only one that matters: does binding cost less width for equal
fidelity, or does it not?

Run:  python experiments/tensor_embedding/arm_a_capacity.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hrr import bind, bundle, cleanup, codebook, unbind  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[2] / "runs" / "tensor_embedding_v1"
DIMENSIONS = (256, 512, 1024, 2048, 4096)
ROLE_COUNTS = (2, 3, 4, 5, 6, 8)
VOCAB = 1000
TRIALS = 200


def _unit_rows(book: np.ndarray) -> np.ndarray:
    return book / (np.linalg.norm(book, axis=1, keepdims=True) + 1e-12)


def hrr_accuracy(d: int, k: int, fillers: np.ndarray, trials: int = TRIALS) -> float:
    """Fraction of bound fields recovered correctly, over ``trials`` draws.

    The filler codebook is drawn ONCE per dimension and passed in. The first
    draft redrew a 1000-by-d codebook inside every trial: 6000 draws, the
    largest 32 MB each, which blew a 120 s budget past 300 s and produced no
    result at all. Only the chosen indices need to vary between trials.
    """
    unit = _unit_rows(fillers)
    rng = np.random.default_rng(10_000 + d * 100 + k)
    roles = codebook(k, d, rng)
    correct = 0
    for _ in range(trials):
        chosen = rng.integers(0, VOCAB, size=k)
        card = bundle([bind(roles[i], fillers[chosen[i]]) for i in range(k)])
        noisy = np.stack([unbind(card, roles[i]) for i in range(k)])
        noisy /= np.linalg.norm(noisy, axis=1, keepdims=True) + 1e-12
        correct += int(np.sum(np.argmax(noisy @ unit.T, axis=1) == chosen))
    return correct / (trials * k)


def slot_accuracy(d: int, k: int, trials: int = TRIALS) -> float:
    """The baseline. Disjoint slices of the same total width ``d``.

    Recovery reads the slice back and cleans it against that slice's codebook.
    Nothing is superposed, so nothing interferes -- which is precisely the
    point of measuring it rather than assuming it.
    """
    width = d // k
    if width == 0:
        return float("nan")
    rng = np.random.default_rng(20_000 + d * 100 + k)
    books = [_unit_rows(codebook(VOCAB, width, rng)) for _ in range(k)]
    correct = 0
    for _ in range(trials):
        chosen = rng.integers(0, VOCAB, size=k)
        for i in range(k):
            stored = books[i][chosen[i]]
            correct += int(int(np.argmax(books[i] @ stored)) == int(chosen[i]))
    return correct / (trials * k)


def main() -> int:
    started = time.time()
    rows = []
    for d in DIMENSIONS:
        fillers = codebook(VOCAB, d, np.random.default_rng(d))
        for k in ROLE_COUNTS:
            rows.append(
                {
                    "d": d,
                    "k": k,
                    "hrr_accuracy": round(hrr_accuracy(d, k, fillers), 4),
                    "slot_accuracy": round(slot_accuracy(d, k), 4),
                    "slot_width": d // k,
                }
            )
            print(
                f"d={d:5d} k={k}  hrr={rows[-1]['hrr_accuracy']:.4f}  "
                f"slot={rows[-1]['slot_accuracy']:.4f}  (slot width {d // k})"
            )

    # The decision the arm exists to make: cheapest width reaching 99 %.
    def cheapest(field: str, k: int) -> int | None:
        for d in DIMENSIONS:
            hit = [r for r in rows if r["d"] == d and r["k"] == k]
            if hit and hit[0][field] >= 0.99:
                return d
        return None

    verdict = {
        k: {
            "hrr_min_d_at_99pct": cheapest("hrr_accuracy", k),
            "slot_min_d_at_99pct": cheapest("slot_accuracy", k),
        }
        for k in ROLE_COUNTS
    }

    # Extension sweep, added AFTER the frozen grid was run and seen to be
    # saturated: every cell but two sat at 1.0000, and a table without a
    # dynamic range cannot be read. The frozen grid above is untouched; this
    # pushes the role count until both methods break, which is the only way to
    # see whether they break in the same place.
    ext_dims = (256, 512, 1024)
    ext_ks = (8, 16, 32, 64, 128)
    ext_rows = []
    print("\n-- extension sweep (added after the frozen grid saturated)")
    for d in ext_dims:
        fillers = codebook(VOCAB, d, np.random.default_rng(d))
        for k in ext_ks:
            row = {
                "d": d,
                "k": k,
                "hrr_accuracy": round(hrr_accuracy(d, k, fillers, trials=50), 4),
                "slot_accuracy": round(slot_accuracy(d, k, trials=50), 4),
                "slot_width": d // k,
            }
            ext_rows.append(row)
            print(
                f"   d={d:5d} k={k:3d}  hrr={row['hrr_accuracy']:.4f}  "
                f"slot={row['slot_accuracy']:.4f}  (slot width {row['slot_width']})"
            )

    payload = {
        "experiment": "tensor-embedding-v1",
        "arm": "A",
        "extension_sweep": {
            "note": "added after the frozen grid saturated; not part of the frozen spec",
            "trials": 50,
            "rows": ext_rows,
        },
        "vocab": VOCAB,
        "trials": TRIALS,
        "numpy": np.__version__,
        "elapsed_seconds": round(time.time() - started, 2),
        "rows": rows,
        "min_dimension_for_99_percent": verdict,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_a.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nwrote {OUT / 'arm_a.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
