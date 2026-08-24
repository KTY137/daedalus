#!/usr/bin/env bash
# Delete the 107 remote branches whose commits are fully contained in
# origin/integration/g0-consolidated-20260807.
#
# Safe to run: every tip in the repository is already anchored by a tag
# (archive/integration-*, archive/pre-cleanup-*, archive/orphan/*), all pushed
# to origin on 2026-08-17. Deleting these branches cannot lose history.
#
# main, experimental, and both integration/* branches are NOT in the list.
#
# Usage:  bash docs/recovery/run_branch_cleanup.sh [--dry-run]

set -euo pipefail

LIST="$(dirname "$0")/absorbed_branches_to_delete.txt"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

mapfile -t BRANCHES < <(tr -d '\r' < "$LIST" | grep -v '^[[:space:]]*$')

# Refuse to proceed if anything protected slipped into the list.
for b in "${BRANCHES[@]}"; do
  case "$b" in
    main|experimental|integration/*|recovery/*|archive/*)
      echo "REFUSING: protected ref in list: $b" >&2; exit 1;;
  esac
done

echo "${#BRANCHES[@]} branches queued for deletion."

# Re-verify containment at run time; the remote may have moved since triage.
CONS=origin/integration/g0-consolidated-20260807
git fetch origin --prune --quiet
for b in "${BRANCHES[@]}"; do
  if ! git rev-parse --verify --quiet "origin/$b" >/dev/null; then
    echo "  skip (already gone): $b"; continue
  fi
  n=$(git rev-list --count "$CONS..origin/$b")
  if [ "$n" -ne 0 ]; then
    echo "REFUSING: $b has $n commits not in $CONS (triage is stale)" >&2; exit 1
  fi
done
echo "containment re-verified: all queued branches are fully absorbed."

if [ "$DRY" -eq 1 ]; then echo "dry run - nothing deleted."; exit 0; fi

# Delete in batches; pushing ~100 refs at once resets the connection.
printf '%s\n' "${BRANCHES[@]}" | xargs -n 12 git push origin --delete

git fetch origin --prune
echo "done. remaining remote branches: $(git branch -r | grep -vc HEAD)"
