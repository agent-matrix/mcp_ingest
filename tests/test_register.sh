#!/usr/bin/env bash
set -euo pipefail

# Register all manifests from a harvest index.json into Matrix Hub.
# Usage:
#   tests/test_register.sh [INDEX_JSON] [HUB_URL]
#
# Defaults:
#   INDEX_JSON = dist/servers-first/index.json
#   HUB_URL    = env HUB_URL or http://localhost:7300
#
# Reads .env (if present) so you can keep HUB_URL, API_TOKEN, etc. there.

# ---------- load .env (optional) ----------
if [[ -f .env ]]; then
  # shellcheck disable=SC2046
  export $(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env | xargs -0 -d '\n' printf "%s\0")
fi

# ---------- config ----------
INDEX_JSON="${1:-dist/servers-first/index.json}"
HUB_URL="${2:-${HUB_URL:-http://localhost:7300}}"
API_TOKEN="${API_TOKEN:-}"           # optional: protects /catalog/install on your Hub

# ---------- styling ----------
if command -v tput >/dev/null 2>&1; then
  BOLD="$(tput bold)"; DIM="$(tput dim)"; RESET="$(tput sgr0)"
  GREEN="$(tput setaf 2)"; YELLOW="$(tput setaf 3)"; RED="$(tput setaf 1)"
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; RED=""
fi
info()  { echo -e "${GREEN}[*]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
error() { echo -e "${RED}[x]${RESET} $*" >&2; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || { error "Missing required command: $1"; exit 1; }; }

# ---------- deps ----------
need_cmd jq
need_cmd curl
command -v mcp-ingest >/dev/null 2>&1 || warn "mcp-ingest not on PATH; will use direct HTTP fallback"

# ---------- checks ----------
[[ -f "$INDEX_JSON" ]] || { error "index.json not found: $INDEX_JSON"; exit 1; }

info "Index: $INDEX_JSON"
info "Hub URL: $HUB_URL"
[[ -n "$API_TOKEN" ]] && info "Auth: Bearer token is set" || warn "Auth: none (API_TOKEN empty)"

# Optional health check (non-fatal)
if curl -fsS "$HUB_URL/health" >/dev/null 2>&1; then
  info "Hub health: OK"
else
  warn "Hub /health not available; continuing…"
fi

# ---------- helpers ----------
register_manifest_cli() {
  local manifest="$1"
  # canonical flags
  local args=( mcp-ingest register "$manifest" --hub-url "$HUB_URL" )
  [[ -n "$API_TOKEN" ]] && args+=( --api-token "$API_TOKEN" )
  "${args[@]}"
}

register_manifest_curl() {
  local manifest="$1"
  local url="$HUB_URL/catalog/install"
  local headers=( -H "Content-Type: application/json" )
  [[ -n "$API_TOKEN" ]] && headers+=( -H "Authorization: Bearer $API_TOKEN" )
  curl -fsSL -X POST "$url" "${headers[@]}" --data-binary "@${manifest}" >/dev/null
}

resolve_path_relative_to_index() {
  python - "$INDEX_JSON" "$1" <<'PY'
import os, sys, json
idx, man = sys.argv[1], sys.argv[2]
if os.path.isabs(man):
    print(man); sys.exit(0)
print(os.path.abspath(os.path.join(os.path.dirname(idx), man)))
PY
}

# ---------- main ----------
mapfile -t manifests < <(jq -r '.manifests[]' "$INDEX_JSON")
(( ${#manifests[@]} > 0 )) || { error "No manifests found in $INDEX_JSON"; exit 1; }

info "Found ${#manifests[@]} manifest(s)"
ok=0; fail=0

for m in "${manifests[@]}"; do
  [[ -f "$m" ]] || m="$(resolve_path_relative_to_index "$m")"
  [[ -f "$m" ]] || { error "Manifest not found: $m"; ((fail++)); continue; }

  info "Registering: $m"

  if command -v mcp-ingest >/dev/null 2>&1; then
    if register_manifest_cli "$m"; then
      info "Registered via CLI"
      ((ok++)); continue
    else
      warn "CLI register failed; trying HTTP fallback…"
    fi
  fi

  if register_manifest_curl "$m"; then
    info "Registered via HTTP"
    ((ok++))
  else
    error "Registration failed: $m"
    ((fail++))
  fi
done

echo
echo -e "${BOLD}Summary:${RESET} ok=${ok} fail=${fail}"
[[ $fail -eq 0 ]] || exit 1
