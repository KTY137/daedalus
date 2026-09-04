# G1-IKARUS-14 — Stream interruption without provider replay

## Scope

This bounded Gate-1 reliability slice closes the server-side half of the Ikarus
stream no-replay contract on the canonical `g1/ikarus-runtime-invocation-binding-07d3`
line. The browser half is already present: an interrupted stream is rendered as
halted and is not retried through the blocking POST path.

Once `_ask_stream_inner(...)` has entered a real provider streamer, an empty or
failed stream is an unknown delivery outcome. The provider request may already
have committed remotely, so Ikarus must not invisibly call `_chat(...)` again.
The existing `streamer is None` branch remains a capability fallback for providers
without a verified streaming transport because no streaming request was attempted.

## Acceptance

- Mid-stream provider failure retains partial text, marks `stream_interrupted=true`,
  and never calls the blocking provider path.
- An empty provider stream emits a halted/interrupted final and never calls `_chat`.
- The final says the request was not automatically retried.
- Existing Ollama single-transport `keep_alive` semantics remain intact.
- No new provider, executor, queue, authority, or action path is introduced.

## Non-claims

This packet does not claim provider cancellation propagation, sealed broker cutover
on this branch, Hermes superiority, or a Gate transition. It removes one duplicate-
execution ambiguity from the conversational transport only.
