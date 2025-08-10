#!/usr/bin/env bash
set -euo pipefail

# Interactive helper to exercise the README extractor and harvesting flows.

# --- CONFIGURATION ---
DEFAULT_REPO_URL="https://github.com/modelcontextprotocol/servers"
DEFAULT_OUT_DIR="dist/servers-first"

# --- STYLING ---
if command -v tput >/dev/null 2>&1; then
  BOLD="$(tput bold)"; DIM="$(tput dim)"; RESET="$(tput sgr0)"; GREEN="$(tput setaf 2)"; YELLOW="$(tput setaf 3)"; RED="$(tput setaf 1)"
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; YELLOW=""; RED=""
fi

# --- HELPER FUNCTIONS ---
info()  { echo -e "${GREEN}[*]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
error() { echo -e "${RED}[x]${RESET} $*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { error "Missing required command: $1"; exit 1; }
}

need_python() {
  command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || {
    error "Python is required on PATH"; exit 1;
  }
}

# --- INTERACTIVE PROMPTS ---
pick_repo_url() {
  local input
  echo -en "${BOLD}GitHub repo to scan [${DEFAULT_REPO_URL}]: ${RESET}" >&2
  read -r input || true
  [[ -z "${input:-}" ]] && echo "$DEFAULT_REPO_URL" || echo "$input"
}

pick_out_dir() {
  local input
  echo -en "${BOLD}Output directory [${DEFAULT_OUT_DIR}]: ${RESET}" >&2
  read -r input || true
  [[ -z "${input:-}" ]] && echo "$DEFAULT_OUT_DIR" || echo "$input"
}

# --- MODIFIED FUNCTION ---
pick_candidate() {
  local candidates="$1"
  local choice
  local -a candidates_arr
  mapfile -t candidates_arr <<< "$candidates"

  if [[ ${#candidates_arr[@]} -eq 0 ]]; then
    warn "No candidates to choose from."
    return 1
  fi

  # FIX: Print all UI elements to standard error (>&2) so they are displayed.
  echo -e "${BOLD}Please choose a candidate to harvest:${RESET}" >&2
  for i in "${!candidates_arr[@]}"; do
    echo -e "  ${GREEN}$((i+1)))${RESET} ${candidates_arr[i]}" >&2
  done

  echo -en "${BOLD}Enter a number (or paste a URL) [1]: ${RESET}" >&2
  read -r choice || true
  choice="${choice:-1}"

  if [[ "$choice" =~ ^[0-9]+$ ]]; then
    if (( choice > 0 && choice <= ${#candidates_arr[@]} )); then
      # This is DATA, it goes to stdout to be captured.
      echo "${candidates_arr[choice-1]}"
      return 0
    else
      error "Invalid number: $choice."
      return 1
    fi
  elif [[ "$choice" == http* ]]; then
    # This is DATA, it goes to stdout.
    echo "$choice"
    return 0
  else
    error "Invalid input."
    return 1
  fi
}


# --- CORE LOGIC ---
extract_candidates() {
  local repo_url="$1"
  python -m mcp_ingest.utils.extractor "$repo_url"
}

harvest_target() {
    local target_url="$1"
    local out_dir="$2"
    info "Processing target: $target_url"
    local harvest_cmd=(mcp-ingest harvest-repo "$target_url" --out "$out_dir")
    info "Running: ${harvest_cmd[*]}"
    if "${harvest_cmd[@]}"; then
        info "Harvest command completed."
    else
        error "Harvest command failed with exit code $?."
        return 1
    fi
    if [[ -f "$out_dir/index.json" ]]; then
        info "SUCCESS! Output manifest found at: $out_dir/index.json"
        if command -v jq >/dev/null 2>&1; then
            jq '.manifests | length as $n | {manifests_count:$n, sample:(.[:5])}' "$out_dir/index.json"
        fi
    else
        warn "Harvest ran, but no index.json was created in $out_dir"
    fi
}

# --- MAIN MENU & LOOP ---
menu() {
  echo
  echo "${BOLD}What would you like to do?${RESET}"
  echo "  1) List all candidate repos from a URL"
  echo "  2) Harvest a SINGLE repo from a URL's README"
  echo "  3) Run full harvest-source (Orchestrator)"
  echo "  q) Quit"
  echo -en "${BOLD}Select [1/2/3/q]: ${RESET}"
}

main() {
  need_cmd jq || true
  need_python
  need_cmd mcp-ingest
  while true; do
    menu
    read -r -n 1 -s choice || true
    echo
    case "${choice:-}" in
      1)
        repo_url="$(pick_repo_url)"
        info "Extracting candidates from README at $repo_url..."
        candidates="$(extract_candidates "$repo_url" || true)"
        if [[ -z "${candidates}" ]]; then warn "No candidates found."; else
          echo -e "${DIM}--- All Candidates ---${RESET}\n$candidates\n${DIM}----------------------${RESET}"
        fi
        ;;
      2)
        repo_url="$(pick_repo_url)"
        out_dir="$(pick_out_dir)"
        mkdir -p "$out_dir"
        info "Extracting README candidates…"
        candidates="$(extract_candidates "$repo_url" || true)"
        target_to_harvest="$(pick_candidate "$candidates" || true)"
        if [[ -z "$target_to_harvest" ]]; then
            warn "No target selected. Returning to menu."
            continue
        fi
        harvest_target "$target_to_harvest" "$out_dir"
        ;;
      3)
        repo_url="$(pick_repo_url)"
        out_dir="$(pick_out_dir)"
        mkdir -p "$out_dir"
        info "Running full orchestrator (harvest-source)…"
        mcp-ingest harvest-source "$repo_url" --out "$out_dir" --yes
        ;;
      q|Q)
        echo "Bye."; exit 0
        ;;
      *)
        warn "Unknown choice."
        ;;
    esac
  done
}

main "$@"
