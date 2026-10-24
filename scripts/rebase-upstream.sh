#!/usr/bin/env bash
# Update this fork without automatically committing data or publishing changes.
set -euo pipefail

if [[ $# -gt 0 ]]; then
  echo "Usage: bash scripts/rebase-upstream.sh"
  echo "Close LearnHarness on both machines and commit your data first."
  [[ $# -eq 1 && "$1" == "--help" ]] && exit 0
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$script_dir/.."

fail() { echo "Error: $*" >&2; exit 1; }

[[ "$(git branch --show-current)" == "main" ]] || fail "Switch to main before running this script."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Commit or stash your changes, including learning data, first."

for state in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [[ ! -e "$(git rev-parse --git-path "$state")" ]] || fail "Finish or abort the existing Git operation first."
done

git remote get-url origin >/dev/null || fail "Configure origin to point to your fork."
git remote get-url upstream >/dev/null || fail "Add upstream: git remote add upstream https://github.com/amosblomqvist/learnharness.git"

echo "LearnHarness must remain closed on both machines during this operation."
git fetch --multiple origin upstream
origin_tip=$(git rev-parse --verify refs/remotes/origin/main)
git rev-parse --verify refs/remotes/upstream/main >/dev/null

# Divergence may contain learning data from the other machine. Never overwrite it.
if ! git merge-base --is-ancestor "$origin_tip" HEAD && ! git merge-base --is-ancestor HEAD "$origin_tip"; then
  fail "Local main and origin/main have diverged. Reconcile their data changes before rebasing upstream."
fi

backup="backup-before-rebase-$(date -u +%Y%m%dT%H%M%SZ)-$$"
git branch "$backup"
echo "Recovery branch: $backup"
git merge --ff-only "$origin_tip"

if ! git rebase upstream/main; then
  echo "Rebase stopped. Resolve conflicts, stage the resolved files, then run git rebase --continue." >&2
  echo "To cancel the rebase, run git rebase --abort. Recovery branch: $backup" >&2
  exit 1
fi

echo
echo "Rebase complete. Review the result, then publish with:"
echo "git push --force-with-lease=refs/heads/main:$origin_tip origin main"
echo "Before updating the other machine, preserve any local data changes there."
