#!/usr/bin/env bash
# Harvest README-linked MCP servers from a GitHub repo into ./dist/servers
# Usage:
#   ./run.sh                               # defaults to modelcontextprotocol/servers
#   OUT_DIR=dist/custom ./run.sh https://github.com/owner/repo
#   MATRIXHUB_URL=http://127.0.0.1:7300 ./run.sh  # also register (idempotent)
#
# Tips:
#   - Optional: export GITHUB_TOKEN to avoid rate limits.
#   - Requires mcp-ingest installed (pip install -e ".[dev,harvester]") or via your venv.

set -euo pipefail

REPO_URL="${1:-https://github.com/modelcontextprotocol/servers}"
OUT_DIR="${OUT_DIR:-dist/servers}"

OPTS=(--out "$OUT_DIR" --yes)

# If MATRIXHUB_URL is set, also register manifests (409 is treated as success)
if [[ -n "${MATRIXHUB_URL:-}" ]]; then
  OPTS+=(--register --matrixhub "$MATRIXHUB_URL")
fi

# Run
exec mcp-ingest harvest-source "$REPO_URL" "${OPTS[@]}"
