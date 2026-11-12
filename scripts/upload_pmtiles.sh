#!/usr/bin/env bash
# Upload PMTiles archives from data/pmtiles/ to gs://$TILE_STORE_BUCKET/pmtiles/,
# keeping the same layout. Only new or changed archives are uploaded and nothing
# remote is deleted, so a failed upload can simply be re-run.
#
# Usage (run from anywhere):
#   ./scripts/upload_pmtiles.sh                           # all archives
#   ./scripts/upload_pmtiles.sh both                      # every both/{t}.pmtiles
#   ./scripts/upload_pmtiles.sh both/t0298 model_levels   # specific archives
#   ./scripts/upload_pmtiles.sh -n pluto_nonvacant        # dry run: only list what would upload
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi
: "${TILE_STORE_BUCKET:?set it in .env}"

LOCAL_ROOT="data/pmtiles"
REMOTE_ROOT="gs://${TILE_STORE_BUCKET}/pmtiles"
# Objects stay private (bucket default); the API serves them (server/app.py, "PMTiles archives")
FLAGS=(--cache-control="public, max-age=86400")

DRY_RUN=0
targets=""
for arg in "$@"; do
  case "$arg" in
    -n|--dry-run) DRY_RUN=1 ;;
    *)
      # Accept "model_levels", "model_levels.pmtiles" or "data/pmtiles/model_levels.pmtiles"
      name="${arg#"$LOCAL_ROOT"/}"; name="${name%/}"; name="${name%.pmtiles}"
      if [[ ! -f "$LOCAL_ROOT/$name.pmtiles" && ! -d "$LOCAL_ROOT/$name" ]]; then
        echo "No archive $LOCAL_ROOT/$name.pmtiles or directory $LOCAL_ROOT/$name/" >&2
        exit 1
      fi
      targets="${targets:+$targets|}${name//./\\.}"
      ;;
  esac
done

# rsync excludes by regex on paths relative to LOCAL_ROOT: keep only .pmtiles files,
# and only the selected archives when any are given
if [[ -n "$targets" ]]; then
  EXCLUDE="^(?!(?:${targets})(?:\.pmtiles$|/.*\.pmtiles$)).*"
else
  EXCLUDE="^(?!.*\.pmtiles$).*"
fi
RSYNC=(gcloud storage rsync -r --exclude="$EXCLUDE" "$LOCAL_ROOT" "$REMOTE_ROOT")

human() { awk -v b="$1" 'BEGIN { split("B KB MB GB TB", u); i = 1; while (b >= 1024 && i < 5) { b /= 1024; i++ } printf (i == 1 ? "%d %s" : "%.1f %s"), b, u[i] }'; }

echo "Checking $LOCAL_ROOT/ against $REMOTE_ROOT/ ..."
plan=$("${RSYNC[@]}" --dry-run 2>&1 | sed -n "s#^Would copy file://${LOCAL_ROOT}/\(.*\) to .*#\1#p" | sort)
remote=$(gcloud storage ls "${REMOTE_ROOT}/**" 2>/dev/null | sed "s#^${REMOTE_ROOT}/##" || true)

if [[ -z "$plan" ]]; then
  echo "Everything selected is already up to date on GCS."
  exit 0
fi

total=0
count=0
echo
echo "To upload:"
while IFS= read -r rel; do
  size=$(wc -c < "$LOCAL_ROOT/$rel" | tr -d ' ')
  total=$((total + size))
  count=$((count + 1))
  if grep -qxF "$rel" <<< "$remote"; then status="replace"; else status="new"; fi
  printf "  %-8s %-36s %10s  → %s/%s\n" "$status" "$rel" "$(human "$size")" "$REMOTE_ROOT" "$rel"
done <<< "$plan"
echo "  $count archive(s), $(human "$total")"
echo

if (( DRY_RUN )); then
  echo "Dry run: nothing uploaded."
  exit 0
fi

"${RSYNC[@]}" "${FLAGS[@]}"
echo
echo "Uploaded $count archive(s), $(human "$total")."
