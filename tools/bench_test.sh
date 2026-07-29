#!/usr/bin/env bash
# Run the gate suite on the RTX bench instead of this laptop.
#
# WHY: the laptop is an i7-10510U (15W, 2019, 8 threads); the bench is a
# Ryzen 7 9800X3D (16 threads). But the real reason is not speed -- it is that
# this repo's own hard-won rule says a number measured under load is WRONG, not
# slow. Agents run here; the suite should not compete with them for the CPU it
# is being timed on.
#
# THE ONE RULE: the bench checkout is DISPOSABLE AND NEVER EDITED. It is
# replaced from this machine on every run. Two editable checkouts means two
# answers to "what is the code right now", and that ambiguity has already cost
# this project a day.
#
#   tools/bench_test.sh                 # full suite
#   tools/bench_test.sh tests/test_x.py # a subset
#   tools/bench_test.sh --setup         # install deps on the bench, then exit
set -uo pipefail

BENCH="${DAEDALUS_BENCH_SSH:-Administrator@100.119.126.9}"
# The Windows Store python stub cannot spawn over SSH; name the real one.
PY='C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe'
REMOTE='C:/bench/agent_env'
REMOTE_WIN='C:\bench\agent_env'
LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\033[36m[bench]\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--setup" ]]; then
  say "installing test dependencies (matching this laptop's set)"
  ssh -o BatchMode=yes "$BENCH" "\"$PY\" -m pip install --quiet --upgrade \
      pytest tiktoken pyyaml numpy scipy networkx tree_sitter \
      tree_sitter_language_pack lizard" || exit 1
  ssh -o BatchMode=yes "$BENCH" "\"$PY\" -c \"import pytest,tiktoken,yaml,numpy,scipy,networkx,tree_sitter,tree_sitter_language_pack,lizard; print('deps ok')\""
  exit $?
fi

# 1. Ship the WORKING TREE, not HEAD: the point is to test what is on disk
#    right now, including uncommitted work. git ls-files covers tracked files;
#    --others --exclude-standard adds untracked ones that are not ignored.
say "packing working tree"
TAR="$(mktemp -t daedalus-bench-XXXX.tar)"
# NUL is the separator, so translate it to newline -- deleting it concatenates
# every path into one impossible filename, which tar reports as "File name too
# long" several hundred paths later.
( cd "$LOCAL" && git ls-files -z && git ls-files -z --others --exclude-standard ) \
  | tr '\0' '\n' | grep -v '^$' | sort -u > "${TAR}.list" || exit 1
COUNT=$(wc -l < "${TAR}.list")
( cd "$LOCAL" && tar -cf "$TAR" -T "${TAR}.list" ) || exit 1
say "$COUNT files, $(du -h "$TAR" | cut -f1)"

# 2. Replace the remote checkout wholesale. No merge, no incremental sync --
#    a stale file surviving a sync is exactly how two checkouts silently drift.
say "replacing remote checkout"
# rmdir+mkdir in one cmd line races: the shell can reach mkdir before the
# recursive delete has released the directory. Separate them, and verify.
ssh -o BatchMode=yes "$BENCH" "if exist $REMOTE_WIN rmdir /s /q $REMOTE_WIN" >/dev/null 2>&1
ssh -o BatchMode=yes "$BENCH" "mkdir $REMOTE_WIN" >/dev/null 2>&1
ssh -o BatchMode=yes "$BENCH" "if exist $REMOTE_WIN (exit 0) else (exit 1)" || {
  say "could not create $REMOTE_WIN on the bench"; exit 1; }
scp -o BatchMode=yes -q "$TAR" "$BENCH:C:/bench/tree.tar" || exit 1
ssh -o BatchMode=yes "$BENCH" "cd /d $REMOTE_WIN && tar -xf C:\\bench\\tree.tar && del C:\\bench\\tree.tar" || exit 1
rm -f "$TAR" "${TAR}.list"

# 3. Run. Timing is reported by the bench itself, uncontended.
TARGET="${*:-}"
say "running: pytest -q ${TARGET:-<full suite>}"
START=$(date +%s)
ssh -o BatchMode=yes "$BENCH" "cd /d $REMOTE_WIN && \"$PY\" -m pytest -q $TARGET"
RC=$?
say "wall clock including transfer: $(( $(date +%s) - START ))s (exit $RC)"
exit $RC
