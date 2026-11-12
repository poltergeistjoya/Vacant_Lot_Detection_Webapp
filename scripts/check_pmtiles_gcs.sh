#!/usr/bin/env bash
# Check that every PMTiles archive the frontend loads is on GCS. Exits 1 if any is missing.
# Expected set: Model + PLUTO per threshold (one per data/masks/t*), plus the
# threshold-independent Model-only archives. PLUTO-only reuses both/t1000.
#
# Also reports (without failing) archives whose size differs from the local copy in
# data/pmtiles/, and remote files the frontend doesn't use.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/env.sh
require_env TILE_STORE_BUCKET
PREFIX="gs://${TILE_STORE_BUCKET}/pmtiles"
LOCAL_ROOT="data/pmtiles"

expected=()
for d in data/masks/t*/; do
  expected+=("both/$(basename "$d").pmtiles")
done
expected+=("pluto_nonvacant.pmtiles" "model_levels.pmtiles")

human() { awk -v b="$1" 'BEGIN { split("B KB MB GB TB", u); i = 1; while (b >= 1024 && i < 5) { b /= 1024; i++ } printf (i == 1 ? "%d %s" : "%.1f %s"), b, u[i] }'; }

echo "Checking ${#expected[@]} archives in $PREFIX/ ..."
# "<size> <path relative to PREFIX>" per remote object
remote=$(gcloud storage ls -l "${PREFIX}/**" 2>/dev/null | awk -v p="${PREFIX}/" '$NF ~ "^gs://" { sub(p, "", $NF); print $1, $NF }' || true)

missing=0
differs=0
total=0
echo
for f in "${expected[@]}"; do
  size=$(awk -v f="$f" '$2 == f { print $1 }' <<< "$remote")
  if [[ -z "$size" ]]; then
    printf "  %-9s %s\n" "MISSING" "$f"
    missing=$((missing + 1))
    continue
  fi
  total=$((total + size))
  note=""
  if [[ -f "$LOCAL_ROOT/$f" ]]; then
    local_size=$(wc -c < "$LOCAL_ROOT/$f" | tr -d ' ')
    if [[ "$local_size" != "$size" ]]; then
      note="  (local copy is $(human "$local_size"): re-upload?)"
      differs=$((differs + 1))
    fi
  fi
  printf "  %-9s %-28s %10s%s\n" "ok" "$f" "$(human "$size")" "$note"
done

extra=$(awk '{ print $2 }' <<< "$remote" | grep -vxF -f <(printf '%s\n' "${expected[@]}") || true)
if [[ -n "$extra" ]]; then
  echo
  echo "Not used by the frontend (safe to delete once nothing deployed needs them):"
  while IFS= read -r f; do
    printf "  %-9s %-28s %10s\n" "unused" "$f" "$(human "$(awk -v f="$f" '$2 == f { print $1 }' <<< "$remote")")"
  done <<< "$extra"
fi

echo
present=$(( ${#expected[@]} - missing ))
echo "$present/${#expected[@]} present, $(human "$total")."
if (( differs )); then
  echo "$differs differ in size from data/pmtiles/: ./scripts/upload_pmtiles.sh -n to see what would upload."
fi
if (( missing )); then
  echo "$missing missing: upload with ./scripts/upload_pmtiles.sh before deploying." >&2
  exit 1
fi
