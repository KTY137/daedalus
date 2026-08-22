"""Owner-run kit 2026-08-22: big house cleanup. DRY RUN by default.

Measured before writing this (2026-08-22 08:57): 237 remote branches, 56 local
branches, 37 worktrees (2 under Temp), thousands of tracked-but-ignored files
under runs/. Run AFTER unify_and_retire_guard_kit.py (main must be the g0
trunk; the commit hooks must be gone).

    python docs/recovery/house_cleanup_kit.py            # report only, writes lists
    python docs/recovery/house_cleanup_kit.py --execute  # acts on the lists below

What --execute does (and only this):
  1. local branches fully merged into main      -> git branch -d
  2. remote branches fully merged into main     -> git push origin --delete (batches of 25)
     (the list is written first to docs/recovery/cleanup_2026-08-22/remote_merged.txt;
      edit it before --execute if you want to keep one)
  3. stale worktrees (path missing)             -> git worktree prune
  4. worktrees under Temp/ or AppData/ that are clean -> git worktree remove
  5. tracked-but-ignored files (runs/ debris)   -> git rm --cached + one commit on main
What it never does: delete unmerged branches (they are LISTED with age and last
subject in remote_unmerged.txt / local_unmerged.txt for you to decide), touch
dirty worktrees, delete any directory on disk except via git worktree remove,
force-push, or rewrite history.
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXEC = "--execute" in sys.argv
ROOT = Path(r"C:\Users\nukei\Desktop\agent_env_g0")   # main lives here after unify
OUT = Path(r"C:\Users\nukei\Desktop\agent_env\docs\recovery\cleanup_2026-08-22")
OUT.mkdir(parents=True, exist_ok=True)
KEEP_LOCAL = {"main"}
KEEP_REMOTE = {"origin/main", "origin/HEAD"}


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return (r.stdout or "").strip()


def lines(s):
    return [x.strip() for x in s.splitlines() if x.strip()]


def write(name, rows):
    p = OUT / name
    p.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    print(f"  -> {p} ({len(rows)})")


def age_subject(ref):
    out = git("log", "-1", "--format=%cs %s", ref, check=False)
    return out or "? ?"


print("mode:", "EXECUTE" if EXEC else "DRY RUN (report only)")
if git("branch", "--show-current") != "main":
    raise SystemExit("the g0 worktree is not on main; run the unify kit first")
git("fetch", "--prune", "origin")

# ---------------------------------------------------------------- 1 local
print("\n== 1 local branches")
local_all = [b.lstrip("* +").strip() for b in lines(git("branch", "--format=%(refname:short)"))]
local_merged = [b for b in lines(git("branch", "--merged", "main", "--format=%(refname:short)"))
                if b not in KEEP_LOCAL]
local_unmerged = [b for b in local_all if b not in local_merged and b not in KEEP_LOCAL]
checked_out = {l.split()[-1].strip("[]") for l in lines(git("worktree", "list")) if "[" in l}
local_merged_safe = [b for b in local_merged if b not in checked_out]
print(f"  total {len(local_all)} | merged-into-main {len(local_merged)} (deletable now: {len(local_merged_safe)}; "
      f"{len(local_merged) - len(local_merged_safe)} checked out in a worktree) | unmerged {len(local_unmerged)}")
write("local_merged_delete.txt", local_merged_safe)
write("local_unmerged.txt", [f"{b}\t{age_subject(b)}" for b in local_unmerged])
if EXEC:
    for b in local_merged_safe:
        git("branch", "-d", b, check=False)
    print(f"  deleted {len(local_merged_safe)} local branches")

# ---------------------------------------------------------------- 2 remote
print("\n== 2 remote branches (origin)")
remote_all = [b for b in lines(git("branch", "-r", "--format=%(refname:short)")) if b not in KEEP_REMOTE]
remote_merged = [b for b in lines(git("branch", "-r", "--merged", "main", "--format=%(refname:short)"))
                 if b not in KEEP_REMOTE]
remote_unmerged = [b for b in remote_all if b not in remote_merged]
print(f"  total {len(remote_all)} | merged-into-main {len(remote_merged)} | unmerged {len(remote_unmerged)}")
merged_list = OUT / "remote_merged.txt"
if not merged_list.exists() or not EXEC:
    write("remote_merged.txt", remote_merged)
else:
    print(f"  using existing {merged_list} (edited by you?)")
write("remote_unmerged.txt", [f"{b}\t{age_subject(b)}" for b in remote_unmerged])
if EXEC:
    todo = [b.split("origin/", 1)[1] for b in lines(merged_list.read_text(encoding="utf-8")) if b.startswith("origin/")]
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        r = subprocess.run(["git", "-C", str(ROOT), "push", "origin", "--delete", *batch],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"  push --delete batch {i // 25 + 1}: rc={r.returncode} {r.stderr.strip().splitlines()[-1:] if r.returncode else ''}")
    git("fetch", "--prune", "origin")

# ---------------------------------------------------------------- 3/4 worktrees
print("\n== 3/4 worktrees")
if EXEC:
    git("worktree", "prune")
wt = git("worktree", "list", "--porcelain").split("\n\n")
rows, removable, dirty = [], [], []
for block in wt:
    b = lines(block)
    if not b:
        continue
    path = b[0].replace("worktree ", "", 1)
    branch = next((x.replace("branch refs/heads/", "") for x in b if x.startswith("branch ")), "(detached)")
    disposable = ("\\Temp\\" in path) or ("/Temp/" in path) or ("AppData" in path)
    status = subprocess.run(["git", "-C", path, "status", "--porcelain"], capture_output=True, text=True).stdout.strip() \
        if Path(path).exists() else "MISSING"
    rows.append(f"{path}\t{branch}\t{'clean' if not status else ('missing' if status == 'MISSING' else 'DIRTY')}")
    if disposable and Path(path).exists() and not status and path.lower() != str(ROOT).lower():
        removable.append(path)
    elif status and status != "MISSING":
        dirty.append(f"{path}\t{branch}")
write("worktrees.txt", rows)
write("worktrees_removable.txt", removable)
write("worktrees_dirty_keep.txt", dirty)
if EXEC:
    for p in removable:
        git("worktree", "remove", p, check=False)
    print(f"  removed {len(removable)} clean disposable worktrees; {len(dirty)} dirty kept")

# ---------------------------------------------------------------- 5 runs/ debris
print("\n== 5 tracked-but-ignored files")
tracked_ignored = lines(git("ls-files", "-ci", "--exclude-standard"))
print(f"  {len(tracked_ignored)} files are tracked although .gitignore excludes them")
write("tracked_but_ignored.txt", tracked_ignored)
if EXEC and tracked_ignored:
    for i in range(0, len(tracked_ignored), 500):
        git("rm", "--cached", "-q", "--", *tracked_ignored[i:i + 500])
    msg = OUT / "untrack_commitmsg.txt"
    msg.write_text(f"cleanup: {len(tracked_ignored)} tracked-but-ignored files leave the index\n\n"
                   "They stay on disk; .gitignore already excluded them. Owner cleanup 2026-08-22.\n\n"
                   "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n", encoding="utf-8")
    git("commit", "-F", str(msg))
    print("  committed:", git("log", "--oneline", "-1"))

# ---------------------------------------------------------------- 6 stray dirs (report only)
print("\n== 6 top-level directories (report only; decide by hand)")
for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")):
    tracked = len(lines(git("ls-files", "--", d.name, check=False)))
    total = sum(1 for _ in d.rglob("*") if _.is_file())
    print(f"  {d.name:<20} tracked {tracked:>6} | on disk {total:>6}")

print("\nDONE." if EXEC else "\nDRY RUN done. Review the lists in", OUT, "then rerun with --execute.")
