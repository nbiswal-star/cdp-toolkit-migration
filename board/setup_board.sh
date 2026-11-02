#!/usr/bin/env bash
# Creates the Group 19 GitHub Projects board for the CDP Toolkit Migration.
# Idempotent: safe to re-run; the repo, project, fields, view, and cards are reused and refreshed.
#
# Requirements: gh (authenticated as the board owner, with the "project" scope) and jq.
#   gh auth refresh -s project
#
# Env options:
#   OWNER        GitHub user that owns the repo and board (default: the authenticated user)
#   REPO         repository name (default: cdp-toolkit-migration); must be private
#   MAKE_PUBLIC  1 makes the board viewable by graders while the repo stays private (default: 1)
#
# Usage: ./setup_board.sh [board_items.json]

set -euo pipefail

ITEMS_FILE="${1:-$(dirname "$0")/board_items.json}"
OWNER="${OWNER:-$(gh api user --jq .login)}"
REPO="${REPO:-cdp-toolkit-migration}"
MAKE_PUBLIC="${MAKE_PUBLIC:-1}"
TITLE="Group 19: CDP Toolkit Migration"
STAGES=("Backlog" "To Do" "In Progress" "Review" "Done")

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
[ -f "$ITEMS_FILE" ] || { echo "Items file not found: $ITEMS_FILE" >&2; exit 1; }
if ! gh project list --owner "$OWNER" --limit 1 >/dev/null 2>&1; then
  echo "gh lacks the project scope. Run: gh auth refresh -s project" >&2; exit 1
fi

echo "Owner: $OWNER  Repo: $OWNER/$REPO"

# 1. Repository (must be private: it will hold client work)
if ! gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  gh repo create "$OWNER/$REPO" --private --add-readme \
    --description "Group 19, Intro to AI Fall 2026: CDP Toolkit Migration for Interactivity Foundation"
  echo "Created private repo $OWNER/$REPO"
fi
VIS="$(gh repo view "$OWNER/$REPO" --json visibility --jq .visibility)"
[ "$VIS" = "PRIVATE" ] || { echo "Repo $OWNER/$REPO is $VIS, not PRIVATE. Stopping." >&2; exit 1; }

# 2. Project
NUM="$(gh project list --owner "$OWNER" --closed --format json --limit 100 \
  --jq ".projects[] | select(.title==\"$TITLE\") | .number" | head -n1)"
if [ -z "$NUM" ]; then
  NUM="$(gh project create --owner "$OWNER" --title "$TITLE" --format json --jq .number)"
  echo "Created project #$NUM"
fi
gh project close "$NUM" --owner "$OWNER" --undo >/dev/null 2>&1 || true
PID="$(gh project view "$NUM" --owner "$OWNER" --format json --jq .id)"
URL="$(gh project view "$NUM" --owner "$OWNER" --format json --jq .url)"
gh project link "$NUM" --owner "$OWNER" --repo "$REPO" >/dev/null 2>&1 || true
gh project edit "$NUM" --owner "$OWNER" \
  --description "Kanban for the Collaborative Discussion Toolkit migration (Wix to the IF WordPress website)." >/dev/null

fields_json() { gh project field-list "$NUM" --owner "$OWNER" --format json --limit 100; }
field_id() { fields_json | jq -r --arg n "$1" '.fields[] | select(.name==$n) | .id'; }

# 3. Stage field: set built-in Status options to the five stages; fall back to a "Stage" field
STATUS_FIELD="Status"
SID="$(field_id Status)"
CURRENT="$(fields_json | jq -r '.fields[] | select(.name=="Status") | [.options[].name] | join(",")')"
WANT="$(IFS=,; echo "${STAGES[*]}")"
if [ "$CURRENT" != "$WANT" ]; then
  if ! gh api graphql -f f="$SID" -f query='
    mutation($f: ID!) {
      updateProjectV2Field(input: {fieldId: $f, singleSelectOptions: [
        {name: "Backlog",     color: GRAY,   description: ""},
        {name: "To Do",       color: BLUE,   description: ""},
        {name: "In Progress", color: YELLOW, description: ""},
        {name: "Review",      color: PURPLE, description: ""},
        {name: "Done",        color: GREEN,  description: ""}
      ]}) { projectV2Field { ... on ProjectV2SingleSelectField { id } } }
    }' >/dev/null; then
    echo "Could not edit Status options via API; using a separate Stage field." >&2
    STATUS_FIELD="Stage"
    if [ -z "$(field_id Stage)" ]; then
      gh project field-create "$NUM" --owner "$OWNER" --name Stage \
        --data-type SINGLE_SELECT --single-select-options "$WANT" >/dev/null
    fi
  fi
fi

# 4. Owner, Due, Area fields
[ -n "$(field_id Owner)" ] || gh project field-create "$NUM" --owner "$OWNER" --name Owner --data-type TEXT >/dev/null
[ -n "$(field_id Due)" ]   || gh project field-create "$NUM" --owner "$OWNER" --name Due --data-type DATE >/dev/null
[ -n "$(field_id Area)" ]  || gh project field-create "$NUM" --owner "$OWNER" --name Area \
  --data-type SINGLE_SELECT --single-select-options "Client,Docs,Build,Eval" >/dev/null

F="$(fields_json)"
STAGE_FID="$(jq -r --arg n "$STATUS_FIELD" '.fields[] | select(.name==$n) | .id' <<<"$F")"
OWNER_FID="$(jq -r '.fields[] | select(.name=="Owner") | .id' <<<"$F")"
DUE_FID="$(jq -r '.fields[] | select(.name=="Due") | .id' <<<"$F")"
AREA_FID="$(jq -r '.fields[] | select(.name=="Area") | .id' <<<"$F")"
opt_id() { jq -r --arg f "$1" --arg o "$2" '.fields[] | select(.name==$f) | .options[] | select(.name==$o) | .id' <<<"$F"; }

# 5. Kanban board view (REST). "View 1" cannot be edited by API, so the link points at this view.
views() {
  gh api graphql -f o="$OWNER" -F n="$NUM" \
    -f query='query($o:String!,$n:Int!){user(login:$o){projectV2(number:$n){views(first:20){nodes{name number}}}}}' \
    --jq '.data.user.projectV2.views.nodes' 2>/dev/null || echo '[]'
}
VIEW_OK=0
if [ "$(views | jq '[.[] | select(.name=="Kanban")] | length')" = "0" ]; then
  UID_NUM="$(gh api "users/$OWNER" --jq .id)"
  STAGE_DBID="$(gh api "users/$OWNER/projectsV2/$NUM/fields" --jq ".[] | select(.name==\"$STATUS_FIELD\") | .id" || true)"
  BODY="$(printf '{"name":"Kanban","layout":"board","vertical_group_by":[%s]}' "$STAGE_DBID")"
  if [ -n "$STAGE_DBID" ] && \
     { gh api -X POST "users/$UID_NUM/projectsV2/$NUM/views" --input - >/dev/null <<<"$BODY" || \
       gh api -X POST "users/$UID_NUM/projectsV2/$NUM/views" -H "X-GitHub-Api-Version: 2026-03-10" --input - >/dev/null <<<"$BODY"; }; then
    echo "Created Kanban view"
  else
    echo "Could not create the Kanban view via API; switch the layout manually (see handoff step 3)." >&2
  fi
fi
VNUM="$(views | jq -r '.[]? | select(.name=="Kanban") | .number' | head -n1 || true)"
if [ -n "$VNUM" ]; then URL="$URL/views/$VNUM"; VIEW_OK=1; fi

# 6. Cards (draft items, so they stay visible on a public board while the repo is private).
#    Existing cards are matched by title and have their fields refreshed, so a failed run can be resumed.
ITEMS="$(gh project item-list "$NUM" --owner "$OWNER" --format json --limit 500)"
created=0; updated=0
while IFS= read -r item; do
  t="$(jq -r .title <<<"$item")"
  so="$(opt_id "$STATUS_FIELD" "$(jq -r .status <<<"$item")")"
  ao="$(opt_id Area "$(jq -r .area <<<"$item")")"
  [ -n "$so" ] || { echo "Unknown stage for: $t" >&2; exit 1; }
  [ -n "$ao" ] || { echo "Unknown area for: $t" >&2; exit 1; }
  iid="$(jq -r --arg t "$t" '[.items[] | select(.content.title==$t)][0].id // empty' <<<"$ITEMS")"
  if [ -z "$iid" ]; then
    iid="$(gh project item-create "$NUM" --owner "$OWNER" --title "$t" \
           --body "$(jq -r .body <<<"$item")" --format json --jq .id)"
    created=$((created+1))
  else
    updated=$((updated+1))
    did="$(jq -r --arg i "$iid" '[.items[] | select(.id==$i)][0].content.id // empty' <<<"$ITEMS")"
    [ -n "$did" ] && gh project item-edit --id "$did" --title "$t" --body "$(jq -r .body <<<"$item")" >/dev/null
  fi
  gh project item-edit --id "$iid" --project-id "$PID" --field-id "$STAGE_FID" --single-select-option-id "$so" >/dev/null
  gh project item-edit --id "$iid" --project-id "$PID" --field-id "$AREA_FID"  --single-select-option-id "$ao" >/dev/null
  gh project item-edit --id "$iid" --project-id "$PID" --field-id "$OWNER_FID" --text "$(jq -r .owner <<<"$item")" >/dev/null
  gh project item-edit --id "$iid" --project-id "$PID" --field-id "$DUE_FID"   --date "$(jq -r .due <<<"$item")" >/dev/null
done < <(jq -c '.[]' "$ITEMS_FILE")
echo "Cards created: $created, refreshed: $updated"

# 7. Public board for graders (repo stays private)
if [ "$MAKE_PUBLIC" = "1" ]; then
  gh project edit "$NUM" --owner "$OWNER" --visibility PUBLIC >/dev/null
  echo "Board visibility: PUBLIC (repo stays private)"
fi

echo "$URL" > "$(dirname "$0")/board_url.txt"
echo "STAGE_FIELD=$STATUS_FIELD"
echo "KANBAN_VIEW_CREATED=$VIEW_OK"
echo "BOARD_URL=$URL"
