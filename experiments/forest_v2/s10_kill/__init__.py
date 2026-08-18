"""EXPERIMENT s10 -- the kill-criteria evaluator for the Forest v2 priors.

Frozen, isolated, read-only.  Master plan section 1 (isolated experiment),
section 10 Gate 2 prework, section 14 (kill criteria), section 15 (amendment
protocol).  Nothing here is production-capable, nothing in the kernel imports
it, and it promotes, gates and blocks nothing.

The plan says a kill result "does not silently delete this plan": archive the
evidence, stop the affected track, submit an amendment.  This package turns
the mechanically checkable part of that judgement into code, so a KILL is a
*computed proposal* with a stated uncertainty rather than a mood.

Layout:

``schema``    the result-record contract this evaluator reads (JSON, not code)
``stats``     paired bootstrap CIs and an equivalence test, pure stdlib
``criteria``  the section-14 bullets as predicates over a ``ResultSet``
``report``    the honest KEEP / KILL / INCONCLUSIVE / NOT_EVALUABLE rollup
``synth``     synthetic result sets for the self-test (values drawn at runtime)
``cli``       ``python -m experiments.forest_v2.s10_kill.cli`` -- prints only

Design constraint worth stating out loud: this package **never imports the
harness that produced its input** (slice s09 or any later one).  It reads
serialised results.  The evaluator being unable to reach into the thing it
grades is the same separation the plan demands between candidate and
evaluator (invariants 3 and 4), applied one level up.
"""

SCHEMA_ID = "forest_v2.s10.kill-input/1"

__all__ = ["SCHEMA_ID"]
