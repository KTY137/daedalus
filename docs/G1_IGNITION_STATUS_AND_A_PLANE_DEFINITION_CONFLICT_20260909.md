# Gate 1's ignition slice is green at HEAD — and the Twin contradicts my type-plane refinement

`[MEASURED 2026-09-09 on origin/main 094f3567, frozen detached worktree]`
Classification: `EXPERIMENT` (measurement of an existing slice; nothing built).
**Decides nothing. Closes no gate. Promotes nothing.**

## Part 1 — the Renovation obligation, measured

Plan §12 says *"The Renovation ignition slice remains an active obligation."*
I had spent the day on Gate-2 research and never measured it. Three consecutive
`python -m daedalus.ignition` runs in a frozen worktree at `094f3567`:

| receipt field | value |
| --- | --- |
| `replay.replay_demonstrated` | **true** |
| `replay.previous_run_complete` | true |
| `replay.same_evaluator_bundle` | true |
| `blockers` | **[]** |
| `execution_blockers` | **[]** |
| `work_item_ids` | `wi-000-c41495030c8f`, `wi-001-c8c563f2c0da` |
| attempt leases | both `lease_outcome: COMPLETED`, `lease_id` non-null |
| `check_kinds` | `link`, `pytest`, `schema` — all passed |
| `promotion.status` | `nominated, not promoted` |

Against Gate 1's own words — *"Ikarus produces one MissionContract; the four
planes produce two typed WorkItems; attempts run in isolation; restart/replay
works; tests, schema checks, and link checks produce an EvidencePacket. No
auto-merge."* — every clause is satisfied by this receipt.

The fixture covers the three file kinds the gate names, plus a schema:

```
src/ignition_app/models.py, repository.py     Python
wiki/Event.md                                 Markdown
data/events.csv                               CSV
schemas/event.schema.json                     JSON Schema
```

**What this does NOT do.** It does not close Gate 1. §11's Gate-1 text also
carries the Genesis and general-assistance strands, and closure is an owner
decision on evidence, not a green receipt. Run 1 exits non-zero by design (its
bundle differs from the committed receipt's); replay needs three runs. The
three local preconditions — armed killswitch, an existing spine ledger, a
frozen tree — are fail-closed behaviour, not defects, and are undocumented in
the repository.

## Part 2 — the correction, and it lands on my own packet

`G2-TYPEPLANE-01` (committed `1275e1d4`, two hours ago) refined the
`forest_v2` plane rule so that a path ending `.schema.json` becomes the **type**
plane. The ignition receipt shows the Project Twin doing the opposite:

```
type:field:src/ignition_app/models.py#Event.bias_voltage      <- a .py file
data:schema-field:schemas/event.schema.json#bias_voltage      <- a .schema.json file
data:field:data/events.csv#bias_voltage
```

**The Twin compiler assigns planes by semantic role.** A Python file yields a
`type:` node (a field's declared type); a JSON Schema file yields a
`data:schema-field:` node. `forest_v2`'s task set assigns planes **by file
suffix**, and my refinement mapped `.schema.json` to `type` — which is the
opposite of what the Twin does with the same file.

So the refinement was not merely insufficient. **It pointed the wrong way**, and
the system's own compiler is the evidence.

### What this means for the earlier findings

`taskset.py::PLANE_BY_SUFFIX`'s comment said it plainly and was more right than
I credited:

> the Type plane has no file-level representative at all

Types in this repository live **inside** code files, as annotations. That is
what the Twin extracts and what `s02_types` has been measuring all along
(46,882 type-name sites, 7,052 functions). A suffix map cannot reach them,
because the type plane is not a property of a *path*.

`G2-TYPEPLANE-01`'s conclusion — *"the Type plane is dominated by creation
events, and a retrieve-from-the-pre-image task is blind to creations"* — is
still true of the artifact it measured, but it is **no longer the primary
reason** the forest_v2 type plane is empty. The primary reason is prior and
simpler:

> `forest_v2` classifies planes by file suffix, and the Type plane is not a
> file-level property in the Twin's own model. The two instruments use
> **incompatible definitions of "plane"**, and every forest_v2 result is about
> the suffix definition, not the Twin's.

`G2-TYPEPLANE-01`'s refinement should be read as **withdrawn on the merits**.
Its acceptance-step-2 proof (frozen artifacts unmoved) and its creation-event
measurement stand; its plane assignment does not.

### What is NOT overturned

The twelve retrieval measurements (four arms × three subjects, all negative
against pooled BM25) are unaffected. They compare arms **within** the
suffix-defined instrument, and every arm shares that definition, so the
comparison is internally valid. What changes is the scope of the claim:

> They are results about **suffix-partitioned lexical retrieval**, not about
> the Project Twin's planes.

That is a narrower claim than `CONFIRM-04` made, and the narrowing is mine to
absorb: `CONFIRM-04` said "plane-conditioned retrieval, as instrumented here,
provides no measurable benefit" — the qualifier *as instrumented here* was
carrying more weight than I knew when I wrote it.

## The obvious next instrument, named but not built

A retrieval task whose planes come from the **Twin compiler** rather than from
a suffix map. The compiler already emits `type:`, `data:`, `code:` and
knowledge nodes with source locators (`daedalus/twin/`), and the ignition
receipt shows it working on a four-file fixture. Nothing in this programme has
ever used it as the plane oracle.

That is a substantially larger packet than a suffix refinement, and it is the
one that would actually test plan §5. It is named here rather than started, so
the next iteration begins from a measured position instead of a fresh guess.

## Reproduction

```
git worktree add --detach <frozen> origin/main
python -m daedalus.spine.killswitch arm "<note>"          # per-checkout permit
python -c "from daedalus.spine.ledger import SpineLedger; \
           from daedalus.spine.picker import resolve_spine_db_path; ..."   # create the ledger
python -m daedalus.ignition        # x3; run 1 exits 1 by design
```

`resolve_spine_db_path` now lives in `daedalus.spine.picker`, not
`daedalus.spine.offload_lease` — the module moved and the recipe I had recorded
was stale.
