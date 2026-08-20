# chemlab (fixture 3 of higher-twin-nc-v1)

Five-field four-plane project used as intervention substrate:

- Code plane: `calib.py` (calibration pipeline), `checks.py` (behavior checks)
- Type plane: `schema.json` (field names, types, units)
- Data plane: `data/events.csv`
- Knowledge plane: `docs/fields.md` (generated-canonical field reference)

Documented contract (knowledge plane), COMPLETE by construction:
`calibrated = A_COEF * reagent_a + B_COEF * reagent_b + C_COEF * catalyst
+ OFFSET`. Purely additive, every read declared, no hidden coupling.
`temperature` is read by nothing (inert control).

Purpose (experiment record, watchdog slice 2): the SPECIFICITY fixture.
The chemlab operator profile targets pairwise distinct fields, so the
standard matrix is expected to be the strongest possible null table —
every pair commutes tree-identically, k = 0 everywhere, zero anomalies,
and more certified-disjoint pairs than sensorlab/pumplab. A single
anomaly on this fixture would be a false alarm of the detector.

The fixture is never mutated in place; the assay runner copies it per run.
`docs/fields.md` is byte-identical to the `regen_docs` operator template so
that doc regeneration is idempotent on the pristine tree (a designed null).
