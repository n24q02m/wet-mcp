#!/bin/bash
# Merge source branch to target branch with auto-resolve for semantic-release managed files
# Usage: ./merge-with-auto-resolve.sh [--source=dev] [--target=main] [--files="CHANGELOG.md,package.json"]
# Environment: Must be run in a git repository with proper permissions

set -euo pipefail

# Default values
SOURCE_BRANCH="${SOURCE_BRANCH:-dev}"
TARGET_BRANCH="${TARGET_BRANCH:-main}"
AUTO_RESOLVE_FILES="${AUTO_RESOLVE_FILES:-CHANGELOG.md,package.json}"

# Parse arguments
for arg in "$@"; do
  case $arg in
    --source=*)
      SOURCE_BRANCH="${arg#*=}"
      ;;
    --target=*)
      TARGET_BRANCH="${arg#*=}"
      ;;
    --files=*)
      AUTO_RESOLVE_FILES="${arg#*=}"
      ;;
    *)
      echo "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

echo "Merging $SOURCE_BRANCH to $TARGET_BRANCH..."
echo "Auto-resolve files: $AUTO_RESOLVE_FILES"

# Setup git
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# Fetch and checkout target
git fetch origin
git checkout "$TARGET_BRANCH"
git pull origin "$TARGET_BRANCH"

# Disable exit on error to handle merge conflicts gracefully
set +e

# Attempt merge
git merge "origin/$SOURCE_BRANCH" --no-ff -m "chore: promote $SOURCE_BRANCH to $TARGET_BRANCH"
MERGE_RESULT=$?

set -e

if [ $MERGE_RESULT -ne 0 ]; then
  echo "Merge had conflicts, attempting auto-resolution..."

  # Convert comma-separated list to array
  IFS=',' read -ra FILES <<< "$AUTO_RESOLVE_FILES"

  for file in "${FILES[@]}"; do
    # Trim whitespace
    file=$(echo "$file" | xargs)
    if git diff --name-only --diff-filter=U | grep -q "^${file}$"; then
      echo "Auto-resolving conflict in $file (accepting $SOURCE_BRANCH version)"
      git checkout --theirs "$file"
      git add "$file"
    fi
  done

  # Check if there are remaining conflicts
  if git diff --name-only --diff-filter=U | grep -q .; then
    echo "Error: Unresolved conflicts in files not managed by semantic-release:"
    git diff --name-only --diff-filter=U
    exit 1
  fi

  # Complete the merge
  git commit --no-edit
  echo "✓ Conflicts resolved and merge completed"
else
  echo "✓ Merge completed without conflicts"
fi

# Push
git push origin "$TARGET_BRANCH"
echo "✓ Successfully pushed to $TARGET_BRANCH"
