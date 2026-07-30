"""HAZARD I5a — ambiguity that is UNDECIDABLE, not merely inconvenient.

``Result`` is bound by a try/except ImportError pair, so WHICH ``Result`` this
module means is a property of the runtime environment, not of the source. Two
imported modules declare the name; nothing in the text picks one.

The required behaviour is NO EDGE, counted into ``types.coverage.ambiguous``.
"Deterministic" is not "correct": ``resolve`` takes the first sorted import, so
a naive implementation emits a stably reproducible edge to ``result_alpha`` on
every run, in every process -- a false edge with a determinism test to protect
it. This is the same refuse-to-guess rule ``markdown.py`` already applies to
unresolvable links.
"""
try:
    from result_alpha import Result
except ImportError:  # pragma: no cover -- the ambiguity IS the fixture
    from result_beta import Result


def consume(outcome: Result) -> str:
    return repr(outcome)


def produce(flag: bool) -> Result:
    raise NotImplementedError(flag)
