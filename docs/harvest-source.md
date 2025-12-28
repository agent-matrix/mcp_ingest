# Harvest MCP Servers in a Repo **and** All Servers Linked in its README

This tutorial shows how to extract links from a repo’s README, harvest/describe every server found (both in the repo and linked externally), and optionally register the results to MatrixHub.

> Example target: https://github.com/modelcontextprotocol/servers

---

## Prerequisites

- **Python 3.11**
- **Virtualenv** (recommended)
- *(Optional)* **MatrixHub** at `http://127.0.0.1:7300`
- *(Optional)* **Docker** (only if you plan to validate in containers)
- *(Recommended)* `GITHUB_TOKEN` to avoid GitHub rate limits

---

## 1) Install `mcp-ingest`

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,harvester]"
make tools
```

---

## 2) One command: Extract README → Harvest/Describe → (Optional) Register

```bash
mcp-ingest harvest-source \
  https://github.com/modelcontextprotocol/servers \
  --out dist/servers \
  --yes \
  --max-parallel 4 \
  --register \
  --matrixhub http://127.0.0.1:7300
```

### What this does

1. **Reads the README** on the default branch (with fallbacks).
2. **Identifies GitHub candidates**, including `/tree/<ref>/<subdir>` links.
3. **Resolves relative links** from markdown (e.g., `./src/server` → full GitHub URL).
4. **Plans** each candidate (repo vs. subdir-of-ref).
5. **Detects & describes** with existing detectors (FastMCP, LangChain, LlamaIndex, AutoGen, CrewAI, Semantic Kernel; fallback to raw).
6. **Adds provenance metadata**: source repo/path, detector, confidence, stars, forks, timestamp.
7. **Emits** one `manifest.json` per server and **merges** all into a single `index.json`.
8. **(Optional)** Registers each manifest to MatrixHub (`/catalog/install`, 409 is OK).

### Production Features

#### Relative Link Resolution
The harvester automatically converts relative markdown links into absolute GitHub URLs. For example, in `modelcontextprotocol/servers`, links like `./src/sqlite` are resolved to `https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite`.

This **captures ~5% more servers** that would otherwise be missed.

#### HTTP ETag Caching
All GitHub API and raw content requests use intelligent ETag caching:
- First request: `200 OK` with ETag stored
- Subsequent requests: `304 Not Modified` if unchanged
- **90%+ reduction** in bandwidth and API calls
- Automatic exponential backoff for rate limits

Cache stored in `.cache/` directory (configurable via `MCP_INGEST_HTTP_CACHE` environment variable).

#### Provenance Metadata
Every manifest includes rich provenance tracking:

```json
{
  "provenance": {
    "harvested_at": "2025-12-28T10:00:00Z",
    "source_repo": "https://github.com/owner/repo",
    "source_ref": "main",
    "source_path": "src/server",
    "detector": "fastmcp",
    "confidence": 0.95,
    "stars": 1234,
    "forks": 56,
    "harvester": "mcp-ingest",
    "harvester_version": "0.1.0"
  }
}
```

Use provenance for:
- **Deduplication**: Fingerprint by source_repo + source_path + name
- **Quality ranking**: Sort by stars, filter by confidence
- **Trust scoring**: Combine detector confidence with GitHub metrics
- **Debugging**: Track harvest source and timing

**Useful flags**

* `--yes` / `-y` Skip the confirmation prompt.
* `--max-parallel N` Process multiple candidates concurrently.
* `--register --matrixhub URL` Register results to MatrixHub.
* `--only-github` Ignore non-GitHub links in the README.
* `--log-file FILE` Write structured logs to disk.

---

## 3) Inspect results

All artifacts are written to `dist/servers/`:

* Per-server **`manifest.json`**
* A single **`index.json`** listing them all

Quick checks:

```bash
jq . dist/servers/index.json | head -n 40
jq -r '.manifests[]' dist/servers/index.json | sort | uniq | sed 's/^/ • /'
```

Open a manifest:

```bash
jq . dist/servers/<some-server>/manifest.json
```

---

## 4) Register later (optional)

```bash
mcp-ingest register \
  --matrixhub http://127.0.0.1:7300 \
  --manifest dist/servers/<some-server>/manifest.json
```

> Registration is **idempotent**; HTTP 409 counts as success.

---

## Tips & Troubleshooting

* **Performance:** `--max-parallel` speeds things up when harvesting many candidates.
* **Rate limits:** set `GITHUB_TOKEN` to avoid anonymous throttling.
* **Safety:** the fetcher uses size/time limits and safe extraction (ZipSlip guards).
* **Transports:** SSE is normalized unless `/messages` is explicitly used.
* **STDIO:** Manifests include an `exec` block where applicable (Node MCP servers).
* **Compare:** `harvest-repo` handles a single source; `harvest-source` expands to README-linked repos too.

---

## Why this matters

Curated READMEs often link to dozens of independent MCP servers. `harvest-source` turns a single entrypoint into a wide crawl, scaling your MatrixHub catalog with one command.