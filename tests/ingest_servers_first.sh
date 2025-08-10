#!/usr/bin/env bash
set -euo pipefail

# Minimal local-ingest + install for your ./dist/servers-first layout.
# - Reads dist/servers-first/index.json
# - Loads each manifest listed there (relative to that index file)
# - Calls POST /catalog/install for each
#
# Env:
#   HUB_URL   (default: http://127.0.0.1:7300)
#   INDEX_PATH (default: dist/servers-first/index.json)
#   TARGET_DIR (default: ./)
#   API_TOKEN  (optional: adds Authorization: Bearer <token>)
#
# Requires: jq, curl, python

HUB_URL="${HUB_URL:-http://127.0.0.1:7300}"
INDEX_PATH="${INDEX_PATH:-dist/servers-first/index.json}"
TARGET_DIR="${TARGET_DIR:-./}"

command -v jq >/dev/null 2>&1 || { echo "✖ jq is required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "✖ curl is required"; exit 1; }
command -v python >/dev/null 2>&1 || { echo "✖ python is required"; exit 1; }

[[ -f "$INDEX_PATH" ]] || { echo "✖ Index file not found: $INDEX_PATH"; exit 1; }

# Absolute path to index + its directory (so we can resolve relative manifest paths)
ABS_INDEX="$(python - "$INDEX_PATH" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]).expanduser().resolve()
print(str(p))
PY
)"
INDEX_DIR="$(python - "$ABS_INDEX" <<'PY'
import sys, pathlib
print(str(pathlib.Path(sys.argv[1]).parent))
PY
)"

echo "ℹ️ Using index: $ABS_INDEX"
echo "ℹ️ Index dir: $INDEX_DIR"

# Pull .manifests[] from the index (your shape)
readarray -t MANIFEST_REFS < <(jq -r '.manifests[]' "$ABS_INDEX")

if (( ${#MANIFEST_REFS[@]} == 0 )); then
  echo "✖ No manifests listed in index."
  exit 1
fi

# Optional Authorization header
AUTH_ARGS=()
if [[ "${API_TOKEN:-}" != "" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer $API_TOKEN")
fi

for REF in "${MANIFEST_REFS[@]}"; do
  # Resolve the manifest path relative to the index directory
  ABS_MANIFEST="$(python - "$INDEX_DIR" "$REF" <<'PY'
import sys, pathlib
base = pathlib.Path(sys.argv[1])
ref  = sys.argv[2]
print(str((base / ref).expanduser().resolve()))
PY
)"

  [[ -f "$ABS_MANIFEST" ]] || { echo "⚠️ Skipping missing manifest: $ABS_MANIFEST"; continue; }

  echo "▶️ Manifest: $ABS_MANIFEST"

  # Load manifest JSON
  MANIFEST_JSON="$(cat "$ABS_MANIFEST")"

  # Compute entity uid "<type>:<id>@<version>"
  ENTITY_UID="$(jq -r '"\(.type):\(.id)@\(.version)"' <<<"$MANIFEST_JSON")"
  if [[ -z "$ENTITY_UID" || "$ENTITY_UID" == *null* ]]; then
    echo "   ⚠️ Invalid manifest (missing type/id/version); skipping."
    continue
  fi

  # NOTE: your manifest already has transport=SSE and url with /sse, so no patching needed.

  echo "   📦 Installing $ENTITY_UID -> $TARGET_DIR"
  RESP="$(curl -sS -X POST "$HUB_URL/catalog/install" \
           -H "Content-Type: application/json" \
           "${AUTH_ARGS[@]}" \
           -d "$(jq -nc \
                 --arg id "$ENTITY_UID" \
                 --arg target "$TARGET_DIR" \
                 --argjson manifest "$MANIFEST_JSON" \
                 '{id:$id, target:$target, manifest:$manifest}')" )"

  # Print a short success line or the full response on error
  if jq -e '.results' >/dev/null 2>&1 <<<"$RESP"; then
    echo "   ✅ install ok"
  else
    echo "   ❌ install failed:"
    echo "$RESP" | jq .
    exit 1
  fi
done

echo "✅ Done."
