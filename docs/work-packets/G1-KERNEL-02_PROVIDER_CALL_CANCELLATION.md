# G1-KERNEL-02 — A running provider call the kill switch can reach, without inventing a deadline

Packet ID: G1-KERNEL-02

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247

Working-tree context: isolated worktree `.claude/worktrees/agent-a2f761e27e84b8473`, branch `loop/lane2-provider-cancel`, own `.venv` (CPython 3.13.14)

Dependencies: `G1-IKARUS-26_COMPUTER_LOOP_LIVE` (the live measurement that exposed the hang), Revision 10 (`unbounded_execution`), Revision 12 (general computer assistance)

Origin: Codex's ruling in the room (2026-09-05, 16:49) that cancellation *during* a running provider call deserves its own packet, and the Momus critique of 18:15 that named the four conditions such a design has to meet.

## Primary acceptance claim

`providers/_openai_compat.chat_completion` and `chat_raw` accept an optional
`cancelled()` probe. With one, a request that is already in flight ends within
seconds of the probe flipping, as a typed `ProviderCancelled`; without one the
call is the blocking call it has always been. No deadline is created, shortened
or hidden anywhere: `timeout_s` still reaches `urlopen` untouched, `None`
included, and the poll interval is granularity, never a cap.

## Scope

In scope: `daedalus/providers/_openai_compat.py` (new `ProviderCancelled`,
`DEFAULT_CANCEL_POLL_S`, `_poll_interval`, `_budget_explicit_bridge`,
`run_cancellable`, `_send` split out of `_post`, probe keywords on `_post`,
`chat_raw`, `chat_completion`; a residual note on `chat_stream`), new
`tests/providers/test_openai_compat_cancellation.py`, this packet and
`docs/evidence/G1-KERNEL-02_PROVIDER_CALL_CANCELLATION/`.

Out of scope and deliberately untouched: `daedalus/orchestration/ikarus/shell.py`
and `computer_loop.py` (other lanes — this packet only *describes* the wiring,
below), `daedalus/providers/_ollama_native.py` (the native offload transport,
same hole, named as a residual), `daedalus/providers/ollama.py` (in this lane
but needing no change: it reaches the model through `_ollama_native.native_chat`,
not through this module), `chat_stream`, `runtimes/providers/execution_policy.py`,
`kernel/policy/limits.py`, the ledger, and every cap axis.

Not done, on purpose: **no new cap axis.** Momus is right that
`LIMIT_AXES` is a final eight-tuple with exact key matching
(`kernel/policy/limits.py:35`) and that every ledger row carries
`configured/effective_limit_axes`, so a `provider_liveness` axis is
constitutional text plus a ledger migration — an AMENDMENT under section 16,
not a packet. Nothing here touches those tuples. Cancellation is the kill
switch reaching further, and the kill switch is explicitly not a cap
(plan 4.1).

## Contracts and behavior

**`ProviderCancelled(RuntimeError)`** — new, and deliberately *not* a subclass
of `ProviderHTTPError`. A caller that catches the HTTP error means "the vendor
failed"; the kill switch working is not that. It is also not a timeout: nothing
in this module decides how long a call may run.

**`chat_completion(..., cancelled=None, poll_interval_s=None)`** and
**`chat_raw(..., cancelled=None, poll_interval_s=None)`** — `cancelled` is a
zero-argument predicate. `None` (every caller in the tree today) takes the
unchanged blocking path: `_post` calls `_send`, which is the previous body of
`_post` verbatim, on the calling thread.

**`run_cancellable(work, *, cancelled, poll_interval_s, name)`** — runs `work`
on a daemon worker thread and waits on an `Event`, asking `cancelled()` between
waits. A probe that is already True refuses *before* a connection is opened, so
a cancelled mission does not buy one more reservation. A reply that lands during
the same interval is returned rather than paid for and discarded.

**Why the blocking call moves and the watcher does not.** The obvious shape is
the mirror image — keep the request on this thread, have a watcher tear the
socket down — and it is the shape Momus costed. Inverting the roles removes
both of its problems instead of solving them, and needs neither a socket handle
nor a portable way to wake a thread parked in `recv`. The honest cost is stated
in the code: cancelling *abandons* the worker. The request runs until the peer
answers or the process exits and its result is discarded, so a cancelled call
must never be retried.

**`DEFAULT_CANCEL_POLL_S = 0.2` is not a cap.** It bounds how long a
cancellation takes to be *noticed*, not how long a call may run. While the probe
stays False the call waits exactly as long as `timeout_s` allows, and
`timeout_s=None` still means no deadline at all. Raising it delays the kill
switch; it can never end a call. `poll_interval_s <= 0` is refused, because zero
would busy-spin and neither value is a way to express "no cap" — a False probe
already is that.

**The existing chokepoint keeps its monopoly.** How long a call may run is
answered in exactly one place,
`runtimes/providers/execution_policy.provider_http_timeout`, whose docstring is
"never encode unlimited as a number". This packet adds a second *question*
("who may stop it"), never a second answer to the first one. `_send` documents
that and passes `timeout_s` through untouched.

**Ledger.** `budget_process` suppresses a duplicate reservation with a
`threading.local()` depth counter, so a call made from a worker thread would
look unreserved and be booked a **second** time whenever the caller had already
reserved explicitly (`budget.spend`). `_budget_explicit_bridge` captures the
mark on the calling thread and re-enters it on the worker. A failed import is
not fatal — without the interposer there is no mark to carry.

**What a worker thread does not move.** Three things a reviewer should check
and which are unchanged. (1) The egress fence, provider admission, lane guard
and secret floor all run *before* the request is built, on the caller's thread
(`shell._provider_start` and the provider's own admission); nothing about them
is reached from the worker. (2) The budget interposer replaces
`urllib.request.urlopen` as a **module global**, so the worker's call is
guarded like any other — pinned by
`test_a_cancellable_call_is_reserved_exactly_once`, which runs the real
`install_process_guard`. (3) `_budget_explicit_bridge` imports two private
names from `daedalus.budget`, the declared stable effect facade that already
re-exports them. That coupling is guarded rather than hoped: if either name is
renamed upstream the import fails, the bridge silently degrades to a no-op —
and `test_a_call_inside_an_explicit_reservation_is_not_reserved_twice` goes red,
which is exactly what mutation A demonstrates.

**Bound on the abandoned worker.** One thread and one socket per *cancelled*
call, released when the peer finally answers. Because a cancelled call must not
be retried and a cancelled mission ends, the count is bounded by the number of
cancelled missions in a process, not by attempts.

## Acceptance matrix

Host: Windows 11, CPython 3.13.14, worktree `.venv`, box shared with nine other
lane agents. No number below is offered as a performance measurement; the
discriminating claim is always "seconds, not the server's delay".

| Check | Result (2026-09-05) |
| --- | --- |
| the 16 new tests against the base file (585b7ea4) | 1 collection error: `ImportError: cannot import name 'DEFAULT_CANCEL_POLL_S'` — the contract does not exist |
| the 16 new tests with the change | 16 passed, 24.5 s |
| control: `test_the_same_call_without_a_probe_is_not_interruptible` | passes — the un-probed call is still parked after 3 s against the same server |
| mutation A: `_budget_explicit_bridge` returns a no-op | `test_a_call_inside_an_explicit_reservation_is_not_reserved_twice` FAILED: "the same call was reserved again: ['remote_inference']" (1 failed, 1 passed) |
| mutation B: the in-flight `cancelled()` check removed | both cancellation tests FAILED "DID NOT RAISE ProviderCancelled" after ~60 s each (2 failed in 139.5 s) — Momus's "hang or fall" |
| mutation B, second finding | it also exposed a real defect in the tests themselves: a `_FlipAfter` probe built *before* the server fixture could already be True at the pre-flight check, so the test would have passed without ever reaching an in-flight call. Probes now start after the server is up and the tests pin *which* refusal fired |
| rejected design measured (slice reads under a short socket timeout) | 4043-byte reply, second half late: slice loop returned **0** bytes, 1 socket timeout, 4043 dropped, and the retry raised `OSError: cannot read from timed out object` |
| providers, council and the provider-adjacent files (12 targets) | 295 passed, 15 subtests passed, 332.6 s |
| the budget register and its drift detector (4 files) | 191 passed, 11 subtests passed, 34.4 s |
| `tools/index_work_packets.py --render` after `git add` | exit 0, JSON; G1-KERNEL-02 present with all six required sections |
| the Gate-0 static conformance scanner (`test_effect_boundary.py`, `test_cli_effect_boundary.py`) | 92 passed, 206.7 s. Checkable rather than hopeful: the only new call inside a scanned package is `threading.Thread`, which is not in `_HIGH_IMPACT_CALLS`; no entrypoint was added; and the test file's `ThreadingHTTPServer` is invisible because `SCAN_PACKAGES` is `("daedalus", "tools", "runs")` |
| not run | `tests/test_ikarus_shells.py` (Lane 5 owns it, known order dependency) and the eval/kairos suites, which reach `chat_completion` only through fakes |

## Migration and rollback

Purely additive. Every existing caller passes no probe and takes a code path
whose statements are unchanged; no stored artifact, schema, ledger row, event or
cap axis changes shape. Rollback is deleting the new names, folding `_send` back
into `_post`, and deleting the test file; nothing depends on them yet.

Wiring is a *separate* change in another lane, and is deliberately not done
here. The shape it would take:

1. `shell._ollama` / `shell._deepseek` gain `cancelled: Callable[[], bool] | None = None`
   and forward it to `chat_completion(cancelled=cancelled)`; `shell._llm`
   forwards it from its own signature.
2. `computer_loop._model_proposal` passes a probe. The loop already holds
   everything it needs: `checkpoint()` (line ~424) combines the mission
   `cancelled` callable with `service.check_cancelled()`. The probe must be the
   **non-raising** form of that pair, and should not read the control root five
   times a second — a cached or rate-limited predicate belongs in that lane's
   design, not in the transport.
3. `_ollama`/`_deepseek` currently end in `except Exception: return None`. Even
   unnarrowed the kill-switch case still ends as cancelled, because the loop's
   `checkpoint()` re-reads the switch after the failed proposal and raises
   `_ComputerCancelled`. Narrowing so `ProviderCancelled` propagates is
   nevertheless the honest form, and is the difference between "the provider
   gave nothing" and "we stopped it".

## Evidence, expected failures, and review

Evidence: `docs/evidence/G1-KERNEL-02_PROVIDER_CALL_CANCELLATION/`
(`slice_read_probe.log.txt` with the rejected design's script and output,
`ollama_v1_keep_alive.log.txt` with the open-item measurement, `suites.log.txt`).
Expected failures retained above: the base-revision collection error, both
mutation runs, and the rejected slice design.

### The four Momus conditions (18:15), answered

**(a) Waking a parked thread — `close()` vs `shutdown(SHUT_RDWR)`, and
`settimeout` as a disguised Daedalus duration.** Does not arise. Nothing here
closes, shuts down or re-times a socket. The thread that is parked in `recv` is
the *worker*, and it is never woken — it is abandoned. The thread that needs to
regain control is the caller's, and it was never blocked on the socket in the
first place; it waits on an `Event` it can stop waiting on. No `settimeout` is
called anywhere, so the covert-cap trap Momus named is not merely avoided, it is
structurally absent.

**(b) `urlopen` yields no socket handle; `resp.fp.raw._sock` is private CPython
API needing its own opener and a version-pinned test.** Also does not arise, and
this is the reason the roles are inverted rather than the watcher being made
cleverer. It is also the reason the *measured* case is covered at all: the hang
in G1-IKARUS-26 was inside `urlopen`, before any response object exists, because
a non-streaming completion sends its status line only once generation has
finished. A watcher has nothing to hold during exactly the window that matters.

Reading the body in bounded slices instead was measured and rejected, not
assumed. On CPython 3.13.14 a 4043-byte reply whose second half is late returns
**zero** bytes from the slice loop — the buffered first half is discarded with
the raising read — and every retry afterwards raises `OSError: cannot read from
timed out object`, because `socket.SocketIO` latches `_timeout_occurred` and
refuses the response object permanently. The design does not merely truncate; it
cannot resume. Script and output are retained.

**(c) A cancellation must not arrive as a `JSONDecodeError` and be read as
"failed".** `ProviderCancelled` is raised by `_post` itself, is not a
`ProviderHTTPError`, and is pinned by
`test_a_cancellation_is_not_a_provider_http_error`. Two further tests pin that a
timeout and an HTTP error keep the *same* exception class and message with and
without a probe, so the new type never displaces an old one.

**(d) The ledger: exactly one settle, no retries.** Tested, not assumed.
`test_a_cancellable_call_is_reserved_exactly_once` runs the real
`install_process_guard` with a counting reserve and gets one reservation and one
settle per call, probe or no probe.
`test_a_call_inside_an_explicit_reservation_is_not_reserved_twice` gets zero,
and fails loudly under mutation A. `test_a_call_already_cancelled_never_opens_a_connection`
pins that an already-cancelled call reaches no socket, so it cannot be reserved
at all. The honest residual: because the worker is abandoned, the guard's
`res.settle()` in its `finally` runs when that thread finally unwinds — late,
never missing while the process lives, and conservative in the safe direction
(the reservation stands at its estimate until then). "A cancelled call must not
be retried" is stated in `run_cancellable`'s docstring and above; it is not
enforced by this module, because the retry decision belongs to the caller.

### On the sham thermometer

Momus is right that `tests/test_ikarus_computer_loop.py:286`
`test_stream_cancellation_reaches_inflight_computer_planner` passes against a
transport that was never blocked. That file is Lane 1's and is untouched here.
The equivalent honest thermometer at this level is
`test_the_same_call_without_a_probe_is_not_interruptible`: same loopback server,
same `timeout_s=None`, no probe, and the call must still be parked after
seconds — plus mutation B, which shows the cancellation tests hang for the
server's full delay once the probe check is removed. The loop-level thermometer
Momus specified (kill switch, `unbounded_execution`, state `cancelled` within
N s, one settle, zero retries) becomes writable only once a caller passes a
probe, and belongs in the wiring change described above.

### Open item, measured: the `/v1` shim drops `keep_alive` and `num_ctx`

Pythia's hypothesis (room, 18:25) was that the computer loop's ~74 s per planner
call is a *routing* effect, because the planner reaches this module through
`shell._llm -> _ollama -> chat_completion` — the OpenAI-compat `/v1` shim —
while the native offload path sets `keep_alive_value()`. Measured on this box,
Ollama 0.33.3, `qwen2.5-coder:7b`, using `/api/ps` `expires_at`:

| Call | `expires_at` | `context_length` |
| --- | --- | --- |
| `POST /v1/chat/completions` with top-level `keep_alive: "30m"`, `max_tokens: 1` | +5m00s (Ollama's default) | 4096 |
| `POST /api/generate` with `keep_alive: "30m"`, `options.num_ctx: 6144` | +30m00s | 6144 |

Both fields are dropped by the shim, confirming the docstring at
`_openai_compat.py:132-134` against the current Ollama version. The `/v1` call
did more than fail to extend the TTL: it **evicted and reloaded** the
natively-warmed 6144-context instance at the 4096 default, and the one-token
completion took 39 s. So the eviction Pythia suspected is real and is a routing
consequence, and the planner is additionally running in a 4096-token window it
did not ask for.

It is **not fixed here**, and not because it is small: the fix is not available
in this module. Ollama's shim ignores the fields no matter what this client
sends, so the only real repair is to route the planner through
`_ollama_native.native_chat` — `shell.py` and `_ollama_native.py`, both outside
this lane — and that is a different architectural axis with a different primary
claim (section 10: one packet, one axis). Recorded as an open item with the
numbers above so whoever takes it starts from measurement.

Caveat on this measurement: nine other agents share this box and one of them was
independently probing the same endpoint, so an intervening call could in
principle have reset a TTL. The two rows were taken 70 s apart, both `+Xm00s`
exactly, and they disagree in the predicted direction, so the confound would
have to be adversarially well-timed to produce them.

### Other residuals, named rather than half-fixed

- `chat_stream` is **not** cancellable. A stream yields between frames, so a
  caller already regains control on every delta, but a peer that stalls
  mid-stream still parks the generator. Covering only the `urlopen` window would
  advertise a cancellation that works only before the first token, which is
  worse than none. Wiring it needs a producer thread and a queue, on
  `run_cancellable`.
- `_ollama_native.native_chat` — the native offload transport — has the same
  `urlopen(timeout=None)` hole and is outside this lane. `run_cancellable` is
  written to be reused there without duplication.
- `codex_cli.py:370` passes the same `None` to `subprocess.run`, so a second
  hanging path exists that this packet does not touch at all.
- Under `unbounded_execution`, until the wiring lands, kill-switch latency is
  still bounded only by provider goodwill. This packet makes the mechanism
  exist; it does not yet make the loop use it.

Review questions: is `0.2 s` the right default poll interval when the probe may
read the control root from disk (the caller's cached-predicate problem, or a
cheaper one this module should not decide)? Should `run_cancellable` refuse to
start a second call while an abandoned worker from the same caller is still
running, or is "do not retry" correctly left to the caller?

Iron Plan: **ALIGNED**

Iron Gate: **1**

Evidence: 16 new tests (16 passed; base revision cannot import the contract), two mutation runs, one rejected-design measurement, one open-item measurement

Automatic merge/promotion: **forbidden**
