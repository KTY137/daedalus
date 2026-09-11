"""Provider execution: what is invoked, how it is bound, and what came back.

WHY A SUBPACKAGE. Twenty-five modules under ``daedalus/runtimes/`` shared the
``provider_`` prefix, which is a package spelled with underscores. Fourteen of
them are one strongly connected import component -- the largest in the tree --
so the grouping is not a matter of taste: the modules already behave as a unit
and only the directory disagreed. The prefix is dropped because the package now
carries it; ``daedalus.runtimes.provider.invocation_abi`` says once what
the old flat name said twice.

FOUR FAMILIES LIVE HERE, and their names are the map:

* ``executable_*`` -- what the runtime is allowed to spawn, admitted before use;
* ``invocation*`` -- one call: identity, authority, ABI, payload, resolution;
* ``observation*`` -- what came back, and where it is stored;
* ``target_*`` -- receipts, retention and verification for a provider target.

WHAT DOES NOT LIVE HERE. ``daedalus.runtimes.providers`` (plural) is a different
thing and stays where it is: it owns the provider CATALOGUE, personas, contracts
and token policy -- configuration and shape, not execution. The two are one
letter apart and the distinction is worth the sentence: singular is the act,
plural is the roster.

This package holds no policy of its own. Admission, budget and containment stay
with the kernel and spine contracts it calls into.
"""
