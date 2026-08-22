# Verification: v-picker

Claims 1-3,5-9 confirmed; claims 4,10,16,17,20 undecidable due to missing code (build_queue, load_work_queue body). No refuted claims.

## Confirmed / actionable

- Add math.isfinite(offset) check in _candidate to reject NaN offset.
- Enforce evidence schema in _candidate (e.g., require specific keys).
- Implement band escalation if offset reaches BAND_SPAN (e.g., promote hotspot to eval_miss band).
- Add test to verify cross-band ordering when evidence warrants (requires escalation first).
- Review OUTCOME_POLICY to not reduce offset for high-importance candidates.
- Add starvation detector alert for low-band candidates pending too long.
- Make eval/hotspot sources cheap by default or add warning when disabled.

## Verdicts

- CONFIRMED: 1 High-band starvation possible due to band gaps > BAND_SPAN.
- CONFIRMED: 2 No band escalation mechanism.
- CONFIRMED: 3 Default cheap sources skip eval/hotspots as per docstring.
- UNDECIDABLE: 4 Work_queue disabled by default? Need build_queue logic.
- CONFIRMED: 5 Outcome memory reduces offset for failed attempts per docstring.
- CONFIRMED: 6 Docref high band but limited scope per docstring comments.
- CONFIRMED: 7 Unvalidated evidence structure; _candidate only checks non-empty.
- CONFIRMED: 8 Silent config masking: _project_config returns None on non-Mapping.
- CONFIRMED: 9 NaN propagation possible via _clamp on NaN offset leading to NaN score.
- UNDECIDABLE: 10 TOCTOU on queue file read; load_work_queue body missing.
