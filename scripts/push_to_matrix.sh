#!/usr/bin/env bash
# Fast publisher: copies per-server folders to agent-matrix/catalog and emits a RAW-URL index
# Optimized for speed on large trees (2k+ servers) + interactive auth & identity prompts.
#
# Key features
# - Single rsync for the whole servers tree (preserves subfolders)
# - Parallel JSON collection (GNU parallel if present, else xargs -P)
# - HTTPS by default; uses GITHUB_TOKEN if provided, else interactive user/pass prompt
# - Repo-local git user.name/user.email prompts if missing (no global changes)
#
# Usage:
#   GITHUB_TOKEN=ghp_xxx PUSH=1 bash scripts/push_to_matrix_fast.sh
#   SRC_ROOT=dist/servers CATALOG_DIR=~/.cache/catalog BRANCH=main bash scripts/push_to_matrix_fast.sh

set -euo pipefail

# -------- pretty output --------
if command -v tput >/dev/null 2>&1; then
  BOLD="$(tput bold)"; DIM="$(tput dim)"; RESET="$(tput sgr0)"
  GREEN="$(tput setaf 2)"; YELLOW="$(tput setaf 3)"; RED="$(tput setaf 1)"
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; RED=""
fi
info()  { echo -e "${GREEN}[*]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
error() { echo -e "${RED}[x]${RESET} $*" >&2; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || { error "Missing: $1"; exit 1; }; }

# -------- config --------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="${SRC_ROOT:-${ROOT_DIR}/dist/servers}"
CATALOG_REPO="${CATALOG_REPO:-https://github.com/agent-matrix/catalog.git}"
CATALOG_DIR="${CATALOG_DIR:-${ROOT_DIR}/.cache/catalog}"
BRANCH="${BRANCH:-main}"
TARGET_SUBDIR="${TARGET_SUBDIR:-servers}"
RAW_PREFIX_DEFAULT="https://raw.githubusercontent.com/agent-matrix/catalog/refs/heads/${BRANCH}/${TARGET_SUBDIR}"
RAW_PREFIX="${RAW_PREFIX:-$RAW_PREFIX_DEFAULT}"

COMMIT="${COMMIT:-1}"
PUSH="${PUSH:-0}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_USER="${GITHUB_USER:-oauth2}"

need_cmd jq
need_cmd git
need_cmd rsync

[[ -d "$SRC_ROOT" ]] || { error "SRC_ROOT not found: $SRC_ROOT"; exit 1; }

# -------- HTTPS auth helper (prompts if no token) --------
get_https_clone_url(){
  local url="$1"; local user_part; local tok
  if [[ "$url" =~ ^https://github.com/ ]]; then
    if [[ -z "$GITHUB_TOKEN" ]]; then
      warn "No GITHUB_TOKEN in env. We'll prompt for credentials to clone/push over HTTPS." >&2
      read -r -p "GitHub username [oauth2]: " user_part || true
      user_part="${user_part:-oauth2}"
      read -r -s -p "GitHub token/password (hidden): " tok || true; echo >&2
      if [[ -n "$tok" ]]; then
        echo "https://${user_part}:${tok}@github.com/${url#https://github.com/}"
      else
        # no token: return plain URL; git may use credential helper/prompt
        echo "$url"
      fi
    else
      echo "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${url#https://github.com/}"
    fi
  else
    echo "$url"
  fi
}

# -------- clone/update quickly --------
clone_or_update_repo(){
  local url="$1" dir="$2" branch="$3"
  local url_clone
  url_clone="$(get_https_clone_url "$url")"
  if [[ ! -d "$dir/.git" ]]; then
    info "Cloning catalog -> $dir"
    git clone --quiet --branch "$branch" --single-branch "$url_clone" "$dir"
    (cd "$dir" && git remote set-url origin "$url")
  else
    info "Updating catalog -> $dir"
    (cd "$dir" && git fetch --quiet origin "$branch" && git switch "$branch" >/dev/null 2>&1 && git pull --quiet --ff-only)
  fi
}

clone_or_update_repo "$CATALOG_REPO" "$CATALOG_DIR" "$BRANCH"

# -------- ensure repo-local identity --------
(
  cd "$CATALOG_DIR"
  local_name="$(git config user.name || true)"
  local_email="$(git config user.email || true)"
  if [[ -z "$local_name" || -z "$local_email" ]]; then
    warn "Git identity not set for this repo."
    read -r -p "Enter git user.name: " local_name || true
    read -r -p "Enter git user.email: " local_email || true
    [[ -n "$local_name" ]] && git config user.name "$local_name"
    [[ -n "$local_email" ]] && git config user.email "$local_email"
  fi
)

# -------- one-shot copy (fast) --------
mkdir -p "$CATALOG_DIR/$TARGET_SUBDIR"
info "Rsync all servers -> $CATALOG_DIR/$TARGET_SUBDIR"
rsync -a --delete --exclude ".DS_Store" --exclude "*.tmp" --exclude "*.log" \
  "$SRC_ROOT/" "$CATALOG_DIR/$TARGET_SUBDIR/"

# -------- build top-level index quickly --------
info "Scanning per-server index.json files (fast)"
INDEX_LIST_FILE="$(mktemp -t cat_idx_files.XXXX)"
TMP_INDEX="$(mktemp -t catalog_index.XXXX.json)"
trap 'rm -f "$INDEX_LIST_FILE" "$TMP_INDEX"' EXIT

find "$CATALOG_DIR/$TARGET_SUBDIR" -type f -name index.json > "$INDEX_LIST_FILE"

JOBS="$(nproc 2>/dev/null || echo 4)"
if command -v parallel >/dev/null 2>&1; then
  MANIFEST_URLS=$(cat "$INDEX_LIST_FILE" | parallel -j"$JOBS" --no-notice \
    'd=$(dirname {}); b=$(basename "$d"); jq -r ".manifests[]" {} | sed "s#^#'"${RAW_PREFIX}"'/$b/#"')
else
  MANIFEST_URLS=$(cat "$INDEX_LIST_FILE" | xargs -I{} -P "$JOBS" sh -c \
    'd=$(dirname "$1"); b=$(basename "$d"); jq -r ".manifests[]" "$1" | sed "s#^#'"${RAW_PREFIX}"'/$b/#"' _ {})
fi

# Include any loose manifest.json not referenced by its folder index
LOOSE_MANIFESTS=$(find "$CATALOG_DIR/$TARGET_SUBDIR" -type f -name manifest.json \
  -printf "%h/%f\n" 2>/dev/null | sed "s#^$CATALOG_DIR/$TARGET_SUBDIR/#$RAW_PREFIX/#")

ALL_URLS=$(printf "%s\n%s\n" "$MANIFEST_URLS" "$LOOSE_MANIFESTS" | awk 'NF' | sort -u)

{
  echo '{"manifests": ['
  first=1
  while IFS= read -r url; do
    [[ -z "$url" ]] && continue
    if [[ $first -eq 1 ]]; then first=0; else echo ','; fi
    printf '  "%s"' "$url"
  done <<< "$ALL_URLS"
  echo
  echo ']}'
} > "$TMP_INDEX"

jq . "$TMP_INDEX" > "$CATALOG_DIR/index.json"
info "Wrote catalog index: $CATALOG_DIR/index.json"

# -------- commit & push (quiet) --------
(
  cd "$CATALOG_DIR"
  # Ensure repo-local identity again in case the repo was recloned just now
  if [[ -z "$(git config user.name || true)" || -z "$(git config user.email || true)" ]]; then
    warn "Git identity not set for this repo."
    read -r -p "Enter git user.name: " _name || true
    read -r -p "Enter git user.email: " _email || true
    [[ -n "$_name" ]]  && git config user.name "$_name"
    [[ -n "$_email" ]] && git config user.email "$_email"
  fi

  # Show the remote origin URL and branch
  ORIGIN_URL="$(git remote get-url origin || echo "$CATALOG_REPO")"
  info "Remote origin: $ORIGIN_URL"
  info "Branch: $BRANCH"

  git add -A "$TARGET_SUBDIR" "index.json"
  if ! git diff --cached --quiet; then
    if [[ "$COMMIT" == "1" ]]; then
      BEFORE_SHA="$(git rev-parse HEAD 2>/dev/null || echo "")"
      git commit -q -m "Update catalog servers ($(date -u +'%Y-%m-%d %H:%M:%S UTC'))"
      AFTER_SHA="$(git rev-parse HEAD 2>/dev/null || echo "")"
      info "Committed. New HEAD: $AFTER_SHA"

      if [[ "$PUSH" == "1" ]]; then
        # push with token if available; else interactive/prompt
        if [[ "$CATALOG_REPO" =~ ^https://github.com/ ]]; then
          push_url="$(get_https_clone_url "$CATALOG_REPO")"
          info "Pushing to: $push_url ($BRANCH)"
          git push -q "$push_url" "$BRANCH":"$BRANCH"
        else
          info "Pushing to: origin ($BRANCH)"
          git push -q origin "$BRANCH"
        fi
        info "Pushed."
      else
        warn "PUSH=0 (skipping push)"
        if [[ "$CATALOG_REPO" =~ ^https://github.com/ ]]; then
          push_url="$(get_https_clone_url "$CATALOG_REPO")"
          info "To push manually run:"
          echo "  (cd \"$CATALOG_DIR\" && git push \"$push_url\" \"$BRANCH\":\"$BRANCH\")"
        else
          info "To push manually run:"
          echo "  (cd \"$CATALOG_DIR\" && git push origin \"$BRANCH\")"
        fi
      fi
    else
      warn "COMMIT=0 (staged only)"
      info "To commit manually run:"
      echo "  (cd \"$CATALOG_DIR\" && git commit -m 'Update catalog servers' && git push origin \"$BRANCH\")"
    fi
  else
    info "No changes."
  fi

  # Always print where things would be (or were) pushed
  ORIGIN_URL_CLEAN="$ORIGIN_URL"
  if [[ "$ORIGIN_URL_CLEAN" =~ ^git@github.com:(.*)\.git$ ]]; then
    REPO_PATH="${BASH_REMATCH[1]}"
    ORIGIN_URL_CLEAN="https://github.com/${REPO_PATH}.git"
  fi
  if [[ "$ORIGIN_URL_CLEAN" =~ ^https://github.com/(.*)\.git$ ]]; then
    REPO_PATH="${BASH_REMATCH[1]}"
    WEB_BASE="https://github.com/${REPO_PATH}"
    RAW_BASE="https://raw.githubusercontent.com/${REPO_PATH}"
    CURRENT_SHA="$(git rev-parse HEAD 2>/dev/null || echo "")"
    [[ -n "$CURRENT_SHA" ]] && info "Latest commit (local HEAD): ${WEB_BASE}/commit/${CURRENT_SHA}"
    info "Browse index.json: ${WEB_BASE}/blob/${BRANCH}/index.json"
    info "Raw index.json: ${RAW_BASE}/${BRANCH}/index.json"
  fi
)

info "Done."