# G0-FLT-07A adversarial review findings

This review is independent of the contract builder and is not an approval or Gate evidence.

## Open finding FLT-07A-R1

The current verifier requires every expected durable marker and rejects explicitly forbidden markers, but it still permits unlisted markers. That is weaker than an exact durable-state contract: an unexpected durable mutation could coexist with all expected markers and avoid the forbidden set.

The dependent process-kill harness is frozen until the verifier requires exact equality between the observed durable-marker set and the scenario's expected durable-marker set, or the manifest introduces a separately reviewed explicit allowed-extra set. No dependent execution packet may treat the current subset check as passing fault evidence.

## Closed findings prepared in the current packet

- injection fingerprints are derived from exact source revision, scenario ID, and injection point;
- source, harness, runtime, and toolchain identities are bound;
- restart policy and process-termination observation are checked;
- duplicate, missing, and extra scenario IDs are rejected;
- run artifacts are unique per scenario;
- Primary Checkout before and after digests must match;
- automatic re-execution and LLM hard evidence are forbidden;
- a superficially passing verification receipt is reverified before projection.

`closed=false` remains mandatory.
