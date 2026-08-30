# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The bookkeeper -- keeps the living architecture artifact in sync with reality.

After every build session (and on demand), it renders ``docs/ARCHITECTURE.md``
into a styled, self-contained ``docs/architecture.html`` artifact, and -- when
the content actually changed -- files a **timestamped snapshot** into
``docs/architecture_history/`` with the git hash, so you can see how the
architecture drifted over time. Stdlib only; the markdown renderer is a small,
focused converter (headings, lists, tables, code, blockquote, hr, inline
emphasis/code/links) sufficient for our docs -- not a general engine.
"""

from __future__ import annotations

import hashlib
import html
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCE = DOCS / "ARCHITECTURE.md"
ARTIFACT = DOCS / "architecture.html"
HISTORY = DOCS / "architecture_history"


# --------------------------------------------------------------------------- #
# tiny markdown -> html (scoped to what ARCHITECTURE.md uses)                  #
# --------------------------------------------------------------------------- #

def _inline(text: str) -> str:
    """Escape, then apply inline code / bold / italic / links on the escaped text."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]  # row 1 is the --- separator
    th = "".join(f"<th>{_inline(c)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def render_markdown(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    while i < n:
        line = lines[i]
        # fenced code
        if line.startswith("```"):
            close_list()
            buf = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            i += 1
            continue
        # table (a header row followed by a |---| separator)
        if line.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            close_list()
            block = []
            while i < n and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue
        # horizontal rule
        if re.match(r"^---+\s*$", line):
            close_list()
            out.append("<hr>")
            i += 1
            continue
        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        # blockquote
        if line.startswith(">"):
            close_list()
            out.append(f"<blockquote>{_inline(line.lstrip('> ').rstrip())}</blockquote>")
            i += 1
            continue
        # list item
        if re.match(r"^\s*[-*]\s+", line):
            if not list_open:
                out.append("<ul>")
                list_open = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            out.append("<li>" + _inline(item) + "</li>")
            i += 1
            continue
        # blank
        if not line.strip():
            close_list()
            i += 1
            continue
        # paragraph (gather until blank/structural)
        close_list()
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|>|\s*[-*]\s|```|\|)", lines[i]) \
                and not re.match(r"^---+\s*$", lines[i]):
            para.append(lines[i])
            i += 1
        out.append("<p>" + _inline(" ".join(para)) + "</p>")
    close_list()
    return "\n".join(out)


_CSS = """
:root{--bg:#0d1117;--panel:#131a22;--ink:#e7edf3;--mut:#8ba3b8;--line:#223041;--accent:#4f8cff;--code:#0b1119}
@media (prefers-color-scheme:light){:root{--bg:#f4f6f9;--panel:#fff;--ink:#12202e;--mut:#5a6b7b;--line:#dde5ee;--accent:#2f6fe0;--code:#eef2f7}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:40px 24px 80px}
.meta{color:var(--mut);font:12px/1.5 ui-monospace,monospace;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:28px;background:var(--panel)}
h1{font-size:30px;line-height:1.2;margin:.2em 0 .4em}
h2{font-size:22px;margin:1.6em 0 .5em;padding-top:.4em;border-top:1px solid var(--line)}
h3{font-size:17px;margin:1.3em 0 .4em;color:var(--accent)}
p{margin:.6em 0}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;background:var(--code);padding:.12em .38em;border-radius:5px}
pre{background:var(--code);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow:auto}
pre code{background:none;padding:0;font-size:12.5px;line-height:1.5}
ul{margin:.5em 0;padding-left:1.3em}li{margin:.25em 0}
blockquote{margin:1em 0;padding:.6em 1em;border-left:3px solid var(--accent);background:var(--panel);border-radius:0 8px 8px 0;color:var(--mut)}
hr{border:0;border-top:1px solid var(--line);margin:1.4em 0}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:13.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--panel);font-weight:600}
"""


def _git_hash() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _wrap(body: str, *, stamp: str, git: str, note: str) -> str:
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Daedalus Architecture</title><style>{_CSS}</style></head><body><div class=\"wrap\">"
            f"<div class=\"meta\">Daedalus &middot; architecture artifact &middot; generated {stamp} "
            f"&middot; git {html.escape(git)}{(' &middot; ' + html.escape(note)) if note else ''} "
            f"&middot; <a href=\"architecture_history/index.html\">history</a></div>"
            f"{body}</div></body></html>\n")


def _body_hash(md: str) -> str:
    return hashlib.sha256(md.encode("utf-8")).hexdigest()[:16]


def update(force: bool = False, note: str = "") -> dict:
    """Render ARCHITECTURE.md -> architecture.html; snapshot into history when the
    source changed since the last snapshot. Returns a summary dict."""
    if not SOURCE.is_file():
        return {"ok": False, "reason": f"missing {SOURCE.relative_to(ROOT)}"}
    md = SOURCE.read_text(encoding="utf-8")
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    git = _git_hash()
    body = render_markdown(md)
    ARTIFACT.write_text(_wrap(body, stamp=stamp, git=git, note=note), encoding="utf-8")

    HISTORY.mkdir(parents=True, exist_ok=True)
    digest = _body_hash(md)
    snapshots = _load_manifest()
    changed = force or not snapshots or snapshots[-1].get("hash") != digest
    snap_name = None
    if changed:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        snap_name = f"architecture-{ts}.html"
        k = 1
        while (HISTORY / snap_name).exists():   # avoid same-second collision
            snap_name = f"architecture-{ts}-{k}.html"
            k += 1
        (HISTORY / snap_name).write_text(_wrap(body, stamp=stamp, git=git, note=note), encoding="utf-8")
        snapshots.append({"file": snap_name, "stamp": stamp, "git": git,
                          "hash": digest, "note": note})
        _write_index(snapshots)

    try:
        artifact_label = str(ARTIFACT.relative_to(ROOT))
    except ValueError:
        artifact_label = str(ARTIFACT)
    return {"ok": True, "artifact": artifact_label,
            "changed": changed, "snapshot": snap_name, "git": git,
            "snapshots_total": len(snapshots)}


def _load_manifest() -> list[dict]:
    import json
    mf = HISTORY / "manifest.json"
    if mf.is_file():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def _write_index(snapshots: list[dict]) -> None:
    import json
    (HISTORY / "manifest.json").write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    rows = "\n".join(
        f'<tr><td>{i}</td><td><a href="{html.escape(s["file"])}">{html.escape(s["stamp"])}</a></td>'
        f'<td><code>{html.escape(s["git"])}</code></td><td>{html.escape(s.get("note",""))}</td></tr>'
        for i, s in enumerate(reversed(snapshots), 1))
    body = (f"<h1>Architecture — history</h1>"
            f"<p>{len(snapshots)} snapshot(s). Newest first. Each is filed when "
            f"<code>ARCHITECTURE.md</code> changed after a build session.</p>"
            f"<table><thead><tr><th>#</th><th>when</th><th>git</th><th>note</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            f'<p><a href="../architecture.html">&larr; current architecture</a></p>')
    (HISTORY / "index.html").write_text(
        _wrap(body, stamp=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
              git=_git_hash(), note="history index"), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="daedalus bookkeeper",
                                description="Update the architecture.html artifact + history.")
    sub = p.add_subparsers(dest="action")
    up = sub.add_parser("update", help="render architecture.html (+ snapshot if changed)")
    up.add_argument("--force", action="store_true", help="snapshot even if unchanged")
    up.add_argument("--note", default="", help="short note recorded in the history row")
    args = p.parse_args(argv)
    if args.action in (None, "update"):
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.bookkeeper",
            REGISTRY_BY_ID["cli.bookkeeper"].effects,
            (process_guard_boundary_decision(),),
        )
        res = update(force=getattr(args, "force", False), note=getattr(args, "note", ""))
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
