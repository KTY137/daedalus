"""EXPERIMENT s11 -- the first genuine cross-plane score-fusion retriever.

See ``fusion_retrievers.py`` for the mechanism and ``experiments/forest_v2/
README.md``'s "Continuation (2026-08-24): the first real fusion retriever"
section for the frozen sub-spec, the run and the measured verdicts on plan
kill criteria 14.1 and 14.3.

Pure stdlib.  Reads ``experiments/forest_v2/s09_eval``'s own retriever
contract types (``Candidate``, ``QueryView``) and its plane-suffix map
(``taskset.plane_of``) rather than re-deriving either -- consolidation over
a second implementation, per this repository's own constitution.  Nothing in
``daedalus/`` imports this, and nothing here imports ``daedalus/``.
"""
