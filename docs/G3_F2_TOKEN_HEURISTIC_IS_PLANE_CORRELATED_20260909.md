# Gate 3 §F2: the token heuristic is resolvable, and its error is plane-correlated

`[MEASURED 2026-09-09 on origin/main bb412fa9]`
Classification: `EXPERIMENT` (read-only measurement; no production code changed).
**Decides nothing. Opens no gate.**

## What §F2 said

`G3-BASE-01_FROZEN_BASELINE_HARNESS.md`:

> `harness.tokenizer_name()` returns `chars/4 (heuristic)` on this host:
> `tiktoken` is not installed […] A budget denominated in a chars/4
> approximation is not comparable to one denominated in a real tokenizer, so
> this must be resolved […] before any budget-equal claim is made.

## It is resolvable, and the fix is already declared and locked

`tiktoken==0.14.0` is a declared optional extra (`tokenizer`) in `pyproject.toml`
**and present in `uv.lock` with 60 entries**. `uv sync --frozen --extra tokenizer`
installs it with **zero removals** and leaves `uv.lock` and `pyproject.toml`
untouched — verified by dry-run before running it.

After installing:

```
tokenizer_status() -> name='tiktoken/cl100k_base'  exact=True
                      library='tiktoken 0.14.0'    degrade_reason=None
                      bpe_cache_path=<present>
count_tokens('def hello(name: str) -> str: ...') -> 17
```

So the host's degrade path was the *package*, not the BPE cache — the cache was
already there. §F2's blocker is one `uv sync` away on any host whose lock is
current.

## The finding: the heuristic's error is not uniform, it tracks content type

Exact `cl100k_base` tokens versus `chars/4`, over the repository itself:

| corpus | files | exact tokens | chars/4 | ratio | worst per-file |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python source (`daedalus/`) | 119 | 616 606 | 687 237 | **1.115** | 26 % |
| Markdown (`docs/`) | 80 | 268 965 | 262 561 | **0.976** | 26 % |
| JSON (`docs/work-packets/`) | 80 | 107 364 | 109 576 | 1.021 | 20 % |

**`chars/4` over-counts Python by 11.5 % and under-counts Markdown by 2.4 %.**

That is the part that matters, and it is worse than a uniform error would be.
A uniform bias cancels in a paired comparison. **This one does not cancel,
because its sign and magnitude follow the content type — which is the axis a
cross-plane comparison varies.**

Under `chars/4`, a code-plane arm is charged roughly 11 % more tokens than it
actually spends while a knowledge-plane arm is charged about 2 % less. A
"budget-equal" cross-plane comparison run on that measure would hand the
knowledge arm a systematic relative advantage of order **14 percentage points**,
aligned exactly with the variable under test.

Plan §9 requires comparative claims to use "equal budgets"; §14 lists "extra
context tokens explain the whole gain" as a kill criterion. A budget measure
whose error correlates with the plane being compared can manufacture or mask
either outcome.

## Why this matters now specifically

`G3_CROSS_PLANE_UNBLOCKED_AND_A_HOLE_IN_MY_GUARD_20260909.md` measured that
Gate 3's R3 refusal has stopped firing — the corpus gained data- and
knowledge-plane tasks, so a cross-plane comparison is no longer *structurally*
impossible.

That makes §F2 the live blocker rather than a queued one. The comparison R3 now
permits is exactly the comparison this bias would corrupt: code-plane tasks
against knowledge-plane tasks, on a budget measure that treats the two
differently by ~14 pp.

**So: R3 stopped refusing, and §F2 is now the reason not to run it yet.** One
blocker did not so much disappear as hand over to the next.

## What this does not claim

- **Gate 3 is not open.** This measures the instrument, not the comparison. §F3
  (real provider usage discarded before it reaches the harness) and the power
  question — four non-code tasks of 31 — are untouched.
- **No baseline was run**, and none should be until the frozen spec declares
  which tokenizer its budgets are denominated in.
- The ~14 pp figure is the *relative* gap between the two ratios on this
  repository's own files. It is an order-of-magnitude statement about the
  measure, not a prediction of any arm's score.
- `cl100k_base` is OpenAI's tokenizer and the providers here are not exclusively
  OpenAI. It is exact for what it is and a *declared* proxy for anything else —
  which is precisely why `measures.token_usage` records the tokenizer identity
  with every count. Exactness removes the silent approximation; it does not make
  the tokenizer universal.

## Reproduction

```
uv sync --frozen --extra tokenizer      # zero removals; lock untouched
python -c "from daedalus.structcore import tokens; print(tokens.tokenizer_status())"
```
Then, per corpus, compare `len(tiktoken.get_encoding('cl100k_base').encode(text))`
against `max(1, len(text) // 4)` over the file sets in the table.

## A working note, twice earned today

Both times I reached a wrong conclusion in this session's later half, the cause
was the same: reading `C:\Users\Administrator\Desktop\projects\daedalus`, which
sits at `ed0b0432` — **over 200 commits behind `origin/main`** — instead of a
current worktree. It cost a "the document does not exist" and a "tiktoken was
never locked", the second of which I was one command away from publishing.
Measure from a worktree pinned to the revision being discussed.
