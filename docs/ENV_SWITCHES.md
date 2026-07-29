# Environment switches

Every environment variable this codebase reads, in one place, because a switch
nobody wrote down is a switch nobody can reason about. The architecture drift
gate (`daedalus map --check`) compares this list against the code and reports
both directions — a variable the code reads and this file does not name, and a
variable this file names that no code reads.

**The column that matters is the last one.** A switch that only changes a path
or a worker count is bookkeeping. A switch that turns a safety property OFF is a
different kind of object, and this repo has been bitten by exactly that shape:
`lane="trusted"` was chosen from a provider NAME while the endpoint came from
`OLLAMA_HOST`, so setting one variable silently converted a no-egress lane into
a network one, with no code change, no flag and no log line.

Unless stated otherwise, an unset variable means the built-in default, and an
unparseable value is treated as unset rather than as zero.

## Safety and spend

| variable | default | what it does | weakens a guarantee? |
|---|---|---|---|
| `DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS` | unset (off) | Permits `daedalus web` to bind a non-loopback address. Without it a non-loopback bind is REFUSED before the server is constructed, and the refusal names the address — there is no silent downgrade to loopback. | **YES.** Requires `DAEDALUS_WEB_TOKEN` as well; the escape hatch cannot be opened without authentication. ADR-002 rejected a whole subsystem for shipping an unauthenticated server. |
| `DAEDALUS_WEB_TOKEN` | unset | Bearer token required on every request once remote clients are allowed. Must be ≥32 characters; compared with `hmac.compare_digest`. Loopback is unaffected and needs no token. | Enables the above. Never log it. |
| `DAEDALUS_KILLSWITCH` | `%LOCALAPPDATA%/daedalus/control/<repo-digest>/killswitch` | Path to the run PERMIT. The loop runs only while that file holds the exact token `RUN`; absence, an unreadable file, or any other content means STOP. Deliberately a permit and not a stop-file: `Path.exists()` returns False both for "not there" and for "the ACL denies you", i.e. it answers *continue* exactly when the machine is least trustworthy. | **YES if pointed somewhere a candidate can write.** Under containment the control directory is a sibling of the worktree root, so `(OI)(CI)Low` inheritance cannot reach it; measured. |
| `DAEDALUS_BUDGET_USD` | `5.00` per period | Hard spend ceiling. Unset is NOT infinity. An unparseable value is a refusal, not a default. | Raising it raises the cap. Setting it does not disable the cap. |
| `DAEDALUS_BUDGET_MAX_CALLS` | `40` per period | Second axis, because price is what we are least sure of and call count is what we are most sure of. Free local calls do not consume it. | As above. |
| `DAEDALUS_BUDGET_ON_UNKNOWN` | charge `$5.00` | `refuse` makes an unpriceable call a refusal instead. An unknown price is never treated as free. | Leaving it unset is the permissive setting. |
| `DAEDALUS_BUDGET_LEDGER` | under the repo's runs directory | Where the spend ledger lives. A corrupt or unwritable ledger is a REFUSAL, not a reset. | **Deleting the file resets the period.** It is a plain file with no HMAC; same class as any file-backed counter. |
| `DAEDALUS_BUDGET_PERIOD` | daily | Rollover window. In-flight reservations survive a rollover. | Lengthening it lengthens the window a single ceiling covers. |
| `DAEDALUS_MIN_FREE_GIB` | `2` | Free-space watermark below which `require_storage` refuses before anything is created or recorded. | **YES.** Lowering it lets attempts run on a volume that may fill mid-write. This machine hit 0.49 GB free during one session and 42 worktree tests failed on it — the watermark did its job. |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | The Ollama endpoint. **The lane is decided from the resolved HOST, never from the provider name** (`sensitivity.lane_for_host`): numeric loopback and all of `127.0.0.0/8` are trusted, everything else is not, and the string `localhost` is REFUSED because a resolvable name is a check-then-use window with egress at the end of it. | Pointing it off-machine moves the lane to untrusted, which is correct and is applied automatically. |

## Behaviour

| variable | default | what it does |
|---|---|---|
| `DAEDALUS_LATENT_ROUTE` | on | `0`/`false`/`no`/`off` disables embedding-based role routing; the keyword router then decides alone. The route can never move a task across an egress lane in any case — a lane guard overrules it and records that it did. Pinned to `0` in `tests/conftest.py` so stage-1 routing is deterministic. |
| `DAEDALUS_INDEX_DOCUMENTS` | off | Indexes markdown as first-class Forest nodes. Off by default because it raises `total_tokens` ~17 %, and that is the distill ratio's DENOMINATOR — every existing `reduction_pct` would improve with the slicer not one line better. |
| `DAEDALUS_VECTOR_INDEX` | off | Lets the memory writer maintain the vector index inline. The projection worker (`python -m daedalus.memory.projection_worker`) is the supported path and records the journal watermark that makes freshness answerable. |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model. Changing it changes the `index_id`; an identity anchor refuses with `model_drift` if the weights behind an unchanged tag move. |
| `OLLAMA_EMBED_MODEL_REVISION` | unset | Partitions the index by a caller-asserted revision. **Leave unset.** The search path resolves it to `None`, so pinning it yields a different `index_id` and makes a perfectly good index invisible. It partitions; it does not authenticate. |
| `CODEX_MODEL` | unset | Model passed to the Codex CLI. |
| `DAEDALUS_SCAN_WORKERS` | CPU-derived | Parallelism of the structural scan. |
| `DAEDALUS_CACHE_DIR` | platform cache dir | Base for on-disk caches. |
| `DAEDALUS_SPINE_DB` | under the repo's runs directory | Spine ledger location. Tests and disposable clones override it. |
| `DAEDALUS_ROOM_FILE` | `<cwd>/.room/room.md` | The council room transcript. Append-only, no access control: everything in it is sent to every participant that speaks afterwards. |
| `DAEDALUS_WEB_DEBUG` | off | Verbose server-side error detail. Do not enable on a bind reachable by anyone else. |
| `DAEDALUS_NVOF_SDK` | unset | Path to the NVIDIA Optical Flow SDK, for accelerator detection. |
| `ROOM_BENCH_HOST` / `ROOM_BENCH_SSH` / `ROOM_BENCH_PROMPT` | see `skills/room` | Bench endpoints for the council room. The bench is off-machine, so the egress fence treats it as untrusted. |

## Documented but not read

`FROZEN_GATE_PATHS` appears in documentation and no code reads it. It is listed
here so the drift gate's report stays actionable: either something should read
it, or it should be removed from the prose that names it. Left standing
deliberately rather than deleted quietly, because the reference is the evidence
that somebody once intended it.
