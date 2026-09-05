"""G1-IKARUS-30 privacy pass over the live OCR output.

The packaged Windows 11 Notepad restores the tabs of the owner's previous
session, so a window-scoped capture legitimately contained file names this
measurement was never authorized to retain. Only tokens this measurement itself
put on the screen -- the fixture sentinels, the typed probe and the fixed
Notepad chrome -- survive; everything else becomes a count.

Run once over ``lane10_measure_result.json``; it rewrites the file in place and
truncates the raw run log to its step lines.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

OUT = Path(__file__).resolve().parent

# Tokens this measurement itself produced, including the OCR misreadings of
# them, which are evidence about the OCR adapter and not about the owner.
OURS = {
    "DAEDALUS", "ZINNOBER", "SENTINEL", "739104",
    "LANE10", "LANEIO", "lane10", "lanel(", "LANE1O", "LANEI0",
    "KARMESIN99", "KARMESIN991", "KARMESIN9", "KARMESINS", "KARMESIN",
}
# Fixed German Notepad chrome; verified to contain no owner content.
CHROME = {
    "Datei", "Bearbeiten", "Ansicht", "Zeichen", "Unformatierter", "Text",
    "Windows", "(CRLF)", "UTF-8", "100%", "Zeile", "Spalte", "Ze", "Sp",
    "Textdokument", "Textdokume",
}
COUNT = re.compile(r"^\d{1,3},?$")


def classify(word: str) -> str:
    if word in OURS:
        return "ours"
    if word in CHROME:
        return "chrome"
    if COUNT.match(word):
        return "counter"
    return "redacted"


def redact(words: list[str]) -> dict:
    kept = [w for w in words if classify(w) in {"ours", "chrome", "counter"}]
    dropped = len(words) - len(kept)
    return {"retained_words": kept, "redacted_word_count": dropped,
            "redaction_reason": "restored Notepad session tab titles are owner content"}


def main() -> int:
    target = OUT / "lane10_measure_result.json"
    report = json.loads(target.read_text(encoding="utf-8"))
    for key in ("ocr_words_fixture", "ocr_words_after_typing", "ocr_words_after_backspace"):
        if isinstance(report.get(key), list):
            report[key] = redact(report[key])
    for step in report.get("steps", []):
        result = step.get("result")
        if isinstance(result, dict) and isinstance(result.get("words"), list):
            # Keep the geometry of our own words only; drop every other row.
            rows = [w for w in result["words"] if classify(w.get("text", "")) != "redacted"]
            result["redacted_word_rows"] = len(result["words"]) - len(rows)
            result["words"] = rows
    report["privacy_pass"] = (
        "OCR output filtered by lane10_redact.py: only the measurement's own "
        "sentinels, the typed probe, Notepad chrome and status counters are "
        "retained. No image was ever written to disk by the adapter or this harness."
    )
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for log in OUT.glob("lane10_measure_run*.log.txt"):
        lines = [line for line in log.read_text(encoding="utf-8").splitlines()
                 if line.startswith("[")]
        lines.append("[redacted] the JSON body of this run was moved into "
                     "lane10_measure_result.json and filtered by lane10_redact.py")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("ocr_words_fixture", "ocr_words_after_typing",
                       "ocr_words_after_backspace") if k in report},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
