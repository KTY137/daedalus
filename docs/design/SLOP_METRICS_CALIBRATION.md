# Calibration run 1 — can slop be measured?

2026-07-30 · first beat of `docs/design/GUI_LANE_PLAN.md`
Captured with `daedalus/gui/probe.js` (Node Playwright from `apps/web`, deterministic:
motion paused, clock frozen, `Math.random` stubbed, fonts settled), scored with
`daedalus/gui/lint.py` (stdlib only). Raw evidence: `runs/gui/report.json`.
Viewport 1440×900, dark scheme.

## The corpus (n=4, all verdicts the owner's own words)

| Label | What it is | Verdict |
|---|---|---|
| `live-app` | the shipped `apps/web` after Codex's revamp | *"still looks like ai slop"* |
| `daedalus-design-direction` | my paper/serif "instrument and notebook" | *"Ne sieht nicht gut aus. Immernoch wie AI slop"* |
| `ikarus-hud` | first HUD attempt | interim, no verdict |
| `daedalus-forge` | the graph-as-hero projection | *"ja ist gut"* |

## Results

```
METRIC                  T   live-app  paper-serif  ikarus-hud  forge
                            SLOP      SLOP         (interim)   APPROVED
horizontal_overflow     A          0            0           0      0
contrast_failures       A        228            8          18     14
small_targets           A         60            1           3      6
banned_faces            A          0            0           0      0
console_errors          A          1            1           1      1
visible_elements        B        681           74         137    115
framed_panels           B         92            6          13     15
distinct_radii          B          7            2           0      0
panel_nesting_depth     B          6            3           2      2
allcaps_text_share      B       17.5         10.3        39.8   32.1
status_pills_visible    B         24            0           0      0
largest_equal_tile_row  B         10            2           6      7
accent_hue_families     B          3            2           5      4
identifier_leaks        B          6            1           0      0
```

## What separates — keep these

Eight metrics put the rejected `live-app` far from the approved `forge`, in the direction the
human verdict predicted:

| Metric | slop | approved | ratio |
|---|---|---|---|
| `status_pills_visible` | 24 | 0 | absolute |
| `framed_panels` | 92 | 15 | 6.1× |
| `visible_elements` | 681 | 115 | 5.9× |
| `identifier_leaks` | 6 | 0 | absolute |
| `panel_nesting_depth` | 6 | 2 | 3× |
| `distinct_radii` | 7 | 0 | absolute |
| `contrast_failures` (A) | 228 | 14 | 16× |
| `small_targets` (A) | 60 | 6 | 10× |

The strongest single signal is **`status_pills_visible`: 24 versus 0.** That is the honesty
doctrine turned into visual noise, and it is measurable to the element.

**Independent of taste**, the Tier A numbers on the shipped app are a real accessibility
defect: **228 text elements below WCAG AA contrast** and **60 interactive targets under
44×44**. Those want fixing whatever happens to the visual direction.

## What was falsified — these rules are wrong and are retired

Being wrong here is the useful part; a proxy that survives only because nobody checked it is
worse than no proxy at all.

**`allcaps_text_share` — inverted, retired.** I predicted shouted micro-labels mark slop.
The approved design scores **32.1%**, nearly double the rejected app's **17.5%**. In an
instrument surface, all-caps mono labels are the native vocabulary — they are *correct* there.
The hypothesis was a transplant from editorial design and the data killed it.

**`accent_hue_families` — inverted, retired as written.** Approved uses **4** hue families,
rejected **3**. The rule conflated *semantic* colour (ice = structure, amber = live,
oxide = failed, lime = passed — four states, four hues, all load-bearing) with accent
proliferation. Any replacement must count only *non-semantic* hues, which means the palette
has to declare which hues are semantic before the rule can run.

**`largest_equal_tile_row` — too noisy to use.** 10 versus 7 is not separation, and the
detector fires on incidental co-alignment (rim panels sharing a width) rather than on the
metric-tile trope. Either it needs to require numeric content in every tile, or it goes.

## Inert — not yet usable

**`banned_faces` = 0 everywhere.** It did not fire even on the app it was written for. Either
that app genuinely avoids the banned faces, or the check is too narrow (it inspects only the
first family in `font-family`, so `system-ui, Inter, …` slips past). Unverified either way,
therefore currently worthless.

**`console_errors` = 1 everywhere.** An identical benign error on all four surfaces, so it
discriminates nothing until the known-benign set is filtered.

## Honest reading

**8 of 14 metrics track the human verdict; 3 are falsified, 2 inert, 1 noisy.** For n=4 that
is a better hit rate than this idea deserved, and it is enough to say the direction works:
"looks like AI slop" does have measurable correlates, and the strongest of them —
simultaneous status pills, framed-panel count, nesting depth, leaked identifiers — are
exactly the things a critic names in prose.

What it is **not**: calibrated. Four samples, one of them unlabelled, one viewport, and the
two "slop" samples differ from each other far more than either differs from the keeper on
several metrics (the paper-serif design scores *better* than the approved one on panel count
and nesting — it was rejected for reasons this linter cannot see, namely being the wrong
visual world entirely). **No threshold in here may gate anything yet.** Every number above is
stamped MEASURED for the sample and ASSUMED for any threshold derived from it.

The linter also cannot see the thing that actually got two designs rejected: whether the
surface belongs to the product at all. That stays a human judgement, and the lane's design
already says so — Tier C judges, Tier C never promotes.

## Next

1. Grow the corpus. Every future surface gets captured and labelled at review time; that is
   free and it is the only path to real thresholds.
2. Add viewports (375 / 768 / 1024) — `probe.js` already takes them; overflow and target-size
   rules only earn their keep on narrow screens.
3. Fix the two inert rules or delete them.
4. Rewrite `accent_hue_families` to take a declared semantic palette as input.
5. Fix the Tier A findings in `apps/web` — 228 contrast failures is a defect report, not a
   design opinion.
6. Only then consider promoting one Tier B rule from advisory to blocking, on the strength of
   its own agreement record.
