#!/usr/bin/env bash
# Creates the private GitHub repository, pushes this project, adds nbiswal-star as a collaborator,
# builds the kanban board, links the board in the scope statement and team contract, and pushes that.
#
# Run from the project folder on a computer where `gh auth status` shows your GitHub account:
#   ./scripts/publish.sh
# Options (environment): REPO (default cdp-toolkit-migration), COLLABORATOR (default nbiswal-star)
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-cdp-toolkit-migration}"
COLLABORATOR="${COLLABORATOR:-nbiswal-star}"

command -v gh >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com" >&2; exit 1; }
command -v jq >/dev/null || { echo "Install jq first (brew install jq)" >&2; exit 1; }
gh auth status --active >/dev/null 2>&1 || { echo "Run: gh auth login" >&2; exit 1; }

SCOPES="$(gh auth status --active 2>&1 | grep -i 'token scopes' || true)"
case "$SCOPES" in
  *"'project'"*"'workflow'"*|*"'workflow'"*"'project'"*) ;;
  *) echo "Adding the 'project' and 'workflow' scopes to your GitHub login (a browser step may open)..."
     gh auth refresh -h github.com -s project,workflow ;;
esac
gh auth setup-git   # git pushes use the same GitHub login as gh

[ "$(git symbolic-ref --short HEAD)" = main ] || { echo "Check out the main branch first." >&2; exit 1; }
if git ls-files | grep -qE '(^|/)(state\.json|state\.tmp|\.env)$|^(out|export|\.cache)/'; then
  echo "Run outputs (state.json, out/, export/, .cache/, .env) are tracked by git. Remove them first." >&2
  exit 1
fi

OWNER="$(gh api user --jq .login)"
echo "Owner: $OWNER   Repo: $OWNER/$REPO   Collaborator: $COLLABORATOR"

# 1. Repository (private) and push
if git remote get-url origin >/dev/null 2>&1; then
  case "$(git remote get-url origin)" in
    *github.com[:/]"$OWNER/$REPO"|*github.com[:/]"$OWNER/$REPO".git) git push -u origin main ;;
    *) echo "origin is $(git remote get-url origin), not $OWNER/$REPO. Stopping." >&2; exit 1 ;;
  esac
elif gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "$OWNER/$REPO already exists. Set REPO to another name, or add it as origin and re-run." >&2
  exit 1
else
  gh repo create "$OWNER/$REPO" --private --source . --remote origin --push \
    --description "Group 19, Intro to AI Fall 2026: CDP Toolkit migration for Interactivity Foundation"
fi

# 2. Collaborator (on a personal repository every collaborator gets write access; GitHub emails an invitation)
if [ "$COLLABORATOR" != "$OWNER" ]; then
  gh api -X PUT "repos/$OWNER/$REPO/collaborators/$COLLABORATOR" >/dev/null
  echo "Invited $COLLABORATOR (they accept from their GitHub notifications or email within 7 days)."
fi

# 3. Kanban board
(cd board && OWNER="$OWNER" REPO="$REPO" ./setup_board.sh board_items.json)
URL="$(cat board/board_url.txt)"

# 4. Link the board in the documents and push
python3 scripts/link_board.py "$URL"
git add docs
if ! git diff --cached --quiet; then
  git commit -m "Link project board in scope statement and team contract"
  git push
fi

echo
echo "Done."
echo "Repository: https://github.com/$OWNER/$REPO"
echo "Board:      $URL"
echo "Check that the board opens in a private browser window (the board is public; the repository is private)."
command -v pdflatex >/dev/null || echo "Note: docs/*.pdf still show the old placeholder. Download the rebuilt PDFs from the latest CI run (Actions > documents)."
