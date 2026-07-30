"""lint.py — turn "it looks like AI slop" into numbers.

Reads a capture from ``probe.js`` and computes metrics over the DOM/CSSOM. No
pixels are inspected; every number here is derived from geometry and computed
style, so it is reproducible and explainable — you can always point at the
elements that produced a count.

WHAT THIS IS AND IS NOT
-----------------------
Tier A metrics (contrast, overflow, target size, banned faces) measure things
that are true or false. They can gate.

Tier B metrics are PROXIES for a judgement no rule can make. "Twenty-five
bordered boxes" is not ugliness; it correlates with a screen that was described
as slop. Each proxy carries its own agreement record, and a proxy that stops
tracking the human verdict gets retired rather than defended. The module is
built so that is easy: every metric returns its count AND the elements behind
it, so a disagreement is inspectable instead of arguable.

Thresholds are stamped ASSUMED until the corpus is large enough to earn
MEASURED. Right now the corpus is n=4 (three rejected surfaces, one approved),
which is enough to set direction and nowhere near enough to gate on.

stdlib only, by design: the capture needs a browser, the rules must not.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Faces that read as a generated default. Not a quality judgement about the
# typeface — a statement about what every AI dashboard already wears.
BANNED_FACES = ("inter", "roboto", "arial", "space grotesk", "geist", "helvetica neue")

# Text that is a leaked internal name rather than something a person would say.
def _looks_like_identifier(t: str) -> bool:
    s = t.strip()
    if not s or len(s) > 60:
        return False
    if s.startswith('{"') or s.startswith('{ "'):
        return True                                   # raw JSON on the glass
    if " " in s:
        return False
    return s.count("_") >= 1 and s.replace("_", "").isalnum() and s.islower()


def _lum(c) -> float:
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast_ratio(fg, bg) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@dataclass
class Metric:
    """One measurement, with the evidence that produced it."""
    key: str
    value: float
    unit: str
    tier: str                      # "A" = objective, "B" = proxy
    note: str
    offenders: list = field(default_factory=list)

    def to_dict(self):
        return {"key": self.key, "value": self.value, "unit": self.unit,
                "tier": self.tier, "note": self.note,
                "offenders": self.offenders[:12]}


def _sel(e) -> str:
    c = (e.get("cls") or "").split()
    return e["tag"] + ("." + c[0] if c else "") + f"@{e['x']},{e['y']}"


def _is_panel(e) -> bool:
    """A framed surface, not a hairline divider or a text run."""
    return e.get("borderSides", 0) >= 1 and e["w"] >= 56 and e["h"] >= 24


def _contains(a, b) -> bool:
    return (a["x"] <= b["x"] and a["y"] <= b["y"]
            and a["x"] + a["w"] >= b["x"] + b["w"]
            and a["y"] + a["h"] >= b["y"] + b["h"]
            and (a["w"] * a["h"]) > (b["w"] * b["h"]))


def analyse(cap: dict) -> dict:
    els = cap["els"]
    ms: list[Metric] = []

    # ── Tier A · objective ────────────────────────────────────────────────
    over = cap["scrollWidth"] - cap["clientWidth"]
    ms.append(Metric("horizontal_overflow", max(0, over), "px", "A",
                     "the page body must never scroll sideways"))

    fails = []
    for e in els:
        if not e.get("textLen") or "fg" not in e:
            continue
        large = e["fontSize"] >= 18 or (e["fontSize"] >= 14 and e["fontWeight"] in ("600", "700", "800", "900", "bold"))
        need = 3.0 if large else 4.5
        cr = contrast_ratio(e["fg"], e["bgEff"])
        if cr < need:
            fails.append({"sel": _sel(e), "ratio": round(cr, 2), "need": need,
                          "text": e["text"][:40]})
    ms.append(Metric("contrast_failures", len(fails), "elements", "A",
                     "WCAG AA: 4.5:1 body, 3.0:1 large", fails))

    small = [{"sel": _sel(e), "size": f"{e['w']}x{e['h']}"} for e in els
             if e.get("interactive") and (e["w"] < 44 or e["h"] < 44)]
    ms.append(Metric("small_targets", len(small), "elements", "A",
                     "interactive targets should reach 44x44", small))

    banned = []
    for e in els:
        first = (e.get("font") or "").split(",")[0].strip().strip("'\"").lower()
        if first in BANNED_FACES:
            banned.append({"sel": _sel(e), "font": first})
    ms.append(Metric("banned_faces", len({b["font"] for b in banned}), "families", "A",
                     "grotesk defaults that mark a generated page", banned))

    ms.append(Metric("console_errors", len(cap.get("consoleErrors") or []), "errors", "A",
                     "a broken page is not a design question",
                     [{"msg": m} for m in (cap.get("consoleErrors") or [])]))

    # ── Tier B · proxies for the judgement ────────────────────────────────
    panels = [e for e in els if _is_panel(e)]
    ms.append(Metric("visible_elements", cap["elementsKept"], "elements", "B",
                     "raw density of what is on screen at once"))
    ms.append(Metric("framed_panels", len(panels), "panels", "B",
                     "when everything is a bordered box, nothing is elevated",
                     [{"sel": _sel(p)} for p in panels]))

    radii = Counter(round(p["radiusPx"], 1) for p in panels if p["radiusPx"] > 0.5)
    ms.append(Metric("distinct_radii", len(radii), "values", "B",
                     "more than two or three corner radii reads as unconsidered",
                     [{"radius": r, "count": n} for r, n in radii.most_common()]))

    # deepest chain of panels nested inside one another, by geometry
    deepest, chain = 0, []
    ordered = sorted(panels, key=lambda e: -(e["w"] * e["h"]))
    for p in ordered:
        d, cur = 1, [p]
        for q in ordered:
            if q is not p and _contains(q, p):
                d += 1
                cur.append(q)
        if d > deepest:
            deepest, chain = d, cur
    ms.append(Metric("panel_nesting_depth", deepest, "levels", "B",
                     "frames inside frames inside frames",
                     [{"sel": _sel(c)} for c in chain]))

    total_text = sum(e["textLen"] for e in els) or 1
    caps_len = sum(e["textLen"] for e in els
                   if e.get("transform") == "uppercase"
                   or (e["textLen"] >= 4 and e["text"].isupper()))
    ms.append(Metric("allcaps_text_share", round(100 * caps_len / total_text, 1), "% of chars", "B",
                     "shouted micro-labels used as decoration rather than hierarchy"))

    pills = [e for e in els
             if e["h"] <= 32 and e["radiusPx"] >= (e["h"] / 2 - 1.5)
             and 1 <= e["textLen"] <= 26 and e.get("borderSides", 0) + (1 if e["bgAlpha"] > .25 else 0) > 0]
    ms.append(Metric("status_pills_visible", len(pills), "pills", "B",
                     "if everything is flagged, nothing is flagged",
                     [{"sel": _sel(p), "text": p["text"][:24]} for p in pills]))

    # rows of N equal tiles — the category's signature trope
    best_row = 0
    rows: dict[int, list] = {}
    for e in els:
        if e["w"] < 80 or e["h"] < 40:
            continue
        rows.setdefault(round(e["y"] / 10), []).append(e)
    row_ev = []
    for _, group in rows.items():
        for ref in group:
            same = [g for g in group
                    if abs(g["w"] - ref["w"]) <= max(4, 0.05 * ref["w"])
                    and abs(g["h"] - ref["h"]) <= max(4, 0.05 * ref["h"])]
            if len(same) > best_row:
                best_row = len(same)
                row_ev = [{"sel": _sel(s), "size": f"{s['w']}x{s['h']}"} for s in same]
    ms.append(Metric("largest_equal_tile_row", best_row, "tiles", "B",
                     "an N-equal-tile metric row is the most recognisable trope in the category",
                     row_ev))

    hues = Counter()
    for e in els:
        if e.get("bgSat", 0) > 0.22 and e.get("bgHue", -1) >= 0:
            hues[e["bgHue"] // 30] += 1
        if e.get("fgSat", 0) > 0.35 and e.get("fgHue", -1) >= 0 and e["textLen"]:
            hues[e["fgHue"] // 30] += 1
    live = {k: v for k, v in hues.items() if v >= 2}
    ms.append(Metric("accent_hue_families", len(live), "hues", "B",
                     "distinct 30-degree hue families in use, semantic colour included",
                     [{"hue_bucket": f"{k*30}-{k*30+29}deg", "count": v}
                      for k, v in sorted(live.items(), key=lambda kv: -kv[1])]))

    leaks = [{"sel": _sel(e), "text": e["text"][:50]} for e in els
             if e["textLen"] and _looks_like_identifier(e["text"])]
    ms.append(Metric("identifier_leaks", len(leaks), "strings", "B",
                     "internal field names and raw JSON rendered as user-facing text", leaks))

    return {
        "label": cap.get("label"),
        "url": cap.get("url"),
        "viewport": cap.get("viewport"),
        "truncated": cap.get("truncated"),
        "metrics": [m.to_dict() for m in ms],
    }


# --------------------------------------------------------------------------- #
def _fmt(v) -> str:
    return f"{v:g}"


def compare(reports: list[dict], verdicts: dict[str, str] | None = None) -> str:
    """Side-by-side table. The point of the whole exercise: do the numbers
    separate the surfaces a human rejected from the one he approved?"""
    verdicts = verdicts or {}
    labels = [r["label"] for r in reports]
    keys = [m["key"] for m in reports[0]["metrics"]]
    tiers = {m["key"]: m["tier"] for m in reports[0]["metrics"]}
    w = max(22, max(len(k) for k in keys) + 2)
    colw = max(12, max(len(l) for l in labels) + 2)

    lines = []
    lines.append("METRIC".ljust(w) + "T  " + "".join(l.rjust(colw) for l in labels))
    lines.append("-" * (w + 3 + colw * len(labels)))
    if verdicts:
        lines.append("human verdict".ljust(w) + "-  " +
                     "".join((verdicts.get(l, "?")).rjust(colw) for l in labels))
        lines.append("-" * (w + 3 + colw * len(labels)))
    for k in keys:
        row = k.ljust(w) + tiers[k] + "  "
        for r in reports:
            m = next(x for x in r["metrics"] if x["key"] == k)
            row += _fmt(m["value"]).rjust(colw)
        lines.append(row)
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        print("usage: python -m daedalus.gui.lint runs/gui/*.json")
        return 2
    reports = []
    for p in argv:
        cap = json.loads(Path(p).read_text(encoding="utf-8"))
        reports.append(analyse(cap))
    out = Path("runs/gui/report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=1), encoding="utf-8")
    print(compare(reports))
    print(f"\nfull evidence written to {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
